//! Pure functional match engine over the canonical state (core-api §4/§5/§6/§7
//! + ADR-012 special rules + ADR-014 combat v3.1 + ADR-016 heroes + ADR-017
//! movement v3.4 + ADR-018 energy v3.5). Bit- compatible with
//! `src/core/rules/match_engine.gd`:
//! - `apply_command` never mutates its input and deterministically restores
//!   the RNG stream from (seed, dice journal): fleet draft + hero draft +
//!   one `next_die` per recorded side (ADR-012 §7, ADR-016 §1);
//! - dice consumption order per attack (ADR-014 §3, extending ADR-012 §2):
//!   combat_attacker_dice × d6 (vulture d2 reroll of a natural 1) ->
//!   reaction windows (luke/obi_wan flips — no rng consumption) ->
//!   combat_defender_dice × d6 (+ flat bonus) -> x-wing d2 on a tie -> on
//!   destruction ghost transforms without a die / tie_fighter d2 then d4;
//!   mine/bomb effect dice are 1 × d4 with role "effect" (ADR-016 §3.8);
//! - `legal_actions` returns actions in the prototype's deterministic order;
//!   with seeded_bots_skip_heroes=true no hero command is ever offered and
//!   reaction windows are auto-closed with ReactionSkipped (ADR-016 §7).

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

use crate::cards::{
    ABILITY_LUCKY_SHOT, ABILITY_RANGED_SHOT, ABILITY_REROLL_ONE, ABILITY_RESURRECTION,
    ABILITY_TRANSFORM, HeroDef, Ruleset, ShipDef,
};
use crate::hex;
use crate::rng::{DieRng, Mulberry32Compat};
use crate::serialization::{state_hash as canonical_state_hash, to_canonical};

/// Fallback seat composition for the full 2x2 format (ADR-015). The source of
/// truth for a match is the scenario: seat_order (turn order and draft) and
/// teams (team membership and victory) travel in the state.
pub const SEAT_ORDER: [&str; 4] = ["A1", "B1", "A2", "B2"];
// v3 (ADR-016): state carries "heroes", "objects" (mines/bombs) and
// "pending_reaction" (reaction window) on top of the v2 scenario fields.
// v4 (ADR-018, energy v3.5): every ship carries "spent_round" (charges spent
// this round); EndActivation no longer restores a charge — charges are
// REWRITTEN once at the end of the round (full max_charges when nothing was
// spent, ceil(max_charges/2) otherwise) with one ChargesRefreshed event per
// living ship.
pub const STATE_VERSION: i64 = 4;
pub const DEFAULT_ROUND_LIMIT: i64 = 60;
pub const DEFAULT_SCENARIO: &str = "classic_2v2";

/// Hero ability command ids (ADR-016 §3): the ability_id carried by the
/// UseHeroAbility command for each hero. Active abilities (vader..boba) use
/// the ADR ids; the reaction flips (luke/obi_wan) use the hero card ability
/// ids from data/rulesets/v3/heroes/*.json. Phasma is passive — no command.
pub fn hero_ability_id(hero_id: &str) -> Option<&'static str> {
    match hero_id {
        "darth_vader" => Some("force_attack"),
        "anakin" => Some("force_push"),
        "han_solo" => Some("hyperjump"),
        "jango_fett" => Some("place_mine"),
        "boba_fett" => Some("place_bomb"),
        "luke" => Some("precise_shot"),
        "obi_wan" => Some("miss"),
        _ => None,
    }
}

/// Reaction window kinds (ADR-016 §3.5/§4): pending_reaction.kind per hero.
fn window_kind(hero_id: &str) -> Option<&'static str> {
    match hero_id {
        "luke" => Some("luke_flip"),
        "obi_wan" => Some("obi_wan_flip"),
        _ => None,
    }
}

fn window_hero(kind: &str) -> &'static str {
    if kind == "luke_flip" {
        "luke"
    } else {
        "obi_wan"
    }
}

/// Boba's bomb drifts at most this many times (ADR-016 §3.7).
pub const BOMB_MAX_SHIFTS: i64 = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    Draft,
    Activation,
    Reaction,
    Ended,
}

/// Team membership from the scenario (core-api §7, ADR-015): serializes as
/// {"A": [...], "B": [...]} — key names and value format are pin.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Teams {
    #[serde(rename = "A")]
    pub a: Vec<String>,
    #[serde(rename = "B")]
    pub b: Vec<String>,
}

/// One seat's hero assignment (ADR-016 §1/§4).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeroState {
    pub hero_id: String,
    pub uses_left: i64,
}

/// `heroes` state: {seat: {hero_id, uses_left}} — a JSON object whose keys
/// keep the insertion order (GDScript Dictionaries preserve insertion order,
/// and the oracle inserts in seat_order). Canonical hashing sorts keys, but
/// the plain snapshot keeps the seat_order layout of the oracle.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Heroes(Vec<(String, HeroState)>);

impl Heroes {
    pub fn get(&self, seat: &str) -> Option<&HeroState> {
        self.0.iter().find(|(s, _)| s == seat).map(|(_, h)| h)
    }

    pub fn get_mut(&mut self, seat: &str) -> Option<&mut HeroState> {
        self.0
            .iter_mut()
            .find(|(s, _)| s == seat)
            .map(|(_, h)| h)
    }

    pub fn insert(&mut self, seat: String, hero: HeroState) {
        if let Some(existing) = self.get_mut(&seat) {
            *existing = hero;
        } else {
            self.0.push((seat, hero));
        }
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &HeroState)> {
        self.0.iter().map(|(s, h)| (s, h))
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }
}

impl Serialize for Heroes {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeMap;
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (seat, hero) in &self.0 {
            map.serialize_entry(seat, hero)?;
        }
        map.end()
    }
}

impl<'de> Deserialize<'de> for Heroes {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct HeroesVisitor;
        impl<'de> serde::de::Visitor<'de> for HeroesVisitor {
            type Value = Heroes;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("a map of seat to hero state")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut access: A,
            ) -> Result<Self::Value, A::Error> {
                let mut vec = Vec::new();
                while let Some((seat, hero)) = access.next_entry::<String, HeroState>()? {
                    vec.push((seat, hero));
                }
                Ok(Heroes(vec))
            }
        }
        deserializer.deserialize_map(HeroesVisitor)
    }
}

/// A mine or a bomb on the board (ADR-016 §4). Mines carry no dir/moves_left;
/// bombs always do — the optional fields are omitted like the oracle dicts.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GameObject {
    pub kind: String,
    pub q: i64,
    pub r: i64,
    pub seat: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dir: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub moves_left: Option<i64>,
}

/// An open reaction window (ADR-016 §3.5/§4): carries the combat context so
/// the resolver can finish the fight after the window closes.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PendingReaction {
    pub seat: String,
    pub kind: String,
    pub attacker_id: String,
    pub target_id: String,
    pub faces: Vec<i64>,
    pub range_penalty: i64,
}

/// Canonical state snapshot (core-api §7 + ADR-012 §7 + ADR-016 §4; key names
/// are pin).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MatchState {
    pub version: i64,
    pub ruleset_id: String,
    pub ruleset_hash: String,
    pub seed: i64,
    pub phase: Phase,
    pub round: i64,
    pub round_limit: i64,
    pub active_seat: String,
    pub active_ship: Option<String>,
    /// Turn/draft order, scenario data (ADR-015).
    pub seat_order: Vec<String>,
    /// Team membership, scenario data (ADR-015).
    pub teams: Teams,
    pub rng_counter: i64,
    /// Journal of consumed die sides in order (ADR-012 §7); `rng_counter ==
    /// dice.len()` is the invariant.
    pub dice: Vec<u8>,
    pub winner: Option<String>,
    pub ships: Vec<ShipState>,
    /// Hero per seat in seat_order (ADR-016 §1/§4).
    #[serde(default)]
    pub heroes: Heroes,
    /// Mines and bombs (ADR-016 §4), in placement order.
    #[serde(default)]
    pub objects: Vec<GameObject>,
    /// Open reaction window; null while no window is open.
    pub pending_reaction: Option<PendingReaction>,
    /// Bot-parity pin (ADR-016 §7): when true, legal_actions hides hero
    /// commands and reaction windows are auto-closed by the engine with a
    /// ReactionSkipped event, so seeded-bot replays stay deterministic.
    #[serde(default = "default_true")]
    pub seeded_bots_skip_heroes: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShipState {
    pub id: String,
    pub type_id: String,
    pub seat: String,
    pub team: String,
    pub q: i64,
    pub r: i64,
    pub facing: i64,
    pub hp: i64,
    pub shield: i64,
    pub charges: i64,
    /// v3.5 (ADR-018): charges spent THIS round (move/rotate +1 each,
    /// hyperjump adds the zeroed charges); reset to 0 by RoundStarted.
    #[serde(default)]
    pub spent_round: i64,
    pub activated: bool,
    pub attack_used: bool,
    pub alive: bool,
    /// ADR-012 §7: set on the single revive attempt, whatever the outcome.
    pub revive_used: bool,
}

/// Commands (core-api §5); tagged JSON form: {"type": "...", ...}.
/// v3.4 (ADR-017): `Move { dir }` steps to the neighboring hex `dir` (0..5,
/// DIR_DELTAS order) for one charge — any direction, facing untouched. The
/// field is i64 so out-of-range dirs (e.g. -1 or 6) deserialize and are then
/// rejected with `bad_direction` exactly like the oracle (`int(get("dir",-1))`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Command {
    BeginActivation { ship_instance_id: String },
    Move { dir: i64 },
    RotateLeft,
    RotateRight,
    DeclareAttack { target_ship_instance_id: String },
    EndActivation,
    /// ADR-016: hero ability — active ability (activation phase) or a
    /// reaction flip (inside a reaction window). Only the params of the
    /// addressed ability are present (oracle command dicts).
    UseHeroAbility {
        ability_id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        target_ship_instance_id: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        ship_instance_id: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        dir: Option<i64>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        q: Option<i64>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        r: Option<i64>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        die_index: Option<i64>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        value: Option<i64>,
    },
    /// ADR-016 §3.5: decline the open reaction window (no use is consumed).
    SkipReaction,
}

/// create_match configuration (core-api §9 + ADR-016 §7).
#[derive(Debug, Clone)]
pub struct MatchConfig {
    pub seed: i64,
    pub round_limit: i64,
    pub scenario: String,
    /// ADR-016 §7 bot-parity pin; default true (seeded bots skip heroes).
    pub seeded_bots_skip_heroes: bool,
}

impl Default for MatchConfig {
    fn default() -> Self {
        MatchConfig {
            seed: 0,
            round_limit: DEFAULT_ROUND_LIMIT,
            scenario: DEFAULT_SCENARIO.to_string(),
            seeded_bots_skip_heroes: true,
        }
    }
}

/// Rejected command; codes are pinned in core-api §5 + ADR-016 §6. A
/// rejection never changes state.
#[derive(Debug, Clone, PartialEq)]
pub struct Rejection {
    pub code: String,
    pub detail: String,
}

fn reject(code: &str, detail: impl Into<String>) -> Rejection {
    Rejection {
        code: code.to_string(),
        detail: detail.into(),
    }
}

/// replay() failure: the index of the first rejected command.
#[derive(Debug, Clone, PartialEq)]
pub struct ReplayError {
    pub index: usize,
    pub error: String,
    pub detail: String,
}

// --- create_match ------------------------------------------------------------

struct Pick {
    seat: String,
    ship_instance_id: String,
    ship_type_id: String,
    cost: i64,
}

/// Runs MatchCreated -> draft -> hero draft -> placement -> RoundStarted(1).
pub fn create_match(config: &MatchConfig) -> Result<(MatchState, Vec<Value>), String> {
    create_match_with(config, crate::cards::default_ruleset())
}

