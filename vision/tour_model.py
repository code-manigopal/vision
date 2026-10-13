"""A tour's walk-in model as files any 3D program can open, and the camera's walk through it.

    python -m vision tour bake <slug>     data/tours/<slug>/model/: model.obj + model.mtl, walls.jpg, floor.jpg, ceiling.jpg, path.json
    python -m vision tour film <slug>     Blender films the walk (scripts/tour_film.py) into data/tours/<slug>/walk.mp4

`bake` does on paper what the page does live: every point of the floor, the ceiling and each stretch of wall takes its
colour from the photos whose cameras see it (tour.json `camera`, a wall in between blocks a photo), blended where two
photos overlap. Where no photo reaches, the surface keeps a plain colour. One floor per bake (the first plan with a model).
`walk` lays the camera's route: from photo to photo in tour order, through the doorways, turning to each photo's own view.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

WALL, EYE = 2.5, 1.45            # metres: wall height, camera height (the page's numbers)
PPM = 150                        # texture detail, pixels per metre of surface
ATLAS = 8192
REACH = 14.0                     # a photo paints nothing farther than this from its camera
PLAIN = {"wall": (0.93, 0.91, 0.87), "floor": (0.72, 0.69, 0.65), "ceiling": (0.95, 0.95, 0.93)}


def grid_of(sh: dict) -> np.ndarray:
    return np.array(list(sh["grid"]), dtype=np.uint8).reshape(sh["h"], sh["w"]) > 0


def to_world(sh: dict, fx: float, fy: float) -> tuple[float, float]:
    return ((fx - sh["x0"]) / (sh["x1"] - sh["x0"]) * sh["w"] * sh["cell"], (fy - sh["y0"]) / (sh["y1"] - sh["y0"]) * sh["h"] * sh["cell"])


def wall_runs(solid: np.ndarray) -> list[tuple]:
    """Every straight stretch of wall face: (x0, z0, x1, z1, nx, nz) in squares, the normal pointing into the open side."""
    h, w = solid.shape
    pad = np.pad(solid, 1)
    runs = []
    for y in range(h + 1):                       # faces lying along x, between row y-1 and row y
        a, b = pad[y, 1:-1], pad[y + 1, 1:-1]
        for nz, face in ((1, a & ~b), (-1, ~a & b)):
            x = 0
            while x < w:
                if face[x]:
                    e = x
                    while e < w and face[e]:
                        e += 1
                    runs.append((x, y, e, y, 0, nz))
                    x = e
                else:
                    x += 1
    for x in range(w + 1):                       # faces lying along z, between column x-1 and column x
        a, b = pad[1:-1, x], pad[1:-1, x + 1]
        for nx, face in ((1, a & ~b), (-1, ~a & b)):
            y = 0
            while y < h:
                if face[y]:
                    e = y
                    while e < h and face[e]:
                        e += 1
                    runs.append((x, y, x, e, nx, 0))
                    y = e
                else:
                    y += 1
    return runs


def sweep(solid: np.ndarray, cell: float, x: float, z: float, n: int = 3600) -> np.ndarray:
    """From one spot, how far the first wall is in each of n directions (metres; 0 = toward -z, clockwise)."""
    h, w = solid.shape
    ang = np.arange(n) / n * 2 * np.pi
    t = np.arange(1, int(REACH / cell * 2) + 1) * 0.5
    X = (x / cell + np.outer(np.sin(ang), t)).astype(int)
    Z = (z / cell + np.outer(-np.cos(ang), t)).astype(int)
    out = (X < 0) | (X >= w) | (Z < 0) | (Z >= h)
    hit = np.where(out, False, solid[np.clip(Z, 0, h - 1), np.clip(X, 0, w - 1)])
    first = hit.argmax(1)
    return np.where(hit.any(1), t[first] * cell, REACH).astype(np.float32)


class Painter:
    """Colours surface points from the photos. `cams`: dicts with x, z, yaw, tan (half the lens width), aspect, img (H, W, 3 floats)."""

    def __init__(self, solid: np.ndarray, cell: float, cams: list[dict]):
        self.cams = cams
        for c in cams:
            c["sweep"] = sweep(solid, cell, c["x"], c["z"])

    def paint(self, px, py, pz, normal, plain) -> np.ndarray:
        """px, py, pz: flat arrays of points; normal: (nx, ny, nz) of the surface. Returns (N, 3) colours 0-1."""
        acc = np.zeros((len(px), 3), np.float32)
        tot = np.zeros(len(px), np.float32)
        top = np.zeros(len(px), np.float32)
        for c in self.cams:
            dx, dz = px - c["x"], pz - c["z"]
            f = (math.sin(c["yaw"]), -math.cos(c["yaw"]))
            zc = dx * f[0] + dz * f[1]
            dist = np.hypot(dx, dz)
            ok = (zc > 0.05) & (dist < REACH)
            if normal[1] == 0:                                           # a wall only takes a photo taken from its open side
                ok &= (dx * normal[0] + dz * normal[2]) < -0.02 * dist
            k = np.nonzero(ok)[0]
            if not len(k):
                continue
            u = (dx[k] * math.cos(c["yaw"]) + dz[k] * math.sin(c["yaw"])) / (zc[k] * c["tan"])
            v = (py[k] - EYE) / (zc[k] * c["tan"] / c["aspect"])
            ang = np.arctan2(dx[k], -dz[k]) % (2 * np.pi)
            seen = dist[k] <= c["sweep"][(ang / (2 * np.pi) * len(c["sweep"])).astype(int) % len(c["sweep"])] + 0.18
            ok2 = (np.abs(u) < 1) & (np.abs(v) < 1) & seen
            k, u, v = k[ok2], u[ok2], v[ok2]
            if not len(k):
                continue
            wgt = (1 - np.abs(u) ** 6) * (1 - np.abs(v) ** 6) / (1 + 0.2 * zc[k])
            img = c["img"]
            col = img[np.clip(((0.5 - v * 0.5) * img.shape[0]).astype(int), 0, img.shape[0] - 1), np.clip(((u * 0.5 + 0.5) * img.shape[1]).astype(int), 0, img.shape[1] - 1)]
            w3 = (wgt ** 8).astype(np.float32)                           # where two photos overlap the better-placed one wins outright: an even mix shows everything twice
            acc[k] += col * w3[:, None]
            tot[k] += w3
            top[k] = np.maximum(top[k], wgt)
        a = np.clip(top / 0.1, 0, 1)
        a = (a * a * (3 - 2 * a))[:, None]
        self.cover = top > 0.02                                           # which points a photo reached
        return np.asarray(plain, np.float32) * (1 - a) + acc / np.maximum(tot, 1e-6)[:, None] * a


def mend(col: np.ndarray, cover: np.ndarray, within: np.ndarray | None = None, reach: int = 10 ** 9) -> np.ndarray:
    """Give each point no photo reached the colour of the nearest point one did (the patch of floor under a camera's own
    feet, the wall beside it). `within` limits it to where there is a surface to mend; `reach` to how far (in points)."""
    from scipy import ndimage as ndi
    if not cover.any() or cover.all():
        return col
    dist, (iy, ix) = ndi.distance_transform_edt(~cover, return_indices=True)
    take = ~cover & (dist <= reach) & (within if within is not None else True)
    out = col.copy()
    out[take] = col[iy[take], ix[take]]
    return out


def bake(out: Path, log=print) -> Path:
    tour = json.loads((out / "tour.json").read_text())
    n = next((i for i, p in enumerate(tour["plans"]) if p.get("shell")), None)
    if n is None:
        raise ValueError("This tour has no floor plan with walls to build a model from")
    sh = tour["plans"][n]["shell"]
    solid, cell = grid_of(sh), sh["cell"]
    cams = []
    for s in tour["spots"]:
        c = s.get("camera")
        if c and c["plan"] == n:
            x, z = to_world(sh, c["x"], c["y"])
            cams.append({"file": s["file"], "room": s["room"], "x": x, "z": z, "yaw": c["yaw"], "tan": math.tan(math.radians(c["fov"]) / 2), "aspect": s["aspect"],
                         "img": np.asarray(Image.open(out / s["photo"]).convert("RGB"), np.float32) / 255})
    if not cams:
        raise ValueError("No photo has a camera on this plan: build the tour first")
    painter = Painter(solid, cell, cams)
    model = out / "model"
    model.mkdir(exist_ok=True)
    W, H = sh["w"] * cell, sh["h"] * cell
    ys, xs = np.nonzero(solid)
    bx0, bx1, bz0, bz1 = xs.min() * cell, (xs.max() + 1) * cell, ys.min() * cell, (ys.max() + 1) * cell      # the house's outline: the ceiling covers it

    # floor and ceiling: one picture each, laid over the plan
    tw, th = int(W * PPM), int(H * PPM)
    gx, gz = np.meshgrid((np.arange(tw) + 0.5) / PPM, (np.arange(th) + 0.5) / PPM)
    for name, y, nrm in (("floor", 0.0, (0, 1, 0)), ("ceiling", WALL, (0, -1, 0))):
        col = painter.paint(gx.ravel().astype(np.float32), np.full(tw * th, y, np.float32), gz.ravel().astype(np.float32), nrm, PLAIN[name])
        indoors = (gx > bx0) & (gx < bx1) & (gz > bz0) & (gz < bz1)
        col = mend(col.reshape(th, tw, 3), painter.cover.reshape(th, tw), indoors)
        Image.fromarray((col.clip(0, 1) * 255).astype(np.uint8)).save(model / f"{name}.jpg", quality=90)
        log(f"  {name}: {tw} x {th}")

    # walls: every stretch of wall face is a strip in one big picture
    runs = wall_runs(solid)
    sh_px = int(WALL * PPM)
    strips, x, row = [], 0, 0
    for r in runs:
        length = max(r[2] - r[0], r[3] - r[1]) * cell
        wpx = max(2, int(math.ceil(length * PPM)))
        if x + wpx > ATLAS:
            x, row = 0, row + 1
        strips.append((r, x, row * sh_px, wpx, length))
        x += wpx
    ah = (row + 1) * sh_px
    atlas = np.zeros((ah, ATLAS, 3), np.uint8)
    for (x0, z0, x1, z1, nx, nz), ax, ay, wpx, length in strips:
        s = (np.arange(wpx) + 0.5) / wpx * length
        yy = WALL - (np.arange(sh_px) + 0.5) / PPM
        S, Y = np.meshgrid(s, yy)
        flat = np.full(S.size, 0, np.float32)
        if nz:      # the stretch runs along x; its points sit a hair off the wall, on the open side
            px, pz = (x0 * cell + S).ravel().astype(np.float32), flat + np.float32(z0 * cell + nz * 0.01)
        else:       # it runs along z
            px, pz = flat + np.float32(x0 * cell + nx * 0.01), (z0 * cell + S).ravel().astype(np.float32)
        shade = 1.0 if nx else 0.94                                      # plain walls: one direction a touch darker, so corners read
        col = painter.paint(px, Y.ravel().astype(np.float32), pz, (nx, 0, nz), tuple(v * shade for v in PLAIN["wall"]))
        cover = painter.cover.reshape(sh_px, wpx)
        col = col.reshape(sh_px, wpx, 3)
        if cover.mean() > 0.25:                                           # a stretch mostly seen: carry its colours over the unseen rest (within a metre and a half)
            col = mend(col, cover, reach=int(1.5 * PPM))
        atlas[ay:ay + sh_px, ax:ax + wpx] = (col.clip(0, 1) * 255).astype(np.uint8)
    Image.fromarray(atlas).save(model / "walls.jpg", quality=90)
    log(f"  walls: {len(strips)} stretches, {ATLAS} x {ah}")

    # the model: y is up, x across the plan, z down the plan (metres)
    v, vt, faces = [], [], {"floor": [], "ceiling": [], "walls": []}

    def quad(mat, pts, uvs):
        base = len(v)
        v.extend(pts)
        vt.extend(uvs)
        faces[mat].append([base + 1, base + 2, base + 3, base + 4])
    quad("floor", [(0, 0, H), (W, 0, H), (W, 0, 0), (0, 0, 0)], [(0, 0), (1, 0), (1, 1), (0, 1)])
    quad("ceiling", [(bx0, WALL, bz0), (bx1, WALL, bz0), (bx1, WALL, bz1), (bx0, WALL, bz1)],
         [(bx0 / W, 1 - bz0 / H), (bx1 / W, 1 - bz0 / H), (bx1 / W, 1 - bz1 / H), (bx0 / W, 1 - bz1 / H)])
    for (x0, z0, x1, z1, nx, nz), ax, ay, wpx, length in strips:
        a, b = (x0 * cell, z0 * cell), (x1 * cell, z1 * cell)
        u0, u1, v0, v1 = ax / ATLAS, (ax + wpx) / ATLAS, 1 - (ay + sh_px) / ah, 1 - ay / ah
        quad("walls", [(a[0], 0, a[1]), (b[0], 0, b[1]), (b[0], WALL, b[1]), (a[0], WALL, a[1])], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
    lines = ["mtllib model.mtl"] + [f"v {a:.4f} {b:.4f} {c:.4f}" for a, b, c in v] + [f"vt {a:.6f} {b:.6f}" for a, b in vt]
    for mat, fs in faces.items():
        lines.append(f"usemtl {mat}")
        lines += ["f " + " ".join(f"{i}/{i}" for i in f) for f in fs]
    (model / "model.obj").write_text("\n".join(lines) + "\n")
    (model / "model.mtl").write_text("".join(f"newmtl {m}\nKd 1 1 1\nmap_Kd {m}.jpg\n\n" for m in faces))
    path = walk(sh, solid, [{"file": c["file"], "x": c["x"], "z": c["z"], "yaw": c["yaw"]} for c in cams], tour["plans"][n]["rooms"])
    (model / "path.json").write_text(json.dumps({"fps": path["fps"], "eye": EYE, "frames": path["frames"], "stops": path["stops"]}))
    log(f"  walk: {len(path['frames']) / path['fps']:.0f} s, {len(cams)} photo stops")
    return model


# ---------- the camera's walk ----------
def tight_of(solid: np.ndarray, cell: float, body: float = 0.3) -> np.ndarray:
    """Squares too close to a wall for the camera to pass through."""
    from scipy import ndimage as ndi
    return ndi.binary_dilation(solid, iterations=max(1, math.ceil(body / cell)))


def near_free(tight: np.ndarray, cx: int, cz: int) -> tuple[int, int]:
    if not tight[cz, cx]:
        return cx, cz
    zs, xs = np.nonzero(~tight)
    i = int(np.argmin((xs - cx) ** 2 + (zs - cz) ** 2))
    return int(xs[i]), int(zs[i])


def route(tight: np.ndarray, cell: float, a: tuple, b: tuple) -> list[tuple]:
    """Through the doorways from a to b (metres): the shortest way over open squares, then pulled straight where nothing is in the way."""
    from collections import deque
    h, w = tight.shape
    s = near_free(tight, min(w - 1, max(0, int(a[0] / cell))), min(h - 1, max(0, int(a[1] / cell))))
    g = near_free(tight, min(w - 1, max(0, int(b[0] / cell))), min(h - 1, max(0, int(b[1] / cell))))
    prev = {s: s}
    q = deque([s])
    while q:
        c = q.popleft()
        if c == g:
            break
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (c[0] + dx, c[1] + dz)
            if 0 <= nxt[0] < w and 0 <= nxt[1] < h and nxt not in prev and not tight[nxt[1], nxt[0]]:
                prev[nxt] = c
                q.append(nxt)
    if g not in prev:
        return [a, b]
    cells = [g]
    while cells[-1] != s:
        cells.append(prev[cells[-1]])
    cells.reverse()

    def clear(p, q2):
        n = int(max(abs(q2[0] - p[0]), abs(q2[1] - p[1])) * 2) + 1
        xs = np.round(np.linspace(p[0], q2[0], n)).astype(int)
        zs = np.round(np.linspace(p[1], q2[1], n)).astype(int)
        return not tight[zs, xs].any()
    out, i = [cells[0]], 0
    while i < len(cells) - 1:
        j = len(cells) - 1
        while j > i + 1 and not clear(cells[i], cells[j]):
            j -= max(1, (j - i) // 8)
        out.append(cells[j])
        i = j
    return [a] + [((c[0] + 0.5) * cell, (c[1] + 0.5) * cell) for c in out[1:-1]] + [b]


def walk(sh: dict, solid: np.ndarray, stops: list[dict], rooms: list[dict], fps: int = 30, speed: float = 1.0, hold: float = 2.2) -> dict:
    """The camera's place and direction for every frame: walk to each photo's spot in turn, turn to its view, linger, move on.
    Along the way it looks where it is going; the motion is then smoothed so there are no jerks."""
    cell = sh["cell"]
    tight = tight_of(solid, cell)
    door = next((r for r in rooms if r["room"] == "entry"), None)
    at = to_world(sh, door["x"], door["y"]) if door else (stops[0]["x"], stops[0]["z"])
    xs, zs, yaws, marks = [], [], [], []
    yaw = math.atan2(stops[0]["x"] - at[0], -(stops[0]["z"] - at[1])) if door else stops[0]["yaw"]

    def turn_to(target, seconds):
        nonlocal yaw
        d = math.atan2(math.sin(target - yaw), math.cos(target - yaw))
        for i in range(1, int(seconds * fps) + 1):
            k = i / (seconds * fps)
            xs.append(at[0]); zs.append(at[1]); yaws.append(yaw + d * (k * k * (3 - 2 * k)))
        yaw += d
    for st in stops:
        pts = route(tight, cell, at, (st["x"], st["z"]))
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 0.05:
                continue
            head = math.atan2(b[0] - a[0], -(b[1] - a[1]))
            if L > 0.6:                                                   # face the way it walks, except on the last short shuffle to the spot
                yaw += math.atan2(math.sin(head - yaw), math.cos(head - yaw))
            for i in range(1, int(L / speed * fps) + 1):
                k = i / (L / speed * fps)
                xs.append(a[0] + (b[0] - a[0]) * k); zs.append(a[1] + (b[1] - a[1]) * k); yaws.append(yaw)
        at = (st["x"], st["z"])
        turn_to(st["yaw"], 1.0)
        marks.append({"file": st["file"], "frame": len(xs)})
        for i in range(int(hold * fps)):                                  # linger on the photo's own view
            xs.append(at[0]); zs.append(at[1]); yaws.append(yaw)
    from scipy.ndimage import gaussian_filter1d
    sig = 0.35 * fps
    X, Z = gaussian_filter1d(np.array(xs), sig, mode="nearest"), gaussian_filter1d(np.array(zs), sig, mode="nearest")
    Yw = gaussian_filter1d(np.unwrap(np.array(yaws)), sig * 1.4, mode="nearest")
    return {"fps": fps, "stops": marks, "frames": [[round(float(a), 4), round(float(b), 4), round(float(c), 4)] for a, b, c in zip(X, Z, Yw)]}


# ---------- Blender films the walk ----------
FILM = Path(__file__).resolve().parent.parent / "scripts" / "tour_film.py"


def film(out: Path, quick: bool = False, music: bool = True, log=print) -> int:
    """Bake the model, have Blender render the walk frame by frame, and join the frames into walk.mp4."""
    import shutil
    import subprocess
    blender = shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
    if not Path(blender).exists():
        raise RuntimeError("Blender isn't installed:  brew install --cask blender")
    model = bake(out, log)
    frames = out / "model" / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    fps = json.loads((model / "path.json").read_text())["fps"]
    size = ["640", "360", str(fps * 14)] if quick else ["1920", "1080"]
    p = subprocess.run([blender, "-b", "--python", str(FILM), "--", str(model), str(frames), *size], capture_output=True, text=True)
    made = sorted(frames.glob("f*.jpg"))
    if not made:
        raise RuntimeError("Blender made no frames: " + (p.stderr or p.stdout).strip()[-500:])
    target = out / ("walk-quick.mp4" if quick else "walk.mp4")
    total = len(made) / fps
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames / "f%04d.jpg")]
    track = None
    if music and not quick:
        from .services import bgm
        track = bgm.pick("warm") or bgm.pick("light")
    if track:
        cmd += ["-stream_loop", "-1", "-i", str(track[0]), "-af", f"volume=0.5,afade=t=in:d=1,afade=t=out:st={total - 2.5:.2f}:d=2.5", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}"]
    p = subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", "-movflags", "+faststart", str(target)], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError("ffmpeg failed: " + p.stderr.strip()[-400:])
    shutil.rmtree(frames, ignore_errors=True)
    log(f"film: {target}  ({total:.0f} s)")
    return 0
