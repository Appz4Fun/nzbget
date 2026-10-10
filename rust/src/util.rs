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
    fn sscanf(s: *const c_char, format: *const c_char, ...) -> c_int;
    fn isspace(c: c_int) -> c_int;
    fn isalpha(c: c_int) -> c_int;
    fn isdigit(c: c_int) -> c_int;
    fn tolower(c: c_int) -> c_int;
    fn atoi(s: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
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
    if len_from == 0 || len_to > len_from {
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

/// Util::SplitCommandLine: words split at spaces; a word starting with `'`
/// runs to the next lone `'` (`''` is a quote), each cut to 1023 bytes.
pub fn split_command_line(s: &[u8]) -> Vec<Vec<u8>> {
    const MAX: usize = 1023;
    let at = |i: usize| s.get(i).copied().unwrap_or(0);
    let mut result = Vec::new();
    let mut buf = Vec::new();
    let mut escaping = false;
    let mut space = true;
    let mut i = 0;
    loop {
        let c = at(i);
        if c != 0 {
            if escaping {
                if c == b'\'' {
                    if at(i + 1) == b'\'' && buf.len() < MAX {
                        buf.push(c);
                        i += 1;
                    } else {
                        escaping = false;
                        space = true;
                    }
                } else if buf.len() < MAX {
                    buf.push(c);
                }
            } else if c == b' ' {
                space = true;
            } else if c == b'\'' && space {
                escaping = true;
                space = false;
            } else if buf.len() < MAX {
                buf.push(c);
                space = false;
            }
        }
        if (space || c == 0) && !buf.is_empty() {
            result.push(std::mem::take(&mut buf));
        }
        if c == 0 {
            break;
        }
        i += 1;
    }
    result
}

fn line_space(c: u8) -> bool {
    matches!(c, b'\n' | b'\r' | b' ' | b'\t')
}

/// Util::TrimRight(char*): the length without trailing CR, LF, space and tab.
pub fn trim_right_line(s: &[u8]) -> usize {
    s.len() - s.iter().rev().take_while(|&&c| line_space(c)).count()
}

/// Util::Trim(char*): (start, end) without CR, LF, space and tab around.
pub fn trim_line(s: &[u8]) -> (usize, usize) {
    let end = trim_right_line(s);
    (s[..end].iter().take_while(|&&c| line_space(c)).count(), end)
}

/// Util::Trim(std::string&): (start, end) without the locale's isspace around:
/// TrimLeft tests unsigned bytes, TrimRight the C++ char (signed or not).
pub fn trim_string(s: &[u8], left: bool, right: bool) -> (usize, usize) {
    let start = if left { s.iter().take_while(|&&c| unsafe { isspace(c as c_int) } != 0).count() } else { 0 };
    let mut end = s.len();
    if right {
        while end > start && unsafe { isspace(s[end - 1] as c_char as c_int) } != 0 {
            end -= 1;
        }
        // TrimRight runs after TrimLeft erased the start: nothing more to strip
    }
    (start, end)
}

/// Util::SanitizeLine: control characters (below space, and DEL) become
/// spaces, then Trim.
pub fn sanitize_line(s: &mut [u8]) -> (usize, usize) {
    for c in s.iter_mut() {
        if *c < 32 || *c == 127 {
            *c = b' ';
        }
    }
    trim_string(s, true, true)
}

/// Util::EndsWith (std::string_view): `suffix` ends `s`, case-insensitively
/// with the locale's tolower of unsigned bytes unless `case_sensitive`.
pub fn ends_with(s: &[u8], suffix: &[u8], case_sensitive: bool) -> bool {
    if suffix.is_empty() {
        return true;
    }
    if s.len() < suffix.len() {
        return false;
    }
    let tail = &s[s.len() - suffix.len()..];
    if case_sensitive {
        return tail == suffix;
    }
    tail.iter().zip(suffix).all(|(&a, &b)| unsafe { tolower(a as c_int) == tolower(b as c_int) })
}

/// Util::FormatBuffer: each byte as `%02x `.
pub fn format_buffer(buf: &[u8]) -> Vec<u8> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = Vec::with_capacity(buf.len() * 3 + 1);
    for &b in buf {
        out.extend_from_slice(&[HEX[(b >> 4) as usize], HEX[(b & 15) as usize], b' ']);
    }
    out
}

/// Util::Timegm (Boost's arithmetic) on the fields ParseRfc822DateTime sets,
/// in the C++ int arithmetic (wrapping where it would overflow).
fn timegm_c(year: i32, mon: i32, mday: i32, hour: i32, min: i32, sec: i32) -> i64 {
    const DAYS: [[i32; 12]; 2] = [
        [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334],
        [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335],
    ];
    let leap = year % 400 == 0 || (year % 100 != 0 && year % 4 == 0);
    let y = year.wrapping_sub(1);
    let days_from_0 = 365i32.wrapping_mul(y).wrapping_add(y / 400).wrapping_sub(y / 100).wrapping_add(y / 4);
    let day_of_year = DAYS[leap as usize][mon as usize].wrapping_add(mday).wrapping_sub(1);
    let days = days_from_0.wrapping_sub(719162).wrapping_add(day_of_year);
    86400i64 * days as i64 + 3600i32.wrapping_mul(hour) as i64 + 60i32.wrapping_mul(min) as i64 + sec as i64
}

/// WebUtil::ParseRfc822DateTime: `[Day,] DD Mon YYYY HH:MM[:SS] [zone]` as a
/// Unix time, 0 if it doesn't parse. Numbers are read by the C library
/// (sscanf, atoi) and names compared in the current locale, as before.
pub fn parse_rfc822_date_time(s: &CStr) -> i64 {
    let bytes = s.to_bytes_with_nul();
    let mut p = 0;
    while bytes[p] == b' ' {
        p += 1;
    }
    if unsafe { isalpha(bytes[p] as c_int) } != 0 {
        while bytes[p] != 0 && bytes[p] != b',' && bytes[p] != b' ' {
            p += 1;
        }
        if bytes[p] == b',' {
            p += 1;
        }
    }
    let at = |p: usize| bytes[p..].as_ptr().cast::<c_char>();
    let mut month = [0 as c_char; 4];
    let (mut day, mut year, mut hours, mut minutes, mut seconds, mut len): (c_int, c_int, c_int, c_int, c_int, c_int) =
        (0, 0, 0, 0, 0, 0);
    // the format's conversions and the argument types agree; %3s writes at most 4 bytes
    let n = unsafe {
        sscanf(
            at(p),
            c"%d %3s %d %d:%d%n".as_ptr(),
            &mut day as *mut c_int,
            month.as_mut_ptr(),
            &mut year as *mut c_int,
            &mut hours as *mut c_int,
            &mut minutes as *mut c_int,
            &mut len as *mut c_int,
        )
    };
    if n != 5 {
        return 0;
    }
    p += len as usize;
    if bytes[p] == b':' {
        let mut sec_len: c_int = 0;
        if unsafe { sscanf(at(p + 1), c"%d%n".as_ptr(), &mut seconds as *mut c_int, &mut sec_len as *mut c_int) } != 1 {
            return 0;
        }
        p += 1 + sec_len as usize;
    }
    while bytes[p] == b' ' {
        p += 1;
    }
    let mut zone_offset: i32 = 0; // minutes east of UTC
    if (bytes[p] == b'+' || bytes[p] == b'-') && unsafe { isdigit(bytes[p + 1] as c_int) } != 0 {
        let zone = unsafe { atoi(at(p + 1)) };
        zone_offset = (zone / 100).wrapping_mul(60).wrapping_add(zone % 100);
        if bytes[p] == b'-' {
            zone_offset = zone_offset.wrapping_neg();
        }
    } else {
        const ZONES: [(&CStr, i32); 8] = [
            (c"EST", -5), (c"EDT", -4), (c"CST", -6), (c"CDT", -5),
            (c"MST", -7), (c"MDT", -6), (c"PST", -8), (c"PDT", -7),
        ];
        if let Some((_, hours)) = ZONES.iter().find(|(name, _)| unsafe { strncasecmp(at(p), name.as_ptr(), 3) } == 0) {
            zone_offset = hours * 60;
        }
    }
    const MONTHS: [&CStr; 12] = [c"Jan", c"Feb", c"Mar", c"Apr", c"May", c"Jun", c"Jul", c"Aug", c"Sep", c"Oct", c"Nov", c"Dec"];
    let mon = MONTHS.iter().position(|m| unsafe { strcasecmp(month.as_ptr(), m.as_ptr()) } == 0).unwrap_or(0) as i32;
    timegm_c(year, mon, day, hours, minutes, seconds) - zone_offset.wrapping_mul(60) as i64
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
            // Initially equal operands are not a no-op: the first copy
            // truncates the aliased replacement, so the next deletes 'a'.
            let mut b = *b"aa\0";
            reduce_str(b.as_mut_ptr().cast(), c"a".as_ptr(), b.as_ptr().add(1).cast());
            assert_eq!(&b, b"\0\0\0");
        }
    }

    #[test]
    fn command_line_and_trims() {
        assert_eq!(split_command_line(b"a 'b c' 'd''e' f"), [b"a" as &[u8], b"b c", b"d'e", b"f"]);
        assert_eq!(trim_line(b" \tx y\r\n"), (2, 5));
        assert!(ends_with(b"file.NZB", b".nzb", false));
        assert!(!ends_with(b"file.NZB", b".nzb", true));
        assert_eq!(format_buffer(b"\x00\xff"), b"00 ff ");
        assert_eq!(parse_rfc822_date_time(c"Wed, 26 Jun 2013 01:02:54 -0600"), 1372230174);
        assert_eq!(parse_rfc822_date_time(c"26 Jun 2013 01:02 GMT"), 1372208520);
        assert_eq!(parse_rfc822_date_time(c"junk"), 0);
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
