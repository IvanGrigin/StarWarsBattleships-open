"""Запись партии ботов по ходам и поиск «хорошей» партии для просмотра.

Играет N партий «умный против умного» (драфт — ValueDrafter с обеих сторон,
бой — TacticalBot против NeuralBot), записывает каждое действие со
состоянием поля и событиями (кубики, урон, способности героев), затем
выбирает партию длинную, равную и с победой одной стороны:
  оценка = атаки × (1 + смены лидера) × (1 − 2·среднее отклонение доли сил от 50%),
  со штрафом за долгие паузы без выстрелов; не короче 6 раундов.

Запуск (из tools/):  python3 -m sim_v4.replay --games 300 --out replay.json
"""

from __future__ import annotations

import argparse
import json
import random

import numpy as np

from .bots import TacticalBot, worth
from .draft import run_draft
from .draft_ai import RosterNet, ValueDrafter
from .nn import WEIGHTS, NeuralBot, ValueNet
from .rules import HEROES, SHIPS, V4, Match

VIEWER = __import__("pathlib").Path(__file__).resolve().parent / "replay_viewer.html"
ABIL = {a["id"]: a for a in json.loads((V4 / "ship_abilities.json").read_text(encoding="utf-8"))["abilities"]}


def state(m: Match):
    return {
        "round": m.round,
        "turn": m.turn_seat,
        "active": None if m.active is None else m.active.uid,
        "ships": [[s.q, s.r, s.facing, s.hp, s.shield, s.charges, int(s.alive), s.type, s.max_hp, s.max_shield]
                  for s in m.ships],
        "mines": [list(x["pos"]) for x in m.mines],
        "bombs": [list(b["pos"]) + [b["dir"]] for b in m.bombs],
    }


def share(m: Match):
    w = [sum(worth(s) for s in m.ships if s.seat == k) for k in (0, 1)]
    return w[0] / max(1e-9, w[0] + w[1])


def record(heroes, fleets, bots, seed):
    m = Match(heroes, fleets, seed=seed)
    m.events = []
    frames = [dict(state(m), act=["start"], seat=None, ev=[], share=share(m))]
    raw_apply = m.apply

    def apply(act):
        if m.probing:
            return raw_apply(act)
        seat = m.turn_seat
        m.events.clear()
        raw_apply(act)
        frames.append(dict(state(m), act=list(act), seat=seat, ev=list(m.events), share=share(m)))
    m.apply = apply
    guard = 0
    while not m.done and guard < 5000:
        bots[m.turn_seat].play_turn(m)
        guard += 1
    return m, frames


def quality(m, frames):
    if m.winner is None:
        return 0.0, 0, 0.0
    sh = [f["share"] for f in frames]
    cut = sh[: max(1, int(len(sh) * 0.8))]
    dev = sum(abs(x - 0.5) for x in cut) / len(cut)
    lead, changes = 0, 0
    for x in sh:
        cur = 1 if x > 0.53 else (-1 if x < 0.47 else 0)
        if cur and lead and cur != lead:
            changes += 1
        if cur:
            lead = cur
    attacks = sum(1 for f in frames if f["act"][0] == "attack" or f["act"][0] == "hero")
    idle = longest = 0
    for f in frames:                                   # самая длинная пауза без выстрелов (в активациях)
        if f["act"][0] in ("attack", "hero"):
            idle = 0
        elif f["act"][0] == "activate":
            idle += 1
            longest = max(longest, idle)
    if m.round < 6:
        return 0.0, changes, dev
    return min(attacks, 40) * (1 + changes) * max(0.0, 1 - 2 * dev) / (1 + max(0, longest - 6) / 6), changes, dev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--seed", type=int, default=777000)
    ap.add_argument("--out", default="replay.json")
    ap.add_argument("--only", type=int, default=None, help="сыграть только партию с этим сидом")
    ap.add_argument("--notes", default=None, help="JSON с разбором: {кадр начала активации: текст}")
    ap.add_argument("--html", default=None, help="собрать просмотрщик партии (replay_viewer.html + данные)")
    args = ap.parse_args()
    net = RosterNet.load()
    vnet = ValueNet.load(WEIGHTS)
    best = None
    seeds = [args.only] if args.only is not None else [args.seed + i for i in range(args.games)]
    for seed in seeds:
        picks = []
        drafters = [ValueDrafter(seed, net, temperature=0.05), ValueDrafter(seed + 1, net, temperature=0.05)]
        for k, d in enumerate(drafters):
            d.pick = (lambda st_, orig=d.pick, k=k: (lambda p: (picks.append([k, p[0], p[1]]), p)[1])(orig(st_)))
        st = run_draft(drafters, seed)
        if st is None:
            continue
        kinds = [TacticalBot(seed), NeuralBot(seed + 1, vnet)]
        if seed % 2:
            kinds = kinds[::-1]
        m, frames = record(st.heroes, st.ships, kinds, seed)
        q, ch, dev = quality(m, frames)
        if best is None or q > best[0]:
            best = (q, seed, st, m, frames, [k.name for k in kinds], ch, dev, picks)
            print(f"партия {seed}: раундов {m.round}, смен лидера {ch}, отклонение {dev:.2f}, оценка {q:.1f}",
                  flush=True)
    q, seed, st, m, frames, names, ch, dev, picks = best
    used_ships = sorted({s for side in st.ships for s in side} | {f["ships"][k][7] for f in frames
                                                                  for k in range(len(f["ships"]))})
    out = {
        "seed": seed, "bots": names, "winner": m.winner, "rounds": m.round - 1 if m.done else m.round,
        "lead_changes": ch, "heroes": st.heroes, "fleets": st.ships,
        "hero_info": {h: {"name": HEROES[h]["display_name"], "faction": HEROES[h]["faction"],
                          "ability": HEROES[h]["ability"], "synergy": HEROES[h]["synergy"]} for h in st.heroes},
        "ship_info": {s: {k: SHIPS[s][k] for k in ("display_name", "faction", "role", "draft_cost", "arc_modifiers",
                                                  "weapon", "engine", "max_charges", "max_hp", "max_shield",
                                                  "initial_charges", "hyperdrive", "unique", "era", "description")}
                      | {"abilities": [ABIL.get(a["id"], {"display_name": a["id"], "text": ""})["display_name"]
                                       for a in SHIPS[s]["abilities"]],
                         "ability_text": [[ABIL.get(a["id"], {}).get("display_name", a["id"]),
                                           ABIL.get(a["id"], {}).get("text", "")] for a in SHIPS[s]["abilities"]]}
                      for s in used_ships},
        "draft_order": picks,
        "factions": {f["id"]: {"short": f.get("short"), "display_name": f["display_name"], "trait": f.get("trait")}
                     for f in json.loads((V4 / "factions.json").read_text(encoding="utf-8"))["factions"]},
        "frames": frames,
        "notes": json.loads(open(args.notes, encoding="utf-8").read()) if args.notes else {},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), default=lambda o: o.tolist()
                  if isinstance(o, np.ndarray) else int(o))
    if args.html:
        page = VIEWER.read_text(encoding="utf-8")
        data = json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=int).replace("</", "<\\/")
        page = page.replace("__TITLE__", f"{HEROES[st.heroes[0]]['display_name']} — "
                                         f"{HEROES[st.heroes[1]]['display_name']}")
        page = page.replace("/*REPLAY*/null", data)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"OK: {args.html}")
    print(f"OK: {args.out} — партия {seed}, кадров {len(frames)}, победил {names[m.winner]} "
          f"(сторона {'AB'[m.winner]})")


if __name__ == "__main__":
    main()
