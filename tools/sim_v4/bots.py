"""Стратегии для симулятора v4.

RandomBot   — случайные разрешённые действия (нижняя планка).
GreedyBot   — «самая жадная»: для каждого своего корабля перебирает все
              последовательности до двух манёвров (шаг, поворот, форсаж) и
              выбирает ту, после которой ожидаемый урон атаки максимален;
              угрозу от врага не учитывает (threat=0).
TacticalBot — то же, но вычитает ожидаемый урон, который корабль получит на
              новой позиции от вражеских кораблей (threat=0.45), и не тратит
              заряды без пользы (полная перезарядка, если не тратил).

Способности героев (Match.hero_options) бот решает сам: перед атакой оценивает
каждый вариант — пробно применяет его на снимке партии (со своими кубиками,
не подсматривая будущие броски партии) и сравнивает оценку позиции до и после.
Применяет лучший вариант, если выгода не меньше порога героя STRAT[герой] ×
(доля живых кораблей): чем выше порог, тем дольше способность бережётся для
сильного момента; к концу партии порог падает — неиспользованная способность
ничего не стоит. Пороги героев — их индивидуальные стратегии; подбираются
самоигрой (sim_v4.strategy).
"""

from __future__ import annotations

import random

from .rules import DIRS, P, Match, dir_to, dist, expected, in_board, sector

KILL_BONUS = 3.0
RANDOM_KINDS = {"vader", "snoke", "holdo", "boba", "carrier", "ion", "board"}   # случайный исход — усреднять
JUMP_TEMPO = 1.5
CHARGE_W = 0.35                          # ценность одного заряда врага
STUN_W = 2.0                             # ценность оглушения врага абордажем                         # цена гиперпрыжка: корабль пропускает темп (иначе боты «прыгают» вечно)
SAMPLES = 4
MAX_OPTS = 14
STRAT = {}                                                  # герой → порог применения способности
DEFAULT_THETA = 0.6


WELL_W = 1.0                                          # вес риска гиперколодца в оценке хода


def worth(s):
    """Ценность живого корабля: запас прочности + премия за то, что он ещё в игре."""
    return (s.hp + s.shield + KILL_BONUS) * (1 + s.d["draft_cost"] / 10) if s.alive else 0.0


class RandomBot:
    name = "random"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def play_turn(self, m: Match):
        acts = m.legal()
        m.apply(self.rng.choice(acts))
        while m.active is not None and not m.done:
            acts = m.legal()
            hero = m.special_options(m.active)
            if hero and self.rng.random() < 0.1:
                m.apply(self.rng.choice(hero)); continue
            att = [a for a in acts if a[0] == "attack"]
            if att and self.rng.random() < 0.7:
                m.apply(self.rng.choice(att)); continue
            if self.rng.random() < 0.3:
                m.apply(("end",)); continue
            m.apply(self.rng.choice(acts))


