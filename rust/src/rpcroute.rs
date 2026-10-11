//! XmlRpcProcessor's request routing and response envelope (XmlRpc.cpp):
//! the protocol from the URL (Execute), the method name, where the
//! parameters start and the JSON request id (Dispatch), and the text around
//! a command's response (BuildResponse), as the C++ did them. Also the access
//! a request runs with (Access) and whether Dispatch runs a command or
//! answers with an error (Decide).

use crate::webutil::{json_find_field, xml_find_tag};

/// XmlRpcProcessor::ERpcProtocol
pub const RP_UNDEFINED: i32 = 0;
pub const RP_XML_RPC: i32 = 1;
pub const RP_JSON_RPC: i32 = 2;
pub const RP_JSONP_RPC: i32 = 3;

/// BString<100>
const METHOD_SIZE: usize = 100;

// WebUtil reports lengths through a C int, before Dispatch applies its caps.
// Preserve that narrowing even for inputs larger than the HTTP body's limit:
// the routing ABI can be called directly with any NUL-terminated string.
fn value_length(len: usize) -> i64 {
    i64::from(len as std::ffi::c_int)
}

/// Execute: the protocol of an RPC URL, or RP_UNDEFINED.
pub fn protocol(url: &[u8]) -> i32 {
    let is = |p: &[u8]| url == p || (url.starts_with(p) && url.get(p.len()) == Some(&b'/'));
    if is(b"/xmlrpc") {
        RP_XML_RPC
    } else if is(b"/jsonrpc") {
        RP_JSON_RPC
    } else if is(b"/jsonprpc") {
        RP_JSONP_RPC
    } else {
        RP_UNDEFINED
    }
}

/// BString<100>::Set(str, len): up to `len` bytes (99 at most; all 99 when
/// `len` <= 0), stopping at a NUL.
fn bstring_set(s: &[u8], len: i64) -> Vec<u8> {
    let max = METHOD_SIZE as i64 - 1;
    let n = if len > 0 { len.min(max) } else { max } as usize;
    let s = &s[..s.len().min(n)];
    s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())].to_vec()
}

/// What Dispatch reads from a request.
#[derive(Debug, Default, PartialEq)]
pub struct Route {
    /// at most 99 bytes
    pub method: Vec<u8>,
    /// GET: the parameters' offset in the URL (else they start at the request)
    pub params: Option<usize>,
    /// JSON-RPC: the id's offset and legacy C-int length, when <= 4096
    pub id: Option<(usize, i64)>,
}

/// Dispatch's parsing: `url` and `request` without their NULs.
pub fn route(url: &[u8], request: &[u8], get: bool, protocol: i32) -> Route {
    let mut r = Route::default();
    if get {
        // the request is the URL after its first character
        let base = 1.min(url.len());
        let rest = &url[base..];
        r.params = Some(base);
        if let Some(slash) = rest.iter().position(|&b| b == b'/') {
            let name = &rest[slash + 1..];
            match name.iter().position(|&b| b == b'?') {
                Some(q) => {
                    r.method = bstring_set(name, q.min(METHOD_SIZE - 1) as i64);
                    r.params = Some(base + slash + 1 + q + 1);
                }
                None => {
                    r.method = bstring_set(name, 0);
                    r.params = Some(url.len());
                }
            }
        }
    } else if protocol == RP_XML_RPC {
        // WebUtil::XmlParseTagValue into the 100-byte buffer
        if let Some((start, len)) = xml_find_tag(request, b"methodName") {
            // The fixed tags cannot overlap. A negative narrowed length made
            // the old strncpy undefined; do not turn it into a huge copy.
            let n = (value_length(len as usize).max(0) as usize).min(METHOD_SIZE - 1);
            let value = &request[start..];
            let value = &value[..value.len().min(n)];
            r.method = value[..value.iter().position(|&b| b == 0).unwrap_or(value.len())].to_vec();
        }
    } else if protocol == RP_JSON_RPC {
        if let Some((start, len)) = json_find_field(request, b"method") {
            let len = value_length(len).min(METHOD_SIZE as i64 - 1);
            r.method = bstring_set(&request[(start + 1).min(request.len())..], len - 2);
        }
        if let Some((start, len)) = json_find_field(request, b"id") {
            let len = value_length(len);
            if len <= 4096 {
                r.id = Some((start, len));
            }
        }
    }
    r
}

