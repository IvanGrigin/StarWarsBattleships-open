"""Драфт из общего каталога (правило владельца от 2026-09-18).

* Каталог общий: каждый корабль и каждый герой — в одном экземпляре; взятую
  карточку больше никто не берёт. Повторов кораблей нет.
* Игроки берут по очереди (порядок — ORDER); каждым ходом — любую из своих
  четырёх «фигурок»: героя (если его ещё нет) или корабль (если их меньше 3).
* Итоговый состав обязан быть законным по v4: бюджет 24, эпоха героя или
  «any», ≤1 capital, ≤1 именной, ≤1 корабль чужой фракции. Поэтому ход
  разрешён, только если после него состав ещё можно законно достроить из
  оставшихся карточек.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .rules import HEROES, SHIPS, budget_for, legal_fleet

ORDER = [0, 1, 1, 0, 0, 1, 1, 0]          # «змейка»: первый ход компенсируется двойным ответом
CATALOG_SHIPS = sorted(s for s, d in SHIPS.items() if d["draftable"])
CATALOG_HEROES = sorted(HEROES)


def _era_ok(h, sid):
    era = HEROES[h]["era"]
    return era == "any" or SHIPS[sid]["era"] in (era, "any")


# для каждого героя — подходящие по эпохе корабли каталога, по возрастанию цены
HERO_POOL = {h: sorted((s for s in CATALOG_SHIPS if _era_ok(h, s)), key=lambda s: SHIPS[s]["draft_cost"])
             for h in CATALOG_HEROES}


ERAS = ["fall_of_republic", "galactic_civil_war", "new_order"]


def in_era(card_era, era):
    """Карточка годится для партии эпохи era (None — эпоха партии не выбрана)."""
    return era is None or card_era in (era, "any")


@dataclass
class DraftState:
    heroes: list = field(default_factory=lambda: [None, None])
    ships: list = field(default_factory=lambda: [[], []])
    step: int = 0
    era: str | None = None                             # эпоха партии (выбирается до драфта)

    @property
    def seat(self):
        return ORDER[self.step] if self.step < len(ORDER) else None

    @property
    def done(self):
        return self.step >= len(ORDER)

    def taken(self):
        return set(h for h in self.heroes if h) | {s for side in self.ships for s in side}

    def copy(self):
        return DraftState(list(self.heroes), [list(self.ships[0]), list(self.ships[1])], self.step, self.era)


COST = {s: SHIPS[s]["draft_cost"] for s in CATALOG_SHIPS}
CAP = {s: int(SHIPS[s]["role"] == "capital") for s in CATALOG_SHIPS}
UNQ = {s: int(bool(SHIPS[s]["unique"])) for s in CATALOG_SHIPS}
FOREIGN = {h: {s: int(SHIPS[s]["faction"] != HEROES[h]["faction"] and not (
    h == "emperor_palpatine" and SHIPS[s]["faction"] in ("empire", "separatists"))) for s in CATALOG_SHIPS}
    for h in CATALOG_HEROES}


BASE_COST = {s: SHIPS[s]["draft_cost"] for s in SHIPS}
BASE_ARCS = {s: list(SHIPS[s]["arc_modifiers"]) for s in SHIPS}
BASE_RAW = {s: SHIPS[s]["raw_cost"] for s in SHIPS}


def cost_with_arcs(sid, arcs):
    """Цена по формуле v4 (gen_v4_dataset.raw_cost/draft_cost) при других числах секторов."""
    b = BASE_ARCS[sid]
    d = [x - y for x, y in zip(arcs, b)]
    raw = BASE_RAW[sid] + 2 * d[0] + d[1] + d[5] + d[2] + d[4] + d[3]
    return max(2, (raw * 2 + 2) // 5)


def apply_arcs(deltas=None):
    """Поправки секторов кораблей (для подбора баланса): {корабль: [ΔF, ΔFR, ΔBR, ΔB, ΔBL, ΔFL]}.
    Цена пересчитывается по формуле. Меняет SHIPS на месте и пересобирает таблицы драфта."""
    deltas = deltas or {}
    for s in SHIPS:
        d = deltas.get(s, [0] * 6)
        SHIPS[s]["arc_modifiers"] = [a + x for a, x in zip(BASE_ARCS[s], d)]
        SHIPS[s]["draft_cost"] = cost_with_arcs(s, SHIPS[s]["arc_modifiers"]) if s in deltas else BASE_COST[s]
    for s in CATALOG_SHIPS:
        COST[s] = SHIPS[s]["draft_cost"]
    for h in HERO_POOL:
        HERO_POOL[h].sort(key=lambda x: COST[x])


def _completable(hero_opts, ships, pool):
    """Можно ли достроить: для какого-то героя из hero_opts и кораблей из pool.
    Те же проверки, что legal_fleet (бюджет, ≤1 capital, ≤1 именной, ≤1 чужой, эпоха),
    но с отсечением по ходу перебора."""
    need = 3 - len(ships)
    pool_set = set(pool)
    for h in hero_opts:
        if any(not _era_ok(h, s) for s in ships):
            continue
        budget = budget_for(h)
        fo_h = FOREIGN[h]
        cost0 = sum(COST[s] for s in ships)
        cap0 = sum(CAP[s] for s in ships)
        un0 = sum(UNQ[s] for s in ships)
        fo0 = sum(fo_h[s] for s in ships)
        if cost0 > budget or cap0 > 1 or un0 > 1 or fo0 > 1:
            continue
        if need == 0:
            return True
        cands = [s for s in HERO_POOL[h] if s in pool_set]

        def rec(k, start, cost, cap, un, fo):
            if k == 0:
                return True
            for i in range(start, len(cands)):
                c = cands[i]
                if cost + k * COST[c] > budget:          # кандидаты по возрастанию цены
                    break
                ncap, nun, nfo = cap + CAP[c], un + UNQ[c], fo + fo_h[c]
                if ncap > 1 or nun > 1 or nfo > 1:
                    continue
                if rec(k - 1, i + 1, cost + COST[c], ncap, nun, nfo):
                    return True
            return False
        if rec(need, 0, cost0, cap0, un0, fo0):
            return True
    return False


def legal_picks(st: DraftState):
    seat = st.seat
    taken = st.taken()
    free_ships = [s for s in CATALOG_SHIPS if s not in taken and in_era(SHIPS[s]["era"], st.era)]
    free_heroes = [h for h in CATALOG_HEROES if h not in taken and in_era(HEROES[h]["era"], st.era)]
    mine_h, mine_s = st.heroes[seat], st.ships[seat]
    picks = []
    if mine_h is None:
        for h in free_heroes:
            if _completable([h], mine_s, free_ships):
                picks.append(("hero", h))
    if len(mine_s) < 3:
        hero_opts = [mine_h] if mine_h else free_heroes
        for s in free_ships:
            rest = [x for x in free_ships if x != s]
            if _completable(hero_opts, mine_s + [s], rest):
                picks.append(("ship", s))
    if not picks:
        picks = fallback_picks(st)
    return picks


def fallback_picks(st: DraftState):
    """Запасное правило (предложение, ждёт решения владельца): если законно достроить
    состав уже нельзя — соперник забрал нужное, — игрок берёт любую оставшуюся
    карточку в пределах бюджета; ограничения эпохи и фракции для неё не действуют."""
    seat = st.seat
    taken = st.taken()
    if st.heroes[seat] is None:
        return [("hero", h) for h in CATALOG_HEROES if h not in taken and in_era(HEROES[h]["era"], st.era)]
    left = 24 - sum(SHIPS[s]["draft_cost"] for s in st.ships[seat]) - 4 * (2 - len(st.ships[seat]))
    free = [s for s in CATALOG_SHIPS if s not in taken and SHIPS[s]["role"] != "station"
            and in_era(SHIPS[s]["era"], st.era)]
    fit = [("ship", s) for s in free if SHIPS[s]["draft_cost"] <= left]
    return fit or [("ship", min(free, key=lambda s: SHIPS[s]["draft_cost"]))]


def apply_pick(st: DraftState, pick):
    seat = st.seat
    if pick[0] == "hero":
        st.heroes[seat] = pick[1]
    else:
        st.ships[seat].append(pick[1])
    st.step += 1


class RandomDrafter:
    name = "random"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def pick(self, st):
        return self.rng.choice(legal_picks(st))


class GreedyDrafter:
    """Драфт «как у человека»: тратит бюджет на самые дорогие доступные корабли (пока состав остаётся
    законным); героя берёт в случайный момент — сразу или после первых кораблей."""
    name = "greedy"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def pick(self, st):
        picks = legal_picks(st)
        heroes = [p for p in picks if p[0] == "hero"]
        ships = [p for p in picks if p[0] == "ship"]
        if heroes and (not ships or self.rng.random() < 0.45):
            return self.rng.choice(heroes)
        return max(ships, key=lambda p: (SHIPS[p[1]]["draft_cost"], self.rng.random()))


def era_heroes(era):
    """Герои, которые могут собрать законный флот в партии этой эпохи."""
    pool = [s for s in CATALOG_SHIPS if in_era(SHIPS[s]["era"], era)]
    return [h for h in CATALOG_HEROES if in_era(HEROES[h]["era"], era) and _completable([h], [], pool)]


def run_draft(drafters, seed=0, heroes=None, era=None):
    """Драфт до конца. heroes=(h0, h1) — герои заданы заранее, драфтятся только корабли
    (так турнир баланса даёт каждому герою равное число партий)."""
    st = DraftState(era=era)
    if heroes:
        st.heroes = list(heroes)
    while not st.done:
        s = st.seat
        if st.heroes[s] is not None and len(st.ships[s]) == 3:
            st.step += 1
            continue
        picks = legal_picks(st)
        if not picks:                                   # тупик (не должен случаться) — сброс
            return None
        pick = drafters[st.seat].pick(st)
        apply_pick(st, pick)
    return st
