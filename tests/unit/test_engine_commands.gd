# Engine tests: match creation, illegal commands, charges, movement, rotation,
# turn passing and input-state purity (core-api §5, §9).
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


func _apply(state: Dictionary, command: Dictionary) -> Dictionary:
	return MatchEngine.apply_command(state, command)


func _expect_error(state: Dictionary, command: Dictionary, code: String, msg: String) -> void:
	var res := _apply(state, command)
	assert_true(not bool(res.get("ok", true)), msg + " (rejected)")
	assert_eq(String(res.get("error", "")), code, msg + " (code)")


## Activates one throwaway ship per turn (any seat) until `target_round` has
## started and no ship is mid-activation. A round needs all living ships
## activated (ADR-015 duel: seats A1 and B1, 3 ships each): the turn keeps
## cycling A1->B1 while a seat still has idle ships, so after RoundStarted(N)
## the active seat is always A1 (first seat with ships).
func _advance_round(start_state: Dictionary, target_round: int) -> Dictionary:
	return _advance_round_events(start_state, target_round)["state"]


## Same round-cycling as _advance_round, but returns {"state", "events"} with
## the events of every apply merged — the end-of-round ChargesRefreshed batch
## and RoundStarted(n+1) live in the final apply's events (v3.5, ADR-018).
func _advance_round_events(start_state: Dictionary, target_round: int) -> Dictionary:
	var st := start_state
	var merged: Array = []
	var guard := 0
	while int(st["round"]) < target_round or st["active_ship"] != null:
		var res := {}
		if st["active_ship"] == null:
			var ship_id := ""
			for s: Dictionary in st["ships"]:
				if String(s["seat"]) == String(st["active_seat"]) and bool(s["alive"]) \
						and not bool(s["activated"]):
					ship_id = String(s["id"])
					break
			assert_true(ship_id != "", "advance_round: idle ship found for seat")
			res = _apply(st, {"type": "BeginActivation", "ship_instance_id": ship_id})
			assert_true(bool(res.get("ok", false)), "advance_round BeginActivation for %s" % ship_id)
		else:
			res = _apply(st, {"type": "EndActivation"})
			assert_true(bool(res.get("ok", false)), "advance_round EndActivation")
		st = res["state"]
		merged.append_array(res["events"])
		guard += 1
		if guard > 128:
			assert_true(false, "advance_round did not converge")
			break
	return {"state": st, "events": merged}


## The ChargesRefreshed event of `instance_id` inside a merged event list.
func _refresh_event_for(events: Array, instance_id: String) -> Dictionary:
	for e: Dictionary in events:
		if String(e.get("type", "")) == "ChargesRefreshed" \
				and String(e.get("ship_instance_id", "")) == instance_id:
			return e
	return {}


