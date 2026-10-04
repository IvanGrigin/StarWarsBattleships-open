#!/usr/bin/env python3
"""Проверка, что архив ассетов data.zip распакован в корень репозитория.

Ассеты (картинки, 3D-модели, текстуры) в git не входят — их передаёт владелец
архивом data.zip (docs/ASSETS.md). Установка — одной командой из корня клона:

    unzip -o data.zip

Запуск проверки:  python3 tools/check_assets.py
Код возврата 0 — всё на месте; 1 — чего-то не хватает (игра запустится на заглушках).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# у этих кораблей свободных моделей нет — на поле заглушка, это не ошибка установки
NO_MODEL = {"mg100_bomber", "nantex_fighter", "punishing_one"}
# у этих кораблей нет иллюстрации карточки — карточка показывается без картинки
NO_ART = {"munificent", "punishing_one", "rz2_awing", "tri_fighter"}


def main() -> int:
    ships = sorted(p.stem for p in (ROOT / "data/rulesets/v4/ships").glob("*.json"))
    heroes = sorted(p.stem for p in (ROOT / "data/rulesets/v4/heroes").glob("*.json"))
    index = json.loads((ROOT / "demo/assets/models/v4/index.json").read_text(encoding="utf-8"))
    groups = {
        "3D-модели кораблей (demo/assets/models/v4)": [f"demo/assets/models/v4/{s}.glb" for s in index],
        "иллюстрации кораблей (demo/assets/card_art/ships)": [f"demo/assets/card_art/ships/{s}.webp" for s in ships if s not in NO_ART],
        "портреты героев (demo/assets/card_art/heroes)": [f"demo/assets/card_art/heroes/{h}.webp" for h in heroes],
        "планеты и Солнце (tools/play_v4/assets/planets)": [f"tools/play_v4/assets/planets/{n}.webp"
                                                            for n in ("coruscant", "csilla", "korriban", "sun")],
        "декорации фона (tools/play_v4/assets/decor)": ["tools/play_v4/assets/decor/death_star_ii.glb"],
    }
    bad = 0
    for title, files in groups.items():
        missing = [f for f in files if not (ROOT / f).is_file()]
        print(f"{'OK ' if not missing else 'НЕТ'} {title}: {len(files) - len(missing)} из {len(files)}")
        for f in missing[:5]:
            print(f"      нет файла {f}")
        if len(missing) > 5:
            print(f"      … и ещё {len(missing) - 5}")
        bad += len(missing)
    no_model = sorted(set(ships) - set(index) - NO_MODEL)
    if no_model:
        print("Корабли без записи в index.json:", ", ".join(no_model))
    if bad:
        print("\nАссеты не установлены или установлены не полностью. Из корня репозитория:\n    unzip -o data.zip")
        return 1
    print("\nВсе ассеты на месте. Запуск игры: python3 tools/play_v4/server.py --cards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
