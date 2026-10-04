# Exports the differential test corpus for the Rust core (RUST-CORE task):
# N full RandomLegal-vs-RandomLegal matches; one JSON line per match:
#   {"seed":..., "round_limit":60, "commands":[...], "final_hash":"...",
#    "saw_special": true|false}
# final_hash is MatchEngine.state_hash of the finished state; saw_special is
# true when the event journal contains ShipTransformed or ShipRevived
# (ADR-012). The Rust crate `game_core` must reproduce every final_hash from
# seed + commands alone (bit-compatible oracle contract).
#
# Usage:
#   godot --headless --path . --script res://tools/export_diff_corpus.gd -- \
#       [--matches N] [--seed-base S] [--out PATH]
extends SceneTree

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const RngScript := preload("res://src/core/rng/rng.gd")
const RandomLegal := preload("res://src/bots/policies/random_legal.gd")
const Playout := preload("res://src/bots/playout.gd")

const SPECIAL_EVENTS: Array[String] = ["ShipTransformed", "ShipRevived"]


func _initialize() -> void:
	var opts := _parse_args()
	if opts.is_empty():
		quit(2)
		return
	var matches := int(opts["matches"])
	var seed_base := int(opts["seed_base"])
	var round_limit := int(opts["round_limit"])
	var out_path := String(opts["out"])

	var dir := String(out_path).get_base_dir()
	if not dir.is_empty():
		var err := DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(dir))
		if err != OK:
			printerr("export_diff_corpus: cannot create directory %s (code %d)" % [dir, err])
			quit(1)
			return
	var f := FileAccess.open(out_path, FileAccess.WRITE)
	if f == null:
		printerr("export_diff_corpus: cannot write %s" % out_path)
		quit(1)
		return

	var factory := func(seat: String, seat_index: int, match_seed: int) -> Variant:
		return RandomLegal.new(RngScript.new(Playout.bot_seed(match_seed, seat_index)))

	var specials := 0
	var eliminations := 0
	var draws := 0
	var started_usec := Time.get_ticks_usec()
	for i in matches:
		var match_seed := seed_base + i
		var res_v: Variant = Playout.play({"seed": match_seed, "round_limit": round_limit}, factory)
		# The corpus is only valid when every match finished cleanly.
		if not (res_v is Dictionary) or not (res_v as Dictionary).has("state"):
			printerr("export_diff_corpus: seed %d produced no state" % match_seed)
			f.close()
			quit(1)
			return
		var res: Dictionary = res_v
		var state: Dictionary = res["state"]
		if res.has("error") or String(state.get("phase", "")) != "ended":
			var detail := String(res.get("error", "unfinished"))
			if res.has("detail"):
				detail += ": " + String(res["detail"])
			printerr("export_diff_corpus: seed %d did not finish (%s)" % [match_seed, detail])
			f.close()
			quit(1)
			return
		var saw_special := false
		var reason := ""
		for ev: Dictionary in res["events"]:
			var t := String(ev.get("type", ""))
			if SPECIAL_EVENTS.has(t):
				saw_special = true
			elif t == "MatchEnded":
				reason = String(ev.get("reason", ""))
		if saw_special:
			specials += 1
		if reason == "elimination":
			eliminations += 1
		elif reason != "":
			draws += 1
		var line := {
			"seed": match_seed,
			"round_limit": round_limit,
			"commands": res["commands"],
			"final_hash": MatchEngine.state_hash(state),
			"saw_special": saw_special,
		}
		f.store_line(JSON.stringify(line))
	f.close()
	var elapsed_sec := float(Time.get_ticks_usec() - started_usec) / 1000000.0
	print("--- export_diff_corpus ---")
	print("wrote %d matches to %s" % [matches, out_path])
	print("specials in %d matches, elimination wins in %d, draws %d, %.2fs (%.1f matches/sec)"
			% [specials, eliminations, draws, elapsed_sec,
			float(matches) / maxf(elapsed_sec, 0.000001)])
	quit(0)


func _parse_args() -> Dictionary:
	var opts := {
		"matches": 100,
		"seed_base": 5000,
		"round_limit": 60,
		"out": "tests/golden/diff_corpus_100.jsonl",
	}
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		var a := String(args[i])
		var wants_value := a in ["--matches", "--seed-base", "--round-limit", "--out"]
		if not wants_value:
			printerr("Unknown argument: %s" % a)
			return {}
		if i + 1 >= args.size():
			printerr("Missing value for %s" % a)
			return {}
		i += 1
		var value := String(args[i])
		match a:
			"--matches":
				opts["matches"] = int(value)
			"--seed-base":
				opts["seed_base"] = int(value)
			"--round-limit":
				opts["round_limit"] = int(value)
			"--out":
				opts["out"] = value
		i += 1
	return opts
