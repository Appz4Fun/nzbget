//! Options' value parsers (Options.cpp): ParseTime and ParseWeekDays (the
//! scheduler's task times), ValidateOptionName's classification of option
//! names, ConvertOldOption's renames, HasScript and ParseCategorySource.
//! Names are compared with the C library's strcasecmp/strncasecmp and numbers
//! read with atoi/strtol, in the current locale, as the C++ did.

use std::ffi::{c_char, c_int, c_long, CStr, CString};

extern "C" {
    fn atoi(s: *const c_char) -> c_int;
    fn strtol(s: *const c_char, end: *mut *mut c_char, base: c_int) -> c_long;
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
}

fn eq(a: &CStr, b: &CStr) -> bool {
    unsafe { strcasecmp(a.as_ptr(), b.as_ptr()) == 0 }
}

fn eq_n(a: &CStr, b: &CStr, n: usize) -> bool {
    unsafe { strncasecmp(a.as_ptr(), b.as_ptr(), n) == 0 }
}

/// The C string from byte `at` of `s` (at most its length).
fn from(s: &CStr, at: usize) -> &CStr {
    let bytes = s.to_bytes_with_nul();
    CStr::from_bytes_with_nul(&bytes[at.min(bytes.len() - 1)..]).expect("one NUL at the end")
}

/// Options::ParseTime: `*` (a startup task: hours -1), `*:MM` (every hour:
/// hours -2) or `HH:MM`. Writes the outputs as the C++ did, also on failure.
pub fn parse_time(time: &CStr, hours: &mut i32, minutes: &mut i32) -> bool {
    let t = time.to_bytes();
    if t == b"*" {
        *hours = -1;
        *minutes = 0;
        return true;
    }
    if t.iter().any(|c| !b"0123456789: *".contains(c)) {
        return false;
    }
    if t.iter().filter(|&&c| c == b':').count() != 1 {
        return false;
    }
    let colon = t.iter().position(|&c| c == b':').expect("one colon");
    if t[0] == b'*' {
        *hours = -2;
    } else {
        *hours = unsafe { atoi(time.as_ptr()) };
        if *hours < 0 || *hours > 23 {
            return false;
        }
    }
    if t.get(colon + 1) == Some(&b'*') {
        return false;
    }
    *minutes = unsafe { atoi(from(time, colon + 1).as_ptr()) };
    !(*minutes < 0 || *minutes > 59)
}

/// Options::ParseWeekDays: days 1 (Monday) to 7, lists and ranges (`1-5,7`)
/// as bits (bit n: day n + 1). Writes the bits as the C++ did, also on failure.
pub fn parse_week_days(week_days: &[u8], bits: &mut i32) -> bool {
    *bits = 0;
    let mut first_day = 0;
    let mut range = false;
    for &c in week_days {
        match c {
            b'1'..=b'7' => {
                let day = (c - b'0') as i32;
                if range {
                    if day <= first_day || first_day == 0 {
                        return false;
                    }
                    for i in first_day..=day {
                        *bits |= 1 << (i - 1);
                    }
                    first_day = 0;
                } else {
                    *bits |= 1 << (day - 1);
                    first_day = day;
                }
                range = false;
            }
            b',' => range = false,
            b'-' => range = true,
            b' ' => {}
            _ => return false,
        }
    }
    true
}

/// What Options::ValidateOptionName decided (and logged).
#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(i32)]
pub enum NameCheck {
    /// not an option (or a read-only one)
    Invalid = 0,
    Valid = 1,
    /// obsolete, ignored: a warning
    Obsolete = 2,
    /// an obsolete script option: an error when it has a value
    ObsoleteScript = 3,
    /// an obsolete log option (use WriteLog): a warning
    ObsoleteLog = 4,
}

/// The numbered sections and their option suffixes.
const SECTIONS: [(&CStr, usize, &[&CStr]); 4] = [
    (c"server", 6, &[
        c".active", c".name", c".level", c".host", c".port", c".username", c".password", c".joingroup",
        c".encryption", c".connections", c".cipher", c".group", c".retention", c".optional", c".notes",
        c".ipversion", c".certverification",
    ]),
    (c"task", 4, &[c".time", c".weekdays", c".command", c".param", c".downloadrate", c".process"]),
    (c"category", 8, &[c".name", c".destdir", c".extensions", c".unpack", c".aliases"]),
    (c"feed", 4, &[
        c".name", c".url", c".interval", c".filter", c".backlog", c".pausenzb", c".category",
        c".categorySource", c".priority", c".extensions", c".certverification",
    ]),
];

