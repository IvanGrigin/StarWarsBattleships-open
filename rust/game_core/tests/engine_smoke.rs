//! Engine smoke tests: match creation, activation-phase legality, full-match
//! termination, state invariants, snapshot round-trip and deterministic
//! replay — self-contained in Rust (the corpus covers GDScript parity).

mod common;

use game_core::{
    apply_command, create_match, legal_actions, replay, restore_snapshot, snapshot_bytes,
    state_hash, Command, MatchConfig, Phase,
};
use serde_json::Value;

fn config(seed: i64) -> MatchConfig {
    MatchConfig {
        seed,
        ..MatchConfig::default()
    }
}

#[test]
fn created_match_has_6_ships_and_opening_legality() {
    let (state, _) = create_match(&config(42)).unwrap();
    assert_eq!(state.ships.len(), 6, "2 seats x 3 ships (v3.2 duel, ADR-015)");
    assert_eq!(state.version, 4, "STATE_VERSION pin (ADR-018)");
    // Seat composition travels in the state (core-api §7, ADR-015).
    assert_eq!(state.seat_order, ["A1", "B1"]);
    assert_eq!(
        state.teams.a,
        vec!["A1".to_string()],
        "teams.A from the scenario"
    );
    assert_eq!(
        state.teams.b,
        vec!["B1".to_string()],
        "teams.B from the scenario"
    );
    assert_eq!(state.phase, Phase::Activation);
    assert_eq!(state.round, 1);
    assert_eq!(state.active_seat, "A1");
    assert!(state.active_ship.is_none());
    assert_eq!(state.rng_counter, 0);
    assert!(state.dice.is_empty());
    assert!(state.winner.is_none());
    // Duel placement: fixed cells and facing per seat (classic_2v2.json).
    let cells: Vec<(i64, i64)> = state.ships.iter().map(|s| (s.q, s.r)).collect();
    assert_eq!(
        cells,
        vec![(0, 3), (0, 2), (1, 2), (0, -3), (0, -2), (-1, -2)]
    );
    assert!(state.ships.iter().take(3).all(|s| s.facing == 0 && s.team == "A"));
    assert!(state.ships.iter().skip(3).all(|s| s.facing == 3 && s.team == "B"));
    let legal = legal_actions(&state);
    assert!(!legal.is_empty(), "legal actions in activation phase");
    assert_eq!(legal.len(), 3, "A1 has three unactivated ships");
    // BeginActivation comes per ships-array order (core-api §9).
    let first = &state.ships[0];
    assert!(matches!(
        &legal[0],
        Command::BeginActivation { ship_instance_id } if ship_instance_id == &first.id
    ));
}

#[test]
fn radius_3_board_rejects_move_off_the_edge() {
    // ADR-015: board radius is data (board.json radius 3). The first A1 ship
    // on (0,3) has a neighbor at dir 2 (SE) = (1,3) with |s| = 4 — off the
    // 37-hex board, so Move{dir:2} must be neither legal nor applicable.
    let (state, _) = create_match(&config(42)).unwrap();
    let edge_ship = state
        .ships
        .iter()
        .find(|s| (s.q, s.r) == (0, 3))
        .expect("A1 ship on (0,3)");
    assert_eq!(edge_ship.seat, "A1");
    assert_eq!(edge_ship.facing, 0);
    let (_, active) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: edge_ship.id.clone(),
        },
    )
    .unwrap();
    assert!(legal_actions(&active)
        .iter()
        .all(|c| !matches!(c, Command::Move { dir: 2 })),
        "Move dir 2 to (1,3) must not be legal on the radius-3 board");
    let rejection = apply_command(&active, &Command::Move { dir: 2 }).unwrap_err();
    assert_eq!(rejection.code, "out_of_board");
    assert!(rejection.detail.contains("(1,3)"), "{}", rejection.detail);
    // A direction along the board keeps its move: (0,2) dir 0 (N) -> (0,1)
    // is still on the board.
    let inner_ship = state
        .ships
        .iter()
        .find(|s| (s.q, s.r) == (0, 2))
        .expect("A1 ship on (0,2)");
    let (_, active) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: inner_ship.id.clone(),
        },
    )
    .unwrap();
    assert!(legal_actions(&active)
        .iter()
        .any(|c| matches!(c, Command::Move { dir: 0 })));
}

