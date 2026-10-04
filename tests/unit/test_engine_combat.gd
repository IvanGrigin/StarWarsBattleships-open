# Engine tests: combat pipeline — dice order (v3.1: 2 attacker d6 vs d6 +1,
# ADR-014), sectors, arcs, strength formula, shield-first damage, destruction
# (core-api §4.3, rules-v3 §7).
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const CardStore := preload("res://src/core/data/card_store.gd")


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


## Places attacker at (0,0) facing 0 and defender at (0,-1) facing 0:
## attacker sees the defender in sector F (0), defender sees the attacker in
## sector B (3). Runs BeginActivation + DeclareAttack and returns the result.
func _run_attack(full_state: Dictionary, attacker: Dictionary, defender: Dictionary) -> Dictionary:
	attacker["q"] = 0
	attacker["r"] = 0
	attacker["facing"] = 0
	defender["q"] = 0
	defender["r"] = -1
	defender["facing"] = 0
	var res := MatchEngine.apply_command(full_state,
			{"type": "BeginActivation", "ship_instance_id": String(attacker["id"])})
	assert_true(bool(res.get("ok", false)), "begin attacker activation")
	if not bool(res.get("ok", false)):
		return res
	return MatchEngine.apply_command(res["state"],
			{"type": "DeclareAttack", "target_ship_instance_id": String(defender["id"])})


## First ship of `seat` whose type has no enabled special abilities; such ships
## keep the plain combat pipeline (no transform, revive, reroll, lucky shot).
func _plain_ship(state: Dictionary, seat: String) -> Dictionary:
	var defs := CardStore.ships_ref()
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) != seat:
			continue
		var has_enabled := false
		for a: Dictionary in defs.get(String(s["type_id"]), {}).get("abilities", []):
			if bool(a.get("enabled", false)):
				has_enabled = true
				break
		if not has_enabled:
			return s
	return {}


