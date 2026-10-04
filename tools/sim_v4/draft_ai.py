"""ИИ драфта: сеть оценки составов и драфтер, который по ней выбирает карточки.

RosterNet(A, B) → вероятность, что состав A обыграет состав B (при данном
боте в бою). Вход — герой (one-hot) и корабли (multi-hot) обеих сторон.
Учится на сыгранных партиях; при обучении часть карточек случайно скрывается,
поэтому сеть оценивает и неполные составы — позицию посреди драфта.

ValueDrafter на своём ходу для каждой разрешённой карточки p считает
  польза = V(A+p, B) + λ·[V(A, B) − V(A, B+p)]
— насколько карточка усиливает себя и насколько ослабила бы соперника,
достанься она ему (отбор). Порядок «герой или корабли» выбирается сам.

Запуск (из tools/):  python3 -m sim_v4.draft_ai --matches 60000 --iterations 2
"""

from __future__ import annotations

import argparse
import random
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from .bots import TacticalBot, play_match
from .draft import CATALOG_HEROES, CATALOG_SHIPS, DraftState, RandomDrafter, legal_picks, run_draft

HERE = Path(__file__).resolve().parent
WEIGHTS = HERE / "roster_net.npz"
H_IDX = {h: i for i, h in enumerate(CATALOG_HEROES)}
S_IDX = {s: i for i, s in enumerate(CATALOG_SHIPS)}
SIDE = len(H_IDX) + len(S_IDX)


def side_vec(hero, ships):
    v = np.zeros(SIDE, dtype=np.float32)
    if hero:
        v[H_IDX[hero]] = 1
    for s in ships:
        v[len(H_IDX) + S_IDX[s]] = 1
    return v


def pair_vec(a, b):
    return np.concatenate([a, b])


class RosterNet:
    def __init__(self, p):
        self.p = p

    @classmethod
    def load(cls):
        d = np.load(WEIGHTS)
        return cls({k: d[k] for k in d.files})

    def __call__(self, X):
        h = np.maximum(0, X @ self.p["w1"] + self.p["b1"])
        h = np.maximum(0, h @ self.p["w2"] + self.p["b2"])
        z = (h @ self.p["w3"] + self.p["b3"])[:, 0]
        return 1 / (1 + np.exp(-z))

    def value(self, A, B):
        """Антисимметричная оценка: среднее V(A,B) и 1−V(B,A)."""
        X = np.stack([pair_vec(A, B), pair_vec(B, A)])
        v = self(X)
        return (v[0] + 1 - v[1]) / 2


class ValueDrafter:
    name = "value"
    deny = 0.6

    def __init__(self, seed=0, net: RosterNet | None = None, temperature=0.0):
        self.rng = random.Random(seed)
        self.net = net or RosterNet.load()
        self.t = temperature                           # >0 — слабее и разнообразнее (уровни сложности)

    def pick(self, st: DraftState):
        seat = st.seat
        me = side_vec(st.heroes[seat], st.ships[seat])
        opp = side_vec(st.heroes[1 - seat], st.ships[1 - seat])
        picks = legal_picks(st)
        rows_self, rows_deny = [], []
        for kind, cid in picks:
            idx = H_IDX[cid] if kind == "hero" else len(H_IDX) + S_IDX[cid]
            a = me.copy(); a[idx] = 1
            b = opp.copy(); b[idx] = 1
            rows_self += [pair_vec(a, opp), pair_vec(opp, a)]
            rows_deny += [pair_vec(me, b), pair_vec(b, me)]
        vs = self.net(np.stack(rows_self)).reshape(-1, 2)
        vd = self.net(np.stack(rows_deny)).reshape(-1, 2)
        gain = (vs[:, 0] + 1 - vs[:, 1]) / 2
        after_opp = (vd[:, 0] + 1 - vd[:, 1]) / 2          # моя оценка, если карточку взял соперник
        base = self.net.value(me, opp)
        score = gain + self.deny * (base - after_opp)
        if self.t > 0:
            w = np.exp((score - score.max()) / self.t)
            return picks[self.rng.choices(range(len(picks)), weights=w)[0]]
        return picks[int(np.argmax(score + np.array([self.rng.random() * 1e-6 for _ in picks])))]


# ------------------------------------------------------------------ данные и обучение
def _one(args):
    seed, kinds = args
    rng = random.Random(seed)
    make = {"random": lambda s: RandomDrafter(s), "value": lambda s: ValueDrafter(s, temperature=0.02)}
    drafters = [make[rng.choice(kinds)](seed), make[rng.choice(kinds)](seed + 1)]
    st = run_draft(drafters, seed)
    if st is None:
        return None
    win, _, _ = play_match(st.heroes, st.ships, [TacticalBot(seed), TacticalBot(seed + 1)], seed=seed)
    return st.heroes, st.ships, win


