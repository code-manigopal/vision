"""A made-up furnished home for testing the photo tour, where the truth is known.

    .venv/bin/python scripts/dummy_home.py            writes data/dummy_home/: spec.json, plan.png, truth.json
    blender -b --python scripts/dummy_home_render.py  builds the home from spec.json and photographs it

Two photo sets come out of the render: `one/` (a single shot per room from a corner, the way a listing is usually shot) and
`four/` (four shots per room from one spot, a quarter turn apart). truth.json holds where every camera really stood, so the
tour's camera finder can be marked in metres and degrees. Metres throughout: x across the plan, z down it; a direction of
0 points up the plan and grows clockwise.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "data" / "dummy_home"
T = 0.16                                   # wall thickness
W, H = 10.0, 8.0
door, window = "door", "window"
# a wall: its two ends (along x or along z) and the openings in it, each (from, to, kind) measured along that axis
WALLS = [
    ((0, 0), (10, 0), [(0.6, 1.5, door), (2.4, 4.2, window), (6.5, 8.5, window)]),      # north, with the front door
    ((0, 8), (10, 8), [(1.2, 3.0, window), (4.9, 5.7, window), (7.4, 9.0, window)]),    # south
    ((0, 0), (0, 8), [(1.2, 3.2, window), (5.4, 7.0, window)]),                         # west
    ((10, 0), (10, 8), [(1.0, 2.4, window), (5.0, 6.6, window)]),                       # east
    ((5.2, 0), (5.2, 4.4), [(1.2, 2.6, door)]),                                         # living | kitchen: a wide opening
    ((0, 4.4), (5.2, 4.4), [(4.4, 5.1, door)]),                                         # living | bedroom, hall
    ((5.2, 3.6), (10, 3.6), [(5.4, 6.2, door)]),                                        # kitchen | hall, office
    ((4.2, 4.4), (4.2, 8), [(4.6, 5.4, door)]),                                         # bedroom | hall, bathroom
    ((6.4, 3.6), (6.4, 8), [(4.5, 5.3, door)]),                                         # hall, bathroom | office
    ((4.2, 5.6), (6.4, 5.6), [(4.9, 5.7, door)]),                                       # hall | bathroom
]
# room: key, printed name, the rectangles it covers, floor kind, where its name is printed, plan colour
ROOMS = [
    ("living", "LIVING", [(0, 0, 5.2, 4.4)], "wood", (2.6, 2.4), (255, 249, 225)),
    ("kitchen", "KITCHEN", [(5.2, 0, 10, 3.6)], "tile", (7.6, 2.0), (226, 242, 232)),
    ("bedroom", "BEDROOM", [(0, 4.4, 4.2, 8)], "wood", (1.6, 6.3), (255, 240, 205)),
    ("office", "OFFICE", [(6.4, 3.6, 10, 8)], "wood", (8.2, 6.0), (236, 228, 214)),
    ("bathroom", "BATH", [(4.2, 5.6, 6.4, 8)], "tile", (5.3, 6.9), (200, 228, 250)),
    ("hall", "HALL", [(4.2, 4.4, 6.4, 5.6), (5.2, 3.6, 6.4, 4.4)], "wood", (5.6, 4.9), (255, 250, 232)),
]
# furniture: (x0, z0, x1, z1, bottom, top, colour 0-1)
BOX = [
    # living room
    (1.2, 3.55, 3.4, 4.3, 0.0, 0.42, (0.22, 0.30, 0.42)), (1.2, 4.05, 3.4, 4.3, 0.42, 0.85, (0.22, 0.30, 0.42)),      # sofa and its back
    (1.6, 2.7, 3.0, 3.25, 0.0, 0.38, (0.36, 0.22, 0.12)),                                                              # coffee table
    (4.55, 2.9, 5.1, 4.2, 0.0, 0.5, (0.15, 0.15, 0.16)), (4.95, 3.0, 5.05, 4.1, 0.6, 1.3, (0.03, 0.03, 0.04)),         # TV unit and screen
    (0.25, 0.3, 1.05, 1.1, 0.0, 0.75, (0.55, 0.16, 0.12)),                                                             # armchair
    (1.0, 1.4, 3.6, 3.4, 0.0, 0.015, (0.50, 0.12, 0.10)),                                                              # rug
    (2.0, 4.25, 2.9, 4.31, 1.2, 1.8, (0.85, 0.65, 0.15)),                                                              # painting over the sofa
    # kitchen
    (5.5, 0.1, 9.2, 0.7, 0.0, 0.9, (0.93, 0.93, 0.92)), (5.5, 0.08, 9.2, 0.72, 0.9, 0.94, (0.16, 0.16, 0.17)),         # counter and its top
    (9.25, 0.1, 9.9, 0.78, 0.0, 1.85, (0.75, 0.77, 0.79)),                                                             # fridge
    (5.5, 0.1, 6.4, 0.42, 1.45, 2.15, (0.93, 0.93, 0.92)), (8.6, 0.1, 9.2, 0.42, 1.45, 2.15, (0.93, 0.93, 0.92)),      # wall cupboards either side of the window
    (8.3, 2.3, 9.5, 3.2, 0.7, 0.75, (0.45, 0.30, 0.16)), (8.85, 2.7, 8.95, 2.8, 0.0, 0.7, (0.2, 0.2, 0.2)),            # table and its leg
    (7.8, 2.5, 8.2, 2.9, 0.0, 0.45, (0.80, 0.55, 0.15)), (8.7, 3.25, 9.1, 3.5, 0.0, 0.45, (0.80, 0.55, 0.15)),         # two stools
    # bedroom
    (2.2, 6.1, 4.1, 7.7, 0.0, 0.5, (0.90, 0.90, 0.88)), (3.95, 6.1, 4.1, 7.7, 0.5, 1.15, (0.35, 0.22, 0.14)),          # bed and headboard
    (2.2, 6.1, 3.3, 7.7, 0.5, 0.56, (0.30, 0.45, 0.40)),                                                               # blanket
    (3.6, 5.5, 4.1, 5.95, 0.0, 0.55, (0.35, 0.22, 0.14)), (3.6, 7.75, 4.1, 7.9, 0.0, 0.55, (0.35, 0.22, 0.14)),        # bedside tables
    (0.3, 4.5, 2.2, 5.1, 0.0, 2.1, (0.82, 0.78, 0.70)),                                                                # wardrobe
    # office
    (9.2, 4.6, 9.9, 6.9, 0.7, 0.75, (0.45, 0.30, 0.16)), (9.25, 4.65, 9.85, 4.7, 0.0, 0.7, (0.45, 0.30, 0.16)), (9.25, 6.8, 9.85, 6.85, 0.0, 0.7, (0.45, 0.30, 0.16)),   # desk
    (8.5, 5.5, 9.0, 6.0, 0.0, 0.48, (0.12, 0.12, 0.13)),                                                               # chair
    (7.0, 3.7, 9.0, 4.05, 0.0, 1.9, (0.30, 0.20, 0.12)),                                                               # bookshelf
    (6.6, 7.1, 8.4, 7.9, 0.0, 0.45, (0.42, 0.45, 0.30)),                                                               # daybed
    # bathroom
    (5.65, 5.9, 6.3, 7.6, 0.0, 0.55, (0.96, 0.96, 0.97)),                                                              # bath
    (4.3, 7.1, 4.85, 7.9, 0.0, 0.85, (0.30, 0.34, 0.38)),                                                              # basin unit
    (4.3, 5.75, 4.75, 6.35, 0.0, 0.42, (0.96, 0.96, 0.97)),                                                            # toilet
    # hall
    (5.3, 3.72, 6.3, 3.98, 0.0, 0.8, (0.35, 0.22, 0.14)),                                                              # console table
]
# the photographer: one corner shot per room, then four from one spot per room
ONE = [("living", 4.5, 3.4, 300), ("kitchen", 9.5, 3.2, 300), ("bedroom", 0.5, 5.5, 125), ("office", 6.8, 6.8, 45), ("bathroom", 4.6, 6.7, 100), ("hall", 5.8, 4.2, 200)]
FOUR = [("living", 2.6, 2.1), ("kitchen", 7.4, 1.9), ("bedroom", 1.3, 6.2), ("office", 7.9, 5.6), ("bathroom", 5.2, 6.7), ("hall", 5.3, 5.0)]
FOV, ASPECT = 100, 1.5

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cams = [{"set": "one", "file": f"{i + 1:02d}-{r}.jpg", "room": r, "x": x, "z": z, "yaw": yaw, "fov": FOV} for i, (r, x, z, yaw) in enumerate(ONE)]
    cams += [{"set": "four", "file": f"{r}-{k + 1}.jpg", "room": r, "x": x, "z": z, "yaw": k * 90 + 10, "fov": FOV} for i, (r, x, z) in enumerate(FOUR) for k in range(4)]
    spec = {"t": T, "size": [W, H], "walls": [{"a": a, "b": b, "open": o} for a, b, o in WALLS], "boxes": BOX, "cameras": cams, "aspect": ASPECT,
            "rooms": [{"key": k, "name": n, "rects": r, "floor": f, "label": l} for k, n, r, f, l, _ in ROOMS]}
    (OUT / "spec.json").write_text(json.dumps(spec, indent=1))

    # the floor plan, drawn the way the capture services draw them: black walls, blue windows, a pale colour per room
    S, M = 100, 150                                   # pixels per metre, margin
    im = Image.new("RGB", (int(W * S) + 2 * M, int(H * S) + 2 * M + 60), "white")
    d = ImageDraw.Draw(im)
    px = lambda x, z: (M + x * S, M + 40 + z * S)
    for k, n, rects, f, l, col in ROOMS:
        for x0, z0, x1, z1 in rects:
            d.rectangle((*px(x0, z0), *px(x1, z1)), fill=col)
    for a, b, opens in WALLS:
        along_x = a[1] == b[1]
        lo, hi = (a[0], b[0]) if along_x else (a[1], b[1])
        box = lambda s, e, pad=T / 2: (*px(s - (pad if along_x else T / 2), a[1] - T / 2), *px(e + (pad if along_x else T / 2), a[1] + T / 2)) if along_x else (*px(a[0] - T / 2, s - pad), *px(a[0] + T / 2, e + pad))
        d.rectangle(box(lo, hi), fill="black")
        for s, e, kind in opens:
            d.rectangle(box(s, e, 0), fill=(70, 150, 220) if kind == window else "white")
    try:
        font, small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22), ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 30)
    except OSError:
        font = small = ImageFont.load_default(22)
    for k, n, rects, f, l, col in ROOMS:
        d.text(px(*l), n, fill="black", font=font, anchor="mm")
    d.text((im.width // 2, 50), "12 Sample Street  ·  Main Floor", fill="black", font=small, anchor="mm")
    im.save(OUT / "plan.png")
    # the truth, in the tour's own terms: x, y as fractions of the drawing
    truth = {c["set"] + "/" + c["file"]: {"x": round(px(c["x"], c["z"])[0] / im.width, 4), "y": round(px(c["x"], c["z"])[1] / im.height, 4), "yaw": c["yaw"] % 360, "fov": c["fov"],
                                           "metres_per_plan_width": im.width / S} for c in cams}
    (OUT / "truth.json").write_text(json.dumps(truth, indent=1))
    print(f"{len(cams)} cameras, plan {im.size} -> {OUT}")

if __name__ == "__main__":
    main()
