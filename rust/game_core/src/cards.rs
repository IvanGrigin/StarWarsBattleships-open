//! Ruleset data loading (core-api §8): `data/rulesets/v3` — game.json,
//! board.json, ships/*.json, scenarios/*.json, heroes/*.json. `ruleset_hash`
//! is computed exactly as `src/core/data/card_store.gd`: FNV-1a 64 of the
//! canonical form of `{"board":…, "game":…, "ships":{id: def}}` (scenarios and
//! heroes excluded — ADR-016 §7: hero cards are content, but the hash inputs
//! must match CardStore verbatim).

use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use crate::serialization::state_hash;

/// Special-rule ability ids (data mechanism: "abilities": [{"id", "enabled"}]).
pub const ABILITY_TRANSFORM: &str = "transform_to_phantom";
pub const ABILITY_RANGED_SHOT: &str = "ranged_shot";
pub const ABILITY_LUCKY_SHOT: &str = "lucky_shot";
pub const ABILITY_RESURRECTION: &str = "resurrection";
pub const ABILITY_REROLL_ONE: &str = "reroll_one";

#[derive(Debug, Clone)]
pub struct Ability {
    pub id: String,
    pub enabled: bool,
    pub transform_to: Option<String>,
}

/// Typed view over a ships/*.json card (defaults mirror card_store.gd users:
/// group 1, draftable, draft_cost 0, max_hp 1, max_shield 0, charges 3/5).
#[derive(Debug, Clone)]
pub struct ShipDef {
    pub id: String,
    pub group: i64,
    pub draftable: bool,
    pub draft_cost: i64,
    pub max_hp: i64,
    pub max_shield: i64,
    pub initial_charges: i64,
    pub max_charges: i64,
    pub arc_modifiers: Vec<i64>,
    pub abilities: Vec<Ability>,
}

/// Fallback for unknown type ids (prototype: `defs.get(id, {})`).
pub static EMPTY_SHIP_DEF: ShipDef = ShipDef {
    id: String::new(),
    group: 1,
    draftable: true,
    draft_cost: 0,
    max_hp: 1,
    max_shield: 0,
    initial_charges: 3,
    max_charges: 5,
    arc_modifiers: Vec::new(),
    abilities: Vec::new(),
};

/// Typed view over a heroes/*.json card (ADR-016 §1): `uses_per_match` lives
/// on the ability block (data schema v1; 0 for the passive phasma).
#[derive(Debug, Clone)]
pub struct HeroDef {
    pub id: String,
    pub uses_per_match: i64,
}

impl HeroDef {
    fn from_value(value: &Value, fallback_id: &str) -> HeroDef {
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or(fallback_id)
            .to_string();
        // Oracle CardStore/match_engine: uses = ability.uses_per_match, with a
        // top-level uses_per_match fallback and 0 when absent.
        let uses_per_match = value
            .get("ability")
            .and_then(|a| a.get("uses_per_match"))
            .or_else(|| value.get("uses_per_match"))
            .and_then(Value::as_i64)
            .unwrap_or(0);
        HeroDef { id, uses_per_match }
    }
}

impl ShipDef {
    fn from_value(value: &Value) -> Result<ShipDef, String> {
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| "ship definition has no string id".to_string())?
            .to_string();
        let abilities = value
            .get("abilities")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .map(|a| Ability {
                        id: a.get("id")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        enabled: a.get("enabled").and_then(Value::as_bool).unwrap_or(false),
                        transform_to: a
                            .get("transform_to")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                    })
                    .collect()
            })
            .unwrap_or_default();
        Ok(ShipDef {
            id,
            group: get_i64(value, "group", 1),
            draftable: value
                .get("draftable")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            draft_cost: get_i64(value, "draft_cost", 0),
            max_hp: get_i64(value, "max_hp", 1),
            max_shield: get_i64(value, "max_shield", 0),
            initial_charges: get_i64(value, "initial_charges", 3),
            max_charges: get_i64(value, "max_charges", 5),
            arc_modifiers: value
                .get("arc_modifiers")
                .and_then(Value::as_array)
                .map(|arr| arr.iter().map(|v| v.as_i64().unwrap_or(0)).collect())
                .unwrap_or_default(),
            abilities,
        })
    }

    /// True when `ability_id` is among the enabled abilities.
    pub fn has_ability(&self, ability_id: &str) -> bool {
        self.abilities
            .iter()
            .any(|a| a.id == ability_id && a.enabled)
    }

    /// arc[sector]; out of range -> 0 (match_engine._arc).
    pub fn arc(&self, sector: i64) -> i64 {
        if sector < 0 || sector as usize >= self.arc_modifiers.len() {
            return 0;
        }
        self.arc_modifiers[sector as usize]
    }
}