pub fn create_match_with(
    config: &MatchConfig,
    ruleset: &Ruleset,
) -> Result<(MatchState, Vec<Value>), String> {
    let scenario = ruleset
        .scenario(&config.scenario)
        .ok_or_else(|| format!("unknown scenario '{}'", config.scenario))?;

    // Seat composition and teams are scenario data (ADR-015): seat_order
    // drives the draft and the turn order, teams drives placement team and
    // victory. Empty seat_order falls back to the full 2x2 composition.
    let seat_order: Vec<String> = if scenario.seat_order.is_empty() {
        SEAT_ORDER.iter().map(|s| s.to_string()).collect()
    } else {
        scenario.seat_order.clone()
    };
    let seat_team: BTreeMap<&str, &str> = scenario
        .teams
        .iter()
        .flat_map(|(team, seats)| {
            seats.iter().map(move |seat| (seat.as_str(), team.as_str()))
        })
        .collect();

    let mut events = vec![json!({
        "type": "MatchCreated",
        "ruleset_id": ruleset.game.ruleset_id,
        "ruleset_hash": ruleset.ruleset_hash,
        "seed": config.seed,
        "round_limit": config.round_limit,
    })];

    let mut rng = Mulberry32Compat::new(config.seed as u64);
    let picks = run_draft(&mut rng, ruleset, &seat_order).ok_or("draft_no_candidates")?;
    // Hero draft (ADR-016 §1): after the fleet draft the same match RNG deals
    // one distinct hero per scenario seat, in seat_order (rng order matters;
    // the HeroDrafted events are appended below, after the fleet journal).
    let heroes = run_hero_draft(&mut rng, ruleset, &seat_order);

    let mut seat_picks: BTreeMap<&str, Vec<&Pick>> = BTreeMap::new();
    for pick in &picks {
        seat_picks.entry(pick.seat.as_str()).or_default().push(pick);
        events.push(json!({
            "type": "ShipDrafted",
            "seat": pick.seat,
            "ship_instance_id": pick.ship_instance_id,
            "ship_type_id": pick.ship_type_id,
            "cost": pick.cost,
        }));
    }

    // HeroDrafted after the whole fleet journal, in seat_order (oracle).
    for seat in &seat_order {
        if let Some(hero) = heroes.get(seat) {
            events.push(json!({
                "type": "HeroDrafted",
                "seat": seat,
                "hero_id": hero.hero_id,
            }));
        }
    }

    let mut ships: Vec<ShipState> = Vec::new();
    for seat in &seat_order {
        let info = scenario.seats.get(seat);
        let facing = info.map(|s| s.facing).unwrap_or(0);
        let default_cells: Vec<(i64, i64)> = Vec::new();
        let cells = info.map(|s| &s.cells).unwrap_or(&default_cells);
        let empty: Vec<&Pick> = Vec::new();
        let seat_list = seat_picks.get(seat.as_str()).unwrap_or(&empty);
        for (k, pick) in seat_list.iter().enumerate() {
            let def = ruleset.ship(&pick.ship_type_id);
            let (q, r) = cells.get(k).copied().ok_or_else(|| {
                format!(
                    "scenario '{}' lacks cells for seat {}",
                    scenario.scenario_id, seat
                )
            })?;
            let ship = ShipState {
                id: pick.ship_instance_id.clone(),
                type_id: pick.ship_type_id.clone(),
                seat: seat.clone(),
                team: seat_team
                    .get(seat.as_str())
                    .map(|t| t.to_string())
                    .unwrap_or_else(|| seat[..1].to_string()),
                q,
                r,
                facing,
                hp: def.max_hp,
                shield: def.max_shield,
                charges: def.initial_charges,
                spent_round: 0,
                activated: false,
                attack_used: false,
                revive_used: false,
                alive: true,
            };
            events.push(json!({
                "type": "ShipPlaced",
                "ship_instance_id": ship.id,
                "q": ship.q,
                "r": ship.r,
                "facing": facing,
                "hp": ship.hp,
                "shield": ship.shield,
                "charges": ship.charges,
            }));
            ships.push(ship);
        }
    }

    let state = MatchState {
        version: STATE_VERSION,
        ruleset_id: ruleset.game.ruleset_id.clone(),
        ruleset_hash: ruleset.ruleset_hash.clone(),
        seed: config.seed,
        phase: Phase::Activation,
        round: 1,
        round_limit: config.round_limit,
        seat_order: seat_order.clone(),
        teams: Teams {
            a: scenario.teams.get("A").cloned().unwrap_or_default(),
            b: scenario.teams.get("B").cloned().unwrap_or_default(),
        },
        active_seat: seat_order
            .first()
            .ok_or("scenario seat_order is empty")?
            .clone(),
        active_ship: None,
        rng_counter: 0,
        dice: Vec::new(),
        winner: None,
        ships,
        heroes,
        objects: Vec::new(),
        pending_reaction: None,
        seeded_bots_skip_heroes: config.seeded_bots_skip_heroes,
    };
    events.push(json!({ "type": "RoundStarted", "round": 1 }));
    Ok((state, events))
}

// --- legal_actions -----------------------------------------------------------

/// Legal commands right now, deterministic order (core-api §9, ADR-012 §8,
/// ADR-016 §3). In a reaction window: every legal flip of one attacker die
/// plus SkipReaction, from the window owner. Otherwise the activation rules;
/// with seeded_bots_skip_heroes=true no hero command is ever offered.
pub fn legal_actions(state: &MatchState) -> Vec<Command> {
    legal_actions_with(state, crate::cards::default_ruleset())
}

pub fn legal_actions_with(state: &MatchState, ruleset: &Ruleset) -> Vec<Command> {
    let mut out = Vec::new();
    if let Some(pending) = &state.pending_reaction {
        let ability_id = hero_ability_id(window_hero(&pending.kind)).unwrap_or_default();
        for die_index in 0..pending.faces.len() {
            let from_face = pending.faces[die_index];
            for value in 1..=6i64 {
                if value == from_face || flip_forbidden(&pending.kind, from_face, value) {
                    continue;
                }
                out.push(Command::UseHeroAbility {
                    ability_id: ability_id.to_string(),
                    target_ship_instance_id: None,
                    ship_instance_id: None,
                    dir: None,
                    q: None,
                    r: None,
                    die_index: Some(die_index as i64),
                    value: Some(value),
                });
            }
        }
        out.push(Command::SkipReaction);
        return out;
    }
    if state.phase != Phase::Activation {
        return out;
    }
    let Some(active_id) = &state.active_ship else {
        for ship in &state.ships {
            if ship.seat == state.active_seat && ship.alive && !ship.activated {
                out.push(Command::BeginActivation {
                    ship_instance_id: ship.id.clone(),
                });
            }
        }
        return out;
    };
    let Some(ship) = state.ships.iter().find(|s| &s.id == active_id) else {
        return out;
    };
    if !ship.alive {
        // Attacker died from its own attack: only passing the turn remains.
        out.push(Command::EndActivation);
        return out;
    }
    if ship.charges > 0 {
        // v3.4 (ADR-017): Move steps to ANY neighboring hex for one charge.
        // One Move{dir} entry per legal direction, in DIR_DELTAS order 0..5;
        // a direction whose target is off the board or occupied is skipped.
        for dir in 0..6i64 {
            let (tq, tr) = hex::step(ship.q as i32, ship.r as i32, dir as usize);
            if hex::in_board(tq, tr, ruleset.board_radius as i32)
                && alive_ship_at(state, tq, tr).is_none()
            {
                out.push(Command::Move { dir });
            }
        }
        out.push(Command::RotateLeft);
        out.push(Command::RotateRight);
    }
    if !ship.attack_used {
        let team = ship.team.as_str();
        if ruleset.ship(&ship.type_id).has_ability(ABILITY_RANGED_SHOT) {
            // C008: the Death Star threatens every living enemy on the board;
            // targets follow the ships array order for determinism.
            for s in &state.ships {
                if s.alive && s.team != team {
                    out.push(Command::DeclareAttack {
                        target_ship_instance_id: s.id.clone(),
                    });
                }
            }
        } else {
            for (nq, nr) in hex::neighbors(ship.q as i32, ship.r as i32) {
                if let Some(occ) = alive_ship_at(state, nq, nr) {
                    if occ.team != team {
                        out.push(Command::DeclareAttack {
                            target_ship_instance_id: occ.id.clone(),
                        });
                    }
                }
            }
        }
    }
    if !state.seeded_bots_skip_heroes {
        append_hero_actions(&mut out, state, ship, ruleset);
    }
    out.push(Command::EndActivation);
    out
}

/// Appends the legal UseHeroAbility commands of the active seat's hero
/// (ADR-016 §2-§3): active abilities only, used inside the seat's own
/// activation on the active ship. Deterministic order: ships array order,
/// directions 0..5, board cells scanned q asc then r asc.
fn append_hero_actions(out: &mut Vec<Command>, state: &MatchState, ship: &ShipState, ruleset: &Ruleset) {
    let active_seat = state.active_seat.as_str();
    let Some(hero) = state.heroes.get(active_seat) else {
        return;
    };
    if hero.uses_left <= 0 {
        return;
    }
    let team = ship.team.as_str();
    let radius = ruleset.board_radius as i32;
    let cell = (ship.q as i32, ship.r as i32);
    match hero.hero_id.as_str() {
        "darth_vader" => {
            if ship.attack_used {
                return;
            }
            for s in &state.ships {
                if s.alive
                    && s.team != team
                    && hex::distance(cell.0, cell.1, s.q as i32, s.r as i32) == 2
                {
                    out.push(Command::UseHeroAbility {
                        ability_id: "force_attack".to_string(),
                        target_ship_instance_id: Some(s.id.clone()),
                        ship_instance_id: None,
                        dir: None,
                        q: None,
                        r: None,
                        die_index: None,
                        value: None,
                    });
                }
            }
        }
        "anakin" => {
            for s in &state.ships {
                if !s.alive {
                    continue;
                }
                let from = (s.q as i32, s.r as i32);
                for dir in 0..6usize {
                    let (tq, tr) = hex::step(from.0, from.1, dir);
                    if hex::in_board(tq, tr, radius) && alive_ship_at(state, tq, tr).is_none() {
                        out.push(Command::UseHeroAbility {
                            ability_id: "force_push".to_string(),
                            target_ship_instance_id: None,
                            ship_instance_id: Some(s.id.clone()),
                            dir: Some(dir as i64),
                            q: None,
                            r: None,
                            die_index: None,
                            value: None,
                        });
                    }
                }
            }
        }
        "han_solo" => {
            if ship.charges <= 0 {
                return;
            }
            for q in -radius..=radius {
                for r in -radius..=radius {
                    if !hex::in_board(q, r, radius) {
                        continue;
                    }
                    if alive_ship_at(state, q, r).is_some() {
                        continue;
                    }
                    if living_enemy_near(state, q, r, team) {
                        continue;
                    }
                    out.push(Command::UseHeroAbility {
                        ability_id: "hyperjump".to_string(),
                        target_ship_instance_id: None,
                        ship_instance_id: None,
                        dir: None,
                        q: Some(q as i64),
                        r: Some(r as i64),
                        die_index: None,
                        value: None,
                    });
                }
            }
        }
        "jango_fett" => {
            out.push(Command::UseHeroAbility {
                ability_id: "place_mine".to_string(),
                target_ship_instance_id: None,
                ship_instance_id: None,
                dir: None,
                q: None,
                r: None,
                die_index: None,
                value: None,
            });
        }
        "boba_fett" => {
            for dir in 0..6i64 {
                out.push(Command::UseHeroAbility {
                    ability_id: "place_bomb".to_string(),
                    target_ship_instance_id: None,
                    ship_instance_id: None,
                    dir: Some(dir),
                    q: None,
                    r: None,
                    die_index: None,
                    value: None,
                });
            }
        }
        _ => {}
    }
}

// --- apply_command -----------------------------------------------------------

