//! NzbFile's own logic (NzbFile.cpp): a file's segments put in part-number
//! order, the parts its subject declares ("(1/N)") and the tail they count
//! when the nzb plainly stops short, the file's sizes, and the test for
//! filenames that came out of the subjects as duplicates. The XML parsing,
//! the queue objects and the filenames' extraction stay C++.

use std::collections::HashMap;

/// The C library's character classes and lower case under the daemon's
/// locale, as isspace/isdigit((unsigned char)c) and tolower(char) saw them.
pub struct Ctype<'a> {
    /// The classes of unsigned bytes 0..=255.
    pub classes: &'a [u16],
    pub space: u16,
    pub digit: u16,
    /// tolower of the char values -128..=255 (index + 128).
    pub lower: &'a [i32],
    /// Whether char is signed: tolower(*p) took the byte as a char.
    pub char_signed: bool,
}

impl Ctype<'_> {
    fn is_space(&self, b: u8) -> bool {
        self.classes[b as usize] & self.space != 0
    }

    fn is_digit(&self, b: u8) -> bool {
        self.classes[b as usize] & self.digit != 0
    }

    /// The byte as the C++ char's value.
    fn char_value(&self, b: u8) -> i32 {
        if self.char_signed { b as i8 as i32 } else { b as i32 }
    }

    /// `*p = tolower(*p)` on a char.
    fn to_lower(&self, b: u8) -> u8 {
        self.lower[(self.char_value(b) + 128) as usize] as u8
    }
}

/// NzbFile::DeclaredParts: the part count posters put at the very end of
/// the subject, "(1/N)" (N up to 1,000,000; 0 for none).
pub fn declared_parts(subject: &[u8], ct: &Ctype) -> i32 {
    let s = subject;
    let mut end = s.len();
    while end > 0 && ct.is_space(s[end - 1]) {
        end -= 1;
    }
    if end == 0 || s[end - 1] != b')' {
        return 0;
    }
    let mut p = end - 1;
    let mut total: i64 = 0;
    let mut scale: i64 = 1;
    while p > 0 && ct.is_digit(s[p - 1]) && scale <= 1_000_000 {
        p -= 1;
        total += (ct.char_value(s[p]) - b'0' as i32) as i64 * scale;
        scale *= 10;
    }
    if scale == 1 || p == 0 || s[p - 1] != b'/' {
        return 0;
    }
    p -= 1;
    let digits = p;
    while p > 0 && ct.is_digit(s[p - 1]) {
        p -= 1;
    }
    if p == digits || p == 0 || s[p - 1] != b'(' {
        return 0;
    }
    if total <= 1_000_000 { total as i32 } else { 0 }
}

/// NzbFile::DeclaredTail: the parts the subject declares when they count
/// past the last listed segment (`last`), else 0. `sizes` are the listed
/// segments' sizes in part order.
pub fn declared_tail(subject: &[u8], last: i32, sizes: &[i64], ct: &Ctype) -> i32 {
    let listed = sizes.len() as i32;
    let declared = declared_parts(subject, ct);
    if listed < 2 || declared.wrapping_sub(last) < 100 || (listed as i64) * 3 >= (declared as i64) * 2 {
        return 0;
    }
    // BString<1024>: the first 1023 bytes, in lower case
    let cut = &subject[..subject.len().min(1023)];
    let lower: Vec<u8> = cut.iter().map(|&b| ct.to_lower(b)).collect();
    // strstr stops at a NUL tolower made (none for real tables)
    let lower = &lower[..lower.iter().position(|&b| b == 0).unwrap_or(lower.len())];
    if crate::bytes::find(lower, b".par2").is_some() {
        return 0;
    }
    let mut sorted = sizes.to_vec();
    let half = sorted.len() / 2;
    let median = *sorted.select_nth_unstable(half).1;
    let last_size = sizes[sizes.len() - 1];
    let same_size = sizes.iter().filter(|&&s| s == median).count() as i64;
    let full = if same_size * 2 >= listed as i64 {
        last_size == median
    } else {
        last_size.wrapping_mul(100) >= median.wrapping_mul(99)
    };
    if median > 0 && full { declared } else { 0 }
}