#[test]
fn v34_move_offers_every_legal_direction_in_dir_deltas_order() {
    // ADR-017: legal_actions carries one Move{dir} per legal direction, in
    // DIR_DELTAS order 0..5, before RotateLeft/RotateRight. Ship on (0,2)
    // facing 0: dirs 0,1 free; 2 -> (1,2) and 3 -> (0,3) occupied by allies;
    // 4,5 free. Exactly [0,1,4,5] must be offered, ascending.
    let (state, _) = create_match(&config(42)).unwrap();
    let ship = state
        .ships
        .iter()
        .find(|s| (s.q, s.r) == (0, 2))
        .expect("A1 ship on (0,2)")
        .clone();
    let (_, active) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: ship.id.clone(),
        },
    )
    .unwrap();
    let legal = legal_actions(&active);
    let move_dirs: Vec<i64> = legal
        .iter()
        .filter_map(|c| match c {
            Command::Move { dir } => Some(*dir),
            _ => None,
        })
        .collect();
    assert_eq!(move_dirs, vec![0, 1, 4, 5], "legal Move dirs ascending");
    // Moves form one contiguous block directly before the rotations.
    let first_move = legal
        .iter()
        .position(|c| matches!(c, Command::Move { .. }))
        .unwrap();
    let last_move = legal
        .iter()
        .rposition(|c| matches!(c, Command::Move { .. }))
        .unwrap();
    assert!(legal[first_move..=last_move]
        .iter()
        .all(|c| matches!(c, Command::Move { .. })));
    assert!(matches!(legal[last_move + 1], Command::RotateLeft));
}

#[test]
fn v34_move_backward_keeps_facing_and_ship_moved_carries_dir() {
    // ADR-017: a move never touches facing — the course is a combat-only
    // property. Rotate to facing 1 (NE), then step through the rear sector
    // (dir = (facing + 3) % 6 = 4): position changes, facing stays 1.
    let (state, _) = create_match(&config(42)).unwrap();
    let inner_id = state.ships[1].id.clone(); // (0,2) facing 0
    let (_, active) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: inner_id.clone(),
        },
    )
    .unwrap();
    let (_, active) = apply_command(&active, &Command::RotateRight).unwrap(); // facing 1
    let (events, moved) = apply_command(&active, &Command::Move { dir: 4 }).unwrap(); // backward
    let ship = moved.ships.iter().find(|s| s.id == inner_id).unwrap();
    assert_eq!((ship.q, ship.r), (-1, 3), "ship stepped to the rear cell");
    assert_eq!(ship.facing, 1, "move never changes facing");
    assert_eq!(ship.charges, 1, "rotate + move, one charge left");
    let ship_moved = events
        .iter()
        .find(|e| e["type"] == "ShipMoved")
        .expect("ShipMoved emitted");
    assert_eq!(ship_moved["from_q"], 0);
    assert_eq!(ship_moved["from_r"], 2);
    assert_eq!(ship_moved["to_q"], -1);
    assert_eq!(ship_moved["to_r"], 3);
    assert_eq!(ship_moved["dir"], 4, "v3.4: ShipMoved carries dir");
    assert_eq!(
        events
            .iter()
            .filter(|e| e["type"] == "ChargeSpent" && e["reason"] == "move")
            .count(),
        1
    );
}

