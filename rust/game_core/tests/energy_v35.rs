//! Energy v3.5 (ADR-018) engine pins, mirroring the GDScript oracle unit
//! tests (tests/unit/test_engine_commands.gd, test_heroes.gd,
//! test_engine_specials.gd): the end-of-round charge REWRITE instead of the
//! old "+1 per activation", the per-ship spent_round tally, the
//! ChargesRefreshed event batch and its "none" opt-out.

mod common;

use game_core::{
    apply_command, apply_command_with, create_match, create_match_with, is_terminal,
    legal_actions, restore_snapshot, snapshot_bytes, state_hash, state_value, Command,
    MatchConfig, MatchState, Ruleset, STATE_VERSION,
};
use serde_json::Value;

fn config(seed: i64) -> MatchConfig {
    MatchConfig {
        seed,
        ..MatchConfig::default()
    }
}

/// Same round-cycling as the GDScript test helper _advance_round_events:
/// every idle ship of the active seat begins and immediately (or after the
/// scripted commands) ends its activation; returns the state of
/// `target_round` with all applied events merged.
fn advance_round_events(
    start: &MatchState,
    target_round: i64,
    ruleset: &Ruleset,
) -> (MatchState, Vec<Value>) {
    let mut st = start.clone();
    let mut merged: Vec<Value> = Vec::new();
    let mut guard = 0;
    while (st.round < target_round || st.active_ship.is_some()) && !is_terminal(&st) {
        let command = if st.active_ship.is_none() {
            let ship_id = st
                .ships
                .iter()
                .find(|s| s.seat == st.active_seat && s.alive && !s.activated)
                .map(|s| s.id.clone())
                .expect("advance_round: idle ship found for seat");
            Command::BeginActivation {
                ship_instance_id: ship_id,
            }
        } else {
            Command::EndActivation
        };
        let (events, next) =
            apply_command_with(&st, &command, ruleset).expect("advance_round apply");
        merged.extend(events);
        st = next;
        guard += 1;
        assert!(guard <= 128, "advance_round did not converge");
    }
    (st, merged)
}

/// The ChargesRefreshed event of `instance_id` inside a merged event list.
fn refresh_event_for<'a>(events: &'a [Value], instance_id: &str) -> &'a Value {
    events
        .iter()
        .find(|e| e["type"] == "ChargesRefreshed" && e["ship_instance_id"] == instance_id)
        .expect("ChargesRefreshed event for ship")
}

fn refresh_events(events: &[Value]) -> Vec<&Value> {
    events
        .iter()
        .filter(|e| e["type"] == "ChargesRefreshed")
        .collect()
}

#[test]
fn state_version_is_4_and_ships_carry_spent_round() {
    let (state, events) = create_match(&config(42)).unwrap();
    assert_eq!(STATE_VERSION, 4);
    assert_eq!(state.version, 4, "state version 4 (ADR-018)");
    assert!(
        state.ships.iter().all(|s| s.spent_round == 0),
        "spent_round present and 0 for all ships (ADR-018)"
    );
    // The snapshot JSON carries the field with the oracle serde name.
    let snapshot = state_value(&state);
    assert_eq!(snapshot["ships"][0]["spent_round"], 0);
    assert!(events
        .iter()
        .all(|e| e["type"] != "ChargesRefreshed"), "no refresh before a round completes");
}

