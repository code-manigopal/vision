"""Mark the tour's camera finder against the made-up home, where every camera's true place is known.

    .venv/bin/python scripts/dummy_home_test.py [one|four]

Builds a tour from data/dummy_home/<set>/ (photos) + plan.png, then compares each found camera with truth.json: how far
off in metres and in degrees. The rooms of the photos and the names on the plan are given, not asked of a vision model, so
the marks are for the finder alone. Tours land in data/tours/dummy-one and dummy-four.
"""
import asyncio
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from vision import tour                                                    # noqa: E402

HOME = ROOT / "data" / "dummy_home"
spec, truth = json.loads((HOME / "spec.json").read_text()), json.loads((HOME / "truth.json").read_text())


def run(which: str) -> list[dict]:
    from PIL import Image
    src, out = HOME / which, tour.DIR / f"dummy-{which}"
    shutil.copy(HOME / "plan.png", src / "99-plan.png")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    pw, ph = Image.open(HOME / "plan.png").size
    cams = [c for c in spec["cameras"] if c["set"] == which]
    (out / "rooms.txt").write_text("".join(f"{c['file']} = {c['room']}\n" for c in cams) + "99-plan.png = plan\n")
    rooms = [{"room": r["key"], "name": tour.NAMES[r["key"]], "x": round((150 + r["label"][0] * 100) / pw, 4), "y": round((190 + r["label"][1] * 100) / ph, 4)} for r in spec["rooms"]]
    (out / "tour.json").write_text(json.dumps({"plans": [{"file": "99-plan.png", "rooms": rooms}]}))
    t = asyncio.run(tour.build(src, f"Dummy {which}", out=out, log=lambda s: None))
    rows = []
    for s in t["spots"]:
        c, tr = s.get("camera"), truth[f"{which}/{s['file']}"]
        if not c:
            rows.append({"file": s["file"], "found": False})
            continue
        off = math.hypot((c["x"] - tr["x"]) * pw / 100, (c["y"] - tr["y"]) * ph / 100)
        turn = abs((math.degrees(c["yaw"]) - tr["yaw"] + 180) % 360 - 180)
        best = min([c] + c.get("alts", []), key=lambda a: abs((math.degrees(a["yaw"]) - tr["yaw"] + 180) % 360 - 180) + 40 * math.hypot((a["x"] - tr["x"]) * pw / 100, (a["y"] - tr["y"]) * ph / 100))
        rows.append({"file": s["file"], "found": True, "off_m": off, "turn": turn, "fov": c["fov"], "fit": c.get("fit"),
                     "alt_turn": abs((math.degrees(best["yaw"]) - tr["yaw"] + 180) % 360 - 180), "alt_off": math.hypot((best["x"] - tr["x"]) * pw / 100, (best["y"] - tr["y"]) * ph / 100)})
    return rows


for which in (sys.argv[1:] or ["one", "four"]):
    rows = run(which)
    print(f"\n{which}: {len(rows)} photos   (true lens 100 degrees)")
    print(f"  {'photo':<20} {'off by':>8} {'turned':>8} {'lens':>5} {'fit':>5}   best of its guesses")
    for r in rows:
        print(f"  {r['file']:<20} " + (f"{r['off_m']:>6.2f} m {r['turn']:>6.0f}° {r['fov']:>5.0f} {r['fit'] or 0:>5.2f}   {r['alt_off']:.2f} m {r['alt_turn']:.0f}°" if r["found"] else "no camera found"))
    ok = [r for r in rows if r["found"] and r["off_m"] < 0.75 and r["turn"] < 20]
    near = [r for r in rows if r["found"] and r["alt_off"] < 0.75 and r["alt_turn"] < 20]
    print(f"  right first time (within 0.75 m and 20°): {len(ok)} of {len(rows)};  right among its guesses: {len(near)} of {len(rows)}")
