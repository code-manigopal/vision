"""Walk-through tour: room order, near-duplicates, and the folder it writes. The depth model and the vision model are faked."""

import asyncio
import json

import numpy as np
from PIL import Image, ImageDraw

from vision import tour
from vision.services import depth


def photo(path, seed, size=(600, 400)):
    im = Image.new("RGB", size, (seed * 40 % 255, 90, 200 - seed * 30 % 200))
    d = ImageDraw.Draw(im)
    d.rectangle((seed * 60 % 400, 50, seed * 60 % 400 + 150, 300), fill=(250, 240 - seed * 20, seed * 50 % 255))
    d.ellipse((300 - seed * 40, 200, 420 - seed * 40, 380), fill=(20, seed * 60 % 255, 60))
    im.save(path)
    return im


def flat(im):
    return np.full((10, 14), 0.5, dtype=np.float32)


class Eyes:
    """Stands in for the local vision model: answers from a list, one photo at a time."""
    def __init__(self, rooms, up=True):
        self.rooms, self.up, self.asked = list(rooms), up, 0

    async def local_available(self):
        return self.up

    async def chat(self, messages, **kw):
        assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        self.asked += 1
        return {"text": self.rooms.pop(0)}


def test_room_from_file_name():
    assert tour.from_name("03-kitchen") == "kitchen" and tour.from_name("Master_Bed 2") == "primary"
    assert tour.from_name("IMG_1234") == "" and tour.from_name("DSC00412") == ""


def test_depth_input_size_is_multiples_of_14():
    for w, h in [(1920, 1280), (1080, 1920), (800, 800), (4000, 1000)]:
        a, b = depth.size_for(w, h)
        assert a % 14 == 0 and b % 14 == 0 and max(a, b) == 518


def test_near_duplicates_are_left_out(tmp_path):
    a, b = photo(tmp_path / "a.jpg", 1), photo(tmp_path / "b.jpg", 4)
    assert tour.distinct([a, a.copy(), b]) == [0, 2]


def test_model_puts_rooms_in_walking_order(tmp_path):
    for i, n in enumerate(["a.jpg", "b.jpg", "c.jpg", "d.jpg"]):
        photo(tmp_path / n, i + 1)
    eyes = Eyes(['{"room": "backyard"}', '<think>hm {x}</think> {"room": "kitchen"}', "no idea", '{"room": "front"}'])
    t = asyncio.run(tour.build(tmp_path, "12 Main St", llm=eyes, depth_fn=flat, out=tmp_path / "out", log=lambda s: None))
    assert [s["label"] for s in t["spots"]] == ["Exterior", "Kitchen", "Interior", "Backyard"] and eyes.asked == 4
    out = tmp_path / "out"
    assert [s["photo"] for s in t["spots"]] == [f"photos/0{i}.jpg" for i in range(4)]
    assert all((out / s["photo"]).exists() and (out / s["depth"]).exists() for s in t["spots"])
    page = (out / "index.html").read_text()
    assert "__TOUR__" not in page and "<title>12 Main St</title>" in page and '"label": "Kitchen"' in page
    assert json.loads((out / "tour.json").read_text())["spots"][0]["aspect"] == 1.5


def test_without_a_model_file_order_stands_and_names_label(tmp_path):
    for i, n in enumerate(["01-yard.jpg", "02-kitchen.jpg", "03-IMG.jpg"]):
        photo(tmp_path / n, i + 1)
    for llm in (None, Eyes([], up=False)):
        t = asyncio.run(tour.build(tmp_path, llm=llm, depth_fn=flat, out=tmp_path / "out", log=lambda s: None))
        assert [s["label"] for s in t["spots"]] == ["Backyard", "Kitchen", "Interior"]
    kept = asyncio.run(tour.build(tmp_path, llm=Eyes(["x"]), depth_fn=flat, keep_order=True, out=tmp_path / "out", log=lambda s: None))
    assert [s["file"] for s in kept["spots"]] == ["01-yard.jpg", "02-kitchen.jpg", "03-IMG.jpg"]


