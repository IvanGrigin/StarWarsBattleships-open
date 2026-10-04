"""Полный прогон баланса v4: три эпохи параллельно → слияние → согласование общих карточек.

1. ЭПОХИ. Три процесса optimize --era … параллельно (по --workers каждый), каждый стартует
   со своего лучшего патча (patches/r1_<эпоха>_best.json, если есть). Карточки, играющие в
   нескольких эпохах, здесь заморожены (якорь 20): их двигает только шаг 3.
2. СЛИЯНИЕ. Числа карточек своей эпохи берутся из лучшего патча этой эпохи; общие карточки —
   среднее по эпохам (округлённое), цены героев — из их эпохи.
3. СОГЛАСОВАНИЕ. optimize --era mixed: эпоха случайная в каждой партии; общие карточки
   двигаются охотно (якорь 0.5), карточки одной эпохи почти заморожены (якорь 4).
Итог: patches/final.json и reports/balance_v4_ml_*.md. Партии копятся в data/ (--reuse).

Запуск (из tools/):  python3 -m sim_v4.full_run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .draft import ERAS, era_heroes
from .rules import SHIPS

HERE = Path(__file__).resolve().parent
PATCHES = HERE / "patches"
PREFIX = ["ml"]
TOOLS = HERE.parent


def run_eras(args, strategy):
    procs = []
    for e in ERAS:
        start = PATCHES / f"r1_{e}_best.json"
        cmd = [sys.executable, "-u", "-m", "sim_v4.optimize", "--era", e, "--rounds", str(args.rounds),
               "--data", str(args.data), "--validate", str(args.validate), "--lambdas", args.lambdas,
               "--levers", args.levers, "--workers", str(args.workers), "--anchor-shared", "20",
               "--strategy-from", strategy, "--reuse", "--tag", f"{args.prefix}_{e}",
               "--bot", args.bot, "--drafter", args.drafter]
        if start.exists() and not args.fresh:
            cmd += ["--start", str(start)]
        log = open(Path(args.logdir) / f"full_{e}.log", "w")
        procs.append((e, subprocess.Popen(cmd, cwd=TOOLS, stdout=log, stderr=subprocess.STDOUT)))
        print(f"эпоха {e}: запущена ({' '.join(cmd[3:])})", flush=True)
    for e, p in procs:
        p.wait()
        print(f"эпоха {e}: завершена, код {p.returncode}", flush=True)


def merge():
    per_era = {e: json.loads((PATCHES / f"{PREFIX[0]}_{e}_best.json").read_text(encoding="utf-8")) for e in ERAS}
    out = {"ships": {}, "heroes": {}}
    shared_ships = [s for s in SHIPS if SHIPS[s]["draftable"] and SHIPS[s]["era"] == "any"]
    for e, p in per_era.items():
        for s, d in p["ships"].items():
            if SHIPS[s]["era"] == e:
                out["ships"][s] = d
        for h, c in p["heroes"].items():
            if h in era_heroes(e) and sum(h in era_heroes(x) for x in ERAS) == 1:
                out["heroes"][h] = c
    for s in shared_ships:                      # общие корабли — среднее по эпохам
        keys = {k for p in per_era.values() for k in p["ships"].get(s, {})}
        d = {}
        for k in keys:
            v = round(sum(p["ships"].get(s, {}).get(k, 0) for p in per_era.values()) / len(ERAS))
            if v:
                d[k] = v
        if d:
            out["ships"][s] = d
    multi = {h for e in ERAS for h in era_heroes(e) if sum(h in era_heroes(x) for x in ERAS) > 1}
    for h in multi:                             # герои нескольких эпох — среднее цены
        vals = [p["heroes"].get(h) for e, p in per_era.items() if h in era_heroes(e)]
        vals = [v for v in vals if v is not None]
        if vals:
            out["heroes"][h] = round(sum(vals) / len(vals))
    (PATCHES / "merged.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"слияние: {sum(len(d) for d in out['ships'].values())} чисел кораблей, {len(out['heroes'])} цен героев",
          flush=True)


def run_mixed(args, strategy):
    cmd = [sys.executable, "-u", "-m", "sim_v4.optimize", "--era", "mixed", "--rounds", str(args.mixed_rounds),
           "--data", str(args.mixed_data), "--validate", str(args.mixed_validate), "--lambdas", args.lambdas,
           "--levers", args.levers, "--workers", str(args.workers * 3), "--anchor-old", "4", "--anchor-shared", "0.5",
           "--strategy-from", strategy, "--start", str(PATCHES / "merged.json"), "--reuse", "--tag", f"{args.prefix}_mixed",
           "--bot", args.bot, "--drafter", args.drafter]
    with open(Path(args.logdir) / "full_mixed.log", "w") as log:
        subprocess.run(cmd, cwd=TOOLS, stdout=log, stderr=subprocess.STDOUT, check=False)
    best = PATCHES / f"{args.prefix}_mixed_best.json"
    if best.exists():
        (PATCHES / "final.json").write_text(best.read_text(encoding="utf-8"), encoding="utf-8")
        print("итог: patches/final.json", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--data", type=int, default=200000)
    ap.add_argument("--validate", type=int, default=20000)
    ap.add_argument("--lambdas", default="0.003,0.01,0.03")
    ap.add_argument("--levers", default="цены+сектора,всё")
    ap.add_argument("--workers", type=int, default=3, help="на одну эпоху; согласование — втрое больше")
    ap.add_argument("--mixed-rounds", type=int, default=2)
    ap.add_argument("--mixed-data", type=int, default=300000)
    ap.add_argument("--mixed-validate", type=int, default=30000)
    ap.add_argument("--strategy-from", required=True)
    ap.add_argument("--logdir", default=".")
    ap.add_argument("--skip-eras", action="store_true")
    ap.add_argument("--prefix", default="ml", help="тег прогона (патчи и данные)")
    ap.add_argument("--bot", default="tactical", choices=["tactical", "adaptive"])
    ap.add_argument("--drafter", default="random", choices=["random", "greedy"])
    ap.add_argument("--fresh", action="store_true", help="начать с карточек, а не с прошлых патчей")
    args = ap.parse_args()
    PREFIX[0] = args.prefix
    t0 = time.time()
    if not args.skip_eras:
        run_eras(args, args.strategy_from)
    merge()
    run_mixed(args, args.strategy_from)
    print(f"готово за {(time.time() - t0) / 60:.0f} мин", flush=True)


if __name__ == "__main__":
    main()