#[test]
fn activation_end_adds_no_charge_and_move_rotate_feed_the_tally() {
    let (state, _) = create_match(&config(42)).unwrap();
    let spender = state.ships[0].id.clone();
    let (events, st) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
    )
    .unwrap();
    let activation_started = events
        .iter()
        .find(|e| e["type"] == "ActivationStarted")
        .unwrap();
    assert_eq!(activation_started["charges"], 3, "ActivationStarted charges");
    // Rotate: 3 -> 2 charges, tally 1.
    let (_, st) = apply_command(&st, &Command::RotateLeft).unwrap();
    // Move: 2 -> 1 charge, tally 2.
    let legal = legal_actions(&st);
    let dir = match legal.first().expect("a legal action") {
        Command::Move { dir } => *dir,
        other => panic!("expected Move first, got {other:?}"),
    };
    let (_, st) = apply_command(&st, &Command::Move { dir }).unwrap();
    let ship = st.ships.iter().find(|s| s.id == spender).unwrap();
    assert_eq!(ship.charges, 1, "two spends, one charge left");
    assert_eq!(ship.spent_round, 2, "rotate + move feed the tally");
    // EndActivation keeps the charges (v3.5: no +1 recovery).
    let (events, st) = apply_command(&st, &Command::EndActivation).unwrap();
    let ended = events
        .iter()
        .find(|e| e["type"] == "ActivationEnded")
        .unwrap();
    assert_eq!(ended["charges"], 1, "ActivationEnded reports the ACTUAL count");
    let ship = st.ships.iter().find(|s| s.id == spender).unwrap();
    assert_eq!(ship.charges, 1, "no recovery on the ship");
    assert_eq!(ship.spent_round, 2, "tally survives until RoundStarted");
    assert_eq!(ship.activated, true, "activated flag set");
}

#[test]
fn end_of_round_rewrite_spender_gets_half_saver_gets_full() {
    // (a)+(b): after round 1 the spender is overwritten with ceil(5/2)=3
    // (full=false), every ship that spent nothing gets the full 5
    // (full=true); one ChargesRefreshed per living ship, in ships order,
    // immediately before RoundStarted(2).
    let ruleset = game_core::cards::default_ruleset();
    let (state, _) = create_match(&config(42)).unwrap();
    let spender = state.ships[0].id.clone();
    // After the spender's EndActivation the turn passes to B1, so the saver
    // is B1's first ship.
    let saver = state.ships[3].id.clone();
    let (_, st) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
    )
    .unwrap();
    let (_, st) = apply_command(&st, &Command::RotateLeft).unwrap();
    let (_, st) = apply_command(&st, &Command::EndActivation).unwrap();
    let (_, st) = apply_command(
        &st,
        &Command::BeginActivation {
            ship_instance_id: saver.clone(),
        },
    )
    .unwrap();
    let (_, st) = apply_command(&st, &Command::EndActivation).unwrap();
    let (st2, events) = advance_round_events(&st, 2, ruleset);
    assert_eq!(st2.round, 2);
    assert_eq!(
        events.last().map(|e| e["type"].as_str().unwrap()),
        Some("RoundStarted"),
        "refresh batch precedes RoundStarted(2)"
    );
    assert_eq!(events.last().unwrap()["round"], 2);
    let refreshed = refresh_events(&events);
    assert_eq!(refreshed.len(), 6, "one ChargesRefreshed per living ship");
    // (a) the spender is overwritten with ceil(5/2)=3, full=false.
    let spent_ev = refresh_event_for(&events, &spender);
    assert_eq!(spent_ev["charges"], 3, "spender refreshed to ceil(5/2)=3");
    assert_eq!(spent_ev["full"], false, "spender event full=false");
    let ship = st2.ships.iter().find(|s| s.id == spender).unwrap();
    assert_eq!(ship.charges, 3, "ship stores 3 charges");
    // (b) the saver is overwritten with the full 5, full=true.
    let saved_ev = refresh_event_for(&events, &saver);
    assert_eq!(saved_ev["charges"], 5, "saver refreshed to the full 5");
    assert_eq!(saved_ev["full"], true, "saver event full=true");
    let ship = st2.ships.iter().find(|s| s.id == saver).unwrap();
    assert_eq!(ship.charges, 5, "ship stores 5 charges");
    // Event order follows the ships array order (ADR-018).
    let ev_order: Vec<&str> = refreshed
        .iter()
        .map(|e| e["ship_instance_id"].as_str().unwrap())
        .collect();
    let living_order: Vec<&str> = st2
        .ships
        .iter()
        .filter(|s| s.alive)
        .map(|s| s.id.as_str())
        .collect();
    assert_eq!(ev_order, living_order, "refresh order follows the ships array");
    // The rewrite consumes no RNG: the dice log is untouched (empty here).
    assert_eq!(st2.rng_counter, 0, "no dice consumed by the rewrite");
}

