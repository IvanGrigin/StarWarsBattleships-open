# Batch simulator: N matches RandomLegal vs RandomLegal, aggregated statistics
# written as raw JSON plus a markdown balance report. Statistics are derived
# from the event journal and the final state of each match; states are dropped
# after each match (only aggregates are kept). BOTS+SIM ownership.
#
# Usage:
#   godot --headless --path . --script res://tools/batch_sim.gd -- \
#       [--matches N] [--seed-base N] [--round-limit N] \
#       [--out reports/raw_stats.json] [--report reports/balance_report.md]
extends SceneTree

const CardStore := preload("res://src/core/data/card_store.gd")
const RngScript := preload("res://src/core/rng/rng.gd")
const RandomLegal := preload("res://src/bots/policies/random_legal.gd")
const Playout := preload("res://src/bots/playout.gd")

const SEATS: Array[String] = ["A1", "B1", "A2", "B2"]


func _initialize() -> void:
	var opts := _parse_args()
	if opts.is_empty():
		quit(2)
		return
	var matches := int(opts["matches"])
	var seed_base := int(opts["seed_base"])
	var round_limit := int(opts["round_limit"])
	var out_path := String(opts["out"])
	var report_path := String(opts["report"])

	var game := CardStore.game_rules()
	var fleet_per_match := int(game.get("fleet_size", 3)) * SEATS.size()

	var agg := {
		"wins": {"A": 0, "B": 0},
		"draws": 0,
		"reasons": {},
		"seat_wins": {"A1": 0, "B1": 0, "A2": 0, "B2": 0},
		"rounds_sum": 0,
		"histogram": [],
		"rng_sum": 0,
		"rng_min": -1,
		"rng_max": 0,
		"ships": {},
		"played": 0,
		"errors": 0,
	}
	for i in ceili(float(round_limit) / 10.0):
		agg["histogram"].append(0)

	var factory := func(seat: String, seat_index: int, match_seed: int) -> Variant:
		return RandomLegal.new(RngScript.new(Playout.bot_seed(match_seed, seat_index)))

	var started_usec := Time.get_ticks_usec()
	for i in matches:
		var match_seed := seed_base + i
		var res_v: Variant = Playout.play({"seed": match_seed, "round_limit": round_limit}, factory)
		# A partially-compiled engine makes calls degrade instead of aborting:
		# treat any malformed or unfinished result as a match error, never as data.
		if not (res_v is Dictionary) or not (res_v as Dictionary).has("state") \
				or String((res_v as Dictionary)["state"].get("phase", "")) != "ended":
			agg["errors"] = int(agg["errors"]) + 1
			printerr("batch_sim: seed %d produced no finished state" % match_seed)
			continue
		var res: Dictionary = res_v
		if res.has("error"):
			agg["errors"] = int(agg["errors"]) + 1
			printerr("batch_sim: seed %d failed: %s %s" % [match_seed,
					String(res["error"]), String(res.get("detail", ""))])
			continue
		_accumulate_match(res, agg, round_limit)
	var elapsed_sec := float(Time.get_ticks_usec() - started_usec) / 1000000.0
	var played := int(agg["played"])
	if played == 0:
		printerr("batch_sim: no match completed")
		quit(1)
		return

	var raw := _build_raw_json(agg, matches, seed_base, round_limit, fleet_per_match, elapsed_sec)
	if not _write_text(out_path, JSON.stringify(raw, "  ")):
		quit(1)
		return
	if not _write_text(report_path, _build_report(raw, matches, seed_base, round_limit)):
		quit(1)
		return

	_print_summary(raw, out_path, report_path, elapsed_sec)
	quit(0 if int(agg["errors"]) == 0 else 1)


func _parse_args() -> Dictionary:
	var opts := {
		"matches": 1000,
		"seed_base": 1000,
		"round_limit": 60,
		"out": "reports/raw_stats.json",
		"report": "",
	}
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		var a := String(args[i])
		var wants_value := a in ["--matches", "--seed-base", "--round-limit", "--out", "--report"]
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
			"--report":
				opts["report"] = value
		i += 1
	if String(opts["report"]).is_empty():
		opts["report"] = String(opts["out"]).get_base_dir().path_join("balance_report.md")
	return opts


