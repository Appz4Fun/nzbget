//! File identity contracts for the complete article fallback selector.

// SPDX-License-Identifier: GPL-2.0-or-later
use std::collections::{BTreeMap, BTreeSet};

#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EncodedPart {
    pub part: i32,
    pub size: i32,
}

/// Immutable operation snapshot; no foreign file/article pointers are retained.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileIdentity {
    pub name: Vec<u8>,
    pub subject: Vec<u8>,
    pub encoded_size: i64,
    pub total_articles: i32,
    pub parts: Vec<EncodedPart>,
    pub is_par: bool,
}

/// Evidence must come from the independently validated content authority.
/// A name/size/fingerprint heuristic cannot construct authoritative evidence.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ContentEvidence {
    Unknown,
    KnownDifferent,
    KnownName(Vec<u8>),
}

fn c_bytes(bytes: &[u8]) -> &[u8] {
    &bytes[..bytes.iter().position(|&b| b == 0).unwrap_or(bytes.len())]
}

const fn c_space() -> [bool; 256] {
    let mut result = [false; 256];
    let mut i = 9;
    while i <= 13 {
        result[i] = true;
        i += 1;
    }
    result[32] = true;
    result
}
const C_SPACE: [bool; 256] = c_space();

fn integer(bytes: &[u8], mut at: usize, space: &[bool; 256]) -> Option<(i32, usize)> {
    while bytes.get(at).is_some_and(|b| space[*b as usize]) {
        at += 1;
    }
    let negative = bytes.get(at) == Some(&b'-');
    if negative || bytes.get(at) == Some(&b'+') {
        at += 1;
    }
    let start = at;
    let mut value = 0_i64;
    while let Some(byte) = bytes.get(at).filter(|b| b.is_ascii_digit()) {
        value = value
            .checked_mul(10)?
            .checked_add(i64::from(*byte - b'0'))?;
        if value > i64::from(i32::MAX) + i64::from(negative) {
            return None;
        }
        at += 1;
    }
    if at == start {
        return None;
    }
    let signed = if negative { -value } else { value };
    Some((i32::try_from(signed).ok()?, at))
}

/// The last valid (part/count) group; caller supplies current C classification.
pub fn declared_parts_with_space(subject: &[u8], space: &[bool; 256]) -> i32 {
    let subject = c_bytes(subject);
    let mut declared = 0;
    for (at, byte) in subject.iter().enumerate() {
        if *byte != b'(' {
            continue;
        }
        let Some((part, at)) = integer(subject, at + 1, space) else {
            continue;
        };
        if subject.get(at) != Some(&b'/') {
            continue;
        }
        let Some((count, at)) = integer(subject, at + 1, space) else {
            continue;
        };
        if subject.get(at) == Some(&b')') && part >= 0 && count > 0 {
            declared = count;
        }
    }
    declared
}

/// C-locale convenience for standalone correctness fixtures.
pub fn declared_parts(subject: &[u8]) -> i32 {
    declared_parts_with_space(subject, &C_SPACE)
}

fn sizes_match(left: i64, right: i64, div: i64) -> bool {
    let Some(diff) = left.max(right).checked_sub(left.min(right)) else {
        return false;
    };
    div > 0 && diff <= left.max(right) / div
}

pub fn structure_matches(target: &FileIdentity, donor: &FileIdentity) -> bool {
    structure_matches_with_space(target, donor, &C_SPACE)
}

