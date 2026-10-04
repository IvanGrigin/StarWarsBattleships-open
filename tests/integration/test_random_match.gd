# Integration: full matches driven by a local RandomLegal bot for 20 seeds —
# termination, invariants, replay determinism, snapshot round-trips and the
# tests/golden/replay_seed_42.jsonl golden-replay contract.
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const RngScript := preload("res://src/core/rng/rng.gd")
const CardStore := preload("res://src/core/data/card_store.gd")
const Canonical := preload("res://src/core/serialization/canonical.gd")

const GOLDEN_PATH := "res://tests/golden/replay_seed_42.jsonl"
const GOLDEN_SEED := 42
const MATCH_SEEDS: Array[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 42, 777, 2024, 555, 64, 12345, 31, 47, 8, 99]


## Minimal local random-legal policy (deliberately not from src/bots):
## picks legal[rng.next_below(size)] with its own injected Rng.
class RandomLegal:
	var rng
	func _init(rng_instance) -> void:
		rng = rng_instance
	func choose_action(legal: Array) -> Variant:
		if legal.is_empty():
			return null
		return legal[rng.next_below(legal.size())]


func _by_id(state: Dictionary, instance_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("id", "")) == instance_id:
			return s
	return {}


func _check_final_invariants(state: Dictionary, journal: Array, seed_value: int) -> void:
	assert_eq(String(state["phase"]), "ended", "seed %d: match ended" % seed_value)
	assert_true(state["winner"] == null or String(state["winner"]) == "A"
			or String(state["winner"]) == "B", "seed %d: winner is A/B/null" % seed_value)
	var reason := ""
	for i in range(journal.size() - 1, -1, -1):
		if String(journal[i]["type"]) == "MatchEnded":
			reason = String(journal[i]["reason"])
			break
	assert_true(reason == "elimination" or reason == "both_eliminated"
			or reason == "round_limit", "seed %d: valid MatchEnded reason (%s)" % [seed_value, reason])
	var occupied := {}
	var cards := CardStore.ships()
	var radius := int(CardStore.board().get("radius", 4)) # data-driven (ADR-015)
	for s: Dictionary in state["ships"]:
		var ship_id := String(s["id"])
		var q := int(s["q"])
		var r := int(s["r"])
		if bool(s["alive"]):
			var s_coord := -q - r
			assert_true(maxi(maxi(absi(q), absi(r)), absi(s_coord)) <= radius,
					"seed %d: %s inside the radius-%d board" % [seed_value, ship_id, radius])
			var cell_key := "%d,%d" % [q, r]
			assert_true(not occupied.has(cell_key),
					"seed %d: no two live ships share a cell (%s)" % [seed_value, cell_key])
			occupied[cell_key] = ship_id
			assert_between(int(s["hp"]), 1, int(cards[String(s["type_id"])]["max_hp"]),
					"seed %d: %s alive hp range" % [seed_value, ship_id])
		else:
			assert_eq(int(s["hp"]), 0, "seed %d: %s destroyed hp capped at 0" % [seed_value, ship_id])
		assert_between(int(s["charges"]), 0, 5, "seed %d: %s charges range" % [seed_value, ship_id])
		assert_between(int(s["shield"]), 0, 2, "seed %d: %s shield range" % [seed_value, ship_id])


