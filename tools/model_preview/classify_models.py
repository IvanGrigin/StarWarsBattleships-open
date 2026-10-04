#!/usr/bin/env python3
"""Классификация скачанных моделей по кораблям ростера игры (ruleset v4).

Каждой модели сопоставляется ровно один тип корабля из data/rulesets/v4/ships
или «none» — корабля нет в игре (или файл — не корабль: деталь набора, дроид).
Одна модель — один тип, поэтому одна и та же модель не попадёт в два типа.

Правила проверяются по порядку, первое совпадение побеждает. Сначала по
названию самой модели (часть имени файла после «__»), и только если оно
ничего не говорит — по названию группы-запроса, под которым модель скачана:
внутри групп встречаются чужие модели (в группе b-wing лежит Y-wing,
в death_star_ii — дроид R5-J2, в malevolence — истребитель V-19).

Ручные правки (source: "manual", их делают на странице турнира) при повторном
запуске не перезаписываются.

Запуск:  python3 tools/model_preview/classify_models.py
Вывод:   tools/model_preview/ship_classes.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from serve import list_models  # noqa: E402  — тот же список моделей и номера, что у страницы

OUT = HERE / "ship_classes.json"
SEARCH_REPORT = HERE / "missing_models_report.json"          # find_models.py: uid → корабль
LIKED_MANIFEST = ROOT / "assets_source" / "external_models" / "raw_candidates" / "liked" / "manifest.json"
ROSTER = {p.stem for p in (ROOT / "data" / "rulesets" / "v4" / "ships").glob("*.json")}
NONE = "none"

# (шаблон, тип). Имена нормализуются: нижний регистр, «_», пробелы и точки → «-».
RULES: list[tuple[str, str]] = [
    # не корабли / детали наборов
    (r"r5-j2|astromech", NONE),
    (r"^vulture-flight-zeinfel-thing4458309/", NONE),      # 15 деталей кита; собранный — vulture_flight_kit
    # Первый Орден и поздние TIE — раньше общего «tie»
    (r"silencer", "tie_silencer"),
    (r"tie-sf|special-forces", "tie_sf"),
    (r"first-order-tie|tie-fo\b|tie/fo", "tie_fo"),
    (r"tie-dagger|tie-defender|tie-rb|brute|tie-reaper|reaper|tie-striker|striker", NONE),
    (r"tie-advanced|advanced-x1", "tie_advanced_x1"),
    (r"tie-bomber|tie-bomb", "tie_bomber"),
    (r"astro-interceptor", NONE),                           # не A-wing, хоть и в группе a-wing
    (r"rz-2", "rz2_awing"),
    (r"a-wing", "awing_rz1"),
    (r"tie-interceptor", "tie_interceptor"),
    (r"tie-fighter|t-i-e|tie-ln", "tie_fighter"),
    # X-, Y-, B-wing: T-70 и T-85 раньше общего X-wing; Y-wing раньше B-wing
    (r"t-85", NONE),
    (r"t-70", "xwing_t70"),
    (r"x-wing|xwing|t-65", "xwing_t65"),
    (r"y-wing|btl-a4|btl-b", "ywing_btla4"),
    (r"b-wing|a-sf-01", "bwing"),
    (r"u-55|loadlifter|resistance-transport", "resistance_transport"),   # транспорт Сопротивления (VIII)
    (r"u-wing|v-wing", NONE),
    # эпоха Республики
    (r"eta-2|eta2|actis", "eta2_actis"),
    (r"delta-7|aethersprite", "delta7_aethersprite"),
    (r"arc-170|arc170", "arc170"),
    (r"v-19|torrent", "v19_torrent"),
    (r"laat", "laat_gunship"),
    (r"n-1|n1-starfighter|naboo-n1|naboo-starfighter", "naboo_n1"),
    (r"naboo-royal|royal-starship|nubian-royal|j-type|h-type|nubian-yacht|naboo-cruiser", "naboo_royal_cruiser"),
    (r"venator", "venator"),
    # сепаратисты
    (r"tri-fighter|tri-fighter-droid", "tri_fighter"),
    (r"^converted-glb/vulture-flight-kit|vulture", "vulture_droid"),
    (r"hyena", "hyena_bomber"),
    (r"soulless", "soulless_one"),
    (r"munificent", "munificent"),
    (r"providence|invisible-hand", "providence"),
    (r"nantex", "nantex_fighter"),
    # имперские крупные — конкретные классы раньше общего «star destroyer»
    (r"resurgent", "resurgent_destroyer"),
    (r"executor|super-star-destroyer", "executor"),
    (r"leviathan|old-republic", NONE),                       # не «Иммобилайзер» 418
    (r"interdictor|immobilizer", "interdictor"),
    (r"supremacy|xyston|acclamator|arquitens|546-cruiser|cantwell|quasar|gozanti|"
     r"hammerhead|pelta|nebulon|lucrehulk|core-ship|consular|republic-cruiser|malevolence", NONE),
    (r"eclipse|metther", NONE),                              # другие классы разрушителей
    (r"imperial-class|imperial-star-destroyer|star-destroyer", "star_destroyer"),
    (r"death-star-ii|death-star-2", NONE),
    (r"death-star", "death_star_1"),
    (r"lambda", "lambda_shuttle"),
    (r"upsilon", "upsilon_shuttle"),
    # повстанцы и прочие
    (r"mc80|home-one|mon-calamari", "mc80_home_one"),
    (r"raddus|mc85", "raddus_cruiser"),
    (r"gr-75", "gr75_transport"),
    (r"ghost-+shuttle", "ghost"),                            # «Призрак» с пристыкованным челноком
    (r"phantom|shuttle-stl|shuttle-obj", "phantom"),        # «Фантом» из набора Ghost
    (r"ghost|vcx", "ghost"),
    (r"millennium-falcon|falcon|yt-1300", "millennium_falcon"),
    (r"slave-1|slave-i\b|firespray", "slave_1"),
    (r"z-95|headhunter", "z95_headhunter"),
    (r"mg-100|starfortress", "mg100_bomber"),
    (r"punishing-one", "punishing_one"),
    (r"hound", "hounds_tooth"),
    (r"razor-crest|yt-2400|outrider|fang-fighter|nu-class|t-6|jedi-shuttle|"
     r"sith-infiltrator|scimitar|solar-sailer|twilight|g9-rigger|cr90|cr120|corvette", NONE),
]
COMPILED = [(re.compile(p), t) for p, t in RULES]


def norm(s: str) -> str:
    return re.sub(r"[\s_.]+", "-", s.lower())


def classify(rel: str, ship: str) -> tuple[str | None, str]:
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    # «группа__название» — формат только пакетных загрузок (liked/); у остальных «__»
    # может быть частью имени (Rebells_Ghost__Shuttle = «Призрак» с челноком)
    label = stem.split("__", 1)[1] if rel.startswith("liked/") and "__" in stem else stem
    # 1) путь (для деталей наборов), 2) название модели, 3) группа-запрос
    for text, where in ((norm(rel), "путь"), (norm(label), "название"), (norm(ship), "группа")):
        for rx, t in COMPILED:
            if where == "путь" and not rx.pattern.startswith("^"):
                continue                      # по пути проверяем только привязанные к каталогу правила
            if rx.search(text):
                return t, f"{where}: /{rx.pattern}/"
    return None, "нет совпадения"


def search_intent() -> dict[str, str]:
    """Файл → корабль, для которого модель нашли поиском (find_models.py).

    Такая модель относится к искомому кораблю, даже если по названию правила
    отнесли бы её к другому: YT-2400 найден как пиратский корсар, а общее
    правило отправляет YT-2400 в «нет в игре».
    """
    if not SEARCH_REPORT.exists() or not LIKED_MANIFEST.exists():
        return {}
    uid_ship = {h["uid"]: ship for ship, hits in json.loads(SEARCH_REPORT.read_text(encoding="utf-8")).items()
                for h in hits}
    out = {}
    for m in json.loads(LIKED_MANIFEST.read_text(encoding="utf-8")):
        ship = uid_ship.get(m.get("uid"))
        if ship and ship in ROSTER:
            out[m["file"]] = ship
    return out


def main() -> int:
    bad = {t for _, t in RULES if t != NONE and t not in ROSTER}
    if bad:
        print(f"В правилах есть типы, которых нет в ростере v4: {sorted(bad)}", file=sys.stderr)
        return 1
    old = json.loads(OUT.read_text(encoding="utf-8"))["classes"] if OUT.exists() else {}
    intent = search_intent()
    classes, unmatched = {}, []
    for m in list_models():
        prev = old.get(m["file"])
        if prev and prev.get("source") == "manual":
            classes[m["file"]] = prev                 # ручное решение владельца не трогаем
            continue
        if m["file"] in intent:                       # нашли поиском именно для этого корабля
            classes[m["file"]] = {"ship": intent[m["file"]], "source": "auto",
                                  "rule": "поиск find_models.py", "num": m["num"]}
            continue
        t, why = classify(m["file"], m["ship"])
        if t is None:
            unmatched.append(m["file"])
            t = NONE
            why = "нет совпадения — проверить вручную"
        classes[m["file"]] = {"ship": t, "source": "auto", "rule": why, "num": m["num"]}
    OUT.write_text(json.dumps({
        "note": "Тип корабля ростера v4 для каждой скачанной модели; none — нет в игре. "
                "source: auto (classify_models.py) или manual (правка на странице).",
        "classes": classes}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    per = Counter(c["ship"] for c in classes.values())
    in_game = {k: v for k, v in per.items() if k != NONE}
    print(f"Моделей: {len(classes)}; в игре: {sum(in_game.values())} по {len(in_game)} типам; "
          f"нет в игре: {per[NONE]}; без совпадения: {len(unmatched)}")
    for t in sorted(ROSTER):
        print(f"  {per.get(t, 0):3d}  {t}")
    for f in unmatched:
        print("  ? ", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
