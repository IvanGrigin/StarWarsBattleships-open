# Deterministic mulberry32 RNG. State is 32 bits. 32x32 multiplication is done
# through 16-bit limbs (GDScript int64 is signed, a direct product overflows).
extends RefCounted

var _state: int


func _init(seed_value: int) -> void:
	_state = seed_value & 0xFFFFFFFF


static func _mul32(a: int, b: int) -> int:
	var a0 := a & 0xFFFF
	var a1 := (a >> 16) & 0xFFFF
	var b0 := b & 0xFFFF
	var b1 := (b >> 16) & 0xFFFF
	return ((((a0 * b1) + (a1 * b0)) << 16) + (a0 * b0)) & 0xFFFFFFFF


func next_u32() -> int:
	_state = (_state + 0x6D2B79F5) & 0xFFFFFFFF
	var t := _mul32(_state ^ (_state >> 16), 0x00000001 | _state)
	t = (((t + _mul32(t ^ (t >> 7), 0x0000003D | t)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
	return (t ^ (t >> 14)) & 0xFFFFFFFF


## Uniformly 0..bound-1, rejection sampling.
func next_below(bound: int) -> int:
	assert(bound > 0)
	var modulus := 4294967296 - (4294967296 % bound)
	while true:
		var x := next_u32()
		if x < modulus:
			return x % bound
	return -1 # недостижимо, для анализатора


## Die roll 1..sides. Dice CONSUMPTION ORDER is part of the rules.
func next_die(sides: int) -> int:
	return next_below(sides) + 1
