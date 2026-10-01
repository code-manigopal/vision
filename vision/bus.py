"""Event bus, live state, and the SQLite store.

Every agent status change is published on the bus. The server keeps one in-memory
snapshot (what the dashboard shows) and fans events out to connected dashboards
over WebSocket. The store keeps history on disk.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self.state: dict[str, Any] = {"masters": {}, "reports": {}, "boot": {"active": False, "done": 0, "total": 0},
                                      "approvals": [], "telegram": {"connected": False, "reason": "not started"},
                                      "report_data": {}, "notices": {}}
        self.log: deque[dict] = deque(maxlen=50)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def snapshot(self) -> dict:
        return {"type": "snapshot", "state": {**self.state, "log": list(self.log)}}

    def publish(self, event: dict) -> None:
        self._apply(event)
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # a stalled dashboard never blocks the agents

    def notice(self, key: str, text: str, url: str | None = None) -> None:
        """Something only you can do (log in, drop a CSV). Shown on the dashboard, sent once to Telegram."""
        if self.state["notices"].get(key, {}).get("text") == text:
            return
        self.publish({"type": "notice", "key": key, "text": text, "url": url, "t": time.strftime("%H:%M")})
        self.say(f"Action needed · {text}")

    def clear_notice(self, key: str) -> None:
        if key in self.state["notices"]:
            self.publish({"type": "notice_clear", "key": key})

    def say(self, msg: str) -> None:
        self.publish({"type": "log", "t": time.strftime("%H:%M"), "msg": msg})

    def _apply(self, e: dict) -> None:
        kind = e.get("type")
        if kind == "agent":
            m = self.state["masters"].setdefault(e["master"], {"agents": []})
            agents = m["agents"]
            a = e["agent"]
            for i, cur in enumerate(agents):
                if cur["name"] == a["name"]:
                    agents[i] = {**cur, **a}
                    break
            else:
                agents.append(a)
        elif kind == "master_report":
            self.state["reports"][e["master"]] = e["summary"]
            if e.get("data"):
                self.state["report_data"][e["master"]] = e["data"]
        elif kind == "notice":
            self.state["notices"][e["key"]] = {k: e.get(k) for k in ("text", "url", "t")}
        elif kind == "notice_clear":
            self.state["notices"].pop(e["key"], None)
        elif kind == "boot":
            self.state["boot"] = {k: e[k] for k in ("active", "done", "total")}
        elif kind == "log":
            self.log.appendleft({"t": e["t"], "msg": e["msg"]})
        elif kind == "approval":
            self.state["approvals"] = [a for a in self.state["approvals"] if a["id"] != e["approval"]["id"]] + [e["approval"]]
        elif kind == "approval_decided":
            self.state["approvals"] = [a for a in self.state["approvals"] if a["id"] != e["id"]]
        elif kind == "telegram":
            self.state["telegram"] = e["status"]


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY, ts REAL, master TEXT, agent TEXT, status TEXT, label TEXT,
  summary TEXT, error TEXT, ms INTEGER);
CREATE TABLE IF NOT EXISTS master_reports (
  id INTEGER PRIMARY KEY, ts REAL, master TEXT, summary TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, ts REAL, master TEXT, agent TEXT, title TEXT, payload TEXT,
  status TEXT DEFAULT 'pending', decided_ts REAL);
CREATE INDEX IF NOT EXISTS idx_runs_master ON agent_runs(master, ts);
CREATE TABLE IF NOT EXISTS kv (
  ns TEXT, key TEXT, value TEXT, ts REAL, PRIMARY KEY (ns, key));
"""


class Store:
    """Tiny SQLite wrapper. Writes are quick and run in a thread so the event loop never blocks."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _write(self, sql: str, args: tuple) -> None:
        with self._conn() as c:
            c.execute(sql, args)

    async def record_run(self, master: str, agent: str, status: str, label: str, summary: str, error: str | None, ms: int) -> None:
        await asyncio.to_thread(self._write,
            "INSERT INTO agent_runs(ts, master, agent, status, label, summary, error, ms) VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), master, agent, status, label, summary, error, ms))

    async def record_report(self, master: str, summary: str, data: dict) -> None:
        await asyncio.to_thread(self._write,
            "INSERT INTO master_reports(ts, master, summary, data) VALUES (?,?,?,?)",
            (time.time(), master, summary, json.dumps(data, default=str)))

    # ---------- small JSON key-value store used by the masters (emails, drafts, jobs, leads...) ----------
    def kv_put(self, ns: str, key: str, value: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO kv(ns, key, value, ts) VALUES (?,?,?,?)", (ns, str(key), json.dumps(value, default=str), time.time()))

    def kv_get(self, ns: str, key: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT value FROM kv WHERE ns = ? AND key = ?", (ns, str(key))).fetchone()
        return json.loads(r["value"]) if r else None

    def kv_list(self, ns: str, since: float = 0, limit: int = 500) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT key, value, ts FROM kv WHERE ns = ? AND ts >= ? ORDER BY ts DESC LIMIT ?", (ns, since, limit)).fetchall()
        return [{**json.loads(r["value"]), "_key": r["key"], "_ts": r["ts"]} for r in rows]

    def kv_delete(self, ns: str, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM kv WHERE ns = ? AND key = ?", (ns, str(key)))

    def kv_has(self, ns: str, key: str) -> bool:
        return self.kv_get(ns, key) is not None

    # ---------- approvals: the YOU gate ----------
    def add_approval(self, master: str, agent: str, title: str, payload: dict | None = None) -> dict:
        with self._conn() as c:
            cur = c.execute("INSERT INTO approvals(ts, master, agent, title, payload) VALUES (?,?,?,?,?)",
                            (time.time(), master, agent, title, json.dumps(payload or {})))
            return self.get_approval(cur.lastrowid, c)

    def get_approval(self, approval_id: int, c: sqlite3.Connection | None = None) -> dict | None:
        conn = c or self._conn()
        r = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if not r:
            return None
        row = dict(r)
        try:
            row["payload"] = json.loads(row.get("payload") or "{}")
        except json.JSONDecodeError:
            row["payload"] = {}
        return row

    def find_pending(self, master: str, key: str) -> dict | None:
        """An open approval for the same thing (so agents don't ask twice)."""
        for a in self.pending_approvals():
            if a["master"] == master and a["payload"].get("key") == key:
                return a
        return None

    def pending_approvals(self) -> list[dict]:
        with self._conn() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM approvals WHERE status = 'pending' ORDER BY ts").fetchall()]
            return [self.get_approval(i, c) for i in ids]

    def decide_approval(self, approval_id: int, decision: str) -> dict | None:
        """decision: approved | rejected. Returns the row, or None if it was already decided."""
        with self._conn() as c:
            cur = c.execute("UPDATE approvals SET status = ?, decided_ts = ? WHERE id = ? AND status = 'pending'",
                            (decision, time.time(), approval_id))
            return self.get_approval(approval_id, c) if cur.rowcount else None

    def latest_reports(self) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT master, summary FROM master_reports r WHERE ts = (SELECT MAX(ts) FROM master_reports WHERE master = r.master)"
            ).fetchall()
        return {r["master"]: r["summary"] for r in rows}
