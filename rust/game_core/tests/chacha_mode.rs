//! Production RNG mode (rust-core-api §5): ChaCha20 determinism per 32-byte
//! seed, shared rejection-sampling die interface, and the network commitment
//! SHA-256 (MASTER_PLAN §7.2, ADR-009).

use game_core::rng::{rng_commitment, DieRng, RngMode};
use rand_core::{RngCore, SeedableRng};
use sha2::{Digest, Sha256};

#[test]
fn chacha20_same_seed_same_sequence() {
    let seed = [0x5Au8; 32];
    let mut a = RngMode::chacha20(seed);
    let mut b = RngMode::chacha20(seed);
    for i in 0..256 {
        assert_eq!(a.next_u32(), b.next_u32(), "u32 #{i}");
    }
    let mut a = RngMode::chacha20(seed);
    let mut b = RngMode::chacha20(seed);
    for i in 0..256 {
        assert_eq!(a.next_die(6), b.next_die(6), "d6 #{i}");
    }
}

#[test]
fn chacha20_differs_across_seeds_and_matches_rand_chacha() {
    let mut a = RngMode::chacha20([1u8; 32]);
    let mut b = RngMode::chacha20([2u8; 32]);
    let (x, y) = (a.next_u32(), b.next_u32());
    assert_ne!(x, y, "distinct seeds diverge immediately");
    // Cross-check the raw stream against rand_chacha directly (pinned version).
    let mut direct = rand_chacha::ChaCha20Rng::from_seed([1u8; 32]);
    assert_eq!(x, direct.next_u32());
}

#[test]
fn chacha20_die_values_in_range_with_unbiased_sampler() {
    let mut rng = RngMode::chacha20([7u8; 32]);
    let mut counts = [0u32; 6];
    for _ in 0..6000 {
        let die = rng.next_die(6);
        assert!((1..=6).contains(&die));
        counts[(die - 1) as usize] += 1;
    }
    for count in counts {
        assert!(
            (800..=1200).contains(&count),
            "d6 face count {count} far from uniform"
        );
    }
    // next_below shared sampler: bound 1 always yields 0.
    assert_eq!(rng.next_below(1), 0);
}

#[test]
fn mode_names_are_pinned() {
    assert_eq!(RngMode::mulberry32(0).mode_name(), "mulberry32_compat");
    assert_eq!(RngMode::chacha20([0u8; 32]).mode_name(), "chacha20");
}

#[test]
fn commitment_is_sha256_of_pinned_prefix_and_fields() {
    let seed = [0x11u8; 32];
    let uuid = [0x22u8; 16];
    let commitment = rng_commitment(&seed, &uuid, "ABCDEF0123456789");
    // Reference value computed independently: SHA-256 over
    // b"swb-rng-v1" || [0x11; 32] || [0x22; 16] || SHA256(b"ABCDEF0123456789").
    let mut hasher = Sha256::new();
    hasher.update(b"swb-rng-v1");
    hasher.update([0x11u8; 32]);
    hasher.update([0x22u8; 16]);
    let ruleset_digest: [u8; 32] = Sha256::digest(b"ABCDEF0123456789").into();
    hasher.update(ruleset_digest);
    let expected: String = hasher
        .finalize()
        .iter()
        .map(|b| format!("{b:02X}"))
        .collect();
    assert_eq!(commitment, expected);
    assert_eq!(commitment.len(), 64);
    // Different uuid -> different commitment.
    assert_ne!(commitment, rng_commitment(&seed, &[0x23u8; 16], "ABCDEF0123456789"));
    // Different ruleset hash -> different commitment.
    assert_ne!(commitment, rng_commitment(&seed, &uuid, "ABCDEF012345678A"));
}
