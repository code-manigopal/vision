import asyncio
import json

import httpx
import pytest

from vision.bus import EventBus, Store
from vision.channels.telegram import TelegramChannel
from vision.config import Config, MasterConfig
from vision.masters import build_masters
from vision.orchestrator import Orchestrator


class FakeTelegram:
    """Records every Bot API call; getUpdates returns queued updates once."""

    def __init__(self):
        self.calls, self.updates = [], []

    def handler(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        body = json.loads(req.content or b"{}")
        self.calls.append((method, body))
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "vision_test_bot"}})
        if method == "getUpdates":
            ups, self.updates = self.updates, []
            return httpx.Response(200, json={"ok": True, "result": ups})
        return httpx.Response(200, json={"ok": True, "result": {}})

    def sent(self):
        return [b for m, b in self.calls if m == "sendMessage"]


def make(tmp_path, monkeypatch, token="T", chat="42"):
    for k, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    cfg = Config(masters={"youtube": MasterConfig(enabled=False), "traffic": MasterConfig(mode="live", options={"watch_cities": ["Leamington"]})})
    bus, store = EventBus(), Store(tmp_path / "t.db")
    orch = Orchestrator(cfg, build_masters(cfg), bus, store)
    fake = FakeTelegram()
    tg = TelegramChannel(bus, store, orch, client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    orch.channels.append(tg)
    return bus, store, orch, tg, fake


def test_no_token_stays_off(tmp_path, monkeypatch):
    bus, _, orch, tg, fake = make(tmp_path, monkeypatch, token=None, chat=None)
    asyncio.run(tg.start())
    assert bus.state["telegram"]["connected"] is False
    assert "TELEGRAM_BOT_TOKEN" in bus.state["telegram"]["reason"]
    assert fake.calls == []
    assert asyncio.run(orch.brief("morning"))          # VISION still works without Telegram


def test_setup_mode_replies_chat_id(tmp_path, monkeypatch):
    bus, _, _, tg, fake = make(tmp_path, monkeypatch, chat=None)
    asyncio.run(tg.handle_update({"update_id": 1, "message": {"chat": {"id": 777}, "text": "/start"}}))
    assert fake.sent()[0]["chat_id"] == "777" and "777" in fake.sent()[0]["text"]


def test_strangers_ignored_owner_answered(tmp_path, monkeypatch):
    bus, _, orch, tg, fake = make(tmp_path, monkeypatch)
    asyncio.run(orch.boot())
    asyncio.run(tg.handle_update({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/brief"}}))
    assert fake.sent() == []
    asyncio.run(tg.handle_update({"update_id": 2, "message": {"chat": {"id": 42}, "text": "what's up"}}))
    text = fake.sent()[0]["text"]
    assert "Email Manager" in text and "Traffic Desk" in text and "YouTube" not in text


def test_morning_brief_is_masters_only(tmp_path, monkeypatch):
    bus, _, orch, tg, fake = make(tmp_path, monkeypatch)
    asyncio.run(orch.boot())
    asyncio.run(orch.brief("morning"))
    text = fake.sent()[-1]["text"]
    assert text.startswith("☀️ <b>VISION · Good morning")
    assert "⚠️ <b>Traffic Desk</b>: Blocked" in text          # no TomTom key -> blocked, flagged
    assert "Summarizer" not in text                            # sub-agents never appear, only master reports


def test_alert_and_approval_buttons(tmp_path, monkeypatch):
    bus, store, orch, tg, fake = make(tmp_path, monkeypatch)

    async def flow():
        watcher = asyncio.create_task(tg._watch_bus())
        await asyncio.sleep(0)
        bus.say("⚠ Traffic Desk · City Geocoder failed: TOMTOM_API_KEY is not set")
        bus.say("⚠ Traffic Desk · City Geocoder failed: TOMTOM_API_KEY is not set")   # duplicate: suppressed
        a = store.add_approval("email", "Writer", "Send reply re: meeting next week")
        bus.publish({"type": "approval", "approval": a})
        await asyncio.sleep(0.05)
        watcher.cancel()
        return a

    a = asyncio.run(flow())
    sent = fake.sent()
    assert sum("Alert" in s["text"] for s in sent) == 1
    ap = [s for s in sent if "Approval needed" in s["text"]][0]
    assert ap["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"ap:{a['id']}:approved"

    tap = {"update_id": 9, "callback_query": {"id": "cb1", "data": f"ap:{a['id']}:approved",
           "message": {"chat": {"id": 42}, "message_id": 5, "text": "Approval needed"}}}
    asyncio.run(tg.handle_update(tap))
    assert store.pending_approvals() == []
    assert bus.state["approvals"] == []
    asyncio.run(tg.handle_update(tap))                         # second tap: already decided, no change
    assert ("answerCallbackQuery", {"callback_query_id": "cb1", "text": "Already decided"}) in fake.calls