func run() -> int:
	var created := MatchEngine.create_match({"seed": 42})
	var state: Dictionary = created["state"]
	var events: Array = created["events"]

	section("create_match basics")
	assert_eq(String(events[0]["type"]), "MatchCreated", "first event is MatchCreated")
	assert_eq(String(events[0]["ruleset_id"]),
			String(CardStore.game_rules().get("ruleset_id", "v3")), "ruleset id")
	assert_ne(String(events[0]["ruleset_hash"]), "", "ruleset hash present")
	assert_eq(int(events[0]["seed"]), 42, "seed in MatchCreated")
	assert_eq(int(events[0]["round_limit"]), 60, "default round limit")
	assert_eq(state.ships.size(), 6, "6 ships drafted (2 seats x 3)")
	assert_eq(String(state["phase"]), "activation", "phase after setup")
	assert_eq(int(state["round"]), 1, "round 1")
	assert_eq(int(state["round_limit"]), 60, "round limit in state")
	assert_eq(state["seat_order"], ["A1", "B1"], "seat order from the scenario")
	assert_eq(state["teams"], {"A": ["A1"], "B": ["B1"]}, "teams from the scenario")
	assert_eq(String(state["active_seat"]), "A1", "A1 starts")
	assert_true(state["active_ship"] == null, "no active ship yet")
	assert_eq(int(state["rng_counter"]), 0, "no dice before combat")
	assert_eq(String(state["ruleset_id"]),
			String(CardStore.game_rules().get("ruleset_id", "v3")), "state ruleset id")
	assert_true(state["winner"] == null, "no winner yet")
	assert_true(MatchEngine.is_terminal(state) == false, "fresh match is not terminal")
	var last: Dictionary = events[events.size() - 1]
	assert_eq(String(last["type"]), "RoundStarted", "last setup event is RoundStarted")
	assert_eq(int(last["round"]), 1, "RoundStarted(1)")
	var drafted := 0
	var placed := 0
	for e: Dictionary in events:
		if String(e["type"]) == "ShipDrafted":
			drafted += 1
			assert_true(e.has("seat") and e.has("ship_instance_id") and e.has("ship_type_id") \
					and e.has("cost"), "ShipDrafted fields")
		if String(e["type"]) == "ShipPlaced":
			placed += 1
	assert_eq(drafted, 6, "6 ShipDrafted events")
	assert_eq(placed, 6, "6 ShipPlaced events")

	section("legal_actions: initial BeginActivation list")
	var legal := MatchEngine.legal_actions(state)
	assert_eq(legal.size(), 3, "three BeginActivation options for A1")
	for i in legal.size():
		assert_eq(String(legal[i]["type"]), "BeginActivation", "legal[%d] is BeginActivation" % i)

	var a1 := _seat_ships(state, "A1")
	var b1 := _seat_ships(state, "B1")
	assert_eq(a1.size(), 3, "A1 has 3 ships")
	assert_eq(b1.size(), 3, "B1 has 3 ships")

	section("illegal commands are rejected with pinned codes")
	_expect_error(state, {"type": "BeginActivation", "ship_instance_id": String(a1[0]["id"]), "seat": "B1"},
			"not_your_seat", "command from wrong seat")
	_expect_error(state, {"type": "BeginActivation", "ship_instance_id": String(b1[0]["id"])},
			"not_your_seat", "enemy ship begin")
	_expect_error(state, {"type": "BeginActivation", "ship_instance_id": "no_such_ship"},
			"unknown_ship", "unknown ship id")
	_expect_error(state, {"type": "Move", "dir": 0}, "not_active_ship", "move without activation")
	_expect_error(state, {"type": "EndActivation"}, "not_active_ship", "end without activation")
	_expect_error(state, {"type": "Warp"}, "unknown_command", "unknown command type")

	var res := _apply(state, {"type": "BeginActivation", "ship_instance_id": String(a1[0]["id"])})
	assert_true(bool(res.get("ok", false)), "BeginActivation A1 ship 0 accepted")
	assert_eq(String(res["events"][0]["type"]), "ActivationStarted", "ActivationStarted emitted")
	assert_eq(int(res["events"][0]["charges"]), 3, "ActivationStarted carries charges")
	state = res["state"]
	_expect_error(state, {"type": "BeginActivation", "ship_instance_id": String(a1[1]["id"])},
			"not_active_ship", "second begin while a ship is active")
	_expect_error(state, {"type": "EndActivation", "seat": "B1"}, "not_your_seat",
			"EndActivation from wrong seat")

	section("failed commands never mutate the input state")
	var hash_before := MatchEngine.state_hash(state)
	_expect_error(state, {"type": "Move", "dir": 0, "seat": "B2"}, "not_your_seat",
			"move issued for another seat")
	assert_eq(MatchEngine.state_hash(state), hash_before, "state untouched after failed command")
	# a1[0] sits at (0,3) facing 0; dir 0 steps onto (0,2), taken by a1[1].
	_expect_error(state, {"type": "Move", "dir": 0}, "occupied_cell", "move onto allied cell")
	assert_eq(MatchEngine.state_hash(state), hash_before, "state untouched after occupied_cell")

	section("legal_actions: Move{dir} per DIR_DELTAS order, only legal dirs")
	var legal_mid := MatchEngine.legal_actions(state)
	# From (0,3): dir 0 -> (0,2) and dir 1 -> (1,2) are occupied by allies,
	# dirs 2..4 leave the radius-3 board; only dir 5 -> (-1,3) is legal
	# (v3.4 omnidirectional movement, ADR-017).
	assert_eq(legal_mid.size(), 4, "Move{5}, RotateLeft, RotateRight, EndActivation")
	assert_eq(String(legal_mid[0]["type"]), "Move", "order: Move first")
	assert_eq(int(legal_mid[0]["dir"]), 5, "only dir 5 is legal at (0,3)")
	assert_eq(String(legal_mid[1]["type"]), "RotateLeft", "order: RotateLeft")
	assert_eq(String(legal_mid[2]["type"]), "RotateRight", "order: RotateRight")
	assert_eq(String(legal_mid[3]["type"]), "EndActivation", "order: EndActivation")

	section("EndActivation keeps charges (v3.5: no recovery) and passes the turn to B1")
	res = _apply(state, {"type": "EndActivation"})
	assert_true(bool(res.get("ok", false)), "EndActivation accepted")
	state = res["state"]
	var end_events: Array = res["events"]
	assert_eq(String(end_events[0]["type"]), "ActivationEnded", "ActivationEnded emitted")
	assert_eq(int(end_events[0]["charges"]), 3, "charges unchanged at end (no recovery)")
	var a0 := _by_id(state, String(a1[0]["id"]))
	assert_eq(int(a0["charges"]), 3, "no recovery on the ship")
	assert_eq(int(a0["spent_round"]), 0, "nothing spent this round")
	assert_eq(bool(a0["activated"]), true, "activated flag set")
	assert_true(state["active_ship"] == null, "activation cleared")
	assert_eq(String(state["active_seat"]), "B1", "turn passed to B1")

	section("movement spends a charge and emits ChargeSpent + ShipMoved with dir")
	state = _advance_round(state, 2)
	assert_eq(int(state["round"]), 2, "round 2 after all 6 ships activated")
	# v3.5 end-of-round rewrite of round 1: nobody spent a charge, so every
	# living ship was refilled to the full max_charges 5 with full=true.
	assert_eq(int(_by_id(state, String(a1[0]["id"]))["charges"]), 5,
			"full refresh after an unused round")
	assert_eq(int(_by_id(state, String(a1[0]["id"]))["spent_round"]), 0,
			"spent_round reset by RoundStarted")
	var a2 := _seat_ships(state, "A1")
	assert_eq(bool(a2[2]["activated"]), false, "flags reset on new round")
	res = _apply(state, {"type": "BeginActivation", "ship_instance_id": String(a2[2]["id"])})
	assert_true(bool(res.get("ok", false)), "begin A1 ship 2 at (1,2)")
	state = res["state"]
	_by_id(state, String(a2[2]["id"]))["charges"] = 5 # test pins charges for exact math
	# From (1,2): dir 0 -> (1,1) and dir 1 -> (2,1) are free; dirs 2..3 leave
	# the board (|s|=4); dir 4 -> (0,3) and dir 5 -> (0,2) are allied cells.
	var legal_move := MatchEngine.legal_actions(state)
	assert_eq(legal_move.size(), 5, "Move{0}, Move{1}, RotateLeft, RotateRight, EndActivation")
	assert_eq(String(legal_move[0]["type"]), "Move", "order: Move dir 0 first")
	assert_eq(int(legal_move[0]["dir"]), 0, "dirs follow DIR_DELTAS: 0 first")
	assert_eq(int(legal_move[1]["dir"]), 1, "dirs follow DIR_DELTAS: 1 second")
	assert_eq(String(legal_move[2]["type"]), "RotateLeft", "order: RotateLeft after moves")
	assert_eq(String(legal_move[3]["type"]), "RotateRight", "order: RotateRight")
	assert_eq(String(legal_move[4]["type"]), "EndActivation", "order: EndActivation")
	res = _apply(state, {"type": "Move", "dir": 0})
	assert_true(bool(res.get("ok", false)), "Move dir 0 accepted")
	var move_events: Array = res["events"]
	assert_eq(String(move_events[0]["type"]), "ChargeSpent", "ChargeSpent first")
	assert_eq(String(move_events[0]["reason"]), "move", "reason move")
	assert_eq(int(move_events[0]["charges_left"]), 4, "charges_left 4")
	assert_eq(String(move_events[1]["type"]), "ShipMoved", "ShipMoved second")
	assert_eq(int(move_events[1]["from_q"]), 1, "from_q")
	assert_eq(int(move_events[1]["from_r"]), 2, "from_r")
	assert_eq(int(move_events[1]["to_q"]), 1, "to_q")
	assert_eq(int(move_events[1]["to_r"]), 1, "to_r")
	assert_eq(int(move_events[1]["dir"]), 0, "ShipMoved carries dir")
	state = res["state"]
	var moved := _by_id(state, String(a2[2]["id"]))
	assert_eq(int(moved["q"]), 1, "ship moved to q=1")
	assert_eq(int(moved["r"]), 1, "ship moved to r=1")
	assert_eq(int(moved["charges"]), 4, "charge spent")
	assert_eq(int(moved["spent_round"]), 1, "move counts into spent_round")
	assert_eq(int(moved["facing"]), 0, "move does not change facing")

	section("v3.4: backward and sideways moves are legal and keep facing")
	# ADR-017: any of the six directions costs one charge; the course is a
	# combat-only property, so no move direction ever rotates the ship.
	res = _apply(state, {"type": "Move", "dir": 3})
	assert_true(bool(res.get("ok", false)), "backward Move dir 3 accepted (charges left)")
	state = res["state"]
	moved = _by_id(state, String(a2[2]["id"]))
	assert_eq(int(moved["q"]), 1, "backward move keeps q")
	assert_eq(int(moved["r"]), 2, "backward move returns to r=2")
	assert_eq(int(moved["charges"]), 3, "backward move spent a charge")
	assert_eq(int(moved["spent_round"]), 2, "every move adds to spent_round")
	assert_eq(int(moved["facing"]), 0, "backward move does not change facing")
	res = _apply(state, {"type": "Move", "dir": 1})
	assert_true(bool(res.get("ok", false)), "sideways Move dir 1 accepted")
	state = res["state"]
	moved = _by_id(state, String(a2[2]["id"]))
	assert_eq(int(moved["q"]), 2, "sideways move to q=2")
	assert_eq(int(moved["r"]), 1, "sideways move to r=1")
	assert_eq(int(moved["charges"]), 2, "sideways move spent a charge")
	assert_eq(int(moved["facing"]), 0, "sideways move does not change facing")

	section("rotation changes facing by +-60 and spends a charge")
	res = _apply(state, {"type": "RotateLeft"})
	assert_true(bool(res.get("ok", false)), "RotateLeft accepted")
	var rot_events: Array = res["events"]
	assert_eq(String(rot_events[0]["reason"]), "rotate", "ChargeSpent reason rotate")
	assert_eq(int(rot_events[0]["charges_left"]), 1, "charges_left after rotate")
	assert_eq(String(rot_events[1]["type"]), "ShipRotated", "ShipRotated emitted")
	assert_eq(int(rot_events[1]["from_facing"]), 0, "from_facing 0")
	assert_eq(int(rot_events[1]["to_facing"]), 5, "to_facing 5 (-60 deg)")
	state = res["state"]
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["facing"]), 5, "facing stored mod 6")
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["q"]), 2, "rotate keeps position")
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["r"]), 1, "rotate keeps position")
	res = _apply(state, {"type": "RotateRight"})
	assert_true(bool(res.get("ok", false)), "RotateRight accepted")
	state = res["state"]
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["facing"]), 0, "facing 5 -> 0 (+60 deg)")
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["charges"]), 0, "charges exhausted")
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["spent_round"]), 5,
			"moves and rotations all tallied")
	res = _apply(state, {"type": "EndActivation"})
	assert_true(bool(res.get("ok", false)), "EndActivation at 0 charges")
	state = res["state"]
	assert_eq(int(_by_id(state, String(a2[2]["id"]))["charges"]), 0,
			"0 charges stay 0 at end (no recovery)")
	assert_eq(String(state["active_seat"]), "B1", "turn passed on")

	section("out_of_board/occupied per direction, bad dir, then no_charges at zero")
	state = _advance_round(state, 3)
	assert_eq(int(state["round"]), 3, "round 3 reached")
	var a3 := _seat_ships(state, "A1")
	# a3[0] sits on the edge cell (0,3) facing 0 (v3.2 radius 3, ADR-015).
	# Two RotateRight aim it SE for the classic out-of-board case; then the
	# per-direction checks prove the Move errors do not depend on facing.
	res = _apply(state, {"type": "BeginActivation", "ship_instance_id": String(a3[0]["id"])})
	assert_true(bool(res.get("ok", false)), "begin edge ship")
	state = res["state"]
	_by_id(state, String(a3[0]["id"]))["charges"] = 3 # test pins charges for exact math
	res = _apply(state, {"type": "RotateRight"})
	assert_true(bool(res.get("ok", false)), "rotate right 1")
	state = res["state"]
	res = _apply(state, {"type": "RotateRight"})
	assert_true(bool(res.get("ok", false)), "rotate right 2")
	state = res["state"]
	assert_eq(int(_by_id(state, String(a3[0]["id"]))["charges"]), 1, "two rotations left one charge")
	# From (0,3): dirs 2 (SE), 3 (S), 4 (SW) leave the radius-3 board and dir 0
	# steps onto the allied cell (0,2); dir 1 -> (1,2) is free again (that ally
	# moved away in round 2). Errors are per direction and independent of facing.
	_expect_error(state, {"type": "Move", "dir": 2}, "out_of_board", "dir 2 leaves the board")
	_expect_error(state, {"type": "Move", "dir": 3}, "out_of_board", "dir 3 leaves the board")
	_expect_error(state, {"type": "Move", "dir": 4}, "out_of_board", "dir 4 leaves the board")
	_expect_error(state, {"type": "Move", "dir": 0}, "occupied_cell", "dir 0 onto allied cell")
	_expect_error(state, {"type": "Move", "dir": 6}, "bad_direction", "dir 6 outside 0..5")
	_expect_error(state, {"type": "Move", "dir": -1}, "bad_direction", "negative dir")
	var edge_legal := MatchEngine.legal_actions(state)
	var edge_dirs: Array = []
	for action_v: Variant in edge_legal:
		var action: Dictionary = action_v
		if String(action["type"]) == "Move":
			edge_dirs.append(int(action["dir"]))
	assert_eq(edge_dirs, [1, 5], "edge legal move dirs are 1 and 5, in DIR_DELTAS order")
	res = _apply(state, {"type": "Move", "dir": 5})
	assert_true(bool(res.get("ok", false)), "dir 5 to the free cell (-1,3) accepted")
	state = res["state"]
	assert_eq(int(_by_id(state, String(a3[0]["id"]))["charges"]), 0, "all charges spent")
	_expect_error(state, {"type": "Move", "dir": 5}, "no_charges", "move at 0 charges")
	_expect_error(state, {"type": "RotateLeft"}, "no_charges", "rotate at 0 charges")
	res = _apply(state, {"type": "EndActivation"})
	assert_true(bool(res.get("ok", false)), "EndActivation at 0 charges")
	state = res["state"]
	assert_eq(int(_by_id(state, String(a3[0]["id"]))["charges"]), 0,
			"0 charges stay 0 at end (no recovery)")
	assert_eq(int(_by_id(state, String(a3[0]["id"]))["spent_round"]), 3,
			"three spends tallied in round 3")

	section("attack validation: attack_used, bad_target, not_adjacent")
	var created2 := MatchEngine.create_match({"seed": 7})
	var st2: Dictionary = created2["state"]
	var a := _seat_ships(st2, "A1")
	var b := _seat_ships(st2, "B1")
	# Test-owned direct layout: attacker (0,0); enemies N, SE and far; ally NE.
	a[0]["q"] = 0
	a[0]["r"] = 0
	a[0]["facing"] = 0
	b[0]["q"] = 0
	b[0]["r"] = -1
	b[1]["q"] = 1
	b[1]["r"] = 0
	b[2]["q"] = 3
	b[2]["r"] = 0
	a[1]["q"] = 1
	a[1]["r"] = -1
	res = _apply(st2, {"type": "BeginActivation", "ship_instance_id": String(a[0]["id"])})
	assert_true(bool(res.get("ok", false)), "begin attacker")
	st2 = res["state"]
	_expect_error(st2, {"type": "DeclareAttack", "target_ship_instance_id": String(a[1]["id"])},
			"bad_target", "attack an ally")
	_expect_error(st2, {"type": "DeclareAttack", "target_ship_instance_id": String(b[2]["id"])},
			"not_adjacent", "attack a distant enemy")
	_by_id(st2, String(b[1]["id"]))["alive"] = false # mutate the current state copy
	_expect_error(st2, {"type": "DeclareAttack", "target_ship_instance_id": String(b[1]["id"])},
			"bad_target", "attack a destroyed ship")
	_by_id(st2, String(b[1]["id"]))["alive"] = true
	res = _apply(st2, {"type": "DeclareAttack", "target_ship_instance_id": String(b[0]["id"])})
	assert_true(bool(res.get("ok", false)), "legal attack accepted")
	var atk_events: Array = res["events"]
	assert_eq(String(atk_events[0]["type"]), "AttackDeclared", "AttackDeclared emitted")
	assert_eq(String(atk_events[0]["attacker_id"]), String(a[0]["id"]), "attacker id")
	assert_eq(String(atk_events[0]["target_id"]), String(b[0]["id"]), "target id")
	st2 = res["state"]
	assert_eq(int(_by_id(st2, String(a[0]["id"]))["charges"]), 3, "attack costs no charges")
	_expect_error(st2, {"type": "DeclareAttack", "target_ship_instance_id": String(b[1]["id"])},
			"attack_used", "second attack in one activation")

	section("wrong_phase after the match is over")
	st2["phase"] = "ended"
	_expect_error(st2, {"type": "EndActivation"}, "wrong_phase", "command after match end")
	_expect_error(st2, {"type": "BeginActivation", "ship_instance_id": String(a[1]["id"])},
			"wrong_phase", "begin after match end")

	section("already_activated / ship_dead within the same round")
	var created3 := MatchEngine.create_match({"seed": 11})
	var st3: Dictionary = created3["state"]
	var a4 := _seat_ships(st3, "A1")
	a4[0]["activated"] = true
	_expect_error(st3, {"type": "BeginActivation", "ship_instance_id": String(a4[0]["id"])},
			"already_activated", "activate twice in a round")
	a4[0]["alive"] = false
	_expect_error(st3, {"type": "BeginActivation", "ship_instance_id": String(a4[0]["id"])},
			"ship_dead", "activate a destroyed ship")

	section("purity: successful apply keeps the input dictionary intact")
	var created4 := MatchEngine.create_match({"seed": 5})
	var st4: Dictionary = created4["state"]
	var a5 := _seat_ships(st4, "A1")
	var hash0 := MatchEngine.state_hash(st4)
	var canonical0 := MatchEngine.snapshot_bytes(st4)
	res = _apply(st4, {"type": "BeginActivation", "ship_instance_id": String(a5[0]["id"])})
	assert_true(bool(res.get("ok", false)), "successful begin")
	assert_eq(MatchEngine.state_hash(st4), hash0, "input state hash unchanged after success")
	assert_eq(MatchEngine.snapshot_bytes(st4), canonical0, "input state bytes unchanged after success")
	assert_ne(MatchEngine.state_hash(res["state"]), hash0, "result state differs")
	assert_eq(res["state"].ships.size(), 6, "result state has all ships")
	var res2 := _apply(res["state"], {"type": "EndActivation"})
	assert_true(bool(res2.get("ok", false)), "chained EndActivation works")
	assert_eq(String(res2["state"]["active_seat"]), "B1", "sequential applies chain correctly")

	# ------------------------------------------------------------- v3.5 refresh
	section("v3.5 round refresh: half for spenders, full for savers (a, b)")
	var created_r := MatchEngine.create_match({"seed": 42})
	var st_r: Dictionary = created_r["state"]
	var spender: Dictionary = _seat_ships(st_r, "A1")[0]
	var saver: Dictionary = _seat_ships(st_r, "A1")[1]
	var corpse: Dictionary = _seat_ships(st_r, "B1")[0]
	# Spender: begin, two rotations (2 of its 3 charges), end.
	var b_r := _apply(st_r, {"type": "BeginActivation", "ship_instance_id": String(spender["id"])})
	assert_true(bool(b_r.get("ok", false)), "spender begins")
	st_r = b_r["state"]
	_by_id(st_r, String(spender["id"]))["charges"] = 3 # test pins charges for exact math
	var rot1 := _apply(st_r, {"type": "RotateLeft"})
	assert_true(bool(rot1.get("ok", false)), "spender rotate 1")
	st_r = rot1["state"]
	var rot2 := _apply(st_r, {"type": "RotateLeft"})
	assert_true(bool(rot2.get("ok", false)), "spender rotate 2")
	st_r = rot2["state"]
	var end_r := _apply(st_r, {"type": "EndActivation"})
	assert_true(bool(end_r.get("ok", false)), "spender ends at 1 charge")
	st_r = end_r["state"]
	assert_eq(int(_by_id(st_r, String(spender["id"]))["charges"]), 1, "2 of 3 charges spent")
	var round_fin := _advance_round_events(st_r, 2)
	st_r = round_fin["state"]
	var refresh_events: Array = []
	for e: Dictionary in round_fin["events"]:
		if String(e["type"]) == "ChargesRefreshed":
			refresh_events.append(e)
	assert_eq(String(round_fin["events"][round_fin["events"].size() - 1]["type"]),
			"RoundStarted", "refresh batch precedes RoundStarted(2)")
	assert_eq(refresh_events.size(), 6, "one ChargesRefreshed per living ship (6 alive)")
	# (a) the spender is overwritten with ceil(5/2)=3, full=false.
	var spent_ev := _refresh_event_for(refresh_events, String(spender["id"]))
	assert_eq(int(spent_ev["charges"]), 3, "spender refreshed to ceil(5/2)=3")
	assert_eq(bool(spent_ev["full"]), false, "spender event full=false")
	assert_eq(int(_by_id(st_r, String(spender["id"]))["charges"]), 3, "ship stores 3 charges")
	# (b) the saver is overwritten with the full 5, full=true.
	var saved_ev := _refresh_event_for(refresh_events, String(saver["id"]))
	assert_eq(int(saved_ev["charges"]), 5, "saver refreshed to the full 5")
	assert_eq(bool(saved_ev["full"]), true, "saver event full=true")
	assert_eq(int(_by_id(st_r, String(saver["id"]))["charges"]), 5, "ship stores 5 charges")
	# Event order follows the ships array order (ADR-018).
	var ev_order: Array = []
	for e: Dictionary in refresh_events:
		ev_order.append(String(e["ship_instance_id"]))
	var living_order: Array = []
	for s: Dictionary in st_r["ships"]:
		if bool(s["alive"]):
			living_order.append(String(s["id"]))
	assert_eq(ev_order, living_order, "refresh order follows the ships array")
	# The rewrite consumes no RNG: the dice log is untouched (empty here).
	assert_eq(int(st_r["rng_counter"]), 0, "no dice consumed by the rewrite")

	section("v3.5 round refresh: spent_round resets, dead ships untouched (c, d)")
	# (c) RoundStarted reset every ship's tally.
	var all_reset := true
	for s: Dictionary in st_r["ships"]:
		if int(s["spent_round"]) != 0:
			all_reset = false
	assert_true(all_reset, "spent_round is 0 for every ship in the new round")
	# (d) the destroyed ship gets no event and keeps its dying charges.
	var corpse_id := String(corpse["id"])
	_by_id(st_r, corpse_id)["alive"] = false # test-owned kill before the round plays out
	_by_id(st_r, corpse_id)["charges"] = 1
	_by_id(st_r, corpse_id)["spent_round"] = 2 # dying tally must not matter
	# The spender also burns one charge in round 2 so the half-path is
	# exercised again alongside the dead-ship pass.
	var b_d2 := _apply(st_r, {"type": "BeginActivation", "ship_instance_id": String(spender["id"])})
	assert_true(bool(b_d2.get("ok", false)), "spender begins round 2")
	st_r = b_d2["state"]
	var rot_d := _apply(st_r, {"type": "RotateLeft"})
	assert_true(bool(rot_d.get("ok", false)), "spender rotates in round 2")
	st_r = rot_d["state"]
	var end_d2 := _apply(st_r, {"type": "EndActivation"})
	assert_true(bool(end_d2.get("ok", false)), "spender ends round 2")
	st_r = end_d2["state"]
	var fin_d := _advance_round_events(st_r, 3)
	st_r = fin_d["state"]
	for e: Dictionary in fin_d["events"]:
		if String(e["type"]) == "ChargesRefreshed":
			assert_ne(String(e["ship_instance_id"]), corpse_id, "dead ship is never refreshed")
	assert_eq(int(_by_id(st_r, corpse_id)["charges"]), 1, "dead ship keeps its charges")
	assert_eq(int(_by_id(st_r, corpse_id)["spent_round"]), 0,
			"RoundStarted resets the tally of every ship, dead included")
	assert_eq(bool(_by_id(st_r, corpse_id)["alive"]), false, "corpse stays dead")
	# And the round-2 spender (one rotation) is back to half again.
	assert_eq(int(_refresh_event_for(fin_d["events"], String(spender["id"]))["charges"]), 3,
			"round-2 spender refreshed to 3 again")

	section("v3.5: ceil formula for a nonstandard card maximum (e, test-owned tuning)")
	var created_c := MatchEngine.create_match({"seed": 13})
	var st_c: Dictionary = created_c["state"]
	var tuned: Dictionary = _seat_ships(st_c, "A1")[0]
	var idle_c: Dictionary = _seat_ships(st_c, "A1")[1]
	var cards_ref: Dictionary = CardStore.ships_ref()
	var card: Dictionary = cards_ref[String(tuned["type_id"])]
	var saved_max := int(card["max_charges"])
	card["max_charges"] = 4 # direct tuning; restored below, data files untouched
	idle_c["type_id"] = String(tuned["type_id"]) # state tuning: same card for the saver
	var b_c := _apply(st_c, {"type": "BeginActivation", "ship_instance_id": String(tuned["id"])})
	assert_true(bool(b_c.get("ok", false)), "tuned ship begins")
	st_c = b_c["state"]
	var rot_c := _apply(st_c, {"type": "RotateLeft"})
	assert_true(bool(rot_c.get("ok", false)), "tuned ship spends one charge")
	st_c = rot_c["state"]
	var end_c := _apply(st_c, {"type": "EndActivation"})
	assert_true(bool(end_c.get("ok", false)), "tuned ship ends")
	st_c = end_c["state"]
	var fin_c := _advance_round_events(st_c, 2)
	card["max_charges"] = saved_max # restore the card store before asserting
	var tuned_ev := _refresh_event_for(fin_c["events"], String(tuned["id"]))
	var idle_ev := _refresh_event_for(fin_c["events"], String(idle_c["id"]))
	assert_eq(int(tuned_ev["charges"]), 2, "spender: ceil(4/2)=2")
	assert_eq(bool(tuned_ev["full"]), false, "spender event full=false")
	assert_eq(int(idle_ev["charges"]), 4, "saver: full 4 from the tuned card")
	assert_eq(bool(idle_ev["full"]), true, "saver event full=true")

	section("v3.5: EndActivation of a dying attacker adds no charge either")
	# An attacker killed by its own attack (mine chain) can only pass the turn;
	# whatever the path, a dead ship never gains charges.
	var created_d := MatchEngine.create_match({"seed": 42})
	var st_d: Dictionary = created_d["state"]
	var d0: Dictionary = _seat_ships(st_d, "A1")[0]
	var b_d := _apply(st_d, {"type": "BeginActivation", "ship_instance_id": String(d0["id"])})
	assert_true(bool(b_d.get("ok", false)), "doomed ship begins")
	st_d = b_d["state"]
	_by_id(st_d, String(d0["id"]))["alive"] = false # test-owned death mid-activation
	_by_id(st_d, String(d0["id"]))["charges"] = 0
	var end_d := _apply(st_d, {"type": "EndActivation"})
	assert_true(bool(end_d.get("ok", false)), "dead active ship passes the turn")
	assert_eq(int(_by_id(end_d["state"], String(d0["id"]))["charges"]), 0,
			"no recovery for a dead ship at EndActivation")

	return finish()