# --- Per-match aggregation ---------------------------------------------------

func _ship_slot(pool: Dictionary, type_id: String) -> Dictionary:
	if not pool.has(type_id):
		pool[type_id] = {
			"picks": 0, "matches_present": 0, "kills": 0, "deaths": 0,
			"damage_dealt": 0, "damage_taken": 0, "death_round_sum": 0,
			"destroyed": 0, "survived": 0, "cost_sum": 0,
		}
	return pool[type_id]


func _accumulate_match(res: Dictionary, agg: Dictionary, round_limit: int) -> void:
	agg["played"] = int(agg["played"]) + 1
	var state: Dictionary = res["state"]
	var events: Array = res["events"]
	var ships: Dictionary = agg["ships"]
	var present := {}
	var id_type := {}
	var round_num := 1
	var current_attacker := "" # AttackDeclared -> DamageApplied/ShipDestroyed are sequential
	for ev: Dictionary in events:
		match String(ev.get("type", "")):
			"ShipDrafted":
				var type_id := String(ev["ship_type_id"])
				id_type[String(ev["ship_instance_id"])] = type_id
				present[type_id] = true
				var slot := _ship_slot(ships, type_id)
				slot["picks"] = int(slot["picks"]) + 1
				slot["cost_sum"] = int(slot["cost_sum"]) + int(ev["cost"])
			"RoundStarted":
				round_num = int(ev["round"])
			"AttackDeclared":
				current_attacker = String(ev["attacker_id"])
			"DamageApplied":
				var dmg := int(ev["shield_damage"]) + int(ev["hull_damage"])
				if id_type.has(current_attacker):
					var att_slot := _ship_slot(ships, String(id_type[current_attacker]))
					att_slot["damage_dealt"] = int(att_slot["damage_dealt"]) + dmg
				var victim_id := String(ev["target_id"])
				if id_type.has(victim_id):
					var victim_slot := _ship_slot(ships, String(id_type[victim_id]))
					victim_slot["damage_taken"] = int(victim_slot["damage_taken"]) + dmg
			"ShipDestroyed":
				var dead_id := String(ev["ship_instance_id"])
				if id_type.has(dead_id):
					var victim_slot2 := _ship_slot(ships, String(id_type[dead_id]))
					victim_slot2["deaths"] = int(victim_slot2["deaths"]) + 1
					victim_slot2["destroyed"] = int(victim_slot2["destroyed"]) + 1
					victim_slot2["death_round_sum"] = int(victim_slot2["death_round_sum"]) + round_num
				if id_type.has(current_attacker):
					var killer_slot := _ship_slot(ships, String(id_type[current_attacker]))
					killer_slot["kills"] = int(killer_slot["kills"]) + 1
			"MatchEnded":
				var winner: Variant = ev.get("winner")
				if winner == null:
					agg["draws"] = int(agg["draws"]) + 1
				else:
					var team := String(winner)
					agg["wins"][team] = int(agg["wins"][team]) + 1
					for seat: String in SEATS:
						if seat.begins_with(team):
							agg["seat_wins"][seat] = int(agg["seat_wins"][seat]) + 1
				var reason := String(ev.get("reason", ""))
				agg["reasons"][reason] = int(agg["reasons"].get(reason, 0)) + 1
	for type_id2: Variant in present:
		var slot2 := _ship_slot(ships, String(type_id2))
		slot2["matches_present"] = int(slot2["matches_present"]) + 1
	for s: Dictionary in state["ships"]:
		if bool(s["alive"]):
			var slot3 := _ship_slot(ships, String(s["type_id"]))
			slot3["survived"] = int(slot3["survived"]) + 1
	# A round_limit draw ends with round == round_limit + 1: clamp for stats.
	var rounds := mini(int(state["round"]), round_limit)
	agg["rounds_sum"] = int(agg["rounds_sum"]) + rounds
	var bucket: int = clampi((rounds - 1) / 10, 0, agg["histogram"].size() - 1)
	agg["histogram"][bucket] = int(agg["histogram"][bucket]) + 1
	var rng_calls := int(state["rng_counter"])
	agg["rng_sum"] = int(agg["rng_sum"]) + rng_calls
	if int(agg["rng_min"]) < 0 or rng_calls < int(agg["rng_min"]):
		agg["rng_min"] = rng_calls
	if rng_calls > int(agg["rng_max"]):
		agg["rng_max"] = rng_calls


