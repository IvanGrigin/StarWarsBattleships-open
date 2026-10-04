//! Shared test helpers: a faithful port of the GDScript RandomLegal bot and
//! the Playout driver (src/bots/playout.gd + src/bots/policies/random_legal.gd)
//! so Rust tests can play full matches with the same bot seeds.

use game_core::{
    apply_command, create_match, is_terminal, legal_actions, Command, DieRng, MatchConfig,
    MatchState, Mulberry32Compat, SEAT_ORDER,
};
use serde_json::Value;
use std::collections::HashMap;

/// Playout.SEAT_SEED_MULTIPLIER (playout.gd): bot seed = match_seed * 1000003
/// + seat_index.
pub const SEAT_SEED_MULTIPLIER: i64 = 1000003;

pub fn bot_seed(match_seed: i64, seat_index: i64) -> u64 {
    (match_seed * SEAT_SEED_MULTIPLIER + seat_index) as u64
}

/// random_legal.gd: uniform pick among legal actions with the injected Rng.
pub struct RandomLegalBot {
    rng: Mulberry32Compat,
}

impl RandomLegalBot {
    pub fn choose(&mut self, legal: &[Command]) -> Option<Command> {
        if legal.is_empty() {
            return None;
        }
        Some(legal[self.rng.next_below(legal.len() as u32) as usize].clone())
    }
}

/// Plays one full match exactly like Playout.play: per-seat bots created on
/// first encounter of the seat, commands applied until termination.
pub fn play_random_match(match_seed: i64) -> (MatchState, Vec<Value>, Vec<Command>) {
    let config = MatchConfig {
        seed: match_seed,
        ..MatchConfig::default()
    };
    let (mut state, mut events) = create_match(&config).expect("create_match");
    let mut bots: HashMap<String, RandomLegalBot> = HashMap::new();
    let mut commands = Vec::new();
    while !is_terminal(&state) {
        let seat = state.active_seat.clone();
        let rng = bots.entry(seat.clone()).or_insert_with(|| {
            let seat_index = SEAT_ORDER
                .iter()
                .position(|s| *s == seat)
                .expect("active seat is one of A1/B1/A2/B2") as i64;
            RandomLegalBot {
                rng: Mulberry32Compat::new(bot_seed(match_seed, seat_index)),
            }
        });
        let legal = legal_actions(&state);
        let Some(command) = rng.choose(&legal) else {
            panic!("no legal actions in an unfinished match");
        };
        let (command_events, new_state) =
            apply_command(&state, &command).expect("bot command is legal");
        events.extend(command_events);
        state = new_state;
        commands.push(command);
    }
    (state, events, commands)
}