#[test]
fn round_start_resets_the_tally_and_a_second_spender_stays_at_half() {
    // (c): RoundStarted zeroes every ship's spent_round; a ship that spends
    // again in round 2 is refreshed to ceil = 3 once more.
    let ruleset = game_core::cards::default_ruleset();
    let (state, _) = create_match(&config(42)).unwrap();
    let spender = state.ships[0].id.clone();
    let (_, st) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
    )
    .unwrap();
    let (_, st) = apply_command(&st, &Command::RotateLeft).unwrap();
    let (_, st) = apply_command(&st, &Command::EndActivation).unwrap();
    let (st2, _) = advance_round_events(&st, 2, ruleset);
    assert!(
        st2.ships.iter().all(|s| s.spent_round == 0),
        "spent_round is 0 for every ship in the new round"
    );
    // Round 2: the same ship spends one rotation and ends; round 2 refreshes
    // it back to half again.
    let (_, st) = apply_command(
        &st2,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
    )
    .unwrap();
    let (_, st) = apply_command(&st, &Command::RotateRight).unwrap();
    let (_, st) = apply_command(&st, &Command::EndActivation).unwrap();
    let (st3, events) = advance_round_events(&st, 3, ruleset);
    let spent_ev = refresh_event_for(&events, &spender);
    assert_eq!(spent_ev["charges"], 3, "round-2 spender refreshed to 3 again");
    assert_eq!(spent_ev["full"], false);
    assert!(
        st3.ships.iter().all(|s| s.spent_round == 0),
        "tally reset again at RoundStarted(3)"
    );
}

#[test]
fn dead_ships_get_no_refresh_and_keep_their_dying_charges() {
    // (d): a destroyed ship receives no ChargesRefreshed, keeps the charges
    // it died with, but its tally still resets at RoundStarted (every ship's
    // does). Also: EndActivation of a dying attacker adds no charge either.
    let ruleset = game_core::cards::default_ruleset();
    let (state, _) = create_match(&config(42)).unwrap();
    let corpse_id = state.ships[3].id.clone(); // first B1 ship
    let mut st = state.clone();
    let corpse = &mut st.ships[3];
    corpse.alive = false; // test-owned death mid-round
    corpse.charges = 1; // dying charges pinned for the assertion
    corpse.spent_round = 4; // dead ships keep whatever tally they died with
    let (st2, events) = advance_round_events(&st, 2, ruleset);
    for e in refresh_events(&events) {
        assert_ne!(
            e["ship_instance_id"], corpse_id,
            "dead ship is never refreshed"
        );
    }
    let corpse = st2.ships.iter().find(|s| s.id == corpse_id).unwrap();
    assert_eq!(corpse.charges, 1, "dead ship keeps its charges");
    assert_eq!(
        corpse.spent_round, 0,
        "RoundStarted resets the tally of every ship, dead included"
    );
    assert_eq!(corpse.alive, false, "corpse stays dead");
    assert_eq!(refresh_events(&events).len(), 5, "5 living ships refreshed");

    // A dead ACTIVE ship may only pass the turn; EndActivation grants it
    // nothing.
    let (fresh, _) = create_match(&config(42)).unwrap();
    let doomed = fresh.ships[0].id.clone();
    let (_, st) = apply_command(
        &fresh,
        &Command::BeginActivation {
            ship_instance_id: doomed.clone(),
        },
    )
    .unwrap();
    let mut st = st;
    let ship = &mut st.ships[0];
    ship.alive = false; // test-owned death mid-activation
    ship.charges = 0;
    let (events, st) = apply_command(&st, &Command::EndActivation).unwrap();
    let ended = events
        .iter()
        .find(|e| e["type"] == "ActivationEnded")
        .unwrap();
    assert_eq!(ended["charges"], 0);
    let ship = st.ships.iter().find(|s| s.id == doomed).unwrap();
    assert_eq!(ship.charges, 0, "no recovery for a dead ship at EndActivation");
}

