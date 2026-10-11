//! XmlCommand's request parameter parsing (XmlRpc.cpp): PrepareParams and
//! NextParamAsInt/Bool/Str over the request buffer, as the C++ did it:
//! GET query strings, JSON-RPC and XML-RPC, parsing in place (NULs written
//! into the request, URL decoding) and moving the read position.
//!
//! `buf` is the request from the read position through its NUL (the last
//! byte). Positions are offsets into it.
//! Unterminated slices are rejected without mutation, including empty slices.

use std::ffi::{c_char, c_int, CStr};

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

use crate::bytes::{find, find_byte};

/// The text up to the first NUL.
fn text(buf: &[u8]) -> &[u8] {
    &buf[..find_byte(buf, 0).unwrap_or(buf.len())]
}

// Validate the safe Rust API before any indexing or call to C's strtoll.
fn terminated(buf: &mut [u8]) -> Option<&mut [u8]> {
    let end = find_byte(buf, 0)?;
    Some(&mut buf[..=end])
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
/// `buf` ends with its first NUL.
fn xml_next_value(buf: &[u8], tag: &[u8]) -> Option<(usize, usize)> {
    let t = &buf[..buf.len() - 1];
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
    next_int_terminated(buf, kind)
}

/// next_int on a buffer that ends with its first NUL.
fn next_int_terminated(buf: &mut [u8], kind: Kind) -> (usize, Option<i32>) {
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
    next_str_terminated(buf, kind)
}

/// next_str on a buffer that ends with its first NUL.
fn next_str_terminated(buf: &mut [u8], kind: Kind) -> (usize, Option<usize>) {
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
    next_bool_terminated(buf, kind, json)
}

/// next_bool on a buffer that ends with its first NUL.
fn next_bool_terminated(buf: &mut [u8], kind: Kind, json: bool) -> (usize, Option<bool>) {
    match kind {
        Kind::Get => {
            let (pos, param) = next_str_terminated(buf, kind);
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

/// The request read in place from a NUL-terminated pointer, for JSON and GET
/// parameters: every scan stops at the first NUL and goes only as far as the
/// value being read, as the C++ did - the rest of the request (an NZB of
/// several hundred KB in `append`) isn't measured on each parameter.
#[derive(Clone, Copy)]
pub struct Raw(*mut u8);

impl Raw {
    /// # Safety
    /// `p` is writable and NUL-terminated; it outlives the value.
    pub unsafe fn new(p: *mut u8) -> Raw {
        Raw(p)
    }

    /// # Safety
    /// `i` is at most the index of the first NUL.
    unsafe fn at(self, i: usize) -> u8 {
        *self.0.add(i)
    }

    /// # Safety
    /// As `at`, and `i` is before the first NUL.
    unsafe fn set(self, i: usize, v: u8) {
        *self.0.add(i) = v;
    }

    /// The index of the first byte from `i` that `stop` accepts, or of the NUL.
    unsafe fn scan(self, mut i: usize, stop: impl Fn(u8) -> bool) -> usize {
        while self.at(i) != 0 && !stop(self.at(i)) {
            i += 1;
        }
        i
    }

    /// decode::json_next_value on the text up to the first NUL.
    unsafe fn json_next_value(self) -> Option<(usize, usize)> {
        let start = self.scan(0, |b| !b" ,[{:\r\n\t\x0c".contains(&b));
        if self.at(start) == 0 {
            return None;
        }
        if self.at(start) != b'"' {
            let end = self.scan(start, |b| b" ,]}\r\n\t\x0c".contains(&b));
            return Some((start, end - start));
        }
        let mut e = start + 1;
        loop {
            e = self.scan(e, |b| b == b'"' || b == b'\\');
            match self.at(e) {
                0 => return Some((start, e - start)),
                b'"' => return Some((start, e + 1 - start)),
                _ => {}
            }
            // a byte must follow both the backslash and the byte after it
            if self.at(e + 1) == 0 || self.at(e + 2) == 0 {
                return None;
            }
            e += 2;
        }
    }

    unsafe fn json_step(self, at: usize) -> usize {
        match self.at(at) {
            b']' | 0 => 0,
            _ => 1,
        }
    }

    /// The offset just after the first '=', if any.
    unsafe fn get_param(self) -> Option<usize> {
        let eq = self.scan(0, |b| b == b'=');
        (self.at(eq) != 0).then_some(eq + 1)
    }

    unsafe fn parse_int(self, at: usize) -> Option<i32> {
        let start = self.0.add(at).cast::<c_char>();
        let mut end: *mut c_char = std::ptr::null_mut();
        let number = strtoll(start, &mut end, 10);
        if end.cast_const() == start.cast_const() {
            return None;
        }
        i32::try_from(number).ok()
    }

    /// The whole request up to its NUL, for XML-RPC.
    unsafe fn terminated(self) -> &'static mut [u8] {
        let len = CStr::from_ptr(self.0.cast()).to_bytes().len();
        std::slice::from_raw_parts_mut(self.0, len + 1)
    }

    /// next_int.
    ///
    /// # Safety
    /// As `new`; the request isn't otherwise accessed during the call.
    pub unsafe fn next_int(self, kind: Kind) -> (usize, Option<i32>) {
        let r = match kind {
            Kind::Get => (|| {
                let param = self.get_param()?;
                let value = self.parse_int(param)?;
                let pos = self.scan(param, |b| !in_set(b"-+0123456789&", b));
                Some((pos, value))
            })(),
            Kind::Json => (|| {
                let (param, len) = self.json_next_value()?;
                if !in_set(b"-+0123456789", self.at(param)) {
                    return None;
                }
                let value = self.parse_int(param)?;
                Some((param + len + self.json_step(param + len), value))
            })(),
            Kind::Xml => return next_int_terminated(self.terminated(), kind),
        };
        r.map_or((0, None), |(pos, value)| (pos, Some(value)))
    }

    /// next_str.
    ///
    /// # Safety
    /// As `next_int`.
    pub unsafe fn next_str(self, kind: Kind) -> (usize, Option<usize>) {
        let r = match kind {
            Kind::Get => (|| {
                let param = self.get_param()?;
                let end = self.scan(param, |b| b == b'&');
                let pos = if self.at(end) == b'&' {
                    self.set(end, 0);
                    end + 1
                } else {
                    end
                };
                let value = std::slice::from_raw_parts_mut(self.0.add(param), end - param);
                let n = crate::text::url_decode(value);
                self.set(param + n, 0);
                Some((pos, param))
            })(),
            Kind::Json => (|| {
                let (param, len) = self.json_next_value()?;
                if len < 2 || self.at(param) != b'"' || self.at(param + len - 1) != b'"' {
                    return None;
                }
                let pos = param + len + self.json_step(param + len);
                self.set(param + len - 1, 0);
                Some((pos, param + 1))
            })(),
            Kind::Xml => return next_str_terminated(self.terminated(), kind),
        };
        r.map_or((0, None), |(pos, value)| (pos, Some(value)))
    }

    /// next_bool.
    ///
    /// # Safety
    /// As `next_int`.
    pub unsafe fn next_bool(self, kind: Kind, json: bool) -> (usize, Option<bool>) {
        match kind {
            Kind::Get => {
                let (pos, param) = self.next_str(kind);
                let Some(param) = param else { return (0, None) };
                let value = CStr::from_ptr(self.0.add(param).cast()).to_bytes();
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
                let Some((param, len)) = self.json_next_value() else { return (0, None) };
                let value = match std::slice::from_raw_parts(self.0.add(param), len) {
                    b"true" => true,
                    b"false" => false,
                    _ => return (0, None),
                };
                (param + len + self.json_step(param + len), Some(value))
            }
            Kind::Xml => next_bool_terminated(self.terminated(), kind, json),
        }
    }
}

/// TestServerXmlCommand::ServerParams.
#[derive(Debug, PartialEq)]
pub struct ServerParams {
    pub host: Vec<u8>,
    pub port: i32,
    pub username: Vec<u8>,
    pub password: Vec<u8>,
    pub encryption: bool,
    pub cipher: Vec<u8>,
    pub timeout: i32,
    pub cert_verif_level: i32,
}

#[derive(Debug, PartialEq)]
pub enum ServerParamsError {
    /// "Invalid JSON"
    Json,
    /// "Invalid parameters"
    Params,
}

/// TestServerXmlCommand's JSON body: Json::Deserialize, then
/// ParseRequestParams - an object whose "params" array has at least 8
/// entries: host, port, username, password, encryption, cipher, timeout and
/// certVerifLevel, as value_to<std::string/int/bool> takes them (strings
/// whole, NULs included).
pub fn test_server_params(request: &[u8], limits: crate::json::Limits) -> Result<ServerParams, ServerParamsError> {
    use crate::json::Value;
    let json = crate::json::parse(request, limits).ok_or(ServerParamsError::Json)?;
    let Some(Value::Array(params)) = json.get(b"params") else { return Err(ServerParamsError::Params) };
    if params.len() < 8 {
        return Err(ServerParamsError::Params);
    }
    let string = |v: &Value| match v {
        Value::String(s) => Some(s.clone()),
        _ => None,
    };
    let parsed = (|| Some(ServerParams {
        host: string(&params[0])?,
        port: params[1].to_i32()?,
        username: string(&params[2])?,
        password: string(&params[3])?,
        encryption: match params[4] { Value::Bool(b) => b, _ => return None },
        cipher: string(&params[5])?,
        timeout: params[6].to_i32()?,
        cert_verif_level: params[7].to_i32()?,
    }))();
    parsed.ok_or(ServerParamsError::Params)
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
    #[test]
    fn raw_matches_slices() {
        let mut state = 0x9e3779b97f4a7c15u64;
        let mut next = move || { state ^= state << 13; state ^= state >> 7; state ^= state << 17; state };
        const PIECES: &[&[u8]] = &[b"\"", b"\\", b"\\\"", b"a", b"12", b"-3", b"+", b"true", b"false", b",", b"]", b"}", b"[",
            b" ", b"\t", b"=", b"&", b"%41", b"%", b"x=1", b"\0", b":", b"\"params\"", b"1", b"0"];
        for _ in 0..200_000 {
            let mut buf = Vec::new();
            for _ in 0..next() % 12 {
                buf.extend_from_slice(PIECES[(next() % PIECES.len() as u64) as usize]);
            }
            buf.push(0);
            let kind = [Kind::Get, Kind::Json][(next() % 2) as usize];
            let what = next() % 3;
            let json = next() % 2 == 0;
            let (mut a, mut b) = (buf.clone(), buf.clone());
            let ra = match what {
                0 => { let (p, v) = next_int(&mut a, kind); (p, v.map(|v| v as i64)) }
                1 => { let (p, v) = next_bool(&mut a, kind, json); (p, v.map(|v| v as i64)) }
                _ => { let (p, v) = next_str(&mut a, kind); (p, v.map(|v| v as i64)) }
            };
            let rb = unsafe {
                let raw = Raw::new(b.as_mut_ptr());
                match what {
                    0 => { let (p, v) = raw.next_int(kind); (p, v.map(|v| v as i64)) }
                    1 => { let (p, v) = raw.next_bool(kind, json); (p, v.map(|v| v as i64)) }
                    _ => { let (p, v) = raw.next_str(kind); (p, v.map(|v| v as i64)) }
                }
            };
            assert_eq!(ra, rb, "{:?} {what} {:?}", kind, String::from_utf8_lossy(&buf));
            assert_eq!(a, b, "{:?} {what} {:?}", kind, String::from_utf8_lossy(&buf));
        }
    }
}
