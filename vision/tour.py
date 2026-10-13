"""Walk-through tour from a folder of listing photos (a standalone tool, not a master).

    python -m vision tour <photo folder> [--title "12 Main St"] [--keep-order] [--fresh] [--no-video] [--upright] [--no-music]
    python -m vision tour model           fetch the depth model (99 MB, once)
    python -m vision tour open <slug>     serve data/tours/<slug>/ and open it in the browser
    python -m vision tour bake <slug>     the walk-in model as files (model/model.obj + textures) and the camera's route
    python -m vision tour film <slug>     Blender films the walk through that model into walk.mp4 (--quick: a short low-detail test)

Each photo becomes a standing spot. The local vision model says which room it shows and the spots are put in
walking order (front door first, backyard last; a wrong room is corrected in the tour's rooms.txt, `--fresh` asks the model again); a depth map per photo lets the viewer push forward and look
around. Nothing is invented: every pixel on screen comes from the photo, only shifted by its depth.
A floor plan among the photos is kept out of the walk: the model reads the room names printed on it and where, which
gives the walk its order (room to nearest room, from the front door) and the page a map with a "you are here" dot.
The plan's walls are also raised into a plain 3D model to walk through (W A S D), with each photo standing in its room:
walking into a photo opens it. The model is the plan's shape only, white walls, not the real interior.
Output in data/tours/<slug>/: index.html (arrow keys), photos/, depth/, plans/, tour.json, tour.mp4 (the same walk).
Only use photos you have the right to use; this tool reads a folder and fetches nothing from listing sites.
"""

from __future__ import annotations

import asyncio
import base64
import html
import io
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .config import ROOT

DIR = ROOT / "data" / "tours"
VIEWER = Path(__file__).with_name("tour_viewer.html")
NOTE = "Motion generated from listing photos"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
LONG_SIDE = 1920
# the walk: a home's parts in the order a visitor meets them
ROOMS = [("front", "Exterior"), ("entry", "Entry"), ("living", "Living room"), ("dining", "Dining room"), ("kitchen", "Kitchen"),
         ("family", "Family room"), ("office", "Office"), ("hall", "Hallway"), ("stairs", "Stairs"), ("primary", "Primary bedroom"),
         ("bedroom", "Bedroom"), ("bathroom", "Bathroom"), ("laundry", "Laundry"), ("utility", "Utility room"), ("basement", "Basement"),
         ("attic", "Attic"), ("garage", "Garage"), ("other", "Interior"), ("backyard", "Backyard"), ("view", "View")]
NAMES = dict(ROOMS)
RANK = {k: i for i, (k, _) in enumerate(ROOMS)}
WORDS = {"exterior": "front", "front": "front", "entry": "entry", "foyer": "entry", "living": "living", "dining": "dining",
         "kitchen": "kitchen", "family": "family", "office": "office", "den": "office", "hall": "hall", "hallway": "hall",
         "stairs": "stairs", "primary": "primary", "master": "primary", "bedroom": "bedroom", "bed": "bedroom", "bath": "bathroom",
         "bathroom": "bathroom", "laundry": "laundry", "utility": "utility", "basement": "basement", "attic": "attic", "garage": "garage", "backyard": "backyard",
         "yard": "backyard", "patio": "backyard", "deck": "backyard", "view": "view"}
# camera move, the same numbers in tour_viewer.html
ZMAX, NEAR, FAR, PIVOT, OVERSCAN = 0.24, 0.4, 0.85, 0.45, 0.94    # near things grow only a little faster than far ones: more tears faces and furniture edges
FPS, FADE = 30, 0.7
WALL_M = 0.16       # an outside wall as drawn on a plan, in metres: sets the size of the walk-in model (approximate)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "tour"


def from_name(stem: str) -> str:
    """The room a file name states ("03-kitchen" -> kitchen), or "" when it says nothing (IMG_1234)."""
    for w in re.findall(r"[a-z]+", stem.lower()):
        if w in WORDS:
            return WORDS[w]
    return ""


def natural(p: Path) -> list:
    """Sort key that puts 2.jpg before 10.jpg."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def dhash(img: Image.Image) -> int:
    px = img.convert("L").resize((9, 8), Image.BILINEAR).tobytes()
    return sum(1 << (r * 8 + c) for r in range(8) for c in range(8) if px[r * 9 + c] > px[r * 9 + c + 1])


def distinct(imgs: list[Image.Image], within: int = 3) -> list[int]:
    """Indexes of the photos to keep: one that is nearly the same picture as an earlier one is left out."""
    keep, seen = [], []
    for i, im in enumerate(imgs):
        h = dhash(im)
        if all(bin(h ^ s).count("1") > within for s in seen):
            keep.append(i)
            seen.append(h)
    return keep


async def see(llm, img: Image.Image, ask: str, max_tokens: int, side: int = 640) -> str:
    """Show the local vision model one picture with a question. "" when it doesn't answer."""
    buf = io.BytesIO()
    small = img.copy()
    small.thumbnail((side, side))
    small.save(buf, "JPEG", quality=85)
    msg = [{"role": "user", "content": [{"type": "text", "text": ask}, {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]}]
    try:
        text = (await llm.chat(msg, tier="local", max_tokens=max_tokens, temperature=0))["text"]
    except Exception:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S)      # a thinking model may reason out loud first