/// Pure: returns (events, new_state) or a Rejection; the input is untouched.
pub fn apply_command(
    state: &MatchState,
    command: &Command,
) -> Result<(Vec<Value>, MatchState), Rejection> {
    apply_command_with(state, command, crate::cards::default_ruleset())
}

pub fn apply_command_with(
    state: &MatchState,
    command: &Command,
    ruleset: &Ruleset,
) -> Result<(Vec<Value>, MatchState), Rejection> {
    if state.phase == Phase::Reaction {
        // A reaction window is open (ADR-016 §3.5): exactly two commands from
        // the window owner are legal.
        return match command {
            Command::UseHeroAbility { .. } | Command::SkipReaction => {
                let mut new_state = state.clone();
                let mut events: Vec<Value> = Vec::new();
                apply_reaction(&mut new_state, command, ruleset, &mut events)?;
                finish(&mut new_state, &mut events);
                Ok((events, new_state))
            }
            _ => {
                let pending = state.pending_reaction.as_ref();
                Err(reject(
                    "wrong_phase",
                    format!(
                        "reaction window '{}' is open for seat '{}'",
                        pending.map(|p| p.kind.as_str()).unwrap_or(""),
                        pending.map(|p| p.seat.as_str()).unwrap_or(""),
                    ),
                ))
            }
        };
    }
    if state.phase != Phase::Activation {
        return Err(reject(
            "wrong_phase",
            format!("match phase is '{:?}'", state.phase),
        ));
    }
    match command {
        Command::UseHeroAbility { .. } => {
            let mut new_state = state.clone();
            let mut events: Vec<Value> = Vec::new();
            apply_hero_ability(&mut new_state, command, ruleset, &mut events)?;
            finish(&mut new_state, &mut events);
            Ok((events, new_state))
        }
        Command::SkipReaction => Err(reject("wrong_phase", "no reaction window is open")),
        _ => {
            let mut new_state = state.clone();
            let mut events: Vec<Value> = Vec::new();
            match command {
                Command::BeginActivation { ship_instance_id } => {
                    apply_begin(&mut new_state, ship_instance_id, &mut events)?;
                }
                _ => apply_active(&mut new_state, command, ruleset, &mut events)?,
            }
            finish(&mut new_state, &mut events);
            Ok((events, new_state))
        }
    }
}

fn apply_begin(
    state: &mut MatchState,
    instance_id: &str,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    if state.active_ship.is_some() {
        return Err(reject(
            "not_active_ship",
            format!("ship '{}' is already active", state.active_ship.clone().unwrap_or_default()),
        ));
    }
    let Some(pos) = state.ships.iter().position(|s| s.id == instance_id) else {
        return Err(reject("unknown_ship", format!("no ship '{instance_id}'")));
    };
    {
        let ship = &state.ships[pos];
        if ship.seat != state.active_seat {
            return Err(reject(
                "not_your_seat",
                format!(
                    "ship '{instance_id}' belongs to seat '{}', active seat is '{}'",
                    ship.seat, state.active_seat
                ),
            ));
        }
        if !ship.alive {
            return Err(reject("ship_dead", format!("ship '{instance_id}' is destroyed")));
        }
        if ship.activated {
            return Err(reject(
                "already_activated",
                format!("ship '{instance_id}' already acted this round"),
            ));
        }
    }
    state.active_ship = Some(instance_id.to_string());
    events.push(json!({
        "type": "ActivationStarted",
        "seat": state.active_seat,
        "ship_instance_id": instance_id,
        "charges": state.ships[pos].charges,
    }));
    Ok(())
}

fn apply_active(
    state: &mut MatchState,
    command: &Command,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let active = state
        .active_ship
        .clone()
        .ok_or_else(|| reject("not_active_ship", "no ship is activated (BeginActivation first)"))?;
    let ship_pos = state
        .ships
        .iter()
        .position(|s| s.id == active)
        .ok_or_else(|| reject("unknown_ship", format!("active ship '{active}' not found")))?;
    if !matches!(command, Command::EndActivation) && !state.ships[ship_pos].alive {
        return Err(reject(
            "ship_dead",
            format!("active ship '{active}' is destroyed"),
        ));
    }

    match command {
        Command::Move { dir } => {
            // v3.4 (ADR-017): one charge steps to any neighboring hex. Facing
            // is never touched by a move (course stays a combat-only property).
            // Validation order per the oracle: no_charges -> bad_direction ->
            // out_of_board -> occupied_cell.
            let charges = state.ships[ship_pos].charges;
            if charges <= 0 {
                return Err(reject("no_charges", format!("ship '{active}' has 0 charges")));
            }
            let dir = *dir;
            if !(0..=5).contains(&dir) {
                return Err(reject("bad_direction", format!("dir {dir} outside 0..5")));
            }
            let (fq, fr) = (state.ships[ship_pos].q, state.ships[ship_pos].r);
            let (tq, tr) = hex::step(fq as i32, fr as i32, dir as usize);
            let (tq, tr) = (tq as i64, tr as i64);
            if !hex::in_board(tq as i32, tr as i32, ruleset.board_radius as i32) {
                return Err(reject(
                    "out_of_board",
                    format!("cell ({tq},{tr}) is outside the board"),
                ));
            }
            if alive_ship_at(state, tq as i32, tr as i32).is_some() {
                return Err(reject("occupied_cell", format!("cell ({tq},{tr}) is occupied")));
            }
            let ship = &mut state.ships[ship_pos];
            ship.charges = charges - 1;
            // v3.5 (ADR-018): every spent charge counts toward the round tally.
            ship.spent_round += 1;
            ship.q = tq;
            ship.r = tr;
            events.push(json!({
                "type": "ChargeSpent",
                "ship_instance_id": active,
                "reason": "move",
                "charges_left": charges - 1,
            }));
            events.push(json!({
                "type": "ShipMoved",
                "ship_instance_id": active,
                "from_q": fq, "from_r": fr,
                "to_q": tq, "to_r": tr,
                "dir": dir,
            }));
            check_mines_after_move(state, ship_pos, ruleset, events);
        }
        Command::RotateLeft | Command::RotateRight => {
            let charges = state.ships[ship_pos].charges;
            if charges <= 0 {
                return Err(reject("no_charges", format!("ship '{active}' has 0 charges")));
            }
            let steps = if matches!(command, Command::RotateLeft) { -1 } else { 1 };
            let from_facing = state.ships[ship_pos].facing;
            let to_facing = hex::rotate(from_facing as i32, steps) as i64;
            let ship = &mut state.ships[ship_pos];
            ship.charges = charges - 1;
            // v3.5 (ADR-018): every spent charge counts toward the round tally.
            ship.spent_round += 1;
            ship.facing = to_facing;
            events.push(json!({
                "type": "ChargeSpent",
                "ship_instance_id": active,
                "reason": "rotate",
                "charges_left": charges - 1,
            }));
            events.push(json!({
                "type": "ShipRotated",
                "ship_instance_id": active,
                "from_facing": from_facing,
                "to_facing": to_facing,
            }));
        }
        Command::DeclareAttack { target_ship_instance_id } => {
            let attacker_pos = ship_pos;
            validate_attack(state, attacker_pos, target_ship_instance_id, ruleset)?;
            let target_pos = state
                .ships
                .iter()
                .position(|s| s.id == *target_ship_instance_id)
                .expect("validated target exists");
            let att_cell = (state.ships[attacker_pos].q as i32, state.ships[attacker_pos].r as i32);
            let tgt_cell = (state.ships[target_pos].q as i32, state.ships[target_pos].r as i32);
            let ranged = ruleset.ship(&state.ships[attacker_pos].type_id).has_ability(ABILITY_RANGED_SHOT);
            let dist = hex::distance(att_cell.0, att_cell.1, tgt_cell.0, tgt_cell.1);
            let range_penalty: i64 = if ranged { 2 * (dist as i64 - 1) } else { 0 };
            state.ships[attacker_pos].attack_used = true;
            start_combat(state, attacker_pos, target_pos, range_penalty, ruleset, events)?;
        }
        Command::EndActivation => {
            // v3.5 (ADR-018): no charge recovery at the end of the activation
            // any more. Charges stay as they are until the end-of-round
            // rewrite in pass_turn; ActivationEnded keeps reporting the
            // actual count.
            let seat = state.ships[ship_pos].seat.clone();
            let charges = state.ships[ship_pos].charges;
            state.ships[ship_pos].activated = true;
            state.active_ship = None;
            events.push(json!({
                "type": "ActivationEnded",
                "ship_instance_id": active,
                "charges": charges,
            }));
            // Boba's bombs drift at the end of every activation of the owner
            // seat, including the activation that placed them (ADR-016 §3.7).
            drift_bombs_of_seat(state, &seat, ruleset, events);
            pass_turn(state, ruleset, events);
        }
        Command::BeginActivation { .. } | Command::UseHeroAbility { .. }
        | Command::SkipReaction => unreachable!("handled by apply_command_with"),
    }
    Ok(())
}

/// Validation for a regular DeclareAttack (oracle `_validate_attack`).
fn validate_attack(
    state: &MatchState,
    attacker_pos: usize,
    target_id: &str,
    ruleset: &Ruleset,
) -> Result<(), Rejection> {
    let attacker_id = state.ships[attacker_pos].id.clone();
    if state.ships[attacker_pos].attack_used {
        return Err(reject(
            "attack_used",
            format!("ship '{attacker_id}' already attacked this activation"),
        ));
    }
    let Some(target_pos) = state.ships.iter().position(|s| s.id == target_id) else {
        return Err(reject("unknown_ship", format!("no target ship '{target_id}'")));
    };
    let att_cell = (state.ships[attacker_pos].q as i32, state.ships[attacker_pos].r as i32);
    let tgt_cell = (state.ships[target_pos].q as i32, state.ships[target_pos].r as i32);
    let ranged = ruleset
        .ship(&state.ships[attacker_pos].type_id)
        .has_ability(ABILITY_RANGED_SHOT);
    let dist = hex::distance(att_cell.0, att_cell.1, tgt_cell.0, tgt_cell.1);
    if !ranged && dist != 1 {
        return Err(reject(
            "not_adjacent",
            format!("target '{target_id}' is not on a neighboring cell"),
        ));
    }
    if !state.ships[target_pos].alive {
        return Err(reject("bad_target", format!("target '{target_id}' is destroyed")));
    }
    if state.ships[target_pos].team == state.ships[attacker_pos].team {
        return Err(reject("bad_target", format!("target '{target_id}' is an ally")));
    }
    Ok(())
}

