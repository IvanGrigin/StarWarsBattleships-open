#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Валидатор датасета ruleset v4 «Эпохи и фракции».

Проверяет data/rulesets/v4/** без сторонних зависимостей:
  * структуру всех файлов (обязательные поля, типы, диапазоны);
  * межфайловые ссылки (фракция, эпоха, способность, корабль, местность);
  * стоимость драфта — пересчётом по формуле §4 правил v4 (формула здесь
    намеренно реализована ВТОРОЙ раз, независимо от генератора: так ошибка
    в одном из двух мест становится видимой);
  * совместимость с v3: 11 кораблей и 8 героев наследия должны сохранить (боевые числа кораблей —
    либо как в v3, либо изменены утверждённым патчем баланса с исходным значением в balance_patch.before)
    id, HP, щит, сектора и текст способности;
  * играбельность: для каждой играбельной фракции существует легальный
    флот из 3 кораблей в пределах бюджета;
  * геометрию сценариев: клетки внутри поля, без пересечений.

Запуск:  python3 tools/validate_v4.py
"""

from __future__ import annotations

import json
import sys
from itertools import combinations, combinations_with_replacement
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "data" / "rulesets" / "v4"
V3 = ROOT / "data" / "rulesets" / "v3"

errors: list[str] = []
checked = 0


def fail(msg: str) -> None:
    errors.append(msg)


def load(path: Path) -> dict:
    global checked
    checked += 1
    return json.loads(path.read_text(encoding="utf-8"))


# --- формула стоимости (независимая реализация, см. rules-v4 §4) -----------
HYPER_POINTS = {0: 3, 1: 2, 2: 1, 3: 0, 4: 0}


def expected_cost(ship: dict, ability_points: dict[str, int]) -> tuple[int, int]:
    f, fr, br, b, bl, fl = ship["arc_modifiers"]
    raw = ship["max_hp"] + 2 * ship["max_shield"]
    raw += 2 * f + (fr + fl) + (br + bl) + b
    raw += 3 * (ship["weapon"]["max_range"] - 1)
    hyper = ship["hyperdrive"]
    raw += HYPER_POINTS[hyper["class"]] if hyper else -1
    if ship["engine"]["move_cost"] is None:
        raw -= 4
    if ship["engine"]["pivot_cost"] > 1:
        raw -= 2
    if ship["engine"]["boost"]:
        raw += 1
    for a in ship["abilities"]:
        raw += ability_points[a["id"]]
    return raw, max(2, (raw * 2 + 2) // 5)


def main() -> int:
    game = load(V4 / "game.json")
    board = load(V4 / "board.json")
    factions = {f["id"]: f for f in load(V4 / "factions.json")["factions"]}
    eras = {e["id"]: e for e in load(V4 / "eras.json")["eras"]}
    terrain = {t["id"]: t for t in load(V4 / "terrain.json")["terrain"]}
    abilities = {a["id"]: a for a in load(V4 / "ship_abilities.json")["abilities"]}
    ability_points = {a["id"]: a["cost_points"] for a in abilities.values()}
    events = load(V4 / "events.json")
    pirates = load(V4 / "pirates.json")
    index = load(V4 / "index.json")

    ships = {}
    for path in sorted((V4 / "ships").glob("*.json")):
        s = load(path)
        if s["id"] != path.stem:
            fail(f"ships/{path.name}: id={s['id']} не совпадает с именем файла")
        ships[s["id"]] = s

    heroes = {}
    for path in sorted((V4 / "heroes").glob("*.json")):
        h = load(path)
        if h["id"] != path.stem:
            fail(f"heroes/{path.name}: id={h['id']} не совпадает с именем файла")
        heroes[h["id"]] = h

    # --- корабли ----------------------------------------------------------
    roles = {"fighter", "interceptor", "bomber", "gunship", "support",
             "transport", "freighter", "corvette", "capital", "station"}
    for sid, s in ships.items():
        if s["schema_version"] != 2:
            fail(f"{sid}: schema_version должен быть 2")
        if s["faction"] not in factions:
            fail(f"{sid}: неизвестная фракция {s['faction']}")
        if s["era"] not in eras:
            fail(f"{sid}: неизвестная эпоха {s['era']}")
        if s["role"] not in roles:
            fail(f"{sid}: неизвестная роль {s['role']}")
        if len(s["arc_modifiers"]) != 6:
            fail(f"{sid}: arc_modifiers должен содержать ровно 6 чисел")
        if not 1 <= s["max_hp"] <= 20:
            fail(f"{sid}: max_hp вне диапазона 1..20")
        if not 0 <= s["max_shield"] <= 4:
            fail(f"{sid}: max_shield вне диапазона 0..4")
        w = s["weapon"]
        if not 1 <= w["max_range"] <= 6:
            fail(f"{sid}: max_range вне диапазона 1..6")
        if w["max_range"] > 1 and w["range_penalty_per_hex"] < 1:
            fail(f"{sid}: дальнобойный корабль без штрафа за дистанцию")
        if w["long_range_arc"] not in ("front", "front_flank", "all"):
            fail(f"{sid}: недопустимый long_range_arc {w['long_range_arc']}")
        if s["hyperdrive"] is not None and s["hyperdrive"]["class"] not in HYPER_POINTS:
            fail(f"{sid}: недопустимый класс гипердрайва")
        for a in s["abilities"]:
            if a["id"] not in abilities:
                fail(f"{sid}: способность {a['id']} отсутствует в ship_abilities.json")
        if s["role"] == "station" and s["draftable"]:
            fail(f"{sid}: станция не может быть draftable")
        if s["faction"] == "pirates" and s["draftable"]:
            fail(f"{sid}: пиратский корабль не берётся в драфт")
        raw, cost = expected_cost(s, ability_points)
        cost = max(2, cost + s.get("cost_adjust", 0))      # утверждённая поправка цены (data/balance)
        if s["raw_cost"] != raw or s["draft_cost"] != cost:
            fail(f"{sid}: стоимость {s['raw_cost']}/{s['draft_cost']} "
                 f"не сходится с формулой {raw}/{cost}")

    # --- герои ------------------------------------------------------------
    need = {"id", "name", "text", "kind", "trigger", "cost", "uses_per_match",
            "effect_sequence", "priority", "friendly_fire", "expires_at", "events"}
    for hid, h in heroes.items():
        if h["faction"] not in factions:
            fail(f"герой {hid}: неизвестная фракция {h['faction']}")
        if h["era"] not in eras:
            fail(f"герой {hid}: неизвестная эпоха {h['era']}")
        missing = need - set(h["ability"])
        if missing:
            fail(f"герой {hid}: в ability не хватает полей {sorted(missing)}")
        if h["ability"]["kind"] not in ("active", "reaction", "passive"):
            fail(f"герой {hid}: недопустимый kind {h['ability']['kind']}")
        if h["ability"]["kind"] == "passive" and h["ability"]["uses_per_match"] != 0:
            fail(f"герой {hid}: пассивная способность должна иметь uses_per_match=0")
        if h["ability"]["kind"] != "passive" and h["ability"]["uses_per_match"] < 1:
            fail(f"герой {hid}: активная способность должна иметь uses_per_match>=1")
        syn = h.get("synergy")
        if syn is None:
            fail(f"герой {hid}: нет синергии — у каждого героя есть способность и фракционная синергия")
        else:
            if syn["condition"]["faction"] not in factions:
                fail(f"герой {hid}: синергия ссылается на неизвестную фракцию")
            if not syn["effects"]:
                fail(f"герой {hid}: синергия без эффектов")

    # --- совместимость с v3 ------------------------------------------------
    for path in sorted((V3 / "ships").glob("*.json")):
        old = load(path)
        new = ships.get(old["id"])
        if new is None:
            fail(f"совместимость: корабль v3 {old['id']} отсутствует в v4")
            continue
        # Боевые числа v3 меняются только утверждённым патчем баланса (data/balance/v4_patch.json,
        # решение владельца от 2026-09-19); тогда исходное значение хранится в balance_patch.before.
        base = new.get("balance_patch", {}).get("before", new)
        for field in ("max_hp", "max_shield", "arc_modifiers"):
            if base[field] != old[field]:
                fail(f"совместимость: {old['id']}.{field} изменён "
                     f"({old[field]} -> {base[field]}) не через патч баланса")
        if not new["legacy_v3"]:
            fail(f"совместимость: {old['id']} должен быть помечен legacy_v3=true")
    for path in sorted((V3 / "heroes").glob("*.json")):
        old = load(path)
        new = heroes.get(old["id"])
        if new is None:
            fail(f"совместимость: герой v3 {old['id']} отсутствует в v4")
            continue
        if new["ability"]["text"] != old["ability"]["text"]:
            fail(f"совместимость: текст способности {old['id']} изменён")

    # --- играбельность драфта ---------------------------------------------
    draft = game["draft"]
    for fid, f in factions.items():
        if f["npc"]:
            continue
        pool = [s for s in ships.values()
                if s["draftable"] and s["faction"] == fid]
        # один корабль чужой фракции разрешён (max_foreign_faction_ships); эпоха — героя фракции или any
        eras_f = {f["era"], "any"} | {h["era"] for h in heroes.values() if h["faction"] == fid}
        foreign = [s for s in ships.values() if s["draftable"] and s["faction"] != fid
                   and s["faction"] != "pirates" and s["era"] in eras_f]
        ok = False
        # повтор неименных кораблей разрешён (draft.duplicates_allowed), именных — нет
        picks = (combinations_with_replacement if draft.get("duplicates_allowed")
                 else combinations)(pool, draft["fleet_size"])
        if not draft.get("duplicates_allowed"):
            picks = [c for c in combinations(pool + foreign, draft["fleet_size"])
                     if sum(1 for x in c if x["faction"] != fid) <= draft["max_foreign_faction_ships"]]
        for combo in picks:
            if any(c["unique"] and combo.count(c) > 1 for c in combo):
                continue
            if sum(c["draft_cost"] for c in combo) > draft["budget"]:
                continue
            if sum(1 for c in combo if c["role"] == "capital") > draft["max_capital_per_seat"]:
                continue
            if sum(1 for c in combo if c["unique"]) > draft["max_unique_per_seat"]:
                continue
            ok = True
            break
        if not ok:
            fail(f"драфт: фракция {fid} не может собрать легальный флот "
                 f"из {draft['fleet_size']} кораблей в бюджете {draft['budget']}")
        if len(pool) < draft["fleet_size"]:
            fail(f"драфт: у фракции {fid} меньше {draft['fleet_size']} "
                 f"кораблей в драфте")

    # у каждой играбельной фракции есть хотя бы один герой
    for fid, f in factions.items():
        if f["npc"]:
            continue
        if not any(h["faction"] == fid for h in heroes.values()):
            fail(f"фракция {fid}: нет ни одного героя")

    # --- события, местность, пираты ---------------------------------------
    total = sum(c["copies"] for c in events["cards"])
    if total != events["deck_size"] or total != game["events"]["deck_size"]:
        fail(f"события: размер колоды {total} не сходится с объявленным")
    for card in events["cards"]:
        p = card["effect"].get("params", {})
        t = p.get("terrain")
        for tid in ([t] if isinstance(t, str) else (t or [])):
            if tid not in terrain:
                fail(f"событие {card['id']}: неизвестная местность {tid}")
        if "ship" in p and p["ship"] not in ships:
            fail(f"событие {card['id']}: неизвестный корабль {p['ship']}")
    for entry in game["terrain"]["default_setup"]:
        if entry["terrain"] not in terrain:
            fail(f"game.terrain: неизвестная местность {entry['terrain']}")
    if pirates["faction"] not in factions:
        fail("pirates.json: неизвестная фракция")

    # --- сценарии ----------------------------------------------------------
    radius = board["radius"]
    for path in sorted((V4 / "scenarios").glob("*.json")):
        sc = load(path)
        if sc["scenario_id"] != path.stem:
            fail(f"сценарий {path.name}: id не совпадает с именем файла")
        used: set[tuple[int, int]] = set()
        for seat, cfg in sc["seats"].items():
            if seat not in sc["seat_order"]:
                fail(f"сценарий {sc['scenario_id']}: сид {seat} вне seat_order")
            for q, r in cfg["cells"]:
                if max(abs(q), abs(r), abs(-q - r)) > radius:
                    fail(f"сценарий {sc['scenario_id']}: клетка ({q},{r}) вне поля")
                if (q, r) in used:
                    fail(f"сценарий {sc['scenario_id']}: клетка ({q},{r}) занята дважды")
                used.add((q, r))
            if not 0 <= cfg["facing"] <= 5:
                fail(f"сценарий {sc['scenario_id']}: курс {cfg['facing']} вне 0..5")
        for q, r in sc.get("pirate_cells", []):
            if max(abs(q), abs(r), abs(-q - r)) > radius:
                fail(f"сценарий {sc['scenario_id']}: клетка пиратов ({q},{r}) вне поля")
            if (q, r) in used:
                fail(f"сценарий {sc['scenario_id']}: клетка пиратов ({q},{r}) занята")
        for sid in sc.get("pirate_ships", []):
            if sid not in ships:
                fail(f"сценарий {sc['scenario_id']}: неизвестный корабль пиратов {sid}")
        if sc.get("era") not in eras:
            fail(f"сценарий {sc['scenario_id']}: неизвестная эпоха {sc.get('era')}")

    # --- индекс ------------------------------------------------------------
    if sorted(ships) != index["ships"]:
        fail("index.json: список кораблей разошёлся с каталогом ships/")
    if sorted(heroes) != index["heroes"]:
        fail("index.json: список героев разошёлся с каталогом heroes/")
    if board["cell_count"] != 3 * radius * (radius + 1) + 1:
        fail("board.json: cell_count не соответствует радиусу")

    if errors:
        for e in errors:
            print(f"ОШИБКА: {e}")
        print(f"\n{len(errors)} ошибок в {checked} файлах")
        return 1
    print(f"OK: {checked} файлов, {len(ships)} кораблей, {len(heroes)} героев — "
          f"ошибок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
