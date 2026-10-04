use game_core::{apply_command, create_match, is_terminal, legal_actions, Command, MatchConfig};
mod core_bot { include!("tests/common/mod.rs"); }
fn main() {
    for seed in [0i64] {
        let config = MatchConfig { seed, ..MatchConfig::default() };
        let (mut state, mut events) = create_match(&config).unwrap();
        let mut bots = std::collections::HashMap::new();
        while !is_terminal(&state) {
            let seat = state.active_seat.clone();
            let rng = bots.entry(seat.clone()).or_insert_with(|| core_bot::RandomLegalBot { rng: game_core::Mulberry32Compat::new(core_bot::bot_seed(seed, game_core::SEAT_ORDER.iter().position(|s| *s == seat).unwrap() as i64)) });
            let legal = legal_actions(&state);
            let cmd = rng.choose(&legal).unwrap();
            let (ev, ns) = apply_command(&state, &cmd).unwrap();
            events.extend(ev);
            state = ns;
        }
        for (i, e) in events.iter().enumerate() {
            let t = e["type"].as_str().unwrap_or("?");
            if matches!(t, "AttackDeclared"|"DieRolled"|"StrengthCalculated"|"DamageApplied") {
                println!("{i}: {e}");
            }
        }
    }
}
