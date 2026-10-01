"""Email Manager (live): Reader -> Categorizer -> Summarizer (reporter) -> Writer -> YOU -> Sender.

Reads the last 24 h from every connected inbox (read or unread), sorts it, flags what needs you,
drafts replies, and sends a reply only after you approve it.
Accounts are listed in config.yaml -> masters.email.options.accounts.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..agents import AgentResult, SubAgent, request_approval
from ..services import mailcal, oauth
from ..services.llm import LLMUnavailable

CATS = ["action", "meeting", "work", "finance", "personal", "jobs", "promo", "notification"]
PROMO_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS", "other"}
RX = {
    "jobs": re.compile(r"jobbank|job alert|new jobs? (for|matching)", re.I),
    "promo": re.compile(r"unsubscribe|newsletter|% off|sale|deal|promo|webinar", re.I),
    "notification": re.compile(r"no-?reply|do-?not-?reply|notification|verification code|security alert|receipt from", re.I),
    "finance": re.compile(r"invoice|payment|statement|bank|receipt|transaction|bill\b|\$\d", re.I),
    "meeting": re.compile(r"meeting|call|schedule|availability|available|catch up|invite|zoom|teams|calendar", re.I),
    "action": re.compile(r"\?|please|could you|can you|kindly|urgent|asap|deadline|reply|confirm|review|approve|let me know", re.I),
}


def accounts(options: dict, kind: str = "mail") -> list[dict]:
    return [a for a in options.get("accounts") or [] if a.get(kind, True)]


def rule_category(e: dict) -> str:
    text = f"{e['from']} {e['subject']} {e['snippet']}"
    if RX["jobs"].search(text):
        return "jobs"
    if PROMO_LABELS & set(e.get("labels") or []) or RX["promo"].search(text):
        return "promo"
    if RX["notification"].search(e["from"] + " " + e["subject"]):
        return "notification"
    if RX["finance"].search(text):
        return "finance"
    if RX["meeting"].search(e["subject"] + " " + e["snippet"][:200]):
        return "meeting"
    if RX["action"].search(e["subject"] + " " + e["snippet"][:200]):
        return "action"
    return "work"


def login_notice(ctx: dict, err: oauth.AuthNeeded) -> None:
    port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
    ctx["bus"].notice(f"auth:{err.account}", f"Sign in to {err.provider.title()} for the '{err.account}' account",
                      f"http://127.0.0.1:{port}/auth/{err.provider}/login?account={err.account}")


class Reader(SubAgent):
    name, tier, note = "Reader", "API", "all inboxes · last 24h"

    async def run(self, ctx):
        accts = accounts(ctx["options"])
        if not accts:
            return AgentResult("idle", "NOT SET UP", "Email: add accounts in config.yaml")
        store, mail, waiting = ctx["store"], [], []
        for a in accts:
            try:
                msgs = await mailcal.list_recent(a, hours=24)
                ctx["bus"].clear_notice(f"auth:{a['id']}")
            except oauth.AuthNeeded as e:
                login_notice(ctx, e)
                waiting.append(a["id"])
                continue
            for m in msgs:
                old = store.kv_get("emails", f"{a['id']}:{m['id']}") or {}
                m.update({k: old[k] for k in ("category", "attention", "summary", "drafted") if k in old})
                store.kv_put("emails", f"{a['id']}:{m['id']}", m)
            mail += msgs
        ctx["mail"] = sorted(mail, key=lambda m: -m["ts"])
        if waiting and not mail:
            return AgentResult("wait", "SIGN IN", "Waiting for you to sign in: " + ", ".join(waiting))
        return AgentResult("done", f"{len(mail)} READ", f"{len(mail)} emails in 24h across {len(accts) - len(waiting)} accounts")


class Categorizer(SubAgent):
    name, tier, note = "Categorizer", "LOCAL", "action · meeting · work · finance · promo"

    async def run(self, ctx):
        mail = ctx.get("mail", [])
        todo = [m for m in mail if "category" not in m]
        for m in todo:
            m["category"] = rule_category(m)
            m["attention"] = m["category"] in ("action", "meeting")
        llm = ctx.get("llm")
        if llm and todo:
            items = [{"i": i, "from": m["from_name"] or m["from"], "subject": m["subject"], "preview": m["snippet"][:240]} for i, m in enumerate(todo[:40])]
            try:
                res = await llm.json(
                    "Classify each email for a busy person. For each item return {i, category, attention, summary}. "
                    f"category is one of {CATS}. attention=true only if they personally need to reply, decide or act. "
                    "summary is 12 words max.\n" + str(items), tier="local", max_tokens=2000)
                for r in res or []:
                    m = todo[int(r["i"])]
                    if r.get("category") in CATS:
                        m["category"] = r["category"]
                    m["attention"] = bool(r.get("attention"))
                    m["summary"] = r.get("summary") or m["subject"]
            except (LLMUnavailable, Exception):
                pass  # rules already applied
        for m in todo:
            ctx["store"].kv_put("emails", f"{m['account']}:{m['id']}", m)
        counts = {c: sum(1 for m in mail if m.get("category") == c) for c in CATS}
        return AgentResult("done", "SORTED", " · ".join(f"{k} {v}" for k, v in counts.items() if v) or "inbox empty", {"counts": counts})


class Summarizer(SubAgent):
    name, tier, note = "Summarizer", "LOCAL", "digest + needs attention"

    async def run(self, ctx):
        mail, store = ctx.get("mail", []), ctx["store"]
        need = [m for m in mail if m.get("attention")]
        for m in mail:
            if m.get("category") == "meeting" and not store.kv_has("meeting_requests", m["id"]):
                store.kv_put("meeting_requests", m["id"], {"email": m, "status": "new"})
        drafts = [d for d in store.kv_list("drafts", since=time.time() - 3 * 86400) if d.get("status") == "pending"]
        top = [{"from": m["from_name"] or m["from"], "subject": m["subject"], "summary": m.get("summary") or m["snippet"][:90],
                "category": m["category"], "key": f"{m['account']}:{m['id']}"} for m in need[:5]]
        summary = f"{len(mail)} new · {len(need)} need you · {len(drafts)} drafts"
        if not mail and ctx["results"].get("Reader") and ctx["results"]["Reader"].status != "done":
            summary = ctx["results"]["Reader"].summary
        return AgentResult("done", f"{len(need)} NEED YOU", summary,
                           {"total": len(mail), "attention": top, "drafts": [{"to": d["to"], "subject": d["subject"], "body": d["body"]} for d in drafts[:3]],
                            "counts": (ctx["results"].get("Categorizer").data if ctx["results"].get("Categorizer") else {}).get("counts", {})})


class Writer(SubAgent):
    name, tier, note = "Writer", "CLOUD", "drafts in your tone"

    async def run(self, ctx):
        store, llm, opts = ctx["store"], ctx.get("llm"), ctx["options"]
        todo = [m for m in ctx.get("mail", []) if m.get("attention") and not m.get("drafted")][: int(opts.get("max_drafts_per_cycle", 3))]
        if not todo:
            pending = len([d for d in store.kv_list("drafts") if d.get("status") == "pending"])
            return AgentResult("wait" if pending else "done", f"{pending} DRAFTS" if pending else "NOTHING TO DRAFT", f"{pending} drafts waiting")
        if not llm:
            return AgentResult("idle", "NEEDS AI", "Drafting needs LM Studio or a cloud model")
        accts = {a["id"]: a for a in accounts(opts)}
        made = 0
        for m in todo:
            try:
                body = await mailcal.get_body(accts[m["account"]], m["id"])
                text = await llm.complete(
                    f"Write a short, friendly, professional reply as {ctx['cfg'].vision.owner}. Tone: {opts.get('tone', 'warm, direct, concise')}. "
                    "Don't invent facts, dates or commitments; if something must be decided, propose options or ask. "
                    f"Sign off as: {opts.get('signature', ctx['cfg'].vision.owner)}\n\nFrom: {m['from_name']} <{m['from']}>\nSubject: {m['subject']}\n\n{body[:3500]}",
                    system="You draft email replies. Output only the reply body.", tier="cloud", max_tokens=500)
            except LLMUnavailable:
                return AgentResult("idle", "NEEDS AI", "Drafting needs LM Studio or a cloud model")
            key = f"{m['account']}:{m['id']}"
            subj = m["subject"] if m["subject"].lower().startswith("re:") else "Re: " + m["subject"]
            store.kv_put("drafts", key, {"to": m["from"], "subject": subj, "body": text.strip(), "email": m, "status": "pending"})
            m["drafted"] = True
            store.kv_put("emails", key, m)
            request_approval(ctx, self.name, f"Reply to {m['from_name'] or m['from']}: {m['subject'][:60]}",
                             {"key": f"reply:{key}", "kind": "email_reply", "draft": key})
            made += 1
        return AgentResult("wait", f"{made} DRAFTS", f"Drafted {made} replies for your OK")


class Sender(SubAgent):
    name, tier, note = "Sender", "API", "sends after approval"

    async def run(self, ctx):
        sent = ctx["store"].kv_list("sent", since=time.time() - 86400)
        return AgentResult("done" if sent else "idle", f"{len(sent)} SENT" if sent else "WAITING", f"{len(sent)} sent today")


# ---------- approval actions (also used by other masters to send email) ----------
async def _send(ctx: dict, account_id: str, to: str, subject: str, body: str, reply_to: dict | None = None) -> None:
    opts = ctx["cfg"].master("email").options
    accts = {a["id"]: a for a in accounts(opts)}
    acct = accts.get(account_id) or (accounts(opts) or [None])[0]
    if not acct:
        raise RuntimeError("No email account connected")
    await mailcal.send(acct, to=to, subject=subject, body=body, reply_to=reply_to)
    ctx["store"].kv_put("sent", f"{int(time.time() * 1000)}", {"to": to, "subject": subject, "account": acct["id"]})


async def approve_reply(row: dict, decision: str, ctx: dict) -> str:
    store = ctx["store"]
    d = store.kv_get("drafts", row["payload"]["draft"])
    if not d:
        return "draft not found"
    if decision != "approved":
        d["status"] = "rejected"
        store.kv_put("drafts", row["payload"]["draft"], d)
        return "kept as draft"
    await _send(ctx, d["email"]["account"], d["to"], d["subject"], d["body"], reply_to=d["email"])
    d["status"] = "sent"
    store.kv_put("drafts", row["payload"]["draft"], d)
    return f"reply sent to {d['to']}"


async def approve_send(row: dict, decision: str, ctx: dict) -> str:
    p = row["payload"]
    if decision != "approved":
        return "not sent"
    await _send(ctx, p.get("account", ""), p["to"], p["subject"], p["body"])
    return f"sent to {p['to']}"


APPROVAL_HANDLERS = {"email_reply": approve_reply, "email_send": approve_send}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Reader": Reader(), "Categorizer": Categorizer(), "Summarizer": Summarizer(), "Writer": Writer(), "Sender": Sender()}
