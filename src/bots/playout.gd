# Shared full-match driver for bots: create_match -> legal_actions -> bot ->
# apply_command until termination. Lives in src/bots so the console, the batch
# simulator and the tests share one code path (BOTS+SIM ownership).
extends RefCounted

const MatchEngine := preload("res://src/core/rules/match_engine.gd")

## Per-seat bot seed derivation shared by console_match, batch_sim and tests:
## seed_bot = match_seed * SEAT_SEED_MULTIPLIER + seat_index (A1=0, B1=1, A2=2, B2=3).
const SEAT_SEED_MULTIPLIER := 1000003


static func bot_seed(match_seed: int, seat_index: int) -> int:
	return match_seed * SEAT_SEED_MULTIPLIER + seat_index


## Plays one match to termination. bot_factory: Callable(seat: String,
## seat_index: int, match_seed: int) -> bot exposing choose_action(state, legal)
## (BotPolicy, core-api §10). config: {seed, round_limit, step_limit = 100000}.
## Returns {"state", "events", "commands"}; on failure also "error" (+ "detail").
static func play(config: Dictionary, bot_factory: Callable) -> Dictionary:
	var match_seed := int(config.get("seed", 0))
	var created_v: Variant = MatchEngine.create_match(config)
	if not (created_v is Dictionary):
		# Engine call aborted (e.g. src/core failed to compile) -> null.
		return {"state": {}, "events": [], "commands": [], "error": "engine_unavailable"}
	var created: Dictionary = created_v
	var events: Array = created.get("events", [])
	var result := {"state": {}, "events": events, "commands": []}
	if created.has("error"):
		result["error"] = String(created["error"])
		return result
	var state: Dictionary = created["state"]
	var commands: Array = []
	var bots := {}
	var step_limit := int(config.get("step_limit", 100000))
	var steps := 0
	while not MatchEngine.is_terminal(state):
		var seat := String(state["active_seat"])
		if not bots.has(seat):
			bots[seat] = bot_factory.call(seat, MatchEngine.SEAT_ORDER.find(seat), match_seed)
		var legal := MatchEngine.legal_actions(state)
		if legal.is_empty():
			result["error"] = "no_legal_actions"
			break
		var cmd_v: Variant = bots[seat].choose_action(state, legal)
		if not (cmd_v is Dictionary) or (cmd_v as Dictionary).is_empty():
			result["error"] = "bot_returned_no_command"
			break
		var res := MatchEngine.apply_command(state, cmd_v)
		if not bool(res.get("ok", false)):
			result["error"] = "rejected_command"
			result["detail"] = "%s: %s" % [String(res.get("error", "")), String(res.get("detail", ""))]
			break
		state = res["state"]
		events.append_array(res["events"])
		commands.append(cmd_v)
		steps += 1
		if steps > step_limit:
			result["error"] = "step_limit_exceeded"
			break
	result["state"] = state
	result["commands"] = commands
	return result
