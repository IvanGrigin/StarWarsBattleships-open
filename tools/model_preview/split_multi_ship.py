# Blender CLI: detect and split multi-ship GLB files into separate ships.
# Ships inside one file are found as spatial clusters of mesh objects whose
# world bounding boxes do not overlap. Single-ship files are kept untouched.
#
# Usage:
#   blender --background --python split_multi_ship.py -- <out_report.json> <file.glb> [more.glb ...]
#
# Splits are written next to the source as <stem}__s1.glb, __s2.glb, ...
import json
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT_REPORT = argv[0]
FILES = argv[1:]

# Кластеры считаем разными кораблями, если их bbox не пересекаются с запасом 8%
# от наибольшего габарита сцены. Кластеры мельче 12% габарита крупнейшего
# считаем мусором/подставками и не экспортируем отдельными кораблями.
OVERLAP_MARGIN = 0.08
MIN_CLUSTER_FRACTION = 0.12


def union_find_assign(items, overlaps):
    parent = {i: i for i in items}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in overlaps:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    clusters = {}
    for i in items:
        clusters.setdefault(find(i), []).append(i)
    return list(clusters.values())


def bbox_overlap(a, b, margin):
    for axis in range(3):
        if a[1][axis] + margin < b[0][axis] or b[1][axis] + margin < a[0][axis]:
            return False
    return True


def process(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as error:  # noqa: BLE001
        print(f"SPLIT_FAIL {os.path.basename(path)}: {error}")
        return
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if len(meshes) < 2:
        print(f"SINGLE {os.path.basename(path)}")
        return
    boxes = {}
    for o in meshes:
        pts = [o.matrix_world @ v.co for v in o.data.vertices]
        if not pts:
            continue
        xs, ys, zs = zip(*[(p.x, p.y, p.z) for p in pts])
        boxes[o.name] = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    spans = [max(b[1][i] - b[0][i] for i in range(3)) for b in boxes.values()]
    scene_span = max(spans) if spans else 0.0
    margin = scene_span * OVERLAP_MARGIN
    names = list(boxes.keys())
    overlaps = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if bbox_overlap(boxes[names[i]], boxes[names[j]], margin):
                overlaps.append((names[i], names[j]))
    clusters = union_find_assign(names, overlaps)
    # размер кластера = габарит объединения его bbox
    sized = []
    for cl in clusters:
        lo = [min(boxes[n][0][i] for n in cl) for i in range(3)]
        hi = [max(boxes[n][1][i] for n in cl) for i in range(3)]
        size = max(hi[i] - lo[i] for i in range(3))
        sized.append((cl, size))
    biggest = max(s for _, s in sized)
    ships = [(cl, s) for cl, s in sized if s >= biggest * MIN_CLUSTER_FRACTION]
    debris = [(cl, s) for cl, s in sized if s < biggest * MIN_CLUSTER_FRACTION]
    if len(ships) < 2:
        print(f"SINGLE {os.path.basename(path)} ({len(ships)} ship cluster)")
        return
    stem = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.dirname(path)
    parts = []
    ships.sort(key=lambda t: -t[1])
    for k, (cl, size) in enumerate(ships, start=1):
        bpy.ops.object.select_all(action="DESELECT")
        chosen = set(cl)
        for o in bpy.context.scene.objects:
            o.select_set(o.type == "MESH" and o.name in chosen)
        out_path = os.path.join(out_dir, f"{stem}__s{k}.glb")
        bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB",
                                  use_selection=True)
        parts.append({"part": k, "file": os.path.basename(out_path),
                      "objects": len(cl), "size": round(size, 3)})
    print(f"SPLIT {os.path.basename(path)}: {len(ships)} ships "
          f"+ {len(debris)} debris clusters, sizes={[round(s, 2) for _, s in sized]}")
    return {"file": os.path.basename(path), "parts": parts,
            "debris_clusters": len(debris),
            "cluster_sizes": [round(s, 3) for _, s in sized]}


report = []
for f in FILES:
    result = process(f)
    if result:
        report.append(result)
with open(OUT_REPORT, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)
print(f"REPORT {OUT_REPORT} models={len(FILES)} multi_ship={len(report)}")
