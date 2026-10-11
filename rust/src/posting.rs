//! Posting (daemon/dupesearch/Posting.cpp): which search results are one
//! posting, the order to fetch postings in, and sketches of postings' articles.
//! SketchOfFile (file reading and its cache) stays C++.

/// Listings of one size posted this close together are one posting on several indexers.
pub const RELIST_WINDOW_SEC: i64 = 120;
/// Share of the articles two nzb-files may have in common before they count as one posting.
pub const SAME_POSTING_SHARE: f64 = 0.01;
/// Message-id hashes kept in a posting's sketch.
pub const SKETCH_SIZE: usize = 64;
/// An nzb-file this share off the listed size is another nzb-file than the listing's.
pub const LISTING_MISMATCH_SHARE: f64 = 0.02;

/// zlib's crc32 (the reflected IEEE polynomial), as `crc32(0, data, len)`.
pub fn crc32(data: &[u8]) -> u32 {
    const TABLE: [u32; 256] = {
        let mut table = [0u32; 256];
        let mut i = 0;
        while i < 256 {
            let mut c = i as u32;
            let mut k = 0;
            while k < 8 {
                c = if c & 1 != 0 { 0xedb8_8320 ^ (c >> 1) } else { c >> 1 };
                k += 1;
            }
            table[i] = c;
            i += 1;
        }
        table
    };
    let mut crc = !0u32;
    for &b in data {
        crc = TABLE[((crc ^ b as u32) & 0xff) as usize] ^ (crc >> 8);
    }
    !crc
}

/// MakeSketch: the SKETCH_SIZE smallest distinct CRC32s of the message-ids, ascending.
pub fn make_sketch<'a>(message_ids: impl IntoIterator<Item = &'a [u8]>) -> Vec<u32> {
    let mut hashes: Vec<u32> = message_ids.into_iter().map(crc32).collect();
    hashes.sort_unstable();
    hashes.dedup();
    hashes.truncate(SKETCH_SIZE);
    hashes
}

/// Elements both sorted sequences hold (std::set_intersection's count, duplicates matched pairwise).
fn common<T: Ord>(a: &[T], b: &[T]) -> usize {
    let (mut i, mut j, mut n) = (0, 0, 0);
    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => {
                n += 1;
                i += 1;
                j += 1;
            }
        }
    }
    n
}

/// SameSketch: at least an eighth (at least one) of the smaller sketch in common.
pub fn same_sketch(a: &[u32], b: &[u32]) -> bool {
    let k = a.len().min(b.len());
    k != 0 && common(a, b) >= 1.max(k / 8)
}

/// SamePosting: more than SAME_POSTING_SHARE of the articles in common (both sorted).
pub fn same_posting(a: &[&[u8]], b: &[&[u8]]) -> bool {
    common(a, b) as f64 > SAME_POSTING_SHARE * a.len().min(b.len()) as f64
}

/// The fields of a search result the grouping and ordering look at.
#[derive(Clone, Copy, Debug)]
pub struct Listing<'a> {
    pub link: &'a [u8],
    pub size: i64,
    pub grabs: i32,
    pub date: i64,
}

/// GroupListings: indices into `results`, one group per posting (same size,
/// posted within RELIST_WINDOW_SEC of the group's first; without a size or a
/// date a listing stays alone), groups in (size, date) order.
pub fn group_listings(results: &[Listing]) -> Vec<Vec<usize>> {
    let mut order: Vec<usize> = (0..results.len()).collect();
    order.sort_by(|&a, &b| (results[a].size, results[a].date).cmp(&(results[b].size, results[b].date)));
    let mut groups: Vec<Vec<usize>> = Vec::new();
    for i in order {
        let r = &results[i];
        if let Some(group) = groups.last_mut() {
            let first = &results[group[0]];
            if r.size != 0 && r.date != 0 && first.date != 0 && r.size == first.size
                && r.date.wrapping_sub(first.date) <= RELIST_WINDOW_SEC
            {
                group.push(i);
                continue;
            }
        }
        groups.push(vec![i]);
    }
    groups
}

