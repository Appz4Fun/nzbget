//! Util's string helpers: FormatSize, FormatSpeed, AlphaNum, HashBJ96,
//! ReduceStr, the Tokenizer's tokens and MatchFileExt. Each matches the C++
//! code it replaces, quirks included.

use crate::wildmask::Lower;
use std::ffi::{c_char, c_int, CStr};

// Use the process C runtime, just as CString::Format does. Rust's formatter
// ignores LC_NUMERIC and the C floating-point rounding mode. Keep raw bytes:
// a locale's decimal separator need not be UTF-8.
extern "C" {
    fn snprintf(buf: *mut c_char, size: usize, format: *const c_char, ...) -> c_int;
}

fn decimal(value: f64, precision: c_int, suffix: &[u8]) -> Vec<u8> {
    let mut buf = vec![0u8; 64];
    loop {
        // The fixed format and promoted varargs types agree; snprintf writes
        // at most buf.len() bytes, including its terminator.
        let n = unsafe { snprintf(buf.as_mut_ptr().cast(), buf.len(), c"%.*f".as_ptr(), precision, value) };
        if n < 0 {
            return Vec::new();
        }
        let n = n as usize;
        if n < buf.len() {
            buf.truncate(n);
            buf.extend_from_slice(suffix);
            return buf;
        }
        buf.resize(n + 1, 0);
    }
}

/// Util::FormatSize: the C++ computes in float and prints with "%.2f".
pub fn format_size(size: i64) -> Vec<u8> {
    let f = size as f32;
    if size > 1024 * 1024 * 1000 {
        decimal((f / 1024.0 / 1024.0 / 1024.0) as f64, 2, b" GB")
    } else if size > 1024 * 1000 {
        decimal((f / 1024.0 / 1024.0) as f64, 2, b" MB")
    } else if size > 1000 {
        decimal((f / 1024.0) as f64, 2, b" KB")
    } else if size == 0 {
        b"0 MB".to_vec()
    } else {
        // (int) of an int64: wraps
        format!("{} B", size as i32).into_bytes()
    }
}

/// Util::FormatSpeed.
pub fn format_speed(bps: i64) -> Vec<u8> {
    const K: i64 = 1024;
    let d = bps as f64;
    if bps >= 100 * K * K * K {
        format!("{} GB/s", bps / K / K / K).into_bytes()
    } else if bps >= 10 * K * K * K {
        decimal(d / 1024.0 / 1024.0 / 1024.0, 1, b" GB/s")
    } else if bps >= K * K * K {
        decimal(d / 1024.0 / 1024.0 / 1024.0, 2, b" GB/s")
    } else if bps >= 100 * K * K {
        format!("{} MB/s", bps / K / K).into_bytes()
    } else if bps >= 10 * K * K {
        decimal(d / 1024.0 / 1024.0, 1, b" MB/s")
    } else if bps >= K * 1000 {
        decimal(d / 1024.0 / 1024.0, 2, b" MB/s")
    } else {
        format!("{} KB/s", bps / K).into_bytes()
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

/// Util::ReduceStr, preserving the legacy forward copies, including every
/// intermediate NUL and the truncation caused by equal-length replacements.
/// Read operands afresh: they may point into the buffer being modified.
///
/// # Safety
/// `s` is null or a writable NUL-terminated string. `from` and `to` are null
/// or readable NUL-terminated strings, and may alias `s`. As in C++, operands
/// must stay terminated during the call. Empty patterns and growing
/// replacements (which could loop forever or overflow in C++) are no-ops.
pub unsafe fn reduce_str(s: *mut c_char, from: *const c_char, to: *const c_char) {
    if s.is_null() || from.is_null() || to.is_null() {
        return;
    }
    let capacity = CStr::from_ptr(s).to_bytes().len();
    let len_from = CStr::from_ptr(from).to_bytes().len();
    let len_to = CStr::from_ptr(to).to_bytes().len();
    if len_from == 0 || len_to > len_from || CStr::from_ptr(from) == CStr::from_ptr(to) {
        return;
    }
    loop {
        // End all shared borrows before writing; an operand may alias s.
        let text = CStr::from_ptr(s).to_bytes();
        let pattern = CStr::from_ptr(from).to_bytes();
        if pattern.is_empty() {
            return;
        }
        let Some(p) = text.windows(pattern.len()).position(|w| w == pattern) else { return };
        // Aliasing can change either operand's length. The C++ still uses
        // their initial lengths to locate the tail, even past the current
        // NUL. Bound access by the original allocation's known string span.
        let replacement_len = CStr::from_ptr(to).to_bytes().len();
        let shift = len_from - len_to;
        if shift > capacity - p || replacement_len > capacity - p - shift {
            return;
        }
        for i in 0..=replacement_len {
            let byte = *to.add(i);
            *s.add(p + i) = byte;
            // A forward-overlapping copy that overwrote its own terminator
            // would run off the allocation in C++; stop before doing that.
            if i == replacement_len && byte != 0 { return; }
        }
        let mut dest = p + replacement_len;
        let mut source = dest + shift;
        loop {
            let byte = *s.add(source);
            *s.add(dest) = byte;
            if byte == 0 { break; }
            dest += 1;
            source += 1;
        }
    }
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
        assert_eq!(format_size(0), b"0 MB");
        assert_eq!(format_size(512), b"512 B");
        assert_eq!(format_size(1536), b"1.50 KB");
        assert_eq!(format_size(5 * 1024 * 1024 * 1024), b"5.00 GB");
        assert_eq!(format_speed(500), b"0 KB/s");
        assert_eq!(format_speed(85_496_208), b"81.5 MB/s");
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
        unsafe {
            for (raw, from, to, expected) in [
                (&b"TTTF|FT\0"[..], c"TT", c"T", &b"TF|FT\0\0\0"[..]),
                (&b"abc\0"[..], c"ab", c"xy", &b"xy\0\0"[..]),
            ] {
                let mut b = raw.to_vec();
                reduce_str(b.as_mut_ptr().cast(), from.as_ptr(), to.as_ptr());
                assert_eq!(b, expected);
            }
            let mut b = *b"ababX\0";
            reduce_str(b.as_mut_ptr().cast(), c"ab".as_ptr(), b.as_ptr().add(4).cast());
            assert_eq!(&b, b"XbX\0\0\0");
        }
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
