# Pure functional match engine over the canonical state dictionary (core-api §7).
# All functions are static; apply_command never mutates its input state.
extends RefCounted

const HexMath := preload("res://src/core/hex/hex_math.gd")
const Rng := preload("res://src/core/rng/rng.gd")
const Canonical := preload("res://src/core/serialization/canonical.gd")
const CardStore := preload("res://src/core/data/card_store.gd")

## Fallback seat composition for the full 2x2 format (ADR-015). The source of
## truth for a match is the scenario: seat_order (turn order and draft) and
## teams (team membership and victory) travel in the state.
const SEAT_ORDER: Array[String] = ["A1", "B1", "A2", "B2"]
# v3 (ADR-016): state carries "heroes", "objects" (mines/bombs) and
# "pending_reaction" (reaction window) on top of the v2 scenario fields.
# v4 (ADR-018, energy v3.5): every ship carries "spent_round" (charges spent
# this round); EndActivation no longer restores a charge — charges are
# REWRITTEN once at the end of the round (full max_charges when nothing was
# spent, ceil(max_charges/2) otherwise) with one ChargesRefreshed event per
# living ship.
const STATE_VERSION := 4
const COMMAND_TYPES: Array[String] = [
	"BeginActivation",
	"Move",
	"RotateLeft",
	"RotateRight",
	"DeclareAttack",
	"EndActivation",
	"UseHeroAbility",
	"SkipReaction",
]

# Hero ability command ids (ADR-016 §3): the ability_id carried by the
# UseHeroAbility command for each hero. Active abilities (vader..boba) use the
# ADR ids; the reaction flips (luke/obi_wan) use the hero card ability ids from
# data/rulesets/v3/heroes/*.json. Phasma is passive — no command exists.
const HERO_ABILITY_IDS := {
	"darth_vader": "force_attack",
	"anakin": "force_push",
	"han_solo": "hyperjump",
	"jango_fett": "place_mine",
	"boba_fett": "place_bomb",
	"luke": "precise_shot",
	"obi_wan": "miss",
}
# Reaction window kinds (ADR-016 §3.5/§4): pending_reaction.kind per hero.
const HERO_WINDOW_KINDS := {"luke": "luke_flip", "obi_wan": "obi_wan_flip"}
# Boba's bomb drifts at most this many times (ADR-016 §3.7).
const BOMB_MAX_SHIFTS := 3

# apply_command is pure, yet combat dice must continue the match RNG stream.
# state["dice"] (ADR-012) records the sides of every consumed die in order, so
# (seed, dice log) fully determines the stream position: draft replay (a fixed
# number of next_below calls) plus one next_die per recorded side. Special
# rules (ADR-012) make the per-event die sizes non-uniform (d2, d4), hence the
# log instead of a bare counter. The cache keeps the most advanced stream per
# seed; any log mismatch or rewind rebuilds from the seed.
static var _rng_cache := {"seed": -1, "log": [], "rng": null}

# Special-rule ability ids (data: ships/*.json "abilities", enabled: true).
const ABILITY_TRANSFORM := "transform_to_phantom"
const ABILITY_RANGED_SHOT := "ranged_shot"
const ABILITY_LUCKY_SHOT := "lucky_shot"
const ABILITY_RESURRECTION := "resurrection"
const ABILITY_REROLL_ONE := "reroll_one"


## config: {seed: int, ruleset_dir: String = "res://data/rulesets/v3",
##          round_limit: int = 60, scenario: String = "classic_2v2"}
## Runs MatchCreated -> draft -> placement -> RoundStarted(1) internally.
static func create_match(config: Dictionary) -> Dictionary:
	var seed_value := int(config.get("seed", 0))
	var round_limit := int(config.get("round_limit", 60))
	var ruleset_dir := String(config.get("ruleset_dir", CardStore.DEFAULT_RULESET_DIR))
	var scenario_name := String(config.get("scenario", "classic_2v2"))
	var defs := CardStore.ships_ref(ruleset_dir)
	var game := CardStore.game_rules(ruleset_dir)
	var scenario := CardStore.scenario(scenario_name, ruleset_dir)
	if defs.is_empty() or game.is_empty() or scenario.is_empty():
		push_error("match_engine: ruleset data unavailable in %s" % ruleset_dir)
		return {"state": {}, "events": [], "error": "data_unavailable"}
	var ruleset_hash := CardStore.ruleset_hash(ruleset_dir)
	var events: Array = []
	# Seat composition and teams are scenario data (ADR-015): seat_order drives
	# the draft and the turn order, teams drives placement team and victory.
	var seats_cfg: Dictionary = scenario.get("seats", {})
	var seat_order: Array[String] = []
	for seat: Variant in scenario.get("seat_order", SEAT_ORDER):
		seat_order.append(String(seat))
	if seat_order.is_empty():
		seat_order = SEAT_ORDER.duplicate()
	var teams_cfg: Dictionary = scenario.get("teams", {})
	var seat_team := {}
	for team_key: Variant in teams_cfg:
		for seat: Variant in teams_cfg[team_key]:
			seat_team[String(seat)] = String(team_key)
	events.append({
		"type": "MatchCreated",
		"ruleset_id": String(game.get("ruleset_id", "v3")),
		"ruleset_hash": ruleset_hash,
		"seed": seed_value,
		"round_limit": round_limit,
	})
	var rng: Rng = Rng.new(seed_value)
	var picks := _run_draft(rng, defs, game, seat_order)
	if picks.is_empty():
		return {"state": {}, "events": events, "error": "draft_no_candidates"}
	# Hero draft (ADR-016 §1): after the fleet draft the same match RNG deals
	# one distinct hero per scenario seat, in seat_order (rng order matters;
	# the HeroDrafted events are appended below, after the fleet journal).
	var heroes := _run_hero_draft(rng, CardStore.heroes(), seat_order)
	var seat_picks := {}
	for pick: Dictionary in picks:
		var list: Array = seat_picks.get(pick["seat"], [])
		list.append(pick)
		seat_picks[pick["seat"]] = list
	for pick: Dictionary in picks:
		events.append({
			"type": "ShipDrafted",
			"seat": pick["seat"],
			"ship_instance_id": pick["ship_instance_id"],
			"ship_type_id": pick["ship_type_id"],
			"cost": pick["cost"],
		})
	for seat_v: Variant in seat_order:
		var hero_seat := String(seat_v)
		if heroes.has(hero_seat):
			events.append({"type": "HeroDrafted", "seat": hero_seat,
					"hero_id": String(heroes[hero_seat]["hero_id"])})
	var ships_out: Array = []
	for seat_v: Variant in seat_order:
		var seat := String(seat_v)
		var info: Dictionary = seats_cfg.get(seat, {})
		var cells: Array = info.get("cells", [])
		var facing := int(info.get("facing", 0))
		var seat_list: Array = seat_picks.get(seat, [])
		for k in seat_list.size():
			var pick: Dictionary = seat_list[k]
			var def: Dictionary = defs[pick["ship_type_id"]]
			var cell: Array = cells[k]
			var ship := {
				"id": pick["ship_instance_id"],
				"type_id": pick["ship_type_id"],
				"seat": seat,
				"team": String(seat_team.get(seat, seat.substr(0, 1))),
				"q": int(cell[0]),
				"r": int(cell[1]),
				"facing": facing,
				"hp": int(def.get("max_hp", 1)),
				"shield": int(def.get("max_shield", 0)),
				"charges": int(def.get("initial_charges", 3)),
				"spent_round": 0,
				"activated": false,
				"attack_used": false,
				"revive_used": false,
				"alive": true,
			}
			ships_out.append(ship)
			events.append({
				"type": "ShipPlaced",
				"ship_instance_id": ship["id"],
				"q": ship["q"],
				"r": ship["r"],
				"facing": facing,
				"hp": ship["hp"],
				"shield": ship["shield"],
				"charges": ship["charges"],
			})
	var state := {
		"version": STATE_VERSION,
		"ruleset_id": String(game.get("ruleset_id", "v3")),
		"ruleset_hash": ruleset_hash,
		"seed": seed_value,
		"phase": "activation",
		"round": 1,
		"round_limit": round_limit,
		"seat_order": seat_order,
		"teams": teams_cfg,
		"active_seat": seat_order[0],
		"active_ship": null,
		"rng_counter": 0,
		"dice": [],
		"winner": null,
		"ships": ships_out,
		"heroes": heroes,
		"objects": [],
		"pending_reaction": null,
		# Bot-parity pin (ADR-016 §7): when true, legal_actions hides hero
		# commands and reaction windows are auto-closed by the engine with a
		# ReactionSkipped event, so seeded-bot replays stay deterministic.
		"seeded_bots_skip_heroes": bool(config.get("seeded_bots_skip_heroes", true)),
	}
	events.append({"type": "RoundStarted", "round": 1})
	return {"state": state, "events": events}


