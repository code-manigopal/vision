"""US visa appointment portal for Canada (ais.usvisa-info.com, en-ca): read the dates on offer, nothing else.

The approach follows the open-source kcajc/usvisa-ca (Selenium for the sign-in, then the portal's own dates request
with the session's cookies), without its automatic sign-in and without its rescheduling.

Hard rules, enforced here:
- Sign-in happens in a visible Chrome window Selenium opens (`sign_in_canada`). By default the person signs in
  themselves and VISION types nothing. **Mani's choice (2026-10-07): an account may carry a saved password, and then
  VISION signs in itself the way that repo does** (email, password, the policy box, Sign In; nothing else). An earlier
  automated attempt got sign-in locked for an hour, so: one attempt, never repeated by itself; a refusal, a lock
  message or a visible CAPTCHA pauses the account. Only the session (cookies, the browser's user agent, the schedule
  number) is reused afterwards.
- Read-only. The hourly look is plain HTTP and can only send GETs (`_only_get`); it asks for one thing, the list of
  days for a consulate. No browser is open during a look, so nothing can be clicked or submitted.
- A CAPTCHA page or any other challenge in an answer stops the check (`Challenge`); it is never worked around.
- No proxies, no retries. The look sends the user agent of the browser the person signed in with (Mani's choice,
  2026-10-07, own family's accounts, same as the repo above); nothing else about the request is dressed up.

The dates address and the consulate numbers come from that repo (reported working March 2026). None of this has run
signed in from VISION yet. Addresses are kept together so a first-run fix is one line.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx

HOST = "ais.usvisa-info.com"
BASE = f"https://{HOST}/en-ca/niv"
SIGN_IN = f"{BASE}/users/sign_in"
DAYS = BASE + "/schedule/{schedule}/appointment/days/{facility}.json?appointments[expedite]=false"
# The portal's numbers for its Canadian consulates (Toronto and Vancouver confirmed in kcajc/usvisa-ca, the rest reported).
FACILITIES = {"calgary": "89", "halifax": "90", "montreal": "91", "ottawa": "92", "quebec": "93", "quebec city": "93",
              "toronto": "94", "vancouver": "95"}
REFUSED_WORDS = re.compile(r"invalid email or password|incorrect (email|password)", re.I)
LOCKED_WORDS = re.compile(r"account (is|has been) locked[^.\n]*", re.I)
CHALLENGE_WORDS = re.compile(r"captcha|verify (that )?you are (a )?human|one[- ]time (pass)?code|verification code|unusual activity", re.I)
TIMEOUT = 30


class PortalError(RuntimeError):
    """The check failed in an ordinary way (page changed, network, portal down)."""


class Challenge(PortalError):
    """The portal asked for something only a person may answer. The account is paused."""


class NeedsSignIn(PortalError):
    """There is no live session. Only the person can make one (VISION never signs in); the account waits for them."""


class SignInRefused(PortalError):
    """The portal turned the saved email and password down. Never tried again by itself (a lock-out risk)."""


class Locked(PortalError):
    """The portal has locked sign-in for a while. Trying again only makes it worse; the account is paused."""


class ReadOnlyViolation(PortalError):
    """Something tried to send a non-GET request to the portal."""


def allowed(method: str, url: str) -> bool:
    """The read-only rule: GETs always; one POST, the sign-in form (which only the person ever submits)."""
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return True
    u = urlsplit(url)
    return method.upper() == "POST" and u.hostname == HOST and u.path.rstrip("/").endswith("/users/sign_in")


async def _only_get(request: httpx.Request) -> None:
    if request.method != "GET" or request.url.host != HOST:
        raise ReadOnlyViolation(f"refused to send {request.method} {request.url.host}{request.url.path}")


def redact(text: str, *secrets: str) -> str:
    """Take secrets out of a message and hide the name part of any email address."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return re.sub(r"[\w.+-]+@([\w-]+\.[\w.-]+)", r"***@\1", text)


def parse_days(body: str) -> list[str]:
    """The portal's day list -> sorted ISO dates. Anything that isn't that list is a failure, not 'no dates'."""
    try:
        rows = json.loads(body)
    except ValueError:
        raise PortalError("the dates request did not return a list of dates")
    if not isinstance(rows, list):
        raise PortalError("the dates request did not return a list of dates")
    out = []
    for r in rows:
        try:
            out.append(date.fromisoformat(r["date"]).isoformat())
        except (KeyError, TypeError, ValueError):
            raise PortalError("the dates request returned a date in a form not seen before")
    return sorted(set(out))


def match_facilities(cities: list[str], known: dict[str, str] | None = None) -> dict[str, str]:
    """City names as you wrote them -> the portal's consulate numbers."""
    out, missing = {}, []
    for c in cities:
        fid = (known or {}).get(c) or FACILITIES.get(c.strip().lower())
        if fid:
            out[c] = fid
        else:
            missing.append(c)
    if missing:
        raise PortalError(f"no consulate called {', '.join(missing)} (known: {', '.join(sorted(n.title() for n in FACILITIES if n != 'quebec city'))})")
    return out


