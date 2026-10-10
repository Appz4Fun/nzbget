//! Deobfuscation: the file name in a usenet subject (Deobfuscate) and
//! whether a file name looks like an obfuscated hash (IsExcessivelyObfuscated).
//! It matches the C++ code: character classes are the C library's (current
//! locale) and the regular expressions, written out by hand, the ASCII ones
//! std::regex used (classic locale).

use std::ffi::c_int;

use crate::filetypes::{file_extension, is_parity_ext, is_rar_ext, is_rar_volume_ext, is_seven_zip_ext};

extern "C" {
    fn isalpha(c: c_int) -> c_int;
    fn isalnum(c: c_int) -> c_int;
    fn isdigit(c: c_int) -> c_int;
    fn isupper(c: c_int) -> c_int;
    fn islower(c: c_int) -> c_int;
}

fn alpha(b: u8) -> bool {
    unsafe { isalpha(b as c_int) != 0 }
}
fn alnum(b: u8) -> bool {
    unsafe { isalnum(b as c_int) != 0 }
}
fn digit(b: u8) -> bool {
    unsafe { isdigit(b as c_int) != 0 }
}
fn upper(b: u8) -> bool {
    unsafe { isupper(b as c_int) != 0 }
}
fn lower(b: u8) -> bool {
    unsafe { islower(b as c_int) != 0 }
}

const MAX_TITLE_LEN: usize = 32;
const MAX_PLAUSIBLE_EXT_LEN: usize = 4;
const MIN_DEOBFUSCATE_SIZE: usize = 3;
const MIN_ALNUM_HASH_LEN: usize = 12;
const MIN_CAPS_HASH_LEN: usize = 10;
const MAX_MOVIE_TITLE_LEN: usize = 15;
const MIN_ALPHA_RUN_HASH_LEN: usize = 24;
const MIN_NUMERIC_HASH_LEN: usize = 16;
const MIN_INTERIOR_CAPS_COUNT: usize = 3;
const MIN_CASE_TRANSITIONS_FOR_HASH: usize = 3;

fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if from > hay.len() {
        return None;
    }
    if needle.is_empty() {
        return Some(from);
    }
    hay[from..].windows(needle.len()).position(|w| w == needle).map(|k| from + k)
}

fn rfind(hay: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.len() > hay.len() {
        return None;
    }
    (0..=hay.len() - needle.len()).rev().find(|&k| &hay[k..k + needle.len()] == needle)
}

fn strip_one_extension(s: &[u8]) -> &[u8] {
    let Some(dot) = s.iter().rposition(|&b| b == b'.') else { return s };
    let ext = &s[dot + 1..];
    if ext.is_empty() || ext.len() > MAX_PLAUSIBLE_EXT_LEN || !ext.iter().any(|&c| alpha(c)) {
        return s;
    }
    &s[..dot]
}

/// The extension as written, and the real one before a numeric volume
/// extension (".001" of "x.rar.001").
fn extension_info(s: &[u8]) -> (Vec<u8>, Vec<u8>) {
    let raw = file_extension(s).to_vec();
    if raw.is_empty() {
        return (raw, Vec::new());
    }
    let mut real = raw.clone();
    if raw.len() > 1 && raw[0] == b'.' && raw[1..].iter().all(|&c| digit(c)) {
        real = file_extension(&s[..s.len() - raw.len()]).to_vec();
    }
    (raw, real)
}