class GreedyBot:
    name = "greedy"
    threat_w = 0.0
    idle_w = 0.0

    def __init__(self, seed=0, strat=None):
        self.rng = random.Random(seed)
        self.strat = strat                            # свои пороги способностей (иначе — STRAT)

    # ---- оценки
    def best_attack(self, m, s):
        best, tgt = 0.0, None
        for o in m.ships:
            if o.alive and o.seat != s.seat:
                v = self.attack_value(m, s, o)
                if v is not None and v > best:
                    best, tgt = v, o
        return best, tgt

    def threat(self, m: Match, s):
        t = 0.0
        for e in m.ships:
            if not e.alive or e.seat == s.seat:
                continue
            d = dist(e.pos, s.pos)
            reach = e.d["weapon"]["max_range"] + (1 if e.d["engine"]["move_cost"] is not None else 0)
            if d > reach:
                continue
            my_sec = sector(s.facing, dir_to(s.pos, e.pos))
            off = max(e.d["arc_modifiers"]) - (s.d["arc_modifiers"][my_sec] + 1)
            off -= e.d["weapon"]["range_penalty_per_hex"] * max(0, d - 2)
            t += expected(off, s.shield, s.hp, 4 if s.has("heavy_armor") else 0)[0]
        return t

    def well_penalty(self, m, s):
        """Гиперколодец: сколько потеряет корабль, закончив ход здесь (провал — весь корабль и сверху)."""
        loss, dies = m.well_risk(s)
        return loss + (worth(s) if dies else 0.0)

    def score_here(self, m, s, spent):
        atk, _ = self.best_attack(m, s) if not s.attack_used else (0.0, None)
        score = atk - self.threat_w * self.threat(m, s) - WELL_W * self.well_penalty(m, s)
        if atk == 0:                                   # стрелять не по кому — сближаться
            nearest = min((dist(s.pos, o.pos) for o in m.ships if o.alive and o.seat != s.seat), default=0)
            score -= 0.05 * nearest
        if spent and self.idle_w:
            score -= self.idle_w
        return score

    # ---- перебор манёвров
    def plans(self, m: Match, s):
        """Все последовательности до 2 манёвров: [(действия, итог q,r,facing, потрачено)]."""
        occupied = {o.pos for o in m.ships if o.alive and o is not s}
        if getattr(m, "well", None):
            occupied.add(m.well)                          # в колодец своим ходом не входят
        mc, pc = s.d["engine"]["move_cost"], m.pivot_cost(s)
        u = m.hero_uses[s.seat]
        poe = m.hero(s.seat) == "poe_dameron" and mc is not None and P["poe.dash"] > 0 and \
            (u.get("dash_round") != m.round or u.get("dash", 0) < P["poe.dash"])
        start = ((), s.q, s.r, s.facing, 0)
        out, frontier = [start], [start]
        for _ in range(2):
            nxt = []
            for acts, q, r, f, spent in frontier:
                left = s.charges - spent
                if mc is not None and left >= mc:
                    for i, (dq, dr) in enumerate(DIRS):
                        p = (q + dq, r + dr)
                        c = m.step_cost(s, (q, r), p)       # прочь от колодца — дороже
                        if in_board(*p) and p not in occupied and left >= c:
                            nxt.append((acts + (("move", i),), p[0], p[1], f, spent + c))
                if left >= pc:
                    for k in (1, -1):
                        nxt.append((acts + (("rot", k),), q, r, (f + k) % 6, spent + pc))
                if poe and left >= 1 and not any(a[0] == "hero" for a in acts):
                    dq, dr = DIRS[f]
                    p1, p2 = (q + dq, r + dr), (q + 2 * dq, r + 2 * dr)
                    if in_board(*p2) and p1 not in occupied and p2 not in occupied:
                        nxt.append((acts + (("hero", "poe"),), p2[0], p2[1], f, spent + 1))
                if s.d["engine"]["boost"] and left >= 2:
                    dq, dr = DIRS[f]
                    p1, p2 = (q + dq, r + dr), (q + 2 * dq, r + 2 * dr)
                    bc = 2 + (m.step_cost(s, (q, r), p1) > (mc or 0)) + (m.step_cost(s, p1, p2) > (mc or 0))
                    if in_board(*p2) and p1 not in occupied and p2 not in occupied and left >= bc:
                        nxt.append((acts + (("boost",),), p2[0], p2[1], f, spent + bc))
            out += nxt
            frontier = nxt
        return out

    def choose(self, m: Match, only=None):
        """Лучший (корабль, манёвры) для текущего сида (или только для корабля only)."""
        best = (-1e9, None, ())
        for s in m.ships:
            if not (s.alive and s.seat == m.turn_seat and not s.activated) and s is not only:
                continue
            if only is not None and s is not only:
                continue
            q0, r0, f0 = s.q, s.r, s.facing
            for acts, q, r, f, spent in self.plans(m, s):
                s.q, s.r, s.facing = q, r, f
                sc = self.score_here(m, s, spent) + self.rng.random() * 1e-3
                if sc > best[0]:
                    best = (sc, s, acts)
            s.q, s.r, s.facing = q0, r0, f0
        return best[1], best[2]

    # ---- способности героя
    def evaluate(self, m: Match, seat, active=None):
        """Оценка позиции для стороны seat: материал + позиция кораблей + мины и бомбы."""
        tw = max(self.threat_w, 0.3)
        v = 0.0
        for o in m.ships:
            if not o.alive:
                continue
            if o.seat == seat:
                v += worth(o) - WELL_W * self.well_penalty(m, o)
                atk = self.best_attack(m, o)[0] if not (o is active and o.attack_used) else 0.0
                v += (1.0 if o is active else 0.3) * atk - tw * self.threat(m, o)
            else:
                v -= worth(o) - WELL_W * self.well_penalty(m, o)
                v -= CHARGE_W * o.charges                 # заряды врага — его манёвр (ионная пушка)
                if o.uses.get("stunned"):
                    v += STUN_W                           # оглушён абордажем — пропустит активацию
        for mn in m.mines:
            dmg = 0.35 * ((mn["die"] + 1) / 2 + mn["bonus"])
            for o in m.ships:
                if o.alive and dist(o.pos, mn["pos"]) <= 2:
                    v += dmg if o.seat != seat else -dmg
        for b in m.bombs:
            dq, dr = DIRS[b["dir"]]
            p = b["pos"]
            for _ in range(b["left"] + 1):
                p = (p[0] + dq, p[1] + dr)
                o = next((x for x in m.ships if x.alive and x.pos == p), None)
                if o:
                    dmg = 0.6 * (b["die"] + 1) / 2
                    v += dmg if o.seat != seat else -dmg
                    break
        return v

    def option_value(self, m: Match, s, opt, base):
        name = opt[1]
        if name in ("palpatine", "grievous", "tarkin"):          # лишняя атака после основной
            mod = P["grievous.mod"] if name == "grievous" else 0
            vals = sorted((self.attack_value(m, s, o, mod) or 0.0) for o in m.ships
                          if o.alive and o.seat != s.seat)
            return 0.8 * vals[-1] if vals else 0.0          # основная атака может уже снять лучшую цель
        if name == "hux":
            left = sum(1 for o in m.ships if o.alive and o.seat == s.seat and (not o.activated or o is s))
            alive = sum(1 for o in m.ships if o.alive and o.seat == s.seat)
            return 0.5 * P["hux.atk"] * left - 0.15 * P["hux.pen"] * alive
        if name == "kylo":
            t = m.ships[opt[2]]
            now = any(m.can_attack(t, o) for o in m.ships if o.alive and o.seat == s.seat)
            return (0.25 if now else 0.8) * t.d["draft_cost"] / 3
        snap = m.snapshot()
        rng, m.rng = m.rng, self.rng
        m.probing = True
        n = SAMPLES if name in RANDOM_KINDS else 1
        tot = 0.0
        try:
            for _ in range(n):
                m.apply(opt)
                tot += self.evaluate(m, s.seat, s) if not m.done else (1e3 if m.winner == s.seat else -1e3)
                m.restore(snap)
        finally:
            m.rng = rng
            m.probing = False
        return tot / n - base - (JUMP_TEMPO if name == "jump" else 0.0)

    def threshold(self, m: Match, s):
        alive = sum(1 for o in m.ships if o.alive and o.seat == s.seat)
        h = m.hero(s.seat)
        theta = self.strat.get(h, STRAT.get(h, DEFAULT_THETA)) if self.strat else STRAT.get(h, DEFAULT_THETA)
        return theta * alive / 3

    def hero_phase(self, m: Match, s):
        for _ in range(3):
            if m.done or m.active is not s or not s.alive:
                return
            opts = [o for o in m.special_options(s) if o[1] != "poe"]
            if not opts:
                return
            if len(opts) > MAX_OPTS:                  # Хан, Джанго, Пиетт: десятки клеток — выборка
                opts = self.rng.sample(opts, MAX_OPTS)
            base = self.evaluate(m, s.seat, s)
            bv, best = max((self.option_value(m, s, o, base) + self.rng.random() * 1e-6, o) for o in opts)
            if bv < self.threshold(m, s):
                return
            m.apply(best)

    def attack_value(self, m: Match, s, target, mod=0):
        ev = m.attack_ev(s, target, extra_mod=mod)
        if ev is None:
            return None
        hull, kill = ev
        return hull + KILL_BONUS * kill * (1 + target.d["draft_cost"] / 10)

    def return_from_hyper(self, m: Match):
        """Возврат своих кораблей из гиперпространства: клетка с лучшей оценкой позиции."""
        while True:
            back = m.return_options(m.turn_seat)
            if not back or m.done:
                return
            seat = m.turn_seat
            best, bv = None, -1e18
            for o in back:
                snap = m.snapshot()
                m.probing = True
                m.apply(o)
                v = self.evaluate(m, seat, m.ships[o[2]]) + self.rng.random() * 1e-6
                m.restore(snap)
                m.probing = False
                if v > bv:
                    best, bv = o, v
            m.apply(best)

    def play_turn(self, m: Match):
        self.return_from_hyper(m)
        if m.done or m.active is not None or not any(a[0] == "activate" for a in m.legal()):
            return
        s, acts = self.choose(m)
        m.apply(("activate", s.uid))
        if m.active is not s:                         # Йода заставил начать с другого корабля
            s = m.active
            _, acts = self.choose(m, only=s)
        for a in acts:
            if m.done or m.active is None:
                return
            if a in m.legal() or (a[0] == "hero" and a in m.hero_options(s)):
                m.apply(a)
        if m.done or m.active is None:
            return
        self.hero_phase(m, s)
        if m.done or m.active is None:
            return
        if not s.alive:
            m.apply(("end",)); return
        _, tgt = self.best_attack(m, s)
        if tgt is not None and ("attack", tgt.uid) in m.legal():
            m.apply(("attack", tgt.uid))
        if not m.done and m.active is not None:
            m.apply(("end",))


class TacticalBot(GreedyBot):
    name = "tactical"
    threat_w = 0.45
    idle_w = 0.15


class HunterBot(TacticalBot):
    """Тактический бот, который помнит о лимите раундов: чем меньше раундов осталось, тем меньше он
    боится ответного огня (вес угрозы падает до нуля). Нужен атакующей стороне сценариев на время."""
    name = "hunter"

    def play_turn(self, m: Match):
        left = max(0, m.round_limit - m.round) / max(1, m.round_limit)
        self.threat_w = TacticalBot.threat_w * left
        super().play_turn(m)


def play_match(heroes, fleets, bots, seed=0, scen=None):
    """Партия до конца. Возвращает (победитель 0/1/None, раундов, match)."""
    m = Match(heroes, fleets, seed=seed, scen=scen)
    guard = 0
    while not m.done and guard < 5000:
        bots[m.turn_seat].play_turn(m)
        guard += 1
    return m.winner, m.round, m
