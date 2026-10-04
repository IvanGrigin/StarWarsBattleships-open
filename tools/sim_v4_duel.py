#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка стоимостей v4 упрощённой дуэлью «каждый против каждого».

Это не симуляция матча (нет поля, движения, героев, событий и местности), а
однородный стенд, который отвечает на один вопрос: не выбивается ли корабль
из своей ценовой категории по чистой боевой мощи.

Модель дуэли (сознательно упрощена, ограничения перечислены в отчёте):
  * два корабля стоят вплотную и бьют по очереди, первый ход разыгрывается
    честной монетой;
  * атакующий бросает 2d6 + модификатор своего сектора атаки, защищающийся —
    1d6 + 1 + модификатор своего сектора защиты (правила v3.5/ADR-014);
  * сектор выбирается равномерно из шести — усреднение вместо маневрирования;
  * разница сил уходит сначала в щит, затем в корпус;
  * дальность даёт атакующему бесплатный залп в начале боя со штрафом
    range_penalty * (max_range - 1) — грубая оценка преимущества дальнобоя;
  * способности кораблей НЕ моделируются (их вклад учтён в цене отдельно).

Запуск:  python3 tools/sim_v4_duel.py [--duels N] [--seed S]
Вывод:   reports/balance_v4_duel.md
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "data" / "rulesets" / "v4"


def load_ships() -> list[dict]:
    ships = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted((V4 / "ships").glob("*.json"))]
    return [s for s in ships if s["draftable"]]


def duel(a: dict, b: dict, rng: random.Random) -> int:
    """1 — победил a, -1 — победил b, 0 — ничья по лимиту раундов."""
    hp = {0: a["max_hp"], 1: b["max_hp"]}
    sh = {0: a["max_shield"], 1: b["max_shield"]}
    ships = {0: a, 1: b}
    turn = rng.randint(0, 1)

    # Бесплатный залп дальнобойного корабля до схождения вплотную.
    for i in (0, 1):
        extra = ships[i]["weapon"]["max_range"] - 1
        if extra > 0:
            pen = ships[i]["weapon"]["range_penalty_per_hex"] * extra
            att = rng.randint(1, 6) + rng.randint(1, 6) + rng.choice(ships[i]["arc_modifiers"]) - pen
            dfn = rng.randint(1, 6) + 1 + rng.choice(ships[1 - i]["arc_modifiers"])
            dmg = max(0, att - dfn)
            absorbed = min(sh[1 - i], dmg)
            sh[1 - i] -= absorbed
            hp[1 - i] -= dmg - absorbed

    for _ in range(200):
        if hp[0] <= 0 or hp[1] <= 0:
            break
        att_i, def_i = turn, 1 - turn
        att = rng.randint(1, 6) + rng.randint(1, 6) + rng.choice(ships[att_i]["arc_modifiers"])
        dfn = rng.randint(1, 6) + 1 + rng.choice(ships[def_i]["arc_modifiers"])
        dmg = max(0, att - dfn)
        absorbed = min(sh[def_i], dmg)
        sh[def_i] -= absorbed
        hp[def_i] -= dmg - absorbed
        turn = def_i

    if hp[0] <= 0 and hp[1] <= 0:
        return 0
    if hp[1] <= 0:
        return 1
    if hp[0] <= 0:
        return -1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duels", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260917)
    args = ap.parse_args()

    ships = load_ships()
    rng = random.Random(args.seed)
    wins = {s["id"]: 0 for s in ships}
    games = {s["id"]: 0 for s in ships}

    for i, a in enumerate(ships):
        for b in ships[i + 1:]:
            for _ in range(args.duels):
                res = duel(a, b, rng)
                games[a["id"]] += 1
                games[b["id"]] += 1
                if res > 0:
                    wins[a["id"]] += 1
                elif res < 0:
                    wins[b["id"]] += 1

    rows = []
    for s in ships:
        wr = wins[s["id"]] / games[s["id"]]
        rows.append((s["id"], s["display_name"], s["faction"], s["draft_cost"], wr))

    # Ожидаемый винрейт как функция цены: линейная регрессия winrate ~ cost.
    n = len(rows)
    mx = sum(r[3] for r in rows) / n
    my = sum(r[4] for r in rows) / n
    sxy = sum((r[3] - mx) * (r[4] - my) for r in rows)
    sxx = sum((r[3] - mx) ** 2 for r in rows)
    syy = sum((r[4] - my) ** 2 for r in rows)
    slope = sxy / sxx
    intercept = my - slope * mx
    corr = sxy / ((sxx * syy) ** 0.5)

    scored = []
    for sid, name, fac, cost, wr in rows:
        expected = intercept + slope * cost
        scored.append((sid, name, fac, cost, wr, wr - expected))
    scored.sort(key=lambda r: -r[5])

    out = [
        "# Дуэльный стенд — ruleset v4",
        "",
        f"- Сгенерировано: `tools/sim_v4_duel.py --duels {args.duels} --seed {args.seed}`",
        f"- Кораблей в драфте: {n}; дуэлей на пару: {args.duels}; "
        f"всего дуэлей: {n * (n - 1) // 2 * args.duels}",
        "- Модель: бой вплотную, сектор равновероятен, способности не "
        "моделируются (см. шапку скрипта).",
        "",
        "## Связь цены и силы",
        "",
        f"- Линейная подгонка: winrate ≈ {intercept:.3f} + {slope:.4f} · цена",
        f"- Корреляция Пирсона цена↔винрейт: **{corr:.3f}** "
        f"(1.0 — цена идеально предсказывает силу в этой модели)",
        "",
        "## Отклонение от цены (положительное = сильнее своей цены)",
        "",
        "| Корабль | Фракция | Цена | Винрейт | Δ к ожидаемому |",
        "|---|---|---:|---:|---:|",
    ]
    for sid, name, fac, cost, wr, delta in scored:
        out.append(f"| {name} | {fac} | {cost} | {wr * 100:.1f}% | {delta * 100:+.1f} pp |")
    out += [
        "",
        "## Как читать",
        "",
        "- |Δ| ≤ 5 pp — корабль в своей ценовой категории;",
        "- Δ > +8 pp — кандидат на удорожание (или на ослабление секторов);",
        "- Δ < −8 pp — корабль платит за то, чего в этой модели нет: "
        "способности, гипердрайв, ангар, ремонт. Это ожидаемо для support, "
        "transport и носителей — проверять их нужно матчевой симуляцией, "
        "а не дуэлью.",
        "",
    ]
    path = ROOT / "reports" / "balance_v4_duel.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"corr(cost, winrate) = {corr:.3f}; отчёт: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
