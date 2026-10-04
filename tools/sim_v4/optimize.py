"""Баланс v4 как задача машинного обучения: суррогатная модель + перебор гиперпараметров.

Что можно менять (решение владельца): у кораблей — сектора (F, борта FR+FL парой, корма-борта
BR+BL парой, B), корпус, щит и цену; у героев — только цену в драфте (общий бюджет 26 на героя
и корабли, базовая цена героя 2). Способности героев — как на карточках.

Раунд оптимизации:
  1. ДАННЫЕ. N партий; в каждой числа всех карточек случайно сдвинуты от центра (сначала —
     карточки как есть). Герои — случайная пара, корабли — случайный законный драфт из общего
     каталога, бой — TacticalBot с подобранными порогами способностей.
  2. МОДЕЛЬ. Логистическая регрессия: logit P(A победит) = Σ по карточкам A − Σ по карточкам B
     (сила карточки + чувствительность к каждому её числу · сдвиг) + преимущество первого хода.
     Регуляризация C подбирается по отложенной выборке (log-loss).
  3. ПЕРЕБОР ГИПЕРПАРАМЕТРОВ. Для каждого λ (штраф за изменение числа) и набора рычагов
     («цены», «цены+сектора», «всё») для каждой карточки перебираются все целые сдвиги в
     границах и выбирается тот, что приближает её силу к общей норме с наименьшим штрафом
     λ·якорь·|сдвиг|. Якорь — вес карточки: большой — её числа почти не трогаются.
  4. ПРОВЕРКА. Каждый кандидат играет честные партии без сдвигов; метрика — среднеквадратичное
     отклонение процента побед героев и кораблей от 50%. Лучший — центр следующего раунда.

Новые герои: `--new hero_id ...` — эти герои чаще попадают в партии (точнее оценка), а
`--anchor-new` / `--anchor-old` задают, чьи числа двигать ради баланса: новых карточек
(старые защищены) или старых (новая карточка печатается как задумана).

Запуск (из tools/):
  python3 -m sim_v4.optimize --rounds 2 --data 400000 --validate 25000 --workers 6
  python3 -m sim_v4.optimize --new rey --anchor-new 0.2 --anchor-old 3   # новый герой подстраивается сам
Вывод: reports/balance_v4_ml.md, tools/sim_v4/patches/*.json (best.json — лучший патч).
"""

from __future__ import annotations

import argparse
import gzip
import itertools
import pickle
import json
import math
import random
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from . import tune
from .bots import TacticalBot, play_match
from .draft import (BASE_ARCS, BASE_COST, CATALOG_HEROES, CATALOG_SHIPS, COST, ERAS, HERO_POOL, RandomDrafter,
                    era_heroes, in_era, run_draft)
from .rules import HEROES, SHIPS

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PATCHES = HERE / "patches"
OUT = ROOT / "reports" / "balance_v4_ml.md"

SHIP_IDS = list(CATALOG_SHIPS)
HERO_IDS = list(CATALOG_HEROES)
S, H = len(SHIP_IDS), len(HERO_IDS)
SI = {s: i for i, s in enumerate(SHIP_IDS)}
HI = {h: i for i, h in enumerate(HERO_IDS)}

PARAMS = ["F", "sides", "rear", "B", "hp", "shield", "cost"]
NP = len(PARAMS)
UNIT = {"F": (0,), "sides": (1, 5), "rear": (2, 4), "B": (3,)}
BOUNDS = {"F": (-2, 2), "sides": (-2, 2), "rear": (-2, 2), "B": (-2, 2), "hp": (-2, 2), "shield": (-1, 1),
          "cost": (-3, 3)}
LEVERS = {"цены": ["cost"], "цены+сектора": ["cost", "F", "sides", "rear", "B"], "всё": PARAMS}
BASE_HP = {s: SHIPS[s]["max_hp"] for s in SHIPS}
BASE_SH = {s: SHIPS[s]["max_shield"] for s in SHIPS}
HCOST = (0, tune.MAX_HERO_COST)

