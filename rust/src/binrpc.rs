//! The binary remote protocol's frame (BinRpc.cpp): the checks
//! BinRpcProcessor makes on a request's base - credentials compared as the
//! C++ strcmp compared them, the request type, its size - the request names
//! for the log, the bool responses and the check of a request's trailing
//! data length. Integers on the wire are big-endian (htonl/ntohl). Reading
//! from and writing to the connection, and what each command does, stay C++.

use std::ffi::CStr;

/// NZBMESSAGE_SIGNATURE ("nzb1").
pub const SIGNATURE: i32 = 0x6E7A_6231;
/// NZBREQUESTPASSWORDSIZE.
const PASSWORD_SIZE: usize = 32;
/// sizeof(SNzbRequestBase): signature, struct size, type, user, password.
pub const BASE_SIZE: usize = 12 + 2 * PASSWORD_SIZE;
const USER_AT: usize = 12;
const PASSWORD_AT: usize = USER_AT + PASSWORD_SIZE;
/// rrHistory, the last request type.
pub const LAST_TYPE: u32 = 14;

/// g_MessageRequestNames.
const NAMES: [&CStr; LAST_TYPE as usize + 1] = [c"N/A", c"Download", c"Pause/Unpause", c"List", c"Set download rate",
    c"Dump debug", c"Edit queue", c"Log", c"Quit", c"Reload", c"Version", c"Post-queue", c"Write log", c"Scan", c"History"];

fn be32(base: &[u8; BASE_SIZE], at: usize) -> u32 {
    u32::from_be_bytes(base[at..at + 4].try_into().unwrap())
}

/// A C string in the base from `at`: strcmp read on past an unterminated
/// field (the user name into the password); the base's end stops it here.
fn c_field(base: &[u8; BASE_SIZE], at: usize) -> &[u8] {
    let rest = &base[at..];
    &rest[..rest.iter().position(|&b| b == 0).unwrap_or(rest.len())]
}

/// BinRpcProcessor::Execute's credential check: true when the request may
/// go on (an empty ControlUsername isn't compared).
pub fn credentials_ok(base: &[u8; BASE_SIZE], control_user: &[u8], control_password: &[u8]) -> bool {
    !((!control_user.is_empty() && c_field(base, USER_AT) != control_user) || c_field(base, PASSWORD_AT) != control_password)
}

/// The request type (ntohl(m_type)).
pub fn request_type(base: &[u8; BASE_SIZE]) -> u32 {
    be32(base, 8)
}

/// The request's name in the debug line ("Unknown" past rrHistory).
pub fn request_name(kind: u32) -> &'static CStr {
    NAMES.get(kind as usize).copied().unwrap_or(c"Unknown")
}

/// Dispatch's size check: Some((expected, received)) when a known request
/// type comes with another struct size than g_MessageRequestSizes gives.
pub fn size_error(base: &[u8; BASE_SIZE], sizes: &[u32]) -> Option<(u32, u32)> {
    let kind = request_type(base);
    let size = be32(base, 4);
    if (1..=LAST_TYPE).contains(&kind) {
        let expected = sizes.get(kind as usize).copied()?;
        if expected != size {
            return Some((expected, size));
        }
    }
    None
}

/// SendBoolResponse's bytes: SNzbDownloadResponse (signature, struct size,
/// success, text length) then the text and its NUL.
pub fn bool_response(success: bool, text: &[u8]) -> Vec<u8> {
    let text = &text[..text.iter().position(|&b| b == 0).unwrap_or(text.len())];
    let mut out = Vec::with_capacity(16 + text.len() + 1);
    out.extend_from_slice(&(SIGNATURE as u32).to_be_bytes());
    out.extend_from_slice(&16u32.to_be_bytes());
    out.extend_from_slice(&(success as u32).to_be_bytes());
    out.extend_from_slice(&((text.len() + 1) as u32).to_be_bytes());
    out.extend_from_slice(text);
    out.push(0);
    out
}

/// ReceiveTrailing's check of the client's data length.
pub fn trailing_ok(len: i64, max: i64) -> bool {
    !(len < 0 || len > max)
}