async def label(llm, img: Image.Image) -> str:
    """The room the model sees in a photo, "plan" for a floor plan drawing, or "" when it gives no usable answer."""
    ask = ("This is one image from a home listing. What does it show? Choose exactly one of: "
           + ", ".join(k for k, _ in ROOMS) + ', plan. "front" is the house seen from outside (front or side), "backyard" is the yard or garden, '
           '"primary" is the main bedroom, "utility" is a room with the furnace or water heater, "other" is any indoor space not on the list, '
           '"plan" is a floor plan drawing, not a photo.\nReply with JSON only: {"room": "<one of the list>"}')
    found = re.findall(r'"room"\s*:\s*"([a-z]+)"', (await see(llm, img, ask, 400)).lower())
    return found[-1] if found and (found[-1] in NAMES or found[-1] == "plan") else ""


async def read_plan(llm, img: Image.Image) -> list[dict]:
    """The rooms named on a floor plan and where each name is printed (x, y as fractions of the drawing)."""
    ask = ("This is a floor plan. For every room name printed on it, give the point where that name is printed. Reply with JSON only: "
           '[{"name": "<text as printed>", "x": <0-1000 from the left edge>, "y": <0-1000 from the top edge>}]')
    rooms = []
    for m in re.findall(r"\{[^{}]*\}", await see(llm, img, ask, 1500, side=1024)):
        try:
            o = json.loads(m)
            key, x, y = from_name(str(o["name"])), float(o["x"]) / 1000, float(o["y"]) / 1000
        except (ValueError, KeyError, TypeError):
            continue
        if key and 0 <= x <= 1 and 0 <= y <= 1:
            rooms.append({"room": key, "name": NAMES[key], "x": round(x, 3), "y": round(y, 3)})
    return rooms


def path(rooms: list[dict]) -> list[str]:
    """A walk through one plan: from the front door (else the living room), each time to the nearest room not yet visited."""
    left = list(rooms)
    cur = next((r for r in left if r["room"] == "entry"), None) or next((r for r in left if r["room"] == "living"), None) or (left[0] if left else None)
    out = []
    while cur:
        out.append(cur["room"])
        left.remove(cur)
        cur = min(left, key=lambda r: math.hypot(r["x"] - cur["x"], r["y"] - cur["y"]), default=None)
    return list(dict.fromkeys(out))


def shell(img: Image.Image, px: int = 5) -> dict | None:
    """The walls of a floor plan as a grid, for the walk-in model: 1 = wall, 2 = window, 0 = open floor.
    Walls are the plan's big black shapes (lettering and thin lines are too small to count), windows the blue
    strips set in them. `cell` is a square's size in metres, judged from the wall thickness; x0..y1 say which part
    of the drawing the grid covers. None when the picture has no walls to find."""
    import numpy as np
    from scipy import ndimage as ndi
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    dark = ndi.binary_opening((r < 80) & (g < 80) & (b < 80), structure=np.ones((5, 5), bool))
    lab, n = ndi.label(dark)
    if not n:
        return None
    sizes = ndi.sum(dark, lab, index=range(1, n + 1))
    # windows and doors cut the walls into pieces: the long pieces mark out the house, and a short piece (the bit of
    # wall between a door and a window) counts when it lies within that outline; a scale bar or a logo lies outside it
    ys, xs = np.nonzero(np.isin(lab, [i + 1 for i, v in enumerate(sizes) if v >= 0.1 * sizes.max()]))
    inside = lambda c: ys.min() <= c[0] <= ys.max() and xs.min() <= c[1] <= xs.max()
    walls = np.isin(lab, [i + 1 for i, c in enumerate(ndi.center_of_mass(dark, lab, range(1, n + 1))) if sizes[i] >= 60 and inside(c)])
    if walls.sum() < 0.004 * walls.size:
        return None
    thick = 2 * float(np.percentile(ndi.distance_transform_edt(walls)[walls], 90))
    scale = WALL_M / max(thick, 2.0)                                       # metres per pixel
    blue = ndi.binary_opening((b > 150) & (r < 140) & (b - r > 60), structure=np.ones((3, 3), bool))
    bl, _ = ndi.label(blue)
    glass = np.isin(bl, [i for i in np.unique(bl[ndi.binary_dilation(walls, iterations=4)]) if i])   # only blue that sits in a wall
    ys, xs = np.nonzero(walls)
    pad = int(1.5 / scale)
    x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
    w, h = (min(a.shape[1], xs.max() + 1 + pad) - x0) // px, (min(a.shape[0], ys.max() + 1 + pad) - y0) // px
    cut = lambda m: m[y0:y0 + h * px, x0:x0 + w * px].reshape(h, px, w, px).mean(axis=(1, 3))
    grid = np.where(cut(walls) > 0.4, 1, np.where(cut(glass) > 0.4, 2, 0))
    return {"cell": round(px * scale, 4), "w": int(w), "h": int(h), "x0": round(x0 / a.shape[1], 5), "y0": round(y0 / a.shape[0], 5),
            "x1": round((x0 + w * px) / a.shape[1], 5), "y1": round((y0 + h * px) / a.shape[0], 5), "grid": "".join(map(str, grid.ravel()))}