#[derive(Debug, Clone)]
pub struct GameRules {
    pub ruleset_id: String,
    pub fleet_size: i64,
    pub draft_budget: i64,
    pub max_group2_per_seat: i64,
    pub max_same_type_group1_per_seat: i64,
    pub round_limit: i64,
    /// Combat dice are data, not code (ADR-014 §1). The engine clamps the
    /// dice counts to >= 1 (oracle `maxi(1, …)`); the flat bonus is used raw.
    pub combat_attacker_dice: i64,
    pub combat_defender_dice: i64,
    pub combat_defender_flat_bonus: i64,
    /// v3.5 (ADR-018): end-of-round charge rewrite mode. "half_up" rewrites
    /// every living ship's charges once at the end of the round (full
    /// max_charges when nothing was spent, ceil(max_charges/2) otherwise);
    /// "none" skips the rewrite entirely.
    pub charge_round_reset: String,
    /// v3.5 (ADR-018): a ship that spent no charge this round (spent_round
    /// == 0) is rewritten to the FULL max_charges ("saved up -> full tank").
    pub charge_full_if_unused: bool,
}

impl GameRules {
    fn from_value(value: &Value) -> GameRules {
        GameRules {
            ruleset_id: value
                .get("ruleset_id")
                .and_then(Value::as_str)
                .unwrap_or("v3")
                .to_string(),
            fleet_size: get_i64(value, "fleet_size", 3),
            draft_budget: get_i64(value, "draft_budget", 17),
            max_group2_per_seat: get_i64(value, "max_group2_per_seat", 1),
            max_same_type_group1_per_seat: get_i64(value, "max_same_type_group1_per_seat", 2),
            round_limit: get_i64(value, "round_limit", 60),
            combat_attacker_dice: get_i64(value, "combat_attacker_dice", 2),
            combat_defender_dice: get_i64(value, "combat_defender_dice", 1),
            combat_defender_flat_bonus: get_i64(value, "combat_defender_flat_bonus", 1),
            charge_round_reset: value
                .get("charge_round_reset")
                .and_then(Value::as_str)
                .unwrap_or("half_up")
                .to_string(),
            charge_full_if_unused: value
                .get("charge_full_if_unused")
                .and_then(Value::as_bool)
                .unwrap_or(true),
        }
    }
}

#[derive(Debug, Clone)]
pub struct SeatPlacement {
    pub cells: Vec<(i64, i64)>,
    pub facing: i64,
}

#[derive(Debug, Clone)]
pub struct Scenario {
    pub scenario_id: String,
    /// Turn order and draft order (ADR-015: composition is data, not code).
    pub seat_order: Vec<String>,
    /// Team membership: {"A": ["A1"], "B": ["B1"]}; drives placement team and
    /// victory.
    pub teams: BTreeMap<String, Vec<String>>,
    pub seats: BTreeMap<String, SeatPlacement>,
}

impl Scenario {
    fn from_value(value: &Value, fallback_id: &str) -> Scenario {
        let mut seats = BTreeMap::new();
        if let Some(map) = value.get("seats").and_then(Value::as_object) {
            for (seat, info) in map {
                let cells = info
                    .get("cells")
                    .and_then(Value::as_array)
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|c| {
                                let pair = c.as_array()?;
                                Some((
                                    pair.first()?.as_i64()?,
                                    pair.get(1)?.as_i64()?,
                                ))
                            })
                            .collect()
                    })
                    .unwrap_or_default();
                seats.insert(
                    seat.clone(),
                    SeatPlacement {
                        cells,
                        facing: get_i64(info, "facing", 0),
                    },
                );
            }
        }
        Scenario {
            scenario_id: value
                .get("scenario_id")
                .and_then(Value::as_str)
                .unwrap_or(fallback_id)
                .to_string(),
            seat_order: value
                .get("seat_order")
                .and_then(Value::as_array)
                .map(|arr| {
                    arr.iter()
                        .filter_map(Value::as_str)
                        .map(str::to_string)
                        .collect()
                })
                .unwrap_or_else(|| ["A1", "B1", "A2", "B2"].iter().map(|s| s.to_string()).collect()),
            teams: value
                .get("teams")
                .and_then(Value::as_object)
                .map(|map| {
                    map.iter()
                        .map(|(team, seats)| {
                            (
                                team.clone(),
                                seats
                                    .as_array()
                                    .map(|arr| {
                                        arr.iter()
                                            .filter_map(Value::as_str)
                                            .map(str::to_string)
                                            .collect()
                                    })
                                    .unwrap_or_default(),
                            )
                        })
                        .collect()
                })
                .unwrap_or_default(),
            seats,
        }
    }
}

