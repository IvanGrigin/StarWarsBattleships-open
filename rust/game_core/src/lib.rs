//! game_core — the single source of rules for Star Wars Battleships
//! (MASTER_PLAN §5.1). Semantics are 1:1 with the GDScript prototype oracle
//! (`src/core/**`); normative contracts: `docs/contracts/core-api.md`,
//! `docs/contracts/rust-core-api.md`, ADR-012, ADR-013.
//!
//! Modules:
//! - [`hex`] — pointy-top axial grid math;
//! - [`rng`] — mulberry32 (oracle mode) and ChaCha20 (production), die sampler;
//! - [`serialization`] — canonical JSON + FNV-1a 64 state hash;
//! - [`cards`] — ruleset v3 loading, ruleset_hash identical to CardStore;
//! - [`engine`] — create_match / legal_actions / apply_command / replay.

pub mod cards;
pub mod engine;
pub mod hex;
pub mod rng;
pub mod serialization;

pub use cards::Ruleset;
pub use engine::{
    apply_command, apply_command_with, create_match, create_match_with, is_terminal,
    legal_actions, legal_actions_with, replay, replay_with, restore_snapshot, snapshot_bytes,
    state_hash, state_value, Command, GameObject, HeroState, Heroes, MatchConfig, MatchState,
    PendingReaction, Phase, Rejection, ReplayError, ShipState, Teams, BOMB_MAX_SHIFTS,
    SEAT_ORDER, STATE_VERSION,
};
pub use rng::{DieRng, Mulberry32Compat, RngMode};
