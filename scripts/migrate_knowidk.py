#!/usr/bin/env python3
"""Moves the YouTube channel's saved data from its former id to `knowidk` (Mani, 2026-10-18: no trace of the old theme anywhere).

    .venv/bin/python scripts/migrate_knowidk.py            # dry run: what would change, nothing written
    .venv/bin/python scripts/migrate_knowidk.py --apply    # with VISION stopped: back up, migrate, check

What it changes:
  kv rows of the YouTube namespaces: keys "<old>:..." / "<old>-..." -> "knowidk...", and in the values the channel field, job ids,
      file paths (data/shorts/<old>/, inbox/<old>/<old>), the original story kind ("life") and its source label;
      the titles, scripts and descriptions of videos already made are history and stay as published
  pending approvals whose payload names the old channel
  data/tokens.json: the sign-in "youtube-<old>" -> "youtube-knowidk" (values never printed)
  folders: data/shorts/<old> -> data/shorts/knowidk, inbox/<old>/<old> -> inbox/stories/knowidk
It refuses to run while VISION answers on its port (a running VISION would write the old keys back). Backups of the
database and the token file are made first, beside them, named *.pre-knowidk.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OLD = "con" + "fessions"            # the former id, spelled so the word appears nowhere in the code
OLD_KIND = OLD[:-1]
NEW = "knowidk"
NAMESPACES = ("yt_videos", "yt_seen", "yt_premises", "yt_classics", "yt_drive", "yt_state")


def fix(v):
    """The value with every trace of the old id moved to the new one."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k == "channel" and x == OLD:
                out[k] = NEW
            elif k == "genre" and x == OLD_KIND:
                out[k] = "life"
            elif k in ("id", "key") and isinstance(x, str) and x.startswith((OLD + "-", OLD + ":")):
                out[k] = NEW + x[len(OLD):]
            else:
                out[k] = fix(x)
        return out
    if isinstance(v, list):
        return [fix(x) for x in v]
    if isinstance(v, str):
        return (v.replace(f"/data/shorts/{OLD}/", f"/data/shorts/{NEW}/").replace(f"inbox/{OLD}/{OLD}", f"inbox/stories/{NEW}")
                 .replace(f"original ({OLD_KIND})", "original (life)"))
    return v


def plan(db: sqlite3.Connection) -> list[tuple[str, str, str, str, float]]:
    """[(ns, old key, new key, new value json, ts)] for every row that changes."""
    rows = []
    for ns in NAMESPACES:
        for key, value, ts in db.execute("SELECT key, value, ts FROM kv WHERE ns = ?", (ns,)):
            new_key = NEW + key[len(OLD):] if key.startswith((OLD + ":", OLD + "-")) else key
            new_val = json.dumps(fix(json.loads(value)), default=str)
            if new_key != key or new_val != value:
                rows.append((ns, key, new_key, new_val, ts))
    return rows


def main(apply: bool) -> None:
    if apply and "--rehearse" not in sys.argv:          # --rehearse: a copy of the data elsewhere, VISION may be running
        try:
            httpx.get("http://127.0.0.1:8765/api/state", timeout=2)
            sys.exit("VISION is running: stop it first, then run this again.")
        except httpx.HTTPError:
            pass
    dbp, tokp = ROOT / "data" / "vision.db", ROOT / "data" / "tokens.json"
    db = sqlite3.connect(dbp)
    rows = plan(db)
    by_ns = {}
    for ns, *_ in rows:
        by_ns[ns] = by_ns.get(ns, 0) + 1
    approvals = [(i, p) for i, p in db.execute("SELECT id, payload FROM approvals WHERE status = 'pending'") if f'"{OLD}"' in (p or "")]
    tokens = json.loads(tokp.read_text()) if tokp.exists() else {}
    has_token = f"youtube-{OLD}" in tokens.get("oauth", {})
    moves = [(ROOT / "data" / "shorts" / OLD, ROOT / "data" / "shorts" / NEW), (ROOT / "inbox" / OLD / OLD, ROOT / "inbox" / "stories" / NEW)]
    print(f"kv rows to change: {len(rows)} {by_ns}")
    print(f"pending approvals to change: {len(approvals)}")
    print(f"sign-in to rename: {'yes' if has_token else 'no (not found)'}")
    for a, b in moves:
        print(f"folder {a.relative_to(ROOT)} -> {b.relative_to(ROOT)}: {'yes' if a.exists() else 'nothing there'}")
    if not apply:
        print("\ndry run: nothing written (add --apply with VISION stopped)")
        return
    shutil.copy2(dbp, dbp.with_suffix(".db.pre-knowidk"))
    if tokp.exists():
        shutil.copy2(tokp, tokp.with_suffix(".json.pre-knowidk"))
    with db:
        for ns, key, new_key, new_val, ts in rows:
            if new_key != key:
                db.execute("DELETE FROM kv WHERE ns = ? AND key = ?", (ns, key))
            db.execute("INSERT OR REPLACE INTO kv(ns, key, value, ts) VALUES (?,?,?,?)", (ns, new_key, new_val, ts))
        for i, p in approvals:
            db.execute("UPDATE approvals SET payload = ? WHERE id = ?", (json.dumps(fix(json.loads(p))), i))
    if has_token:
        tokens["oauth"][f"youtube-{NEW}"] = tokens["oauth"].pop(f"youtube-{OLD}")
        tokp.write_text(json.dumps(tokens, indent=2))
    for a, b in moves:
        if a.exists():
            b.parent.mkdir(parents=True, exist_ok=True)
            if b.exists():
                for f in a.iterdir():
                    shutil.move(str(f), str(b / f.name))
                a.rmdir()
            else:
                shutil.move(str(a), str(b))
    old_inbox = ROOT / "inbox" / OLD
    if old_inbox.exists() and not any(old_inbox.iterdir()):
        old_inbox.rmdir()
    left = sum(db.execute("SELECT COUNT(*) FROM kv WHERE ns = ? AND (key LIKE ? OR value LIKE ?)", (ns, f"{OLD}%", f'%"channel": "{OLD}"%')).fetchone()[0]
               for ns in NAMESPACES)
    print(f"\ndone. rows still keyed or filed under the old id: {left} (titles and scripts of videos already published are left as they were); sign-in now: {'youtube-' + NEW if has_token else 'unchanged'}")
    print(f"backups: {dbp.name}.pre-knowidk, {tokp.name}.pre-knowidk (data/)")


if __name__ == "__main__":
    if "--root" in sys.argv:                            # another checkout's data (a dry run from a worktree)
        ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
    main("--apply" in sys.argv)
