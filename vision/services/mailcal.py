"""Mail and calendar access for every connected account (Google or Microsoft), normalised to one shape.

email: {id, account, provider, thread, from, from_name, to, subject, snippet, ts, unread, message_id, labels}
event: {id, account, provider, title, start, end, all_day, attendees, location}
"""

from __future__ import annotations

import base64
import email.utils
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import unescape

import httpx

from . import oauth

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GCAL = "https://www.googleapis.com/calendar/v3/calendars/primary"
GRAPH = "https://graph.microsoft.com/v1.0/me"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30)


async def _auth(account: dict) -> dict:
    tok = await oauth.access_token(account["id"], account["provider"])
    return {"Authorization": f"Bearer {tok}"}


def _strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s, flags=re.I)
    return re.sub(r"[ \t]+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _addr(raw: str) -> tuple[str, str]:
    name, addr = email.utils.parseaddr(raw or "")
    return name or addr, addr


# ======================= MAIL =======================

async def list_recent(account: dict, hours: int = 24) -> list[dict]:
    h = await _auth(account)
    async with _client() as c:
        if account["provider"] == "google":
            r = await c.get(f"{GMAIL}/messages", headers=h, params={"q": f"newer_than:{max(1, hours // 24)}d", "maxResults": 100})
            r.raise_for_status()
            out = []
            for m in r.json().get("messages", []):
                d = (await c.get(f"{GMAIL}/messages/{m['id']}", headers=h, params=[("format", "metadata")] +
                                 [("metadataHeaders", x) for x in ("From", "To", "Subject", "Date", "Message-ID")])).json()
                hd = {x["name"].lower(): x["value"] for x in d.get("payload", {}).get("headers", [])}
                ts = int(d.get("internalDate", "0")) / 1000
                if ts < time.time() - hours * 3600:
                    continue
                name, addr = _addr(hd.get("from", ""))
                out.append({"id": d["id"], "account": account["id"], "provider": "google", "thread": d.get("threadId"),
                            "from": addr, "from_name": name, "to": hd.get("to", ""), "subject": hd.get("subject", "(no subject)"),
                            "snippet": unescape(d.get("snippet", "")), "ts": ts, "unread": "UNREAD" in d.get("labelIds", []),
                            "message_id": hd.get("message-id"), "labels": d.get("labelIds", [])})
            return out
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = await c.get(f"{GRAPH}/messages", headers=h, params={
            "$filter": f"receivedDateTime ge {since}", "$top": 100, "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,from,toRecipients,subject,bodyPreview,receivedDateTime,isRead,internetMessageId,categories,inferenceClassification"})
        r.raise_for_status()
        out = []
        for m in r.json().get("value", []):
            f = (m.get("from") or {}).get("emailAddress", {})
            out.append({"id": m["id"], "account": account["id"], "provider": "microsoft", "thread": m.get("conversationId"),
                        "from": f.get("address", ""), "from_name": f.get("name", ""), "to": ", ".join(x["emailAddress"]["address"] for x in m.get("toRecipients", [])),
                        "subject": m.get("subject") or "(no subject)", "snippet": m.get("bodyPreview", ""),
                        "ts": datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00")).timestamp(),
                        "unread": not m.get("isRead"), "message_id": m.get("internetMessageId"),
                        "labels": (m.get("categories") or []) + [m.get("inferenceClassification", "")]})
        return out


async def get_body(account: dict, msg_id: str, limit: int = 6000) -> str:
    h = await _auth(account)
    async with _client() as c:
        if account["provider"] == "google":
            d = (await c.get(f"{GMAIL}/messages/{msg_id}", headers=h, params={"format": "full"})).json()
            texts, htmls = [], []

            def walk(part):
                data = part.get("body", {}).get("data")
                if data:
                    raw = base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
                    (texts if part.get("mimeType") == "text/plain" else htmls if part.get("mimeType") == "text/html" else []).append(raw)
                for p in part.get("parts", []) or []:
                    walk(p)
            walk(d.get("payload", {}))
            body = "\n".join(texts) or _strip_html("\n".join(htmls))
        else:
            d = (await c.get(f"{GRAPH}/messages/{msg_id}", headers={**h, "Prefer": 'outlook.body-content-type="text"'}, params={"$select": "body"})).json()
            body = d.get("body", {}).get("content", "")
    return body[:limit]


async def send(account: dict, *, to: str, subject: str, body: str, reply_to: dict | None = None) -> None:
    """Send a new message, or a reply when reply_to (a normalised email) is given."""
    h = await _auth(account)
    async with _client() as c:
        if account["provider"] == "google":
            msg = EmailMessage()
            msg["To"], msg["Subject"] = to, subject
            if reply_to and reply_to.get("message_id"):
                msg["In-Reply-To"] = msg["References"] = reply_to["message_id"]
            msg.set_content(body)
            payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
            if reply_to and reply_to.get("thread"):
                payload["threadId"] = reply_to["thread"]
            r = await c.post(f"{GMAIL}/messages/send", headers=h, json=payload)
        elif reply_to:
            r = await c.post(f"{GRAPH}/messages/{reply_to['id']}/reply", headers=h, json={"comment": body})
        else:
            r = await c.post(f"{GRAPH}/sendMail", headers=h, json={"message": {
                "subject": subject, "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": a.strip()}} for a in to.split(",") if a.strip()]}})
        r.raise_for_status()


