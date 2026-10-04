#!/usr/bin/env python3
"""Текстуры планет для фона боя: исходники из assets_source/planets/ → 2048×1024 WebP.

Кладёте скачанные текстуры (например, набор Shiny Man с CGTrader) в
assets_source/planets/ как есть — архивы распаковать. Скрипт находит у каждой
планеты цветовую карту (не normal/bump/specular/облака/ночь), уменьшает до
2048×1024 и пишет tools/play_v4/assets/planets/<планета>.webp. Имя планеты
берётся из имени файла или папки: coruscant, kuat, korriban, taris, felucia,
mandalore, nar_shaddaa, csilla.

Запуск:  python3 tools/play_v4/prepare_planets.py [каталог исходников]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "assets_source" / "planets"
OUT = Path(__file__).resolve().parent / "assets" / "planets"
PLANETS = {"coruscant": "coruscant", "kuat": "kuat", "korriban": "korriban", "taris": "taris",
           "felucia": "felucia", "mandalore": "mandalore", "nar[ _-]?shaddaa": "nar_shaddaa", "csilla": "csilla"}
SKIP = re.compile(r"normal|bump|spec|rough|metal|night|light|cloud|height|elevation|disp|emiss|ao\b|mask|ring", re.I)
Image.MAX_IMAGE_PIXELS = None                     # 16K-текстуры больше защитного предела PIL


def planet_of(path: Path) -> str | None:
    text = str(path.relative_to(SRC)).lower()
    for pat, name in PLANETS.items():
        if re.search(pat, text):
            return name
    return None


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Нет каталога {SRC} — положите туда скачанные текстуры.")
    best: dict[str, Path] = {}
    for f in SRC.rglob("*"):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp") or SKIP.search(f.stem):
            continue
        name = planet_of(f)
        rank = (bool(re.search(r"diffuse|albedo|color|day", f.stem, re.I)), f.stat().st_size)
        if name and (name not in best or rank > best[name][0]):
            best[name] = (rank, f)                # «Diffuse» важнее размера; из равных — самая подробная
    if not best:
        raise SystemExit("Цветовых карт планет не найдено.")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (_, f) in sorted(best.items()):
        img = Image.open(f).convert("RGB").resize((2048, 1024), Image.LANCZOS)
        dst = OUT / f"{name}.webp"
        img.save(dst, "WEBP", quality=86, method=6)
        print(f"{name}: {f.name} → {dst.relative_to(ROOT)} ({dst.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()
