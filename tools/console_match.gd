# Console match: plays one full match with RandomLegal bots (per-seat rng)
# and prints a human-readable log: header, draft, per-step actions, combat
# results, final. BOTS+SIM ownership.
#
# Usage:
#   godot --headless --path . --script res://tools/console_match.gd -- \
#       [--seed N] [--round-limit N] [--quiet]
extends SceneTree

const HexMath := preload("res://src/core/hex/hex_math.gd")
const RngScript := preload("res://src/core/rng/rng.gd")
const RandomLegal := preload("res://src/bots/policies/random_legal.gd")
const Playout := preload("res://src/bots/playout.gd")

# Event types that may follow AttackDeclared as part of the same combat block
# (rerolls add extra DieRolled/StrengthCalculated pairs).
const COMBAT_TAIL: Array[String] = ["DieRolled", "StrengthCalculated", "DamageApplied", "ShipDestroyed"]


func _initialize() -> void:
	var opts := _parse_args()
	if opts.is_empty():
		quit(2)
		return
	var seed_value := int(opts["seed"])
	var round_limit := int(opts["round_limit"])
	var quiet := bool(opts["quiet"])
	print("=== Star Wars Battleships — console match (ruleset v3, sprint 1: heroes/abilities off, ADR-011) ===")
	print("seed: %d  round_limit: %d  bots: RandomLegal (per-seat rng seed = match_seed*%d + seat_index)"
			% [seed_value, round_limit, Playout.SEAT_SEED_MULTIPLIER])
	var factory := func(seat: String, seat_index: int, match_seed: int) -> Variant:
		return RandomLegal.new(RngScript.new(Playout.bot_seed(match_seed, seat_index)))
	var res_v: Variant = Playout.play({"seed": seed_value, "round_limit": round_limit}, factory)
	if not (res_v is Dictionary) or not (res_v as Dictionary).has("state") \
			or (res_v as Dictionary)["state"].is_empty():
		printerr("console_match: engine produced no state (is src/core compiled?)")
		quit(1)
		return
	var res: Dictionary = res_v
	if res.has("error"):
		printerr("match failed: %s %s" % [String(res["error"]), String(res.get("detail", ""))])
		quit(1)
		return
	_print_match(res["events"], quiet)
	_print_final(res["state"], res["commands"].size(), res["events"], quiet)
	quit(0)


func _parse_args() -> Dictionary:
	var opts := {"seed": 42, "round_limit": 60, "quiet": false}
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		var a := String(args[i])
		if a == "--seed" or a == "--round-limit":
			if i + 1 >= args.size():
				printerr("Missing value for %s" % a)
				return {}
			i += 1
			opts["seed" if a == "--seed" else "round_limit"] = int(String(args[i]))
		elif a == "--quiet":
			opts["quiet"] = true
		else:
			printerr("Unknown argument: %s" % a)
			return {}
		i += 1
	return opts


