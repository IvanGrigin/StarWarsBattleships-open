# Canonical JSON serialization and FNV-1a 64 state hashing.
# Byte-identical with tools/reference/hash_reference.py:
#   - dictionary keys sorted recursively (insertion order into a fresh Dictionary;
#     verified by test: Godot 4 preserves insertion order with sort_keys=false);
#   - no whitespace, ints as ints, bool as true/false, unicode emitted raw
#     (JSON.stringify does not escape non-ASCII, matching Python ensure_ascii=False).
extends RefCounted

const FNV_OFFSET_BASIS := -3750763034362895579 # 0xCBF29CE484222325 (signed int64, same bits)
const FNV_PRIME := 1099511628211               # 0x00000100000001B3


static func to_canonical(value: Variant) -> String:
	return JSON.stringify(_normalize(value), "", false, true)


static func _normalize(value: Variant) -> Variant:
	if value is Dictionary:
		var out := {}
		var keys: Array = value.keys()
		keys.sort()
		for k: Variant in keys:
			out[k] = _normalize(value[k])
		return out
	if value is Array:
		var out_arr: Array = []
		for v: Variant in value:
			out_arr.append(_normalize(v))
		return out_arr
	return value


## 64x64 unsigned multiplication via 16-bit limbs; partial products <= 2^35, no overflow.
## Works for negative (two's complement) int64 inputs.
static func mul64(a: int, b: int) -> int:
	var a0 := a & 0xFFFF; var a1 := (a >> 16) & 0xFFFF
	var a2 := (a >> 32) & 0xFFFF; var a3 := (a >> 48) & 0xFFFF
	var b0 := b & 0xFFFF; var b1 := (b >> 16) & 0xFFFF
	var b2 := (b >> 32) & 0xFFFF; var b3 := (b >> 48) & 0xFFFF
	var c0 := a0 * b0
	var c1 := (a0 * b1) + (a1 * b0)
	var c2 := (a0 * b2) + (a1 * b1) + (a2 * b0)
	var c3 := (a0 * b3) + (a1 * b2) + (a2 * b1) + (a3 * b0)
	var carry := c1 + (c0 >> 16)
	var l0 := c0 & 0xFFFF; var l1 := carry & 0xFFFF
	carry = c2 + (carry >> 16)
	var l2 := carry & 0xFFFF
	var l3 := (c3 + (carry >> 16)) & 0xFFFF
	return (l3 << 48) | (l2 << 32) | (l1 << 16) | l0


## FNV-1a 64 over UTF-8 bytes; returns 16 UPPERCASE hex characters.
static func fnv1a64_hex(text: String) -> String:
	var bytes := text.to_utf8_buffer()
	var h := FNV_OFFSET_BASIS
	for byte: int in bytes:
		h ^= byte
		h = mul64(h, FNV_PRIME)
	return "%04X%04X%04X%04X" % [(h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF, (h >> 16) & 0xFFFF, h & 0xFFFF]


static func state_hash(snapshot: Dictionary) -> String:
	return fnv1a64_hex(to_canonical(snapshot))