func run() -> int:
	var total_commands := 0
	var total_rounds := 0
	var golden_commands: Array = []
	var golden_hash := ""
	var golden_events := ""
	var started_usec := Time.get_ticks_usec()
	var play_usec := 0
	var match_count := MATCH_SEEDS.size()

	section("random legal matches for %d seeds" % match_count)
	for seed_value: int in MATCH_SEEDS:
		var config := {"seed": seed_value, "round_limit": 60}
		var created := MatchEngine.create_match(config)
		assert_true(not created.has("error"), "seed %d: match created" % seed_value)
		var state: Dictionary = created["state"]
		var journal: Array = created["events"]
		var bot := RandomLegal.new(RngScript.new(seed_value * 7919 + 13))
		var commands: Array = []
		var pending_restore := {}
		var guard := 0
		var seed_started_usec := Time.get_ticks_usec()
		while not MatchEngine.is_terminal(state):
			var legal := MatchEngine.legal_actions(state)
			assert_true(legal.size() > 0, "seed %d: legal actions never empty" % seed_value)
			var cmd: Variant = bot.choose_action(legal)
			assert_true(cmd is Dictionary, "seed %d: bot returned a command" % seed_value)
			var res := MatchEngine.apply_command(state, cmd)
			assert_true(bool(res.get("ok", false)),
					"seed %d: bot command legal (%s)" % [seed_value, String(cmd.get("type", ""))])
			if not bool(res.get("ok", false)):
				break
			# Mid-match snapshot fidelity: the restored copy must accept the
			# same command and produce the identical resulting hash.
			if not pending_restore.is_empty():
				var rres := MatchEngine.apply_command(pending_restore, cmd)
				assert_true(bool(rres.get("ok", false)),
						"seed %d: restored state accepts the same command" % seed_value)
				assert_eq(MatchEngine.state_hash(rres["state"]), MatchEngine.state_hash(res["state"]),
						"seed %d: restored state diverges" % seed_value)
				pending_restore = {}
			state = res["state"]
			journal.append_array(res["events"])
			commands.append(cmd)
			if commands.size() == 10:
				var restored := MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(state))
				assert_eq(MatchEngine.state_hash(restored), MatchEngine.state_hash(state),
						"seed %d: mid-match restore hash matches" % seed_value)
				pending_restore = restored
			guard += 1
			if guard > 200000:
				assert_true(false, "seed %d: match did not terminate" % seed_value)
				break
		total_commands += commands.size()
		total_rounds += int(state["round"])
		play_usec += Time.get_ticks_usec() - seed_started_usec
		_check_final_invariants(state, journal, seed_value)

		# Replay of the full command list reproduces the final hash.
		var replayed := MatchEngine.replay(config, commands)
		assert_true(not replayed.has("replay_error"), "seed %d: replay accepted all commands" % seed_value)
		assert_eq(MatchEngine.state_hash(replayed["state"]), MatchEngine.state_hash(state),
				"seed %d: replay hash matches" % seed_value)
		if seed_value == GOLDEN_SEED:
			golden_commands = commands.duplicate()
			golden_hash = MatchEngine.state_hash(state)
			golden_events = Canonical.to_canonical(replayed["events"])

	var elapsed_sec := float(Time.get_ticks_usec() - started_usec) / 1000000.0
	var play_sec := float(play_usec) / 1000000.0
	print("STATS matches=%d avg_commands=%.1f avg_rounds=%.1f total_time=%.2fs play_time=%.2fs play_matches_per_sec=%.1f"
			% [match_count, float(total_commands) / float(match_count),
			float(total_rounds) / float(match_count), elapsed_sec, play_sec,
			float(match_count) / maxf(play_sec, 0.000001)])

	section("golden replay contract (seed 42)")
	assert_eq(golden_commands.size() > 0, true, "seed 42 run captured")
	if FileAccess.file_exists(GOLDEN_PATH):
		var text := FileAccess.get_file_as_string(GOLDEN_PATH)
		assert_true(not text.is_empty(), "golden file readable")
		var lines := text.split("\n", false)
		assert_true(lines.size() >= 2, "golden file has config and commands")
		var config_line: Variant = JSON.parse_string(String(lines[0]))
		assert_true(config_line is Dictionary, "golden config line parses")
		var replay_config := {
			"seed": int(config_line["seed"]),
			"round_limit": int(config_line["round_limit"]),
		}
		assert_eq(int(replay_config["seed"]), GOLDEN_SEED, "golden config seed")
		var golden_cmds: Array = []
		for i in range(1, lines.size()):
			var parsed_cmd: Variant = JSON.parse_string(String(lines[i]))
			assert_true(parsed_cmd is Dictionary, "golden command line %d parses" % i)
			golden_cmds.append(parsed_cmd)
		assert_eq(golden_cmds.size(), golden_commands.size(), "golden command count unchanged")
		var rep := MatchEngine.replay(replay_config, golden_cmds)
		assert_true(not rep.has("replay_error"), "golden replay accepted every command")
		assert_eq(MatchEngine.state_hash(rep["state"]), golden_hash,
				"golden replay reproduces the recorded final hash")
	else:
		var f := FileAccess.open(GOLDEN_PATH, FileAccess.WRITE)
		assert_true(f != null, "golden file opened for writing")
		if f != null:
			f.store_line(JSON.stringify({"seed": GOLDEN_SEED, "round_limit": 60}))
			for cmd: Dictionary in golden_commands:
				f.store_line(JSON.stringify(cmd))
			f.close()
			print("STATS golden file written: %s (%d commands)" % [GOLDEN_PATH, golden_commands.size()])

	section("golden journal is deterministic")
	var rep2 := MatchEngine.replay({"seed": GOLDEN_SEED, "round_limit": 60}, golden_commands)
	assert_eq(Canonical.to_canonical(rep2["events"]), golden_events,
			"replayed event journal byte-identical")

	return finish()