#[test]
fn ceil_formula_for_a_nonstandard_card_maximum() {
    // (e, test-owned tuning): with max_charges 4 on every card, the spender
    // is refreshed to ceil(4/2)=2 (full=false) and the saver to the full 4
    // (full=true) — the maximum is read per ship card at rewrite time.
    let mut ruleset = game_core::cards::default_ruleset().clone();
    for def in ruleset.ships.values_mut() {
        def.max_charges = 4;
    }
    let (state, _) = create_match_with(&config(42), &ruleset).unwrap();
    let spender = state.ships[0].id.clone();
    // After the spender's EndActivation the turn passes to B1, so the saver
    // is B1's first ship.
    let saver = state.ships[3].id.clone();
    let (_, st) = apply_command_with(
        &state,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
        &ruleset,
    )
    .unwrap();
    let (_, st) = apply_command_with(&st, &Command::RotateLeft, &ruleset).unwrap();
    let (_, st) = apply_command_with(&st, &Command::EndActivation, &ruleset).unwrap();
    let (_, st) = apply_command_with(
        &st,
        &Command::BeginActivation {
            ship_instance_id: saver.clone(),
        },
        &ruleset,
    )
    .unwrap();
    let (_, st) = apply_command_with(&st, &Command::EndActivation, &ruleset).unwrap();
    let (st2, events) = advance_round_events(&st, 2, &ruleset);
    let tuned_ev = refresh_event_for(&events, &spender);
    assert_eq!(tuned_ev["charges"], 2, "spender: ceil(4/2)=2");
    assert_eq!(tuned_ev["full"], false, "spender event full=false");
    let idle_ev = refresh_event_for(&events, &saver);
    assert_eq!(idle_ev["charges"], 4, "saver: full 4 from the tuned card");
    assert_eq!(idle_ev["full"], true, "saver event full=true");
    assert!(st2.ships.iter().all(|s| s.charges == 2 || s.charges == 4));
}

#[test]
fn transform_carries_spent_round_into_the_phantom() {
    // Ghost -> Phantom (ADR-012/013 D2) keeps the spend tally (ADR-018 D2):
    // a tuned ghost with spent_round 1 that transforms stores the counter in
    // the phantom.
    for seed in 0..200i64 {
        let (state, _) = create_match(&config(seed)).unwrap();
        let Some(attacker) = state
            .ships
            .iter()
            .find(|s| s.seat == state.active_seat && s.alive && !s.activated)
            .cloned()
        else {
            continue;
        };
        let Some(ghost_pos) = state.ships.iter().position(|s| s.type_id == "ghost") else {
            continue;
        };
        let ghost = state.ships[ghost_pos].clone();
        if attacker.team == ghost.team {
            continue;
        }
        // Park the ghost on a free neighboring cell of the attacker.
        let target_cell = game_core::hex::neighbors(attacker.q as i32, attacker.r as i32)
            .into_iter()
            .find(|&(nq, nr)| {
                game_core::hex::in_board(nq, nr, 3)
                    && !state
                        .ships
                        .iter()
                        .any(|s| s.alive && s.q == i64::from(nq) && s.r == i64::from(nr))
            });
        let Some((gq, gr)) = target_cell else {
            continue;
        };
        let mut st = state.clone();
        {
            let ghost = &mut st.ships[ghost_pos];
            ghost.q = i64::from(gq);
            ghost.r = i64::from(gr);
            ghost.hp = 1; // any damage transforms
            ghost.shield = 0;
            ghost.charges = 2;
            ghost.spent_round = 1; // v3.5 tuning: the tally must carry over
        }
        let Ok((_, st)) = apply_command(
            &st,
            &Command::BeginActivation {
                ship_instance_id: attacker.id.clone(),
            },
        ) else {
            continue;
        };
        let Ok((events, st)) = apply_command(
            &st,
            &Command::DeclareAttack {
                target_ship_instance_id: ghost.id.clone(),
            },
        ) else {
            continue;
        };
        let Some(transformed) = events.iter().find(|e| e["type"] == "ShipTransformed") else {
            continue; // dice did not kill the ghost: try the next seed
        };
        assert_eq!(transformed["to_type"], "phantom", "seed {seed}");
        let phantom = st.ships.iter().find(|s| s.id == ghost.id).unwrap();
        assert_eq!(
            phantom.spent_round, 1,
            "seed {seed}: spent_round carries into the phantom (v3.5, ADR-018 D2)"
        );
        assert_eq!(phantom.charges, 2, "seed {seed}: charges capped at 2");
        assert_eq!(phantom.hp, 2, "seed {seed}: phantom enters at full hp");
        return;
    }
    panic!("no ghost transform found in seeds 0..=200");
}