/// One entry of a list response (List, Log, PostQueue, History): `ints`
/// (host order) written big-endian, each string's length with its NUL put
/// into its field (`strings`: the text and the index of its length field),
/// then the strings with their NULs, and zeros to a 4-byte boundary counted
/// in the length field at `pad_field`, as the C++ aligned the entries (its
/// buffer started aligned, so the offset decides). Fields not given a value
/// are 0.
pub fn append_entry(buf: &mut Vec<u8>, ints: &[u32], strings: &[(&[u8], usize)], pad_field: usize) {
    let start = buf.len();
    let mut fields = ints.to_vec();
    for &(text, field) in strings {
        let text = &text[..text.iter().position(|&b| b == 0).unwrap_or(text.len())];
        if let Some(f) = fields.get_mut(field) {
            *f = (text.len() + 1) as u32;
        }
    }
    buf.resize(start + fields.len() * 4, 0);
    for &(text, _) in strings {
        let text = &text[..text.iter().position(|&b| b == 0).unwrap_or(text.len())];
        buf.extend_from_slice(text);
        buf.push(0);
    }
    let pad = (4 - buf.len() % 4) % 4;
    if pad > 0 {
        buf.resize(buf.len() + pad, 0);
        if let Some(f) = fields.get_mut(pad_field) {
            *f = f.wrapping_add(pad as u32);
        }
    }
    for (k, f) in fields.iter().enumerate() {
        buf[start + 4 * k..start + 4 * k + 4].copy_from_slice(&f.to_be_bytes());
    }
}

/// EditQueue's check of the client's counts and lengths against each other
/// and the trailing data's length (64-bit sums).
pub fn edit_sizes_ok(ids: i32, names: i32, names_len: i32, text_len: i32, data_len: u32) -> bool {
    ids >= 0
        && names >= 0
        && text_len >= 0
        && names_len >= 0
        && ids <= 10_000_000
        && names <= names_len
        && i64::from(ids) * 4 + i64::from(text_len) + i64::from(names_len) == i64::from(data_len)
}

/// EditQueue's trailing data after the size check: the text, then
/// `ids_out.len()` big-endian ids, then `names` NUL-terminated names to the
/// data's end. Checks that the parts fit and that each name ends within the
/// names' part, then writes the ids to `ids_out` in host order; false (with
/// `ids_out` untouched) when they don't. Nothing is allocated, whatever the
/// counts.
pub fn edit_split(data: &[u8], text_len: usize, ids_out: &mut [u32], names: usize) -> bool {
    let Some(ids_end) = ids_out.len().checked_mul(4).and_then(|n| n.checked_add(text_len)) else { return false };
    let Some(id_bytes) = data.get(text_len..ids_end) else { return false };
    let mut at = ids_end;
    for _ in 0..names {
        let Some(len) = data.get(at..).and_then(|rest| crate::bytes::find_byte(rest, 0)) else { return false };
        at += len + 1;
    }
    for (out, id) in ids_out.iter_mut().zip(id_bytes.as_chunks::<4>().0) {
        *out = u32::from_be_bytes(*id);
    }
    true
}