fn looks_like_camel_case_title(tok: &[u8]) -> bool {
    if tok.is_empty() {
        return false;
    }
    const CONNECTORS: [&[u8]; 7] = [b"On", b"In", b"To", b"Of", b"At", b"By", b"No"];
    const ROMAN: [&[u8]; 24] = [
        b"XXX", b"XXIII", b"XXII", b"XXI", b"XX", b"XIX", b"XVIII", b"XVII", b"XVI", b"XV", b"XIV", b"XIII", b"XII", b"XI",
        b"X", b"IX", b"VIII", b"VII", b"VI", b"V", b"IV", b"III", b"II", b"I",
    ];
    let is_year = |s: &[u8]| s.len() == 4 && (s.starts_with(b"19") || s.starts_with(b"20"));
    let match_word = |p: usize| -> Option<usize> {
        if p >= tok.len() || !upper(tok[p]) {
            return None;
        }
        for conn in CONNECTORS {
            if tok[p..].starts_with(conn) {
                // followed by lowercase: part of a longer word ("Into", "Only")
                if p + 2 < tok.len() && lower(tok[p + 2]) {
                    break;
                }
                return Some(p + 2);
            }
        }
        let mut end = p + 1;
        while end < tok.len() && lower(tok[end]) {
            end += 1;
        }
        (end - p >= 3).then_some(end)
    };
    let Some(mut pos) = match_word(0) else { return false };
    while pos < tok.len() {
        let mut next = pos;
        while next < tok.len() && digit(tok[next]) {
            next += 1;
        }
        let count = next - pos;
        if count > 0 && !is_year(&tok[pos..next]) && count > 2 {
            break;
        }
        match match_word(next) {
            Some(end) => pos = end,
            None => break,
        }
    }
    if pos == tok.len() {
        return true;
    }
    let tail = &tok[pos..];
    if tail.iter().all(|&c| digit(c)) && ((1..=3).contains(&tail.len()) || is_year(tail)) {
        return true;
    }
    ROMAN.contains(&tail)
}

fn is_vowel(c: u8) -> bool {
    b"aeiouyAEIOUY".contains(&c)
}

fn count_vowels(s: &[u8]) -> usize {
    s.iter().filter(|&&c| is_vowel(c)).count()
}

fn looks_like_hash_blob(tok: &[u8]) -> bool {
    if tok.is_empty() {
        return true;
    }
    if looks_like_camel_case_title(tok) {
        return false;
    }
    let (mut alphas, mut digits, mut uppers, mut lowers) = (0, 0, 0, 0);
    for &c in tok {
        if alpha(c) {
            alphas += 1;
            if upper(c) {
                uppers += 1;
            } else {
                lowers += 1;
            }
        }
        if digit(c) {
            digits += 1;
        }
    }
    let n = tok.len();
    // 1. a mixed alphanumeric token of 12+ characters
    if n >= MIN_ALNUM_HASH_LEN && alphas > 0 && digits > 0 && alphas + digits == n {
        return true;
    }
    // 2. 16+ digits
    if digits >= MIN_NUMERIC_HASH_LEN && digits == n {
        return true;
    }
    // 3. short all-caps titles with plausible vowels
    if n <= MAX_MOVIE_TITLE_LEN && alphas > 0 && digits == 0 && uppers == alphas && (n <= 3 || count_vowels(tok) * 5 >= n) {
        return false;
    }
    // 4. interior caps or an all-caps consonant string
    let allowed = MIN_INTERIOR_CAPS_COUNT + upper(tok[0]) as usize;
    if n >= MIN_CAPS_HASH_LEN && digits == 0 && uppers >= allowed {
        if uppers == alphas {
            if count_vowels(tok) == 0 {
                return true;
            }
        } else {
            let transitions = tok.windows(2).filter(|w| upper(w[0]) != upper(w[1])).count();
            if transitions >= MIN_CASE_TRANSITIONS_FOR_HASH {
                return true;
            }
        }
    }
    // 5. long single-case alphabetic runs with < 20% vowels
    n >= MIN_ALPHA_RUN_HASH_LEN && alphas == n && (lowers == alphas || uppers == alphas) && count_vowels(tok) * 5 < n
}

fn all(s: &[u8], f: impl Fn(u8) -> bool) -> bool {
    s.iter().all(|&c| f(c))
}