# --- Output builders ---------------------------------------------------------

func _build_raw_json(agg: Dictionary, matches: int, seed_base: int, round_limit: int,
		fleet_per_match: int, elapsed_sec: float) -> Dictionary:
	var played := int(agg["played"])
	var ships_out := {}
	var type_ids: Array = agg["ships"].keys()
	type_ids.sort()
	for type_id: Variant in type_ids:
		var slot: Dictionary = agg["ships"][type_id]
		var destroyed := int(slot["destroyed"])
		ships_out[String(type_id)] = {
			"picks": int(slot["picks"]),
			"pick_rate": float(int(slot["picks"])) / float(played * fleet_per_match),
			"matches_present": int(slot["matches_present"]),
			"kills": int(slot["kills"]),
			"deaths": int(slot["deaths"]),
			"damage_dealt": int(slot["damage_dealt"]),
			"damage_taken": int(slot["damage_taken"]),
			"avg_death_round": null if destroyed == 0
					else float(int(slot["death_round_sum"])) / float(destroyed),
			"survived": int(slot["survived"]),
			"cost_sum": int(slot["cost_sum"]),
		}
	var hist_out := {}
	var buckets: Array = agg["histogram"]
	for k in buckets.size():
		var lo := k * 10 + 1
		var hi := mini((k + 1) * 10, round_limit)
		hist_out["%d-%d" % [lo, hi]] = int(buckets[k])
	return {
		"meta": {
			"ruleset_id": String(CardStore.game_rules().get("ruleset_id", "v3")),
			"ruleset_hash": CardStore.ruleset_hash(),
			"bots": "RandomLegal vs RandomLegal (per-seat Rng, seed = match_seed*%d + seat_index)"
					% Playout.SEAT_SEED_MULTIPLIER,
			"adr": "sprint 1: heroes and special abilities disabled (ADR-011)",
			"matches": matches,
			"played": played,
			"errors": int(agg["errors"]),
			"seed_base": seed_base,
			"round_limit": round_limit,
			"generated": "%s %s" % [Time.get_date_string_from_system(),
					Time.get_time_string_from_system()],
			"elapsed_sec": snappedf(elapsed_sec, 0.001),
		},
		"outcomes": {
			"wins_a": int(agg["wins"]["A"]),
			"wins_b": int(agg["wins"]["B"]),
			"draws": int(agg["draws"]),
			"reasons": agg["reasons"],
			"rounds_sum": int(agg["rounds_sum"]),
			"rounds_avg": float(int(agg["rounds_sum"])) / float(played),
			"length_histogram": hist_out,
		},
		"seats": {
			"wins": agg["seat_wins"],
			"games_per_seat": played,
		},
		"rng_calls_per_match": {
			"sum": int(agg["rng_sum"]),
			"avg": float(int(agg["rng_sum"])) / float(played),
			"min": int(agg["rng_min"]),
			"max": int(agg["rng_max"]),
		},
		"ships": ships_out,
	}


