//! Decoders for RPC requests (WebUtil::DecodeBase64, ...). Each matches the
//! C++ code it replaces byte for byte, quirks included.

/// The C++ BASE64_DEALPHABET, verbatim: '=' maps to 61, other non-alphabet
/// bytes to 0.
const DEALPHABET: [u8; 128] = {
    let mut t = [0u8; 128];
    let mut i = 0;
    while i < 26 {
        t[b'A' as usize + i] = i as u8;
        t[b'a' as usize + i] = 26 + i as u8;
        i += 1;
    }
    let mut d = 0;
    while d < 10 {
        t[b'0' as usize + d] = 52 + d as u8;
        d += 1;
    }
    t[b'+' as usize] = 62;
    t[b'/' as usize] = 63;
    t[b'=' as usize] = 61;
    t
};

/// Sextet of an alphabet byte other than '=', or 0x80: the fast path's table.
const FAST: [u8; 256] = {
    let mut t = [0x80u8; 256];
    let mut i = 0;
    while i < 128 {
        if DEALPHABET[i] != 0 || i == b'A' as usize {
            t[i] = DEALPHABET[i];
        }
        i += 1;
    }
    t[b'=' as usize] = 0x80;
    t
};

#[inline]
fn is_b64(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'+' || c == b'/' || c == b'='
}

/// Decodes the quartet `q` into `out`, as the C++ DecodeByteQuartet; returns
/// the number of bytes written (1, 2 or 3).
#[inline]
fn quartet(q: [u8; 4], out: &mut [u8; 3]) -> usize {
    let v = |c: u8| DEALPHABET[c as usize] as u32;
    if q[3] == b'=' {
        if q[2] == b'=' {
            let b = ((v(q[0]) << 6 | v(q[1])) << 6) << 14;
            out[0] = (b >> 24) as u8;
            1
        } else {
            let b = (((v(q[0]) << 6 | v(q[1])) << 6 | v(q[2])) << 6) << 8;
            out[0] = (b >> 24) as u8;
            out[1] = (b >> 16) as u8;
            2
        }
    } else {
        let b = ((((v(q[0]) << 6 | v(q[1])) << 6 | v(q[2])) << 6 | v(q[3])) << 6) << 2;
        out[0] = (b >> 24) as u8;
        out[1] = (b >> 16) as u8;
        out[2] = (b >> 8) as u8;
        3
    }
}

/// Base64-decodes `len` bytes at `input` into `output`, skipping bytes outside
/// the alphabet; an incomplete last quartet is dropped. `output` may be
/// `input` (in place): output never passes the input already read.
/// Returns the number of bytes written.
///
/// # Safety
/// `input` is readable for `len` bytes; `output` is writable for `len / 4 * 3`
/// bytes and is either `input` or doesn't overlap it.
pub unsafe fn base64_in_place(input: *const u8, len: usize, output: *mut u8) -> usize {
    let mut q = [0u8; 4];
    let mut n = 0;
    let mut o = 0;
    let mut i = 0;
    // whole quartets of alphabet bytes without '=' take the fast path; any
    // other byte goes through the C++-exact handling
    while i < len {
        if n == 0 && i + 4 <= len {
            let (a, b, c, d) = (
                FAST[*input.add(i) as usize],
                FAST[*input.add(i + 1) as usize],
                FAST[*input.add(i + 2) as usize],
                FAST[*input.add(i + 3) as usize],
            );
            if (a | b | c | d) & 0x80 == 0 {
                let w = (a as u32) << 18 | (b as u32) << 12 | (c as u32) << 6 | d as u32;
                *output.add(o) = (w >> 16) as u8;
                *output.add(o + 1) = (w >> 8) as u8;
                *output.add(o + 2) = w as u8;
                o += 3;
                i += 4;
                continue;
            }
        }
        let c = *input.add(i);
        i += 1;
        if is_b64(c) {
            q[n] = c;
            n += 1;
            if n == 4 {
                let mut out = [0u8; 3];
                let k = quartet(q, &mut out);
                for (j, &b) in out[..k].iter().enumerate() {
                    *output.add(o + j) = b;
                }
                o += k;
                n = 0;
            }
        }
    }
    o
}

/// Index of the first `a` or `b` in `s`, testing eight bytes per step.
#[inline]
fn find2(s: &[u8], a: u8, b: u8) -> Option<usize> {
    const LO: u64 = 0x0101_0101_0101_0101;
    const HI: u64 = 0x8080_8080_8080_8080;
    let (ma, mb) = (LO * a as u64, LO * b as u64);
    let has_zero = |v: u64| v.wrapping_sub(LO) & !v & HI;
    let mut i = 0;
    while i + 8 <= s.len() {
        let w = u64::from_le_bytes(s[i..i + 8].try_into().unwrap());
        if has_zero(w ^ ma) | has_zero(w ^ mb) != 0 {
            break;
        }
        i += 8;
    }
    s[i..].iter().position(|&c| c == a || c == b).map(|k| i + k)
}

