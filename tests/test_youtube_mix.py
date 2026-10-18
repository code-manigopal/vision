"""Mani, 2026-10-18: daily two Shorts of science, one story, one finance; the Analytics Manager reads YouTube Analytics and
re-splits the slots weekly by how each category is watched, at least one each."""
import asyncio
import time

import httpx

from vision.agents import AgentResult
from vision.bus import EventBus, Store
from vision.masters import youtube
from vision.services import oauth, yt_analytics

MIX = {"science": 2, "story": 1, "money": 1}


def test_categories_and_which_slot_comes_next():
    assert [youtube.category(k) for k in ("science", "money", "real", "viewer", "classic", "original", "motivational", None)] == \
        ["science", "money", "story", "story", "story", "story", "story", "story"]
    order, made = [], {}
    while (c := youtube.next_category(MIX, made)):
        order.append(c)
        made[c] = made.get(c, 0) + 1
    assert order == ["science", "science", "story", "money"] and youtube.mix_text(MIX) == "2 science / 1 story / 1 finance"


def test_mix_comes_from_the_weekly_resplit_else_the_setting(tmp_path):
    store = Store(tmp_path / "t.db")
    ch = youtube.channel({"daily_mix": MIX})
    assert youtube.mix_of(store, ch) == MIX and youtube.mix_of(store, youtube.channel({})) == {}
    store.kv_put(youtube.STATE, "confessions:mix", {"mix": {"science": 1, "story": 1, "money": 2}, "at": time.time()})
    assert youtube.mix_of(store, ch) == {"science": 1, "story": 1, "money": 2}
    assert youtube.mix_of(store, youtube.channel({"daily_mix": MIX, "mix_auto": False})) == MIX


def test_resplit_keeps_the_total_and_one_each():
    s = lambda score, n=6: {"n": n, "score": score, "views": 0, "pct": 0, "subs": 0}
    assert youtube.resplit(MIX, {"science": s(200), "story": s(20), "money": s(20)}, 6) == {"science": 2, "story": 1, "money": 1}
    assert youtube.resplit(MIX, {"science": s(50), "story": s(20), "money": s(300)}, 6) == {"science": 1, "story": 1, "money": 2}
    assert youtube.resplit(MIX, {"science": s(50), "story": s(20), "money": s(300, n=3)}, 6) == {"science": 2, "story": 1, "money": 1}  # finance not measured enough: keeps its slot
    assert youtube.resplit(MIX, {"science": s(50)}, 6) == MIX                                       # one measured category: nothing to compare


def test_category_scores_use_share_watched_and_subscribers():
    now = time.time()
    v = lambda kind, views, pct, subs=0, age=5: {"status": "public", "kind": kind, "publish_at": now - age * 86400,
                                                 "analytics": {"views": views, "avg_pct": pct, "subs": subs}}
    log = [v("science", 900, 44), v("science", 400, 75, subs=2), v("real", 100, 40), v("money", 30, 50), v("money", 999, 90, age=1),   # too fresh
           v("classic", 500, 50, age=40)]                                                                                         # too old
    sc = youtube.category_scores(log, 28, now)
    assert sc["science"] == {"n": 2, "views": 650, "pct": 59.5, "subs": 2, "score": round((396 + 300 + 100) / 2, 1)}
    assert sc["story"]["n"] == 1 and sc["money"] == {"n": 1, "views": 30, "pct": 50.0, "subs": 0, "score": 15.0}


def test_the_scout_fills_the_open_slot(tmp_path, monkeypatch):
    store, bus = Store(tmp_path / "t.db"), EventBus()
    ch = youtube.channel({"daily_mix": MIX, "originals": True, "trends": False})
    scout = youtube.StoryScout(ch)
    wanted = []

    async def original(self, ctx, want=None):
        wanted.append(want)
        ctx["job"] = {"source": {"title": "t"}, "genre": want}
        return {"title": f"a {want} one"}

    async def nothing(*a, **k):
        return []

    monkeypatch.setattr(youtube.StoryScout, "_original", original)
    monkeypatch.setattr(youtube.StoryScout, "_from_drive", nothing)
    monkeypatch.setattr(youtube.StoryScout, "_from_comments", nothing)
    monkeypatch.setattr(youtube.StoryScout, "_classic", lambda self, ctx, long=False: asyncio.sleep(0, None))
    monkeypatch.setattr(youtube.StoryScout, "_inbox", lambda self: [])
    monkeypatch.setattr(youtube.reddit, "configured", lambda: False)
    made = lambda kind, n: [store.kv_put(youtube.LOG, f"{kind}{i}", {"channel": "confessions", "kind": kind, "made": time.time(), "status": "public", "title": kind, "seconds": 9})
                            for i in range(n)]
    res = asyncio.run(scout._short({"store": store, "bus": bus}))
    assert wanted == ["science"] and res.data["category"] == "science"
    made("science", 2)
    asyncio.run(scout._short({"store": store, "bus": bus}))
    assert wanted[-1] == "confession"                                          # the story slot: no real story or classic, so an original confession
    made("original", 1)
    asyncio.run(scout._short({"store": store, "bus": bus}))
    assert wanted[-1] == "money"
    made("money", 1)
    res = asyncio.run(scout.run({"store": store, "bus": bus}))
    assert res.label == "QUOTA MET" and "4 of 4" in res.summary and "2 science / 1 story / 1 finance" in res.summary


