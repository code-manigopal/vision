"""Mani's own pronunciation fixes (data/voice_fixes.json): precedence, validation, the approved-reference guard, /say and the API. Nothing real is written."""

import asyncio
import json

import pytest

from vision.masters import tamil_say as ts
from tests.test_telegram import make


@pytest.fixture(autouse=True)
def tmp_fixes(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "FIXES", tmp_path / "voice_fixes.json")
    monkeypatch.setattr(ts, "LEARNED", tmp_path / "voice_words.json")
    return tmp_path


def test_his_fix_wins_over_the_table_and_the_learned_words(tmp_fixes):
    (tmp_fixes / "voice_words.json").write_text(json.dumps({"zebra": "ஜீப்ரா"}), encoding="utf-8")
    assert "revenue" in ts.SOUNDS and "ஜீப்ரா" in ts.voiced("zebra")
    before = ts.voiced("The Revenue grew, zebra.")
    assert ts.set_fix("Revenue", "ரெவென்யூ")["ok"] and ts.set_fix("zebra", "சீப்ரா")["ok"]
    after = ts.voiced("The Revenue grew, zebra.")
    assert "ரெவென்யூ" in after and "சீப்ரா" in after and "ஜீப்ரா" not in after and after != before
    assert ts.source("revenue") == ("fix", "ரெவென்யூ") and ts.source("zebra")[0] == "fix"
    assert ts.source("quarter")[0] == "table" and ts.source("qwertyu") == ("none", "")


def test_longest_phrase_first_whole_words_only_and_ch_rule_not_applied():
    ts.set_fix("free cash flow", "ஃப்ரீ கேஷ் ஃப்ளோ")
    ts.set_fix("cash", "காசு")
    assert ts.voiced("free cash flow") == "ஃப்ரீ கேஷ் ஃப்ளோ" and ts.voiced("Free  Cash Flow") == "ஃப்ரீ கேஷ் ஃப்ளோ" and ts.voiced("Cash") == "காசு"
    assert ts.voiced("cashew") == "cashew"                       # inside another word: untouched
    ts.set_fix("channel", "சேனல்")                                    # his spelling is kept as typed, not turned into ச்சேனல்
    assert ts.voiced("channel") == "சேனல்" and ts.ch_sound("channel", "சேனல்") == "ச்சேனல்"


def test_validation():
    assert not ts.set_fix("channel", "chanel")["ok"] and not ts.set_fix("channel", "")["ok"] and not ts.set_fix("சேனல்", "சேனல்")["ok"]
    assert not ts.set_fix("a" * 50, "சேனல்")["ok"] and not ts.FIXES.exists()


def test_a_word_in_the_approved_reference_is_refused_unless_forced():
    r = ts.set_fix("quarter", "க்வார்ட்டர்")
    assert not r["ok"] and "approved HDFC reference" in r["message"] and not ts.FIXES.exists()
    r = ts.set_fix("quarter", "க்வார்ட்டர்", force=True)
    assert r["ok"] and "tests/test_voice.py will now fail" in r["message"] and ts.source("quarter")[0] == "fix"


def test_telegram_say_command(tmp_path, monkeypatch):
    _, _, _, tg, fake = make(tmp_path, monkeypatch)
    say = lambda t: asyncio.run(tg.handle_update({"update_id": 1, "message": {"chat": {"id": 42}, "text": t}}))
    say("/say channel = ச்சேனல்")
    assert "saved" in fake.sent()[-1]["text"] and ts.source("channel") == ("fix", "ச்சேனல்")
    say("/say channel")
    assert "ச்சேனல்" in fake.sent()[-1]["text"] and "(fix)" in fake.sent()[-1]["text"]
    say("/say nothing")
    assert "no spelling set" in fake.sent()[-1]["text"]
    say("/say bad = abc")
    assert "Tamil letters" in fake.sent()[-1]["text"]
    say("/say quarter = க்வார்ட்டர்")
    assert "approved HDFC reference" in fake.sent()[-1]["text"] and ts.source("quarter")[0] == "table"
    say("/say! quarter = க்வார்ட்டர்")
    assert "will now fail" in fake.sent()[-1]["text"] and ts.source("quarter")[0] == "fix"
    n = len(fake.sent())
    asyncio.run(tg.handle_update({"update_id": 2, "message": {"chat": {"id": 999}, "text": "/say channel = சேனல்"}}))
    assert len(fake.sent()) == n and ts.source("channel")[1] == "ச்சேனல்"


def test_api(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("VISION_HOME", os.getcwd())
    from fastapi.testclient import TestClient
    from vision.server import create_app
    app = create_app(boot_on_start=False, schedules=False, telegram_on=False, voice_on=False)
    with TestClient(app) as c:
        assert c.post("/api/voice/fix", json={"word": "channel", "spelling": "ச்சேனல்"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/api/voice/fix", json={"word": "channel", "spelling": "x"}).status_code == 400
        assert c.post("/api/voice/fix", json={"word": "quarter", "spelling": "க்வார்ட்டர்"}).status_code == 400
        assert c.post("/api/voice/fix", json={"word": "quarter", "spelling": "க்வார்ட்டர்", "force": True}).status_code == 200
        assert c.post("/api/voice/fix", json={"word": "channel", "spelling": "ச்சேனல்"}).json()["ok"] is True
        assert c.get("/api/voice/fix", params={"word": "Channel"}).json() == {"word": "channel", "source": "fix", "spelling": "ச்சேனல்"}
        assert c.get("/api/voice/fix", params={"word": "revenue"}).json()["source"] == "table"
