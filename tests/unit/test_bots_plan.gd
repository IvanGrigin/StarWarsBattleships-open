# Unit tests for src/bots/activation_plans.gd (E003, MASTER_PLAN §7.4):
# reachability at current charges, one micro-sequence per (cell, facing) pair,
# and full applicability of every plan through MatchEngine.apply_command.
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const ActivationPlans := preload("res://src/bots/activation_plans.gd")

const SEEDS: Array[int] = [42, 1, 7, 123, 2024]
const ROUND_LIMIT := 60


func _find_ship(state: Dictionary, instance_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("id", "")) == instance_id:
			return s
	return {}


func _pair_key(cell_v: Vector2i, facing: int) -> String:
	return "%d,%d,%d" % [cell_v.x, cell_v.y, facing]


func run() -> int:
	section("fresh match seed 42: plans for the first A1 ship")
	var created := MatchEngine.create_match({"seed": 42, "round_limit": ROUND_LIMIT})
	var state: Dictionary = created["state"]
	var hash_before := MatchEngine.state_hash(state)
	var plans: Array = ActivationPlans.enumerate_plans(state)
	assert_true(not plans.is_empty(), "plans are non-empty")
	assert_eq(MatchEngine.state_hash(state), hash_before, "enumerate_plans does not mutate state")
	var first_ship: Dictionary = state["ships"][0]
	assert_eq(String(first_ship["seat"]), "A1", "first ship belongs to seat A1")
	var pass_positions := {}
	var variants := {}
	var start_key := _pair_key(Vector2i(int(first_ship["q"]), int(first_ship["r"])),
			int(first_ship["facing"]))
	var start_covered := false
	for plan_v: Variant in plans:
		var plan: Dictionary = plan_v
		assert_eq(String(plan["ship_instance_id"]), String(first_ship["id"]),
				"plans target the first A1 ship")
		var commands: Array = plan["commands"]
		assert_true(commands.size() >= 2, "plan carries at least Begin + End")
		assert_eq(String(commands[0]["type"]), "BeginActivation", "plan starts with BeginActivation")
		assert_eq(String(commands[commands.size() - 1]["type"]), "EndActivation",
				"plan ends with EndActivation")
		var key := _pair_key(plan["final_cell"], int(plan["final_facing"]))
		var variant_key := key + "|" + String(plan["attack_target"])
		assert_true(not variants.has(variant_key), "plan variant unique: %s" % variant_key)
		variants[variant_key] = true
		if String(plan["attack_target"]).is_empty():
			assert_true(not pass_positions.has(key), "pass-plan (cell,facing) unique: %s" % key)
			pass_positions[key] = true
		if key == start_key:
			start_covered = true
	assert_true(start_covered, "start position is among the reachable pairs")
	var attack_variants := variants.size() - pass_positions.size()
	assert_true(attack_variants >= 0, "attack variants counted")
	# A fresh-match enemy is far away, so most positions are pass-only; the
	# command budget is 3 charges, so the reachable set is bounded but > 1.
	assert_true(pass_positions.size() > 1, "movement changes reachable positions")

	section("every plan applies from scratch and reaches its declared position (seeds %s)"
			% str(SEEDS))
	for seed_value: int in SEEDS:
		var created_seed := MatchEngine.create_match({"seed": seed_value, "round_limit": ROUND_LIMIT})
		var fresh_state: Dictionary = created_seed["state"]
		var plans_seed: Array = ActivationPlans.enumerate_plans(fresh_state)
		assert_true(not plans_seed.is_empty(), "seed %d: plans non-empty" % seed_value)
		for plan_v2: Variant in plans_seed:
			var plan2: Dictionary = plan_v2
			var cur: Dictionary = fresh_state
			var applied := true
			for cmd_v: Variant in plan2["commands"]:
				var res := MatchEngine.apply_command(cur, cmd_v)
				if not bool(res.get("ok", false)):
					applied = false
					assert_true(false, "seed %d: %s rejected: %s" % [seed_value,
							String(cmd_v.get("type", "")), String(res.get("error", ""))])
					break
				cur = res["state"]
			if applied:
				var ship := _find_ship(cur, String(plan2["ship_instance_id"]))
				assert_eq(Vector2i(int(ship["q"]), int(ship["r"])), plan2["final_cell"],
						"seed %d: plan reaches final_cell" % seed_value)
				assert_eq(int(ship["facing"]), int(plan2["final_facing"]),
						"seed %d: plan reaches final_facing" % seed_value)
				if not String(plan2["attack_target"]).is_empty():
					var attack_declared := false
					for cmd2_v: Variant in plan2["commands"]:
						if String(cmd2_v.get("type", "")) == "DeclareAttack":
							attack_declared = true
							assert_eq(String(cmd2_v["target_ship_instance_id"]),
									String(plan2["attack_target"]),
									"seed %d: attack target matches plan field" % seed_value)
					assert_true(attack_declared, "seed %d: attack plan declares its attack" % seed_value)

	section("explicit ship selection picks the requested ship")
	var ship_id := String(state["ships"][0]["id"])
	var explicit_plans: Array = ActivationPlans.enumerate_plans(state, ship_id)
	assert_true(not explicit_plans.is_empty(), "explicit plans non-empty")
	assert_eq(String(explicit_plans[0]["ship_instance_id"]), ship_id, "explicit plan ship id")

	section("continuation plans for an already active ship apply to the current state")
	var begin := MatchEngine.apply_command(state,
			{"type": "BeginActivation", "ship_instance_id": ship_id})
	assert_true(bool(begin.get("ok", false)), "BeginActivation accepted")
	var mid: Dictionary = begin["state"]
	var continuation: Array = ActivationPlans.enumerate_plans(mid)
	assert_true(not continuation.is_empty(), "continuation plans non-empty")
	for plan_v3: Variant in continuation:
		var plan3: Dictionary = plan_v3
		assert_ne(String(plan3["commands"][0]["type"]), "BeginActivation",
				"continuation plan must not re-begin")
		var cur3: Dictionary = mid
		var ok3 := true
		for cmd3_v: Variant in plan3["commands"]:
			var res3 := MatchEngine.apply_command(cur3, cmd3_v)
			if not bool(res3.get("ok", false)):
				ok3 = false
				assert_true(false, "continuation %s rejected: %s"
						% [String(cmd3_v.get("type", "")), String(res3.get("error", ""))])
				break
			cur3 = res3["state"]
		if ok3:
			var ship3 := _find_ship(cur3, String(plan3["ship_instance_id"]))
			assert_eq(Vector2i(int(ship3["q"]), int(ship3["r"])), plan3["final_cell"],
					"continuation reaches final_cell")
			assert_eq(int(ship3["facing"]), int(plan3["final_facing"]),
					"continuation reaches final_facing")

	section("no active ship anywhere -> empty plan list")
	var exhausted := {"phase": "activation", "active_seat": "A1", "active_ship": null,
			"ships": [], "round": 1}
	assert_eq(ActivationPlans.enumerate_plans(exhausted).is_empty(), true,
			"no ships -> no plans")
	var other_seat: Dictionary = MatchEngine.create_match({"seed": 5, "round_limit": ROUND_LIMIT})["state"]
	# Synthetic seat A1 owns no ships in this state (only foreign-seat ships):
	# enumeration must return nothing instead of picking a foreign ship.
	var foreign_ships: Array = []
	for s: Dictionary in other_seat["ships"]:
		if String(s["seat"]) != "A1":
			foreign_ships.append(s)
	assert_true(not foreign_ships.is_empty(), "foreign ships present in fixture")
	var synthetic := {"phase": "activation", "active_seat": "A1", "active_ship": null,
			"ships": foreign_ships}
	var b_only: Array = ActivationPlans.enumerate_plans(synthetic)
	assert_true(b_only.is_empty(), "seat A1 has no own ships -> no plans")

	return finish()
