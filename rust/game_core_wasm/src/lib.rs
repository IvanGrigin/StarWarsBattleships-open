//! WASM bindings for `game_core` — the browser demo talks to the real rules
//! core through this thin JSON-in/JSON-out layer. The ruleset v3 data is
//! embedded at compile time (no filesystem in the browser).
//!
//! Semantics are identical to the desktop core; see docs/contracts/core-api.md
//! and docs/contracts/rust-core-api.md. Contract for the frontend:
//!   swb.create_match(seed /*u32*/, round_limit /*u32*/) -> state JSON string
//!   swb.legal_actions(state_json)                       -> JSON array string
//!   swb.apply_command(state_json, cmd_json)             -> {"ok","events","state"}
//!                                                          or {"ok":false,"error"}
//!   swb.state_hash(state_json)                          -> 16 hex chars
use std::sync::OnceLock;

use game_core::cards::{self, Ruleset};
use game_core::engine::{self, Command, MatchConfig, MatchState};
use serde_json::{json, Value};
use wasm_bindgen::prelude::*;

const SHIP_FILES: &[(&str, &str)] = &[
    ("death_star_1.json", include_str!("../../../data/rulesets/v3/ships/death_star_1.json")),
    ("eta2_actis.json", include_str!("../../../data/rulesets/v3/ships/eta2_actis.json")),
    ("ghost.json", include_str!("../../../data/rulesets/v3/ships/ghost.json")),
    ("millennium_falcon.json", include_str!("../../../data/rulesets/v3/ships/millennium_falcon.json")),
    ("phantom.json", include_str!("../../../data/rulesets/v3/ships/phantom.json")),
    ("slave_1.json", include_str!("../../../data/rulesets/v3/ships/slave_1.json")),
    ("star_destroyer.json", include_str!("../../../data/rulesets/v3/ships/star_destroyer.json")),
    ("tie_advanced_x1.json", include_str!("../../../data/rulesets/v3/ships/tie_advanced_x1.json")),
    ("tie_fighter.json", include_str!("../../../data/rulesets/v3/ships/tie_fighter.json")),
    ("vulture_droid.json", include_str!("../../../data/rulesets/v3/ships/vulture_droid.json")),
    ("xwing_t65.json", include_str!("../../../data/rulesets/v3/ships/xwing_t65.json")),
];

// Hero cards v3.3 (ADR-016); embedded like the ships.
const HERO_FILES: &[(&str, &str)] = &[
    ("anakin.json", include_str!("../../../data/rulesets/v3/heroes/anakin.json")),
    ("boba_fett.json", include_str!("../../../data/rulesets/v3/heroes/boba_fett.json")),
    ("darth_vader.json", include_str!("../../../data/rulesets/v3/heroes/darth_vader.json")),
    ("han_solo.json", include_str!("../../../data/rulesets/v3/heroes/han_solo.json")),
    ("jango_fett.json", include_str!("../../../data/rulesets/v3/heroes/jango_fett.json")),
    ("luke.json", include_str!("../../../data/rulesets/v3/heroes/luke.json")),
    ("obi_wan.json", include_str!("../../../data/rulesets/v3/heroes/obi_wan.json")),
    ("phasma.json", include_str!("../../../data/rulesets/v3/heroes/phasma.json")),
];

fn ruleset() -> &'static Ruleset {
    static RULESET: OnceLock<Ruleset> = OnceLock::new();
    RULESET.get_or_init(|| {
        let game: Value = serde_json::from_str(include_str!("../../../data/rulesets/v3/game.json"))
            .expect("embedded game.json");
        let board: Value = serde_json::from_str(include_str!("../../../data/rulesets/v3/board.json"))
            .expect("embedded board.json");
        let ships: Vec<Value> = SHIP_FILES
            .iter()
            .map(|(name, src)| {
                serde_json::from_str(src).unwrap_or_else(|e| panic!("embedded {}: {}", name, e))
            })
            .collect();
        let scenario: Value = serde_json::from_str(include_str!(
            "../../../data/rulesets/v3/scenarios/classic_2v2.json"
        ))
        .expect("embedded classic_2v2.json");
        let heroes: Vec<(String, Value)> = HERO_FILES
            .iter()
            .map(|(name, src)| {
                let value: Value = serde_json::from_str(src)
                    .unwrap_or_else(|e| panic!("embedded {}: {}", name, e));
                (name.trim_end_matches(".json").to_string(), value)
            })
            .collect();
        cards::ruleset_from_values(
            game,
            board,
            ships,
            vec![("classic_2v2".to_string(), scenario)],
            heroes,
        )
        .expect("embedded ruleset v3")
    })
}

fn parse_state(state_json: &str) -> Result<MatchState, JsValue> {
    serde_json::from_str(state_json)
        .map_err(|e| JsValue::from_str(&format!("bad state json: {}", e)))
}

fn dump(value: &Value) -> Result<String, JsValue> {
    serde_json::to_string(value).map_err(|e| JsValue::from_str(&format!("serialize: {}", e)))
}

#[wasm_bindgen]
pub fn version() -> String {
    "swb-demo-v1".to_string()
}

#[wasm_bindgen]
pub fn ruleset_hash() -> String {
    ruleset().ruleset_hash.clone()
}

#[wasm_bindgen]
pub fn create_match(seed: u32, round_limit: u32) -> Result<String, JsValue> {
    let config = MatchConfig {
        seed: seed as i64,
        round_limit: round_limit as i64,
        ..Default::default()
    };
    let (state, _) = engine::create_match_with(&config, ruleset()).map_err(|e| JsValue::from_str(&e))?;
    dump(&engine::state_value(&state))
}

#[wasm_bindgen]
pub fn legal_actions(state_json: &str) -> Result<String, JsValue> {
    let state = parse_state(state_json)?;
    dump(&serde_json::to_value(engine::legal_actions_with(&state, ruleset())).expect("commands json"))
}

/// Result is ALWAYS a JSON object string: {"ok":true,"events":[...],"state":{...}}
/// or {"ok":false,"error":"code","detail":"..."}. Illegal commands never throw —
/// the frontend must read the `ok` field.
#[wasm_bindgen]
pub fn apply_command(state_json: &str, cmd_json: &str) -> Result<String, JsValue> {
    let state = parse_state(state_json)?;
    let command: Command = serde_json::from_str(cmd_json)
        .map_err(|e| JsValue::from_str(&format!("bad command json: {}", e)))?;
    match engine::apply_command_with(&state, &command, ruleset()) {
        Ok((events, new_state)) => dump(&json!({
            "ok": true,
            "events": events,
            "state": engine::state_value(&new_state),
        })),
        Err(rej) => dump(&json!({
            "ok": false,
            "error": rej.code,
            "detail": rej.detail,
        })),
    }
}

#[wasm_bindgen]
pub fn state_hash(state_json: &str) -> Result<String, JsValue> {
    let state = parse_state(state_json)?;
    Ok(engine::state_hash(&state))
}

#[wasm_bindgen]
pub fn is_terminal(state_json: &str) -> Result<bool, JsValue> {
    let state = parse_state(state_json)?;
    Ok(engine::is_terminal(&state))
}
