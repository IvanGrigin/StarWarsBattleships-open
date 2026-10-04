#!/usr/bin/env python3
"""Картинки кораблей для карточек — снимки собственных 3D-моделей.

Для каждого корабля ростера берётся модель-победитель турнира (tournament.json);
если турнир по кораблю ещё не сыгран — лучшая по посеву (как в турнире).
Модель облегчается gltf-transform (без meshopt — Blender его не читает),
к ней применяется поворот владельца из model_reviews.json, и Blender делает
снимок тем же ракурсом, что по умолчанию на странице ориентации.

Вывод: demo/assets/card_renders/<корабль>.png (720×480, прозрачный фон)
и card_renders/index.json — какая модель, лицензия, автор.

Запуск:  python3 tools/model_preview/render_cards.py [корабль ...] [--force]
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
OUT = ROOT / "demo" / "assets" / "card_renders"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
GLTF_TRANSFORM = ["npx", "--yes", "@gltf-transform/cli@4.1.1"]


def load(p: Path, key: str | None = None):
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return d.get(key, {}) if key else d


def pick_models() -> dict[str, dict]:
    roster = json.loads((ROOT / "data/rulesets/v4/index.json").read_text(encoding="utf-8"))["ships"]
    tour = load(HERE / "tournament.json", "types")
    classes = load(HERE / "ship_classes.json", "classes")
    reviews = load(HERE / "model_reviews.json", "reviews")
    manifest = {m["file"]: m for m in load(RAW / "liked" / "manifest.json") or []} \
        if (RAW / "liked" / "manifest.json").exists() else {}
    out = {}
    for ship in roster:
        winner = (tour.get(ship) or {}).get("winner")
        how = "победитель турнира"
        if not winner or not (RAW / winner).exists():
            cands = sorted((v["num"], f) for f, v in classes.items()
                           if v["ship"] == ship and (RAW / f).exists()
                           and reviews.get("file:" + f, {}).get("verdict") != "dislike")
            winner = cands[0][1] if cands else None
            how = "лучшая по посеву (турнир не сыгран)"
        if not winner:
            continue
        man = manifest.get(winner, {})
        out[ship] = {"file": winner, "how": how,
                     "orientation": (reviews.get("file:" + winner) or {}).get("orientation") or [0, 0, 0, 1],
                     "license": man.get("license"), "author": man.get("author"), "url": man.get("url")}
    return out


def main(argv: list[str]) -> int:
    force = "--force" in argv
    only = [a for a in argv if not a.startswith("--")]
    OUT.mkdir(parents=True, exist_ok=True)
    picks = pick_models()
    index = load(OUT / "index.json")
    for ship, info in picks.items():
        if only and ship not in only:
            continue
        png = OUT / f"{ship}.png"
        same = index.get(ship, {}).get("file") == info["file"] and \
            index.get(ship, {}).get("orientation") == info["orientation"]
        if png.exists() and same and not force:
            continue
        src = RAW / info["file"]
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "light.glb"
            r = subprocess.run(GLTF_TRANSFORM + ["optimize", str(src), str(light), "--compress", "false",
                                                 "--texture-size", "1024", "--texture-compress", "false",
                                                 "--simplify-error", "0.001"], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"{ship}: не удалось облегчить модель — {r.stderr.strip()[-200:]}")
                continue
            q = [str(v) for v in info["orientation"]]
            r = subprocess.run([BLENDER, "--background", "--python", str(HERE / "blender_card_render.py"),
                                "--", str(light), str(png), *q], capture_output=True, text=True, timeout=900)
        if "CARD_RENDER_OK" not in r.stdout:
            print(f"{ship}: рендер не удался — {(r.stderr or r.stdout).strip()[-300:]}")
            continue
        index[ship] = info
        print(f"{ship:22} ✓ {info['how']}: {info['file'][-50:]}", flush=True)
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                    encoding="utf-8")
    print(f"Снимков: {len(list(OUT.glob('*.png')))}; индекс: {(OUT / 'index.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