#[test]
fn v34_move_rejections_by_direction() {
    // ADR-017 validation order on the active ship (oracle _apply_active):
    // no_charges -> bad_direction -> out_of_board -> occupied_cell, each
    // reachable through any direction.
    let (state, _) = create_match(&config(42)).unwrap();
    let edge_id = state.ships[0].id.clone(); // (0,3) facing 0
    let (_, active) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: edge_id.clone(),
        },
    )
    .unwrap();
    // Out of board through dirs 2, 3, 4 (|s| = 4 off the radius-3 board).
    for dir in [2i64, 3, 4] {
        let rejection = apply_command(&active, &Command::Move { dir }).unwrap_err();
        assert_eq!(rejection.code, "out_of_board", "dir {dir}");
    }
    // Occupied through dirs 0 and 1: allies stand on (0,2) and (1,2).
    let rejection = apply_command(&active, &Command::Move { dir: 0 }).unwrap_err();
    assert_eq!(rejection.code, "occupied_cell");
    assert!(rejection.detail.contains("(0,2)"), "{}", rejection.detail);
    let rejection = apply_command(&active, &Command::Move { dir: 1 }).unwrap_err();
    assert_eq!(rejection.code, "occupied_cell");
    assert!(rejection.detail.contains("(1,2)"), "{}", rejection.detail);
    // Only dir 5 (NW -> (-1,3)) is applicable here and succeeds with mines
    // logic untouched (no mines on the board -> no extra events).
    let (events, moved) = apply_command(&active, &Command::Move { dir: 5 }).unwrap();
    assert!(events.iter().any(|e| e["type"] == "ShipMoved"));
    assert!(!events.iter().any(|e| e["type"] == "MineTriggered"));
    assert_eq!(
        moved
            .ships
            .iter()
            .find(|s| s.id == edge_id)
            .map(|s| (s.q, s.r)),
        Some((-1, 3))
    );
    // bad_direction for 6 and -1 (before the board checks).
    let rejection = apply_command(&moved, &Command::Move { dir: 6 }).unwrap_err();
    assert_eq!(rejection.code, "bad_direction");
    assert!(rejection.detail.contains("dir 6 outside 0..5"));
    let rejection = apply_command(&moved, &Command::Move { dir: -1 }).unwrap_err();
    assert_eq!(rejection.code, "bad_direction");
    assert!(rejection.detail.contains("dir -1 outside 0..5"));
    // no_charges precedes bad_direction (oracle order).
    let mut drained = moved;
    loop {
        let ship = drained.ships.iter().find(|s| s.id == edge_id).unwrap();
        if ship.charges == 0 {
            break;
        }
        let legal = legal_actions(&drained);
        let rotate = legal
            .iter()
            .find(|c| matches!(c, Command::RotateLeft | Command::RotateRight))
            .expect("rotate stays legal while charges remain");
        let (_, next) = apply_command(&drained, rotate).unwrap();
        drained = next;
    }
    let rejection = apply_command(&drained, &Command::Move { dir: 9 }).unwrap_err();
    assert_eq!(rejection.code, "no_charges", "no_charges is checked first");
}

#[test]
fn random_matches_terminate_with_invariants() {
    for seed in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] {
        let (state, events, commands) = common::play_random_match(seed);
        assert!(
            matches!(state.phase, Phase::Ended),
            "seed {seed}: match terminated"
        );
        assert!(
            state.winner.as_deref().map(|w| w == "A" || w == "B").unwrap_or(true),
            "seed {seed}: winner A/B/null"
        );
        // rng_counter == dice.len() (ADR-012 §7).
        assert_eq!(
            state.rng_counter as usize,
            state.dice.len(),
            "seed {seed}: dice journal invariant"
        );
        // No two live ships share a cell; dead ships keep hp 0.
        let mut occupied = std::collections::HashSet::new();
        for ship in &state.ships {
            if ship.alive {
                assert!(
                    occupied.insert((ship.q, ship.r)),
                    "seed {seed}: cell collision"
                );
                assert!(ship.hp > 0, "seed {seed}: alive ship has hp > 0");
            } else {
                assert_eq!(ship.hp, 0, "seed {seed}: destroyed hp capped");
            }
        }
        // The journal ends with exactly one MatchEnded.
        assert_eq!(
            events
                .iter()
                .filter(|e| e["type"] == "MatchEnded")
                .count(),
            1,
            "seed {seed}: single MatchEnded"
        );
        // Replay from scratch reproduces the final hash.
        let (replayed, _) = replay(&config(seed), &commands).unwrap();
        assert_eq!(
            state_hash(&replayed),
            state_hash(&state),
            "seed {seed}: replay hash"
        );
    }
}

