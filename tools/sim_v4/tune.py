"""Числа способностей героев — ручки баланса симулятора v4.

P          — действующие значения (их читает rules.py). По умолчанию — как на
             карточках датасета v4 (ступень «карточка как есть»).
LADDERS    — для каждого героя лестница вариантов от слабого к сильному;
             каждая ступень — (текст для отчёта, переопределения P).
             Ступень с пустыми переопределениями — карточка как есть.
set_levels — выставить ступени героям ({hero: индекс}); остальные — карточка.

Лестницы — предложения по правке карточек; сама карточка меняется только
решением владельца (генератор tools/gen_v4_dataset.py).
"""

from __future__ import annotations

DEFAULT = {
    # Акбар: синергия рядом с крупным кораблём, «Это ловушка!» (раз за игру)
    "ackbar.syn": 1, "ackbar.trap": 1,
    # Пиетт: поворот крупного за 1 заряд, «Сомкнуть сеть» (сдвиг двух кораблей), защита крупных
    "piett.pivot": 1, "piett.shift": 1, "piett.syn_def": 0,
    # Энакин: избранный пилот +атака/−защита, «Путь силы» (сдвиг корабля рядом)
    "anakin.chosen_atk": 1, "anakin.chosen_def": -1, "anakin.push": 1,
    # Боба: +1 HP за уничтожение, бомбы
    "boba.heal": 1, "boba.bombs": 1, "boba.die": 4,
    # Чубакка: ремонт в фазе восстановления
    "chewie.repairs": 2, "chewie.amount": 1,
    # Дуку: +заряд в начале, молнии
    "dooku.charges": 1, "dooku.dmg": 1, "dooku.drain": 2, "dooku.uses": 1,
    # Мол: +урон вплотную, месть
    "maul.melee": 1, "maul.revenge": 1,
    # Вейдер: +атака в секторе F, «Путь силы» (атака через клетку)
    "vader.syn": 1, "vader.force": 1, "vader.cap_only": 0,
    # Палпатин: «Неограниченная власть» (+заряды и лишняя атака)
    "palpatine.power": 1, "palpatine.charges": 3,
    # Финн: +атака по Первому Ордену и Империи, +защита от них
    "finn.atk": 1, "finn.def": 0,
    # Гривус: +атака по Республике, «Четыре клинка» (вторая атака с модификатором)
    "grievous.syn": 1, "grievous.mod": -1, "grievous.uses": 1,
    # Хакс: +щит при чистом Первом Ордене, массированный залп
    "hux.shield": 1, "hux.atk": 1, "hux.pen": 1,
    # Таркин: +заряд в конце раунда, двойная атака корабля с дальностью ≥ range
    "tarkin.charge": 1, "tarkin.double": 1, "tarkin.range": 3,
    # Хан: гиперпрыжок (за все заряды; free — без траты зарядов)
    "han.jump": 1, "han.free": 0,
    # Джанго: мины 1d(die) (+syn от синергии)
    "jango.mines": 1, "jango.die": 4, "jango.syn": 1,
    # Кайло: остановка Силой, ярость (+rage при потере ≥ thr HP за раунд)
    "kylo.stops": 2, "kylo.rage": 2, "kylo.thr": 3,
    # Лэндо: +бюджет, блеф
    "lando.budget": 2, "lando.bluff": 1,
    # Лея: +атака в хвост при чистых повстанцах, инструктаж
    "leia.syn": 1, "leia.brief": 1,
    # Люк: +атака, пока кораблей ≤ left, точный выстрел
    "luke.syn": 2, "luke.left": 1, "luke.shot": 1,
    # Мейс: ваапад (обмен кубиков), дисциплина
    "mace.uses": 2, "mace.syn": 1,
    # Нут: дроидная верфь (возврат дроида)
    "nute.hp": 2, "nute.uses": 1, "nute.all3": 1,
    # Оби-Ван: «Мимо» (переворот кубика атакующего), высокая позиция
    "obi.uses": 2, "obi.syn": 1, "obi.soft": 0,
    # Падме: +атака за каждый корабль Республики до cap, бонус чистой Республики, неприкосновенность
    "padme.per": 1, "padme.cap": 3, "padme.full": 1, "padme.immunity": 1,
    # Фазма: +к силе атаки (карточка: +1 к каждому из двух кубиков = +2); own — только Первому Ордену
    "phasma.atk": 2, "phasma.own": 0, "phasma.front": 0,
    # По: рывок на 2 клетки за 1 заряд (раз в раунд), «Чёрное звено»
    "poe.dash": 1, "poe.syn": 1,
    # Квай-Гон: живая Сила (лечение), воля Силы
    "quigon.heal": 2, "quigon.uses": 1, "quigon.will": 1,
    # R2-D2: +щит раз в period раундов
    "r2.period": 2, "r2.amount": 1,
    # Рей: перебросы, защита от Первого Ордена
    "rey.rerolls": 2, "rey.syn": 1,
    # Сноук: +заряд раз в period раундов, «Нити кукловода»
    "snoke.period": 2, "snoke.puppet": 1,
    # Холдо: +щит транспортам/крупным, манёвр Холдо (dice × d6)
    "holdo.shield": 1, "holdo.ram": 1, "holdo.dice": 1,
    # Ведж: «Держись цели», «Разбойная эскадрилья»
    "wedge.atk": 1, "wedge.syn": 1,
    # Йода: переброс кубика защиты (syn раз на корабль), предвидение, +защита республиканцам
    "yoda.syn": 1, "yoda.foresight": 1, "yoda.def": 0,
}

