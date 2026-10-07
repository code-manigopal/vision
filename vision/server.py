"""VISION server: serves the dashboard, streams live state over WebSocket, exposes a small API.

Listens on 127.0.0.1 only. For phone access use Telegram (Phase 2) or a private network like Tailscale.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import desk
from .bus import EventBus, Store
from .config import ROOT, load_config
from .masters import build_masters
from .ask import AskEngine
from .orchestrator import Orchestrator
from .voice import STT, TTS, VoiceUnavailable, WakeWord
from .channels.telegram import TelegramChannel
from .services import fyers, kite_mcp, mailcal, oauth, sysmon, traffic_api, weather
from .services.llm import LLMUnavailable
from .masters.email import accounts as email_accounts
from .masters import visa

log = logging.getLogger("vision")
DASH = ROOT / "dashboard"


def _short(s: str, n: int = 160) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:n]


def rule_explanation(master: str, agent: str, error: str, blocked: list[str]) -> str:
    e, low = _short(error), (error or "").lower()
    who = f"{agent} in {master}"
    key = re.search(r"\b(?:add|set|missing)\s+([A-Z][A-Z0-9_]{3,})", error or "")
    if key or "api key" in low or "not set" in low or ".env" in low:
        what = f"The setting {key.group(1)}" if key else "A required key or setting"
        text = f"{who} failed because {what} is missing. Add it to your .env file and restart VISION."
    elif re.search(r"\b(401|403)\b|unauthori[sz]ed|forbidden|expired|log ?in|sign ?in|token", low):
        text = f"{who} failed, most likely a sign-in or key problem: it was refused or the login expired. Sign in again or check the key."
    elif re.search(r"\b429\b|rate.?limit|too many requests", low):
        text = f"{who} hit a rate limit. Wait a while; it will try again on its next cycle."
    elif re.search(r"timeout|timed out|connect|dns|name or service|unreachable|network", low):
        text = f"{who} could not reach its service, so the service or the network is down. It will retry on its next cycle."
    else:
        text = f"{who} failed with: {e or 'no error text'}. It will retry on its next cycle."
    if blocked:
        text += f" That is holding up {', '.join(blocked)}."
    return text


def create_app(*, boot_on_start: bool = True, schedules: bool = True, telegram_on: bool = True, voice_on: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = load_config()
        bus = EventBus()
        store = Store(ROOT / "data" / "vision.db")
        orch = Orchestrator(cfg, build_masters(cfg), bus, store)
        orch.seed_state()
        app.state.cfg, app.state.bus, app.state.orch = cfg, bus, orch
        app.state.ask = AskEngine(orch)
        app.state.tts, app.state.stt = TTS(cfg.voice), STT(cfg.voice)
        wake = WakeWord(cfg.voice, bus, asyncio.get_running_loop())
        bus.state["voice"] = {"tts": app.state.tts.available(), "stt": app.state.stt.available(), "wake": wake.start() if voice_on else False}
        telegram = TelegramChannel(bus, store, orch)
        orch.channels.append(telegram)
        app.state.store, app.state.telegram = store, telegram
        if telegram_on:
            await telegram.start()
        if boot_on_start:
            orch.start_boot()
        if schedules:
            orch.start_schedules()
        instruments = asyncio.create_task(sysmon.run(bus))
        log.info("VISION online at http://%s:%s", cfg.vision.host, cfg.vision.port)
        yield
        instruments.cancel()
        orch.shutdown()
        wake.stop()
        await telegram.stop()

    app = FastAPI(title="VISION", lifespan=lifespan)
    app.include_router(traffic_api.router)
    app.mount("/dashboard", StaticFiles(directory=DASH), name="dashboard")

    @app.get("/")
    async def index():
        return FileResponse(DASH / "index.html")

    # ---------- broker logins ----------
    @app.get("/auth/fyers/login")
    async def fyers_login():
        if not fyers.configured():
            return HTMLResponse(_page("Fyers isn't set up", "Add FYERS_APP_ID and FYERS_SECRET to .env, then restart VISION."), 400)
        return RedirectResponse(fyers.login_url(app.state.cfg.vision.port))

    @app.get("/auth/fyers/callback")
    async def fyers_callback(auth_code: str | None = None, s: str | None = None, message: str | None = None):
        if not auth_code:
            return HTMLResponse(_page("Fyers login didn't finish", message or "No code came back. Try the login link again."), 400)
        try:
            await fyers.exchange_code(auth_code)
        except Exception as e:
            return HTMLResponse(_page("Fyers login failed", str(e)), 400)
        app.state.bus.clear_notice("fyers")
        app.state.bus.say("Fyers connected")
        asyncio.create_task(app.state.orch.run_master("invest", "login"))
        return HTMLResponse(_page("Fyers connected ✓", "You can close this tab. VISION is refreshing your holdings."))

    @app.get("/auth/kite/login")
    async def kite_login():
        """Zerodha's login belongs to VISION's own Kite MCP session, so we fetch the link live."""
        try:
            url, text = await kite_mcp.shared().login_url()
        except Exception as e:
            return HTMLResponse(_page("Couldn't reach Zerodha", f"The Kite MCP server didn't answer: {e}<br>Try again in a moment."), 502)
        if url:
            # Kite sends the browser back to the MCP server, not to VISION, so watch the session ourselves
            if not (getattr(app.state, "kite_wait", None) and not app.state.kite_wait.done()):
                app.state.kite_wait = asyncio.create_task(_kite_wait(app.state.orch, app.state.bus))
            return RedirectResponse(url)
        return HTMLResponse(_page("No login link came back", f"Kite replied:<br><pre style='white-space:pre-wrap'>{text[:800]}</pre>"), 502)

    @app.get("/auth/kite/done")
    async def kite_done():
        app.state.bus.clear_notice("kite")
        asyncio.create_task(app.state.orch.run_master("invest", "login"))
        return HTMLResponse(_page("Thanks ✓", "Refreshing your Zerodha holdings now."))

    @app.get("/auth/{provider}/login")
    async def oauth_login(provider: str, account: str):
        if provider not in oauth.PROVIDERS:
            raise HTTPException(404)
        if not oauth.configured(provider):
            keys = "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET" if provider in ("google", "youtube") else "MS_CLIENT_ID / MS_CLIENT_SECRET"
            return HTMLResponse(_page(f"{provider.title()} isn't set up", f"Add {keys} to .env, then restart VISION."), 400)
        return RedirectResponse(oauth.login_url(provider, account, app.state.cfg.vision.port))

    @app.get("/auth/{provider}/callback")
    async def oauth_callback(provider: str, code: str | None = None, state: str | None = None, error: str | None = None):
        st = oauth.pop_state(state or "")
        if not code or not st or st[0] != provider:
            return HTMLResponse(_page("Sign-in didn't finish", error or "Try the sign-in link again."), 400)
        try:
            await oauth.exchange(provider, st[1], code, app.state.cfg.vision.port)
        except Exception as e:
            return HTMLResponse(_page("Sign-in failed", str(e)), 400)
        app.state.bus.clear_notice(f"auth:{st[1]}")
        app.state.bus.say(f"{provider.title()} connected for {st[1]}")
        for mid in ("email", "calendar"):
            asyncio.create_task(app.state.orch.run_master(mid, "login"))
        return HTMLResponse(_page(f"{provider.title()} connected ✓", f"The '{st[1]}' account is connected. You can close this tab."))

    # ---------- Ask + voice ----------
    @app.post("/api/ask")
    async def ask(item: dict):
        text = (item.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text is required")
        return await app.state.ask.ask(text, item.get("session") or "default")

    @app.post("/api/tts")
    async def tts(item: dict):
        try:
            wav = await app.state.tts.synth(item.get("text") or "", item.get("voice"))
        except VoiceUnavailable as e:
            raise HTTPException(503, str(e))
        return Response(wav, media_type="audio/wav")

    @app.get("/api/weather/grid")
    async def weather_grid():
        """Current weather at ~100 points for the World Watch globe (Open-Meteo, cached an hour)."""
        try:
            return await weather.grid()
        except Exception as e:
            raise HTTPException(502, f"Weather grid unavailable: {e}")

    @app.get("/api/voices")
    async def voices():
        return await asyncio.to_thread(app.state.tts.voices)

    @app.post("/api/stt")
    async def stt(request: Request):
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "no audio")
        kind = request.headers.get("content-type", "audio/webm")
        try:
            text = await app.state.stt.transcribe(audio, ".wav" if "wav" in kind else ".mp4" if "mp4" in kind else ".webm")
        except VoiceUnavailable as e:
            raise HTTPException(503, str(e))
        return {"text": text}

    @app.get("/api/state")
    async def state():
        return app.state.bus.snapshot()["state"]

    @app.post("/api/boot")
    async def reboot():
        app.state.orch.wake()
        app.state.orch.start_boot()
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown():
        await app.state.orch.standby()
        return {"ok": True}

    @app.post("/api/masters/{master_id}/run")
    async def run_master(master_id: str):
        orch = app.state.orch
        if master_id not in orch.by_id:
            raise HTTPException(404, f"No master called {master_id}")
        if orch.asleep:
            raise HTTPException(409, "VISION is in standby")
        asyncio.create_task(orch.run_master(master_id, "manual"))
        return {"ok": True}

    @app.get("/api/brief")
    async def brief():
        return {"text": app.state.orch.compose_brief()}

    @app.post("/api/brief/send")
    async def send_brief():
        await app.state.orch.brief("now")
        return {"ok": True, "telegram": app.state.bus.state["telegram"]}

    # ---------- approvals (the YOU gate) ----------
    @app.get("/api/approvals")
    async def approvals():
        return app.state.store.pending_approvals()

    @app.post("/api/approvals")
    async def new_approval(item: dict):
        a = app.state.store.add_approval(item.get("master", "vision"), item.get("agent", "manual"), item["title"], item.get("payload"))
        app.state.bus.publish({"type": "approval", "approval": a})
        return a

    # ---------- issues (agent errors) ----------
    def _issues() -> list[dict]:
        out = []
        for mid, m in app.state.bus.state["masters"].items():
            agents = m.get("agents", [])
            for a in agents:
                if a.get("status") != "error":
                    continue
                run = app.state.store.last_run(mid, a["name"])
                err = a.get("summary") or ((app.state.store.last_run(mid, a["name"], True) or {}).get("error")) or ""
                blocked = [b["name"] for b in agents if b.get("label") == "BLOCKED" and (b.get("summary") or "") == f"Waiting on {a['name']}"]
                out.append({"master": mid, "master_name": m.get("name", mid), "agent": a["name"], "label": a.get("label", "ERROR"),
                            "error": err, "ts": run["ts"] if run else None, "blocked": blocked})
        return out

    @app.get("/api/issues")
    async def issues():
        return {"issues": _issues()}

    @app.post("/api/issues/explain")
    async def explain_issue(body: dict):
        it = next((i for i in _issues() if i["master"] == body.get("master") and i["agent"] == body.get("agent")), None)
        if not it:
            raise HTTPException(404, "No such issue")
        prompt = ("Explain this problem in a personal assistant app to its owner, in 2-3 short plain sentences that will be spoken aloud: "
                  "what failed, the most likely cause, and what to do. Use only the facts below; do not invent details.\n"
                  f"Master: {it['master_name']}\nAgent: {it['agent']}\nError: {_short(it['error'], 400)}\n"
                  f"Agents blocked by it: {', '.join(it['blocked']) or 'none'}")
        try:
            text = (await asyncio.wait_for(app.state.orch.llm.complete(prompt, tier="local", max_tokens=200), 20)).strip()
            if text:
                return {"text": text, "source": "llm"}
        except (LLMUnavailable, asyncio.TimeoutError, Exception):
            pass
        return {"text": rule_explanation(it["master_name"], it["agent"], it["error"], it["blocked"]), "source": "rule"}

    # ---------- email reply preview ----------
    def _email_approval(approval_id: int) -> tuple[dict, dict, dict, dict]:
        row = app.state.store.get_approval(approval_id)
        p = (row or {}).get("payload") or {}
        d = app.state.store.kv_get("drafts", p["draft"]) if p.get("kind") == "email_reply" and p.get("draft") else None
        if not d or not d.get("email"):
            raise HTTPException(404, "Not an email reply approval")
        msg = d["email"]
        accts = {a["id"]: a for a in email_accounts(app.state.cfg.master("email").options)}
        acct = accts.get(msg.get("account"))
        if not acct:
            raise HTTPException(404, "Email account not configured")
        return row, d, msg, acct

    @app.get("/api/approvals/{approval_id}/email")
    async def approval_email(approval_id: int):
        _, d, msg, acct = _email_approval(approval_id)
        partial, atts = False, []
        try:
            body = await mailcal.get_body(acct, msg["id"], limit=200000)
        except Exception:
            body, partial = msg.get("snippet", ""), True
        try:
            atts = await mailcal.list_attachments(acct, msg)
        except Exception:
            pass
        out = {"email": {"from": msg.get("from"), "from_name": msg.get("from_name"), "to": msg.get("to"), "subject": msg.get("subject"),
                         "ts": msg.get("ts"), "body": body},
               "draft": {"to": d.get("to"), "subject": d.get("subject"), "body": d.get("body")}, "attachments": atts}
        if partial:
            out["partial"] = True
        return out

    @app.get("/api/approvals/{approval_id}/attachments/{att_id}")
    async def approval_attachment(approval_id: int, att_id: str):
        _, _, msg, acct = _email_approval(approval_id)
        try:
            data, mime, name = await mailcal.get_attachment(acct, msg, att_id)
        except mailcal.AttachmentNotFound:
            raise HTTPException(404, "No such attachment")
        except mailcal.AttachmentTooLarge:
            raise HTTPException(413, "Attachment is over 25 MB")
        except Exception:
            raise HTTPException(502, "Could not fetch the attachment")
        safe = re.sub(r'[^A-Za-z0-9._ -]', "_", name)[:120] or "attachment"
        headers = {"Content-Disposition": f'inline; filename="{safe}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        if mime != "application/pdf":   # Chrome's own PDF viewer won't render a sandboxed response; everything else stays locked down
            headers["Content-Security-Policy"] = "sandbox"
        return Response(data, media_type=mime or "application/octet-stream", headers=headers)

    # ---------- Visa Watch accounts (the dashboard's form; a password is optional, comes in once, is encrypted, and is never sent back) ----------
    signing: dict[str, asyncio.Task] = {}

    async def _visa_sign_in(acc: dict) -> None:
        try:
            await visa.sign_in(app.state.store, acc)
            if acc["status"] == "active" and not app.state.orch.asleep and "visa" in app.state.orch.by_id:
                await app.state.orch.run_master("visa", "manual")      # first look straight after the sign-in
        finally:
            signing.pop(acc["id"], None)

    def _visa(request: Request, acc_id: str | None = None) -> dict | None:
        origin = request.headers.get("origin")
        if origin and origin.split("//")[-1].split(":")[0] not in ("127.0.0.1", "localhost"):
            raise HTTPException(403, "Only the dashboard on this Mac may change accounts")
        if acc_id is None:
            return None
        acc = next((a for a in visa.accounts(app.state.store) if a["id"] == acc_id), None)
        if not acc:
            raise HTTPException(404, "No such account")
        return acc

    def _visa_list() -> dict:
        return {"accounts": [{**visa.public(a), "signing": a["id"] in signing} for a in visa.accounts(app.state.store)]}

    def _cities(v) -> list[str]:
        return [c.strip() for c in (v.split(",") if isinstance(v, str) else v or []) if str(c).strip()]

    @app.get("/api/visa/accounts")
    async def visa_accounts():
        return _visa_list()

    @app.post("/api/visa/accounts")
    async def visa_add(request: Request):
        _visa(request)
        b = await request.json()
        name, email, cities = (b.get("name") or "").strip(), (b.get("email") or "").strip(), _cities(b.get("cities"))
        if not (name and email and cities):
            raise HTTPException(400, "Name, sign-in email and at least one city are needed")
        try:
            visa.add_account(app.state.store, name, email, cities, (b.get("booked") or "").strip(), password=b.get("password") or None,
                             not_before=(b.get("not_before") or "").strip() or None, skip=b.get("skip"))
        except ValueError:
            raise HTTPException(400, "Dates must look like 2027-04-22; dates to skip like 2027-03-10, 2027-04-01..2027-04-07")
        return _visa_list()

    @app.post("/api/visa/accounts/{acc_id}")
    async def visa_update(acc_id: str, request: Request):
        acc = _visa(request, acc_id)
        b = await request.json()
        action = b.get("action")
        try:
            if action in ("pause", "resume"):
                visa.set_status(app.state.store, acc, "paused" if action == "pause" else "active")
            elif action == "signin":             # opens a window on this Mac; the person signs in, VISION keeps the session
                if acc["id"] not in signing:
                    signing[acc["id"]] = asyncio.create_task(_visa_sign_in(acc))
            elif action == "check":              # due now; the master still keeps its gap between checks
                acc["next_due"] = 0
                visa.save(app.state.store, acc)
                if not app.state.orch.asleep and "visa" in app.state.orch.by_id:
                    asyncio.create_task(app.state.orch.run_master("visa", "manual"))
            else:
                visa.update_account(app.state.store, acc, cities=_cities(b.get("cities")) or None, booked=(b.get("booked") or "").strip() or None,
                                    password=b.get("password") or None, forget=action == "forget",
                                    not_before=b["not_before"].strip() if isinstance(b.get("not_before"), str) else None, skip=b.get("skip"))
        except ValueError:
            raise HTTPException(400, "Dates must look like 2027-04-22; dates to skip like 2027-03-10, 2027-04-01..2027-04-07")
        return _visa_list()

    @app.delete("/api/visa/accounts/{acc_id}")
    async def visa_remove(acc_id: str, request: Request):
        acc = _visa(request, acc_id)
        visa.remove_account(app.state.store, acc["id"])
        for key in (f"visa:slot:{acc['id']}", f"visa:paused:{acc['id']}", f"visa:signin:{acc['id']}"):
            app.state.bus.clear_notice(key)
        return _visa_list()

    @app.get("/api/desk/{master_id}")
    async def desk_view(master_id: str):
        out = desk.build(app.state.store, master_id)
        if out is None:
            raise HTTPException(404, "No such master")
        return out

    @app.get("/api/files/{path:path}")
    async def desk_file(path: str):
        p = desk.resolve_file(path)
        if p is None:
            raise HTTPException(404, "No such file")
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        safe = re.sub(r'[^A-Za-z0-9._ -]', "_", p.name)[:120] or "file"
        headers = {"Content-Disposition": f'inline; filename="{safe}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        if mime != "application/pdf":   # Chrome's PDF viewer won't render a sandboxed response
            # VISION's own demo pages reveal their sections with a script, so they may run it (still no same-origin access)
            own_page = path.split("/", 1)[0] == "sites" and mime == "text/html"
            headers["Content-Security-Policy"] = "sandbox allow-scripts" if own_page else "sandbox"
        return Response(p.read_bytes(), media_type=mime, headers=headers)

    @app.post("/api/approvals/{approval_id}/{decision}")
    async def decide(approval_id: int, decision: str):
        if decision not in ("approved", "rejected"):
            raise HTTPException(400, "decision must be approved or rejected")
        if app.state.orch.asleep:
            raise HTTPException(409, "VISION is in standby")
        row = app.state.store.decide_approval(approval_id, decision)
        if not row:
            raise HTTPException(409, "Already decided or not found")
        app.state.bus.publish({"type": "approval_decided", "id": approval_id, "decision": decision})
        app.state.bus.say(f"{row['title']} → {decision} on the dashboard")
        return row

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        bus: EventBus = app.state.bus
        q = bus.subscribe()
        try:
            await sock.send_json(bus.snapshot())
            while True:
                await sock.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            bus.unsubscribe(q)

    return app


async def _kite_wait(orch, bus, tries: int = 60, every: float = 5) -> None:
    """After the Log in button: poll until the Kite session is logged in, then clear the notice and refresh holdings."""
    for _ in range(tries):
        await asyncio.sleep(every)
        try:
            if await kite_mcp.shared().logged_in():
                bus.clear_notice("kite")
                await orch.run_master("invest", "login")
                return
        except Exception as e:
            log.warning("Kite login check failed: %s", e)


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><meta name=viewport content='width=device-width'><title>VISION</title>"
            f"<body style='background:#07080A;color:#EDE6D6;font-family:system-ui;padding:40px'>"
            f"<h2 style='color:#FBCA03;letter-spacing:2px'>{title}</h2><p>{body}</p></body>")
