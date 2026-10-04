//! Differential oracle test (RUST-CORE): for every corpus line produced by
//! tools/export_diff_corpus.gd (GDScript prototype, RandomLegal bots), the
//! same seed + the same commands must reproduce the same state_hash in
//! game_core. 100/100 matches are mandatory.

use game_core::{create_match, is_terminal, apply_command, state_hash, Command, MatchConfig};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::time::Instant;

fn corpus_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/golden/diff_corpus_100.jsonl")
}

struct CorpusLine {
    seed: i64,
    round_limit: i64,
    commands: Vec<Command>,
    final_hash: String,
    saw_special: bool,
}

fn parse_line(line: &str, index: usize) -> CorpusLine {
    let value: Value = serde_json::from_str(line)
        .unwrap_or_else(|e| panic!("line {index}: bad JSON: {e}"));
    let commands: Vec<Command> = value["commands"]
        .as_array()
        .expect("commands array")
        .iter()
        .map(|c| serde_json::from_value(c.clone()).expect("command shape"))
        .collect();
    CorpusLine {
        seed: value["seed"].as_i64().expect("seed"),
        round_limit: value["round_limit"].as_i64().expect("round_limit"),
        commands,
        final_hash: value["final_hash"].as_str().expect("final_hash").to_string(),
        saw_special: value["saw_special"].as_bool().expect("saw_special"),
    }
}

fn replay_line(line: &CorpusLine, index: usize) {
    let config = MatchConfig {
        seed: line.seed,
        round_limit: line.round_limit,
        ..MatchConfig::default()
    };
    let (mut state, mut events) =
        create_match(&config).unwrap_or_else(|e| panic!("line {index}: create failed: {e}"));
    for (i, command) in line.commands.iter().enumerate() {
        match apply_command(&state, command) {
            Ok((mut command_events, new_state)) => {
                events.append(&mut command_events);
                state = new_state;
            }
            Err(rejection) => panic!(
                "line {index} (seed {}): command {i} rejected: {} ({})",
                line.seed, rejection.code, rejection.detail
            ),
        }
    }
    assert!(
        is_terminal(&state),
        "line {index} (seed {}): match must be over after all commands",
        line.seed
    );
    let hash = state_hash(&state);
    assert_eq!(
        hash, line.final_hash,
        "line {index} (seed {}): state_hash mismatch",
        line.seed
    );
    // saw_special flag must agree with the Rust event journal (ADR-012).
    let rust_special = events.iter().any(|e| {
        matches!(e["type"].as_str(), Some("ShipTransformed") | Some("ShipRevived"))
    });
    assert_eq!(
        rust_special, line.saw_special,
        "line {index} (seed {}): saw_special mismatch",
        line.seed
    );
}

#[test]
fn differential_corpus_100_matches() {
    let text = std::fs::read_to_string(corpus_path())
        .expect("tests/golden/diff_corpus_100.jsonl readable (generate via tools/export_diff_corpus.gd)");
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    assert_eq!(lines.len(), 100, "corpus must contain exactly 100 matches");

    let started = Instant::now();
    let mut passed = 0;
    for (index, line) in lines.iter().enumerate() {
        let parsed = parse_line(line, index);
        replay_line(&parsed, index);
        passed += 1;
    }
    let elapsed = started.elapsed().as_secs_f64();
    println!("DIFFERENTIAL: {passed}/100 matches reproduced the GDScript final_hash");
    println!(
        "REPLAY SPEED: {elapsed:.3}s for {passed} matches = {:.1} matches/sec",
        f64::from(passed) / elapsed
    );
    assert_eq!(passed, 100, "differential 100/100 required");
}

#[test]
fn differential_command_shapes_are_pinned() {
    // The corpus commands must deserialize strictly via the Command enum.
    let begin: Command = serde_json::from_value(json!({
        "type": "BeginActivation", "ship_instance_id": "A1_tie_fighter_0"
    }))
    .unwrap();
    assert_eq!(
        serde_json::to_value(&begin).unwrap(),
        json!({"type": "BeginActivation", "ship_instance_id": "A1_tie_fighter_0"})
    );
    // v3.4 (ADR-017): the corpus Move command is {"type":"Move","dir":N}.
    let mv: Command = serde_json::from_value(json!({"type": "Move", "dir": 2})).unwrap();
    assert_eq!(mv, Command::Move { dir: 2 });
    assert_eq!(serde_json::to_value(&mv).unwrap(), json!({"type": "Move", "dir": 2}));
    // Out-of-range dirs must deserialize (i64 field) and be rejected by the
    // engine with bad_direction, never fail at the serde boundary.
    let bad: Command = serde_json::from_value(json!({"type": "Move", "dir": -1})).unwrap();
    assert_eq!(bad, Command::Move { dir: -1 });
    let attack: Command = serde_json::from_value(json!({
        "type": "DeclareAttack", "target_ship_instance_id": "B1_tie_fighter_0"
    }))
    .unwrap();
    assert_eq!(
        serde_json::to_value(&attack).unwrap(),
        json!({"type": "DeclareAttack", "target_ship_instance_id": "B1_tie_fighter_0"})
    );
}
