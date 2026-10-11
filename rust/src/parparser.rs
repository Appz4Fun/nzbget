//! ParParser's name checks (ParParser.cpp): whether a file name is a par2
//! file of a set - its base name and, for a volume, its block count - and
//! whether two names belong to the same set, as the C++ did (BString's
//! 1023-byte cut, the C library's tolower of the C++ char, strcasecmp,
//! strncasecmp and atoi in the current locale).

use std::ffi::{c_char, c_int, CStr};

extern "C" {
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
    fn atoi(s: *const c_char) -> c_int;
}

pub const BSTRING_MAX: usize = 1023;

/// ParParser::ParseParFilename: Some((base name length, block count)) for a
/// par2 file name; the block count is -1 for a volume numbered without one.
/// `lower` is the caller's tolower(char), not Rust's target-default c_char:
/// the C++ compiler may have been invoked with a different char signedness.
pub fn parse_par_filename(name: &[u8], confirmed: bool, lower: &dyn Fn(u8) -> u8) -> Option<(usize, i32)> {
    let mut f: Vec<u8> = name.iter().take(BSTRING_MAX).take_while(|&&b| b != 0).map(|&b| lower(b)).collect();
    // strlen observes a NUL produced by the locale's case conversion, too.
    if let Some(end) = f.iter().position(|&b| b == 0) {
        f.truncate(end);
    }
    if f.len() < 6 {
        return None;
    }
    if !confirmed {
        // cut after the last ".par2"
        let mut end = 0;
        let mut at = 0;
        while let Some(k) = f[at..].windows(5).position(|w| w == b".par2") {
            end = at + k + 5;
            at = end;
        }
        f.truncate(end);
    }
    if f.len() < 6 {
        return None;
    }
    let len = f.len();
    let mut tail = f[len - 5..].to_vec();
    tail.push(0);
    if unsafe { strcasecmp(tail.as_ptr().cast(), c".par2".as_ptr()) } != 0 {
        return None;
    }
    f.truncate(len - 5);
    let mut blocks = 0;
    if let Some(dot) = f.iter().rposition(|&b| b == b'.') {
        let mut p = f[dot..].to_vec();
        p.push(0);
        if unsafe { strncasecmp(p.as_ptr().cast(), c".vol".as_ptr(), 4) } == 0 {
            let sep = p.iter().position(|&b| b == b'+').or_else(|| p.iter().position(|&b| b == b'-'));
            if let Some(b) = sep.filter(|&b| b < p.len() - 1) {
                blocks = if b == 4 { -1 } else { unsafe { atoi(p[b + 1..].as_ptr().cast()) } };
                f.truncate(dot);
            }
        }
    }
    Some((f.len(), blocks))
}

/// ParParser::SameParCollection: both are par2 names with the same base
/// (compared without case, in the current locale, on the names as given).
pub fn same_par_collection(name1: &CStr, name2: &CStr, confirmed: bool, lower: &dyn Fn(u8) -> u8) -> bool {
    let Some((b1, _)) = parse_par_filename(name1.to_bytes(), confirmed, lower) else {
        return false;
    };
    let Some((b2, _)) = parse_par_filename(name2.to_bytes(), confirmed, lower) else {
        return false;
    };
    b1 == b2 && unsafe { strncasecmp(name1.as_ptr(), name2.as_ptr(), b1) } == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        assert_eq!(parse_par_filename(b"Movie.par2", true, &|b| b.to_ascii_lowercase()), Some((5, 0)));
        assert_eq!(parse_par_filename(b"Movie.vol07+08.PAR2", true, &|b| b.to_ascii_lowercase()), Some((5, 8)));
        assert_eq!(parse_par_filename(b"Movie.vol-06.par2", true, &|b| b.to_ascii_lowercase()), Some((5, -1)));
        assert_eq!(parse_par_filename(b"Movie.par2.1", true, &|b| b.to_ascii_lowercase()), None);
        assert_eq!(parse_par_filename(b"Movie.par2.1", false, &|b| b.to_ascii_lowercase()), Some((5, 0)));
        assert_eq!(parse_par_filename(b".par2", true, &|b| b.to_ascii_lowercase()), None);
        assert!(same_par_collection(c"A.vol00+01.par2", c"a.par2", true, &|b| b.to_ascii_lowercase()));
        assert!(!same_par_collection(c"A.par2", c"B.par2", true, &|b| b.to_ascii_lowercase()));
    }

    #[test]
    fn case_folding_can_introduce_terminators_and_separators() {
        let fold = |b: u8| match b {
            b'X' => 0,
            255 => b'.',
            _ => b.to_ascii_lowercase(),
        };
        assert_eq!(parse_par_filename(b"a.par2Xjunk", true, &fold), Some((1, 0)));
        assert_eq!(parse_par_filename(b"a.vol1+X8.par2", false, &fold), None);
        assert_eq!(parse_par_filename(b"a\xffpar2", false, &fold), Some((1, 0)));
        assert_eq!(parse_par_filename(b"a\xffpar2", false, &|b| b.to_ascii_lowercase()), None);
        assert_eq!(parse_par_filename(b"a.par2\0ignored.par2", true, &fold), Some((1, 0)));
    }
}
