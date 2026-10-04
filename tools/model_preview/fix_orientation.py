# Blender CLI: symmetry-based orientation fix for ship GLBs.
# A ship is roughly bilaterally symmetric: the mirror plane contains the
# nose-tail axis and the up axis; the normal of that plane is the wingspan.
# Usage:
#   blender --background --python fix_orientation.py -- <file.glb> [more.glb ...]
# For each file: analyze, report the deviation angle, rotate only if > THRESHOLD.
# The original is copied to <dir>/backup_original/ before overwriting.
import copy
import math
import os
import shutil
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
            pts.append(o.matrix_world @ v.co)
    return np.array([[p.x, p.y, p.z] for p in pts])


def symmetry_plane(pts):
    pts = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts, full_matrices=False)
    axes = vt
    ext = (pts @ axes.T).std(axis=0)
    if ext.max() / max(ext.min(), 1e-9) < 1.5:
        return None, 0.0  # near-isotropic (sphere): nothing to fix
    sample = pts[RNG_A.choice(len(pts), min(2500, len(pts)), replace=False)]
    ref = pts[RNG_B.choice(len(pts), min(7000, len(pts)), replace=False)]
    best = None
    for ai in range(3):
        a = axes[ai]
        d = sample @ a
        mirrored = sample - np.outer(2.0 * d, a)
        mins = np.empty(len(mirrored))
        for i in range(0, len(mirrored), 400):
            chunk = mirrored[i:i + 400]
            dists = np.linalg.norm(ref[None, :, :] - chunk[:, None, :], axis=2)
            mins[i:i + 400] = dists.min(axis=1)
        score = float(mins.mean())
        if best is None or score < best[0]:
            best = (score, ai)
    wings_i = best[1]
    # высота корабля — ось с минимальным размахом; зеркальная (крыльевая)
    # плоскость выбирается только между двумя оставшимися осями, иначе корабль
    # с почти симметричным профилем встаёт на хвост
    up_i = int(np.argmax([-ext[i] for i in range(3)]))  # argmin ext
    wing_candidates = [i for i in range(3) if i != up_i]
    # пересчёт score только для двух кандидатов
    scores = {}
    for ai in wing_candidates:
        a = axes[ai]
        d = sample @ a
        mirrored = sample - np.outer(2.0 * d, a)
        mins = np.empty(len(mirrored))
        for i in range(0, len(mirrored), 400):
            chunk = mirrored[i:i + 400]
            dists = np.linalg.norm(ref[None, :, :] - chunk[:, None, :], axis=2)
            mins[i:i + 400] = dists.min(axis=1)
        scores[ai] = float(mins.mean())
    wings_i = min(wing_candidates, key=lambda i: scores[i])
    others = [i for i in range(3) if i != wings_i]
    len_i = [i for i in others if i != up_i][0]
    L, W, U = axes[len_i], axes[wings_i], axes[up_i]
    dl = pts @ L
    span = dl.max() - dl.min()
    hi = pts[dl > dl.max() - 0.18 * span]
    lo = pts[dl < dl.min() + 0.18 * span]
    spread_hi = float(np.std(hi @ W) + np.std(hi @ U))
    spread_lo = float(np.std(lo @ W) + np.std(lo @ U))
    nose = L if spread_hi <= spread_lo else -L
    up = U if U[1] >= 0 else -U  # сохраняем текущий верх, если не перевёрнут
    M = np.column_stack([nose, np.cross(nose, up), up])
    T = np.column_stack([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    R = T @ M.T
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))))
    return R, angle


def process(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = list(bpy.context.scene.objects)
    pts = collect_points(objs)
    if len(pts) < 100:
        print(f"SKIP {path}: too few points")
        return
    R, angle = symmetry_plane(pts)
    if R is None:
        print(f"SKIP {path}: isotropic shape")
        return
    if angle < THRESHOLD_DEG:
        print(f"OK {os.path.basename(path)}: deviation {angle:.1f} deg (< {THRESHOLD_DEG}) — not touched")
        return
    rot = Matrix([[R[0][0], R[0][1], R[0][2], 0.0],
                  [R[1][0], R[1][1], R[1][2], 0.0],
                  [R[2][0], R[2][1], R[2][2], 0.0],
                  [0.0, 0.0, 0.0, 1.0]])
    roots = [o for o in objs if o.parent is None]
    for o in roots:
        o.matrix_world = rot @ o.matrix_world
    bpy.context.view_layer.objects.active = objs[0]
    for o in bpy.context.scene.objects:
        o.select_set(o.type == "MESH")
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    backup_dir = os.path.join(os.path.dirname(path), "backup_original")
    os.makedirs(backup_dir, exist_ok=True)
    backup = os.path.join(backup_dir, os.path.basename(path))
    if not os.path.exists(backup):
        shutil.copyfile(path, backup)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")
    print(f"FIXED {os.path.basename(path)}: rotated {angle:.1f} deg (backup in backup_original/)")


argv = sys.argv[sys.argv.index("--") + 1:]
for p in argv:
    process(p)