/// Starts a full combat of `attacker` against `target` with a fixed
/// range_penalty (0 for a regular melee attack, 2*(dist-1) for the ranged
/// shot, always 0 for vader's force_attack — ADR-016 §3.2). Emits
/// AttackDeclared, rolls the attacker's dice (+vulture reroll), opens
/// reaction windows (pausing the combat in a pending_reaction) or resolves
/// to the end.
fn start_combat(
    state: &mut MatchState,
    attacker_pos: usize,
    target_pos: usize,
    range_penalty: i64,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let attacker_id = state.ships[attacker_pos].id.clone();
    let target_id = state.ships[target_pos].id.clone();
    events.push(json!({
        "type": "AttackDeclared",
        "attacker_id": attacker_id,
        "target_id": target_id,
    }));

    let mut rng = stream_rng(state.seed, &state.dice, ruleset, &state.seat_order);
    let mut roll_index = state.rng_counter;

    // Combat dice parameters are data, not code (ADR-014 §1); the dice counts
    // are clamped to >= 1 like the oracle (`maxi(1, …)`).
    let attacker_dice_count = ruleset.game.combat_attacker_dice.max(1);

    // 1. Attacker dice (ADR-014 §3): every die is its own DieRolled event with
    // its own rng_index; role is "attacker" for all of them.
    let mut faces_a: Vec<i64> = Vec::new();
    for _ in 0..attacker_dice_count {
        faces_a.push(roll_die(&mut rng, 6, "attacker", roll_index, state, events));
        roll_index += 1;
    }

    // 2. Vulture reroll (ADR-014 §3, C011): after the attacker's dice a single
    // d2 (role "attacker") gates exactly one forced reroll of the first natural
    // 1; the rerolled value is final even when it is a 1 again.
    if ruleset
        .ship(&state.ships[attacker_pos].type_id)
        .has_ability(ABILITY_REROLL_ONE)
        && faces_a.contains(&1)
    {
        let reroll_luck = roll_die(&mut rng, 2, "attacker", roll_index, state, events);
        roll_index += 1;
        if reroll_luck == 2 {
            let first_one = faces_a.iter().position(|&face| face == 1).unwrap();
            faces_a[first_one] = roll_die(&mut rng, 6, "attacker", roll_index, state, events);
            roll_index += 1;
        }
    }
    state.rng_counter = roll_index;

    // 3. Reaction windows (ADR-016 §3.5): BEFORE the defender roll — first the
    // attacker seat's luke window, then the defender seat's obi_wan window.
    // In seeded_bots_skip_heroes mode every applicable window is announced and
    // immediately closed with a ReactionSkipped event (no state pause).
    let paused = open_reaction_windows(state, attacker_pos, target_pos, &faces_a, range_penalty, events);
    if paused {
        return Ok(());
    }
    combat_resolve(state, attacker_pos, target_pos, faces_a, range_penalty, ruleset, events);
    Ok(())
}

/// Opens the reaction windows (ADR-016 §3.5): after the attacker's dice (and
/// the vulture reroll), before the defender roll — first the attacker seat's
/// luke window, then the defender seat's obi_wan window. In
/// seeded_bots_skip_heroes mode every applicable window is announced and
/// immediately closed with a ReactionSkipped event (no state pause). Returns
/// true when a window was left open (state.phase = Reaction).
fn open_reaction_windows(
    state: &mut MatchState,
    attacker_pos: usize,
    target_pos: usize,
    faces: &[i64],
    range_penalty: i64,
    events: &mut Vec<Value>,
) -> bool {
    let attacker_id = state.ships[attacker_pos].id.clone();
    let target_id = state.ships[target_pos].id.clone();
    let mut after_kind = String::new();
    while let Some((seat, kind)) = next_reaction_window(state, attacker_pos, target_pos, &after_kind) {
        events.push(json!({
            "type": "ReactionWindow",
            "seat": seat,
            "kind": kind,
        }));
        if state.seeded_bots_skip_heroes {
            events.push(json!({
                "type": "ReactionSkipped",
                "seat": seat,
            }));
            after_kind = kind.to_string();
            continue;
        }
        state.pending_reaction = Some(PendingReaction {
            seat,
            kind: kind.to_string(),
            attacker_id,
            target_id,
            faces: faces.to_vec(),
            range_penalty,
        });
        state.phase = Phase::Reaction;
        return true;
    }
    false
}

/// The next applicable reaction window after `after_kind` ("" = the first):
/// luke for the attacker seat, then obi_wan for the defender seat.
fn next_reaction_window(
    state: &MatchState,
    attacker_pos: usize,
    target_pos: usize,
    after_kind: &str,
) -> Option<(String, &'static str)> {
    let attacker_seat = state.ships[attacker_pos].seat.as_str();
    let target_seat = state.ships[target_pos].seat.as_str();
    if after_kind.is_empty() {
        if let Some(hero) = state.heroes.get(attacker_seat) {
            if hero.hero_id == "luke" && hero.uses_left > 0 {
                return Some((attacker_seat.to_string(), window_kind("luke").unwrap()));
            }
        }
    }
    if after_kind.is_empty() || after_kind == window_kind("luke").unwrap() {
        if let Some(hero) = state.heroes.get(target_seat) {
            if hero.hero_id == "obi_wan" && hero.uses_left > 0 {
                return Some((target_seat.to_string(), window_kind("obi_wan").unwrap()));
            }
        }
    }
    None
}

/// True when the flip `from`->`to` is forbidden for the window kind
/// (ADR-016 §3.5): luke must not turn a 1 into a 6, obi_wan must not turn a
/// 6 into a 1.
fn flip_forbidden(kind: &str, from_face: i64, to_face: i64) -> bool {
    if kind == "luke_flip" {
        return from_face == 1 && to_face == 6;
    }
    if kind == "obi_wan_flip" {
        return from_face == 6 && to_face == 1;
    }
    false
}

/// Resolves the combat after the reaction windows are closed: defender dice,
/// strengths (after every die, ADR-014 §3 item 5), compare, damage and
/// destruction specials.
fn combat_resolve(
    state: &mut MatchState,
    attacker_pos: usize,
    target_pos: usize,
    faces: Vec<i64>,
    range_penalty: i64,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) {
    let mut rng = stream_rng(state.seed, &state.dice, ruleset, &state.seat_order);
    let mut roll_index = state.rng_counter;
    let attacker_id = state.ships[attacker_pos].id.clone();
    let target_id = state.ships[target_pos].id.clone();

    // Defender dice (ADR-014 §3): rolled after the attacker's reroll check and
    // after every reaction window has closed.
    let defender_dice_count = ruleset.game.combat_defender_dice.max(1);
    let flat_bonus = ruleset.game.combat_defender_flat_bonus;
    let mut faces_d: Vec<i64> = Vec::new();
    for _ in 0..defender_dice_count {
        faces_d.push(roll_die(&mut rng, 6, "defender", roll_index, state, events));
        roll_index += 1;
    }

    // C008: sectors follow the ray on both sides; line of sight is never
    // blocked. Ships cannot move while a window is open, so the sectors match
    // the pre-window geometry.
    let att_cell = (state.ships[attacker_pos].q as i32, state.ships[attacker_pos].r as i32);
    let tgt_cell = (state.ships[target_pos].q as i32, state.ships[target_pos].r as i32);
    let att_def: &ShipDef = ruleset.ship(&state.ships[attacker_pos].type_id);
    let def_def: &ShipDef = ruleset.ship(&state.ships[target_pos].type_id);
    let sector_a = hex::sector_index(
        state.ships[attacker_pos].facing as i32,
        ray_direction(att_cell, tgt_cell),
    ) as i64;
    let arc_a = att_def.arc(sector_a);
    let die_a: i64 = faces.iter().sum();
    // ADR-016 §3.1: phasma on the ATTACKER's seat grants the attacker +1.
    let att_flat: i64 = if seat_hero_id(state, &state.ships[attacker_pos].seat) == "phasma" {
        1
    } else {
        0
    };
    let total_a = 0i64.max(0i64.max(die_a + arc_a) - range_penalty) + att_flat;
    let sector_d = hex::sector_index(
        state.ships[target_pos].facing as i32,
        ray_direction(tgt_cell, att_cell),
    ) as i64;
    let arc_d = def_def.arc(sector_d);
    let die_d: i64 = faces_d.iter().sum();
    let total_d = 0i64.max(die_d + flat_bonus + arc_d);

    events.push(json!({
        "type": "StrengthCalculated",
        "ship_instance_id": attacker_id,
        "die": die_a,
        "dice": faces,
        "sector_index": sector_a,
        "arc_bonus": arc_a,
        "total": total_a,
        "range_penalty": range_penalty,
        "flat_bonus": att_flat,
    }));
    events.push(json!({
        "type": "StrengthCalculated",
        "ship_instance_id": target_id,
        "die": die_d,
        "dice": faces_d,
        "sector_index": sector_d,
        "arc_bonus": arc_d,
        "total": total_d,
        "range_penalty": 0,
        "flat_bonus": flat_bonus,
    }));

    state.rng_counter = roll_index;

    // Compare strengths; C009: attacking xwing_t65 on a tie rolls d2,
    // success (2) deals exactly 1 damage to the defender (shield first).
    let mut loser_pos: Option<usize> = None;
    let mut diff: i64 = 0;
    if total_a == total_d {
        if att_def.has_ability(ABILITY_LUCKY_SHOT) {
            let tie_luck = roll_die(&mut rng, 2, "attacker", roll_index, state, events);
            roll_index += 1;
            state.rng_counter = roll_index;
            if tie_luck == 2 {
                loser_pos = Some(target_pos);
                diff = 1;
            }
        }
    } else if total_a > total_d {
        loser_pos = Some(target_pos);
        diff = total_a - total_d;
    } else {
        loser_pos = Some(attacker_pos);
        diff = total_d - total_a;
    }

    // Damage and destruction specials.
    if let Some(loser) = loser_pos {
        apply_damage(state, loser, diff, events);
        if state.ships[loser].hp <= 0 {
            let role = if loser == attacker_pos { "attacker" } else { "defender" };
            resolve_destruction(state, loser, role, &mut rng, &mut roll_index, ruleset, events);
        }
    }
    // Sync the stream position with the full dice journal.
    state.rng_counter = roll_index;
}

/// Reaction window command (ADR-016 §3.5): UseHeroAbility flip or SkipReaction
/// from the window owner. A flip rewrites one attacker die face (no rng
/// consumption — the DieFlipped event replaces the value of the last roll);
/// afterwards the next window opens or the combat resolves.
fn apply_reaction(
    state: &mut MatchState,
    command: &Command,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let pending = state
        .pending_reaction
        .clone()
        .ok_or_else(|| reject("wrong_phase", "no reaction window is open"))?;
    let window_seat = pending.seat.clone();
    let kind = pending.kind.clone();
    let window_hero_id = window_hero(&kind);
    if matches!(command, Command::SkipReaction) {
        events.push(json!({
            "type": "ReactionSkipped",
            "seat": window_seat,
        }));
    } else {
        let Command::UseHeroAbility {
            ability_id,
            die_index,
            value,
            ..
        } = command
        else {
            unreachable!("reaction phase accepts only UseHeroAbility/SkipReaction");
        };
        let expected_ability = hero_ability_id(window_hero_id).unwrap_or_default();
        if ability_id != expected_ability {
            return Err(reject(
                "not_your_hero",
                format!("window '{kind}' expects ability '{expected_ability}'"),
            ));
        }
        let Some(hero) = state.heroes.get_mut(&window_seat) else {
            return Err(reject(
                "not_your_hero",
                format!("seat '{window_seat}' no longer owns hero '{window_hero_id}'"),
            ));
        };
        if hero.hero_id != window_hero_id {
            return Err(reject(
                "not_your_hero",
                format!("seat '{window_seat}' no longer owns hero '{window_hero_id}'"),
            ));
        }
        if hero.uses_left <= 0 {
            return Err(reject(
                "hero_no_uses",
                format!("hero '{window_hero_id}' has no uses left"),
            ));
        }
        let faces = &pending.faces;
        let die_index = die_index.unwrap_or(-1);
        if die_index < 0 || die_index as usize >= faces.len() {
            return Err(reject(
                "bad_target",
                format!("die_index {die_index} outside 0..{}", faces.len() as i64 - 1),
            ));
        }
        let value = value.unwrap_or(0);
        if !(1..=6).contains(&value) {
            return Err(reject("bad_target", format!("die face {value} outside 1..6")));
        }
        let from_face = faces[die_index as usize];
        if value == from_face {
            return Err(reject(
                "bad_target",
                format!("die {die_index} already shows {from_face}"),
            ));
        }
        if flip_forbidden(&kind, from_face, value) {
            return Err(reject(
                "bad_target",
                format!("flip {from_face}->{value} is forbidden for '{window_hero_id}'"),
            ));
        }
        let hero = state.heroes.get_mut(&window_seat).expect("checked above");
        hero.uses_left -= 1;
        events.push(json!({
            "type": "AbilityUsed",
            "seat": window_seat,
            "hero_id": window_hero_id,
            "ability_id": expected_ability,
        }));
        let mut faces_now = pending.faces.clone();
        faces_now[die_index as usize] = value;
        events.push(json!({
            "type": "DieFlipped",
            "role": "attacker",
            "die_index": die_index,
            "from": from_face,
            "to": value,
            "by_hero": window_hero_id,
        }));
        state.pending_reaction = Some(PendingReaction {
            seat: pending.seat.clone(),
            kind: kind.clone(),
            attacker_id: pending.attacker_id.clone(),
            target_id: pending.target_id.clone(),
            faces: faces_now.clone(),
            range_penalty: pending.range_penalty,
        });
    }

    // Close this window; open the next one (defender obi_wan after attacker
    // luke) or resolve the combat.
    let attacker_pos = state
        .ships
        .iter()
        .position(|s| s.id == pending.attacker_id)
        .ok_or_else(|| reject("unknown_ship", format!("no ship '{}'", pending.attacker_id)))?;
    let target_pos = state
        .ships
        .iter()
        .position(|s| s.id == pending.target_id)
        .ok_or_else(|| reject("unknown_ship", format!("no ship '{}'", pending.target_id)))?;
    let faces_now = match &state.pending_reaction {
        Some(p) => p.faces.clone(),
        None => pending.faces.clone(),
    };
    let range_penalty = pending.range_penalty;
    let next_window =
        next_reaction_window(state, attacker_pos, target_pos, &kind);
    if let Some((seat, next_kind)) = next_window {
        events.push(json!({
            "type": "ReactionWindow",
            "seat": seat,
            "kind": next_kind,
        }));
        state.pending_reaction = Some(PendingReaction {
            seat,
            kind: next_kind.to_string(),
            attacker_id: pending.attacker_id.clone(),
            target_id: pending.target_id.clone(),
            faces: faces_now,
            range_penalty,
        });
        // Phase stays Reaction; the match-end check cannot change while a
        // window is open (no damage happened since the attack was declared).
        return Ok(());
    }
    state.pending_reaction = None;
    state.phase = Phase::Activation;
    combat_resolve(state, attacker_pos, target_pos, faces_now, range_penalty, ruleset, events);
    Ok(())
}