# столбцы признаков
C_SHIP = 0
C_SPAR = S
C_HERO = S + S * NP
C_HCOST = C_HERO + H
C_FIRST = C_HCOST + H
NCOL = C_FIRST + 1


# ---------------------------------------------------------------- патч: числа карточек
def empty_patch():
    return {"ships": {}, "heroes": {}}


def ship_numbers(sid, d):
    """Числа корабля при сдвигах d (словарь параметр → целое) с ограничениями правил."""
    arcs = list(BASE_ARCS[sid])
    for p, idx in UNIT.items():
        for i in idx:
            arcs[i] = arcs[i] + d.get(p, 0)
    return {
        "arcs": arcs,
        "hp": BASE_HP[sid] + d.get("hp", 0),
        "shield": BASE_SH[sid] + d.get("shield", 0),
        "cost": BASE_COST[sid] + d.get("cost", 0),
    }


def valid_ship(sid, d):
    n = ship_numbers(sid, d)
    return all(-1 <= a <= 4 for a in n["arcs"]) and n["hp"] >= 1 and n["shield"] >= 0 and n["cost"] >= 2


def clamp_ship(sid, d):
    """Сдвиги в границах BOUNDS и правил; параметр, выводящий за правила, откатывается к ближайшему."""
    d = {p: max(BOUNDS[p][0], min(BOUNDS[p][1], v)) for p, v in d.items() if v}
    for p in list(d):
        while d.get(p) and not valid_ship(sid, d):
            d[p] -= 1 if d[p] > 0 else -1
        if not d.get(p):
            d.pop(p, None)
    return d


def apply_patch(patch):
    """Выставить числа всех карточек (SHIPS, цены героев, таблицы драфта)."""
    for s in SHIP_IDS:
        n = ship_numbers(s, patch["ships"].get(s, {}))
        d = SHIPS[s]
        d["arc_modifiers"], d["max_hp"], d["max_shield"], d["draft_cost"] = n["arcs"], n["hp"], n["shield"], n["cost"]
        COST[s] = n["cost"]
    for h in HERO_POOL:
        HERO_POOL[h].sort(key=lambda x: COST[x])
    tune.set_hero_costs(dict(patch["heroes"]))


def hero_cost_of(patch, h):
    return patch["heroes"].get(h, tune.DATASET_HERO_COST.get(h, tune.BASE_HERO_COST))


# ---------------------------------------------------------------- партии
_STRAT = {}
_ERA = {"era": None, "heroes": list(CATALOG_HEROES)}
_CFG = {"bot": "tactical", "drafter": "random"}


def _init(strat, era=None, bot="tactical", drafter="random"):
    _STRAT.update(strat)
    _CFG["bot"], _CFG["drafter"] = bot, drafter
    tune.set_levels(None)                       # способности — карточки как есть
    _ERA["era"] = era
    _ERA["pools"] = {e: era_heroes(e) for e in ERAS}
    _ERA["heroes"] = era_heroes(era) if era in ERAS else list(CATALOG_HEROES)


def _jitter(rng, center, p):
    """Случайный сдвиг вокруг центра: каждый параметр с вероятностью p — на ±1 (цена ±1..2)."""
    ships = {}
    for s in SHIP_IDS:
        d = dict(center["ships"].get(s, {}))
        for par in PARAMS:
            if rng.random() < p:
                step = rng.choice((-2, -1, 1, 2)) if par == "cost" else rng.choice((-1, 1))
                d[par] = d.get(par, 0) + step
        d = clamp_ship(s, d)
        if d:
            ships[s] = d
    heroes = {}
    for h in HERO_IDS:
        c = hero_cost_of(center, h)
        if rng.random() < max(p, 0.5):
            c += rng.choice((-2, -1, 1, 2))
        heroes[h] = max(HCOST[0], min(HCOST[1], c))
    return {"ships": ships, "heroes": heroes}


