"""Run inside Blender (no window):  blender -b --python scripts/tour_film.py -- <model dir> <frames dir> <width> <height> [last frame]

Films a tour's walk-in model: loads model.obj with its baked photo textures, puts a camera on the route in path.json and
renders one picture per frame. The surfaces glow with the photos' own colours (no lamps: the photos already hold the room's
light), so what comes out is the photos seen from a moving camera. `python -m vision tour film <slug>` calls this.
"""
import json
import math
import sys
from pathlib import Path

import bpy

model, frames, width, height = Path(sys.argv[sys.argv.index("--") + 1]), Path(sys.argv[sys.argv.index("--") + 2]), int(sys.argv[sys.argv.index("--") + 3]), int(sys.argv[sys.argv.index("--") + 4])
last = int(sys.argv[sys.argv.index("--") + 5]) if len(sys.argv) > sys.argv.index("--") + 5 else 0
path = json.loads((model / "path.json").read_text())

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=str(model / "model.obj"))          # the file's y-up becomes Blender's z-up: (x, y, z) -> (x, -z, y)
for mat in bpy.data.materials:                                     # each surface shows its picture at full strength, unlit
    tex = model / f"{mat.name}.jpg"
    if not tex.exists():
        continue
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    img = nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(str(tex))
    img.extension = "EXTEND"
    glow, out = nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeOutputMaterial")
    links.new(img.outputs["Color"], glow.inputs["Color"])
    links.new(glow.outputs["Emission"], out.inputs["Surface"])

scene = bpy.context.scene
world = bpy.data.worlds.new("sky")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.62, 0.69, 0.77, 1)
scene.world = world
cam_data = bpy.data.cameras.new("walker")
cam_data.sensor_width, cam_data.lens, cam_data.clip_start, cam_data.clip_end = 36, 17, 0.03, 100      # a wide lens, about 93 degrees across
cam = bpy.data.objects.new("walker", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
n = len(path["frames"]) if not last else min(last, len(path["frames"]))
for i, (x, z, yaw) in enumerate(path["frames"][:n]):
    cam.location = (x, -z, path["eye"])
    cam.rotation_euler = (math.pi / 2, 0, -yaw)
    cam.keyframe_insert("location", frame=i + 1)
    cam.keyframe_insert("rotation_euler", frame=i + 1)

for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
scene.view_settings.view_transform = "Standard"                   # keep the photos' colours as they are
scene.render.use_motion_blur = True
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, 100
scene.render.fps = path["fps"]
scene.frame_start, scene.frame_end = 1, n
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 92
scene.render.filepath = str(frames / "f")
bpy.ops.render.render(animation=True)
