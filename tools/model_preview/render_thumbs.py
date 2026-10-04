# Blender CLI: render quick orientation-check thumbnails for ship GLBs.
# Usage:
#   blender --background --python render_thumbs.py -- <out_dir> <file.glb> [more.glb ...]
# Produces <out_dir>/<stem>__top.png and <stem>__iso.png (Workbench, texture color).
import math
import os
import sys

import bpy
from mathutils import Vector

OUT_DIR = sys.argv[sys.argv.index("--") + 1]
FILES = sys.argv[sys.argv.index("--") + 2:]


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "TEXTURE"
    sc.display.shading.show_shadows = False
    sc.render.resolution_x = 360
    sc.render.resolution_y = 300
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new("w") if sc.world is None else sc.world
    sc.world.color = (0.05, 0.06, 0.09)


def add_camera(name, location, target):
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.01
    cam_data.clip_end = 10 ** 9
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = location
    direction = Vector(target) - Vector(location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def frame(points, cam):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    center = Vector((sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)))
    radius = max(
        max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
    ) * 0.62 + 0.001
    cam_data = cam.data
    cam_data.ortho_scale = radius * 2.05
    return center


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


for path in FILES:
    stem = os.path.splitext(os.path.basename(path))[0][:42]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render()
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as error:
        print(f"THUMB_FAIL {path}: {error}")
        continue
    pts = []
    for o in bpy.context.scene.objects:
        if o.type == "MESH":
            for v in o.data.vertices:
                w = o.matrix_world @ v.co
                pts.append((w.x, w.y, w.z))
    if not pts:
        print(f"THUMB_FAIL {path}: no mesh")
        continue
    center = (sum(p[0] for p in pts) / len(pts),
              sum(p[1] for p in pts) / len(pts),
              sum(p[2] for p in pts) / len(pts))
    span = max(
        max(p[0] for p in pts) - min(p[0] for p in pts),
        max(p[1] for p in pts) - min(p[1] for p in pts),
        max(p[2] for p in pts) - min(p[2] for p in pts),
    )
    d = span * 1.1 + 0.01

    cam_top = add_camera("top", (center[0], center[1] + d, center[2]), center)
    frame(pts, cam_top)
    render_to(os.path.join(OUT_DIR, f"{stem}__top.png"))

    cam_iso = add_camera("iso",
                         (center[0] + d * 0.75, center[1] - d * 0.6, center[2] + d * 0.55),
                         center)
    frame(pts, cam_iso)
    render_to(os.path.join(OUT_DIR, f"{stem}__iso.png"))
    print(f"THUMB_OK {stem}")