pub fn structure_matches_with_space(
    target: &FileIdentity,
    donor: &FileIdentity,
    space: &[bool; 256],
) -> bool {
    if target.parts.is_empty() {
        return false;
    }
    let target_declared = declared_parts_with_space(&target.subject, space);
    let donor_declared = declared_parts_with_space(&donor.subject, space);
    if target_declared > 0 && donor_declared > 0 && target_declared != donor_declared {
        return false;
    }
    if target_declared > 0 && donor.parts.iter().any(|a| a.part > target_declared) {
        return false;
    }
    if target.parts.len() < donor.parts.len() {
        let extra = donor.parts.len() - target.parts.len();
        if extra > (donor.parts.len() / 16).max(1) {
            return false;
        }
        // Historical std::map assignment keeps the LAST duplicate part's size.
        let donor_parts: BTreeMap<_, _> = donor.parts.iter().map(|a| (a.part, a.size)).collect();
        let mut target_parts = BTreeSet::new();
        let mut last_target = 0;
        for article in &target.parts {
            let Some(size) = donor_parts.get(&article.part) else {
                return false;
            };
            if !sizes_match(i64::from(article.size), i64::from(*size), 16) {
                return false;
            }
            target_parts.insert(article.part);
            last_target = last_target.max(article.part);
        }
        let mut trailing = 0;
        let mut trailing_size = 0_i64;
        for article in &donor.parts {
            if !target_parts.contains(&article.part) && article.part > last_target {
                trailing += 1;
                let Some(total) = trailing_size.checked_add(i64::from(article.size)) else {
                    return false;
                };
                trailing_size = total;
            }
        }
        let Some(total) = target.encoded_size.checked_add(trailing_size) else {
            return false;
        };
        return trailing <= 1 && sizes_match(total, donor.encoded_size, 64);
    }
    target.parts.len() == donor.parts.len()
        && target.total_articles == donor.total_articles
        && sizes_match(target.encoded_size, donor.encoded_size, 64)
        && target
            .parts
            .iter()
            .zip(&donor.parts)
            .all(|(a, b)| a.part == b.part && sizes_match(i64::from(a.size), i64::from(b.size), 16))
}

pub fn size_steps_match(target: &FileIdentity, donor: &FileIdentity) -> bool {
    if target.parts.len() < 8 || target.parts.len() != donor.parts.len() {
        return false;
    }
    let mut varying = false;
    for i in 1..target.parts.len() {
        let Some(a) = target.parts[i].size.checked_sub(target.parts[i - 1].size) else {
            return false;
        };
        let Some(b) = donor.parts[i].size.checked_sub(donor.parts[i - 1].size) else {
            return false;
        };
        if a != b {
            return false;
        }
        varying |= a != 0 && i < target.parts.len() - 1;
    }
    varying
}

pub fn size_steps_hash(file: &FileIdentity) -> u64 {
    if file.parts.len() < 8 {
        return 0;
    }
    let Ok(count) = i64::try_from(file.parts.len()) else {
        return 0;
    };
    let mut hash = 14695981039346656037_u64;
    fn mix(hash: &mut u64, value: i64) {
        for byte in value.to_le_bytes() {
            *hash ^= u64::from(byte);
            *hash = hash.wrapping_mul(1099511628211);
        }
    }
    mix(&mut hash, count);
    let mut varying = false;
    for i in 1..file.parts.len() {
        let Some(step) = file.parts[i].size.checked_sub(file.parts[i - 1].size) else {
            return 0;
        };
        mix(&mut hash, i64::from(step));
        varying |= step != 0 && i < file.parts.len() - 1;
    }
    if varying {
        hash
    } else {
        0
    }
}

fn folded_equal(a: &[u8], b: &[u8], fold: &[u8; 256]) -> bool {
    let a = c_bytes(a);
    let b = c_bytes(b);
    a.len() == b.len()
        && a.iter()
            .zip(b)
            .all(|(&a, &b)| fold[a as usize] == fold[b as usize])
}

/// C-locale whitespace convenience. Production adapters must pass the captured
/// LC_CTYPE whitespace table to match_donor_file_with_space as well as its fold map.
pub fn match_donor_file(
    target: &FileIdentity,
    donors: &[FileIdentity],
    alternate: &[u8],
    evidence: &ContentEvidence,
    fold: &[u8; 256],
) -> Option<usize> {
    match_donor_file_with_space(target, donors, alternate, evidence, fold, &C_SPACE)
}

