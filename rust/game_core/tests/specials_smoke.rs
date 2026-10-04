//! Special-rules smoke (ADR-012): the differential corpus must contain
//! matches with ShipTransformed/ShipRevived and elimination endings; a seed
//! scan (0..=200) must find both event kinds; transformed/revived states
//! survive a snapshot round-trip.

mod common;

use game_core::{
    apply_command, create_match, legal_actions, replay, restore_snapshot, snapshot_bytes,
    state_hash, MatchConfig, MatchState,
};
use serde_json::Value;
use std::path::PathBuf;

fn corpus_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/golden/diff_corpus_100.jsonl")
}

fn load_corpus() -> Vec<(i64, bool)> {
    let text = std::fs::read_to_string(corpus_path()).expect("corpus readable");
    text.lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| {
            let v: Value = serde_json::from_str(l).unwrap();
            (v["seed"].as_i64().unwrap(), v["saw_special"].as_bool().unwrap())
        })
        .collect()
}

#[test]
fn corpus_contains_special_matches() {
    let corpus = load_corpus();
    assert_eq!(corpus.len(), 100);
    let specials = corpus.iter().filter(|(_, s)| *s).count();
    assert!(
        specials > 0,
        "corpus must contain matches with special events (found 0)"
    );
    println!("SPECIALS: {specials}/100 corpus matches contain ShipTransformed/ShipRevived");

    // Elimination wins must also be present (coverage of both endings).
    let mut eliminations = 0;
    for (seed, _) in &corpus {
        let (_state, events, _) = common::play_random_match(*seed);
        if events.iter().any(|e| {
            e["type"] == "MatchEnded" && e["reason"] == "elimination"
        }) {
            eliminations += 1;
        }
    }
    assert!(eliminations > 0, "corpus must contain elimination wins");
    println!("ELIMINATIONS: {eliminations}/100 corpus matches end by elimination");
}

#[test]
fn seed_scan_0_to_200_finds_both_special_events() {
    let mut transformed_seed: Option<i64> = None;
    let mut revived_seed: Option<i64> = None;
    for seed in 0..=200i64 {
        let (_state, events, _commands) = common::play_random_match(seed);
        if transformed_seed.is_none()
            && events.iter().any(|e| e["type"] == "ShipTransformed")
        {
            transformed_seed = Some(seed);
        }
        if revived_seed.is_none() && events.iter().any(|e| e["type"] == "ShipRevived") {
            revived_seed = Some(seed);
        }
        if transformed_seed.is_some() && revived_seed.is_some() {
            break;
        }
    }
    assert!(
        transformed_seed.is_some(),
        "no ShipTransformed in seeds 0..=200"
    );
    assert!(revived_seed.is_some(), "no ShipRevived in seeds 0..=200");
    println!(
        "SPECIAL SEEDS: ShipTransformed at seed {:?}, ShipRevived at seed {:?}",
        transformed_seed, revived_seed
    );
}

fn first_seed_with(event_type: &str) -> i64 {
    (0..=200i64)
        .find(|s| {
            let (_, events, _) = common::play_random_match(*s);
            events.iter().any(|e| e["type"] == event_type)
        })
        .unwrap_or_else(|| panic!("no {event_type} seed in 0..=200"))
}

#[test]
fn transformed_state_survives_snapshot_roundtrip() {
    let seed = first_seed_with("ShipTransformed");
    let (final_state, _, commands) = common::play_random_match(seed);
    assert!(
        final_state.ships.iter().any(|s| s.type_id == "phantom"),
        "a phantom exists at the end of seed {seed}"
    );
    let restored: MatchState = restore_snapshot(&snapshot_bytes(&final_state)).unwrap();
    assert_eq!(state_hash(&restored), state_hash(&final_state));

    // Mid-match: the state right after the transform round-trips too.
    let config = MatchConfig { seed, ..MatchConfig::default() };
    let (mut state, _) = create_match(&config).unwrap();
    for command in &commands {
        let (_, next) = apply_command(&state, command).unwrap();
        if next.ships.iter().any(|s| s.type_id == "phantom") {
            let mid_restored = restore_snapshot(&snapshot_bytes(&next)).unwrap();
            assert_eq!(state_hash(&mid_restored), state_hash(&next));
            break;
        }
        state = next;
    }
}

