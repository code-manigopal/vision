"""Zerodha holdings via the free hosted Kite MCP server (https://mcp.kite.trade/mcp).

How login works: the login is tied to one MCP session. VISION keeps that session open in the
background; when Zerodha asks for a login, VISION sends you the link (dashboard + Telegram).
You open it, log in to Kite, and from then on holdings flow until the session expires (daily).
The hosted server is read-only for trading: it cannot place orders.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

log = logging.getLogger("vision.kite")
KITE_URL = "https://mcp.kite.trade/mcp"
LOGIN_RE = re.compile(r"https://(?:kite\.zerodha\.com|kite\.trade)[^\s)\"'<>\]]+")
ANY_URL = re.compile(r"https://[^\s)\"'<>\]]+")


class KiteLoginNeeded(Exception):
    def __init__(self, url: str | None):
        super().__init__("Zerodha login needed")
        self.url = url


def _text(result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in (getattr(result, "content", None) or []))


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
        return json.loads(m.group(1)) if m else None


_shared: "KiteMCP | None" = None


def shared() -> "KiteMCP":
    """One Kite session for the whole app: the login is tied to it, so the server routes reuse it."""
    global _shared
    if _shared is None:
        _shared = KiteMCP()
    return _shared


class KiteMCP:
    """One long-lived MCP session, driven by a background task (MCP sessions must open and close in one task)."""

    def __init__(self, url: str = KITE_URL, session_factory=None) -> None:
        self.url = url
        self._factory = session_factory or self._default_factory
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    @staticmethod
    def _default_factory(url: str):
        from contextlib import asynccontextmanager

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        @asynccontextmanager
        async def open_session():
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    yield s
        return open_session()

    async def _runner(self) -> None:
        while True:
            try:
                async with self._factory(self.url) as session:
                    while True:
                        tool, args, fut = await self._queue.get()
                        if fut.done():  # caller already gave up (timeout)
                            continue
                        try:
                            res = await session.call_tool(tool, args or {})
                            if not fut.done():
                                fut.set_result(res)
                        except Exception as e:
                            if not fut.done():
                                fut.set_exception(e)
                            raise  # reopen the session
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Kite MCP session dropped: %s (reconnecting)", e)
                await asyncio.sleep(5)

    async def call(self, tool: str, args: dict | None = None, timeout: float = 25) -> Any:
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._runner())
        fut = asyncio.get_running_loop().create_future()
        await self._queue.put((tool, args, fut))
        return await asyncio.wait_for(fut, timeout)

    async def _holdings_data(self) -> Any:
        """Raw holdings, or None while this session isn't logged in."""
        res = await self.call("get_holdings")
        text = _text(res)
        data = None if getattr(res, "isError", False) else _parse_json(text)
        if data is None or (isinstance(data, dict) and not data.get("data") and "login" in text.lower()):
            return None
        return data

    async def logged_in(self) -> bool:
        return await self._holdings_data() is not None

    async def holdings(self) -> dict:
        data = await self._holdings_data()
        if data is None:
            url, _ = await self.login_url()
            raise KiteLoginNeeded(url)
        rows = data.get("data", data) if isinstance(data, dict) else data
        positions, value, day = [], 0.0, 0.0
        for x in rows or []:
            qty = (x.get("quantity") or 0) + (x.get("t1_quantity") or 0)
            ltp = x.get("last_price") or 0.0
            close = x.get("close_price") or ltp
            d = x["day_change"] * qty if x.get("day_change") is not None else (ltp - close) * qty
            mv = qty * ltp
            value += mv
            day += d
            positions.append({"symbol": f"{x.get('exchange', 'NSE')}:{x.get('tradingsymbol')}", "qty": qty, "value": mv,
                              "day": d, "cost": (x.get("average_price") or 0) * qty})
        return {"account": "Zerodha", "ccy": "INR", "value": value, "day": day, "positions": positions}

    async def login_url(self) -> tuple[str | None, str]:
        """Ask the MCP server for a fresh Kite login link. Returns (url, raw text)."""
        text = _text(await self.call("login"))
        m = LOGIN_RE.search(text) or ANY_URL.search(text)
        return (m.group(0) if m else None), text

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
