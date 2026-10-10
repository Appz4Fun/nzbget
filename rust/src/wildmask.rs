//! Wildcard matching (WildMask): `*` any run, `?` any byte, `#` one digit;
//! letters compare case-insensitively through a table supplied by the C++ caller
//! for its current locale. With positions wanted, it records where each wildcard
//! matched, exactly as the C++ code did (quirks included).

use std::ffi::c_int;

/// Case folding of one byte, as the C++ code's tolower saw it: the full-width
/// tolower result of the byte as the caller's char in its current locale (EOF
/// stays distinct from 255).
pub enum Lower<'a> {
    /// glibc's tolower table for the calling thread's locale (what tolower
    /// itself reads), stored in order for char values -128..=255, and whether
    /// that char is signed (a compiler setting, so the C++ side says).
    /// Borrow the entire table so safe Rust callers cannot supply a dangling
    /// pointer or a table that is too short.
    Table(&'a [c_int; 384], bool),
    /// Any other C library: a call per comparison of two different bytes.
    Fold(&'a dyn Fn(u8) -> c_int),
}

impl Lower<'_> {
    #[inline]
    fn get(&self, b: u8) -> c_int {
        match *self {
            Lower::Table(t, signed) => t[(if signed { b as i8 as i32 } else { b as i32 } + 128) as usize],
            Lower::Fold(f) => f(b),
        }
    }

    #[inline]
    fn eq(&self, a: u8, b: u8) -> bool {
        a == b || self.get(a) == self.get(b)
    }
}

// C++ subtracts pointers before narrowing to int. Narrowing the end first and
// doing checked i32 subtraction can panic in Debug even when the length fits.
fn capture_len(end: usize, start: i32) -> i32 {
    (end as i32).wrapping_sub(start)
}

/// Matches `text` against `pat`. When `pos` is Some, it receives the
/// (start, len) of each wildcard match.
pub fn wild_match(lower: &Lower<'_>, pat: &[u8], text: &[u8], mut pos: Option<&mut Vec<(i32, i32)>>) -> bool {
    let want = pos.is_some();
    if let Some(p) = pos.as_deref_mut() {
        p.clear();
    }
    // C strings: reading at the end gives NUL
    let pc = |i: usize| -> u8 { *pat.get(i).unwrap_or(&0) };
    let sc = |i: usize| -> u8 { *text.get(i).unwrap_or(&0) };
    let digit = |c: u8| c.is_ascii_digit();

    let mut w: Vec<(i32, i32)> = Vec::new();
    let (mut p, mut s) = (0usize, 0usize);
    let (mut spos, mut wpos) = (0usize, 0usize);
    let mut qmark = false;
    let mut star = false;

    macro_rules! close_last {
        ($s:expr) => {{
            let n = w.len() - 1;
            w[n].1 = capture_len($s, w[n].0);
        }};
    }

    while sc(s) != 0 && pc(p) != b'*' {
        if want && (pc(p) == b'?' || pc(p) == b'#') {
            if !qmark {
                w.push((s as i32, 0));
                qmark = true;
            }
        } else if want && qmark {
            close_last!(s);
            qmark = false;
        }
        if !(lower.eq(pc(p), sc(s)) || pc(p) == b'?' || (pc(p) == b'#' && digit(sc(s)))) {
            if let Some(out) = pos {
                *out = w;
            }
            return false;
        }
        s += 1;
        p += 1;
    }

    if want && qmark {
        close_last!(s);
        qmark = false;
    }

    while sc(s) != 0 {
        if pc(p) == b'*' {
            if want && qmark {
                close_last!(s);
                qmark = false;
            }
            if want && !star {
                w.push((s as i32, 0));
                star = true;
            }
            p += 1;
            if pc(p) == 0 {
                if want && star {
                    let n = w.len() - 1;
                    w[n].1 = (text.len() - s) as i32;
                }
                if let Some(out) = pos {
                    *out = w;
                }
                return true;
            }
            wpos = p;
            spos = s + 1;
        } else if pc(p) == b'?' || (pc(p) == b'#' && digit(sc(s))) {
            if want && !qmark {
                w.push((s as i32, 0));
                qmark = true;
            }
            p += 1;
            s += 1;
        } else if lower.eq(pc(p), sc(s)) {
            if want && qmark {
                close_last!(s);
                qmark = false;
            } else if want && star {
                close_last!(s);
                star = false;
            }
            p += 1;
            s += 1;
        } else {
            if want && qmark {
                w.pop();
                qmark = false;
            }
            p = wpos;
            s = spos;
            spos += 1;
            star = true;
        }
    }

    if want && qmark {
        close_last!(s);
    }
    if pc(p) == b'*' && want && !star {
        w.push((s as i32, (text.len() - s) as i32));
    }
    while pc(p) == b'*' {
        p += 1;
    }
    if let Some(out) = pos {
        *out = w;
    }
    pc(p) == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ascii(b: u8) -> c_int {
        b.to_ascii_lowercase() as c_int
    }

    fn lower() -> Lower<'static> {
        Lower::Fold(&ascii)
    }

    fn m(p: &str, t: &str) -> bool {
        wild_match(&lower(), p.as_bytes(), t.as_bytes(), None)
    }

    #[test]
    fn matches() {
        assert!(m("*.nzb", "Show.S01E01.NZB"));
        assert!(m("S##E##", "S01E02"));
        assert!(!m("S##E##", "S0xE02"));
        assert!(m("a?c", "abc"));
        assert!(m("*", ""));
        assert!(!m("a", ""));
        assert!(m("192.168.*", "192.168.1.93"));
    }

    #[test]
    fn full_width_locale_results_keep_eof_distinct() {
        let fold = |b: u8| match b {
            0xff => -1,
            0xbe => 255,
            b'I' => 0xfd,
            _ => b.to_ascii_lowercase() as c_int,
        };
        let lower = Lower::Fold(&fold);
        assert!(!wild_match(&lower, b"\xbe", b"\xff", None));
        assert!(wild_match(&lower, b"I", b"\xfd", None));
        assert!(!wild_match(&lower, b"I", b"i", None));
    }

    #[test]
    fn glibc_style_table() {
        // index -128..=255, as glibc's __ctype_tolower_loc table
        let mut table = [0i32; 384];
        for (i, slot) in table.iter_mut().enumerate() {
            let c = i as i32 - 128;
            *slot = if (b'A' as i32..=b'Z' as i32).contains(&c) { c + 32 } else { c };
        }
        let lower = Lower::Table(&table, true);
        assert!(wild_match(&lower, b"*aBc*", b"xxAbCxx", None));
        assert!(!wild_match(&lower, b"\xff", b"\x7f", None));
        assert!(wild_match(&lower, b"\xe9", b"\xe9", None));
        let unsigned = Lower::Table(&table, false);
        assert!(wild_match(&unsigned, b"*aBc*", b"xxAbCxx", None));
    }

    #[test]
    fn capture_length_across_signed_int_boundary() {
        assert_eq!(capture_len(i32::MAX as usize + 3, i32::MAX - 1), 4);
    }

    #[test]
    fn positions() {
        let mut v = Vec::new();
        assert!(wild_match(&lower(), b"S##E*.mkv", b"S01E02.x.mkv", Some(&mut v)));
        assert_eq!(v, vec![(1, 2), (4, 4)]);
    }
}
