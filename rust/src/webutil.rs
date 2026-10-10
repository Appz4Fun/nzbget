//! WebUtil's tag and field finders and ParseContentDispositionFilename,
//! matching the C++ code byte for byte, quirks included.

use crate::wildmask::Lower;

/// strstr on NUL-free byte strings: an empty needle is found at 0.
fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() {
        return Some(0);
    }
    hay.windows(needle.len()).position(|w| w == needle)
}

/// A string formatted into BString<100>: at most 99 bytes.
fn bstring100(parts: &[&[u8]]) -> Vec<u8> {
    // BString has fixed storage. Do not allocate/copy the full name before
    // truncating: a long caller-supplied name must not exhaust the heap.
    let mut v = Vec::with_capacity(99);
    for part in parts {
        let n = part.len().min(99 - v.len());
        v.extend_from_slice(&part[..n]);
        if v.len() == 99 {
            break;
        }
    }
    v
}

/// WebUtil::XmlFindTag: the value of `<tag>value</tag>` as (start, length),
/// or (start of `<tag/>`, 0) when that comes first. The tags are formatted as
/// the C++ code did (cut to 99 bytes), and the length can come out negative,
/// as it could there.
pub fn xml_find_tag(xml: &[u8], tag: &[u8]) -> Option<(usize, i64)> {
    let open = bstring100(&[b"<", tag, b">"]);
    let close = bstring100(&[b"</", tag, b">"]);
    let open_close = bstring100(&[b"<", tag, b"/>"]);
    let pstart = find(xml, &open);
    let pstartend = find(xml, &open_close);
    if let Some(e) = pstartend {
        if pstart.is_none_or(|s| e < s) {
            return Some((e, 0));
        }
    }
    let pstart = pstart?;
    let pend = pstart + find(&xml[pstart..], &close)?;
    Some((pstart + open.len(), pend as i64 - pstart as i64 - open.len() as i64))
}

/// WebUtil::JsonFindField: the value after `"field"` (as JsonNextValue).
pub fn json_find_field(text: &[u8], field: &[u8]) -> Option<(usize, usize)> {
    let open = bstring100(&[b"\"", field, b"\""]);
    let after = find(text, &open)? + open.len();
    crate::decode::json_next_value(&text[after..]).map(|(s, l)| (after + s, l))
}

/// strncasecmp(a, b, n) == 0 for `a` and `b` of length n, through the
/// locale's tolower of unsigned bytes.
fn case_eq(lower: &Lower<'_>, a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(&x, &y)| lower.eq(x, y))
}

/// A C string's text: up to its first NUL.
fn c_str(mut v: Vec<u8>) -> Vec<u8> {
    if let Some(n) = v.iter().position(|&b| b == 0) {
        v.truncate(n);
    }
    v
}