/// Loaded ruleset v3 (ships + game + board + scenarios + heroes + hash).
#[derive(Debug, Clone)]
pub struct Ruleset {
    pub game: GameRules,
    pub board_radius: i64,
    pub ships: BTreeMap<String, ShipDef>,
    /// Ship ids sorted (code-point order), like CardStore.ship_ids_sorted.
    pub ship_ids: Vec<String>,
    pub scenarios: BTreeMap<String, Scenario>,
    /// Hero cards (ADR-016) keyed by hero id (sorted == the oracle draft pool
    /// order: `pool.sort()` over the keys).
    pub heroes: BTreeMap<String, HeroDef>,
    pub ruleset_hash: String,
}

impl Ruleset {
    pub fn ship(&self, type_id: &str) -> &ShipDef {
        self.ships.get(type_id).unwrap_or(&EMPTY_SHIP_DEF)
    }

    pub fn scenario(&self, name: &str) -> Option<&Scenario> {
        self.scenarios.get(name)
    }
}

/// Default ruleset location: `SWB_RULESET_DIR` env override, otherwise
/// `<repo>/data/rulesets/v3` relative to the crate manifest.
pub fn default_ruleset_path() -> PathBuf {
    if let Ok(dir) = std::env::var("SWB_RULESET_DIR") {
        return PathBuf::from(dir);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../data/rulesets/v3")
}

static DEFAULT_RULESET: OnceLock<Ruleset> = OnceLock::new();

/// Lazily loaded shared ruleset from `default_ruleset_path()`.
pub fn default_ruleset() -> &'static Ruleset {
    DEFAULT_RULESET.get_or_init(|| {
        load_ruleset(&default_ruleset_path())
            .unwrap_or_else(|e| panic!("default ruleset unavailable: {}", e))
    })
}

/// Loads and validates the ruleset directory (game.json, board.json,
/// ships/*.json sorted by file name, scenarios/*.json).
pub fn load_ruleset(dir: &Path) -> Result<Ruleset, String> {
    let game_value = read_json(&dir.join("game.json"))?;
    let board_value = read_json(&dir.join("board.json"))?;

    let mut ship_values: Vec<Value> = Vec::new();
    for entry in list_sorted_json_files(&dir.join("ships"))? {
        ship_values.push(read_json(&entry)?);
    }

    let mut scenario_values: Vec<(String, Value)> = Vec::new();
    for entry in list_sorted_json_files(&dir.join("scenarios"))? {
        let stem = entry
            .file_stem()
            .and_then(std::ffi::OsStr::to_str)
            .unwrap_or_default()
            .to_string();
        scenario_values.push((stem, read_json(&entry)?));
    }

    let mut hero_values: Vec<(String, Value)> = Vec::new();
    for entry in list_sorted_json_files(&dir.join("heroes"))? {
        let stem = entry
            .file_stem()
            .and_then(std::ffi::OsStr::to_str)
            .unwrap_or_default()
            .to_string();
        hero_values.push((stem, read_json(&entry)?));
    }

    build_ruleset(game_value, board_value, ship_values, scenario_values, hero_values)
        .map_err(|e| format!("{}: {}", dir.display(), e))
}

/// Filesystem-free constructor for embedded targets (WASM bindings).
/// `ships` — parsed ship definitions (the `id` field is required);
/// `scenarios` — (file stem, value) pairs, mirroring `load_ruleset`;
/// `heroes` — (file stem, value) pairs (ADR-016).
pub fn ruleset_from_values(
    game: Value,
    board: Value,
    ships: Vec<Value>,
    scenarios: Vec<(String, Value)>,
    heroes: Vec<(String, Value)>,
) -> Result<Ruleset, String> {
    build_ruleset(game, board, ships, scenarios, heroes)
}

