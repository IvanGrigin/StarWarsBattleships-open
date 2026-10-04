# Blender CLI: convert textureless STL/OBJ candidates to GLB with correct orientation.
# Usage:
#   blender --background --python convert_to_glb.py -- <src> <dst> <stl|obj> [extra_x_deg]
# Blender is Z-up; the glTF exporter emits Y-up automatically, which fixes
# print-oriented STL files (the reason they stood on their nose in three.js).
import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst, kind = argv[0], argv[1], argv[2]
extra_x_deg = float(argv[3]) if len(argv) > 3 else 0.0

bpy.ops.wm.read_factory_settings(use_empty=True)

if kind == "stl":
    try:
        bpy.ops.wm.stl_import(filepath=src)
    except AttributeError:
        bpy.ops.import_mesh.stl(filepath=src)
elif kind == "obj":
    try:
        bpy.ops.wm.obj_import(filepath=src)
    except AttributeError:
        bpy.ops.import_scene.obj(filepath=src)
else:
    raise SystemExit("unsupported kind: %s" % kind)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported from %s" % src)

if extra_x_deg:
    for o in meshes:
        o.rotation_mode = "XYZ"
        o.rotation_euler.rotate_axis("X", math.radians(extra_x_deg))

# Общий transform в вершины: иначе экспортер вынесет поворот в ноду сцены,
# а нам нужен «правильный» файл сам по себе.
bpy.context.view_layer.objects.active = meshes[0]
for o in bpy.context.scene.objects:
    o.select_set(o.type == "MESH")
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
tris = sum(len(o.data.polygons) for o in meshes)
print("CONVERTED %s -> %s (%d objects, %d faces, extra_x=%.1f deg)"
      % (src, dst, len(meshes), tris, extra_x_deg))
