//! WebDownloader's HTTP decisions (WebDownloader.cpp): the status line
//! (CheckResponse), the response headers it acts on (ProcessHeader) and the
//! URL a redirect leads to (ParseRedirect), as the C++ did them. Logging,
//! the connection and the file stay C++.

use std::ffi::{c_char, c_int, CStr};

use crate::url::{parse_url, Part};

extern "C" {
    fn atoi(s: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
}

/// What CheckResponse decided.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Response {
    /// 0 running, 1 running a redirect, 2 connect error, 3 not found, 4 failed
    pub result: i32,
    /// whether the status line set the HTTP status
    pub set_status: bool,
    pub http_status: i32,
    /// 0 none, 1 "connection closed" (unless stopped), 2 failed with the
    /// whole line, 3 failed with the text from `status_offset`
    pub warn: i32,
    pub status_offset: usize,
}

/// CheckResponse for the first line (None: the connection closed).
pub fn check_response(response: Option<&CStr>) -> Response {
    let Some(response) = response else {
        return Response { result: 2, warn: 1, ..Default::default() };
    };
    let line = response.to_bytes();
    let space = line.iter().position(|&b| b == b' ');
    let Some(space) = space.filter(|_| line.starts_with(b"HTTP")) else {
        return Response { result: 4, warn: 2, ..Default::default() };
    };
    let at = space + 1;
    let status = &line[at..];
    let http_status = unsafe { atoi(response.as_ptr().add(at)) };
    let is = |code: &[u8]| status.starts_with(code);
    let (result, warn) = if is(b"400") || is(b"499") {
        (2, 3)
    } else if is(b"404") {
        (3, 3)
    } else if [&b"301"[..], b"302", b"303", b"307", b"308"].iter().any(|c| is(c)) {
        (1, 0)
    } else if is(b"200") {
        (0, 0)
    } else {
        (4, 2)
    };
    Response { result, set_status: true, http_status, warn, status_offset: at }
}

/// ProcessHeader: 0 nothing, 1 Content-Length (its atoi in the second
/// value), 2 gzip, 3 Content-Disposition, 4 Location while redirecting (the
/// address from the offset in the second value).
pub fn process_header(line: &CStr, redirecting: bool) -> (i32, i32) {
    let starts = |prefix: &CStr, n: usize| unsafe { strncasecmp(line.as_ptr(), prefix.as_ptr(), n) == 0 };
    if starts(c"Content-Length: ", 16) {
        // the line is at least 16 bytes: its prefix matched
        (1, unsafe { atoi(line.as_ptr().add(16)) })
    } else if starts(c"Content-Encoding: gzip", 22) {
        (2, 0)
    } else if starts(c"Content-Disposition: ", 21) {
        (3, 0)
    } else if redirecting && starts(c"Location: ", 10) {
        (4, 10)
    } else {
        (0, 0)
    }
}

/// A URL part as the C++ URL class holds it (None: a null CString).
fn part(addr: &[u8], valid: bool, p: Part, default: Option<&[u8]>) -> Option<Vec<u8>> {
    if !valid {
        return None;
    }
    match p {
        Some((start, len)) => Some(addr[start..start + len].to_vec()),
        None => default.map(<[u8]>::to_vec),
    }
}

/// printf's "%s": glibc prints a null pointer as "(null)".
fn s(v: &Option<Vec<u8>>) -> &[u8] {
    v.as_deref().unwrap_or(b"(null)")
}

/// ParseRedirect: the address `location` (a Location header) leads to from `old_url`.
pub fn redirect(old_url: &CStr, location: &CStr) -> Vec<u8> {
    let loc = location.to_bytes();
    if parse_url(location).valid {
        return loc.to_vec();
    }
    let old = old_url.to_bytes();
    let u = parse_url(old_url);
    let protocol = part(old, u.valid, u.protocol, None);
    let mut out = Vec::new();
    if loc.starts_with(b"//") {
        // protocol-relative: another host, same protocol
        out.extend_from_slice(s(&protocol));
        out.push(b':');
        out.extend_from_slice(loc);
        return out;
    }
    // within the host
    let resource = if loc.first() == Some(&b'/') {
        loc.to_vec()
    } else {
        // the old resource up to its query and last '/' (a null one as empty)
        let mut r = part(old, u.valid, u.resource, Some(b"/")).unwrap_or_default();
        if let Some(q) = r.iter().position(|&b| b == b'?') {
            r.truncate(q);
        }
        if let Some(slash) = r.iter().rposition(|&b| b == b'/') {
            r.truncate(slash + 1);
        }
        r.extend_from_slice(loc);
        r
    };
    let host = part(old, u.valid, u.host, None);
    out.extend_from_slice(s(&protocol));
    out.extend_from_slice(b"://");
    out.extend_from_slice(s(&host));
    if u.port > 0 {
        out.push(b':');
        out.extend_from_slice(u.port.to_string().as_bytes());
    }
    out.extend_from_slice(&resource);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn responses() {
        let r = check_response(Some(c"HTTP/1.1 200 OK"));
        assert_eq!((r.result, r.http_status, r.warn), (0, 200, 0));
        assert_eq!(check_response(Some(c"HTTP/1.1 302 Found")).result, 1);
        assert_eq!(check_response(Some(c"HTTP/1.1 404 Not Found")).result, 3);
        assert_eq!(check_response(Some(c"HTTP/1.1 500 Oops")).result, 4);
        assert_eq!(check_response(Some(c"garbage")).warn, 2);
        assert_eq!(check_response(None).result, 2);
    }

    #[test]
    fn headers() {
        assert_eq!(process_header(c"content-length: 1234", false), (1, 1234));
        assert_eq!(process_header(c"Content-Encoding: gzip", false), (2, 0));
        assert_eq!(process_header(c"Location: /x", false), (0, 0));
        assert_eq!(process_header(c"Location: /x", true), (4, 10));
    }

    #[test]
    fn redirects() {
        let old = c"https://example.com:8443/a/b/get?apikey=1";
        assert_eq!(redirect(old, c"https://other.org/z"), b"https://other.org/z");
        assert_eq!(redirect(old, c"//cdn.org/f"), b"https://cdn.org/f");
        assert_eq!(redirect(old, c"/root?x"), b"https://example.com:8443/root?x");
        assert_eq!(redirect(old, c"next?y"), b"https://example.com:8443/a/b/next?y");
        assert_eq!(redirect(c"http://h", c"rel"), b"http://h/rel");
        assert_eq!(redirect(c"bad", c"rel"), b"(null)://(null)rel");
    }
}