def _game(args):
    seed, center, jitter_p, focus = args
    rng = random.Random(seed)
    patch = _jitter(rng, center, jitter_p) if jitter_p else center
    apply_patch(patch)
    era = _ERA["era"]
    if era == "mixed":                          # согласование: эпоха партии — случайная
        era = rng.choice(ERAS)
    pool = _ERA["pools"][era] if era in ERAS else _ERA["heroes"]
    focus = [h for h in focus if h in pool]
    if focus and rng.random() < 0.5:            # новые герои — чаще в партиях
        a = rng.choice(focus)
        heroes = [a, rng.choice([h for h in pool if h != a])]
        rng.shuffle(heroes)
    else:
        heroes = rng.sample(pool, 2)
    from .draft import GreedyDrafter
    D = GreedyDrafter if _CFG["drafter"] == "greedy" else RandomDrafter
    st = run_draft([D(seed), D(seed + 1)], seed, heroes=heroes, era=era)
    if st is None:
        return None
    if _CFG["bot"] == "adaptive":
        from .arena import AdaptiveBot, load_adaptive
        w = load_adaptive().get("duel")
        bots = [AdaptiveBot(seed + i, strat={heroes[i]: _STRAT.get(heroes[i], 0.6)}, w=w) for i in (0, 1)]
    else:
        bots = [TacticalBot(seed + i, strat={heroes[i]: _STRAT.get(heroes[i], 0.6)}) for i in (0, 1)]
    first = seed % 2                                          # кто ходит первым в раунде 1
    if first:
        w, _, _ = play_match(heroes[::-1], st.ships[::-1], bots[::-1], seed=seed)
        w = None if w is None else 1 - w
    else:
        w, _, _ = play_match(heroes, st.ships, bots, seed=seed)
    if w is None:
        return None
    sides = []
    for k in (0, 1):
        ships = [(s, patch["ships"].get(s, {})) for s in st.ships[k]]
        sides.append((heroes[k], hero_cost_of(patch, heroes[k]), ships))
    return sides, w, first


def play(pool, n, seed0, center, jitter_p=0.0, focus=None):
    args = [(seed0 + i, center, jitter_p, focus or []) for i in range(n)]
    return [r for r in pool.imap_unordered(_game, args, chunksize=48) if r]


# ---------------------------------------------------------------- модель
def design(games):
    rows, cols, vals, y = [], [], [], []
    for r, (sides, w, first) in enumerate(games):
        for k, sign in ((0, 1.0), (1, -1.0)):
            hero, hcost, ships = sides[k]
            rows += [r, r]; cols += [C_HERO + HI[hero], C_HCOST + HI[hero]]
            vals += [sign, sign * (hcost - tune.BASE_HERO_COST)]
            for s, d in ships:
                i = SI[s]
                rows.append(r); cols.append(C_SHIP + i); vals.append(sign)
                for j, par in enumerate(PARAMS):
                    if d.get(par):
                        rows.append(r); cols.append(C_SPAR + i * NP + j); vals.append(sign * d[par])
        rows.append(r); cols.append(C_FIRST); vals.append(1.0 if first == 0 else -1.0)
        y.append(1 if w == 0 else 0)
    X = sparse.csr_matrix((vals, (rows, cols)), shape=(len(games), NCOL))
    return X, np.array(y)


def fit(games, cs=(0.03, 0.3, 3.0)):
    """Логистическая регрессия; C — по отложенной выборке (20%). Возвращает (веса, C, таблицу C→log-loss)."""
    X, y = design(games)
    idx = np.random.RandomState(0).permutation(len(y))
    cut = int(len(y) * 0.8)
    tr, va = idx[:cut], idx[cut:]
    scores = {}
    for c in cs:
        m = LogisticRegression(C=c, fit_intercept=False, max_iter=3000)
        m.fit(X[tr], y[tr])
        p = np.clip(m.predict_proba(X[va])[:, 1], 1e-6, 1 - 1e-6)
        scores[c] = float(-np.mean(y[va] * np.log(p) + (1 - y[va]) * np.log(1 - p)))
    best = min(scores, key=scores.get)
    m = LogisticRegression(C=best, fit_intercept=False, max_iter=3000)
    m.fit(X, y)
    return m.coef_[0], best, scores


