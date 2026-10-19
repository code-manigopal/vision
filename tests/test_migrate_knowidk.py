"""The one-off move of the YouTube channel's saved data to the id `knowidk` (scripts/migrate_knowidk.py)."""
import importlib.util
import json
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location("mig", Path(__file__).resolve().parent.parent / "scripts" / "migrate_knowidk.py")
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)
OLD = mig.OLD


def test_ids_paths_and_kind_move_and_history_stays(tmp_path):
    db = sqlite3.connect(tmp_path / "v.db")
    db.execute("CREATE TABLE kv (ns TEXT, key TEXT, value TEXT, ts REAL, PRIMARY KEY (ns, key))")
    rec = {"channel": OLD, "title": "An old title kept as published", "file": f"/x/data/shorts/{OLD}/a/final.mp4",
           "source": {"from": f"original ({mig.OLD_KIND})"}, "genre": mig.OLD_KIND, "id": f"{OLD}-orig-1"}
    db.execute("INSERT INTO kv VALUES ('yt_videos', ?, ?, 5)", (f"{OLD}-classic-1", json.dumps(rec)))
    db.execute("INSERT INTO kv VALUES ('yt_state', ?, ?, 6)", (f"{OLD}:insights", json.dumps({"videos": 3})))
    db.execute("INSERT INTO kv VALUES ('yt_videos', '2026-10-14-postmarket', ?, 7)", (json.dumps({"channel": "manimarket"}),))
    rows = mig.plan(db)
    assert sorted(r[2] for r in rows) == ["knowidk-classic-1", "knowidk:insights"]                 # the other channel is untouched
    new = json.loads(next(r for r in rows if r[2] == "knowidk-classic-1")[3])
    assert new["channel"] == "knowidk" and new["file"] == "/x/data/shorts/knowidk/a/final.mp4" and new["genre"] == "life"
    assert new["source"]["from"] == "original (life)" and new["id"] == "knowidk-orig-1" and new["title"] == "An old title kept as published"
    assert all(r[4] in (5, 6) for r in rows)                                                         # the order of the log is kept