/// UseHeroAbility in the activation phase (ADR-016 §2-§3): a free action of
/// the active seat's hero. Active abilities only; the reaction flips are
/// handled by apply_reaction inside an open window.
fn apply_hero_ability(
    state: &mut MatchState,
    command: &Command,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let Command::UseHeroAbility { ability_id, .. } = command else {
        unreachable!("apply_hero_ability is only called for UseHeroAbility");
    };
    let active_seat = state.active_seat.clone();
    let active = state
        .active_ship
        .clone()
        .ok_or_else(|| {
            reject(
                "bad_phase_for_ability",
                "hero abilities need an active ship (BeginActivation first)",
            )
        })?;
    let ship_pos = state
        .ships
        .iter()
        .position(|s| s.id == active)
        .ok_or_else(|| {
            reject(
                "bad_phase_for_ability",
                "active ship is missing or destroyed",
            )
        })?;
    if !state.ships[ship_pos].alive {
        return Err(reject(
            "bad_phase_for_ability",
            "active ship is missing or destroyed",
        ));
    }
    let Some(hero) = state.heroes.get(&active_seat) else {
        return Err(reject(
            "not_your_hero",
            format!("seat '{active_seat}' has no hero"),
        ));
    };
    let hero_id = hero.hero_id.clone();
    if hero_ability_id(&hero_id) != Some(ability_id.as_str()) {
        return Err(reject(
            "not_your_hero",
            format!("hero '{hero_id}' has no ability '{ability_id}'"),
        ));
    }
    if hero.uses_left <= 0 {
        return Err(reject(
            "hero_no_uses",
            format!("hero '{hero_id}' has no uses left"),
        ));
    }
    match hero_id.as_str() {
        "darth_vader" => hero_force_attack(state, ship_pos, command, ruleset, events),
        "anakin" => hero_force_push(state, ship_pos, command, ruleset, events),
        "han_solo" => hero_hyperjump(state, ship_pos, command, ruleset, events),
        "jango_fett" => hero_place_mine(state, ship_pos, events),
        "boba_fett" => hero_place_bomb(state, ship_pos, command, ruleset, events),
        _ => Err(reject(
            "not_your_hero",
            format!("hero '{hero_id}' has no usable ability"),
        )),
    }
}

/// Vader "force_attack" (ADR-016 §3.2): a full regular combat against a living
/// enemy at distance EXACTLY 2 (never touching), no range penalty, sectors
/// from the ray. Counts as the activation's attack: attack_used = true.
fn hero_force_attack(
    state: &mut MatchState,
    attacker_pos: usize,
    command: &Command,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let Command::UseHeroAbility { target_ship_instance_id, .. } = command else {
        unreachable!("hero_force_attack is only called for UseHeroAbility");
    };
    let attacker_id = state.ships[attacker_pos].id.clone();
    if state.ships[attacker_pos].attack_used {
        return Err(reject(
            "attack_used",
            format!("ship '{attacker_id}' already attacked this activation"),
        ));
    }
    let target_id = target_ship_instance_id.clone().unwrap_or_default();
    let Some(target_pos) = state.ships.iter().position(|s| s.id == target_id) else {
        return Err(reject(
            "bad_target",
            format!("no living target ship '{target_id}'"),
        ));
    };
    if !state.ships[target_pos].alive {
        return Err(reject(
            "bad_target",
            format!("no living target ship '{target_id}'"),
        ));
    }
    if state.ships[target_pos].team == state.ships[attacker_pos].team {
        return Err(reject(
            "bad_target",
            format!("target '{target_id}' is an ally"),
        ));
    }
    let dist = hex::distance(
        state.ships[attacker_pos].q as i32,
        state.ships[attacker_pos].r as i32,
        state.ships[target_pos].q as i32,
        state.ships[target_pos].r as i32,
    );
    if dist != 2 {
        return Err(reject(
            "not_in_range",
            format!("target '{target_id}' is at distance {dist}, force_attack needs 2"),
        ));
    }
    let active_seat = state.active_seat.clone();
    let hero = state.heroes.get_mut(&active_seat).expect("hero checked by caller");
    hero.uses_left -= 1;
    state.ships[attacker_pos].attack_used = true;
    events.push(json!({
        "type": "AbilityUsed",
        "seat": active_seat,
        "hero_id": "darth_vader",
        "ability_id": "force_attack",
    }));
    start_combat(state, attacker_pos, target_pos, 0, ruleset, events)
}

/// Anakin "force_push" (ADR-016 §3.3): move ANY living ship one cell along
/// `dir`; the destination must be on the board and free. Facing is kept.
fn hero_force_push(
    state: &mut MatchState,
    _ship_pos: usize,
    command: &Command,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let Command::UseHeroAbility { ship_instance_id, dir, .. } = command else {
        unreachable!("hero_force_push is only called for UseHeroAbility");
    };
    let target_id = ship_instance_id.clone().unwrap_or_default();
    let Some(victim_pos) = state.ships.iter().position(|s| s.id == target_id) else {
        return Err(reject("bad_target", format!("no living ship '{target_id}'")));
    };
    if !state.ships[victim_pos].alive {
        return Err(reject("bad_target", format!("no living ship '{target_id}'")));
    }
    let dir = dir.unwrap_or(-1);
    if !(0..=5).contains(&dir) {
        return Err(reject("bad_direction", format!("dir {dir} outside 0..5")));
    }
    let from_cell = (state.ships[victim_pos].q as i32, state.ships[victim_pos].r as i32);
    let (tq, tr) = hex::step(from_cell.0, from_cell.1, dir as usize);
    if !hex::in_board(tq, tr, ruleset.board_radius as i32) {
        return Err(reject(
            "out_of_board",
            format!("cell ({tq},{tr}) is outside the board"),
        ));
    }
    if alive_ship_at(state, tq, tr).is_some() {
        return Err(reject("occupied_cell", format!("cell ({tq},{tr}) is occupied")));
    }
    let active_seat = state.active_seat.clone();
    let hero = state.heroes.get_mut(&active_seat).expect("hero checked by caller");
    hero.uses_left -= 1;
    events.push(json!({
        "type": "AbilityUsed",
        "seat": active_seat,
        "hero_id": "anakin",
        "ability_id": "force_push",
    }));
    let (fq, fr) = (state.ships[victim_pos].q, state.ships[victim_pos].r);
    {
        let victim = &mut state.ships[victim_pos];
        victim.q = tq as i64;
        victim.r = tr as i64;
    }
    events.push(json!({
        "type": "ShipMoved",
        "ship_instance_id": target_id,
        "from_q": fq, "from_r": fr,
        "to_q": tq as i64, "to_r": tr as i64,
    }));
    check_mines_after_move(state, victim_pos, ruleset, events);
    Ok(())
}

/// Han "hyperjump" (ADR-016 §3.4): move the seat's active ship to any board
/// cell that is free and not adjacent to a living enemy. Needs charges >= 1
/// and zeroes them. Facing is kept.
fn hero_hyperjump(
    state: &mut MatchState,
    ship_pos: usize,
    command: &Command,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let Command::UseHeroAbility { q, r, .. } = command else {
        unreachable!("hero_hyperjump is only called for UseHeroAbility");
    };
    let ship_id = state.ships[ship_pos].id.clone();
    if state.ships[ship_pos].charges <= 0 {
        return Err(reject("no_charges", format!("ship '{ship_id}' has 0 charges")));
    }
    let tq = q.unwrap_or(9999);
    let tr = r.unwrap_or(9999);
    if !hex::in_board(tq as i32, tr as i32, ruleset.board_radius as i32) {
        return Err(reject(
            "out_of_board",
            format!("cell ({tq},{tr}) is outside the board"),
        ));
    }
    if alive_ship_at(state, tq as i32, tr as i32).is_some() {
        return Err(reject("occupied_cell", format!("cell ({tq},{tr}) is occupied")));
    }
    let team = state.ships[ship_pos].team.clone();
    if living_enemy_near(state, tq as i32, tr as i32, &team) {
        return Err(reject(
            "too_close_to_enemy",
            format!("cell ({tq},{tr}) neighbors a living enemy"),
        ));
    }
    let from_cell = (state.ships[ship_pos].q, state.ships[ship_pos].r);
    let active_seat = state.active_seat.clone();
    let hero = state.heroes.get_mut(&active_seat).expect("hero checked by caller");
    hero.uses_left -= 1;
    events.push(json!({
        "type": "AbilityUsed",
        "seat": active_seat,
        "hero_id": "han_solo",
        "ability_id": "hyperjump",
    }));
    {
        let ship = &mut state.ships[ship_pos];
        // v3.5 (ADR-018): zeroing the charges is a spend — it feeds the tally.
        ship.spent_round += ship.charges;
        ship.charges = 0;
        ship.q = tq;
        ship.r = tr;
    }
    events.push(json!({
        "type": "ChargeSpent",
        "ship_instance_id": ship_id,
        "reason": "hyperjump",
        "charges_left": 0,
    }));
    events.push(json!({
        "type": "ShipMoved",
        "ship_instance_id": ship_id,
        "from_q": from_cell.0, "from_r": from_cell.1,
        "to_q": tq, "to_r": tr,
    }));
    check_mines_after_move(state, ship_pos, ruleset, events);
    Ok(())
}

/// Jango "place_mine" (ADR-016 §3.6): a mine goes onto the active ship's cell.
/// Ships already standing in the trigger radius do not detonate it; it blows
/// up when any ship ENTERS the cell or a neighbor after a move (§5).
fn hero_place_mine(
    state: &mut MatchState,
    ship_pos: usize,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let cell = (state.ships[ship_pos].q, state.ships[ship_pos].r);
    let active_seat = state.active_seat.clone();
    let hero = state.heroes.get_mut(&active_seat).expect("hero checked by caller");
    hero.uses_left -= 1;
    let seat = active_seat.clone();
    events.push(json!({
        "type": "AbilityUsed",
        "seat": seat,
        "hero_id": "jango_fett",
        "ability_id": "place_mine",
    }));
    state.objects.push(GameObject {
        kind: "mine".to_string(),
        q: cell.0,
        r: cell.1,
        seat,
        dir: None,
        moves_left: None,
    });
    events.push(json!({
        "type": "MinePlaced",
        "seat": active_seat,
        "q": cell.0,
        "r": cell.1,
    }));
    Ok(())
}

