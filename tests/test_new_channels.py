"""Mani, 2026-10-19: three new English channels (Cosmic Roadster = space, Know Body Things = body and mind, Camping on Satellites =
geography) on the same crew as Know IDK Things, which stays as it was."""
import asyncio
import time

from vision.bus import Store
from vision.masters import youtube


def test_kinds_and_categories_leave_know_idk_things_as_it_was():
    assert [youtube.category(k) for k in ("science", "money", "real", "original", "classic", "motivational")] == ["science", "money", "story", "story", "story", "story"]
    assert [youtube.category(k) for k in ("space", "body", "geography")] == ["space", "body", "geography"]
    assert youtube.kind({"original": True, "genre": "body", "source": {}}) == "body"
    assert youtube.next_category({"space": 2}, {"space": 1}) == "space" and youtube.next_category({"space": 2}, {"space": 2}) is None
    for g in ("space", "body", "geography"):
        assert g in youtube.GENRE_ASK and g in youtube.GENRE_WRITE and sum(len(v) for v in youtube.BANKS[g].values()) >= 45
    assert "health advice" in youtube.GENRE_WRITE["body"][1] and "No politics" in youtube.GENRE_WRITE["geography"][1]


def test_a_subject_another_channel_told_lately_is_skipped(tmp_path):
    store = Store(tmp_path / "t.db")
    store.kv_put(youtube.LOG, "a", {"channel": "knowidk", "title": "Why the Moon Shows Us Only One Face", "made": time.time()})
    others = youtube.others_recent(store, {"id": "cosmicroadster"})
    assert youtube.told_elsewhere("why the Moon always shows us the same face", others)
    assert not youtube.told_elsewhere("Europa's hidden ocean", others)
    assert youtube.others_recent(store, {"id": "knowidk"}) == []                    # its own titles never count


def test_a_channel_with_its_own_writer_model_uses_it_for_writing_only():
    seen = []

    class LLM:
        async def json(self, prompt, **kw):
            seen.append(kw.get("model"))
            return {}

    w = youtube.OwnWriter(LLM(), "openai/gpt-oss-20b")
    asyncio.run(w.json("x", tier="writer"))
    asyncio.run(w.json("x", tier="local"))
    asyncio.run(w.json("x", tier="writer", model="qwen/qwen3.8-27b"))
    assert seen == ["openai/gpt-oss-20b", None, "qwen/qwen3.8-27b"]


def test_build_gives_new_channels_their_own_director_and_keeps_the_lead():
    from vision.config import Config
    ag = youtube.build_agents({"channels": [{}, {"id": "cosmicroadster", "name": "Cosmic Roadster", "director": "Cosmic Roadster Director",
                                                  "writer_model": "openai/gpt-oss-20b"}]}, Config())
    assert isinstance(ag["Know IDK Things Director"], youtube.Lead) and isinstance(ag["Cosmic Roadster Director"], youtube.ChannelDirector)


def test_groq_budget_stops_before_the_free_limit_and_at_a_channels_share():
    from vision.services import groq_budget
    groq_budget.record("openai/gpt-oss-20b", 100_000, "cosmicroadster")
    assert groq_budget.why_not("openai/gpt-oss-20b", 15_000, "cosmicroadster", cap=60_000)                 # past its own share
    assert not groq_budget.why_not("openai/gpt-oss-20b", 15_000, "knowbodythings", cap=60_000)
    groq_budget.record("openai/gpt-oss-20b", 80_000, "knowbodythings")
    assert "nearly used" in groq_budget.why_not("openai/gpt-oss-20b", 15_000, "knowbodythings", cap=0)     # 95 % of the model's day
    assert not groq_budget.why_not("openai/gpt-oss-120b", 15_000)                                          # every model has its own day


def test_light_steps_go_local_first_and_fall_back_to_groq():
    calls = []

    class LLM:
        def __init__(self, up):
            self.up = up

        async def local_available(self):
            return self.up

        async def json(self, prompt, **kw):
            calls.append((kw.get("tier"), kw.get("model"), kw.get("who")))
            return ["a"] if kw.get("tier") == "local" and self.up else ["g"]

    w = youtube.OwnWriter(LLM(True), "openai/gpt-oss-20b", "cosmicroadster", 60_000, "local")
    assert asyncio.run(w.json("x", tier="writer", light=True)) == ["a"] and calls[-1][0] == "local"
    w = youtube.OwnWriter(LLM(False), "openai/gpt-oss-20b", "cosmicroadster", 60_000, "local")
    assert asyncio.run(w.json("x", tier="writer", light=True)) == ["g"] and calls[-1] == ("writer", "openai/gpt-oss-20b", "cosmicroadster")
    assert asyncio.run(w.json("x", tier="writer")) == ["g"]                    # a script is never sent to the local model