/// BuildResponse: the text before and after a command's response.
pub fn envelope(protocol: i32, fault: bool, callback: Option<&[u8]>, id: Option<&[u8]>) -> (Vec<u8>, Vec<u8>) {
    let xml = protocol == RP_XML_RPC;
    let jsonp = protocol == RP_JSONP_RPC;
    let mut head = Vec::new();
    if let Some(cb) = callback {
        head.extend_from_slice(cb);
    }
    if jsonp {
        head.push(b'(');
    }
    head.extend_from_slice(if xml { b"<?xml version=\"1.0\"?>\n<methodResponse>\n" } else { b"{\n\"version\" : \"1.1\",\n" });
    if let Some(id) = id.filter(|id| !xml && !id.is_empty()) {
        head.extend_from_slice(b"\"id\" : ");
        head.extend_from_slice(id);
        head.extend_from_slice(b",\n");
    }
    head.extend_from_slice(match (fault, xml) {
        (true, true) => b"<fault><value>".as_slice(),
        (true, false) => b"\"error\" : ",
        (false, true) => b"<params><param><value>",
        (false, false) => b"\"result\" : ",
    });
    let mut tail = Vec::new();
    tail.extend_from_slice(match (fault, xml) {
        (true, true) => b"</value></fault>\n".as_slice(),
        (false, true) => b"</value></param></params>\n",
        _ => b"",
    });
    tail.extend_from_slice(if xml { b"</methodResponse>".as_slice() } else { b"\n}" });
    if jsonp {
        tail.push(b')');
    }
    (head, tail)
}

/// XmlRpcProcessor::EHttpMethod
pub const HM_POST: i32 = 0;
/// XmlRpcProcessor::EUserAccess
pub const UA_CONTROL: i32 = 0;
pub const UA_RESTRICTED: i32 = 1;

/// XmlRpcProcessor::EDispatch: run the command, answer an error through the
/// JSON-P callback, or answer an error without a callback.
pub const DP_EXECUTE: i32 = 0;
pub const DP_REFUSE_IN_CALLBACK: i32 = 1;
pub const DP_REFUSE: i32 = 2;

/// Access: JSON-P changes control access to restricted; other access is unchanged.
pub fn access(protocol: i32, access: i32) -> i32 {
    if protocol == RP_JSONP_RPC && access == UA_CONTROL {
        UA_RESTRICTED
    } else {
        access
    }
}

/// Decide's answer: what Dispatch does, and for an error its code and text.
#[derive(Debug, PartialEq)]
pub struct Decision {
    pub dispatch: i32,
    pub code: i32,
    pub text: Option<&'static std::ffi::CStr>,
}

