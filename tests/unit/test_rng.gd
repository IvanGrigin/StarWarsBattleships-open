# Unit tests for src/core/rng/rng.gd against tools/reference/rng_reference.py vectors.
extends "res://tools/test_base.gd"

const Rng := preload("res://src/core/rng/rng.gd")


func _load_golden() -> Dictionary:
	var text := FileAccess.get_file_as_string("res://tests/golden/rng_vectors.json")
	assert_true(text != "", "rng golden file is readable")
	var parsed: Variant = JSON.parse_string(text)
	assert_true(parsed is Dictionary, "rng golden parses to Dictionary")
	if parsed is Dictionary:
		return parsed
	return {}


func run() -> int:
	var golden := _load_golden()

	section("golden vectors: u32 then dice on one continuous stream")
	for key in ["seed_42", "seed_0", "seed_4294967295"]:
		var seed_value: int = key.trim_prefix("seed_").to_int()
		var vectors: Dictionary = golden.get(key, {})
		var rng: Rng = Rng.new(seed_value)
		var u32_out: Array[int] = []
		for i in 8:
			u32_out.append(rng.next_u32())
		for i in 8:
			assert_eq(u32_out[i], int(vectors["u32_first_8"][i]), "%s u32[%d]" % [key, i])
		for i in 8:
			assert_eq(rng.next_die(6), int(vectors["die6_first_8"][i]), "%s die6[%d]" % [key, i])
		for i in 4:
			assert_eq(rng.next_die(4), int(vectors["die4_first_4"][i]), "%s die4[%d]" % [key, i])

	section("same seed gives same sequence")
	var rng_a: Rng = Rng.new(12345)
	var rng_b: Rng = Rng.new(12345)
	for i in 8:
		assert_eq(rng_a.next_u32(), rng_b.next_u32(), "identical stream at %d" % i)

	section("next_below(1) is always 0")
	var rng_c: Rng = Rng.new(777)
	var all_zero := true
	for i in 100:
		if rng_c.next_below(1) != 0:
			all_zero = false
	assert_true(all_zero, "100 calls of next_below(1) all zero")

	section("next_die(6) range")
	var rng_d: Rng = Rng.new(2024)
	var in_range := true
	for i in 1000:
		var value: int = rng_d.next_die(6)
		if value < 1 or value > 6:
			in_range = false
	assert_true(in_range, "1000 d6 rolls within 1..6")

	section("d6 distribution over 1000 rolls")
	var rng_e: Rng = Rng.new(424242)
	var counts := {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
	for i in 1000:
		var rolled: int = rng_e.next_die(6)
		counts[rolled] = int(counts[rolled]) + 1
	for face in [1, 2, 3, 4, 5, 6]:
		assert_true(int(counts[face]) > 30, "face %d count %d > 30" % [face, counts[face]])

	return finish()
