//! Pointy-top hex grid math (core-api §1). Axial coordinates `(q, r)`,
//! cube sub-coordinate `s = -q - r`. Directions 0..5 clockwise starting from
//! north. Bit-compatible with `src/core/hex/hex_math.gd`.

pub type Axial = (i32, i32);

pub const DIR_DELTAS: [Axial; 6] = [
    (0, -1), // 0: N  (forward at facing=0)
    (1, -1), // 1: NE
    (1, 0),  // 2: SE
    (0, 1),  // 3: S
    (-1, 1), // 4: SW
    (-1, 0), // 5: NW
];

/// Clockwise from the bow; `arc_modifiers` of ship cards are indexed by this order.
pub const SECTOR_NAMES: [&str; 6] = ["F", "FR", "BR", "B", "BL", "FL"];

pub const DEFAULT_RADIUS: i32 = 4;

#[inline]
pub fn in_board(q: i32, r: i32, radius: i32) -> bool {
    let s = -q - r;
    q.abs().max(r.abs()).max(s.abs()) <= radius
}

/// The 6 neighbors in DIR_DELTAS order.
#[inline]
pub fn neighbors(q: i32, r: i32) -> [Axial; 6] {
    let mut out = [(0, 0); 6];
    for (i, (dq, dr)) in DIR_DELTAS.iter().enumerate() {
        out[i] = (q + dq, r + dr);
    }
    out
}

/// `dir` is expected to be 0..5 (core-api §1: the single delta table).
#[inline]
pub fn direction_delta(dir: usize) -> Axial {
    DIR_DELTAS[dir]
}

#[inline]
pub fn step(q: i32, r: i32, dir: usize) -> Axial {
    let (dq, dr) = DIR_DELTAS[dir];
    (q + dq, r + dr)
}

#[inline]
pub fn distance(aq: i32, ar: i32, bq: i32, br: i32) -> i32 {
    let dq = bq - aq;
    let dr = br - ar;
    let ds = -dq - dr;
    (dq.abs() + dr.abs() + ds.abs()) / 2
}

/// `(dir + steps) mod 6`; steps may be negative (posmod semantics).
#[inline]
pub fn rotate(dir: i32, steps: i32) -> i32 {
    (dir + steps).rem_euclid(6)
}

/// Index of the delta `(to - from)` among DIR_DELTAS; -1 when not neighbors.
#[inline]
pub fn direction_from(fq: i32, fr: i32, tq: i32, tr: i32) -> i32 {
    let dq = tq - fq;
    let dr = tr - fr;
    for (i, (a, b)) in DIR_DELTAS.iter().enumerate() {
        if *a == dq && *b == dr {
            return i as i32;
        }
    }
    -1
}

/// `(dir_to_target - facing) mod 6`.
#[inline]
pub fn sector_index(facing: i32, dir_to_target: i32) -> i32 {
    (dir_to_target - facing).rem_euclid(6)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn board_radius_4_has_61_cells() {
        let mut count = 0;
        for q in -6..=6 {
            for r in -6..=6 {
                if in_board(q, r, 4) {
                    count += 1;
                    assert!(q.abs() <= 4 && r.abs() <= 4 && (-q - r).abs() <= 4);
                }
            }
        }
        assert_eq!(count, 61);
        assert!(in_board(0, 4, 4));
        assert!(in_board(-4, 4, 4));
        assert!(in_board(4, -4, 4));
        assert!(!in_board(0, 5, 4));
        assert!(!in_board(-4, 5, 4));
        assert!(!in_board(5, -4, 4));
    }

    #[test]
    fn distances_match_axial_formula() {
        assert_eq!(distance(0, 0, 0, 0), 0);
        assert_eq!(distance(0, 4, 0, -4), 8);
        assert_eq!(distance(0, 0, 2, -1), 2);
        assert_eq!(distance(-4, 4, 4, -4), 8);
        assert_eq!(distance(1, 3, 0, -3), 7);
        // symmetric
        assert_eq!(distance(2, -2, -1, 3), distance(-1, 3, 2, -2));
    }

    #[test]
    fn direction_from_and_step_roundtrip() {
        for (dir, &(dq, dr)) in DIR_DELTAS.iter().enumerate() {
            assert_eq!(direction_from(0, 0, dq, dr), dir as i32);
            assert_eq!(step(3, -2, dir), (3 + dq, -2 + dr));
        }
        assert_eq!(direction_from(0, 0, 2, -1), -1);
        assert_eq!(direction_from(1, 1, 1, 1), -1);
    }

    #[test]
    fn rotate_wraps_posmod() {
        assert_eq!(rotate(0, 1), 1);
        assert_eq!(rotate(5, 1), 0);
        assert_eq!(rotate(0, -1), 5);
        assert_eq!(rotate(2, -3), 5);
        assert_eq!(rotate(3, 9), 0);
        assert_eq!(rotate(0, -7), 5);
    }

    #[test]
    fn sectors_cover_all_36_combinations() {
        // sector_index(facing, dir) == (dir - facing) mod 6, exactly as hex_math.gd.
        for facing in 0..6i32 {
            for dir in 0..6i32 {
                let expected = (dir - facing).rem_euclid(6);
                assert_eq!(sector_index(facing, dir), expected);
            }
        }
        assert_eq!(sector_index(0, 1), 1); // facing N, enemy NE -> FR
        assert_eq!(sector_index(0, 3), 3); // enemy behind -> B
    }

    #[test]
    fn neighbors_follow_delta_table_order() {
        let n = neighbors(1, 1);
        for (i, cell) in n.iter().enumerate() {
            assert_eq!(*cell, step(1, 1, i));
        }
    }
}