#[test]
fn revived_state_survives_snapshot_roundtrip() {
    let seed = first_seed_with("ShipRevived");
    let (final_state, events, commands) = common::play_random_match(seed);
    assert!(
        final_state.ships.iter().any(|s| s.revive_used),
        "revive_used flag recorded (seed {seed})"
    );
    let restored: MatchState = restore_snapshot(&snapshot_bytes(&final_state)).unwrap();
    assert_eq!(state_hash(&restored), state_hash(&final_state));
    let config = MatchConfig { seed, ..MatchConfig::default() };
    let (replayed, _) = replay(&config, &commands).unwrap();
    assert_eq!(state_hash(&replayed), state_hash(&final_state));

    // The revive hp is a d4 result; the journal holds the d2 attempt and d4.
    let revived = events
        .iter()
        .find(|e| e["type"] == "ShipRevived")
        .expect("revive event");
    let hp = revived["hp"].as_i64().unwrap();
    assert!((1..=4).contains(&hp), "revive hp is d4");
}

#[test]
fn legal_actions_stay_nonempty_until_match_end() {
    for seed in [0, 1, 2] {
        let config = MatchConfig { seed, ..MatchConfig::default() };
        let (mut state, _) = create_match(&config).unwrap();
        while !game_core::is_terminal(&state) {
            let legal = legal_actions(&state);
            assert!(!legal.is_empty(), "seed {seed}: legal actions never empty");
            let command = legal[0].clone();
            let (_, next) =
                apply_command(&state, &command).expect("legal command must apply");
            state = next;
        }
    }
}

/// Splits an event journal into per-attack segments [start, end) starting at
/// an AttackDeclared and ending before the next one.
fn attack_segments(events: &[Value]) -> Vec<(usize, usize)> {
    let mut bounds: Vec<usize> = events
        .iter()
        .enumerate()
        .filter(|(_, e)| e["type"] == "AttackDeclared")
        .map(|(i, _)| i)
        .collect();
    bounds.push(events.len());
    bounds
        .windows(2)
        .map(|w| (w[0], w[1]))
        .filter(|(s, e)| e > s)
        .collect()
}

