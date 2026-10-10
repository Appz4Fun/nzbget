//! URL::ParseUrl: splits "scheme://user:password@host:port/resource". It
//! matches the C++ code, quirks included: the scheme is checked with the C
//! library's isalpha/isalnum (current locale), the port is the C atoi of what
//! follows the first ':' of the host part, and a host part that comes out
//! empty or reversed is, as CString::Set made it, the rest of the address.

use std::ffi::{c_char, c_int, CStr};

extern "C" {
    fn isalpha(c: c_int) -> c_int;
    fn isalnum(c: c_int) -> c_int;
    fn atoi(s: *const c_char) -> c_int;
}

/// A part of the address: (start, length).
pub type Part = Option<(usize, usize)>;

#[derive(Default, Debug, PartialEq)]
pub struct Url {
    pub valid: bool,
    pub protocol: Part,
    pub user: Part,
    pub password: Part,
    pub host: Part,
    /// None with `valid`: "/" (the address has no resource)
    pub resource: Part,
    pub port: i32,
}

fn find(s: &[u8], from: usize, b: u8) -> Option<usize> {
    s.get(from..)?.iter().position(|&c| c == b).map(|k| from + k)
}

/// CString::Set(str, len): a length of 0 or less takes the rest of the text.
fn set(s: &[u8], start: usize, len: isize) -> Part {
    Some((start, if len <= 0 { s.len() - start } else { len as usize }))
}

pub fn parse_url(address: &CStr) -> Url {
    let s = address.to_bytes();
    let mut url = Url::default();
    let Some(prot_end) = s.windows(3).position(|w| w == b"://") else { return url };
    // a scheme is letters, digits, "+", "-" and "."; a "://" further on (a
    // relative "/get?u=https://...") doesn't make an absolute URL
    if prot_end == 0 || unsafe { isalpha(s[0] as c_int) } == 0 {
        return url;
    }
    if !s[..prot_end].iter().all(|&c| unsafe { isalnum(c as c_int) } != 0 || b"+-.".contains(&c)) {
        return url;
    }
    url.protocol = Some((0, prot_end));

    let mut host_start = prot_end + 3;
    let slash = find(s, host_start, b'/');
    if let Some(amp) = find(s, host_start, b'@').filter(|&a| slash.is_none_or(|sl| a < sl)) {
        // user and password
        let mut user_end = amp as isize - 1;
        if let Some(pass) = find(s, host_start, b':').filter(|&p| p < amp) {
            let len = amp as isize - pass as isize - 1;
            if len > 0 {
                url.password = set(s, pass + 1, len);
            }
            user_end = pass as isize - 1;
        }
        let len = user_end - host_start as isize + 1;
        if len > 0 {
            url.user = set(s, host_start, len);
        }
        host_start = amp + 1;
    }

    let mut host_end: isize = match slash {
        Some(sl) => {
            url.resource = Some((sl, s.len() - sl));
            sl as isize - 1
        }
        None => s.len() as isize,
    };
    if let Some(colon) = find(s, host_start, b':').filter(|&c| (c as isize) < host_end) {
        host_end = colon as isize - 1;
        url.port = unsafe { atoi(address.as_ptr().add(colon + 1)) };
    }
    // past the end of the address: an empty host (what strncpy copies)
    let start = host_start.min(s.len());
    url.host = set(s, start, host_end - host_start as isize + 1);
    if let Some((st, l)) = url.host {
        url.host = Some((st, l.min(s.len() - st)));
    }
    url.valid = true;
    url
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parts(a: &str) -> (bool, Vec<String>, i32) {
        let c = std::ffi::CString::new(a).unwrap();
        let u = parse_url(&c);
        let get = |p: Part| p.map_or("<none>".to_string(), |(s, l)| a[s..s + l].to_string());
        (u.valid, vec![get(u.protocol), get(u.user), get(u.password), get(u.host), get(u.resource)], u.port)
    }

    #[test]
    fn urls() {
        assert_eq!(
            parts("https://me:pw@example.com:8443/x/y?z"),
            (true, ["https", "me", "pw", "example.com", "/x/y?z"].map(String::from).to_vec(), 8443)
        );
        assert_eq!(parts("http://host").1[3], "host");
        assert_eq!(parts("http://host").1[4], "<none>");
        assert!(!parts("/get?u=https://x").0);
        assert!(!parts("1http://x").0);
        // an empty host part: the rest of the address, as CString::Set made it
        assert_eq!(parts("http://:80/x").1[3], ":80/x");
    }
}
