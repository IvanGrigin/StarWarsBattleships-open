# Unit tests for src/core/hex/hex_math.gd.
extends "res://tools/test_base.gd"

const HexMath := preload("res://src/core/hex/hex_math.gd")
const CardStore := preload("res://src/core/data/card_store.gd")


func _ref_distance(a: Vector2i, b: Vector2i) -> int:
	# Independent cube-formula reference: (|dq| + |dr| + |ds|) / 2, s = -q - r.
	var dq: int = b.x - a.x
	var dr: int = b.y - a.y
	var ds: int = -dq - dr
	return (absi(dq) + absi(dr) + absi(ds)) / 2


func run() -> int:
	section("in_board with the v3.2 data radius (ADR-015: board.json radius 3)")
	var data_radius := int(CardStore.board()["radius"])
	assert_eq(data_radius, 3, "board.json pins radius 3")
	assert_true(HexMath.in_board(Vector2i(0, 0), data_radius), "center inside")
	assert_true(HexMath.in_board(Vector2i(0, 3), data_radius), "(0,3) inside")
	assert_true(HexMath.in_board(Vector2i(3, -3), data_radius), "(3,-3) inside")
	assert_true(HexMath.in_board(Vector2i(-3, 3), data_radius), "(-3,3) inside")
	assert_true(HexMath.in_board(Vector2i(3, 0), data_radius), "(3,0) inside")
	assert_true(HexMath.in_board(Vector2i(0, -3), data_radius), "(0,-3) inside")
	assert_true(HexMath.in_board(Vector2i(-3, 0), data_radius), "(-3,0) inside")
	assert_true(HexMath.in_board(Vector2i(1, 2), data_radius), "(1,2) inside (s=-3)")
	assert_true(not HexMath.in_board(Vector2i(0, 4), data_radius), "(0,4) outside")
	assert_true(not HexMath.in_board(Vector2i(4, 0), data_radius), "(4,0) outside")
	assert_true(not HexMath.in_board(Vector2i(-3, -1), data_radius), "(-3,-1) outside (s=4)")
	assert_true(not HexMath.in_board(Vector2i(2, 2), data_radius), "(2,2) outside (s=-4)")

	section("board cell count for the data radius")
	var count := 0
	for q in range(-data_radius, data_radius + 1):
		for r in range(-data_radius, data_radius + 1):
			if HexMath.in_board(Vector2i(q, r), data_radius):
				count += 1
	assert_eq(count, 37, "radius 3 board has 37 cells")
	assert_eq(count, int(CardStore.board()["cell_count"]),
			"cell count matches board.json cell_count")

	section("in_board honors an explicit radius (parameterized, not hardcoded)")
	assert_true(HexMath.in_board(Vector2i(0, 4), 4), "(0,4) inside for radius 4")
	assert_true(not HexMath.in_board(Vector2i(0, 4), 3), "(0,4) outside for radius 3")
	assert_true(HexMath.in_board(Vector2i(0, 2), 2), "(0,2) inside for radius 2")
	assert_true(not HexMath.in_board(Vector2i(0, 3), 2), "(0,3) outside for radius 2")

	section("distance")
	assert_eq(HexMath.distance(Vector2i(0, 0), Vector2i(0, 4)), 4, "(0,0)-(0,4)")
	assert_eq(HexMath.distance(Vector2i(0, 0), Vector2i(4, -4)), 4, "(0,0)-(4,-4)")
	assert_eq(_ref_distance(Vector2i(2, -1), Vector2i(-1, 2)), 3, "reference formula gives 3")
	assert_eq(HexMath.distance(Vector2i(2, -1), Vector2i(-1, 2)), _ref_distance(Vector2i(2, -1), Vector2i(-1, 2)), "(2,-1)-(-1,2) matches reference")
	assert_eq(HexMath.distance(Vector2i(3, 1), Vector2i(-2, -3)), _ref_distance(Vector2i(3, 1), Vector2i(-2, -3)), "far pair matches reference")
	assert_eq(HexMath.distance(Vector2i(1, -2), Vector2i(1, -2)), 0, "zero distance")
	for a_q in range(-4, 5):
		for a_r in range(-4, 5):
			for b_q in range(-4, 5):
				for b_r in range(-4, 5):
					var a := Vector2i(a_q, a_r)
					var b := Vector2i(b_q, b_r)
					assert_eq(HexMath.distance(a, b), _ref_distance(a, b), "sweep distance matches reference")

	section("neighbors order")
	var center := Vector2i(2, -1)
	var neigh := HexMath.neighbors(center)
	assert_eq(neigh.size(), 6, "6 neighbors")
	for i in 6:
		assert_eq(neigh[i], center + HexMath.DIR_DELTAS[i], "neighbor %d follows DIR_DELTAS" % i)

	section("direction_delta and step")
	for i in 6:
		assert_eq(HexMath.direction_delta(i), HexMath.DIR_DELTAS[i], "delta %d" % i)
		assert_eq(HexMath.step(center, i), center + HexMath.DIR_DELTAS[i], "step %d" % i)

	section("rotate")
	assert_eq(HexMath.rotate(5, 1), 0, "rotate(5,1)")
	assert_eq(HexMath.rotate(0, -1), 5, "rotate(0,-1)")
	assert_eq(HexMath.rotate(2, 6), 2, "rotate(2,6) full circle")
	assert_eq(HexMath.rotate(3, -1), 2, "rotate(3,-1)")
	assert_eq(HexMath.rotate(0, 0), 0, "rotate(0,0)")

	section("direction_from")
	for i in 6:
		var cell := Vector2i(-1, 2)
		assert_eq(HexMath.direction_from(cell, HexMath.step(cell, i)), i, "neighbor direction %d" % i)
	assert_eq(HexMath.direction_from(Vector2i(0, 0), Vector2i(1, 1)), -1, "non-neighbor gives -1")
	assert_eq(HexMath.direction_from(Vector2i(0, 0), Vector2i(0, 2)), -1, "distance-2 cell gives -1")
	assert_eq(HexMath.direction_from(Vector2i(0, 0), Vector2i(0, 0)), -1, "same cell gives -1")

	section("sector_index")
	assert_eq(HexMath.sector_index(0, 1), 1, "facing 0, target NE -> FR")
	assert_eq(HexMath.sector_index(0, 3), 3, "facing 0, target S -> B")
	assert_eq(HexMath.sector_index(2, 1), 5, "(2,1) -> FL")
	assert_eq(HexMath.sector_index(0, 0), 0, "target straight ahead -> F")
	assert_eq(HexMath.sector_index(1, 0), 5, "negative diff wraps to 5")
	assert_eq(HexMath.SECTOR_NAMES[1], "FR", "sector name 1")
	assert_eq(HexMath.SECTOR_NAMES[3], "B", "sector name 3")
	assert_eq(HexMath.SECTOR_NAMES[5], "FL", "sector name 5")

	section("sector rotation invariance")
	# Rotating the whole situation (facing and dir_to_target by the same amount)
	# must not change the sector. All 36 (facing, dir) combinations, rotations 1..5.
	for facing in 6:
		for dir in 6:
			var base: int = HexMath.sector_index(facing, dir)
			for rot in range(1, 6):
				var rotated: int = HexMath.sector_index(HexMath.rotate(facing, rot), HexMath.rotate(dir, rot))
				assert_eq(rotated, base, "sector preserved: facing=%d dir=%d rot=%d" % [facing, dir, rot])

	return finish()
