# Unit tests for src/core/serialization/canonical.gd against
# tools/reference/hash_reference.py golden vectors.
extends "res://tools/test_base.gd"

const Canonical := preload("res://src/core/serialization/canonical.gd")


func run() -> int:
	section("to_canonical: key sorting")
	var d := {"b": 1, "a": 2}
	assert_eq(Canonical.to_canonical(d), "{\"a\":2,\"b\":1}", "keys sorted")

	section("to_canonical: nested dictionaries")
	var nested := {"z": {"y": 1, "a": 2}, "m": [{"b": 1, "a": 0}]}
	assert_eq(Canonical.to_canonical(nested), "{\"m\":[{\"a\":0,\"b\":1}],\"z\":{\"a\":2,\"y\":1}}", "nested sorted recursively")

	section("to_canonical: insertion order does not matter")
	var built_a := {}
	built_a["ships"] = []
	built_a["round"] = 1
	built_a["active_seat"] = "A1"
	var built_b := {}
	built_b["active_seat"] = "A1"
	built_b["round"] = 1
	built_b["ships"] = []
	assert_eq(Canonical.to_canonical(built_a), Canonical.to_canonical(built_b), "same dict, different insertion order")
	assert_eq(Canonical.to_canonical(built_a), "{\"active_seat\":\"A1\",\"round\":1,\"ships\":[]}", "fixed canonical string")

	section("to_canonical: arrays keep order")
	assert_eq(Canonical.to_canonical([3, 1, 2]), "[3,1,2]", "array elements not sorted")
	assert_eq(Canonical.to_canonical([{"b": 1, "a": 2}, {"d": 3, "c": 4}]), "[{\"a\":2,\"b\":1},{\"c\":4,\"d\":3}]", "dicts inside array sorted")

	section("to_canonical: scalars")
	assert_eq(Canonical.to_canonical(true), "true", "bool true")
	assert_eq(Canonical.to_canonical(false), "false", "bool false")
	assert_eq(Canonical.to_canonical(42), "42", "int as int")
	assert_eq(Canonical.to_canonical(-7), "-7", "negative int")
	assert_eq(Canonical.to_canonical("hi"), "\"hi\"", "string quoted")
	assert_eq(Canonical.to_canonical(null), "null", "null")
	assert_eq(Canonical.to_canonical("русская строка"), "\"русская строка\"", "unicode not escaped")

	section("state_hash: golden vectors")
	var text := FileAccess.get_file_as_string("res://tests/golden/hash_vectors.json")
	assert_true(text != "", "hash golden file is readable")
	var golden: Variant = JSON.parse_string(text)
	assert_true(golden is Dictionary, "hash golden parses to Dictionary")
	var inputs: Array = golden["inputs"]
	var hashes: Array = golden["hashes"]
	assert_eq(inputs.size(), hashes.size(), "inputs/hashes same length")
	for i in inputs.size():
		var input := String(inputs[i])
		# Inputs are canonical strings already; hash them directly.
		assert_eq(Canonical.fnv1a64_hex(input), String(hashes[i]), "fnv input %d" % i)

	section("state_hash: canonical byte identity with golden inputs")
	# JSON.parse_string returns every number as float in Godot, so golden inputs
	# are rebuilt here as typed GDScript literals (ints stay ints).
	var dict_inputs: Array[Dictionary] = [
		{},
		{"a": 1},
		{"ships": [{"hp": 4, "id": "A1_tie_fighter_0"}]},
	]
	for i in dict_inputs.size():
		var golden_input := String(inputs[i + 1])
		assert_eq(Canonical.to_canonical(dict_inputs[i]), golden_input, "canonical byte identity %d" % i)
		assert_eq(Canonical.state_hash(dict_inputs[i]), String(hashes[i + 1]), "state_hash input %d" % i)

	section("state_hash: insertion order and sensitivity")
	var s1 := {"a": 1, "b": 2, "c": 3}
	var s2 := {"c": 3, "a": 1, "b": 2}
	assert_eq(Canonical.state_hash(s1), Canonical.state_hash(s2), "hash independent of insertion order")
	var s3 := {"a": 2, "b": 2, "c": 3}
	assert_ne(Canonical.state_hash(s1), Canonical.state_hash(s3), "hash changes on value change")
	assert_ne(Canonical.fnv1a64_hex("abc"), Canonical.fnv1a64_hex("abd"), "hash changes on input change")
	assert_eq(Canonical.fnv1a64_hex(""), "CBF29CE484222325", "FNV-1a 64 offset basis")

	return finish()