func _build_report(raw: Dictionary, matches: int, seed_base: int, round_limit: int) -> String:
	var played := int(raw["meta"]["played"])
	var wins_a := int(raw["outcomes"]["wins_a"])
	var wins_b := int(raw["outcomes"]["wins_b"])
	var draws := int(raw["outcomes"]["draws"])
	var lines: Array[String] = []
	lines.append("# Balance report — ruleset v3, sprint 1")
	lines.append("")
	lines.append("- Generated: %s" % String(raw["meta"]["generated"]))
	lines.append("- Matches: %d requested, %d played, match seeds %d..%d"
			% [matches, played, seed_base, seed_base + matches - 1])
	lines.append("- Round limit: %d" % round_limit)
	lines.append("- Bots: %s" % String(raw["meta"]["bots"]))
	lines.append("- Scope: %s" % String(raw["meta"]["adr"]))
	lines.append("- ruleset_hash: %s" % String(raw["meta"]["ruleset_hash"]))
	lines.append("")
	lines.append("## Outcomes")
	lines.append("")
	lines.append("| Outcome | Count | Share |")
	lines.append("|---|---:|---:|")
	lines.append("| Team A win | %d | %.1f%% |" % [wins_a, _pct(wins_a, played)])
	lines.append("| Team B win | %d | %.1f%% |" % [wins_b, _pct(wins_b, played)])
	lines.append("| Draw | %d | %.1f%% |" % [draws, _pct(draws, played)])
	for reason: String in ["elimination", "both_eliminated", "round_limit"]:
		var count := int(raw["outcomes"]["reasons"].get(reason, 0))
		lines.append("| — ended by %s | %d | %.1f%% |" % [reason, count, _pct(count, played)])
	lines.append("| Average rounds | %.1f | |" % float(raw["outcomes"]["rounds_avg"]))
	lines.append("")
	lines.append("## Ships")
	lines.append("")
	lines.append("| Type | Picks | Kills | Deaths | Damage dealt | Damage taken | Dmg/death | Avg death round | Survived |")
	lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
	var type_ids: Array = raw["ships"].keys()
	type_ids.sort()
	for type_id: Variant in type_ids:
		var s: Dictionary = raw["ships"][type_id]
		var deaths := int(s["deaths"])
		var dmg_per_death := float(int(s["damage_dealt"])) / float(deaths) if deaths > 0 else -1.0
		var avg_death: Variant = s["avg_death_round"]
		lines.append("| %s | %d | %d | %d | %d | %d | %s | %s | %d |" % [
				String(type_id), int(s["picks"]), int(s["kills"]), deaths,
				int(s["damage_dealt"]), int(s["damage_taken"]),
				"-" if deaths == 0 else "%.1f" % dmg_per_death,
				"-" if avg_death == null else "%.1f" % float(avg_death),
				int(s["survived"])])
	lines.append("")
	lines.append("## Seats (team A = A1+A2, team B = B1+B2)")
	lines.append("")
	lines.append("| Seat | Wins | Winrate |")
	lines.append("|---|---:|---:|")
	for seat: String in SEATS:
		var w := int(raw["seats"]["wins"][seat])
		lines.append("| %s | %d | %.1f%% |" % [seat, w, _pct(w, played)])
	lines.append("")
	lines.append("## Observations")
	lines.append("")
	for obs: String in _observations(raw):
		lines.append("- %s" % obs)
	lines.append("")
	return "\n".join(lines)


