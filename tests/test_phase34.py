import asyncio
import json
import time
from email.utils import formatdate
from types import SimpleNamespace

import httpx
import pytest

from vision.bus import EventBus, Store
from vision.config import Config, MasterConfig
from vision.masters import build_masters
from vision.services import fyers, markets, news, weather
from vision.services import kite_mcp

NOW = formatdate(time.time())
OLD = formatdate(time.time() - 5 * 86400)


def rss(items):
    body = "".join(f"<item><title>{t} - {s}</title><link>https://x/{i}</link><pubDate>{d}</pubDate><source url='https://s'>{s}</source></item>"
                   for i, (t, s, d) in enumerate(items))
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>Google News</title>{body}</channel></rss>"


def router(req: httpx.Request) -> httpx.Response:
    host, path, q = req.url.host, req.url.path, str(req.url.params)
    if host == "news.google.com":
        if "cricket" in q:
            return httpx.Response(200, text=rss([("India win series", "ESPNcricinfo", NOW)]))
        if "Sensex" in q:
            return httpx.Response(200, text=rss([("Sensex rises 300 points", "Mint", NOW), ("Sensex rises 300 points", "ET", NOW),
                                                 ("Old story", "ET", OLD)]))
        if "politics" in q:
            return httpx.Response(500)
        return httpx.Response(200, text=rss([("Stocks edge higher", "Reuters", NOW)]))
    if host == "geocoding-api.open-meteo.com":
        return httpx.Response(200, json={"results": [
            {"name": "Leamington", "latitude": 52.3, "longitude": -1.5, "admin1": "England", "country_code": "GB"},
            {"name": "Leamington", "latitude": 42.05, "longitude": -82.6, "admin1": "Ontario", "country_code": "CA"}]})
    if host == "api.open-meteo.com":
        assert req.url.params["latitude"] == "42.05"
        return httpx.Response(200, json={"current": {"temperature_2m": 21.6, "weather_code": 3, "relative_humidity_2m": 70, "wind_speed_10m": 9},
                                         "daily": {"time": ["2026-09-30", "2026-10-01"], "weather_code": [3, 63],
                                                   "temperature_2m_max": [22.4, 18.6], "temperature_2m_min": [14.1, 11.0],
                                                   "precipitation_probability_max": [10, 80]}})
    if host == "query1.finance.yahoo.com":
        base = {"^NSEI": 25000, "^NSEBANK": 52000, "^CNXIT": 36000, "^NYA": 19000, "^IXIC": 18000, "VFV.TO": 140, "AAPL": 220}[path.rsplit("/", 1)[-1]]
        return httpx.Response(200, json={"chart": {"result": [{"meta": {"regularMarketPrice": base * 1.01, "currency": "X"},
                                                                "indicators": {"quote": [{"close": [base * 0.99, base, base * 1.01]}]}}]}})
    if host == "api.coingecko.com":
        return httpx.Response(200, json={"bitcoin": {"usd": 60000, "cad": 82000, "usd_24h_change": -1.35, "cad_24h_change": -1.2}})
    if host == "www.bankofcanada.ca":
        return httpx.Response(200, json={"observations": [{"FXUSDCAD": {"v": "1.37"}, "FXINRCAD": {"v": "0.0164"}}]})
    if host == "api-t1.fyers.in":
        if path.endswith("/holdings"):
            return httpx.Response(200, json={"s": "ok", "holdings": [{"symbol": "NSE:TCS-EQ", "quantity": 10, "ltp": 4000, "marketVal": 40000, "costPrice": 3500}]})
        if path.endswith("/quotes"):
            return httpx.Response(200, json={"s": "ok", "d": [{"n": "NSE:TCS-EQ", "v": {"ch": -42.0}}]})
    return httpx.Response(404)


@pytest.fixture
def mocked(monkeypatch):
    real = httpx.AsyncClient
    factory = lambda **kw: real(transport=httpx.MockTransport(router))
    for mod in (news, weather, markets, fyers):
        monkeypatch.setattr(mod.httpx, "AsyncClient", factory)


def test_wmo_mapping():
    assert weather.wmo(0) == ("sun", "clear")
    assert weather.wmo(63) == ("rain", "rain")
    assert weather.wmo(95) == ("storm", "thunderstorms")


def test_news_gather_dedups_and_drops_old(mocked):
    items = asyncio.run(news.gather("Sensex OR Nifty", "IN"))
    assert [i["title"] for i in items] == ["Sensex rises 300 points"]
    assert items[0]["source"] in ("Mint", "ET")


def test_news_master_live(mocked, tmp_path):
    cfg = Config(masters={"news": MasterConfig(mode="live")})
    m = next(x for x in build_masters(cfg) if x.id == "news")
    bus = EventBus()
    report = asyncio.run(m.cycle(bus, Store(tmp_path / "t.db")))
    agents = {a["name"]: a for a in bus.state["masters"]["news"]["agents"]}
    assert agents["Political News"]["status"] == "error"       # feed down...
    assert agents["News Summarizer"]["status"] == "done"       # ...but the brief still goes out
    data = bus.state["report_data"]["news"]
    tags = [h["tag"] for h in data["headlines"]]
    assert tags == ["INDIA MKT", "GLOBAL", "CRICKET", "WEATHER"]
    assert data["weather"]["temp"] == 22 and data["weather"]["daily"][1]["kind"] == "rain"
    assert report.startswith("3 desks updated · Leamington 22°C cloudy")


