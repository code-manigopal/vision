"""Investments (live, read-only).

SYNC (Zerodha · Fyers · Wealthsimple, in parallel) -> CONSOLIDATE (to CAD) ->
ANALYZE (allocation · risk · market watch · tax records) -> MARKET PULSE (indices · BTC) ->
Daily P&L Reporter (reporter): the day's P&L, the overall P&L against cost, the day's top gainers and
losers with the news on them, and a few ideas to consider.

A broker that isn't set up or needs a login never blocks the others: the brief uses what's available.
Nothing here can trade.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..agents import AgentResult, SubAgent
from ..config import ROOT
from ..services import fyers, markets, news
from ..services import wealthsimple as ws
from ..services import kite_mcp
from ..services.kite_mcp import KiteLoginNeeded, KiteMCP


def money(v: float, sym: str) -> str:
    sign = "+" if v >= 0 else "−"
    return f"{sign}{sym}{abs(v):,.0f}"


def pct(v: float | None) -> str:
    return "—" if v is None else f"{'+' if v >= 0 else '−'}{abs(v):.2f}%"


def short(sym: str) -> str:
    return (sym or "").split(":")[-1].replace("-EQ", "")


MOVERS = 3   # top gainers and top losers shown
MIN_WEIGHT = 1.0   # % of the portfolio a holding needs to be listed as a mover
GENERIC = {"class", "corp", "corporation", "company", "limited", "group", "holdings", "technologies", "trust", "fund", "index",
           "shares", "stock", "common", "international", "global", "systems", "industries"}


def telling(p: dict) -> str | None:
    """The word a headline would use for a holding: "Palantir" for "Palantir Technologies Inc (Class A)"."""
    return next((w for w in re.findall(r"[A-Za-z]+", p["name"]) if len(w) > 3 and w.lower() not in GENERIC), None)


JUNK_TITLE = re.compile(r"share price|stock price|quote (&|and) history|price prediction", re.I)   # quote pages and guesses, not news


def about(title: str, p: dict) -> bool:
    """A headline counts for a holding only if it names it: its ticker, or the first two telling words of its name
    ("Constellation Software", so a story about Constellation Energy does not count)."""
    t = title.lower()
    if JUNK_TITLE.search(t):
        return False
    name = [w.lower() for w in re.findall(r"[A-Za-z]+", p["name"]) if len(w) > 3 and w.lower() not in GENERIC][:2]
    if name and all(re.search(rf"\b{re.escape(w)}\b", t) for w in name):
        return True
    words = [p["symbol"].lower()]
    return any(re.search(rf"\b{re.escape(w)}\b", title.lower()) for w in words)


def flatten(accounts: list[dict], fx: dict) -> list[dict]:
    """Every holding in CAD: value, day change, cost and overall P&L where the broker gives a cost."""
    out = []
    for a in accounts:
        for p in a["positions"]:
            rate = fx.get(p.get("ccy") or a["ccy"], 1.0)
            value, day = p["value"] * rate, (p.get("day") or 0.0) * rate
            cost = p.get("book_cad") or (p.get("cost") or 0.0) * rate
            prev = value - day
            out.append({"symbol": short(p["symbol"]), "name": p.get("name") or short(p["symbol"]), "account": a["account"],
                        "india": ":" in (p["symbol"] or ""), "crypto": bool(p.get("crypto")), "value_cad": value, "day_cad": day,
                        "day_pct": p["pct"] if "pct" in p else (day / prev * 100 if prev else None),
                        "cost_cad": cost or None, "pnl_cad": value - cost if cost else None,
                        "pnl_pct": (value - cost) / cost * 100 if cost else None})
    return out


def rule_ideas(pf: dict, flags: list[str], drift: dict) -> list[dict]:
    """Plain observations from the numbers, used when no model answers."""
    out = [{"idea": f"Concentration: {f}. Consider not adding to it until the mix evens out.", "why": "risk flag"} for f in flags]
    for k, d in (drift or {}).items():
        if abs(d) >= 5:
            out.append({"idea": f"{k.upper() if len(k) <= 2 else k.title()} is {abs(d):.0f} points {'over' if d > 0 else 'under'} its target. New money could go "
                                f"{'elsewhere' if d > 0 else 'there'} first.", "why": "allocation drift"})
    for p in pf.get("losers", []):
        if p["day_pct"] <= -5 or (p.get("pnl_pct") or 0) <= -20:
            news_bit = f' Read "{p["news"][0]["title"]}" first.' if p.get("news") else ""
            out.append({"idea": f"{p['symbol']} is down {abs(p['day_pct']):.1f}% today"
                                + (f" and {abs(p['pnl_pct']):.0f}% below cost" if (p.get("pnl_pct") or 0) < 0 else "")
                                + f". Check whether the reason you hold it still stands.{news_bit}", "why": "top loser"})
    for p in pf.get("gainers", []):
        if (p.get("pnl_pct") or 0) >= 50 and p["weight"] >= 10:
            out.append({"idea": f"{p['symbol']} is {p['pnl_pct']:.0f}% above cost and {p['weight']:.0f}% of the portfolio. "
                                "Booking part of the gain is one option.", "why": "large winner"})
    return out[:3]


# ---------- SYNC ----------
class ZerodhaSync(SubAgent):
    name, tier, note, blocking = "Zerodha Sync", "MCP", "via Kite MCP", False

    def __init__(self, kite: KiteMCP, enabled: bool, port: int) -> None:
        super().__init__()
        self.kite, self.enabled, self.port = kite, enabled, port

    async def run(self, ctx):
        if not self.enabled:
            return AgentResult("idle", "OFF", "Zerodha sync off in config")
        try:
            acct = await self.kite.holdings()
        except KiteLoginNeeded as e:
            # always give a clickable button: the local route fetches a fresh Kite link on demand
            ctx["bus"].notice("kite", "Zerodha login needed for holdings (valid for the day)", f"http://127.0.0.1:{self.port}/auth/kite/login")
            return AgentResult("wait", "LOGIN", "Zerodha: waiting for your Kite login")
        ctx["bus"].clear_notice("kite")
        ctx.setdefault("accounts", []).append(acct)
        return AgentResult("done", "SYNCED", f"Zerodha {len(acct['positions'])} holdings", {"account": acct})


class FyersSync(SubAgent):
    name, tier, note, blocking = "Fyers Sync", "API", "via Fyers API v3", False

    def __init__(self, port: int) -> None:
        super().__init__()
        self.port = port

    async def run(self, ctx):
        if not fyers.configured():
            return AgentResult("idle", "NOT SET UP", "Fyers: add FYERS_APP_ID and FYERS_SECRET to .env")
        try:
            acct = await fyers.holdings_with_day_change()
        except fyers.FyersAuthError:
            ctx["bus"].notice("fyers", "Fyers login needed (tokens expire daily)", f"http://127.0.0.1:{self.port}/auth/fyers/login")
            return AgentResult("wait", "LOGIN", "Fyers: waiting for your login")
        ctx["bus"].clear_notice("fyers")
        ctx.setdefault("accounts", []).append(acct)
        return AgentResult("done", "SYNCED", f"Fyers {len(acct['positions'])} holdings", {"account": acct})


class WealthsimpleSync(SubAgent):
    name, tier, note, blocking = "Wealthsimple Sync", "CSV", "inbox/wealthsimple", False

    def __init__(self, folder, stale_days: int) -> None:
        super().__init__()
        self.folder, self.stale_days = folder, stale_days

    async def run(self, ctx):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = ws.latest_holdings_csv(self.folder)
        if not path:
            ctx["bus"].notice("wealthsimple", "Drop a Wealthsimple holdings CSV into inbox/wealthsimple")
            return AgentResult("wait", "NEEDS CSV", "Wealthsimple: no holdings CSV yet")
        h = ws.read_holdings(path)
        pos = h["positions"]
        # live prices between exports
        ysyms = {p["symbol"]: ws.yahoo_symbol(p) for p in pos if ws.yahoo_symbol(p)}
        stock_pct = await markets.stock_changes(sorted(set(ysyms.values())))
        cids = {p["symbol"]: markets.COINGECKO_IDS.get(p["symbol"]) for p in pos if p["crypto"]}
        cg = await markets.crypto(sorted({v for v in cids.values() if v})) if any(cids.values()) else {}
        for p in pos:
            if p["crypto"]:
                ch = (cg.get(cids.get(p["symbol"]) or "", {}) or {}).get("cad_24h_change")
            else:
                ch = stock_pct.get(ysyms.get(p["symbol"]))
            p["pct"] = ch
            p["day"] = p["value"] * ch / (100 + ch) if ch is not None else 0.0
        tfsa = [p for p in pos if not p["crypto"]]
        cry = [p for p in pos if p["crypto"]]
        accts = []
        if tfsa:
            accts.append({"account": "Wealthsimple TFSA", "ccy": "MIX", "positions": tfsa})
        if cry:
            accts.append({"account": "Wealthsimple Crypto", "ccy": "MIX", "positions": cry})
        ctx.setdefault("accounts", []).extend(accts)
        if h["age_days"] > self.stale_days:
            ctx["bus"].notice("wealthsimple", f"Wealthsimple CSV is {h['age_days']:.0f} days old; drop a fresh export")
            return AgentResult("wait", "CSV DUE", f"Wealthsimple: using {h['file']} ({h['age_days']:.0f}d old)", {"file": h["file"]})
        ctx["bus"].clear_notice("wealthsimple")
        return AgentResult("done", "SYNCED", f"Wealthsimple {len(pos)} positions", {"file": h["file"]})


# ---------- CONSOLIDATE ----------
class PortfolioAggregator(SubAgent):
    name, tier, note = "Portfolio Aggregator", "QUICK", "INR/USD → CAD"

    async def run(self, ctx):
        if not ctx.get("accounts"):
            ctx["portfolio"] = {"accounts": [], "total_cad": 0, "day_cad": 0, "day_pct": None, "fx": {}}
            return AgentResult("idle", "NO DATA", "No accounts synced yet")
        fx = await markets.fx_to_cad()
        positions = flatten(ctx["accounts"], fx)   # before the accounts below are restated in CAD
        order = ["Zerodha", "Fyers", "Wealthsimple TFSA", "Wealthsimple Crypto"]
        out = []
        for a in sorted(ctx.get("accounts", []), key=lambda x: order.index(x["account"]) if x["account"] in order else 9):
            if a["ccy"] == "MIX":  # Wealthsimple: per-position currency
                v = sum(p["value"] * fx.get(p["ccy"], 1.0) for p in a["positions"])
                d = sum(p["day"] * fx.get(p["ccy"], 1.0) for p in a["positions"])
                a.update(value_cad=v, day_cad=d, value=v, day=d, ccy="CAD")
            else:
                rate = fx.get(a["ccy"], 1.0)
                a.update(value_cad=a["value"] * rate, day_cad=a["day"] * rate)
            prev = a["value_cad"] - a["day_cad"]
            a["day_pct"] = a["day_cad"] / prev * 100 if prev else None
            out.append(a)
        total = sum(a["value_cad"] for a in out)
        day = sum(a["day_cad"] for a in out)
        for p in positions:
            p["weight"] = p["value_cad"] / total * 100 if total else 0.0
        costed = [p for p in positions if p["cost_cad"]]
        cost = sum(p["cost_cad"] for p in costed)
        pnl = sum(p["pnl_cad"] for p in costed)
        for a in out:   # each broker's own overall P&L, in its own currency like its day P&L
            mine = [p for p in costed if p["account"] == a["account"]]
            a_cost, a_pnl = sum(p["cost_cad"] for p in mine), sum(p["pnl_cad"] for p in mine)
            a["overall"] = {"pnl": a_pnl / (fx.get("INR") or 1.0 if a["ccy"] == "INR" else 1.0), "pnl_cad": a_pnl,
                            "pnl_pct": a_pnl / a_cost * 100} if a_cost else None
        # movers that matter: a holding under 1% of the portfolio can jump without changing anything
        big = [p for p in positions if p["day_pct"] and p["weight"] >= MIN_WEIGHT]
        moved = sorted(big or [p for p in positions if p["day_pct"]], key=lambda p: -p["day_pct"])
        ctx["portfolio"] = {"accounts": out, "total_cad": total, "day_cad": day,
                            "day_pct": day / (total - day) * 100 if total - day else None, "fx": fx,
                            "positions": positions,
                            # overall = what the holdings are worth against what they cost, for holdings with a known cost
                            "overall": {"pnl_cad": pnl, "cost_cad": cost, "pnl_pct": pnl / cost * 100,
                                        "of_portfolio": pnl / total * 100 if total else None} if cost else None,
                            "gainers": [p for p in moved if p["day_pct"] > 0][:MOVERS],
                            "losers": [p for p in reversed(moved) if p["day_pct"] < 0][:MOVERS]}
        if not out:
            return AgentResult("idle", "NO DATA", "No accounts synced yet")
        return AgentResult("done", "CONSOLIDATED", f"{len(out)} accounts · C${total:,.0f}", {"total_cad": total})


# ---------- ANALYZE ----------
def _bucket(a: dict, p: dict) -> str:
    if a["account"] in ("Zerodha", "Fyers"):
        return "india"
    if p.get("crypto"):
        return "crypto"
    return "us" if p.get("ccy") == "USD" else "canada"


class AllocationAnalyst(SubAgent):
    name, tier, note, blocking = "Allocation Analyst", "QUICK", "mix vs targets", False

    def __init__(self, targets: dict) -> None:
        super().__init__()
        self.targets = targets or {}

    async def run(self, ctx):
        pf = ctx.get("portfolio") or {}
        fx, total = pf.get("fx", {}), pf.get("total_cad") or 0
        if not total:
            return AgentResult("idle", "NO DATA", "Nothing to analyse yet")
        mix: dict[str, float] = {}
        for a in pf["accounts"]:
            for p in a["positions"]:
                rate = fx.get(p.get("ccy", a["ccy"]), 1.0) if a["account"].startswith("Wealthsimple") else fx.get(a["ccy"], 1.0)
                mix[_bucket(a, p)] = mix.get(_bucket(a, p), 0) + p["value"] * rate
        mix_pct = {k: v / total * 100 for k, v in mix.items()}
        ctx["mix"] = mix_pct
        if not self.targets:
            return AgentResult("done", "NO TARGET", " · ".join(f"{k} {v:.0f}%" for k, v in sorted(mix_pct.items())), {"mix": mix_pct})
        drift = ctx["drift"] = {k: mix_pct.get(k, 0) - t for k, t in self.targets.items()}
        off = {k: d for k, d in drift.items() if abs(d) >= 5}
        label = "ON TARGET" if not off else f"DRIFT {len(off)}"
        return AgentResult("done", label, ", ".join(f"{k} {d:+.0f}pp" for k, d in off.items()) or "within 5pp of targets",
                           {"mix": mix_pct, "drift": drift})


class RiskMonitor(SubAgent):
    name, tier, note, blocking = "Risk Monitor", "QUICK", "concentration · drawdown", False

    async def run(self, ctx):
        pf = ctx.get("portfolio") or {}
        total = pf.get("total_cad") or 0
        if not total:
            return AgentResult("idle", "NO DATA", "Nothing to check yet")
        flags, fx = [], pf["fx"]
        biggest = max(((p["symbol"], p["value"] * fx.get(p.get("ccy", a["ccy"]), 1.0)) for a in pf["accounts"] for p in a["positions"]),
                      key=lambda x: x[1], default=None)
        if biggest and biggest[1] / total > 0.25:
            flags.append(f"{biggest[0]} is {biggest[1] / total:.0%} of portfolio")
        if (ctx.get("mix") or {}).get("crypto", 0) > 30:
            flags.append(f"crypto {ctx['mix']['crypto']:.0f}%")
        if (pf.get("day_pct") or 0) < -3:
            flags.append(f"down {pf['day_pct']:.1f}% in a day")
        ctx["flags"] = flags
        return AgentResult("done", f"{len(flags)} FLAGS" if flags else "OK", "; ".join(flags) or "no risk flags", {"flags": flags})


class MarketWatcher(SubAgent):
    name, tier, note, blocking = "Market Watcher", "API", "news on your movers", False

    async def run(self, ctx):
        pf = ctx.get("portfolio") or {}
        # the day's movers first: their news is what explains the P&L; with no movers, the largest holdings
        picks = pf.get("gainers", []) + pf.get("losers", [])
        if not picks:
            picks = sorted(pf.get("positions", []), key=lambda p: -p["value_cad"])[:3]
        stories = []
        for p in picks:
            try:
                items = await news.gather(f'"{telling(p) or p["symbol"]}" {"price" if p["crypto"] else "stock"}', "IN" if p["india"] else "US", max_age_hours=24, limit=8)
            except Exception:
                items = []
            items = [i for i in items if about(i["title"], p)][:2]   # a search also returns stories that only sit near the name
            p["news"] = [{"title": i["title"], "source": i["source"], "link": i["link"]} for i in items]
            stories += [{"symbol": p["symbol"], **i} for i in items]
        return AgentResult("done", f"{len(stories)} STORIES", stories[0]["title"] if stories else "no news on your movers", {"stories": stories})


class TaxRecordsKeeper(SubAgent):
    name, tier, note, blocking = "Tax & Records Keeper", "QUICK", "TFSA · T1135 · snapshots", False

    async def run(self, ctx):
        pf = ctx.get("portfolio") or {}
        if not pf.get("accounts"):
            return AgentResult("idle", "NO DATA", "Nothing to record yet")
        store = ctx["store"]
        rate = pf["fx"].get("INR", 0)
        india_cost = sum(p.get("cost", 0) for a in pf["accounts"] if a["account"] in ("Zerodha", "Fyers") for p in a["positions"]) * rate
        import json as _json
        with store._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS portfolio_snapshots (ts REAL, account TEXT, value_cad REAL, day_cad REAL)")
            c.executemany("INSERT INTO portfolio_snapshots VALUES (?,?,?,?)",
                          [(time.time(), a["account"], a["value_cad"], a["day_cad"]) for a in pf["accounts"]])
        notes = ["TFSA gains tax-free; US dividends lose 15% withholding"]
        if india_cost > 100_000:
            notes.insert(0, f"Indian holdings cost ≈ C${india_cost:,.0f}: over C$100k, T1135 filing likely needed")
        return AgentResult("done", "RECORDED", notes[0], {"notes": notes, "india_cost_cad": india_cost})


# ---------- MARKET PULSE ----------
class IndexTracker(SubAgent):
    name, tier, note, blocking = "Index Tracker", "API", "NIFTY · BANKNIFTY · IT · NYSE · NDQ", False

    async def run(self, ctx):
        ctx["indices"] = await markets.indices()
        nifty = ctx["indices"][0]
        return AgentResult("done", "CLOSED", f"NIFTY {pct(nifty['pct'])}", {"indices": ctx["indices"]})


class BitcoinTracker(SubAgent):
    name, tier, note, blocking = "Bitcoin Tracker", "API", "CoinGecko", False

    async def run(self, ctx):
        d = (await markets.crypto(["bitcoin"])).get("bitcoin", {})
        ctx["btc"] = {"usd": d.get("usd"), "cad": d.get("cad"), "pct": d.get("usd_24h_change")}
        return AgentResult("done", "LIVE", f"BTC ${d.get('usd', 0):,.0f} ({pct(d.get('usd_24h_change'))})", {"btc": ctx["btc"]})


# ---------- REPORT ----------
class DailyPnLReporter(SubAgent):
    name, tier, note = "Daily P&L Reporter", "QUICK", "day + overall P&L, movers, ideas → VISION"

    def __init__(self, ideas_tier: str = "local", ideas_timeout: float = 45) -> None:
        super().__init__()
        self.ideas_tier, self.ideas_timeout = ideas_tier, ideas_timeout

    async def ideas(self, ctx, pf: dict) -> tuple[list[dict], str]:
        """Up to three things to consider, from the model when one answers, else from plain rules.
        Read-only desk: these are options to weigh, never orders, and nothing here can trade."""
        flags, drift = ctx.get("flags") or [], ctx.get("drift") or {}
        llm = ctx.get("llm")
        if llm and (pf.get("gainers") or pf.get("losers") or flags):
            row = lambda p: {"holding": p["symbol"], "day_pct": round(p["day_pct"], 2), "share_of_portfolio_pct": round(p["weight"], 1),
                             "vs_cost_pct": None if p.get("pnl_pct") is None else round(p["pnl_pct"], 1),
                             "news": [n["title"] for n in p.get("news", [])]}
            facts = {"overall_vs_cost_pct": (pf.get("overall") or {}).get("pnl_pct"), "day_pct": pf.get("day_pct"),
                     "gainers": [row(p) for p in pf.get("gainers", [])], "losers": [row(p) for p in pf.get("losers", [])],
                     "risk_flags": flags, "drift_vs_targets_pp": drift}
            try:
                # capped: a slow local model must not hold up the report (or the boot roll call); the rules answer instead
                res = await asyncio.wait_for(llm.json(
                    "You help a long-term investor read their own portfolio. From these facts only, give at most 3 things "
                    "they could consider doing, most important first. Return a list of {idea, why}: idea is one plain sentence "
                    "(under 30 words) naming the holding; why is the fact or headline behind it (under 15 words). Phrase each as "
                    "an option to weigh (hold, add, trim, review, wait for results), never an order. No price targets, no "
                    "predictions, no promised returns, no quantities. If a headline does not explain a move, say the cause is "
                    "unclear. If nothing calls for action, return one idea saying so.\n" + str(facts),
                    tier=self.ideas_tier, max_tokens=1500), self.ideas_timeout)
                out = [{"idea": str(r["idea"]).strip()[:260], "why": str(r.get("why") or "").strip()[:140]}
                       for r in (res or []) if isinstance(r, dict) and r.get("idea")][:3]
                if out:
                    return out, "model"
            except Exception:
                pass
        return rule_ideas(pf, flags, drift), "rules"

    async def run(self, ctx):
        pf = ctx.get("portfolio") or {}
        ports = []
        for a in pf.get("accounts", []):
            sym = "₹" if a["ccy"] == "INR" else "C$"
            ports.append({"name": a["account"], "value": a["day"], "pct": a.get("day_pct"), "sym": sym})
        if pf.get("accounts"):
            ports.append({"name": "Total (CAD)", "value": pf["day_cad"], "pct": pf.get("day_pct"), "sym": "C$", "total": True})
        mkts = [{"name": i["name"], "pct": i["pct"]} for i in ctx.get("indices", [])]
        if ctx.get("btc"):
            mkts.append({"name": "Bitcoin (24h)", "pct": ctx["btc"]["pct"]})
        parts = []
        overall, gainers, losers = pf.get("overall"), pf.get("gainers", []), pf.get("losers", [])
        # overall P&L broker by broker (worth against cost), then the total in CAD
        overall_ports = [{"name": a["account"], "value": a["overall"]["pnl"], "pct": a["overall"]["pnl_pct"],
                          "sym": "₹" if a["ccy"] == "INR" else "C$"} for a in pf.get("accounts", []) if a.get("overall")]
        if overall:
            overall_ports.append({"name": "Total (CAD)", "value": overall["pnl_cad"], "pct": overall["pnl_pct"], "sym": "C$", "total": True})
        ideas, ideas_by = await self.ideas(ctx, pf) if pf.get("accounts") else ([], "rules")
        if pf.get("accounts"):
            parts.append(f"Portfolio {money(pf['day_cad'], 'C$')} ({pct(pf.get('day_pct'))})")
            if overall:
                parts.append("Overall " + ", ".join(f"{o['name'].replace('Wealthsimple ', 'WS ')} {money(o['value'], o['sym'])} ({pct(o['pct'])})"
                                                    for o in overall_ports))
            if gainers:
                parts.append(f"Top gainer {gainers[0]['symbol']} {pct(gainers[0]['day_pct'])}")
            if losers:
                parts.append(f"Top loser {losers[0]['symbol']} {pct(losers[0]['day_pct'])}")
            parts += [f"{a['account'].replace('Wealthsimple ', 'WS ')} {money(a['day'], '₹' if a['ccy'] == 'INR' else 'C$')}"
                      for a in pf["accounts"]]
        else:
            parts.append("No accounts synced yet")
        for i in ctx.get("indices", [])[:1] + ctx.get("indices", [])[4:5]:
            parts.append(f"{i['name'].split()[0]} {pct(i['pct'])}")
        if ctx.get("btc"):
            parts.append(f"BTC {pct(ctx['btc']['pct'])}")
        waiting = [k for k in ("kite", "fyers", "wealthsimple") if k in ctx["bus"].state.get("notices", {})]
        if waiting:
            parts.append("waiting on: " + ", ".join(waiting))
        if ideas:
            parts.append("Consider: " + ideas[0]["idea"])
        keep = ("symbol", "name", "account", "day_pct", "day_cad", "weight", "pnl_cad", "pnl_pct", "news")
        mover = lambda p: {k: p.get(k) for k in keep}
        return AgentResult("done", "SENT", " · ".join(parts),
                           {"ports": ports, "mkts": mkts, "total_cad": pf.get("total_cad"), "overall": overall, "overall_ports": overall_ports,
                            "gainers": [mover(p) for p in gainers], "losers": [mover(p) for p in losers],
                            "ideas": ideas, "ideas_by": ideas_by})


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    port = cfg.vision.port if cfg else 8765
    brokers = options.get("brokers") or {}
    inbox = ROOT / options.get("wealthsimple_inbox", "inbox/wealthsimple")
    kite = kite_mcp.shared()
    return {
        "Zerodha Sync": ZerodhaSync(kite, brokers.get("zerodha", True), port),
        "Fyers Sync": FyersSync(port),
        "Wealthsimple Sync": WealthsimpleSync(inbox, int(options.get("csv_stale_days", 7))),
        "Portfolio Aggregator": PortfolioAggregator(),
        "Allocation Analyst": AllocationAnalyst(options.get("targets") or {}),
        "Risk Monitor": RiskMonitor(),
        "Market Watcher": MarketWatcher(),
        "Tax & Records Keeper": TaxRecordsKeeper(),
        "Index Tracker": IndexTracker(),
        "Bitcoin Tracker": BitcoinTracker(),
        "Daily P&L Reporter": DailyPnLReporter(options.get("ideas_tier", "local"), float(options.get("ideas_timeout", 45))),
    }
