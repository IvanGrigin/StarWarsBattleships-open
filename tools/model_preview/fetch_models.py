#!/usr/bin/env python3
"""Скачивание найденных моделей из открытого датасета Objaverse (без токена).

Objaverse (allenai, HuggingFace) — зеркало моделей Sketchfab, которые на момент
сбора (2022) были выложены под лицензиями Creative Commons. Модель берётся
оттуда, только если её Sketchfab-uid есть в индексе object-paths.json.gz;
лицензия и автор — из отчёта поиска find_models.py (missing_models_report.json).

Файлы кладутся в raw_candidates/liked/v4_<корабль>__<название>.glb и
дописываются в liked/manifest.json — так же, как у загрузчика с токеном.
Префикс v4_<корабль> — тип корабля, для которого модель искали: по нему её
классифицирует classify_models.py.

Остальных кандидатов (которых нет в Objaverse) качает официальный загрузчик
с токеном владельца: tools/download_selected_models.py --all-v4

Запуск:  python3 tools/model_preview/fetch_models.py
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
LIKED = RAW / "liked"
REPORT = HERE / "missing_models_report.json"
INDEX_URL = "https://huggingface.co/datasets/allenai/objaverse/resolve/main/object-paths.json.gz"
BASE_URL = "https://huggingface.co/datasets/allenai/objaverse/resolve/main/"
INDEX_CACHE = RAW / "_objaverse_object-paths.json.gz"
AGENT = "Mozilla/5.0 (StarWarsBattleships model fetch)"


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "model"


def get(url: str, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(target)


def main() -> int:
    if not RAW.is_dir():
        print(f"Нет каталога с моделями: {RAW} — запускайте из основной папки проекта.", file=sys.stderr)
        return 2
    if not REPORT.exists():
        print("Сначала поиск: python3 tools/model_preview/find_models.py", file=sys.stderr)
        return 2
    if not INDEX_CACHE.exists():
        print("Индекс Objaverse (~20 МБ)…", flush=True)
        get(INDEX_URL, INDEX_CACHE)
    paths = json.load(gzip.open(INDEX_CACHE))
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    manifest_path = LIKED / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    have = {m.get("uid") for m in manifest}
    got = skipped = missing = 0
    for ship, hits in report.items():
        for h in hits:
            if h["uid"] in have:
                skipped += 1
                continue
            rel = paths.get(h["uid"])
            if not rel:
                missing += 1                   # нет в Objaverse — только через Sketchfab с токеном
                continue
            glb = LIKED / f"v4_{ship}__{sanitize(h['name'])}.glb"
            print(f"СКАЧИВАЮ {ship}: {h['name']} ({h['license']}, {h['author']})", flush=True)
            try:
                get(BASE_URL + rel, glb)
            except Exception as e:             # сетевой сбой по одной модели не валит остальные
                print(f"  ОШИБКА: {e}", file=sys.stderr)
                continue
            manifest.append({"uid": h["uid"], "ship": f"v4:{ship}", "label": h["name"],
                             "file": f"liked/{glb.name}", "kind": "gltf",
                             "license": h["license"], "author": h["author"], "url": h["url"],
                             "source": "objaverse"})
            have.add(h["uid"])
            got += 1
            print(f"  OK {glb.name} — {glb.stat().st_size / 1e6:.1f} МБ", flush=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nСкачано из Objaverse: {got}; уже были: {skipped}; нет в Objaverse (нужен токен): {missing}")
    if missing:
        print("Их скачает официальный загрузчик с вашим токеном Sketchfab:\n"
              "  SKETCHFAB_TOKEN=<ваш токен> python3 tools/download_selected_models.py --all-v4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