/// What NzbFile::AddFileInfo makes of a file's segments.
#[derive(Debug, PartialEq, Eq, Default)]
pub struct FileTotals {
    /// The segments kept, in part-number order (indexes into the input):
    /// of two with one number the later counts.
    pub order: Vec<usize>,
    pub total_articles: i32,
    pub missed_articles: i32,
    pub size: i64,
    pub remaining_size: i64,
    pub missed_size: i64,
    /// The subject's declared parts counted past the last listed one.
    pub cut_short: bool,
}

/// NzbFile::AddFileInfo's arithmetic over a file's segments (`parts` and
/// `sizes` in the nzb's order). None when no segment is left.
pub fn file_totals(subject: &[u8], parts: &[i32], sizes: &[i64], ct: &Ctype) -> Option<FileTotals> {
    let mut order: Vec<usize> = (0..parts.len()).collect();
    order.sort_by_key(|&i| parts[i]);
    let mut kept = Vec::with_capacity(order.len());
    for (k, &i) in order.iter().enumerate() {
        if order.get(k + 1).is_none_or(|&next| parts[next] != parts[i]) {
            kept.push(i);
        }
    }
    let first = *kept.first()?;
    let kept_sizes: Vec<i64> = kept.iter().map(|&i| sizes[i]).collect();
    let mut total = parts[kept[kept.len() - 1]];
    let mut cut_short = false;
    let declared = declared_tail(subject, total, &kept_sizes, ct);
    if declared != 0 {
        total = declared;
        cut_short = true;
    }
    let missed = total.wrapping_sub(kept.len() as i32);
    let one = sizes[first];
    let listed: i64 = kept_sizes.iter().fold(0i64, |a, &s| a.wrapping_add(s));
    // int * int64
    let missed_size = (missed as i64).wrapping_mul(one);
    let size = listed.wrapping_add(missed_size);
    Some(FileTotals {
        order: kept,
        total_articles: total,
        missed_articles: missed,
        size,
        remaining_size: size.wrapping_sub(missed_size),
        missed_size,
        cut_short,
    })
}

