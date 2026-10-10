//! Util's string helpers: FormatSize, FormatSpeed, AlphaNum, HashBJ96,
//! ReduceStr, the Tokenizer's tokens and MatchFileExt. Each matches the C++
//! code it replaces, quirks included.

use crate::wildmask::Lower;

/// Util::FormatSize: the C++ computes in float and prints with "%.2f".
pub fn format_size(size: i64) -> String {
    let f = size as f32;
    if size > 1024 * 1024 * 1000 {
        format!("{:.2} GB", (f / 1024.0 / 1024.0 / 1024.0) as f64)
    } else if size > 1024 * 1000 {
        format!("{:.2} MB", (f / 1024.0 / 1024.0) as f64)
    } else if size > 1000 {
        format!("{:.2} KB", (f / 1024.0) as f64)
    } else if size == 0 {
        "0 MB".to_string()
    } else {
        // (int) of an int64: wraps
        format!("{} B", size as i32)
    }
}

/// Util::FormatSpeed.
pub fn format_speed(bps: i64) -> String {
    const K: i64 = 1024;
    let d = bps as f64;
    if bps >= 100 * K * K * K {
        format!("{} GB/s", bps / K / K / K)
    } else if bps >= 10 * K * K * K {
        format!("{:.1} GB/s", d / 1024.0 / 1024.0 / 1024.0)
    } else if bps >= K * K * K {
        format!("{:.2} GB/s", d / 1024.0 / 1024.0 / 1024.0)
    } else if bps >= 100 * K * K {
        format!("{} MB/s", bps / K / K)
    } else if bps >= 10 * K * K {
        format!("{:.1} MB/s", d / 1024.0 / 1024.0)
    } else if bps >= K * 1000 {
        format!("{:.2} MB/s", d / 1024.0 / 1024.0)
    } else {
        format!("{} KB/s", bps / K)
    }
}

/// Util::AlphaNum: only ASCII letters and digits.
pub fn alpha_num(s: &[u8]) -> bool {
    s.iter().all(|b| b.is_ascii_alphanumeric())
}

/// Util::HashBJ96: Bob Jenkins' lookup2 hash.
pub fn hash_bj96(k: &[u8], init: u32) -> u32 {
    fn mix(a: &mut u32, b: &mut u32, c: &mut u32) {
        *a = a.wrapping_sub(*b).wrapping_sub(*c) ^ (*c >> 13);
        *b = b.wrapping_sub(*c).wrapping_sub(*a) ^ (*a << 8);
        *c = c.wrapping_sub(*a).wrapping_sub(*b) ^ (*b >> 13);
        *a = a.wrapping_sub(*b).wrapping_sub(*c) ^ (*c >> 12);
        *b = b.wrapping_sub(*c).wrapping_sub(*a) ^ (*a << 16);
        *c = c.wrapping_sub(*a).wrapping_sub(*b) ^ (*b >> 5);
        *a = a.wrapping_sub(*b).wrapping_sub(*c) ^ (*c >> 3);
        *b = b.wrapping_sub(*c).wrapping_sub(*a) ^ (*a << 10);
        *c = c.wrapping_sub(*a).wrapping_sub(*b) ^ (*b >> 15);
    }
    let word = |s: &[u8]| u32::from_le_bytes([s[0], s[1], s[2], s[3]]);
    let (mut a, mut b, mut c) = (0x9e37_79b9u32, 0x9e37_79b9u32, init);
    // the whole length, as the C++ uint32 had it (the caller passes an int)
    let length = k.len() as u32;
    let mut k = k;
    while k.len() >= 12 {
        a = a.wrapping_add(word(&k[0..4]));
        b = b.wrapping_add(word(&k[4..8]));
        c = c.wrapping_add(word(&k[8..12]));
        mix(&mut a, &mut b, &mut c);
        k = &k[12..];
    }
    c = c.wrapping_add(length);
    let mut tail = [0u8; 12];
    tail[..k.len()].copy_from_slice(k);
    a = a.wrapping_add(word(&tail[0..4]));
    b = b.wrapping_add(word(&tail[4..8]));
    // the first byte of c is reserved for the length
    c = c.wrapping_add(word(&tail[8..12]) << 8);
    mix(&mut a, &mut b, &mut c);
    c
}

