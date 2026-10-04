# Blender CLI: снимок одной модели для карточки корабля.
#   blender --background --python blender_card_render.py -- <in.glb> <out.png> <qx> <qy> <qz> <qw>
# q — поворот владельца из model_reviews.json (кватернион three.js / glTF, Y вверх).
# Ракурс — как по умолчанию на странице ориентации: спереди-справа-сверху,
# нос (glTF −Z) смотрит на зрителя. Фон прозрачный: карточка кладёт снимок на
# свой звёздный фон.
import math
import sys

import bpy
from mathutils import Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], argv[1]
qx, qy, qz, qw = (float(v) for v in argv[2:6])
CAM_DIR = tuple(float(v) for v in argv[6:9]) if len(argv) >= 9 else (0.55, -1.0, 0.45)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
scene = bpy.context.scene

# корень: все объекты верхнего уровня — под пустышку, на неё — поворот владельца.
# Проверено на X-wing против страницы ориентации: после переподчинения модель
# лежит в осях glTF (Y вверх, нос −Z), поэтому сначала применяется поворот
# владельца как есть (он задан в тех же осях), затем +90° вокруг X переводит
# glTF (Y вверх) в оси Blender (Z вверх): нос −Z → +Y, верх +Y → +Z.
root = bpy.data.objects.new("card_root", None)
scene.collection.objects.link(root)
for o in list(scene.objects):
    if o is not root and o.parent is None:
        o.parent = root
root.rotation_mode = "QUATERNION"
to_blender = Quaternion((1.0, 0.0, 0.0), math.radians(90))
root.rotation_quaternion = to_blender @ Quaternion((qw, qx, qy, qz))
bpy.context.view_layer.update()

# габарит всех мешей после поворота → центр в начало координат, масштаб к 1
lo = Vector((1e18, 1e18, 1e18)); hi = Vector((-1e18, -1e18, -1e18))
for o in scene.objects:
    if o.type != "MESH":
        continue
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
center = (lo + hi) / 2
size = max((hi - lo).length, 1e-6)
root.location = -center
bpy.context.view_layer.update()
k = 2.0 / size
root.scale = (k, k, k)
root.location = -center * k
bpy.context.view_layer.update()

# камера: спереди (+Y — нос), справа (+X), сверху (+Z)
# Направление подобрано сверкой со страницей ориентации (нос к зрителю,
# вправо-вниз). Модель вписана в сферу радиуса 1; объектив 50 мм, кадр 3:2 —
# вертикальный угол 27°, дистанция 4.3 вмещает сферу целиком.
cam_data = bpy.data.cameras.new("cam"); cam_data.lens = 50
cam = bpy.data.objects.new("cam", cam_data); scene.collection.objects.link(cam)
direction = Vector(CAM_DIR).normalized()
cam.location = direction * 4.3
cam.rotation_mode = "QUATERNION"
cam.rotation_quaternion = (-direction).to_track_quat("-Z", "Z")
scene.camera = cam

def light(name, kind, energy, loc, color=(1, 1, 1), size=1.0):
    d = bpy.data.lights.new(name, kind); d.energy = energy; d.color = color
    if hasattr(d, "size"): d.size = size
    o = bpy.data.objects.new(name, d); o.location = loc
    o.rotation_mode = "QUATERNION"; o.rotation_quaternion = (-Vector(loc)).normalized().to_track_quat("-Z", "Z")
    scene.collection.objects.link(o)

light("key", "SUN", 3.2, (2.5, 3.0, 4.0))
light("fill", "SUN", 1.0, (-3.0, 1.5, 1.0), (0.75, 0.85, 1.0))
light("rim", "SUN", 2.2, (0.0, -4.0, 2.5), (1.0, 0.85, 0.7))

world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.025, 0.04, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.6

scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.eevee.taa_render_samples = 32
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = 720, 480
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"
scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("CARD_RENDER_OK", OUT)