const OBSOLETE: [&CStr; 22] = [
    c"RetryOnCrcError", c"AllowReProcess", c"LoadPars", c"ThreadLimit", c"PostLogKind", c"NZBLogKind",
    c"ProcessLogKind", c"AppendNzbDir", c"RenameBroken", c"MergeNzb", c"StrictParName", c"ReloadUrlQueue",
    c"ReloadPostQueue", c"ParCleanupQueue", c"DeleteCleanupDisk", c"HistoryCleanupDisk", c"SaveQueue",
    c"ReloadQueue", c"TerminateTimeout", c"AccurateRate", c"CreateBrokenLog", c"BrokenLog",
];

/// Options::ValidateOptionName; `predefined` tells whether the name is one of
/// the options (GetOption), asked only after the read-only check.
pub fn validate_option_name(name: &CStr, predefined: &mut dyn FnMut() -> bool) -> NameCheck {
    if [c"ConfigFile", c"AppBin", c"AppDir", c"Version"].iter().any(|n| eq(name, n)) {
        return NameCheck::Invalid;
    }
    if predefined() {
        return NameCheck::Valid;
    }
    for (prefix, len, suffixes) in SECTIONS {
        if eq_n(name, prefix, len) {
            let digits = name.to_bytes()[len.min(name.to_bytes().len())..].iter().take_while(|c| c.is_ascii_digit()).count();
            let rest = from(name, len + digits);
            if suffixes.iter().any(|s| eq(rest, s)) {
                return NameCheck::Valid;
            }
        }
    }
    if name.to_bytes().contains(&b':') {
        return NameCheck::Valid;
    }
    if OBSOLETE.iter().any(|n| eq(name, n)) {
        return NameCheck::Obsolete;
    }
    if [c"PostProcess", c"NZBProcess", c"NZBAddedProcess"].iter().any(|n| eq(name, n)) {
        return NameCheck::ObsoleteScript;
    }
    if [c"ScanScript", c"QueueScript", c"FeedScript"].iter().any(|n| eq(name, n)) {
        return NameCheck::Valid;
    }
    if [c"CreateLog", c"ResetLog"].iter().any(|n| eq(name, n)) {
        return NameCheck::ObsoleteLog;
    }
    NameCheck::Invalid
}

/// CString::Replace(from, to): every case-sensitive occurrence, searching on
/// after each replacement.
fn replace_all(s: &mut Vec<u8>, from: &[u8], to: &[u8]) {
    let mut pos = 0;
    loop {
        // CString::Find: nothing at or past the end (except at 0)
        if pos != 0 && pos >= s.len() {
            return;
        }
        let Some(found) = s[pos..].windows(from.len()).position(|w| w == from) else { return };
        let at = pos + found;
        s.splice(at..at + from.len(), to.iter().copied());
        pos = at + to.len();
    }
}

fn cstring(v: Vec<u8>) -> CString {
    CString::new(v).expect("no NUL: built from C strings")
}

/// Options::ConvertOldOption: the current name and value of an old option.
pub fn convert_old_option(option: &CStr, value: &CStr) -> (CString, CString) {
    let mut option = option.to_owned();
    let mut value = value.to_owned();
    for (old, new) in [
        (c"$MAINDIR", c"MainDir"),
        (c"ServerIP", c"ControlIP"),
        (c"ServerPort", c"ControlPort"),
        (c"ServerPassword", c"ControlPassword"),
        (c"PostPauseQueue", c"ScriptPauseQueue"),
    ] {
        if eq(&option, old) {
            option = new.to_owned();
        }
    }
    if eq(&option, c"ParCheck") && eq(&value, c"yes") {
        value = c"always".to_owned();
    }
    if eq(&option, c"ParCheck") && eq(&value, c"no") {
        value = c"auto".to_owned();
    }
    if eq(&option, c"ParScan") && eq(&value, c"auto") {
        value = c"extended".to_owned();
    }
    if eq(&option, c"DefScript") || eq(&option, c"PostScript") {
        option = c"Extensions".to_owned();
    }
    let name_len = option.to_bytes().len();
    if eq_n(&option, c"Category", 8)
        && ((name_len > 10 && eq(from(&option, name_len - 10), c".DefScript"))
            || (name_len > 11 && eq(from(&option, name_len - 11), c".PostScript")))
    {
        let mut v = option.as_bytes().to_vec();
        replace_all(&mut v, b".DefScript", b".Extensions");
        replace_all(&mut v, b".PostScript", b".Extensions");
        option = cstring(v);
    }
    if eq_n(&option, c"Feed", 4) && name_len > 11 && eq(from(&option, name_len - 11), c".FeedScript") {
        let mut v = option.as_bytes().to_vec();
        replace_all(&mut v, b".FeedScript", b".Extensions");
        option = cstring(v);
    }
    if eq(&option, c"WriteBufferSize") {
        option = c"WriteBuffer".to_owned();
        // strtol's long cut to an int, as the C++ stored it
        let val = unsafe { strtol(value.as_ptr(), std::ptr::null_mut(), 10) } as c_int;
        let val = if val == -1 { 1024 } else { val / 1024 };
        value = cstring(val.to_string().into_bytes());
    }
    for (old, new) in [
        (c"ConnectionTimeout", c"ArticleTimeout"),
        (c"Retries", c"ArticleRetries"),
        (c"RetryInterval", c"ArticleInterval"),
        (c"DumpCore", c"CrashDump"),
    ] {
        if eq(&option, old) {
            option = new.to_owned();
        }
    }
    if eq(&option, c"Decode") {
        option = c"RawArticle".to_owned();
        value = if eq(&value, c"no") { c"yes" } else { c"no" }.to_owned();
    }
    if eq(&option, c"LogBufferSize") {
        option = c"LogBuffer".to_owned();
    }
    (option, value)
}

