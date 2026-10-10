//! WebUtil's in-place text helpers: XmlDecode, XmlStripTags,
//! XmlRemoveEntities, HttpUnquote, UrlDecode, plus UrlEncode and
//! Latin1ToUtf8. Each matches the C++ code byte for byte, quirks included.
//! The in-place ones take the text up to its NUL and return the new length
//! (never longer).

/// A code point as UTF-8, as the C++ AppendUtf8 (also in decode.rs): NUL, a
/// surrogate or a value past Unicode becomes U+FFFD.
fn push_utf8(code: u32, out: &mut Vec<u8>) {
    let c = char::from_u32(code).filter(|&c| c != '\0').unwrap_or('\u{fffd}');
    let mut buf = [0u8; 4];
    out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
}

/// WebUtil::XmlDecode: the five predefined entities, numeric references (as
/// UTF-8; digits clamp at 0x110000), CDATA sections as their text; an unknown
/// entity is kept.
pub fn xml_decode(buf: &mut [u8]) -> usize {
    let s = buf.to_vec();
    let mut out = Vec::with_capacity(s.len());
    let mut p = 0;
    let at = |k: usize| *s.get(k).unwrap_or(&0);
    while p < s.len() {
        match s[p] {
            b'<' if s[p..].starts_with(b"<![CDATA[") => {
                p += 9;
                let end = s[p..].windows(3).position(|w| w == b"]]>").map(|k| p + k);
                let stop = end.unwrap_or(s.len());
                out.extend_from_slice(&s[p..stop]);
                p = end.map_or(stop, |e| e + 3);
            }
            b'&' => {
                p += 1;
                let rest = &s[p..];
                let named: &[(&[u8], u8)] = &[(b"lt;", b'<'), (b"gt;", b'>'), (b"amp;", b'&'), (b"apos;", b'\''), (b"quot;", b'"')];
                if let Some(&(lit, c)) = named.iter().find(|(lit, _)| rest.starts_with(lit)) {
                    out.push(c);
                    p += lit.len();
                } else if at(p) == b'#' {
                    p += 1;
                    let hex = at(p) == b'x' || at(p) == b'X';
                    if hex {
                        p += 1;
                    }
                    let mut code: u32 = 0;
                    let mut any = false;
                    while let Some(d) = (at(p) as char).to_digit(if hex { 16 } else { 10 }) {
                        code = (code * if hex { 16 } else { 10 } + d).min(0x110000);
                        any = true;
                        p += 1;
                    }
                    if at(p) == b';' {
                        p += 1;
                    }
                    if any {
                        push_utf8(code, &mut out);
                    }
                } else if p >= s.len() {
                    out.push(b'&');
                } else {
                    // unknown entity: kept as is
                    out.push(b'&');
                    out.push(s[p]);
                    p += 1;
                }
            }
            c => {
                out.push(c);
                p += 1;
            }
        }
    }
    buf[..out.len()].copy_from_slice(&out);
    out.len()
}

/// WebUtil::XmlStripTags: each "<...>" becomes spaces; an unclosed '<' stays.
pub fn xml_strip_tags(buf: &mut [u8]) {
    let mut p = 0;
    while let Some(start) = buf[p..].iter().position(|&b| b == b'<').map(|k| p + k) {
        let Some(end) = buf[start..].iter().position(|&b| b == b'>').map(|k| start + k) else { break };
        buf[start..=end].fill(b' ');
        p = end + 1;
    }
}

