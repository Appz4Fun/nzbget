//! FileSystem's path text functions: NormalizePathSeparators, BaseFileName,
//! SplitPathAndFilename, ReservedChar, MakeValidFilename,
//! SanitizePathSegment, SanitizeRelativePath, ExtractFilePathFromCmd and
//! EscapePathForShell. They match the C++ code; reserved device names
//! compare as the C library's strncasecmp (current locale).

use std::ffi::{c_char, c_int};

extern "C" {
    #[cfg_attr(windows, link_name = "_strnicmp")]
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
}

#[cfg(windows)]
pub const PATH_SEPARATOR: u8 = b'\\';
#[cfg(windows)]
pub const ALT_PATH_SEPARATOR: u8 = b'/';
#[cfg(not(windows))]
pub const PATH_SEPARATOR: u8 = b'/';
#[cfg(not(windows))]
pub const ALT_PATH_SEPARATOR: u8 = b'\\';

const RESERVED_DEVICE_NAMES: [&str; 22] = [
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
    "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

/// FileSystem::NormalizePathSeparators, in place.
pub fn normalize_path_separators(path: &mut [u8]) {
    for b in path.iter_mut() {
        if *b == ALT_PATH_SEPARATOR {
            *b = PATH_SEPARATOR;
        }
    }
}

/// FileSystem::BaseFileName: the offset of the name after the last
/// separator of either kind.
pub fn base_file_name(path: &[u8]) -> usize {
    path.iter().rposition(|&b| b == PATH_SEPARATOR || b == ALT_PATH_SEPARATOR).map_or(0, |k| k + 1)
}

/// FileSystem::SplitPathAndFilename: (path, name) at the last '/' or '\\';
/// (whole, "") without one.
pub fn split_path_and_filename(full: &[u8]) -> (&[u8], &[u8]) {
    match full.iter().rposition(|&b| b == b'/' || b == b'\\') {
        Some(k) => (&full[..k], &full[k + 1..]),
        None => (full, &[]),
    }
}

/// Util::IsControlChar.
fn control(c: u8) -> bool {
    c < 32 || c == 127
}

/// FileSystem::ReservedChar.
pub fn reserved_char(c: u8) -> bool {
    control(c) || b"\"*/:<>?\\|".contains(&c)
}

/// FileSystem::MakeValidFilename: reserved characters as '_' (separators kept
/// as the platform's with `allow_slashes`), trailing dots and spaces off,
/// and a leading reserved device name ("CON", "COM1" ...) prefixed with '_'.
/// The text is a C string: it ends at a NUL.
pub fn make_valid_filename(name: &[u8], allow_slashes: bool) -> Vec<u8> {
    let name = &name[..name.iter().position(|&b| b == 0).unwrap_or(name.len())];
    let mut r: Vec<u8> = name
        .iter()
        .map(|&c| {
            if !reserved_char(c) {
                c
            } else if allow_slashes && (c == PATH_SEPARATOR || c == ALT_PATH_SEPARATOR) {
                PATH_SEPARATOR
            } else {
                b'_'
            }
        })
        .collect();
    while matches!(r.last(), Some(b'.' | b' ')) {
        r.pop();
    }
    for reserved in RESERVED_DEVICE_NAMES {
        let len = reserved.len();
        let mut c_r = r.clone();
        c_r.push(0);
        let mut c_res = reserved.as_bytes().to_vec();
        c_res.push(0);
        let equal = unsafe { strncasecmp(c_r.as_ptr().cast(), c_res.as_ptr().cast(), len) } == 0;
        // result[len]: the NUL at the end counts
        if equal && matches!(c_r.get(len), Some(b'.' | 0)) {
            r.insert(0, b'_');
            break;
        }
    }
    r
}

/// FileSystem::SanitizePathSegment: one path segment made safe ("" when
/// nothing is left of it).
pub fn sanitize_path_segment(name: &[u8]) -> Vec<u8> {
    let mut name = name;
    // bounded length, cut at a UTF-8 character boundary
    if name.len() > 1024 {
        let mut cut = 1024;
        while cut > 0 && (name[cut] & 0xc0) == 0x80 {
            cut -= 1;
        }
        name = &name[..cut];
    }
    while matches!(name.first(), Some(b' ' | b'\t')) {
        name = &name[1..];
    }
    while matches!(name.last(), Some(b' ' | b'\t' | b'.')) {
        name = &name[..name.len() - 1];
    }
    if name.is_empty() {
        return Vec::new();
    }
    let result = make_valid_filename(name, false);
    // runs of two or more dots become '_'
    let mut collapsed = Vec::with_capacity(result.len());
    let mut dots = 0;
    for &c in &result {
        if c == b'.' {
            dots += 1;
            continue;
        }
        match dots {
            0 => {}
            1 => collapsed.push(b'.'),
            _ => collapsed.push(b'_'),
        }
        dots = 0;
        collapsed.push(c);
    }
    match dots {
        0 => {}
        1 => collapsed.push(b'.'),
        _ => collapsed.push(b'_'),
    }
    while matches!(collapsed.last(), Some(b'.' | b' ')) {
        collapsed.pop();
    }
    if collapsed.is_empty() || collapsed == b"." || collapsed == b".." {
        return Vec::new();
    }
    collapsed
}

/// FileSystem::SanitizeRelativePath: each segment sanitized, empty ones
/// dropped, joined with the platform's separator.
pub fn sanitize_relative_path(path: &[u8]) -> Vec<u8> {
    let mut clean = Vec::new();
    for seg in path.split(|&b| b == b'/' || b == b'\\').filter(|s| !s.is_empty()) {
        let s = sanitize_path_segment(seg);
        if !s.is_empty() {
            if !clean.is_empty() {
                clean.push(PATH_SEPARATOR);
            }
            clean.extend_from_slice(&s);
        }
    }
    clean
}

/// FileSystem::ExtractFilePathFromCmd: up to the first space after the last
/// separator (the arguments of a command line cut off).
pub fn extract_file_path_from_cmd(path: &[u8]) -> &[u8] {
    if let Some(last) = path.iter().rposition(|&b| b == PATH_SEPARATOR) {
        if let Some(sp) = path[last..].iter().position(|&b| b == b' ') {
            return &path[..last + sp];
        }
    }
    path
}

/// FileSystem::EscapePathForShell: in double quotes ("" stays "").
pub fn escape_path_for_shell(path: &[u8]) -> Vec<u8> {
    if path.is_empty() {
        return Vec::new();
    }
    [&b"\""[..], path, b"\""].concat()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        assert_eq!(make_valid_filename(b"a:b/c*d. . ", false), b"a_b_c_d");
        assert_eq!(make_valid_filename(b"con.txt", false), b"_con.txt");
        assert_eq!(make_valid_filename(b"COM1", false), b"_COM1");
        assert_eq!(make_valid_filename(b"console", false), b"console");
        assert_eq!(sanitize_path_segment(b"  ..evil..name.  "), b"_evil_name");
        assert_eq!(sanitize_relative_path(b"../a//b\\..\\c"), [b'a', PATH_SEPARATOR, b'b', PATH_SEPARATOR, b'c']);
        let cmd = [PATH_SEPARATOR, b'x', b' ', b'-', b'v'];
        assert_eq!(extract_file_path_from_cmd(&cmd), &cmd[..2]);
        assert_eq!(&b"/a/b"[base_file_name(b"/a/b")..], b"b");
    }
}