def test_analytics_are_read_scored_and_the_mix_resplit_once_a_week(tmp_path, monkeypatch):
    store, bus = Store(tmp_path / "t.db"), EventBus()
    old = time.time() - 5 * 86400
    kinds = ["science"] * 6 + ["real"] * 6 + ["money"] * 6
    for i, k in enumerate(kinds):
        store.kv_put(youtube.LOG, f"v{i}", {"channel": "confessions", "kind": k, "status": "public", "video_id": f"id{i}", "made": old, "uploaded": old,
                                            "publish_at": old, "title": f"{k} {i}", "seconds": 60})
    stats = {"science": (200, 70), "real": (30, 40), "money": (900, 80)}

    def handler(req):
        u = str(req.url)
        if "youtube/v3/videos" in u:
            return httpx.Response(200, json={"items": [{"id": i, "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "1"}} for i in req.url.params["id"].split(",")]})
        if u.startswith(yt_analytics.API):
            if "engagedViews" in req.url.params["metrics"]:
                return httpx.Response(400, json={"error": {"message": "Unknown metric"}})
            ids = req.url.params["filters"].split("==")[1].split(",")
            rows = [[i, *stats[kinds[int(i[2:])]], 30, 0, 1, 0] for i in ids]
            return httpx.Response(200, json={"columnHeaders": [{"name": n} for n in ["video", "views", "averageViewPercentage", "averageViewDuration", "subscribersGained", "likes", "shares"]], "rows": rows})
        return httpx.Response(404)

    async def token(account, provider, client=None):
        return "tok"

    monkeypatch.setattr(oauth, "access_token", token)
    ch = youtube.channel({"daily_mix": MIX})
    am = lambda: youtube.AnalyticsManager(ch, client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    sent = []
    q = bus.subscribe()

    monkeypatch.setattr(oauth, "granted", lambda account: "https://www.googleapis.com/auth/youtube.force-ssl")   # an older sign-in
    res = asyncio.run(am().run({"store": store, "bus": bus}))
    assert "youtube-analytics-confessions" in bus.state["notices"] and "analytics wait for a sign-in" in res.summary

    monkeypatch.setattr(oauth, "granted", lambda account: "youtube.force-ssl yt-analytics.readonly")
    res = asyncio.run(am().run({"store": store, "bus": bus}))
    assert "youtube-analytics-confessions" not in bus.state["notices"]
    assert store.kv_get(youtube.LOG, "v0")["analytics"]["avg_pct"] == 70.0
    assert youtube.mix_of(store, ch) == {"science": 1, "story": 1, "money": 2}                   # finance is watched best
    assert "daily mix 1 science / 1 story / 2 finance" in res.summary and "watched: finance 80.0% of 900 views/Short" in res.summary
    while not q.empty():
        e = q.get_nowait()
        if e.get("type") == "reminder":
            sent.append(e["text"])
    assert len(sent) == 1 and "the daily mix is now 1 science / 1 story / 2 finance (was 2 science / 1 story / 1 finance)" in sent[0]

    stats["science"] = (5000, 90)                                                                    # within the week: no new re-split
    store.kv_put(youtube.STATE, "confessions:analytics_at", {"at": 0})
    asyncio.run(am().run({"store": store, "bus": bus}))
    assert youtube.mix_of(store, ch) == {"science": 1, "story": 1, "money": 2}


def test_latest_is_the_last_made_not_the_last_saved(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    for k, made in (("new", 200), ("old", 100)):                 # "old" saved last
        store.kv_put(youtube.LOG, k, {"channel": "confessions", "kind": "real", "status": "ready", "made": made, "title": k, "seconds": 9})
    res = asyncio.run(youtube.AnalyticsManager(youtube.channel({})).run({"store": store, "bus": EventBus()}))
    assert "latest “new”" in res.summary