## Legal commands right now, deterministic order (core-api §9). Commands carry
## no command_id/seat: the engine applies them on behalf of the active seat
## (or, in a reaction window, on behalf of the window owner). With
## seeded_bots_skip_heroes=true no hero command is ever offered and reaction
## windows never open in the state (ADR-016 §7).
static func legal_actions(state: Dictionary) -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	var pending_v: Variant = state.get("pending_reaction")
	if pending_v is Dictionary and not (pending_v as Dictionary).is_empty():
		var pending: Dictionary = pending_v
		var kind := String(pending["kind"])
		var window_hero := "luke" if kind == "luke_flip" else "obi_wan"
		var ability_id := String(HERO_ABILITY_IDS[window_hero])
		var faces: Array = pending.get("faces", [])
		for die_index in faces.size():
			var from_face := int(faces[die_index])
			for value in range(1, 7):
				if value == from_face or _flip_forbidden(kind, from_face, value):
					continue
				out.append({"type": "UseHeroAbility", "ability_id": ability_id,
						"die_index": die_index, "value": value})
		out.append({"type": "SkipReaction"})
		return out
	if String(state.get("phase", "")) != "activation":
		return out
	var active_seat := String(state.get("active_seat", ""))
	var active_ship: Variant = state.get("active_ship")
	if active_ship == null:
		for s: Dictionary in state.get("ships", []):
			if String(s.get("seat", "")) == active_seat \
					and bool(s.get("alive", false)) and not bool(s.get("activated", false)):
				out.append({"type": "BeginActivation", "ship_instance_id": String(s["id"])})
		return out
	var ship := _find_ship(state, String(active_ship))
	if ship.is_empty():
		return out
	if not bool(ship.get("alive", false)):
		# Attacker died from its own attack: only passing the turn remains.
		out.append({"type": "EndActivation"})
		return out
	var cell := Vector2i(int(ship.get("q", 0)), int(ship.get("r", 0)))
	if int(ship.get("charges", 0)) > 0:
		# v3.4 (ADR-017): Move steps to ANY neighboring hex for one charge.
		# One Move{dir} entry per legal direction, in DIR_DELTAS order 0..5;
		# a direction whose target is off the board or occupied is skipped.
		for dir in 6:
			var to_cell := HexMath.step(cell, dir)
			if HexMath.in_board(to_cell, _board_radius()) and _alive_ship_at(state, to_cell).is_empty():
				out.append({"type": "Move", "dir": dir})
		out.append({"type": "RotateLeft"})
		out.append({"type": "RotateRight"})
	if not bool(ship.get("attack_used", false)):
		var team := String(ship.get("team", ""))
		var defs := CardStore.ships_ref()
		if _has_ability(defs.get(String(ship["type_id"]), {}), ABILITY_RANGED_SHOT):
			# C008: the Death Star threatens every living enemy on the board;
			# targets follow the ships array order for determinism.
			for s: Dictionary in state.get("ships", []):
				if bool(s.get("alive", false)) and String(s.get("team", "")) != team:
					out.append({"type": "DeclareAttack", "target_ship_instance_id": String(s["id"])})
		else:
			for n: Vector2i in HexMath.neighbors(cell):
				var occ := _alive_ship_at(state, n)
				if not occ.is_empty() and String(occ.get("team", "")) != team:
					out.append({"type": "DeclareAttack", "target_ship_instance_id": String(occ["id"])})
	if not bool(state.get("seeded_bots_skip_heroes", true)):
		_append_hero_actions(out, state, ship)
	out.append({"type": "EndActivation"})
	return out


## Appends the legal UseHeroAbility commands of the active seat's hero
## (ADR-016 §2-§3): active abilities only, used inside the seat's own
## activation on the active ship. Deterministic order: ships array order,
## directions 0..5, board cells scanned q asc then r asc.
static func _append_hero_actions(out: Array[Dictionary], state: Dictionary,
		ship: Dictionary) -> void:
	var active_seat := String(state["active_seat"])
	var hero: Dictionary = state.get("heroes", {}).get(active_seat, {})
	if hero.is_empty() or int(hero.get("uses_left", 0)) <= 0:
		return
	var team := String(ship.get("team", ""))
	var cell := Vector2i(int(ship["q"]), int(ship["r"]))
	var radius := _board_radius()
	match String(hero.get("hero_id", "")):
		"darth_vader":
			if bool(ship.get("attack_used", false)):
				return
			for s: Dictionary in state.get("ships", []):
				if bool(s.get("alive", false)) and String(s.get("team", "")) != team \
						and HexMath.distance(cell, Vector2i(int(s["q"]), int(s["r"]))) == 2:
					out.append({"type": "UseHeroAbility", "ability_id": "force_attack",
							"target_ship_instance_id": String(s["id"])})
		"anakin":
			for s: Dictionary in state.get("ships", []):
				if not bool(s.get("alive", false)):
					continue
				var from_cell := Vector2i(int(s["q"]), int(s["r"]))
				for dir in 6:
					var to_cell := HexMath.step(from_cell, dir)
					if HexMath.in_board(to_cell, radius) and _alive_ship_at(state, to_cell).is_empty():
						out.append({"type": "UseHeroAbility", "ability_id": "force_push",
								"ship_instance_id": String(s["id"]), "dir": dir})
		"han_solo":
			if int(ship.get("charges", 0)) <= 0:
				return
			for q in range(-radius, radius + 1):
				for r in range(-radius, radius + 1):
					var to_cell := Vector2i(q, r)
					if not HexMath.in_board(to_cell, radius):
						continue
					if not _alive_ship_at(state, to_cell).is_empty():
						continue
					if _living_enemy_near(state, to_cell, team):
						continue
					out.append({"type": "UseHeroAbility", "ability_id": "hyperjump",
							"q": q, "r": r})
		"jango_fett":
			out.append({"type": "UseHeroAbility", "ability_id": "place_mine"})
		"boba_fett":
			for dir in 6:
				out.append({"type": "UseHeroAbility", "ability_id": "place_bomb", "dir": dir})


## Pure: returns {"ok": true, "events": [...], "state": <new snapshot>} or
## {"ok": false, "error": <code>, "detail": <text>} (core-api §5). A rejected
## command leaves the input state untouched.
static func apply_command(state: Dictionary, command: Dictionary) -> Dictionary:
	var cmd_type := String(command.get("type", ""))
	if not COMMAND_TYPES.has(cmd_type):
		return _reject("unknown_command", "unknown command type '%s'" % cmd_type)
	if String(state.get("phase", "")) == "reaction":
		# A reaction window is open (ADR-016 §3.5): exactly two commands from
		# the window owner are legal.
		if cmd_type == "UseHeroAbility" or cmd_type == "SkipReaction":
			return _apply_reaction(state, command)
		return _reject("wrong_phase", "reaction window '%s' is open for seat '%s'"
				% [String((state.get("pending_reaction", {}) as Dictionary).get("kind", "")),
				String((state.get("pending_reaction", {}) as Dictionary).get("seat", ""))])
	if String(state.get("phase", "")) != "activation":
		return _reject("wrong_phase", "match phase is '%s'" % String(state.get("phase", "")))
	if cmd_type == "UseHeroAbility":
		return _apply_hero_ability(state, command)
	if cmd_type == "SkipReaction":
		return _reject("wrong_phase", "no reaction window is open")
	if command.has("seat") and String(command["seat"]) != String(state.get("active_seat", "")):
		return _reject("not_your_seat", "command seat '%s' is not the active seat '%s'"
				% [String(command["seat"]), String(state.get("active_seat", ""))])
	var new_state := _copy_state(state)
	var events: Array = []
	if cmd_type == "BeginActivation":
		return _apply_begin(new_state, command, events)
	return _apply_active(new_state, cmd_type, command, events)


static func is_terminal(state: Dictionary) -> bool:
	return String(state.get("phase", "")) == "ended"


static func snapshot_bytes(state: Dictionary) -> String:
	return Canonical.to_canonical(state)


