# Pointy-top hex grid math. Axial coordinates Vector2i(q, r), cube sub-coordinate s = -q - r.
# Directions 0..5 clockwise starting from north. Single source of truth: DIR_DELTAS.
extends RefCounted

const DIR_DELTAS: Array[Vector2i] = [
	Vector2i(0, -1),   # 0: N  (вперёд при facing=0)
	Vector2i(1, -1),   # 1: NE
	Vector2i(1, 0),    # 2: SE
	Vector2i(0, 1),    # 3: S
	Vector2i(-1, 1),   # 4: SW
	Vector2i(-1, 0),   # 5: NW
]

## По часовой стрелке от переда; arc_modifiers карточек индексируются этим же порядком.
const SECTOR_NAMES: Array[String] = ["F", "FR", "BR", "B", "BL", "FL"]


static func in_board(cell: Vector2i, radius: int = 4) -> bool:
	var s := -cell.x - cell.y
	return maxi(maxi(absi(cell.x), absi(cell.y)), absi(s)) <= radius


static func neighbors(cell: Vector2i) -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	for d: Vector2i in DIR_DELTAS:
		out.append(cell + d)
	return out


static func direction_delta(dir: int) -> Vector2i:
	return DIR_DELTAS[dir]


static func step(cell: Vector2i, dir: int) -> Vector2i:
	return cell + DIR_DELTAS[dir]


static func distance(a: Vector2i, b: Vector2i) -> int:
	var dq := b.x - a.x
	var dr := b.y - a.y
	var ds := -dq - dr
	return (absi(dq) + absi(dr) + absi(ds)) / 2


static func rotate(dir: int, steps: int) -> int:
	return posmod(dir + steps, 6)


static func direction_from(from: Vector2i, to: Vector2i) -> int:
	var delta := to - from
	for i in DIR_DELTAS.size():
		if DIR_DELTAS[i] == delta:
			return i
	return -1


static func sector_index(facing: int, dir_to_target: int) -> int:
	return posmod(dir_to_target - facing, 6)
