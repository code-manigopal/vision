"""News Desk (live): 5 gatherers in parallel -> News Summarizer (reporter).

Sources and searches are set in config.yaml -> masters.news.options.
"""

from __future__ import annotations

from typing import Any

from ..agents import AgentResult, SubAgent
from ..services import news, weather

DEFAULT_TOPICS = {
    "india_markets": {"query": "Sensex OR Nifty OR \"Indian stock market\"", "edition": "IN"},
    "global_markets": {"query": "\"stock market\" OR \"Wall Street\" OR \"Federal Reserve\"", "edition": "US"},
    "cricket": {"query": "cricket", "edition": "IN"},
    "politics": {"query": "Canada politics OR India politics", "edition": "CA"},
}


class Gatherer(SubAgent):
    tier = "API"
    blocking = False  # one bad feed never stops the brief

    def __init__(self, name: str, topic: str, tag: str, cfg: dict, extra: list[str], max_age: float) -> None:
        super().__init__(name=name, note="RSS · many outlets")
        self.topic, self.tag, self.cfg, self.extra, self.max_age = topic, tag, cfg, extra, max_age

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        items = await news.gather(self.cfg.get("query"), self.cfg.get("edition", "CA"), self.extra, max_age_hours=self.max_age)
        ctx.setdefault("news", {})[self.topic] = items
        if not items:
            return AgentResult("done", "QUIET", f"{self.tag}: nothing new", {"items": []})
        return AgentResult("done", f"{len(items)} NEW", f"{self.tag}: {items[0]['title']}", {"items": items})


class WeatherAgent(SubAgent):
    name, tier, note = "Weather Agent", "API", "Open-Meteo"
    blocking = False

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        w = await weather.forecast(self.opts["city"], self.opts["tz"], self.opts.get("lat"), self.opts.get("lon"))
        ctx["weather"] = w
        today = w["daily"][0] if w["daily"] else {}
        line = f"{w['city']} {w['temp']}°C, {w['words']}" + (f" · high {today['hi']}°" if today else "")
        return AgentResult("done", f"{w['temp']}°C", line, {"weather": w})


class NewsSummarizer(SubAgent):
    name, tier, note = "News Summarizer", "LOCAL", "top item per desk"

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        n = ctx.get("news", {})
        tags = [("india_markets", "INDIA MKT"), ("global_markets", "GLOBAL"), ("cricket", "CRICKET"), ("politics", "POLITICS")]
        headlines, parts = [], []
        for topic, tag in tags:
            items = n.get(topic) or []
            if items:
                top = items[0]
                headlines.append({"tag": tag, "text": top["title"], "source": top["source"], "link": top["link"]})
                parts.append(f"{tag.title()}: {top['title']}")
        w = ctx.get("weather")
        if w:
            headlines.append({"tag": "WEATHER", "text": f"{w['city']} · {w['temp']}°C · {w['words']}", "source": "Open-Meteo", "link": ""})
        if not headlines:
            return AgentResult("done", "QUIET", "No fresh headlines", {"headlines": []})
        summary = f"{len(parts)} desks updated" + (f" · {w['city']} {w['temp']}°C {w['words']}" if w else "")
        return AgentResult("done", f"{len(headlines)} ITEMS", summary,
                           {"headlines": headlines, "weather": w, "detail": parts})


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    topics = {**DEFAULT_TOPICS, **(options.get("topics") or {})}
    extra = options.get("extra_feeds") or {}
    age = float(options.get("max_age_hours", 30))
    home = (cfg.vision.home_city if cfg else "Leamington, ON")
    tz = (cfg.vision.timezone if cfg else "America/Toronto")
    w = options.get("weather") or {}
    return {
        "Indian Market News": Gatherer("Indian Market News", "india_markets", "India", topics["india_markets"], extra.get("india_markets", []), age),
        "Global Market News": Gatherer("Global Market News", "global_markets", "Global", topics["global_markets"], extra.get("global_markets", []), age),
        "Cricket News": Gatherer("Cricket News", "cricket", "Cricket", topics["cricket"], extra.get("cricket", []), age),
        "Political News": Gatherer("Political News", "politics", "Politics", topics["politics"], extra.get("politics", []), age),
        "Weather Agent": WeatherAgent(city=w.get("city", home), tz=tz, lat=w.get("lat"), lon=w.get("lon")),
        "News Summarizer": NewsSummarizer(),
    }