/// Boba "place_bomb" (ADR-016 §3.7): a bomb with a fixed direction goes onto
/// the active ship's cell and drifts one cell at the end of every activation
/// of the owner seat (first drift at the end of this very activation), at
/// most BOMB_MAX_SHIFTS times.
fn hero_place_bomb(
    state: &mut MatchState,
    ship_pos: usize,
    command: &Command,
    _ruleset: &Ruleset,
    events: &mut Vec<Value>,
) -> Result<(), Rejection> {
    let Command::UseHeroAbility { dir, .. } = command else {
        unreachable!("hero_place_bomb is only called for UseHeroAbility");
    };
    let dir = dir.unwrap_or(-1);
    if !(0..=5).contains(&dir) {
        return Err(reject("bad_direction", format!("dir {dir} outside 0..5")));
    }
    let cell = (state.ships[ship_pos].q, state.ships[ship_pos].r);
    let active_seat = state.active_seat.clone();
    let hero = state.heroes.get_mut(&active_seat).expect("hero checked by caller");
    hero.uses_left -= 1;
    let seat = active_seat.clone();
    events.push(json!({
        "type": "AbilityUsed",
        "seat": seat,
        "hero_id": "boba_fett",
        "ability_id": "place_bomb",
    }));
    state.objects.push(GameObject {
        kind: "bomb".to_string(),
        q: cell.0,
        r: cell.1,
        seat,
        dir: Some(dir),
        moves_left: Some(BOMB_MAX_SHIFTS),
    });
    events.push(json!({
        "type": "BombPlaced",
        "seat": active_seat,
        "q": cell.0,
        "r": cell.1,
        "dir": dir,
    }));
    Ok(())
}

/// Mine trigger check (ADR-016 §3.8/§5) after ANY ship movement: a mine in the
/// ship's new cell or one of its six neighbors detonates — 1 x d4 damage
/// (shield first), the mine is removed. The chain stops when the ship is
/// destroyed. Dice of the whole effect chain carry role "effect".
fn check_mines_after_move(
    state: &mut MatchState,
    ship_pos: usize,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) {
    let cell = (state.ships[ship_pos].q as i32, state.ships[ship_pos].r as i32);
    let mut radius_cells: Vec<(i32, i32)> = vec![cell];
    radius_cells.extend(hex::neighbors(cell.0, cell.1));
    while state.ships[ship_pos].alive {
        let hit_index = state.objects.iter().position(|obj| {
            obj.kind == "mine" && radius_cells.contains(&(obj.q as i32, obj.r as i32))
        });
        let Some(hit_index) = hit_index else {
            return;
        };
        let mine = state.objects.remove(hit_index);
        let at_cell = (mine.q, mine.r);
        apply_effect_damage(state, ship_pos, &mine.seat.clone(), at_cell, "mine", ruleset, events);
    }
}

/// One d4 effect hit (mine or bomb, ADR-016 §3.8): DieRolled (role "effect")
/// -> DamageApplied (shield first) -> MineTriggered/BombTriggered ->
/// ObjectRemoved; a lethal hit runs the regular destruction pipeline
/// (ghost/tie, ADR-012) with role "effect" on its dice.
fn apply_effect_damage(
    state: &mut MatchState,
    victim_pos: usize,
    owner_seat: &str,
    at_cell: (i64, i64),
    kind: &str,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) {
    let mut rng = stream_rng(state.seed, &state.dice, ruleset, &state.seat_order);
    let mut roll_index = state.rng_counter;
    let damage = roll_die(&mut rng, 4, "effect", roll_index, state, events);
    roll_index += 1;
    state.rng_counter = roll_index;
    apply_damage(state, victim_pos, damage, events);
    events.push(json!({
        "type": if kind == "mine" { "MineTriggered" } else { "BombTriggered" },
        "seat": owner_seat,
        "q": at_cell.0,
        "r": at_cell.1,
        "target_id": state.ships[victim_pos].id,
    }));
    events.push(json!({
        "type": "ObjectRemoved",
        "kind": kind,
        "q": at_cell.0,
        "r": at_cell.1,
    }));
    if state.ships[victim_pos].hp <= 0 {
        resolve_destruction(state, victim_pos, "effect", &mut rng, &mut roll_index, ruleset, events);
    }
    state.rng_counter = roll_index;
}

/// Bomb drift (ADR-016 §3.7): at the end of every activation of the owner seat
/// each of its bombs steps one cell along its fixed direction. Off the board
/// -> despawn; ship in the destination cell -> 1 x d4 explosion; third step
/// -> the charge disperses (despawn, no explosion).
fn drift_bombs_of_seat(
    state: &mut MatchState,
    seat: &str,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) {
    let mut i = 0usize;
    while i < state.objects.len() {
        let obj = &state.objects[i];
        if obj.kind != "bomb" || obj.seat != seat {
            i += 1;
            continue;
        }
        let from_cell = (obj.q, obj.r);
        let to = hex::step(from_cell.0 as i32, from_cell.1 as i32, obj.dir.unwrap_or(0) as usize);
        let to_cell = (to.0 as i64, to.1 as i64);
        if !hex::in_board(to.0, to.1, ruleset.board_radius as i32) {
            state.objects.remove(i);
            events.push(json!({
                "type": "ObjectRemoved",
                "kind": "bomb",
                "q": from_cell.0,
                "r": from_cell.1,
            }));
            continue;
        }
        let victim = alive_ship_pos(state, to.0, to.1);
        {
            let obj = &mut state.objects[i];
            obj.q = to_cell.0;
            obj.r = to_cell.1;
        }
        events.push(json!({
            "type": "BombMoved",
            "seat": seat,
            "from_q": from_cell.0,
            "from_r": from_cell.1,
            "to_q": to_cell.0,
            "to_r": to_cell.1,
        }));
        if let Some(victim_pos) = victim {
            state.objects.remove(i);
            apply_effect_damage(state, victim_pos, seat, to_cell, "bomb", ruleset, events);
            continue;
        }
        let moves_left = state.objects[i].moves_left.unwrap_or(0) - 1;
        state.objects[i].moves_left = Some(moves_left);
        if moves_left <= 0 {
            state.objects.remove(i);
            events.push(json!({
                "type": "ObjectRemoved",
                "kind": "bomb",
                "q": to_cell.0,
                "r": to_cell.1,
            }));
            continue;
        }
        i += 1;
    }
}

/// Rolls one die, appends its side to the state dice journal and the
/// DieRolled event (rng_index = index) to the journal.
fn roll_die(
    rng: &mut Mulberry32Compat,
    sides: u32,
    role: &str,
    index: i64,
    state: &mut MatchState,
    events: &mut Vec<Value>,
) -> i64 {
    let value = rng.next_die(sides);
    state.dice.push(sides as u8);
    events.push(json!({
        "type": "DieRolled",
        "rng_index": index,
        "sides": sides,
        "value": value,
        "role": role,
    }));
    value as i64
}

/// Shield-first damage of `diff` points; emits DamageApplied.
fn apply_damage(state: &mut MatchState, loser_pos: usize, diff: i64, events: &mut Vec<Value>) {
    let loser = &mut state.ships[loser_pos];
    let shield = loser.shield;
    let hp = loser.hp;
    let shield_damage = shield.min(diff);
    let hull_damage = hp.min(diff - shield_damage);
    loser.shield = shield - shield_damage;
    loser.hp = hp - hull_damage;
    events.push(json!({
        "type": "DamageApplied",
        "target_id": loser.id,
        "shield_damage": shield_damage,
        "hull_damage": hull_damage,
        "hp_left": loser.hp,
        "shield_left": loser.shield,
    }));
}

/// Resolves hp <= 0 of the loser (ADR-012): ghost transforms instead of dying
/// (no dice), tie_fighter gets one d2 revive attempt per match (d4 hp on
/// success), otherwise the ship is destroyed. ShipDestroyed is emitted only
/// when the destruction is final — never before a revive attempt resolves.
#[allow(clippy::too_many_arguments)]
fn resolve_destruction(
    state: &mut MatchState,
    loser_pos: usize,
    role: &str,
    rng: &mut Mulberry32Compat,
    roll_index: &mut i64,
    ruleset: &Ruleset,
    events: &mut Vec<Value>,
) {
    let loser_id = state.ships[loser_pos].id.clone();
    let from_type = state.ships[loser_pos].type_id.clone();
    state.ships[loser_pos].hp = 0;
    let loser_def = ruleset.ships.get(&from_type);

    if loser_def.map(|d| d.has_ability(ABILITY_TRANSFORM)).unwrap_or(false) {
        let mut to_type = "phantom".to_string();
        if let Some(ability) = loser_def
            .map(|d| d.abilities.iter().find(|a| a.id == ABILITY_TRANSFORM))
            .unwrap_or(None)
        {
            if let Some(t) = &ability.transform_to {
                to_type = t.clone();
            }
        }
        let phantom_def = ruleset.ships.get(&to_type);
        let hp = phantom_def.map(|d| d.max_hp).unwrap_or(1);
        let charges = state.ships[loser_pos]
            .charges
            .min(phantom_def.map(|d| d.max_charges).unwrap_or(5));
        let loser = &mut state.ships[loser_pos];
        loser.type_id = to_type.clone();
        loser.hp = hp;
        loser.shield = 0;
        loser.charges = charges;
        events.push(json!({
            "type": "ShipTransformed",
            "ship_instance_id": loser_id,
            "from_type": from_type,
            "to_type": to_type,
            "hp": hp,
            "shield": 0,
            "charges": charges,
        }));
        return;
    }

    let can_revive = loser_def
        .map(|d| d.has_ability(ABILITY_RESURRECTION))
        .unwrap_or(false)
        && !state.ships[loser_pos].revive_used;
    if can_revive {
        state.ships[loser_pos].revive_used = true;
        let luck = roll_die(rng, 2, role, *roll_index, state, events);
        *roll_index += 1;
        if luck == 2 {
            let hp = roll_die(rng, 4, role, *roll_index, state, events);
            *roll_index += 1;
            let loser = &mut state.ships[loser_pos];
            loser.hp = hp;
            loser.shield = 0;
            loser.alive = true;
            events.push(json!({
                "type": "ShipRevived",
                "ship_instance_id": loser_id,
                "hp": hp,
            }));
            state.rng_counter = *roll_index;
            return;
        }
    }
    state.ships[loser_pos].alive = false;
    events.push(json!({
        "type": "ShipDestroyed",
        "ship_instance_id": loser_id,
    }));
    state.rng_counter = *roll_index;
}

// --- Turn passing and match end ----------------------------------------------

