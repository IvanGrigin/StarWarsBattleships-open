# Static loader for ruleset data cards (core-api §8). Reads JSON via FileAccess,
# converts every JSON number without a fractional part to int right after parse
# (Godot's JSON.parse_string returns floats for all numbers — core-api §9
# Addendum) and caches parsed stores per ruleset directory in static vars.
extends RefCounted

const DEFAULT_RULESET_DIR := "res://data/rulesets/v3"

const Canonical := preload("res://src/core/serialization/canonical.gd")

static var _cache: Dictionary = {}


static func ships(ruleset_dir: String = DEFAULT_RULESET_DIR) -> Dictionary:
	return _load(ruleset_dir).get("ships", {}).duplicate(true)


## Read-only view for engine hot paths; callers must not mutate the result.
static func ships_ref(ruleset_dir: String = DEFAULT_RULESET_DIR) -> Dictionary:
	return _load(ruleset_dir).get("ships", {})


static func ship_ids_sorted(ruleset_dir: String = DEFAULT_RULESET_DIR) -> Array[String]:
	var out: Array[String] = []
	for id: Variant in _load(ruleset_dir).get("ship_ids", []):
		out.append(String(id))
	return out


static func game_rules(ruleset_dir: String = DEFAULT_RULESET_DIR) -> Dictionary:
	return _load(ruleset_dir).get("game", {}).duplicate(true)


## Board geometry (ADR-015: radius drives every in_board check of the engine).
static func board(ruleset_dir: String = DEFAULT_RULESET_DIR) -> Dictionary:
	return _load(ruleset_dir).get("board", {}).duplicate(true)


static func scenario(name: String, ruleset_dir: String = DEFAULT_RULESET_DIR) -> Dictionary:
	var scenarios: Dictionary = _load(ruleset_dir).get("scenarios", {})
	return scenarios.get(name, {}).duplicate(true)


## Hero cards (ADR-016): data/rulesets/v3/heroes/*.json keyed by hero id.
## Each entry carries at least {id, display_name, ability:{id, kind, uses_per_match}}.
static func heroes(ruleset_dir: String = DEFAULT_RULESET_DIR) -> Dictionary:
	return _load(ruleset_dir).get("heroes", {}).duplicate(true)


## FNV-1a over the canonical form of game+board+ships. Scenario is excluded:
## it is match configuration, not ruleset content.
static func ruleset_hash(ruleset_dir: String = DEFAULT_RULESET_DIR) -> String:
	return String(_load(ruleset_dir).get("ruleset_hash", ""))


## Recursively converts floats without a fractional part to int; bool, String
## and null pass through untouched.
static func coerce_json(value: Variant) -> Variant:
	if value is float:
		return int(value) if value == floorf(value) else value
	if value is Array:
		var out: Array = []
		out.resize(value.size())
		for i in value.size():
			out[i] = coerce_json(value[i])
		return out
	if value is Dictionary:
		var out_dict := {}
		for key: Variant in value:
			out_dict[key] = coerce_json(value[key])
		return out_dict
	return value


static func _load(ruleset_dir: String) -> Dictionary:
	if _cache.has(ruleset_dir):
		return _cache[ruleset_dir]
	var game := _read_json(ruleset_dir + "/game.json")
	if game.is_empty():
		return {}
	var board := _read_json(ruleset_dir + "/board.json")
	if board.is_empty():
		return {}
	var ship_defs := _read_dir_of_json(ruleset_dir + "/ships")
	if ship_defs.is_empty():
		push_error("card_store: no ship definitions under %s/ships" % ruleset_dir)
		return {}
	var ships := {}
	for file_name: String in ship_defs.keys():
		var def: Dictionary = ship_defs[file_name]
		if not def.has("id"):
			push_error("card_store: %s/ships/%s has no id field" % [ruleset_dir, file_name])
			return {}
		ships[String(def["id"])] = def
	var scenario_defs := _read_dir_of_json(ruleset_dir + "/scenarios")
	var scenarios := {}
	for file_name: String in scenario_defs.keys():
		var data: Dictionary = scenario_defs[file_name]
		var key := String(data.get("scenario_id", ""))
		if key.is_empty():
			key = file_name.trim_suffix(".json")
		scenarios[key] = data
	var hero_defs := _read_dir_of_json(ruleset_dir + "/heroes")
	var heroes := {}
	for file_name: String in hero_defs.keys():
		var hero: Dictionary = hero_defs[file_name]
		var hero_key := String(hero.get("id", ""))
		if hero_key.is_empty():
			hero_key = file_name.trim_suffix(".json")
		heroes[hero_key] = hero
	var ids: Array = ships.keys()
	ids.sort()
	var store := {
		"game": game,
		"board": board,
		"ships": ships,
		"ship_ids": ids,
		"scenarios": scenarios,
		"heroes": heroes,
		"ruleset_hash": Canonical.state_hash({"board": board, "game": game, "ships": ships}),
	}
	_cache[ruleset_dir] = store
	return store


## Reads every *.json of a directory (sorted by file name) into {file_name: dict}.
## Missing directory is not an error (returns {}); a broken file is.
static func _read_dir_of_json(dir_path: String) -> Dictionary:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		if DirAccess.dir_exists_absolute(dir_path):
			push_error("card_store: cannot open directory %s" % dir_path)
		return {}
	var file_names: Array[String] = []
	dir.list_dir_begin()
	var name := dir.get_next()
	while name != "":
		if not dir.current_is_dir() and not name.begins_with(".") and name.ends_with(".json"):
			file_names.append(name)
		name = dir.get_next()
	dir.list_dir_end()
	file_names.sort()
	var out := {}
	for file_name: String in file_names:
		var data := _read_json(dir_path + "/" + file_name)
		if data.is_empty():
			return {}
		out[file_name] = data
	return out


static func _read_json(path: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		push_error("card_store: cannot read %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		push_error("card_store: %s is not a JSON object" % path)
		return {}
	var converted: Variant = coerce_json(parsed)
	if not (converted is Dictionary):
		push_error("card_store: %s did not convert to a Dictionary" % path)
		return {}
	return converted
