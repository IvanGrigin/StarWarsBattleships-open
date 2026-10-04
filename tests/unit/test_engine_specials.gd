# Engine tests: special ship rules C007-C011 (MASTER_PLAN_RU.md §4.8, ADR-012,
# dice order per ADR-014 v3.1) — ghost->phantom transform, Death Star ranged
# shot, X-wing lucky shot, TIE resurrection, vulture reroll; dice order, RNG
# determinism, snapshot fidelity.
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const CardStore := preload("res://src/core/data/card_store.gd")
const Canonical := preload("res://src/core/serialization/canonical.gd")

# Parking cells for ships excluded from a scenario (all inside the v3.2
# radius-3 board, ADR-015; none adjacent to the (0,0)/(0,-1) duel cells).
const PARKS: Array = [[2, -2], [-2, 2], [2, 0], [-2, 0]]


func _seat_ships(state: Dictionary, seat: String) -> Array:
	var out: Array = []
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) == seat:
			out.append(s)
	return out


func _by_id(state: Dictionary, instance_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("id", "")) == instance_id:
			return s
	return {}


func _find_type(state: Dictionary, type_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("type_id", "")) == type_id:
			return s
	return {}


## First ship of `seat` with `type_id`, or {}.
func _seat_type(state: Dictionary, seat: String, type_id: String) -> Dictionary:
	for s: Dictionary in _seat_ships(state, seat):
		if String(s.get("type_id", "")) == type_id:
			return s
	return {}


## Creates a match whose A1 seat contains every type of a_types and whose B1
## seat contains every type of b_types. Scans seeds deterministically.
func _create_match(a_types: Array, b_types: Array) -> Dictionary:
	for seed_value in range(1, 400):
		var c := MatchEngine.create_match({"seed": seed_value})
		if c.has("error"):
			continue
		var st: Dictionary = c["state"]
		var ok := true
		for t: Variant in a_types:
			if _seat_type(st, "A1", String(t)).is_empty():
				ok = false
		for t: Variant in b_types:
			if _seat_type(st, "B1", String(t)).is_empty():
				ok = false
		if ok:
			return c
	return {}


## Moves every ship except the keepers to parking cells so the participants
## control the exact board picture (test-owned tuning, data stays untouched).
func _isolate(state: Dictionary, keep: Array) -> void:
	var park_index := 0
	for s: Dictionary in state.get("ships", []):
		if keep.has(String(s["id"])):
			continue
		var park: Array = PARKS[park_index % PARKS.size()]
		s["q"] = int(park[0])
		s["r"] = int(park[1])
		park_index += 1


## Cycles begin+end over any idle ships until RoundStarted clears the activated
## flag of `ship_id` (i.e. a fresh round has begun). Never rolls dice.
func _cycle_until_fresh(state: Dictionary, ship_id: String) -> Dictionary:
	var st := state
	var guard := 0
	while bool(_by_id(st, ship_id).get("activated", true)):
		if st["active_ship"] == null:
			var idle_id := ""
			for s: Dictionary in st["ships"]:
				if String(s["seat"]) == String(st["active_seat"]) and bool(s["alive"]) \
						and not bool(s["activated"]):
					idle_id = String(s["id"])
					break
			if idle_id.is_empty():
				assert_true(false, "cycle_until_fresh: no idle ship to pass the turn")
				break
			var res := MatchEngine.apply_command(st,
					{"type": "BeginActivation", "ship_instance_id": idle_id})
			assert_true(bool(res.get("ok", false)), "cycle_until_fresh begin %s" % idle_id)
			st = res["state"]
		else:
			var res2 := MatchEngine.apply_command(st, {"type": "EndActivation"})
			assert_true(bool(res2.get("ok", false)), "cycle_until_fresh end")
			st = res2["state"]
		guard += 1
		if guard > 200:
			assert_true(false, "cycle_until_fresh did not converge")
			break
	return st


## Begins the attacker's activation and declares the attack; returns the
## DeclareAttack result with events merged: ActivationStarted + combat events.
func _begin_and_attack(state: Dictionary, attacker_id: String,
		target_id: String) -> Dictionary:
	var begin := MatchEngine.apply_command(state,
			{"type": "BeginActivation", "ship_instance_id": attacker_id})
	assert_true(bool(begin.get("ok", false)), "begin activation of %s" % attacker_id)
	if not bool(begin.get("ok", false)):
		return begin
	var res := MatchEngine.apply_command(begin["state"],
			{"type": "DeclareAttack", "target_ship_instance_id": target_id})
	if bool(res.get("ok", false)):
		var merged: Array = []
		merged.append_array(begin["events"])
		merged.append_array(res["events"])
		res["events"] = merged
	return res


func _dice(events: Array) -> Array:
	var out: Array = []
	for e: Dictionary in events:
		if String(e["type"]) == "DieRolled":
			out.append(e)
	return out


func _first_event(events: Array, type_name: String) -> Dictionary:
	for e: Dictionary in events:
		if String(e["type"]) == type_name:
			return e
	return {}


## Re-applies `commands` to a restored copy of `pre_state` (the tuned input)
## and pins hash plus journal identity of the outcome against `final_state` /
## `final_events`: same state + same commands must yield identical results.
func _assert_deterministic(pre_state: Dictionary, commands: Array, final_state: Dictionary,
		final_events: Array) -> void:
	var restored := MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(pre_state))
	var journal: Array = []
	var cur := restored
	for cmd: Dictionary in commands:
		var res := MatchEngine.apply_command(cur, cmd)
		assert_true(bool(res.get("ok", false)), "deterministic rerun accepts the commands")
		if not bool(res.get("ok", false)):
			return
		cur = res["state"]
		journal.append_array(res["events"])
	assert_eq(MatchEngine.state_hash(cur), MatchEngine.state_hash(final_state),
			"rerun from a restored copy yields the same hash")
	assert_eq(Canonical.to_canonical(journal), Canonical.to_canonical(final_events),
			"rerun from a restored copy yields the same journal")


## Builds the C007 scenario from scratch: fresh match (seed scan), tuned duel
## of the Death Star with a 1-hp ghost, begin + declare attack.
func _build_transform_scenario() -> Dictionary:
	var c := _create_match(["death_star_1"], ["ghost"])
	if c.is_empty():
		return {}
	var st: Dictionary = c["state"]
	var ds := _seat_type(st, "A1", "death_star_1")
	var ghost := _seat_type(st, "B1", "ghost")
	_isolate(st, [String(ds["id"]), String(ghost["id"])])
	ds["q"] = 0
	ds["r"] = 0
	ds["facing"] = 0
	ghost["q"] = 0
	ghost["r"] = -1
	ghost["facing"] = 1
	ghost["hp"] = 1
	ghost["shield"] = 0
	ghost["charges"] = 2
	ghost["spent_round"] = 1 # v3.5 tuning: the tally must carry into the phantom
	var res := _begin_and_attack(st, String(ds["id"]), String(ghost["id"]))
	return {"ok": bool(res.get("ok", false)), "state": res.get("state", {}),
			"events": res.get("events", [])}


