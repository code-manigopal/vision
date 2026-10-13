"""Run inside Blender:  blender -b --python scripts/dummy_home_render.py [-- only <n>]

Builds the made-up home described in data/dummy_home/spec.json (walls with door and window openings, a floor per room,
box furniture, daylight) and photographs it from every camera in the spec into data/dummy_home/one/ and four/.
"""
import json
import math
import sys
from pathlib import Path

import bpy

OUT = Path(__file__).resolve().parent.parent / "data" / "dummy_home"
spec = json.loads((OUT / "spec.json").read_text())
only = int(sys.argv[sys.argv.index("only") + 1]) if "only" in sys.argv else 0
T, HGT = spec["t"], 2.5
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

def material(name, colour, rough=0.6, nodes=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*colour, 1)
    b.inputs["Roughness"].default_value = rough
    if nodes:
        nodes(m.node_tree, b)
    return m

def box(x0, z0, x1, z1, y0, y1, mat):                  # plan x, z and height -> Blender (x, -z, height)
    bpy.ops.mesh.primitive_cube_add(location=((x0 + x1) / 2, -(z0 + z1) / 2, (y0 + y1) / 2))
    o = bpy.context.object
    o.scale = (abs(x1 - x0) / 2, abs(z1 - z0) / 2, abs(y1 - y0) / 2)
    o.data.materials.append(mat)
    return o

def planks(tree, bsdf):                                # floorboards: bands of two browns
    w, ramp = tree.nodes.new("ShaderNodeTexWave"), tree.nodes.new("ShaderNodeValToRGB")
    w.inputs["Scale"].default_value, w.inputs["Distortion"].default_value, w.inputs["Detail"].default_value = 9, 0.6, 2
    ramp.color_ramp.elements[0].color, ramp.color_ramp.elements[1].color = (0.36, 0.20, 0.09, 1), (0.55, 0.33, 0.16, 1)
    tree.links.new(w.outputs["Color"], ramp.inputs["Fac"]); tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

def tiles(tree, bsdf):
    c = tree.nodes.new("ShaderNodeTexChecker")
    c.inputs["Scale"].default_value = 14
    c.inputs["Color1"].default_value, c.inputs["Color2"].default_value = (0.78, 0.78, 0.76, 1), (0.62, 0.63, 0.63, 1)
    tree.links.new(c.outputs["Color"], bsdf.inputs["Base Color"])

wall_m = material("wall", (0.86, 0.84, 0.79), 0.9)
floors = {"wood": material("wood", (0.45, 0.27, 0.13), 0.45, planks), "tile": material("tile", (0.7, 0.7, 0.7), 0.3, tiles)}
for a, b, opens in [(w["a"], w["b"], w["open"]) for w in spec["walls"]]:
    along_x = a[1] == b[1]
    lo, hi = (a[0], b[0]) if along_x else (a[1], b[1])
    def piece(s, e, y0, y1):
        if e - s < 1e-6:
            return
        if along_x:
            box(s, a[1] - T / 2, e, a[1] + T / 2, y0, y1, wall_m)
        else:
            box(a[0] - T / 2, s, a[0] + T / 2, e, y0, y1, wall_m)
    at = lo - T / 2
    for s, e, kind in sorted(opens):
        piece(at, s, 0, HGT)
        piece(s, e, 2.05, HGT)                                         # over a door or a window
        if kind == "window":
            piece(s, e, 0, 0.9)                                        # under a window
        at = e
    piece(at, hi + T / 2, 0, HGT)
for r in spec["rooms"]:
    for x0, z0, x1, z1 in r["rects"]:
        box(x0, z0, x1, z1, -0.05, 0.0, floors[r["floor"]])
W, H = spec["size"]
box(-T / 2, -T / 2, W + T / 2, H + T / 2, HGT, HGT + 0.1, material("ceiling", (0.92, 0.92, 0.9), 0.9))
box(-30, -30, W + 30, H + 30, -0.2, -0.06, material("grass", (0.16, 0.30, 0.10), 0.95))
mats = {}
for x0, z0, x1, z1, y0, y1, col in spec["boxes"]:
    box(x0, z0, x1, z1, y0, y1, mats.setdefault(tuple(col), material("f", col, 0.55)))

# daylight: a bright sky, a low sun, and a soft lamp under each room's ceiling so no room is a cave
world = bpy.data.worlds.new("sky")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value, bg.inputs["Strength"].default_value = (0.55, 0.72, 1.0, 1), 0.7
scene.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy, sun.rotation_euler = 1.5, (math.radians(55), 0, math.radians(35))
scene.collection.objects.link(sun)
for r in spec["rooms"]:
    x0, z0, x1, z1 = r["rects"][0]
    lamp = bpy.data.objects.new("lamp", bpy.data.lights.new("lamp", "AREA"))
    lamp.data.energy, lamp.data.size = 1.6 * (x1 - x0) * (z1 - z0), 0.9
    lamp.location = ((x0 + x1) / 2, -(z0 + z1) / 2, HGT - 0.05)
    scene.collection.objects.link(lamp)

scene.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = True
    scene.cycles.device = "GPU"
except Exception:
    pass
scene.cycles.samples, scene.cycles.use_denoising = 32, True
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = -0.6
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1350, 900, 100
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 92
cam_data = bpy.data.cameras.new("c")
cam_data.sensor_width, cam_data.clip_start = 36, 0.05
cam = bpy.data.objects.new("c", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
todo = spec["cameras"][:only] if only else spec["cameras"]
for c in todo:
    cam_data.lens = 18 / math.tan(math.radians(c["fov"]) / 2)
    cam.location = (c["x"], -c["z"], 1.45)
    cam.rotation_euler = (math.pi / 2, 0, -math.radians(c["yaw"]))
    (OUT / c["set"]).mkdir(exist_ok=True)
    scene.render.filepath = str(OUT / c["set"] / c["file"])
    bpy.ops.render.render(write_still=True)