def generate(n, seed0, kinds, workers=9):
    with Pool(workers) as pool:
        return [r for r in pool.map(_one, [(seed0 + i, kinds) for i in range(n)], chunksize=32) if r]


def train(games, epochs=25, init=None):
    import torch
    rng = np.random.default_rng(0)
    A = np.stack([side_vec(h[0], s[0]) for h, s, w in games])
    B = np.stack([side_vec(h[1], s[1]) for h, s, w in games])
    y = np.array([0.5 if w is None else float(w == 0) for h, s, w in games], dtype=np.float32)
    X = np.concatenate([np.concatenate([A, B], 1), np.concatenate([B, A], 1)])     # обе стороны
    Y = np.concatenate([y, 1 - y])
    model = torch.nn.Sequential(torch.nn.Linear(2 * SIDE, 256), torch.nn.ReLU(),
                                torch.nn.Linear(256, 128), torch.nn.ReLU(), torch.nn.Linear(128, 1))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    lossf = torch.nn.BCEWithLogitsLoss()
    idx = rng.permutation(len(X)); cut = int(len(X) * 0.9)
    Xt, Yt = torch.from_numpy(X), torch.from_numpy(Y)
    tr, va = torch.from_numpy(idx[:cut]), torch.from_numpy(idx[cut:])
    for ep in range(epochs):
        model.train()
        for b in torch.split(tr[torch.randperm(len(tr))], 512):
            xb = Xt[b].clone()
            # скрыть случайную часть карточек — сеть учится оценивать неполные составы
            mask = (torch.rand_like(xb) < torch.rand(len(xb), 1) * 0.5)
            xb[mask] = 0
            opt.zero_grad(); loss = lossf(model(xb)[:, 0], Yt[b]); loss.backward(); opt.step()
    model.eval()
    with torch.no_grad():
        p = torch.sigmoid(model(Xt[va])[:, 0]); yv = Yt[va]
        dec = yv != 0.5
        acc = ((p[dec] > 0.5).float() == yv[dec]).float().mean().item()
        vl = lossf(model(Xt[va])[:, 0], yv).item()
    print(f"  сеть составов: {len(tr)} примеров, проверка: log-loss {vl:.3f}, угадан победитель {acc:.1%}")
    params = {"w1": model[0].weight.detach().numpy().T.copy(), "b1": model[0].bias.detach().numpy().copy(),
              "w2": model[2].weight.detach().numpy().T.copy(), "b2": model[2].bias.detach().numpy().copy(),
              "w3": model[4].weight.detach().numpy().T.copy(), "b3": model[4].bias.detach().numpy().copy()}
    np.savez(WEIGHTS, **params)
    return params


def _duel(args):
    seed, a, b = args
    make = {"random": lambda s: RandomDrafter(s), "value": lambda s: ValueDrafter(s)}
    swap = seed % 2 == 1
    drafters = [make[b](seed), make[a](seed)] if swap else [make[a](seed), make[b](seed)]
    st = run_draft(drafters, seed)
    win, _, _ = play_match(st.heroes, st.ships, [TacticalBot(seed), TacticalBot(seed + 1)], seed=seed)
    if win is None:
        return "draw", None
    a_seat = 1 if swap else 0
    return ("a" if win == a_seat else "b"), (st.heroes[a_seat], st.ships[a_seat])


def evaluate(a, b, n, workers=9):
    with Pool(workers) as pool:
        res = pool.map(_duel, [(20_000_000 + i, a, b) for i in range(n)], chunksize=8)
    wa = sum(1 for r, _ in res if r == "a"); wb = sum(1 for r, _ in res if r == "b")
    return wa, wb, [x for _, x in res if x]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=60000)
    ap.add_argument("--iterations", type=int, default=2)
    ap.add_argument("--eval", type=int, default=1000)
    args = ap.parse_args()
    games = []
    for it in range(args.iterations):
        t = time.time()
        kinds = ["random"] if it == 0 else ["random", "value"]
        games += generate(args.matches, it * 10_000_000, kinds)
        print(f"итерация {it + 1}: всего партий с драфтом {len(games)} ({time.time() - t:.0f} с)")
        train(games)
        wa, wb, rosters = evaluate("value", "random", args.eval)
        print(f"  ИИ-драфтер против случайного: {wa} : {wb} — {wa / max(1, wa + wb):.1%}")
    from collections import Counter
    heroes = Counter(h for h, s in rosters); ships = Counter(x for h, s in rosters for x in s)
    print("  чаще всего берёт героев:", heroes.most_common(8))
    print("  чаще всего берёт корабли:", ships.most_common(10))


if __name__ == "__main__":
    main()
