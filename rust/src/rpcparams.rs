//! XmlCommand's request parameter parsing (XmlRpc.cpp): PrepareParams and
//! NextParamAsInt/Bool/Str over the request buffer, as the C++ did it:
//! GET query strings, JSON-RPC and XML-RPC, parsing in place (NULs written
//! into the request, URL decoding) and moving the read position.
//!
//! `buf` is the request from the read position through its NUL (the last
//! byte). Positions are offsets into it.
//! Unterminated slices are rejected without mutation, including empty slices.

use std::ffi::{c_char, c_int};

use crate::decode::json_next_value;
use crate::webutil::xml_find_tag;

extern "C" {
    fn strtoll(s: *const c_char, end: *mut *mut c_char, base: c_int) -> i64;
}

/// How the request is encoded.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Kind {
    /// GET query string (`a=1&b=2`; JSON or XML-RPC alike)
    Get,
    /// JSON-RPC (or JSONP-RPC) POST
    Json,
    /// XML-RPC POST
    Xml,
}

/// The text up to the first NUL.
fn text(buf: &[u8]) -> &[u8] {
    &buf[..buf.iter().position(|&b| b == 0).unwrap_or(buf.len())]
}

// Validate the safe Rust API before any indexing or call to C's strtoll.
fn terminated(buf: &mut [u8]) -> Option<&mut [u8]> {
    let end = buf.iter().position(|&b| b == 0)?;
    Some(&mut buf[..=end])
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// strchr(set, c): NUL is in every set.
fn in_set(set: &[u8], c: u8) -> bool {
    c == 0 || set.contains(&c)
}

/// ParseIntParam: strtoll in base 10, an int or nothing. (Its ERANGE check
/// is implied: strtoll returns LLONG_MIN/MAX then, which aren't ints.)
fn parse_int(buf: &[u8], at: usize) -> Option<i32> {
    debug_assert!(buf[at..].contains(&0));
    let start = buf[at..].as_ptr().cast::<c_char>();
    let mut end: *mut c_char = std::ptr::null_mut();
    // buf holds a NUL after `at`: strtoll reads within it
    let number = unsafe { strtoll(start, &mut end, 10) };
    if end.cast_const() == start {
        return None;
    }
    i32::try_from(number).ok()
}

/// JsonStep: 1 to skip the separator after a value, 0 at `]` or the end.
fn json_step(buf: &[u8], at: usize) -> usize {
    match buf[at] {
        b']' | 0 => 0,
        _ => 1,
    }
}

/// XmlNextValue: the content of `<tag>` inside the next `<value>`.
fn xml_next_value(buf: &[u8], tag: &[u8]) -> Option<(usize, usize)> {
    let t = text(buf);
    let (value, value_len) = xml_find_tag(t, b"value")?;
    let (content, len) = xml_find_tag(&t[value..], tag)?;
    let content = value + content;
    if content as i64 <= value as i64 + value_len {
        // the fixed tags here can't give a negative length
        Some((content, usize::try_from(len).ok()?))
    } else {
        None
    }
}

/// PrepareParams' POST part for JSON: the read position after `"params"`,
/// or 0 with the request emptied.
pub fn skip_to_params(buf: &mut [u8]) -> usize {
    let Some(buf) = terminated(buf) else { return 0 };
    match find(text(buf), b"\"params\"") {
        Some(at) => at + 8,
        None => {
            buf[0] = 0;
            0
        }
    }
}

/// NextParamAsInt: (new read position, value); the position is unchanged
/// without a value.
pub fn next_int(buf: &mut [u8], kind: Kind) -> (usize, Option<i32>) {
    let Some(buf) = terminated(buf) else { return (0, None) };
    let r = match kind {
        Kind::Get => (|| {
            let param = find(text(buf), b"=")? + 1;
            let value = parse_int(buf, param)?;
            let mut pos = param;
            while buf[pos] != 0 && in_set(b"-+0123456789&", buf[pos]) {
                pos += 1;
            }
            Some((pos, value))
        })(),
        Kind::Json => (|| {
            let (param, len) = json_next_value(text(buf))?;
            if !in_set(b"-+0123456789", buf[param]) {
                return None;
            }
            let value = parse_int(buf, param)?;
            Some((param + len + json_step(buf, param + len), value))
        })(),
        Kind::Xml => (|| {
            let (param, len, tag_len) = match xml_next_value(buf, b"i4") {
                Some((p, l)) => (p, l, 4),
                None => {
                    let (p, l) = xml_next_value(buf, b"int")?;
                    (p, l, 5)
                }
            };
            if !in_set(b"-+0123456789", buf[param]) {
                return None;
            }
            let value = parse_int(buf, param)?;
            Some((param + len + tag_len, value))
        })(),
    };
    match r {
        Some((pos, value)) => (pos, Some(value)),
        None => (0, None),
    }
}

/// NextParamAsStr: (new read position, offset of the NUL-terminated value).
/// The position is unchanged without a value.
pub fn next_str(buf: &mut [u8], kind: Kind) -> (usize, Option<usize>) {
    let Some(buf) = terminated(buf) else { return (0, None) };
    let r = match kind {
        Kind::Get => (|| {
            let param = find(text(buf), b"=")? + 1;
            let pos = match buf[param..].iter().position(|&b| b == b'&' || b == 0) {
                Some(len) if buf[param + len] == b'&' => {
                    buf[param + len] = 0;
                    param + len + 1
                }
                // strlen(param) - 1, then + 1
                Some(len) => param + len,
                None => unreachable!("buf ends with a NUL"),
            };
            let len = text(&buf[param..]).len();
            let n = crate::text::url_decode(&mut buf[param..param + len]);
            buf[param + n] = 0;
            Some((pos, param))
        })(),
        Kind::Json => (|| {
            let (param, len) = json_next_value(text(buf))?;
            if len < 2 || buf[param] != b'"' || buf[param + len - 1] != b'"' {
                return None;
            }
            let pos = param + len + json_step(buf, param + len);
            buf[param + len - 1] = 0;
            Some((pos, param + 1))
        })(),
        Kind::Xml => (|| {
            let (param, len) = xml_next_value(buf, b"string")?;
            buf[param + len] = 0;
            Some((param + len + 8, param))
        })(),
    };
    match r {
        Some((pos, value)) => (pos, Some(value)),
        None => (0, None),
    }
}

/// NextParamAsBool: (new read position, value). A GET parameter moves the
/// position even when it isn't a JSON boolean, as the C++ did.
pub fn next_bool(buf: &mut [u8], kind: Kind, json: bool) -> (usize, Option<bool>) {
    let Some(buf) = terminated(buf) else { return (0, None) };
    match kind {
        Kind::Get => {
            let (pos, param) = next_str(buf, kind);
            let Some(param) = param else { return (0, None) };
            let value = text(&buf[param..]);
            let r = if !json {
                Some(value.first() == Some(&b'1'))
            } else if value.starts_with(b"true") {
                Some(true)
            } else if value.starts_with(b"false") {
                Some(false)
            } else {
                None
            };
            (pos, r)
        }
        Kind::Json => {
            let Some((param, len)) = json_next_value(text(buf)) else { return (0, None) };
            let value = match &buf[param..param + len] {
                b"true" => true,
                b"false" => false,
                _ => return (0, None),
            };
            (param + len + json_step(buf, param + len), Some(value))
        }
        Kind::Xml => {
            let Some((param, len)) = xml_next_value(buf, b"boolean") else { return (0, None) };
            (param + len + 9, Some(buf[param] == b'1'))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn buf(s: &str) -> Vec<u8> {
        let mut v = s.as_bytes().to_vec();
        v.push(0);
        v
    }

    #[test]
    fn unterminated_safe_api() {
        for input in [b"".as_slice(), b"a=123", b"\"params\"", b"\"s\""] {
            let mut b = input.to_vec();
            assert_eq!(skip_to_params(&mut b), 0);
            for kind in [Kind::Get, Kind::Json, Kind::Xml] {
                assert_eq!(next_int(&mut b, kind), (0, None));
                assert_eq!(next_bool(&mut b, kind, true), (0, None));
                assert_eq!(next_str(&mut b, kind), (0, None));
            }
            assert_eq!(b, input);
        }
    }

    #[test]
    fn get() {
        let mut b = buf("?a=12&b=x%20y&c=true");
        let (pos, v) = next_int(&mut b, Kind::Get);
        assert_eq!(v, Some(12));
        assert_eq!(&b[pos..pos + 2], b"b=");
        let rest = &mut b[pos..];
        let (p2, s) = next_str(rest, Kind::Get);
        assert_eq!(text(&rest[s.unwrap()..]), b"x y");
        let (_, t) = next_bool(&mut rest[p2..], Kind::Get, true);
        assert_eq!(t, Some(true));
    }

    #[test]
    fn json() {
        let mut b = buf("{\"method\":\"x\",\"params\":[5, \"s\", false]}");
        let p = skip_to_params(&mut b);
        let (p1, i) = next_int(&mut b[p..], Kind::Json);
        assert_eq!(i, Some(5));
        let p = p + p1;
        let (p2, s) = next_str(&mut b[p..], Kind::Json);
        assert_eq!(text(&b[p + s.unwrap()..]), b"s");
        let p = p + p2;
        assert_eq!(next_bool(&mut b[p..], Kind::Json, true).1, Some(false));
        let mut none = buf("{}");
        assert_eq!(skip_to_params(&mut none), 0);
        assert_eq!(none[0], 0);
    }

    #[test]
    fn xml() {
        let mut b = buf("<params><param><value><i4>-7</i4></value></param><param><value><string>a&amp;b</string></value></param></params>");
        let (p1, i) = next_int(&mut b, Kind::Xml);
        assert_eq!(i, Some(-7));
        let (_, s) = next_str(&mut b[p1..], Kind::Xml);
        assert_eq!(text(&b[p1 + s.unwrap()..]), b"a&amp;b");
        assert_eq!(next_int(&mut buf("<value><i4>2147483648</i4></value>"), Kind::Xml).1, None);
    }
}