fn build_ruleset(
    game_value: Value,
    board_value: Value,
    ship_values: Vec<Value>,
    scenario_values: Vec<(String, Value)>,
    hero_values: Vec<(String, Value)>,
) -> Result<Ruleset, String> {
    let mut ships_map: Map<String, Value> = Map::new();
    let mut ship_defs: BTreeMap<String, ShipDef> = BTreeMap::new();
    for value in ship_values {
        let value = coerce_json(value);
        let def = ShipDef::from_value(&value)?;
        ships_map.insert(def.id.clone(), value);
        ship_defs.insert(def.id.clone(), def);
    }
    if ship_defs.is_empty() {
        return Err("no ship definitions".to_string());
    }

    let mut scenarios: BTreeMap<String, Scenario> = BTreeMap::new();
    for (stem, value) in scenario_values {
        let scenario = Scenario::from_value(&coerce_json(value), &stem);
        scenarios.insert(scenario.scenario_id.clone(), scenario);
    }

    // Hero cards keyed by hero id, falling back to the file stem
    // (CardStore._load: `hero.get("id", "")` or trimmed file name).
    let mut heroes: BTreeMap<String, HeroDef> = BTreeMap::new();
    for (stem, value) in hero_values {
        let value = coerce_json(value);
        let def = HeroDef::from_value(&value, &stem);
        heroes.insert(def.id.clone(), def);
    }

    let ship_ids: Vec<String> = ship_defs.keys().cloned().collect();
    let ruleset_hash = state_hash(&json!({
        "board": board_value,
        "game": game_value,
        "ships": Value::Object(ships_map),
    }));

    Ok(Ruleset {
        game: GameRules::from_value(&game_value),
        board_radius: get_i64(&board_value, "radius", 4),
        ships: ship_defs,
        ship_ids,
        scenarios,
        heroes,
        ruleset_hash,
    })
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read {}: {}", path.display(), e))?;
    serde_json::from_str(&text).map_err(|e| format!("cannot parse {}: {}", path.display(), e))
}

/// Every *.json of a directory sorted by file name (hidden files skipped);
/// missing directory is not an error (like CardStore._read_dir_of_json).
fn list_sorted_json_files(dir: &Path) -> Result<Vec<PathBuf>, String> {
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(_) => return Ok(Vec::new()),
    };
    let mut files: Vec<PathBuf> = entries
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.is_file()
                && p.extension().and_then(std::ffi::OsStr::to_str) == Some("json")
                && !p
                    .file_name()
                    .and_then(std::ffi::OsStr::to_str)
                    .map(|n| n.starts_with('.'))
                    .unwrap_or(false)
        })
        .collect();
    files.sort();
    Ok(files)
}

/// Mirrors CardStore.coerce_json: numbers without a fractional part become
/// integers so serialization stays byte-compatible with the prototype.
pub fn coerce_json(value: Value) -> Value {
    match value {
        Value::Number(n) => {
            // Whole-valued floats (Godot JSON parses every number as float)
            // become integers; anything else passes through untouched.
            if let Some(f) = n.as_f64() {
                if f.fract() == 0.0 && f.abs() <= 9.007_199_254_740_992e15 {
                    return Value::Number(serde_json::Number::from(f as i64));
                }
            }
            Value::Number(n)
        }
        Value::Array(items) => Value::Array(items.into_iter().map(coerce_json).collect()),
        Value::Object(map) => Value::Object(
            map.into_iter()
                .map(|(k, v)| (k, coerce_json(v)))
                .collect(),
        ),
        other => other,
    }
}

