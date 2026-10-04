"""Нейросеть для симулятора v4: оценка позиции и бот, который ею пользуется.

Сеть V(позиция) → вероятность победы стороны, которая сейчас ходит. Учится на
сыгранных партиях (самообучение): в каждой позиции, где сид выбирает ход,
запоминаются признаки, а меткой служит итог партии для этого сида.

NeuralBot перебирает те же манёвры, что GreedyBot, но к ожидаемому урону
атаки добавляет вклад сети: насколько выигрышна позиция после манёвра.
Итерации: партии → обучение → партии уже с NeuralBot → дообучение.

Запуск:  python3 -m sim_v4.nn --iterations 3 --matches 6000   (из tools/)
Вывод:   tools/sim_v4/value_net.npz — веса (numpy), отчёт — в stdout.
"""

from __future__ import annotations

import argparse
import math
import random
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from .bots import GreedyBot, TacticalBot, play_match
from .rules import HEROES, Match, dir_to, dist, random_fleet, sector

HERE = Path(__file__).resolve().parent
WEIGHTS = HERE / "value_net.npz"
HERO_IDS = sorted(HEROES)
ROLES = ["fighter", "interceptor", "bomber", "gunship", "support", "transport", "freighter",
         "corvette", "capital", "station"]
_greedy_probe = GreedyBot(0)


def ship_feats(m: Match, s, persp):
    if not s.alive:
        return [0.0] * 30
    f = [1.0, s.hp / 10, s.shield / 3, s.charges / 5, float(s.activated), s.d["draft_cost"] / 20,
         s.d["weapon"]["max_range"] / 6]
    f += [1.0 if s.d["role"] == r else 0.0 for r in ROLES]
    f += [a / 7 for a in s.d["arc_modifiers"]]
    q, r = (s.q, s.r) if persp == 0 else (-s.q, -s.r)          # поле «от себя»
    f += [q / 4, r / 4, math.sin(s.facing * math.pi / 3), math.cos(s.facing * math.pi / 3)]
    enemies = [o for o in m.ships if o.alive and o.seat != s.seat]
    f.append(min((dist(s.pos, o.pos) for o in enemies), default=8) / 8)
    return f[:30] + [0.0] * (30 - len(f[:30]))


def features(m: Match, seat):
    own = [s for s in m.ships if s.seat == seat][:3]
    opp = [s for s in m.ships if s.seat != seat][:3]
    x = [m.round / 60, float(m.first_seat == seat)]
    for group in (own, opp):
        for i in range(3):
            x += ship_feats(m, group[i], seat) if i < len(group) else [0.0] * 30
    x += [1.0 if HERO_IDS[i] == m.heroes[seat] else 0.0 for i in range(len(HERO_IDS))]
    x += [1.0 if HERO_IDS[i] == m.heroes[1 - seat] else 0.0 for i in range(len(HERO_IDS))]
    # агрегаты: суммарные корпус/щит, сколько можно атаковать прямо сейчас
    for grp in (own, opp):
        x += [sum(s.hp for s in grp if s.alive) / 30, sum(s.shield for s in grp if s.alive) / 8,
              sum(1 for s in grp if s.alive) / 3]
    x.append(sum(1 for s in own if s.alive for o in opp if m.can_attack(s, o)) / 9)
    x.append(sum(1 for s in opp if s.alive for o in own if m.can_attack(s, o)) / 9)
    return np.asarray(x, dtype=np.float32)


N_FEAT = 2 + 6 * 30 + 2 * len(HERO_IDS) + 6 + 2


class ValueNet:
    """MLP, прямой проход на numpy (быстро для перебора сотен манёвров)."""

    def __init__(self, params=None):
        self.p = params

    @classmethod
    def load(cls, path=WEIGHTS):
        d = np.load(path)
        return cls({k: d[k] for k in d.files})

    def __call__(self, X):
        h = np.maximum(0, X @ self.p["w1"] + self.p["b1"])
        h = np.maximum(0, h @ self.p["w2"] + self.p["b2"])
        z = h @ self.p["w3"] + self.p["b3"]
        return 1 / (1 + np.exp(-z[:, 0]))


class NeuralBot(GreedyBot):
    name = "neural"
    weight = 4.0                                     # вклад сети в оценку манёвра

    def __init__(self, seed=0, net: ValueNet | None = None):
        super().__init__(seed)
        self.net = net

    def choose(self, m: Match, only=None):
        cands, feats = [], []
        for s in m.ships:
            if not (s.alive and s.seat == m.turn_seat and not s.activated):
                continue
            if only is not None and s is not only:
                continue
            q0, r0, f0, c0 = s.q, s.r, s.facing, s.charges
            for acts, q, r, f, spent in self.plans(m, s):
                s.q, s.r, s.facing, s.charges = q, r, f, c0 - spent
                cands.append((self.score_here(m, s, spent), s, acts))
                feats.append(features(m, m.turn_seat))
            s.q, s.r, s.facing, s.charges = q0, r0, f0, c0
        v = self.net(np.stack(feats))
        best = max(range(len(cands)), key=lambda i: cands[i][0] + self.weight * v[i] + self.rng.random() * 1e-3)
        return cands[best][1], cands[best][2]