pub fn match_donor_file_with_space(
    target: &FileIdentity,
    donors: &[FileIdentity],
    alternate: &[u8],
    evidence: &ContentEvidence,
    fold: &[u8; 256],
    space: &[bool; 256],
) -> Option<usize> {
    if target.is_par || matches!(evidence, ContentEvidence::KnownDifferent) {
        return None;
    }
    let content_name = match evidence {
        ContentEvidence::KnownName(name) if name.as_slice() == b"-" => return None,
        ContentEvidence::KnownName(name) if !name.is_empty() => Some(name),
        _ => None,
    };
    if let Some(name) = content_name {
        let mut exact = Vec::new();
        let mut folded = Vec::new();
        for (index, donor) in donors.iter().enumerate().filter(|(_, d)| !d.is_par) {
            if c_bytes(&donor.name) == c_bytes(name) {
                exact.push(index);
            } else if folded_equal(&donor.name, name, fold) {
                folded.push(index);
            }
        }
        let named = if exact.len() == 1 {
            Some(exact[0])
        } else if exact.is_empty() && folded.len() == 1 {
            Some(folded[0])
        } else {
            None
        };
        if let Some(index) = named {
            return structure_matches_with_space(target, &donors[index], space).then_some(index);
        }
    }
    let mut structural = Vec::new();
    let mut filename = None;
    let mut ambiguous = false;
    for (index, donor) in donors.iter().enumerate() {
        if donor.is_par || !structure_matches_with_space(target, donor, space) {
            continue;
        }
        if folded_equal(&target.name, &donor.name, fold)
            || (!c_bytes(alternate).is_empty() && folded_equal(alternate, &donor.name, fold))
        {
            if filename.is_some() {
                ambiguous = true;
            } else {
                filename = Some(index);
            }
        } else {
            structural.push(index);
        }
    }
    if ambiguous {
        return None;
    }
    if filename.is_some() {
        return filename;
    }
    if structural.len() == 1 {
        return Some(structural[0]);
    }
    let mut matched = None;
    for index in structural {
        if size_steps_match(target, &donors[index]) {
            if matched.is_some() {
                return None;
            }
            matched = Some(index);
        }
    }
    matched
}

#[cfg(feature = "article-match-trace")]
static MATCH_CALLS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

#[cfg(feature = "article-match-trace")]
#[no_mangle]
pub extern "C" fn nzbget_rs_article_match_trace_count() -> u64 {
    MATCH_CALLS.load(std::sync::atomic::Ordering::Relaxed)
}

/// Daemon-internal immutable file view, borrowed only for one synchronous call.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct IdentityFileView {
    pub name: *const u8,
    pub name_len: usize,
    pub subject: *const u8,
    pub subject_len: usize,
    pub encoded_size: i64,
    pub total_articles: i32,
    pub is_par: i32,
    pub parts: *const EncodedPart,
    pub part_count: usize,
}

unsafe fn view_slice<'a, T>(pointer: *const T, count: usize) -> Option<&'a [T]> {
    if count == 0 {
        return Some(&[]);
    }
    let bytes = count.checked_mul(std::mem::size_of::<T>())?;
    let address = pointer as usize;
    if address == 0
        || address % std::mem::align_of::<T>() != 0
        || bytes > isize::MAX as usize
        || address.checked_add(bytes).is_none()
    {
        return None;
    }
    // SAFETY: numeric span checked, caller provides live initialized read-only allocation.
    Some(unsafe { std::slice::from_raw_parts(pointer, count) })
}

unsafe fn own_view(view: &IdentityFileView) -> Option<FileIdentity> {
    Some(FileIdentity {
        name: unsafe { view_slice(view.name, view.name_len) }?.to_vec(),
        subject: unsafe { view_slice(view.subject, view.subject_len) }?.to_vec(),
        encoded_size: view.encoded_size,
        total_articles: view.total_articles,
        is_par: view.is_par != 0,
        parts: unsafe { view_slice(view.parts, view.part_count) }?.to_vec(),
    })
}