func _observations(raw: Dictionary) -> Array[String]:
	var played := int(raw["meta"]["played"])
	var out: Array[String] = []
	var best_surv := ""
	var best_surv_rate := -1.0
	var worst_surv := ""
	var worst_surv_rate := 2.0
	var best_dps_death := ""
	var best_dps_death_val := -1.0
	var most_picked := ""
	var most_picked_val := -1
	var total_dmg := 0
	for type_id: Variant in raw["ships"].keys():
		var s: Dictionary = raw["ships"][type_id]
		var picks := int(s["picks"])
		if picks == 0:
			continue
		total_dmg += int(s["damage_dealt"])
		if picks > most_picked_val:
			most_picked = String(type_id)
			most_picked_val = picks
		var surv_rate := float(int(s["survived"])) / float(picks)
		if surv_rate > best_surv_rate:
			best_surv = String(type_id)
			best_surv_rate = surv_rate
		if surv_rate < worst_surv_rate:
			worst_surv = String(type_id)
			worst_surv_rate = surv_rate
		var deaths := int(s["deaths"])
		if deaths > 0:
			var ratio := float(int(s["damage_dealt"])) / float(deaths)
			if ratio > best_dps_death_val:
				best_dps_death = String(type_id)
				best_dps_death_val = ratio
	out.append("Draft: most picked type is '%s' (%d picks of %d slots, pick_rate %.1f%%)."
			% [most_picked, most_picked_val, played * 12, _pct(most_picked_val, played * 12)])
	out.append("Survivability: '%s' survives most often (%.1f%% of its picks alive at the end); '%s' survives least (%.1f%%)."
			% [best_surv, best_surv_rate * 100.0, worst_surv, worst_surv_rate * 100.0])
	out.append("Damage efficiency: '%s' deals the most damage per death (%.1f). Total damage dealt by all types: %d."
			% [best_dps_death, best_dps_death_val, total_dmg])
	var wins_a := int(raw["outcomes"]["wins_a"])
	var wins_b := int(raw["outcomes"]["wins_b"])
	var skew_pp := _pct(wins_a, played) - _pct(wins_b, played)
	# 2 sigma of the winrate of a fair coin over `played` matches, in percentage points.
	var noise_pp := 200.0 / sqrt(float(played))
	if absf(skew_pp) > noise_pp:
		out.append("SYMMETRY SIGNAL: team A wins %.1f pp more often than team B (2 sigma = %.1f pp) — check placement symmetry."
				% [skew_pp, noise_pp])
	else:
		out.append("Team A vs team B win skew is %.1f pp — within 2 sigma (%.1f pp) of a fair coin, placement looks symmetric."
				% [skew_pp, noise_pp])
	out.append("Draws: %d (%.1f%%), of which round_limit %d and both_eliminated %d."
			% [int(raw["outcomes"]["draws"]), _pct(int(raw["outcomes"]["draws"]), played),
			int(raw["outcomes"]["reasons"].get("round_limit", 0)),
			int(raw["outcomes"]["reasons"].get("both_eliminated", 0))])
	return out


# --- Small helpers -----------------------------------------------------------

func _pct(part: int, whole: int) -> float:
	if whole == 0:
		return 0.0
	return 100.0 * float(part) / float(whole)


func _write_text(path: String, text: String) -> bool:
	var dir := String(path).get_base_dir()
	if not dir.is_empty():
		var err := DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(dir))
		if err != OK:
			printerr("batch_sim: cannot create directory %s (code %d)" % [dir, err])
			return false
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		printerr("batch_sim: cannot write %s" % path)
		return false
	f.store_string(text)
	f.close()
	return true


func _print_summary(raw: Dictionary, out_path: String, report_path: String,
		elapsed_sec: float) -> void:
	var played := int(raw["meta"]["played"])
	var wins_a := int(raw["outcomes"]["wins_a"])
	var wins_b := int(raw["outcomes"]["wins_b"])
	var draws := int(raw["outcomes"]["draws"])
	print("--- batch_sim summary ---")
	print("matches: %d  errors: %d  elapsed: %.2fs  rate: %.1f matches/sec"
			% [played, int(raw["meta"]["errors"]), elapsed_sec, float(played) / maxf(elapsed_sec, 0.000001)])
	print("A wins %d (%.1f%%)  B wins %d (%.1f%%)  draws %d (%.1f%%)  avg rounds %.1f"
			% [wins_a, _pct(wins_a, played), wins_b, _pct(wins_b, played),
			draws, _pct(draws, played), float(raw["outcomes"]["rounds_avg"])])
	var ranked: Array = raw["ships"].keys()
	ranked.sort_custom(func(a: Variant, b: Variant) -> bool:
		return int(raw["ships"][a]["damage_dealt"]) > int(raw["ships"][b]["damage_dealt"]))
	var top: Array[String] = []
	for i in mini(3, ranked.size()):
		top.append("%s (%d)" % [String(ranked[i]), int(raw["ships"][ranked[i]]["damage_dealt"])])
	print("top 3 by damage dealt: %s" % ", ".join(top))
	print("out: %s" % out_path)
	print("report: %s" % report_path)