/// Util::ReduceStr, in place: every `from` becomes `to` (shorter or the same
/// length), looking again from the start after each replacement, as the C++
/// did; a match can only reappear where the text changed, so the search goes
/// on from there. An empty `from` or a `to` equal to it (the C++ looped
/// forever) or a longer `to` (it wrote past the text) leaves the text as it
/// is. Returns the length.
pub fn reduce_str(buf: &mut [u8], from: &[u8], to: &[u8]) -> usize {
    let mut len = buf.len();
    if from.is_empty() || to.len() > from.len() || to == from {
        return len;
    }
    let mut at = 0;
    while let Some(k) = buf[at..len].windows(from.len()).position(|w| w == from) {
        let p = at + k;
        buf[p..p + to.len()].copy_from_slice(to);
        buf.copy_within(p + from.len()..len, p + to.len());
        len -= from.len() - to.len();
        at = (p + 1).saturating_sub(from.len());
    }
    len
}

/// The tokens of the C++ Tokenizer: strtok_r's (runs between separators),
/// trimmed of spaces, tabs, CR and LF, empty ones skipped.
pub fn tokens<'a>(s: &'a [u8], separators: &'a [u8]) -> impl Iterator<Item = &'a [u8]> + 'a {
    s.split(move |b| separators.contains(b)).filter_map(|t| {
        let is_ws = |b: &u8| matches!(b, b'\n' | b'\r' | b' ' | b'\t');
        let start = t.iter().position(|b| !is_ws(b))?;
        let end = t.iter().rposition(|b| !is_ws(b))? + 1;
        Some(&t[start..end])
    })
}

/// Util::MatchFileExt: whether `filename` ends with one of the extensions of
/// `list` (strcasecmp, folding through `case_lower`, unsigned bytes) or matches
/// one with '*' or '?' as a WildMask (folding through `mask_lower`, as the C++
/// char).
pub fn match_file_ext(filename: &[u8], list: &[u8], separators: &[u8], case_lower: &Lower<'_>, mask_lower: &Lower<'_>) -> bool {
    tokens(list, separators).any(|ext| {
        (filename.len() >= ext.len()
            && filename[filename.len() - ext.len()..].iter().zip(ext).all(|(&a, &b)| case_lower.eq(a, b)))
            || (ext.iter().any(|&b| b == b'*' || b == b'?')
                && crate::wildmask::wild_match(mask_lower, ext, filename, None))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats() {
        assert_eq!(format_size(0), "0 MB");
        assert_eq!(format_size(512), "512 B");
        assert_eq!(format_size(1536), "1.50 KB");
        assert_eq!(format_size(5 * 1024 * 1024 * 1024), "5.00 GB");
        assert_eq!(format_speed(500), "0 KB/s");
        assert_eq!(format_speed(85_496_208), "81.5 MB/s");
    }

    #[test]
    fn hash() {
        // the init value and every byte count in the tail change the hash
        // (rust/tests/util_differential.py compares it with the C++)
        let h: Vec<u32> = (0..=24).map(|n| hash_bj96(&b"Four score and seven years ago"[..n], 0)).collect();
        assert!(h.windows(2).all(|w| w[0] != w[1]));
        assert_ne!(hash_bj96(b"x", 0), hash_bj96(b"x", 1));
    }

    #[test]
    fn reduce() {
        let mut b = b"TTTF|FT".to_vec();
        let n = reduce_str(&mut b, b"TT", b"T");
        assert_eq!(&b[..n], b"TF|FT");
        let mut b = b"a-b--c".to_vec();
        let n = reduce_str(&mut b, b"-", b"");
        assert_eq!(&b[..n], b"abc");
    }

    #[test]
    fn file_ext() {
        fn ascii(b: u8) -> std::ffi::c_int {
            b.to_ascii_lowercase() as std::ffi::c_int
        }
        let l = Lower::Fold(&ascii);
        let m = |f: &[u8], list: &[u8]| match_file_ext(f, list, b",;", &l, &l);
        assert!(m(b"a.NZB", b".zip, .nzb"));
        assert!(m(b"x.r01", b"*.r??"));
        assert!(!m(b"a.nzb", b".zip"));
        assert_eq!(tokens(b" a ,, b\t;", b",;").collect::<Vec<_>>(), [b"a" as &[u8], b"b"]);
    }
}
