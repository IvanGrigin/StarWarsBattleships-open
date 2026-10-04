"""Правила v4 для симулятора баланса.

МОДЕЛИРУЕТСЯ
  * поле радиуса 4, расстановка сценария era_duel (A1 против B1, по 3 корабля);
  * активации по очереди сидов, заряды: шаг move_cost (любая из 6 сторон),
    поворот pivot_cost, форсаж (2 клетки по курсу за 2 заряда);
  * перезарядка v3.5: не тратил за раунд — max, тратил — ceil(max/2); щит
    не восстанавливается; лимит 60 раундов → ничья;
  * бой: атакующий 2d6 + сектор, защищающийся 1d6 + 1 + сектор; дальний огонь
    со штрафом за клетку, только из сектора long_range_arc, линия огня
    перекрывается крупными кораблями и станциями; урон — в щит, потом в корпус;
  * драфт: бюджет 24, 3 корабля, эпоха героя или «any», ≤1 capital, ≤1 именной,
    ≤1 корабль чужой фракции, неименные — повторно;
  * черты всех 7 играбельных фракций; синергии героев; способности кораблей и
    героев — кроме перечисленных ниже.

НЕ МОДЕЛИРУЕТСЯ (в отчёте баланса перечисляется явно)
  гиперпрыжок, абордаж, таран, местность, события, пираты, мины и бомбы
  Феттов; способности: ion_cannon, tractor_beam, interdictor, cloaking,
  boarding_pods, fast_hyperdrive; герои: Вейдер «Путь силы» (в v4 его
  заменяет дальний огонь), Энакин, Хан, Джанго, Боба (активные), Йода
  «Предвидение», Нут «Блокада», Пиетт «Сомкнуть сеть», Сноук «Нити»,
  Финн «Перебежчик», Чубакка «Сила вуки», Хан «Удача контрабандиста».
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .tune import BUDGET_TOTAL, DATASET_HERO_COST, P, hero_cost

ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "data" / "rulesets" / "v4"

DIRS = [(0, -1), (1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0)]      # N NE SE S SW NW
RADIUS = 4
ROUND_LIMIT = 60
REAR = {2, 3, 4}
HYPER_POS = (99, 99)                     # корабль в гиперпространстве: вне поля, клетку не занимает
HYPER_COST = {0: 1, 1: 1, 2: 2, 3: 3, 4: 4}
BOARD_ROLES = {"support", "transport", "freighter", "corvette", "capital"}


def _load(name):
    return json.loads((V4 / name).read_text(encoding="utf-8"))


SHIPS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (V4 / "ships").glob("*.json")}
HEROES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (V4 / "heroes").glob("*.json")}
GAME = _load("game.json")
DATASET_HERO_COST.update({h: d.get("draft_cost", 2) for h, d in HEROES.items()})   # цены героев из карточек
SCEN = _load("scenarios/era_duel.json")


# «Призрак» превращается в «Фантом» только если в команде герой экипажа «Призрака» из мультсериала
# «Звёздные войны: Повстанцы» (решение владельца 2026-09-24). Пока таких героев в наборе нет.
# Сила гиперколодца (подбирается симуляцией, см. docs/V0.5_DESIGN.md):
# PULL_ON_OPEN — рывок и при открытии (иначе только в конце раунда);
# BITE — у края в конце раунда: "half" — щиты в ноль и половина корпуса, "shields" — только щиты и 1 корпус.
# Решение 2026-09-24: колодец был слишком смертоносен (партии ~3 раунда) — рывок только в конце раунда.
WELL_CFG = {"pull_on_open": False, "bite": "half"}
PHANTOM_PILOTS = {"hera_syndulla", "kanan_jarrus", "ezra_bridger", "sabine_wren", "garazeb_orrelios", "chopper"}


# --------------------------------------------------------------------------- гексы
def in_board(q, r):
    return max(abs(q), abs(r), abs(q + r)) <= RADIUS


BOARD = [(q, r) for q in range(-RADIUS, RADIUS + 1) for r in range(-RADIUS, RADIUS + 1) if in_board(q, r)]


def dist(a, b):
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def _px(q, r):
    return math.sqrt(3) * (q + r / 2), 1.5 * r


_DIR_PX = [_px(*d) for d in DIRS]


@lru_cache(maxsize=None)
def dir_to(a, b):
    """Направление 0..5 от a к b (ближайшее по углу)."""
    x, y = _px(b[0] - a[0], b[1] - a[1])
    return max(range(6), key=lambda i: x * _DIR_PX[i][0] + y * _DIR_PX[i][1])


@lru_cache(maxsize=None)
def line(a, b):
    """Клетки строго между a и b (гекс-линия, округление куба)."""
    n = dist(a, b)
    out = []
    for i in range(1, n):
        t = i / n
        fq = a[0] + (b[0] - a[0]) * t + 1e-6
        fr = a[1] + (b[1] - a[1]) * t + 1e-6
        fs = -fq - fr
        q, r, s = round(fq), round(fr), round(fs)
        dq, dr, ds = abs(q - fq), abs(r - fr), abs(s - fs)
        if dq > dr and dq > ds:
            q = -r - s
        elif dr > ds:
            r = -q - s
        out.append((q, r))
    return tuple(out)


def sector(facing, direction):
    return (direction - facing) % 6


# --------------------------------------------------------------------------- кубики
@lru_cache(maxsize=None)
def diff_dist():
    """Распределение (2d6) − (1d6): значение → вероятность."""
    d = {}
    for a in range(1, 7):
        for b in range(1, 7):
            for c in range(1, 7):
                d[a + b - c] = d.get(a + b - c, 0) + 1 / 216
    return d


@lru_cache(maxsize=None)
def expected(offset, shield, hp, cap):
    """(ожидаемый урон корпусу, вероятность уничтожения) при разнице сил offset."""
    ev = kill = 0.0
    for v, p in diff_dist().items():
        dmg = max(0, v + offset)
        if cap:
            dmg = min(dmg, cap)
        hull = max(0, dmg - shield)
        ev += p * min(hull, hp)
        if hull >= hp:
            kill += p
    return ev, kill


# --------------------------------------------------------------------------- состояние
@dataclass
class Ship:
    uid: int
    type: str
    seat: int
    q: int
    r: int
    facing: int
    hp: int
    shield: int
    max_hp: int
    max_shield: int
    charges: int
    alive: bool = True
    spent: int = 0
    activated: bool = False
    attack_used: bool = False
    moved: int = 0
    lost_this_round: int = 0
    lost_last_round: int = 0
    attacked_this_round: bool = False
    rage: bool = False
    last_target: int = -1
    uses: dict = field(default_factory=dict)

    @property
    def d(self):
        return SHIPS[self.type]

    @property
    def pos(self):
        return (self.q, self.r)

    def has(self, ability):
        return any(a["id"] == ability for a in self.d["abilities"])


class Match:
    def __init__(self, heroes, fleets, seed=0, scen=None, well=False):
        self.rng = random.Random(seed)
        self.heroes = heroes                              # [hero_id, hero_id]
        self.hero_faction = [HEROES[h]["faction"] for h in heroes]
        self.ships: list[Ship] = []
        self.round = 1
        self.turn_seat = 0
        self.first_seat = 0
        self.active: Ship | None = None
        self.winner = None
        self.done = False
        self.hero_uses = [{}, {}]
        self.log_damage = [0, 0]
        self.mines = []                                   # [{pos, die, bonus}] — мины Джанго
        self.bombs = []                                   # [{pos, dir, left, die, owner}] — бомбы Бобы
        self.act_id = 0                                   # номер активации (окно «Сомкнуть сеть»)
        self.blockade = None                              # «Торговая блокада» Нута: (его сторона, раунд)
        self.acts_in_round = 0
        self.events = None                                # список — запись событий для повтора партии
        self.probing = False                              # бот пробует вариант на снимке — не записывать
        self.on_apply = None                              # наблюдатель действий (журнал игры)
        scen = scen or SCEN
        self.round_limit = scen.get("round_limit", ROUND_LIMIT)
        # по истечении лимита — победа стороны флагмана (сценарий «Эскадра против флагмана»), иначе ничья
        self.timeout_winner = ("A1", "B1").index(scen["flagship_seat"]) if scen.get("flagship_seat") else None
        # сколько раз за раунд может активироваться корабль (флагман сценария — несколько раз)
        self.acts_per_round = {scen["flagship"]: scen.get("flagship_activations", 1)} if scen.get("flagship") else {}
        for seat, fleet in enumerate(fleets):
            cfg = scen["seats"][("A1", "B1")[seat]]
            for i, t in enumerate(fleet):
                d = SHIPS[t]
                q, r = cfg["cells"][i]
                s = Ship(len(self.ships), t, seat, q, r, cfg["facing"], d["max_hp"], d["max_shield"],
                         d["max_hp"], d["max_shield"], d["initial_charges"])
                self.ships.append(s)
        self._setup_synergies()
        # Гиперколодец (место боя «у чёрной дыры», решение владельца 2026-09-24): открывается в нечётных
        # раундах в случайной свободной клетке; после ходов всех игроков каждый корабль смещается на клетку
        # к нему (рывок и при открытии — WELL_CFG); попавший в колодец уничтожен; в конце раунда корабли вплотную
        # к колодцу теряют щиты и половину корпуса; затем колодец закрывается, следующий раунд обычный.
        self.well_mode = well
        self.well = None                                  # (q, r) открытого колодца
        self.well_safe = []                               # зелёные клетки без притяжения
        self.well_n = 0                                   # сколько раз открывался (интерфейсу — показать плашку)
        self.well_rng = random.Random(seed ^ 0x5eed)
        if well:
            self._open_well()

    # ------------------------------------------------------------ гиперколодец
    def blocked(self):
        """Клетки, куда нельзя встать своим ходом: корабли и открытый колодец."""
        occ = {o.pos for o in self.ships if o.alive}
        if self.well:
            occ.add(self.well)
        return occ

    def step_cost(self, s, a, b):
        """Шаг из a в b: обычная цена; прочь от открытого колодца — на заряд дороже (по кругу — как обычно)."""
        mc = s.d["engine"]["move_cost"] or 0
        w = getattr(self, "well", None)
        return mc + 1 if w and dist(b, w) > dist(a, w) else mc

    def boost_cost(self, s):
        """Форсаж — 2 заряда, плюс по заряду за каждую клетку, уводящую от колодца."""
        w = getattr(self, "well", None)
        if not w:
            return 2
        dq, dr = DIRS[s.facing]
        p1, p2 = (s.q + dq, s.r + dr), (s.q + 2 * dq, s.r + 2 * dr)
        return 2 + (dist(p1, w) > dist(s.pos, w)) + (dist(p2, w) > dist(p1, w))

    def _open_well(self):
        ships = [o.pos for o in self.ships if o.alive and not o.uses.get("hyper")]
        mines = {tuple(x["pos"]) for x in self.mines}
        free = [c for c in BOARD if c not in mines and all(dist(c, p) >= 2 for p in ships)]
        central = [c for c in free if dist(c, (0, 0)) <= RADIUS - 1] or free
        if not central:
            return
        self.well = self.well_rng.choice(central)
        self.well_n += 1
        # 2–3 зелёные клетки, где притяжение не действует (не рядом с колодцем)
        calm = [c for c in BOARD if dist(c, self.well) >= 2 and c not in mines]
        self.well_safe = self.well_rng.sample(calm, min(len(calm), self.well_rng.choice((2, 3))))
        self._ev(t="well_open", pos=list(self.well), n=self.well_n, safe=[list(c) for c in self.well_safe])
        if WELL_CFG["pull_on_open"]:
            self._pull()

    def well_step(self, pos):
        """Куда рывок колодца сдвинет корабль с клетки pos (без учёта занятости) — прогноз для ботов."""
        w = getattr(self, "well", None)
        if not w or pos in set(getattr(self, "well_safe", [])):
            return pos
        d = dist(pos, w)
        if d == 0:
            return pos
        wx, wz = _px(*w)
        steps = [(pos[0] + dq, pos[1] + dr) for dq, dr in DIRS]
        steps = [c for c in steps if dist(c, w) == d - 1]
        return min(steps, key=lambda c: (_px(*c)[0] - wx) ** 2 + (_px(*c)[1] - wz) ** 2)

    def well_risk(self, s, pos=None):
        """Ожидаемая потеря корабля s, если он закончит ход на клетке pos: рывок в конце раунда и укус края.
        Возвращает (потеря корпуса+щита, погибнет ли)."""
        w = getattr(self, "well", None)
        if not w:
            return 0.0, False
        p = self.well_step(pos or s.pos)
        if p == w:
            return float(s.hp + s.shield), True
        if dist(p, w) == 1:
            if WELL_CFG["bite"] == "half":
                left = math.ceil(s.hp / 2) if s.shield > 0 else s.hp // 2
            else:
                left = s.hp - 1
            return float(s.shield + s.hp - max(0, left)), left <= 0
        return 0.0, False

    def _pull(self):
        """Все корабли — на клетку к колодцу; ближние первыми, в занятую клетку не сдвигаются."""
        w = self.well
        moves, fell = [], []
        safe = set(getattr(self, "well_safe", []))
        for o in sorted((o for o in self.ships if o.alive and not o.uses.get("hyper")), key=lambda o: dist(o.pos, w)):
            d = dist(o.pos, w)
            if d == 0 or o.pos in safe:                   # в зелёной зоне притяжение не действует
                continue
            occ = {x.pos for x in self.ships if x.alive and x is not o and not x.uses.get("hyper")}
            wx, wz = _px(*w)
            steps = [(o.q + dq, o.r + dr) for dq, dr in DIRS]
            steps = [c for c in steps if dist(c, w) == d - 1 and c not in occ]
            if not steps:
                continue
            c = min(steps, key=lambda c: (_px(*c)[0] - wx) ** 2 + (_px(*c)[1] - wz) ** 2)
            o.q, o.r = c
            if c == w:                                    # провалился в колодец — уничтожен сразу
                o.alive = False
                fell.append(o.uid)
                self._ev(t="kill", uid=o.uid, by=None)
            moves.append([o.uid, o.q, o.r])
        self._ev(t="well_pull", moves=moves, fell=fell)
        self._check_end()

    def _well_bite(self):
        """Конец раунда: вплотную к колодцу — щиты в ноль и половина корпуса.
        Был щит — остаток округляется вверх, не было — вниз."""
        bitten = []
        for o in self.ships:
            if o.alive and not o.uses.get("hyper") and dist(o.pos, self.well) == 1:
                had = o.shield > 0
                o.shield = 0
                if WELL_CFG["bite"] == "half":
                    o.hp = math.ceil(o.hp / 2) if had else o.hp // 2
                else:
                    o.hp -= 1
                bitten.append([o.uid, o.hp])
                if o.hp <= 0:
                    o.alive = False
                    self._ev(t="kill", uid=o.uid, by=None)
        self._ev(t="well_bite", ships=bitten)
        self._check_end()

    def __getstate__(self):
        """Копия партии (deepcopy — откат хода, доигрывания Монте-Карло) — без наблюдателя-журнала."""
        st = dict(self.__dict__)
        st["on_apply"] = None
        return st

    def _ev(self, **kw):
        if self.events is not None and not self.probing:
            self.events.append(kw)

    # ------------------------------------------------------------ снимок (для перебора ботом)
    def snapshot(self):
        return ([(dict(s.__dict__), dict(s.uses)) for s in self.ships],
                [dict(u) for u in self.hero_uses], [dict(x) for x in self.mines], [dict(b) for b in self.bombs],
                self.done, self.winner, list(self.log_damage), self.active, self.blockade, getattr(self, "well", None),
                # раунд и очередь: проба бота может дойти до конца раунда — откат обязан вернуть и их
                (self.round, self.turn_seat, self.first_seat, self.acts_in_round,
                 list(getattr(self, "well_safe", [])), getattr(self, "well_n", 0)))

    def restore(self, snap):
        ships, uses, mines, bombs, self.done, self.winner, logd, self.active, self.blockade, self.well, rnd = snap
        self.round, self.turn_seat, self.first_seat, self.acts_in_round, safe, self.well_n = rnd
        self.well_safe = list(safe)
        for s, (d, su) in zip(self.ships, ships):
            s.__dict__.update(d)
            s.uses = dict(su)
        self.hero_uses = [dict(u) for u in uses]
        self.mines = [dict(x) for x in mines]
        self.bombs = [dict(b) for b in bombs]
        self.log_damage = list(logd)

    # ------------------------------------------------------------ синергии / черты
    def syn(self, seat):
        return HEROES[self.heroes[seat]]["synergy"]

    def hero(self, seat):
        return self.heroes[seat]

    def factions_as(self, seat, ship):
        """Считается ли корабль «своей» фракцией героя (Палпатин объединяет Империю и КНС)."""
        hf = self.hero_faction[seat]
        f = ship.d["faction"]
        if f == hf:
            return True
        if self.hero(seat) == "emperor_palpatine" and {f, hf} <= {"empire", "separatists"}:
            return True
        return False

    def own_faction_count(self, seat):
        return sum(1 for s in self.ships if s.seat == seat and self.factions_as(seat, s))

    def trait(self, ship):
        """Фракционная черта корабля: только у кораблей фракции героя."""
        return ship.d["faction"] if self.factions_as(ship.seat, ship) else None

    def _setup_synergies(self):
        for seat in (0, 1):
            h = self.hero(seat)
            mine = [s for s in self.ships if s.seat == seat]
            ownf = [s for s in mine if self.factions_as(seat, s)]
            if h == "padme_amidala" and len(ownf) == 3:
                k = P["padme.full"]
                for s in ownf:
                    s.max_hp += k; s.hp += k; s.max_shield += k; s.shield += k
            if h == "general_hux" and len(ownf) == 3:
                for s in ownf:
                    s.max_shield += P["hux.shield"]; s.shield += P["hux.shield"]
            if h == "vice_admiral_holdo":
                for s in ownf:
                    if s.d["role"] in ("transport", "capital"):
                        s.max_shield += P["holdo.shield"]; s.shield += P["holdo.shield"]
            if h == "count_dooku":
                for s in ownf:
                    s.charges = min(s.d["max_charges"], s.charges + P["dooku.charges"])
            if h == "anakin" and ownf:
                max(ownf, key=lambda s: s.d["draft_cost"]).uses["chosen"] = True

    # ------------------------------------------------------------ сила атаки/защиты
    def attack_mods(self, att: Ship, dfn: Ship, dist_, att_sector, def_sector):
        seat = att.seat
        h = self.hero(seat)
        m = 0
        own = self.factions_as(seat, att)
        tr = self.trait(att)
        if tr == "republic" and any(o.alive and o.seat == seat and o is not att and o.d["faction"] == "republic"
                                    and 1 <= dist(o.pos, dfn.pos) <= 2 for o in self.ships):
            m += 1
        if tr == "empire" and dfn.hp < att.hp:
            m += 1
        if tr == "rebels" and def_sector in REAR:
            m += 1
        if tr == "first_order" and att.moved >= 2:
            m += 1
        # синергии героя
        if own:
            if h == "padme_amidala":
                m += min(P["padme.cap"], P["padme.per"] * self.own_faction_count(seat))
            if h == "darth_vader" and att_sector == 0 and (not P["vader.cap_only"] or att.d["role"] == "capital"):
                m += P["vader.syn"]
            if h == "leia_organa" and self.own_faction_count(seat) == 3 and def_sector in REAR:
                m += P["leia.syn"]
            if h == "luke" and sum(1 for s in self.ships if s.seat == seat and s.alive) <= P["luke.left"]:
                m += P["luke.syn"]
            if h == "general_grievous" and dfn.d["faction"] == "republic":
                m += P["grievous.syn"]
            if h == "kylo_ren" and att.rage:
                m += P["kylo.rage"]
            if h == "general_hux" and self.hero_uses[seat].get("barrage_round") == self.round:
                m += P["hux.atk"]
        if h == "anakin" and att.uses.get("chosen"):
            m += P["anakin.chosen_atk"]
        if h == "admiral_ackbar" and any(o.alive and o.seat == seat and o is not att and
                                         o.d["role"] in ("capital", "corvette") and dist(o.pos, att.pos) == 1
                                         for o in self.ships):
            m += P["ackbar.syn"]
        if h == "finn" and dfn.d["faction"] in ("first_order", "empire"):
            m += P["finn.atk"]
        if h == "wedge_antilles" and att.last_target == dfn.uid:
            m += P["wedge.atk"]
        if h == "phasma" and (own or not P["phasma.own"]) and (att_sector == 0 or not P["phasma.front"]):
            m += P["phasma.atk"]                     # карточка: «+1 к каждому кубику атаки» — их два
        if att.uses.get("extra_now"):
            m += att.uses.get("extra_mod", 0)        # вторая атака «Четырёх клинков»
        # способности корабля
        if att.has("squadron_link") and any(o.alive and o.seat == seat and o is not att and
                                            o.d["faction"] == att.d["faction"] and dist(o.pos, att.pos) == 1
                                            for o in self.ships):
            m += 1
        if dist_ > 1 and not att.uses.get("force_path"):
            m -= att.d["weapon"]["range_penalty_per_hex"] * (dist_ - 1)
        return m

    def defense_mods(self, dfn: Ship, att: Ship, dist_, def_sector):
        seat = dfn.seat
        h = self.hero(seat)
        m = 1                                        # плоский бонус защиты v3.1
        own = self.factions_as(seat, dfn)
        if own:
            if h == "obi_wan" and def_sector == 0:
                m += P["obi.syn"]
            if h == "poe_dameron" and self.own_faction_count(seat) >= 2 and any(
                    o.alive and o.seat == seat and o is not dfn and dist(o.pos, dfn.pos) == 1 for o in self.ships):
                m += P["poe.syn"]
            if h == "rey" and att.d["faction"] == "first_order":
                m += P["rey.syn"]
            if h == "wedge_antilles" and def_sector == 0 and dfn.d["role"] in ("fighter", "interceptor") and \
                    sum(1 for s in self.ships if s.seat == seat and s.d["role"] in ("fighter", "interceptor")) >= 2:
                m += P["wedge.syn"]
            if h == "admiral_piett" and dfn.d["role"] == "capital":
                m += P["piett.syn_def"]
            if h == "yoda":
                m += P["yoda.def"]
        if h == "finn" and att.d["faction"] in ("first_order", "empire"):
            m += P["finn.def"]
        if h == "anakin" and dfn.uses.get("chosen"):
            m += P["anakin.chosen_def"]
        if h == "general_hux" and self.hero_uses[seat].get("barrage_round") == self.round - 1:
            m -= P["hux.pen"]
        if dist_ >= 2 and dfn.has("point_defense"):
            m += 1
        if any(o.alive and o.seat == seat and o is not dfn and o.has("shield_projector") and
               dist(o.pos, dfn.pos) == 1 for o in self.ships):
            m += 1
        return m

    # ------------------------------------------------------------ дальность и сектора
    def geo(self, att: Ship, dfn: Ship):
        """Геометрия выстрела att → dfn без проверки сторон: (дистанция, сектор атаки, сектор защиты)."""
        if not (att.alive and dfn.alive) or att is dfn or att.uses.get("hyper") or dfn.uses.get("hyper"):
            return None
        d = dist(att.pos, dfn.pos)
        if d > 1 and dfn.uses.get("cloak_round") == self.round:
            return None                          # маскировочное поле: издали не атаковать
        w = att.d["weapon"]
        if d > w["max_range"]:
            return None
        direction = dir_to(att.pos, dfn.pos)
        a_sec = sector(att.facing, direction)
        if d > 1:
            mode = w["long_range_arc"]
            if mode == "front" and a_sec != 0 or mode == "front_flank" and a_sec not in (5, 0, 1):
                return None
            blockers = {s.pos for s in self.ships if s.alive and s.d["role"] in ("capital", "station")
                        and s is not att and s is not dfn}
            if any(c in blockers for c in line(att.pos, dfn.pos)):
                return None
        d_sec = sector(dfn.facing, dir_to(dfn.pos, att.pos))
        return d, a_sec, d_sec

    def can_attack(self, att: Ship, dfn: Ship):
        if att.seat == dfn.seat:
            return None
        return self.geo(att, dfn)

    def force_geo(self, att: Ship, dfn: Ship):
        """«Путь силы» Вейдера: атака через одну клетку (дистанция 2, клетка между свободна),
        как вплотную — без штрафа за дальность и без ограничения сектором дальнего огня."""
        if not (att.alive and dfn.alive) or att.seat == dfn.seat or dist(att.pos, dfn.pos) != 2:
            return None
        occ = {s.pos for s in self.ships if s.alive}
        if any(c in occ for c in line(att.pos, dfn.pos)):
            return None
        return 2, sector(att.facing, dir_to(att.pos, dfn.pos)), sector(dfn.facing, dir_to(dfn.pos, att.pos))

    def attack_offset(self, att, dfn, geo=None):
        geo = geo or self.can_attack(att, dfn)
        if not geo:
            return None
        d, a_sec, d_sec = geo
        a = att.d["arc_modifiers"][a_sec] + self.attack_mods(att, dfn, d, a_sec, d_sec)
        b = dfn.d["arc_modifiers"][d_sec] + self.defense_mods(dfn, att, d, d_sec)
        return a - b, d, a_sec, d_sec

    def attack_ev(self, att, dfn, geo=None, extra_mod=0):
        o = self.attack_offset(att, dfn, geo)
        if o is None:
            return None
        off = o[0] + extra_mod + (2 if att.has("torpedoes") and att.uses.get("torpedoes", 0) < 2
                                  and 1 <= o[1] <= 3 else 0)
        cap = 4 if dfn.has("heavy_armor") else 0
        return expected(off, dfn.shield, dfn.hp, cap)

    # ------------------------------------------------------------ ходы
    def pivot_cost(self, s):
        if self.hero(s.seat) == "admiral_piett" and s.d["role"] == "capital" and self.factions_as(s.seat, s):
            return P["piett.pivot"]
        return s.d["engine"]["pivot_cost"]

    def legal(self):
        if self.done:
            return []
        if self.active is None:
            back = self.return_options(self.turn_seat)
            if back:
                return back                      # сначала вернуть корабли из гиперпространства
            return [("activate", s.uid) for s in self.ships
                    if s.alive and s.seat == self.turn_seat and not s.activated]
        s = self.active
        acts = [("end",)]
        if not s.alive or s.uses.get("stunned") or s.uses.get("hyper"):
            return acts
        mc = s.d["engine"]["move_cost"]
        occupied = self.blocked()                        # корабли и открытый гиперколодец
        if mc is not None and s.charges >= mc:
            for i, (dq, dr) in enumerate(DIRS):
                p = (s.q + dq, s.r + dr)
                if in_board(*p) and p not in occupied and s.charges >= self.step_cost(s, s.pos, p):
                    acts.append(("move", i))
        pc = self.pivot_cost(s)
        if s.charges >= pc:
            acts += [("rot", 1), ("rot", -1)]
        if s.d["engine"]["boost"] and s.charges >= 2:
            dq, dr = DIRS[s.facing]
            p1, p2 = (s.q + dq, s.r + dr), (s.q + 2 * dq, s.r + 2 * dr)
            if in_board(*p2) and p1 not in occupied and p2 not in occupied and s.charges >= self.boost_cost(s):
                acts.append(("boost",))
        if not s.attack_used:
            acts += [("attack", o.uid) for o in self.ships if self.can_attack(s, o)]
        return acts

    def spend(self, s, n):
        s.charges -= n
        s.spent += n

    def apply(self, act):
        """Действие. on_apply(match, act, ctx) — наблюдатель (журнал игры): зовётся до (ctx=None) и после
        действия; пробные ходы бота (probing) и копии партии, которые делает Монте-Карло, его не зовут."""
        hook = self.on_apply if (self.on_apply and not self.probing) else None
        ctx = hook(self, act, None) if hook else None
        self._apply(act)
        if hook:
            hook(self, act, ctx)

    def _apply(self, act):
        kind = act[0]
        if kind == "ship" and act[1] == "return":
            self._ship_action(None, act)
            return
        if kind == "activate":
            s = self.ships[act[1]]
            s = self._foresight(s)
            self.active = s
            self.act_id += 1
            self.acts_in_round += 1
            s.moved = 0
            self._hero_on_activate(s)
            return
        s = self.active
        if kind == "move":
            dq, dr = DIRS[act[1]]
            cost = self.step_cost(s, s.pos, (s.q + dq, s.r + dr))
            s.q += dq; s.r += dr
            self.spend(s, cost)
            if act[1] == s.facing:
                s.moved += 1
            self._entered(s)
        elif kind == "boost":
            dq, dr = DIRS[s.facing]
            cost = self.boost_cost(s)
            s.q += dq; s.r += dr
            self._entered(s)
            if s.alive:
                s.q += dq; s.r += dr
                self._entered(s)
            self.spend(s, cost)
            s.moved += 2
        elif kind == "rot":
            pc = self.pivot_cost(s)
            s.facing = (s.facing + act[1]) % 6
            self.spend(s, pc)
        elif kind == "attack":
            self.attack(s, self.ships[act[1]])
            s.attack_used = True
            self._hero_extra_attack(s)
        elif kind == "hero":
            self._hero_action(s, act)
        elif kind == "ship":
            self._ship_action(s, act)
        elif kind == "end":
            self._end_activation(s)

    # ------------------------------------------------------------ мины и бомбы
    def _entered(self, s: Ship):
        """Корабль встал на клетку: мины Джанго (эта и соседние клетки), бомбы Бобы (эта клетка)."""
        if not s.alive:
            return
        for mn in list(self.mines):
            if dist(mn["pos"], s.pos) <= 1:
                self.mines.remove(mn)
                self._ev(t="mine", uid=s.uid, pos=mn["pos"])
                self.damage(s, self.rng.randint(1, mn["die"]) + mn["bonus"])
                if not s.alive:
                    return
        for b in list(self.bombs):
            if b["pos"] == s.pos:
                self.bombs.remove(b)
                self._ev(t="bomb", uid=s.uid, pos=b["pos"])
                self.damage(s, self.rng.randint(1, b["die"]))
                if not s.alive:
                    return

    def _advance_bombs(self, seat):
        for b in [b for b in self.bombs if b["owner"] == seat]:
            dq, dr = DIRS[b["dir"]]
            p = (b["pos"][0] + dq, b["pos"][1] + dr)
            if not in_board(*p) or b["left"] <= 0:
                self.bombs.remove(b); continue
            hit = next((o for o in self.ships if o.alive and o.pos == p), None)
            if hit:
                self.bombs.remove(b)
                self._ev(t="bomb", uid=hit.uid, pos=p)
                self.damage(hit, self.rng.randint(1, b["die"]))
                continue
            b["pos"] = p
            b["left"] -= 1

    # ------------------------------------------------------------ бой
    def roll_attack(self, att, dfn, off_info):
        off, d, a_sec, d_sec = off_info
        a_dice = [self.rng.randint(1, 6), self.rng.randint(1, 6)]
        # переброс единиц: дроидный рой (1 раз на корабль) и «переброс единицы» (шанс 1/2)
        for i in range(2):
            if a_dice[i] == 1:
                if self.trait(att) == "separatists" and self.own_faction_count(att.seat) == 3 \
                        and not att.uses.get("swarm"):
                    att.uses["swarm"] = True; a_dice[i] = self.rng.randint(1, 6)
                elif att.has("reroll_one") and self.rng.random() < 0.5:
                    a_dice[i] = self.rng.randint(1, 6)
        d_die = self.rng.randint(1, 6)
        # реакции героев на кубики (решения — простые пороги: кубик плохой / урон большой)
        h_att, h_def = self.hero(att.seat), self.hero(dfn.seat)
        ua, ud = self.hero_uses[att.seat], self.hero_uses[dfn.seat]
        if h_att == "rey" and ua.get("rey", 0) < P["rey.rerolls"] and min(a_dice) <= 2:
            ua["rey"] = ua.get("rey", 0) + 1
            i = a_dice.index(min(a_dice)); a_dice[i] = self.rng.randint(1, 6)
        if h_att == "luke" and ua.get("luke", 0) < P["luke.shot"]:
            low = min(a_dice)
            gain = 6 - low
            total = sum(a_dice) + off - d_die
            if low != 1 and gain >= 3 and total + gain >= dfn.hp + dfn.shield > total:
                ua["luke"] = ua.get("luke", 0) + 1; a_dice[a_dice.index(low)] = 6
        if h_def == "obi_wan" and ud.get("obi", 0) < P["obi.uses"]:
            hi = max(a_dice)
            dmg = sum(a_dice) + off - d_die
            if dmg >= 3 and hi >= 3:
                ud["obi"] = ud.get("obi", 0) + 1
                a_dice[a_dice.index(hi)] = max(1, hi - 3) if P["obi.soft"] else (2 if hi == 6 else 1)
        if h_def == "mace_windu" and ud.get("mace", 0) < P["mace.uses"] and self.factions_as(dfn.seat, dfn):
            if max(a_dice) > d_die + 2:
                ud["mace"] = ud.get("mace", 0) + 1
                i = a_dice.index(max(a_dice)); a_dice[i], d_die = d_die, a_dice[i]
        if h_def == "yoda" and self.factions_as(dfn.seat, dfn) and dfn.uses.get("yoda", 0) < P["yoda.syn"] \
                and d_die <= 2:
            dfn.uses["yoda"] = dfn.uses.get("yoda", 0) + 1; d_die = self.rng.randint(1, 6)
        self._ev(t="roll", att=att.uid, dfn=dfn.uid, a=list(a_dice), d=d_die, off=off, dist=d,
                 a_sec=a_sec, d_sec=d_sec)
        return sum(a_dice) + off - d_die

    def attack(self, att: Ship, dfn: Ship, geo=None):
        info = self.attack_offset(att, dfn, geo)
        if info is None:
            return
        off, d, a_sec, d_sec = info
        h_def = self.hero(dfn.seat)
        ud = self.hero_uses[dfn.seat]
        # отмена дальней атаки: Акбар, Падме (порог — корабль под угрозой уничтожения)
        if d >= 2 and dfn.hp + dfn.shield <= 4:
            for hero, key, lim in (("admiral_ackbar", "trap", "ackbar.trap"),
                                   ("padme_amidala", "immunity", "padme.immunity")):
                if h_def == hero and ud.get(key, 0) < P[lim]:
                    ud[key] = ud.get(key, 0) + 1
                    self._ev(t="cancel", att=att.uid, dfn=dfn.uid, hero=hero)
                    return
        torp = att.has("torpedoes") and att.uses.get("torpedoes", 0) < 2 and 1 <= d <= 3
        if torp:
            att.uses["torpedoes"] = att.uses.get("torpedoes", 0) + 1
            off += 2
        ua = self.hero_uses[att.seat]
        bluff = self.hero(att.seat) == "lando_calrissian" and ua.get("bluff", 0) < P["lando.bluff"] and off >= 3
        if bluff:
            ua["bluff"] = ua.get("bluff", 0) + 1
        before = [dict(u) for u in self.hero_uses] if self.events is not None and not self.probing else None
        diff = self.roll_attack(att, dfn, (off, d, a_sec, d_sec))
        if before is not None:
            for seat in (0, 1):
                for k, v in self.hero_uses[seat].items():
                    if before[seat].get(k) != v and k in ("rey", "luke", "obi", "mace"):
                        self._ev(t="react", seat=seat, hero=self.hero(seat), key=k)
        dmg = max(0, diff)
        if dmg == 0 and att.has("lucky_shot") and self.rng.random() < 0.5:
            dmg = 1
        if bluff:
            if dmg > 0:
                dmg *= 2
            else:
                self.damage(att, 1, ignore_shield=True)
        if dmg > 0 and d == 1 and att.has("bomb_rack") and d_sec == 3:
            dmg += 1
        if d == 1 and self.hero(att.seat) == "darth_maul" and dmg > 0:
            dmg += P["maul.melee"]
        if dfn.has("heavy_armor"):
            dmg = min(dmg, 4)
        if diff == 0 and d == 1 and h_def == "mace_windu" and self.factions_as(dfn.seat, dfn):
            self.damage(att, P["mace.syn"])
        att.last_target = dfn.uid
        if dmg:
            self.damage(dfn, dmg, ignore_shield=torp, killer=att)

    def damage(self, s: Ship, dmg, ignore_shield=False, killer: Ship | None = None):
        if not s.alive or dmg <= 0:
            return
        if not ignore_shield:
            a = min(s.shield, dmg); s.shield -= a; dmg -= a
        dealt = min(dmg, s.hp)
        self._ev(t="dmg", uid=s.uid, hull=dmg, pierce=ignore_shield)
        s.hp -= dmg
        s.lost_this_round += dealt
        self.log_damage[1 - s.seat] += dealt
        if s.hp <= 0:
            self.destroy(s, killer)

    def destroy(self, s: Ship, killer):
        seat = s.seat
        h = self.hero(seat)
        u = self.hero_uses[seat]
        if h == "qui_gon_jinn" and self.factions_as(seat, s) and u.get("will", 0) < P["quigon.will"]:
            u["will"] = u.get("will", 0) + 1; s.hp = 1
            self._ev(t="save", uid=s.uid, how="will"); return
        if s.has("resurrection") and not s.uses.get("res") and self.rng.random() < 0.5:
            s.uses["res"] = True; s.hp = self.rng.randint(1, 4)
            self._ev(t="save", uid=s.uid, how="resurrection"); return
        if s.has("transform_to_phantom") and h in PHANTOM_PILOTS:
            s.type = "phantom"; s.hp = s.max_hp = SHIPS["phantom"]["max_hp"]
            s.shield = s.max_shield = 0
            self._ev(t="save", uid=s.uid, how="phantom"); return
        if h == "nute_gunray" and s.has("droid_brain") and (self.own_faction_count(seat) == 3 or not P["nute.all3"]) \
                and u.get("foundry", 0) < P["nute.uses"]:
            u["foundry"] = u.get("foundry", 0) + 1; s.hp = P["nute.hp"]
            self._ev(t="save", uid=s.uid, how="foundry"); return
        s.alive = False
        self._ev(t="kill", uid=s.uid, by=None if killer is None else killer.uid)
        if killer is not None and killer.alive:
            if self.trait(killer) == "bounty_hunters":
                killer.charges = min(killer.d["max_charges"], killer.charges + 2)
            if self.hero(killer.seat) == "boba_fett" and self.factions_as(killer.seat, killer):
                killer.hp = min(killer.max_hp, killer.hp + P["boba.heal"])
            if h == "darth_maul" and self.factions_as(seat, s):
                self.damage(killer, P["maul.revenge"], ignore_shield=True)
        self._check_end()

    def _check_end(self):
        alive = [any(s.alive and s.seat == k for s in self.ships) for k in (0, 1)]
        if not all(alive):
            self.done = True
            self.winner = None if not any(alive) else (0 if alive[0] else 1)

    # ------------------------------------------------------------ герои: активные способности
    def _foresight(self, s):
        """Йода «Предвидение»: первый корабль противника в раунде известен заранее; раз за игру
        Йода заставляет начать с другого — с того, у кого сейчас меньше всего выстрелов по его флоту."""
        opp = 1 - s.seat
        u = self.hero_uses[opp]
        if self.hero(opp) != "yoda" or self.acts_in_round or u.get("foresight", 0) >= P["yoda.foresight"]:
            return s
        mine = [o for o in self.ships if o.alive and o.seat == opp]

        def danger(x):
            return max((sum(self.attack_ev(x, o) or (0, 0)) for o in mine), default=0)
        alts = [x for x in self.ships if x.alive and x.seat == s.seat and not x.activated and x is not s]
        if not alts or danger(s) < 1.0:
            return s
        best = min(alts, key=danger)
        if danger(best) >= danger(s) - 0.5:
            return s
        u["foresight"] = u.get("foresight", 0) + 1
        return best

    def hero_options(self, s: Ship):
        """Активные способности героя, доступные активному кораблю s сейчас: [("hero", имя, ...)]."""
        if self.done or s is None or not s.alive:
            return []
        seat, h, u = s.seat, self.hero(s.seat), self.hero_uses[s.seat]
        enemies = [o for o in self.ships if o.alive and o.seat != seat]
        occ = {o.pos for o in self.ships if o.alive}
        out = []
        free_extra = not s.attack_used and not s.uses.get("extra")
        if h == "emperor_palpatine" and u.get("power", 0) < P["palpatine.power"] and free_extra:
            out.append(("hero", "palpatine"))
        elif h == "general_grievous" and u.get("blades", 0) < P["grievous.uses"] and free_extra:
            out.append(("hero", "grievous"))
        elif h == "grand_moff_tarkin" and u.get("fire", 0) < P["tarkin.double"] and free_extra and \
                s.d["weapon"]["max_range"] >= P["tarkin.range"]:
            out.append(("hero", "tarkin"))
        elif h == "count_dooku" and u.get("lightning", 0) < P["dooku.uses"]:
            out += [("hero", "dooku", o.uid) for o in enemies if 1 <= dist(o.pos, s.pos) <= 2]
        elif h == "kylo_ren" and u.get("stop", 0) < P["kylo.stops"]:
            out += [("hero", "kylo", o.uid) for o in enemies if 1 <= dist(o.pos, s.pos) <= 3 and not o.activated]
        elif h == "qui_gon_jinn" and u.get("living", 0) < P["quigon.uses"]:
            out += [("hero", "quigon", o.uid) for o in self.ships
                    if o.alive and o.seat == seat and o.hp < o.max_hp]
        elif h == "vice_admiral_holdo" and u.get("ram", 0) < P["holdo.ram"] and s.d["hyperdrive"] is not None:
            out.append(("hero", "holdo"))
        elif h == "darth_vader" and u.get("force", 0) < P["vader.force"]:
            out += [("hero", "vader", o.uid) for o in enemies if self.force_geo(s, o)]
        elif h == "anakin" and u.get("push", 0) < P["anakin.push"]:
            for o in self.ships:
                if o.alive and o is not s and dist(o.pos, s.pos) == 1:
                    for i, (dq, dr) in enumerate(DIRS):
                        p = (o.q + dq, o.r + dr)
                        if in_board(*p) and p not in occ:
                            out.append(("hero", "anakin", o.uid, i))
        elif h == "han_solo" and u.get("jump", 0) < P["han.jump"] and s.charges >= 1 and not self.jump_blocked(s):
            others = [o.pos for o in self.ships if o.alive and o is not s]
            for p in BOARD:
                if p not in occ and all(dist(p, x) > 1 for x in others):
                    out.append(("hero", "han", p[0], p[1]))
        elif h == "jango_fett" and u.get("mines", 0) < P["jango.mines"]:
            mined = {mn["pos"] for mn in self.mines}
            out += [("hero", "jango", p[0], p[1]) for p in BOARD
                    if 1 <= dist(p, s.pos) <= 2 and p not in occ and p not in mined]
        elif h == "boba_fett" and u.get("bombs", 0) < P["boba.bombs"]:
            out += [("hero", "boba", i) for i, (dq, dr) in enumerate(DIRS) if in_board(s.q + dq, s.r + dr)]
        elif h == "admiral_piett":
            if u.get("piett_act") == self.act_id and u.get("piett_left", 0) > 0:
                movers = [o for o in self.ships if o.alive and o.seat == seat and o.uid != u.get("piett_first")]
            elif u.get("piett", 0) < P["piett.shift"]:
                movers = [o for o in self.ships if o.alive and o.seat == seat]
            else:
                movers = []
            for o in movers:
                for i, (dq, dr) in enumerate(DIRS):
                    p = (o.q + dq, o.r + dr)
                    if in_board(*p) and p not in occ:
                        out.append(("hero", "piett", o.uid, i))
        elif h == "snoke" and u.get("puppet", 0) < P["snoke.puppet"]:
            for c in enemies:
                if c.d["role"] in ("fighter", "interceptor"):
                    out += [("hero", "snoke", c.uid, t.uid) for t in enemies if t is not c and self.geo(c, t)]
        elif h == "poe_dameron" and s.d["engine"]["move_cost"] is not None and s.charges >= 1 and \
                (u.get("dash_round") != self.round or u.get("dash", 0) < P["poe.dash"]) and P["poe.dash"] > 0:
            dq, dr = DIRS[s.facing]
            p1, p2 = (s.q + dq, s.r + dr), (s.q + 2 * dq, s.r + 2 * dr)
            if in_board(*p2) and p1 not in occ and p2 not in occ:
                out.append(("hero", "poe"))
        elif h == "general_hux" and not u.get("barrage"):
            out.append(("hero", "hux"))
        elif h == "nute_gunray" and not u.get("blockade"):
            out.append(("hero", "nute"))
        return out

    def _hero_action(self, s: Ship, act):
        name = act[1]
        seat, u = s.seat, self.hero_uses[s.seat]
        if name == "palpatine":
            u["power"] = u.get("power", 0) + 1
            s.charges = min(s.d["max_charges"], s.charges + P["palpatine.charges"]); s.uses["extra"] = 1
        elif name == "grievous":
            u["blades"] = u.get("blades", 0) + 1; s.uses["extra"] = 1; s.uses["extra_mod"] = P["grievous.mod"]
        elif name == "tarkin":
            u["fire"] = u.get("fire", 0) + 1; s.uses["extra"] = 1
        elif name == "dooku":
            u["lightning"] = u.get("lightning", 0) + 1
            o = self.ships[act[2]]
            o.charges = max(0, o.charges - P["dooku.drain"])
            self.damage(o, P["dooku.dmg"], ignore_shield=True, killer=s)
        elif name == "kylo":
            u["stop"] = u.get("stop", 0) + 1
            self.ships[act[2]].charges = 0
        elif name == "quigon":
            u["living"] = u.get("living", 0) + 1
            o = self.ships[act[2]]; o.hp = min(o.max_hp, o.hp + P["quigon.heal"])
        elif name == "holdo":
            u["ram"] = u.get("ram", 0) + 1
            dq, dr = DIRS[s.facing]
            cells = [(s.q + dq * k, s.r + dr * k) for k in (1, 2, 3)]
            s.alive = False
            for o in [o for o in self.ships if o.alive and o.pos in cells]:
                self.damage(o, sum(self.rng.randint(1, 6) for _ in range(P["holdo.dice"])), killer=None)
            self._check_end()
        elif name == "vader":
            u["force"] = u.get("force", 0) + 1
            o = self.ships[act[2]]
            s.uses["force_path"] = True
            self.attack(s, o, geo=self.force_geo(s, o))
            s.uses["force_path"] = False
        elif name == "anakin":
            u["push"] = u.get("push", 0) + 1
            o = self.ships[act[2]]; dq, dr = DIRS[act[3]]
            o.q += dq; o.r += dr
            self._entered(o)
        elif name == "han":
            u["jump"] = u.get("jump", 0) + 1
            s.q, s.r = act[2], act[3]
            if not P["han.free"]:
                self.spend(s, s.charges)
            self._entered(s)
        elif name == "jango":
            u["mines"] = u.get("mines", 0) + 1
            bonus = P["jango.syn"] if self.factions_as(seat, s) else 0
            self.mines.append({"pos": (act[2], act[3]), "die": P["jango.die"], "bonus": bonus})
        elif name == "boba":
            u["bombs"] = u.get("bombs", 0) + 1
            dq, dr = DIRS[act[2]]
            p = (s.q + dq, s.r + dr)
            hit = next((o for o in self.ships if o.alive and o.pos == p), None)
            if hit:
                self.damage(hit, self.rng.randint(1, P["boba.die"]))
            else:
                self.bombs.append({"pos": p, "dir": act[2], "left": 2, "die": P["boba.die"], "owner": seat})
        elif name == "piett":
            if u.get("piett_act") == self.act_id and u.get("piett_left", 0) > 0:
                u["piett_left"] -= 1
            else:
                u["piett"] = u.get("piett", 0) + 1
                u["piett_act"], u["piett_left"], u["piett_first"] = self.act_id, 1, act[2]
            o = self.ships[act[2]]; dq, dr = DIRS[act[3]]
            o.q += dq; o.r += dr
            self._entered(o)
        elif name == "snoke":
            u["puppet"] = u.get("puppet", 0) + 1
            c, t = self.ships[act[2]], self.ships[act[3]]
            self.attack(c, t, geo=self.geo(c, t))
        elif name == "poe":
            if u.get("dash_round") != self.round:
                u["dash_round"], u["dash"] = self.round, 0
            u["dash"] += 1
            dq, dr = DIRS[s.facing]
            for _ in range(2):
                if s.alive:
                    s.q += dq; s.r += dr
                    self._entered(s)
            self.spend(s, 1)
            s.moved += 2
        elif name == "hux":
            u["barrage"] = True; u["barrage_round"] = self.round
        elif name == "nute":
            u["blockade"] = True
            self.blockade = (seat, self.round)   # до конца раунда противник Нута не прыгает

    # ------------------------------------------------------------ способности кораблей, гиперпрыжок, абордаж
    def special_options(self, s: Ship):
        """Все особые действия активного корабля: способности героя и корабля."""
        if s is None or s.uses.get("stunned") or s.uses.get("hyper"):
            return []
        return self.hero_options(s) + self.ship_options(s)

    def jump_cost(self, s: Ship):
        hd = s.d["hyperdrive"]
        if hd is None:
            return None
        c = HYPER_COST[hd["class"]]
        if s.has("fast_hyperdrive"):
            c = max(1, c - 1)
        if self.hero(s.seat) == "han_solo" and hd["class"] <= 1 and self.factions_as(s.seat, s):
            c = max(0, c - 1)                    # «Удача контрабандиста»
        return c

    def jump_blocked(self, s: Ship):
        if self.blockade and self.blockade[0] != s.seat and self.blockade[1] == self.round:
            return True
        # у края гиперколодца гиперпрыжок невозможен — кроме «Сокола тысячелетия»
        if getattr(self, "well", None) and dist(s.pos, self.well) <= 1 and s.type != "millennium_falcon":
            return True
        return any(o.alive and o.seat != s.seat and o.has("interdictor") and not o.uses.get("hyper")
                   and 1 <= dist(o.pos, s.pos) <= 3 for o in self.ships)

    def can_board(self, s: Ship):
        free = self.hero(s.seat) == "finn" and self.factions_as(s.seat, s) and not self.hero_uses[s.seat].get("finn_board")
        if not (s.d["role"] in BOARD_ROLES or s.has("boarding_pods") or free):
            return False
        return free or s.charges >= 2

    def ship_options(self, s: Ship):
        if self.done or s is None or not s.alive:
            return []
        out = []
        enemies = [o for o in self.ships if o.alive and o.seat != s.seat and not o.uses.get("hyper")]
        occ = {o.pos for o in self.ships if o.alive}
        if s.has("carrier") and not s.uses.get("carrier"):
            out += [("ship", "carrier", o.uid) for o in enemies if 1 <= dist(o.pos, s.pos) <= 2]
        if s.has("ion_cannon") and not s.attack_used:
            out += [("ship", "ion", o.uid) for o in enemies if self.can_attack(s, o)]
        if s.has("tractor_beam") and s.uses.get("tractor_round") != self.round:
            for o in enemies:
                d = dist(o.pos, s.pos)
                if 1 <= d <= 2 and self._tractor_cell(s, o, occ):
                    out.append(("ship", "tractor", o.uid))
        if s.has("cloaking") and not s.uses.get("cloak"):
            out.append(("ship", "cloak"))
        c = self.jump_cost(s)
        if c is not None and s.charges >= c and not self.jump_blocked(s):
            out.append(("ship", "jump"))
        if not s.attack_used and self.can_board(s):
            out += [("ship", "board", o.uid) for o in enemies if dist(o.pos, s.pos) == 1
                    and not o.has("droid_brain") and o.d["role"] != "station"]
        return out

    def _tractor_cell(self, s, o, occ):
        """Клетка на шаг ближе к кораблю s, куда тяговый луч тянет o (или None)."""
        d = dist(o.pos, s.pos)
        for dq, dr in DIRS:
            p = (o.q + dq, o.r + dr)
            if in_board(*p) and p not in occ and dist(p, s.pos) == d - 1 and d > 1:
                return p
        return None

    def return_options(self, seat):
        """Возврат из гиперпространства в начале хода владельца: свободная клетка не рядом с врагом."""
        away = [x for x in self.ships if x.alive and x.seat == seat and x.uses.get("hyper")]
        if not away or self.done:
            return []
        x = away[0]
        occ = {o.pos for o in self.ships if o.alive and not o.uses.get("hyper")}
        if getattr(self, "well", None):
            occ.add(self.well)
        foes = [o.pos for o in self.ships if o.alive and o.seat != seat and not o.uses.get("hyper")]
        return [("ship", "return", x.uid, q, r) for q, r in BOARD
                if (q, r) not in occ and all(dist((q, r), f) > 1 for f in foes)]

    def _ship_action(self, s: Ship, act):
        name = act[1]
        if name == "return":
            x = self.ships[act[2]]
            x.q, x.r = act[3], act[4]
            x.uses.pop("hyper", None)
            foes = [o for o in self.ships if o.alive and o.seat != x.seat and not o.uses.get("hyper")]
            if foes:                             # курс — на ближайшего врага
                x.facing = dir_to(x.pos, min(foes, key=lambda o: dist(o.pos, x.pos)).pos)
            self._ev(t="return", uid=x.uid)
            self._entered(x)
            return
        if name == "carrier":
            s.uses["carrier"] = True
            o = self.ships[act[2]]
            self._ev(t="carrier", uid=o.uid)
            self.damage(o, self.rng.randint(1, 4), killer=s)
        elif name == "ion":
            o = self.ships[act[2]]
            s.attack_used = True
            info = self.attack_offset(s, o)
            if info is None:
                return
            diff = self.roll_attack(s, o, info)
            immune = (self.hero(o.seat) == "phasma" and self.factions_as(o.seat, o)) or \
                (self.hero(o.seat) == "r2_d2" and o.d["role"] in ("fighter", "interceptor")
                 and self.factions_as(o.seat, o) and not o.uses.get("r2_ion"))
            if diff > 0 and immune:
                if self.hero(o.seat) == "r2_d2":
                    o.uses["r2_ion"] = True
                self._ev(t="ion_block", uid=o.uid)
            elif diff > 0:
                o.charges = max(0, o.charges - 2)
                self._ev(t="ion", uid=o.uid)
        elif name == "tractor":
            s.uses["tractor_round"] = self.round
            o = self.ships[act[2]]
            p = self._tractor_cell(s, o, {x.pos for x in self.ships if x.alive})
            if p:
                o.q, o.r = p
                self._ev(t="tractor", uid=o.uid)
                self._entered(o)
        elif name == "cloak":
            s.uses["cloak"] = True
            s.uses["cloak_round"] = self.round
        elif name == "jump":
            self.spend(s, self.jump_cost(s))
            s.uses["hyper"] = True
            s.q, s.r = HYPER_POS
            self._ev(t="jump", uid=s.uid)
            self._end_activation(s)
        elif name == "board":
            o = self.ships[act[2]]
            u = self.hero_uses[s.seat]
            finn = self.hero(s.seat) == "finn" and self.factions_as(s.seat, s) and not u.get("finn_board") \
                and (s.charges < 2 or not (s.d["role"] in BOARD_ROLES or s.has("boarding_pods")))
            if finn:
                u["finn_board"] = True
            else:
                self.spend(s, 2)
            s.attack_used = True
            chew = lambda x: 2 if self.hero(x.seat) == "chewbacca" and x.d["faction"] == "rebels" else 0
            a = self.rng.randint(1, 6) + s.shield + chew(s)
            d = self.rng.randint(1, 6) + o.charges + chew(o)
            if a > d:
                o.charges = 0
                o.uses["stunned"] = True
                self._ev(t="board", uid=o.uid, ok=True)
                self.damage(o, 1, ignore_shield=True, killer=s)
            else:
                self._ev(t="board", uid=o.uid, ok=False)
                self.damage(s, 1, ignore_shield=True)

    def _hero_on_activate(self, s):
        if self.bombs:
            self._advance_bombs(s.seat)

    def _hero_extra_attack(self, s):
        if s.uses.get("extra") and s.alive and not self.done:
            targets = [o for o in self.ships if self.can_attack(s, o)]
            s.uses["extra"] = 0
            if targets:
                t = min(targets, key=lambda o: o.hp + o.shield)
                s.uses["extra_now"] = True
                self.attack(s, t)
                s.uses["extra_now"] = False
                s.uses["extra_mod"] = 0

    def _end_activation(self, s):
        s.uses.pop("stunned", None)
        done = s.uses.get("acts_done", 0) + 1
        s.uses["acts_done"] = done
        s.activated = not (s.alive and done < self.acts_per_round.get(s.type, 1))
        s.rage = False
        s.attacked_this_round = bool(s.attack_used)
        s.attack_used = False
        s.uses["extra"] = 0
        self.active = None
        self._advance()

    def _advance(self):
        other = 1 - self.turn_seat
        if any(x.alive and x.seat == other and not x.activated for x in self.ships):
            self.turn_seat = other
        elif any(x.alive and x.seat == self.turn_seat and not x.activated for x in self.ships):
            pass
        else:
            self._end_round()

    def _end_round(self):
        if getattr(self, "well", None):                   # после ходов всех — ещё рывок к колодцу, укус, закрытие
            self._pull()
            if self.done:
                return
            self._well_bite()
            self._ev(t="well_close", pos=list(self.well))
            self.well = None
            self.well_safe = []
            if self.done:
                return
        for seat in (0, 1):
            h, u = self.hero(seat), self.hero_uses[seat]
            mine = [s for s in self.ships if s.alive and s.seat == seat]
            for s in mine:
                mx = s.d["max_charges"]
                s.charges = mx if s.spent == 0 else max(s.charges, math.ceil(mx / 2))
                if h == "grand_moff_tarkin" and self.factions_as(seat, s):
                    s.charges = min(mx, s.charges + P["tarkin.charge"])
                if h == "snoke" and self.round % P["snoke.period"] == 0 and self.factions_as(seat, s):
                    s.charges = min(mx, s.charges + 1)
                if self.trait(s) == "resistance" and not s.attacked_this_round and s.lost_last_round == 0:
                    s.hp = min(s.max_hp, s.hp + 1)
                if h == "kylo_ren" and self.factions_as(seat, s) and s.lost_this_round >= P["kylo.thr"]:
                    s.rage = True
                if s.has("repair_bay"):
                    hurt = [o for o in mine if o.hp < o.max_hp and dist(o.pos, s.pos) <= 1]
                    if hurt:
                        o = min(hurt, key=lambda x: x.hp); o.hp += 1
                s.lost_last_round, s.lost_this_round = s.lost_this_round, 0
                s.spent = 0; s.activated = False; s.attacked_this_round = False; s.uses["acts_done"] = 0
            if h == "chewbacca" and u.get("repair", 0) < P["chewie.repairs"]:
                hurt = [s for s in mine if s.hp < s.max_hp]
                if hurt:
                    u["repair"] = u.get("repair", 0) + 1; o = min(hurt, key=lambda x: x.hp)
                    o.hp = min(o.max_hp, o.hp + P["chewie.amount"])
            if h == "r2_d2" and self.round % P["r2.period"] == 0:
                low = [s for s in mine if s.shield < s.max_shield]
                if low:
                    low[0].shield = min(low[0].max_shield, low[0].shield + P["r2.amount"])
            if h == "leia_organa" and u.get("brief", 0) < P["leia.brief"] and self.round >= 2:
                u["brief"] = u.get("brief", 0) + 1
                for s in mine:
                    s.charges = min(s.d["max_charges"], s.charges + 1)
        self.round += 1
        self.acts_in_round = 0
        if self.round > self.round_limit:
            self.done = True; self.winner = self.timeout_winner
        self.first_seat = 1 - self.first_seat
        self.turn_seat = self.first_seat
        if not any(x.alive and x.seat == self.turn_seat for x in self.ships):
            self.turn_seat = 1 - self.turn_seat
        if getattr(self, "well_mode", False) and not self.done and self.round % 2 == 1:
            self._open_well()                             # нечётный раунд — колодец открывается снова
            if not any(x.alive and x.seat == self.turn_seat for x in self.ships):
                self.turn_seat = 1 - self.turn_seat


# --------------------------------------------------------------------------- драфт
def draft_pool(hero_id):
    era = HEROES[hero_id]["era"]
    return [s for s in SHIPS.values() if s["draftable"] and (era == "any" or s["era"] in (era, "any"))]


def budget_for(hero_id):
    """Очки на корабли: общий бюджет минус цена героя (+ бонус Лэндо). При базовой цене героя — 24."""
    return BUDGET_TOTAL - hero_cost(hero_id) + (P["lando.budget"] if hero_id == "lando_calrissian" else 0)


def legal_fleet(hero_id, fleet, budget=None):
    h = HEROES[hero_id]
    budget = budget or budget_for(hero_id)
    ds = [SHIPS[t] for t in fleet]
    if len(ds) != 3 or sum(d["draft_cost"] for d in ds) > budget:
        return False
    era = h["era"]
    if any(not d["draftable"] or (era != "any" and d["era"] not in (era, "any")) for d in ds):
        return False
    if sum(1 for d in ds if d["role"] == "capital") > 1:
        return False
    uniq = [d["id"] for d in ds if d["unique"]]
    if len(uniq) > 1:
        return False
    foreign = sum(1 for d in ds if d["faction"] != h["faction"] and not (
        hero_id == "emperor_palpatine" and d["faction"] in ("empire", "separatists")))
    return foreign <= 1


def random_fleet(hero_id, rng, tries=400):
    pool = [s["id"] for s in draft_pool(hero_id)]
    own = [t for t in pool if SHIPS[t]["faction"] == HEROES[hero_id]["faction"]]
    for _ in range(tries):
        k = rng.choice([3, 3, 2])                         # чаще — чистая фракция
        fleet = [rng.choice(own or pool) for _ in range(k)] + [rng.choice(pool) for _ in range(3 - k)]
        if legal_fleet(hero_id, fleet):
            return sorted(fleet)
    return None