#[test]
fn hyperjump_zeroing_feeds_the_tally() {
    // Han's hyperjump zeroes the charges; v3.5 counts the zeroing as a spend:
    // spent_round += charges before the rewrite, so the jumper is refreshed
    // with ceil(5/2)=3 (full=false) and never with the full tank.
    let ruleset = game_core::cards::default_ruleset();
    let mut jumper_seed: Option<i64> = None;
    for seed in 0..100i64 {
        let (state, _) = create_match(&config(seed)).unwrap();
        if state
            .heroes
            .get("A1")
            .map(|h| h.hero_id == "han_solo")
            .unwrap_or(false)
        {
            jumper_seed = Some(seed);
            break;
        }
    }
    let Some(seed) = jumper_seed else {
        panic!("no han_solo-on-A1 seed in 0..100");
    };
    let (state, _) = create_match(&config(seed)).unwrap();
    let jumper = state.ships[0].id.clone();
    let mut st = state.clone();
    st.seeded_bots_skip_heroes = false; // expose hero commands (test-only)
    let (_, st) = apply_command(
        &st,
        &Command::BeginActivation {
            ship_instance_id: jumper.clone(),
        },
    )
    .unwrap();
    let jump = legal_actions(&st)
        .into_iter()
        .find_map(|c| match c {
            Command::UseHeroAbility {
                ability_id,
                q: Some(q),
                r: Some(r),
                ..
            } if ability_id == "hyperjump" => Some((q, r)),
            _ => None,
        })
        .expect("han_solo offers a hyperjump");
    let (_, st) = apply_command(
        &st,
        &Command::UseHeroAbility {
            ability_id: "hyperjump".to_string(),
            target_ship_instance_id: None,
            ship_instance_id: None,
            dir: None,
            q: Some(jump.0),
            r: Some(jump.1),
            die_index: None,
            value: None,
        },
    )
    .unwrap();
    let ship = st.ships.iter().find(|s| s.id == jumper).unwrap();
    assert_eq!(ship.charges, 0, "charges zeroed by the jump");
    assert_eq!(
        ship.spent_round, 3,
        "hyperjump zeroing counts as spent charges (v3.5, ADR-018)"
    );
    assert_eq!(st.heroes.get("A1").unwrap().uses_left, 0, "use consumed");
    // Round end: the jumper gets ceil, the untouched ships get the full tank.
    let (st2, events) = advance_round_events(&st, 2, ruleset);
    let jump_ev = refresh_event_for(&events, &jumper);
    assert_eq!(jump_ev["charges"], 3, "jumper refreshed to ceil(5/2)=3");
    assert_eq!(jump_ev["full"], false);
    assert!(st2.ships.iter().all(|s| s.spent_round == 0));
}