/// HASHED_RELEASES_REGEXES (ECMAScript, classic locale: ASCII classes and
/// case folding), searched in the stem.
fn hashed_release(s: &[u8]) -> bool {
    let n = s.len();
    let az09 = |c: u8| c.is_ascii_lowercase() || c.is_ascii_digit();
    let ci = |a: &[u8], lit: &[u8]| a.eq_ignore_ascii_case(lit);
    (n >= 24 && all(&s[..24], |c| c.is_ascii_alphanumeric()))
        || ((16..=256).contains(&n) && all(s, az09))
        || (n >= 16 && all(s, |c| c.is_ascii_digit()))
        || ci(s, b"abc")
        || (n >= 7 && ci(&s[..3], b"abc") && b"-_. ".contains(&s[3]) && ci(&s[4..7], b"xyz"))
        || s == b"123"
        || ci(s, b"b00bs")
        || backup_release(s)
        || (n == 9 && all(&s[..6], |c| c.is_ascii_digit()) && s[6] == b'_' && all(&s[7..], |c| c.is_ascii_digit()))
        || (n == 14 && all(&s[..11], |c| c.is_ascii_uppercase()) && all(&s[11..], |c| c.is_ascii_digit()))
        || (n == 15 && all(&s[..12], |c| c.is_ascii_lowercase()) && all(&s[12..], |c| c.is_ascii_digit()))
}

/// ^Backup_[0-9]{5,256}S[0-9]{2}-[0-9]{2}$
fn backup_release(s: &[u8]) -> bool {
    let Some(rest) = s.strip_prefix(b"Backup_") else { return false };
    let digits = rest.iter().take_while(|c| c.is_ascii_digit()).count();
    // the digits run then "S##-##": backtracking can't change where S is
    (5..=256).contains(&digits)
        && rest.len() == digits + 6
        && rest[digits] == b'S'
        && all(&rest[digits + 1..digits + 3], |c| c.is_ascii_digit())
        && rest[digits + 3] == b'-'
        && all(&rest[digits + 4..], |c| c.is_ascii_digit())
}

/// EXCLUDED_MULTIPART_REGEX: (part\d+\.(rar|par2)$)|(vol\d+\+\d+\.par2$),
/// case-insensitive, searched anywhere (so: a suffix).
fn excluded_multipart(s: &[u8]) -> bool {
    let lower: Vec<u8> = s.to_ascii_lowercase();
    let ends_digits_after = |head: &[u8], prefix: &[u8]| -> bool {
        let d = head.iter().rev().take_while(|c| c.is_ascii_digit()).count();
        d > 0 && head[..head.len() - d].ends_with(prefix)
    };
    for ext in [&b".rar"[..], b".par2"] {
        if let Some(head) = lower.strip_suffix(ext) {
            if ends_digits_after(head, b"part") {
                return true;
            }
        }
    }
    if let Some(head) = lower.strip_suffix(b".par2") {
        let d2 = head.iter().rev().take_while(|c| c.is_ascii_digit()).count();
        if d2 > 0 {
            let head = &head[..head.len() - d2];
            if let Some(head) = head.strip_suffix(b"+") {
                if ends_digits_after(head, b"vol") {
                    return true;
                }
            }
        }
    }
    false
}

/// Deobfuscation::IsExcessivelyObfuscated.
pub fn is_excessively_obfuscated(s: &[u8]) -> bool {
    if s.is_empty() {
        return false;
    }
    let (raw, real) = extension_info(s);
    if !real.is_empty() {
        let mut before = &s[..s.len() - raw.len()];
        if let Some(&last) = before.last() {
            if matches!(last, b'.' | b'_' | b'-' | b' ') {
                before = &before[..before.len() - 1];
            }
        }
        let (mut max_run, mut run) = (0, 0);
        for &c in before {
            run = if alnum(c) { run + 1 } else { 0 };
            max_run = max_run.max(run);
        }
        // single-part archives and parity files stay as they are
        if (16..=256).contains(&max_run)
            && (is_seven_zip_ext(&real) || is_rar_ext(&real) || is_rar_volume_ext(&real) || is_parity_ext(&real))
        {
            return false;
        }
    }
    // multipart archives (part01.rar, vol01+02.par2)
    if excluded_multipart(s) {
        return false;
    }
    let stem = strip_one_extension(s);
    if hashed_release(stem) {
        return true;
    }
    let mixed = |t: &[u8]| t.iter().any(|&c| upper(c)) && t.iter().any(|&c| lower(c));
    let mut prev: &[u8] = &[];
    for tok in stem.split(|c| b"._- ".contains(c)).filter(|t| !t.is_empty()) {
        if looks_like_hash_blob(tok) {
            return true;
        }
        if !prev.is_empty() && stem.len() <= MAX_TITLE_LEN && mixed(prev) && mixed(tok) && looks_like_hash_blob(&[prev, tok].concat()) {
            return true;
        }
        prev = tok;
    }
    false
}