/// WebUtil::XmlRemoveEntities: "&name;" / "&#123;" become one space.
/// `is_alpha` is the C library's isalpha of the current locale for bytes from
/// 0x80 (as the C++ char, see nzbget_rs.h).
pub fn xml_remove_entities(buf: &mut [u8], is_alpha: &dyn Fn(u8) -> bool) -> usize {
    let len = buf.len();
    let (mut p, mut o) = (0, 0);
    while p < len {
        if buf[p] == b'&' {
            let mut q = p + 1;
            while q < len && {
                let b = buf[q];
                if b < 0x80 { b.is_ascii_alphanumeric() || b == b'#' } else { is_alpha(b) }
            } {
                q += 1;
            }
            if q < len && buf[q] == b';' {
                buf[o] = b' ';
                o += 1;
                p = q + 1;
                continue;
            }
        }
        buf[o] = buf[p];
        o += 1;
        p += 1;
    }
    o
}

/// WebUtil::HttpUnquote: a "quoted string" without its quotes and with its
/// backslash escapes resolved; text not starting with '"' stays as it is.
pub fn http_unquote(buf: &mut [u8]) -> usize {
    if buf.first() != Some(&b'"') {
        return buf.len();
    }
    let len = buf.len();
    let (mut p, mut o) = (1, 0);
    while p < len && buf[p] != b'"' {
        if buf[p] == b'\\' {
            p += 1;
            if p < len {
                buf[o] = buf[p];
                o += 1;
                p += 1;
            }
        } else {
            buf[o] = buf[p];
            o += 1;
            p += 1;
        }
    }
    o
}

/// WebUtil::UrlDecode: "%XY" as the byte (a digit that isn't hex counts 0;
/// "%" with fewer than two bytes after it stays).
pub fn url_decode(buf: &mut [u8]) -> usize {
    let nibble = |c: u8| (c as char).to_digit(16).unwrap_or(0) as u8;
    let len = buf.len();
    let (mut p, mut o) = (0, 0);
    while p < len {
        if buf[p] == b'%' && p + 2 < len {
            buf[o] = (nibble(buf[p + 1]) << 4).wrapping_add(nibble(buf[p + 2]));
            p += 3;
        } else {
            buf[o] = buf[p];
            p += 1;
        }
        o += 1;
    }
    o
}

/// WebUtil::UrlEncode: spaces as "%20", everything else as is.
pub fn url_encode(s: &[u8], out: &mut Vec<u8>) {
    out.reserve(s.len());
    for &b in s {
        if b == b' ' {
            out.extend_from_slice(b"%20");
        } else {
            out.push(b);
        }
    }
}

/// WebUtil::Latin1ToUtf8.
pub fn latin1_to_utf8(s: &[u8], out: &mut Vec<u8>) {
    out.reserve(s.len() * 2);
    for &b in s {
        if b < 0x80 {
            out.push(b);
        } else {
            out.push(0xc2 + (b > 0xbf) as u8);
            out.push((b & 0x3f) + 0x80);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inplace(f: impl Fn(&mut [u8]) -> usize, s: &[u8]) -> Vec<u8> {
        let mut v = s.to_vec();
        let n = f(&mut v);
        v.truncate(n);
        v
    }

    #[test]
    fn decoders() {
        assert_eq!(
            inplace(xml_decode, b"a&lt;b&gt;&amp;&apos;&quot;&#233;&#xe9;&nbsp;<![CDATA[&lt;]]>&"),
            "a<b>&'\"\u{e9}\u{e9}&nbsp;&lt;&".as_bytes()
        );
        assert_eq!(inplace(xml_decode, b"&#0;&#x110000;&#xd800;&#"), "\u{fffd}\u{fffd}\u{fffd}".as_bytes());
        assert_eq!(inplace(http_unquote, b"\"a\\\"b\\\\c\"rest"), b"a\"b\\c");
        assert_eq!(inplace(http_unquote, b"plain"), b"plain");
        assert_eq!(inplace(url_decode, b"a%20b%zz%4"), b"a b\0%4");
        assert_eq!(inplace(|b| xml_remove_entities(b, &|_| false), b"x&amp;y&#12;z&nope"), b"x y z&nope");
        let mut v = b"a<b>c<d".to_vec();
        xml_strip_tags(&mut v);
        assert_eq!(v, b"a   c<d");
    }
}
