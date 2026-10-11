//! FileSystem's file operations (FileSystem.cpp, POSIX): FileExists,
//! DirectoryExists, ForceDirectories, MakeUniqueFilename and ExpandHomePath,
//! and the error text of GetLastErrorMessage.

use std::ffi::{c_char, c_int, CStr, OsStr};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::DirBuilderExt;
use std::path::Path;

extern "C" {
    // These libcs export the GNU ABI as strerror_r and the XSI ABI under
    // __xpg_strerror_r. In particular, Cygwin has an empty target_env.
    // Other POSIX libcs (including musl and the BSDs) use strerror_r for XSI.
    #[cfg_attr(
        any(target_env = "gnu", target_env = "uclibc", target_os = "cygwin"),
        link_name = "__xpg_strerror_r"
    )]
    fn strerror_r(errnum: c_int, buf: *mut c_char, len: usize) -> c_int;
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
}

/// BString<1024>'s capacity
const BSTRING_MAX: usize = 1023;

fn path(p: &[u8]) -> &Path {
    Path::new(OsStr::from_bytes(p))
}

/// The text of an errno value, cut to BString<1024> (GetLastErrorMessage).
pub fn error_message(errnum: i32) -> Vec<u8> {
    let mut buf = [0u8; BSTRING_MAX + 1];
    // The C++ passes msg.Capacity(), 1023 including the terminator, rather
    // than sizeof(msg). Keep that cut, including on ERANGE or unknown errors.
    unsafe { strerror_r(errnum, buf.as_mut_ptr().cast(), BSTRING_MAX) };
    CStr::from_bytes_until_nul(&buf).map(|c| c.to_bytes().to_vec()).unwrap_or_default()
}

/// A native stat callback returns -errno on failure, 1 for a regular file,
/// 2 for a directory, and 0 for another file type. Use the caller's stat ABI:
/// std::fs::metadata may use statx, changing errno and 32-bit overflow behavior.
pub type Stat<'a> = dyn Fn(&[u8]) -> i32 + 'a;

/// FileSystem::FileExists: a regular file (following links).
pub fn file_exists(p: &[u8], stat: &Stat<'_>) -> bool {
    stat(p) == 1
}

/// FileSystem::DirectoryExists: a directory (following links).
pub fn directory_exists(p: &[u8], stat: &Stat<'_>) -> bool {
    stat(p) == 2
}

fn bstring(s: &[u8]) -> Vec<u8> {
    s[..s.len().min(BSTRING_MAX)].to_vec()
}

fn cat(parts: &[&[u8]]) -> Vec<u8> {
    parts.concat()
}

/// FileSystem::ForceDirectories (POSIX): creates `path` and its missing
/// parents; on failure the message is in `errmsg`.
pub fn force_directories(orig: &[u8], errmsg: &mut Vec<u8>, stat: &Stat<'_>) -> bool {
    errmsg.clear();
    let mut norm = bstring(orig);
    crate::paths::normalize_path_separators(&mut norm);
    if norm.last() == Some(&b'/') {
        norm.pop();
    }
    let st = stat(&norm);
    match st {
        e if e < 0 && e != -ENOENT => {
            let e = -e;
            *errmsg = cat(&[b"could not read information for directory ", &norm, b": errno ", e.to_string().as_bytes(), b", ", &error_message(e)]);
            return false;
        }
        kind if kind >= 0 && kind != 2 => {
            *errmsg = cat(&[b"path ", &norm, b" is not a directory"]);
            return false;
        }
        _ => {}
    }
    if st < 0 {
        if let Some(slash) = norm.iter().rposition(|&b| b == b'/') {
            let parent = &norm[..slash];
            if parent.len() != orig.len() && !force_directories(parent, errmsg, stat) {
                return false;
            }
        }
        if let Err(e) = std::fs::DirBuilder::new().mode(0o777).create(path(&norm)) {
            let e = e.raw_os_error().unwrap_or(0);
            if e != EEXIST {
                *errmsg = cat(&[b"could not create directory ", &norm, b": ", &error_message(e)]);
                return false;
            }
        }
        match stat(&norm) {
            e if e < 0 => {
                let e = -e;
                *errmsg = cat(&[b"could not read information for directory ", &norm, b": ", &error_message(e)]);
                return false;
            }
            kind if kind >= 0 && kind != 2 => {
                *errmsg = cat(&[b"path ", &norm, b" is not a directory"]);
                return false;
            }
            _ => {}
        }
    }
    true
}

