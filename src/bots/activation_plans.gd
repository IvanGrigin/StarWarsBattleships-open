# Activation plan generator (MASTER_PLAN §7.4, E003): enumerates every reachable
# (cell, facing) pair for one ship at its current charges and completes each
# position with EndActivation or with DeclareAttack on each adjacent enemy.
# Static helpers only: no RNG consumption, no floats, deterministic order
# (core-api §0). Rules are mirrored from match_engine.gd: a Move to any of the
# six neighbors or a 60-degree rotation costs 1 charge (v3.4, ADR-017); the
# destination cell must be on the board and free of LIVING ships (destroyed
# ships do not block).
extends RefCounted

const HexMath := preload("res://src/core/hex/hex_math.gd")
const CardStore := preload("res://src/core/data/card_store.gd")

## Board radius from data — the same source match_engine applies to its
## in_board checks (ADR-015), so plans never leave the actual board.
static func _board_radius() -> int:
	return maxi(1, int(CardStore.board().get("radius", 4)))

## Plans for the ship to act. Two modes:
## - state.active_ship == null: full plans for the first living, not-yet
##   activated ship of the active seat (or `ship_instance_id` if given). Every
##   command list starts with BeginActivation, so each plan applies to the
##   passed state from scratch via MatchEngine.apply_command without rejects.
## - state.active_ship set: continuation plans for that ship; commands apply to
##   the passed state as-is (no BeginActivation inside).
## Plan: {ship_instance_id: String, commands: Array[Dictionary],
## final_cell: Vector2i, final_facing: int, attack_target: String} where
## attack_target "" means a passing plan. The last command is always
## EndActivation; attack variants carry DeclareAttack right before it.
static func enumerate_plans(state: Dictionary, ship_instance_id: String = "") -> Array:
	var ship := _target_ship(state, ship_instance_id)
	if ship.is_empty() or not bool(ship.get("alive", false)):
		return []
	var ship_id := String(ship["id"])
	var head: Array = []
	if state.get("active_ship") == null:
		head.append({"type": "BeginActivation", "ship_instance_id": ship_id})
	var blocked := _blocked_cells(state, ship_id)
	var positions := _reachable_positions(ship, blocked)
	var plans: Array = []
	for pos: Dictionary in positions:
		var cell: Vector2i = pos["cell"]
		var facing := int(pos["facing"])
		var prefix: Array = head.duplicate()
		prefix.append_array(pos["commands"])
		var pass_commands: Array = prefix.duplicate()
		pass_commands.append({"type": "EndActivation"})
		plans.append(_make_plan(ship_id, pass_commands, cell, facing, ""))
		if bool(ship.get("attack_used", false)):
			continue
		var team := String(ship.get("team", ""))
		for target_id: String in _adjacent_enemies(state, cell, team):
			var attack_commands: Array = prefix.duplicate()
			attack_commands.append({"type": "DeclareAttack", "target_ship_instance_id": target_id})
			attack_commands.append({"type": "EndActivation"})
			plans.append(_make_plan(ship_id, attack_commands, cell, facing, target_id))
	return plans