func run() -> int:
	var cards := CardStore.ships()
	var rules := CardStore.game_rules()
	var flat_bonus := int(rules.get("combat_defender_flat_bonus", 1))

	section("attack event pipeline recomputed from DieRolled (plain duelists)")
	var created := {}
	var state: Dictionary = {}
	var attacker: Dictionary = {}
	var defender: Dictionary = {}
	for seed_value in range(1, 200):
		var candidate := MatchEngine.create_match({"seed": seed_value})
		var plain_a := _plain_ship(candidate["state"], "A1")
		var plain_d := _plain_ship(candidate["state"], "B1")
		if not plain_a.is_empty() and not plain_d.is_empty():
			created = candidate
			state = candidate["state"]
			attacker = plain_a
			defender = plain_d
			break
	assert_true(not created.is_empty(), "a match with plain duelists on both sides found")
	if created.is_empty():
		return finish()
	# Plain ships only: special dice (vulture reroll, xwing lucky shot) are
	# covered in test_engine_specials.gd, this section pins the base pipeline.
	var att_id := String(attacker["id"])
	var def_id := String(defender["id"])
	var att_arc: Array = cards[String(attacker["type_id"])]["arc_modifiers"]
	var def_arc: Array = cards[String(defender["type_id"])]["arc_modifiers"]
	defender["shield"] = 2 # shield-first absorption check
	var def_hp0 := int(defender["hp"])
	var att_hp0 := int(attacker["hp"])
	var att_shield0 := int(attacker["shield"])
	var charges0 := int(attacker["charges"])
	var counter0 := int(state["rng_counter"])
	var res := _run_attack(state, attacker, defender)
	assert_true(bool(res.get("ok", false)), "DeclareAttack accepted")
	var ev: Array = res["events"]
	assert_true(ev.size() >= 6, "attack emits at least the six pipeline events")
	assert_eq(String(ev[0]["type"]), "AttackDeclared", "event 0 AttackDeclared")
	assert_eq(String(ev[0]["attacker_id"]), att_id, "attacker id in AttackDeclared")
	assert_eq(String(ev[0]["target_id"]), def_id, "target id in AttackDeclared")
	# Dice order (ADR-014 §3): two attacker d6, then the defender d6 — every
	# die its own DieRolled with a consecutive rng_index; strengths after.
	assert_eq(String(ev[1]["type"]), "DieRolled", "event 1 first attacker die")
	assert_eq(String(ev[1]["role"]), "attacker", "attacker rolls first")
	assert_eq(int(ev[1]["rng_index"]), counter0, "first attacker rng_index")
	assert_eq(int(ev[1]["sides"]), 6, "attacker d6 1")
	assert_eq(String(ev[2]["type"]), "DieRolled", "event 2 second attacker die")
	assert_eq(String(ev[2]["role"]), "attacker", "second die is the attacker's")
	assert_eq(int(ev[2]["rng_index"]), counter0 + 1, "second attacker rng_index")
	assert_eq(int(ev[2]["sides"]), 6, "attacker d6 2")
	assert_eq(String(ev[3]["type"]), "DieRolled", "event 3 defender die")
	assert_eq(String(ev[3]["role"]), "defender", "defender rolls after both attacker dice")
	assert_eq(int(ev[3]["rng_index"]), counter0 + 2, "defender rng_index")
	assert_eq(int(ev[3]["sides"]), 6, "defender d6")
	assert_eq(String(ev[4]["type"]), "StrengthCalculated", "event 4 attacker strength")
	assert_eq(String(ev[4]["ship_instance_id"]), att_id, "attacker strength id")
	assert_eq(String(ev[5]["type"]), "StrengthCalculated", "event 5 defender strength")
	assert_eq(String(ev[5]["ship_instance_id"]), def_id, "defender strength id")

	var die_a1 := int(ev[1]["value"])
	var die_a2 := int(ev[2]["value"])
	var die_d := int(ev[3]["value"])
	assert_between(die_a1, 1, 6, "attacker die 1 in 1..6")
	assert_between(die_a2, 1, 6, "attacker die 2 in 1..6")
	assert_between(die_d, 1, 6, "defender die in 1..6")
	var sum_a := die_a1 + die_a2
	# attacker: dir (0,0)->(0,-1) is 0 (N), facing 0 -> sector 0 (F)
	assert_eq(int(ev[4]["sector_index"]), 0, "attacker sector F")
	assert_eq(int(ev[4]["arc_bonus"]), int(att_arc[0]), "attacker arc from card")
	assert_eq(int(ev[4]["die"]), sum_a, "attacker die field is the face sum")
	assert_eq(ev[4]["dice"], [die_a1, die_a2], "attacker dice field lists both faces")
	assert_eq(int(ev[4]["flat_bonus"]), 0, "attacker has no flat bonus")
	assert_eq(int(ev[4]["range_penalty"]), 0, "adjacent attack has no range penalty")
	assert_eq(int(ev[4]["total"]), maxi(0, sum_a + int(att_arc[0])),
			"strength = max(0, dice sum + arc)")
	# defender: dir (0,-1)->(0,0) is 3 (S), facing 0 -> sector 3 (B)
	assert_eq(int(ev[5]["sector_index"]), 3, "defender sector B")
	assert_eq(int(ev[5]["arc_bonus"]), int(def_arc[3]), "defender arc from card")
	assert_eq(int(ev[5]["die"]), die_d, "defender die field is the face sum")
	assert_eq(ev[5]["dice"], [die_d], "defender dice field lists its single face")
	assert_eq(int(ev[5]["flat_bonus"]), flat_bonus, "defender carries the flat bonus")
	assert_eq(int(ev[5]["total"]), maxi(0, die_d + flat_bonus + int(def_arc[3])),
			"strength = max(0, die + flat bonus + arc)")

	var new_state: Dictionary = res["state"]
	assert_eq(int(new_state["rng_counter"]), counter0 + 3, "three dice consumed")
	assert_eq(int(new_state["dice"].size()), counter0 + 3, "dice log mirrors rng_counter")
	assert_eq(int(_by_id(new_state, att_id)["charges"]), charges0, "attack costs no charges")

	var total_a := int(ev[4]["total"])
	var total_d := int(ev[5]["total"])
	var diff := absi(total_a - total_d)
	var post_att := _by_id(new_state, att_id)
	var post_def := _by_id(new_state, def_id)
	if diff == 0:
		assert_eq(ev.size(), 6, "tie: no damage events")
		assert_eq(int(post_def["hp"]), def_hp0, "tie keeps defender hp")
		assert_eq(int(post_def["shield"]), 2, "tie keeps defender shield")
		assert_eq(int(post_att["hp"]), att_hp0, "tie keeps attacker hp")
		assert_eq(bool(post_def["alive"]), true, "tie kills nobody")
	else:
		var loser_id := def_id if total_a > total_d else att_id
		var loser0_hp := def_hp0 if total_a > total_d else att_hp0
		var loser0_shield := 2 if total_a > total_d else att_shield0
		var post_loser := post_def if total_a > total_d else post_att
		assert_eq(String(ev[6]["type"]), "DamageApplied", "DamageApplied on non-tie")
		var dmg: Dictionary = ev[6]
		assert_eq(String(dmg["target_id"]), loser_id, "damage hits the loser")
		assert_eq(int(dmg["shield_damage"]), mini(loser0_shield, diff), "shield absorbs first")
		assert_eq(int(dmg["hull_damage"]), mini(loser0_hp, diff - int(dmg["shield_damage"])),
				"hull = max(0, diff - shield), capped by hp")
		assert_eq(int(dmg["shield_left"]), loser0_shield - int(dmg["shield_damage"]), "shield left")
		assert_eq(int(dmg["hp_left"]), loser0_hp - int(dmg["hull_damage"]), "hp left")
		assert_eq(int(post_loser["hp"]), int(dmg["hp_left"]), "hp stored on the loser")
		assert_eq(int(post_loser["shield"]), int(dmg["shield_left"]), "shield stored on the loser")
		if int(dmg["hp_left"]) <= 0:
			assert_eq(String(ev[7]["type"]), "ShipDestroyed", "ShipDestroyed at hp<=0")
			assert_eq(String(ev[7]["ship_instance_id"]), loser_id, "destroyed id")
			assert_eq(bool(post_loser["alive"]), false, "loser is dead")
		else:
			assert_eq(bool(post_loser["alive"]), true, "survivor stays alive")

	section("destruction across fixed seeds (hp tuned directly by the test)")
	var destroyed_seen := false
	var exercised := 0
	for seed_value in range(1, 41):
		var c := MatchEngine.create_match({"seed": seed_value})
		var st: Dictionary = c["state"]
		# Plain ships only: special destruction rules (transform/revive) are
		# covered in test_engine_specials.gd, this loop pins the base pipeline.
		var atk: Dictionary = _plain_ship(st, "A1")
		var dfn: Dictionary = _plain_ship(st, "B1")
		if atk.is_empty() or dfn.is_empty():
			continue
		exercised += 1
		atk["hp"] = 20 # attacker cannot die within one exchange (max diff 13:
		# 2d6+3 front arc vs d6+1+0 back arc, ADR-014)
		dfn["hp"] = 1
		dfn["shield"] = 0
		var attack := _run_attack(st, atk, dfn)
		assert_true(bool(attack.get("ok", false)), "tuned attack accepted, seed %d" % seed_value)
		if not bool(attack.get("ok", false)):
			continue
		var defender_after := _by_id(attack["state"], String(dfn["id"]))
		var attacker_after := _by_id(attack["state"], String(atk["id"]))
		var destroyed := false
		var defender_was_hit := false
		for e: Dictionary in attack["events"]:
			if String(e["type"]) == "ShipDestroyed":
				destroyed = true
				assert_eq(String(e["ship_instance_id"]), String(dfn["id"]),
						"destroyed event id, seed %d" % seed_value)
			if String(e["type"]) == "DamageApplied" and String(e["target_id"]) == String(dfn["id"]):
				defender_was_hit = true
		if destroyed:
			destroyed_seen = true
			assert_eq(bool(defender_after["alive"]), false, "destroyed ship is not alive")
			assert_eq(int(defender_after["hp"]), 0, "destroyed ship hp capped at 0")
			assert_eq(bool(attacker_after["alive"]), true, "attacker survives its win")
			assert_true(not MatchEngine.is_terminal(attack["state"]),
					"one destruction cannot end a 3v3 duel")
		else:
			# The tuned defender survives only on a tie or when the attacker
			# lost the exchange; hp=1 with shield=0 forbids partial damage.
			assert_eq(bool(defender_after["alive"]), true, "surviving defender is alive")
			assert_eq(int(defender_after["hp"]), 1, "surviving tuned defender keeps hp 1")
			assert_eq(defender_was_hit, false, "no unresolved damage to the defender")
	assert_between(exercised, 8, 40, "enough seeds exercised the plain pipeline")
	assert_true(destroyed_seen, "at least one seed destroyed the tuned ship")

	section("dead ship cannot be activated or attack")
	var created2 := MatchEngine.create_match({"seed": 3})
	var st2: Dictionary = created2["state"]
	var a := _seat_ships(st2, "A1")
	var b := _seat_ships(st2, "B1")
	a[0]["q"] = 0
	a[0]["r"] = 0
	b[0]["q"] = 0
	b[0]["r"] = -1
	var r1 := MatchEngine.apply_command(st2, {"type": "BeginActivation", "ship_instance_id": String(a[0]["id"])})
	assert_true(bool(r1.get("ok", false)), "begin activation")
	st2 = r1["state"]
	var r2 := MatchEngine.apply_command(st2, {"type": "DeclareAttack", "target_ship_instance_id": String(b[0]["id"])})
	assert_true(bool(r2.get("ok", false)), "attack accepted")
	st2 = r2["state"]
	_by_id(st2, String(b[0]["id"]))["alive"] = false # test forces the death
	# Close the attacker's activation; the turn passes to B1 (dead b[0] skipped,
	# its living squadmates remain), which is exactly b[0]'s seat.
	var r_end := MatchEngine.apply_command(st2, {"type": "EndActivation"})
	assert_true(bool(r_end.get("ok", false)), "attacker ends activation")
	st2 = r_end["state"]
	var r3 := MatchEngine.apply_command(st2,
			{"type": "BeginActivation", "ship_instance_id": String(b[0]["id"])})
	assert_true(not bool(r3.get("ok", false)), "dead ship cannot begin activation")
	assert_eq(String(r3.get("error", "")), "ship_dead", "ship_dead code")

	section("snapshot round-trip preserves combat state")
	var snap := MatchEngine.snapshot_bytes(st2)
	var restored := MatchEngine.restore_snapshot(snap)
	assert_eq(MatchEngine.state_hash(restored), MatchEngine.state_hash(st2), "restored hash matches")
	assert_eq(int(restored["rng_counter"]), int(st2["rng_counter"]), "rng counter survives")
	return finish()