def test_title_cannot_break_the_page(tmp_path):
    photo(tmp_path / "a.jpg", 1)
    asyncio.run(tour.build(tmp_path, '</script><b>"x"', depth_fn=flat, out=tmp_path / "out", log=lambda s: None))
    page = (tmp_path / "out" / "index.html").read_text()
    assert page.count("</script>") == 1 and "<title>&lt;/script&gt;" in page


def test_cover_fills_the_screen():
    kx, ky = tour.cover(1.5, 16 / 9)          # a 3:2 photo on a wide screen: full width, cropped top and bottom
    assert kx == tour.OVERSCAN and ky < kx
    kx, ky = tour.cover(1.5, 9 / 16)          # the same photo upright: full height, a slice of the width
    assert ky == tour.OVERSCAN and kx < ky


def test_numbered_files_sort_as_numbers(tmp_path):
    assert sorted([tmp_path / n for n in ["10.jpg", "2.jpg", "1.jpg"]], key=tour.natural) == [tmp_path / n for n in ["1.jpg", "2.jpg", "10.jpg"]]


PLAN = ('[{"name": "LIVING", "x": 260, "y": 340}, {"name": "BEDROOM", "x": 260, "y": 668}, {"name": "DINING", "x": 420, "y": 295}, '
        '{"name": "KITCHEN", "x": 570, "y": 315}, {"name": "4PC BATH", "x": 390, "y": 720}, {"name": "F/P", "x": 270, "y": 180}, {"name": "CLO", "x": 5000, "y": 1}]')


def test_floor_plan_stays_out_of_the_walk_and_orders_it(tmp_path):
    for i, n in enumerate(["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg", "10.jpg"]):
        photo(tmp_path / n, i + 1)
    eyes = Eyes(['{"room": "bathroom"}', '{"room": "kitchen"}', '{"room": "front"}', '{"room": "dining"}', '{"room": "backyard"}', '{"room": "plan"}', PLAN])
    out = tmp_path / "out"
    t = asyncio.run(tour.build(tmp_path, "Home", llm=eyes, depth_fn=flat, out=out, log=lambda s: None))
    # outside first, then the plan's walk (living -> dining -> kitchen -> ... nearest room each time), backyard last
    assert [s["room"] for s in t["spots"]] == ["front", "dining", "kitchen", "bathroom", "backyard"]
    plan = t["plans"][0]
    assert plan["file"] == "10.jpg" and (out / plan["image"]).exists() and not (out / "photos" / "05.jpg").exists()
    assert [r["room"] for r in plan["rooms"]] == ["living", "bedroom", "dining", "kitchen", "bathroom"]      # unnamed and off-page points dropped
    assert plan["rooms"][0] == {"room": "living", "name": "Living room", "x": 0.26, "y": 0.34}
    assert tour.path(plan["rooms"]) == ["living", "dining", "kitchen", "bathroom", "bedroom"]

    # a corrected rooms.txt is used on the next run, and neither the photos nor the plan are shown to the model again
    rooms = out / "rooms.txt"
    assert "1.jpg = bathroom" in rooms.read_text() and "10.jpg = plan" in rooms.read_text()
    rooms.write_text(rooms.read_text().replace("1.jpg = bathroom", "1.jpg = living"))
    quiet = Eyes([])
    t = asyncio.run(tour.build(tmp_path, "Home", llm=quiet, depth_fn=flat, out=out, log=lambda s: None))
    assert [s["room"] for s in t["spots"]] == ["front", "living", "dining", "kitchen", "backyard"] and quiet.asked == 0
    assert t["plans"][0]["rooms"][0]["room"] == "living"


def test_plan_walls_become_a_grid():
    im = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((200, 150, 600, 450), outline="black", width=14)          # a room
    d.rectangle((380, 150, 430, 163), fill="white")                       # a doorway in the top wall
    d.rectangle((200, 280, 213, 330), fill=(70, 150, 220))                # a window in the left wall
    d.text((300, 300), "LIVING", fill="black")                            # lettering is not a wall
    d.line((50, 560, 750, 560), fill="black", width=2)                    # nor is a thin rule
    sh = tour.shell(im)
    at = lambda x, y: sh["grid"][int((y / 600 - sh["y0"]) / (sh["y1"] - sh["y0"]) * sh["h"]) * sh["w"] + int((x / 800 - sh["x0"]) / (sh["x1"] - sh["x0"]) * sh["w"])]
    assert at(300, 156) == "1" and at(593, 300) == "1" and at(300, 443) == "1"      # walls
    assert at(405, 156) == "0" and at(400, 300) == "0" and at(320, 305) == "0"      # doorway, floor, lettering
    assert at(206, 305) == "2" and len(sh["grid"]) == sh["w"] * sh["h"]             # window
    assert 0.05 < sh["cell"] < 0.07                                                 # 14 px wall = 0.16 m, 5 px squares
    assert tour.shell(Image.new("RGB", (400, 300), "white")) is None


