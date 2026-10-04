# Engine tests: deterministic draft, fleet constraints, scenario placement,
# seed determinism (core-api §4.1, §8; ADR-015: 2-seat duel, seat composition
# from the scenario).
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const CardStore := preload("res://src/core/data/card_store.gd")
const HexMath := preload("res://src/core/hex/hex_math.gd")

# Scenario composition under test (classic_2v2 v3.2, ADR-015).
const SEATS: Array[String] = ["A1", "B1"]


func _seat_ships(state: Dictionary, seat: String) -> Array:
	var out: Array = []
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) == seat:
			out.append(s)
	return out


func run() -> int:
	var cards := CardStore.ships()
	var scenario := CardStore.scenario("classic_2v2")
	var board := CardStore.board()

	section("card store sanity")
	assert_eq(cards.size(), 11, "11 ship cards loaded")
	assert_eq(CardStore.ship_ids_sorted().size(), 11, "11 sorted ids")
	var ids := CardStore.ship_ids_sorted()
	for i in range(1, ids.size()):
		assert_true(String(ids[i - 1]) < String(ids[i]), "ids sorted, %s < %s" % [ids[i - 1], ids[i]])
	assert_eq(int(CardStore.game_rules()["draft_budget"]), 17, "budget from game.json")
	assert_eq(String(CardStore.game_rules()["ruleset_id"]), "v3_5", "ruleset id v3_5 (ADR-018)")
	assert_eq(String(CardStore.game_rules().get("charge_round_reset", "")), "half_up",
			"charge_round_reset half_up (ADR-018)")
	assert_eq(bool(CardStore.game_rules().get("charge_full_if_unused", false)), true,
			"charge_full_if_unused flag (ADR-018)")
	assert_eq(bool(CardStore.game_rules().get("omnidirectional_movement", false)), true,
			"omnidirectional_movement flag (ADR-017)")
	assert_eq(int(board["radius"]), 3, "board radius 3 (ADR-015)")
	assert_eq(int(board["cell_count"]), 37, "board has 37 cells")

	section("scenario composition (ADR-015 duel)")
	assert_eq(scenario["seat_order"], ["A1", "B1"], "seat_order is A1, B1")
	assert_eq(scenario["teams"], {"A": ["A1"], "B": ["B1"]}, "teams A=[A1], B=[B1]")
	assert_eq(int(scenario["seats"]["A1"]["facing"]), 0, "A1 facing readable")
	assert_eq(int(scenario["seats"]["B1"]["facing"]), 3, "B1 facing readable")
	for seat: String in SEATS:
		assert_eq(scenario["seats"][seat]["cells"].size(), 3,
				"seat %s has 3 scenario cells" % seat)
		var cells: Array = scenario["seats"][seat]["cells"]
		for k in cells.size():
			var cell := Vector2i(int(cells[k][0]), int(cells[k][1]))
			assert_true(HexMath.in_board(cell, int(board["radius"])),
					"seat %s cell %d inside the radius-3 board" % [seat, k])
	assert_true(cards.has("phantom"), "phantom card exists but is not draftable")
	assert_eq(bool(cards["phantom"]["draftable"]), false, "phantom draftable=false")

	section("draft constraints and placement for fixed seeds")
	for seed_value: int in [1, 2, 3, 42, 777]:
		var created := MatchEngine.create_match({"seed": seed_value})
		var state: Dictionary = created["state"]
		assert_eq(state.ships.size(), 6, "seed %d: 6 ships" % seed_value)
		assert_eq(state["seat_order"], ["A1", "B1"], "seed %d: state seat_order" % seed_value)
		assert_eq(state["teams"], {"A": ["A1"], "B": ["B1"]}, "seed %d: state teams" % seed_value)
		assert_eq(String(state["active_seat"]), "A1", "seed %d: first seat_order seat starts" % seed_value)
		# Hero draft (ADR-016 §1): one distinct hero per seat with card uses.
		var hero_cards := CardStore.heroes()
		var heroes_state: Dictionary = state["heroes"]
		assert_eq(heroes_state.size(), 2, "seed %d: both seats drafted a hero" % seed_value)
		assert_ne(String(heroes_state["A1"]["hero_id"]), String(heroes_state["B1"]["hero_id"]),
				"seed %d: the two seats hold different heroes" % seed_value)
		for hero_seat: String in SEATS:
			var hero: Dictionary = heroes_state[hero_seat]
			assert_true(hero_cards.has(String(hero["hero_id"])),
					"seed %d: hero %s is from the 8-card pool" % [seed_value, hero["hero_id"]])
			var hero_card: Dictionary = hero_cards[String(hero["hero_id"])]
			var ability: Dictionary = hero_card.get("ability", {})
			assert_eq(int(hero["uses_left"]),
					int(ability.get("uses_per_match", hero_card.get("uses_per_match", 0))),
					"seed %d: uses_left from the hero card" % seed_value)
		var g2_seen := {}
		for seat: String in SEATS:
			var fleet := _seat_ships(state, seat)
			assert_eq(fleet.size(), 3, "seed %d seat %s: 3 ships" % [seed_value, seat])
			var cost_sum := 0
			var g2_count := 0
			var g1_counts := {}
			for k in fleet.size():
				var ship: Dictionary = fleet[k]
				var type_id := String(ship["type_id"])
				assert_ne(type_id, "phantom", "phantom never drafted")
				var def: Dictionary = cards[type_id]
				assert_eq(bool(def["draftable"]), true, "drafted ship is draftable")
				cost_sum += int(def["draft_cost"])
				# instance id = "{seat}_{type_id}_{k}"
				assert_eq(String(ship["id"]), "%s_%s_%d" % [seat, type_id, k],
						"instance id format, seat %s k=%d" % [seat, k])
				if int(def["group"]) == 2:
					g2_count += 1
					assert_true(not g2_seen.has(type_id),
							"group 2 type %s unique in match (seed %d)" % [type_id, seed_value])
					g2_seen[type_id] = seat
				else:
					g1_counts[type_id] = int(g1_counts.get(type_id, 0)) + 1
			assert_between(cost_sum, 0, 17, "seed %d seat %s: budget <= 17" % [seed_value, seat])
			assert_between(g2_count, 0, 1, "seed %d seat %s: <= 1 group 2" % [seed_value, seat])
			for type_id: String in g1_counts:
				assert_between(int(g1_counts[type_id]), 0, 2,
						"seed %d seat %s: <= 2 copies of %s" % [seed_value, seat, type_id])
			# placement: k-th draft of the seat takes the k-th scenario cell
			var seat_cfg: Dictionary = scenario["seats"][seat]
			var cells: Array = seat_cfg["cells"]
			var facing := int(seat_cfg["facing"])
			for k in fleet.size():
				var ship: Dictionary = fleet[k]
				var def: Dictionary = cards[String(ship["type_id"])]
				assert_eq(int(ship["q"]), int(cells[k][0]),
						"seed %d seat %s ship %d cell q" % [seed_value, seat, k])
				assert_eq(int(ship["r"]), int(cells[k][1]),
						"seed %d seat %s ship %d cell r" % [seed_value, seat, k])
				assert_eq(int(ship["facing"]), facing, "seat facing")
				assert_eq(int(ship["hp"]), int(def["max_hp"]), "hp from card")
				assert_eq(int(ship["shield"]), int(def["max_shield"]), "shield from card")
				assert_eq(int(ship["charges"]), int(def["initial_charges"]), "charges from card")
				assert_eq(int(ship["spent_round"]), 0, "spent_round starts 0 (ADR-018)")
				assert_eq(bool(ship["alive"]), true, "ship starts alive")
				assert_eq(bool(ship["activated"]), false, "ship starts unactivated")
				assert_eq(bool(ship["attack_used"]), false, "attack not used")
				# team membership comes from the scenario teams table
				var expected_team := ""
				for team_key: Variant in scenario["teams"]:
					if (scenario["teams"][team_key] as Array).has(seat):
						expected_team = String(team_key)
				assert_ne(expected_team, "", "seat %s listed in teams" % seat)
				assert_eq(String(ship["team"]), expected_team, "team from scenario teams")

		section("determinism: same seed -> identical match")
		var again := MatchEngine.create_match({"seed": seed_value})
		assert_eq(MatchEngine.state_hash(again["state"]), MatchEngine.state_hash(state),
				"seed %d: identical state hash" % seed_value)
		assert_eq(MatchEngine.snapshot_bytes(again["state"]), MatchEngine.snapshot_bytes(state),
				"seed %d: identical canonical bytes" % seed_value)

	section("event journal shape for seed 42")
	var evts: Array = MatchEngine.create_match({"seed": 42})["events"]
	assert_eq(String(evts[0]["type"]), "MatchCreated", "journal starts with MatchCreated")
	assert_eq(String(evts[1]["type"]), "ShipDrafted", "then ShipDrafted")
	assert_eq(String(evts[1]["seat"]), "A1", "A1 picks first")
	var drafted := 0
	var placed := 0
	var started := 0
	var hero_drafted := 0
	var first_hero_index := -1
	var last_ship_drafted_index := -1
	for i in evts.size():
		var e: Dictionary = evts[i]
		match String(e["type"]):
			"ShipDrafted":
				drafted += 1
				last_ship_drafted_index = i
			"HeroDrafted":
				hero_drafted += 1
				if first_hero_index < 0:
					first_hero_index = i
			"ShipPlaced":
				placed += 1
			"RoundStarted":
				started += 1
	assert_eq(drafted, 6, "6 ShipDrafted (2 seats x fleet_size 3)")
	assert_eq(placed, 6, "6 ShipPlaced")
	assert_eq(started, 1, "single RoundStarted(1)")
	# Hero draft (ADR-016 §1): one HeroDrafted per seat, after the fleet draft
	# and before the placements.
	assert_eq(hero_drafted, 2, "2 HeroDrafted (scenario seats)")
	assert_true(first_hero_index > last_ship_drafted_index,
			"HeroDrafted events follow the fleet draft")
	assert_eq(String(evts[evts.size() - 1]["type"]), "RoundStarted", "journal ends with RoundStarted")
	assert_eq(int(evts[evts.size() - 1]["round"]), 1, "round 1")

	section("different seeds produce different fleets (sanity)")
	var h1 := MatchEngine.state_hash(MatchEngine.create_match({"seed": 1})["state"])
	var h2 := MatchEngine.state_hash(MatchEngine.create_match({"seed": 2})["state"])
	assert_ne(h1, h2, "seeds 1 and 2 differ")

	return finish()