fn pass_turn(state: &mut MatchState, ruleset: &Ruleset, events: &mut Vec<Value>) {
    // Turn order is scenario data (ADR-015); empty order falls back to the
    // full 2x2 composition like the oracle.
    let order: Vec<String> = if state.seat_order.is_empty() {
        SEAT_ORDER.iter().map(|s| s.to_string()).collect()
    } else {
        state.seat_order.clone()
    };
    let idx = order
        .iter()
        .position(|s| *s == state.active_seat)
        .unwrap_or(0);
    for j in 1..=order.len() {
        let candidate = order[(idx + j) % order.len()].clone();
        if seat_has_actionable(state, &candidate) {
            state.active_seat = candidate;
            return;
        }
    }
    // Every living ship has activated: the round is complete. v3.5 (ADR-018):
    // charges are REWRITTEN once here, before RoundStarted(n+1) — a decided
    // match (round limit reached, or this very activation ended the game)
    // neither refreshes charges nor starts a next round.
    let next_round = state.round + 1;
    if next_round > state.round_limit {
        state.phase = Phase::Ended;
        state.winner = None;
        events.push(json!({
            "type": "MatchEnded",
            "winner": null,
            "reason": "round_limit",
        }));
        return;
    }
    if match_is_decided(state) {
        return;
    }
    refresh_round_charges(state, ruleset, events);
    state.round = next_round;
    for ship in &mut state.ships {
        ship.activated = false;
        ship.attack_used = false;
        // v3.5 (ADR-018): the spend tally resets with the new round.
        ship.spent_round = 0;
    }
    state.active_seat = first_seat_with_living(state);
    events.push(json!({ "type": "RoundStarted", "round": next_round }));
}

/// True when the outcome is already fixed: at most one team still has living
/// ships (victory or draw). Mirrors the finish check; used by pass_turn so a
/// round whose last activation ended the match never rolls into the next
/// round and never rewrites charges (ADR-018).
fn match_is_decided(state: &MatchState) -> bool {
    let mut alive_by_team: BTreeMap<&str, i64> = BTreeMap::new();
    for ship in &state.ships {
        if ship.alive {
            *alive_by_team.entry(ship.team.as_str()).or_insert(0) += 1;
        }
    }
    alive_by_team.len() <= 1
}

/// v3.5 end-of-round charge rewrite (ADR-018): every LIVING ship's charges
/// are overwritten (never added to) — max_charges when the ship spent no
/// charge this round (spent_round == 0, "saved up -> full tank"),
/// ceil(max_charges/2) otherwise. max_charges is read from the individual
/// ship card. One ChargesRefreshed event per living ship, in ships array
/// order. Pure bookkeeping: the dice log is untouched, so
/// rng_counter == dice.len() holds. With charge_round_reset = "none" in
/// game.json the rewrite is skipped.
fn refresh_round_charges(state: &mut MatchState, ruleset: &Ruleset, events: &mut Vec<Value>) {
    if ruleset.game.charge_round_reset == "none" {
        return;
    }
    for i in 0..state.ships.len() {
        if !state.ships[i].alive {
            continue;
        }
        let max_charges = ruleset.ship(&state.ships[i].type_id).max_charges.max(1);
        let full = ruleset.game.charge_full_if_unused && state.ships[i].spent_round == 0;
        let charges = if full { max_charges } else { (max_charges + 1) / 2 };
        state.ships[i].charges = charges;
        events.push(json!({
            "type": "ChargesRefreshed",
            "ship_instance_id": state.ships[i].id,
            "charges": charges,
            "full": full,
        }));
    }
}

/// Match-end check after every applied command (core-api §4.3 item 7). Teams
/// are scenario data (ADR-015): the match ends when at most one team still
/// has living ships; with two teams (A/B) the outcome is identical to
/// counting alive_a/alive_b as before.
fn finish(state: &mut MatchState, events: &mut Vec<Value>) {
    if state.phase != Phase::Ended {
        // Only teams with at least one living ship get an entry, so every
        // count below is > 0 (mirrors the oracle's alive_by_team dictionary).
        let mut alive_by_team: BTreeMap<String, i64> = BTreeMap::new();
        for ship in &state.ships {
            if ship.alive {
                *alive_by_team.entry(ship.team.clone()).or_insert(0) += 1;
            }
        }
        if alive_by_team.is_empty() {
            state.phase = Phase::Ended;
            state.winner = None;
            events.push(json!({ "type": "MatchEnded", "winner": null, "reason": "both_eliminated" }));
        } else if alive_by_team.len() == 1 {
            let last_team = alive_by_team.into_keys().next().expect("one team");
            state.phase = Phase::Ended;
            state.winner = Some(last_team.clone());
            events.push(json!({ "type": "MatchEnded", "winner": last_team, "reason": "elimination" }));
        }
    }
}

// --- Draft (core-api §4.1) -----------------------------------------------------

#[derive(Default, Clone)]
struct SeatDraft {
    sum: i64,
    g2: i64,
    g1: std::collections::BTreeMap<String, i64>,
}

/// Deterministic draft; consumes exactly one rng.next_below per pick.
/// Drafts only for the scenario seats, in seat_order (ADR-015: 2 seats for
/// the duel, 4 for the full 2x2). Returns None when a seat runs out of
/// candidates (configuration error).
fn run_draft(
    rng: &mut Mulberry32Compat,
    ruleset: &Ruleset,
    seat_order: &[String],
) -> Option<Vec<Pick>> {
    let game = &ruleset.game;
    let fleet_size = game.fleet_size;
    let budget = game.draft_budget;
    let max_group2 = game.max_group2_per_seat;
    let max_same_g1 = game.max_same_type_group1_per_seat;
    let ids = &ruleset.ship_ids;

    let mut seat_state: BTreeMap<&str, SeatDraft> = seat_order
        .iter()
        .map(|s| (s.as_str(), SeatDraft::default()))
        .collect();
    let mut g2_taken: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut picks: Vec<Pick> = Vec::new();

    for round_index in 0..fleet_size {
        for seat in seat_order {
            let seat = seat.as_str();
            let ss = &seat_state[seat];
            let mut candidates: Vec<&str> = Vec::new();
            for type_id in ids {
                let def = ruleset.ship(type_id);
                if !def.draftable {
                    continue;
                }
                match def.group {
                    0 => continue,
                    2 => {
                        if ss.g2 >= max_group2 || g2_taken.contains(type_id) {
                            continue;
                        }
                    }
                    _ => {
                        if ss.g1.get(type_id).copied().unwrap_or(0) >= max_same_g1 {
                            continue;
                        }
                    }
                }
                let cost = def.draft_cost;
                let remaining = fleet_size - round_index - 1;
                if remaining == 0 {
                    if ss.sum + cost > budget {
                        continue;
                    }
                } else {
                    let min_rest = min_remaining_cost(
                        ruleset, ss, &g2_taken, type_id, remaining, max_group2, max_same_g1,
                    );
                    if min_rest < 0 || ss.sum + cost + min_rest > budget {
                        continue;
                    }
                }
                candidates.push(type_id.as_str());
            }
            if candidates.is_empty() {
                return None;
            }
            let choice = candidates[rng.next_below(candidates.len() as u32) as usize];
            let chosen = ruleset.ship(choice);
            picks.push(Pick {
                seat: seat.to_string(),
                ship_instance_id: format!("{seat}_{choice}_{round_index}"),
                ship_type_id: choice.to_string(),
                cost: chosen.draft_cost,
            });
            let ss = seat_state.get_mut(seat).unwrap();
            ss.sum += chosen.draft_cost;
            if chosen.group == 2 {
                ss.g2 += 1;
                g2_taken.insert(choice.to_string());
            } else {
                *ss.g1.entry(choice.to_string()).or_insert(0) += 1;
            }
        }
    }
    Some(picks)
}

/// Deterministic hero draft (ADR-016 §1): one distinct hero per scenario seat
/// in seat_order; every pick consumes exactly one rng.next_below over the
/// remaining pool of hero ids (sorted). Returns {seat: {hero_id, uses_left}}
/// with uses_left from the hero card (uses_per_match; 0 for the passive
/// phasma). An empty hero store yields an empty map (engine runs hero-less).
fn run_hero_draft(
    rng: &mut Mulberry32Compat,
    ruleset: &Ruleset,
    seat_order: &[String],
) -> Heroes {
    let mut pool: Vec<String> = ruleset.heroes.keys().cloned().collect();
    let mut heroes = Heroes::default();
    for seat in seat_order {
        if pool.is_empty() {
            break;
        }
        let index = rng.next_below(pool.len() as u32) as usize;
        let hero_id = pool.remove(index);
        let uses = ruleset
            .heroes
            .get(&hero_id)
            .map(|h: &HeroDef| h.uses_per_match)
            .unwrap_or(0);
        heroes.insert(
            seat.clone(),
            HeroState {
                hero_id,
                uses_left: uses,
            },
        );
    }
    heroes
}

/// Cheapest sum of `remaining` ship types still allowed for the seat after it
/// hypothetically takes extra_type; -1 if not enough allowed types remain.
fn min_remaining_cost(
    ruleset: &Ruleset,
    ss: &SeatDraft,
    g2_taken: &std::collections::BTreeSet<String>,
    extra_type: &str,
    remaining: i64,
    max_group2: i64,
    max_same_g1: i64,
) -> i64 {
    let extra = ruleset.ship(extra_type);
    let mut g2 = ss.g2;
    let mut g1 = ss.g1.clone();
    let mut g2_after: std::collections::BTreeSet<String> = g2_taken.clone();
    if extra.group == 2 {
        g2 += 1;
        g2_after.insert(extra_type.to_string());
    } else {
        *g1.entry(extra_type.to_string()).or_insert(0) += 1;
    }
    let mut costs: Vec<i64> = Vec::new();
    for type_id in &ruleset.ship_ids {
        let def = ruleset.ship(type_id);
        if !def.draftable {
            continue;
        }
        match def.group {
            0 => continue,
            2 => {
                if g2 >= max_group2 || g2_after.contains(type_id) {
                    continue;
                }
            }
            _ => {
                if g1.get(type_id).copied().unwrap_or(0) >= max_same_g1 {
                    continue;
                }
            }
        }
        costs.push(def.draft_cost);
    }
    if (costs.len() as i64) < remaining {
        return -1;
    }
    costs.sort_unstable();
    costs[..remaining as usize].iter().sum()
}

// --- RNG stream reconstruction (ADR-012 §7) ------------------------------------

/// An Rng positioned so that the next next_die() continues the match stream
/// exactly after the dice recorded in `dice_log`: fleet draft + hero draft
/// plus one next_die per recorded side. The prototype keeps a cache for speed
/// only; rebuilding from the seed is always exact.
fn stream_rng(
    seed: i64,
    dice_log: &[u8],
    ruleset: &Ruleset,
    seat_order: &[String],
) -> Mulberry32Compat {
    let mut rng = Mulberry32Compat::new(seed as u64);
    let _ = run_draft(&mut rng, ruleset, seat_order);
    let _ = run_hero_draft(&mut rng, ruleset, seat_order);
    for &sides in dice_log {
        rng.next_die(u32::from(sides));
    }
    rng
}

// --- Special-rule helpers -------------------------------------------------------

/// Direction index 0..5 of the straight ray from `from` toward `to`, defined
/// for any distance (C008 ranged sectors). Exact hex direction for neighbors;
/// otherwise the direction whose unit vector encloses the smallest angle with
/// the offset, computed in exact integer arithmetic: with X = 2q + r the
/// projection score of offset (dq, dr) onto direction delta (a, b) is
/// (2*dq + dr) * (2*a + b) + 3 * dr * b — up to one positive factor. Ties
/// resolve to the lowest direction index. No floats, fully deterministic.
fn ray_direction(from: (i32, i32), to: (i32, i32)) -> i32 {
    let exact = hex::direction_from(from.0, from.1, to.0, to.1);
    if exact >= 0 {
        return exact;
    }
    let wx = 2 * (to.0 - from.0) + (to.1 - from.1);
    let wy = to.1 - from.1;
    let mut best_dir = 0i32;
    let mut best_score: i64 = -1;
    for d in 0..6usize {
        let (dx, dy) = hex::DIR_DELTAS[d];
        let score = i64::from(wx * (2 * dx + dy)) + 3 * i64::from(wy * dy);
        if score > best_score {
            best_score = score;
            best_dir = d as i32;
        }
    }
    best_dir
}

// --- Small helpers --------------------------------------------------------------

fn alive_ship_at(state: &MatchState, q: i32, r: i32) -> Option<&ShipState> {
    state
        .ships
        .iter()
        .find(|s| s.alive && s.q == i64::from(q) && s.r == i64::from(r))
}