## BFS over (cell, facing) with a visited set: the FIRST path found to a pair is
## the shortest in command count, later paths are skipped. This removes rotate
## cycles and duplicate routes (one pair = one micro-sequence). Expansion order
## at every node: Move dir 0..5 (DIR_DELTAS order, mirroring legal_actions),
## then RotateLeft, RotateRight; each costs one charge (v3.4, ADR-017).
static func _reachable_positions(ship: Dictionary, blocked: Dictionary) -> Array:
	var start := {
		"cell": Vector2i(int(ship["q"]), int(ship["r"])),
		"facing": int(ship["facing"]),
		"commands": [] as Array,
	}
	var visited := {_pair_key(start["cell"], int(ship["facing"])): true}
	var queue: Array = [start]
	var out: Array = []
	var charges := int(ship["charges"])
	while not queue.is_empty():
		var node: Dictionary = queue.pop_front()
		out.append(node)
		var spent: int = (node["commands"] as Array).size()
		if spent >= charges:
			continue
		var cell: Vector2i = node["cell"]
		var facing := int(node["facing"])
		var base: Array = node["commands"]
		for dir in 6:
			var to_cell := HexMath.step(cell, dir)
			if HexMath.in_board(to_cell, _board_radius()) and not blocked.has(_cell_key(to_cell)):
				_push(queue, visited, to_cell, facing, _child(base, {"type": "Move", "dir": dir}))
		_push(queue, visited, cell, HexMath.rotate(facing, -1),
				_child(base, {"type": "RotateLeft"}))
		_push(queue, visited, cell, HexMath.rotate(facing, 1),
				_child(base, {"type": "RotateRight"}))
	return out


static func _push(queue: Array, visited: Dictionary, cell: Vector2i, facing: int,
		commands: Array) -> void:
	var key := _pair_key(cell, facing)
	if visited.has(key):
		return
	visited[key] = true
	queue.append({"cell": cell, "facing": facing, "commands": commands})


static func _child(base: Array, command: Dictionary) -> Array:
	var out: Array = base.duplicate()
	out.append(command)
	return out


static func _pair_key(cell: Vector2i, facing: int) -> String:
	return "%d,%d,%d" % [cell.x, cell.y, facing]


static func _cell_key(cell: Vector2i) -> String:
	return "%d,%d" % [cell.x, cell.y]


## Cells occupied by LIVING ships other than the acting one (the acting ship
## itself never blocks its own path because it is the only mover).
static func _blocked_cells(state: Dictionary, except_id: String) -> Dictionary:
	var out := {}
	for s: Dictionary in state.get("ships", []):
		if not bool(s.get("alive", false)) or String(s.get("id", "")) == except_id:
			continue
		out[_cell_key(Vector2i(int(s["q"]), int(s["r"])))] = true
	return out


## Adjacent living enemy ship ids in HexMath.neighbors order (DIR_DELTAS).
static func _adjacent_enemies(state: Dictionary, cell: Vector2i, team: String) -> Array:
	var out: Array = []
	for n: Vector2i in HexMath.neighbors(cell):
		var occ := _alive_ship_at(state, n)
		if not occ.is_empty() and String(occ.get("team", "")) != team:
			out.append(String(occ["id"]))
	return out


static func _alive_ship_at(state: Dictionary, cell: Vector2i) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if bool(s.get("alive", false)) and int(s.get("q", 0)) == cell.x \
				and int(s.get("r", 0)) == cell.y:
			return s
	return {}


## The ship whose activation is enumerated. If an activation is running, it is
## the active ship (a mismatching explicit id is a caller error -> {}).
## Otherwise the first living unactivated ship of the active seat, in ships
## array order — the same order legal_actions offers BeginActivation.
static func _target_ship(state: Dictionary, ship_instance_id: String) -> Dictionary:
	var active: Variant = state.get("active_ship")
	if active != null:
		if not ship_instance_id.is_empty() and ship_instance_id != String(active):
			return {}
		return _find_ship(state, String(active))
	var seat := String(state.get("active_seat", ""))
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) != seat or not bool(s.get("alive", false)) \
				or bool(s.get("activated", false)):
			continue
		if ship_instance_id.is_empty() or ship_instance_id == String(s["id"]):
			return s
	return {}


static func _find_ship(state: Dictionary, instance_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("id", "")) == instance_id:
			return s
	return {}


static func _make_plan(ship_id: String, commands: Array, cell: Vector2i, facing: int,
		attack_target: String) -> Dictionary:
	return {
		"ship_instance_id": ship_id,
		"commands": commands,
		"final_cell": cell,
		"final_facing": facing,
		"attack_target": attack_target,
	}