CARD = "карточка как есть"

LADDERS = {
    "admiral_ackbar": [
        ("без «Это ловушка!»", {"ackbar.trap": 0}),
        (CARD, {}),
        ("«Это ловушка!» — 2 раза в игру", {"ackbar.trap": 2}),
        ("ловушка 2 раза и синергия +2", {"ackbar.trap": 2, "ackbar.syn": 2}),
    ],
    "admiral_piett": [
        ("без «Сомкнуть сеть»", {"piett.shift": 0}),
        (CARD, {}),
        ("«Сомкнуть сеть» — 2 раза в игру", {"piett.shift": 2}),
        ("сеть 2 раза и крупные корабли Империи +1 к защите", {"piett.shift": 2, "piett.syn_def": 1}),
    ],
    "anakin": [
        ("избранный: −2 к защите", {"anakin.chosen_def": -2}),
        (CARD, {}),
        ("избранный без штрафа к защите", {"anakin.chosen_def": 0}),
        ("избранный без штрафа, «Путь силы» 2 раза", {"anakin.chosen_def": 0, "anakin.push": 2}),
        ("избранный +2 атаки без штрафа, «Путь силы» 2 раза",
         {"anakin.chosen_atk": 2, "anakin.chosen_def": 0, "anakin.push": 2}),
    ],
    "boba_fett": [
        ("без бомбы", {"boba.bombs": 0}),
        (CARD, {}),
        ("бомба 2 раза в игру", {"boba.bombs": 2}),
        ("бомба 2 раза, урон 1d6", {"boba.bombs": 2, "boba.die": 6}),
        ("бомба 3 раза, урон 1d6", {"boba.bombs": 3, "boba.die": 6}),
    ],
    "chewbacca": [
        ("ремонт 1 раз", {"chewie.repairs": 1}),
        (CARD, {}),
        ("ремонт 3 раза", {"chewie.repairs": 3}),
        ("ремонт 4 раза", {"chewie.repairs": 4}),
        ("ремонт 4 раза по 2 HP", {"chewie.repairs": 4, "chewie.amount": 2}),
    ],
    "count_dooku": [
        ("без стартового заряда", {"dooku.charges": 0}),
        (CARD, {}),
        ("молнии: 2 HP", {"dooku.dmg": 2}),
        ("молнии 2 раза по 2 HP", {"dooku.dmg": 2, "dooku.uses": 2}),
    ],
    "darth_maul": [
        ("без мести ситха", {"maul.revenge": 0}),
        (CARD, {}),
        ("месть ситха — 2 урона", {"maul.revenge": 2}),
        ("двойной удар +2, месть 2", {"maul.melee": 2, "maul.revenge": 2}),
    ],
    "darth_vader": [
        ("без «Пути силы», синергия только крупным кораблям", {"vader.force": 0, "vader.cap_only": 1}),
        ("без «Пути силы»", {"vader.force": 0}),
        (CARD, {}),
        ("«Путь силы» 2 раза", {"vader.force": 2}),
        ("«Путь силы» 3 раза", {"vader.force": 3}),
        ("«Путь силы» 3 раза, +2 в секторе F", {"vader.force": 3, "vader.syn": 2}),
    ],
    "emperor_palpatine": [
        ("без «Неограниченной власти»", {"palpatine.power": 0}),
        ("власть даёт 1 заряд", {"palpatine.charges": 1}),
        (CARD, {}),
        ("власть 2 раза", {"palpatine.power": 2}),
    ],
    "finn": [
        ("без «Знания изнутри»", {"finn.atk": 0}),
        (CARD, {}),
        ("+1 и к защите от Первого Ордена и Империи", {"finn.def": 1}),
        ("+2 атаки и +1 защиты против них", {"finn.atk": 2, "finn.def": 1}),
    ],
    "general_grievous": [
        ("вторая атака с −2", {"grievous.mod": -2}),
        (CARD, {}),
        ("вторая атака без штрафа", {"grievous.mod": 0}),
        ("«Четыре клинка» 2 раза без штрафа", {"grievous.mod": 0, "grievous.uses": 2}),
    ],
    "general_hux": [
        ("без щита доктрины", {"hux.shield": 0}),
        (CARD, {}),
        ("залп без штрафа к защите", {"hux.pen": 0}),
        ("залп +2 без штрафа", {"hux.atk": 2, "hux.pen": 0}),
    ],
    "grand_moff_tarkin": [
        ("без заряда дисциплины", {"tarkin.charge": 0}),
        (CARD, {}),
        ("двойная атака 2 раза", {"tarkin.double": 2}),
        ("двойная атака 2 раза, от дальности 2", {"tarkin.double": 2, "tarkin.range": 2}),
    ],
    "han_solo": [
        ("без гиперпрыжка", {"han.jump": 0}),
        (CARD, {}),
        ("гиперпрыжок 2 раза", {"han.jump": 2}),
        ("прыжок 2 раза и без траты зарядов", {"han.jump": 2, "han.free": 1}),
        ("прыжок 3 раза без траты зарядов", {"han.jump": 3, "han.free": 1}),
    ],
    "jango_fett": [
        ("без мины", {"jango.mines": 0}),
        (CARD, {}),
        ("мина 2 раза", {"jango.mines": 2}),
        ("мина 3 раза", {"jango.mines": 3}),
        ("мина 3 раза, 1d6", {"jango.mines": 3, "jango.die": 6}),
    ],
    "kylo_ren": [
        ("остановка 1 раз, ярость +1", {"kylo.stops": 1, "kylo.rage": 1}),
        ("остановка 1 раз", {"kylo.stops": 1}),
        (CARD, {}),
        ("ярость от 2 HP", {"kylo.thr": 2}),
        ("остановка 3 раза, ярость от 2 HP", {"kylo.stops": 3, "kylo.thr": 2}),
    ],
    "lando_calrissian": [
        ("без бонуса бюджета", {"lando.budget": 0}),
        ("бюджет +1", {"lando.budget": 1}),
        (CARD, {}),
        ("блеф 2 раза", {"lando.bluff": 2}),
        ("бюджет +4, блеф 2 раза", {"lando.budget": 4, "lando.bluff": 2}),
    ],
    "leia_organa": [
        ("без удара в хвост", {"leia.syn": 0}),
        (CARD, {}),
        ("инструктаж 2 раза", {"leia.brief": 2}),
        ("инструктаж 2 раза, удар в хвост +2", {"leia.brief": 2, "leia.syn": 2}),
    ],
    "luke": [
        ("без «Сила велика в нём»", {"luke.syn": 0}),
        ("последний корабль +1", {"luke.syn": 1}),
        (CARD, {}),
        ("точный выстрел 2 раза", {"luke.shot": 2}),
        ("выстрел 2 раза, «Сила» уже при двух кораблях", {"luke.shot": 2, "luke.left": 2}),
    ],
    "mace_windu": [
        ("ваапад 1 раз, без дисциплины", {"mace.uses": 1, "mace.syn": 0}),
        ("ваапад 1 раз", {"mace.uses": 1}),
        (CARD, {}),
        ("ваапад 3 раза", {"mace.uses": 3}),
    ],
    "nute_gunray": [
        ("без верфи", {"nute.uses": 0}),
        (CARD, {}),
        ("верфь без условия «все три — сепаратисты»", {"nute.all3": 0}),
        ("верфь без условия, 2 раза по 3 HP", {"nute.all3": 0, "nute.hp": 3, "nute.uses": 2}),
    ],
    "obi_wan": [
        ("без «Мимо»", {"obi.uses": 0}),
        ("«Мимо» 1 раз, кубик уменьшается на 3 (не ниже 1)", {"obi.uses": 1, "obi.soft": 1}),
        ("«Мимо» 1 раз", {"obi.uses": 1}),
        ("«Мимо» 2 раза, кубик уменьшается на 3", {"obi.soft": 1}),
        (CARD, {}),
        ("«Мимо» 3 раза", {"obi.uses": 3}),
    ],
    "padme_amidala": [
        ("+1 атаки республиканцам, без бонуса чистой Республики и без неприкосновенности",
         {"padme.cap": 1, "padme.full": 0, "padme.immunity": 0}),
        ("+1 атаки республиканцам, без бонуса чистой Республики", {"padme.cap": 1, "padme.full": 0}),
        ("+1 за корабль до +2, без бонуса чистой Республики", {"padme.cap": 2, "padme.full": 0}),
        ("+1 за корабль до +2, бонус чистой Республики", {"padme.cap": 2}),
        (CARD, {}),
    ],
    "phasma": [
        ("+1 к силе атаки кораблям Первого Ордена только в секторе F",
         {"phasma.atk": 1, "phasma.own": 1, "phasma.front": 1}),
        ("+1 к силе атаки кораблям Первого Ордена", {"phasma.atk": 1, "phasma.own": 1}),
        ("+1 к силе атаки всем кораблям", {"phasma.atk": 1}),
        ("+2 только кораблям Первого Ордена", {"phasma.own": 1}),
        (CARD, {}),
    ],
    "poe_dameron": [
        ("без рывка", {"poe.dash": 0}),
        (CARD, {}),
        ("рывок 2 раза за раунд", {"poe.dash": 2}),
        ("рывок 2 раза, «Чёрное звено» +2", {"poe.dash": 2, "poe.syn": 2}),
    ],
    "qui_gon_jinn": [
        ("без воли Силы", {"quigon.will": 0}),
        (CARD, {}),
        ("лечение 3 HP", {"quigon.heal": 3}),
        ("лечение 3 HP 2 раза", {"quigon.heal": 3, "quigon.uses": 2}),
    ],
    "r2_d2": [
        ("щит раз в 3 раунда", {"r2.period": 3}),
        (CARD, {}),
        ("щит каждый раунд", {"r2.period": 1}),
        ("2 щита каждый раунд", {"r2.period": 1, "r2.amount": 2}),
    ],
    "rey": [
        ("переброс 1 раз", {"rey.rerolls": 1}),
        (CARD, {}),
        ("переброс 3 раза", {"rey.rerolls": 3}),
        ("переброс 3 раза, защита +2", {"rey.rerolls": 3, "rey.syn": 2}),
    ],
    "snoke": [
        ("без «Нитей кукловода»", {"snoke.puppet": 0}),
        (CARD, {}),
        ("заряд каждый раунд", {"snoke.period": 1}),
        ("заряд каждый раунд, «Нити» 2 раза", {"snoke.period": 1, "snoke.puppet": 2}),
    ],
    "vice_admiral_holdo": [
        ("без стартового щита", {"holdo.shield": 0}),
        (CARD, {}),
        ("стартовый щит +2", {"holdo.shield": 2}),
        ("щит +2, таран 2d6", {"holdo.shield": 2, "holdo.dice": 2}),
    ],
    "wedge_antilles": [
        ("без «Разбойной эскадрильи»", {"wedge.syn": 0}),
        (CARD, {}),
        ("«Держись цели» +2", {"wedge.atk": 2}),
        ("«Держись цели» +2, эскадрилья +2", {"wedge.atk": 2, "wedge.syn": 2}),
    ],
    "yoda": [
        ("без предвидения", {"yoda.foresight": 0}),
        (CARD, {}),
        ("переброс защиты 2 раза на корабль", {"yoda.syn": 2}),
        ("переброс 2 раза, +1 к защите республиканцам", {"yoda.syn": 2, "yoda.def": 1}),
    ],
}