def strengths(w, patch):
    """Сила каждой карточки (в логитах) при данном патче — по модели."""
    ship = {}
    for s in SHIP_IDS:
        i = SI[s]
        d = patch["ships"].get(s, {})
        ship[s] = w[C_SHIP + i] + sum(w[C_SPAR + i * NP + j] * d.get(p, 0) for j, p in enumerate(PARAMS))
    hero = {h: w[C_HERO + HI[h]] + w[C_HCOST + HI[h]] * (hero_cost_of(patch, h) - tune.BASE_HERO_COST)
            for h in HERO_IDS}
    return ship, hero


# ---------------------------------------------------------------- оптимизация по модели
def _grid(levers):
    ranges = [range(BOUNDS[p][0], BOUNDS[p][1] + 1) if p in levers else range(0, 1) for p in PARAMS]
    return np.array(list(itertools.product(*ranges)), dtype=np.int8)


GRIDS = {}


def optimize(w, center, lam, levers, anchor, counts, ships=None, heroes=None):
    """Новый патч: для каждой карточки — целые сдвиги, приближающие силу к норме (медиана,
    взвешенная по частоте карточки) со штрафом λ·якорь·Σ|сдвиг| (сдвиг — от карточки)."""
    grid = GRIDS.setdefault(levers, _grid(LEVERS[levers]))
    ship0, hero0 = strengths(w, empty_patch())
    ships = ships or SHIP_IDS
    heroes = heroes or HERO_IDS
    ws = np.array([counts.get(s, 1) for s in ships], dtype=float)
    base_ship = np.array([ship0[s] for s in ships])
    order = np.argsort(base_ship)
    cum = np.cumsum(ws[order])
    t_ship = base_ship[order][np.searchsorted(cum, cum[-1] / 2)]
    hb = np.array([hero0[h] for h in heroes])
    t_hero = float(np.median(hb))
    out = {"ships": {k: v for k, v in center["ships"].items() if k not in ships},
           "heroes": {k: v for k, v in center["heroes"].items() if k not in heroes}}
    for s in ships:
        i = SI[s]
        g = np.array([w[C_SPAR + i * NP + j] for j in range(NP)])
        pred = w[C_SHIP + i] + grid @ g
        loss = (pred - t_ship) ** 2 + lam * anchor.get(s, 1.0) * np.abs(grid).sum(axis=1)
        ok = np.array([valid_ship(s, dict(zip(PARAMS, map(int, row)))) for row in grid]) \
            if len(grid) < 2000 else _valid_mask(s, grid)
        loss[~ok] = np.inf
        best = grid[int(np.argmin(loss))]
        d = {p: int(v) for p, v in zip(PARAMS, best) if v}
        if d:
            out["ships"][s] = d
    for h in heroes:
        a, b = w[C_HERO + HI[h]], w[C_HCOST + HI[h]]
        best = min(range(HCOST[0], HCOST[1] + 1),
                   key=lambda c: (a + b * (c - tune.BASE_HERO_COST) - t_hero) ** 2
                   + lam * anchor.get(h, 1.0) * abs(c - tune.BASE_HERO_COST))
        if best != tune.BASE_HERO_COST:
            out["heroes"][h] = best
    return out


def _valid_mask(sid, grid):
    arcs0 = np.array(BASE_ARCS[sid])
    arcs = np.tile(arcs0, (len(grid), 1))
    for j, (p, idx) in enumerate(UNIT.items()):
        for i in idx:
            arcs[:, i] += grid[:, PARAMS.index(p)]
    ok = (arcs >= -1).all(axis=1) & (arcs <= 4).all(axis=1)
    ok &= BASE_HP[sid] + grid[:, PARAMS.index("hp")] >= 1
    ok &= BASE_SH[sid] + grid[:, PARAMS.index("shield")] >= 0
    ok &= BASE_COST[sid] + grid[:, PARAMS.index("cost")] >= 2
    return ok