/// Options::HasScript: `name` is in the `,;`-separated list (as Tokenizer
/// splits and trims it), compared with strcasecmp.
pub fn has_script(list: &[u8], name: &CStr) -> bool {
    crate::util::tokens(list, b",;").any(|t| eq(&cstring(t.to_vec()), name))
}

/// Options::ParseCategorySource: 0 Auto, 1 NZBFile (also the default), 2 FeedFile.
pub fn parse_category_source(value: Option<&CStr>) -> i32 {
    let Some(value) = value else { return 1 };
    if eq_n(value, c"auto", 4) {
        0
    } else if eq_n(value, c"nzbfile", 8) {
        1
    } else if eq_n(value, c"feedfile", 9) {
        2
    } else {
        1
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn times_and_days() {
        let (mut h, mut m) = (99, 99);
        assert!(parse_time(c"*", &mut h, &mut m) && (h, m) == (-1, 0));
        assert!(parse_time(c"*:30", &mut h, &mut m) && (h, m) == (-2, 30));
        assert!(parse_time(c"23:59", &mut h, &mut m) && (h, m) == (23, 59));
        assert!(!parse_time(c"24:00", &mut h, &mut m));
        assert!(!parse_time(c"1:*", &mut h, &mut m));
        assert!(!parse_time(c"1:2:3", &mut h, &mut m));
        let mut b = 0;
        assert!(parse_week_days(b"1-5, 7", &mut b) && b == 0b1011111);
        assert!(!parse_week_days(b"5-1", &mut b));
    }

    #[test]
    fn names() {
        let mut no = || false;
        assert_eq!(validate_option_name(c"Server12.Host", &mut no), NameCheck::Valid);
        assert_eq!(validate_option_name(c"server.port", &mut no), NameCheck::Valid);
        assert_eq!(validate_option_name(c"Feed3.CategorySource", &mut no), NameCheck::Valid);
        assert_eq!(validate_option_name(c"AppDir", &mut || true), NameCheck::Invalid);
        assert_eq!(validate_option_name(c"Script.sh:Opt", &mut no), NameCheck::Valid);
        assert_eq!(validate_option_name(c"loadpars", &mut no), NameCheck::Obsolete);
        assert_eq!(validate_option_name(c"Bogus", &mut no), NameCheck::Invalid);
    }

    #[test]
    fn old_options() {
        let (o, v) = convert_old_option(c"Category2.DefScript", c"x");
        assert_eq!((o.as_bytes(), v.as_bytes()), (b"Category2.Extensions".as_slice(), b"x".as_slice()));
        // matched without case, replaced with case: left as it was
        assert_eq!(convert_old_option(c"category2.defscript", c"x").0.as_bytes(), b"category2.defscript");
        let (o, v) = convert_old_option(c"WriteBufferSize", c"-1");
        assert_eq!((o.as_bytes(), v.as_bytes()), (b"WriteBuffer".as_slice(), b"1024".as_slice()));
        assert_eq!(convert_old_option(c"Decode", c"NO").1.as_bytes(), b"yes");
        assert!(has_script(b"a.py, B.sh", c"b.SH"));
        assert_eq!(parse_category_source(Some(c"FeedFile")), 2);
    }
}
