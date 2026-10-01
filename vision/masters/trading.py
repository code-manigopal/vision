"""Trading Desk (live): Analysts (market, sentiment, news, macro) -> Bull vs Bear -> Research Manager ->
Trader -> Risk debate -> Portfolio Manager (reporter) -> YOU -> OANDA Executor -> Reflection.

Safety rails:
- Nothing trades without your approval (dashboard or Telegram).
- Practice account by default (OANDA_ENV=practice). Live needs OANDA_ENV=live AND
  masters.trading.options.live_trading: true.
- An approval expires after 30 min, and is refused if price moved more than half an ATR since.
- Units are capped by max_units; risk per trade by risk_pct.
Without an AI model, the desk falls back to plain indicator rules (labelled as such).
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..agents import AgentResult, SubAgent, request_approval
from ..config import ROOT, secret
from ..services import news
from ..services.llm import LLMUnavailable

RATINGS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}


def oanda() -> tuple[str, dict, str] | None:
    tok, acct = secret("OANDA_API_TOKEN"), secret("OANDA_ACCOUNT_ID")
    if not (tok and acct):
        return None
    base = "https://api-fxtrade.oanda.com" if (secret("OANDA_ENV") or "practice") == "live" else "https://api-fxpractice.oanda.com"
    return base, {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}, acct


def indicators(candles: list[dict]) -> dict:
    c = [float(x["mid"]["c"]) for x in candles if x.get("complete", True)]
    hi = [float(x["mid"]["h"]) for x in candles if x.get("complete", True)]
    lo = [float(x["mid"]["l"]) for x in candles if x.get("complete", True)]
    sma = lambda n: sum(c[-n:]) / n if len(c) >= n else c[-1]
    gains = [max(0, c[i] - c[i - 1]) for i in range(len(c) - 14, len(c))]
    losses = [max(0, c[i - 1] - c[i]) for i in range(len(c) - 14, len(c))]
    rs = (sum(gains) / 14) / ((sum(losses) / 14) or 1e-9)
    trs = [max(hi[i] - lo[i], abs(hi[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(len(c) - 14, len(c))]
    return {"price": c[-1], "sma20": sma(20), "sma50": sma(50), "rsi": 100 - 100 / (1 + rs), "atr": sum(trs) / 14,
            "chg5": (c[-1] / c[-31] - 1) * 100 if len(c) > 31 else 0.0}


def rule_rating(ind: dict) -> str:
    up = ind["sma20"] > ind["sma50"]
    if up and ind["rsi"] < 65:
        return "Overweight"
    if not up and ind["rsi"] > 35:
        return "Underweight"
    return "Hold"


async def ask(ctx, prompt: str, tier: str = "local", tokens: int = 350) -> str | None:
    llm = ctx.get("llm")
    if not llm:
        return None
    try:
        return await llm.complete(prompt, system="You are part of a disciplined FX research desk. Be concise and specific. No hype.", tier=tier, max_tokens=tokens)
    except LLMUnavailable:
        return None


# ---------- analysts ----------
class MarketAnalyst(SubAgent):
    name, tier, note = "Market Analyst", "QUICK", "H4 trend · RSI · ATR"

    async def run(self, ctx):
        evt = ctx.setdefault("desk_evt", asyncio.Event())
        try:
            return await self._run(ctx)
        finally:
            evt.set()  # the other analysts in this stage wait for the market data

    async def _run(self, ctx):
        o = oanda()
        if not o:
            return AgentResult("idle", "NOT SET UP", "Trading: add OANDA_API_TOKEN and OANDA_ACCOUNT_ID (practice) to .env")
        base, h, acct = o
        ctx["desk"] = {}
        async with httpx.AsyncClient(timeout=20) as c:
            for inst in ctx["options"].get("instruments", ["EUR_USD"]):
                r = await c.get(f"{base}/v3/instruments/{inst}/candles", headers=h, params={"granularity": ctx["options"].get("granularity", "H4"), "count": 200, "price": "M"})
                r.raise_for_status()
                ind = indicators(r.json()["candles"])
                text = await ask(ctx, f"{inst} H4: price {ind['price']:.5f}, SMA20 {ind['sma20']:.5f}, SMA50 {ind['sma50']:.5f}, RSI {ind['rsi']:.0f}, ATR {ind['atr']:.5f}, 5-day change {ind['chg5']:.2f}%. Two-sentence technical read.")
                ctx["desk"][inst] = {"ind": ind, "market": text or f"Trend {'up' if ind['sma20'] > ind['sma50'] else 'down'}, RSI {ind['rsi']:.0f} (rules)"}
            acc = await c.get(f"{base}/v3/accounts/{acct}/summary", headers=h)
            ctx["equity"] = float(acc.json()["account"]["NAV"]) if acc.status_code == 200 else 0.0
        return AgentResult("done", "ANALYZED", " · ".join(f"{k}: {v['market'][:70]}" for k, v in ctx["desk"].items()))


class _HeadlineAnalyst(SubAgent):
    blocking = False
    query = ""
    question = ""

    async def run(self, ctx):
        try:
            await asyncio.wait_for(ctx.setdefault("desk_evt", asyncio.Event()).wait(), 90)
        except asyncio.TimeoutError:
            pass
        if not ctx.get("desk"):
            return AgentResult("idle", "WAITING", "waiting on market data")
        for inst, d in ctx["desk"].items():
            pair = inst.replace("_", "/")
            items = await news.gather(self.query.format(pair=pair, base=inst[:3], quote=inst[4:]), "US", max_age_hours=36, limit=6)
            heads = "; ".join(i["title"] for i in items) or "no fresh headlines"
            d[self.key] = await ask(ctx, f"{self.question} for {pair}. Headlines: {heads}") or f"{len(items)} headlines (no AI read)"
        return AgentResult("done", "READ", " · ".join(f"{k}: {v[self.key][:60]}" for k, v in ctx["desk"].items()))


class SentimentAnalyst(_HeadlineAnalyst):
    name, tier, note, key = "Sentiment Analyst", "QUICK", "positioning from headlines", "sentiment"
    query, question = '"{pair}" OR "{base} {quote}" forex', "In one sentence, is market sentiment bullish, bearish or mixed"


class NewsAnalyst(_HeadlineAnalyst):
    name, tier, note, key = "News Analyst", "QUICK", "event risk", "news"
    query, question = '"{pair}" OR "{base}" currency news', "In one sentence, what news could move price in the next day"


class MacroAnalyst(_HeadlineAnalyst):
    name, tier, note, key = "Macro Analyst", "QUICK", "central banks · rates", "macro"
    query, question = "Federal Reserve OR ECB OR \"Bank of Canada\" interest rates", "In one sentence, what's the macro bias"


# ---------- research debate ----------
class _Researcher(SubAgent):
    side = ""

    async def run(self, ctx):
        if not ctx.get("desk"):
            return AgentResult("idle", "WAITING", "waiting on analysts")
        for inst, d in ctx["desk"].items():
            brief = {k: d.get(k) for k in ("market", "sentiment", "news", "macro")}
            d[self.side] = await ask(ctx, f"Make the strongest honest {self.side} case for {inst} over the next 1-3 days in 3 sentences, using only: {brief}") or "(no AI: rules only)"
        return AgentResult("done", "ARGUED", f"{self.side} case made")


class BullResearcher(_Researcher):
    name, tier, note, side = "Bull Researcher", "QUICK", "long case", "bull"


class BearResearcher(_Researcher):
    name, tier, note, side = "Bear Researcher", "QUICK", "short case", "bear"


class ResearchManager(SubAgent):
    name, tier, note = "Research Manager", "DEEP", "judges the debate"

    async def run(self, ctx):
        if not ctx.get("desk"):
            return AgentResult("idle", "WAITING", "waiting on research")
        for inst, d in ctx["desk"].items():
            txt = await ask(ctx, f"Judge this debate for {inst}. Bull: {d.get('bull')} Bear: {d.get('bear')} Technicals: {d['market']}. "
                                 f"Answer with one word from {list(RATINGS)} then a one-sentence reason.", tier="cloud", tokens=120)
            rating = next((r for r in RATINGS if txt and txt.strip().lower().startswith(r.lower())), None)
            d["rating"], d["reason"] = (rating, txt) if rating else (rule_rating(d["ind"]), "indicator rules (no AI verdict)")
        return AgentResult("done", " · ".join(d["rating"].upper() for d in ctx["desk"].values()), " · ".join(f"{k}: {d['rating']}" for k, d in ctx["desk"].items()))


class Trader(SubAgent):
    name, tier, note = "Trader", "QUICK", "entry · stop · target · size"

    async def run(self, ctx):
        opts = ctx["options"]
        for inst, d in (ctx.get("desk") or {}).items():
            ind = d["ind"]
            stop_dist = 1.5 * ind["atr"]
            risk_cash = ctx.get("equity", 0) * float(opts.get("risk_pct", 0.5)) / 100
            units = min(int(opts.get("max_units", 1000)), int(risk_cash / stop_dist) if stop_dist else 0)
            d["plan"] = {"units": units, "stop_dist": stop_dist, "tp_dist": 2 * ind["atr"]}
        return AgentResult("done", "PLANNED", " · ".join(f"{k}: max {d['plan']['units']} units" for k, d in (ctx.get("desk") or {}).items()) or "no plan")


class _Risk(SubAgent):
    stance, lo, hi = "", 0.5, 1.0

    async def run(self, ctx):
        for inst, d in (ctx.get("desk") or {}).items():
            txt = await ask(ctx, f"As the {self.stance} risk officer, give a position-size multiplier between {self.lo} and {self.hi} for a {d['rating']} call on {inst} "
                                 f"(RSI {d['ind']['rsi']:.0f}, news: {d.get('news')}). Reply with the number first, then why.", tokens=80)
            try:
                mult = float(txt.split()[0].strip(",:")) if txt else (self.lo + self.hi) / 2
            except ValueError:
                mult = (self.lo + self.hi) / 2
            d.setdefault("risk", {})[self.stance] = max(self.lo, min(self.hi, mult))
        return AgentResult("done", "SIZED", f"{self.stance} view in")


class AggressiveRisk(_Risk):
    name, tier, note, stance, lo, hi = "Aggressive Risk", "QUICK", "size up", "aggressive", 0.8, 1.5


class ConservativeRisk(_Risk):
    name, tier, note, stance, lo, hi = "Conservative Risk", "QUICK", "size down", "conservative", 0.2, 0.6


class NeutralRisk(_Risk):
    name, tier, note, stance, lo, hi = "Neutral Risk", "QUICK", "balance", "neutral", 0.5, 1.0


class PortfolioManager(SubAgent):
    name, tier, note = "Portfolio Manager", "DEEP", "final call → your OK"

    async def run(self, ctx):
        desk = ctx.get("desk") or {}
        if not desk:
            prev = ctx["results"].get("Market Analyst")
            return AgentResult("idle", "NO DATA", prev.summary if prev else "No market data")
        calls, waiting = [], 0
        for inst, d in desk.items():
            r = d.get("risk", {})
            mult = 0.25 * r.get("aggressive", 1) + 0.45 * r.get("neutral", 0.75) + 0.30 * r.get("conservative", 0.4)
            units = int(d["plan"]["units"] * abs(RATINGS[d["rating"]]) * mult)
            side = 1 if RATINGS[d["rating"]] > 0 else -1
            if units < int(ctx["options"].get("min_units", 100)) or RATINGS[d["rating"]] == 0:
                calls.append(f"{inst.replace('_', '/')}: {d['rating']}, no trade")
                continue
            price = d["ind"]["price"]
            stop = price - side * d["plan"]["stop_dist"]
            tp = price + side * d["plan"]["tp_dist"]
            request_approval(ctx, self.name, f"{'Buy' if side > 0 else 'Sell'} {units:,} {inst.replace('_', '/')} @ ~{price:.5f} · stop {stop:.5f} · target {tp:.5f} ({d['rating']})",
                             {"key": f"trade:{inst}:{datetime.now():%Y%m%d%H}", "kind": "trade", "instrument": inst, "units": side * units,
                              "price": price, "stop": round(stop, 5), "tp": round(tp, 5), "atr": d["ind"]["atr"], "created": time.time(),
                              "rating": d["rating"], "reason": d.get("reason", "")})
            calls.append(f"{inst.replace('_', '/')}: {d['rating']} → {'buy' if side > 0 else 'sell'} {units:,}, waiting for you")
            waiting += 1
        return AgentResult("wait" if waiting else "done", f"{waiting} WAITING" if waiting else "NO TRADE", " · ".join(calls),
                           {"calls": [{"instrument": k, "rating": d["rating"], "reason": d.get("reason", "")} for k, d in desk.items()]})


class OandaExecutor(SubAgent):
    name, tier, note, blocking = "OANDA Executor", "API", "only after your approval", False

    async def run(self, ctx):
        o = oanda()
        if not o:
            return AgentResult("idle", "NOT SET UP", "OANDA not connected")
        base, h, acct = o
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{base}/v3/accounts/{acct}/openTrades", headers=h)
        n = len(r.json().get("trades", [])) if r.status_code == 200 else 0
        env = (secret("OANDA_ENV") or "practice").upper()
        return AgentResult("done", f"{n} OPEN", f"{n} open trades ({env})")


class Reflection(SubAgent):
    name, tier, note, blocking = "Reflection", "QUICK", "lessons 5 days later", False

    async def run(self, ctx):
        o, store = oanda(), ctx["store"]
        due = [t for t in store.kv_list("trades") if not t.get("reflected") and time.time() - t.get("at", 0) > 5 * 86400]
        if not o or not due:
            return AgentResult("idle", "5D LATER", f"{len(due)} trades due for review")
        base, h, acct = o
        path = ROOT / "vault" / "trading" / "lessons.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=15) as c:
            for t in due:
                r = await c.get(f"{base}/v3/accounts/{acct}/trades/{t['trade_id']}", headers=h)
                tr = r.json().get("trade", {}) if r.status_code == 200 else {}
                pl = tr.get("realizedPL") or tr.get("unrealizedPL") or "?"
                lesson = await ask(ctx, f"Trade {t['instrument']} {t['units']} units, rating {t['rating']}, reason: {t['reason']}. Result P/L {pl}. One-line lesson.") or f"Result {pl}."
                with path.open("a") as f:
                    f.write(f"- {datetime.now():%Y-%m-%d} {t['instrument']} {t['units']} ({t['rating']}): P/L {pl}. {lesson.strip()}\n")
                t["reflected"] = True
                store.kv_put("trades", t.pop("_key"), {k: v for k, v in t.items() if k != "_ts"})
        return AgentResult("done", f"{len(due)} REVIEWED", f"{len(due)} lessons written")


async def approve_trade(row: dict, decision: str, ctx: dict) -> str:
    p, opts = row["payload"], ctx["cfg"].master("trading").options
    if decision != "approved":
        return "not traded"
    o = oanda()
    if not o:
        return "OANDA not connected"
    base, h, acct = o
    if (secret("OANDA_ENV") or "practice") == "live" and not opts.get("live_trading"):
        return "refused: live trading is off (set masters.trading.options.live_trading: true)"
    if time.time() - p["created"] > int(opts.get("approval_ttl_min", 30)) * 60:
        return "refused: approval expired, wait for the next call"
    async with httpx.AsyncClient(timeout=15) as c:
        pr = (await c.get(f"{base}/v3/accounts/{acct}/pricing", headers=h, params={"instruments": p["instrument"]})).json()["prices"][0]
        mid = (float(pr["bids"][0]["price"]) + float(pr["asks"][0]["price"])) / 2
        if abs(mid - p["price"]) > 0.5 * p["atr"]:
            return f"refused: price moved too far ({mid:.5f} vs {p['price']:.5f})"
        r = await c.post(f"{base}/v3/accounts/{acct}/orders", headers=h, json={"order": {
            "type": "MARKET", "instrument": p["instrument"], "units": str(int(p["units"])), "timeInForce": "FOK",
            "stopLossOnFill": {"price": f"{p['stop']:.5f}"}, "takeProfitOnFill": {"price": f"{p['tp']:.5f}"}}})
    d = r.json()
    fill = d.get("orderFillTransaction")
    if not fill:
        return "order not filled: " + str(d.get("orderCancelTransaction", {}).get("reason") or d.get("errorMessage", "unknown"))
    trade_id = (fill.get("tradeOpened") or {}).get("tradeID", fill["id"])
    ctx["store"].kv_put("trades", trade_id, {"trade_id": trade_id, "instrument": p["instrument"], "units": p["units"], "rating": p["rating"],
                                             "reason": p["reason"], "price": fill.get("price"), "at": time.time()})
    return f"filled {p['units']} {p['instrument']} @ {fill.get('price')}"


APPROVAL_HANDLERS = {"trade": approve_trade}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Market Analyst": MarketAnalyst(), "Sentiment Analyst": SentimentAnalyst(), "News Analyst": NewsAnalyst(), "Macro Analyst": MacroAnalyst(),
            "Bull Researcher": BullResearcher(), "Bear Researcher": BearResearcher(), "Research Manager": ResearchManager(), "Trader": Trader(),
            "Aggressive Risk": AggressiveRisk(), "Conservative Risk": ConservativeRisk(), "Neutral Risk": NeutralRisk(),
            "Portfolio Manager": PortfolioManager(), "OANDA Executor": OandaExecutor(), "Reflection": Reflection()}