# ------------------------------------------------------------------ самоигра
def _record_match(args):
    seed, use_net = args
    rng = random.Random(seed)
    heroes = [rng.choice(HERO_IDS), rng.choice(HERO_IDS)]
    fleets = [random_fleet(heroes[0], rng), random_fleet(heroes[1], rng)]
    if None in fleets:
        return []
    net = ValueNet.load() if use_net and WEIGHTS.exists() else None
    kinds = [GreedyBot, TacticalBot] + ([lambda s: NeuralBot(s, net)] if net else [])
    bots = [rng.choice(kinds)(seed * 2 + i) for i in range(2)]
    for b in bots:                                   # немного случайности — разнообразие позиций
        b.rng = random.Random(seed + 7)
    m = Match(heroes, fleets, seed=seed)
    samples = []
    guard = 0
    while not m.done and guard < 5000:
        if m.active is None:
            samples.append((features(m, m.turn_seat), m.turn_seat))
        bots[m.turn_seat].play_turn(m)
        guard += 1
    out = []
    for x, seat in samples:
        y = 0.5 if m.winner is None else float(m.winner == seat)
        out.append((x, y))
    return out


def generate(n, seed0, use_net, workers=9):
    with Pool(workers) as pool:
        chunks = pool.map(_record_match, [(seed0 + i, use_net) for i in range(n)], chunksize=64)
    X = np.stack([x for c in chunks for x, _ in c])
    y = np.asarray([y for c in chunks for _, y in c], dtype=np.float32)
    return X, y


def train(X, y, epochs=12, init=None):
    import torch
    torch.manual_seed(0)
    model = torch.nn.Sequential(torch.nn.Linear(X.shape[1], 256), torch.nn.ReLU(),
                                torch.nn.Linear(256, 128), torch.nn.ReLU(), torch.nn.Linear(128, 1))
    if init is not None:
        with torch.no_grad():
            for layer, (w, b) in zip([model[0], model[2], model[4]],
                                     [("w1", "b1"), ("w2", "b2"), ("w3", "b3")]):
                layer.weight.copy_(torch.from_numpy(init[w].T)); layer.bias.copy_(torch.from_numpy(init[b]))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    Xt, yt = torch.from_numpy(X), torch.from_numpy(y)
    idx = torch.randperm(len(Xt)); cut = int(len(Xt) * 0.9)
    tr, va = idx[:cut], idx[cut:]
    lossf = torch.nn.BCEWithLogitsLoss()
    for ep in range(epochs):
        model.train()
        for b in torch.split(tr[torch.randperm(len(tr))], 1024):
            opt.zero_grad(); loss = lossf(model(Xt[b])[:, 0], yt[b]); loss.backward(); opt.step()
        model.eval()
        with torch.no_grad():
            p = torch.sigmoid(model(Xt[va])[:, 0])
            vl = lossf(model(Xt[va])[:, 0], yt[va]).item()
            acc = ((p > 0.5).float() == (yt[va] > 0.5).float())[yt[va] != 0.5].float().mean().item()
    print(f"  обучение: {len(tr)} позиций, проверка {len(va)}: log-loss {vl:.3f}, точность исхода {acc:.1%}")
    params = {"w1": model[0].weight.detach().numpy().T.copy(), "b1": model[0].bias.detach().numpy().copy(),
              "w2": model[2].weight.detach().numpy().T.copy(), "b2": model[2].bias.detach().numpy().copy(),
              "w3": model[4].weight.detach().numpy().T.copy(), "b3": model[4].bias.detach().numpy().copy()}
    np.savez(WEIGHTS, **params)
    return params


def _eval_match(args):
    seed, kind_a, kind_b = args
    rng = random.Random(10_000_000 + seed)
    heroes = [rng.choice(HERO_IDS), rng.choice(HERO_IDS)]
    fleets = [random_fleet(heroes[0], rng), random_fleet(heroes[1], rng)]
    if None in fleets:
        return None
    net = ValueNet.load()
    make = {"neural": lambda s: NeuralBot(s, net), "greedy": GreedyBot, "tactical": TacticalBot}
    swap = seed % 2 == 1                               # стороны меняются через партию
    bots = [make[kind_b](seed), make[kind_a](seed)] if swap else [make[kind_a](seed), make[kind_b](seed)]
    win, _, _ = play_match(heroes, fleets, bots, seed=seed)
    if win is None:
        return "draw"
    a_seat = 1 if swap else 0
    return "a" if win == a_seat else "b"


def evaluate(kind_a, kind_b, n, workers=9):
    with Pool(workers) as pool:
        res = pool.map(_eval_match, [(i, kind_a, kind_b) for i in range(n)], chunksize=16)
    a, b, d = res.count("a"), res.count("b"), res.count("draw")
    return a, b, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--matches", type=int, default=6000)
    ap.add_argument("--eval", type=int, default=1000)
    args = ap.parse_args()
    params = None
    for it in range(args.iterations):
        t = time.time()
        X, y = generate(args.matches, seed0=it * 1_000_000, use_net=it > 0)
        print(f"итерация {it + 1}: {args.matches} партий самоигры → {len(X)} позиций ({time.time() - t:.0f} с)")
        params = train(X, y, init=params)
        a, b, d = evaluate("neural", "greedy", args.eval)
        print(f"  нейробот против жадного: {a} : {b} (ничьих {d}) — доля побед {a / max(1, a + b):.1%}")
    a, b, d = evaluate("neural", "tactical", args.eval)
    print(f"итог: нейробот против тактического: {a} : {b} (ничьих {d}) — {a / max(1, a + b):.1%}")


if __name__ == "__main__":
    main()
