#!/usr/bin/env python3
"""Compare 3,888 combat formulas built from d4/d6/d8/d10 pools.

Candidate pools: every single die, every unordered two-die combination with
replacement, and homogeneous triples. Each attacker/defender pool pair is
tested with attacker bonus 0..2 and cap 2/3/4/infinity.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from analyze_combat_variants import duel_metrics, exchange_metrics, score_variant


SIDES = (4, 6, 8, 10)
POOLS = (
    [(side,) for side in SIDES]
    + list(itertools.combinations_with_replacement(SIDES, 2))
    + [(side, side, side) for side in SIDES]
)
ATTACK_BONUSES = range(3)
DAMAGE_CAPS = (2, 3, 4, None)
HULLS = (4, 5, 7, 9)


def pool_label(pool: tuple[int, ...]) -> str:
    counts = Counter(pool)
    if len(counts) == 1:
        side, count = next(iter(counts.items()))
        return f"d{side}" if count == 1 else f"{count}d{side}"
    return "+".join(f"d{side}" for side in pool)


@lru_cache(maxsize=None)
def sum_distribution(pool: tuple[int, ...]) -> Counter[int]:
    distribution = Counter({0: 1})
    for side in pool:
        next_distribution: Counter[int] = Counter()
        for subtotal, count in distribution.items():
            for face in range(1, side + 1):
                next_distribution[subtotal + face] += count
        distribution = next_distribution
    return distribution


def exchange_distribution(
    attacker_pool: tuple[int, ...],
    defender_pool: tuple[int, ...],
    attacker_bonus: int,
    damage_cap: int | None,
    attacker_arc: int = 0,
    defender_arc: int = 0,
) -> dict[tuple[str, int], float]:
    attacker = sum_distribution(attacker_pool)
    defender = sum_distribution(defender_pool)
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for attack_roll, attack_count in attacker.items():
        for defense_roll, defense_count in defender.items():
            multiplicity = attack_count * defense_count
            attack = max(0, attack_roll + attacker_bonus + attacker_arc)
            defense = max(0, defense_roll + defender_arc)
            if attack == defense:
                counts[("none", 0)] += multiplicity
                continue
            damage = abs(attack - defense)
            if damage_cap is not None:
                damage = min(damage, damage_cap)
            counts[("target" if attack > defense else "active", damage)] += multiplicity
    total = sum(attacker.values()) * sum(defender.values())
    return {outcome: count / total for outcome, count in counts.items()}


def convenience_penalty(attacker_pool: tuple[int, ...],
                        defender_pool: tuple[int, ...]) -> float:
    """At most one point; it can break a close tie, not erase better math."""
    extra_dice = max(0, len(attacker_pool) + len(defender_pool) - 2)
    mixed_pools = int(len(set(attacker_pool)) > 1) + int(len(set(defender_pool)) > 1)
    asymmetric_roles = int(attacker_pool != defender_pool)
    return min(1.0, 0.15 * extra_dice + 0.25 * mixed_pools
               + 0.10 * asymmetric_roles)


def exchange_prefilter(row: dict) -> list[str]:
    failures = []
    flank_delta = row["flank_target_hit"] - row["neutral_target_hit"]
    if row["neutral_oneshot_4"] > 0.15:
        failures.append("one-shot >15%")
    if not 0.35 <= row["neutral_target_hit"] <= 0.80:
        failures.append("target hit outside 35-80%")
    if not 0.10 <= row["neutral_active_hit"] <= 0.55:
        failures.append("counter-hit outside 10-55%")
    if row["neutral_tie"] > 0.35:
        failures.append("tie >35%")
    if not 0.08 <= flank_delta <= 0.40:
        failures.append("flank value")
    return failures


def analyze() -> list[dict]:
    rows = []
    fully_evaluated = 0
    for attacker_pool in POOLS:
        for defender_pool in POOLS:
            for bonus in ATTACK_BONUSES:
                for cap in DAMAGE_CAPS:
                    neutral_distribution = exchange_distribution(
                        attacker_pool, defender_pool, bonus, cap)
                    flank_distribution = exchange_distribution(
                        attacker_pool, defender_pool, bonus, cap, attacker_arc=2)
                    neutral = exchange_metrics(neutral_distribution)
                    flank = exchange_metrics(flank_distribution)
                    row = {
                        "formula": (
                            f"{pool_label(attacker_pool)} vs {pool_label(defender_pool)}; "
                            f"A+{bonus}; cap {cap or 'inf'}"
                        ),
                        "attacker_pool": list(attacker_pool),
                        "defender_pool": list(defender_pool),
                        "attacker_bonus": bonus,
                        "damage_cap": cap,
                    }
                    row.update({f"neutral_{key}": value for key, value in neutral.items()})
                    row.update({f"flank_{key}": value for key, value in flank.items()})
                    prefilter_failures = exchange_prefilter(row)
                    if prefilter_failures:
                        row.update({
                            "score": 0.0,
                            "selection_score": 0.0,
                            "eligible": False,
                            "fully_evaluated": False,
                            "failures": prefilter_failures,
                            "components": {},
                            "convenience_penalty": convenience_penalty(
                                attacker_pool, defender_pool),
                        })
                        rows.append(row)
                        continue
                    fully_evaluated += 1
                    for hp in HULLS:
                        duel = duel_metrics(neutral_distribution, hp)
                        row.update({f"duel_{hp}_{key}": value for key, value in duel.items()})
                    score, components, failures = score_variant(row)
                    penalty = convenience_penalty(attacker_pool, defender_pool)
                    row.update({
                        "score": score,
                        "selection_score": score - penalty,
                        "eligible": not failures,
                        "fully_evaluated": True,
                        "failures": failures,
                        "components": components,
                        "convenience_penalty": penalty,
                    })
                    rows.append(row)
    assert len(rows) == 3888
    rows.sort(
        key=lambda item: (
            item["eligible"], item["selection_score"], item["score"],
            -item["convenience_penalty"], item["formula"]
        ),
        reverse=True,
    )
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    print(f"fully evaluated duels: {fully_evaluated}/3888")
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    fields = [
        "rank", "eligible", "fully_evaluated", "score", "selection_score",
        "convenience_penalty", "formula", "attacker_pool", "defender_pool",
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
            flat = {field: row.get(field, "") for field in fields}
            flat["attacker_pool"] = "+".join(f"d{x}" for x in row["attacker_pool"])
            flat["defender_pool"] = "+".join(f"d{x}" for x in row["defender_pool"])
            flat["failures"] = "; ".join(row["failures"])
            writer.writerow(flat)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rows = analyze()
    if args.csv:
        write_csv(rows, args.csv)
    if args.json:
        args.json.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("rank eligible score selected formula | hit target/active tie dmg one-shot "
          "flank duel4 duel9 first-win complexity")
    for row in rows[:25]:
        print(
            f"{row['rank']:>2} {str(row['eligible']):>5} {row['score']:6.2f} "
            f"{row['selection_score']:6.2f} {row['formula']:<32} | "
            f"{row['neutral_target_hit']:.3f}/{row['neutral_active_hit']:.3f} "
            f"{row['neutral_tie']:.3f} {row['neutral_target_damage']:.3f} "
            f"{row['neutral_oneshot_4']:.3f} {row['flank_target_hit']:.3f} "
            f"{row.get('duel_4_exchanges', 0):.2f} {row.get('duel_9_exchanges', 0):.2f} "
            f"{row.get('duel_5_first_win', 0):.3f} {row['convenience_penalty']:.2f}"
        )


if __name__ == "__main__":
    main()
