//! Wildcard matching (WildMask): `*` any run, `?` any byte, `#` one digit;
//! letters compare case-insensitively through the C library's tolower, so the
//! result matches the C++ code in every locale. With positions wanted, it records
//! where each wildcard matched, exactly as the C++ code did (quirks included).

use std::ffi::{c_char, c_int};
use std::sync::OnceLock;

extern "C" {
    fn tolower(c: c_int) -> c_int;
}

/// tolower of each byte as the C++ code saw it: a `char` (signed or unsigned,
/// as on the platform) widened to int.
pub struct Lower([u8; 256]);

impl Lower {
    fn new() -> Self {
        let mut t = [0u8; 256];
        for (b, slot) in t.iter_mut().enumerate() {
            *slot = unsafe { tolower(b as u8 as c_char as c_int) } as u8;
        }
        Lower(t)
    }

    /// The table of the current locale. nzbget sets the locale once at start,
    /// before any match, so the table is built on first use.
    pub fn get() -> &'static Lower {
        static LOWER: OnceLock<Lower> = OnceLock::new();
        LOWER.get_or_init(Lower::new)
    }

    #[inline]
    fn eq(&self, a: u8, b: u8) -> bool {
        self.0[a as usize] == self.0[b as usize]
    }
}

/// Matches `text` against `pat`. When `pos` is Some, it receives the
/// (start, len) of each wildcard match.
pub fn wild_match(lower: &Lower, pat: &[u8], text: &[u8], mut pos: Option<&mut Vec<(i32, i32)>>) -> bool {
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
            w[n].1 = ($s as i32) - w[n].0;
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

    fn m(p: &str, t: &str) -> bool {
        wild_match(Lower::get(), p.as_bytes(), t.as_bytes(), None)
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
    fn positions() {
        let mut v = Vec::new();
        assert!(wild_match(Lower::get(), b"S##E*.mkv", b"S01E02.x.mkv", Some(&mut v)));
        assert_eq!(v, vec![(1, 2), (4, 4)]);
    }
}
