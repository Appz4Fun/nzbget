//! The web server's request handling decisions (WebProcessor): what a request
//! header line means, the URL's prefix and credentials, the credential check
//! and the authorized-IP list. They match the C++ code; header names compare
//! as the C library's strncasecmp and numbers parse as its atoi (current
//! locale). Reading the request and answering it stay C++.

use std::ffi::{c_char, c_int, CString};

use crate::wildmask::{wild_match, Lower};

extern "C" {
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
    fn atoi(s: *const c_char) -> c_int;
}

/// sizeof(m_authInfo) and TOKEN_SIZE of WebServer.h.
pub const AUTH_INFO_SIZE: usize = 256 + 1;
pub const TOKEN_SIZE: usize = 48 + 1;

fn c(b: &[u8]) -> CString {
    CString::new(b).unwrap_or_default()
}

fn prefix(line: &[u8], lit: &str) -> bool {
    unsafe { strncasecmp(c(line).as_ptr(), c(lit.as_bytes()).as_ptr(), lit.len()) == 0 }
}

fn find(h: &[u8], n: &[u8]) -> Option<usize> {
    h.windows(n.len()).position(|w| w == n)
}

/// What a header line (its last '\r' cut off) does in ParseHeaders.
#[derive(Debug, PartialEq)]
pub enum Header<'a> {
    ContentLength(i32),
    /// base64 credentials for m_authInfo
    Auth(&'a [u8]),
    /// credentials too long: an error, and the headers end
    AuthTooBig,
    AcceptEncoding { gzip: bool },
    Origin(&'a [u8]),
    /// the Auth-Token cookie's value as copied (up to TOKEN_SIZE - 1 bytes)
    AuthToken(&'a [u8]),
    ForwardedFor(&'a [u8]),
    IfNoneMatch(&'a [u8]),
    KeepAlive,
    /// the empty line: the headers end
    End,
    Other,
}

/// ParseHeaders for one line; `auth_info_empty`: no credentials yet (only
/// then does "Authorization:" count, else the line goes on to the next tests).
fn auth(b64: &[u8]) -> Header<'_> {
    if b64.len() > AUTH_INFO_SIZE {
        Header::AuthTooBig
    } else {
        Header::Auth(b64)
    }
}

pub fn header(line: &[u8], auth_info_empty: bool) -> Header<'_> {
    // the C string of the line ends at a NUL
    let line = &line[..line.iter().position(|&b| b == 0).unwrap_or(line.len())];
    if prefix(line, "Content-Length: ") {
        Header::ContentLength(unsafe { atoi(c(&line[16..]).as_ptr()) })
    } else if prefix(line, "Authorization: Basic ") && auth_info_empty {
        auth(&line[21..])
    } else if prefix(line, "X-Authorization: Basic ") {
        auth(&line[23..])
    } else if prefix(line, "Accept-Encoding: ") {
        Header::AcceptEncoding { gzip: find(line, b"gzip").is_some() }
    } else if prefix(line, "Origin: ") {
        Header::Origin(&line[8..])
    } else if prefix(line, "Cookie: ") {
        match find(line, b"Auth-Token=").map(|k| &line[k + 11..]) {
            Some(tok) if !tok.is_empty() && tok[0] != b';' => Header::AuthToken(&tok[..tok.len().min(TOKEN_SIZE - 1)]),
            _ => Header::Other,
        }
    } else if prefix(line, "X-Forwarded-For: ") {
        Header::ForwardedFor(&line[17..])
    } else if prefix(line, "If-None-Match: ") {
        Header::IfNoneMatch(&line[15..])
    } else if prefix(line, "Connection: keep-alive") {
        Header::KeepAlive
    } else if line.is_empty() {
        Header::End
    } else {
        Header::Other
    }
}

/// What ParseUrl makes of the request URL.
#[derive(Debug, PartialEq)]
pub enum Url {
    /// "/nzbget": a redirect to this location
    Redirect(Vec<u8>),
    /// the URL to dispatch, and credentials given in it (URL-decoded, as the
    /// C string they made: up to a NUL)
    Go { url: Vec<u8>, auth: Option<Vec<u8>> },
}

/// WebProcessor::ParseUrl.
pub fn parse_url(url: &[u8]) -> Url {
    // Like the header parser, preserve the original C string boundary even
    // when a bounded FFI input includes bytes after its terminator.
    let url = &url[..url.iter().position(|&b| b == 0).unwrap_or(url.len())];
    let mut url = url.to_vec();
    if url.starts_with(b"/nzbget/") {
        url.drain(..7);
    }
    if url == b"/nzbget" {
        // BString<1024>("%s/")
        let mut loc = [&url[..], b"/"].concat();
        loc.truncate(1023);
        return Url::Redirect(loc);
    }
    // "/username:password/jsonrpc"
    let rest = url.get(1..).unwrap_or_default();
    let colon = rest.iter().position(|&b| b == b':');
    let slash = rest.iter().position(|&b| b == b'/');
    if let (Some(c), Some(s)) = (colon, slash) {
        if c < s {
            let mut auth = rest[..s.min(AUTH_INFO_SIZE - 1)].to_vec();
            let len = crate::text::url_decode(&mut auth);
            auth.truncate(len);
            if let Some(n) = auth.iter().position(|&b| b == 0) {
                auth.truncate(n);
            }
            let url = url[1 + s..].to_vec();
            return Url::Go { url, auth: Some(auth) };
        }
    }
    Url::Go { url, auth: None }
}

/// The options CheckCredentials compares with (null C strings as None).
pub struct Credentials<'a> {
    pub control_username: Option<&'a [u8]>,
    pub control_password: Option<&'a [u8]>,
    pub restricted_username: Option<&'a [u8]>,
    pub restricted_password: Option<&'a [u8]>,
    pub add_username: Option<&'a [u8]>,
    pub add_password: Option<&'a [u8]>,
    pub authorized_ip: Option<&'a [u8]>,
}

/// The result of CheckCredentials.
#[derive(Debug, PartialEq)]
pub struct Check {
    pub authorized: bool,
    /// 0 control, 1 restricted, 2 add (as EUserAccess); None: unchanged
    pub access: Option<i32>,
    /// where the C++ cut m_authInfo (its ':' became a NUL)
    pub auth_cut: Option<usize>,
    /// the "username or password invalid" warning
    pub warn: bool,
}

fn empty(s: Option<&[u8]>) -> bool {
    s.is_none_or(|v| v.is_empty())
}

/// strcmp(a, b) == 0 for C strings (a null one compares as the C++ would
/// crash; the C++ never passed one here: callers check EmptyStr first).
fn eq(a: &[u8], b: Option<&[u8]>) -> bool {
    b.is_some_and(|b| a == b)
}

/// WebProcessor::IsAuthorizedIp: the address matches one of the option's
/// wildcard patterns (',' or ';' separated).
pub fn is_authorized_ip(option: &[u8], remote: &[u8], lower: &Lower<'_>) -> bool {
    crate::util::tokens(option, b",;").any(|ip| wild_match(lower, ip, remote, None))
}

/// WebProcessor::CheckCredentials: `auth_info` as received (up to its NUL),
/// `auth_token` the cookie's, `server_tokens` the three access levels'.
pub fn check_credentials(
    o: &Credentials<'_>,
    remote: &[u8],
    auth_info: &[u8],
    auth_token: &[u8],
    server_tokens: [&[u8]; 3],
    lower: &Lower<'_>,
) -> Check {
    let mut r = Check { authorized: true, access: None, auth_cut: None, warn: false };
    let ip_ok = !empty(o.authorized_ip) && is_authorized_ip(o.authorized_ip.unwrap_or_default(), remote, lower);
    if empty(o.control_password) || ip_ok {
        return r;
    }
    if auth_info.is_empty() {
        // the X-Auth-Token
        match server_tokens.iter().position(|t| *t == auth_token) {
            Some(j) => r.access = Some(j as i32),
            None => r.authorized = false,
        }
        return r;
    }
    // "username:password"
    let (user, pw) = match auth_info.iter().position(|&b| b == b':') {
        Some(k) => {
            r.auth_cut = Some(k);
            (&auth_info[..k], Some(&auth_info[k + 1..]))
        }
        None => (auth_info, None),
    };
    let pw_is = |p: Option<&[u8]>| pw.is_some_and(|pw| eq(pw, p));
    if (empty(o.control_username) || eq(user, o.control_username)) && pw_is(o.control_password) {
        r.access = Some(0);
    } else if !empty(o.restricted_username) && eq(user, o.restricted_username) && pw_is(o.restricted_password) {
        r.access = Some(1);
    } else if !empty(o.add_username) && eq(user, o.add_username) && pw_is(o.add_password) {
        r.access = Some(2);
    } else {
        r.authorized = false;
        r.warn = true;
    }
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ascii(b: u8) -> c_int {
        b.to_ascii_lowercase() as c_int
    }

    #[test]
    fn headers() {
        assert_eq!(header(b"content-length: 42", true), Header::ContentLength(42));
        assert_eq!(header(b"Authorization: Basic YWJj", true), Header::Auth(b"YWJj"));
        assert_eq!(header(b"Authorization: Basic YWJj", false), Header::Other);
        assert_eq!(header(b"Cookie: a=1; Auth-Token=xyz; b=2", true), Header::AuthToken(b"xyz; b=2"));
        assert_eq!(header(b"Cookie: Auth-Token=;", true), Header::Other);
        assert_eq!(header(b"", true), Header::End);
    }

    #[test]
    fn urls() {
        assert_eq!(parse_url(b"/nzbget"), Url::Redirect(b"/nzbget/".to_vec()));
        assert_eq!(parse_url(b"/nzbget/u:p%40/jsonrpc"), Url::Go { url: b"/jsonrpc".to_vec(), auth: Some(b"u:p@".to_vec()) });
        assert_eq!(parse_url(b"/jsonrpc?x=a:b"), Url::Go { url: b"/jsonrpc?x=a:b".to_vec(), auth: None });
        assert_eq!(parse_url(b"/nzbget\0/u:p/jsonrpc"), Url::Redirect(b"/nzbget/".to_vec()));
        assert_eq!(parse_url(b"/u:p\0/jsonrpc"), Url::Go { url: b"/u:p".to_vec(), auth: None });
    }

    #[test]
    fn credentials() {
        let l = Lower::Fold(&ascii);
        let o = Credentials {
            control_username: Some(b"nzbget"),
            control_password: Some(b"secret"),
            restricted_username: None,
            restricted_password: None,
            add_username: None,
            add_password: None,
            authorized_ip: Some(b"192.168.1.*"),
        };
        let tokens: [&[u8]; 3] = [b"t0", b"t1", b"t2"];
        assert!(check_credentials(&o, b"192.168.1.93", b"", b"", tokens, &l).authorized);
        let c = check_credentials(&o, b"10.0.0.1", b"nzbget:secret", b"", tokens, &l);
        assert_eq!((c.authorized, c.access, c.auth_cut), (true, Some(0), Some(6)));
        assert!(check_credentials(&o, b"10.0.0.1", b"nzbget:wrong", b"", tokens, &l).warn);
        assert_eq!(check_credentials(&o, b"10.0.0.1", b"", b"t2", tokens, &l).access, Some(2));
    }
}
