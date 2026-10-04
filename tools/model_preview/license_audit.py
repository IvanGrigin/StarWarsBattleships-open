#!/usr/bin/env python3
"""Аудит лицензий моделей, выбранных для игры (победители турнира).

Для каждого корабля ростера: какая модель выбрана, её лицензия, автор, ссылка,
и два ответа — можно ли её использовать в платной игре и можно ли её менять
(облегчённые копии, запечённый поворот — это уже изменение).

Лицензия берётся из liked/manifest.json (пакетные загрузки) или из таблицы
EARLY ниже — для первых файлов, скачанных вручную (источник: README.md
карантинного каталога raw_candidates).

Запуск:  python3 tools/model_preview/license_audit.py
Вывод:   reports/model_licenses.md
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
OUT = ROOT / "reports" / "model_licenses.md"

# Файлы, скачанные до пакетного загрузчика (raw_candidates/README.md)
EARLY = {
    "death_star_1_2k_opt.glb": ("CC BY-NC-ND 4.0", "SebastianSosnowski", "https://github.com/EdoEdoEdo/Death-Star-Promo"),
    "death_star_1_joe_scalise.glb": ("CC BY 3.0", "Joe Scalise / Poly Pizza", "https://poly.pizza"),
    "star_destroyer_opt.glb": ("CC BY 4.0", "rubaun", "https://github.com/EdoEdoEdo/Death-Star-Promo"),
    "tie_fighter_opt.glb": ("CC BY 4.0", "Daniel Andersson", "https://github.com/EdoEdoEdo/Death-Star-Promo"),
    "xwing_t65_heataker_objaverse.glb": ("CC BY 4.0", "Heataker", "https://sketchfab.com/3d-models/star-wars-x-wing-fighter-e6b85951f85940c1b26505eda7d73ef9"),
    "millennium_falcon_stym/scene.gltf": ("CC BY-SA 4.0", "Stym", "https://github.com/RDGKing/threejs-3d-model-sample"),
    "vulture_droid_theo_objaverse.glb": ("CC BY-NC", "Théo A", "https://sketchfab.com/3d-models/vulture-droid-668662520d6c46dea6ba23b8e36befbe"),
    "eta2_actis_maxkamms_objaverse.glb": ("CC BY", "maxkamms", "https://sketchfab.com/3d-models/eta-2-actis-finished-eb30996c13ba4e2ab36af8bea1531827"),
    "tie_advanced_x1_daniel_objaverse.glb": ("CC BY", "Daniel Andersson", "https://sketchfab.com/3d-models/star-wars-tiex1-advanced-x1-a3a01470d6794792892dff5c15c7a267"),
}


def verdict(lic: str) -> tuple[str, str]:
    """(платная игра, изменения) по тексту лицензии."""
    L = lic.lower().replace("attribution", "by").replace("noncommercial", "nc") \
        .replace("sharealike", "sa").replace("noderivs", "nd").replace("-", " ")
    if not lic or lic.startswith("?"):
        return "неизвестно — проверить", "неизвестно — проверить"
    if "free standard" in L:
        return "да (внутри игры, без отдельной выкладки модели)", "да"
    if "cc0" in L or "public domain" in L:
        return "да", "да"
    commercial = "нет" if " nc" in f" {L}" else "да, с указанием автора"
    if " nd" in f" {L}":
        return commercial, "нет — нельзя выкладывать изменённую (и облегчённую) копию"
    if " sa" in f" {L}":
        return commercial, "да, но производные — под той же лицензией"
    return commercial, "да"


def main() -> int:
    roster = json.loads((ROOT / "data/rulesets/v4/index.json").read_text(encoding="utf-8"))["ships"]
    names = {p.stem: json.loads(p.read_text(encoding="utf-8"))["display_name"]
             for p in (ROOT / "data/rulesets/v4/ships").glob("*.json")}
    tour = json.loads((HERE / "tournament.json").read_text(encoding="utf-8"))["types"]
    renders = json.loads((ROOT / "demo/assets/card_renders/index.json").read_text(encoding="utf-8")) \
        if (ROOT / "demo/assets/card_renders/index.json").exists() else {}
    manifest = {m["file"]: m for m in json.loads((RAW / "liked/manifest.json").read_text(encoding="utf-8"))}

    rows, tally = [], Counter()
    for ship in roster:
        f = (tour.get(ship) or {}).get("winner") or (renders.get(ship) or {}).get("file")
        how = "турнир" if (tour.get(ship) or {}).get("winner") else ("посев" if f else "—")
        if not f:
            rows.append((names[ship], "—", "модели нет", "—", "—", "—")); tally["модели нет"] += 1
            continue
        m = manifest.get(f)
        if m:
            lic, author, url = m.get("license") or "?", m.get("author") or "—", m.get("url") or ""
        else:
            lic, author, url = EARLY.get(f, ("? не подтверждена", "—", ""))
        paid, edit = verdict(lic)
        tally["платно можно" if paid.startswith("да") else ("платно нельзя" if paid == "нет" else "неизвестно")] += 1
        link = f"[{author}]({url})" if url else author
        rows.append((names[ship], f"`{f.split('/')[-1][:48]}` ({how})", lic, link, paid, edit))

    out = [
        "# Лицензии моделей кораблей",
        "",
        "Сгенерировано `tools/model_preview/license_audit.py`. Для каждого корабля игры — модель,",
        "выбранная в турнире (или лучшая по посеву, если турнир не сыгран), её лицензия и два",
        "ответа: можно ли использовать в **платной** игре и можно ли **изменять** (облегчённая",
        "копия и запечённый поворот — уже изменение).",
        "",
        f"Итог: платно можно — {tally['платно можно']}, платно нельзя — {tally['платно нельзя']}, "
        f"лицензия не подтверждена — {tally['неизвестно']}, модели нет — {tally['модели нет']}.",
        "",
        "> Лицензия модели касается только труда её автора. Сам дизайн кораблей «Звёздных войн»",
        "> принадлежит Lucasfilm/Disney, и никакая CC-лицензия фанатской модели не даёт права",
        "> продавать игру с этими кораблями. См. `docs/decisions/ADR-020-licensing-paid-or-free.md`.",
        "",
        "| Корабль | Модель | Лицензия | Автор | Платная игра | Изменения |",
        "|---|---|---|---|---|---|",
    ]
    out += [f"| {' | '.join(r)} |" for r in rows]
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)} — {dict(tally)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
