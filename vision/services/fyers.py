"""Fyers API v3 (free for Fyers account holders).

Login: VISION opens Fyers' login page; Fyers redirects back to
    http://127.0.0.1:8765/auth/fyers/callback
which must be set as the Redirect URL of your app at myapi.fyers.in.
Access tokens last about a day. With FYERS_PIN in .env, VISION renews them using the
refresh token (valid ~15 days) so you log in far less often.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..config import ROOT, secret

BASE = "https://api-t1.fyers.in"
TOKENS = ROOT / "data" / "tokens.json"


class FyersAuthError(Exception):
    """Token missing or expired: you need to log in (VISION sends you the link)."""


def _tokens() -> dict:
    try:
        return json.loads(TOKENS.read_text()).get("fyers", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(fy: dict) -> None:
    TOKENS.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(TOKENS.read_text()) if TOKENS.exists() else {}
    data["fyers"] = fy
    TOKENS.write_text(json.dumps(data))
    TOKENS.chmod(0o600)


def configured() -> bool:
    return bool(secret("FYERS_APP_ID") and secret("FYERS_SECRET"))


def redirect_uri(port: int) -> str:
    return secret("FYERS_REDIRECT_URI") or f"http://127.0.0.1:{port}/auth/fyers/callback"


def login_url(port: int) -> str:
    q = {"client_id": secret("FYERS_APP_ID"), "redirect_uri": redirect_uri(port), "response_type": "code", "state": "vision"}
    return f"{BASE}/api/v3/generate-authcode?{urlencode(q)}"


def _app_hash() -> str:
    return hashlib.sha256(f"{secret('FYERS_APP_ID')}:{secret('FYERS_SECRET')}".encode()).hexdigest()


async def exchange_code(auth_code: str, client: httpx.AsyncClient | None = None) -> None:
    async with (client or httpx.AsyncClient(timeout=15)) as c:
        r = await c.post(f"{BASE}/api/v3/validate-authcode",
                         json={"grant_type": "authorization_code", "appIdHash": _app_hash(), "code": auth_code})
    d = r.json()
    if d.get("s") != "ok" or not d.get("access_token"):
        raise FyersAuthError(d.get("message", "Fyers login failed"))
    _save({"access_token": d["access_token"], "refresh_token": d.get("refresh_token"), "at": time.time()})


async def _refresh(c: httpx.AsyncClient) -> str | None:
    tok, pin = _tokens(), secret("FYERS_PIN")
    if not (tok.get("refresh_token") and pin):
        return None
    r = await c.post(f"{BASE}/api/v3/validate-refresh-token",
                     json={"grant_type": "refresh_token", "appIdHash": _app_hash(), "refresh_token": tok["refresh_token"], "pin": pin})
    d = r.json()
    if d.get("s") != "ok" or not d.get("access_token"):
        return None
    _save({**tok, "access_token": d["access_token"], "at": time.time()})
    return d["access_token"]


def _token_error(d: dict) -> bool:
    msg = str(d.get("message", "")).lower()
    return d.get("code") in (-8, -15, -16, -17) or "token" in msg or "authenticate" in msg


async def _get(c: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    tok = _tokens().get("access_token")
    if not tok:
        tok = await _refresh(c)
        if not tok:
            raise FyersAuthError("Fyers login needed")
    for attempt in (1, 2):
        r = await c.get(f"{BASE}{path}", params=params, headers={"Authorization": f"{secret('FYERS_APP_ID')}:{tok}"})
        d = r.json()
        if d.get("s") == "ok":
            return d
        if _token_error(d) and attempt == 1:
            tok = await _refresh(c)
            if tok:
                continue
            raise FyersAuthError("Fyers session expired")
        raise RuntimeError(d.get("message", f"Fyers error on {path}"))
    raise FyersAuthError("Fyers session expired")


async def holdings_with_day_change(client: httpx.AsyncClient | None = None) -> dict:
    async with (client or httpx.AsyncClient(timeout=20)) as c:
        h = await _get(c, "/api/v3/holdings")
        rows = h.get("holdings") or []
        syms = [x["symbol"] for x in rows if x.get("symbol")]
        changes: dict[str, float] = {}
        for i in range(0, len(syms), 50):  # quotes take up to 50 symbols per call
            q = await _get(c, "/data/quotes", {"symbols": ",".join(syms[i:i + 50])})
            for item in q.get("d") or []:
                changes[item.get("n")] = (item.get("v") or {}).get("ch") or 0.0
    positions, value, day = [], 0.0, 0.0
    for x in rows:
        qty = x.get("quantity") or x.get("remainingQuantity") or 0
        ltp = x.get("ltp") or 0.0
        mv = x.get("marketVal") or qty * ltp
        d = qty * changes.get(x.get("symbol"), 0.0)
        value += mv
        day += d
        positions.append({"symbol": x.get("symbol"), "qty": qty, "value": mv, "day": d, "cost": x.get("costPrice", 0) * qty})
    return {"account": "Fyers", "ccy": "INR", "value": value, "day": day, "positions": positions}