## Builds a C010 revive-success scenario from scratch: fresh match (seed scan
## over first success), tuned lethal duel of the Death Star with a TIE.
func _build_revive_scenario() -> Dictionary:
	for seed_value in range(1, 97):
		var c := MatchEngine.create_match({"seed": seed_value})
		var st: Dictionary = c["state"]
		var ds := _seat_type(st, "A1", "death_star_1")
		var tie := _seat_type(st, "B1", "tie_fighter")
		if ds.is_empty() or tie.is_empty():
			continue
		_isolate(st, [String(ds["id"]), String(tie["id"])])
		ds["q"] = 0
		ds["r"] = 0
		ds["facing"] = 0
		tie["q"] = 0
		tie["r"] = -1
		tie["facing"] = 0
		tie["hp"] = 1
		tie["shield"] = 0
		var res := _begin_and_attack(st, String(ds["id"]), String(tie["id"]))
		if not bool(res.get("ok", false)):
			continue
		if _first_event(res["events"], "ShipRevived").is_empty():
			continue
		return {"ok": true, "seed": seed_value, "state": res["state"],
				"events": res["events"]}
	return {}


func run() -> int:
	var cards := CardStore.ships()

	# ------------------------------------------------------------------ C007
	section("C007 ghost transforms into phantom on destruction")
	var c007 := _create_match(["death_star_1"], ["ghost"])
	assert_true(not c007.is_empty(), "match with A1 death_star and B1 ghost found")
	if c007.is_empty():
		return finish()
	var st: Dictionary = c007["state"]
	var ds := _seat_type(st, "A1", "death_star_1")
	var ghost := _seat_type(st, "B1", "ghost")
	_isolate(st, [String(ds["id"]), String(ghost["id"])])
	# Attacker in the Death Star front arc (sector F, +7) always wins:
	# total_a >= 1+1+7 = 9 > 7 >= total_d (d6 max +1 flat +0 arc, ADR-014).
	# Ghost faces 1 so it sees the attacker in sector BR (arc 0) — no arc help,
	# and the kill is deterministic.
	ds["q"] = 0
	ds["r"] = 0
	ds["facing"] = 0
	ghost["q"] = 0
	ghost["r"] = -1
	ghost["facing"] = 1
	ghost["hp"] = 1
	ghost["shield"] = 0
	ghost["charges"] = 2
	ghost["spent_round"] = 1 # v3.5 tuning: the tally must carry into the phantom
	var ghost_id := String(ghost["id"])
	var counter0 := int(st["rng_counter"])
	var res := _begin_and_attack(st, String(ds["id"]), ghost_id)
	assert_true(bool(res.get("ok", false)), "attack on tuned ghost accepted")
	if bool(res.get("ok", false)):
		var ev: Array = res["events"]
		var transformed := _first_event(ev, "ShipTransformed")
		assert_true(not transformed.is_empty(), "ShipTransformed emitted")
		assert_eq(String(transformed.get("ship_instance_id", "")), ghost_id, "transform id")
		assert_eq(String(transformed.get("from_type", "")), "ghost", "from_type ghost")
		assert_eq(String(transformed.get("to_type", "")), "phantom", "to_type phantom")
		assert_eq(int(transformed.get("hp", -1)), 2, "phantom enters at full hp 2")
		assert_eq(int(transformed.get("shield", -1)), 0, "phantom shield 0")
		assert_eq(int(transformed.get("charges", -1)), 2, "charges kept (min(2, max 5))")
		var destroyed := _first_event(ev, "ShipDestroyed")
		assert_true(destroyed.is_empty(), "no ShipDestroyed for the transforming ghost")
		# DamageApplied precedes the transform; transform consumes no dice.
		assert_true(ev.find(_first_event(ev, "DamageApplied")) < ev.find(transformed),
				"DamageApplied before ShipTransformed")
		var new_state: Dictionary = res["state"]
		var phantom := _by_id(new_state, ghost_id)
		assert_eq(String(phantom["type_id"]), "phantom", "ship type is now phantom")
		assert_eq(int(phantom["hp"]), 2, "stored hp 2")
		assert_eq(int(phantom["shield"]), 0, "stored shield 0")
		assert_eq(int(phantom["charges"]), 2, "stored charges 2")
		assert_eq(int(phantom["spent_round"]), 1,
				"spent_round carries into the phantom (v3.5, ADR-018 D2)")
		assert_eq(bool(phantom["alive"]), true, "transformed ship is alive")
		assert_eq(int(phantom["q"]), 0, "same cell q")
		assert_eq(int(phantom["r"]), -1, "same cell r")
		assert_eq(int(phantom["facing"]), 1, "same facing")
		assert_eq(int(new_state["rng_counter"]), counter0 + 3,
				"2 attacker d6 + defender d6; transform rolls no dice")
		assert_eq(String(new_state["phase"]), "activation", "match continues")
		assert_eq(bool(_by_id(new_state, String(ds["id"]))["attack_used"]), true,
				"attack consumed")

		section("C007 transform survives snapshot round-trip and is deterministic")
		var commands: Array = [
			{"type": "BeginActivation", "ship_instance_id": String(ds["id"])},
			{"type": "DeclareAttack", "target_ship_instance_id": ghost_id},
		]
		_assert_deterministic(st, commands, new_state, ev)
		# From-scratch determinism: two fresh builds of the same scenario
		# (same seed, same tuning, same commands) must agree with each other
		# and with the played-out state above.
		var run_a := _build_transform_scenario()
		var run_b := _build_transform_scenario()
		assert_true(bool(run_a["ok"]) and bool(run_b["ok"]), "scenario rebuilds succeed")
		assert_eq(MatchEngine.state_hash(run_a["state"]), MatchEngine.state_hash(new_state),
				"rebuild hash matches the played state")
		assert_eq(MatchEngine.state_hash(run_a["state"]), MatchEngine.state_hash(run_b["state"]),
				"two rebuilds share one hash")
		assert_eq(Canonical.to_canonical(run_a["events"]),
				Canonical.to_canonical(run_b["events"]),
				"two rebuilds share one journal")
		assert_eq(Canonical.to_canonical(run_a["events"]), Canonical.to_canonical(ev),
				"rebuild journal matches the played journal")
		var restored := MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(new_state))
		assert_eq(MatchEngine.state_hash(restored), MatchEngine.state_hash(new_state),
				"transformed state restores to the same hash")
		assert_eq(String(_by_id(restored, ghost_id)["type_id"]), "phantom",
				"phantom type survives restore")
		# Same continuation on both copies diverges nowhere.
		var cont_a := MatchEngine.apply_command(new_state, {"type": "EndActivation"})
		var cont_b := MatchEngine.apply_command(restored, {"type": "EndActivation"})
		assert_eq(MatchEngine.state_hash(cont_b["state"]),
				MatchEngine.state_hash(cont_a["state"]),
				"restored copy continues identically")

		section("C007 phantom death is final (ghost is gone)")
		# ds ends its activation, a full round passes, ds attacks the phantom
		# (hp 2 at (0,-1)) again and the destruction is a plain destroy.
		var after_end := MatchEngine.apply_command(new_state, {"type": "EndActivation"})
		assert_true(bool(after_end.get("ok", false)), "ds ends activation")
		var back := _cycle_until_fresh(after_end["state"], String(ds["id"]))
		assert_eq(bool(_by_id(back, String(ds["id"]))["activated"]), false,
				"fresh round for the death star")
		var res2 := _begin_and_attack(back, String(ds["id"]), ghost_id)
		assert_true(bool(res2.get("ok", false)), "second attack on phantom accepted")
		if bool(res2.get("ok", false)):
			var ev2: Array = res2["events"]
			var destroyed2 := _first_event(ev2, "ShipDestroyed")
			assert_eq(String(destroyed2.get("ship_instance_id", "")), ghost_id,
					"phantom destroyed plainly")
			assert_true(_first_event(ev2, "ShipTransformed").is_empty(),
					"no second transform")
			var dead := _by_id(res2["state"], ghost_id)
			assert_eq(bool(dead["alive"]), false, "phantom is dead")
			assert_eq(String(dead["type_id"]), "phantom", "stays phantom after death")
			assert_eq(int(dead["hp"]), 0, "dead hp 0")

	section("C007 negative: surviving ghost does not transform")
	var c007n := _create_match(["death_star_1"], ["ghost"])
	assert_true(not c007n.is_empty(), "negative match found")
	if not c007n.is_empty():
		var stn: Dictionary = c007n["state"]
		var dsn := _seat_type(stn, "A1", "death_star_1")
		var ghostn := _seat_type(stn, "B1", "ghost")
		_isolate(stn, [String(dsn["id"]), String(ghostn["id"])])
		dsn["q"] = 0
		dsn["r"] = 0
		dsn["facing"] = 0
		ghostn["q"] = 0
		ghostn["r"] = -1
		ghostn["facing"] = 1
		ghostn["hp"] = 20 # survives any single exchange (max diff 17: 2d6+7
		# vs d6+1+0, ADR-014)
		ghostn["shield"] = 0
		var resn := _begin_and_attack(stn, String(dsn["id"]), String(ghostn["id"]))
		assert_true(bool(resn.get("ok", false)), "negative attack accepted")
		if bool(resn.get("ok", false)):
			var evn: Array = resn["events"]
			assert_true(_first_event(evn, "ShipTransformed").is_empty(),
					"no transform on survival")
			assert_true(_first_event(evn, "ShipDestroyed").is_empty(), "no destruction")
			var surv := _by_id(resn["state"], String(ghostn["id"]))
			assert_eq(String(surv["type_id"]), "ghost", "type unchanged")
			assert_eq(bool(surv["alive"]), true, "ghost alive")
			var dmg := _first_event(evn, "DamageApplied")
			assert_eq(int(surv["hp"]), 20 - int(dmg["hull_damage"]),
					"hp reduced exactly by the hull damage")

	# ------------------------------------------------------------------ C008
	section("C008 ranged shot: distance 2 and 3 penalties")
	for step in [2, 3]:
		var c008 := _create_match(["death_star_1"], ["tie_fighter"])
		assert_true(not c008.is_empty(), "ranged match found (distance %d)" % step)
		if c008.is_empty():
			continue
		var st8: Dictionary = c008["state"]
		var ds8 := _seat_type(st8, "A1", "death_star_1")
		var tie8 := _seat_type(st8, "B1", "tie_fighter")
		_isolate(st8, [String(ds8["id"]), String(tie8["id"])])
		ds8["q"] = 0
		ds8["r"] = 0
		ds8["facing"] = 0
		tie8["q"] = 0
		tie8["r"] = -step # exact north ray, distance = step
		tie8["facing"] = 0
		tie8["hp"] = 20 # no destruction noise
		tie8["shield"] = 0
		var id8 := String(tie8["id"])
		var legal_check := MatchEngine.apply_command(st8,
				{"type": "BeginActivation", "ship_instance_id": String(ds8["id"])})
		assert_true(bool(legal_check.get("ok", false)), "ds activation begins")
		var legal := MatchEngine.legal_actions(legal_check["state"])
		var ranged_targets: Array = []
		for action: Dictionary in legal:
			if String(action["type"]) == "DeclareAttack":
				ranged_targets.append(String(action["target_ship_instance_id"]))
		var enemies: Array = []
		for s: Dictionary in st8["ships"]:
			if bool(s["alive"]) and String(s["team"]) != "A":
				enemies.append(String(s["id"]))
		assert_eq(ranged_targets, enemies,
				"distance %d: legal targets are all living enemies in ships order" % step)
		var res8 := MatchEngine.apply_command(legal_check["state"],
				{"type": "DeclareAttack", "target_ship_instance_id": id8})
		assert_true(bool(res8.get("ok", false)), "distance %d attack accepted" % step)
		if bool(res8.get("ok", false)):
			var ev8: Array = res8["events"]
			var str_a := _first_event(ev8, "StrengthCalculated")
			var arc_f := int(cards["death_star_1"]["arc_modifiers"][0])
			assert_eq(int(str_a["range_penalty"]), 2 * (step - 1),
					"distance %d: range_penalty -%d" % [step, 2 * (step - 1)])
			assert_eq(int(str_a["sector_index"]), 0, "distance %d: ray sector F" % step)
			assert_eq(int(str_a["flat_bonus"]), 0, "distance %d: attacker flat bonus 0" % step)
			assert_eq(int(str_a["die"]),
					int(str_a["dice"][0]) + int(str_a["dice"][1]),
					"distance %d: die field sums the two attacker faces" % step)
			assert_eq(int(str_a["total"]),
					maxi(0, maxi(0, int(str_a["die"]) + arc_f) - 2 * (step - 1)),
					"distance %d: total = max(0, dice+arc) - 2*(d-1)" % step)
			var str_d := {}
			var seen_strength := 0
			for e: Dictionary in ev8:
				if String(e["type"]) == "StrengthCalculated":
					seen_strength += 1
					if seen_strength == 2:
						str_d = e
			assert_eq(int(str_d["range_penalty"]), 0, "defender has no range penalty")
			assert_eq(int(str_d["flat_bonus"]), 1, "defender keeps its flat bonus at range")
			# Dice order (ADR-014 §3): two attacker d6, then the defender d6.
			var dice8 := _dice(ev8)
			assert_eq(dice8.size(), 3, "distance %d: two attacker d6 + defender d6" % step)
			assert_eq(String(dice8[0]["role"]), "attacker", "distance %d: die 1 attacker" % step)
			assert_eq(String(dice8[1]["role"]), "attacker", "distance %d: die 2 attacker" % step)
			assert_eq(String(dice8[2]["role"]), "defender", "distance %d: die 3 defender" % step)
			assert_eq(int(dice8[0]["rng_index"]), counter0, "distance %d: attacker index 1" % step)
			assert_eq(int(dice8[1]["rng_index"]), counter0 + 1, "distance %d: attacker index 2" % step)
			assert_eq(int(dice8[2]["rng_index"]), counter0 + 2, "distance %d: defender index" % step)
			assert_eq(int(res8["state"]["rng_counter"]), counter0 + 3,
					"distance %d: three dice consumed" % step)

	section("C008 adjacent Death Star attack keeps zero penalty")
	var c008a := _create_match(["death_star_1"], ["tie_fighter"])
	assert_true(not c008a.is_empty(), "adjacent ranged match found")
	if not c008a.is_empty():
		var st8a: Dictionary = c008a["state"]
		var ds8a := _seat_type(st8a, "A1", "death_star_1")
		var tie8a := _seat_type(st8a, "B1", "tie_fighter")
		_isolate(st8a, [String(ds8a["id"]), String(tie8a["id"])])
		ds8a["q"] = 0
		ds8a["r"] = 0
		ds8a["facing"] = 0
		tie8a["q"] = 0
		tie8a["r"] = -1
		tie8a["facing"] = 0
		tie8a["hp"] = 20
		tie8a["shield"] = 0
		var res8a := _begin_and_attack(st8a, String(ds8a["id"]), String(tie8a["id"]))
		assert_true(bool(res8a.get("ok", false)), "adjacent ds attack accepted")
		if bool(res8a.get("ok", false)):
			var str_aa := _first_event(res8a["events"], "StrengthCalculated")
			assert_eq(int(str_aa["range_penalty"]), 0, "adjacent attack: no penalty")
			assert_eq(int(str_aa["total"]), int(str_aa["die"]) + int(str_aa["arc_bonus"]),
					"adjacent attack: total = die + arc")

	section("C008 negative: non-ranged distant attack rejected, state unchanged")
	var c008n := _create_match(["death_star_1"], ["tie_fighter"])
	assert_true(not c008n.is_empty(), "melee-negative match found")
	if not c008n.is_empty():
		var st8n: Dictionary = c008n["state"]
		var melee := {}
		for s: Dictionary in _seat_ships(st8n, "A1"):
			if String(s["type_id"]) != "death_star_1":
				melee = s
				break
		var far_enemy := _seat_type(st8n, "B1", "tie_fighter")
		_isolate(st8n, [String(melee["id"]), String(far_enemy["id"])])
		melee["q"] = 0
		melee["r"] = 0
		melee["facing"] = 0
		far_enemy["q"] = 0
		far_enemy["r"] = -2
		far_enemy["facing"] = 0
		var begun_n := MatchEngine.apply_command(st8n,
				{"type": "BeginActivation", "ship_instance_id": String(melee["id"])})
		assert_true(bool(begun_n.get("ok", false)), "melee ship begins activation")
		# With the melee ship active, the distant enemy is not even legal.
		var distant_legal := false
		for action: Dictionary in MatchEngine.legal_actions(begun_n["state"]):
			if String(action["type"]) == "DeclareAttack" \
					and String(action.get("target_ship_instance_id", "")) == String(far_enemy["id"]):
				distant_legal = true
		assert_true(not distant_legal, "distant enemy not offered to a melee attacker")
		var hash_before := MatchEngine.state_hash(begun_n["state"])
		var rejected := MatchEngine.apply_command(begun_n["state"],
				{"type": "DeclareAttack", "target_ship_instance_id": String(far_enemy["id"])})
		assert_true(not bool(rejected.get("ok", true)), "distant attack rejected")
		assert_eq(String(rejected.get("error", "")), "not_adjacent", "not_adjacent code")
		assert_eq(MatchEngine.state_hash(begun_n["state"]), hash_before,
				"rejected command leaves state untouched")

	# ------------------------------------------------------------------ C009
	section("C009 X-wing lucky shot on a tie (d2, 1 damage)")
	var ties_seen := 0
	var lucky_wins := 0
	var lucky_losses := 0
	# The v3.2 duel drafts 3 enemy ships per seed (was 6), so ties over
	# (attacker faces == defender die + 1) are rarer per seed: scan twice as
	# many deterministic seeds.
	for seed_value in range(1, 481):
		var c009 := MatchEngine.create_match({"seed": seed_value})
		var xw := _seat_type(c009["state"], "A1", "xwing_t65")
		if xw.is_empty():
			continue
		# Prefer a defender whose back arc equals the X-wing front arc (+2):
		# then a tie happens exactly when the two attacker faces sum to the
		# defender die + 1 flat bonus — still p = 1/6 over (d6+d6) vs d6.
		var target := {}
		for s: Dictionary in _seat_ships(c009["state"], "B1"):
			if int(cards[String(s["type_id"])]["arc_modifiers"][3]) == 2:
				target = s
				break
		if target.is_empty():
			continue
		var st9: Dictionary = c009["state"]
		var def9 := target
		_isolate(st9, [String(xw["id"]), String(def9["id"])])
		xw["q"] = 0
		xw["r"] = 0
		xw["facing"] = 0
		def9["q"] = 0
		def9["r"] = -1
		def9["facing"] = 0
		def9["hp"] = 20
		def9["shield"] = 1
		var res9 := _begin_and_attack(st9, String(xw["id"]), String(def9["id"]))
		assert_true(bool(res9.get("ok", false)), "xwing attack accepted, seed %d" % seed_value)
		if not bool(res9.get("ok", false)):
			continue
		var post9: Dictionary = res9["state"]
		var ev9: Array = res9["events"]
		var strengths9: Array = []
		for e: Dictionary in ev9:
			if String(e["type"]) == "StrengthCalculated":
				strengths9.append(e)
		var dice9 := _dice(ev9)
		# Base dice order (ADR-014 §3): two attacker d6, then the defender d6.
		assert_eq(String(dice9[0]["role"]), "attacker", "seed %d: die 1 attacker" % seed_value)
		assert_eq(String(dice9[1]["role"]), "attacker", "seed %d: die 2 attacker" % seed_value)
		assert_eq(String(dice9[2]["role"]), "defender", "seed %d: die 3 defender" % seed_value)
		var total_a9 := int(strengths9[0]["total"])
		var total_d9 := int(strengths9[1]["total"])
		if total_a9 != total_d9:
			# Negative path: no tie, no bonus die of any kind.
			assert_eq(dice9.size(), 3,
					"seed %d: non-tie keeps exactly the three base dice" % seed_value)
			assert_eq(int(post9["rng_counter"]), counter0 + 3,
					"seed %d: non-tie consumes three dice" % seed_value)
			assert_true(_first_event(ev9, "ShipRevived").is_empty(), "no revive noise")
			continue
		ties_seen += 1
		assert_eq(dice9.size(), 4, "seed %d: tie adds one d2" % seed_value)
		assert_eq(int(dice9[3]["sides"]), 2, "seed %d: bonus die is a d2" % seed_value)
		# The lucky-shot d2 comes after the defender die (ADR-014 §3 / ADR-012 §2).
		assert_eq(int(dice9[3]["rng_index"]), counter0 + 3,
				"seed %d: d2 rng_index follows the defender" % seed_value)
		assert_eq(int(post9["rng_counter"]), counter0 + 4, "seed %d: four dice consumed" % seed_value)
		var d2_value := int(dice9[3]["value"])
		var dmg9 := _first_event(ev9, "DamageApplied")
		if d2_value == 2:
			lucky_wins += 1
			assert_true(not dmg9.is_empty(), "seed %d: success deals damage" % seed_value)
			assert_eq(String(dmg9["target_id"]), String(def9["id"]),
					"seed %d: damage hits the defender" % seed_value)
			assert_eq(int(dmg9["shield_damage"]), 1, "seed %d: shield absorbs the 1" % seed_value)
			assert_eq(int(dmg9["hull_damage"]), 0, "seed %d: no hull damage" % seed_value)
			assert_eq(int(_by_id(res9["state"], String(def9["id"]))["hp"]), 20,
					"seed %d: hp untouched" % seed_value)
			assert_eq(int(_by_id(res9["state"], String(def9["id"]))["shield"]), 0,
					"seed %d: shield spent" % seed_value)
		else:
			lucky_losses += 1
			assert_true(dmg9.is_empty(), "seed %d: failed d2 deals nothing" % seed_value)
			assert_eq(int(_by_id(res9["state"], String(def9["id"]))["hp"]), 20,
					"seed %d: hp untouched on fail" % seed_value)
			assert_eq(int(_by_id(res9["state"], String(def9["id"]))["shield"]), 1,
					"seed %d: shield untouched on fail" % seed_value)
	assert_between(ties_seen, 4, 480, "enough ties observed for C009")
	assert_true(lucky_wins >= 1, "at least one successful lucky shot")
	assert_true(lucky_losses >= 1, "at least one failed lucky shot")

	# ------------------------------------------------------------------ C010
	section("C010 TIE resurrection: one d2 attempt, d4 hp on success")
	var revives_seen := 0
	var revive_fails := 0
	for seed_value in range(1, 97):
		var c010 := MatchEngine.create_match({"seed": seed_value})
		var st10: Dictionary = c010["state"]
		var ds10 := _seat_type(st10, "A1", "death_star_1")
		var tie10 := _seat_type(st10, "B1", "tie_fighter")
		if ds10.is_empty() or tie10.is_empty():
			continue
		_isolate(st10, [String(ds10["id"]), String(tie10["id"])])
		ds10["q"] = 0
		ds10["r"] = 0
		ds10["facing"] = 0
		tie10["q"] = 0
		tie10["r"] = -1
		tie10["facing"] = 0
		tie10["hp"] = 1
		tie10["shield"] = 0
		var tie_id10 := String(tie10["id"])
		var res10 := _begin_and_attack(st10, String(ds10["id"]), tie_id10)
		assert_true(bool(res10.get("ok", false)), "seed %d: kill attack accepted" % seed_value)
		if not bool(res10.get("ok", false)):
			continue
		var post10: Dictionary = res10["state"]
		var ev10: Array = res10["events"]
		var dice10 := _dice(ev10)
		assert_eq(String(dice10[0]["role"]), "attacker", "seed %d: die 1 attacker" % seed_value)
		assert_eq(int(dice10[0]["sides"]), 6, "seed %d: attacker d6 1" % seed_value)
		assert_eq(String(dice10[1]["role"]), "attacker", "seed %d: die 2 attacker" % seed_value)
		assert_eq(int(dice10[1]["sides"]), 6, "seed %d: attacker d6 2" % seed_value)
		assert_eq(String(dice10[2]["role"]), "defender", "seed %d: defender rolls third" % seed_value)
		assert_eq(int(dice10[2]["sides"]), 6, "seed %d: defender d6" % seed_value)
		assert_eq(int(dice10[2]["rng_index"]), counter0 + 2, "seed %d: defender index" % seed_value)
		var revived10 := _first_event(ev10, "ShipRevived")
		var destroyed10 := _first_event(ev10, "ShipDestroyed")
		var dmg10 := _first_event(ev10, "DamageApplied")
		assert_true(not dmg10.is_empty(), "seed %d: lethal damage applied" % seed_value)
		if not dmg10.is_empty():
			assert_eq(int(dmg10["hp_left"]), 0, "seed %d: hp reaches 0" % seed_value)
		assert_true(not revived10.is_empty() or not destroyed10.is_empty(),
				"seed %d: destruction resolved" % seed_value)
		if not revived10.is_empty():
			revives_seen += 1
			assert_eq(dice10.size(), 5, "seed %d: revive consumes d2+d4" % seed_value)
			assert_eq(int(dice10[3]["sides"]), 2, "seed %d: revive chance is d2" % seed_value)
			assert_eq(int(dice10[4]["sides"]), 4, "seed %d: hp die is d4" % seed_value)
			assert_eq(int(dice10[3]["value"]), 2, "seed %d: success path" % seed_value)
			assert_eq(int(dice10[3]["rng_index"]), counter0 + 3, "seed %d: d2 index" % seed_value)
			assert_eq(int(dice10[4]["rng_index"]), counter0 + 4, "seed %d: d4 index" % seed_value)
			assert_eq(String(revived10["ship_instance_id"]), tie_id10, "seed %d: revived id" % seed_value)
			assert_eq(int(revived10["hp"]), int(dice10[4]["value"]),
					"seed %d: ShipRevived hp equals the d4" % seed_value)
			var tie_after := _by_id(res10["state"], tie_id10)
			assert_eq(bool(tie_after["alive"]), true, "seed %d: revived is alive" % seed_value)
			assert_eq(int(tie_after["hp"]), int(dice10[4]["value"]),
					"seed %d: stored hp = d4" % seed_value)
			assert_eq(int(tie_after["shield"]), 0, "seed %d: shield reset" % seed_value)
			assert_eq(bool(tie_after["revive_used"]), true, "seed %d: attempt consumed" % seed_value)
			assert_eq(int(tie_after["q"]), 0, "seed %d: stays on its cell" % seed_value)
			assert_eq(int(tie_after["r"]), -1, "seed %d: stays on its cell r" % seed_value)
			assert_true(destroyed10.is_empty(),
					"seed %d: no ShipDestroyed before the attempt" % seed_value)
			assert_eq(int(post10["rng_counter"]), counter0 + 5,
					"seed %d: five dice consumed" % seed_value)
		else:
			revive_fails += 1
			assert_eq(dice10.size(), 4, "seed %d: failed revive consumes only d2" % seed_value)
			assert_eq(int(dice10[3]["sides"]), 2, "seed %d: chance die still rolled" % seed_value)
			assert_eq(int(dice10[3]["value"]), 1, "seed %d: failure path" % seed_value)
			assert_eq(String(destroyed10["ship_instance_id"]), tie_id10,
					"seed %d: ShipDestroyed on failure" % seed_value)
			var tie_dead := _by_id(res10["state"], tie_id10)
			assert_eq(bool(tie_dead["alive"]), false, "seed %d: stays dead" % seed_value)
			assert_eq(bool(tie_dead["revive_used"]), true,
					"seed %d: failed attempt is consumed" % seed_value)
			assert_eq(int(post10["rng_counter"]), counter0 + 4,
					"seed %d: four dice consumed" % seed_value)
	assert_true(revives_seen >= 1, "at least one successful revival")
	assert_true(revive_fails >= 1, "at least one failed revival")

	section("C010 revive determinism and snapshot round-trip")
	var scenario := _build_revive_scenario()
	assert_true(not scenario.is_empty(), "a revival scenario was captured")
	if not scenario.is_empty():
		var scenario_b := _build_revive_scenario()
		assert_eq(MatchEngine.state_hash(scenario["state"]),
				MatchEngine.state_hash(scenario_b["state"]),
				"two revive rebuilds share one hash")
		assert_eq(Canonical.to_canonical(scenario["events"]),
				Canonical.to_canonical(scenario_b["events"]),
				"two revive rebuilds share one journal")
		var revived_event := _first_event(scenario["events"], "ShipRevived")
		var restored10 := MatchEngine.restore_snapshot(
				MatchEngine.snapshot_bytes(scenario["state"]))
		assert_eq(MatchEngine.state_hash(restored10),
				MatchEngine.state_hash(scenario["state"]),
				"revived state restores to the same hash")
		assert_eq(int(_by_id(restored10, String(revived_event["ship_instance_id"]))["hp"]),
				int(revived_event["hp"]), "revive d4 hp survives restore")
		assert_eq(bool(_by_id(restored10, String(revived_event["ship_instance_id"]))["revive_used"]),
				true, "revive_used survives restore")

	section("C010 negative: second destruction is final (no d2)")
	var c010n := _create_match(["death_star_1"], ["tie_fighter"])
	assert_true(not c010n.is_empty(), "second-death match found")
	if not c010n.is_empty():
		var st10n: Dictionary = c010n["state"]
		var ds10n := _seat_type(st10n, "A1", "death_star_1")
		var tie10n := _seat_type(st10n, "B1", "tie_fighter")
		_isolate(st10n, [String(ds10n["id"]), String(tie10n["id"])])
		ds10n["q"] = 0
		ds10n["r"] = 0
		ds10n["facing"] = 0
		tie10n["q"] = 0
		tie10n["r"] = -1
		tie10n["facing"] = 0
		tie10n["hp"] = 1
		tie10n["shield"] = 0
		tie10n["revive_used"] = true # the single attempt is already spent
		var res10n := _begin_and_attack(st10n, String(ds10n["id"]), String(tie10n["id"]))
		assert_true(bool(res10n.get("ok", false)), "second-death attack accepted")
		if bool(res10n.get("ok", false)):
			var ev10n: Array = res10n["events"]
			assert_eq(_dice(ev10n).size(), 3, "base dice only, no revive dice for the second death")
			var destroyed10n := _first_event(ev10n, "ShipDestroyed")
			assert_eq(String(destroyed10n.get("ship_instance_id", "")), String(tie10n["id"]),
					"ShipDestroyed emitted immediately")
			assert_eq(bool(_by_id(res10n["state"], String(tie10n["id"]))["alive"]), false,
					"tie stays dead")
			assert_true(_first_event(ev10n, "ShipRevived").is_empty(), "no revival")

	section("C010 negative: non-TIE destruction rolls no revive dice")
	var non_tie_seen := false
	for seed_value in range(1, 97):
		var c010b := MatchEngine.create_match({"seed": seed_value})
		var st10b: Dictionary = c010b["state"]
		var ds10b := _seat_type(st10b, "A1", "death_star_1")
		var victim := {}
		for s: Dictionary in _seat_ships(st10b, "B1"):
			var t := String(s["type_id"])
			if t != "tie_fighter" and t != "ghost": # plain hull, no death specials
				victim = s
				break
		if ds10b.is_empty() or victim.is_empty():
			continue
		_isolate(st10b, [String(ds10b["id"]), String(victim["id"])])
		ds10b["q"] = 0
		ds10b["r"] = 0
		ds10b["facing"] = 0
		victim["q"] = 0
		victim["r"] = -1
		victim["facing"] = 0
		victim["hp"] = 1
		victim["shield"] = 0
		var res10b := _begin_and_attack(st10b, String(ds10b["id"]), String(victim["id"]))
		assert_true(bool(res10b.get("ok", false)), "plain kill accepted, seed %d" % seed_value)
		if not bool(res10b.get("ok", false)):
			continue
		non_tie_seen = true
		var ev10b: Array = res10b["events"]
		assert_eq(_dice(ev10b).size(), 3, "seed %d: plain death, base three dice" % seed_value)
		assert_eq(String(_first_event(ev10b, "ShipDestroyed").get("ship_instance_id", "")),
				String(victim["id"]), "seed %d: plain ShipDestroyed" % seed_value)
		assert_eq(int(res10b["state"]["rng_counter"]), counter0 + 3,
				"seed %d: three dice consumed" % seed_value)
		break
	assert_true(non_tie_seen, "a plain-hull destruction was exercised")

	# ------------------------------------------------------------------ C011
	section("C011 vulture rerolls one natural attack 1 via d2 (ADR-014 §3)")
	var ones_seen := 0
	var reroll_ok := 0
	var reroll_fail := 0
	for seed_value in range(1, 97):
		var c011 := MatchEngine.create_match({"seed": seed_value})
		var st11: Dictionary = c011["state"]
		var vul := _seat_type(st11, "A1", "vulture_droid")
		if vul.is_empty():
			continue
		var foe: Dictionary = _seat_ships(st11, "B1")[0]
		_isolate(st11, [String(vul["id"]), String(foe["id"])])
		vul["q"] = 0
		vul["r"] = 0
		vul["facing"] = 0
		vul["hp"] = 20 # nobody dies: pure dice observation
		vul["shield"] = 0
		foe["q"] = 0
		foe["r"] = -1
		foe["facing"] = 0
		foe["hp"] = 20
		foe["shield"] = 0
		var res11 := _begin_and_attack(st11, String(vul["id"]), String(foe["id"]))
		assert_true(bool(res11.get("ok", false)), "vulture attack accepted, seed %d" % seed_value)
		if not bool(res11.get("ok", false)):
			continue
		var post11: Dictionary = res11["state"]
		var ev11: Array = res11["events"]
		var dice11 := _dice(ev11)
		var strengths11: Array = []
		for e: Dictionary in ev11:
			if String(e["type"]) == "StrengthCalculated":
				strengths11.append(e)
		# Dice order (ADR-014 §3): attacker d6, attacker d6, [d2 + optional d6],
		# defender d6 last.
		assert_eq(String(dice11[0]["role"]), "attacker", "seed %d: die 1 attacker" % seed_value)
		assert_eq(int(dice11[0]["rng_index"]), counter0, "seed %d: die 1 index" % seed_value)
		assert_eq(String(dice11[1]["role"]), "attacker", "seed %d: die 2 attacker" % seed_value)
		assert_eq(int(dice11[1]["rng_index"]), counter0 + 1, "seed %d: die 2 index" % seed_value)
		assert_eq(String(dice11[dice11.size() - 1]["role"]), "defender",
				"seed %d: defender rolls last" % seed_value)
		var first_roll := int(dice11[0]["value"])
		var second_roll := int(dice11[1]["value"])
		if first_roll != 1 and second_roll != 1:
			# Negative path: ability does not trigger without a natural 1.
			assert_eq(dice11.size(), 3, "seed %d: no 1, no extra dice" % seed_value)
			assert_eq(int(strengths11[0]["die"]), first_roll + second_roll,
					"seed %d: attacker dice unchanged" % seed_value)
			assert_eq(int(post11["rng_counter"]), counter0 + 3,
					"seed %d: three dice consumed" % seed_value)
			continue
		ones_seen += 1
		assert_eq(int(dice11[2]["sides"]), 2,
				"seed %d: d2 follows the second attacker die" % seed_value)
		assert_eq(int(dice11[2]["rng_index"]), counter0 + 2, "seed %d: d2 index" % seed_value)
		var faces: Array = [first_roll, second_roll]
		if int(dice11[2]["value"]) == 2:
			reroll_ok += 1
			assert_eq(int(dice11[3]["sides"]), 6,
					"seed %d: success forces a d6 reroll" % seed_value)
			assert_eq(int(dice11[3]["rng_index"]), counter0 + 3,
					"seed %d: reroll index" % seed_value)
			var rerolled := int(dice11[3]["value"])
			faces[faces.find(1)] = rerolled # only the FIRST 1 is replaced
			assert_eq(dice11.size(), 5, "seed %d: d6,d6,d2,d6 + defender d6" % seed_value)
			assert_eq(int(strengths11[0]["die"]), int(faces[0]) + int(faces[1]),
					"seed %d: final dice are summed" % seed_value)
			assert_eq(strengths11[0]["dice"], faces,
					"seed %d: dice field shows the final faces" % seed_value)
			assert_eq(int(post11["rng_counter"]), counter0 + 5,
					"seed %d: d6+d6+d2+d6+defender d6" % seed_value)
			if first_roll == 1 and second_roll == 1:
				assert_eq(int(faces[1]), 1,
						"seed %d: with two ones only the first rerolls" % seed_value)
		else:
			reroll_fail += 1
			assert_eq(dice11.size(), 4, "seed %d: failed d2 keeps the ones" % seed_value)
			assert_eq(int(strengths11[0]["die"]), first_roll + second_roll,
					"seed %d: dice stay" % seed_value)
			assert_eq(int(post11["rng_counter"]), counter0 + 4,
					"seed %d: d6+d6+d2+defender d6" % seed_value)
	assert_true(ones_seen >= 1, "at least one natural 1 observed")
	assert_true(reroll_ok >= 1, "at least one successful reroll")
	assert_true(reroll_fail >= 1, "at least one failed reroll chance")

	section("C011 reroll edge cases pinned on hunted seeds (deterministic)")
	# Hunted scan: find one attack with two natural 1s (only the first rerolls)
	# and one whose forced reroll lands on 1 again (final, no repeat).
	var double_one := {}
	var rerolled_one := {}
	for seed_value in range(1, 2001):
		var c011b := MatchEngine.create_match({"seed": seed_value})
		var stb: Dictionary = c011b["state"]
		var vulb := _seat_type(stb, "A1", "vulture_droid")
		if vulb.is_empty():
			continue
		var foeb: Dictionary = _seat_ships(stb, "B1")[0]
		_isolate(stb, [String(vulb["id"]), String(foeb["id"])])
		vulb["q"] = 0
		vulb["r"] = 0
		vulb["facing"] = 0
		vulb["hp"] = 20
		vulb["shield"] = 0
		foeb["q"] = 0
		foeb["r"] = -1
		foeb["facing"] = 0
		foeb["hp"] = 20
		foeb["shield"] = 0
		var resb := _begin_and_attack(stb, String(vulb["id"]), String(foeb["id"]))
		if not bool(resb.get("ok", false)):
			continue
		var diceb := _dice(resb["events"])
		if int(diceb[2]["sides"]) != 2 or int(diceb[2]["value"]) != 2:
			continue # no successful reroll in this attack
		if int(diceb[0]["value"]) == 1 and int(diceb[1]["value"]) == 1 and double_one.is_empty():
			double_one = {"seed": seed_value, "events": resb["events"], "state": resb["state"]}
		if int(diceb[3]["value"]) == 1 and rerolled_one.is_empty():
			rerolled_one = {"seed": seed_value, "events": resb["events"], "state": resb["state"]}
		if not double_one.is_empty() and not rerolled_one.is_empty():
			break
	assert_true(not double_one.is_empty(), "a two-natural-1 vulture attack was observed")
	assert_true(not rerolled_one.is_empty(), "a reroll landing on 1 was observed")
	if not double_one.is_empty():
		var evd: Array = double_one["events"]
		var diced := _dice(evd)
		var str_ad := _first_event(evd, "StrengthCalculated")
		assert_eq(diced.size(), 5, "d6,d6,d2,d6 reroll, defender d6 — exactly one reroll")
		assert_eq(int(diced[2]["sides"]), 2, "single d2 gate")
		assert_eq(int(diced[2]["value"]), 2, "reroll chance succeeded")
		assert_eq(int(diced[3]["sides"]), 6, "exactly one d6 reroll follows")
		assert_eq(int(diced[3]["rng_index"]), counter0 + 3, "reroll index")
		assert_eq(String(diced[4]["role"]), "defender", "defender after the reroll")
		assert_eq(int(diced[4]["rng_index"]), counter0 + 4, "defender index after the reroll")
		assert_eq(str_ad["dice"], [int(diced[3]["value"]), 1],
				"only the first 1 was rerolled; the second 1 stands")
		assert_eq(int(str_ad["die"]), int(diced[3]["value"]) + 1,
				"die field = rerolled face + untouched second 1")
		assert_eq(int(double_one["state"]["rng_counter"]), counter0 + 5, "five dice consumed")
	if not rerolled_one.is_empty():
		var evr: Array = rerolled_one["events"]
		var dicer := _dice(evr)
		var str_ar := _first_event(evr, "StrengthCalculated")
		assert_eq(int(dicer[3]["sides"]), 6, "one forced reroll d6")
		assert_eq(int(dicer[3]["value"]), 1, "the reroll landed on 1")
		# The rerolled 1 counts as 1: the die sum equals the two natural faces.
		assert_eq(int(str_ar["die"]), int(dicer[0]["value"]) + int(dicer[1]["value"]),
				"the rerolled 1 is final (no repeated reroll)")
		assert_eq(int(str_ar["total"]), maxi(0, int(str_ar["die"]) + int(str_ar["arc_bonus"])),
				"total uses the final 1")
		assert_eq(int(rerolled_one["state"]["rng_counter"]), counter0 + 5,
				"no extra die after the rerolled 1")

	# ------------------------------------------------------------ legal actions
	section("legal_actions: ranged attacker threatens the whole board")
	var c_leg := _create_match(["death_star_1"], ["tie_fighter"])
	assert_true(not c_leg.is_empty(), "legal-actions match found")
	if not c_leg.is_empty():
		var stl: Dictionary = c_leg["state"]
		var dsl := _seat_type(stl, "A1", "death_star_1")
		_isolate(stl, [String(dsl["id"])])
		dsl["q"] = 0
		dsl["r"] = 0
		dsl["facing"] = 0
		var begun := MatchEngine.apply_command(stl,
				{"type": "BeginActivation", "ship_instance_id": String(dsl["id"])})
		assert_true(bool(begun.get("ok", false)), "ds begins activation")
		var legal_l := MatchEngine.legal_actions(begun["state"])
		var targets_l: Array = []
		var other_l := 0
		for action: Dictionary in legal_l:
			if String(action["type"]) == "DeclareAttack":
				targets_l.append(String(action["target_ship_instance_id"]))
			else:
				other_l += 1
		var enemies_l: Array = []
		for s: Dictionary in begun["state"]["ships"]:
			if bool(s["alive"]) and String(s["team"]) != "A":
				enemies_l.append(String(s["id"]))
		assert_eq(targets_l, enemies_l, "every living enemy is a legal target, ships order")
		assert_true(other_l >= 4, "movement, rotations and EndActivation remain legal")

	section("legal_actions: melee attacker keeps adjacency only")
	var c_leg2 := _create_match(["death_star_1"], ["tie_fighter"])
	assert_true(not c_leg2.is_empty(), "melee legal-actions match found")
	if not c_leg2.is_empty():
		var stl2: Dictionary = c_leg2["state"]
		var melee2 := {}
		for s: Dictionary in _seat_ships(stl2, "A1"):
			if String(s["type_id"]) != "death_star_1":
				melee2 = s
				break
		var near := _seat_type(stl2, "B1", "tie_fighter")
		_isolate(stl2, [String(melee2["id"]), String(near["id"])])
		melee2["q"] = 0
		melee2["r"] = 0
		melee2["facing"] = 0
		near["q"] = 0
		near["r"] = -1
		near["facing"] = 0
		var begun2 := MatchEngine.apply_command(stl2,
				{"type": "BeginActivation", "ship_instance_id": String(melee2["id"])})
		assert_true(bool(begun2.get("ok", false)), "melee ship begins activation")
		var attack_ids: Array = []
		for action: Dictionary in MatchEngine.legal_actions(begun2["state"]):
			if String(action["type"]) == "DeclareAttack":
				attack_ids.append(String(action["target_ship_instance_id"]))
		assert_eq(attack_ids, [String(near["id"])], "only the adjacent enemy is legal")

	section("every ship carries the revive_used and spent_round fields from creation")
	var fresh := MatchEngine.create_match({"seed": 42})
	var all_flagged := true
	for s: Dictionary in fresh["state"]["ships"]:
		if not s.has("revive_used") or bool(s["revive_used"]):
			all_flagged = false
	assert_true(all_flagged, "revive_used present and false for all 6 ships")
	var all_spent_zero := true
	for s: Dictionary in fresh["state"]["ships"]:
		if not s.has("spent_round") or int(s["spent_round"]) != 0:
			all_spent_zero = false
	assert_true(all_spent_zero, "spent_round present and 0 for all 6 ships (ADR-018)")
	assert_eq(int(fresh["state"]["version"]), 4, "state version 4 (ADR-018)")
	assert_true(fresh["state"].has("dice"), "state carries the dice log")
	var dice_empty: Array = fresh["state"]["dice"]
	assert_eq(dice_empty.size(), 0, "dice log starts empty")
	assert_eq(int(fresh["state"]["rng_counter"]), 0, "counter starts at 0")

	return finish()
