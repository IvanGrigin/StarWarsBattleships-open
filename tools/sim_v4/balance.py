"""Турнир баланса v4: какие герои, корабли и связки выигрывают чаще, чем должны.

Партии: бот против того же бота, случайные герои и случайные законные флоты
(драфт по правилам v4), стороны меняются через партию. Отдельно —
прицельная проверка заданных флотов против случайных соперников.

Запуск (из tools/):  python3 -m sim_v4.balance --matches 60000 --bot tactical
Вывод:   reports/balance_v4_matches.md
"""

from __future__ import annotations

import argparse
import math
import random
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

from .bots import GreedyBot, TacticalBot, play_match
from .rules import HEROES, SHIPS, legal_fleet, random_fleet

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "balance_v4_matches.md"
BOTS = {"greedy": GreedyBot, "tactical": TacticalBot}
HERO_IDS = sorted(HEROES)

# Прицельные флоты: то, что владелец назвал подозрительным, и очевидные «сильные» сборки
TARGETED = [
    ("luke", ["xwing_t65", "xwing_t65", "xwing_t65"], "Люк + три X-wing"),
    ("luke", ["awing_rz1", "xwing_t65", "xwing_t65"], "Люк + два X-wing + A-wing"),
    ("luke", ["awing_rz1", "xwing_t65", "ywing_btla4"], "Люк + X-wing + Y-wing + A-wing"),
    ("emperor_palpatine", ["star_destroyer", "tie_interceptor", "tie_fighter"], "Палпатин + ISD + СИДы"),
    ("emperor_palpatine", ["providence", "vulture_droid", "tie_fighter"], "Палпатин + «Провиденс» (КНС+Империя)"),
    ("darth_vader", ["tie_advanced_x1", "tie_interceptor", "tie_interceptor"], "Вейдер + TIE Advanced + перехватчики"),
    ("phasma", ["tie_fo", "tie_fo", "resurgent_destroyer"], "Фазма + СИД/fo ×2 + «Возрождение»"),
    ("padme_amidala", ["arc170", "v19_torrent", "eta2_actis"], "Падме + чистая Республика"),
    ("kylo_ren", ["tie_silencer", "tie_fo", "tie_fo"], "Кайло + «Тихушник» + СИД/fo ×2"),
    ("general_grievous", ["soulless_one", "vulture_droid", "tri_fighter"], "Гривус + «Бездушный» + дроиды"),
]


def _one(args):
    seed, bot, fixed = args
    rng = random.Random(seed)
    if fixed:
        hero_a, fleet_a = fixed
        hero_b = rng.choice(HERO_IDS)
        fleets = [fleet_a, random_fleet(hero_b, rng)]
        heroes = [hero_a, hero_b]
    else:
        heroes = [rng.choice(HERO_IDS), rng.choice(HERO_IDS)]
        fleets = [random_fleet(heroes[0], rng), random_fleet(heroes[1], rng)]
    if None in fleets:
        return None
    swap = seed % 2 == 1
    if swap:
        heroes, fleets = heroes[::-1], fleets[::-1]
    win, rounds, m = play_match(heroes, fleets, [BOTS[bot](seed), BOTS[bot](seed + 1)], seed=seed)
    if swap:                                           # вернуть порядок: сторона 0 = «первая» в записи
        heroes, fleets = heroes[::-1], fleets[::-1]
        win = None if win is None else 1 - win
    return heroes, fleets, win, rounds, swap