/// ListingMismatch: the nzb-file is more than LISTING_MISMATCH_SHARE off the listed size.
pub fn listing_mismatch(listing_size: i64, nzb_bytes: i64) -> bool {
    listing_size > 0 && (nzb_bytes.wrapping_sub(listing_size)).wrapping_abs() as f64 > LISTING_MISMATCH_SHARE * listing_size as f64
}

/// OrderPostings: groups of indices into `candidates`, each group's listings by
/// rank (closest to `pick_bytes`, most grabbed, newest), groups by their first
/// listing's rank, one posting of each distinct size before the rest, at most
/// 3 * `max_postings` groups when that is above 0.
pub fn order_postings(candidates: &[Listing], pick_bytes: i64, max_postings: i32) -> Vec<Vec<usize>> {
    let mut by_rank: Vec<usize> = (0..candidates.len()).collect();
    let dist = |i: usize| candidates[i].size.wrapping_sub(pick_bytes).wrapping_abs();
    by_rank.sort_by(|&a, &b| {
        dist(a)
            .cmp(&dist(b))
            .then_with(|| candidates[b].grabs.cmp(&candidates[a].grabs))
            .then_with(|| candidates[b].date.cmp(&candidates[a].date))
    });
    let mut rank = vec![0usize; candidates.len()];
    for (r, &i) in by_rank.iter().enumerate() {
        rank[i] = r;
    }
    // the C++ looked a listing up by (link, size, date): the first candidate that matches gives its rank
    let rank_of = |i: usize| {
        let c = &candidates[i];
        let first = candidates
            .iter()
            .position(|o| o.link == c.link && o.size == c.size && o.date == c.date)
            .unwrap_or(i);
        rank[first]
    };
    let mut groups = group_listings(candidates);
    for group in &mut groups {
        group.sort_by_key(|&i| rank_of(i));
    }
    groups.sort_by_key(|g| rank_of(g[0]));
    let mut seen = std::collections::BTreeSet::new();
    let (mut firsts, mut rest) = (Vec::new(), Vec::new());
    for group in groups {
        if seen.insert(candidates[group[0]].size) {
            firsts.push(group);
        } else {
            rest.push(group);
        }
    }
    firsts.extend(rest);
    if max_postings > 0 && firsts.len() > 3 * max_postings as usize {
        firsts.truncate(3 * max_postings as usize);
    }
    firsts
}

#[cfg(test)]
mod tests {
    use super::*;

    fn l(link: &'static [u8], size: i64, grabs: i32, date: i64) -> Listing<'static> {
        Listing { link, size, grabs, date }
    }

    #[test]
    fn crc32_is_zlibs() {
        assert_eq!(crc32(b""), 0);
        assert_eq!(crc32(b"123456789"), 0xcbf4_3926);
    }

    #[test]
    fn sketches_keep_the_smallest_distinct_hashes() {
        let ids: Vec<Vec<u8>> = (0..200).map(|i| format!("<{i}@x>").into_bytes()).collect();
        let s = make_sketch(ids.iter().map(|v| v.as_slice()));
        assert_eq!(s.len(), SKETCH_SIZE);
        assert!(s.windows(2).all(|w| w[0] < w[1]));
        assert!(same_sketch(&s, &s) && !same_sketch(&s, &[]));
    }

    #[test]
    fn groups_relistings_and_orders_by_rank() {
        let c = [l(b"a", 100, 0, 1000), l(b"b", 100, 5, 1060), l(b"c", 300, 0, 1000), l(b"d", 100, 0, 5000)];
        assert_eq!(group_listings(&c), vec![vec![0, 1], vec![3], vec![2]]);
        assert_eq!(order_postings(&c, 100, 0), vec![vec![1, 0], vec![2], vec![3]]);
        assert_eq!(order_postings(&c, 100, 1).len(), 3);
        assert!(listing_mismatch(100, 103) && !listing_mismatch(100, 102) && !listing_mismatch(0, 5));
    }
}