def test_camera_is_found_from_depth_against_the_plan():
    """An L-shaped view: standing in the south-west corner of a 2:1 room looking north-east. The depth along the eye line
    is made from the plan itself, so the finder must give back the square and the direction it was made from."""
    import math
    im = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((150, 150, 750, 450), outline="black", width=14)
    d.rectangle((150, 150, 450, 300), fill="black")                       # a block in one corner: the room is not symmetric
    plan = {"shell": tour.shell(im), "rooms": [{"room": "living", "name": "Living room", "x": 0.62, "y": 0.6}]}
    f = tour.Finder(plan)
    i = int(np.argmin(np.hypot(f.pos[:, 0] - f.pos[:, 0].min(), f.pos[:, 1] - f.pos[:, 1].max())))    # bottom-left open square
    yaw, fov = math.radians(60), 98
    al = np.arctan(np.linspace(-1, 1, 518) * math.tan(math.radians(fov) / 2))
    rays = (np.round((yaw + al) / (2 * np.pi) * f.RAYS).astype(int)) % f.RAYS
    near = 1.0 / (f.dist[i][rays] * np.cos(al))
    depth_map = np.tile((near - near.min()) / (near.max() - near.min()), (350, 1)).astype(np.float32)
    got = f.find("living", Image.new("RGB", (518, 350), "white"), depth_map)
    sh = plan["shell"]
    assert abs(got["x"] - (sh["x0"] + (f.pos[i, 0] + .5) / sh["w"] * (sh["x1"] - sh["x0"]))) < 0.03
    assert abs(math.degrees(got["yaw"]) - 60) <= 4 and got["fov"] == 98 and got["fit"] > 0.95
    assert f.find("kitchen", Image.new("RGB", (518, 350)), depth_map) is None


def test_cameras_txt_is_read(tmp_path):
    (tmp_path / "cameras.txt").write_text("# note\n10.jpg = 1 0.31 0.43 90 118\nbad = x\n")
    assert tour.read_cameras(tmp_path / "cameras.txt") == {"10.jpg": {"plan": 0, "x": 0.31, "y": 0.43, "yaw": 1.571, "fov": 118.0}}


def test_editor_save_rewrites_the_tour(tmp_path):
    photo(tmp_path / "a.jpg", 1)
    out = tmp_path / "out"
    asyncio.run(tour.build(tmp_path, "Home", depth_fn=flat, out=out, log=lambda s: None))
    t = json.loads((out / "tour.json").read_text())
    t["plans"] = [{"file": "p.jpg", "image": "plans/0.jpg", "rooms": [], "shell": None}]
    (out / "tour.json").write_text(json.dumps(t))
    assert tour.save_cameras(out, {"a.jpg": {"plan": 0, "x": 0.25, "y": 0.5, "yaw": 7.0, "fov": 100}, "zz.jpg": {"plan": 0}, "bad": 3}) == 1
    cam = json.loads((out / "tour.json").read_text())["spots"][0]["camera"]
    assert cam == {"plan": 0, "x": 0.25, "y": 0.5, "yaw": round(7.0 % (2 * 3.141592653589793), 3), "fov": 100.0, "by": "hand"}
    assert "a.jpg = 1 0.25 0.5 41 100" in (out / "cameras.txt").read_text() and '"by": "hand"' in (out / "index.html").read_text()
    assert tour.save_cameras(out, {"a.jpg": {"plan": 5, "x": 0, "y": 0, "yaw": 0, "fov": 90}}) == 0       # no such plan


