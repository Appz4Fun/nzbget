//! XmlRpcProcessor's request routing and response envelope (XmlRpc.cpp):
//! the protocol from the URL (Execute), the method name, where the
//! parameters start and the JSON request id (Dispatch), and the text around
//! a command's response (BuildResponse), as the C++ did them.

use crate::webutil::{json_find_field, xml_find_tag};

/// XmlRpcProcessor::ERpcProtocol
pub const RP_UNDEFINED: i32 = 0;
pub const RP_XML_RPC: i32 = 1;
pub const RP_JSON_RPC: i32 = 2;
pub const RP_JSONP_RPC: i32 = 3;

/// BString<100>
const METHOD_SIZE: usize = 100;

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
    /// JSON-RPC: the id's offset and length in the request, when <= 4096
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
            // never negative: "</methodName>" can't overlap "<methodName>"
            let n = (len.max(0) as usize).min(METHOD_SIZE - 1);
            let value = &request[start..];
            let value = &value[..value.len().min(n)];
            r.method = value[..value.iter().position(|&b| b == 0).unwrap_or(value.len())].to_vec();
        }
    } else if protocol == RP_JSON_RPC {
        if let Some((start, len)) = json_find_field(request, b"method") {
            let len = (len as i64).min(METHOD_SIZE as i64 - 1);
            r.method = bstring_set(&request[(start + 1).min(request.len())..], len - 2);
        }
        if let Some((start, len)) = json_find_field(request, b"id") {
            if len <= 4096 {
                r.id = Some((start, len as i64));
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
