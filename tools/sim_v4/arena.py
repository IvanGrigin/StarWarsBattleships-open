"""Турнир ботов разного уровня: кто выигрывает и насколько сценарий честен при сильной игре.

Боты:
  random     — случайные разрешённые действия;
  greedy     — самый жадный: лучший выстрел после до двух манёвров, ответный огонь не учитывает;
  tactical   — жадный + осторожность (угроза на новой клетке) + бережёт заряды;
  hunter     — тактический, который смелеет к концу лимита раундов (для атакующей стороны);
  neural     — тактический + нейросеть оценки позиции (value_net.npz);
  adaptive   — «сам подстраивается»: веса его оценки (осторожность, премия за уничтожение,
               стремление сблизиться, бережливость, порог способностей) подобраны
               автоматически восхождением по результатам партий — отдельно для каждой роли;
  montecarlo — «всегда ищет лучший ход»: берёт K лучших кандидатов тактического бота и каждый
               доигрывает N раз вперёд на H раундов (своими кубиками, будущее партии не
               подсматривает); выбирает кандидат с лучшим средним исходом.

Режимы: flagship — «Эскадра против флагмана» (A — «Палач», B — эскадра, бюджет 31, до 4
кораблей, лимит 12); duel — дуэль эпохи «Галактическая гражданская война» (случайный драфт).

Запуск (из tools/):
  python3 -m sim_v4.arena train            # подобрать веса adaptive для ролей empire/squad/duel
  python3 -m sim_v4.arena tournament       # сетка «бот против бота» в обоих режимах
Вывод: tools/sim_v4/adaptive.json, reports/arena.md
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from multiprocessing import Pool
from pathlib import Path

from .bots import WELL_W, KILL_BONUS, GreedyBot, HunterBot, RandomBot, TacticalBot, play_match, worth
from .draft import RandomDrafter, run_draft
from .flagship import EMPIRE, SCEN as FLAG_SCEN, SQUAD_HEROES, squad_fleet
from .rules import Match, dist

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADAPTIVE = HERE / "adaptive.json"
OUT = ROOT / "reports" / "arena.md"
STRAT = json.loads((HERE / "strategy.json").read_text(encoding="utf-8"))["strategy"]
ENGAGE_MARGIN = 0.1
DEFAULT_W = {"threat_w": 0.45, "idle_w": 0.15, "kill_bonus": KILL_BONUS, "approach": 0.05, "theta": 1.0}


# ------------------------------------------------------------------ подстраивающийся бот
class AdaptiveBot(TacticalBot):
    name = "adaptive"

    def __init__(self, seed=0, strat=None, w=None):
        super().__init__(seed, strat)
        w = {**DEFAULT_W, **(w or {})}
        # сближение всегда выгоднее бережливости: иначе бот «учится» стоять и ждать соперника —
        # против другого такого же бота это ничья по лимиту раундов (найдено при самоигре)
        w["approach"] = max(w["approach"], w["idle_w"] + ENGAGE_MARGIN)
        self.w = w
        self.threat_w = w["threat_w"]
        self.idle_w = w["idle_w"]
        if self.strat:
            self.strat = {h: v * w["theta"] for h, v in self.strat.items()}

    def attack_value(self, m, s, target, mod=0):
        ev = m.attack_ev(s, target, extra_mod=mod)
        if ev is None:
            return None
        hull, kill = ev
        return hull + self.w["kill_bonus"] * kill * (1 + target.d["draft_cost"] / 10)

    def score_here(self, m, s, spent):
        atk, _ = self.best_attack(m, s) if not s.attack_used else (0.0, None)
        score = atk - self.threat_w * self.threat(m, s) - WELL_W * self.well_penalty(m, s)
        if atk == 0:
            nearest = min((dist(s.pos, o.pos) for o in m.ships if o.alive and o.seat != s.seat), default=0)
            score -= self.w["approach"] * nearest
        if spent and self.idle_w:
            score -= self.idle_w
        return score


# ------------------------------------------------------------------ Монте-Карло
class _Forced(TacticalBot):
    """Исполнитель одного заданного хода (корабль + манёвры), дальше — как тактический."""

    def __init__(self, seed, strat, uid, acts):
        super().__init__(seed, strat)
        self.forced = (uid, acts)

    def choose(self, m, only=None):
        if self.forced and only is None:
            uid, acts = self.forced
            self.forced = None
            return m.ships[uid], acts
        return super().choose(m, only)


class MonteCarloBot(TacticalBot):
    name = "montecarlo"
    K, N, H = 5, 10, 6                                 # кандидатов, доигрываний, раундов вперёд

    def outcome(self, m: Match, seat):
        if m.done:
            return 0.5 if m.winner is None else float(m.winner == seat)
        mine = sum(worth(s) for s in m.ships if s.seat == seat)
        other = sum(worth(s) for s in m.ships if s.seat != seat)
        return mine / max(1e-9, mine + other)          # не доиграли — доля сил

    def choose(self, m: Match, only=None):
        if only is not None:
            return super().choose(m, only)
        cands = []
        for s in m.ships:
            if not (s.alive and s.seat == m.turn_seat and not s.activated):
                continue
            q0, r0, f0 = s.q, s.r, s.facing
            for acts, q, r, f, spent in self.plans(m, s):
                s.q, s.r, s.facing = q, r, f
                cands.append((self.score_here(m, s, spent) + self.rng.random() * 1e-3, s.uid, acts))
            s.q, s.r, s.facing = q0, r0, f0
        cands.sort(key=lambda x: -x[0])
        top, seen = [], set()
        for sc, uid, acts in cands:                    # K разных кандидатов (разные клетки/корабли)
            if (uid, acts) in seen:
                continue
            seen.add((uid, acts))
            top.append((uid, acts))
            if len(top) >= self.K:
                break
        seat = m.turn_seat
        best, best_v = top[0], -1.0
        for uid, acts in top:
            v = 0.0
            for _ in range(self.N):
                m2 = copy.deepcopy(m)
                m2.rng = random.Random(self.rng.random())       # свои кубики, будущее партии не видно
                m2.events = None
                m2.on_apply = None               # копия партии не пишет в журнал игры
                h = m2.heroes
                pol = [TacticalBot(self.rng.randrange(1 << 30), strat={h[0]: STRAT.get(h[0], .6)}),
                       TacticalBot(self.rng.randrange(1 << 30), strat={h[1]: STRAT.get(h[1], .6)})]
                _Forced(self.rng.randrange(1 << 30), {h[seat]: STRAT.get(h[seat], .6)}, uid, acts).play_turn(m2)
                stop = m2.round + self.H
                guard = 0
                while not m2.done and m2.round < stop and guard < 400:
                    pol[m2.turn_seat].play_turn(m2)
                    guard += 1
                v += self.outcome(m2, seat)
            v /= self.N
            if v > best_v:
                best, best_v = (uid, acts), v
        return m.ships[best[0]], best[1]


# ------------------------------------------------------------------ партии
def load_adaptive():
    try:
        return json.loads(ADAPTIVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def make_bot(kind, seed, hero, role, weights=None):
    st = {hero: STRAT.get(hero, .6)}
    if kind == "random":
        return RandomBot(seed)
    if kind == "greedy":
        return GreedyBot(seed, strat=st)
    if kind == "tactical":
        return TacticalBot(seed, strat=st)
    if kind == "hunter":
        return HunterBot(seed, strat=st)
    if kind == "neural":
        from .nn import NeuralBot, ValueNet, WEIGHTS
        return NeuralBot(seed, ValueNet.load(WEIGHTS)) if WEIGHTS.exists() else TacticalBot(seed, strat=st)
    if kind == "adaptive":
        return AdaptiveBot(seed, strat=st, w=(weights or load_adaptive()).get(role))
    if kind == "montecarlo":
        return MonteCarloBot(seed, strat=st)
    raise ValueError(kind)


def setup(mode, seed):
    rng = random.Random(seed)
    if mode == "flagship":
        ha, hb = rng.choice(EMPIRE), rng.choice(SQUAD_HEROES)
        o = FLAG_SCEN["seat_overrides"]["B1"]
        fleet = squad_fleet(rng, hb, o["draft_budget"], o["fleet_size"])
        return ([ha, hb], [["executor"], fleet], FLAG_SCEN) if fleet else None
    st = run_draft([RandomDrafter(seed), RandomDrafter(seed + 1)], seed, era="galactic_civil_war")
    return (list(st.heroes), [list(st.ships[0]), list(st.ships[1])], None) if st else None


def game(args):
    """Партия: бот kind_a на месте 0, kind_b на месте 1. Возвращает победителя (0/1/None)."""
    mode, seed, kind_a, kind_b, weights = args
    s = setup(mode, seed)
    if s is None:
        return None
    heroes, fleets, scen = s
    roles = ("empire", "squad") if mode == "flagship" else ("duel", "duel")
    bots = [make_bot(kind_a, seed, heroes[0], roles[0], weights), make_bot(kind_b, seed + 1, heroes[1], roles[1], weights)]
    if mode == "duel" and seed % 2:                     # в дуэли меняем стороны — первый ход
        w, _, _ = play_match(heroes[::-1], fleets[::-1], bots[::-1], seed=seed)
        return None if w is None else 1 - w
    w, _, _ = play_match(heroes, fleets, bots, seed=seed, scen=scen)
    return w


# ------------------------------------------------------------------ обучение adaptive
def score_weights(pool, mode, role, w, opp, seeds):
    weights = {role: w}
    if mode == "flagship" and role == "empire":
        args = [(mode, s, "adaptive", opp, weights) for s in seeds]
        me = 0
    elif mode == "flagship":
        args = [(mode, s, opp, "adaptive", weights) for s in seeds]
        me = 1
    else:
        args = [(mode, s, "adaptive", opp, weights) for s in seeds]
        me = 0
    res = [r for r in pool.map(game, args, chunksize=16)]
    return sum(1.0 if r == me else (0.5 if r is None else 0.0) for r in res) / len(res)


def train(args):
    rng = random.Random(7)
    out = load_adaptive()
    jobs = [("flagship", "empire", "hunter"), ("flagship", "squad", "tactical"), ("duel", "duel", "tactical")]
    STEP = {"threat_w": 0.15, "idle_w": 0.08, "kill_bonus": 1.0, "approach": 0.04, "theta": 0.3}
    LIM = {"threat_w": (0, 1.5), "idle_w": (0, 0.6), "kill_bonus": (0, 8), "approach": (0, 0.3), "theta": (0, 3)}
    with Pool(args.workers) as pool:
        for mode, role, opp in jobs:
            cur = dict(out.get(role, DEFAULT_W))
            seeds = list(range(1000, 1000 + args.games))
            cur_s = score_weights(pool, mode, role, cur, opp, seeds)
            print(f"[{role}] старт: {cur_s:.1%} против {opp}", flush=True)
            for it in range(args.iters):
                seeds = list(range(10_000 * (it + 2), 10_000 * (it + 2) + args.games))   # общие сиды для честного сравнения
                cur_s = score_weights(pool, mode, role, cur, opp, seeds)
                best, best_s = cur, cur_s
                for _ in range(args.cands):
                    cand = dict(cur)
                    for k in rng.sample(list(STEP), 2):
                        cand[k] = round(min(LIM[k][1], max(LIM[k][0], cand[k] + rng.choice((-1, 1)) * STEP[k])), 3)
                    s = score_weights(pool, mode, role, cand, opp, seeds)
                    if s > best_s:
                        best, best_s = cand, s
                cur = best
                print(f"[{role}] шаг {it + 1}: {best_s:.1%} {cur}", flush=True)
            out[role] = cur
            ADAPTIVE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ турнир
def tournament(args):
    kinds = args.bots.split(",")
    t0 = time.time()
    lines = ["# Турнир ботов", "",
             f"- Сгенерировано: `python3 -m sim_v4.arena tournament --games {args.games} --mc-games {args.mc_games}` "
             "(из `tools/`).",
             "- Ячейка — процент побед бота строки против бота столбца. В «Эскадре против флагмана» строка "
             "играет за Империю («Палач»), столбец — за эскадру; в дуэли стороны меняются через партию.",
             "- montecarlo играет меньше партий (он в сотни раз медленнее), поэтому его цифры шумнее.", ""]
    with Pool(args.workers) as pool:
        for mode in ("flagship", "duel"):
            title = "Эскадра против флагмана (строка — Империя, столбец — эскадра)" if mode == "flagship" \
                else "Дуэль эпохи «Галактическая гражданская война» (строка против столбца)"
            lines += [f"## {title}", "", "| | " + " | ".join(kinds) + " |", "|---|" + "---:|" * len(kinds)]
            for a in kinds:
                row = []
                for b in kinds:
                    n = args.mc_games if "montecarlo" in (a, b) else args.games
                    if a == b and mode == "duel":
                        row.append("—"); continue
                    res = [r for r in pool.map(game, [(mode, 50_000 + i, a, b, None) for i in range(n)], chunksize=4)]
                    dec = [r for r in res if r is not None]
                    p = sum(1 for r in dec if r == 0) / max(1, len(dec))
                    row.append(f"{p:.0%} ({len(dec)})")
                    print(f"{mode}: {a} против {b}: {p:.0%} ({len(dec)} партий), {(time.time() - t0) / 60:.1f} мин",
                          flush=True)
                lines.append(f"| **{a}** | " + " | ".join(row) + " |")
            lines.append("")
    lines += ["Веса adaptive (подобраны `python3 -m sim_v4.arena train`):", "", "```json",
              json.dumps(load_adaptive(), ensure_ascii=False, indent=1), "```"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "tournament"])
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--mc-games", type=int, default=24)
    ap.add_argument("--iters", type=int, default=8)
    ap.add_argument("--cands", type=int, default=4)
    ap.add_argument("--bots", default="random,greedy,tactical,hunter,neural,adaptive,montecarlo")
    ap.add_argument("--workers", type=int, default=9)
    args = ap.parse_args()
    (train if args.cmd == "train" else tournament)(args)


if __name__ == "__main__":
    main()
