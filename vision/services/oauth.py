"""OAuth sign-in for Google (Gmail + Calendar) and Microsoft (Outlook mail + calendar).

You sign in once per account in the browser; VISION keeps the refresh token in data/tokens.json
(readable only by you) and renews access tokens itself.

Setup (once):
- Google: console.cloud.google.com -> new project -> enable Gmail API + Google Calendar API ->
  OAuth consent screen (External, add yourself as test user) -> Credentials -> OAuth client ID ->
  "Web application" with redirect URI  http://127.0.0.1:8765/auth/google/callback
  -> GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env
- Microsoft: entra.microsoft.com -> App registrations -> New -> "Personal Microsoft accounts and
  organizational" -> redirect (Web) http://127.0.0.1:8765/auth/microsoft/callback -> Certificates &
  secrets -> new client secret -> MS_CLIENT_ID / MS_CLIENT_SECRET in .env
"""

from __future__ import annotations

import json
import secrets as pysecrets
import time
from urllib.parse import urlencode

import httpx

from ..config import ROOT, secret

TOKENS = ROOT / "data" / "tokens.json"

PROVIDERS = {
    "google": {
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send",
                   "https://www.googleapis.com/auth/calendar.events", "openid", "email"],
        "id": "GOOGLE_CLIENT_ID", "secret": "GOOGLE_CLIENT_SECRET",
        "extra": {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    },
    "youtube": {      # the same Google app as above (enable "YouTube Data API v3" on it); a separate sign-in per channel
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
                   "https://www.googleapis.com/auth/youtube.force-ssl",    # playlists, reading and posting comments
                   "https://www.googleapis.com/auth/drive.readonly"],      # Drive: the folder stories are dropped into
        "id": "GOOGLE_CLIENT_ID", "secret": "GOOGLE_CLIENT_SECRET",
        "extra": {"access_type": "offline", "prompt": "consent"},
    },
    "microsoft": {
        "auth": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["offline_access", "User.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite"],
        "id": "MS_CLIENT_ID", "secret": "MS_CLIENT_SECRET",
        "extra": {"response_mode": "query", "prompt": "select_account"},
    },
}

_pending_state: dict[str, tuple[str, str]] = {}  # state -> (provider, account)


class AuthNeeded(Exception):
    def __init__(self, account: str, provider: str):
        super().__init__(f"{provider} sign-in needed for {account}")
        self.account, self.provider = account, provider


def _all() -> dict:
    try:
        return json.loads(TOKENS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(account: str, tok: dict) -> None:
    TOKENS.parent.mkdir(parents=True, exist_ok=True)
    data = _all()
    data.setdefault("oauth", {})[account] = tok
    TOKENS.write_text(json.dumps(data))
    TOKENS.chmod(0o600)


def configured(provider: str) -> bool:
    p = PROVIDERS[provider]
    return bool(secret(p["id"]) and secret(p["secret"]))


def redirect_uri(provider: str, port: int) -> str:
    return f"http://127.0.0.1:{port}/auth/{provider}/callback"


def login_url(provider: str, account: str, port: int) -> str:
    p = PROVIDERS[provider]
    state = pysecrets.token_urlsafe(16)
    _pending_state[state] = (provider, account)
    q = {"client_id": secret(p["id"]), "redirect_uri": redirect_uri(provider, port), "response_type": "code",
         "scope": " ".join(p["scopes"]), "state": state, **p["extra"]}
    return f"{p['auth']}?{urlencode(q)}"


def pop_state(state: str) -> tuple[str, str] | None:
    return _pending_state.pop(state, None)


async def exchange(provider: str, account: str, code: str, port: int, client: httpx.AsyncClient | None = None) -> None:
    p = PROVIDERS[provider]
    data = {"client_id": secret(p["id"]), "client_secret": secret(p["secret"]), "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(provider, port)}
    if provider == "microsoft":
        data["scope"] = " ".join(p["scopes"])
    async with (client or httpx.AsyncClient(timeout=20)) as c:
        r = await c.post(p["token"], data=data)
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(d.get("error_description") or d.get("error") or "token exchange failed")
    _save(account, {"provider": provider, "access_token": d["access_token"], "refresh_token": d.get("refresh_token"),
                    "expires_at": time.time() + int(d.get("expires_in", 3600)) - 60, "scope": d.get("scope") or ""})


def granted(account: str) -> str:
    """The permissions the account's sign-in was given (empty for a sign-in made before this was recorded)."""
    return (_all().get("oauth", {}).get(account) or {}).get("scope") or ""


async def access_token(account: str, provider: str, client: httpx.AsyncClient | None = None) -> str:
    tok = _all().get("oauth", {}).get(account)
    if not tok:
        raise AuthNeeded(account, provider)
    if tok["expires_at"] > time.time():
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise AuthNeeded(account, provider)
    p = PROVIDERS[provider]
    data = {"client_id": secret(p["id"]), "client_secret": secret(p["secret"]), "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}
    if provider == "microsoft":
        data["scope"] = " ".join(p["scopes"])
    async with (client or httpx.AsyncClient(timeout=20)) as c:
        r = await c.post(p["token"], data=data)
    d = r.json()
    if "access_token" not in d:
        raise AuthNeeded(account, provider)
    tok.update(access_token=d["access_token"], expires_at=time.time() + int(d.get("expires_in", 3600)) - 60)
    if d.get("refresh_token"):
        tok["refresh_token"] = d["refresh_token"]
    _save(account, tok)
    return tok["access_token"]
