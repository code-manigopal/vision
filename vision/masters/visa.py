"""Visa Watch (live): Canada Checker -> Slot Watcher (reporter).

Looks, about once an hour per account, at the US visa appointment dates the Canada portal offers and tells Mani
(dashboard notice + Telegram) when a date earlier than the booked one shows up in a city he chose. It only looks:
booking is always done by hand. The rules that keep it that way live in services/visa_portal.py.

Sign-in is in a Chrome window VISION opens with Selenium (`sign_in`): by default the account holder signs in
themselves and no password is kept; an account with a saved password (encrypted) is signed in by VISION, once per
expired session and at most MAX_SIGN_INS times a day; the session that makes is kept encrypted in data/visa/ (key in
the macOS Keychain) and reused for the hourly looks, which are plain GET requests with no browser. When it runs out the account waits in status `signin` and a notice
asks for a new sign-in. Accounts live in kv `visa_accounts`, alerts already sent in kv `visa_alerts`.
Manage accounts on the dashboard (Visa Watch -> Desk) or with `python -m vision visa ...`.
The India portal (usvisascheduling.com) is parked: add it to PORTALS and SIGNERS when it is built.
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import date
from typing import Any

from ..agents import AgentResult, SubAgent
from ..config import ROOT
from ..services import keyvault, visa_portal as vp

NS, ALERTS, STATE = "visa_accounts", "visa_alerts", "visa_state"
PORTALS = {"canada": vp.check_canada}
SIGNERS = {"canada": vp.sign_in_canada}
MAX_FAILS = 3              # in a row, then the account is paused
GAP = 5 * 60               # two checks never start closer together than this
REPEAT = 24 * 3600         # the same city + date is not announced twice within this
SECRET = ("password",)     # optional, encrypted; never leaves the record: not in reports, lists, the API or logs
MAX_SIGN_INS = 8           # automatic sign-ins per account per 24 h; past that it waits for a sign-in by hand


def session_file(acc_id: str):
    return ROOT / "data" / "visa" / f"{acc_id}.session"


def accounts(store) -> list[dict]:
    return sorted(({**a, "id": a.pop("_key")} for a in store.kv_list(NS)), key=lambda a: a.get("created", 0))


def public(acc: dict) -> dict:
    return {**{k: v for k, v in acc.items() if k not in SECRET and not k.startswith("_")}, "auto": bool(acc.get("password")),
            "slots": [list(s) for s in earlier(acc)]}


def save(store, acc: dict) -> None:
    store.kv_put(NS, acc["id"], {k: v for k, v in acc.items() if k not in ("id", "auto", "slots") and not k.startswith("_")})


def parse_skip(value) -> list[list[str]]:
    """Dates never to offer: "2027-03-10, 2027-04-01..2027-04-07" (or " to ") -> [[start, end], ...], each end included."""
    if isinstance(value, list):
        value = ", ".join(v if isinstance(v, str) else "..".join(v) for v in value)
    out = []
    for part in re.split(r"[,;\n]+", value or ""):
        if not part.strip():
            continue
        ends = [date.fromisoformat(x.strip()).isoformat() for x in re.split(r"\.\.+|\bto\b", part.strip())]
        if len(ends) > 2 or ends[0] > ends[-1]:
            raise ValueError(f"not a date or a range: {part.strip()}")
        out.append([ends[0], ends[-1]])
    return sorted(out)


def acceptable(acc: dict, day: str) -> bool:
    """A date worth telling Mani about: strictly before the date to beat, not before `not_before`, not in a skipped range."""
    return day < acc["booked"] and day >= (acc.get("not_before") or "") and not any(a <= day <= b for a, b in acc.get("skip") or [])


def add_account(store, name: str, email: str, cities: list[str], booked: str, portal: str = "canada", password: str | None = None,
                not_before: str | None = None, skip=None) -> dict:
    if portal not in PORTALS:
        raise ValueError(f"portal {portal!r} is not built (have: {', '.join(PORTALS)})")
    date.fromisoformat(booked)
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "account"
    acc_id, n = base, 1
    while store.kv_has(NS, acc_id):
        n += 1
        acc_id = f"{base}-{n}"
    acc = {"id": acc_id, "name": name, "email": email, "portal": portal, "cities": cities, "booked": booked,
           "not_before": date.fromisoformat(not_before).isoformat() if not_before else "", "skip": parse_skip(skip),
           "status": "signin", "error": "not signed in yet", "fails": 0, "next_due": 0, "created": time.time()}
    if password:               # automatic sign-in: the first look finds no session and signs in
        acc.update(password=keyvault.seal(password), status="active", error="")
    save(store, acc)
    return acc


def update_account(store, acc: dict, *, cities: list[str] | None = None, booked: str | None = None, password: str | None = None,
                   forget: bool = False, not_before: str | None = None, skip=None) -> dict:
    if not_before is not None:      # "" clears it; None leaves it as it is
        acc["not_before"] = date.fromisoformat(not_before).isoformat() if not_before else ""
    if skip is not None:
        acc["skip"] = parse_skip(skip)
    if forget:                 # back to signing in by hand
        acc.pop("password", None)
    if password:
        acc["password"] = keyvault.seal(password)
        session_file(acc["id"]).unlink(missing_ok=True)
        if acc["status"] == "signin":
            acc.update(status="active", error="", next_due=0)
    if cities:
        if [c.lower() for c in cities] != [c.lower() for c in acc["cities"]]:
            acc["dates"] = {c: d for c, d in (acc.get("dates") or {}).items() if c in cities}
        acc["cities"] = cities
    if booked:
        acc["booked"] = date.fromisoformat(booked).isoformat()
    save(store, acc)
    return acc


def set_status(store, acc: dict, status: str) -> dict:
    """Pause or resume by hand; a resume wipes the failure count and makes the account due."""
    acc.update(status=status, fails=0, error="", next_due=0)
    save(store, acc)
    return acc


def remove_account(store, acc_id: str) -> None:
    store.kv_delete(NS, acc_id)
    for a in store.kv_list(ALERTS, limit=5000):
        if a["_key"].startswith(acc_id + "|"):
            store.kv_delete(ALERTS, a["_key"])
    session_file(acc_id).unlink(missing_ok=True)


def earlier(acc: dict) -> list[tuple[str, str]]:
    """(city, date) for each chosen city: the earliest date on offer that is acceptable (see `acceptable`).

    A skipped or too-early date is passed over for the next one, so the search goes on to other dates."""
    out = []
    for city in acc.get("cities", []):
        ok = sorted(d for d in (acc.get("dates") or {}).get(city) or [] if acceptable(acc, d))
        if ok:
            out.append((city, ok[0]))
    return out


def in_quiet(quiet: list[str], now: float) -> bool:
    if len(quiet or []) != 2:
        return False
    hm = time.strftime("%H:%M", time.localtime(now))
    a, b = quiet
    return a <= hm < b if a <= b else (hm >= a or hm < b)


def _load_state(acc_id: str) -> dict | None:
    f = session_file(acc_id)
    try:
        return json.loads(keyvault.unseal(f.read_text())) if f.exists() else None
    except Exception:      # an unreadable session is only a reason to sign in again
        return None


def _save_state(acc_id: str, state: dict) -> None:
    f = session_file(acc_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(keyvault.seal(json.dumps(state)))


async def sign_in(store, acc: dict, *, auto: bool = False) -> dict:
    """Open the portal's sign-in page in a Chrome window and keep the session it makes.

    By hand (the default) the person signs in. `auto` uses the account's saved password, once: a refusal, a lock
    or a CAPTCHA pauses the account, and nothing here tries again."""
    sealed = acc.get("password") if auto else None
    try:
        if sealed:
            acc["sign_ins"] = [t for t in acc.get("sign_ins", []) if time.time() - t < 86400] + [time.time()]
            state = await SIGNERS[acc["portal"]](email=acc["email"], password=lambda: keyvault.unseal(sealed).decode())
        else:
            state = await SIGNERS[acc["portal"]]()
        _save_state(acc["id"], state)
        acc.update(status="active", fails=0, error="", next_due=0, signed_in=time.time())
    except (vp.SignInRefused, vp.Locked, vp.Challenge) as e:
        acc.update(status="paused", last_result="paused", error=vp.redact(str(e), acc["email"]))
    except Exception as e:
        acc.update(status="signin", error="sign-in not completed: " + vp.redact(str(e), acc["email"])[:200])
    save(store, acc)
    return acc


async def check_account(store, acc: dict, *, interval: int = 60, jitter: int = 10) -> dict:
    """One look for one account. Updates and saves the record; never raises and never tries twice."""
    now = time.time()
    store.kv_put(STATE, "run", {"started": now})
    async def look() -> None:
        res = await PORTALS[acc["portal"]](cities=acc["cities"], state=_load_state(acc["id"]), schedule=None, facilities=acc.get("facilities"))
        _save_state(acc["id"], res["state"])
        acc.update(dates=res["dates"], schedule=res["schedule"], facilities=res["facilities"], fails=0, last_result="ok", error="")
        acc["empties"] = 0 if any(res["dates"].values()) else acc.get("empties", 0) + 1     # looks in a row with no date in any city

    try:
        try:
            await look()
        except vp.NeedsSignIn as e:
            recent = [t for t in acc.get("sign_ins", []) if now - t < 86400]
            if not acc.get("password") or len(recent) >= MAX_SIGN_INS:      # not a fault: the account waits for its owner
                acc.update(status="signin", last_result="signin", error=str(e) + (f" ({MAX_SIGN_INS} automatic sign-ins in a day already)" if acc.get("password") else ""))
            else:
                await sign_in(store, acc, auto=True)                         # one sign-in, then the look once more; never a loop
                if acc["status"] == "active":
                    await look()
                else:
                    acc["last_result"] = acc["status"]
    except vp.NeedsSignIn as e:
        acc.update(status="signin", last_result="signin", error="signed in, but the portal still refused the look: " + str(e))
    except (vp.Challenge, vp.ReadOnlyViolation) as e:             # only a person can clear these
        acc.update(status="paused", last_result="paused", error=vp.redact(str(e), acc["email"]))
    except Exception as e:
        acc["fails"] = acc.get("fails", 0) + 1
        acc.update(last_result="fail", error=vp.redact(str(e), acc["email"])[:400])
        if acc["fails"] >= MAX_FAILS:
            acc.update(status="paused", last_result="paused", error=f"{MAX_FAILS} checks failed in a row, last: {acc['error']}")
    acc["last_check"] = now
    acc["next_due"] = now + (interval + random.uniform(-jitter, jitter)) * 60
    save(store, acc)
    return acc


class CanadaChecker(SubAgent):
    name, tier, note = "Canada Checker", "API", "ais.usvisa-info.com · read-only"
    blocking = False

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        store, o, now = ctx["store"], self.opts, time.time()
        active = [a for a in accounts(store) if a["status"] == "active" and a["portal"] == "canada"]
        if not active:
            return AgentResult("idle", "NO ACCOUNTS", "No active account")
        if in_quiet(o.get("quiet") or [], now):
            return AgentResult("idle", "QUIET", "Quiet hours")
        due = sorted((a for a in active if a.get("next_due", 0) <= now), key=lambda a: a.get("next_due", 0))
        gap = 0 if o.get("test_mode") else GAP      # test mode: "Check now" really is now
        if not due or now - (store.kv_get(STATE, "run") or {}).get("started", 0) < gap:
            nxt = min(a.get("next_due", 0) for a in active)
            return AgentResult("done", "WAITING", "Next check " + time.strftime("%H:%M", time.localtime(max(nxt, now))))
        acc = await check_account(store, due[0], interval=o.get("interval", 60), jitter=o.get("jitter", 10))
        ctx["visa_checked"] = acc["id"]
        if acc["last_result"] == "ok":
            return AgentResult("done", "CHECKED", f"{acc['name']}: checked {len(acc['cities'])} cities")
        if acc["status"] == "signin":
            return AgentResult("wait", "SIGN IN", f"{acc['name']}: {acc['error']}")
        return AgentResult("error", "PAUSED" if acc["status"] == "paused" else "FAILED", f"{acc['name']}: {acc['error']}")


class SlotWatcher(SubAgent):
    name, tier, note = "Slot Watcher", "NONE", "earlier than booked?"

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        store, bus, now = ctx["store"], ctx["bus"], time.time()
        accs, parts, found = accounts(store), [], 0
        for acc in accs:
            if acc["status"] == "signin":
                bus.notice(f"visa:signin:{acc['id']}", f"Visa Watch needs a sign-in for {acc['name']} ({acc.get('error') or 'no saved sign-in'}). "
                           "On the Mac: Visa Watch, Desk, Sign in.")
                parts.append(f"{acc['name']} needs sign-in")
                continue
            bus.clear_notice(f"visa:signin:{acc['id']}")
            if acc["status"] == "paused":
                if acc.get("error"):      # paused by hand = no notice
                    bus.notice(f"visa:paused:{acc['id']}", f"Visa Watch paused for {acc['name']}: {acc['error']}. "
                               "Check the portal yourself, then press Resume on the Visa Watch desk.", vp.SIGN_IN)
                parts.append(f"{acc['name']} paused")
                continue
            bus.clear_notice(f"visa:paused:{acc['id']}")
            slots = earlier(acc)
            found += bool(slots)
            failed = " · last check failed" if acc.get("last_result") == "fail" else ""
            if not acc.get("dates"):
                parts.append(f"{acc['name']} not checked yet{failed}")
            elif not any(acc["dates"].values()):     # an empty list: nothing on offer, a finished application, or the portal holding back
                parts.append(f"{acc['name']} portal lists no dates" + (f" ({acc['empties']} looks in a row)" if acc.get("empties", 0) >= 3 else "") + failed)
            elif slots:
                parts.append(f"{acc['name']} EARLIER SLOT " + ", ".join(f"{c} {d}" for c, d in slots) + f" (booked {acc['booked']})")
            else:
                parts.append(f"{acc['name']} nothing earlier than {acc['booked']}{failed}")
            if acc["id"] != ctx.get("visa_checked") or acc.get("last_result") != "ok":
                continue
            key = f"visa:slot:{acc['id']}"
            if not slots:
                bus.clear_notice(key)
                continue
            fresh = [(c, d) for c, d in slots if now - (store.kv_get(ALERTS, f"{acc['id']}|{c}|{d}") or {}).get("at", 0) > REPEAT]
            if fresh:
                bus.notice(key, f"Earlier US visa slot for {acc['name']} · " + ", ".join(f"{c}: {d}" for c, d in slots)
                           + f" (booked: {acc['booked']}). Log in and book it yourself; slots go fast.", vp.SIGN_IN)
                for c, d in fresh:
                    store.kv_put(ALERTS, f"{acc['id']}|{c}|{d}", {"at": now})
        if not accs:
            return AgentResult("idle", "NO ACCOUNTS", "No accounts yet (add one on the Visa Watch desk)")
        return AgentResult("done", f"{found} EARLIER" if found else "WATCHING", " · ".join(parts), {"accounts": [public(a) for a in accs]})


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {
        "Canada Checker": CanadaChecker(interval=options.get("interval_minutes", 60), jitter=options.get("jitter_minutes", 10),
                                        quiet=options.get("quiet") or [], test_mode=bool(options.get("test_mode"))),
        "Slot Watcher": SlotWatcher(),
    }


# ---------- python -m vision visa ... ----------
USAGE = """python -m vision visa add                      add an account (asks; a password is optional and never shown or stored in plain text)
python -m vision visa signin <id>              opens the portal's sign-in page; you sign in yourself, VISION keeps the session
python -m vision visa list                     accounts and their state
python -m vision visa update <id> [--date YYYY-MM-DD] [--from YYYY-MM-DD] [--skip "2027-03-10, 2027-04-01..2027-04-07"] [--cities "Toronto, Ottawa"] [--password | --forget-password]
python -m vision visa pause <id> | resume <id> | remove <id>
python -m vision visa check <id>               one look right now, printed here (no Telegram)"""


def cli(args: list[str]) -> int:
    import asyncio

    from ..bus import Store
    (ROOT / "data").mkdir(exist_ok=True)
    store = Store(ROOT / "data" / "vision.db")
    cmd, rest = (args[0] if args else ""), args[1:]
    by_id = {a["id"]: a for a in accounts(store)}

    def cities_of(text: str) -> list[str]:
        return [c.strip() for c in text.split(",") if c.strip()]

    if cmd == "add":
        name = input("Whose account (a name for alerts): ").strip()
        from getpass import getpass
        email = input("Portal sign-in email: ").strip()
        password = getpass("Portal password, not shown (leave empty to sign in yourself each time): ")
        cities = cities_of(input("Cities to watch, comma separated (e.g. Toronto, Ottawa): "))
        booked = input("Alert if earlier than (the booked date, or the latest date you would take; YYYY-MM-DD): ").strip()
        not_before = input("Not before (optional, YYYY-MM-DD): ").strip()
        skip = input("Dates to skip (optional, e.g. 2027-03-10, 2027-04-01..2027-04-07): ").strip()
        if not (name and email and cities):
            print("Nothing saved: name, email and at least one city are needed.")
            return 1
        acc = add_account(store, name, email, cities, booked, password=password or None, not_before=not_before or None, skip=skip)
        print(f"Saved as '{acc['id']}'. " + ("VISION signs in by itself at the first look." if password else f"Now sign in once: python -m vision visa signin {acc['id']}"))
        return 0
    if cmd == "list":
        for a in by_id.values():
            last = time.strftime("%d %b %H:%M", time.localtime(a["last_check"])) if a.get("last_check") else "never"
            print(f"{a['id']:<14} {a['status']:<7} {a['name']} · {vp.redact(a['email'])} · {', '.join(a['cities'])} · booked {a['booked']} · last check {last}"
                  + (f" · {a['error']}" if a.get("error") else ""))
        if not by_id:
            print("No accounts yet. Add one with: python -m vision visa add")
        return 0
    acc = by_id.get(rest[0]) if rest else None
    if cmd not in ("update", "pause", "resume", "remove", "check", "signin"):
        print(USAGE)
        return 1
    if not acc:
        print("Which account? See: python -m vision visa list")
        return 1
    if cmd == "update":
        opts = rest[1:]
        from getpass import getpass
        update_account(store, acc, cities=cities_of(opts[opts.index("--cities") + 1]) if "--cities" in opts else None,
                       booked=opts[opts.index("--date") + 1] if "--date" in opts else None,
                       not_before=opts[opts.index("--from") + 1] if "--from" in opts else None, skip=opts[opts.index("--skip") + 1] if "--skip" in opts else None,
                       password=getpass("Portal password (not shown): ") if "--password" in opts else None, forget="--forget-password" in opts)
        print(f"Updated '{acc['id']}'.")
    elif cmd in ("pause", "resume"):
        set_status(store, acc, "paused" if cmd == "pause" else "active")
        print(f"'{acc['id']}' is now {acc['status']}.")
    elif cmd == "remove":
        remove_account(store, acc["id"])
        print(f"Removed '{acc['id']}': its record, saved session and sent-alert history.")
    elif cmd == "signin":
        print("A Chrome window is opening. Sign in there yourself; it closes by itself once you are in (5 minutes at most).")
        acc = asyncio.run(sign_in(store, acc))
        print("Signed in; the session is saved." if acc["status"] == "active" else acc["error"])
        return 0 if acc["status"] == "active" else 1
    elif cmd == "check":
        acc = asyncio.run(check_account(store, acc))
        if acc["last_result"] != "ok":
            print(f"{acc['last_result'].upper()}: {acc['error']}")
            return 1
        for c in acc["cities"]:
            days = acc["dates"].get(c) or []
            print(f"{c}: " + (f"earliest {days[0]} ({len(days)} dates listed)" if days else "no dates listed"))
        slots = earlier(acc)
        print("Earlier than booked: " + ", ".join(f"{c} {d}" for c, d in slots) if slots else f"Nothing earlier than {acc['booked']}.")
    return 0