/// WebUtil::ParseContentDispositionFilename: the RFC 5987 `filename*` when it
/// gives one, else `filename` (unquoted), else None (the C++ null CString).
/// `lower` folds case as the C library's strncasecmp (unsigned bytes).
pub fn content_disposition_filename(cd: &[u8], lower: &Lower<'_>) -> Option<Vec<u8>> {
    let n = cd.len();
    let at = |k: usize| *cd.get(k).unwrap_or(&0);
    let mut filename: Option<Vec<u8>> = None;
    let mut ext: Option<Vec<u8>> = None;
    let mut p = 0;
    while p < n {
        while matches!(at(p), b';' | b' ' | b'\t' | b'\r' | b'\n') {
            p += 1;
        }
        if p >= n {
            break;
        }
        let name_start = p;
        while p < n && cd[p] != b'=' && cd[p] != b';' {
            p += 1;
        }
        let mut name_len = p - name_start;
        while name_len > 0 && matches!(cd[name_start + name_len - 1], b' ' | b'\t') {
            name_len -= 1;
        }
        if at(p) != b'=' {
            // the disposition type ("attachment") or a parameter without value
            continue;
        }
        p += 1;
        while matches!(at(p), b' ' | b'\t') {
            p += 1;
        }
        let value_start = p;
        let quoted = at(p) == b'"';
        let value_len;
        if quoted {
            p += 1;
            while p < n && cd[p] != b'"' {
                p += if cd[p] == b'\\' && p + 1 < n { 2 } else { 1 };
            }
            if at(p) == b'"' {
                p += 1;
            }
            value_len = p - value_start;
            while p < n && cd[p] != b';' {
                p += 1;
            }
        } else {
            while p < n && cd[p] != b';' {
                p += 1;
            }
            let mut len = p - value_start;
            while len > 0 && matches!(cd[value_start + len - 1], b' ' | b'\t' | b'\r' | b'\n') {
                len -= 1;
            }
            value_len = len;
        }
        if value_len == 0 {
            continue;
        }
        let name = &cd[name_start..name_start + name_len];
        let value = &cd[value_start..value_start + value_len];
        if case_eq(lower, name, b"filename") {
            let mut f = value.to_vec();
            if quoted {
                let len = crate::text::http_unquote(&mut f);
                f.truncate(len);
            }
            filename = Some(f);
        } else if case_eq(lower, name, b"filename*") {
            // ext-value = charset "'" [ language ] "'" value-chars (RFC 5987)
            let apo1 = value.iter().position(|&b| b == b'\'');
            let apo2 = apo1.and_then(|a| value[a + 1..].iter().position(|&b| b == b'\'').map(|k| a + 1 + k));
            if let (Some(a1), Some(a2)) = (apo1, apo2) {
                if a2 + 1 < value.len() {
                    let mut e = value[a2 + 1..].to_vec();
                    let len = crate::text::url_decode(&mut e);
                    e.truncate(len);
                    let mut e = c_str(e);
                    if a1 == 10 && case_eq(lower, &value[..10], b"ISO-8859-1") {
                        let mut u = Vec::new();
                        crate::text::latin1_to_utf8(&e, &mut u);
                        e = u;
                    }
                    ext = Some(e);
                }
            }
        }
    }
    match ext {
        Some(e) if !e.is_empty() => Some(e),
        _ => filename,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ascii(b: u8) -> std::ffi::c_int {
        b.to_ascii_lowercase() as std::ffi::c_int
    }

    #[test]
    fn tags_and_fields() {
        let xml = b"<a><b>12</b><c/></a>";
        assert_eq!(xml_find_tag(xml, b"b"), Some((6, 2)));
        assert_eq!(xml_find_tag(xml, b"c"), Some((12, 0)));
        assert_eq!(xml_find_tag(xml, b"d"), None);
        let json = b"{\"x\" : \"yz\", \"n\": 5}";
        assert_eq!(json_find_field(json, b"n"), Some((18, 1)));
    }

    #[test]
    fn truncated_search_names() {
        let tag = vec![b'/'; 4096];
        let mut xml = vec![b'<'];
        xml.extend_from_slice(&tag[..98]);
        // All three formatted tags truncate to the same string. Preserve the
        // legacy negative length and pointer to the terminating NUL.
        assert_eq!(xml_find_tag(&xml, &tag), Some((99, -99)));
        let field = vec![b'a'; 4096];
        let mut json = vec![b'"'];
        json.extend_from_slice(&field[..98]);
        json.extend_from_slice(b": 12");
        assert_eq!(json_find_field(&json, &field), Some((101, 2)));
    }

    #[test]
    fn content_disposition() {
        let l = Lower::Fold(&ascii);
        let f = |s: &[u8]| content_disposition_filename(s, &l);
        assert_eq!(f(b"attachment; filename=\"a \\\"b\\\".nzb\""), Some(b"a \"b\".nzb".to_vec()));
        assert_eq!(f(b"attachment;FILENAME=x.nzb ; filename*=UTF-8''y%20z.nzb"), Some(b"y z.nzb".to_vec()));
        assert_eq!(f(b"attachment; filename*=ISO-8859-1''caf%E9.nzb"), Some("caf\u{e9}.nzb".as_bytes().to_vec()));
        assert_eq!(f(b"attachment"), None);
        assert_eq!(f(b"attachment; filename*=UTF-8''%00x; filename=k"), Some(b"k".to_vec()));
    }
}
