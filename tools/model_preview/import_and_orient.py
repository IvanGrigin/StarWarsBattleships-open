# Blender CLI: import a downloaded glTF scene, orient it by symmetry, export GLB.
# Usage:
#   blender --background --python import_and_orient.py -- <scene.gltf> <out.glb>
import math
import sys

import bpy
import numpy as np
from mathutils import Matrix

THRESHOLD_DEG = 12.0
RNG_A = np.random.default_rng(7)
RNG_B = np.random.default_rng(11)


def collect_points(objs):
    pts = []
    for o in objs:
        if o.type != "MESH":
            continue
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            pts.append((w.x, w.y, w.z))
    return np.array(pts)


def symmetry_rotation(pts):
    pts = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts, full_matrices=False)
    axes = vt
    ext = (pts @ axes.T).std(axis=0)
    if ext.max() / max(ext.min(), 1e-9) < 1.5:
        return None, 0.0
    sample = pts[RNG_A.choice(len(pts), min(2500, len(pts)), replace=False)]
    ref = pts[RNG_B.choice(len(pts), min(7000, len(pts)), replace=False)]

    def mirror_score(ai):
        a = axes[ai]
        d = sample @ a
        mirrored = sample - np.outer(2.0 * d, a)
        mins = np.empty(len(mirrored))
        for i in range(0, len(mirrored), 400):
            chunk = mirrored[i:i + 400]
            dists = np.linalg.norm(ref[None, :, :] - chunk[:, None, :], axis=2)
            mins[i:i + 400] = dists.min(axis=1)
        return float(mins.mean())

    up_i = int(np.argmax([-ext[i] for i in range(3)]))  # height = smallest extent
    wing_candidates = [i for i in range(3) if i != up_i]
    wings_i = min(wing_candidates, key=mirror_score)
    len_i = [i for i in range(3) if i not in (up_i, wings_i)][0]
    L, W, U = axes[len_i], axes[wings_i], axes[up_i]
    dl = pts @ L
    span = dl.max() - dl.min()
    hi = pts[dl > dl.max() - 0.18 * span]
    lo = pts[dl < dl.min() + 0.18 * span]
    nose = L if float(np.std(hi @ W) + np.std(hi @ U)) <= float(np.std(lo @ W) + np.std(lo @ U)) else -L
    up = U if U[1] >= 0 else -U
    M = np.column_stack([nose, np.cross(nose, up), up])
    # Целевые оси ДО экспорта (Blender Z-up): нос +Y, спин +X, dorsal +Z.
    # Экспортёр glTF применяет (x, z, -y), итого в glTF: нос -Z, dorsal +Y.
    T = np.column_stack([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    R = T @ M.T
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))))
    return R, angle


argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = list(bpy.context.scene.objects)
pts = collect_points(objs)
R, angle = (None, 0.0)
if len(pts) >= 100:
    R, angle = symmetry_rotation(pts)
if R is not None and angle >= THRESHOLD_DEG:
    rot = Matrix([[R[0][0], R[0][1], R[0][2], 0.0],
                  [R[1][0], R[1][1], R[1][2], 0.0],
                  [R[2][0], R[2][1], R[2][2], 0.0],
                  [0.0, 0.0, 0.0, 1.0]])
    for o in objs:
        if o.parent is None:
            o.matrix_world = rot @ o.matrix_world
    print(f"ORIENT rotated {angle:.1f} deg")
else:
    print(f"ORIENT kept as-is ({angle:.1f} deg)")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
print(f"GLB_OK {dst}")
