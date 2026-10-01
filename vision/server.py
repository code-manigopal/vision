"""VISION server: serves the dashboard, streams live state over WebSocket, exposes a small API.

Listens on 127.0.0.1 only. For phone access use Telegram (Phase 2) or a private network like Tailscale.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .bus import EventBus, Store
from .config import ROOT, load_config
from .masters import build_masters
from .ask import AskEngine
from .orchestrator import Orchestrator
from .voice import STT, TTS, VoiceUnavailable, WakeWord
from .channels.telegram import TelegramChannel
from .services import fyers, kite_mcp, oauth, sysmon, traffic_api

log = logging.getLogger("vision")
DASH = ROOT / "dashboard"


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
            keys = "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET" if provider == "google" else "MS_CLIENT_ID / MS_CLIENT_SECRET"
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
            wav = await app.state.tts.synth(item.get("text") or "")
        except VoiceUnavailable as e:
            raise HTTPException(503, str(e))
        return Response(wav, media_type="audio/wav")

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
