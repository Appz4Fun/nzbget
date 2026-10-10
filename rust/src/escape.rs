//! JSON and XML string escaping for RPC responses (WebUtil::JsonEncode, WebUtil::XmlEncode).
//!
//! The input is a NUL-free byte string (the C++ callers pass C strings). Bytes
//! below 0x20 or at/above 0x80 are decoded as UTF-8 the way the C++ code always
//! has, quirks included, so responses don't change: a sequence cut short by the
//! end of the input ends the output, and only the first continuation byte is checked.

use std::io::Write;

/// Decodes the code point starting at `s[i]` (a control or non-ASCII byte).
/// Returns the code point and the index of its last byte, or None when the
/// input ends inside the sequence.
#[inline]
fn decode(s: &[u8], i: usize) -> Option<(u32, usize)> {
    let at = |k: usize| -> Option<u32> { s.get(k).map(|&b| b as u32) };
    let ch = s[i] as u32;
    let next_cont = matches!(s.get(i + 1), Some(&b) if b & 0xc0 == 0x80);
    if ch >> 5 == 0x6 && next_cont {
        let c1 = at(i + 1)?;
        Some((((ch << 6) & 0x7ff) + (c1 & 0x3f), i + 1))
    } else if ch >> 4 == 0xe && next_cont {
        let c1 = at(i + 1)?;
        let mut cp = ((ch << 12) & 0xffff) + ((c1 << 6) & 0xfff);
        let c2 = at(i + 2)?;
        cp += c2 & 0x3f;
        Some((cp, i + 2))
    } else if ch >> 3 == 0x1e && next_cont {
        let c1 = at(i + 1)?;
        let mut cp = ((ch << 18) & 0x1fffff) + ((c1 << 12) & 0x3ffff);
        let c2 = at(i + 2)?;
        cp += (c2 << 6) & 0xfff;
        let c3 = at(i + 3)?;
        cp += c3 & 0x3f;
        Some((cp, i + 3))
    } else {
        Some((ch, i))
    }
}

#[inline]
fn json_plain(b: u8) -> bool {
    (0x20..0x80).contains(&b) && b != b'"' && b != b'\\' && b != b'/'
}

pub fn json_encode(s: &[u8], out: &mut Vec<u8>) {
    out.reserve(s.len() + s.len() / 8 + 16);
    let mut i = 0;
    while i < s.len() {
        // copy the run of bytes that need no escape in one go
        let start = i;
        while i < s.len() && json_plain(s[i]) {
            i += 1;
        }
        out.extend_from_slice(&s[start..i]);
        if i == s.len() {
            break;
        }
        match s[i] {
            b'"' => out.extend_from_slice(b"\\\""),
            b'\\' => out.extend_from_slice(b"\\\\"),
            b'/' => out.extend_from_slice(b"\\/"),
            0x08 => out.extend_from_slice(b"\\b"),
            0x0c => out.extend_from_slice(b"\\f"),
            b'\n' => out.extend_from_slice(b"\\n"),
            b'\r' => out.extend_from_slice(b"\\r"),
            b'\t' => out.extend_from_slice(b"\\t"),
            _ => {
                let Some((cp, last)) = decode(s, i) else { return };
                i = last;
                if cp <= 0xffff {
                    let _ = write!(out, "\\u{:04x}", cp);
                } else {
                    let c = cp - 0x10000;
                    let _ = write!(out, "\\u{:04x}\\u{:04x}", 0xd800 + (c >> 10), 0xdc00 + (c & 0x3ff));
                }
            }
        }
        i += 1;
    }
}

#[inline]
fn xml_plain(b: u8) -> bool {
    (0x20..0x80).contains(&b) && !matches!(b, b'<' | b'>' | b'&' | b'\'' | b'"')
}

pub fn xml_encode(s: &[u8], out: &mut Vec<u8>) {
    out.reserve(s.len() + s.len() / 8 + 16);
    let mut i = 0;
    while i < s.len() {
        let start = i;
        while i < s.len() && xml_plain(s[i]) {
            i += 1;
        }
        out.extend_from_slice(&s[start..i]);
        if i == s.len() {
            break;
        }
        match s[i] {
            b'<' => out.extend_from_slice(b"&lt;"),
            b'>' => out.extend_from_slice(b"&gt;"),
            b'&' => out.extend_from_slice(b"&amp;"),
            b'\'' => out.extend_from_slice(b"&apos;"),
            b'"' => out.extend_from_slice(b"&quot;"),
            _ => {
                let Some((cp, last)) = decode(s, i) else { return };
                i = last;
                // only valid XML 1.0 characters; others become dots
                if cp == 0x9
                    || cp == 0xa
                    || cp == 0xd
                    || (0x20..=0xd7ff).contains(&cp)
                    || (0xe000..=0xfffd).contains(&cp)
                    || (0x10000..=0x10ffff).contains(&cp)
                {
                    let _ = write!(out, "&#x{:06x};", cp);
                } else {
                    out.push(b'.');
                }
            }
        }
        i += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn j(s: &[u8]) -> String {
        let mut v = Vec::new();
        json_encode(s, &mut v);
        String::from_utf8(v).unwrap()
    }
    fn x(s: &[u8]) -> String {
        let mut v = Vec::new();
        xml_encode(s, &mut v);
        String::from_utf8(v).unwrap()
    }

    #[test]
    fn json() {
        assert_eq!(j(b"plain"), "plain");
        assert_eq!(j(b"a\"b\\c/d\n\t"), "a\\\"b\\\\c\\/d\\n\\t");
        assert_eq!(j("é".as_bytes()), "\\u00e9");
        assert_eq!(j("€".as_bytes()), "\\u20ac");
        assert_eq!(j("😀".as_bytes()), "\\ud83d\\ude00");
        assert_eq!(j(b"\x01"), "\\u0001");
        assert_eq!(j(b"a\xff"), "a\\u00ff");
        assert_eq!(j(b"a\xe2\x82"), "a"); // cut short: output ends
    }

    #[test]
    fn xml() {
        assert_eq!(x(b"<a href='x'>&\"</a>"), "&lt;a href=&apos;x&apos;&gt;&amp;&quot;&lt;/a&gt;");
        assert_eq!(x("é".as_bytes()), "&#x0000e9;");
        assert_eq!(x(b"\x01"), ".");
        assert_eq!(x(b"\t"), "&#x000009;");
    }
}
