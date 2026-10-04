#!/usr/bin/env python3
"""Игровые 3D-модели кораблей: выбранная модель → готовый к игре GLB.

Для каждого корабля ростера v4 берётся модель-победитель турнира (или лучшая
по посеву, если турнир не сыгран — та же логика, что у render_cards.py).
Источник — облегчённая копия из raw_candidates/_preview (текстуры ≤512 px
WebP, меши слиты, meshopt), иначе оригинал через gltf-transform.

Поворот владельца запекается так: все корневые узлы сцены оборачиваются в
новый узел «swb_orientation» с кватернионом из model_reviews.json. Модель
поворачивается целиком, вокруг начала координат — как на странице ориентации.
(patch_glb_rotation.py поворачивает каждый корневой узел на месте и не
сдвигает его: для моделей из многих частей со смещениями части разъедутся.)

Вывод: demo/assets/models/v4/<корабль>.glb и index.json (модель-источник,
лицензия, автор, ссылка, поворот, габарит, признаки NC/ND).

Запуск:  python3 tools/model_preview/export_game_models.py [корабль ...]
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
OUT = ROOT / "demo" / "assets" / "models" / "v4"
GLTF_TRANSFORM = ["npx", "--yes", "@gltf-transform/cli@4.1.1"]
sys.path.insert(0, str(HERE))
from render_cards import pick_models          # noqa: E402 — тот же выбор модели
from license_audit import EARLY                # noqa: E402 — лицензии первых файлов


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + jlen]), data[20 + jlen + 8:]


def write_glb(path: Path, gltf: dict, binary: bytes) -> None:
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, total)
                     + struct.pack("<II", len(js), 0x4E4F534A) + js
                     + struct.pack("<II", len(binary), 0x004E4942) + binary)


def bake_orientation(gltf: dict, quat: list[float]) -> None:
    """Все корневые узлы сцены — под новый узел с поворотом владельца."""
    for scene in gltf.get("scenes", []):
        roots = scene.get("nodes", [])
        gltf.setdefault("nodes", []).append({"name": "swb_orientation", "rotation": quat,
                                             "children": roots})
        scene["nodes"] = [len(gltf["nodes"]) - 1]
    gltf.setdefault("extras", {})["swb_orientation"] = quat


def main(argv: list[str]) -> int:
    only = set(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {m["file"]: m for m in json.loads((RAW / "liked/manifest.json").read_text(encoding="utf-8"))}
    index = {}
    for ship, info in pick_models().items():
        if only and ship not in only:
            continue
        src = RAW / info["file"]
        preview = (RAW / "_preview" / info["file"]).with_suffix(".glb")
        with tempfile.TemporaryDirectory() as tmp:
            if preview.exists() and preview.stat().st_mtime >= src.stat().st_mtime:
                light = preview
            else:
                light = Path(tmp) / "light.glb"
                r = subprocess.run(GLTF_TRANSFORM + ["optimize", str(src), str(light), "--texture-size", "512",
                                                     "--texture-compress", "webp", "--compress", "meshopt",
                                                     "--simplify-error", "0.002"], capture_output=True, text=True)
                if r.returncode != 0:
                    print(f"{ship}: не удалось облегчить — {r.stderr.strip()[-160:]}")
                    continue
            gltf, binary = read_glb(light)
        bake_orientation(gltf, [float(v) for v in info["orientation"]])
        dst = OUT / f"{ship}.glb"
        write_glb(dst, gltf, binary)
        m = manifest.get(info["file"], {})
        lic, author, url = (m.get("license"), m.get("author"), m.get("url")) if m else \
            EARLY.get(info["file"], ("? не подтверждена", None, None))
        L = (lic or "").lower()
        index[ship] = {"file": f"{ship}.glb", "source": info["file"], "chosen": info["how"],
                       "orientation": info["orientation"], "bytes": dst.stat().st_size,
                       "license": lic, "author": author, "url": url,
                       "noncommercial": "noncommercial" in L or "nc" in L.replace("-", " ").split(),
                       "noderivatives": "noderiv" in L or "nd" in L.replace("-", " ").split()}
        print(f"{ship:22} {dst.stat().st_size / 1e6:5.2f} МБ  {info['how'][:22]:22} {lic}")
    old = json.loads((OUT / "index.json").read_text(encoding="utf-8")) if (OUT / "index.json").exists() else {}
    old.update(index)
    (OUT / "index.json").write_text(json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                    encoding="utf-8")
    total = sum(v["bytes"] for v in old.values()) / 1e6
    print(f"Игровых моделей: {len(old)}; всего {total:.0f} МБ → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
