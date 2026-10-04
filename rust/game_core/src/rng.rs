//! Deterministic RNG (core-api §2, rust-core-api §5).
//!
//! Two modes:
//! - `Mulberry32Compat` — bit-for-bit mulberry32 as `src/core/rng/rng.gd`
//!   (differential oracle mode). In Rust this is plain `u32` wrapping
//!   arithmetic: the 16-bit limb scheme of GDScript computes the same values
//!   as `wrapping_mul` mod 2^32.
//! - `ChaCha20` — production mode over `rand_chacha::ChaCha20Rng` seeded from
//!   32 bytes of OS CSPRNG (seed_from_u64 is deliberately not exposed).
//!
//! Both share the same modulo-bias-free sampler: `modulus = 2^32 - (2^32 mod
//! bound)`, rejection sampling; `next_die(s) = next_below(s) + 1`.

use rand_chacha::ChaCha20Rng;
use rand_core::{RngCore, SeedableRng};
use sha2::{Digest, Sha256};

/// Common die-drawing interface. Dice consumption order is part of the rules.
pub trait DieRng {
    fn next_u32(&mut self) -> u32;

    /// Uniformly 0..bound-1 via rejection sampling (no modulo bias).
    fn next_below(&mut self, bound: u32) -> u32 {
        assert!(bound > 0, "next_below: bound must be > 0");
        let two_pow_32: u64 = 1 << 32;
        let modulus = two_pow_32 - (two_pow_32 % u64::from(bound));
        loop {
            let x = u64::from(self.next_u32());
            if x < modulus {
                return (x % u64::from(bound)) as u32;
            }
        }
    }

    /// Die 1..sides. Consumption order is part of the rules (core-api §2).
    fn next_die(&mut self, sides: u32) -> u32 {
        self.next_below(sides) + 1
    }
}

/// mulberry32, bit-identical to `src/core/rng/rng.gd` (state is 32 bits).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Mulberry32Compat {
    state: u32,
}

impl Mulberry32Compat {
    /// Seeds with the low 32 bits (GDScript: `seed_value & 0xFFFFFFFF`).
    pub fn new(seed: u64) -> Self {
        Self {
            state: seed as u32,
        }
    }

    #[inline]
    fn mul32(a: u32, b: u32) -> u32 {
        a.wrapping_mul(b)
    }
}

impl DieRng for Mulberry32Compat {
    #[inline]
    fn next_u32(&mut self) -> u32 {
        self.state = self.state.wrapping_add(0x6D2B79F5);
        let s = self.state;
        let mut t = Self::mul32(s ^ (s >> 16), 0x00000001 | s);
        t = Self::mul32(t ^ (t >> 7), 0x0000003D | t).wrapping_add(t) ^ t;
        t ^ (t >> 14)
    }
}

/// Production source: ChaCha20 seeded from 32 bytes (OS CSPRNG on the server).
#[derive(Clone)]
pub struct ChaCha20Source {
    inner: ChaCha20Rng,
}

impl ChaCha20Source {
    pub fn from_seed(seed: [u8; 32]) -> Self {
        Self {
            inner: ChaCha20Rng::from_seed(seed),
        }
    }
}

impl DieRng for ChaCha20Source {
    #[inline]
    fn next_u32(&mut self) -> u32 {
        self.inner.next_u32()
    }
}

impl std::fmt::Debug for ChaCha20Source {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("ChaCha20Source(<secret>)")
    }
}

/// RNG mode fixed in `create_match` config; default for v3-experimental is
/// `Mulberry32Compat` (rust-core-api §5).
#[derive(Debug, Clone)]
pub enum RngMode {
    Mulberry32Compat(Mulberry32Compat),
    Chacha20(ChaCha20Source),
}

impl RngMode {
    pub fn mulberry32(seed: u64) -> Self {
        RngMode::Mulberry32Compat(Mulberry32Compat::new(seed))
    }

    pub fn chacha20(seed: [u8; 32]) -> Self {
        RngMode::Chacha20(ChaCha20Source::from_seed(seed))
    }

    pub fn mode_name(&self) -> &'static str {
        match self {
            RngMode::Mulberry32Compat(_) => "mulberry32_compat",
            RngMode::Chacha20(_) => "chacha20",
        }
    }
}

impl DieRng for RngMode {
    fn next_u32(&mut self) -> u32 {
        match self {
            RngMode::Mulberry32Compat(r) => r.next_u32(),
            RngMode::Chacha20(r) => r.next_u32(),
        }
    }
}

/// Network honesty commitment (MASTER_PLAN §7.2, ADR-009):
/// `SHA-256("swb-rng-v1" || seed_32 || match_uuid_16 || ruleset_digest_32)`,
/// fixed field lengths and order. `ruleset_digest_32` is the SHA-256 of the
/// UTF-8 `ruleset_hash` hex string (the 64-bit FNV hash serialized to a
/// fixed-width digest). Returned as 64 uppercase hex characters.
pub fn rng_commitment(
    seed32: &[u8; 32],
    match_uuid16: &[u8; 16],
    ruleset_hash_hex: &str,
) -> String {
    let ruleset_digest: [u8; 32] = Sha256::digest(ruleset_hash_hex.as_bytes()).into();
    let mut hasher = Sha256::new();
    hasher.update(b"swb-rng-v1");
    hasher.update(seed32);
    hasher.update(match_uuid16);
    hasher.update(ruleset_digest);
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest {
        out.push_str(&format!("{:02X}", byte));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mulberry32_matches_golden_first_values() {
        // Prefix of tests/golden/rng_vectors.json (seed 42) — full file is
        // checked in tests/golden_rng.rs.
        let mut rng = Mulberry32Compat::new(42);
        assert_eq!(rng.next_u32(), 4188581575);
        assert_eq!(rng.next_u32(), 3801168510);
    }

    #[test]
    fn next_below_rejects_zero() {
        let mut rng = Mulberry32Compat::new(1);
        let result = std::panic::catch_unwind(move || rng.next_below(0));
        assert!(result.is_err());
    }

    #[test]
    fn next_die_range_and_uniformity_smoke() {
        let mut rng = Mulberry32Compat::new(7);
        for _ in 0..1000 {
            let die = rng.next_die(6);
            assert!((1..=6).contains(&die));
        }
        let mut rng = Mulberry32Compat::new(7);
        for _ in 0..1000 {
            let v = rng.next_below(1);
            assert_eq!(v, 0); // bound 1: modulus 2^32, always accepted, x % 1 == 0
        }
    }

    #[test]
    fn chacha20_is_deterministic_per_seed() {
        let mut a = ChaCha20Source::from_seed([9u8; 32]);
        let mut b = ChaCha20Source::from_seed([9u8; 32]);
        for _ in 0..64 {
            assert_eq!(a.next_u32(), b.next_u32());
        }
        let mut c = ChaCha20Source::from_seed([10u8; 32]);
        let x = a.next_u32();
        let y = c.next_u32();
        assert_ne!(x, y);
    }

    #[test]
    fn commitment_is_stable_hex() {
        let c1 = rng_commitment(&[1u8; 32], &[2u8; 16], "ABC");
        let c2 = rng_commitment(&[1u8; 32], &[2u8; 16], "ABC");
        assert_eq!(c1, c2);
        assert_eq!(c1.len(), 64);
        assert!(c1.chars().all(|ch| ch.is_ascii_hexdigit()));
        let c3 = rng_commitment(&[1u8; 32], &[3u8; 16], "ABC");
        assert_ne!(c1, c3);
    }
}
