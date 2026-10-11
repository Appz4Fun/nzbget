//! Pure queue/history discovery policy. Callers hold their queue lock, supply a
//! stable time and persist search stamps only after a Search decision.
use std::sync::atomic::{AtomicUsize, Ordering};

pub const ENABLED: u32 = 1 << 0;
pub const DUPE_CHECK: u32 = 1 << 1;
pub const PRESENT: u32 = 1 << 2;
pub const NZB: u32 = 1 << 3;
pub const HISTORY: u32 = 1 << 4;
pub const SUCCESS: u32 = 1 << 5;
pub const DELETING: u32 = 1 << 6;
pub const DELETE_NONE: u32 = 1 << 7;
pub const DELETE_MANUAL: u32 = 1 << 8;
pub const DELETE_DUPE: u32 = 1 << 9;
pub const DELETE_COPY: u32 = 1 << 10;
pub const DELETE_GOOD: u32 = 1 << 11;
pub const POST_PROCESS: u32 = 1 << 12;
pub const SCORE_MODE: u32 = 1 << 13;
pub const DONOR: u32 = 1 << 14;
pub const AUTO_REDOWNLOAD: u32 = 1 << 15;
pub const MANAGED_FLEET: u32 = 1 << 16;
pub const BASE_PICK_SCORE: i32 = 1_000_000;
pub const SEARCH_WINDOW_SEC: i64 = 6 * 3600;

#[repr(u32)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Decision {
    Skip = 0,
    RetryPostProcess = 1,
    Search = 2,
}

#[derive(Clone, Copy, Debug)]
pub struct SearchStamp {
    pub score: i32,
    pub time: i64,
}

/// Higher-score selection is performed separately so integrations can preserve
/// the legacy live-only policy or enable the historical proxy enhancement.
pub fn decide(
    flags: u32,
    score: i32,
    higher_score: Option<i32>,
    now: i64,
    previous: Option<SearchStamp>,
    identity_changed: bool,
) -> Decision {
    let required = ENABLED | DUPE_CHECK | PRESENT | NZB;
    if flags & required != required {
        return Decision::Skip;
    }
    if flags & HISTORY != 0 {
        if flags & (SUCCESS | DELETE_MANUAL | DELETE_DUPE | DELETE_COPY | DELETE_GOOD) != 0 {
            return Decision::Skip;
        }
    } else {
        if flags & DELETING != 0 || flags & DELETE_NONE == 0 {
            return Decision::Skip;
        }
        if flags & POST_PROCESS != 0 {
            return Decision::RetryPostProcess;
        }
    }
    if flags & SCORE_MODE == 0 || flags & (DONOR | AUTO_REDOWNLOAD | MANAGED_FLEET) != 0 {
        return Decision::Skip;
    }
    if higher_score.is_some_and(|other| other > score) {
        return Decision::Skip;
    }
    if !identity_changed && recent_search_suppressed(score, now, previous) {
        return Decision::Skip;
    }
    Decision::Search
}

pub fn recent_search_suppressed(score: i32, now: i64, previous: Option<SearchStamp>) -> bool {
    previous.is_some_and(|stamp| {
        now.saturating_sub(stamp.time) < SEARCH_WINDOW_SEC
            && stamp.score >= score.max(BASE_PICK_SCORE)
    })
}