#[test]
fn mid_match_snapshot_roundtrip_keeps_hash() {
    let (state, _) = create_match(&config(42)).unwrap();
    let mut current = state;
    for step in 0..25 {
        let legal = legal_actions(&current);
        let command = legal[0].clone();
        let (_, next) = apply_command(&current, &command).unwrap();
        current = next;
        if step == 12 {
            let restored = restore_snapshot(&snapshot_bytes(&current)).unwrap();
            assert_eq!(
                state_hash(&restored),
                state_hash(&current),
                "restore round-trip"
            );
            // The restored copy accepts the same next command identically.
            let next_legal = legal_actions(&current);
            let (_, from_original) = apply_command(&current, &next_legal[0]).unwrap();
            let (_, from_restored) = apply_command(&restored, &next_legal[0]).unwrap();
            assert_eq!(state_hash(&from_original), state_hash(&from_restored));
        }
    }
}

#[test]
fn combat_v31_dice_order_and_strength_fields() {
    // ADR-014 §3 pin: per attack — combat_attacker_dice × d6 (role
    // "attacker", one DieRolled each), optional vulture d2 + reroll of the
    // first natural 1, then combat_defender_dice × d6 (role "defender"); all
    // combat rolls precede the two StrengthCalculated events, which carry the
    // faces array "dice" and "flat_bonus" (defender = config, attacker = 0).
    let ruleset = game_core::cards::default_ruleset();
    let attacker_dice = ruleset.game.combat_attacker_dice.max(1) as usize;
    let defender_dice = ruleset.game.combat_defender_dice.max(1) as usize;
    let flat_bonus = ruleset.game.combat_defender_flat_bonus;

    let mut attacks = 0usize;
    let mut rerolls = 0usize;
    for seed in 0..=50 {
        let (_state, events, _commands) = common::play_random_match(seed);
        let mut dice_seen = 0usize; // rng_index restarts with every match
        let mut i = 0;
        while i < events.len() {
            if events[i]["type"] == "DieRolled" {
                assert_eq!(events[i]["rng_index"], dice_seen as i64, "seed {seed}: rng_index");
                dice_seen += 1;
            }
            if events[i]["type"] != "AttackDeclared" {
                i += 1;
                continue;
            }
            attacks += 1;
            i += 1;
            // Combat rolls with optional hero reaction windows (ADR-016 §3.5)
            // between the attacker and defender dice.
            let mut combat: Vec<&Value> = Vec::new();
            while events[i]["type"] != "StrengthCalculated" {
                if events[i]["type"] == "DieRolled" {
                    assert_eq!(events[i]["rng_index"], dice_seen as i64, "seed {seed}: rng_index");
                    dice_seen += 1;
                    combat.push(&events[i]);
                } else {
                    assert!(
                        matches!(events[i]["type"].as_str(), Some("ReactionWindow" | "ReactionSkipped")),
                        "seed {seed}: only reaction events may interrupt combat rolls"
                    );
                }
                i += 1;
            }
            assert!(combat.len() >= attacker_dice + defender_dice, "seed {seed}: combat rolls present");
            let split = combat.len() - defender_dice;
            let (pre_att, pre_def) = combat.split_at(split);
            for die in pre_def {
                assert_eq!(die["sides"], 6, "seed {seed}: defender d6");
                assert_eq!(die["role"], "defender", "seed {seed}: defender role");
            }
            for die in pre_att {
                assert_eq!(die["role"], "attacker", "seed {seed}: attacker role");
            }
            let d6_count = pre_att.iter().filter(|d| d["sides"] == 6).count();
            let d2_count = pre_att.iter().filter(|d| d["sides"] == 2).count();
            assert!(d2_count <= 1, "seed {seed}: at most one vulture d2");
            if d2_count == 0 {
                assert_eq!(d6_count, attacker_dice, "seed {seed}: plain attacker dice");
            } else {
                // d2 gate after the opening dice; the reroll d6 follows only
                // on success (2) — the gate may legitimately fail (1).
                assert!(
                    d6_count == attacker_dice || d6_count == attacker_dice + 1,
                    "seed {seed}: gate pattern"
                );
                assert_eq!(pre_att.len(), d6_count + 1, "seed {seed}: gate pattern");
                if d6_count == attacker_dice + 1 {
                    rerolls += 1;
                }
            }
            // StrengthCalculated (attacker, defender) with the v3.1 fields.
            let att = &events[i];
            let def = &events[i + 1];
            let faces = |v: &Value| -> Vec<i64> {
                v["dice"]
                    .as_array()
                    .expect("dice array")
                    .iter()
                    .map(|f| f.as_i64().expect("face"))
                    .collect()
            };
            let faces_a = faces(att);
            let faces_d = faces(def);
            assert_eq!(faces_a.len(), attacker_dice, "seed {seed}: attacker faces");
            assert_eq!(faces_d.len(), defender_dice, "seed {seed}: defender faces");
            assert_eq!(att["die"].as_i64().unwrap(), faces_a.iter().sum::<i64>());
            assert_eq!(def["die"].as_i64().unwrap(), faces_d.iter().sum::<i64>());
            let attacker_flat = att["flat_bonus"].as_i64().unwrap();
            assert!(
                matches!(attacker_flat, 0 | 1),
                "seed {seed}: attacker flat is 0 or Phasma's +1"
            );
            assert_eq!(
                def["flat_bonus"].as_i64().unwrap(),
                flat_bonus,
                "seed {seed}: defender flat bonus"
            );
            assert_eq!(def["range_penalty"].as_i64().unwrap(), 0);
            let total_a = 0i64.max(
                0i64.max(att["die"].as_i64().unwrap() + attacker_flat + att["arc_bonus"].as_i64().unwrap())
                    - att["range_penalty"].as_i64().unwrap(),
            );
            let total_d = 0i64.max(
                def["die"].as_i64().unwrap() + flat_bonus + def["arc_bonus"].as_i64().unwrap(),
            );
            assert_eq!(att["total"].as_i64().unwrap(), total_a);
            assert_eq!(def["total"].as_i64().unwrap(), total_d);
            i += 2;
        }
    }
    assert!(attacks > 0, "the seed scan must cover attacks");
    assert!(rerolls > 0, "the seed scan must cover a vulture reroll");
    println!("COMBAT V3.1: {attacks} attacks, {rerolls} vulture rerolls over seeds 0..=50");
}

#[test]
fn error_codes_are_pinned() {
    let (state, _) = create_match(&config(3)).unwrap();
    // Wrong ship owner (a real ship of another seat).
    let enemy = state
        .ships
        .iter()
        .find(|s| s.seat != state.active_seat)
        .unwrap();
    let rejection = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: enemy.id.clone(),
        },
    )
    .unwrap_err();
    assert_eq!(rejection.code, "not_your_seat");
    // Unknown ship.
    let rejection = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: "missing".into(),
        },
    )
    .unwrap_err();
    assert_eq!(rejection.code, "unknown_ship");
    // Move without an active ship.
    let rejection = apply_command(&state, &Command::Move { dir: 0 }).unwrap_err();
    assert_eq!(rejection.code, "not_active_ship");
    // Unknown command type at the JSON boundary.
    let parsed: Result<Command, _> = serde_json::from_str(r#"{"type":"Warp"}"#);
    assert!(parsed.is_err());
}