/// Download's test of the request's content for a URL to fetch rather than
/// an NZB: "http:/" or "https:/" in any case, as strncasecmp compared them.
pub fn is_url(content: &[u8]) -> bool {
    let starts = |prefix: &[u8]| content.get(..prefix.len()).is_some_and(|head| head.eq_ignore_ascii_case(prefix));
    starts(b"http:/") || starts(b"https:/")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base(kind: u32, size: u32, user: &[u8], password: &[u8]) -> [u8; BASE_SIZE] {
        let mut b = [0u8; BASE_SIZE];
        b[..4].copy_from_slice(&(SIGNATURE as u32).to_be_bytes());
        b[4..8].copy_from_slice(&size.to_be_bytes());
        b[8..12].copy_from_slice(&kind.to_be_bytes());
        b[USER_AT..USER_AT + user.len()].copy_from_slice(user);
        b[PASSWORD_AT..PASSWORD_AT + password.len()].copy_from_slice(password);
        b
    }

    #[test]
    fn credentials() {
        assert!(credentials_ok(&base(1, 0, b"nzbget", b"tegbzn6789"), b"nzbget", b"tegbzn6789"));
        assert!(credentials_ok(&base(1, 0, b"anyone", b"tegbzn6789"), b"", b"tegbzn6789"));
        assert!(!credentials_ok(&base(1, 0, b"nzbget", b"wrong"), b"nzbget", b"tegbzn6789"));
        assert!(!credentials_ok(&base(1, 0, b"other", b"tegbzn6789"), b"nzbget", b"tegbzn6789"));
        // an unterminated user name runs on into the password, as strcmp read it
        let full = [b'u'; PASSWORD_SIZE];
        let b = base(1, 0, &full, b"pw");
        assert!(!credentials_ok(&b, &full, b"pw"));
        assert!(credentials_ok(&b, &[&full[..], b"pw"].concat(), b"pw"));
        // No read beyond the base when neither field is terminated. The old
        // strcmp could read out of bounds here; the bounded port stops here.
        let b = base(1, 0, &full, &full);
        assert!(credentials_ok(&b, &[b'u'; 64], &full));
        assert!(!credentials_ok(&b, b"", &[b'u'; 33]));
        assert!(!credentials_ok(&b, b"", &[b'u'; 31]));
    }

    #[test]
    fn sizes_and_names() {
        let sizes: Vec<u32> = (0..=LAST_TYPE).map(|t| 100 + t).collect();
        assert_eq!(size_error(&base(3, 103, b"", b""), &sizes), None);
        assert_eq!(size_error(&base(3, 99, b"", b""), &sizes), Some((103, 99)));
        assert_eq!(size_error(&base(0, 99, b"", b""), &sizes), None);
        assert_eq!(size_error(&base(15, 99, b"", b""), &sizes), None);
        assert_eq!(request_name(14), c"History");
        assert_eq!(request_name(15), c"Unknown");
        assert_eq!(request_name(u32::MAX), c"Unknown");
        for kind in [0x7fff_ffff, 0x8000_0000, u32::MAX] {
            assert_eq!(size_error(&base(kind, 99, b"", b""), &sizes), None);
            assert_eq!(request_name(kind), c"Unknown");
        }
        assert_eq!(size_error(&base(14, u32::MAX, b"", b""), &sizes), Some((114, u32::MAX)));
    }

    #[test]
    fn entries() {
        let mut buf = Vec::new();
        append_entry(&mut buf, &[7, 0, 9], &[(b"ab", 1)], 1);
        assert_eq!(buf, [0, 0, 0, 7, 0, 0, 0, 4, 0, 0, 0, 9, b'a', b'b', 0, 0]);
        // 33 bytes: 3 bytes of padding, counted in the empty string's length
        append_entry(&mut buf, &[1, 0, 0], &[(b"xyz", 1), (b"", 2)], 2);
        assert_eq!(&buf[16..], [0, 0, 0, 1, 0, 0, 0, 4, 0, 0, 0, 4, b'x', b'y', b'z', 0, 0, 0, 0, 0]);
        assert_eq!(buf.len() % 4, 0);
        // a string ends at its NUL; the offset (not the entry) decides the padding
        let mut buf = vec![0u8; 2];
        append_entry(&mut buf, &[0], &[(b"a\0hidden", 0)], 0);
        assert_eq!(buf, [0, 0, 0, 0, 0, 2, b'a', 0]);
    }

    #[test]
    fn edits() {
        assert!(edit_sizes_ok(2, 1, 3, 4, 15));
        assert!(!edit_sizes_ok(2, 1, 3, 4, 16));
        assert!(!edit_sizes_ok(-1, 0, 0, 4, 0));
        assert!(!edit_sizes_ok(0, 2, 1, 0, 1));
        assert!(!edit_sizes_ok(10_000_001, 0, 0, 0, 40_000_004));
        assert!(!edit_sizes_ok(i32::MAX, 0, 0, i32::MAX, u32::MAX));
        assert!(edit_sizes_ok(0, 0, 0, 0, 0));
        let data = b"tx\0\0\0\0\0\x07\xff\xff\xff\xfeab\0\0c\0";
        let mut ids = [0u32; 2];
        assert!(edit_split(data, 4, &mut ids, 3));
        assert_eq!(ids, [7, 0xffff_fffe]);
        // a name running to the end, or past it: the ids stay untouched
        let mut ids = [1u32; 2];
        assert!(!edit_split(&data[..17], 4, &mut ids, 3));
        assert!(!edit_split(data, 4, &mut ids, 4));
        assert!(!edit_split(&data[..8], 4, &mut ids, 0));
        assert_eq!(ids, [1, 1]);
        assert!(edit_split(b"", 0, &mut [], 0));
        assert!(!edit_split(b"", 1, &mut [], 0));
    }

    #[test]
    fn urls() {
        for yes in [&b"http://x"[..], b"HTTPS://x", b"http:/", b"hTtPs:/", b"http:/\0"] {
            assert!(is_url(yes), "{yes:?}");
        }
        for no in [&b""[..], b"http:", b"https:", b"ftp://x", b"<?xml", b"http\0:/", b"https:\\"] {
            assert!(!is_url(no), "{no:?}");
        }
    }

    #[test]
    fn responses() {
        let r = bool_response(true, b"ok");
        assert_eq!(r, [0x6e, 0x7a, 0x62, 0x31, 0, 0, 0, 16, 0, 0, 0, 1, 0, 0, 0, 3, b'o', b'k', 0]);
        assert!(trailing_ok(0, 10) && trailing_ok(10, 10) && !trailing_ok(-1, 10) && !trailing_ok(11, 10));
        assert!(trailing_ok(0, 0));
        assert!(!trailing_ok(0, -1));
        assert!(!trailing_ok(i64::MIN, i64::MAX));
        assert!(trailing_ok(i64::MAX, i64::MAX));
        assert!(!trailing_ok(i64::MAX, i64::MAX - 1));
    }
}
