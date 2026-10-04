#!/usr/bin/env python3
"""Enumerate and rank exactly 100 baseline combat formulas for rules v3.6.

Grid: five attacker/defender d6 pool pairs, five active-attacker bonuses,
and four damage caps. Ship abilities are deliberately excluded: the script
selects a stable baseline first, then abilities must be tested separately.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path


DICE_PAIRS = [(1, 1), (2, 1), (2, 2), (3, 2), (2, 3)]
ATTACK_BONUSES = range(5)
DAMAGE_CAPS = (2, 3, 4, None)
HULLS = (4, 5, 7, 9)


def dice_sums(count: int) -> list[int]:
    return [sum(faces) for faces in itertools.product(range(1, 7), repeat=count)]


def exchange_distribution(
    attacker_dice: int,
    defender_dice: int,
    attacker_bonus: int,
    damage_cap: int | None,
    attacker_arc: int = 0,
    defender_arc: int = 0,
) -> dict[tuple[str, int], float]:
    """Exact distribution: ('target'|'active'|'none', damage)."""
    attacker = dice_sums(attacker_dice)
    defender = dice_sums(defender_dice)
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for attack_roll in attacker:
        for defense_roll in defender:
            attack = max(0, attack_roll + attacker_bonus + attacker_arc)
            defense = max(0, defense_roll + defender_arc)
            if attack == defense:
                counts[("none", 0)] += 1
                continue
            damage = abs(attack - defense)
            if damage_cap is not None:
                damage = min(damage, damage_cap)
            counts[("target" if attack > defense else "active", damage)] += 1
    total = len(attacker) * len(defender)
    return {outcome: count / total for outcome, count in counts.items()}


def exchange_metrics(distribution: dict[tuple[str, int], float]) -> dict[str, float]:
    result = {
        "target_hit": 0.0,
        "active_hit": 0.0,
        "tie": 0.0,
        "target_damage": 0.0,
        "active_damage": 0.0,
        "oneshot_4": 0.0,
    }
    for (side, damage), probability in distribution.items():
        if side == "target":
            result["target_hit"] += probability
            result["target_damage"] += probability * damage
            if damage >= 4:
                result["oneshot_4"] += probability
        elif side == "active":
            result["active_hit"] += probability
            result["active_damage"] += probability * damage
        else:
            result["tie"] += probability
    return result


def duel_metrics(
    distribution: dict[tuple[str, int], float], hull: int
) -> dict[str, float]:
    """Exact alternating-attack duel via converged finite-state recurrences.

    State is (first-player HP, second-player HP, active player). The same
    exchange distribution applies on every activation; roles swap afterward.
    """
    states = [
        (hp_a, hp_b, turn)
        for hp_a in range(1, hull + 1)
        for hp_b in range(1, hull + 1)
        for turn in (0, 1)
    ]
    win = {state: 0.5 for state in states}
    expected = {state: 0.0 for state in states}

    def transitions(state: tuple[int, int, int]):
        hp_a, hp_b, turn = state
        for (side, damage), probability in distribution.items():
            next_a, next_b = hp_a, hp_b
            if side == "target":
                if turn == 0:
                    next_b -= damage
                else:
                    next_a -= damage
            elif side == "active":
                if turn == 0:
                    next_a -= damage
                else:
                    next_b -= damage
            yield probability, next_a, next_b, 1 - turn

    for _ in range(20000):
        delta = 0.0
        next_win: dict[tuple[int, int, int], float] = {}
        next_expected: dict[tuple[int, int, int], float] = {}
        for state in states:
            w = 0.0
            e = 1.0
            continuation = 0.0
            for probability, hp_a, hp_b, turn in transitions(state):
                if hp_b <= 0:
                    w += probability
                elif hp_a <= 0:
                    pass
                else:
                    nxt = (hp_a, hp_b, turn)
                    w += probability * win[nxt]
                    continuation += probability * expected[nxt]
            e += continuation
            next_win[state] = w
            next_expected[state] = e
            delta = max(delta, abs(w - win[state]), abs(e - expected[state]))
        win, expected = next_win, next_expected
        if delta < 1e-13:
            break
    else:
        raise RuntimeError("duel recurrence did not converge")

    second = {state: expected[state] ** 2 for state in states}
    for _ in range(20000):
        delta = 0.0
        next_second: dict[tuple[int, int, int], float] = {}
        for state in states:
            continuation_e = 0.0
            continuation_second = 0.0
            for probability, hp_a, hp_b, turn in transitions(state):
                if hp_a > 0 and hp_b > 0:
                    nxt = (hp_a, hp_b, turn)
                    continuation_e += probability * expected[nxt]
                    continuation_second += probability * second[nxt]
            value = 1.0 + 2.0 * continuation_e + continuation_second
            next_second[state] = value
            delta = max(delta, abs(value - second[state]))
        second = next_second
        if delta < 1e-12:
            break
    else:
        raise RuntimeError("duel second moment did not converge")

    initial = (hull, hull, 0)
    variance = max(0.0, second[initial] - expected[initial] ** 2)
    return {
        "first_win": win[initial],
        "exchanges": expected[initial],
        "stddev": math.sqrt(variance),
        "cv": math.sqrt(variance) / expected[initial],
    }


def plateau_score(value: float, outer_low: float, ideal_low: float,
                  ideal_high: float, outer_high: float) -> float:
    if ideal_low <= value <= ideal_high:
        return 1.0
    if value <= outer_low or value >= outer_high:
        return 0.0
    if value < ideal_low:
        return (value - outer_low) / (ideal_low - outer_low)
    return (outer_high - value) / (outer_high - ideal_high)


def upper_score(value: float, ideal_max: float, outer_max: float) -> float:
    if value <= ideal_max:
        return 1.0
    if value >= outer_max:
        return 0.0
    return (outer_max - value) / (outer_max - ideal_max)


def score_variant(row: dict) -> tuple[float, dict[str, float], list[str]]:
    # Targets are design choices, not empirical facts. They encode: a 4-HP
    # mirror duel lasts about 3-4 exchanges, a 9-HP duel about 6-8.5; neutral
    # attacks are useful but risky; a +2 flank is material, never automatic.
    # The ranges intentionally prefer the faster side of the safe spectrum:
    # the user's requested objective is a short game without one-roll kills.
    tempo_targets = {4: (2.5, 3.0, 4.0, 5.5), 5: (3.0, 3.5, 5.0, 6.5),
                     7: (4.0, 5.0, 7.0, 9.0), 9: (5.0, 6.0, 8.5, 11.0)}
    tempo = sum(plateau_score(row[f"duel_{hp}_exchanges"], *tempo_targets[hp])
                for hp in HULLS) / len(HULLS)
    lethality = 0.5 * upper_score(row["neutral_oneshot_4"], 0.10, 0.20)
    lethality += 0.5 * plateau_score(row["neutral_target_damage"], 0.8, 1.2, 1.8, 2.5)
    exchange_balance = 0.5 * plateau_score(
        row["neutral_target_hit"], 0.42, 0.52, 0.62, 0.75)
    exchange_balance += 0.5 * plateau_score(
        row["neutral_active_hit"], 0.15, 0.25, 0.38, 0.50)
    flank_delta = row["flank_target_hit"] - row["neutral_target_hit"]
    flank = 0.5 * plateau_score(flank_delta, 0.08, 0.15, 0.28, 0.40)
    flank += 0.5 * plateau_score(row["flank_target_hit"], 0.55, 0.68, 0.82, 0.92)
    first = upper_score(abs(row["duel_5_first_win"] - 0.5), 0.07, 0.18)
    predictability = sum(upper_score(row[f"duel_{hp}_cv"], 0.45, 0.70)
                         for hp in HULLS) / len(HULLS)
    stall = upper_score(row["neutral_tie"], 0.15, 0.35)
    components = {
        "tempo": tempo,
        "lethality": lethality,
        "exchange_balance": exchange_balance,
        "flank": flank,
        "first_action": first,
        "predictability": predictability,
        "anti_stall": stall,
    }
    weights = {
        "tempo": 0.25,
        "lethality": 0.15,
        "exchange_balance": 0.20,
        "flank": 0.15,
        "first_action": 0.15,
        "predictability": 0.05,
        "anti_stall": 0.05,
    }
    score = 100.0 * sum(weights[key] * components[key] for key in weights)
    failures = []
    if row["neutral_oneshot_4"] > 0.15:
        failures.append("one-shot >15%")
    if not 2.5 <= row["duel_4_exchanges"] <= 8.0:
        failures.append("4HP tempo")
    if not 5.0 <= row["duel_9_exchanges"] <= 16.0:
        failures.append("9HP tempo")
    if abs(row["duel_5_first_win"] - 0.5) > 0.15:
        failures.append("first action >15pp")
    if not 0.08 <= flank_delta <= 0.40:
        failures.append("flank value")
    return score, components, failures


def analyze() -> list[dict]:
    rows = []
    for attacker_dice, defender_dice in DICE_PAIRS:
        for bonus in ATTACK_BONUSES:
            for cap in DAMAGE_CAPS:
                neutral_distribution = exchange_distribution(
                    attacker_dice, defender_dice, bonus, cap)
                flank_distribution = exchange_distribution(
                    attacker_dice, defender_dice, bonus, cap, attacker_arc=2)
                neutral = exchange_metrics(neutral_distribution)
                flank = exchange_metrics(flank_distribution)
                row = {
                    "formula": f"{attacker_dice}d6 vs {defender_dice}d6; A+{bonus}; cap {cap or 'inf'}",
                    "attacker_dice": attacker_dice,
                    "defender_dice": defender_dice,
                    "attacker_bonus": bonus,
                    "damage_cap": cap,
                }
                row.update({f"neutral_{key}": value for key, value in neutral.items()})
                row.update({f"flank_{key}": value for key, value in flank.items()})
                for hp in HULLS:
                    duel = duel_metrics(neutral_distribution, hp)
                    row.update({f"duel_{hp}_{key}": value for key, value in duel.items()})
                score, components, failures = score_variant(row)
                row["score"] = score
                row["eligible"] = not failures
                row["failures"] = failures
                row["components"] = components
                rows.append(row)
    assert len(rows) == 100
    rows.sort(key=lambda item: (item["eligible"], item["score"]), reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    fields = [
        "rank", "eligible", "score", "formula", "attacker_dice", "defender_dice",
        "attacker_bonus", "damage_cap", "neutral_target_hit", "neutral_active_hit",
        "neutral_tie", "neutral_target_damage", "neutral_active_damage",
        "neutral_oneshot_4", "flank_target_hit", "flank_target_damage",
        "duel_4_exchanges", "duel_5_exchanges", "duel_7_exchanges",
        "duel_9_exchanges", "duel_5_first_win", "duel_5_cv", "failures",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["failures"] = "; ".join(row["failures"])
            writer.writerow(flat)


def write_json(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rows = analyze()
    if args.csv:
        write_csv(rows, args.csv)
    if args.json:
        write_json(rows, args.json)
    print("rank eligible score formula | hit target/active tie dmg target one-shot flank-hit "
          "duel4 duel9 first-win")
    for row in rows[:20]:
        print(
            f"{row['rank']:>2} {str(row['eligible']):>5} {row['score']:6.2f} "
            f"{row['formula']:<29} | "
            f"{row['neutral_target_hit']:.3f}/{row['neutral_active_hit']:.3f} "
            f"{row['neutral_tie']:.3f} {row['neutral_target_damage']:.3f} "
            f"{row['neutral_oneshot_4']:.3f} {row['flank_target_hit']:.3f} "
            f"{row['duel_4_exchanges']:.2f} {row['duel_9_exchanges']:.2f} "
            f"{row['duel_5_first_win']:.3f}"
        )


if __name__ == "__main__":
    main()