def write_ws_csv(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "holdings-report.csv").write_text(
        "Account Name,Account Type,Symbol,Exchange,Name,Security Type,Quantity,Market Price,Market Value,Market Value Currency,Book Value (CAD)\n"
        "TFSA,TFSA,VFV,TSX,Vanguard S&P 500,ETF,100,140,\"14,000.00\",CAD,12000\n"
        "TFSA,TFSA,AAPL,NASDAQ,Apple,EQUITY,10,220,2200,USD,2600\n"
        "Crypto,Crypto,BTC,,Bitcoin,CRYPTOCURRENCY,0.05,82000,4100,CAD,3000\n")


class FakeSession:
    def __init__(self, logged_in=True):
        self.logged_in = logged_in

    async def call_tool(self, name, args):
        txt = lambda s: SimpleNamespace(content=[SimpleNamespace(text=s)], isError=False)
        if name == "login":
            return txt("Please log in: https://kite.zerodha.com/connect/login?api_key=kitemcp&v=3&redirect_params=session_id%3Dabc")
        if not self.logged_in:
            return txt("You are not logged in. Please call the login tool first.")
        return txt(json.dumps([{"tradingsymbol": "INFY", "exchange": "NSE", "quantity": 20, "t1_quantity": 0, "last_price": 1500,
                                "close_price": 1490, "average_price": 1300, "day_change": 10}]))


def fake_factory(session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def cm():
        yield session
    return lambda url: cm()


def invest_master(monkeypatch, tmp_path, logged_in=True, fyers_on=False):
    write_ws_csv(tmp_path / "inbox")
    monkeypatch.setattr(kite_mcp.KiteMCP, "_default_factory", staticmethod(fake_factory(FakeSession(logged_in))))
    kite_mcp._shared = None   # fresh session per test
    monkeypatch.setattr(fyers, "TOKENS", tmp_path / "tokens.json")
    if fyers_on:
        monkeypatch.setenv("FYERS_APP_ID", "APP-100")
        monkeypatch.setenv("FYERS_SECRET", "s")
        (tmp_path / "tokens.json").write_text(json.dumps({"fyers": {"access_token": "tok"}}))
    else:
        monkeypatch.delenv("FYERS_APP_ID", raising=False)
    import vision.masters.invest as inv
    monkeypatch.setattr(inv, "ROOT", tmp_path)
    cfg = Config(masters={"invest": MasterConfig(mode="live", options={"wealthsimple_inbox": "inbox", "targets": {"india": 40, "us": 40, "crypto": 20}})})
    return next(x for x in build_masters(cfg) if x.id == "invest")


def test_invest_master_end_to_end(mocked, monkeypatch, tmp_path):
    m = invest_master(monkeypatch, tmp_path, fyers_on=True)
    bus = EventBus()
    report = asyncio.run(m.cycle(bus, Store(tmp_path / "t.db")))
    st = {a["name"]: a for a in bus.state["masters"]["invest"]["agents"]}
    assert st["Zerodha Sync"]["status"] == "done" and st["Fyers Sync"]["status"] == "done"
    assert st["Wealthsimple Sync"]["status"] == "done"
    data = bus.state["report_data"]["invest"]
    names = [p["name"] for p in data["ports"]]
    assert names == ["Zerodha", "Fyers", "Wealthsimple TFSA", "Wealthsimple Crypto", "Total (CAD)"]
    z = data["ports"][0]
    assert z["value"] == 200 and z["sym"] == "₹"                # 20 shares x +₹10 day change
    assert data["ports"][1]["value"] == -420                    # Fyers: 10 x −₹42
    assert [x["name"] for x in data["mkts"]][-1] == "Bitcoin (24h)"
    assert report.startswith("Portfolio ") and "NIFTY +1.00%" in report and "BTC −1.35%" in report
    assert "ALLOC" not in report


def test_invest_partial_setup_never_blocks(mocked, monkeypatch, tmp_path):
    m = invest_master(monkeypatch, tmp_path, logged_in=False, fyers_on=False)
    bus = EventBus()
    report = asyncio.run(m.cycle(bus, Store(tmp_path / "t.db")))
    st = {a["name"]: a for a in bus.state["masters"]["invest"]["agents"]}
    assert st["Zerodha Sync"]["label"] == "LOGIN"
    assert st["Fyers Sync"]["label"] == "NOT SET UP"
    assert bus.state["notices"]["kite"]["url"].endswith("/auth/kite/login")
    assert st["Daily P&L Reporter"]["status"] == "done"
    assert "WS TFSA" in report and "waiting on: kite" in report


def test_fyers_expired_token_asks_for_login(monkeypatch, tmp_path):
    monkeypatch.setattr(fyers, "TOKENS", tmp_path / "tokens.json")
    monkeypatch.setenv("FYERS_APP_ID", "APP-100")
    monkeypatch.setenv("FYERS_SECRET", "s")
    monkeypatch.delenv("FYERS_PIN", raising=False)
    (tmp_path / "tokens.json").write_text(json.dumps({"fyers": {"access_token": "old"}}))
    real = httpx.AsyncClient
    expired = lambda req: httpx.Response(200, json={"s": "error", "code": -16, "message": "Could not authenticate the user"})
    monkeypatch.setattr(fyers.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(expired)))
    with pytest.raises(fyers.FyersAuthError):
        asyncio.run(fyers.holdings_with_day_change())
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fauth%2Ffyers%2Fcallback" in fyers.login_url(8765)
