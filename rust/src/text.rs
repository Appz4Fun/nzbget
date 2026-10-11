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
/// entity is kept. `lower` supplies C's locale-sensitive tolower for hex letters.
pub fn xml_decode(buf: &mut [u8], lower: &dyn Fn(u8) -> i32) -> usize {
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
                    while if hex { at(p).is_ascii_hexdigit() } else { at(p).is_ascii_digit() } {
                        // C's digit classes are fixed, but tolower need not map
                        // A-F to a-f in every locale. Preserve the C++ unsigned
                        // arithmetic even when the mapped digit is negative.
                        let d = if at(p).is_ascii_digit() {
                            i32::from(at(p) - b'0')
                        } else {
                            lower(at(p)) - i32::from(b'a') + 10
                        };
                        code = (code * if hex { 16 } else { 10 }).wrapping_add(d as u32).min(0x110000);
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
/// `is_alpha` classifies each byte in the caller's locale and char signedness
/// (see nzbget_rs.h), including locale-specific ASCII letters.
pub fn xml_remove_entities(buf: &mut [u8], is_alpha: &dyn Fn(u8) -> bool) -> usize {
    let len = buf.len();
    let (mut p, mut o) = (0, 0);
    while p < len {
        if buf[p] == b'&' {
            let mut q = p + 1;
            while q < len && {
                let b = buf[q];
                is_alpha(b) || b.is_ascii_digit() || b == b'#'
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

#[cfg(any(target_arch = "x86_64", target_arch = "x86"))]
const LATIN1_PACK: [[u8; 17]; 256] = {
    let mut masks = [[0x80u8; 17]; 256];
    let mut bits = 0;
    while bits < 256 {
        let (mut i, mut out) = (0, 0);
        while i < 8 {
            masks[bits][out] = (2 * i) as u8;
            out += 1;
            if bits & (1 << i) != 0 { masks[bits][out] = (2 * i + 1) as u8; out += 1; }
            i += 1;
        }
        masks[bits][16] = out as u8;
        bits += 1;
    }
    masks
};

/// # Safety
/// CPU supports SSSE3; dst is disjoint and writable for 2*s.len()+1 bytes.
#[cfg(any(target_arch = "x86_64", target_arch = "x86"))]
#[target_feature(enable = "ssse3")]
unsafe fn latin1_ssse3(s: &[u8], dst: *mut u8) -> usize {
    #[cfg(target_arch = "x86_64")]
    use std::arch::x86_64::*;
    #[cfg(target_arch = "x86")]
    use std::arch::x86::*;
    let (mut i, mut output) = (0, dst);
    while s.len() - i >= 8 {
        // loadl reads exactly eight proven source bytes, including at the end.
        let input = _mm_loadl_epi64(s.as_ptr().add(i).cast());
        let high = _mm_cmplt_epi8(input, _mm_setzero_si128());
        let bits = _mm_movemask_epi8(high) as usize & 255;
        if bits == 0 {
            _mm_storel_epi64(output.cast(), input);
            output = output.add(8);
        } else {
            let lead = _mm_or_si128(_mm_set1_epi8(0xc2u8 as i8),
                _mm_and_si128(_mm_srli_epi16::<6>(input), _mm_set1_epi8(1)));
            let first = _mm_or_si128(_mm_and_si128(high, lead), _mm_andnot_si128(high, input));
            let tail = _mm_or_si128(_mm_and_si128(input, _mm_set1_epi8(0x3f)), _mm_set1_epi8(0x80u8 as i8));
            let pairs = _mm_unpacklo_epi8(first, tail);
            let mask = &LATIN1_PACK[bits];
            let packed = _mm_shuffle_epi8(pairs, _mm_loadu_si128(mask.as_ptr().cast()));
            // Previously emitted <=2*i bytes, so this 16-byte store fits in
            // 2*s.len() whenever the input has these eight bytes remaining.
            _mm_storeu_si128(output.cast(), packed);
            output = output.add(mask[16] as usize);
        }
        i += 8;
    }
    for &c in &s[i..] {
        if c < 0x80 { *output = c; output = output.add(1); }
        else {
            *output = 0xc2 + (c > 0xbf) as u8;
            *output.add(1) = (c & 0x3f) + 0x80;
            output = output.add(2);
        }
    }
    *output = 0;
    output.offset_from(dst) as usize
}

/// # Safety
/// raw is readable through its NUL; dst is disjoint and has worst-case room
/// (two bytes per input byte, plus NUL). The portable loop is unchanged.
unsafe fn latin1_scalar_cstr(raw: *const u8, dst: *mut u8) -> usize {
    let (mut read, mut write) = (raw, dst);
    loop {
        let c = *read;
        if c == 0 { break; }
        *write = c;
        write = write.add(1);
        if c >= 0x80 {
            *write.sub(1) = 0xc2 + (c > 0xbf) as u8;
            *write = (c & 0x3f) + 0x80;
            write = write.add(1);
        }
        read = read.add(1);
    }
    *write = 0;
    write.offset_from(dst) as usize
}

/// The known C-string length avoids a second strlen. With worst-case room,
/// the direct loop initializes only output bytes and its final NUL.
///
/// # Safety
/// raw is readable through the first NUL at s.len(), and its bytes equal s.
/// For empty s, raw may be null. dst is null or writable for cap bytes and
/// does not overlap the input (including its NUL).
pub unsafe fn latin1_known_into(s: &[u8], raw: *const u8, dst: *mut u8, cap: usize) -> usize {
    if s.is_empty() {
        if !dst.is_null() && cap > 0 { *dst = 0; }
        return 0;
    }
    let Some(max) = s.len().checked_mul(2) else { return usize::MAX };
    if dst.is_null() || cap <= max {
        let n = s.len() + s.iter().filter(|&&c| c >= 0x80).count();
        if dst.is_null() || n >= cap { return n; }
        return latin1_scalar_cstr(raw, dst);
    }
    #[cfg(any(target_arch = "x86_64", target_arch = "x86"))]
    if s.len() >= 8 && std::arch::is_x86_feature_detected!("ssse3") { return latin1_ssse3(s, dst); }
    latin1_scalar_cstr(raw, dst)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn latin_blocks_all_masks_bytes_and_offsets() {
        let check = |input: &[u8], source_offset: usize, output_offset: usize, cap: usize| {
            let mut source = vec![b'!'; source_offset + input.len() + 1];
            source[source_offset..source_offset + input.len()].copy_from_slice(input);
            source[source_offset + input.len()] = 0;
            let mut expected = Vec::new(); latin1_to_utf8(input, &mut expected);
            let mut output = vec![std::mem::MaybeUninit::<u8>::uninit(); output_offset + cap + 16];
            for byte in &mut output[..output_offset] { byte.write(0x55); }
            for byte in &mut output[output_offset + cap..] { byte.write(0xaa); }
            let span = &source[source_offset..source_offset + input.len()];
            let n = unsafe { latin1_known_into(span, source.as_ptr().add(source_offset), output.as_mut_ptr().add(output_offset).cast(), cap) };
            assert_eq!(n, expected.len());
            if cap > n {
                let bytes = unsafe { std::slice::from_raw_parts(output.as_ptr().add(output_offset).cast::<u8>(), n + 1) };
                assert_eq!(&bytes[..n], expected); assert_eq!(bytes[n], 0);
            }
            if cap > 2 * input.len() {
                let n = unsafe { latin1_scalar_cstr(source.as_ptr().add(source_offset), output.as_mut_ptr().add(output_offset).cast()) };
                assert_eq!(n, expected.len());
                let bytes = unsafe { std::slice::from_raw_parts(output.as_ptr().add(output_offset).cast::<u8>(), n + 1) };
                assert_eq!(&bytes[..n], expected); assert_eq!(bytes[n], 0);
            }
            assert!(output[..output_offset].iter().all(|b| unsafe { b.assume_init() } == 0x55));
            assert!(output[output_offset + cap..].iter().all(|b| unsafe { b.assume_init() } == 0xaa));
            assert_eq!(&source[source_offset..source_offset + input.len()], input);
        };
        for bits in 0..256 {
            let input: Vec<u8> = (0..8).map(|i| if bits & (1 << i) == 0 { b'a' + i } else { 0x80 + 17 * i }).collect();
            for source_offset in 0..16 {
                for output_offset in 0..16 { check(&input, source_offset, output_offset, 17); }
            }
        }
        for len in [0, 1, 7, 8, 9, 15, 16, 17, 31, 32, 33] {
            for byte in 1..=255u8 {
                let input = vec![byte; len];
                let required = len * if byte < 0x80 { 1 } else { 2 };
                for cap in [0, required, required + 1, 2 * len + 1] { check(&input, 3, 5, cap); }
            }
        }
    }

    fn inplace(f: impl Fn(&mut [u8]) -> usize, s: &[u8]) -> Vec<u8> {
        let mut v = s.to_vec();
        let n = f(&mut v);
        v.truncate(n);
        v
    }

    #[test]
    fn decoders() {
        let xml_decode = |b: &mut [u8]| super::xml_decode(b, &|c| i32::from(c.to_ascii_lowercase()));
        assert_eq!(
            inplace(xml_decode, b"a&lt;b&gt;&amp;&apos;&quot;&#233;&#xe9;&nbsp;<![CDATA[&lt;]]>&"),
            "a<b>&'\"\u{e9}\u{e9}&nbsp;&lt;&".as_bytes()
        );
        assert_eq!(inplace(xml_decode, b"&#0;&#x110000;&#xd800;&#"), "\u{fffd}\u{fffd}\u{fffd}".as_bytes());
        assert_eq!(inplace(http_unquote, b"\"a\\\"b\\\\c\"rest"), b"a\"b\\c");
        assert_eq!(inplace(http_unquote, b"plain"), b"plain");
        assert_eq!(inplace(url_decode, b"a%20b%zz%4"), b"a b\0%4");
        assert_eq!(inplace(|b| xml_remove_entities(b, &|c| c.is_ascii_alphabetic()), b"x&amp;y&#12;z&nope"), b"x y z&nope");
        let mut v = b"a<b>c<d".to_vec();
        xml_strip_tags(&mut v);
        assert_eq!(v, b"a   c<d");
    }

    #[test]
    fn xml_numeric_references_use_locale_case_mapping() {
        // A custom LC_CTYPE can map A to b and leave C uppercase. The latter
        // yields a negative digit, which C++ adds to its unsigned accumulator.
        let lower = |c| if c == b'A' { i32::from(b'b') } else { i32::from(c) };
        assert_eq!(
            inplace(|b| xml_decode(b, &lower), b"&#xA;&#xa;&#xC;&#x1C;"),
            "\u{b}\u{a}\u{fffd}\u{fffd}".as_bytes()
        );
    }
}