fn parse_without_quotes(sv: &[u8]) -> &[u8] {
    if let Some(end) = find(sv, b" yEnc", 0) {
        if end == 0 {
            return sv;
        }
        // find_last_of(' ', end - 1)
        let Some(start) = sv[..end].iter().rposition(|&b| b == b' ') else { return &sv[..end] };
        let start = start + 1;
        return if start < end { &sv[start..end] } else { sv };
    }
    let start = find(sv, b"Re: ", 0);
    let end = rfind(sv, b" (");
    if let Some(start) = start {
        let start = start + 4;
        return match end {
            Some(e) if start < e => &sv[start..e],
            _ => &sv[start..],
        };
    }
    match end {
        Some(e) => &sv[..e],
        None => sv,
    }
}

fn parse_private_nzb(sv: &[u8]) -> Vec<u8> {
    const SIGNATURE: &[u8] = b"[PRiVATE]-[";
    let Some(begin) = find(sv, SIGNATURE, 0) else { return sv.to_vec() };
    let Some(begin) = find(sv, b"]-[", begin + SIGNATURE.len()) else { return sv.to_vec() };
    let begin = begin + 2;
    let end = match rfind(sv, b" - \"\"") {
        Some(e) if e >= begin => e,
        _ => return sv.to_vec(),
    };
    let mut result = Vec::with_capacity(end - begin);
    let mut found = false;
    let mut depth = 0i32;
    for &ch in &sv[begin..end] {
        if ch == b'[' {
            depth += 1;
            if depth == 1 {
                continue;
            }
        }
        if ch == b']' {
            depth -= 1;
            if depth == 0 {
                continue;
            }
        }
        if found && depth == 0 {
            break;
        }
        if !found && depth == 0 {
            result.clear();
            continue;
        }
        if depth == 0 && ch == b'-' {
            continue;
        }
        if depth == 1 && (ch == b'/' || ch == b'\\') {
            result.clear();
            continue;
        }
        if depth == 1 && (ch == b'.' || alpha(ch)) {
            found = true;
        }
        result.push(ch);
    }
    result
}

/// Deobfuscation::Deobfuscate: the file name in a subject.
pub fn deobfuscate(s: &[u8]) -> Vec<u8> {
    if s.len() < MIN_DEOBFUSCATE_SIZE {
        return s.to_vec();
    }
    let Some(first) = s.iter().position(|&b| b == b'"') else { return parse_without_quotes(s).to_vec() };
    if first + 1 >= s.len() {
        return s[first + 1..].to_vec();
    }
    let Some(second) = s[first + 1..].iter().position(|&b| b == b'"').map(|k| first + 1 + k) else {
        return s[first + 1..].to_vec();
    };
    if second == first + 1 {
        // empty quotes: a [PRiVATE]-[signature] release
        return parse_private_nzb(s);
    }
    s[first + 1..second].to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn subjects() {
        assert_eq!(deobfuscate(b"[1/10] - \"show.s01e01.mkv\" yEnc (1/50)"), b"show.s01e01.mkv");
        assert_eq!(deobfuscate(b"some file.rar yEnc (1/3)"), b"file.rar");
        assert_eq!(deobfuscate(b"Re: x.nzb (1/2)"), b"x.nzb");
    }

    #[test]
    fn obfuscation() {
        assert!(is_excessively_obfuscated(b"5KzdcWdGVGUG83Q9jv8KXht4O2k57w.mkv"));
        assert!(!is_excessively_obfuscated(b"Interstellar.2014.1080p.mkv"));
        assert!(!is_excessively_obfuscated(b"abcdef0123456789abcd.part01.rar"));
        assert!(is_excessively_obfuscated(b"abc"));
    }
}