/// Decide: JSON-P runs only with option JsonP; a safe (reading) method, a
/// POST or an error command runs; any other method answers error 4, through
/// the callback for JSON-P.
pub fn decide(protocol: i32, http_method: i32, safe: bool, error: bool, jsonp: bool) -> Decision {
    let refuse = |dispatch, code, text| Decision { dispatch, code, text: Some(text) };
    if protocol == RP_JSONP_RPC && !jsonp {
        refuse(DP_REFUSE_IN_CALLBACK, 403, c"JSON-P is turned off (option JsonP). Use JSON-RPC or XML-RPC instead")
    } else if safe || http_method == HM_POST || error {
        Decision { dispatch: DP_EXECUTE, code: 0, text: None }
    } else if protocol == RP_JSONP_RPC {
        refuse(DP_REFUSE_IN_CALLBACK, 4, c"Not safe procedure for JSON-P. Use JSON-RPC or XML-RPC with HTTP-Method POST instead")
    } else {
        refuse(DP_REFUSE, 4, c"Not safe procedure for HTTP-Method GET. Use Method POST instead")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn helper_lengths_narrow_before_dispatch_caps() {
        assert_eq!(value_length(i32::MAX as usize), i64::from(i32::MAX));
        assert_eq!(value_length(i32::MAX as usize + 3), i64::from(i32::MIN) + 2);
        if usize::BITS > 32 {
            assert_eq!(value_length((u64::from(u32::MAX) + 4) as usize), 3);
        }
    }

    #[test]
    fn protocols() {
        assert_eq!(protocol(b"/xmlrpc"), RP_XML_RPC);
        assert_eq!(protocol(b"/jsonrpc/status"), RP_JSON_RPC);
        assert_eq!(protocol(b"/jsonprpc/x"), RP_JSONP_RPC);
        assert_eq!(protocol(b"/jsonrpcx"), RP_UNDEFINED);
    }

    #[test]
    fn routes() {
        let r = route(b"/jsonrpc/log?IDFrom=0", b"", true, RP_JSON_RPC);
        assert_eq!((r.method.as_slice(), r.params), (b"log".as_slice(), Some(13)));
        let r = route(b"/jsonrpc", b"", true, RP_JSON_RPC);
        assert_eq!((r.method.as_slice(), r.params), (b"".as_slice(), Some(1)));
        let r = route(b"/jsonrpc/?abc", b"", true, RP_JSON_RPC);
        assert_eq!(r.method, b"?abc");
        let req = b"{\"method\": \"status\", \"id\": 7}";
        let r = route(b"/jsonrpc", req, false, RP_JSON_RPC);
        assert_eq!(r.method, b"status");
        let (s, l) = r.id.unwrap();
        assert_eq!(&req[s..s + l as usize], b"7");
        let r = route(b"/xmlrpc", b"<methodName>version</methodName>", false, RP_XML_RPC);
        assert_eq!(r.method, b"version");
    }

    #[test]
    fn envelopes() {
        let (h, t) = envelope(RP_JSONP_RPC, false, Some(b"cb"), None);
        assert_eq!(h, b"cb({\n\"version\" : \"1.1\",\n\"result\" : ");
        assert_eq!(t, b"\n})");
    }

    #[test]
    fn access_of_jsonp() {
        for protocol in [RP_UNDEFINED, RP_XML_RPC, RP_JSON_RPC, RP_JSONP_RPC, -1, 4] {
            for user in [UA_CONTROL, UA_RESTRICTED, 2, -1, 3] {
                let expected = if protocol == RP_JSONP_RPC && user == UA_CONTROL { UA_RESTRICTED } else { user };
                assert_eq!(access(protocol, user), expected, "protocol {protocol} access {user}");
            }
        }
    }

    #[test]
    fn decisions() {
        // every input: JSON-P only with option JsonP; then safe, POST or error runs
        for protocol in [RP_UNDEFINED, RP_XML_RPC, RP_JSON_RPC, RP_JSONP_RPC, -1, 7] {
            for http_method in [HM_POST, 1, -1, 2] {
                for bits in 0..8 {
                    let (safe, error, jsonp) = (bits & 1 != 0, bits & 2 != 0, bits & 4 != 0);
                    let d = decide(protocol, http_method, safe, error, jsonp);
                    let runs = safe || http_method == HM_POST || error;
                    if protocol == RP_JSONP_RPC && !jsonp {
                        assert_eq!((d.dispatch, d.code), (DP_REFUSE_IN_CALLBACK, 403));
                    } else if runs {
                        assert_eq!(d, Decision { dispatch: DP_EXECUTE, code: 0, text: None });
                    } else {
                        let callback = protocol == RP_JSONP_RPC;
                        assert_eq!((d.dispatch, d.code), (if callback { DP_REFUSE_IN_CALLBACK } else { DP_REFUSE }, 4));
                    }
                }
            }
        }
        assert_eq!(decide(RP_JSON_RPC, 1, false, false, false).text,
            Some(c"Not safe procedure for HTTP-Method GET. Use Method POST instead"));
    }
}