fn alive_ship_pos(state: &MatchState, q: i32, r: i32) -> Option<usize> {
    state
        .ships
        .iter()
        .position(|s| s.alive && s.q == i64::from(q) && s.r == i64::from(r))
}

/// Hero id of `seat` in the state, "" when the seat has none.
fn seat_hero_id<'a>(state: &'a MatchState, seat: &str) -> &'a str {
    state
        .heroes
        .get(seat)
        .map(|h| h.hero_id.as_str())
        .unwrap_or("")
}

/// True when a living enemy-team ship sits on `cell` or one of its neighbors.
fn living_enemy_near(state: &MatchState, q: i32, r: i32, team: &str) -> bool {
    hex::neighbors(q, r)
        .iter()
        .filter_map(|&(nq, nr)| alive_ship_at(state, nq, nr))
        .any(|occ| occ.team != team)
}

fn seat_has_actionable(state: &MatchState, seat: &str) -> bool {
    state
        .ships
        .iter()
        .any(|s| s.seat == seat && s.alive && !s.activated)
}

fn first_seat_with_living(state: &MatchState) -> String {
    // Turn order is scenario data (ADR-015); empty order falls back to the
    // full 2x2 composition like the oracle.
    let order: Vec<String> = if state.seat_order.is_empty() {
        SEAT_ORDER.iter().map(|s| s.to_string()).collect()
    } else {
        state.seat_order.clone()
    };
    for seat in &order {
        if state.ships.iter().any(|s| *s.seat == **seat && s.alive) {
            return seat.clone();
        }
    }
    String::new()
}

// --- Snapshot / hash / replay ---------------------------------------------------

/// The state as a serde_json Value (canonical snapshot dictionary, §7 keys).
pub fn state_value(state: &MatchState) -> Value {
    serde_json::to_value(state).expect("MatchState always serializes")
}

pub fn is_terminal(state: &MatchState) -> bool {
    state.phase == Phase::Ended
}

/// Canonical JSON bytes of the state (core-api §9).
pub fn snapshot_bytes(state: &MatchState) -> String {
    to_canonical(&state_value(state))
}

/// Restores a state from canonical JSON; `state_hash(restored)` equals the
/// hash of the original (round-trip fixed by tests).
pub fn restore_snapshot(text: &str) -> Result<MatchState, String> {
    serde_json::from_str(text).map_err(|e| format!("restore_snapshot: invalid snapshot: {e}"))
}

/// FNV-1a 64 over the canonical form; 16 uppercase hex characters.
pub fn state_hash(state: &MatchState) -> String {
    canonical_state_hash(&state_value(state))
}

/// Plays commands from scratch; Ok(final state, all events) or the index and
/// error of the first rejected command.
pub fn replay(
    config: &MatchConfig,
    commands: &[Command],
) -> Result<(MatchState, Vec<Value>), ReplayError> {
    replay_with(config, commands, crate::cards::default_ruleset())
}

pub fn replay_with(
    config: &MatchConfig,
    commands: &[Command],
    ruleset: &Ruleset,
) -> Result<(MatchState, Vec<Value>), ReplayError> {
    let (mut state, mut events) = create_match_with(config, ruleset)
        .map_err(|e| ReplayError { index: 0, error: e, detail: String::new() })?;
    for (i, command) in commands.iter().enumerate() {
        match apply_command_with(&state, command, ruleset) {
            Ok((mut command_events, new_state)) => {
                events.append(&mut command_events);
                state = new_state;
            }
            Err(rejection) => {
                return Err(ReplayError {
                    index: i,
                    error: rejection.code,
                    detail: rejection.detail,
                });
            }
        }
    }
    Ok((state, events))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(seed: i64) -> MatchConfig {
        MatchConfig {
            seed,
            ..MatchConfig::default()
        }
    }

    #[test]
    fn create_match_produces_6_ships_and_draft_events() {
        let ruleset = crate::cards::default_ruleset();
        let (state, events) = create_match(&config(42)).unwrap();
        assert_eq!(state.ships.len(), 6);
        assert_eq!(state.version, 4, "STATE_VERSION pin (ADR-018)");
        // v3.2 duel: seat composition travels in the state (core-api §7).
        assert_eq!(state.seat_order, vec!["A1".to_string(), "B1".to_string()]);
        assert_eq!(
            state.teams,
            Teams {
                a: vec!["A1".to_string()],
                b: vec!["B1".to_string()],
            }
        );
        assert_eq!(state.phase, Phase::Activation);
        assert_eq!(state.active_seat, "A1");
        assert_eq!(state.rng_counter, 0);
        assert!(state.dice.is_empty());
        assert_eq!(state.ruleset_hash, ruleset.ruleset_hash);
        // v3.5 (ADR-018) ruleset hash pin.
        assert_eq!(state.ruleset_hash, "289FEA29F1BB029E");
        // v3.5: every ship starts with a zero spend tally.
        assert!(state.ships.iter().all(|s| s.spent_round == 0));
        // v3.3 (ADR-016): one hero per seat, objects/pending empty, bot pin on.
        assert_eq!(state.heroes.len(), 2);
        assert!(state.heroes.iter().all(|(_, h)| h.uses_left >= 0));
        assert!(state.objects.is_empty());
        assert!(state.pending_reaction.is_none());
        assert!(state.seeded_bots_skip_heroes);
        let types: Vec<&str> = events.iter().map(|e| e["type"].as_str().unwrap()).collect();
        assert_eq!(types[0], "MatchCreated");
        assert_eq!(types.iter().filter(|t| **t == "ShipDrafted").count(), 6);
        assert_eq!(types.iter().filter(|t| **t == "HeroDrafted").count(), 2);
        assert_eq!(types.iter().filter(|t| **t == "ShipPlaced").count(), 6);
        assert_eq!(*types.last().unwrap(), "RoundStarted");
        // Event order: ShipDrafted* then HeroDrafted* (seat order), then
        // ShipPlaced* (oracle create_match).
        let first_hero = types.iter().position(|t| *t == "HeroDrafted").unwrap();
        let last_ship_draft = types.iter().rposition(|t| *t == "ShipDrafted").unwrap();
        assert!(last_ship_draft < first_hero);
        let hero_seats: Vec<&str> = events
            .iter()
            .filter(|e| e["type"] == "HeroDrafted")
            .map(|e| e["seat"].as_str().unwrap())
            .collect();
        assert_eq!(hero_seats, ["A1", "B1"]);
        // Heroes state keeps the seat_order layout.
        let hero_keys: Vec<&str> = state.heroes.iter().map(|(s, _)| s.as_str()).collect();
        assert_eq!(hero_keys, ["A1", "B1"]);
        // Draft order: round-major, seat order A1,B1 inside a round.
        let drafted_seats: Vec<&str> = events
            .iter()
            .filter(|e| e["type"] == "ShipDrafted")
            .map(|e| e["seat"].as_str().unwrap())
            .collect();
        assert_eq!(drafted_seats, ["A1", "B1", "A1", "B1", "A1", "B1"]);
        // ship_instance_id scheme (§7).
        assert!(state.ships.iter().all(|s| s.id.starts_with(&format!("{}_", s.seat))));
        // Duel placement cells and facing (classic_2v2.json, ADR-015).
        let cells: Vec<(i64, i64)> = state.ships.iter().map(|s| (s.q, s.r)).collect();
        assert_eq!(
            cells,
            vec![(0, 3), (0, 2), (1, 2), (0, -3), (0, -2), (-1, -2)]
        );
        assert_eq!(state.ships[0].facing, 0);
        assert_eq!(state.ships[3].facing, 3);
        // Team membership from the scenario, not the seat letter prefix.
        assert!(state.ships.iter().take(3).all(|s| s.team == "A"));
        assert!(state.ships.iter().skip(3).all(|s| s.team == "B"));
    }

    #[test]
    fn hero_draft_matches_oracle_rng_stream() {
        // The hero draft consumes exactly one next_below per seat right after
        // the fleet draft: recreating the stream (fleet + hero draft replay)
        // must reproduce the same assignment for a spread of seeds, and the
        // same hero must never be dealt twice.
        for seed in 0..50i64 {
            let (state, _) = create_match(&config(seed)).unwrap();
            let ids: Vec<&str> = state
                .heroes
                .iter()
                .map(|(_, h)| h.hero_id.as_str())
                .collect();
            assert_eq!(ids.len(), 2, "seed {seed}");
            assert_ne!(ids[0], ids[1], "seed {seed}: distinct heroes");
            for (_, hero) in state.heroes.iter() {
                let uses = crate::cards::default_ruleset()
                    .heroes
                    .get(&hero.hero_id)
                    .map(|d| d.uses_per_match)
                    .unwrap();
                assert_eq!(hero.uses_left, uses, "seed {seed}: uses from the card");
            }
        }
    }

    #[test]
    fn legal_actions_deterministic_order() {
        let (state, _) = create_match(&config(7)).unwrap();
        let legal = legal_actions(&state);
        assert!(!legal.is_empty());
        // BeginActivation by ships array order, then EndActivation is not here
        // while no ship is active.
        assert!(matches!(legal[0], Command::BeginActivation { .. }));
        assert!(matches!(legal.last().unwrap(), Command::BeginActivation { .. }));
        let (_, state2) = apply_command(&state, &legal[0]).unwrap();
        let legal2 = legal_actions(&state2);
        assert!(matches!(legal2[0], Command::Move { .. } | Command::RotateLeft | Command::RotateRight | Command::DeclareAttack { .. }));
        assert!(matches!(legal2.last().unwrap(), Command::EndActivation));
        // ADR-016 §7 bot-parity pin: default mode never offers hero commands.
        assert!(legal2
            .iter()
            .all(|c| !matches!(c, Command::UseHeroAbility { .. } | Command::SkipReaction)));
    }

    #[test]
    fn rejected_command_does_not_mutate_state() {
        let (state, _) = create_match(&config(9)).unwrap();
        let ghost = apply_command(&state, &Command::EndActivation);
        assert!(ghost.is_err(), "no active ship yet");
        let res = apply_command(&state, &Command::BeginActivation {
            ship_instance_id: "nope".into(),
        });
        assert_eq!(res.unwrap_err().code, "unknown_ship");
        assert_eq!(state_hash(&state), state_hash(&state));
    }

    #[test]
    fn snapshot_roundtrip_and_replay_hash() {
        let (state, _) = create_match(&config(11)).unwrap();
        let mut commands = Vec::new();
        let mut current = state;
        for _ in 0..30 {
            let legal = legal_actions(&current);
            let cmd = legal[0].clone();
            let (events, next) = apply_command(&current, &cmd).unwrap();
            assert!(!events.is_empty());
            commands.push(cmd);
            current = next;
        }
        let restored = restore_snapshot(&snapshot_bytes(&current)).unwrap();
        assert_eq!(state_hash(&restored), state_hash(&current));
        let (replayed, _) = replay(&config(11), &commands).unwrap();
        assert_eq!(state_hash(&replayed), state_hash(&current));
        // Invariant rng_counter == dice.len().
        assert_eq!(replayed.rng_counter as usize, replayed.dice.len());
    }

    #[test]
    fn ray_direction_matches_neighbor_and_projection_rules() {
        assert_eq!(ray_direction((0, 0), (0, -1)), 0);
        assert_eq!(ray_direction((0, 0), (1, 0)), 2);
        // Non-neighbor: (0,0) -> (0,4) is exactly south along the hex ray.
        assert_eq!(ray_direction((0, 0), (0, 4)), 3);
        // (0,0) -> (4,-2): offset dominated by NE.
        assert_eq!(ray_direction((0, 0), (4, -2)), 1);
        // Deterministic tie-break to the lowest direction index for ties.
        assert_eq!(ray_direction((0, 0), (1, 2)), 3); // S-ish offset: projection of S wins
    }
}
