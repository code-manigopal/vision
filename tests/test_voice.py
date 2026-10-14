"""The cloned voice's safety net: pinned spellings, the listen-back check, and making a bad line again. No model, no audio engine."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from vision.masters.tamil_say import voiced
from vision.voice import clone, listen

GOLDEN = json.loads((Path(__file__).parent / "golden_voice.json").read_text(encoding="utf-8"))


def test_the_approved_video_is_still_spelt_for_the_voice_exactly_as_mani_approved_it():
    """The 13 lines of the video Mani approved by ear (HDFC Bank Q1 FY27, 2026-10-13). A change to tamil_say that alters how
    any of them is given to the voice fails here: change the golden file only after he has listened to the new sound."""
    assert len(GOLDEN) == 13
    for g in GOLDEN:
        assert voiced(g["say"]) == g["voiced"], g["say"]
        assert clone.unspelt(g["say"]) == []


def test_the_approved_settings_are_the_defaults():
    assert (clone.SPEED, clone.STEPS, clone.PAUSE, clone.TRIES) == (1.3, 16, 0.15, 3)
    assert (listen.MIN_SCORE, listen.MAX_GAP, listen.MAX_EDGE) == (0.55, 0.6, 0.45) and "turbo" in listen.MODEL


def test_score_compares_what_was_meant_with_what_was_heard():
    say = "Net profit போன வருஷம் இதே quarter-ல 18155 கோடி, இப்போ 19060 கோடி."
    assert listen.score(say, "Net Profit போன வருஷம் இதே குவார்ட்டர்ல 18,155 கோடி இப்போ 19,060 கோடி") > 0.9      # English letters and digits are heard as said
    assert listen.score(say, "ரக்கு ரக்கு ரக்கு ரக்கு ரக்கு ரக்கு") < 0.3 and listen.score(say, "") == 0.0


def ffmpeg(stderr):
    return lambda *a, **kw: SimpleNamespace(stderr=stderr)


def test_silences_are_read_from_the_ends_and_the_middle():
    log = "  Duration: 00:00:10.00, bitrate\n[s] silence_start: 0\n[s] silence_end: 0.2 | silence_duration: 0.2\n[s] silence_start: 4.1\n[s] silence_end: 5.0 | silence_duration: 0.9\n[s] silence_start: 9.7\n"
    assert listen.silences(Path("x.wav"), run=ffmpeg(log)) == {"lead": 0.2, "tail": 0.3, "gap": 0.9}
    assert listen.silences(Path("x.wav"), run=ffmpeg("  Duration: 00:00:03.00, bitrate\n")) == {"lead": 0.0, "tail": 0.0, "gap": 0.0}


def test_check_names_what_is_wrong(monkeypatch):
    monkeypatch.setattr(listen, "silences", lambda wav: {"lead": 0.1, "tail": 0.0, "gap": 0.9})
    bad = listen.check(Path("x.wav"), "வணக்கம் நண்பர்களே", hear=lambda w: "வேற ஏதோ")
    assert not bad["ok"] and "hole" in bad["why"] and "heard only" in bad["why"]
    monkeypatch.setattr(listen, "silences", lambda wav: {"lead": 0.1, "tail": 0.2, "gap": 0.3})
    assert listen.check(Path("x.wav"), "வணக்கம் நண்பர்களே", hear=lambda w: "வணக்கம் நண்பர்களே")["ok"]


LINES = [{"say": "வணக்கம் நண்பர்களே!"}, {"say": "Net profit 221 கோடி."}]


def engine(calls):
    def make(say, seed):
        calls.append((say, seed))
        return np.zeros(2400, np.float32), 24000
    return make


def test_a_bad_line_is_made_again_with_another_seed_and_a_good_one_is_kept(tmp_path):
    calls, verdicts = [], iter([{"ok": True, "score": 0.9, "why": ""}, {"ok": False, "score": 0.2, "why": "garbled"}, {"ok": True, "score": 0.8, "why": ""}])
    out = clone.speak(LINES, tmp_path, make=engine(calls), check=lambda wav, say: next(verdicts), log=lambda m: None)
    assert [p.name for p in out] == ["v000.wav", "v001.wav"] and len(calls) == 3
    assert calls[1][0] == voiced(LINES[1]["say"]) and calls[2][1] == calls[1][1] + 1          # the same words, the next seed
    qa = json.loads((tmp_path / "qa.json").read_text(encoding="utf-8"))
    assert [q["tries"] for q in qa] == [1, 2] and all(q["ok"] for q in qa)
    again = []
    clone.speak(LINES, tmp_path, make=engine(again), check=lambda wav, say: {"ok": True, "why": ""}, log=lambda m: None)
    assert again == []                                                                        # passed lines on disk are not made again


def test_a_line_that_never_passes_stops_the_video(tmp_path):
    calls = []
    with pytest.raises(clone.VoiceFailed, match="line 1 did not pass after 3 tries: garbled"):
        clone.speak(LINES, tmp_path, make=engine(calls), check=lambda wav, say: {"ok": False, "score": 0.1, "why": "garbled"}, log=lambda m: None)
    assert len(calls) == 3
    retry = []
    clone.speak(LINES[:1], tmp_path, make=engine(retry), check=lambda wav, say: {"ok": True, "why": ""}, log=lambda m: None)
    assert len(retry) == 1                                                                    # a failed line is not trusted from disk


def test_a_word_left_in_english_letters_never_reaches_the_voice(tmp_path):
    calls = []
    with pytest.raises(clone.VoiceFailed, match="English letters"):
        clone.speak([{"say": "Zomato-ஓட result வந்துருக்கு."}], tmp_path, make=engine(calls), check=lambda wav, say: {"ok": True, "why": ""}, log=lambda m: None)
    assert calls == []


def test_a_line_made_at_another_speed_is_made_again(tmp_path):
    first, second, third = [], [], []
    ok = lambda wav, say: {"ok": True, "why": ""}                                              # noqa: E731
    clone.speak(LINES[:1], tmp_path, make=engine(first), check=ok, log=lambda m: None)
    clone.speak(LINES[:1], tmp_path, speed=clone.SHORT_SPEED, make=engine(second), check=ok, log=lambda m: None)
    clone.speak(LINES[:1], tmp_path, speed=clone.SHORT_SPEED, make=engine(third), check=ok, log=lambda m: None)
    assert (len(first), len(second), len(third)) == (1, 1, 0) and clone.SHORT_SPEED == 1.2


def test_while_the_local_model_is_set_aside_no_request_reaches_lm_studio(monkeypatch):
    """LM Studio reloads a model the moment a request reaches it, so during a video's voice VISION must not ask it anything:
    a local request then falls to the cloud model if there is one, else the caller hears "no model" (never Groq: what the
    owner keeps local stays local)."""
    import asyncio
    import httpx
    from vision.config import Config
    from vision.services import lmstudio
    from vision.services.llm import LLM, LLMUnavailable
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, json={"data": []})
    llm = LLM(Config(), client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(lmstudio, "_models", lambda run: [])

    async def go():
        async with lmstudio.freed(run=lambda *a, **k: None):
            assert lmstudio.set_aside() and not await llm.local_available()
            monkeypatch.setattr(llm, "cloud_available", lambda: False)
            with pytest.raises(LLMUnavailable):
                await llm.pick("local")
        assert not lmstudio.set_aside() and await llm.local_available()
    asyncio.run(go())
    assert len(calls) == 1                                  # only the check after the block reached the local server
