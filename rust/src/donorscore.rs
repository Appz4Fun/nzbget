//! DonorScore: the DupeScore offsets of duplicates (donors and backups) under a
//! pick, as daemon/dupesearch/DonorScore.cpp gave them.
//!
//! Rounding is the C++ `std::nearbyint` in the default mode: halves go to even.

/// The score of a posting known dead.
pub const DEAD: i32 = 1;
/// The highest donor offset.
pub const TOP: i32 = 90;

/// The base of the donor scores under a pick with this score.
pub fn base(pick_score: i32) -> i32 {
    pick_score.wrapping_sub(1000).max(0)
}

/// The offset for a posting alive by this share (negative: unknown, taken as
/// whole): 9 + 80 * share, one more for a byte-identical twin, at most TOP.
pub fn target(alive: f64, twin: bool) -> i32 {
    // std::min(1.0, alive): 1.0 unless alive < 1.0 (NaN keeps 1.0)
    let share = if alive < 0.0 { 1.0 } else if alive < 1.0 { alive } else { 1.0 };
    TOP.min(9 + (80.0 * share).round_ties_even() as i32 + i32::from(twin))
}

/// One duplicate as Rerank sees it.
#[derive(Clone, Copy, Debug, Default)]
pub struct Entry {
    pub score: i32,
    pub alive: f64,
    pub twin: bool,
    pub bytes: i64,
    pub grabs: i32,
}

/// The offsets for the live entries once every check is in: most alive first
/// (whole percent), then twin, closest to `pick_bytes`, most grabbed; strictly
/// falling, each at most its target. Entries scored DEAD (or less) keep their
/// score. Parallel to `entries`.
pub fn rerank(entries: &[Entry], pick_bytes: i64) -> Vec<i32> {
    let mut scores: Vec<i32> = entries.iter().map(|e| e.score).collect();
    let mut live: Vec<usize> = (0..entries.len()).filter(|&i| entries[i].score > DEAD).collect();
    let percent = |e: &Entry| (100.0 * if e.alive < 0.0 { 1.0 } else { e.alive }).round_ties_even() as i32;
    let distance = |e: &Entry| {
        if e.bytes > pick_bytes { e.bytes.wrapping_sub(pick_bytes) } else { pick_bytes.wrapping_sub(e.bytes) }
    };
    // std::stable_sort with the C++ comparator: a stable sort keeps equal entries in order
    live.sort_by(|&a, &b| {
        let (x, y) = (&entries[a], &entries[b]);
        percent(y)
            .cmp(&percent(x))
            .then_with(|| y.twin.cmp(&x.twin))
            .then_with(|| distance(x).cmp(&distance(y)))
            .then_with(|| y.grabs.cmp(&x.grabs))
    });
    let mut previous = 100;
    for i in live {
        let want = (DEAD + 1).max(target(entries[i].alive, entries[i].twin).min(previous - 1));
        previous = want;
        scores[i] = want;
    }
    scores
}

#[cfg(test)]
mod tests {
    use super::*;

    fn e(score: i32, alive: f64, twin: bool, bytes: i64, grabs: i32) -> Entry {
        Entry { score, alive, twin, bytes, grabs }
    }

    #[test]
    fn base_never_below_zero() {
        assert_eq!(base(1_000_000), 999_000);
        assert_eq!(base(500), 0);
    }

    #[test]
    fn target_rounds_halves_to_even_and_caps() {
        assert_eq!(target(1.0, false), 89);
        assert_eq!(target(1.0, true), 90);
        assert_eq!(target(-1.0, false), 89);
        assert_eq!(target(0.5, false), 49);
        assert_eq!(target(0.0125 * 0.5, false), 9); // 80 * share = 0.5 rounds to 0
        assert_eq!(target(f64::NAN, false), 89);
    }

    #[test]
    fn rerank_orders_by_health_then_twin_then_size_then_grabs() {
        let entries = [e(50, 0.9, false, 100, 0), e(50, 1.0, false, 300, 0), e(1, 1.0, false, 100, 0),
                       e(50, 1.0, true, 300, 0), e(50, 1.0, false, 100, 5)];
        assert_eq!(rerank(&entries, 100), vec![81, 88, 1, 90, 89]);
    }
}
