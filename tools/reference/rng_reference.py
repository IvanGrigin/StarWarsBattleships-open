#!/usr/bin/env python3
"""Reference mulberry32 RNG — bitwise-identical to src/core/rng/rng.gd.

All values are kept in [0, 2**32) after every operation (mask & 0xFFFFFFFF).
Prints golden vectors as JSON to stdout:
    python3 tools/reference/rng_reference.py > tests/golden/rng_vectors.json
"""

import json

MASK32 = 0xFFFFFFFF


def _mul32(a: int, b: int) -> int:
    a0 = a & 0xFFFF
    a1 = (a >> 16) & 0xFFFF
    b0 = b & 0xFFFF
    b1 = (b >> 16) & 0xFFFF
    return ((((a0 * b1) + (a1 * b0)) << 16) + (a0 * b0)) & MASK32


class Rng:
    """Same state machine as src/core/rng/rng.gd (mulberry32)."""

    def __init__(self, seed_value: int) -> None:
        self.state = seed_value & MASK32

    def next_u32(self) -> int:
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = _mul32(self.state ^ (self.state >> 16), 0x00000001 | self.state)
        t = (((t + _mul32(t ^ (t >> 7), 0x0000003D | t)) & MASK32) ^ t) & MASK32
        return (t ^ (t >> 14)) & MASK32

    def next_below(self, bound: int) -> int:
        assert bound > 0
        modulus = 4294967296 - (4294967296 % bound)
        while True:
            x = self.next_u32()
            if x < modulus:
                return x % bound

    def next_die(self, sides: int) -> int:
        return self.next_below(sides) + 1


SEEDS = [42, 0, 4294967295]


def vectors_for(seed: int) -> dict:
    rng = Rng(seed)
    # u32 first, then die6 and die4 continue the SAME stream.
    return {
        "u32_first_8": [rng.next_u32() for _ in range(8)],
        "die6_first_8": [rng.next_die(6) for _ in range(8)],
        "die4_first_4": [rng.next_die(4) for _ in range(4)],
    }


def main() -> None:
    print(json.dumps({f"seed_{seed}": vectors_for(seed) for seed in SEEDS}))


if __name__ == "__main__":
    main()