/// A snapshot carries the effective, normalized identity computed by the
/// release-name parser; this module does not guess at title identity.
#[derive(Clone, Copy, Debug)]
pub struct Snapshot<'a> {
    pub id: i32,
    pub key: &'a [u8],
    pub score: i32,
    pub flags: u32,
}
pub fn higher_score(
    pick: Snapshot<'_>,
    others: &[Snapshot<'_>],
    include_history: bool,
) -> Option<i32> {
    others
        .iter()
        .filter(|other| {
            other.id != pick.id
                && other.flags & (PRESENT | NZB) == PRESENT | NZB
                && other.key.eq_ignore_ascii_case(pick.key)
                && other.score > pick.score
                && other.flags & (DELETING | DELETE_MANUAL | DELETE_COPY) == 0
                && if other.flags & HISTORY != 0 {
                    include_history
                } else {
                    other.flags & DELETE_NONE != 0
                }
        })
        .map(|other| other.score)
        .max()
}

/// Compare persisted normalized title/key with current normalized title/key.
/// Update the persisted identity on Search so a rename is retried only once.
pub fn identity_changed(previous: Option<(&[u8], &[u8])>, current: (&[u8], &[u8])) -> bool {
    previous.is_some_and(|old| old.0 != current.0 || !old.1.eq_ignore_ascii_case(current.1))
}

/// Additional broad listing queries; every resulting donor still needs identity verification.
pub fn lenient_queries(title: &[u8]) -> Vec<Vec<u8>> {
    let mut attrs = crate::releasename::parse(title);
    attrs.seasons.dedup();
    attrs.episodes.dedup();
    if attrs.title.is_empty() {
        return Vec::new();
    }
    let normalized = crate::releasename::normalize(title);
    let mut joined = Vec::new();
    let mut bare = Vec::new();
    for token in normalized
        .split(|b| !b.is_ascii_alphanumeric())
        .filter(|t| !t.is_empty())
    {
        joined.extend_from_slice(token);
        if !attrs.title.starts_with(&joined) {
            break;
        }
        if !bare.is_empty() {
            bare.push(b' ');
        }
        bare.extend_from_slice(token);
        if joined == attrs.title {
            break;
        }
    }
    if joined != attrs.title {
        bare = attrs.title.clone();
    }
    let mut detailed = bare.clone();
    for (index, season) in attrs.seasons.iter().enumerate() {
        detailed.extend_from_slice(format!(" s{season:02}").as_bytes());
        // An episode list belongs to the sole season; multiple seasons are season-pack queries.
        if attrs.seasons.len() == 1 && index == 0 {
            for episode in &attrs.episodes {
                detailed.extend_from_slice(format!("e{episode:02}").as_bytes());
            }
        }
    }
    if attrs.seasons.len() != 1 {
        for episode in &attrs.episodes {
            detailed.extend_from_slice(format!(" e{episode:02}").as_bytes());
        }
    }
    if attrs.year > 0 {
        detailed.extend_from_slice(format!(" {}", attrs.year).as_bytes());
    }
    let mut queries = vec![bare];
    if detailed != queries[0] {
        queries.push(detailed);
    }
    queries
}

/// Provider outages and unknown health alone are not evidence of a failing pick.
pub fn should_expand(pick_alive: f64, missing: i32, failed: bool, whole_backup: bool) -> bool {
    !whole_backup
        && (failed
            || (pick_alive.is_finite() && pick_alive >= 0.0 && pick_alive < 0.85 && missing >= 5))
}

/// Listed and reliably inferred total parts of one NZB file.
pub fn part_counts(parts: &[(i64, i64)], declared: u32, parity: bool) -> (u64, u64) {
    const MAX_PART: i64 = 200_000;
    let listed = parts.len() as u64;
    let numbered = parts.iter().all(|&(n, _)| (1..=MAX_PART).contains(&n));
    let last = parts.iter().copied().max();
    let fallback = if numbered {
        listed.max(last.map_or(0, |p| p.0 as u64))
    } else {
        listed
    };
    if parity
        || parts.len() < 2
        || !numbered
        || declared == 0
        || i64::from(declared) > MAX_PART
        || listed * 3 >= u64::from(declared) * 2
        || parts.iter().any(|p| p.1 <= 0)
    {
        return (listed, fallback);
    }
    let (last_no, last_bytes) = last.unwrap();
    if i64::from(declared) - last_no < 100 {
        return (listed, fallback);
    }
    let mut sizes: Vec<i64> = parts.iter().map(|p| p.1).collect();
    sizes.sort_unstable();
    let mut common = sizes[0];
    let mut count = 0;
    let mut run = 0;
    let mut previous = sizes[0];
    for &size in &sizes {
        if size == previous {
            run += 1;
        } else {
            run = 1;
            previous = size;
        }
        if run > count {
            common = size;
            count = run;
        }
    }
    let full = if count * 2 > sizes.len() {
        last_bytes == common
    } else {
        last_bytes as f64 >= 0.99 * sizes[sizes.len() / 2] as f64
    };
    (listed, if full { u64::from(declared) } else { fallback })
}
/// Whole posting estimate using the proxy's ties-to-even rounding.
pub fn whole_bytes(total: u64, listed: u64, declared: u64) -> u64 {
    if listed == 0 || listed >= declared {
        return total;
    }
    (total as f64 / (listed as f64 / declared as f64)).round_ties_even() as u64
}
/// Known article health weighted by the share of parts actually listed.
pub fn weighted_alive(alive: f64, listed: u64, declared: u64) -> f64 {
    if !alive.is_finite() {
        return -1.0;
    }
    if alive < 0.0 {
        return alive;
    }
    let alive = alive.clamp(0.0, 1.0);
    if listed > 0 && listed < declared {
        alive * (listed as f64 / declared as f64)
    } else {
        alive
    }
}

/// Synthetic missing articles matching proxy with_unlisted integer normalization.
pub fn unlisted_missing(answered: i32, listed: u64, declared: u64) -> i32 {
    normalized_missing(i64::from(answered), listed, declared)
}
fn normalized_missing(answered: i64, listed: u64, declared: u64) -> i32 {
    if answered < 5 || listed == 0 || listed >= declared {
        return 0;
    }
    (answered as f64 * (declared as f64 / listed as f64 - 1.0)).round_ties_even() as i32
}
/// Known health includes unlisted parts; native answered samples include errors.
pub fn effective_alive(present: i32, missing: i32, error: i32, listed: u64, declared: u64) -> f64 {
    if present < 0 || missing < 0 || error < 0 {
        return -1.0;
    }
    let answered = i64::from(present) + i64::from(missing) + i64::from(error);
    if answered < 5 {
        return -1.0;
    }
    let extra = i64::from(normalized_missing(answered, listed, declared));
    f64::from(present) / (answered + extra) as f64
}

/// Count structurally absent parts as missing when evaluating an unusable donor.
pub fn dead_donor(present: i32, missing: i32, error: i32, listed: u64, declared: u64, minimum: i32) -> bool {
    let alive = effective_alive(present, missing, error, listed, declared);
    let answered = present.max(0).saturating_add(missing.max(0)).saturating_add(error.max(0));
    let missing = i64::from(missing.max(0)) + i64::from(unlisted_missing(answered, listed, declared));
    alive >= 0.0 && alive * 100.0 < f64::from(minimum) && missing >= 5
}

/// Conservative PAR2 feasibility estimate; broadens discovery only.
pub fn par_doomed(
    data_bytes: u64,
    article_bytes: u64,
    volumes: &[u64],
    alive: f64,
    block: u64,
) -> bool {
    if data_bytes == 0
        || article_bytes == 0
        || block == 0
        || volumes.is_empty()
        || volumes.contains(&0)
        || !alive.is_finite()
        || !(0.0..=1.0).contains(&alive)
    {
        return false;
    }
    let blocks = data_bytes / block + u64::from(data_bytes % block != 0);
    let damaged = blocks as f64 * (1.0 - alive.powf(block as f64 / article_bytes as f64));
    let recovery: f64 = volumes
        .iter()
        .map(|&bytes| (bytes as f64 / (block as f64 * 1.02 + 68.0)).round_ties_even())
        .sum();
    damaged > 1.25 * recovery + 2.0
}

/// Shared per-search indexer-download budget. Each attempted fetch, including
/// retries, takes a slot; cooldown skips must occur before calling take().
pub struct FetchBudget {
    limit: Option<usize>,
    used: AtomicUsize,
}
impl FetchBudget {
    pub fn new(limit: Option<usize>) -> Self {
        Self {
            limit,
            used: AtomicUsize::new(0),
        }
    }
    pub fn from_max_donors(max_donors: usize) -> Self {
        Self::new((max_donors != 0).then_some(max_donors.saturating_mul(3)))
    }
    pub fn take(&self) -> bool {
        self.used
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |used| {
                if self.limit.is_some_and(|limit| used >= limit) {
                    None
                } else {
                    used.checked_add(1)
                }
            })
            .is_ok()
    }
    pub fn spent(&self) -> bool {
        self.limit.is_some_and(|limit| self.used() >= limit)
    }
    pub fn used(&self) -> usize {
        self.used.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn inferred_missing_rejects_unusable_partial_donors() {
        assert!(dead_donor(5, 0, 0, 5, 150, 10));
        assert!(!dead_donor(4, 0, 0, 5, 150, 10));
        assert!(!dead_donor(0, 0, 100, 100, 100, 10));
        assert!(dead_donor(0, 5, 0, 5, 5, 10));
        assert!(!dead_donor(5, 0, 0, 5, 5, 10));
        assert!(!dead_donor(5, 0, 0, 5, 150, 0));
    }

    use super::*;
    const LIVE: u32 = ENABLED | DUPE_CHECK | PRESENT | NZB | DELETE_NONE | SCORE_MODE;
    #[test]
    fn flags_and_postprocess() {
        assert_eq!(decide(LIVE, 0, None, 100, None, false), Decision::Search);
        for bad in [DONOR, AUTO_REDOWNLOAD, MANAGED_FLEET, DELETING] {
            assert_eq!(
                decide(LIVE | bad, 0, None, 100, None, false),
                Decision::Skip
            );
        }
        for required in [ENABLED, DUPE_CHECK, PRESENT, NZB, DELETE_NONE, SCORE_MODE] {
            assert_eq!(
                decide(LIVE & !required, 0, None, 100, None, false),
                Decision::Skip
            );
        }
        assert_eq!(
            decide(
                (LIVE & !SCORE_MODE) | POST_PROCESS | DONOR,
                0,
                None,
                100,
                None,
                false
            ),
            Decision::RetryPostProcess
        );
    }
    #[test]
    fn historical_failure_and_success() {
        assert_eq!(
            decide((LIVE & !DELETE_NONE) | HISTORY, 0, None, 100, None, false),
            Decision::Search
        );
        for bad in [
            SUCCESS,
            DELETE_MANUAL,
            DELETE_DUPE,
            DELETE_COPY,
            DELETE_GOOD,
        ] {
            assert_eq!(
                decide(LIVE | HISTORY | bad, 0, None, 100, None, true),
                Decision::Skip
            );
        }
    }
    #[test]
    fn recent_boundary_score_and_rename() {
        let stamp = Some(SearchStamp {
            score: BASE_PICK_SCORE,
            time: 100,
        });
        assert_eq!(
            decide(LIVE, 3, None, 100 + SEARCH_WINDOW_SEC - 1, stamp, false),
            Decision::Skip
        );
        assert_eq!(
            decide(LIVE, 3, None, 100 + SEARCH_WINDOW_SEC, stamp, false),
            Decision::Search
        );
        assert_eq!(
            decide(LIVE, BASE_PICK_SCORE + 1, None, 101, stamp, false),
            Decision::Search
        );
        assert_eq!(decide(LIVE, 3, None, 101, stamp, true), Decision::Search);
        assert!(!identity_changed(None, (b"title", b"key")));
        assert!(!identity_changed(
            Some((b"title", b"key")),
            (b"title", b"KEY")
        ));
        assert!(identity_changed(
            Some((b"title", b"key")),
            (b"new title", b"key")
        ));
        assert!(!identity_changed(
            Some((b"new title", b"key")),
            (b"new title", b"key")
        ));
        // A clock that moved backwards still suppresses a recent search.
        assert_eq!(decide(LIVE, 3, None, 99, stamp, false), Decision::Skip);
    }
    #[test]
    fn historical_higher_excludes_copies_and_manual() {
        let pick = Snapshot {
            id: 1,
            key: b"Key",
            score: 5,
            flags: LIVE,
        };
        let mut other = Snapshot {
            id: 2,
            key: b"key",
            score: 6,
            flags: LIVE | HISTORY,
        };
        assert_eq!(higher_score(pick, &[other], false), None);
        assert_eq!(higher_score(pick, &[other], true), Some(6));
        for bad in [DELETE_COPY, DELETE_MANUAL, DELETING] {
            other.flags = LIVE | HISTORY | bad;
            assert_eq!(higher_score(pick, &[other], true), None);
        }
        other.flags = LIVE;
        assert_eq!(higher_score(pick, &[other], false), Some(6));
        assert_eq!(decide(LIVE, 5, Some(6), 1, None, false), Decision::Skip);
        assert_eq!(decide(LIVE, 5, Some(5), 1, None, false), Decision::Search);
    }
    #[test]
    fn raw_identity_bytes_remain_distinct() {
        assert!(identity_changed(
            Some((b"title", b"key\xff")),
            (b"title", b"key\xfe")
        ));
        let pick = Snapshot {
            id: 1,
            key: b"key\xff",
            score: 1,
            flags: LIVE,
        };
        let other = Snapshot {
            id: 2,
            key: b"key\xfe",
            score: 2,
            flags: LIVE,
        };
        assert_eq!(higher_score(pick, &[other], true), None);
    }
    #[test]
    fn broad_queries_preserve_episode_year_without_resolution() {
        assert_eq!(
            lenient_queries(b"The.Show.S01E02.2025.1080p.WEB-DL.x264-GRP"),
            vec![b"the show".to_vec(), b"the show s01e02 2025".to_vec()]
        );
        assert_eq!(
            lenient_queries(b"Some.Movie.2024.2160p.BluRay-GRP"),
            vec![b"some movie".to_vec(), b"some movie 2024".to_vec()]
        );
        assert_eq!(
            lenient_queries(b"The.Show.S01E02E03.1080p-GRP"),
            vec![b"the show".to_vec(), b"the show s01e02e03".to_vec()]
        );
        assert_eq!(
            lenient_queries(b"Plain.Title"),
            vec![b"plain title".to_vec()]
        );
        assert!(lenient_queries(b"").is_empty());
    }
    #[test]
    fn expansion_health_boundaries_and_outages() {
        assert!(should_expand(0.849999, 5, false, false));
        assert!(!should_expand(0.85, 5, false, false));
        assert!(!should_expand(0.0, 4, false, false));
        assert!(!should_expand(-1.0, 10, false, false));
        assert!(!should_expand(f64::NAN, 10, false, false));
        assert!(!should_expand(f64::INFINITY, 10, false, false));
        assert!(should_expand(-1.0, 0, true, false));
        assert!(!should_expand(0.0, 100, true, true));
    }
    #[test]
    fn max_donors_is_three_fetches_per_donor() {
        let b = FetchBudget::from_max_donors(2);
        for _ in 0..6 {
            assert!(b.take());
        }
        assert!(!b.take());
        assert!(b.spent());
    }
    #[test]
    fn part_count_guards_and_true_tail() {
        assert_eq!(part_counts(&[(1, 100), (2, 100)], 1000, false), (2, 1000));
        assert_eq!(part_counts(&[(1, 100), (2, 30)], 1000, false), (2, 2));
        assert_eq!(part_counts(&[(1, 100), (2, 100)], 1000, true), (2, 2));
        assert_eq!(part_counts(&[(1, 100), (2, 100)], 140, false), (2, 140));
        assert_eq!(part_counts(&[(1, 100), (2, 100)], 101, false), (2, 2));
        assert_eq!(part_counts(&[(1, 100), (3, 100)], 0, false), (2, 3));
        assert_eq!(part_counts(&[(9374, 100)], 10000, false), (1, 9374));
        assert_eq!(part_counts(&[(0, 100), (2, 100)], 1000, false), (2, 2));
        assert_eq!(part_counts(&[(1, 100), (200001, 100)], 1000, false), (2, 2));
        assert_eq!(part_counts(&[(1, 100), (2, 100)], 200001, false), (2, 2));
        assert_eq!(part_counts(&[], 1000, false), (0, 0));
        // No strict majority: upper median is 101; last99 fails the99% test.
        assert_eq!(
            part_counts(&[(1, 100), (2, 101), (3, 102), (4, 99)], 1000, false),
            (4, 4)
        );
        assert_eq!(
            part_counts(&[(1, 100), (2, 101), (3, 102), (4, 100)], 1000, false),
            (4, 1000)
        );
    }
    #[test]
    fn whole_size_ties_and_weighted_health() {
        assert_eq!(whole_bytes(1, 2, 5), 2); //2.5 rounds to even
        assert_eq!(whole_bytes(3, 2, 5), 8); //7.5 rounds to even
        assert_eq!(whole_bytes(100, 0, 1000), 100);
        assert_eq!(whole_bytes(100, 1000, 100), 100);
        assert_eq!(whole_bytes(u64::MAX, 1, 200000), u64::MAX);
        assert_eq!(weighted_alive(1.0, 2, 5), 0.4);
        assert_eq!(weighted_alive(-1.0, 2, 5), -1.0);
        assert_eq!(weighted_alive(f64::NAN, 2, 5), -1.0);
        assert_eq!(weighted_alive(2.0, 2, 5), 0.4);
        assert_eq!(weighted_alive(0.5, 0, 5), 0.5);
    }
    #[test]
    fn integer_health_normalization_and_unknowns() {
        assert_eq!(unlisted_missing(13, 3, 10), 30);
        assert_eq!(effective_alive(13, 0, 0, 3, 10), 13.0 / 43.0);
        assert_eq!(unlisted_missing(5, 2, 3), 2); //2.5 ties to even
        assert_eq!(unlisted_missing(7, 2, 3), 4); //3.5 ties to even
        assert_eq!(effective_alive(4, 0, 0, 3, 10), -1.0);
        assert_eq!(effective_alive(0, 0, 100, 3, 10), 0.0);
        assert_eq!(effective_alive(8, 2, 99, 0, 10), 8.0 / 109.0);
        assert_eq!(effective_alive(8, 2, 0, 10, 3), 0.8);
        assert_eq!(effective_alive(5, 5, 0, 5, 10), 0.25);
        assert_eq!(unlisted_missing(5, 1, u64::MAX), i32::MAX);
        assert_eq!(effective_alive(-1, 6, 0, 3, 10), -1.0);
    }
    #[test]
    fn mixed_errors_match_native_answered() {
        assert_eq!(effective_alive(5, 0, 5, 10, 10), 0.5);
        assert_eq!(effective_alive(5, 0, 5, 1, 2), 0.25);
        assert_eq!(effective_alive(0, 0, 10, 10, 10), 0.0);
        assert!(!should_expand(
            effective_alive(0, 0, 10, 10, 10),
            0,
            false,
            false
        ));
    }
    #[test]
    fn par_feasibility_is_bounded_and_conservative() {
        assert!(!par_doomed(10000, 100, &[3000], 0.8, 100));
        assert!(par_doomed(10000, 100, &[3000], 0.8, 1000));
        assert!(!par_doomed(10000, 100, &[3000], 1.0, 1000));
        for alive in [-1.0, f64::NAN, f64::INFINITY, 1.1] {
            assert!(!par_doomed(10000, 100, &[3000], alive, 1000));
        }
        assert!(!par_doomed(0, 100, &[3000], 0.8, 1000));
        assert!(!par_doomed(10000, 0, &[3000], 0.8, 1000));
        assert!(!par_doomed(10000, 100, &[], 0.8, 1000));
        assert!(!par_doomed(10000, 100, &[0], 0.8, 1000));
        assert!(!par_doomed(10000, 100, &[3000], 0.8, 0));
    }
    #[test]
    fn budgets_retries_zero_and_parallel() {
        let b = FetchBudget::new(Some(2));
        assert!(b.take());
        assert!(!b.spent());
        assert!(b.take());
        assert!(b.spent());
        assert!(!b.take());
        assert_eq!(b.used(), 2);
        let zero = FetchBudget::new(Some(0));
        assert!(zero.spent());
        assert!(!zero.take());
        let unlimited = FetchBudget::from_max_donors(0);
        for _ in 0..1000 {
            assert!(unlimited.take());
        }
        assert!(!unlimited.spent());
        let shared = std::sync::Arc::new(FetchBudget::new(Some(127)));
        let workers: Vec<_> = (0..16)
            .map(|_| {
                let b = shared.clone();
                std::thread::spawn(move || (0..100).filter(|_| b.take()).count())
            })
            .collect();
        assert_eq!(
            workers
                .into_iter()
                .map(|w| w.join().unwrap())
                .sum::<usize>(),
            127
        );
        assert!(shared.spent());
        assert_eq!(shared.used(), 127);
    }
}