#[test]
fn vulture_reroll_replaces_first_natural_one_and_result_is_final() {
    // C011 / ADR-014 §3: after the attacker's dice a single d2 gates one
    // forced reroll of the FIRST face == 1; the rerolled value stands even
    // when it is 1 again, and the attacker strength uses the final faces.
    for seed in 0..=200i64 {
        let (_state, events, _commands) = common::play_random_match(seed);
        let mut found = false;
        for (start, end) in attack_segments(&events) {
            let segment = &events[start..end];
            let Some(first_strength) = segment
                .iter()
                .position(|e| e["type"] == "StrengthCalculated")
            else {
                continue;
            };
            let rolls: Vec<&Value> = segment[..first_strength]
                .iter()
                .filter(|e| e["type"] == "DieRolled")
                .collect();
            // The defender d6 closes the pre-strength sequence; the vulture
            // reroll pattern precedes it: attacker d6, d6, d2, d6 (v3.1:
            // 2 attacker dice).
            let defender_last = rolls
                .last()
                .map(|r| r["role"].as_str() == Some("defender") && r["sides"].as_u64() == Some(6))
                .unwrap_or(false);
            if !defender_last {
                continue;
            }
            let att: Vec<&Value> = rolls[..rolls.len() - 1].iter().copied().collect();
            if att.len() != 4 || att.iter().any(|r| r["role"] != "attacker") {
                continue;
            }
            let sides: Vec<u64> = att.iter().map(|r| r["sides"].as_u64().unwrap()).collect();
            let values: Vec<i64> = att.iter().map(|r| r["value"].as_i64().unwrap()).collect();
            if sides != [6, 6, 2, 6] {
                continue;
            }
            found = true;
            let gate = att[2]["value"].as_i64().unwrap();
            assert!(matches!(gate, 1 | 2));
            if gate == 2 {
                let opening = [values[0], values[1]];
                assert!(
                    opening.contains(&1),
                    "seed {seed}: d2 gate only fires on a natural 1"
                );
                let strength = &segment[first_strength];
                let dice: Vec<i64> = strength["dice"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_i64().unwrap())
                    .collect();
                // The FIRST natural 1 is replaced by the reroll; the second
                // die keeps its original face even when the reroll is a 1.
                let expected = if opening[0] == 1 {
                    [values[3], opening[1]]
                } else {
                    [opening[0], values[3]]
                };
                assert_eq!(dice, expected, "seed {seed}: rerolled faces");
                assert_eq!(strength["die"].as_i64().unwrap(), expected.iter().sum::<i64>());
            }
            break;
        }
        if found {
            println!("VULTURE REROLL: pinned at seed {seed}");
            return;
        }
    }
    panic!("no vulture reroll found in seeds 0..=200");
}

#[test]
fn xwing_lucky_shot_d2_on_tie_uses_new_totals() {
    // C009 / ADR-014 §5: the tie check runs on the v3.1 totals; an attacking
    // xwing_t65 then rolls one d2 (role "attacker") between the two
    // StrengthCalculated events and DamageApplied; success deals exactly 1.
    for seed in 0..=200i64 {
        let (_state, events, _commands) = common::play_random_match(seed);
        let mut found = false;
        for (start, end) in attack_segments(&events) {
            let segment = &events[start..end];
            let strengths: Vec<&Value> = segment
                .iter()
                .filter(|e| e["type"] == "StrengthCalculated")
                .collect();
            if strengths.len() != 2 {
                continue;
            }
            let total_a = strengths[0]["total"].as_i64().unwrap();
            let total_d = strengths[1]["total"].as_i64().unwrap();
            if total_a != total_d {
                continue;
            }
            // Tie: the event right after the second StrengthCalculated is the
            // lucky-shot d2 exactly when the special fires; destruction dice
            // (revive) only ever come after a DamageApplied, never here.
            let second_strength = segment
                .iter()
                .position(|e| e["type"] == "StrengthCalculated")
                .map(|first| {
                    first
                        + 1
                        + segment[first + 1..]
                            .iter()
                            .position(|e| e["type"] == "StrengthCalculated")
                            .expect("two strengths per attack")
                })
                .expect("two strengths per attack");
            let Some(luck) = segment.get(second_strength + 1) else {
                continue;
            };
            if luck["type"] != "DieRolled" {
                continue; // tie without lucky shot (no die, no damage)
            }
            found = true;
            assert_eq!(luck["sides"], 2, "seed {seed}: tie luck is d2");
            assert_eq!(luck["role"], "attacker", "seed {seed}: tie luck role");
            let gate = luck["value"].as_i64().unwrap();
            let damage: i64 = segment
                .iter()
                .filter(|e| e["type"] == "DamageApplied")
                .map(|e| {
                    e["shield_damage"].as_i64().unwrap() + e["hull_damage"].as_i64().unwrap()
                })
                .sum();
            assert_eq!(
                damage,
                if gate == 2 { 1 } else { 0 },
                "seed {seed}: lucky shot deals exactly 1 on success, 0 otherwise"
            );
            break;
        }
        if found {
            println!("LUCKY SHOT TIE: pinned at seed {seed}");
            return;
        }
    }
    panic!("no tie lucky-shot d2 found in seeds 0..=200");
}