static func restore_snapshot(text: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		push_error("match_engine: restore_snapshot: input is not a JSON object")
		return {}
	var converted: Variant = CardStore.coerce_json(parsed)
	if not (converted is Dictionary):
		push_error("match_engine: restore_snapshot: converted value is not a Dictionary")
		return {}
	return converted


static func state_hash(state: Dictionary) -> String:
	return Canonical.state_hash(state)


## Plays commands from scratch; returns final {"state", "events"}. On the first
## rejected command stops and adds "replay_error": {index, error, detail}.
static func replay(config: Dictionary, commands: Array) -> Dictionary:
	var created := create_match(config)
	if created.has("error"):
		return created
	var state: Dictionary = created["state"]
	var events: Array = Array(created["events"])
	for i in commands.size():
		var res := apply_command(state, commands[i])
		if not bool(res.get("ok", false)):
			push_error("match_engine: replay command %d rejected: %s"
					% [i, String(res.get("error", ""))])
			return {
				"state": state,
				"events": events,
				"replay_error": {
					"index": i,
					"error": res.get("error", ""),
					"detail": res.get("detail", ""),
				},
			}
		state = res["state"]
		events.append_array(res["events"])
	return {"state": state, "events": events}


# --- BeginActivation ---------------------------------------------------------

static func _apply_begin(new_state: Dictionary, command: Dictionary, events: Array) -> Dictionary:
	if new_state.get("active_ship") != null:
		return _reject("not_active_ship", "ship '%s' is already active" % String(new_state["active_ship"]))
	var instance_id := String(command.get("ship_instance_id", ""))
	var ship := _find_ship(new_state, instance_id)
	if ship.is_empty():
		return _reject("unknown_ship", "no ship '%s'" % instance_id)
	if String(ship.get("seat", "")) != String(new_state.get("active_seat", "")):
		return _reject("not_your_seat", "ship '%s' belongs to seat '%s', active seat is '%s'"
				% [instance_id, String(ship.get("seat", "")), String(new_state.get("active_seat", ""))])
	if not bool(ship.get("alive", false)):
		return _reject("ship_dead", "ship '%s' is destroyed" % instance_id)
	if bool(ship.get("activated", false)):
		return _reject("already_activated", "ship '%s' already acted this round" % instance_id)
	new_state["active_ship"] = instance_id
	events.append({
		"type": "ActivationStarted",
		"seat": String(new_state["active_seat"]),
		"ship_instance_id": instance_id,
		"charges": int(ship["charges"]),
	})
	return _finish(new_state, events)


# --- Move / Rotate / DeclareAttack / EndActivation ---------------------------

static func _apply_active(new_state: Dictionary, cmd_type: String, command: Dictionary,
		events: Array) -> Dictionary:
	var active: Variant = new_state.get("active_ship")
	if active == null:
		return _reject("not_active_ship", "no ship is activated (BeginActivation first)")
	var ship := _find_ship(new_state, String(active))
	if ship.is_empty():
		return _reject("unknown_ship", "active ship '%s' not found" % String(active))
	if cmd_type != "EndActivation" and not bool(ship.get("alive", false)):
		return _reject("ship_dead", "active ship '%s' is destroyed" % String(active))

	if cmd_type == "Move":
		# v3.4 (ADR-017): one charge steps to any neighboring hex. Facing is
		# never touched by a move (course stays a combat-only property).
		var charges := int(ship["charges"])
		if charges <= 0:
			return _reject("no_charges", "ship '%s' has 0 charges" % String(active))
		var dir := int(command.get("dir", -1))
		if dir < 0 or dir > 5:
			return _reject("bad_direction", "dir %d outside 0..5" % dir)
		var from_cell := Vector2i(int(ship["q"]), int(ship["r"]))
		var to_cell := HexMath.step(from_cell, dir)
		if not HexMath.in_board(to_cell, _board_radius()):
			return _reject("out_of_board", "cell (%d,%d) is outside the board" % [to_cell.x, to_cell.y])
		if not _alive_ship_at(new_state, to_cell).is_empty():
			return _reject("occupied_cell", "cell (%d,%d) is occupied" % [to_cell.x, to_cell.y])
		ship["charges"] = charges - 1
		# v3.5 (ADR-018): every spent charge counts toward the round tally.
		ship["spent_round"] = int(ship.get("spent_round", 0)) + 1
		ship["q"] = to_cell.x
		ship["r"] = to_cell.y
		events.append({
			"type": "ChargeSpent",
			"ship_instance_id": String(active),
			"reason": "move",
			"charges_left": charges - 1,
		})
		events.append({
			"type": "ShipMoved",
			"ship_instance_id": String(active),
			"from_q": from_cell.x, "from_r": from_cell.y,
			"to_q": to_cell.x, "to_r": to_cell.y,
			"dir": dir,
		})
		_check_mines_after_move(new_state, ship, events)
	elif cmd_type == "RotateLeft" or cmd_type == "RotateRight":
		var charges := int(ship["charges"])
		if charges <= 0:
			return _reject("no_charges", "ship '%s' has 0 charges" % String(active))
		var steps := -1 if cmd_type == "RotateLeft" else 1
		var from_facing := int(ship["facing"])
		var to_facing := HexMath.rotate(from_facing, steps)
		ship["charges"] = charges - 1
		# v3.5 (ADR-018): every spent charge counts toward the round tally.
		ship["spent_round"] = int(ship.get("spent_round", 0)) + 1
		ship["facing"] = to_facing
		events.append({
			"type": "ChargeSpent",
			"ship_instance_id": String(active),
			"reason": "rotate",
			"charges_left": charges - 1,
		})
		events.append({
			"type": "ShipRotated",
			"ship_instance_id": String(active),
			"from_facing": from_facing,
			"to_facing": to_facing,
		})
	elif cmd_type == "DeclareAttack":
		var attack_error := _validate_attack(new_state, ship, command)
		if not attack_error.is_empty():
			return _reject(attack_error[0], attack_error[1])
		var target := _find_ship(new_state, String(command.get("target_ship_instance_id", "")))
		var att_def: Dictionary = CardStore.ships_ref().get(String(ship["type_id"]), {})
		var dist := HexMath.distance(Vector2i(int(ship["q"]), int(ship["r"])),
				Vector2i(int(target["q"]), int(target["r"])))
		var range_penalty := 2 * (dist - 1) if _has_ability(att_def, ABILITY_RANGED_SHOT) else 0
		ship["attack_used"] = true
		return _combat_from(new_state, ship, target, range_penalty, events)
	elif cmd_type == "EndActivation":
		# v3.5 (ADR-018): no charge recovery at the end of the activation any
		# more. Charges stay as they are until the end-of-round rewrite in
		# _pass_turn; ActivationEnded keeps reporting the actual count.
		ship["activated"] = true
		new_state["active_ship"] = null
		events.append({
			"type": "ActivationEnded",
			"ship_instance_id": String(active),
			"charges": int(ship["charges"]),
		})
		# Boba's bombs drift at the end of every activation of the owner seat,
		# including the activation that placed them (ADR-016 §3.7).
		_drift_bombs_of_seat(new_state, String(ship.get("seat", "")), events)
		_pass_turn(new_state, events)
	return _finish(new_state, events)


## Combat pipeline with special rules (ADR-012; v3.1 dice per ADR-014; hero
## reaction windows per ADR-016 §3.5). Dice order is part of the rules:
## 1) combat_attacker_dice x d6 for the attacker (each die its own DieRolled
## event), 2) vulture_droid reroll check — with reroll_one and at least one
## natural 1, one d2 gates a single reroll (C011), 3) reaction windows BEFORE
## the defender roll: first the attacker's luke window, then the defender's
## obi_wan window (each flips one attacker die, no rng consumption), 4)
## combat_defender_dice x d6 for the defender (+ flat bonus), 5) strengths and
## compare — on a tie an attacking xwing_t65 rolls d2 for 1 damage (C009),
## 6) on destruction: ghost transforms without a die (C007), tie_fighter rolls
## d2 then d4 for its single revive (C010). Every roll appends its sides to
## state["dice"] and bumps rng_counter. StrengthCalculated carries "die" = the
## side's face sum (compat), "dice" = the faces array and "flat_bonus" (the
## defender's combat_defender_flat_bonus; 1 for the attacker when the
## ATTACKER's seat hero is phasma, else 0 — ADR-016 §3.1).
## The pipeline splits in three: _validate_attack (pure checks), _combat_from
## (AttackDeclared + attacker dice + window opening, may pause the combat with
## a pending_reaction) and _combat_resolve (defender dice .. destruction).

## Validation for a regular DeclareAttack. Returns [] on success or
## [error_code, detail].
static func _validate_attack(new_state: Dictionary, ship: Dictionary,
		command: Dictionary) -> Array:
	var attacker_id := String(ship["id"])
	if bool(ship.get("attack_used", false)):
		return ["attack_used", "ship '%s' already attacked this activation" % attacker_id]
	var target_id := String(command.get("target_ship_instance_id", ""))
	var target := _find_ship(new_state, target_id)
	if target.is_empty():
		return ["unknown_ship", "no target ship '%s'" % target_id]
	var att_cell := Vector2i(int(ship["q"]), int(ship["r"]))
	var tgt_cell := Vector2i(int(target["q"]), int(target["r"]))
	var att_def: Dictionary = CardStore.ships_ref().get(String(ship["type_id"]), {})
	var ranged := _has_ability(att_def, ABILITY_RANGED_SHOT)
	var dist := HexMath.distance(att_cell, tgt_cell)
	if not ranged and dist != 1:
		return ["not_adjacent", "target '%s' is not on a neighboring cell" % target_id]
	if not bool(target.get("alive", false)):
		return ["bad_target", "target '%s' is destroyed" % target_id]
	if String(target.get("team", "")) == String(ship.get("team", "")):
		return ["bad_target", "target '%s' is an ally" % target_id]
	return []


## Starts a full combat of `attacker` against `target` with a fixed
## range_penalty (0 for a regular melee attack, 2*(dist-1) for the ranged
## shot, always 0 for vader's force_attack — ADR-016 §3.2). Emits
## AttackDeclared, rolls the attacker's dice (+vulture reroll), opens reaction
## windows (pausing the combat in a pending_reaction) or resolves to the end.
static func _combat_from(new_state: Dictionary, attacker: Dictionary, target: Dictionary,
		range_penalty: int, events: Array) -> Dictionary:
	events.append({"type": "AttackDeclared", "attacker_id": String(attacker["id"]),
			"target_id": String(target["id"])})
	var defs := CardStore.ships_ref()
	var game := CardStore.game_rules()
	var rng: Rng = _stream_rng(int(new_state["seed"]), new_state["dice"], defs, game,
			new_state.get("seat_order", SEAT_ORDER))
	# new_state is a deep copy: appending to its dice log never touches the input.
	var dice_log: Array = new_state["dice"]
	var rolled: Dictionary = _roll_attacker_dice(rng, attacker, int(new_state["rng_counter"]),
			dice_log, events)
	var faces: Array = rolled["faces"]
	new_state["rng_counter"] = int(rolled["roll_index"])
	new_state["dice"] = dice_log
	var paused := _open_reaction_windows(new_state, attacker, target, faces, range_penalty,
			events)
	# The cached Rng has advanced past every roll so far: sync the cache with
	# the dice log so a resume in a later apply_command reuses the position.
	_cache_rng_stream(dice_log)
	if paused:
		return _finish(new_state, events)
	_combat_resolve(new_state, attacker, target, faces, range_penalty, events)
	return _finish(new_state, events)


## Rolls the attacker's dice: combat_attacker_dice x d6, then the C011 vulture
## reroll check (single d2 gates one forced reroll of the first natural 1; the
## rerolled value is final even when it is a 1 again).
static func _roll_attacker_dice(rng: Rng, attacker: Dictionary, roll_index: int,
		dice_log: Array, events: Array) -> Dictionary:
	var game := CardStore.game_rules()
	var count := maxi(1, int(game.get("combat_attacker_dice", 2)))
	var faces: Array = []
	for i in count:
		faces.append(_roll(rng, 6, "attacker", roll_index, dice_log, events))
		roll_index += 1
	var att_def: Dictionary = CardStore.ships_ref().get(String(attacker["type_id"]), {})
	if _has_ability(att_def, ABILITY_REROLL_ONE) and faces.has(1):
		var reroll_luck := _roll(rng, 2, "attacker", roll_index, dice_log, events)
		roll_index += 1
		if reroll_luck == 2:
			faces[faces.find(1)] = _roll(rng, 6, "attacker", roll_index, dice_log, events)
			roll_index += 1
	return {"faces": faces, "roll_index": roll_index}


## Opens the reaction windows (ADR-016 §3.5): after the attacker's dice (and
## the vulture reroll), before the defender roll — first the attacker seat's
## luke window, then the defender seat's obi_wan window. In
## seeded_bots_skip_heroes mode every applicable window is announced and
## immediately closed with a ReactionSkipped event (no state pause). Returns
## true when a window was left open (state.phase = "reaction").
static func _open_reaction_windows(new_state: Dictionary, attacker: Dictionary,
		target: Dictionary, faces: Array, range_penalty: int, events: Array) -> bool:
	var after_kind := ""
	var window := _next_reaction_window(new_state, attacker, target, after_kind)
	while not window.is_empty():
		events.append({"type": "ReactionWindow", "seat": window["seat"], "kind": window["kind"]})
		if bool(new_state.get("seeded_bots_skip_heroes", true)):
			events.append({"type": "ReactionSkipped", "seat": window["seat"]})
			after_kind = String(window["kind"])
			window = _next_reaction_window(new_state, attacker, target, after_kind)
			continue
		new_state["pending_reaction"] = {
			"seat": window["seat"],
			"kind": window["kind"],
			"attacker_id": String(attacker["id"]),
			"target_id": String(target["id"]),
			"faces": faces.duplicate(),
			"range_penalty": range_penalty,
		}
		new_state["phase"] = "reaction"
		return true
	return false


## The next applicable reaction window after `after_kind` ("" = the first):
## luke for the attacker seat, then obi_wan for the defender seat.
static func _next_reaction_window(new_state: Dictionary, attacker: Dictionary,
		target: Dictionary, after_kind: String) -> Dictionary:
	var heroes: Dictionary = new_state.get("heroes", {})
	if after_kind.is_empty():
		var a_hero: Dictionary = heroes.get(String(attacker["seat"]), {})
		if String(a_hero.get("hero_id", "")) == "luke" and int(a_hero.get("uses_left", 0)) > 0:
			return {"seat": String(attacker["seat"]),
					"kind": String(HERO_WINDOW_KINDS["luke"])}
	if after_kind.is_empty() or after_kind == String(HERO_WINDOW_KINDS["luke"]):
		var d_hero: Dictionary = heroes.get(String(target["seat"]), {})
		if String(d_hero.get("hero_id", "")) == "obi_wan" and int(d_hero.get("uses_left", 0)) > 0:
			return {"seat": String(target["seat"]),
					"kind": String(HERO_WINDOW_KINDS["obi_wan"])}
	return {}


## True when the flip `from`->`to` is forbidden for the window kind
## (ADR-016 §3.5): luke must not turn a 1 into a 6, obi_wan must not turn a
## 6 into a 1.
static func _flip_forbidden(kind: String, from_face: int, to_face: int) -> bool:
	if kind == "luke_flip":
		return from_face == 1 and to_face == 6
	if kind == "obi_wan_flip":
		return from_face == 6 and to_face == 1
	return false


## Resolves the combat after the reaction windows are closed: defender dice,
## strengths (after every die, ADR-014 §3 item 5), compare, damage and
## destruction specials.
static func _combat_resolve(new_state: Dictionary, attacker: Dictionary, target: Dictionary,
		faces: Array, range_penalty: int, events: Array) -> void:
	var defs := CardStore.ships_ref()
	var game := CardStore.game_rules()
	var rng: Rng = _stream_rng(int(new_state["seed"]), new_state["dice"], defs, game,
			new_state.get("seat_order", SEAT_ORDER))
	var dice_log: Array = new_state["dice"]
	var roll_index := int(new_state["rng_counter"])
	var attacker_id := String(attacker["id"])
	var target_id := String(target["id"])

	# Defender dice (ADR-014 §3): rolled after the attacker's reroll check and
	# after every reaction window has closed.
	var defender_dice_count := maxi(1, int(game.get("combat_defender_dice", 1)))
	var flat_bonus := int(game.get("combat_defender_flat_bonus", 1))
	var faces_d: Array = []
	for i in defender_dice_count:
		faces_d.append(_roll(rng, 6, "defender", roll_index, dice_log, events))
		roll_index += 1

	# C008: sectors follow the ray on both sides; line of sight is never
	# blocked. Ships cannot move while a window is open, so the sectors match
	# the pre-window geometry.
	var att_cell := Vector2i(int(attacker["q"]), int(attacker["r"]))
	var tgt_cell := Vector2i(int(target["q"]), int(target["r"]))
	var att_def: Dictionary = defs.get(String(attacker["type_id"]), {})
	var def_def: Dictionary = defs.get(String(target["type_id"]), {})
	var sector_a := HexMath.sector_index(int(attacker["facing"]), _ray_direction(att_cell, tgt_cell))
	var arc_a := _arc(att_def, sector_a)
	var die_a := 0
	for face_a: int in faces:
		die_a += face_a
	var att_flat := 1 if _seat_hero_id(new_state, String(attacker["seat"])) == "phasma" else 0
	var total_a := maxi(0, maxi(0, die_a + arc_a) - range_penalty) + att_flat
	var sector_d := HexMath.sector_index(int(target["facing"]), _ray_direction(tgt_cell, att_cell))
	var arc_d := _arc(def_def, sector_d)
	var die_d := 0
	for face_d: int in faces_d:
		die_d += face_d
	var total_d := maxi(0, die_d + flat_bonus + arc_d)

	events.append({"type": "StrengthCalculated", "ship_instance_id": attacker_id, "die": die_a,
			"dice": faces, "sector_index": sector_a, "arc_bonus": arc_a, "total": total_a,
			"range_penalty": range_penalty, "flat_bonus": att_flat})
	events.append({"type": "StrengthCalculated", "ship_instance_id": target_id, "die": die_d,
			"dice": faces_d, "sector_index": sector_d, "arc_bonus": arc_d, "total": total_d,
			"range_penalty": 0, "flat_bonus": flat_bonus})

	new_state["rng_counter"] = roll_index
	new_state["dice"] = dice_log

	# Compare strengths; C009: attacking xwing_t65 on a tie rolls d2,
	# success (2) deals exactly 1 damage to the defender (shield first).
	var loser: Dictionary = {}
	var diff := 0
	if total_a == total_d:
		if _has_ability(att_def, ABILITY_LUCKY_SHOT):
			var tie_luck := _roll(rng, 2, "attacker", roll_index, dice_log, events)
			roll_index += 1
			new_state["rng_counter"] = roll_index
			new_state["dice"] = dice_log
			if tie_luck == 2:
				loser = target
				diff = 1
	else:
		loser = target if total_a > total_d else attacker
		diff = absi(total_a - total_d)

	# Damage and destruction specials.
	if not loser.is_empty():
		_apply_damage(loser, diff, events)
		if int(loser["hp"]) <= 0:
			var role := "attacker" if loser == attacker else "defender"
			_resolve_destruction(new_state, loser, role, rng, roll_index, events)
	_cache_rng_stream(dice_log)


## Reaction window command (ADR-016 §3.5): UseHeroAbility flip or SkipReaction
## from the window owner. A flip rewrites one attacker die face (no rng
## consumption — the DieFlipped event replaces the value of the last roll);
## afterwards the next window opens or the combat resolves.
static func _apply_reaction(state: Dictionary, command: Dictionary) -> Dictionary:
	var pending_v: Variant = state.get("pending_reaction")
	if not (pending_v is Dictionary) or (pending_v as Dictionary).is_empty():
		return _reject("wrong_phase", "no reaction window is open")
	var pending: Dictionary = pending_v
	var window_seat := String(pending["seat"])
	if command.has("seat") and String(command["seat"]) != window_seat:
		return _reject("not_your_seat", "command seat '%s' is not the window seat '%s'"
				% [String(command["seat"]), window_seat])
	var new_state := _copy_state(state)
	var events: Array = []
	var window: Dictionary = new_state["pending_reaction"]
	var kind := String(window["kind"])
	var window_hero := "luke" if kind == "luke_flip" else "obi_wan"
	if String(command.get("type", "")) == "SkipReaction":
		events.append({"type": "ReactionSkipped", "seat": window_seat})
	else:
		var expected_ability := String(HERO_ABILITY_IDS[window_hero])
		if String(command.get("ability_id", "")) != expected_ability:
			return _reject("not_your_hero", "window '%s' expects ability '%s'"
					% [kind, expected_ability])
		var hero: Dictionary = new_state.get("heroes", {}).get(window_seat, {})
		if hero.is_empty() or String(hero.get("hero_id", "")) != window_hero:
			return _reject("not_your_hero", "seat '%s' no longer owns hero '%s'"
					% [window_seat, window_hero])
		if int(hero.get("uses_left", 0)) <= 0:
			return _reject("hero_no_uses", "hero '%s' has no uses left" % window_hero)
		var faces: Array = window["faces"]
		var die_index := int(command.get("die_index", -1))
		if die_index < 0 or die_index >= faces.size():
			return _reject("bad_target", "die_index %d outside 0..%d" % [die_index, faces.size() - 1])
		var value := int(command.get("value", 0))
		if value < 1 or value > 6:
			return _reject("bad_target", "die face %d outside 1..6" % value)
		var from_face := int(faces[die_index])
		if value == from_face:
			return _reject("bad_target", "die %d already shows %d" % [die_index, from_face])
		if _flip_forbidden(kind, from_face, value):
			return _reject("bad_target", "flip %d->%d is forbidden for '%s'"
					% [from_face, value, window_hero])
		hero["uses_left"] = int(hero["uses_left"]) - 1
		events.append({"type": "AbilityUsed", "seat": window_seat, "hero_id": window_hero,
				"ability_id": expected_ability})
		faces[die_index] = value
		events.append({"type": "DieFlipped", "role": "attacker", "die_index": die_index,
				"from": from_face, "to": value, "by_hero": window_hero})
	# Close this window; open the next one (defender obi_wan after attacker
	# luke) or resolve the combat.
	var attacker := _find_ship(new_state, String(window["attacker_id"]))
	var target := _find_ship(new_state, String(window["target_id"]))
	var faces_now: Array = window["faces"]
	var range_penalty := int(window["range_penalty"])
	var next_window := _next_reaction_window(new_state, attacker, target, kind)
	if not next_window.is_empty():
		events.append({"type": "ReactionWindow", "seat": next_window["seat"],
				"kind": next_window["kind"]})
		new_state["pending_reaction"] = {
			"seat": next_window["seat"],
			"kind": next_window["kind"],
			"attacker_id": String(window["attacker_id"]),
			"target_id": String(window["target_id"]),
			"faces": faces_now,
			"range_penalty": range_penalty,
		}
		return {"ok": true, "events": events, "state": new_state}
	new_state["pending_reaction"] = null
	new_state["phase"] = "activation"
	_combat_resolve(new_state, attacker, target, faces_now, range_penalty, events)
	return _finish(new_state, events)


## UseHeroAbility in the activation phase (ADR-016 §2-§3): a free action of
## the active seat's hero. Active abilities only; the reaction flips are
## handled by _apply_reaction inside an open window.
static func _apply_hero_ability(state: Dictionary, command: Dictionary) -> Dictionary:
	var ability_id := String(command.get("ability_id", ""))
	var active_seat := String(state.get("active_seat", ""))
	if command.has("seat") and String(command["seat"]) != active_seat:
		return _reject("not_your_seat", "command seat '%s' is not the active seat '%s'"
				% [String(command["seat"]), active_seat])
	var new_state := _copy_state(state)
	var events: Array = []
	var active: Variant = new_state.get("active_ship")
	if active == null:
		return _reject("bad_phase_for_ability",
				"hero abilities need an active ship (BeginActivation first)")
	var ship := _find_ship(new_state, String(active))
	if ship.is_empty() or not bool(ship.get("alive", false)):
		return _reject("bad_phase_for_ability", "active ship is missing or destroyed")
	var hero: Dictionary = new_state.get("heroes", {}).get(active_seat, {})
	if hero.is_empty():
		return _reject("not_your_hero", "seat '%s' has no hero" % active_seat)
	var hero_id := String(hero["hero_id"])
	if String(HERO_ABILITY_IDS.get(hero_id, "")) != ability_id:
		return _reject("not_your_hero", "hero '%s' has no ability '%s'" % [hero_id, ability_id])
	if int(hero.get("uses_left", 0)) <= 0:
		return _reject("hero_no_uses", "hero '%s' has no uses left" % hero_id)
	match hero_id:
		"darth_vader":
			return _hero_force_attack(new_state, ship, hero, command, events)
		"anakin":
			return _hero_force_push(new_state, ship, hero, command, events)
		"han_solo":
			return _hero_hyperjump(new_state, ship, hero, command, events)
		"jango_fett":
			return _hero_place_mine(new_state, ship, hero, events)
		"boba_fett":
			return _hero_place_bomb(new_state, ship, hero, command, events)
	return _reject("not_your_hero", "hero '%s' has no usable ability" % hero_id)


## Vader "force_attack" (ADR-016 §3.2): a full regular combat against a living
## enemy at distance EXACTLY 2 (never touching), no range penalty, sectors
## from the ray. Counts as the activation's attack: attack_used = true.
static func _hero_force_attack(new_state: Dictionary, ship: Dictionary, hero: Dictionary,
		command: Dictionary, events: Array) -> Dictionary:
	if bool(ship.get("attack_used", false)):
		return _reject("attack_used", "ship '%s' already attacked this activation"
				% String(ship["id"]))
	var target_id := String(command.get("target_ship_instance_id", ""))
	var target := _find_ship(new_state, target_id)
	if target.is_empty() or not bool(target.get("alive", false)):
		return _reject("bad_target", "no living target ship '%s'" % target_id)
	if String(target.get("team", "")) == String(ship.get("team", "")):
		return _reject("bad_target", "target '%s' is an ally" % target_id)
	var dist := HexMath.distance(Vector2i(int(ship["q"]), int(ship["r"])),
			Vector2i(int(target["q"]), int(target["r"])))
	if dist != 2:
		return _reject("not_in_range", "target '%s' is at distance %d, force_attack needs 2"
				% [target_id, dist])
	hero["uses_left"] = int(hero["uses_left"]) - 1
	ship["attack_used"] = true
	events.append({"type": "AbilityUsed", "seat": String(new_state["active_seat"]),
			"hero_id": "darth_vader", "ability_id": "force_attack"})
	return _combat_from(new_state, ship, target, 0, events)


## Anakin "force_push" (ADR-016 §3.3): move ANY living ship one cell along
## `dir`; the destination must be on the board and free. Facing is kept.
static func _hero_force_push(new_state: Dictionary, ship: Dictionary, hero: Dictionary,
		command: Dictionary, events: Array) -> Dictionary:
	var target_id := String(command.get("ship_instance_id", ""))
	var victim := _find_ship(new_state, target_id)
	if victim.is_empty() or not bool(victim.get("alive", false)):
		return _reject("bad_target", "no living ship '%s'" % target_id)
	var dir := int(command.get("dir", -1))
	if dir < 0 or dir > 5:
		return _reject("bad_direction", "dir %d outside 0..5" % dir)
	var from_cell := Vector2i(int(victim["q"]), int(victim["r"]))
	var to_cell := HexMath.step(from_cell, dir)
	if not HexMath.in_board(to_cell, _board_radius()):
		return _reject("out_of_board", "cell (%d,%d) is outside the board"
				% [to_cell.x, to_cell.y])
	if not _alive_ship_at(new_state, to_cell).is_empty():
		return _reject("occupied_cell", "cell (%d,%d) is occupied" % [to_cell.x, to_cell.y])
	hero["uses_left"] = int(hero["uses_left"]) - 1
	events.append({"type": "AbilityUsed", "seat": String(new_state["active_seat"]),
			"hero_id": "anakin", "ability_id": "force_push"})
	victim["q"] = to_cell.x
	victim["r"] = to_cell.y
	events.append({
		"type": "ShipMoved",
		"ship_instance_id": target_id,
		"from_q": from_cell.x, "from_r": from_cell.y,
		"to_q": to_cell.x, "to_r": to_cell.y,
	})
	_check_mines_after_move(new_state, victim, events)
	return _finish(new_state, events)


## Han "hyperjump" (ADR-016 §3.4): move the seat's active ship to any board
## cell that is free and not adjacent to a living enemy. Needs charges >= 1
## and zeroes them. Facing is kept.
static func _hero_hyperjump(new_state: Dictionary, ship: Dictionary, hero: Dictionary,
		command: Dictionary, events: Array) -> Dictionary:
	if int(ship.get("charges", 0)) <= 0:
		return _reject("no_charges", "ship '%s' has 0 charges" % String(ship["id"]))
	var to_cell := Vector2i(int(command.get("q", 9999)), int(command.get("r", 9999)))
	if not HexMath.in_board(to_cell, _board_radius()):
		return _reject("out_of_board", "cell (%d,%d) is outside the board"
				% [to_cell.x, to_cell.y])
	if not _alive_ship_at(new_state, to_cell).is_empty():
		return _reject("occupied_cell", "cell (%d,%d) is occupied" % [to_cell.x, to_cell.y])
	if _living_enemy_near(new_state, to_cell, String(ship.get("team", ""))):
		return _reject("too_close_to_enemy", "cell (%d,%d) neighbors a living enemy"
				% [to_cell.x, to_cell.y])
	var from_cell := Vector2i(int(ship["q"]), int(ship["r"]))
	hero["uses_left"] = int(hero["uses_left"]) - 1
	events.append({"type": "AbilityUsed", "seat": String(new_state["active_seat"]),
			"hero_id": "han_solo", "ability_id": "hyperjump"})
	# v3.5 (ADR-018): zeroing the charges is a spend — it feeds the tally.
	ship["spent_round"] = int(ship.get("spent_round", 0)) + int(ship.get("charges", 0))
	ship["charges"] = 0
	events.append({
		"type": "ChargeSpent",
		"ship_instance_id": String(ship["id"]),
		"reason": "hyperjump",
		"charges_left": 0,
	})
	ship["q"] = to_cell.x
	ship["r"] = to_cell.y
	events.append({
		"type": "ShipMoved",
		"ship_instance_id": String(ship["id"]),
		"from_q": from_cell.x, "from_r": from_cell.y,
		"to_q": to_cell.x, "to_r": to_cell.y,
	})
	_check_mines_after_move(new_state, ship, events)
	return _finish(new_state, events)


## Jango "place_mine" (ADR-016 §3.6): a mine goes onto the active ship's cell.
## Ships already standing in the trigger radius do not detonate it; it blows
## up when any ship ENTERS the cell or a neighbor after a move (§5).
static func _hero_place_mine(new_state: Dictionary, ship: Dictionary, hero: Dictionary,
		events: Array) -> Dictionary:
	var cell := Vector2i(int(ship["q"]), int(ship["r"]))
	hero["uses_left"] = int(hero["uses_left"]) - 1
	var seat := String(new_state["active_seat"])
	events.append({"type": "AbilityUsed", "seat": seat, "hero_id": "jango_fett",
			"ability_id": "place_mine"})
	(new_state["objects"] as Array).append(
			{"kind": "mine", "q": cell.x, "r": cell.y, "seat": seat})
	events.append({"type": "MinePlaced", "seat": seat, "q": cell.x, "r": cell.y})
	return _finish(new_state, events)


## Boba "place_bomb" (ADR-016 §3.7): a bomb with a fixed direction goes onto
## the active ship's cell and drifts one cell at the end of every activation
## of the owner seat (first drift at the end of this very activation), at most
## BOMB_MAX_SHIFTS times.
static func _hero_place_bomb(new_state: Dictionary, ship: Dictionary, hero: Dictionary,
		command: Dictionary, events: Array) -> Dictionary:
	var dir := int(command.get("dir", -1))
	if dir < 0 or dir > 5:
		return _reject("bad_direction", "dir %d outside 0..5" % dir)
	var cell := Vector2i(int(ship["q"]), int(ship["r"]))
	hero["uses_left"] = int(hero["uses_left"]) - 1
	var seat := String(new_state["active_seat"])
	events.append({"type": "AbilityUsed", "seat": seat, "hero_id": "boba_fett",
			"ability_id": "place_bomb"})
	(new_state["objects"] as Array).append({
		"kind": "bomb", "q": cell.x, "r": cell.y, "seat": seat,
		"dir": dir, "moves_left": BOMB_MAX_SHIFTS,
	})
	events.append({"type": "BombPlaced", "seat": seat, "q": cell.x, "r": cell.y, "dir": dir})
	return _finish(new_state, events)


## Mine trigger check (ADR-016 §3.8/§5) after ANY ship movement: a mine in the
## ship's new cell or one of its six neighbors detonates — 1 x d4 damage
## (shield first), the mine is removed. The chain stops when the ship is
## destroyed. Dice of the whole effect chain carry role "effect".
static func _check_mines_after_move(new_state: Dictionary, ship: Dictionary,
		events: Array) -> void:
	var cell := Vector2i(int(ship["q"]), int(ship["r"]))
	var radius_cells: Array[Vector2i] = [cell]
	for n: Vector2i in HexMath.neighbors(cell):
		radius_cells.append(n)
	while bool(ship.get("alive", true)):
		var objects: Array = new_state["objects"]
		var hit_index := -1
		for i in objects.size():
			var obj: Dictionary = objects[i]
			if String(obj.get("kind", "")) != "mine":
				continue
			if radius_cells.has(Vector2i(int(obj["q"]), int(obj["r"]))):
				hit_index = i
				break
		if hit_index < 0:
			return
		var mine: Dictionary = objects[hit_index]
		objects.remove_at(hit_index)
		_apply_effect_damage(new_state, ship, String(mine.get("seat", "")),
				Vector2i(int(mine["q"]), int(mine["r"])), "mine", events)


## One d4 effect hit (mine or bomb, ADR-016 §3.8): DieRolled (role "effect")
## -> DamageApplied (shield first) -> MineTriggered/BombTriggered ->
## ObjectRemoved; a lethal hit runs the regular destruction pipeline
## (ghost/tie, ADR-012) with role "effect" on its dice.
static func _apply_effect_damage(new_state: Dictionary, victim: Dictionary, owner_seat: String,
		at_cell: Vector2i, kind: String, events: Array) -> void:
	var defs := CardStore.ships_ref()
	var game := CardStore.game_rules()
	var rng: Rng = _stream_rng(int(new_state["seed"]), new_state["dice"], defs, game,
			new_state.get("seat_order", SEAT_ORDER))
	var dice_log: Array = new_state["dice"]
	var roll_index := int(new_state["rng_counter"])
	var damage := _roll(rng, 4, "effect", roll_index, dice_log, events)
	roll_index += 1
	new_state["rng_counter"] = roll_index
	new_state["dice"] = dice_log
	_apply_damage(victim, damage, events)
	events.append({
		"type": "MineTriggered" if kind == "mine" else "BombTriggered",
		"seat": owner_seat,
		"q": at_cell.x,
		"r": at_cell.y,
		"target_id": String(victim["id"]),
	})
	events.append({"type": "ObjectRemoved", "kind": kind, "q": at_cell.x, "r": at_cell.y})
	if int(victim["hp"]) <= 0:
		_resolve_destruction(new_state, victim, "effect", rng, roll_index, events)
	_cache_rng_stream(dice_log)


## Bomb drift (ADR-016 §3.7): at the end of every activation of the owner seat
## each of its bombs steps one cell along its fixed direction. Off the board
## -> despawn; ship in the destination cell -> 1 x d4 explosion; third step
## -> the charge disperses (despawn, no explosion).
static func _drift_bombs_of_seat(new_state: Dictionary, seat: String, events: Array) -> void:
	var objects: Array = new_state["objects"]
	var i := 0
	while i < objects.size():
		var obj: Dictionary = objects[i]
		if String(obj.get("kind", "")) != "bomb" or String(obj.get("seat", "")) != seat:
			i += 1
			continue
		var from_cell := Vector2i(int(obj["q"]), int(obj["r"]))
		var to_cell := HexMath.step(from_cell, int(obj.get("dir", 0)))
		if not HexMath.in_board(to_cell, _board_radius()):
			objects.remove_at(i)
			events.append({"type": "ObjectRemoved", "kind": "bomb",
					"q": from_cell.x, "r": from_cell.y})
			continue
		var victim := _alive_ship_at(new_state, to_cell)
		obj["q"] = to_cell.x
		obj["r"] = to_cell.y
		events.append({"type": "BombMoved", "seat": seat, "from_q": from_cell.x,
				"from_r": from_cell.y, "to_q": to_cell.x, "to_r": to_cell.y})
		if not victim.is_empty():
			objects.remove_at(i)
			_apply_effect_damage(new_state, victim, seat, to_cell, "bomb", events)
			continue
		var moves_left := int(obj.get("moves_left", 0)) - 1
		obj["moves_left"] = moves_left
		if moves_left <= 0:
			objects.remove_at(i)
			events.append({"type": "ObjectRemoved", "kind": "bomb",
					"q": to_cell.x, "r": to_cell.y})
			continue
		i += 1


## Stores a copy of the full dice log as the cached stream position (the
## cached Rng object sits exactly at its end after combat rolls).
static func _cache_rng_stream(dice_log: Array) -> void:
	var consumed: Array = []
	consumed.resize(dice_log.size())
	for i in dice_log.size():
		consumed[i] = int(dice_log[i])
	_rng_cache["log"] = consumed


## Rolls one die, appends its sides to the state dice log and the DieRolled
## event (rng_index = index) to the journal.
static func _roll(rng: Rng, sides: int, role: String, index: int, dice_log: Array,
		events: Array) -> int:
	var value := rng.next_die(sides)
	dice_log.append(sides)
	events.append({"type": "DieRolled", "rng_index": index, "sides": sides, "value": value,
			"role": role})
	return value


## Shield-first damage of `diff` points; emits DamageApplied.
static func _apply_damage(loser: Dictionary, diff: int, events: Array) -> void:
	var shield := int(loser["shield"])
	var hp := int(loser["hp"])
	var shield_damage := mini(shield, diff)
	var hull_damage := mini(hp, diff - shield_damage)
	loser["shield"] = shield - shield_damage
	loser["hp"] = hp - hull_damage
	events.append({
		"type": "DamageApplied",
		"target_id": String(loser["id"]),
		"shield_damage": shield_damage,
		"hull_damage": hull_damage,
		"hp_left": int(loser["hp"]),
		"shield_left": int(loser["shield"]),
	})


## Resolves hp <= 0 of `loser` (ADR-012): ghost transforms instead of dying
## (no dice), tie_fighter gets one d2 revive attempt per match (d4 hp on
## success), otherwise the ship is destroyed. ShipDestroyed is emitted only
## when the destruction is final — never before a revive attempt resolves.
static func _resolve_destruction(new_state: Dictionary, loser: Dictionary, role: String,
		rng: Rng, roll_index: int, events: Array) -> void:
	var defs := CardStore.ships_ref()
	var from_type := String(loser["type_id"])
	var loser_id := String(loser["id"])
	loser["hp"] = 0
	var dice_log: Array = new_state["dice"]
	if _has_ability(defs.get(from_type, {}), ABILITY_TRANSFORM):
		var to_type := "phantom"
		for ability: Dictionary in defs.get(from_type, {}).get("abilities", []):
			if String(ability.get("id", "")) == ABILITY_TRANSFORM and ability.has("transform_to"):
				to_type = String(ability["transform_to"])
		var phantom_def: Dictionary = defs.get(to_type, {})
		var hp := int(phantom_def.get("max_hp", 1))
		var charges := mini(int(loser["charges"]), int(phantom_def.get("max_charges", 5)))
		loser["type_id"] = to_type
		loser["hp"] = hp
		loser["shield"] = 0
		loser["charges"] = charges
		events.append({"type": "ShipTransformed", "ship_instance_id": loser_id,
				"from_type": from_type, "to_type": to_type, "hp": hp, "shield": 0,
				"charges": charges})
		return
	if _has_ability(defs.get(from_type, {}), ABILITY_RESURRECTION) \
			and not bool(loser.get("revive_used", false)):
		loser["revive_used"] = true
		var luck := _roll(rng, 2, role, roll_index, dice_log, events)
		roll_index += 1
		if luck == 2:
			var hp := _roll(rng, 4, role, roll_index, dice_log, events)
			roll_index += 1
			loser["hp"] = hp
			loser["shield"] = 0
			loser["alive"] = true
			events.append({"type": "ShipRevived", "ship_instance_id": loser_id, "hp": hp})
			new_state["rng_counter"] = roll_index
			new_state["dice"] = dice_log
			return
	loser["alive"] = false
	events.append({"type": "ShipDestroyed", "ship_instance_id": loser_id})
	new_state["rng_counter"] = roll_index
	new_state["dice"] = dice_log


# --- Turn passing and match end ---------------------------------------------

static func _pass_turn(new_state: Dictionary, events: Array) -> void:
	var order: Array = new_state.get("seat_order", SEAT_ORDER)
	if order.is_empty():
		order = SEAT_ORDER
	var idx := order.find(String(new_state["active_seat"]))
	for j in range(1, order.size() + 1):
		var candidate: String = String(order[(idx + j) % order.size()])
		if _seat_has_actionable(new_state, candidate):
			new_state["active_seat"] = candidate
			return
	# Every living ship has activated: the round is complete. v3.5 (ADR-018):
	# charges are REWRITTEN once here, before RoundStarted(n+1) — a decided
	# match (round limit reached, or this very activation ended the game)
	# neither refreshes charges nor starts a next round.
	var next_round := int(new_state["round"]) + 1
	if next_round > int(new_state["round_limit"]):
		new_state["phase"] = "ended"
		new_state["winner"] = null
		events.append({"type": "MatchEnded", "winner": null, "reason": "round_limit"})
		return
	if _match_is_decided(new_state):
		return
	_refresh_round_charges(new_state, events)
	new_state["round"] = next_round
	for s: Dictionary in new_state["ships"]:
		s["activated"] = false
		s["attack_used"] = false
		# v3.5 (ADR-018): the spend tally resets with the new round.
		s["spent_round"] = 0
	new_state["active_seat"] = _first_seat_with_living(new_state)
	events.append({"type": "RoundStarted", "round": next_round})


## True when the outcome is already fixed: at most one team still has living
## ships (victory or draw). Mirrors the _finish check; used by _pass_turn so a
## round whose last activation ended the match never rolls into the next round
## and never rewrites charges (ADR-018).
static func _match_is_decided(new_state: Dictionary) -> bool:
	var alive_by_team := {}
	for s: Dictionary in new_state["ships"]:
		if bool(s.get("alive", false)):
			var team := String(s.get("team", ""))
			alive_by_team[team] = int(alive_by_team.get(team, 0)) + 1
	var living_teams := 0
	for team_key: Variant in alive_by_team:
		if int(alive_by_team[team_key]) > 0:
			living_teams += 1
	return living_teams <= 1


## v3.5 end-of-round charge rewrite (ADR-018): every LIVING ship's charges are
## overwritten (never added to) — max_charges when the ship spent no charge
## this round (spent_round == 0, "saved up -> full tank"), ceil(max_charges/2)
## otherwise. max_charges is read from the individual ship card. One
## ChargesRefreshed event per living ship, in ships array order. Pure
## bookkeeping: the dice log is untouched, so rng_counter == dice.size() holds.
## With charge_round_reset = "none" in game.json the rewrite is skipped.
static func _refresh_round_charges(new_state: Dictionary, events: Array) -> void:
	var game := CardStore.game_rules()
	if String(game.get("charge_round_reset", "half_up")) == "none":
		return
	var defs := CardStore.ships_ref()
	for s: Dictionary in new_state["ships"]:
		if not bool(s.get("alive", false)):
			continue
		var max_charges := maxi(1, int(defs.get(String(s["type_id"]), {}).get("max_charges", 5)))
		var full := int(s.get("spent_round", 0)) == 0
		var charges := max_charges if full else (max_charges + 1) / 2 # ceil(max/2)
		s["charges"] = charges
		events.append({
			"type": "ChargesRefreshed",
			"ship_instance_id": String(s["id"]),
			"charges": charges,
			"full": full,
		})


## Match-end check after every applied command (core-api §4.3 item 7). Teams
## are scenario data (ADR-015): the match ends when at most one team still has
## living ships; with two teams (A/B) the outcome is identical to counting
## alive_a/alive_b as before.
static func _finish(new_state: Dictionary, events: Array) -> Dictionary:
	if String(new_state["phase"]) != "ended":
		var alive_by_team := {}
		for s: Dictionary in new_state["ships"]:
			if bool(s.get("alive", false)):
				var team := String(s.get("team", ""))
				alive_by_team[team] = int(alive_by_team.get(team, 0)) + 1
		var living_teams := 0
		var last_team := ""
		for team_key: Variant in alive_by_team:
			if int(alive_by_team[team_key]) > 0:
				living_teams += 1
				last_team = String(team_key)
		if living_teams == 0:
			new_state["phase"] = "ended"
			new_state["winner"] = null
			events.append({"type": "MatchEnded", "winner": null, "reason": "both_eliminated"})
		elif living_teams == 1:
			new_state["phase"] = "ended"
			new_state["winner"] = last_team
			events.append({"type": "MatchEnded", "winner": last_team, "reason": "elimination"})
	return {"ok": true, "events": events, "state": new_state}


# --- Draft (core-api §4.1) ---------------------------------------------------

## Deterministic draft; consumes exactly one rng.next_below per pick.
## Drafts only for the scenario seats, in seat_order (ADR-015: 2 seats for the
## duel, 4 for the full 2x2). Returns pick dicts with ShipDrafted event fields,
## in pick order.
static func _run_draft(rng: Rng, defs: Dictionary, game: Dictionary,
		seat_order: Array) -> Array:
	var fleet_size := int(game.get("fleet_size", 3))
	var budget := int(game.get("draft_budget", 17))
	var max_group2 := int(game.get("max_group2_per_seat", 1))
	var max_same_g1 := int(game.get("max_same_type_group1_per_seat", 2))
	var ids: Array = defs.keys()
	ids.sort()
	var seat_state := {}
	for seat_v: Variant in seat_order:
		seat_state[String(seat_v)] = {"sum": 0, "g2": 0, "g1": {}}
	var g2_taken := {} # group 2 types are unique across the whole match
	var picks: Array = []
	for round_index in fleet_size:
		for seat_v: Variant in seat_order:
			var seat := String(seat_v)
			var ss: Dictionary = seat_state[seat]
			var candidates: Array[String] = []
			for type_id: Variant in ids:
				var def: Dictionary = defs[type_id]
				if not bool(def.get("draftable", true)):
					continue
				var group := int(def.get("group", 1))
				if group == 0:
					continue
				var cost := int(def.get("draft_cost", 0))
				if group == 2:
					if int(ss["g2"]) >= max_group2 or g2_taken.has(type_id):
						continue
				elif int(ss["g1"].get(type_id, 0)) >= max_same_g1:
					continue
				var remaining := fleet_size - round_index - 1
				if remaining == 0:
					if int(ss["sum"]) + cost > budget:
						continue
				else:
					var min_rest := _min_remaining_cost(defs, ids, ss, g2_taken, String(type_id),
							remaining, max_group2, max_same_g1)
					if min_rest < 0 or int(ss["sum"]) + cost + min_rest > budget:
						continue
				candidates.append(String(type_id))
			if candidates.is_empty():
				push_error("match_engine: no draft candidates for seat %s (round %d)"
						% [seat, round_index + 1])
				return []
			var choice := candidates[rng.next_below(candidates.size())]
			var chosen: Dictionary = defs[choice]
			var pick := {
				"seat": seat,
				"ship_instance_id": "%s_%s_%d" % [seat, choice, round_index],
				"ship_type_id": choice,
				"cost": int(chosen.get("draft_cost", 0)),
			}
			picks.append(pick)
			ss["sum"] = int(ss["sum"]) + int(chosen.get("draft_cost", 0))
			if int(chosen.get("group", 1)) == 2:
				ss["g2"] = int(ss["g2"]) + 1
				g2_taken[choice] = true
			else:
				ss["g1"][choice] = int(ss["g1"].get(choice, 0)) + 1
	return picks


## Deterministic hero draft (ADR-016 §1): one distinct hero per scenario seat
## in seat_order; every pick consumes exactly one rng.next_below over the
## remaining pool of hero ids (sorted). Returns {seat: {hero_id, uses_left}}
## with uses_left from the hero card (uses_per_match; 0 for the passive
## phasma). An empty hero store yields {} (engine runs hero-less).
static func _run_hero_draft(rng: Rng, hero_defs: Dictionary, seat_order: Array) -> Dictionary:
	var pool: Array = hero_defs.keys()
	pool.sort()
	var out := {}
	for seat_v: Variant in seat_order:
		if pool.is_empty():
			break
		var hero_id := String(pool[rng.next_below(pool.size())])
		pool.erase(hero_id)
		var card: Dictionary = hero_defs.get(hero_id, {})
		# uses_per_match lives on the hero card's ability (data schema v1).
		var ability: Dictionary = card.get("ability", {})
		var uses := int(ability.get("uses_per_match", card.get("uses_per_match", 0)))
		out[String(seat_v)] = {
			"hero_id": hero_id,
			"uses_left": uses,
		}
	return out


## Cheapest sum of `remaining` ship types still allowed for the seat after it
## hypothetically takes extra_type; -1 if not enough allowed types remain.
static func _min_remaining_cost(defs: Dictionary, ids: Array, ss: Dictionary,
		g2_taken: Dictionary, extra_type: String, remaining: int, max_group2: int,
		max_same_g1: int) -> int:
	var extra: Dictionary = defs[extra_type]
	var g2 := int(ss["g2"])
	var g1: Dictionary = ss["g1"].duplicate()
	var g2_after: Dictionary = g2_taken.duplicate()
	if int(extra.get("group", 1)) == 2:
		g2 += 1
		g2_after[extra_type] = true
	else:
		g1[extra_type] = int(g1.get(extra_type, 0)) + 1
	var costs: Array[int] = []
	for type_id: Variant in ids:
		var def: Dictionary = defs[type_id]
		if not bool(def.get("draftable", true)):
			continue
		var group := int(def.get("group", 1))
		if group == 0:
			continue
		if group == 2:
			if g2 >= max_group2 or g2_after.has(type_id):
				continue
		elif int(g1.get(type_id, 0)) >= max_same_g1:
			continue
		costs.append(int(def.get("draft_cost", 0)))
	if costs.size() < remaining:
		return -1
	costs.sort()
	var total := 0
	for i in remaining:
		total += costs[i]
	return total


# --- RNG stream reconstruction ----------------------------------------------

## Returns an Rng positioned so that the next next_die() continues the match
## stream exactly after the dice recorded in dice_log: draft replay plus one
## next_die per recorded side (ADR-012). The cache keeps the most advanced
## stream per seed; a shorter or diverging log rebuilds from the seed.
static func _stream_rng(seed_value: int, dice_log: Array, defs: Dictionary,
		game: Dictionary, seat_order: Array) -> Rng:
	var cached_seed := int(_rng_cache["seed"])
	var cached_log: Array = _rng_cache["log"]
	var rng: Rng = _rng_cache["rng"]
	var reuse := rng != null and cached_seed == seed_value and cached_log.size() <= dice_log.size()
	if reuse:
		for i in cached_log.size():
			if int(cached_log[i]) != int(dice_log[i]):
				reuse = false
				break
	if reuse:
		for i in range(cached_log.size(), dice_log.size()):
			rng.next_die(int(dice_log[i]))
	else:
		rng = Rng.new(seed_value)
		_run_draft(rng, defs, game, seat_order)
		_run_hero_draft(rng, CardStore.heroes(), seat_order)
		for i in dice_log.size():
			rng.next_die(int(dice_log[i]))
	var consumed: Array = []
	consumed.resize(dice_log.size())
	for i in dice_log.size():
		consumed[i] = int(dice_log[i])
	_rng_cache["seed"] = seed_value
	_rng_cache["log"] = consumed
	_rng_cache["rng"] = rng
	return rng


# --- Special-rule helpers ----------------------------------------------------

## True when ship definition `def` carries `ability_id` among its enabled
## abilities (data mechanism: "abilities": [{"id": ..., "enabled": true}]).
static func _has_ability(def: Dictionary, ability_id: String) -> bool:
	for ability: Dictionary in def.get("abilities", []):
		if String(ability.get("id", "")) == ability_id and bool(ability.get("enabled", false)):
			return true
	return false


## Direction index 0..5 of the straight ray from `from` toward `to`, defined
## for any distance (C008 ranged sectors). Exact hex direction for neighbors;
## otherwise the direction whose unit vector encloses the smallest angle with
## the offset, computed in exact integer arithmetic: true plane coordinates
## are x = sqrt(3) * (q + r / 2), y = 3 * r / 2, so after the substitution
## X = 2q + r the projection score of offset (dq, dr) onto direction delta
## (a, b) is (2*dq + dr) * (2*a + b) + 3 * dr * b — up to one positive factor.
## All six direction vectors have equal length, so scores compare directly;
## ties resolve to the lowest direction index. No floats, fully deterministic.
static func _ray_direction(from: Vector2i, to: Vector2i) -> int:
	var exact := HexMath.direction_from(from, to)
	if exact >= 0:
		return exact
	var wx := 2 * (to.x - from.x) + (to.y - from.y)
	var wy := to.y - from.y
	var best_dir := 0
	var best_score := -1
	for d in 6:
		var delta := HexMath.direction_delta(d)
		var score := wx * (2 * delta.x + delta.y) + 3 * wy * delta.y
		if score > best_score:
			best_score = score
			best_dir = d
	return best_dir


# --- Small helpers -----------------------------------------------------------

## Board radius is data (board.json, ADR-015: radius 3 / 37 cells), applied to
## every in_board check of the engine.
static func _board_radius() -> int:
	return maxi(1, int(CardStore.board().get("radius", 4)))


static func _find_ship(state: Dictionary, instance_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("id", "")) == instance_id:
			return s
	return {}


static func _alive_ship_at(state: Dictionary, cell: Vector2i) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if bool(s.get("alive", false)) and int(s.get("q", 0)) == cell.x and int(s.get("r", 0)) == cell.y:
			return s
	return {}


## Hero id of `seat` in the state, "" when the seat has none.
static func _seat_hero_id(state: Dictionary, seat: String) -> String:
	var hero: Dictionary = state.get("heroes", {}).get(seat, {})
	return String(hero.get("hero_id", ""))


## True when a living enemy-team ship sits on `cell` or one of its neighbors.
static func _living_enemy_near(state: Dictionary, cell: Vector2i, team: String) -> bool:
	for n: Vector2i in HexMath.neighbors(cell):
		var occ := _alive_ship_at(state, n)
		if not occ.is_empty() and String(occ.get("team", "")) != team:
			return true
	return false


static func _seat_has_actionable(state: Dictionary, seat: String) -> bool:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) == seat and bool(s.get("alive", false)) \
				and not bool(s.get("activated", false)):
			return true
	return false


static func _first_seat_with_living(state: Dictionary) -> String:
	var order: Array = state.get("seat_order", SEAT_ORDER)
	if order.is_empty():
		order = SEAT_ORDER
	for seat_v: Variant in order:
		var seat := String(seat_v)
		for s: Dictionary in state.get("ships", []):
			if String(s.get("seat", "")) == seat and bool(s.get("alive", false)):
				return seat
	return ""


static func _copy_state(state: Dictionary) -> Dictionary:
	# Native deep copy: duplicates the ships array and every ship dict; cheaper
	# than a scripted loop and preserves the purity guarantee.
	return state.duplicate(true)


static func _arc(def: Dictionary, sector: int) -> int:
	var arcs: Array = def.get("arc_modifiers", [])
	if sector < 0 or sector >= arcs.size():
		return 0
	return int(arcs[sector])


static func _reject(code: String, detail: String) -> Dictionary:
	return {"ok": false, "error": code, "detail": detail}
