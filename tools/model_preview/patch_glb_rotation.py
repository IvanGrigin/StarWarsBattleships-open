#!/usr/bin/env python3
"""Losslessly rotate GLB root nodes by a quaternion (fixes nose-down ships).

The batch pipeline exported ships standing on their tails: nose -Y, dorsal -Z
in glTF space. The quaternion (0, sqrt(.5), sqrt(.5), 0) maps -Y -> -Z (nose
forward) and -Z -> +Y (dorsal up) with span mirrored on X (ships are
mirror-symmetric, so this is invisible).

Usage: python3 patch_glb_rotation.py [--quat x,y,z,w] <file.glb> [more.glb ...]
Default quaternion fixes nose-down pipeline exports. With --quat, bakes an
arbitrary user orientation (e.g. from model_reviews.json "orientation").
Idempotent guard: skips files whose JSON already carries the marker
(--quat implies --force).
"""

import json
import struct
import sys
from pathlib import Path

MARKER = "swb_nose_fix_v1"
Q = [0.0, 0.7071067811865476, 0.7071067811865476, 0.0]  # x, y, z, w


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def patch(path: Path, quat: list, force: bool) -> str:
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        return f"SKIP {path.name}: not GLB"
    json_len, json_type = struct.unpack_from("<II", data, 12)
    gltf = json.loads(data[20:20 + json_len])
    already = MARKER in data[20:20 + json_len].decode("utf-8", errors="ignore")
    if already and not force:
        return f"SKIP {path.name}: already patched"
    scenes = gltf.get("scenes", [])
    if not scenes:
        return f"SKIP {path.name}: no scenes"
    touched = 0
    for scene in scenes:
        for node_index in scene.get("nodes", []):
            node = gltf["nodes"][node_index]
            if "matrix" in node:
                return f"SKIP {path.name}: root node uses matrix (unsupported)"
            existing = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
            node["rotation"] = q_mul(quat, existing)
            touched += 1
    if not already:
        extras = gltf.setdefault("extras", {})
        extras[MARKER] = True
    payload = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    bin_chunk = data[20 + json_len + 8:]
    out = bytearray()
    out += struct.pack("<III", magic, version, 12 + 8 + len(payload) + 8 + len(bin_chunk))
    out += struct.pack("<II", len(payload), 0x4E4F534A)
    out += payload
    out += struct.pack("<II", len(bin_chunk), 0x004E4942)
    out += bin_chunk
    path.write_bytes(bytes(out))
    return f"PATCHED {path.name}: {touched} root nodes"


def main() -> int:
    args = sys.argv[1:]
    quat = Q
    force = False
    if "--quat" in args:
        i = args.index("--quat")
        quat = [float(v) for v in args[i + 1].split(",")]
        args = args[:i] + args[i + 2:]
        force = True
    changed = skipped = 0
    for arg in args:
        result = patch(Path(arg), quat, force)
        print(result)
        if result.startswith("PATCHED"):
            changed += 1
        else:
            skipped += 1
    print(f"DONE patched={changed} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
