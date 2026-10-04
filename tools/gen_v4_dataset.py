#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор датасета ruleset v4 «Эпохи и фракции».

Зачем скрипт, а не рукописные JSON (как в v3): в v4 стоимость корабля в драфте
считается по формуле (docs/rules/rules-v4-factions.md §4), и рукописные числа
неизбежно разъедутся с формулой при любой правке характеристик. Здесь лежит
единственный источник истины по контенту, а data/rulesets/v4/** — его
детерминированный вывод (коммитится в репозиторий, как обычные данные).

Запуск:  python3 tools/gen_v4_dataset.py
Проверка: python3 tools/validate_v4.py

Правило совместимости: 11 кораблей и 8 героев ruleset v3 сохранены полностью,
с теми же id и характеристиками боя; v4 только добавляет им поля (фракция,
эпоха, роль, дальность, гипердрайв) и пересчитывает цену драфта.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "rulesets" / "v4"

SCHEMA_VERSION = 2


def write(rel: str, payload: object) -> None:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Фракции и эпохи
# ---------------------------------------------------------------------------

ERAS = [
    {
        "id": "fall_of_republic",
        "display_name": "Закат Республики",
        "episodes": [1, 2, 3],
        "years": "32–19 ДБЯ",
        "note": "Войны клонов: Республика против Конфедерации независимых систем.",
    },
    {
        "id": "galactic_civil_war",
        "display_name": "Гражданская война",
        "episodes": [4, 5, 6],
        "years": "0–4 ПБЯ",
        "note": "Галактическая Империя против Альянса повстанцев.",
    },
    {
        "id": "new_order",
        "display_name": "Новый порядок",
        "episodes": [7, 8, 9],
        "years": "34–35 ПБЯ",
        "note": "Первый Орден против Сопротивления.",
    },
    {
        "id": "any",
        "display_name": "Вне эпохи",
        "episodes": [],
        "years": "—",
        "note": "Наёмники, пираты и корабли, встречающиеся во всех трилогиях.",
    },
]

FACTIONS = [
    {
        "id": "republic",
        "display_name": "Галактическая Республика",
        "short": "Республика",
        "era": "fall_of_republic",
        "alignment": "light",
        "color": "#c8102e",
        "doctrine": "Числом и строем: слабые поодиночке корабли усиливаются, когда летят звеном.",
        "trait": {
            "id": "unity_drill",
            "name": "Строевая выучка",
            "text": "Республиканский корабль получает +1 к силе атаки, если хотя бы один союзный республиканский корабль стоит на расстоянии 1–2 клетки от цели.",
        },
        "npc": False,
    },
    {
        "id": "separatists",
        "display_name": "Конфедерация независимых систем",
        "short": "Сепаратисты",
        "era": "fall_of_republic",
        "alignment": "dark",
        "color": "#8a6a2f",
        "doctrine": "Дроиды дёшевы: много дешёвых корпусов и переброс неудачных кубиков.",
        "trait": {
            "id": "droid_swarm",
            "name": "Дроидный рой",
            "text": "Если во флоте 3 корабля сепаратистов, каждый из них один раз за матч перебрасывает кубик атаки, выпавший на 1.",
        },
        "npc": False,
    },
    {
        "id": "empire",
        "display_name": "Галактическая Империя",
        "short": "Империя",
        "era": "galactic_civil_war",
        "alignment": "dark",
        "color": "#2f3b45",
        "doctrine": "Броня и дальний огонь: тяжёлые корпуса, лучшие сектора по носу.",
        "trait": {
            "id": "fear_doctrine",
            "name": "Доктрина страха",
            "text": "Имперский корабль, атакующий цель с меньшим текущим HP, получает +1 к силе атаки.",
        },
        "npc": False,
    },
    {
        "id": "rebels",
        "display_name": "Альянс повстанцев",
        "short": "Повстанцы",
        "era": "galactic_civil_war",
        "alignment": "light",
        "color": "#e8a33d",
        "doctrine": "Манёвр и риск: дешёвые истребители, бонусы за атаку в хвост и с фланга.",
        "trait": {
            "id": "rogue_manoeuvre",
            "name": "Манёвр разбойной эскадрильи",
            "text": "Повстанческий корабль, атакующий цель в её задний сектор (B, BL, BR), получает +1 к силе атаки.",
        },
        "npc": False,
    },
    {
        "id": "first_order",
        "display_name": "Первый Орден",
        "short": "Первый Орден",
        "era": "new_order",
        "alignment": "dark",
        "color": "#b3b8bd",
        "doctrine": "Скорость и давление: дешёвые быстрые истребители и точный огонь.",
        "trait": {
            "id": "relentless_advance",
            "name": "Неотвратимое наступление",
            "text": "Корабль Первого Ордена, который в этой активации сдвинулся вперёд минимум на 2 клетки, получает +1 к силе атаки до конца активации.",
        },
        "npc": False,
    },
    {
        "id": "resistance",
        "display_name": "Сопротивление",
        "short": "Сопротивление",
        "era": "new_order",
        "alignment": "light",
        "color": "#e05a2b",
        "doctrine": "Мало кораблей, но каждый чинится и дотягивает до конца.",
        "trait": {
            "id": "keep_them_flying",
            "name": "Дотянуть до базы",
            "text": "Корабль Сопротивления, не атаковавший в свою активацию и не получивший урона в прошлом раунде, восстанавливает 1 HP (не выше максимума).",
        },
        "npc": False,
    },
    {
        "id": "bounty_hunters",
        "display_name": "Охотники за головами",
        "short": "Охотники",
        "era": "any",
        "alignment": "neutral",
        "color": "#4f7a5a",
        "doctrine": "Наёмники: берут добычу за головы и играют в любой эпохе.",
        "trait": {
            "id": "bounty_contract",
            "name": "Контракт",
            "text": "Уничтожив вражеский корабль, корабль охотника немедленно получает 2 заряда (не выше максимума).",
        },
        "npc": False,
    },
    {
        "id": "pirates",
        "display_name": "Пираты Внешнего кольца",
        "short": "Пираты",
        "era": "any",
        "alignment": "hostile",
        "color": "#7a3f8a",
        "doctrine": "Нейтральная фракция поля: пираты не принадлежат игрокам и нападают на ближайшего.",
        "trait": {
            "id": "scavengers",
            "name": "Стервятники",
            "text": "Пиратский корабль атакует ближайший корабль любого игрока; при равенстве — того, у кого меньше текущих HP.",
        },
        "npc": True,
    },
]

# Пары «противник эпохи» — используются сценариями и драфтом.
ERA_MATCHUPS = {
    "fall_of_republic": ["republic", "separatists"],
    "galactic_civil_war": ["empire", "rebels"],
    "new_order": ["first_order", "resistance"],
}


# ---------------------------------------------------------------------------
# 2. Способности кораблей (каталог) и очки стоимости
# ---------------------------------------------------------------------------
# points — вклад способности в сырую стоимость (см. §4 правил v4).

SHIP_ABILITIES = [
    ("resurrection", "Воскрешение", "При взрыве с шансом 1/2 корабль возвращается на ту же клетку с d4 HP (один раз за матч).", 2),
    ("lucky_shot", "Спорный шанс", "При атаке с шансом 1/2 наносит минимум 1 урона, даже если проиграл бросок.", 2),
    ("reroll_one", "Переброс единицы", "С шансом 1/2 перебрасывает кубик атаки, выпавший на 1.", 1),
    ("transform_to_phantom", "Стыковка «Фантома»", "Если в команде герой экипажа «Призрака» из «Повстанцев» (Гера, Кэнан, Эзра, Сабин, Зеб, Чоппер): при взрыве вместо удаления с поля превращается в «Фантом» (2 HP) на той же клетке.", 3),
    ("ranged_shot", "Дальний выстрел", "Атакует на любую дистанцию в пределах max_range; каждая клетка сверх первой — штраф к силе.", 0),
    ("torpedoes", "Протонные торпеды", "Дважды за матч атака по цели на дистанции 1–3 получает +2 к силе и игнорирует щит.", 3),
    ("ion_cannon", "Ионная пушка", "Вместо урона снимает у цели 2 заряда (щит не защищает).", 2),
    ("bomb_rack", "Бомбовый сброс", "Атака по цели, стоящей на соседней клетке позади (сектор B), наносит +1 урона.", 2),
    ("shield_projector", "Проектор щита", "Союзный корабль на расстоянии 1 получает +1 к защите.", 2),
    ("repair_bay", "Ремонтный док", "Раз в раунд восстанавливает 1 HP себе или союзнику на соседней клетке.", 3),
    ("carrier", "Ангар", "Раз за матч выпускает звено истребителей: цель на расстоянии 1–2 получает 1d4 урона.", 3),
    ("tractor_beam", "Тяговый луч", "Раз в раунд сдвигает вражеский корабль на расстоянии 1–2 на одну клетку к себе.", 3),
    ("interdictor", "Гравиколодец", "Вражеские корабли на расстоянии 1–3 не могут уходить в гиперпространство.", 3),
    ("cloaking", "Маскировочное поле", "Раз за матч на раунд: по кораблю нельзя атаковать на дистанции больше 1.", 3),
    ("boarding_pods", "Абордажные капсулы", "Может вести абордаж (см. правила v4 §6.4) без ограничения роли.", 2),
    ("point_defense", "Зенитный огонь", "Атаки по этому кораблю на дистанции 2+ получают −1 к силе.", 2),
    ("fast_hyperdrive", "Модифицированный гипердрайв", "Гиперпрыжок стоит на 1 заряд меньше (минимум 1).", 2),
    ("droid_brain", "Дроидный мозг", "Не теряет заряды от ионного оружия и не может быть взят на абордаж.", 1),
    ("squadron_link", "Звеньевая связь", "Если союзный корабль той же фракции стоит на соседней клетке, оба получают +1 к силе атаки.", 2),
    ("heavy_armor", "Тяжёлая броня", "Урон, превышающий 4 за одну атаку, уменьшается до 4.", 2),
    ("superlaser", "Суперлазер", "Раз за матч: уничтожает любой корабль на поле без броска (кроме станций).", 8),
]

ABILITY_POINTS = {a[0]: a[3] for a in SHIP_ABILITIES}

# Очки за гипердрайв: класс 0 (легендарный, «Сокол») .. 4 (буксируемый).
HYPER_POINTS = {0: 3, 1: 2, 2: 1, 3: 0, 4: 0}
NO_HYPERDRIVE_POINTS = -1


def raw_cost(hp, shield, arcs, weapon, engine, hyper, abilities):
    """Сырая стоимость корабля (§4 правил v4). Только целочисленная арифметика."""
    f, fr, br, b, bl, fl = arcs
    raw = hp + 2 * shield
    raw += 2 * f + (fr + fl) + (br + bl) + b
    raw += 3 * (weapon["max_range"] - 1)
    raw += HYPER_POINTS[hyper["class"]] if hyper else NO_HYPERDRIVE_POINTS
    if engine["move_cost"] is None:
        raw -= 4                      # неподвижная станция
    if engine["pivot_cost"] > 1:
        raw -= 2                      # тяжёлый разворот
    if engine["boost"]:
        raw += 1                      # форсаж (2 клетки по прямой за 2 заряда)
    for ability in abilities:
        raw += ABILITY_POINTS[ability]
    return raw


def draft_cost(raw):
    """cost = round(raw / 2.5), округление вверх на .5, минимум 2."""
    return max(2, (raw * 2 + 2) // 5)


SHIPS = []


def ship(sid, name, faction, era, role, hp, shield, arcs, rng, eng, hyper,
         abilities, unique, legacy, desc):
    max_range, penalty, arc_mode = rng
    move_cost, pivot_cost, boost = eng
    weapon = {
        "max_range": max_range,
        "range_penalty_per_hex": penalty,
        "long_range_arc": arc_mode,   # front | front_flank | all
    }
    engine = {"move_cost": move_cost, "pivot_cost": pivot_cost, "boost": boost}
    hyperdrive = None if hyper is None else {
        "class": hyper,
        "charge_cost": max(1, hyper if hyper > 0 else 1),
    }
    raw = raw_cost(hp, shield, arcs, weapon, engine, hyperdrive, abilities)
    SHIPS.append({
        "schema_version": SCHEMA_VERSION,
        "id": sid,
        "display_name": name,
        "description": desc,
        "faction": faction,
        "era": era,
        "role": role,
        "unique": unique,
        "legacy_v3": legacy,
        "draftable": role != "station",
        "raw_cost": raw,
        "draft_cost": draft_cost(raw),
        "max_hp": hp,
        "max_shield": shield,
        "initial_charges": 3,
        "max_charges": 5,
        "strength_die": {"count": 1, "sides": 6},
        "arc_modifiers": list(arcs),
        "weapon": weapon,
        "engine": engine,
        "hyperdrive": hyperdrive,
        "abilities": [{"id": a, "enabled": True} for a in abilities],
    })


F, P, A = "front", "front_flank", "all"       # сектора дальнего огня
FIGHTER = (1, 1, True)                        # move, pivot, boost
HEAVY = (1, 2, False)
STATION = (None, 2, False)


# ---------------------------------------------------------------------------
# 3. Ростер кораблей
# ---------------------------------------------------------------------------
# ship(id, имя, фракция, эпоха, роль, hp, shield, arcs[F,FR,BR,B,BL,FL],
#      (макс. дальность, штраф за клетку, сектор дальнего огня),
#      (стоимость хода, стоимость поворота, форсаж), класс гипердрайва,
#      способности, уникальный, наследие v3, описание)

# --- Наследие v3: боевые характеристики не изменены -------------------------
ship("tie_fighter", "Истребитель СИД", "empire", "galactic_civil_war", "fighter",
     4, 0, [2, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, None,
     ["resurrection"], False, True,
     "Обычный истребитель Империи. Дёшев, многочислен и лишён гипердрайва: воюет там, где его высадил разрушитель.")
ship("tie_advanced_x1", "TIE Advanced X1", "empire", "galactic_civil_war", "interceptor",
     6, 1, [3, 1, 1, 0, 1, 1], (2, 2, F), FIGHTER, 4,
     [], True, True,
     "Усовершенствованный истребитель СИД X1, звёздный истребитель Вейдера. Вы могли видеть этот СИД в битве у Звезды Смерти в 4 эпизоде.")
ship("xwing_t65", "T-65 X-wing", "rebels", "galactic_civil_war", "fighter",
     4, 0, [2, 1, 0, 1, 0, 1], (2, 2, F), FIGHTER, 1,
     ["lucky_shot"], False, True,
     "Любимый истребитель Люка Скайуокера.")
ship("eta2_actis", "Eta-2 Actis", "republic", "fall_of_republic", "fighter",
     5, 0, [2, 1, 1, 0, 1, 1], (1, 0, F), FIGHTER, None,
     [], False, True,
     "Корабль джедаев Эта-2 класса «Актис». На таком летали Оби-Ван Кеноби с Энакином Скайуокером над Корусантом. Собственного гипердрайва нет — только с гиперкольцом.")
ship("millennium_falcon", "Сокол тысячелетия", "rebels", "any", "freighter",
     8, 1, [2, 1, 2, 0, 2, 1], (2, 2, A), FIGHTER, 0,
     ["fast_hyperdrive"], True, True,
     "Сокол тысячелетия с Хан Соло на борту прошёл Дугу Кесселя по более короткой траектории, пролетев ближе к чёрным дырам.")
ship("star_destroyer", "Имперский звёздный разрушитель", "empire", "galactic_civil_war", "capital",
     8, 1, [2, 2, 1, 1, 1, 2], (3, 2, A), HEAVY, 2,
     ["carrier", "tractor_beam"], False, True,
     "Однажды Сокол тысячелетия пролетел в крошечное пространство между двумя разрушителями, которые чуть не столкнулись, пытаясь его схватить.")
ship("death_star_1", "Звезда Смерти I", "empire", "galactic_civil_war", "station",
     11, 2, [7, 0, 0, -1, 0, 0], (6, 2, A), STATION, None,
     ["ranged_shot", "superlaser"], True, True,
     "Боевая станция Империи. Дальний выстрел: атакует корабль на любой дистанции, каждая клетка — штраф к силе. Уничтожена Люком Скайуокером на X-wing.")
ship("slave_1", "РАБ I", "bounty_hunters", "any", "gunship",
     6, 1, [3, 1, 0, 2, 0, 1], (2, 2, A), FIGHTER, 2,
     ["bomb_rack"], True, True,
     "Личный корабль Джанго Фетта и Бобы Фетта, охотников за головами. Сбрасывает сейсмические заряды в хвост преследователю.")
ship("ghost", "Призрак", "rebels", "galactic_civil_war", "freighter",
     6, 1, [2, 1, 0, 2, 0, 1], (2, 2, A), FIGHTER, 2,
     ["transform_to_phantom"], True, True,
     "Большой звездолёт повстанцев. При взрыве превращается в «Фантом».")
ship("phantom", "Фантом", "rebels", "galactic_civil_war", "fighter",
     2, 0, [2, 1, 0, -1, 0, 1], (1, 0, F), FIGHTER, 3,
     [], True, True,
     "Маленький истребитель, пристыкованный к хвосту «Призрака». В драфт не берётся.")
ship("vulture_droid", "Дроид-стервятник", "separatists", "fall_of_republic", "fighter",
     4, 0, [1, 1, 1, 0, 1, 1], (1, 0, F), FIGHTER, None,
     ["reroll_one", "droid_brain"], False, True,
     "Дроид сепаратистов из первых трёх эпизодов. Сам по себе гипердрайва не имеет — доставляется кораблём-маткой.")

# --- Республика -------------------------------------------------------------
ship("delta7_aethersprite", "Дельта-7 «Эфирная фея»", "republic", "fall_of_republic", "fighter",
     4, 0, [2, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, None,
     [], False, False,
     "Лёгкий джедайский перехватчик Оби-Вана из второго эпизода. Гипердрайв только с кольцом.")
ship("arc170", "ARC-170", "republic", "fall_of_republic", "bomber",
     6, 1, [2, 1, 1, 1, 1, 1], (2, 2, P), FIGHTER, 2,
     ["torpedoes", "bomb_rack"], False, False,
     "Тяжёлый разведывательно-ударный истребитель Республики с хвостовым стрелком и протонными торпедами.")
ship("v19_torrent", "V-19 «Торрент»", "republic", "fall_of_republic", "fighter",
     4, 0, [2, 1, 0, 0, 0, 1], (2, 2, F), FIGHTER, None,
     ["squadron_link"], False, False,
     "Массовый истребитель клонов. Воюет звеньями: рядом с собратом бьёт заметно больнее.")
ship("laat_gunship", "Штурмовой транспорт LAAT/i", "republic", "fall_of_republic", "support",
     6, 0, [2, 1, 1, 1, 1, 1], (1, 0, F), FIGHTER, None,
     ["boarding_pods", "repair_bay"], False, False,
     "Десантный канонерский катер клонов: высаживает абордажную команду и латает союзников прямо в бою.")
ship("naboo_n1", "Истребитель N-1", "republic", "fall_of_republic", "fighter",
     4, 0, [2, 1, 0, 1, 0, 1], (1, 0, F), FIGHTER, 1,
     [], False, False,
     "Хромированный истребитель Набу из первого эпизода. Быстрый гипердрайв, слабое вооружение.")
ship("naboo_royal_cruiser", "Королевский корабль Набу", "republic", "fall_of_republic", "transport",
     7, 2, [1, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, 1,
     ["shield_projector", "repair_bay"], True, False,
     "Дипломатический корабль Падме Амидалы: почти не вооружён, но держит щит над всем звеном.")
ship("venator", "Звёздный разрушитель «Венатор»", "republic", "fall_of_republic", "capital",
     9, 2, [2, 2, 1, 1, 1, 2], (3, 2, A), HEAVY, 2,
     ["carrier", "point_defense"], False, False,
     "Ударный авианосец Республики: выпускает звенья истребителей и отбивает дальние атаки зенитным огнём.")

# --- Сепаратисты ------------------------------------------------------------
ship("tri_fighter", "Дроид-трёхкрылка", "separatists", "fall_of_republic", "interceptor",
     4, 0, [2, 1, 1, 0, 1, 1], (2, 2, F), FIGHTER, None,
     ["droid_brain", "squadron_link"], False, False,
     "Скоростной дроид-перехватчик третьего эпизода: три крыла, три пушки, ноль инстинкта самосохранения.")
ship("hyena_bomber", "Бомбардировщик «Гиена»", "separatists", "fall_of_republic", "bomber",
     5, 0, [1, 1, 0, 2, 0, 1], (1, 0, F), FIGHTER, None,
     ["droid_brain", "bomb_rack"], False, False,
     "Дроид-бомбардировщик Конфедерации: заходит сверху и высыпает боезапас на корму цели.")
ship("nantex_fighter", "Нантекс", "separatists", "fall_of_republic", "interceptor",
     4, 0, [2, 1, 0, 0, 0, 1], (2, 1, F), FIGHTER, None,
     ["tractor_beam"], False, False,
     "Геонозианский истребитель с тяговым лучом: подтягивает жертву под собственные пушки.")
ship("soulless_one", "«Бездушный»", "separatists", "fall_of_republic", "gunship",
     6, 1, [3, 1, 1, 0, 1, 1], (2, 2, F), FIGHTER, 1,
     [], True, False,
     "Личный «Белбуллаб-22» генерала Гривуса.")
ship("munificent", "Фрегат «Мунифисент»", "separatists", "fall_of_republic", "corvette",
     7, 1, [2, 1, 1, 1, 1, 1], (3, 2, A), HEAVY, 2,
     ["ion_cannon", "droid_brain"], False, False,
     "Банковский фрегат Конфедерации: ионные залпы обесточивают жертву перед абордажем.")
ship("providence", "«Провиденс»", "separatists", "fall_of_republic", "capital",
     10, 2, [2, 2, 1, 1, 1, 2], (3, 2, A), HEAVY, 2,
     ["carrier", "boarding_pods"], True, False,
     "Флагман Конфедерации — «Незримая длань» Гривуса. Возит дроидов ротами.")

# --- Империя ----------------------------------------------------------------
ship("tie_interceptor", "СИД-перехватчик", "empire", "galactic_civil_war", "interceptor",
     4, 0, [3, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, None,
     [], False, False,
     "Заострённые крылья, четыре пушки, никакой защиты: элита имперских эскадрилий.")
ship("tie_bomber", "СИД-бомбардировщик", "empire", "galactic_civil_war", "bomber",
     5, 0, [2, 1, 0, 2, 0, 1], (1, 0, F), FIGHTER, None,
     ["bomb_rack", "torpedoes"], False, False,
     "Двухкорпусный СИД для ударов по крупным целям и астероидным базам.")
ship("lambda_shuttle", "Шаттл класса «Лямбда»", "empire", "galactic_civil_war", "support",
     6, 1, [1, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, 1,
     ["boarding_pods", "repair_bay"], False, False,
     "Курьерский и абордажный шаттл Империи со складывающимися крыльями.")
ship("interdictor", "Крейсер «Иммобилайзер»", "empire", "galactic_civil_war", "capital",
     8, 2, [1, 1, 1, 1, 1, 1], (2, 2, A), HEAVY, 2,
     ["interdictor", "tractor_beam"], False, False,
     "Крейсер с гравитационными проекторами: выдёргивает корабли из гиперпространства и не даёт уйти.")
ship("executor", "Суперразрушитель «Палач»", "empire", "galactic_civil_war", "capital",
     14, 3, [3, 2, 2, 1, 2, 2], (4, 2, A), HEAVY, 3,
     ["carrier", "point_defense", "heavy_armor", "tractor_beam"], True, False,
     "Флагман Дарта Вейдера. В драфт не входит — босс сценария «Эскадра против флагмана».")

# --- Повстанцы --------------------------------------------------------------
ship("ywing_btla4", "Y-wing BTL-A4", "rebels", "galactic_civil_war", "bomber",
     5, 1, [2, 1, 0, 1, 0, 1], (2, 2, P), FIGHTER, 2,
     ["ion_cannon", "bomb_rack"], False, False,
     "Рабочая лошадь Альянса: медленный, но с ионной пушкой и бомбами.")
ship("awing_rz1", "A-wing RZ-1", "rebels", "galactic_civil_war", "interceptor",
     3, 0, [2, 1, 0, 0, 0, 1], (2, 1, F), FIGHTER, 1,
     ["fast_hyperdrive"], False, False,
     "Самый быстрый истребитель Альянса. Хрупкий, но уходит в прыжок раньше всех.")
ship("bwing", "B-wing/E2", "rebels", "galactic_civil_war", "bomber",
     6, 1, [3, 1, 0, 1, 0, 1], (2, 2, P), FIGHTER, 2,
     ["ion_cannon", "torpedoes"], False, False,
     "Крестокрыл-«молот» из шестого эпизода: тяжёлое вооружение по носу, неповоротлив в свалке.")
ship("mc80_home_one", "Крейсер MC80 «Дом Один»", "rebels", "galactic_civil_war", "capital",
     10, 2, [2, 1, 1, 1, 1, 1], (3, 2, A), HEAVY, 2,
     ["repair_bay", "shield_projector", "carrier"], True, False,
     "Флагман адмирала Акбара при Эндоре: чинит звено и держит щит над союзниками.")
ship("gr75_transport", "Транспорт GR-75", "rebels", "galactic_civil_war", "transport",
     6, 2, [0, 0, 0, 0, 0, 0], (1, 0, F), FIGHTER, 2,
     ["shield_projector", "repair_bay"], False, False,
     "Безоружный транспорт эвакуации с Хота. Ценен только тем, что довозит остальных.")

# --- Первый Орден -----------------------------------------------------------
ship("tie_fo", "СИД/fo", "first_order", "new_order", "fighter",
     4, 1, [2, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, 3,
     [], False, False,
     "Истребитель Первого Ордена: тот же силуэт, но с дефлектором и гипердрайвом.")
ship("tie_sf", "СИД/sf (спецназ)", "first_order", "new_order", "bomber",
     5, 1, [2, 1, 0, 2, 0, 1], (2, 2, P), FIGHTER, 3,
     ["bomb_rack"], False, False,
     "Двухместный СИД спецназа с хвостовой турелью.")
ship("tie_silencer", "СИД «Тихушник»", "first_order", "new_order", "interceptor",
     6, 1, [3, 1, 1, 0, 1, 1], (2, 1, F), FIGHTER, 2,
     ["torpedoes"], True, False,
     "Личный истребитель Кайло Рена из восьмого эпизода.")
ship("upsilon_shuttle", "Шаттл класса «Ипсилон»", "first_order", "new_order", "support",
     7, 1, [1, 1, 0, 0, 0, 1], (2, 2, F), FIGHTER, 1,
     ["boarding_pods", "point_defense"], False, False,
     "Командный шаттл с огромными крыльями-сенсорами и абордажной командой штурмовиков.")
ship("resurgent_destroyer", "Разрушитель класса «Возрождение»", "first_order", "new_order", "capital",
     10, 2, [2, 2, 1, 1, 1, 2], (3, 2, A), HEAVY, 2,
     ["carrier", "heavy_armor"], False, False,
     "Звёздный разрушитель нового поколения: вдвое крупнее имперского и заметно толще в броне.")

# --- Сопротивление ----------------------------------------------------------
ship("xwing_t70", "T-70 X-wing", "resistance", "new_order", "fighter",
     5, 1, [2, 1, 0, 1, 0, 1], (2, 2, P), FIGHTER, 1,
     ["torpedoes"], False, False,
     "Наследник Т-65 в звене «Чёрных»: щит, торпеды и быстрый гипердрайв.")
ship("rz2_awing", "A-wing RZ-2", "resistance", "new_order", "interceptor",
     4, 0, [2, 1, 0, 0, 0, 1], (2, 1, F), FIGHTER, 1,
     ["fast_hyperdrive"], False, False,
     "Перехватчик Сопротивления: догоняет кого угодно и первым уходит в прыжок.")
ship("mg100_bomber", "Бомбардировщик MG-100", "resistance", "new_order", "bomber",
     6, 1, [1, 1, 0, 3, 0, 1], (1, 0, F), HEAVY, 3,
     ["bomb_rack", "heavy_armor"], False, False,
     "«Звёздная крепость» из восьмого эпизода: неповоротливая баржа, высыпающая бомбы прямо под себя.")
ship("raddus_cruiser", "Крейсер MC85 «Раддус»", "resistance", "new_order", "capital",
     11, 2, [2, 1, 1, 1, 1, 1], (3, 2, A), HEAVY, 1,
     ["repair_bay", "shield_projector"], True, False,
     "Флагман Сопротивления. Единственный корабль, способный на гипертаран Холдо (см. героя «Холдо»).")
ship("resistance_transport", "Транспорт «Ро»", "resistance", "new_order", "transport",
     5, 1, [1, 0, 0, 0, 0, 0], (1, 0, F), FIGHTER, 2,
     ["cloaking"], False, False,
     "Малозаметный челнок эвакуации: под маскировкой его не достать дальним огнём.")

# --- Охотники за головами ---------------------------------------------------
ship("punishing_one", "«Каратель»", "bounty_hunters", "any", "gunship",
     6, 1, [2, 1, 1, 1, 1, 1], (2, 2, A), FIGHTER, 1,
     ["point_defense"], True, False,
     "Корабль Зукусса и Денгара из пятого эпизода: круговые сектора и плотный оборонительный огонь.")
ship("hounds_tooth", "«Клык гончей»", "bounty_hunters", "any", "freighter",
     7, 1, [2, 1, 0, 1, 0, 1], (2, 2, A), FIGHTER, 2,
     ["tractor_beam", "boarding_pods"], True, False,
     "Корабль трандошанина Босска: ловит жертву лучом и берёт живьём.")

ship("z95_headhunter", "Z-95 «Охотник за головами»", "bounty_hunters", "any", "fighter",
     4, 0, [2, 1, 0, 0, 0, 1], (2, 2, F), FIGHTER, 2,
     [], False, False,
     "Прадед X-wing: дешёвый, живучий ровно настолько, чтобы окупиться, любимец наёмников всех эпох.")
# «Патрульный „Огнемёт-31“» удалён: Firespray-31 — это и есть «РАБ I» Бобы Фетта,
# в игре был бы дублем одного корабля под двумя именами (замечание владельца).

# --- Пираты (нейтральная фракция поля) --------------------------------------
ship("pirate_corsair", "Пиратский корсар", "pirates", "any", "freighter",
     5, 0, [2, 1, 0, 1, 0, 1], (1, 0, F), FIGHTER, None,
     [], False, False,
     "Переделанный грузовик с наваренными пушками. Управляется полем, а не игроком.")
ship("pirate_marauder", "Пиратский мародёр", "pirates", "any", "corvette",
     7, 1, [2, 1, 1, 1, 1, 1], (2, 2, A), HEAVY, None,
     ["boarding_pods"], False, False,
     "Лёгкий корвет пиратов Внешнего кольца: берёт на абордаж всех, кто зазевался.")
ship("pirate_skiff", "Пиратский скиф", "pirates", "any", "fighter",
     3, 0, [1, 1, 0, 0, 0, 1], (1, 0, F), FIGHTER, None,
     [], False, False,
     "Одноместная летающая платформа контрабандистов.")

# Не берутся в драфт: «Фантом» (группа X исходных правил), все корабли пиратов и «Палач» —
# сценарный босс «Эскадры против флагмана» (решение владельца от 2026-09-19: в бюджет 24 при трёх
# кораблях он не помещается, а в одиночку против трёх кораблей даёт ничью — к нему не подходят).
# «Каратель» (JumpMaster 5000) — нет 3D-модели со свободной лицензией, на поле он был заглушкой-конусом
# (решение владельца от 2026-09-24: найти модель или убрать корабль, чтобы не портил вид).
for _s in SHIPS:
    if _s["id"] in ("phantom", "executor", "punishing_one") or _s["faction"] == "pirates":
        _s["draftable"] = False


# Баланс: утверждённые правки чисел карточек (data/balance/v4_patch.json — вывод оптимизатора
# sim_v4, перенесённый решением владельца). Кораблям меняются только сектора (борта парой),
# корпус, щит и поправка цены; цена = формула v4 + поправка. Карточка хранит «было → стало».
BALANCE_FILE = Path(__file__).resolve().parents[1] / "data" / "balance" / "v4_patch.json"
BALANCE = json.loads(BALANCE_FILE.read_text(encoding="utf-8")) if BALANCE_FILE.exists() else {"ships": {}, "heroes": {}}
UNIT_IDX = {"F": (0,), "sides": (1, 5), "rear": (2, 4), "B": (3,)}
BUDGET_TOTAL = 26                        # общий бюджет драфта на героя и корабли
HERO_COST_DEFAULT = 2                    # цена героя по умолчанию: кораблям остаётся 24
for _s in SHIPS:
    _d = BALANCE["ships"].get(_s["id"])
    if not _d:
        continue
    _before = {"arc_modifiers": list(_s["arc_modifiers"]), "max_hp": _s["max_hp"], "max_shield": _s["max_shield"],
               "draft_cost": _s["draft_cost"]}
    for _k, _idx in UNIT_IDX.items():
        for _i in _idx:
            _s["arc_modifiers"][_i] += _d.get(_k, 0)
    _s["max_hp"] += _d.get("hp", 0)
    _s["max_shield"] += _d.get("shield", 0)
    _raw = raw_cost(_s["max_hp"], _s["max_shield"], _s["arc_modifiers"], _s["weapon"], _s["engine"],
                    _s["hyperdrive"], [a["id"] for a in _s["abilities"]])
    _s["raw_cost"] = _raw
    _s["cost_adjust"] = _d.get("cost", 0)
    _s["draft_cost"] = max(2, draft_cost(_raw) + _s["cost_adjust"])
    _s["balance_patch"] = {"before": _before, "delta": _d, "source": BALANCE.get("source", "")}


# ---------------------------------------------------------------------------
# 4. Герои
# ---------------------------------------------------------------------------
# Правило исходных правил («Расширение игры»): герой — персонаж основных
# 9 эпизодов, способность «не очень хорошая, но и не слишком плохая».
# Все 8 героев v3 сохранены дословно: их блок ability читается из
# data/rulesets/v3/heroes/*.json и не переписывается — v4 только добавляет
# фракцию, эпоху и (некоторым) фракционную синергию.

V3_HEROES = ROOT / "data" / "rulesets" / "v3" / "heroes"

HEROES = []


def hero(hid, name, faction, era, desc, ability, synergy=None):
    HEROES.append({
        "schema_version": SCHEMA_VERSION,
        "id": hid,
        "display_name": name,
        "description": desc,
        "faction": faction,
        "era": era,
        "ability": ability,
        "synergy": synergy,
    })


def ability(aid, name, text, kind, trigger, charges, uses, op, params,
            friendly_fire=False, priority=20, expires="immediate", events=None):
    return {
        "id": aid,
        "name": name,
        "text": text,
        "kind": kind,                 # active | reaction | passive
        "trigger": trigger,
        "condition": [],
        "target_filter": None,
        "cost": {"charges_mode": "fixed", "charges": charges,
                 "consumes_ship_attack": False},
        "uses_per_match": uses,       # 0 = постоянно (passive)
        "effect_sequence": [{"op": op, "params": params}],
        "priority": priority,
        "friendly_fire": friendly_fire,
        "expires_at": expires,
        "events": events or ["AbilityUsed"],
    }


def synergy(sid, name, text, faction, min_count, effects):
    return {
        "id": sid,
        "name": name,
        "text": text,
        "scope": "fleet",
        "condition": {"faction": faction, "min_ships": min_count},
        "effects": effects,
    }


def legacy_hero(hid, faction, era, synergy_obj=None):
    src = json.loads((V3_HEROES / f"{hid}.json").read_text(encoding="utf-8"))
    HEROES.append({
        "schema_version": SCHEMA_VERSION,
        "id": src["id"],
        "display_name": src["display_name"],
        "description": src["description"],
        "faction": faction,
        "era": era,
        "ability": src["ability"],          # дословно из v3, без изменений
        "synergy": synergy_obj,
    })


# --- Наследие v3 ------------------------------------------------------------
legacy_hero("obi_wan", "republic", "fall_of_republic", synergy(
    "high_ground", "Высокая позиция",
    "Пока в вашем флоте есть хотя бы один республиканский корабль, ваши корабли получают +1 к защите в секторе F (атака в лоб).",
    "republic", 1, [{"op": "arc_bonus", "params": {"sector": 0, "role": "defender", "value": 1}}]))
legacy_hero("anakin", "republic", "fall_of_republic", synergy(
    "chosen_pilot", "Избранный пилот",
    "Один ваш республиканский корабль (выбирается в начале матча) получает +1 к силе атаки и −1 к защите.",
    "republic", 1, [{"op": "mark_ship", "params": {"strength": 1, "defense": -1, "count": 1}}]))
legacy_hero("luke", "rebels", "galactic_civil_war", synergy(
    "force_is_strong", "Сила велика в нём",
    "Пока у вашего флота осталось не больше одного корабля, этот корабль получает +2 к силе атаки.",
    "rebels", 1, [{"op": "last_stand", "params": {"strength": 2, "ships_left_max": 1}}]))
legacy_hero("han_solo", "rebels", "any", synergy(
    "smugglers_luck", "Удача контрабандиста",
    "Ваш корабль с гипердрайвом класса 0–1 платит за гиперпрыжок на 1 заряд меньше.",
    "rebels", 1, [{"op": "hyperjump_discount", "params": {"max_class": 1, "value": 1}}]))
legacy_hero("darth_vader", "empire", "galactic_civil_war", synergy(
    "dark_command", "Тёмное командование",
    "Все ваши имперские корабли получают +1 к силе атаки в секторе F.",
    "empire", 1, [{"op": "arc_bonus", "params": {"sector": 0, "role": "attacker", "value": 1}}]))
legacy_hero("phasma", "first_order", "new_order", synergy(
    "stormtrooper_drill", "Выучка штурмовиков",
    "Ваши корабли Первого Ордена не теряют заряды от ионного оружия.",
    "first_order", 1, [{"op": "immune", "params": {"to": "ion_cannon"}}]))
legacy_hero("jango_fett", "bounty_hunters", "fall_of_republic", synergy(
    "mandalorian_arsenal", "Мандалорский арсенал",
    "Мина, поставленная владельцем, наносит 1d4+1 урона.",
    "bounty_hunters", 1, [{"op": "mine_damage_bonus", "params": {"value": 1}}]))
legacy_hero("boba_fett", "bounty_hunters", "galactic_civil_war", synergy(
    "hunters_prize", "Добыча охотника",
    "Уничтожив вражеский корабль, ваш корабль восстанавливает 1 HP.",
    "bounty_hunters", 1, [{"op": "heal_on_kill", "params": {"value": 1}}]))

# --- Республика -------------------------------------------------------------
hero("padme_amidala", "Падме Амидала", "republic", "fall_of_republic",
     "Королева, а затем сенатор Набу; голос Республики в Сенате и мать Люка и Леи.",
     ability("diplomatic_immunity", "Дипломатическая неприкосновенность",
             "1 раз в игру: до конца раунда по одному вашему кораблю нельзя атаковать на дистанции больше 1.",
             "active", "manual_during_activation", 1, 1,
             "grant_status", {"status": "diplomatic_shield", "duration_rounds": 1, "target": "own_ship"}),
     synergy("unity_force", "Сила единства",
             "За каждый республиканский корабль в вашем флоте все ваши республиканские корабли получают +1 к силе атаки (максимум +3). "
             "Если все три корабля флота республиканские, каждый из них дополнительно получает +1 максимального HP и +1 щита.",
             "republic", 1,
             [{"op": "strength_per_faction_ship", "params": {"faction": "republic", "value": 1, "max": 3}},
              {"op": "full_faction_bonus", "params": {"faction": "republic", "min_ships": 3,
                                                      "max_hp": 1, "max_shield": 1}}]))
hero("mace_windu", "Мейс Винду", "republic", "fall_of_republic",
     "Мастер-джедай, глава Ордена, владелец фиолетового светового меча.",
     ability("vaapad", "Ваапад",
             "2 раза в игру: после броска боя, в котором ваш корабль защищается, поменяйте местами кубики атакующего и защищающегося.",
             "reaction", "after_dice_revealed", 0, 2,
             "swap_dice", {"between": ["attacker", "defender"]}, priority=10,
             events=["AbilityUsed", "DieModified"]),
     synergy("vaapad_discipline", "Дисциплина Ваапада",
             "Если бой вплотную по вашему республиканскому кораблю закончился ничьей, атакующий получает 1 урона.",
             "republic", 1, [{"op": "tie_breaker_damage", "params": {"range": 1, "role": "defender", "value": 1}}]))
hero("yoda", "Йода", "republic", "fall_of_republic",
     "Гранд-мастер Ордена джедаев, учитель Люка Скайуокера.",
     ability("force_sight", "Предвидение",
             "Пассивно: в начале каждого раунда вы узнаёте, какой корабль противник активирует первым; 1 раз в игру можете заставить его начать с другого корабля.",
             "active", "round_start", 0, 1,
             "force_activation_order", {"scope": "enemy_seat"}),
     synergy("jedi_council", "Совет джедаев",
             "Все ваши республиканские корабли один раз за матч перебрасывают свой кубик защиты.",
             "republic", 1, [{"op": "grant_reroll", "params": {"role": "defender", "uses": 1}}]))
hero("qui_gon_jinn", "Квай-Гон Джинн", "republic", "fall_of_republic",
     "Мастер-джедай, учитель Оби-Вана, нашедший Энакина на Татуине.",
     ability("living_force", "Живая Сила",
             "1 раз в игру: восстановите 2 HP любому своему кораблю или снимите с него все эффекты (мина, ион, буксир).",
             "active", "manual_during_activation", 1, 1,
             "heal_or_cleanse", {"heal": 2, "target": "own_ship"}),
     synergy("will_of_the_force", "Воля Силы",
             "Раз за матч ваш республиканский корабль, который должен быть уничтожен, остаётся в игре с 1 HP.",
             "republic", 1, [{"op": "cheat_death", "params": {"hp": 1, "uses": 1}}]))

# --- Сепаратисты ------------------------------------------------------------
hero("count_dooku", "Граф Дуку", "separatists", "fall_of_republic",
     "Граф Серенно, бывший джедай, лидер Конфедерации независимых систем.",
     ability("force_lightning", "Молнии Силы",
             "1 раз в игру: вражеский корабль на расстоянии 1–2 теряет 2 заряда и 1 HP (щит не защищает).",
             "active", "manual_during_activation", 1, 1,
             "drain", {"charges": 2, "hp": 1, "ignore_shield": True, "range": [1, 2]}),
     synergy("separatist_command", "Командование Конфедерации",
             "Все ваши корабли сепаратистов получают +1 заряд в начале матча.",
             "separatists", 1, [{"op": "start_charges", "params": {"value": 1}}]))
hero("general_grievous", "Генерал Гривус", "separatists", "fall_of_republic",
     "Киборг-командующий армиями дроидов, коллекционер световых мечей.",
     ability("four_blades", "Четыре клинка",
             "1 раз в игру: ваш корабль атакует в этой активации дважды, второй раз — с −1 к силе.",
             "active", "manual_during_activation", 2, 1,
             "extra_attack", {"count": 1, "strength_modifier": -1}),
     synergy("jedi_hunter", "Охотник на джедаев",
             "Корабли сепаратистов получают +1 к силе атаки по кораблям Республики.",
             "separatists", 1, [{"op": "faction_hatred", "params": {"targets": ["republic"], "strength": 1}}]))
hero("nute_gunray", "Нут Ганрей", "separatists", "fall_of_republic",
     "Вице-король Торговой федерации, трусливый, но богатый союзник Конфедерации.",
     ability("trade_blockade", "Торговая блокада",
             "1 раз в игру: до конца раунда противник не может уходить в гиперпространство.",
             "active", "round_start", 1, 1,
             "block_hyperjump", {"scope": "enemy_seat", "duration_rounds": 1}),
     synergy("droid_foundry", "Дроидная верфь",
             "Если все три ваших корабля — сепаратисты, один уничтоженный дроидный корабль возвращается в игру с 2 HP (один раз за матч).",
             "separatists", 3, [{"op": "respawn", "params": {"hp": 2, "uses": 1, "require_role": "droid"}}]))
hero("darth_maul", "Дарт Мол", "separatists", "fall_of_republic",
     "Забрак-ситх, ученик Дарта Сидиуса, боец с двойным световым мечом.",
     ability("double_strike", "Двойной удар",
             "Пассивно: при атаке вплотную (дистанция 1) ваш корабль наносит +1 урона, но и получает +1 урона от ответных атак.",
             "passive", "always", 0, 0,
             "melee_trade", {"bonus_damage": 1, "extra_damage_taken": 1}),
     synergy("sith_revenge", "Месть ситха",
             "Если ваш корабль сепаратистов уничтожен в бою вплотную, уничтоживший его корабль получает 1 урона (щит не защищает).",
             "separatists", 1, [{"op": "revenge_damage", "params": {"range": 1, "value": 1, "ignore_shield": True}}]))

# --- Империя и ситхи --------------------------------------------------------
hero("emperor_palpatine", "Император Палпатин", "empire", "any",
     "Дарт Сидиус: канцлер, затем Император; тайный хозяин обеих сторон Войн клонов.",
     ability("unlimited_power", "Неограниченная власть",
             "1 раз в игру: любой ваш корабль немедленно получает 3 заряда и атакует вне очереди.",
             "active", "manual_during_activation", 0, 1,
             "grant_charges_and_attack", {"charges": 3}),
     synergy("shroud_of_the_dark_side", "Покров тёмной стороны",
             "Ваши корабли Империи и сепаратистов считаются одной фракцией для всех синергий.",
             "empire", 1, [{"op": "faction_merge", "params": {"factions": ["empire", "separatists"]}}]))
hero("grand_moff_tarkin", "Гранд-мофф Таркин", "empire", "galactic_civil_war",
     "Губернатор Внешнего кольца, командир Звезды Смерти, автор «доктрины страха».",
     ability("fire_at_will", "Огонь по готовности",
             "1 раз в игру: ваш корабль с дальностью 3+ атакует дважды за активацию.",
             "active", "manual_during_activation", 2, 1,
             "extra_attack", {"count": 1, "require_max_range": 3}),
     synergy("iron_discipline", "Железная дисциплина",
             "Ваши имперские корабли не теряют заряды, когда не атакуют: в конце раунда они получают +1 заряд сверх обычного (не выше максимума).",
             "empire", 1, [{"op": "charge_regen_bonus", "params": {"value": 1}}]))
hero("admiral_piett", "Адмирал Пиетт", "empire", "galactic_civil_war",
     "Офицер «Палача», переживший предшественника на этом посту.",
     ability("tighten_the_net", "Сомкнуть сеть",
             "1 раз в игру: сдвиньте два своих корабля на одну клетку каждый вне очереди активации.",
             "active", "manual_during_activation", 2, 1,
             "reposition", {"ships": 2, "distance": 1}),
     synergy("flagship_drill", "Выучка флагмана",
             "Ваши имперские крупные корабли (capital) поворачиваются за 1 заряд вместо 2.",
             "empire", 1, [{"op": "pivot_discount", "params": {"roles": ["capital"], "value": 1}}]))

# --- Повстанцы --------------------------------------------------------------
hero("leia_organa", "Лея Органа", "rebels", "galactic_civil_war",
     "Принцесса Альдераана, лидер Альянса повстанцев, сестра Люка.",
     ability("rebel_briefing", "Инструктаж",
             "1 раз в игру в начале раунда: все ваши корабли получают по 1 заряду.",
             "active", "round_start", 0, 1,
             "grant_charges", {"value": 1, "scope": "own_fleet"}),
     synergy("alliance_command", "Командование Альянса",
             "Если все три ваших корабля — повстанцы, каждый из них получает +1 к силе атаки в секторах BL, B, BR (удар в хвост).",
             "rebels", 3, [{"op": "arc_bonus", "params": {"sector": [2, 3, 4], "role": "attacker", "value": 1}}]))
hero("chewbacca", "Чубакка", "rebels", "any",
     "Вуки-механик и второй пилот «Сокола тысячелетия».",
     ability("field_repair", "Ремонт на коленке",
             "2 раза в игру: восстановите 1 HP или 1 щит своему кораблю в фазе восстановления.",
             "active", "recovery_phase", 0, 2,
             "repair", {"hp": 1, "or_shield": 1, "target": "own_ship"}),
     synergy("wookiee_strength", "Сила вуки",
             "Корабли повстанцев получают +2 к броску абордажа — и при атаке, и при защите.",
             "rebels", 1, [{"op": "boarding_bonus", "params": {"value": 2}}]))
hero("lando_calrissian", "Лэндо Калриссиан", "rebels", "any",
     "Барон-администратор Облачного города, позже генерал Альянса.",
     ability("cape_and_bluff", "Блеф",
             "1 раз в игру: объявите блеф до броска боя. Если вы выигрываете бросок, урон удваивается; если проигрываете — вы теряете дополнительно 1 HP.",
             "active", "before_dice_rolled", 0, 1,
             "double_or_nothing", {"win_multiplier": 2, "lose_extra_damage": 1}),
     synergy("baron_administrator", "Барон-администратор",
             "Если во флоте есть корабль повстанцев, бюджет драфта увеличивается на 2 очка.",
             "rebels", 1, [{"op": "draft_budget_bonus", "params": {"value": 2}}]))
hero("wedge_antilles", "Ведж Антиллес", "rebels", "galactic_civil_war",
     "Пилот «Разбойной эскадрильи», выживший в обеих атаках на Звезду Смерти.",
     ability("stay_on_target", "Держись цели",
             "Пассивно: ваш корабль, атакующий ту же цель второй раунд подряд, получает +1 к силе атаки.",
             "passive", "always", 0, 0,
             "focus_target", {"value": 1}),
     synergy("rogue_squadron", "Разбойная эскадрилья",
             "Если во флоте два и больше истребителя повстанцев (fighter/interceptor), каждый из них получает +1 к защите в секторе F.",
             "rebels", 2, [{"op": "role_bonus", "params": {"roles": ["fighter", "interceptor"], "defense_sector": 0, "value": 1}}]))
hero("admiral_ackbar", "Адмирал Акбар", "rebels", "galactic_civil_war",
     "Мон-каламари, командующий флотом Альянса при Эндоре.",
     ability("its_a_trap", "Это ловушка!",
             "1 раз в игру: отмените одну атаку противника по вашему кораблю с дистанции 2+ (бросок не совершается).",
             "reaction", "before_dice_rolled", 0, 1,
             "cancel_attack", {"min_range": 2}, priority=5,
             events=["AbilityUsed", "AttackCancelled"]),
     synergy("fleet_focus", "Сосредоточить огонь",
             "Ваш крупный корабль (роль capital или corvette) даёт соседним союзникам +1 к силе атаки.",
             "rebels", 1, [{"op": "aura", "params": {"source_role": ["capital", "corvette"], "radius": 1, "strength": 1}}]))

# --- Первый Орден -----------------------------------------------------------
hero("kylo_ren", "Кайло Рен", "first_order", "new_order",
     "Бен Соло, магистр рыцарей Рен, внук Дарта Вейдера.",
     ability("force_stop", "Остановка Силой",
             "2 раза в игру: остановите вражеский корабль — он тратит все заряды и завершает активацию.",
             "active", "manual_during_activation", 2, 2,
             "stun", {"target": "enemy_ship", "range": [1, 3]}),
     synergy("unchecked_rage", "Необузданная ярость",
             "Корабль Первого Ордена, потерявший за один раунд 3 HP и больше, получает +2 к силе атаки до конца своей следующей активации.",
             "first_order", 1, [{"op": "rage", "params": {"hp_lost_threshold": 3, "strength": 2}}]))
hero("general_hux", "Генерал Хакс", "first_order", "new_order",
     "Командующий «Старкиллером» и флотом Первого Ордена.",
     ability("order_barrage", "Массированный залп",
             "1 раз в игру: все ваши корабли атакуют в этом раунде с +1 к силе, но в следующем раунде получают −1 к защите.",
             "active", "round_start", 2, 1,
             "fleet_buff", {"strength": 1, "next_round_defense": -1}),
     synergy("first_order_doctrine", "Доктрина Первого Ордена",
             "Если все три ваших корабля — Первый Орден, каждый получает +1 щита.",
             "first_order", 3, [{"op": "full_faction_bonus", "params": {"faction": "first_order", "min_ships": 3, "max_shield": 1}}]))
hero("snoke", "Верховный лидер Сноук", "first_order", "new_order",
     "Марионетка Палпатина, наставник Кайло Рена.",
     ability("puppet_strings", "Нити кукловода",
             "1 раз в игру: возьмите под контроль вражеский истребитель на одну атаку (он атакует своего союзника).",
             "active", "manual_during_activation", 3, 1,
             "mind_control", {"target_role": ["fighter", "interceptor"], "actions": 1},
             friendly_fire=True),
     synergy("supreme_leader", "Верховный лидер",
             "В начале каждого чётного раунда корабли Первого Ордена получают +1 заряд (не выше максимума).",
             "first_order", 1, [{"op": "periodic_charges", "params": {"every_rounds": 2, "value": 1}}]))

# --- Сопротивление ----------------------------------------------------------
hero("rey", "Рей", "resistance", "new_order",
     "Мусорщица с Джакку, ученица Люка и Леи, внучка Палпатина.",
     ability("raw_power", "Необученная сила",
             "2 раза в игру: перебросьте любой свой кубик; второй результат окончателен.",
             "reaction", "after_dice_revealed", 0, 2,
             "reroll_die", {"die_owner": "own"}, priority=10,
             events=["AbilityUsed", "DieModified"]),
     synergy("last_jedi", "Последняя из джедаев",
             "Корабли Сопротивления получают +1 к защите от атак кораблей Первого Ордена.",
             "resistance", 1, [{"op": "faction_defense", "params": {"versus": ["first_order"], "value": 1}}]))
hero("poe_dameron", "По Дэмерон", "resistance", "new_order",
     "Лучший пилот Сопротивления, командир «Чёрного звена».",
     ability("best_pilot", "Лучший пилот флота",
             "Пассивно: ваш корабль может двигаться на 2 клетки по прямой за 1 заряд один раз в раунд.",
             "passive", "always", 0, 0,
             "free_boost", {"uses_per_round": 1}),
     synergy("black_squadron", "Чёрное звено",
             "Ваши корабли Сопротивления получают +1 к защите, пока стоят на соседних клетках друг с другом.",
             "resistance", 2, [{"op": "adjacency_bonus", "params": {"defense": 1}}]))
hero("finn", "Финн", "resistance", "new_order",
     "FN-2187: штурмовик Первого Ордена, перешедший на сторону Сопротивления.",
     ability("inside_knowledge", "Знание изнутри",
             "Пассивно: ваши атаки по кораблям Первого Ордена и Империи получают +1 к силе.",
             "passive", "always", 0, 0,
             "faction_hatred", {"targets": ["first_order", "empire"], "strength": 1}),
     synergy("defector", "Перебежчик",
             "Раз за матч корабль Сопротивления ведёт абордаж без траты зарядов и без ограничения по роли.",
             "resistance", 1, [{"op": "free_boarding", "params": {"uses": 1}}]))
hero("vice_admiral_holdo", "Вице-адмирал Холдо", "resistance", "new_order",
     "Командующая, протаранившая флот Первого Ордена на световой скорости.",
     ability("holdo_manoeuvre", "Манёвр Холдо",
             "1 раз в игру: ваш корабль с гипердрайвом уничтожается и наносит 1d6 урона всем кораблям на линии прыжка (до 3 клеток).",
             "active", "manual_during_activation", 3, 1,
             "hyperspace_ram", {"damage_dice": {"count": 1, "sides": 6}, "length": 3,
                                "destroys_self": True},
             friendly_fire=True, events=["AbilityUsed", "HyperspaceRam", "DamageApplied", "ShipDestroyed"]),
     synergy("evacuation_command", "Командир эвакуации",
             "Транспорты и крупные корабли Сопротивления начинают матч с +1 щитом.",
             "resistance", 1, [{"op": "role_bonus", "params": {"roles": ["transport", "capital"], "max_shield": 1}}]))
hero("r2_d2", "R2-D2", "resistance", "any",
     "Астромеханический дроид, прошедший все девять эпизодов.",
     ability("astromech_patch", "Латка астромеха",
             "Пассивно: в фазе восстановления ваш корабль с дроидом восстанавливает 1 щит раз в два раунда.",
             "passive", "recovery_phase", 0, 0,
             "shield_regen", {"value": 1, "every_rounds": 2}),
     synergy("astromech_everywhere", "Астромех в каждом крыле",
             "Раз за матч каждый ваш истребитель Сопротивления (fighter/interceptor) отменяет по себе атаку ионной пушкой.",
             "resistance", 1, [{"op": "immune_once", "params": {"to": "ion_cannon", "roles": ["fighter", "interceptor"]}}]))


# ---------------------------------------------------------------------------
# 5. Поле: препятствия и особые клетки
# ---------------------------------------------------------------------------

TERRAIN = [
    {
        "id": "asteroid_field",
        "display_name": "Астероидное поле",
        "passable": True,
        "blocks_line_of_fire": True,
        "effects": {
            "enter_damage_dice": {"count": 1, "sides": 4},
            "enter_damage_chance": "1/2",
            "defense_bonus": 1,
            "blocks_hyperjump_exit": True,
        },
        "text": "Войти можно, но с шансом 1/2 корабль получает 1d4 урона. Стоящий в поле получает +1 к защите; сквозь клетку нельзя стрелять на дистанции 2+.",
    },
    {
        "id": "dense_asteroids",
        "display_name": "Плотный пояс",
        "passable": False,
        "blocks_line_of_fire": True,
        "effects": {"blocks_hyperjump_exit": True},
        "text": "Непроходимая клетка: корабли не входят, дальний огонь не проходит.",
    },
    {
        "id": "nebula",
        "display_name": "Туманность",
        "passable": True,
        "blocks_line_of_fire": True,
        "effects": {"max_incoming_range": 1, "disables_abilities": ["ranged_shot", "torpedoes"]},
        "text": "Корабль в туманности нельзя атаковать дальше чем с дистанции 1; сам он тоже не стреляет далеко.",
    },
    {
        "id": "debris",
        "display_name": "Обломки",
        "passable": True,
        "blocks_line_of_fire": False,
        "effects": {"move_cost_extra": 1, "defense_bonus": 1},
        "text": "Вход в клетку стоит на 1 заряд дороже; стоящий в обломках получает +1 к защите.",
    },
    {
        "id": "gravity_well",
        "display_name": "Гравитационный колодец",
        "passable": True,
        "blocks_line_of_fire": False,
        "effects": {"blocks_hyperjump": True, "pull_toward_center": 1},
        "text": "Из клетки и с соседних клеток нельзя уйти в гиперпространство; в конце раунда корабль сносит на 1 клетку к центру колодца.",
    },
    {
        "id": "station_wreck",
        "display_name": "Остов станции",
        "passable": True,
        "blocks_line_of_fire": True,
        "effects": {"defense_bonus": 2, "salvage_charges": 1},
        "text": "Укрытие: +2 к защите. Первый корабль, вошедший в клетку, снимает с остова 1 заряд.",
    },
]


# ---------------------------------------------------------------------------
# 6. Колода событий (тянется в начале раунда)
# ---------------------------------------------------------------------------
# weight — сколько копий карты в колоде (всего 24).

EVENTS = [
    ("ion_storm", "Ионный шторм", "round_start", 2,
     "Все корабли теряют по 1 заряду. Корабли со способностью droid_brain теряют 2.",
     {"op": "all_ships_charges", "params": {"value": -1, "droid_extra": -1}}),
    ("solar_flare", "Солнечная вспышка", "round_start", 2,
     "В этом раунде дальний огонь (дистанция 2+) получает −2 к силе.",
     {"op": "global_modifier", "params": {"ranged_strength": -2, "duration_rounds": 1}}),
    ("asteroid_drift", "Дрейф астероидов", "round_start", 2,
     "Все клетки астероидов сдвигаются на одну клетку в направлении, указанном кубиком направления.",
     {"op": "move_terrain", "params": {"terrain": ["asteroid_field", "dense_asteroids"], "distance": 1}}),
    ("pirate_raid", "Налёт пиратов", "round_start", 2,
     "На случайной свободной клетке края поля появляется «Пиратский корсар» под управлением поля.",
     {"op": "spawn_npc", "params": {"ship": "pirate_corsair", "where": "board_edge", "count": 1}}),
    ("bounty_posted", "Объявлена награда", "round_start", 2,
     "Выберите вражеский корабль. Тот, кто его уничтожит, получает 3 заряда на любой свой корабль.",
     {"op": "mark_bounty", "params": {"reward_charges": 3}}),
    ("hyperspace_lane", "Открыт гиперкоридор", "round_start", 2,
     "В этом раунде гиперпрыжок стоит на 1 заряд дешевле для всех.",
     {"op": "global_modifier", "params": {"hyperjump_discount": 1, "duration_rounds": 1}}),
    ("comm_blackout", "Глушение связи", "round_start", 2,
     "В этом раунде фракционные синергии и ауры не работают.",
     {"op": "global_modifier", "params": {"disable_synergies": True, "duration_rounds": 1}}),
    ("reinforcements", "Подкрепление", "round_start", 1,
     "Игрок, у которого меньше всего живых кораблей, возвращает 2 HP одному своему кораблю.",
     {"op": "underdog_heal", "params": {"hp": 2}}),
    ("minefield", "Старое минное поле", "round_start", 1,
     "Поставьте 2 мины (1d4 урона) на случайные свободные клетки. Мины действуют до конца матча.",
     {"op": "place_mines", "params": {"count": 2, "damage_dice": {"count": 1, "sides": 4}}}),
    ("imperial_patrol", "Имперский патруль", "round_start", 1,
     "На краю поля появляется «Истребитель СИД» под управлением поля; он атакует ближайший корабль.",
     {"op": "spawn_npc", "params": {"ship": "tie_fighter", "where": "board_edge", "count": 1}}),
    ("salvage_field", "Поле обломков", "round_start", 1,
     "Две случайные пустые клетки становятся обломками (debris).",
     {"op": "add_terrain", "params": {"terrain": "debris", "count": 2}}),
    ("gravity_anomaly", "Гравитационная аномалия", "round_start", 1,
     "Случайная клетка становится гравитационным колодцем до конца матча.",
     {"op": "add_terrain", "params": {"terrain": "gravity_well", "count": 1}}),
    ("supply_drop", "Сброс припасов", "round_start", 1,
     "Каждый игрок получает 2 заряда, распределяемых между своими кораблями.",
     {"op": "all_seats_charges", "params": {"value": 2}}),
    ("force_vision", "Видение в Силе", "round_start", 1,
     "Каждый игрок с героем-джедаем или ситхом один раз в этом раунде перебрасывает кубик.",
     {"op": "grant_reroll", "params": {"hero_tag": ["jedi", "sith"], "uses": 1}}),
    ("desertion", "Дезертирство", "round_start", 1,
     "Игрок с наибольшим числом живых кораблей теряет 1 заряд на каждом из них.",
     {"op": "leader_penalty", "params": {"charges": -1}}),
    ("nebula_drift", "Наползает туманность", "round_start", 1,
     "Три случайные клетки становятся туманностью до конца следующего раунда.",
     {"op": "add_terrain", "params": {"terrain": "nebula", "count": 3, "duration_rounds": 2}}),
    ("all_quiet", "Затишье", "round_start", 1,
     "Ничего не происходит. Каждый корабль получает +1 заряд сверх обычного восстановления.",
     {"op": "all_ships_charges", "params": {"value": 1}}),
]


# ---------------------------------------------------------------------------
# 7. Пираты — нейтральная фракция поля
# ---------------------------------------------------------------------------

PIRATES = {
    "schema_version": SCHEMA_VERSION,
    "faction": "pirates",
    "activation_order": "after_all_seats",
    "seat_id": "NPC",
    "spawn": {
        "initial_count_default": 0,
        "max_on_board": 3,
        "spawn_cells": "board_edge",
        "spawn_facing": "toward_center",
    },
    "ai": {
        "policy": "nearest_weakest",
        "steps": [
            "Выбрать цель: ближайший корабль любого игрока; при равенстве расстояния — с меньшим текущим HP; при полном равенстве — меньший seat_id (детерминизм).",
            "Если цель на дистанции 1 — атаковать.",
            "Иначе потратить заряды на поворот и движение к цели по кратчайшему пути (детерминированный выбор: сначала поворот к цели, затем движение).",
            "Если зарядов не осталось — завершить активацию.",
        ],
        "never": ["гиперпрыжок", "использование событий", "атака другого пиратского корабля"],
    },
    "loot": {
        "text": "Уничтоживший пиратский корабль игрок получает 2 заряда на любой свой корабль.",
        "charges": 2,
    },
    "victory": {
        "text": "Пираты не выигрывают матч: они не учитываются в условии победы и не считаются кораблями игроков.",
        "counts_for_elimination": False,
    },
}


# ---------------------------------------------------------------------------
# 8. Правила партии: поле, драфт, бой, гиперпространство
# ---------------------------------------------------------------------------

BOARD = {
    "schema_version": SCHEMA_VERSION,
    "radius": 4,
    "cell_count": 61,
    "orientation": "pointy_top",
    "coordinate_system": "axial_qr",
    "note": "61 клетка — как в исходных правилах Григиных («поле — 61 шестиугольник»). v3 играл на радиусе 3 (37 клеток) ради демо.",
}

GAME = {
    "schema_version": SCHEMA_VERSION,
    "ruleset_id": "v4_0",
    "title": "Эпохи и фракции",
    "based_on": "v3_5",

    # --- заряды и активация (без изменений относительно v3.5) ---------------
    "initial_charges": 3,
    "max_charges": 5,
    "move_cost": 1,
    "rotate_cost": 1,
    "attack_cost": 0,
    "attacks_per_activation": 1,
    "charge_round_reset": "half_up",
    "charge_full_if_unused": True,
    "round_limit": 60,
    "activation_timeout_seconds": 60,
    "omnidirectional_movement": True,
    "ability_friendly_fire_default": True,

    # --- бой ----------------------------------------------------------------
    "combat": {
        "attacker_dice": 2,
        "defender_dice": 1,
        "defender_flat_bonus": 1,
        "melee_range": 1,
        "ranged_enabled": True,
        "ranged_requires_line_of_fire": True,
        "ranged_default_penalty_per_hex": 2,
        "ranged_arc_rule": "Дальняя атака возможна только если цель в секторе, указанном в weapon.long_range_arc.",
        "boarding": {
            "enabled": True,
            "requires": ["роль support/transport/freighter/corvette/capital", "или способность boarding_pods"],
            "range": 1,
            "cost_charges": 2,
            "roll": "1d6 + 1 за каждый пункт щита атакующего против 1d6 + текущие заряды защитника",
            "on_success": "Защитник теряет все заряды и 1 HP; на следующей активации он пропускает ход.",
            "on_failure": "Атакующий теряет 1 HP.",
            "immune": ["droid_brain", "station"],
        },
        "ram": {
            "enabled": True,
            "cost_charges": "все оставшиеся, минимум 2",
            "range": 1,
            "damage": "Обе стороны получают 1d6; атакующий дополнительно теряет 1 щит.",
            "note": "Гипертаран (манёвр Холдо) — отдельная способность героя, а не обычный таран.",
        },
    },

    # --- гиперпространство --------------------------------------------------
    "hyperspace": {
        "enabled": True,
        "charge_cost_by_class": {"0": 1, "1": 1, "2": 2, "3": 3, "4": 4},
        "charge_up_activation": "Прыжок объявляется в активации и стоит указанное число зарядов; корабль уходит с поля в конце активации.",
        "return": "В начале следующей активации владельца корабль возвращается на любую свободную клетку, не соседнюю с вражеским кораблём, курс — любой.",
        "blocked_by": ["gravity_well", "interdictor", "block_hyperjump"],
        "no_hyperdrive": "Корабли без гипердрайва (hyperdrive=null) прыгать не могут вообще.",
        "while_in_hyperspace": "Корабль нельзя атаковать, он не считается уничтоженным и не занимает клетку.",
    },

    # --- драфт --------------------------------------------------------------
    "draft": {
        "budget_total": BUDGET_TOTAL,
        "budget_total_text": ("Общий бюджет на героя и корабли; герой стоит очки (карточка героя, draft_cost, "
                              "обычно 2), остальное — на корабли. При цене героя 2 кораблям остаётся 24."),
        "hero_cost_default": HERO_COST_DEFAULT,
        "budget": 24,
        "fleet_size": 3,
        "max_capital_per_seat": 1,
        "max_unique_per_seat": 1,
        "max_foreign_faction_ships": 1,
        "mode": "shared_catalog",
        "mode_text": "Общий каталог: каждый корабль и каждый герой — в одном экземпляре. Игроки берут "
                     "по очереди, каждым ходом — любую из своих четырёх фигурок (героя или корабль).",
        "pick_order": ["A", "B", "B", "A", "A", "B", "B", "A"],
        "pick_order_status": "предложение: «змейка» компенсирует право первого выбора",
        "duplicates_allowed": False,
        "fallback_rule": "Если законно достроить состав уже нельзя (соперник забрал нужное), игрок берёт "
                         "любую оставшуюся карточку в пределах бюджета; эпоха и фракция для неё не действуют.",
        "fallback_status": "предложение, ждёт решения владельцев",
        "era_lock": True,
        "era_lock_text": "Все корабли флота должны принадлежать эпохе героя или эпохе «any».",
        "match_era": True,
        "match_era_text": "Перед драфтом выбирается эпоха партии. Обе стороны берут героев и корабли только этой "
                          "эпохи или «вне эпохи» (any): Империя не встречается с Первым Орденом.",
        "match_era_status": "решение владельца от 2026-09-18",
        "hero_defines_faction": True,
        "stations_draftable": False,
        "legacy_group_rules": "Группы 1/2 из правил v2.0 заменены ролями и бюджетом; поле group сохранено в данных v3 для совместимости.",
    },

    # --- фракции, события, поле --------------------------------------------
    "factions_enabled": True,
    "faction_traits_enabled": True,
    "hero_synergy_enabled": True,
    "events": {
        "enabled": True,
        "draw_per_round": 1,
        "deck_size": sum(e[3] for e in EVENTS),
        "first_event_round": 2,
        "reshuffle_when_empty": True,
    },
    "terrain": {
        "enabled": True,
        "default_setup": [
            {"terrain": "asteroid_field", "count": 4},
            {"terrain": "dense_asteroids", "count": 2},
            {"terrain": "nebula", "count": 2},
            {"terrain": "debris", "count": 2},
        ],
        "placement": "Случайно по сиду матча, но не ближе 2 клеток к стартовым клеткам сидов.",
    },
    "pirates": {"enabled": True, "default_count": 0},
}

# Числа «Эскадры против флагмана» подобраны симуляцией (tools/sim_v4/flagship.py).
FLAGSHIP_HUNT = {"budget": 34, "ships": 4, "rounds": 12, "acts": 2, "cost_add": 0,
                 "note": ("подобрано на сильных ботах (подстраивающийся бот за обе стороны, проверка Монте-Карло за "
                          "«Палача»): эскадра выигрывает 53% и 57% соответственно (reports/flagship_hunt.md)")}

SCENARIOS = [
    {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "era_duel",
        "display_name": "Дуэль эпохи",
        "note": "Базовый формат v4: двое игроков, по 3 корабля, поле радиуса 4, события и препятствия включены.",
        "seat_order": ["A1", "B1"],
        "teams": {"A": ["A1"], "B": ["B1"]},
        "seats": {
            "A1": {"cells": [[0, 4], [1, 3], [-1, 4]], "facing": 0},
            "B1": {"cells": [[0, -4], [-1, -3], [1, -4]], "facing": 3},
        },
        "era": "any",
        "draft_budget": 24,
        "events_enabled": True,
        "terrain_enabled": True,
        "pirates": 0,
    },
    {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "classic_2v2_v4",
        "display_name": "Классика 2×2",
        "note": "Формат исходных правил Григиных: четверо игроков по 3 корабля на поле из 61 клетки.",
        "seat_order": ["A1", "B1", "A2", "B2"],
        "teams": {"A": ["A1", "A2"], "B": ["B1", "B2"]},
        "seats": {
            "A1": {"cells": [[0, 4], [1, 3], [-1, 4]], "facing": 0},
            "A2": {"cells": [[4, 0], [3, 1], [4, -1]], "facing": 5},
            "B1": {"cells": [[0, -4], [-1, -3], [1, -4]], "facing": 3},
            "B2": {"cells": [[-4, 0], [-3, -1], [-4, 1]], "facing": 2},
        },
        "era": "any",
        "draft_budget": 24,
        "events_enabled": True,
        "terrain_enabled": True,
        "pirates": 0,
    },
    {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "clone_wars_ambush",
        "display_name": "Засада Войн клонов",
        "note": "Республика против Конфедерации в астероидном поясе. Эпоха закрыта, препятствий вдвое больше.",
        "seat_order": ["A1", "B1"],
        "teams": {"A": ["A1"], "B": ["B1"]},
        "seats": {
            "A1": {"cells": [[0, 4], [1, 3], [-1, 4]], "facing": 0},
            "B1": {"cells": [[0, -4], [-1, -3], [1, -4]], "facing": 3},
        },
        "era": "fall_of_republic",
        "faction_lock": {"A1": "republic", "B1": "separatists"},
        "draft_budget": 24,
        "events_enabled": True,
        "terrain_enabled": True,
        "terrain_setup": [
            {"terrain": "asteroid_field", "count": 8},
            {"terrain": "dense_asteroids", "count": 4},
        ],
        "pirates": 0,
    },
    {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "pirate_raid",
        "display_name": "Налёт пиратов",
        "note": "Двое игроков и три пиратских корабля поля. Пираты ходят последними и бьют ближайшего.",
        "seat_order": ["A1", "B1"],
        "teams": {"A": ["A1"], "B": ["B1"]},
        "seats": {
            "A1": {"cells": [[0, 4], [1, 3], [-1, 4]], "facing": 0},
            "B1": {"cells": [[0, -4], [-1, -3], [1, -4]], "facing": 3},
        },
        "era": "any",
        "draft_budget": 24,
        "events_enabled": True,
        "terrain_enabled": True,
        "pirates": 3,
        "pirate_ships": ["pirate_marauder", "pirate_corsair", "pirate_skiff"],
        "pirate_cells": [[4, -4], [-4, 4], [4, 0]],
    },
    {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "flagship_siege",
        "display_name": "Осада флагмана",
        "note": "Асимметрия: игрок A защищает станцию (Звезда Смерти I или «Палач»), игрок B получает увеличенный бюджет.",
        "seat_order": ["A1", "B1"],
        "teams": {"A": ["A1"], "B": ["B1"]},
        "seats": {
            "A1": {"cells": [[0, 0], [0, 1], [1, 0]], "facing": 0},
            "B1": {"cells": [[0, -4], [-1, -3], [1, -4]], "facing": 3},
        },
        "era": "any",
        "draft_budget": 24,
        "seat_overrides": {
            "A1": {"draft_budget": 30, "stations_draftable": True, "max_capital_per_seat": 2},
            "B1": {"draft_budget": 34, "fleet_size": 4},
        },
        "victory": "A выигрывает, если станция цела к концу раунда 20; B — если станция уничтожена.",
        "events_enabled": True,
        "terrain_enabled": True,
        "pirates": 0,
    },
    {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "flagship_hunt",
        "display_name": "Эскадра против флагмана",
        "note": ("Асимметрия, эпоха «Галактическая гражданская война». Игрок A — Империя: суперразрушитель "
                 "«Палач» (в драфт не входит) и герой Империи. Игрок B — эскадра: герой повстанцев или «вне "
                 "эпохи» и корабли повстанцев и «вне эпохи» в пределах бюджета. Эскадра должна уничтожить "
                 "флагман до конца раунда-лимита, иначе побеждает Империя: без лимита эскадра просто не "
                 "подходит к флагману, и партия кончается ничьей."),
        "era": "galactic_civil_war",
        "seat_order": ["A1", "B1"],
        "teams": {"A": ["A1"], "B": ["B1"]},
        "seats": {
            "A1": {"cells": [[0, -2]], "facing": 3},
            "B1": {"cells": [[0, 4], [1, 3], [-1, 4], [2, 2], [-2, 4]], "facing": 0},
        },
        "flagship": "executor",
        "flagship_seat": "A1",
        "flagship_heroes": ["darth_vader", "admiral_piett", "grand_moff_tarkin", "emperor_palpatine"],
        "squadron_factions": ["rebels", "bounty_hunters"],
        "seat_overrides": {"B1": {"draft_budget": FLAGSHIP_HUNT["budget"], "fleet_size": FLAGSHIP_HUNT["ships"],
                                  "max_capital_per_seat": 0, "ship_cost_add": FLAGSHIP_HUNT["cost_add"]}},
        "flagship_activations": FLAGSHIP_HUNT["acts"],
        "round_limit": FLAGSHIP_HUNT["rounds"],
        "victory": (f"B выигрывает, если «Палач» уничтожен до конца раунда {FLAGSHIP_HUNT['rounds']}; "
                    "иначе — A (или если уничтожена вся эскадра)."),
        "balance_note": FLAGSHIP_HUNT["note"],
        "events_enabled": False,
        "terrain_enabled": False,
        "pirates": 0,
    },
]


# ---------------------------------------------------------------------------
# 9. Запись файлов
# ---------------------------------------------------------------------------

def main() -> None:
    for _h in HEROES:                                   # цена героя в драфте (общий бюджет 26)
        _h["draft_cost"] = BALANCE["heroes"].get(_h["id"], HERO_COST_DEFAULT)
    write("game.json", GAME)
    write("board.json", BOARD)
    write("eras.json", {"schema_version": SCHEMA_VERSION, "eras": ERAS,
                        "matchups": ERA_MATCHUPS})
    write("factions.json", {"schema_version": SCHEMA_VERSION, "factions": FACTIONS})
    write("terrain.json", {"schema_version": SCHEMA_VERSION, "terrain": TERRAIN})
    write("pirates.json", PIRATES)
    write("ship_abilities.json", {
        "schema_version": SCHEMA_VERSION,
        "abilities": [{"id": a, "display_name": n, "text": t, "cost_points": p}
                      for a, n, t, p in SHIP_ABILITIES],
    })
    write("events.json", {
        "schema_version": SCHEMA_VERSION,
        "deck_size": sum(e[3] for e in EVENTS),
        "cards": [{"id": i, "display_name": n, "timing": tm, "copies": w,
                   "text": txt, "effect": eff}
                  for i, n, tm, w, txt, eff in EVENTS],
    })
    for s in SHIPS:
        write(f"ships/{s['id']}.json", s)
    for h in HEROES:
        write(f"heroes/{h['id']}.json", h)
    # каталоги ships/ и heroes/ целиком принадлежат генератору: удалённое из
    # таблиц должно исчезнуть и с диска, иначе валидатор увидит «лишний» файл
    for sub, ids in (("ships", {s["id"] for s in SHIPS}), ("heroes", {h["id"] for h in HEROES})):
        for path in (OUT / sub).glob("*.json"):
            if path.stem not in ids:
                path.unlink()
                print(f"удалён устаревший {sub}/{path.name}")
    for sc in SCENARIOS:
        write(f"scenarios/{sc['scenario_id']}.json", sc)

    write("index.json", {
        "schema_version": SCHEMA_VERSION,
        "ruleset_id": GAME["ruleset_id"],
        "generated_by": "tools/gen_v4_dataset.py",
        "ships": sorted(s["id"] for s in SHIPS),
        "heroes": sorted(h["id"] for h in HEROES),
        "factions": [f["id"] for f in FACTIONS],
        "eras": [e["id"] for e in ERAS],
        "terrain": [t["id"] for t in TERRAIN],
        "events": [e[0] for e in EVENTS],
        "scenarios": [sc["scenario_id"] for sc in SCENARIOS],
    })

    # Таблица стоимостей — отчёт, а не данные (reports/ читают люди).
    lines = [
        "# Стоимости кораблей — ruleset v4 «Эпохи и фракции»",
        "",
        "Сгенерировано `tools/gen_v4_dataset.py`. Формула стоимости — "
        "`docs/rules/rules-v4-factions.md` §4.",
        "",
        "| Корабль | Фракция | Эпоха | Роль | HP | Щит | Сектора | Дальн. | Гипер | Сырьё | Цена |",
        "|---|---|---|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for s in sorted(SHIPS, key=lambda x: (x["faction"], x["draft_cost"], x["id"])):
        hyper = "—" if s["hyperdrive"] is None else f"кл.{s['hyperdrive']['class']}"
        lines.append(
            f"| {s['display_name']} | {s['faction']} | {s['era']} | {s['role']} | "
            f"{s['max_hp']} | {s['max_shield']} | {s['arc_modifiers']} | "
            f"{s['weapon']['max_range']} | {hyper} | {s['raw_cost']} | {s['draft_cost']} |"
        )
    lines += ["", f"Всего кораблей: {len(SHIPS)}; героев: {len(HEROES)}; "
                  f"фракций: {len(FACTIONS)}; событий в колоде: "
                  f"{sum(e[3] for e in EVENTS)}.", ""]
    (ROOT / "reports" / "balance_v4_costs.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"OK: {len(SHIPS)} ships, {len(HEROES)} heroes, {len(SCENARIOS)} scenarios "
          f"written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