def test_model_walls_route_and_paint():
    from vision import tour_model as tm
    solid = np.zeros((40, 60), bool)
    solid[5, 5:55] = solid[34, 5:55] = solid[5:35, 5] = solid[5:35, 54] = True      # a room
    solid[5:35, 30] = True; solid[15:25, 30] = False                                 # split in two by a wall with a doorway a metre wide
    runs = tm.wall_runs(solid)
    assert (6, 6, 30, 6, 0, 1) in runs                    # the top wall's inner face, left room: it faces down the plan, into the room
    assert all((r[2] - r[0]) * (r[3] - r[1]) == 0 for r in runs)
    tight = tm.tight_of(solid, 0.1, body=0.2)
    way = tm.route(tight, 0.1, (1.5, 1.5), (4.5, 1.5))    # from the left room to the right one: only through the doorway
    assert any(abs(px - 3.05) < 0.5 and 1.5 <= pz <= 2.5 for px, pz in way) and way[0] == (1.5, 1.5) and way[-1] == (4.5, 1.5)
    red = np.zeros((50, 80, 3), np.float32); red[..., 0] = 1
    painter = tm.Painter(solid, 0.1, [{"x": 1.5, "z": 2.0, "yaw": 0.0, "tan": 1.0, "aspect": 1.6, "img": red}])      # a camera in the left room, looking up the plan
    px = np.array([1.5, 1.5, 4.5], np.float32); pz = np.array([0.61, 3.39, 0.61], np.float32); py = np.full(3, 1.4, np.float32)
    col = painter.paint(px, py, pz, (0, 0, 1), (0.5, 0.5, 0.5))
    assert col[0, 0] > 0.95 and col[0, 1] < 0.05          # the wall it faces takes the photo
    assert abs(col[1, 0] - 0.5) < 0.01                    # the wall behind it does not
    assert abs(col[2, 0] - 0.5) < 0.01                    # nor does the other room, behind the dividing wall
    w = tm.walk({"cell": 0.1}, solid, [{"file": "a", "x": 1.5, "z": 1.5, "yaw": 0.0}, {"file": "b", "x": 4.5, "z": 1.5, "yaw": 1.0}], [])
    assert [m["file"] for m in w["stops"]] == ["a", "b"] and len(w["frames"]) > 5 * w["fps"]
    assert not any(solid[int(z / 0.1), int(x / 0.1)] for x, z, _ in w["frames"])      # the camera never passes through a wall


def test_four_shots_from_one_spot_are_placed_together():
    """One wall seen square-on fits many places; the four quarter-turn views from one spot fit only one."""
    import math
    im = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((150, 150, 750, 450), outline="black", width=14)
    d.rectangle((150, 150, 330, 250), fill="black")                       # a block in one corner
    plan = {"shell": tour.shell(im), "rooms": [{"room": "living", "name": "Living room", "x": 0.6, "y": 0.6}]}
    f = tour.Finder(plan)
    i = int(np.argmin(np.hypot(f.pos[:, 0] - (f.pos[:, 0].min() + 20), f.pos[:, 1] - (f.pos[:, 1].max() - 9))))
    fov, shots = 98, []
    al = np.arctan(np.linspace(-1, 1, 518) * math.tan(math.radians(fov) / 2))
    for k in range(4):
        rays = (np.round((math.radians(20 + 90 * k) + al) / (2 * np.pi) * f.RAYS).astype(int)) % f.RAYS
        near = 1.0 / (f.dist[i][rays] * np.cos(al))
        shots.append((Image.new("RGB", (518, 350), "white"), np.tile((near - near.min()) / (near.max() - near.min() + 1e-9), (350, 1)).astype(np.float32)))
    got = f.find_group("living", shots, [0, 90, 180, 270])
    sh = plan["shell"]
    assert [round(math.degrees(g["yaw"])) for g in got] == [20, 110, 200, 290] or all(abs((math.degrees(g["yaw"]) - (20 + 90 * k) + 180) % 360 - 180) <= 3 for k, g in enumerate(got))
    assert all(abs(g["x"] - (sh["x0"] + (f.pos[i, 0] + .5) / sh["w"] * (sh["x1"] - sh["x0"]))) < 0.02 and g["group"] == 4 for g in got)
