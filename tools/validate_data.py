#!/usr/bin/env python3
"""Валидатор данных ruleset v3 (задача DATA, спринт 1).

Проверяет все JSON-файлы в data/rulesets/v3/ подмножеством JSON Schema
draft 2020-12, реализованным вручную на стандартной библиотеке (без pip),
плюс межфайловые правила из docs/contracts/core-api.md §4 и §8.

Запуск:  python3 tools/validate_data.py
Успех:   "OK: N files validated", код возврата 0.
Ошибка:  печать каждой ошибки, код возврата 1.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "rulesets" / "v3"
SCHEMA_DIR = ROOT / "data" / "schemas"

BOARD_RADIUS = 4

# ADR-011: до M2 все способности кораблей disabled; включение = отдельное
# решение (ADR-012, «новая версия ruleset с новым hash»). Пока ADR-012 не
# записан, включённая способность — ошибка (защита от случайного включения).
SPECIALS_SWITCH_ADR = ROOT / "docs" / "decisions" / "ADR-012.md"

errors: list[str] = []
validated_files = 0


def fail(message: str) -> None:
    errors.append(message)


# --------------------------------------------------------------------------
# Мини-валидатор подмножества JSON Schema draft 2020-12.
# Поддерживаются ключевые слова: type, const, enum, minimum, maximum,
# minLength, pattern, minItems, maxItems, items, required, properties,
# additionalProperties (только false).
# --------------------------------------------------------------------------

def _type_ok(value: object, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise AssertionError(f"неподдерживаемое ключевое слово type: {expected!r}")


def validate_schema(value: object, schema: dict, path: str) -> None:
    if "type" in schema and not _type_ok(value, schema["type"]):
        fail(f"{path}: ожидался тип {schema['type']}, получено {type(value).__name__}")
        return
    if "const" in schema and value != schema["const"]:
        fail(f"{path}: ожидалось const={schema['const']!r}, получено {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        fail(f"{path}: значение {value!r} вне enum {schema['enum']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            fail(f"{path}: длина строки меньше minLength={schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            fail(f"{path}: строка {value!r} не соответствует pattern {schema['pattern']!r}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            fail(f"{path}: значение {value} меньше minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            fail(f"{path}: значение {value} больше maximum={schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            fail(f"{path}: массив короче minItems={schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            fail(f"{path}: массив длиннее maxItems={schema['maxItems']}")
        if "items" in schema:
            for index, item in enumerate(value):
                validate_schema(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                fail(f"{path}: отсутствует обязательное поле '{key}'")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in value:
                validate_schema(value[key], subschema, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    fail(f"{path}: недопустимое поле '{key}'")


def load_json(path: Path) -> object | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{path}: не удалось разобрать JSON: {exc}")
        return None


def check_no_floats(value: object, path: str) -> None:
    """Float запрещён во всех данных ruleset (детерминизм, core-api §0)."""
    if isinstance(value, float):
        fail(f"{path}: float-значение запрещено в данных (детерминизм, core-api §0)")
    elif isinstance(value, dict):
        for item in value.values():
            check_no_floats(item, path)
    elif isinstance(value, list):
        for item in value:
            check_no_floats(item, path)


def load_schema(name: str) -> dict:
    schema = load_json(SCHEMA_DIR / name)
    if not isinstance(schema, dict):
        fail(f"{SCHEMA_DIR / name}: схема не является объектом")
        return {}
    return schema


def in_board(q: int, r: int) -> bool:
    s = -q - r
    return max(abs(q), abs(r), abs(s)) <= BOARD_RADIUS


# --------------------------------------------------------------------------
# Сценарий: встроенная схема (отдельный файл схемой не предусмотрен) + ручные
# проверки соответствия classic_2v2 контракту core-api §8.
# --------------------------------------------------------------------------

SEAT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cells", "facing"],
    "properties": {
        "facing": {"type": "integer", "minimum": 0, "maximum": 5},
        "cells": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"type": "integer"},
            },
        },
    },
}

SEATS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["A1", "B1"],
    "properties": {
        "A1": SEAT_SCHEMA,
        "B1": SEAT_SCHEMA,
    },
}

SCENARIO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "scenario_id", "seat_order", "teams", "seats"],
    "properties": {
        "schema_version": {"const": 1},
        "scenario_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "seat_order": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {"type": "string"},
        },
        "teams": {
            "type": "object",
            "additionalProperties": False,
            "required": ["A", "B"],
            "properties": {
                "A": {"type": "array", "items": {"type": "string"}},
                "B": {"type": "array", "items": {"type": "string"}},
            },
        },
        "seats": SEATS_SCHEMA,
        "note": {"type": "string"},
    },
}


def validate_scenario(path: Path, data: object, fleet_size: int) -> None:
    global validated_files
    if not isinstance(data, dict):
        return  # ошибка типа уже записана validate_schema
    validate_schema(data, SCENARIO_SCHEMA, str(path))

    if data.get("seat_order") != list(data.get("teams", {}).get("A", [])) + list(data.get("teams", {}).get("B", [])) \
            and data.get("seat_order") != list(data.get("teams", {}).get("B", [])) + list(data.get("teams", {}).get("A", [])):
        fail(f"{path}: seat_order должен состоять из сидов обеих команд")

    seats = data.get("seats", {})
    seen_cells: set[tuple[int, int]] = set()
    for seat_id, seat in sorted(seats.items()):
        for index, cell in enumerate(seat.get("cells", [])):
            q, r = cell
            if not in_board(q, r):
                fail(f"{path}: клетка {seat_id}[{index}] ({q}, {r}) вне поля радиуса {BOARD_RADIUS}")
            if (q, r) in seen_cells:
                fail(f"{path}: клетка ({q}, {r}) занята дважды")
            seen_cells.add((q, r))
        if len(seat.get("cells", [])) != fleet_size:
            fail(f"{path}: у сида {seat_id} {len(seat.get('cells', []))} клеток, ожидается fleet_size={fleet_size}")


# --------------------------------------------------------------------------
# Межфайловые проверки.
# --------------------------------------------------------------------------

EXPECTED_GAME = {
    "schema_version": 1,
    "ruleset_id": "v3_5",
    "initial_charges": 3,
    "max_charges": 5,
    "move_cost": 1,
    "rotate_cost": 1,
    "attack_cost": 0,
    "attacks_per_activation": 1,
    "fleet_size": 3,
    "draft_budget": 17,
    "max_group2_per_seat": 1,
    "max_same_type_group1_per_seat": 2,
    "round_limit": 60,
}


def validate_ship_file(path: Path, data: dict, ship_ids: dict[str, Path]) -> None:
    if data.get("id") != path.stem:
        fail(f"{path}: поле id={data.get('id')!r} не совпадает с именем файла {path.stem!r}")
    ship_id = data.get("id")
    if isinstance(ship_id, str):
        if ship_id in ship_ids:
            fail(f"{path}: дубликат id корабля '{ship_id}' (уже в {ship_ids[ship_id]})")
        ship_ids[ship_id] = path

    group = data.get("group")
    draftable = data.get("draftable")
    if group == 0 and draftable is not False:
        fail(f"{path}: корабль группы 0 (группа «X») обязан иметь draftable=false")
    if draftable is True and group not in (1, 2):
        fail(f"{path}: драфтуемый корабль обязан иметь группу 1 или 2, получена {group!r}")

    if ship_id == "phantom" and data.get("draft_cost") != 3:
        fail(f"{path}: стоимость Фантома обязана быть 3, получено {data.get('draft_cost')!r}")

    for ability in data.get("abilities", []):
        if ability.get("enabled") is not False and not SPECIALS_SWITCH_ADR.is_file():
            fail(
                f"{path}: способность '{ability.get('id')}' включена; "
                "до записи решения о включении (docs/decisions/ADR-012.md) "
                "способности обязаны быть enabled=false (ADR-011)"
            )


def check_draft_feasibility(ships: list[dict], game: dict) -> None:
    """Проверяет, что из драфтуемых кораблей можно собрать флот из fleet_size
    кораблей в бюджет draft_budget при ограничениях сида
    (<= max_group2_per_seat кораблей группы 2, <= max_same_type_group1_per_seat
    одинаковых типов группы 1)."""
    fleet_size = game["fleet_size"]
    budget = game["draft_budget"]
    draftable = [s for s in ships if s.get("draftable") is True]
    if len(draftable) < fleet_size:
        fail(f"драфтуемых кораблей {len(draftable)}, меньше fleet_size={fleet_size}")
        return

    fleet: list[dict] | None = None
    for combo in itertools.combinations(draftable, fleet_size):
        if sum(s["draft_cost"] for s in combo) > budget:
            continue
        group2 = sum(1 for s in combo if s["group"] == 2)
        if group2 > game["max_group2_per_seat"]:
            continue
        counts: dict[str, int] = {}
        ok = True
        for s in combo:
            if s["group"] == 1:
                counts[s["id"]] = counts.get(s["id"], 0) + 1
                if counts[s["id"]] > game["max_same_type_group1_per_seat"]:
                    ok = False
                    break
        if ok:
            fleet = list(combo)
            break
    if fleet is None:
        fail(
            f"из драфтуемых кораблей нельзя собрать флот из {fleet_size} кораблей "
            f"в бюджет {budget} при ограничениях сида"
        )
        return
    cheapest = sorted(s["draft_cost"] for s in draftable)[:fleet_size]
    if sum(cheapest) > budget:
        fail(f"три самых дешёвых драфтуемых корабля стоят {sum(cheapest)} > бюджета {budget}")


# --------------------------------------------------------------------------
# Контракты героев (MASTER_PLAN_RU §4.9, hero.schema.json).
# --------------------------------------------------------------------------

EXPECTED_HEROES = {
    "obi_wan": {"ability_id": "miss", "uses_per_match": 2, "epic": "C012"},
    "darth_vader": {"ability_id": "force_path", "uses_per_match": 1, "epic": "C013"},
    "anakin": {"ability_id": "force_path", "uses_per_match": 1, "epic": "C014"},
    "han_solo": {"ability_id": "hyperjump", "uses_per_match": 1, "epic": "C015"},
    "luke": {"ability_id": "precise_shot", "uses_per_match": 1, "epic": "C016"},
    "phasma": {"ability_id": "accuracy", "uses_per_match": 0, "epic": "C017"},
    "jango_fett": {"ability_id": "mine", "uses_per_match": 1, "epic": "C018"},
    "boba_fett": {"ability_id": "bomb", "uses_per_match": 1, "epic": "C019"},
}

# kind -> (требуемый trigger, диапазон priority).
KIND_TRIGGER = {
    "passive": "passive_always",
    "reaction": "after_dice_revealed",
    "active": "manual_during_activation",
}


def _iter_effects(ability: dict) -> list[dict]:
    effects = ability.get("effect_sequence")
    return [e for e in effects if isinstance(e, dict)] if isinstance(effects, list) else []


def _effect_params(ability: dict) -> list[dict]:
    return [e.get("params") for e in _iter_effects(ability) if isinstance(e.get("params"), dict)]


def _has_damage_dice(ability: dict) -> bool:
    return any("damage_dice" in params for params in _effect_params(ability))


def validate_hero_contract(path: Path, data: dict) -> None:
    """Ручные проверки контракта способности поверх JSON Schema."""
    hero_id = data.get("id")
    if not isinstance(hero_id, str):
        return
    spec = EXPECTED_HEROES.get(hero_id)
    if spec is None:
        return  # неизвестный герой уже сообщён проверкой набора

    ability = data.get("ability")
    if not isinstance(ability, dict):
        return  # ошибка схемы уже записана

    if ability.get("id") != spec["ability_id"]:
        fail(
            f"{path}: ability.id={ability.get('id')!r}, пин контракта — {spec['ability_id']!r}"
        )
    if ability.get("uses_per_match") != spec["uses_per_match"]:
        fail(
            f"{path}: uses_per_match={ability.get('uses_per_match')!r}, "
            f"пин контракта — {spec['uses_per_match']!r}"
        )

    kind = ability.get("kind")
    trigger = ability.get("trigger")
    expected_trigger = KIND_TRIGGER.get(kind)
    if expected_trigger is not None and trigger != expected_trigger:
        fail(f"{path}: kind={kind!r} требует trigger={expected_trigger!r}, получено {trigger!r}")

    uses = ability.get("uses_per_match")
    if kind == "passive":
        if uses != 0:
            fail(f"{path}: пассивная способность обязана иметь uses_per_match=0")
        if ability.get("condition") != []:
            fail(f"{path}: пассивная способность обязана иметь condition=[]")
        if ability.get("priority") != 0:
            fail(f"{path}: пассивная способность обязана иметь priority=0 (до всех реакций)")
        if ability.get("expires_at") != "match_end":
            fail(f"{path}: пассивная способность обязана иметь expires_at='match_end'")
    if kind == "reaction" and ability.get("expires_at") != "immediate":
        fail(f"{path}: реакция обязана иметь expires_at='immediate'")
    if isinstance(uses, int) and not isinstance(uses, bool) and uses > 0:
        if ability.get("expires_at") not in ("immediate", "match_end", "after_max_distance"):
            fail(f"{path}: недопустимый expires_at={ability.get('expires_at')!r}")
        if ability.get("proposal_v3") == []:
            fail(f"{path}: активная/реакционная способность обязана перечислить proposal_v3 или обосновать их отсутствие")

    cost = ability.get("cost")
    if isinstance(cost, dict):
        if cost.get("charges_mode") == "all" and cost.get("charges") != 0:
            fail(f"{path}: charges_mode='all' требует charges=0")
        if cost.get("consumes_ship_attack") is True and hero_id != "darth_vader":
            fail(f"{path}: consumes_ship_attack=true допустим только у darth_vader (пин v3)")

    # Урон по целям, не ограниченным вражескими кораблями, требует friendly_fire.
    target_filter = ability.get("target_filter")
    if _has_damage_dice(ability):
        limited_to_enemies = (
            isinstance(target_filter, dict) and target_filter.get("target_kind") == "enemy_ship"
        )
        if not limited_to_enemies and ability.get("friendly_fire") is not True:
            fail(f"{path}: урон без ограничения enemy_ship требует friendly_fire=true")

    # Планы тестов обязаны ссылаться на свою задачу EPIC C012–C019.
    test_plan = ability.get("test_plan")
    if isinstance(test_plan, dict):
        for key in ("positive", "negative"):
            text = test_plan.get(key)
            if isinstance(text, str) and spec["epic"] not in text:
                fail(f"{path}: test_plan.{key} не ссылается на задачу {spec['epic']} (EPIC C012–C019)")


def check_hero_set(hero_ids: dict[str, Path]) -> None:
    expected = set(EXPECTED_HEROES)
    actual = set(hero_ids)
    for missing in sorted(expected - actual):
        fail(f"отсутствует карточка героя '{missing}'")
    for extra in sorted(actual - expected):
        fail(f"неизвестный герой '{extra}' (в v3 ровно 8 героев)")


# --------------------------------------------------------------------------
# Основной обход.
# --------------------------------------------------------------------------

def main() -> int:
    global validated_files

    ship_schema = load_schema("ship.schema.json")
    hero_schema = load_schema("hero.schema.json")
    board_schema = load_schema("board.schema.json")
    ruleset_schema = load_schema("ruleset.schema.json")

    if not DATA_DIR.is_dir():
        fail(f"каталог {DATA_DIR} не найден")
    else:
        ship_ids: dict[str, Path] = {}
        hero_ids: dict[str, Path] = {}
        ships: list[dict] = []
        game: dict | None = None

        for path in sorted(DATA_DIR.rglob("*.json")):
            data = load_json(path)
            if data is None:
                continue
            validated_files += 1
            check_no_floats(data, str(path))
            relative = path.relative_to(DATA_DIR).as_posix()

            if relative.startswith("ships/") and isinstance(data, dict):
                validate_schema(data, ship_schema, str(path))
                validate_ship_file(path, data, ship_ids)
                ships.append(data)
            elif relative.startswith("heroes/") and isinstance(data, dict):
                validate_schema(data, hero_schema, str(path))
                validate_hero_contract(path, data)
                hero_id = data.get("id")
                if isinstance(hero_id, str):
                    if hero_id != path.stem:
                        fail(f"{path}: поле id={hero_id!r} не совпадает с именем файла {path.stem!r}")
                    if hero_id in hero_ids:
                        fail(f"{path}: дубликат id героя '{hero_id}' (уже в {hero_ids[hero_id]})")
                    hero_ids[hero_id] = path
            elif relative == "board.json" and isinstance(data, dict):
                validate_schema(data, board_schema, str(path))
                expected_cells = 3 * data.get("radius", 0) * (data.get("radius", 0) + 1) + 1
                if data.get("cell_count") != expected_cells:
                    fail(
                        f"{path}: cell_count={data.get('cell_count')} не равен "
                        f"3*radius*(radius+1)+1={expected_cells} для radius={data.get('radius')}"
                    )
            elif relative == "game.json" and isinstance(data, dict):
                validate_schema(data, ruleset_schema, str(path))
                for key, expected in EXPECTED_GAME.items():
                    if data.get(key) != expected:
                        fail(f"{path}: {key}={data.get(key)!r}, норматив v3 — {expected!r}")
                game = data
            elif relative.startswith("scenarios/") and isinstance(data, dict):
                validate_scenario(path, data, EXPECTED_GAME["fleet_size"])
            else:
                fail(f"{path}: файл вне известных категорий ({relative})")

        if game is not None:
            check_draft_feasibility(ships, game)
        else:
            fail("data/rulesets/v3/game.json не найден или не разобран")

        if len(ship_ids) == 0:
            fail("не найдено ни одной карточки корабля")
        if len(hero_ids) == 0:
            fail("не найдено ни одной карточки героя")
        if hero_ids:
            check_hero_set(hero_ids)

    if validated_files == 0:
        fail("не проверено ни одного файла данных")

    if errors:
        for message in errors:
            print(f"ОШИБКА: {message}", file=sys.stderr)
        print(f"ПРОВАЛЕНО: {len(errors)} ошибок в {validated_files} файлах", file=sys.stderr)
        return 1

    print(f"OK: {validated_files} files validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
