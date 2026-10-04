"""Подбор чисел сценария «Эскадра против флагмана» (data/rulesets/v4/scenarios/flagship_hunt.json).

A — «Палач» и случайный герой Империи (TacticalBot). B — эскадра: случайный герой повстанцев или
охотников и корабли повстанцев и «вне эпохи» (без крупных, ≤1 именной, ≤1 чужой фракции), набранные
«как человек»: из 200 случайных законных составов берётся самый дорогой (бюджет тратится почти
весь). Бот эскадры — HunterBot (смелеет к концу лимита). Перебор: бюджет × число кораблей × лимит.

Запуск (из tools/):  python3 -m sim_v4.flagship --games 1500
Вывод:   reports/flagship_hunt.md
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from multiprocessing import Pool
from pathlib import Path

from .bots import HunterBot, TacticalBot, play_match
from .rules import HEROES, SHIPS, V4

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "flagship_hunt.md"
SCEN = json.loads((V4 / "scenarios" / "flagship_hunt.json").read_text(encoding="utf-8"))
EMPIRE = SCEN["flagship_heroes"]
SQUAD_HEROES = sorted(h for h, d in HEROES.items() if d["faction"] in SCEN["squadron_factions"]
                      and d["era"] in ("galactic_civil_war", "any"))
POOL = sorted(s for s, d in SHIPS.items() if d["draftable"] and d["era"] in ("galactic_civil_war", "any")
              and d["role"] != "capital" and d["faction"] in ("rebels", "bounty_hunters"))
STRAT = json.loads((Path(__file__).resolve().parent / "strategy.json").read_text(encoding="utf-8"))["strategy"]


def squad_fleet(rng, hero, budget, n, cost_add=0):
    """Самый дорогой законный состав из 200 случайных (≤ n кораблей, ≤1 именной, ≤1 чужой);
    cost_add — надбавка к цене каждого корабля эскадры (рычаг сценария)."""
    budget += 2 if hero == "lando_calrissian" else 0
    faction = HEROES[hero]["faction"]
    best = None
    for _ in range(200):
        k = n if rng.random() < 0.8 else n - 1
        f = rng.sample(POOL, k)
        cost = sum(SHIPS[s]["draft_cost"] + cost_add for s in f)
        if cost > budget or sum(SHIPS[s]["unique"] for s in f) > 1:
            continue
        if sum(SHIPS[s]["faction"] != faction for s in f) > 1:
            continue
        if best is None or cost > best[0]:
            best = (cost, f)
    return best[1] if best else None


def strong(args):
    """Партия сильных ботов: эскадра — adaptive (роль squad), Империя — adaptive или montecarlo."""
    from .arena import AdaptiveBot, MonteCarloBot, load_adaptive
    seed, budget, n, rounds, acts, cost_add, empire_kind = args
    rng = random.Random(seed)
    scen = dict(SCEN, round_limit=rounds, flagship_activations=acts)
    ha, hb = rng.choice(EMPIRE), rng.choice(SQUAD_HEROES)
    fleet = squad_fleet(rng, hb, budget, n, cost_add)
    if not fleet:
        return None
    w8 = load_adaptive()
    emp = MonteCarloBot(seed, strat={ha: STRAT.get(ha, .6)}) if empire_kind == "montecarlo" else \
        AdaptiveBot(seed, strat={ha: STRAT.get(ha, .6)}, w=w8.get("empire"))
    sq = AdaptiveBot(seed + 1, strat={hb: STRAT.get(hb, .6)}, w=w8.get("squad"))
    w, r, _ = play_match([ha, hb], [["executor"], fleet], [emp, sq], seed=seed, scen=scen)
    return w, r


def sweep_strong(args):
    """Полный перебор рычагов на сильных ботах: бюджет × кораблей × активаций «Палача» × надбавка
    к цене; затем 6 вариантов, ближайших к 50/50, перепроверяются с Монте-Карло за Империю."""
    grid = list(itertools.product([int(x) for x in args.budgets.split(",")], [int(x) for x in args.ships.split(",")],
                                  [int(x) for x in args.acts.split(",")], [int(x) for x in args.cost_add.split(",")]))
    t0 = time.time()
    rows = []
    with Pool(args.workers) as pool:
        for b, n, a, c in grid:
            res = [x for x in pool.map(strong, [(i, b, n, 12, a, c, "adaptive") for i in range(args.games)],
                                       chunksize=16) if x]
            p = sum(1 for w, _ in res if w == 1) / max(1, len(res))
            rows.append({"budget": b, "ships": n, "acts": a, "cost_add": c, "squad": p, "games": len(res),
                         "len": sum(x[1] for x in res) / max(1, len(res))})
            print(f"бюджет {b}, до {n} кор., активаций «Палача» {a}, надбавка +{c}: эскадра {p:.1%} ({len(res)})",
                  flush=True)
        solid = [r for r in rows if r["games"] >= 0.6 * args.games]   # мало партий — состав почти не собрать
        close = sorted(solid, key=lambda r: abs(r["squad"] - 0.5))[:6]
        for r in close:
            res = [x for x in pool.map(strong, [(900_000 + i, r["budget"], r["ships"], 12, r["acts"], r["cost_add"],
                                                 "montecarlo") for i in range(args.mc_games)], chunksize=2) if x]
            r["squad_mc"] = sum(1 for w, _ in res if w == 1) / max(1, len(res))
            r["mc_games"] = len(res)
            print(f"  проверка Монте-Карло: {r}", flush=True)
    for r in close:
        r["score"] = abs(r["squad"] - 0.5) + abs(r["squad_mc"] - 0.5)
    best = min(close, key=lambda r: r["score"])
    L = ["# «Эскадра против флагмана»: перенастройка под сильных игроков", "",
         f"- Сгенерировано: `python3 -m sim_v4.flagship --strong --games {args.games} --mc-games {args.mc_games}` "
         f"(из `tools/`), {(time.time() - t0) / 60:.0f} мин.",
         "- Эскадра — подстраивающийся бот (роль squad, `adaptive.json`); Империя — подстраивающийся (роль "
         "empire); 6 вариантов, ближайших к 50/50, перепроверены с Монте-Карло за «Палача».",
         "- Рычаги: бюджет эскадры, максимум кораблей, активаций «Палача» за раунд (он ходит через корабль "
         "эскадры и стреляет каждую активацию), надбавка к цене каждого корабля эскадры. Лимит — 12 раундов.", "",
         f"**Принято:** бюджет {best['budget']}, до {best['ships']} кораблей, «Палач» активируется {best['acts']} "
         f"раз(а) за раунд, надбавка +{best['cost_add']} к цене корабля эскадры — эскадра выигрывает "
         f"{best['squad']:.1%} против подстраивающегося «Палача» и {best['squad_mc']:.1%} против Монте-Карло.", "",
         "## Проверка лучших вариантов с Монте-Карло", "",
         "| Бюджет | Кораблей | Активаций «Палача» | Надбавка | Эскадра vs adaptive | Эскадра vs Монте-Карло |",
         "|---:|---:|---:|---:|---:|---:|"]
    for r in close:
        L.append(f"| {r['budget']} | {r['ships']} | {r['acts']} | +{r['cost_add']} | {r['squad']:.1%} ({r['games']}) | "
                 f"{r['squad_mc']:.1%} ({r['mc_games']}) |")
    L += ["", "## Весь перебор (эскадра — adaptive, Империя — adaptive)", "",
          "| Бюджет | Кораблей | Активаций «Палача» | Надбавка | Побед эскадры | Средняя длина | Партий |",
          "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        L.append(f"| {r['budget']} | {r['ships']} | {r['acts']} | +{r['cost_add']} | {r['squad']:.1%} | "
                 f"{r['len']:.1f} | {r['games']} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    (Path(__file__).resolve().parent / "flagship_best.json").write_text(json.dumps(best, ensure_ascii=False, indent=1),
                                                                         encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)}; принято: {best}")


def check(args):
    """Проверка заданных вариантов: Империя — Монте-Карло, эскадра — adaptive."""
    with Pool(args.workers) as pool:
        for spec in args.check.split(";"):
            b, n, a, c = (int(x) for x in spec.split(","))
            res = [x for x in pool.map(strong, [(950_000 + i, b, n, 12, a, c, "montecarlo") for i in range(args.mc_games)],
                                       chunksize=2) if x]
            sq = sum(1 for w, _ in res if w == 1) / max(1, len(res))
            ln = sum(r for _, r in res) / max(1, len(res))
            print(f"бюджет {b}, до {n} кор., активаций {a}, надбавка +{c}: эскадра против Монте-Карло {sq:.1%} "
                  f"({len(res)} партий), средняя длина {ln:.1f}", flush=True)


def one(args):
    seed, budget, n, rounds = args
    rng = random.Random(seed)
    scen = dict(SCEN, round_limit=rounds)
    ha, hb = rng.choice(EMPIRE), rng.choice(SQUAD_HEROES)
    fleet = squad_fleet(rng, hb, budget, n)
    if not fleet:
        return None
    w, r, _ = play_match([ha, hb], [["executor"], fleet],
                         [TacticalBot(seed, strat={ha: STRAT.get(ha, .6)}),
                          HunterBot(seed + 1, strat={hb: STRAT.get(hb, .6)})], seed=seed, scen=scen)
    return w, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1500)
    ap.add_argument("--budgets", default="24,28,32,36")
    ap.add_argument("--ships", default="3,4,5")
    ap.add_argument("--rounds", default="10,12,15")
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--strong", action="store_true", help="перебор на сильных ботах со всеми рычагами")
    ap.add_argument("--acts", default="1,2,3")
    ap.add_argument("--cost-add", default="0,1,2")
    ap.add_argument("--mc-games", type=int, default=80)
    ap.add_argument("--check", default=None, help="проверить варианты с Монте-Карло: «бюджет,кораблей,активаций,надбавка;…»")
    args = ap.parse_args()
    if args.check:
        return check(args)
    if args.strong:
        return sweep_strong(args)
    grid = list(itertools.product([int(x) for x in args.budgets.split(",")], [int(x) for x in args.ships.split(",")],
                                  [int(x) for x in args.rounds.split(",")]))
    t0 = time.time()
    rows = []
    with Pool(args.workers) as pool:
        for b, n, r in grid:
            res = [x for x in pool.map(one, [(i, b, n, r) for i in range(args.games)], chunksize=32) if x]
            wins = sum(1 for w, _ in res if w == 1)
            rows.append((b, n, r, wins / max(1, len(res)), sum(x[1] for x in res) / max(1, len(res)), len(res)))
            print(f"бюджет {b}, кораблей ≤{n}, лимит {r}: эскадра {rows[-1][3]:.1%} ({len(res)} партий)", flush=True)
    best = min(rows, key=lambda x: (abs(x[3] - 0.5), -x[2]))
    L = ["# «Эскадра против флагмана»: подбор чисел", "",
         f"- Сгенерировано: `python3 -m sim_v4.flagship --games {args.games}` (из `tools/`), {(time.time() - t0) / 60:.0f} мин.",
         "- A: «Палач» + случайный герой Империи (тактический бот). B: эскадра повстанцев и «вне эпохи» "
         "без крупных кораблей, набранная «как человек» — самый дорогой законный состав из 200 случайных; "
         "бот эскадры смелеет к концу лимита.",
         "- Победа B — «Палач» уничтожен до конца лимита; иначе победа A.", "",
         f"**Ближе всего к 50/50:** бюджет {best[0]}, до {best[1]} кораблей, лимит {best[2]} раундов — эскадра "
         f"выигрывает {best[3]:.1%}.", "",
         "| Бюджет эскадры | Кораблей | Лимит раундов | Побед эскадры | Средняя длина | Партий |",
         "|---:|---:|---:|---:|---:|---:|"]
    for b, n, r, p, rl, k in rows:
        L.append(f"| {b} | {n} | {r} | {p:.1%} | {rl:.1f} | {k} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)}; лучше всего: {best}")


if __name__ == "__main__":
    main()