fn get_i64(value: &Value, key: &str, default: i64) -> i64 {
    value
        .get(key)
        .and_then(Value::as_i64)
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loads_default_ruleset_and_11_ship_types() {
        let rs = default_ruleset();
        assert_eq!(rs.ship_ids.len(), 11);
        assert_eq!(rs.game.fleet_size, 3);
        assert_eq!(rs.game.draft_budget, 17);
        // ADR-015: board radius is data (board.json), radius 3 / 37 cells.
        assert_eq!(rs.board_radius, 3);
        // v3.5 (ADR-018) ruleset id comes straight from game.json.
        assert_eq!(rs.game.ruleset_id, "v3_5");
        assert_eq!(rs.game.combat_attacker_dice, 2);
        assert_eq!(rs.game.combat_defender_dice, 1);
        assert_eq!(rs.game.combat_defender_flat_bonus, 1);
        // v3.5 energy: end-of-round rewrite parameters from game.json.
        assert_eq!(rs.game.charge_round_reset, "half_up");
        assert!(rs.game.charge_full_if_unused);
        assert_eq!(rs.ship_ids[0], "death_star_1");
        assert!(rs.scenarios.contains_key("classic_2v2"));
        // v3.2 duel scenario (ADR-015): 2 seats, teams travel in the scenario.
        let scenario = rs.scenario("classic_2v2").unwrap();
        assert_eq!(scenario.seat_order, ["A1", "B1"]);
        assert_eq!(scenario.teams.get("A").map(Vec::as_slice), Some(&["A1".to_string()][..]));
        assert_eq!(scenario.teams.get("B").map(Vec::as_slice), Some(&["B1".to_string()][..]));
        let a1 = &scenario.seats["A1"];
        assert_eq!(a1.cells, vec![(0, 3), (0, 2), (1, 2)]);
        assert_eq!(a1.facing, 0);
        let b1 = &scenario.seats["B1"];
        assert_eq!(b1.cells, vec![(0, -3), (0, -2), (-1, -2)]);
        assert_eq!(b1.facing, 3);
        // Ability wiring straight from the data files.
        assert!(rs.ship("ghost").has_ability(ABILITY_TRANSFORM));
        assert_eq!(
            rs.ship("ghost").abilities[0].transform_to.as_deref(),
            Some("phantom")
        );
        assert!(rs.ship("death_star_1").has_ability(ABILITY_RANGED_SHOT));
        assert!(rs.ship("xwing_t65").has_ability(ABILITY_LUCKY_SHOT));
        assert!(rs.ship("tie_fighter").has_ability(ABILITY_RESURRECTION));
        assert!(rs.ship("vulture_droid").has_ability(ABILITY_REROLL_ONE));
        // Phantom is not draftable (group 0).
        let phantom = rs.ship("phantom");
        assert_eq!(phantom.group, 0);
        assert!(!phantom.draftable);
        assert!(rs.ship("unknown_type").arc(0) == 0, "missing def falls back to EMPTY");
        // Hero cards (ADR-016 §1): 8 heroes, uses_per_match from the ability
        // block (phasma passive = 0, obi_wan 2, all others 1).
        assert_eq!(rs.heroes.len(), 8);
        assert_eq!(rs.heroes.get("phasma").map(|h| h.uses_per_match), Some(0));
        assert_eq!(rs.heroes.get("obi_wan").map(|h| h.uses_per_match), Some(2));
        for hero_id in [
            "anakin",
            "boba_fett",
            "darth_vader",
            "han_solo",
            "jango_fett",
            "luke",
        ] {
            assert_eq!(
                rs.heroes.get(hero_id).map(|h| h.uses_per_match),
                Some(1),
                "hero {hero_id}"
            );
        }
        // Draft pool order == sorted hero ids (oracle `pool.sort()`).
        let pool: Vec<&str> = rs.heroes.keys().map(|s| s.as_str()).collect();
        assert_eq!(
            pool,
            [
                "anakin",
                "boba_fett",
                "darth_vader",
                "han_solo",
                "jango_fett",
                "luke",
                "obi_wan",
                "phasma"
            ]
        );
    }

    #[test]
    fn ruleset_hash_matches_prototype_card_store() {
        // The value printed by the GDScript prototype for data/rulesets/v3
        // (console_match / CardStore.ruleset_hash). Any data change on the
        // GDScript side must be mirrored here and in the diff corpus.
        // 289FEA29F1BB029E = ruleset v3_5 (ADR-018: ruleset_id v3_5,
        // charge_round_reset "half_up" + charge_full_if_unused true,
        // charge_recovery_per_activation removed from game.json; scenarios AND
        // heroes stay excluded from the inputs).
        assert_eq!(default_ruleset().ruleset_hash, "289FEA29F1BB029E");
    }

    #[test]
    fn ruleset_hash_excludes_scenarios_and_matches_prototype_shape() {
        let rs = default_ruleset();
        // 16 uppercase hex characters; scenarios exist but do not enter the hash.
        assert_eq!(rs.ruleset_hash.len(), 16);
        assert!(rs
            .ruleset_hash
            .chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_lowercase()));
        let mut clone = rs.clone();
        clone.scenarios.clear();
        assert_eq!(clone.ruleset_hash, rs.ruleset_hash);
    }

    #[test]
    fn coerce_json_converts_whole_floats() {
        let v: Value = serde_json::from_str(r#"{"a": 2.0, "b": 2.5, "c": [3.0], "d": -1.0}"#).unwrap();
        let coerced = coerce_json(v);
        assert_eq!(
            serde_json::to_string(&coerced).unwrap(),
            r#"{"a":2,"b":2.5,"c":[3],"d":-1}"#
        );
    }
}
