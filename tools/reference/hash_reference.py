#!/usr/bin/env python3
"""Reference canonical JSON + FNV-1a 64 hash — byte-identical to
src/core/serialization/canonical.gd.

Canonical form: recursive normalization (dict keys sorted, arrays kept in
order), then json.dumps with separators=(",", ":") and ensure_ascii=False
(Godot JSON.stringify emits non-ASCII raw as well).
Prints golden vectors as JSON to stdout:
    python3 tools/reference/hash_reference.py > tests/golden/hash_vectors.json
"""

import json

MASK64 = 0xFFFFFFFFFFFFFFFF
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 1099511628211


def to_canonical(value):
    """Recursive normalization: dict -> new dict with sorted keys; list -> list."""
    if isinstance(value, dict):
        return {key: to_canonical(value[key]) for key in sorted(value.keys())}
    if isinstance(value, list):
        return [to_canonical(item) for item in value]
    return value


def canonical_dumps(value) -> str:
    return json.dumps(to_canonical(value), separators=(",", ":"), ensure_ascii=False)


def fnv1a64_hex(text: str) -> str:
    h = FNV_OFFSET
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & MASK64
    return "%016X" % h


# Inputs are already canonical strings (applied by hand in these examples).
INPUTS = [
    "",
    "{}",
    "{\"a\":1}",
    "{\"ships\":[{\"hp\":4,\"id\":\"A1_tie_fighter_0\"}]}",
    "русская строка",
]


def main() -> None:
    print(json.dumps(
        {"inputs": INPUTS, "hashes": [fnv1a64_hex(s) for s in INPUTS]},
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
