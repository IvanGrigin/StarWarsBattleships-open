"""Автоподбор баланса героев v4 по партиям ботов.

Итерация:
  1. N партий: герои — случайная пара (каждый герой играет поровну), корабли —
     драфт из общего каталога (случайные законные выборы), бой — TacticalBot
     с обеих сторон, стороны меняются через партию.
  2. Процент побед каждого героя (по результативным партиям) с 95% интервалом.
  3. Герой выше нормы (> 50% + допуск и значимо) — на ступень слабее по своей
     лестнице (tune.LADDERS); ниже нормы — на ступень сильнее.
Повторяется, пока все в коридоре или кончились итерации. Перед этим (--strategy)
подбираются пороги применения способностей: в каждой партии порог каждой
стороны случайный из THETAS, для героя берётся порог с лучшим процентом побед.

Запуск (из tools/):  python3 -m sim_v4.tuner --matches 200000 --iterations 6
Вывод:  reports/balance_v4_tuning.md, tools/sim_v4/tuning.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

from . import tune
from .bots import DEFAULT_THETA, TacticalBot, play_match
from .draft import BASE_ARCS, BASE_COST, RandomDrafter, apply_arcs, cost_with_arcs, run_draft
from .rules import HEROES, SHIPS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "balance_v4_tuning.md"
STATE = Path(__file__).resolve().parent / "tuning.json"
HERO_IDS = sorted(HEROES)
THETAS = [0.0, 0.6, 1.5, 3.0]
BAND = 0.03                                             # коридор нормы: 50% ± 3 п.п.
MAX_ARC_SHIFT = 2                                       # сектор — не дальше ±2 от карточки
MIN_ARC, MAX_ARC = -1, 4
MIN_SHIP_GAMES = 1500                                   # меньше партий — сектора не трогать
UNITS = {"F": (0,), "борта": (1, 5), "корма-борта": (2, 4), "B": (3,)}
NERF_ORDER = ["борта", "корма-борта", "F", "B"]         # при равенстве сначала режем борта, F — в последнюю
BUFF_ORDER = ["борта", "F", "корма-борта", "B"]

_cur = {"levels": None, "arcs": None, "hcost": None}


def _one(args):
    seed, levels, strat, explore, arcs, hcost = args
    if _cur["levels"] != levels:
        tune.set_levels(levels)
        _cur["levels"] = levels
    if _cur["arcs"] != arcs:
        apply_arcs(arcs)
        _cur["arcs"] = arcs
    if _cur["hcost"] != hcost:
        tune.set_hero_costs(hcost)
        _cur["hcost"] = hcost
    rng = random.Random(seed)
    heroes = rng.sample(HERO_IDS, 2)
    st = run_draft([RandomDrafter(seed), RandomDrafter(seed + 1)], seed, heroes=heroes)
    if st is None:
        return None
    thetas = [rng.choice(THETAS) if explore else strat.get(h, DEFAULT_THETA) for h in heroes]
    bots = [TacticalBot(seed + i, strat={heroes[i]: thetas[i]}) for i in (0, 1)]
    ships = st.ships
    if seed % 2:                                        # смена сторон: кто ходит первым
        w, rounds, _ = play_match(heroes[::-1], ships[::-1], bots[::-1], seed=seed)
        w = None if w is None else 1 - w
    else:
        w, rounds, _ = play_match(heroes, ships, bots, seed=seed)
    return heroes, ships, w, rounds, thetas, seed % 2


def ci(w, n):
    if n == 0:
        return 0.5, 0.0, 1.0
    p = w / n
    h = 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / n)
    return p, p - h, p + h


def run(pool, n, seed0, levels, strat, explore=False, arcs=None, hcost=None):
    args = [(seed0 + i, levels, strat, explore, arcs or {}, hcost or {}) for i in range(n)]
    return [r for r in pool.imap_unordered(_one, args, chunksize=64) if r]


def stats(res):
    hero, ship, fac, theta = (defaultdict(lambda: [0, 0]) for _ in range(4))
    first = [0, 0]
    draws = 0
    for heroes, ships, w, _, thetas, swapped in res:
        if w is None:
            draws += 1
            continue
        mover = 1 if swapped else 0                      # сторона, ходившая первой
        first[0] += w == mover; first[1] += 1
        for side in (0, 1):
            won = int(w == side)
            h = heroes[side]
            hero[h][0] += won; hero[h][1] += 1
            fac[HEROES[h]["faction"]][0] += won; fac[HEROES[h]["faction"]][1] += 1
            theta[(h, thetas[side])][0] += won; theta[(h, thetas[side])][1] += 1
            for s in ships[side]:
                ship[s][0] += won; ship[s][1] += 1
    return {"hero": hero, "ship": ship, "fac": fac, "theta": theta, "first": first, "draws": draws}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=200000)
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--strategy", type=int, default=160000, help="партий на подбор порогов (0 — пропустить)")
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--arcs", action="store_true", help="подбирать сектора кораблей (цена — по формуле)")
    ap.add_argument("--hero-cost", action="store_true",
                    help="сначала цена героя в драфте, лестница способности — когда цена упёрлась в край")
    ap.add_argument("--strategy-from", default=None, help="взять пороги способностей из tuning.json")
    args = ap.parse_args()

    levels = {}
    strat = {}
    arcs = {}
    hcost = {}
    if args.strategy_from:
        strat = json.loads(Path(args.strategy_from).read_text(encoding="utf-8"))["strategy"]
        args.strategy = 0
    history = []
    t0 = time.time()
    with Pool(args.workers) as pool:
        if args.strategy:
            t = time.time()
            res = run(pool, args.strategy, 10_000_000, levels, strat, explore=True)
            th = stats(res)["theta"]
            for h in HERO_IDS:
                best = max(THETAS, key=lambda x: ci(*th[(h, x)])[0] if th[(h, x)][1] else -1)
                strat[h] = best
            print(f"пороги способностей подобраны за {(time.time() - t) / 60:.1f} мин: "
                  + ", ".join(f"{h}={v}" for h, v in strat.items()), flush=True)
            strat_table = {h: {x: th[(h, x)] for x in THETAS} for h in HERO_IDS}
        else:
            strat_table = {}

        for it in range(args.iterations + 1):
            t = time.time()
            res = run(pool, args.matches, 20_000_000 + it * 1_000_000, dict(levels), strat,
                      arcs={k: list(v) for k, v in arcs.items()}, hcost=dict(hcost))
            st = stats(res)
            hero = {h: ci(*st["hero"][h]) + (st["hero"][h][1],) for h in HERO_IDS}
            history.append({"levels": dict(levels), "hero": hero, "stats": st,
                            "arcs": {k: list(v) for k, v in arcs.items()}, "hcost": dict(hcost)})
            out_band = [h for h, (p, lo, hi, n) in hero.items() if lo > 0.5 + BAND or hi < 0.5 - BAND]
            print(f"итерация {it}: {len(res)} партий за {(time.time() - t) / 60:.1f} мин; "
                  f"вне коридора {len(out_band)}: " + ", ".join(f"{h} {hero[h][0]:.1%}" for h in out_band),
                  flush=True)
            if it == args.iterations or not out_band:
                break
            moved = False
            for h in out_band:
                p = hero[h][0]
                if args.hero_cost:
                    c = hcost.get(h, tune.BASE_HERO_COST)
                    if p > 0.5 and c < tune.MAX_HERO_COST:
                        hcost[h] = c + 1; moved = True; continue
                    if p < 0.5 and c > 0:
                        hcost[h] = c - 1; moved = True; continue
                cur = levels.get(h, tune.BASE_LEVEL[h])
                nxt = cur - 1 if p > 0.5 else cur + 1
                if 0 <= nxt < len(tune.LADDERS[h]):
                    # не возвращаться на ступень, с которой только что ушли в другую сторону
                    if len(history) >= 3 and history[-3]["levels"].get(h, tune.BASE_LEVEL[h]) == nxt:
                        continue
                    levels[h] = nxt
                    moved = True
            if args.arcs:
                for sid, (w, n) in st["ship"].items():
                    p, lo, hi = ci(w, n)
                    if n < MIN_SHIP_GAMES or (hi >= 0.5 - BAND and lo <= 0.5 + BAND):
                        continue
                    if step_arcs(sid, arcs, nerf=lo > 0.5 + BAND):
                        moved = True
            if not moved:
                break

    STATE.write_text(json.dumps({"levels": levels, "strategy": strat, "arc_delta": arcs, "hero_cost": hcost},
                                ensure_ascii=False, indent=1),
                     encoding="utf-8")
    report(args, history, strat, strat_table, time.time() - t0, arcs, hcost)


def step_arcs(sid, arcs, nerf):
    """Ослабить (nerf) или усилить корабль на единицу сектора: борта меняются парой."""
    d = arcs.setdefault(sid, [0] * 6)
    base = BASE_ARCS[sid]
    cur = [b + x for b, x in zip(base, d)]
    order = NERF_ORDER if nerf else BUFF_ORDER
    step = -1 if nerf else 1
    cands = []
    for k, unit in enumerate(order):
        idx = UNITS[unit]
        if all(MIN_ARC <= cur[i] + step <= MAX_ARC and abs(d[i] + step) <= MAX_ARC_SHIFT for i in idx):
            val = max(cur[i] for i in idx) if nerf else min(cur[i] for i in idx)
            cands.append(((-val if nerf else val), k, idx))
    if not cands:
        if not any(d):
            arcs.pop(sid, None)
        return False
    _, _, idx = min(cands)
    for i in idx:
        d[i] += step
    if not any(d):
        arcs.pop(sid, None)
    return True


def report(args, history, strat, strat_table, took, arcs=None, hcost=None):
    first, last = history[0], history[-1]
    hn = lambda h: HEROES[h]["display_name"]
    L = [
        "# Автоподбор баланса героев v4",
        "",
        f"- Сгенерировано: `python3 -m sim_v4.tuner --matches {args.matches} --iterations {args.iterations} "
        f"--strategy {args.strategy}` (из `tools/`), {took / 60:.0f} мин, итераций {len(history)}.",
        f"- В каждой итерации {args.matches} партий: случайная пара героев (каждый герой играет поровну), "
        "корабли — драфт из общего каталога случайными законными выборами, бой — тактический бот с обеих "
        "сторон, стороны меняются через партию.",
        f"- Коридор нормы — 50% ± {BAND:.0%}: героя выше коридора ослабляем на ступень его лестницы, ниже — "
        "усиливаем (лестницы — `tools/sim_v4/tune.py`).",
        "- Это **предложения**: карточки в датасете не менялись. Итоговые ступени — `tools/sim_v4/tuning.json`.",
        "",
        "> Симулятор не моделирует гиперпрыжок (кроме способности Хана), абордаж, таран, местность, "
        "события, пиратов, ион, тяговый луч, маскировку. Поэтому по героям, чья сила в этих механиках "
        "(Нут — блокада гиперпрыжка, Чубакка и Финн — абордаж, R2-D2 и Фазма — защита от иона), "
        "цифры занижены, а предложения — осторожные.",
        "",
        "## Итог по героям",
        "",
        "| Герой | Фракция | Было (карточка) | Стало | Предлагаемая правка |",
        "|---|---|---:|---:|---|",
    ]
    rows = []
    for h in HERO_IDS:
        p0 = first["hero"][h][0]
        p1 = last["hero"][h][0]
        lvl = last["levels"].get(h, tune.BASE_LEVEL[h])
        text = tune.LADDERS[h][lvl][0]
        rows.append((p0, h, p1, text))
    for p0, h, p1, text in sorted(rows, reverse=True):
        mark = "" if text == tune.CARD else "**"
        L.append(f"| {hn(h)} | {HEROES[h]['faction']} | {p0:.1%} | {p1:.1%} | {mark}{text}{mark} |")
    spread0 = max(first["hero"][h][0] for h in HERO_IDS) - min(first["hero"][h][0] for h in HERO_IDS)
    spread1 = max(last["hero"][h][0] for h in HERO_IDS) - min(last["hero"][h][0] for h in HERO_IDS)
    sd = lambda hist: math.sqrt(sum((hist["hero"][h][0] - 0.5) ** 2 for h in HERO_IDS) / len(HERO_IDS))
    L += ["", f"Разброс героев: было {spread0:.1%} (от худшего до лучшего), стало {spread1:.1%}; "
          f"среднее отклонение от 50%: было {sd(first):.1%}, стало {sd(last):.1%}.", ""]

    SEC = ["F", "FR", "BR", "B", "BL", "FL"]
    if hcost:
        L += ["## Цена героя в драфте", "",
              f"Общий бюджет — {tune.BUDGET_TOTAL} очков на героя и корабли; базовая цена героя — "
              f"{tune.BASE_HERO_COST} (кораблям остаётся 24, как сейчас). Дорогой герой — меньше очков на корабли.", "",
              "| Герой | Цена | Кораблям остаётся |", "|---|---:|---:|"]
        for h, c in sorted(hcost.items(), key=lambda x: -x[1]):
            if c != tune.BASE_HERO_COST:
                L.append(f"| {hn(h)} | {c} | {tune.BUDGET_TOTAL - c} |")
        L.append("")
    if arcs:
        f0 = first["stats"]["ship"]
        f1 = last["stats"]["ship"]
        L += ["## Сектора кораблей", "",
              "Меняются только числа секторов (F FR BR B BL FL); фракция и остальное — как на карточке. "
              "Цена пересчитана по формуле v4. Выше коридора — минус единица в самом сильном секторе "
              "(борта парой), ниже — плюс в самом слабом; не дальше ±2 от карточки.", "",
              "| Корабль | Сектора на карточке | Предлагаемые | Цена | Было побед | Стало |", "|---|---|---|---:|---:|---:|"]
        for sid, d in sorted(arcs.items(), key=lambda x: SHIPS[x[0]]["display_name"]):
            if not any(d):
                continue
            b = BASE_ARCS[sid]
            new = [x + y for x, y in zip(b, d)]
            fmt = lambda a: " ".join(f"{v:+d}" if v else "0" for v in a)
            p0 = f0[sid][0] / f0[sid][1] if f0[sid][1] else 0
            p1 = f1[sid][0] / f1[sid][1] if f1[sid][1] else 0
            L.append(f"| {SHIPS[sid]['display_name']} | {fmt(b)} | {fmt(new)} | {BASE_COST[sid]} → "
                     f"{cost_with_arcs(sid, new)} | {p0:.1%} | {p1:.1%} |")
        L.append("")
    L += ["## Ход подбора", "", "| Итерация | Вне коридора | Изменения ступеней |", "|---:|---:|---|"]
    prev = {}
    for i, hs in enumerate(history):
        out = sum(1 for h in HERO_IDS if hs["hero"][h][1] > 0.5 + BAND or hs["hero"][h][2] < 0.5 - BAND)
        ch = [f"{hn(h)}: {tune.LADDERS[h][v][0]}" for h, v in hs["levels"].items() if prev.get(h) != v]
        L.append(f"| {i} | {out} | {'; '.join(ch) or '—'} |")
        prev = dict(hs["levels"])

    if strat_table:
        L += ["", "## Индивидуальные стратегии: когда применять способность", "",
              "Порог — насколько выгодным должен быть момент (в единицах ожидаемого урона), чтобы бот "
              "потратил способность; 0 — применять при первой пользе, 3 — беречь для очень сильного "
              "момента. Порог падает, когда кораблей остаётся меньше.", "",
              "| Герой | " + " | ".join(f"порог {x}" for x in THETAS) + " | Выбран |",
              "|---|" + "---:|" * len(THETAS) + "---:|"]
        for h in HERO_IDS:
            cells = []
            for x in THETAS:
                w, n = strat_table[h][x]
                cells.append(f"{w / n:.1%}" if n else "—")
            L.append(f"| {hn(h)} | " + " | ".join(cells) + f" | {strat[h]} |")

    st = last["stats"]
    p, lo, hi = ci(*st["first"])
    L += ["", "## После подбора: фракции, первый ход, корабли", "",
          f"Сторона, ходящая первой, выигрывает {p:.1%} ({lo:.1%} – {hi:.1%}). Ничьих: {st['draws']}.", "",
          "| Фракция героя | Побед | 95% интервал |", "|---|---:|---|"]
    for f, (w, n) in sorted(st["fac"].items(), key=lambda x: -x[1][0] / x[1][1]):
        p, lo, hi = ci(w, n)
        L.append(f"| {f} | {p:.1%} | {lo:.1%} – {hi:.1%} |")
    L += ["", "| Корабль | Партий | Побед | 95% интервал |", "|---|---:|---:|---|"]
    for s, (w, n) in sorted(st["ship"].items(), key=lambda x: -x[1][0] / x[1][1]):
        p, lo, hi = ci(w, n)
        L.append(f"| {SHIPS[s]['display_name']} | {n} | {p:.1%} | {lo:.1%} – {hi:.1%} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