def ci(w, n):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = w / n
    h = 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / n)
    return p, p - h, p + h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=60000)
    ap.add_argument("--targeted", type=int, default=2000)
    ap.add_argument("--bot", default="tactical", choices=list(BOTS))
    ap.add_argument("--workers", type=int, default=9)
    args = ap.parse_args()

    t = time.time()
    with Pool(args.workers) as pool:
        res = [r for r in pool.map(_one, [(i, args.bot, None) for i in range(args.matches)], chunksize=128) if r]
        targeted = {}
        for k, (hero, fleet, label) in enumerate(TARGETED):
            assert legal_fleet(hero, fleet), label
            rr = [r for r in pool.map(_one, [(5_000_000 + k * 100_000 + i, args.bot, (hero, fleet))
                                             for i in range(args.targeted)], chunksize=64) if r]
            targeted[label] = rr
    took = time.time() - t

    # --- агрегаты: каждая сторона партии — отдельное наблюдение
    hero_s, ship_s, fac_s, pair_s, fleet_s = (defaultdict(lambda: [0, 0]) for _ in range(5))
    first_wins = decisive = draws = 0
    rounds = []
    for heroes, fleets, win, r, swap in res:
        rounds.append(r)
        if win is None:
            draws += 1
            continue
        decisive += 1
        # «первая» сторона (ходит первой в раунде 1) — seat 0 после обратной перестановки = та, что не swap
        mover0 = 1 if swap else 0
        first_wins += (win == mover0)
        for side in (0, 1):
            won = int(win == side)
            h = heroes[side]
            hero_s[h][0] += won; hero_s[h][1] += 1
            fac_s[HEROES[h]["faction"]][0] += won; fac_s[HEROES[h]["faction"]][1] += 1
            key = (h, tuple(sorted(fleets[side])))
            fleet_s[key][0] += won; fleet_s[key][1] += 1
            for sid in set(fleets[side]):
                ship_s[sid][0] += won; ship_s[sid][1] += 1
                pair_s[(h, sid)][0] += won; pair_s[(h, sid)][1] += 1

    def table(stats, label_fn, min_n, top=None, header="Что"):
        rows = []
        for k, (w, n) in stats.items():
            if n >= min_n:
                p, lo, hi = ci(w, n)
                rows.append((p, lo, hi, n, label_fn(k)))
        rows.sort(key=lambda x: -x[0])
        if top:
            rows = rows[:top] + ([None] if len(rows) > 2 * top else []) + rows[-top:] if len(rows) > 2 * top else rows
        out = [f"| {header} | Партий | Побед | 95% интервал | Оценка |", "|---|---:|---:|---|---|"]
        for r in rows:
            if r is None:
                out.append("| … | | | | |"); continue
            p, lo, hi, n, name = r
            flag = "**перекос вверх**" if lo > 0.55 else ("**слабее нормы**" if hi < 0.45 else "в норме")
            out.append(f"| {name} | {n} | {p:.1%} | {lo:.1%} – {hi:.1%} | {flag} |")
        return out

    hname = lambda h: HEROES[h]["display_name"]
    sname = lambda s: SHIPS[s]["display_name"]
    p0, lo0, hi0 = ci(first_wins, decisive)
    lines = [
        "# Баланс v4 по партиям ботов",
        "",
        f"- Сгенерировано: `python3 -m sim_v4.balance --matches {args.matches} --bot {args.bot}` "
        f"(из `tools/`), {took / 60:.1f} мин.",
        f"- Партий: {len(res)}, результативных {decisive}, ничьих {draws}; средняя длина — "
        f"{sum(rounds) / len(rounds):.1f} раунда.",
        f"- Бот обеих сторон: `{args.bot}`. Герои и флоты — случайные, но законные по драфту v4; "
        "стороны меняются через партию.",
        f"- **Преимущество первого хода:** сторона, ходящая первой, выигрывает {p0:.1%} "
        f"({lo0:.1%} – {hi0:.1%}).",
        "",
        "Оценка «перекос вверх» — нижняя граница 95% интервала выше 55%; «слабее нормы» — верхняя "
        "ниже 45%. Ожидаемая норма — 50%.",
        "",
        "> Симулятор не моделирует гиперпрыжок, абордаж, таран, местность, события, пиратов, мины и "
        "бомбы Феттов, ион/тяговый луч/гравиколодец/маскировку и часть активных способностей героев "
        "(список — в шапке `tools/sim_v4/rules.py`). Герои и корабли, чья сила в этих механиках, "
        "здесь выглядят слабее, чем в настоящей игре.",
        "",
        "## Прицельные проверки",
        "",
        f"Каждый флот сыграл {args.targeted} партий против случайного героя со случайным законным флотом.",
        "",
        "| Флот | Партий | Побед | 95% интервал | Оценка |", "|---|---:|---:|---|---|",
    ]
    for label, rr in targeted.items():
        dec = [r for r in rr if r[2] is not None]
        w = sum(1 for r in dec if r[2] == 0)
        p, lo, hi = ci(w, len(dec))
        flag = "**перекос вверх**" if lo > 0.55 else ("**слабее нормы**" if hi < 0.45 else "в норме")
        lines.append(f"| {label} | {len(dec)} | {p:.1%} | {lo:.1%} – {hi:.1%} | {flag} |")
    lines += ["", "«Сидиус (Палпатин) + „Палач“» — **невозможен по правилам**: «Палач» стоит 21 из бюджета "
              "24, а два самых дешёвых корабля — не меньше 8 очков. Не проходят бюджет и «Люк + два X-wing + "
              "Y-wing» (25) и «Люк + „Сокол“ + два X-wing» (28).", "",
              "## Фракции (по фракции героя)", ""]
    lines += table(fac_s, lambda f: f, 1, header="Фракция")
    lines += ["", "## Герои", ""] + table(hero_s, hname, 1, header="Герой")
    lines += ["", "## Корабли (флоты, где корабль есть)", ""] + table(ship_s, sname, 200, header="Корабль")
    lines += ["", "## Связки «герой + корабль» — 12 сильнейших и 12 слабейших (от 150 партий)", ""]
    lines += table(pair_s, lambda k: f"{hname(k[0])} + {sname(k[1])}", 150, top=12, header="Связка")
    lines += ["", "## Конкретные флоты — 12 сильнейших и 12 слабейших (от 40 партий)", ""]
    lines += table(fleet_s, lambda k: f"{hname(k[0])}: " + ", ".join(sname(s) for s in k[1]), 40, top=12,
                   header="Флот")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)} — {len(res)} партий за {took / 60:.1f} мин; первый ход {p0:.1%}")


if __name__ == "__main__":
    main()