/// A code point as UTF-8, as the C++ AppendUtf8: NUL, a surrogate or a value
/// past Unicode becomes U+FFFD. Returns the number of bytes.
fn utf8(code: u32, out: &mut [u8; 4]) -> usize {
    let code = if code == 0 || code > 0x10ffff || (0xd800..=0xdfff).contains(&code) { 0xfffd } else { code };
    if code < 0x80 {
        out[0] = code as u8;
        1
    } else if code < 0x800 {
        out[0] = 0xc0 | (code >> 6) as u8;
        out[1] = 0x80 | (code & 0x3f) as u8;
        2
    } else if code < 0x10000 {
        out[0] = 0xe0 | (code >> 12) as u8;
        out[1] = 0x80 | ((code >> 6) & 0x3f) as u8;
        out[2] = 0x80 | (code & 0x3f) as u8;
        3
    } else {
        out[0] = 0xf0 | (code >> 18) as u8;
        out[1] = 0x80 | ((code >> 12) & 0x3f) as u8;
        out[2] = 0x80 | ((code >> 6) & 0x3f) as u8;
        out[3] = 0x80 | (code & 0x3f) as u8;
        4
    }
}

/// Four hex digits at `s[i..]`, or None (as the C++ Hex4: it stops at the
/// first byte that isn't one, the end included).
fn hex4(s: &[u8], i: usize) -> Option<u32> {
    let mut code = 0;
    for k in 0..4 {
        let d = (*s.get(i + k)? as char).to_digit(16)?;
        code = code * 16 + d;
    }
    Some(code)
}

/// Decodes a JSON string body in place (WebUtil::JsonDecode); `buf` is the text
/// up to its NUL. Returns the decoded length: the output never grows.
pub fn json_decode(buf: &mut [u8]) -> usize {
    let len = buf.len();
    let (mut p, mut o) = (0, 0);
    loop {
        // copy the run up to the next backslash in one go
        let run = find2(&buf[p..], b'\\', b'\\').unwrap_or(len - p);
        buf.copy_within(p..p + run, o);
        p += run;
        o += run;
        if p >= len {
            return o;
        }
        p += 1; // the backslash
        if p >= len {
            return o;
        }
        let put = |b: u8, o: &mut usize, buf: &mut [u8]| {
            buf[*o] = b;
            *o += 1;
        };
        match buf[p] {
            b'"' => put(b'"', &mut o, buf),
            b'\\' => put(b'\\', &mut o, buf),
            b'/' => put(b'/', &mut o, buf),
            b'b' => put(0x08, &mut o, buf),
            b'f' => put(0x0c, &mut o, buf),
            b'n' => put(b'\n', &mut o, buf),
            b'r' => put(b'\r', &mut o, buf),
            b't' => put(b'\t', &mut o, buf),
            b'u' => match hex4(buf, p + 1) {
                None => {
                    // not four hex digits: skip what is there of them
                    while p + 1 < len && buf[p + 1].is_ascii_hexdigit() {
                        p += 1;
                    }
                }
                Some(mut code) => {
                    p += 4;
                    if (0xd800..=0xdbff).contains(&code) && buf.get(p + 1) == Some(&b'\\') && buf.get(p + 2) == Some(&b'u') {
                        if let Some(low) = hex4(buf, p + 3) {
                            if (0xdc00..=0xdfff).contains(&low) {
                                code = 0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00);
                                p += 6;
                            }
                        }
                    }
                    let mut u = [0u8; 4];
                    let n = utf8(code, &mut u);
                    buf[o..o + n].copy_from_slice(&u[..n]);
                    o += n;
                }
            },
            c => put(c, &mut o, buf),
        }
        p += 1;
    }
}

/// The next JSON value in `s` (WebUtil::JsonNextValue): skips separators, then
/// takes a string (with its quotes; unterminated: to the end) or a bare token.
/// Returns (start, length), or None at the end or for a backslash that the
/// text ends in or right after.
pub fn json_next_value(s: &[u8]) -> Option<(usize, usize)> {
    let start = s.iter().position(|b| !b" ,[{:\r\n\t\x0c".contains(b))?;
    let mut e = start;
    if s[start] == b'"' {
        e += 1;
        loop {
            // jump to the next quote or backslash
            match find2(&s[e..], b'"', b'\\') {
                None => return Some((start, s.len() - start)),
                Some(k) => e += k,
            }
            if s[e] == b'"' {
                return Some((start, e + 1 - start));
            }
            // the C++ code steps over the backslash and the byte after it and
            // gives up unless a byte follows both
            if e + 2 >= s.len() {
                return None;
            }
            e += 2;
        }
    }
    let end = s[e..].iter().position(|b| b" ,]}\r\n\t\x0c".contains(b)).map_or(s.len(), |k| e + k);
    Some((start, end - start))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b64(s: &[u8]) -> Vec<u8> {
        let mut out = vec![0u8; s.len()];
        let n = unsafe { base64_in_place(s.as_ptr(), s.len(), out.as_mut_ptr()) };
        out.truncate(n);
        out
    }

    #[test]
    fn base64() {
        assert_eq!(b64(b"aGVsbG8gd29ybGQ="), b"hello world");
        assert_eq!(b64(b"aGVs\nbG8=\r\n"), b"hello");
        assert_eq!(b64(b"YQ=="), b"a");
        assert_eq!(b64(b"YWI="), b"ab");
        assert_eq!(b64(b"YWJj"), b"abc");
        assert_eq!(b64(b"YWJ"), b"");
        // in place
        let mut v = b"aGVsbG8gd29ybGQh".to_vec();
        let n = unsafe { base64_in_place(v.as_ptr(), v.len(), v.as_mut_ptr()) };
        assert_eq!(&v[..n], b"hello world!");
    }
}