# Цена героя в драфте: общий бюджет — BUDGET_TOTAL очков на героя и корабли; по умолчанию герой
# стоит BASE_HERO_COST, то есть кораблям остаётся 24, как в действующих правилах.
BUDGET_TOTAL = 26
BASE_HERO_COST = 2
MAX_HERO_COST = 8
HERO_COST = {}                                           # герой → цена (переопределение подбора)
DATASET_HERO_COST = {}                                   # герой → цена из карточки (заполняет rules)


def hero_cost(h):
    return HERO_COST.get(h, DATASET_HERO_COST.get(h, BASE_HERO_COST))


def set_hero_costs(costs=None):
    HERO_COST.clear()
    HERO_COST.update(costs or {})


BASE_LEVEL = {h: next(i for i, (_, o) in enumerate(lad) if not o) for h, lad in LADDERS.items()}

P = dict(DEFAULT)
LEVELS = dict(BASE_LEVEL)


def set_levels(levels=None):
    """Выставить ступени лестниц; None — все карточки как есть."""
    P.clear()
    P.update(DEFAULT)
    LEVELS.clear()
    LEVELS.update(BASE_LEVEL)
    for h, lvl in (levels or {}).items():
        LEVELS[h] = lvl
        P.update(LADDERS[h][lvl][1])