def changes(patch):
    return sum(len(d) for d in patch["ships"].values()) + len(patch["heroes"])


# ---------------------------------------------------------------- проверка
def measure(games):
    hero, ship = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    first = [0, 0]
    for sides, w, fm in games:
        first[0] += w == fm; first[1] += 1
        for k in (0, 1):
            won = int(w == k)
            h = sides[k][0]
            hero[h][0] += won; hero[h][1] += 1
            for s, _ in sides[k][2]:
                ship[s][0] += won; ship[s][1] += 1
    hwr = {h: v[0] / v[1] for h, v in hero.items() if v[1]}
    need = max(20, min(300, len(games) // 60))
    swr = {s: v[0] / v[1] for s, v in ship.items() if v[1] >= need}
    rms = lambda d: math.sqrt(sum((x - 0.5) ** 2 for x in d.values()) / max(1, len(d)))
    return {"hero_rms": rms(hwr), "ship_rms": rms(swr), "hero_max": max((abs(x - .5) for x in hwr.values()), default=0),
            "ship_max": max((abs(x - .5) for x in swr.values()), default=0), "first": first[0] / max(1, first[1]),
            "hero": hwr, "ship": swr, "counts": {s: v[1] for s, v in ship.items()}}


def score(m):
    return m["hero_rms"] + m["ship_rms"]


# ---------------------------------------------------------------- конвейер
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--data", type=int, default=400000, help="партий со сдвигами на раунд")
    ap.add_argument("--validate", type=int, default=25000, help="честных партий на кандидата")
    ap.add_argument("--jitter", type=float, default=0.3)
    ap.add_argument("--lambdas", default="0.001,0.004,0.015,0.05")
    ap.add_argument("--levers", default="цены,цены+сектора,всё")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--strategy-from", default=str(HERE / "tuning.json"))
    ap.add_argument("--start", default=None, help="начать с патча (JSON)")
    ap.add_argument("--new", nargs="*", default=[], help="новые герои/корабли")
    ap.add_argument("--anchor-new", type=float, default=1.0, help="якорь новых карточек (меньше — двигаются охотнее)")
    ap.add_argument("--anchor-old", type=float, default=1.0, help="якорь старых карточек")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--era", default=None, choices=ERAS + ["mixed"],
                    help="эпоха партии: драфт только внутри неё; mixed — эпоха случайная в каждой партии")
    ap.add_argument("--reuse", action="store_true", help="дообучаться и на партиях прошлых запусков с тем же тегом")
    ap.add_argument("--bot", default="tactical", choices=["tactical", "adaptive"], help="бот обеих сторон")
    ap.add_argument("--drafter", default="random", choices=["random", "greedy"],
                    help="драфт кораблей: случайный или «как у человека» (тратит бюджет)")
    ap.add_argument("--anchor-shared", type=float, default=5.0,
                    help="якорь карточек, играющих в нескольких эпохах (их числа почти не трогаются)")
    args = ap.parse_args()
    args.tag = args.tag or ("ml_" + args.era if args.era else "ml")
    global OUT
    if args.era:
        OUT = ROOT / "reports" / f"balance_v4_ml_{args.era}.md"
    mixed = args.era == "mixed"
    era_ships = [s for s in SHIP_IDS if mixed or in_era(SHIPS[s]["era"], args.era)]
    era_hero_list = sorted({h for e in ERAS for h in era_heroes(e)}) if mixed else \
        (era_heroes(args.era) if args.era else HERO_IDS)
    shared = set()
    if mixed:
        shared = {s for s in era_ships if SHIPS[s]["era"] == "any"}
        shared |= {h for h in era_hero_list if sum(h in era_heroes(e) for e in ERAS) > 1}
    elif args.era:
        shared = {s for s in era_ships if SHIPS[s]["era"] == "any"}
        shared |= {h for h in era_hero_list if sum(h in era_heroes(e) for e in ERAS) > 1}

    strat = json.loads(Path(args.strategy_from).read_text(encoding="utf-8")).get("strategy", {})
    lambdas = [float(x) for x in args.lambdas.split(",")]
    levers = args.levers.split(",")
    anchor = {e: args.anchor_old for e in SHIP_IDS + HERO_IDS}
    anchor.update({e: args.anchor_shared for e in shared})
    anchor.update({e: args.anchor_new for e in args.new})
    focus = [h for h in args.new if h in HI]
    PATCHES.mkdir(exist_ok=True)
    center = json.loads(Path(args.start).read_text(encoding="utf-8")) if args.start else empty_patch()
    log = []
    t0 = time.time()
    data_file = HERE / "data" / f"{args.tag}.pkl.gz"
    all_games = []
    if args.reuse and data_file.exists():
        with gzip.open(data_file, "rb") as f:
            all_games = pickle.load(f)
        print(f"накоплено партий из прошлых запусков: {len(all_games)}", flush=True)
    seed_base = (int(time.time()) % 100_000) * 10_000_000         # новые партии — новые сиды
    with Pool(args.workers, initializer=_init, initargs=(strat, args.era, args.bot, args.drafter)) as pool:
        base = measure(play(pool, args.validate, 90_000_000, center))
        log.append(("центр раунда 0 (карточки как есть)" if not args.start else "стартовый патч", center, base, None))
        print(f"[{(time.time() - t0) / 60:.0f} мин] старт: герои {base['hero_rms']:.1%}, корабли {base['ship_rms']:.1%}, "
              f"первый ход {base['first']:.1%}", flush=True)
        best_patch, best_m = center, base
        for rnd in range(args.rounds):
            games = play(pool, args.data, seed_base + rnd * 1_000_000, best_patch, args.jitter, focus)
            all_games += games
            data_file.parent.mkdir(exist_ok=True)
            with gzip.open(data_file, "wb") as f:
                pickle.dump(all_games, f)
            w, c, cscores = fit(all_games)
            print(f"[{(time.time() - t0) / 60:.0f} мин] раунд {rnd + 1}: {len(all_games)} партий, модель C={c} "
                  f"(log-loss {cscores[c]:.4f}); первый ход в модели {w[C_FIRST]:+.3f}", flush=True)
            counts = best_m["counts"]
            cands = []
            for lev in levers:
                for lam in lambdas:
                    p = optimize(w, best_patch, lam, lev, anchor, counts, era_ships, era_hero_list)
                    key = json.dumps(p, sort_keys=True)
                    if any(key == json.dumps(q, sort_keys=True) for _, _, q in cands):
                        continue
                    cands.append((lev, lam, p))
            for k, (lev, lam, p) in enumerate(cands):
                m = measure(play(pool, args.validate, seed_base + 500_000_000 + rnd * 1_000_000 + k * 50_000, p))
                name = f"r{rnd + 1}_{lev}_{lam}"
                (PATCHES / f"{args.tag}_{name}.json").write_text(json.dumps(p, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
                log.append((f"раунд {rnd + 1}: {lev}, λ={lam}", p, m, (rnd + 1, lev, lam, c)))
                print(f"[{(time.time() - t0) / 60:.0f} мин]   {lev:13s} λ={lam:<6} изменений {changes(p):3d}: "
                      f"герои {m['hero_rms']:.1%} (макс {m['hero_max']:.1%}), корабли {m['ship_rms']:.1%} "
                      f"(макс {m['ship_max']:.1%})", flush=True)
                if score(m) < score(best_m):
                    best_patch, best_m = p, m
            (PATCHES / f"{args.tag}_best.json").write_text(json.dumps(best_patch, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
    report(args, log, best_patch, best_m, base, time.time() - t0)


def report(args, log, best, bm, base, took):
    hn = lambda h: HEROES[h]["display_name"]
    sn = lambda s: SHIPS[s]["display_name"]
    era_name = {"fall_of_republic": "Падение Республики", "galactic_civil_war": "Галактическая гражданская война",
                "new_order": "Новый порядок"}.get(args.era, "все эпохи вместе")
    L = [f"# Баланс v4: ML-оптимизация чисел карточек — {era_name}", "",
         f"- Сгенерировано: `python3 -m sim_v4.optimize{' --era ' + args.era if args.era else ''} --rounds {args.rounds} "
         f"--data {args.data} --validate {args.validate}` (из `tools/`), {took / 60:.0f} мин.",
         "- Эпоха партии выбирается до драфта: обе стороны берут карточки только этой эпохи или «вне эпохи». "
         "Карточки, играющие в нескольких эпохах, почти не меняются (якорь 5), чтобы прогоны эпох не тянули "
         "их в разные стороны." if args.era else "- Эпоха партии не выбирается.",
         f"- Бот обеих сторон: `{args.bot}`, драфт кораблей: `{args.drafter}`.",
         "- Меняются только числа: у кораблей — сектора (борта парой), корпус, щит, цена; у героев — цена "
         f"в драфте (общий бюджет {tune.BUDGET_TOTAL}, базовая цена героя {tune.BASE_HERO_COST}). "
         "Способности — как на карточках.",
         "- Модель: логистическая регрессия исхода партии по силе карточек и сдвигам их чисел; данные — "
         "партии со случайными сдвигами; гиперпараметры: C модели (по отложенной выборке), штраф λ за "
         "изменение числа и набор рычагов. Каждый кандидат проверен честными партиями.",
         "- Метрика — среднеквадратичное отклонение процента побед от 50% (герои и корабли). Это "
         "**предложения**, датасет не менялся.", "",
         f"**Итог:** герои {base['hero_rms']:.1%} → {bm['hero_rms']:.1%} (худший {base['hero_max']:.1%} → "
         f"{bm['hero_max']:.1%}), корабли {base['ship_rms']:.1%} → {bm['ship_rms']:.1%} (худший "
         f"{base['ship_max']:.1%} → {bm['ship_max']:.1%}); изменено чисел: {changes(best)}. "
         f"Первый ход: {bm['first']:.1%} побед.", "",
         "## Все кандидаты", "", "| Кандидат | Изменений | Герои (СКО) | Худший герой | Корабли (СКО) | Худший корабль |",
         "|---|---:|---:|---:|---:|---:|"]
    for name, p, m, _ in log:
        L.append(f"| {name} | {changes(p)} | {m['hero_rms']:.1%} | {m['hero_max']:.1%} | {m['ship_rms']:.1%} | "
                 f"{m['ship_max']:.1%} |")
    L += ["", "## Лучший патч: цены героев", "", "| Герой | Цена | Кораблям остаётся | Побед было | Стало |",
          "|---|---:|---:|---:|---:|"]
    for h in sorted([x for x in HERO_IDS if x in base["hero"]], key=lambda x: -hero_cost_of(best, x)):
        c = hero_cost_of(best, h)
        L.append(f"| {hn(h)} | {c} | {tune.BUDGET_TOTAL - c} | {base['hero'].get(h, 0):.1%} | {bm['hero'].get(h, 0):.1%} |")
    L += ["", "## Лучший патч: корабли", "",
          "| Корабль | Сектора F FR BR B BL FL | Корпус | Щит | Цена | Побед было | Стало |", "|---|---|---|---|---|---:|---:|"]
    fmt = lambda a: " ".join(f"{v:+d}" if v else "0" for v in a)
    for s in sorted([x for x in best["ships"] if x in base["ship"] or x in bm["ship"]], key=sn):
        n0, n1 = ship_numbers(s, {}), ship_numbers(s, best["ships"][s])
        ch = lambda a, b: f"{a} → **{b}**" if a != b else f"{a}"
        L.append(f"| {sn(s)} | {ch(fmt(n0['arcs']), fmt(n1['arcs']))} | {ch(n0['hp'], n1['hp'])} | "
                 f"{ch(n0['shield'], n1['shield'])} | {ch(n0['cost'], n1['cost'])} | {base['ship'].get(s, 0):.1%} | "
                 f"{bm['ship'].get(s, 0):.1%} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"OK: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