def _sign_in_blocking(wait_seconds: int, email: str | None = None, password=None) -> dict:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By

    auto = bool(email and password)
    driver = webdriver.Chrome()        # the Mac's own Chrome, a visible window, nothing changed about it
    try:
        driver.get(SIGN_IN)
        if auto:                       # as kcajc/usvisa-ca does: the two fields, the policy box itself (not its label), Sign In
            driver.implicitly_wait(10)
            driver.find_element(By.ID, "user_email").send_keys(email)
            secret = password()
            driver.find_element(By.ID, "user_password").send_keys(secret)
            del secret
            box = driver.find_element(By.ID, "policy_confirmed")
            if not box.is_selected():
                driver.find_element(By.CSS_SELECTOR, "#sign_in_form .icheckbox").click()
            if not box.is_selected():
                raise PortalError("could not tick the sign-in page's policy box")
            driver.find_element(By.NAME, "commit").click()
            driver.implicitly_wait(0)
            wait_seconds = 25
        deadline = time.time() + wait_seconds
        while True:                    # by hand, VISION types and clicks nothing: it only watches for the page to move on
            time.sleep(0.5)
            try:
                u = urlsplit(driver.current_url)
            except WebDriverException as e:
                raise PortalError("the sign-in window was closed before signing in") from e
            if u.hostname == HOST and "/users/sign_in" not in u.path and "/niv/" in u.path:
                break
            if auto:
                text = driver.find_element(By.TAG_NAME, "body").text
                if LOCKED_WORDS.search(text):
                    raise Locked("the portal says: " + LOCKED_WORDS.search(text).group(0))
                if REFUSED_WORDS.search(text):
                    raise SignInRefused("the portal did not accept the saved email and password")
                if CHALLENGE_WORDS.search(text) or any(f.is_displayed() and f.size["height"] > 100 for f in
                                                       driver.find_elements(By.CSS_SELECTOR, "iframe[src*='bframe'], iframe[src*='hcaptcha'][src*='challenge']")):
                    raise Challenge("the portal showed a CAPTCHA at sign-in")
            if time.time() > deadline:
                raise PortalError("the portal stayed on the sign-in page without saying why" if auto else f"nobody signed in within {wait_seconds // 60} minutes")
        time.sleep(2)                  # let the account page finish loading
        m = re.search(r"/schedule/(\d+)/", driver.current_url + " " + driver.page_source)
        if not m:
            raise PortalError("signed in, but the account page shows no appointment schedule")
        return {"cookies": [{k: c.get(k) for k in ("name", "value", "domain", "path")} for c in driver.get_cookies()],
                "ua": driver.execute_script("return navigator.userAgent"), "schedule": m.group(1)}
    finally:
        try:
            driver.quit()
        except Exception:
            pass


async def sign_in_canada(*, wait_seconds: int = 300, email: str | None = None, password=None, **_: Any) -> dict:
    """Open the sign-in page in a Chrome window on this Mac. With no password it waits for the person to sign in
    themselves; with `email` and `password` (a function that returns it) VISION fills the form once.

    Returns the session to keep: {cookies, ua, schedule}."""
    return await asyncio.to_thread(_sign_in_blocking, wait_seconds, email, password)


async def check_canada(*, cities: list[str], state: dict | None = None, schedule: str | None = None,
                       facilities: dict[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None, **_: Any) -> dict[str, Any]:
    """One read-only look with a session the person made by signing in themselves.

    Returns {dates: {city: [iso]}, schedule, facilities, state (the session, with any cookie the portal renewed)}."""
    if not state or not state.get("cookies"):
        raise NeedsSignIn("no saved sign-in yet")
    schedule = schedule or state.get("schedule")
    if not schedule:
        raise NeedsSignIn("the saved sign-in has no schedule number")
    facilities = match_facilities(cities, facilities)
    jar = httpx.Cookies()
    for c in state["cookies"]:
        jar.set(c["name"], c["value"], domain=c.get("domain") or HOST, path=c.get("path") or "/")
    headers = {"User-Agent": state.get("ua") or "", "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01",
               "Referer": f"{BASE}/schedule/{schedule}/appointment"}
    dates: dict[str, list[str]] = {}
    async with httpx.AsyncClient(headers=headers, cookies=jar, timeout=TIMEOUT, follow_redirects=False, transport=transport,
                                 event_hooks={"request": [_only_get]}) as client:
        for city in cities:
            r = await client.get(DAYS.format(schedule=schedule, facility=facilities[city]))
            body = r.text
            if r.status_code in (301, 302, 303, 307, 401) or "/users/sign_in" in body[:4000]:
                raise NeedsSignIn("the saved sign-in has run out")
            if body.lstrip().startswith("<") and CHALLENGE_WORDS.search(body):
                raise Challenge("the portal answered with a CAPTCHA or security check")
            if r.status_code != 200:
                raise PortalError(f"the dates request answered {r.status_code}")
            dates[city] = parse_days(body)
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in client.cookies.jar]
    return {"dates": dates, "schedule": schedule, "facilities": facilities, "state": {**state, "cookies": cookies, "schedule": schedule}}