/// NzbFile::HasDuplicateFilenames: whether some file's name comes again in
/// two or more later files with other subjects (or in one, when the nzb has
/// just two files), names and subjects compared byte for byte as strcmp did.
/// One pass from the end, counting each name's and each (name, subject)'s
/// later files.
pub fn has_duplicate_filenames(files: &[(&[u8], &[u8])]) -> bool {
    let mut names: HashMap<&[u8], usize> = HashMap::with_capacity(files.len());
    let mut pairs: HashMap<(&[u8], &[u8]), usize> = HashMap::with_capacity(files.len());
    for &(name, subject) in files.iter().rev() {
        let later = names.get(name).copied().unwrap_or(0);
        let same = pairs.get(&(name, subject)).copied().unwrap_or(0);
        let dupe = 1 + later - same;
        if dupe > 2 || (dupe == 2 && files.len() == 2) {
            return true;
        }
        *names.entry(name).or_default() += 1;
        *pairs.entry((name, subject)).or_default() += 1;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with_c_locale<T>(f: impl FnOnce(&Ctype) -> T) -> T {
        let mut classes = [0u16; 256];
        for b in 0..256usize {
            if matches!(b as u8, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c) {
                classes[b] |= 1;
            }
            if (b as u8).is_ascii_digit() {
                classes[b] |= 2;
            }
        }
        let lower: Vec<i32> = (-128..256).map(|c: i32| if (65..=90).contains(&c) { c + 32 } else { c }).collect();
        f(&Ctype { classes: &classes, space: 1, digit: 2, lower: &lower, char_signed: true })
    }

    #[test]
    fn parts() {
        with_c_locale(|ct| {
            assert_eq!(declared_parts(b"x yEnc (1/3709)", ct), 3709);
            assert_eq!(declared_parts(b"x yEnc (12/3709) \r\n", ct), 3709);
            assert_eq!(declared_parts(b"x (1/1000000)", ct), 1_000_000);
            assert_eq!(declared_parts(b"x (1/1000001)", ct), 0);
            // the scale stops the digits at 7: an 8th digit before the slash
            assert_eq!(declared_parts(b"x (1/12345678)", ct), 0);
            assert_eq!(declared_parts(b"x (/37)", ct), 0);
            assert_eq!(declared_parts(b"(1/37)", ct), 37);
            assert_eq!(declared_parts(b"1/37)", ct), 0);
            assert_eq!(declared_parts(b"x [1/37]", ct), 0);
            assert_eq!(declared_parts(b"", ct), 0);
            assert_eq!(declared_parts(b")", ct), 0);
        });
    }

    #[test]
    fn tails() {
        with_c_locale(|ct| {
            let full = vec![740_000i64; 20];
            // 20 of 3709 listed, last full-size: counts
            assert_eq!(declared_tail(b"a.rar yEnc (1/3709)", 20, &full, ct), 3709);
            // under 100 past the last, too many listed, par2, short last segment
            assert_eq!(declared_tail(b"a.rar yEnc (1/119)", 20, &full, ct), 0);
            assert_eq!(declared_tail(b"a.rar yEnc (1/29)", 20, &full, ct), 0);
            assert_eq!(declared_tail(b"A.PAR2 yEnc (1/3709)", 20, &full, ct), 0);
            let mut short = full.clone();
            *short.last_mut().unwrap() = 1000;
            assert_eq!(declared_tail(b"a.rar yEnc (1/3709)", 20, &short, ct), 0);
            assert_eq!(declared_tail(b"a.rar yEnc (1/3709)", 1, &full[..1], ct), 0);
            // mixed sizes: within 1 % of the median
            let mixed: Vec<i64> = (0..20).map(|i| 700_000 + i * 1000).collect();
            assert_eq!(declared_tail(b"a.rar yEnc (1/3709)", 20, &mixed, ct), 3709);
            // ".par2" past the 1023-byte cut doesn't count
            let long = [vec![b'x'; 1020], b".par2 (1/3709)".to_vec()].concat();
            assert_eq!(declared_tail(&long, 20, &full, ct), 3709);
        });
    }

    #[test]
    fn totals() {
        with_c_locale(|ct| {
            let t = file_totals(b"s", &[3, 1, 2, 2, 5], &[30, 10, 20, 21, 50], ct).unwrap();
            assert_eq!(t.order, vec![1, 3, 0, 4]);
            assert_eq!((t.total_articles, t.missed_articles), (5, 1));
            assert_eq!((t.size, t.remaining_size, t.missed_size), (10 + 21 + 30 + 50 + 10, 111, 10));
            assert!(!t.cut_short);
            assert_eq!(file_totals(b"s", &[], &[], ct), None);
        });
    }

    #[test]
    fn duplicates() {
        let f = |v: &[(&'static str, &'static str)]| {
            has_duplicate_filenames(&v.iter().map(|&(a, b)| (a.as_bytes(), b.as_bytes())).collect::<Vec<_>>())
        };
        assert!(!f(&[("a", "1"), ("b", "2"), ("a", "3")]));
        assert!(f(&[("a", "1"), ("b", "2"), ("a", "3"), ("a", "4")]));
        assert!(f(&[("a", "1"), ("a", "2")]));
        assert!(!f(&[("a", "1"), ("a", "1")]));
        assert!(!f(&[("a", "1"), ("a", "1"), ("a", "1")]));
        assert!(!f(&[("a", "1"), ("A", "2"), ("a", "3")]));
        // same subject later doesn't count, others do
        assert!(f(&[("a", "1"), ("a", "1"), ("a", "2"), ("a", "3")]));
        assert!(!f(&[]));
    }
}