class Finder:
    """Finds where a photo was taken on a floor plan, with no camera data: from every open square of the plan it knows how
    far the walls are in each direction, and a photo's depth along its eye line is compared against that. The best
    agreement (room, square, direction, lens width) is the answer. A boxy empty room looks alike from opposite corners,
    so the direction can come out mirrored: window positions help, and cameras.txt lets a wrong one be put right."""
    COLS, RAYS, REACH = 96, 720, 22.0

    def __init__(self, plan: dict, step_m: float = 0.25):
        import numpy as np
        sh = self.sh = plan["shell"]
        w, h, cell = sh["w"], sh["h"], sh["cell"]
        g = np.array(list(sh["grid"]), dtype=np.uint8).reshape(h, w)
        st = max(1, round(step_m / cell))
        ys, xs = np.mgrid[st // 2:h:st, st // 2:w:st]
        pos = np.stack([xs.ravel(), ys.ravel()], 1)
        wy, wx = np.nonzero(g)
        pos = pos[(g[pos[:, 1], pos[:, 0]] == 0) & (pos[:, 0] > wx.min()) & (pos[:, 0] < wx.max()) & (pos[:, 1] > wy.min()) & (pos[:, 1] < wy.max())]
        ang = np.arange(self.RAYS) / self.RAYS * 2 * np.pi            # 0 = up the plan, clockwise
        dx, dy, t = np.sin(ang), -np.cos(ang), np.arange(1, int(self.REACH / cell * 2)) * 0.5
        self.dist = np.empty((len(pos), self.RAYS), np.float32)
        self.kind = np.empty((len(pos), self.RAYS), np.uint8)
        rows = np.arange(self.RAYS)
        for i, (px, py) in enumerate(pos):                            # what a walker standing here sees all round: how far, and wall or window
            X, Y = (px + 0.5 + np.outer(dx, t)).astype(int), (py + 0.5 + np.outer(dy, t)).astype(int)
            out = (X < 0) | (X >= w) | (Y < 0) | (Y >= h)
            v = np.where(out, 0, g[np.clip(Y, 0, h - 1), np.clip(X, 0, w - 1)])
            stop = (v > 0) | out
            first = stop.argmax(1)
            self.dist[i] = np.where(~stop.any(1) | out[rows, first], self.REACH, t[first] * cell)
            self.kind[i] = v[rows, first]
        # which room each square belongs to: the nearest printed room name it has a clear line to
        L = np.array([[(r["x"] - sh["x0"]) / (sh["x1"] - sh["x0"]) * w, (r["y"] - sh["y0"]) / (sh["y1"] - sh["y0"]) * h] for r in plan["rooms"]]).reshape(-1, 2)
        D = np.hypot(pos[:, None, 0] - L[None, :, 0], pos[:, None, 1] - L[None, :, 1])
        for i in range(len(pos)):
            for j in range(len(L)):
                n = int(D[i, j] * 2) + 1
                lx = np.clip(np.round(np.linspace(pos[i, 0], L[j, 0], n)).astype(int), 0, w - 1)
                ly = np.clip(np.round(np.linspace(pos[i, 1], L[j, 1], n)).astype(int), 0, h - 1)
                if g[ly, lx].any():
                    D[i, j] = 1e9
        self.pos, self.rooms = pos, [r["room"] for r in plan["rooms"]]
        self.own = np.where(D.min(1) < 1e8, D.argmin(1), -1) if len(L) else np.full(len(pos), -1)

    FOVS = (88, 98, 108, 118)                                           # listing photos are shot wide

    def scores(self, room: str, img: Image.Image, depth_map):
        """How well one photo of `room` fits every open square of that room and every direction, for each lens width:
        (the squares, {lens width: marks[square, direction]}). None when the plan has no such room."""
        import numpy as np
        cand = np.nonzero(np.isin(self.own, [j for j, r in enumerate(self.rooms) if r == room]))[0]
        if not len(cand):
            return None
        hgt = depth_map.shape[0]
        row = np.median(depth_map[int(hgt * 0.46):int(hgt * 0.54)], axis=0)                 # nearness along the eye line
        near = np.interp(np.linspace(0, len(row) - 1, self.COLS), np.arange(len(row)), row)
        hsv = np.asarray(img.convert("HSV").resize((self.COLS, 60)), dtype=np.float32)
        colour = hsv[18:29, :, 1].mean(0) / 255                                             # trees and sky through a window, just above eye level

        def corr(a, b):
            a, b = a - a.mean(-1, keepdims=True), b - b.mean(-1, keepdims=True)
            return (a * b).sum(-1) / (np.sqrt((a * a).sum(-1) * (b * b).sum(-1)) + 1e-9)
        out = {}
        for fov in self.FOVS:
            al = np.arctan(np.linspace(-1, 1, self.COLS) * math.tan(math.radians(fov) / 2))
            idx = (np.arange(self.RAYS)[:, None] + np.round(al / (2 * np.pi) * self.RAYS).astype(int)[None, :]) % self.RAYS
            glass = (self.kind[cand][:, idx] == 2).astype(np.float32)
            out[fov] = corr(1.0 / (self.dist[cand][:, idx] * np.cos(al)), near) + 0.3 * np.where(glass.std(-1) > 0, corr(glass, colour), 0)
        return cand, out

    def _ranked(self, cand, by_fov: dict) -> list[dict]:
        """The best place for each of 8 directions, best first, as x, y (fractions of the drawing), yaw, fov, fit."""
        sh, tops = self.sh, {}
        for fov, score in by_fov.items():
            for sector in range(8):
                part = score[:, sector * self.RAYS // 8:(sector + 1) * self.RAYS // 8]
                k = [int(v) for v in __import__("numpy").unravel_index(part.argmax(), part.shape)]
                if sector not in tops or part[k[0], k[1]] > tops[sector][0]:
                    tops[sector] = (float(part[k[0], k[1]]), self.pos[cand[k[0]]], (k[1] + sector * self.RAYS // 8) / self.RAYS * 2 * math.pi, fov)
        return [{"x": round(sh["x0"] + (t[1][0] + 0.5) / sh["w"] * (sh["x1"] - sh["x0"]), 4), "y": round(sh["y0"] + (t[1][1] + 0.5) / sh["h"] * (sh["y1"] - sh["y0"]), 4),
                 "yaw": round(t[2], 3), "fov": t[3], "fit": round(t[0], 2)} for t in sorted(tops.values(), key=lambda t: -t[0])]

    def find(self, room: str, img: Image.Image, depth_map) -> dict | None:
        """Where on the plan a photo of `room` was taken: x, y (fractions of the drawing), yaw (radians, 0 = up the plan,
        clockwise), fov (degrees across), and `alts`, the runners-up (a mirrored room is usually one of them)."""
        got = self.scores(room, img, depth_map)
        if got is None:
            return None
        ranked = self._ranked(*got)
        return {**ranked[0], "alts": ranked[1:5]}

    def find_group(self, room: str, shots: list[tuple], turns: list[float]) -> list[dict] | None:
        """Several photos taken from ONE spot, each turned by a known amount from the first (`turns`, degrees clockwise):
        the spot and direction where they all fit together. One wall seen square-on says little; four walls from one
        spot say where in the room that spot is. Returns one camera per photo, in order."""
        import numpy as np
        each = [self.scores(room, im, d) for im, d in shots]
        if any(e is None for e in each):
            return None
        cand = each[0][0]
        joint = {fov: sum(np.roll(e[1][fov], -round(t / 360 * self.RAYS), axis=1) for e, t in zip(each, turns)) / len(each) for fov in self.FOVS}
        ranked = self._ranked(cand, joint)
        turn = lambda pose, t: {**pose, "yaw": round((pose["yaw"] + math.radians(t)) % (2 * math.pi), 3)}
        return [{**turn(ranked[0], t), "alts": [turn(r, t) for r in ranked[1:5]], "group": len(shots)} for t in turns]


def read_cameras(path: Path) -> dict[str, dict]:
    """cameras.txt in a tour's folder: "10.jpg = 1 0.31 0.43 318 118" (plan number, x, y, direction in degrees with 0 = up
    the plan and clockwise, lens width in degrees): where a photo was taken, as corrected by hand."""
    said = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        name, _, rest = line.partition("#")[0].partition("=")
        try:
            n, x, y, deg, fov = [float(v) for v in rest.split()]
        except ValueError:
            continue
        said[name.strip()] = {"plan": int(n) - 1, "x": x, "y": y, "yaw": round(math.radians(deg), 3), "fov": fov}
    return said


def order(spots: list[dict], keep: bool = False, walk: list[str] | None = None) -> list[dict]:
    """Walking order: outside and the entry, then the rooms a floor plan gave in its order (`walk`), then the rest in the
    usual order with the backyard last. File order stands when asked for, or when the model placed nothing."""
    if keep or not any(s.get("seen") for s in spots):
        return spots
    walk = walk or []

    def place(s: dict) -> tuple:
        r = s["room"]
        if r in walk:
            return 1, walk.index(r)
        return (0 if RANK[r] <= RANK["entry"] else 2), RANK[r]
    return sorted(spots, key=place)


def read_rooms(path: Path) -> dict[str, str]:
    """rooms.txt in a tour's folder: "13.jpg = dining" per line, the room for a photo as corrected by hand."""
    said = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        name, _, room = line.partition("#")[0].partition("=")
        if room.strip().lower() in NAMES or room.strip().lower() == "plan":
            said[name.strip()] = room.strip().lower()
    return said


def write(out: Path, tour: dict) -> None:
    """A tour's files that hold its data: tour.json, the page, and cameras.txt for correcting by hand."""
    spots = tour["spots"]
    if any("camera" in x for x in spots):
        (out / "cameras.txt").write_text(
            "# Where each photo was taken: plan number, x and y on that plan (0-1 from its left and top edges), direction in degrees\n"
            "# (0 = up the plan, 90 = right), lens width in degrees. Found by matching the photo's depth to the plan's walls; a room\n"
            "# can come out facing the wrong way. Correct a line and run the same command again, or use the editor (tour open).\n"
            + "".join(f"{x['file']} = {x['camera']['plan'] + 1} {x['camera']['x']} {x['camera']['y']} {math.degrees(x['camera']['yaw']):.0f} {x['camera']['fov']:g}\n"
                      for x in sorted(spots, key=lambda x: natural(Path(x["file"]))) if "camera" in x))
    (out / "tour.json").write_text(json.dumps(tour, indent=2))
    (out / "index.html").write_text(VIEWER.read_text().replace("__TITLE__", html.escape(tour["title"])).replace("__TOUR__", json.dumps(tour).replace("</", "<\\/")))


def save_cameras(out: Path, cameras: dict) -> int:
    """The editor's Save: new places for some photos' cameras ({file: {plan, x, y, yaw, fov}}), written into the tour's files."""
    tour = json.loads((out / "tour.json").read_text())
    n = 0
    for s in tour["spots"]:
        c = cameras.get(s["file"])
        if isinstance(c, dict) and 0 <= int(c.get("plan", -1)) < len(tour["plans"]):
            s["camera"] = {**s.get("camera", {}), "plan": int(c["plan"]), "x": round(float(c["x"]), 4), "y": round(float(c["y"]), 4),
                           "yaw": round(float(c["yaw"]) % (2 * math.pi), 3), "fov": round(float(c["fov"]), 1), "by": "hand"}
            n += 1
    write(out, tour)
    return n


async def build(folder: Path | str, title: str = "", *, llm=None, depth_fn=None, keep_order: bool = False, fresh: bool = False,
                out: Path | None = None, log=print) -> dict:
    """Photos in `folder` -> a tour folder. Returns the tour (title, spots, plans, dir)."""
    folder = Path(folder).expanduser()
    files = sorted((p for p in folder.iterdir() if p.suffix.lower() in PHOTO_EXT), key=natural) if folder.is_dir() else []
    if not files:
        raise ValueError(f"No photos (.jpg, .png, .webp) in {folder}")
    if depth_fn is None:
        from .services import depth
        depth_fn = depth.estimate
    title = title or folder.name.replace("-", " ").replace("_", " ").title()
    out = out or DIR / slug(title)
    # what an earlier run left: the rooms (rooms.txt, which may be corrected by hand) and what was read off each plan
    said = {} if fresh else read_rooms(out / "rooms.txt")
    cameras = {} if fresh else read_cameras(out / "cameras.txt")
    try:
        read = {} if fresh else {pl["file"]: pl["rooms"] for pl in json.loads((out / "tour.json").read_text()).get("plans", []) if pl.get("rooms")}
    except (OSError, ValueError, KeyError, TypeError):
        read = {}
    use_model = bool(llm) and await llm.local_available()
    if not use_model and not said:
        log("  no local vision model: keeping file-name order")
    spots, plans = [], []
    for p in files:
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        im.thumbnail((LONG_SIDE, LONG_SIDE), Image.LANCZOS)
        seen = said.get(p.name) or (await label(llm, im) if use_model else "")
        if seen == "plan" or (not seen and re.search(r"plan|blueprint", p.stem.lower())):
            plans.append({"file": p.name, "img": im})
            log(f"  {p.name:<28} floor plan")
            continue
        room = seen or from_name(p.stem) or "other"
        spots.append({"file": p.name, "room": room, "label": NAMES[room], "seen": bool(seen), "img": im})
        log(f"  {p.name:<28} {NAMES[room]}" + ("  (rooms.txt)" if p.name in said else "" if seen or not use_model else "  (model gave no answer)"))
    if not spots:
        raise ValueError(f"Only floor plans in {folder}: a tour needs photos")
    kept = distinct([s["img"] for s in spots])
    if len(kept) < len(spots):
        log(f"  left out {len(spots) - len(kept)} near-duplicate photo(s)")
    spots = [spots[i] for i in kept]

    for sub in ("photos", "depth", "plans", "thumbs"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True)
    walk: list[str] = []
    for n, pl in enumerate(plans):
        im = pl.pop("img")
        pl.update(image=f"plans/{n}.jpg", aspect=round(im.width / im.height, 4), rooms=read.get(pl["file"]) or (await read_plan(llm, im) if use_model else []))
        im.save(out / pl["image"], "JPEG", quality=88)
        pl["shell"] = shell(im)
        walk += [r for r in path(pl["rooms"]) if r not in walk]
        log(f"  {pl['file']:<28} rooms on the plan: {', '.join(r['name'] for r in pl['rooms']) or 'none read'}")
    spots = order(spots, keep_order, walk)
    finders = {n: Finder(pl) for n, pl in enumerate(plans) if pl.get("shell") and pl["rooms"]}
    # photos named <something>-1 .. -4 in one room are a set shot from one spot, a quarter turn to the right each time:
    # they are placed together, which pins the spot down far better than each wall on its own
    depths = {s["file"]: depth_fn(s["img"]) for s in spots}
    grouped: dict[str, dict] = {}
    sets: dict[tuple, list] = {}
    for s in spots:
        m = re.match(r"^(.*)-([1-4])$", Path(s["file"]).stem)
        if m:
            sets.setdefault((m.group(1), s["room"]), []).append((int(m.group(2)), s))
    for (_, room), members in sets.items():
        on = next((n for n, pl in enumerate(plans) if n in finders and any(r["room"] == room for r in pl["rooms"])), None)
        if on is None or len(members) < 2:
            continue
        members.sort(key=lambda m: m[0])
        got = finders[on].find_group(room, [(s["img"], depths[s["file"]]) for _, s in members], [(k - members[0][0]) * 90.0 for k, _ in members])
        for (_, s), pose in zip(members, got or []):
            grouped[s["file"]] = pose
    for n, s in enumerate(spots):
        im = s.pop("img")
        s.pop("seen")
        s.update(photo=f"photos/{n:02d}.jpg", depth=f"depth/{n:02d}.png", aspect=round(im.width / im.height, 4))
        im.save(out / s["photo"], "JPEG", quality=86)
        small = im.copy()
        small.thumbnail((1024, 1024))
        small.save(out / f"thumbs/{n:02d}.jpg", "JPEG", quality=82)       # the photo as it stands in the walk-in model
        d = depths[s["file"]]
        on = next((n for n, pl in enumerate(plans) if n in finders and any(r["room"] == s["room"] for r in pl["rooms"])), None)
        found = grouped.get(s["file"]) or (finders[on].find(s["room"], im, d) if on is not None else None)
        if s["file"] in cameras and cameras[s["file"]]["plan"] in finders:      # as corrected by hand; the finder's guesses stay on offer in the editor
            s["camera"] = {**cameras[s["file"]], "alts": ([{k: v for k, v in found.items() if k != "alts"}] + found["alts"]) if found else []}
        elif found:
            s["camera"] = {"plan": on, **found}
        # near things are widened a touch and edges softened, so an object's rim moves with the object instead of tearing
        Image.fromarray((d * 255).clip(0, 255).astype("uint8"), "L").filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3)).save(out / s["depth"])
    if use_model or said:      # with no model the file names decide and there is nothing to correct
        lines = "".join(f"{x['file']} = {x.get('room', 'plan')}\n" for x in sorted(spots + plans, key=lambda x: natural(Path(x["file"]))))
        (out / "rooms.txt").write_text("# The room for each photo. Correct a line and run the same command again: these are used instead of asking the model.\n"
                                       f"# Rooms: {', '.join(k for k, _ in ROOMS)}, plan\n" + lines)
    tour = {"title": title, "note": NOTE, "spots": spots, "plans": plans}
    write(out, tour)
    return {**tour, "dir": out}


# ---------- the video: the same walk, played by itself ----------
def cover(aspect: float, screen: float) -> tuple[float, float]:
    """How much of a photo (as fractions of its width and height) fills a screen of the given shape."""
    kx, ky = (screen / aspect, 1.0) if aspect > screen else (1.0, aspect / screen)
    return kx * OVERSCAN, ky * OVERSCAN


def overlay(w: int, h: int, text: str, title: str = "") -> Image.Image:
    """The room name in a dark pill, bottom left; the tour's title above it on the first spot; the note bottom right."""
    from .masters.shorts_edit import font
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = min(w, h) / 1080
    f = font(int(44 * u))
    x, y, pad = int(60 * u), h - int(150 * u), int(22 * u)
    box = d.textbbox((x, y), text, font=f)
    d.rounded_rectangle((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad), radius=int(14 * u), fill=(0, 0, 0, 150))
    d.text((x, y), text, font=f, fill=(255, 255, 255, 255))
    if title:
        d.text((x - pad, y - int(130 * u)), title, font=font(int(68 * u)), fill=(255, 255, 255, 255), stroke_width=max(2, int(4 * u)), stroke_fill=(0, 0, 0, 200))
    small = font(int(22 * u))
    nb = d.textbbox((0, 0), NOTE, font=small)
    d.text((w - nb[2] - int(40 * u), h - int(56 * u)), NOTE, font=small, fill=(255, 255, 255, 170), stroke_width=1, stroke_fill=(0, 0, 0, 160))
    return im


def video(tour: dict, *, upright: bool = False, seconds: float = 3.2, music: bool = True, log=print) -> Path:
    """Render the walk to tour.mp4 (or tour-upright.mp4): each spot pushes forward and fades into the next."""
    import numpy as np
    import torch
    import torch.nn.functional as F
    out_dir = Path(tour["dir"])
    spots = tour["spots"] + [{"card": pl["image"], "label": "Floor plan"} for pl in tour.get("plans", [])]   # plans close the video, flat
    W, H = (1080, 1920) if upright else (1920, 1080)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ys, xs = torch.meshgrid(torch.linspace(-0.5, 0.5, H), torch.linspace(-0.5, 0.5, W), indexing="ij")
    base = torch.stack([xs, ys], -1).to(dev)                     # the screen, centred on 0
    centre = torch.tensor([0.5, 0.5], device=dev)
    loaded: dict[int, tuple] = {}

    def load(i: int):
        if i not in loaded:
            for k in [k for k in loaded if k < i - 1]:
                del loaded[k]
            s = spots[i]
            to = lambda im: torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0).to(dev)
            if "card" in s:
                card = Image.new("RGB", (W, H), (11, 12, 14))
                plan = Image.open(out_dir / s["card"]).convert("RGB")
                plan.thumbnail((int(W * 0.88), int(H * 0.8)), Image.LANCZOS)
                card.paste(plan, ((W - plan.width) // 2, (H - plan.height) // 2))
                card.paste(ov := overlay(W, H, s["label"]), (0, 0), ov)
                loaded[i] = (to(card).permute(2, 0, 1),)
                return loaded[i]
            img = to(Image.open(out_dir / s["photo"]).convert("RGB")).permute(2, 0, 1)[None]
            dep = to(Image.open(out_dir / s["depth"]).convert("L"))[None, None]
            ov = to(overlay(W, H, s["label"], tour["title"] if i == 0 else "")).permute(2, 0, 1)
            loaded[i] = (img, dep, torch.tensor(cover(s["aspect"], W / H), device=dev), ov[:3], ov[3:])
        return loaded[i]

    def shot(i: int, t: float):
        if len(load(i)) == 1:
            return load(i)[0]
        img, dep, k, ov, a = load(i)
        z = ZMAX * t / (seconds + FADE)
        off = torch.tensor([(0.014 if i % 2 else -0.014) * math.sin(math.pi * t / (seconds + FADE)), 0.0], device=dev)
        q = centre + base * k
        p = q
        for _ in range(4):                                       # where on the photo each screen point looks, given the depth there
            d = F.grid_sample(dep, (p.clamp(0, 1) * 2 - 1)[None], mode="bilinear", align_corners=True)[0, 0]
            p = centre + (q - centre) / (1 + z * (FAR + NEAR * d))[..., None] - off * (d[..., None] - PIVOT)
        frame = F.grid_sample(img, (p.clamp(0, 1) * 2 - 1)[None], mode="bilinear", align_corners=True)[0]
        return frame * (1 - a) + ov * a

    total = len(spots) * seconds + FADE
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    track = None
    if music:
        from .services import bgm
        track = bgm.pick("warm") or bgm.pick("light")
    if track:
        cmd += ["-stream_loop", "-1", "-i", str(track[0])]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20"]
    if track:
        cmd += ["-af", f"volume=0.5,afade=t=in:d=1,afade=t=out:st={total - 2.5:.2f}:d=2.5", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}"]
    out = out_dir / ("tour-upright.mp4" if upright else "tour.mp4")
    ff = subprocess.Popen(cmd + ["-movflags", "+faststart", str(out)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with torch.no_grad():
            for f in range(round(total * FPS)):
                time = f / FPS
                i = min(int(time // seconds), len(spots) - 1)
                t = time - i * seconds
                frame = shot(i, t)
                if i and t < FADE:                               # the spot before is still on screen, fading out
                    m = t / FADE
                    m = m * m * (3 - 2 * m)
                    frame = shot(i - 1, seconds + t) * (1 - m) + frame * m
                ff.stdin.write((frame.clamp(0, 1) * 255).byte().permute(1, 2, 0).cpu().numpy().tobytes())
                if f % (FPS * 10) == 0:
                    log(f"  video {time:5.1f} / {total:.1f} s")
        ff.stdin.close()
    except BrokenPipeError:
        pass
    err = ff.stderr.read().decode(errors="replace")
    if ff.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[-400:]}")
    if track and track[1]:
        from .services import bgm
        (out_dir / "credits.txt").write_text("Music: " + bgm.line(track[1]) + "\n")
    return out


# ---------- command line ----------
def serve(name: str, port: int = 8770, browser: bool = True) -> int:
    """Serve one tour on this machine only, with the camera editor (?edit) able to save."""
    import http.server
    import webbrowser
    d = DIR / name
    if not (d / "index.html").exists():
        print(f"No tour at {d}. Tours: {', '.join(sorted(p.name for p in DIR.iterdir() if p.is_dir())) if DIR.exists() else 'none yet'}")
        return 1

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(d), **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")                 # a saved correction shows on the next reload
            super().end_headers()

        def do_POST(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            origin = self.headers.get("Origin") or ""
            ok = self.path == "/cameras" and host in ("127.0.0.1", "localhost") and (not origin or origin.split("//")[-1].split(":")[0] == host)
            try:
                n = save_cameras(d, json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 200_000)))) if ok else None
            except (ValueError, KeyError, TypeError, OSError):
                n = None
            self.send_response(200 if n is not None else 400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"saved": n}).encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/          the tour\nhttp://127.0.0.1:{port}/?edit     the camera editor   (Ctrl-C to stop)")
    if browser:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cli(args: list[str]) -> int:
    if args[:1] == ["model"]:
        from .services import depth
        print(f"depth model: {depth.fetch()}")
        return 0
    if args[:1] in (["bake"], ["film"]) and len(args) > 1:      # the model as files (bake), and Blender's film of the walk through it (film)
        from . import tour_model
        d = DIR / args[1]
        if not (d / "tour.json").exists():
            print(f"No tour at {d}")
            return 1
        try:
            return tour_model.film(d, quick="--quick" in args) if args[0] == "film" else (print(f"model: {tour_model.bake(d)}") or 0)
        except (ValueError, RuntimeError) as e:
            print(e)
            return 1
    if args[:1] == ["open"] and len(args) > 1:
        return serve(args[1], browser="--no-browser" not in args)
    flags = {a for a in args if a.startswith("--")}
    title = args[args.index("--title") + 1] if "--title" in args and args.index("--title") + 1 < len(args) else ""
    rest = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--title")]
    if not rest:
        print(__doc__)
        return 1
    from .config import load_config
    from .services import depth
    from .services.llm import LLM
    try:
        tour = asyncio.run(build(rest[0], title, llm=LLM(load_config()), keep_order="--keep-order" in flags, fresh="--fresh" in flags))
    except (ValueError, depth.DepthUnavailable) as e:
        print(e)
        return 1
    print(f"{len(tour['spots'])} spots -> {tour['dir']}")
    if "--no-video" not in flags:
        print(f"video: {video(tour, upright='--upright' in flags, music='--no-music' not in flags)}")
    print(f"open it:  python -m vision tour open {tour['dir'].name}")
    return 0