/// Return donor ordinal, -1 for no match, -2 for invalid numeric spans.
/// Allocation failure aborts, as in the existing crate ABI. No pointers survive.
/// # Safety
/// Every numerically valid nonempty span refers to live initialized memory,
/// aligned for its type, immutable throughout the call. Target is one valid view;
/// fold and whitespace each contain 256 bytes captured from the calling locale.
/// Empty counted spans may be null. This is an internal adapter, not an RPC parser.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_article_match(
    target: *const IdentityFileView,
    donors: *const IdentityFileView,
    donor_count: usize,
    alternate: *const u8,
    alternate_len: usize,
    evidence: *const u8,
    evidence_len: usize,
    fold: *const u8,
    whitespace: *const u8,
) -> i64 {
    #[cfg(feature = "article-match-trace")]
    MATCH_CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let Some(target) = (unsafe { view_slice(target, 1) }) else {
        return -2;
    };
    let Some(target) = (unsafe { own_view(&target[0]) }) else {
        return -2;
    };
    let Some(views) = (unsafe { view_slice(donors, donor_count) }) else {
        return -2;
    };
    let mut owned = Vec::new();
    if owned.try_reserve(views.len()).is_err() {
        return -2;
    }
    for view in views {
        let Some(file) = (unsafe { own_view(view) }) else {
            return -2;
        };
        owned.push(file);
    }
    let Some(alternate) = (unsafe { view_slice(alternate, alternate_len) }) else {
        return -2;
    };
    let Some(evidence) = (unsafe { view_slice(evidence, evidence_len) }) else {
        return -2;
    };
    let Some(fold) = (unsafe { view_slice(fold, 256) }) else {
        return -2;
    };
    let Some(whitespace) = (unsafe { view_slice(whitespace, 256) }) else {
        return -2;
    };
    let fold: &[u8; 256] = fold.try_into().unwrap();
    let space = std::array::from_fn(|i| whitespace[i] != 0);
    match_donor_file_with_space(
        &target,
        &owned,
        alternate,
        &ContentEvidence::KnownName(evidence.to_vec()),
        fold,
        &space,
    )
    .map_or(-1, |index| i64::try_from(index).unwrap_or(-2))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fold() -> [u8; 256] {
        std::array::from_fn(|i| (i as u8).to_ascii_lowercase())
    }
    fn file(name: &[u8], count: i32) -> FileIdentity {
        FileIdentity {
            name: name.to_vec(),
            subject: Vec::new(),
            encoded_size: i64::from(count) * 100,
            total_articles: count,
            parts: (1..=count)
                .map(|part| EncodedPart { part, size: 100 })
                .collect(),
            is_par: false,
        }
    }

    #[test]
    fn unique_filename_is_preferred_and_duplicate_filename_is_ambiguous() {
        let target = file(b"movie.r01", 8);
        let a = file(b"other.r01", 8);
        let b = file(b"MOVIE.R01", 8);
        assert_eq!(
            match_donor_file(
                &target,
                &[a.clone(), b.clone()],
                b"",
                &ContentEvidence::Unknown,
                &fold()
            ),
            Some(1)
        );
        assert_eq!(
            match_donor_file(
                &target,
                &[b.clone(), b],
                b"",
                &ContentEvidence::Unknown,
                &fold()
            ),
            None
        );
    }

    #[test]
    fn parity_cannot_be_a_target_or_a_donor() {
        let mut target = file(b"movie.r01", 8);
        let mut donor = target.clone();
        donor.is_par = true;
        assert_eq!(
            match_donor_file(&target, &[donor], b"", &ContentEvidence::Unknown, &fold()),
            None
        );
        target.is_par = true;
        assert_eq!(
            match_donor_file(
                &target,
                &[file(b"movie.r01", 8)],
                b"",
                &ContentEvidence::Unknown,
                &fold()
            ),
            None
        );
    }

    #[test]
    fn authoritative_negative_and_named_structure_failure_do_not_fall_through() {
        let target = file(b"movie.r01", 8);
        let healthy = target.clone();
        let mut named = file(b"by-content", 8);
        named.parts[2].size = 120;
        assert_eq!(
            match_donor_file(
                &target,
                &[healthy.clone()],
                b"",
                &ContentEvidence::KnownDifferent,
                &fold()
            ),
            None
        );
        assert_eq!(
            match_donor_file(
                &target,
                &[named, healthy],
                b"",
                &ContentEvidence::KnownName(b"by-content".to_vec()),
                &fold()
            ),
            None
        );
    }

    #[test]
    fn content_name_exact_case_precedes_folded_aliases() {
        let target = file(b"target", 8);
        let a = file(b"payload", 8);
        let b = file(b"PAYLOAD", 8);
        assert_eq!(
            match_donor_file(
                &target,
                &[a, b],
                b"",
                &ContentEvidence::KnownName(b"payload".to_vec()),
                &fold()
            ),
            Some(0)
        );
    }

    #[test]
    fn missing_interior_parts_match_but_multiple_trailing_parts_do_not() {
        let donor = file(b"x", 20);
        let mut target = donor.clone();
        target.parts.remove(6);
        assert!(structure_matches(&target, &donor));
        let mut tail = donor.clone();
        tail.parts.pop();
        tail.parts.pop();
        assert!(!structure_matches(&tail, &donor));
    }

    #[test]
    fn donor_duplicate_part_lookup_uses_last_size_but_keeps_list_accounting() {
        let donor = file(b"x", 20);
        let mut target = donor.clone();
        target.parts.remove(6);
        let mut changed = donor.clone();
        changed.parts.push(EncodedPart { part: 1, size: 120 });
        // 2 extra list entries exceeds floor20/16, before duplicate-part lookup.
        assert!(!structure_matches(&target, &changed));
        let mut target = file(b"x", 32);
        target.parts.remove(6);
        let mut changed = file(b"x", 32);
        changed.parts.push(EncodedPart { part: 1, size: 120 });
        // Extra2 now fits32/16, and keep-last mapped size rejects part1.
        assert!(!structure_matches(&target, &changed));
    }

    #[test]
    fn declared_count_uses_last_valid_subject_group() {
        assert_eq!(declared_parts(b"x (1/10) y (+2/ 20)"), 20);
        assert_eq!(declared_parts(b"x (1/10) (-1/20)"), 10);
        let mut target = file(b"x", 8);
        let mut donor = target.clone();
        target.subject = b"(1/8)".to_vec();
        donor.subject = b"(1/9)".to_vec();
        assert!(!structure_matches(&target, &donor));
    }

    #[test]
    fn uniform_and_only_short_final_part_have_no_step_identity() {
        let mut a = file(b"x", 8);
        assert_eq!(size_steps_hash(&a), 0);
        a.parts[7].size = 50;
        assert_eq!(size_steps_hash(&a), 0);
        assert!(!size_steps_match(&a, &a));
        a.parts[3].size = 110;
        assert_ne!(size_steps_hash(&a), 0);
        assert!(size_steps_match(&a, &a));
    }

    #[test]
    fn fingerprint_disambiguates_obfuscated_structural_twins() {
        let mut target = file(b"original", 8);
        target.parts[3].size = 105;
        let mut right = target.clone();
        right.name = b"random-a".to_vec();
        let wrong = file(b"random-b", 8);
        assert_eq!(
            match_donor_file(
                &target,
                &[wrong, right],
                b"",
                &ContentEvidence::Unknown,
                &fold()
            ),
            Some(1)
        );
    }

    #[test]
    fn names_keep_c_string_and_supplied_byte_fold_semantics() {
        let target = file(b"\xc0name\0ignored", 8);
        let donor = file(b"\xe0name", 8);
        let other = file(b"different", 8);
        let mut table = fold();
        table[0xc0] = 0xe0;
        assert_eq!(
            match_donor_file(
                &target,
                &[donor, other],
                b"",
                &ContentEvidence::Unknown,
                &table
            ),
            Some(0)
        );
    }
    #[test]
    fn native_content_empty_name_is_unknown_not_authoritative() {
        let target = file(b"target", 8);
        let donors = [file(b"", 8), file(b"other", 8)];
        assert_eq!(
            match_donor_file(
                &target,
                &donors,
                b"",
                &ContentEvidence::KnownName(Vec::new()),
                &fold()
            ),
            None
        );
    }

    #[test]
    fn native_content_dash_is_authoritative_negative() {
        let target = file(b"target", 8);
        let donors = [file(b"-", 8), file(b"other", 8)];
        assert_eq!(
            match_donor_file(
                &target,
                &donors,
                b"",
                &ContentEvidence::KnownName(b"-".to_vec()),
                &fold()
            ),
            None
        );
    }

    #[test]
    fn declared_groups_preserve_c_whitespace_and_literal_close_rules() {
        assert_eq!(declared_parts(b"(\x0b1/\x0b8)"), 8);
        assert_eq!(declared_parts(b"(1/8) (2/14 )"), 8);
        let mut space = C_SPACE;
        space[0xa0] = true;
        assert_eq!(declared_parts_with_space(b"(\xa01/8)", &space), 8);
        assert_eq!(declared_parts(b"(\xa01/8)"), 0);
    }

    #[test]
    fn native_std_string_dash_with_nul_is_a_name_not_negative() {
        let target = file(b"target", 8);
        let donors = [file(b"-", 8), file(b"other", 8)];
        assert_eq!(
            match_donor_file(
                &target,
                &donors,
                b"",
                &ContentEvidence::KnownName(b"-\0suffix".to_vec()),
                &fold()
            ),
            Some(0)
        );
    }
    #[test]
    fn native_std_string_leading_nul_is_nonempty_before_c_name_compare() {
        let target = file(b"target", 8);
        let donors = [file(b"", 8), file(b"other", 8)];
        assert_eq!(
            match_donor_file(
                &target,
                &donors,
                b"",
                &ContentEvidence::KnownName(b"\0suffix".to_vec()),
                &fold()
            ),
            Some(0)
        );
    }
    #[test]
    fn caller_bridge_selects_counted_file_views() {
        let parts = [EncodedPart { part: 1, size: 100 }];
        let target = IdentityFileView {
            name: b"file.bin".as_ptr(),
            name_len: 8,
            subject: std::ptr::null(),
            subject_len: 0,
            encoded_size: 100,
            total_articles: 1,
            is_par: 0,
            parts: parts.as_ptr(),
            part_count: 1,
        };
        let donor = target;
        let fold = fold();
        let space = std::array::from_fn::<_, 256, _>(|i| u8::from(C_SPACE[i]));
        assert_eq!(
            unsafe {
                nzbget_rs_article_match(
                    &target,
                    &donor,
                    1,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    fold.as_ptr(),
                    space.as_ptr(),
                )
            },
            0
        );
        assert_eq!(
            unsafe {
                nzbget_rs_article_match(
                    &target,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    fold.as_ptr(),
                    space.as_ptr(),
                )
            },
            -1
        );
    }
    #[test]
    fn caller_bridge_rejects_numeric_spans_before_borrow() {
        assert_eq!(
            unsafe {
                nzbget_rs_article_match(
                    std::ptr::null(),
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    std::ptr::null(),
                )
            },
            -2
        );
        assert_eq!(
            unsafe {
                nzbget_rs_article_match(
                    3_usize as *const IdentityFileView,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    std::ptr::null(),
                )
            },
            -2
        );
        let parts = [EncodedPart { part: 1, size: 100 }];
        let target = IdentityFileView {
            name: b"file.bin".as_ptr(),
            name_len: 8,
            subject: std::ptr::null(),
            subject_len: 0,
            encoded_size: 100,
            total_articles: 1,
            is_par: 0,
            parts: parts.as_ptr(),
            part_count: 1,
        };
        let fold = fold();
        let space = std::array::from_fn::<_, 256, _>(|i| u8::from(C_SPACE[i]));
        assert_eq!(
            unsafe {
                nzbget_rs_article_match(
                    &target,
                    &target,
                    usize::MAX,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    fold.as_ptr(),
                    space.as_ptr(),
                )
            },
            -2
        );
    }
}