func _print_match(events: Array, quiet: bool) -> void:
	var draft_header_done := false
	var draft_info := {} # ship_instance_id -> "seat type (cost N)" from ShipDrafted
	var attack := {}
	for ev: Dictionary in events:
		var t := String(ev.get("type", ""))
		if not attack.is_empty() and not COMBAT_TAIL.has(t):
			if not quiet:
				_print_attack(attack)
			attack = {}
		match t:
			"MatchCreated":
				if not quiet:
					print("ruleset: %s  hash: %s" % [String(ev["ruleset_id"]),
							String(ev["ruleset_hash"]).substr(0, 16)])
			"ShipDrafted":
				draft_info[String(ev["ship_instance_id"])] = "%s  %s  cost %d" % [
						String(ev["seat"]), String(ev["ship_type_id"]), int(ev["cost"])]
			"ShipPlaced":
				if not quiet:
					if not draft_header_done:
						print("\n--- Draft ---")
						draft_header_done = true
					print("  %s  ->  cell (%d,%d)  facing %d  hp %d  shield %d" % [
							draft_info.get(String(ev["ship_instance_id"]), "?"),
							int(ev["q"]), int(ev["r"]), int(ev["facing"]),
							int(ev["hp"]), int(ev["shield"])])
			"RoundStarted":
				if not quiet:
					print("\n=== Round %d ===" % int(ev["round"]))
			"ActivationStarted":
				if not quiet:
					print("  [%s] %s (charges %d)" % [String(ev["seat"]),
							String(ev["ship_instance_id"]), int(ev["charges"])])
			"ShipMoved":
				if not quiet:
					print("    move (%d,%d)->(%d,%d)" % [int(ev["from_q"]), int(ev["from_r"]),
							int(ev["to_q"]), int(ev["to_r"])])
			"ShipRotated":
				if not quiet:
					var steps := (int(ev["to_facing"]) - int(ev["from_facing"]) + 6) % 6
					print("    rotate %s (%d->%d)" % ["L" if steps == 5 else "R",
							int(ev["from_facing"]), int(ev["to_facing"])])
			"AttackDeclared":
				attack = {
					"attacker": String(ev["attacker_id"]),
					"target": String(ev["target_id"]),
					"att_dice": [],
					"def_dice": [],
					"calc": {},
					"damage": null,
					"destroyed_id": "",
				}
			"DieRolled":
				if String(ev.get("role", "")) == "defender":
					attack["def_dice"].append(int(ev["value"]))
				else:
					attack["att_dice"].append(int(ev["value"]))
			"StrengthCalculated":
				# Last calculation per ship wins (a reroll recalculates).
				attack["calc"][String(ev["ship_instance_id"])] = {
					"sector": int(ev["sector_index"]), "total": int(ev["total"])}
			"DamageApplied":
				attack["damage"] = ev
			"ShipDestroyed":
				attack["destroyed_id"] = String(ev["ship_instance_id"])
			_:
				pass # ChargeSpent / ActivationEnded / MatchEnded are not logged individually
	if not attack.is_empty() and not quiet:
		_print_attack(attack)


func _print_attack(a: Dictionary) -> void:
	var att_calc: Dictionary = a["calc"].get(a["attacker"], {})
	var def_calc: Dictionary = a["calc"].get(a["target"], {})
	var line := "    attack %s -> %s | dice %s v %s | sectors %s/%s | str %s v %s" % [
			a["attacker"], a["target"],
			_dice_list(a["att_dice"]), _dice_list(a["def_dice"]),
			_sector_name(att_calc.get("sector", -1)), _sector_name(def_calc.get("sector", -1)),
			str(att_calc.get("total", "?")), str(def_calc.get("total", "?"))]
	var dmg: Variant = a["damage"]
	if dmg != null:
		line += " | %s loses %d (hp %d, sh %d)" % [String(dmg["target_id"]),
				int(dmg["shield_damage"]) + int(dmg["hull_damage"]),
				int(dmg["hp_left"]), int(dmg["shield_left"])]
	else:
		line += " | tie, no damage"
	if not String(a["destroyed_id"]).is_empty():
		line += "  >> DESTROYED %s" % String(a["destroyed_id"])
	print(line)


func _dice_list(values: Array) -> String:
	if values.is_empty():
		return "?"
	var parts: Array[String] = []
	for v: Variant in values:
		parts.append(str(int(v)))
	return "/".join(parts)


func _sector_name(sector_v: Variant) -> String:
	var sector := int(sector_v)
	if sector < 0 or sector >= HexMath.SECTOR_NAMES.size():
		return "?"
	return String(HexMath.SECTOR_NAMES[sector])


func _print_final(state: Dictionary, command_count: int, events: Array, quiet: bool) -> void:
	var reason := ""
	for ev: Dictionary in events:
		if String(ev.get("type", "")) == "MatchEnded":
			reason = String(ev.get("reason", ""))
	print("\n=== Final ===")
	var winner: Variant = state.get("winner")
	if winner == null:
		print("result: DRAW (%s)" % reason)
	else:
		print("result: team %s wins (%s)" % [str(winner), reason])
	print("rounds: %d/%d  commands: %d  rng_calls: %d" % [int(state["round"]),
			int(state["round_limit"]), command_count, int(state["rng_counter"])])
	for team: String in ["A", "B"]:
		var alive: Array[String] = []
		for s: Dictionary in state["ships"]:
			if String(s["team"]) == team and bool(s["alive"]):
				alive.append("%s hp %d sh %d" % [String(s["id"]), int(s["hp"]), int(s["shield"])])
		print("alive %s (%d): %s" % [team, alive.size(),
				" | ".join(alive) if not alive.is_empty() else "-"])