#[test]
fn charge_round_reset_none_skips_the_rewrite() {
    // charge_round_reset = "none" (game.json): no ChargesRefreshed at the
    // round boundary — charges stay untouched — while RoundStarted still
    // resets flags and the tally.
    let mut ruleset = game_core::cards::default_ruleset().clone();
    ruleset.game.charge_round_reset = "none".to_string();
    let (state, _) = create_match_with(&config(42), &ruleset).unwrap();
    let spender = state.ships[0].id.clone();
    let (_, st) = apply_command_with(
        &state,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
        &ruleset,
    )
    .unwrap();
    let (_, st) = apply_command_with(&st, &Command::RotateLeft, &ruleset).unwrap();
    let (_, st) = apply_command_with(&st, &Command::EndActivation, &ruleset).unwrap();
    let (st2, events) = advance_round_events(&st, 2, &ruleset);
    assert!(
        refresh_events(&events).is_empty(),
        "the rewrite is skipped entirely"
    );
    assert_eq!(
        events.last().map(|e| e["type"].as_str().unwrap()),
        Some("RoundStarted"),
        "the round still rolls over"
    );
    let ship = st2.ships.iter().find(|s| s.id == spender).unwrap();
    assert_eq!(ship.charges, 2, "spender keeps its leftover charges");
    assert_eq!(
        st2.ships[1].charges, 3,
        "untouched ships keep their initial charges"
    );
    assert!(st2.ships.iter().all(|s| s.spent_round == 0), "tally still resets");
    assert!(st2.ships.iter().all(|s| !s.activated), "flags still reset");
}

#[test]
fn round_limit_and_decided_matches_never_refresh() {
    // A match that ends at the round limit rewrites nothing: the last
    // activation ends the game with MatchEnded(round_limit) and no
    // ChargesRefreshed/RoundStarted after it. The same invariant holds for
    // elimination endings of random matches.
    let ruleset = game_core::cards::default_ruleset();
    let config = MatchConfig {
        seed: 42,
        round_limit: 1,
        ..MatchConfig::default()
    };
    let (state, _) = create_match(&config).unwrap();
    let (st, events) = advance_round_events(&state, 2, ruleset);
    assert!(is_terminal(&st), "round limit 1 ends the match");
    let last = events.last().unwrap();
    assert_eq!(last["type"], "MatchEnded");
    assert_eq!(last["reason"], "round_limit");
    assert!(last["winner"].is_null());
    assert!(refresh_events(&events).is_empty(), "no rewrite at the limit");
    assert!(events
        .iter()
        .all(|e| e["type"] != "RoundStarted" || e["round"] == 1));

    for seed in 0..10i64 {
        let (_final, journal, _commands) = common::play_random_match(seed);
        let ended_at = journal
            .iter()
            .position(|e| e["type"] == "MatchEnded")
            .expect("random match ends");
        assert!(
            journal[ended_at + 1..]
                .iter()
                .all(|e| e["type"] != "ChargesRefreshed" && e["type"] != "RoundStarted"),
            "seed {seed}: nothing follows MatchEnded"
        );
    }
}

#[test]
fn spent_round_survives_snapshot_roundtrip_and_replay() {
    let (state, _) = create_match(&config(42)).unwrap();
    let spender = state.ships[0].id.clone();
    let (_, st) = apply_command(
        &state,
        &Command::BeginActivation {
            ship_instance_id: spender.clone(),
        },
    )
    .unwrap();
    let (_, st) = apply_command(&st, &Command::RotateLeft).unwrap();
    let text = snapshot_bytes(&st);
    assert!(text.contains("spent_round"), "snapshot carries the field");
    let restored: MatchState = restore_snapshot(&text).unwrap();
    assert_eq!(state_hash(&restored), state_hash(&st), "round-trip hash");
    assert_eq!(restored.ships[0].spent_round, 1);
    // The restored copy continues identically (the tally feeds the rewrite).
    let (_, from_original) = apply_command(&st, &Command::EndActivation).unwrap();
    let (_, from_restored) = apply_command(&restored, &Command::EndActivation).unwrap();
    assert_eq!(state_hash(&from_original), state_hash(&from_restored));
}