# ======================= CALENDAR =======================

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def list_events(account: dict, start: datetime, end: datetime, tz: str) -> list[dict]:
    h = await _auth(account)
    async with _client() as c:
        if account["provider"] == "google":
            r = await c.get(f"{GCAL}/events", headers=h, params={"timeMin": _iso(start), "timeMax": _iso(end), "singleEvents": "true",
                                                                 "orderBy": "startTime", "maxResults": 250, "timeZone": tz})
            r.raise_for_status()
            out = []
            for e in r.json().get("items", []):
                if e.get("status") == "cancelled":
                    continue
                s, en = e.get("start", {}), e.get("end", {})
                out.append({"id": e["id"], "account": account["id"], "provider": "google", "title": e.get("summary", "(busy)"),
                            "start": s.get("dateTime") or s.get("date"), "end": en.get("dateTime") or en.get("date"),
                            "all_day": "date" in s, "attendees": [a.get("email") for a in e.get("attendees", [])], "location": e.get("location", "")})
            return out
        r = await c.get(f"{GRAPH}/calendarView", headers={**h, "Prefer": f'outlook.timezone="{tz}"'},
                        params={"startDateTime": _iso(start), "endDateTime": _iso(end), "$top": 250,
                                "$select": "id,subject,start,end,isAllDay,attendees,location,isCancelled", "$orderby": "start/dateTime"})
        r.raise_for_status()
        return [{"id": e["id"], "account": account["id"], "provider": "microsoft", "title": e.get("subject") or "(busy)",
                 "start": e["start"]["dateTime"], "end": e["end"]["dateTime"], "all_day": e.get("isAllDay", False),
                 "attendees": [a["emailAddress"]["address"] for a in e.get("attendees", [])], "location": (e.get("location") or {}).get("displayName", "")}
                for e in r.json().get("value", []) if not e.get("isCancelled")]


async def create_event(account: dict, *, title: str, start: str, end: str, tz: str, attendees: list[str] | None = None, description: str = "") -> dict:
    """start/end: local ISO 'YYYY-MM-DDTHH:MM:SS' in tz. Invites go to attendees."""
    h = await _auth(account)
    async with _client() as c:
        if account["provider"] == "google":
            r = await c.post(f"{GCAL}/events", headers=h, params={"sendUpdates": "all"}, json={
                "summary": title, "description": description, "start": {"dateTime": start, "timeZone": tz}, "end": {"dateTime": end, "timeZone": tz},
                "attendees": [{"email": a} for a in attendees or []]})
        else:
            r = await c.post(f"{GRAPH}/events", headers=h, json={
                "subject": title, "body": {"contentType": "Text", "content": description},
                "start": {"dateTime": start, "timeZone": tz}, "end": {"dateTime": end, "timeZone": tz},
                "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in attendees or []]})
        r.raise_for_status()
        return r.json()
