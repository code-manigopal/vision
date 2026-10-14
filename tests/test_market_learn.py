"""Mani Market Tamil learns from its own views: views a day per kind and lesson topic group, and only where the owner's pattern leaves a choice. Fake records."""

import asyncio
import time

from vision.agents import Director, Master, Stage
from vision.bus import EventBus, Store
from vision.config import Config
from vision.masters import lessons, market_crew, youtube
from vision.services import oauth

DAY = 86400
NOW = time.time()
BY_GROUP = {}
for _t in lessons.TOPICS:
    BY_GROUP.setdefault(_t["group"], []).append(_t["id"])


def vid(kind, topic=None, views=1000, age=10, status="public", **kw):
    return {"channel": "manimarket", "kind": kind, "status": status, "topic": topic, "publish_at": NOW - age * DAY, "stats": {"view": views, "like": 0, "comment": 0}, **kw}


def test_views_a_day_count_only_public_videos_older_than_two_days():
    assert market_crew.views_per_day(vid("result", views=500, age=10), NOW) == 50
    assert market_crew.views_per_day(vid("result", age=1.5), NOW) is None
    assert market_crew.views_per_day(vid("result", status="scheduled"), NOW) is None
    assert market_crew.views_per_day({**vid("result"), "stats": {}}, NOW) is None
    assert market_crew.views_per_day({**vid("result", age=0), "publish_at": None, "uploaded": NOW - 5 * DAY, "stats": {"view": 100}}, NOW) == 20      # falls back to the upload time


def test_learn_averages_per_kind_and_per_lesson_group_and_names_the_top_kind_only_with_enough_videos():
    g = sorted(BY_GROUP)[:2]
    log = [vid("lesson", BY_GROUP[g[0]][0], views=1000, age=10), vid("lesson", BY_GROUP[g[0]][1], views=3000, age=10), vid("lesson_short", BY_GROUP[g[1]][0], views=100, age=10),
           vid("result", views=40, age=10), vid("result", status="scheduled")]
    ins = market_crew.learn(log, NOW)
    assert ins["kinds"]["lesson"] == {"videos": 2, "per_day": 200.0} and ins["kinds"]["result"]["videos"] == 1
    assert ins["groups"][g[0]]["per_day"] == 200.0 and ins["groups"][g[1]]["per_day"] == 10.0
    assert ins["top"] is None                                                    # no kind has 8 public videos yet
    ins = market_crew.learn(log + [vid("analysis", views=5000, age=10) for _ in range(8)], NOW)
    assert ins["top"] == {"kind": "analysis", "per_day": 500.0}


def order():
    return [(t, 0, []) for t in lessons.TOPICS]


def groups_first(o):
    return [x[0]["group"] for x in o]


def test_nothing_changes_before_eight_public_lessons():
    g = sorted(BY_GROUP)[1]
    ins = market_crew.learn([vid("lesson", BY_GROUP[g][0], views=99999) for _ in range(7)], NOW)
    assert market_crew.by_own_views(order(), ins, [], "lesson") == order() and market_crew.by_own_views(order(), None, [], "lesson") == order()


def test_the_group_with_more_views_a_day_goes_first_and_the_rest_still_get_a_share():
    gs = list(dict.fromkeys(groups_first(order())))
    best, other = gs[2], gs[0]
    log = [vid("lesson", BY_GROUP[best][0], views=30000)] + [vid("lesson", BY_GROUP[g][0], views=100) for g in gs[3:10]]         # eight public lessons, one group far ahead
    ins = market_crew.learn(log, NOW)
    got = market_crew.by_own_views(order(), ins, log, "lesson")
    assert groups_first(got)[0] == best and sorted(x[0]['id'] for x in got) == sorted(x[0]['id'] for x in order())
    assert [x[0]["id"] for x in got if x[0]["group"] == best] == [t["id"] for t, *_ in order() if t["group"] == best]       # inside a group the given order stands
    # once the best group has been told a lot more than its share, another group takes its turn (explore)
    told = [vid("lesson", BY_GROUP[best][0], status="scheduled") for _ in range(40)]
    assert groups_first(market_crew.by_own_views(order(), ins, log + told, "lesson"))[0] != best


def test_market_analytics_writes_the_insights_and_the_report_line_names_the_top_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")
    ch = youtube.channel({"id": "manimarket", "name": "Mani Market Tamil", "director": "MMT Director", "crew": "market"})
    store, bus = Store(tmp_path / "t.db"), EventBus()
    for n in range(8):
        store.kv_put(youtube.LOG, f"v{n}", vid("analysis", views=1000, age=10, video_id=f"id{n}", seconds=300, title=f"T{n}"))
    agent = market_crew.MarketAnalytics(ch)

    async def no_refresh(ctx, log):
        return None
    agent._refresh = no_refresh
    res = asyncio.run(agent.run({"store": store, "bus": bus, "cfg": Config(masters={})}))
    assert "best kind: analysis, 100 views a day" in res.summary and res.data["insights"]["top"]["kind"] == "analysis"
    assert store.kv_get(youtube.STATE, "manimarket:insights")["kinds"]["analysis"]["videos"] == 8