// ENOENT and EEXIST: the same on Linux, the BSDs and macOS
const ENOENT: i32 = 2;
const EEXIST: i32 = 17;

/// FileSystem::MakeUniqueFilename: `dir/basename`, or the first free
/// `dir/name.duplicateN.ext` (a par2 volume keeps its `.volNN+MM.par2`).
pub fn make_unique_filename(dir: &CStr, basename: &CStr, stat: &Stat<'_>) -> Vec<u8> {
    let base = basename.to_bytes();
    let mut result = cat(&[dir.to_bytes(), b"/", base]);
    let mut n = 0;
    while file_exists(&result, stat) {
        n += 1;
        match base.iter().rposition(|&b| b == b'.').filter(|&e| e > 0) {
            Some(ext_at) => {
                let mut without = bstring(base);
                without.truncate(ext_at.min(BSTRING_MAX));
                let mut ext = &base[ext_at..];
                let ext_c = &basename.to_bytes_with_nul()[ext_at..];
                if unsafe { strcasecmp(ext_c.as_ptr().cast(), c".par2".as_ptr()) } == 0 {
                    if let Some(vol) = without.iter().rposition(|&b| b == b'.').filter(|&v| v > 0) {
                        let mut tail = without[vol..].to_vec();
                        tail.push(0);
                        if unsafe { strncasecmp(tail.as_ptr().cast(), c".vol".as_ptr(), 4) } == 0 {
                            without.truncate(vol);
                            ext = &base[vol..];
                        }
                    }
                }
                result = cat(&[dir.to_bytes(), b"/", &without, b".duplicate", n.to_string().as_bytes(), ext]);
            }
            None => {
                result = cat(&[dir.to_bytes(), b"/", base, b".duplicate", n.to_string().as_bytes()]);
            }
        }
    }
    result
}

/// FileSystem::ExpandHomePath: `~/` replaced by $HOME (or the user's home
/// directory), else the name as it is (empty for none).
pub fn expand_home_path(filename: Option<&CStr>, home: Option<&[u8]>) -> Vec<u8> {
    let Some(f) = filename else { return Vec::new() };
    let b = f.to_bytes();
    if b.starts_with(b"~/") {
        let Some(home) = home else { return b.to_vec() };
        let sep: &[u8] = if home.last() == Some(&b'/') { b"" } else { b"/" };
        return cat(&[home, sep, &b[2..]]);
    }
    b.to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stat(p: &[u8]) -> i32 {
        match std::fs::metadata(path(p)) {
            Ok(m) => if m.is_file() { 1 } else if m.is_dir() { 2 } else { 0 },
            Err(e) => -e.raw_os_error().unwrap(),
        }
    }

    #[test]
    fn messages() {
        assert_eq!(error_message(2), b"No such file or directory");
    }

    #[test]
    fn unique_names() {
        let dir = std::env::temp_dir().join(format!("nzbget-fsops-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let d = std::ffi::CString::new(dir.as_os_str().as_bytes()).unwrap();
        let mut f = dir.as_os_str().as_bytes().to_vec();
        f.extend_from_slice(b"/a.vol01+02.par2");
        std::fs::write(path(&f), b"").unwrap();
        let u = make_unique_filename(&d, c"a.vol01+02.par2", &stat);
        assert!(u.ends_with(b"/a.duplicate1.vol01+02.par2"));
        let mut msg = Vec::new();
        let mut sub = dir.as_os_str().as_bytes().to_vec();
        sub.extend_from_slice(b"/x/y/z");
        assert!(force_directories(&sub, &mut msg, &stat), "{}", String::from_utf8_lossy(&msg));
        assert!(directory_exists(&sub, &stat));
        assert!(!force_directories(&f, &mut msg, &stat));
        assert!(msg.ends_with(b"is not a directory"));
        std::fs::remove_dir_all(&dir).unwrap();
        assert_eq!(expand_home_path(Some(c"~/x"), Some(b"/home/u")), b"/home/u/x");
        assert_eq!(expand_home_path(Some(c"~/x"), Some(b"/")), b"/x");
    }
}
