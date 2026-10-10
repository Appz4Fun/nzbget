//! The article decoder (Decoder): finds yEnc or UU-encoded data in an
//! article as it arrives in pieces, decodes it into the caller's buffer and
//! checks it (sizes, CRC). yEnc bodies are decoded by rapidyenc (its decoder
//! and CRC functions are handed in). It matches the C++ Decoder, quirks
//! included: the line buffer appends as strncpy (a NUL ends the copied text
//! and the rest is zero-filled) and lines are found as strchr found them.

use std::ffi::{c_char, c_int, c_longlong, c_ulong, c_void, CStr, CString};

/// rapidyenc_decode_incremental: returns 0 (no end), 1 ("\r\n=y" found,
/// `src` after the 'y') or 2 ("\r\n.\r\n" found, `src` after it).
pub type DecodeFn = unsafe extern "C" fn(src: *mut *const c_void, dst: *mut *mut c_void, len: usize, state: *mut c_int) -> c_int;
/// rapidyenc_crc.
pub type CrcFn = unsafe extern "C" fn(src: *const c_void, len: usize, init: u32) -> u32;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Format {
    Unknown = 0,
    Yenc = 1,
    Ux = 2,
}

/// Check's results, as Decoder::EStatus.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Status {
    UnknownError = 0,
    Finished = 1,
    ArticleIncomplete = 2,
    CrcError = 3,
    InvalidSize = 4,
    NoBinaryData = 5,
}

/// StringBuilder as the decoder used it: `len` bytes count, the buffer
/// beyond them keeps what was there (strchr scans to the NUL Append wrote).
#[derive(Default)]
struct LineBuf {
    data: Vec<u8>,
    len: usize,
}

impl LineBuf {
    /// Append(str, len): strncpy, then a NUL after; a length of 0 means up to
    /// the NUL of `src` (it never is here: the caller passes the length).
    fn append(&mut self, src: &[u8]) {
        let end = self.len + src.len();
        if self.data.len() < end + 1 {
            self.data.resize(end + 1, 0);
        }
        let copy = src.iter().position(|&b| b == 0).unwrap_or(src.len());
        self.data[self.len..self.len + copy].copy_from_slice(&src[..copy]);
        self.data[self.len + copy..end].fill(0);
        self.data[end] = 0;
        self.len = end;
    }

    fn set_len(&mut self, len: usize) {
        self.len = len;
    }

    /// The C string at `at` (up to its NUL; Append keeps one at `len`).
    fn c_str_end(&self, at: usize) -> usize {
        let limit = self.data.len();
        self.data[at.min(limit)..].iter().position(|&b| b == 0).map_or(limit, |k| at + k)
    }
}

pub struct Decoder {
    decode_fn: DecodeFn,
    crc_fn: CrcFn,
    pub format: Format,
    begin: bool,
    part: bool,
    body: bool,
    end: bool,
    crc: bool,
    pub expected_crc: u32,
    pub calculated_crc: u32,
    pub begin_pos: i64,
    pub end_pos: i64,
    pub size: i64,
    end_size: i64,
    out_size: i64,
    pub eof: bool,
    pub crc_check: bool,
    state: c_int,
    pub raw_mode: bool,
    pub article_filename: Vec<u8>,
    /// the file name and a NUL, for GetArticleFilename
    filename_c: Vec<u8>,
    line_buf: LineBuf,
    crc32: u32,
}

// Use the same CRT as C++: whitespace follows the current C locale and
// strtoul overflow follows the platform's unsigned long width (LLP64 on Windows).
extern "C" {
    #[link_name = "atoll"]
    fn c_atoll(s: *const c_char) -> c_longlong;
    #[link_name = "strtoul"]
    fn c_strtoul(s: *const c_char, end: *mut *mut c_char, base: c_int) -> c_ulong;
}

fn number_string(s: &[u8]) -> CString {
    CString::new(&s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]).expect("NUL removed")
}

fn atoll(s: &[u8]) -> i64 {
    unsafe { c_atoll(number_string(s).as_ptr()) as i64 }
}

fn strtoul_hex(s: &[u8]) -> u32 {
    unsafe { c_strtoul(number_string(s).as_ptr(), std::ptr::null_mut(), 16) as u32 }
}

fn find(h: &[u8], n: &[u8]) -> Option<usize> {
    h.windows(n.len()).position(|w| w == n)
}

/// UU_DECODE_CHAR.
fn uu(c: u8) -> u8 {
    if c == b'`' {
        0
    } else {
        c.wrapping_sub(b' ') & 0o77
    }
}

impl Decoder {
    pub fn new(decode_fn: DecodeFn, crc_fn: CrcFn) -> Decoder {
        let mut d = Decoder {
            decode_fn,
            crc_fn,
            format: Format::Unknown,
            begin: false,
            part: false,
            body: false,
            end: false,
            crc: false,
            expected_crc: 0,
            calculated_crc: 0,
            begin_pos: 0,
            end_pos: 0,
            size: 0,
            end_size: 0,
            out_size: 0,
            eof: false,
            crc_check: false,
            state: 0,
            raw_mode: false,
            article_filename: Vec::new(),
            filename_c: vec![0],
            line_buf: LineBuf::default(),
            crc32: 0,
        };
        d.clear();
        d
    }

    /// Decoder::Clear (the format and raw mode stay, as in the C++).
    pub fn clear(&mut self) {
        self.article_filename.clear();
        self.body = false;
        self.begin = false;
        self.part = false;
        self.end = false;
        self.crc = false;
        self.eof = false;
        self.expected_crc = 0;
        self.crc32 = 0;
        self.begin_pos = 0;
        self.end_pos = 0;
        self.size = 0;
        self.end_size = 0;
        self.out_size = 0;
        self.state = 0;
        self.crc_check = false;
        if self.line_buf.data.len() < 1024 * 8 + 1 {
            self.line_buf.data.resize(1024 * 8 + 1, 0);
        }
        self.line_buf.set_len(0);
    }

    /// Decoder::DecodeBuffer: decodes `len` bytes of `buf`, writing the data
    /// to `buf` itself; returns its length.
    ///
    /// # Safety
    /// `buf` is non-null and readable for `len` bytes. In line mode, zero
    /// length means a NUL-terminated string (StringBuilder::Append's default).
    /// The allocation must also fit the decoded output: up to the input length
    /// plus 63 bytes for a pending UU line. Connection reserves 128 slack bytes.
    /// It must not alias this decoder's storage. Callbacks obey DecodeFn/CrcFn's
    /// contract and must not unwind. No Rust slice bounds the output to `len`.
    pub unsafe fn decode_buffer(&mut self, buf: *mut u8, len: usize) -> usize {
        if self.raw_mode {
            self.process_raw(std::slice::from_raw_parts(buf, len));
            return len;
        }
        let mut outlen = 0usize;
        if self.body && self.format == Format::Yenc {
            outlen = self.decode_yenc_from(buf, buf, len);
            if self.body {
                return outlen;
            }
        } else {
            let chunk = if len == 0 {
                CStr::from_ptr(buf.cast()).to_bytes()
            } else {
                std::slice::from_raw_parts(buf, len)
            };
            self.line_buf.append(chunk);
        }

        let mut line = 0usize;
        // strchr(line, '\n') stops at the first newline or NUL.
        while let Some(nl) = self.line_buf.data[line..].iter().position(|&b| b == 0 || b == b'\n').map(|k| line + k) {
            if self.line_buf.data[nl] == 0 {
                break;
            }
            let llen = nl - line + 1;
            let lb = &self.line_buf.data;
            if lb[line] == b'.' && lb.get(line + 1) == Some(&b'\r') {
                self.eof = true;
                self.line_buf.set_len(0);
                return outlen;
            }
            if self.format == Format::Unknown {
                self.format = detect_format(&self.line_buf.data[line..], llen);
            }
            if self.format == Format::Yenc {
                // Only control lines use strstr, which looked past the newline.
                // Ordinary lines must not scan/copy the whole remaining article.
                let text = &self.line_buf.data[line..];
                if text.starts_with(b"=ybegin ") || text.starts_with(b"=ypart ") || text.starts_with(b"=yend ") {
                    let cend = self.line_buf.c_str_end(line);
                    let full = self.line_buf.data[line..cend].to_vec();
                    self.process_yenc(&full, llen);
                }
                if self.body {
                    let rest_at = nl + 1;
                    let rest = self.line_buf.len - rest_at;
                    let src = self.line_buf.data.as_mut_ptr().add(rest_at);
                    outlen = self.decode_yenc_from(src, buf, rest);
                    if self.body {
                        self.line_buf.set_len(0);
                        return outlen;
                    }
                    line = 0;
                    continue;
                }
            } else if self.format == Format::Ux {
                // Only a begin line's filename parser scans past its newline.
                // Copying the entire remaining article per UU line is quadratic.
                let end = if self.line_buf.data[line..].starts_with(b"begin ") && !self.body {
                    self.line_buf.c_str_end(line) + 1
                } else {
                    (line + llen.max(63)).min(self.line_buf.data.len())
                };
                let text = self.line_buf.data[line..end].to_vec();
                outlen += self.decode_ux(&text, llen, buf.add(outlen));
            }
            line = nl + 1;
        }
        if self.line_buf.data.get(line).is_some_and(|&b| b != 0) {
            let rest = self.line_buf.len - line;
            self.line_buf.data.copy_within(line..line + rest, 0);
            self.line_buf.set_len(rest);
        } else {
            self.line_buf.set_len(0);
        }
        outlen
    }

    fn parse_ypart(&mut self, line: &[u8]) {
        self.part = true;
        self.body = true;
        if let Some(k) = find(line, b" begin=") {
            self.begin_pos = atoll(&line[k + 7..]);
        }
        if let Some(k) = find(line, b" end=") {
            self.end_pos = atoll(&line[k + 5..]);
        }
    }

    /// ParseName: the name after " name=" up to the line end, or to a
    /// "=ypart " on the same line (which is parsed, looking past the line as
    /// the C++ did). An empty name was CString(pb, 0): the rest of the C string.
    fn parse_name(&mut self, full: &[u8], len: usize, at: usize) {
        let pb = at + 6;
        let mut pe = pb;
        while pe < len && !matches!(full[pe], 0 | b'\n' | b'\r') {
            if pe + 7 <= len && &full[pe..pe + 7] == b"=ypart " {
                let rest = full[pe..].to_vec();
                self.parse_ypart(&rest);
                break;
            }
            pe += 1;
        }
        let name = if pe > pb { &full[pb..pe] } else { &full[pb.min(full.len())..] };
        let name = &name[..name.iter().position(|&b| b == 0).unwrap_or(name.len())];
        let mut out = Vec::new();
        crate::text::latin1_to_utf8(name, &mut out);
        self.article_filename = out;
    }

    fn process_yenc(&mut self, full: &[u8], len: usize) {
        let line = &full[..len.min(full.len())];
        let cs = full;
        if len >= 8 && line.starts_with(b"=ybegin ") {
            self.begin = true;
            if let Some(k) = find(cs, b" size=").filter(|&k| k + 6 < len) {
                self.size = atoll(&cs[k + 6..]);
            }
            self.part = find(cs, b" part=").is_some_and(|k| k < len);
            if !self.part {
                self.body = true;
                self.begin_pos = 1;
                self.end_pos = self.size;
            }
            if let Some(k) = find(cs, b" name=").filter(|&k| k + 6 < len) {
                self.parse_name(full, len, k);
            }
        } else if len >= 7 && line.starts_with(b"=ypart ") {
            self.parse_ypart(cs);
        } else if len >= 6 && line.starts_with(b"=yend ") {
            self.end = true;
            let (key, offset): (&[u8], usize) = if self.part { (b" pcrc32=", 8) } else { (b" crc32=", 7) };
            if let Some(k) = find(cs, key).filter(|&k| k + offset < len) {
                self.crc = true;
                self.expected_crc = strtoul_hex(&cs[k + offset..]);
            }
            if let Some(k) = find(cs, b" size=").filter(|&k| k + 6 < len) {
                self.end_size = atoll(&cs[k + 6..]);
            }
        }
    }

    /// DecodeYenc: rapidyenc from `src` to `out`; at the end of the yEnc data
    /// the rest goes back to the line buffer.
    unsafe fn decode_yenc_from(&mut self, src: *mut u8, out: *mut u8, len: usize) -> usize {
        let mut s = src as *const c_void;
        let mut d = out as *mut c_void;
        let endseq = (self.decode_fn)(&mut s, &mut d, len, &mut self.state);
        let written = d as usize - out as usize;
        if endseq != 0 {
            let consumed = s as usize - src as usize;
            let rest = if len > consumed { std::slice::from_raw_parts(s as *const u8, len - consumed).to_vec() } else { Vec::new() };
            self.line_buf.set_len(0);
            self.line_buf.append(if endseq == 1 { b"=y" } else { b".\r\n" });
            if !rest.is_empty() {
                self.line_buf.append(&rest);
            }
            self.body = false;
        }
        if self.crc_check {
            self.crc32 = (self.crc_fn)(out as *const c_void, written, self.crc32);
        }
        self.out_size += written as i64;
        written
    }

    /// DecodeUx for one line (`len` bytes of `line`, which goes on to its NUL).
    unsafe fn decode_ux(&mut self, line: &[u8], len: usize, out: *mut u8) -> usize {
        let at = |k: usize| *line.get(k).unwrap_or(&0);
        if !self.body {
            if line.starts_with(b"begin ") {
                let mut pb = 6;
                while !matches!(at(pb), b' ' | 0 | b'\n' | b'\r') {
                    pb += 1;
                }
                pb += 1;
                let mut pe = pb;
                while !matches!(at(pe), 0 | b'\n' | b'\r') {
                    pe += 1;
                }
                // an empty name was CString(pb, 0): the rest of the C string
                let name = if pe > pb { line.get(pb..pe).unwrap_or_default() } else { line.get(pb..).unwrap_or_default() };
                let name = &name[..name.iter().position(|&b| b == 0).unwrap_or(name.len())];
                let mut outn = Vec::new();
                crate::text::latin1_to_utf8(name, &mut outn);
                self.article_filename = outn;
                self.body = true;
                return 0;
            } else if (len == 62 || len == 63) && matches!(at(62), b'\n' | b'\r') && at(0) == b'M' {
                self.body = true;
            }
        }
        if self.body && (line.starts_with(b"end ") || at(0) == b'`') {
            self.end = true;
        }
        if self.body && !self.end {
            let eff = uu(at(0)) as usize;
            if eff > len {
                return 0;
            }
            // a line shorter than its length says: padded with spaces
            let mut data_len = len;
            while data_len > 0 && matches!(at(data_len - 1), b'\n' | b'\r') {
                data_len -= 1;
            }
            let need = 1 + 4 * eff.div_ceil(3);
            let mut padded = [b' '; 1 + 4 * 22];
            let src: Vec<u8> = if data_len < need {
                padded[..data_len].copy_from_slice(&line[..data_len]);
                padded.to_vec()
            } else {
                line[..len.max(need).min(line.len())].to_vec()
            };
            let g = |k: usize| uu(*src.get(k).unwrap_or(&0));
            let mut o = 0usize;
            let mut i = 1usize;
            let mut eff = eff as isize;
            while eff > 0 {
                if eff >= 3 {
                    *out.add(o) = g(i) << 2 | g(i + 1) >> 4;
                    *out.add(o + 1) = g(i + 1) << 4 | g(i + 2) >> 2;
                    *out.add(o + 2) = g(i + 2) << 6 | g(i + 3);
                    o += 3;
                } else {
                    *out.add(o) = g(i) << 2 | g(i + 1) >> 4;
                    o += 1;
                    if eff >= 2 {
                        *out.add(o) = g(i + 1) << 4 | g(i + 2) >> 2;
                        o += 1;
                    }
                }
                i += 4;
                eff -= 3;
            }
            return o;
        }
        0
    }

    fn process_raw(&mut self, b: &[u8]) {
        let len = b.len();
        self.eof = match self.state {
            1 => len >= 4 && b[..4] == *b"\n.\r\n",
            2 => len >= 3 && b[..3] == *b".\r\n",
            3 => len >= 2 && b[..2] == *b"\r\n",
            4 => len >= 1 && b[0] == b'\n',
            _ => self.eof,
        };
        self.eof |= find(b, b"\r\n.\r\n").is_some();
        self.state = if b.ends_with(b"\r\n.\r") {
            4
        } else if b.ends_with(b"\r\n.") {
            3
        } else if b.ends_with(b"\r\n") {
            2
        } else if b.ends_with(b"\r") {
            1
        } else {
            0
        };
    }

    /// GetArticleFilename: the name as a C string.
    pub fn filename_c(&mut self) -> *const u8 {
        if self.filename_c.len() != self.article_filename.len() + 1 || self.filename_c[..self.article_filename.len()] != self.article_filename[..] {
            self.filename_c = self.article_filename.clone();
            self.filename_c.push(0);
        }
        self.filename_c.as_ptr()
    }

    /// Decoder::Check.
    pub fn check(&mut self) -> Status {
        match self.format {
            Format::Yenc => {
                self.calculated_crc = self.crc32;
                if !self.begin {
                    Status::NoBinaryData
                } else if !self.end {
                    Status::ArticleIncomplete
                } else if (!self.part && self.size != self.end_size) || self.end_size != self.out_size {
                    Status::InvalidSize
                } else if self.crc_check && self.crc && self.expected_crc != self.calculated_crc {
                    Status::CrcError
                } else {
                    Status::Finished
                }
            }
            Format::Ux => if self.body { Status::Finished } else { Status::NoBinaryData },
            Format::Unknown => Status::UnknownError,
        }
    }
}

/// DetectFormat for a line (`len` bytes; the buffer goes on to its NUL).
fn detect_format(line: &[u8], len: usize) -> Format {
    let at = |k: usize| *line.get(k).unwrap_or(&0);
    if line.starts_with(b"=ybegin ") {
        return Format::Yenc;
    }
    if (len == 62 || len == 63) && matches!(at(62), b'\n' | b'\r') && at(0) == b'M' {
        return Format::Ux;
    }
    if line.starts_with(b"begin ") {
        let mut i = 6;
        while at(i) != 0 && at(i) != b' ' {
            if !(b'0'..=b'7').contains(&at(i)) {
                return Format::Unknown;
            }
            i += 1;
        }
        return Format::Ux;
    }
    Format::Unknown
}

#[cfg(test)]
mod tests {
    use super::*;

    unsafe extern "C" fn decode(src: *mut *const c_void, dst: *mut *mut c_void, len: usize, _state: *mut c_int) -> c_int {
        std::ptr::copy(*src as *const u8, *dst as *mut u8, len);
        *src = (*src).byte_add(len);
        *dst = (*dst).byte_add(len);
        0
    }

    unsafe extern "C" fn crc(_src: *const c_void, _len: usize, init: u32) -> u32 { init }

    #[test]
    fn raw_eof_state_zero_is_sticky() {
        let mut d = Decoder::new(decode, crc);
        d.process_raw(b"\r\n.\r\nx");
        d.process_raw(b"more");
        assert!(d.eof);
        d.process_raw(b"\r");
        assert!(d.eof);
        d.process_raw(b"x");
        assert!(!d.eof);
    }

    #[test]
    fn numeric_crt_overflow_and_sign() {
        assert_eq!(strtoul_hex(b"-10000000000000000"), u32::MAX);
        assert_eq!(strtoul_hex(b"-fffffffffffffffff"), u32::MAX);
        assert_eq!(strtoul_hex(b" \t-0x1\r\n"), u32::MAX);
        assert_eq!(strtoul_hex(b"100000000"), if std::mem::size_of::<c_ulong>() == 4 { u32::MAX } else { 0 });
        assert_eq!(atoll(b" \t\x0b-123rest"), -123);
    }

    #[test]
    fn ffi_nulls_and_zero_length_line() {
        use crate::ffi::*;
        use std::ptr::null_mut;
        unsafe {
            assert!(nzbget_rs_decoder_new(None, Some(crc)).is_null());
            assert!(nzbget_rs_decoder_new(Some(decode), None).is_null());
            nzbget_rs_decoder_clear(null_mut());
            nzbget_rs_decoder_set(null_mut(), 0, 1);
            assert_eq!(nzbget_rs_decoder_get(null_mut(), 0), 0);
            assert_eq!(nzbget_rs_decoder_check(null_mut()), Status::UnknownError as c_int);
            assert_eq!(CStr::from_ptr(nzbget_rs_decoder_filename(null_mut())).to_bytes(), b"");
            assert_eq!(nzbget_rs_decoder_decode(null_mut(), null_mut(), 1), 0);
            nzbget_rs_decoder_free(null_mut());
            let d = nzbget_rs_decoder_new(Some(decode), Some(crc));
            for len in [-1, 0, 10] {
                assert_eq!(nzbget_rs_decoder_decode(d, null_mut(), len), 0);
            }
            let mut b = [0u8; 256];
            let input = b"begin 644 x\r\n#04)#\r\n`\r\n\0";
            b[..input.len()].copy_from_slice(input);
            assert_eq!(nzbget_rs_decoder_decode(d, b.as_mut_ptr().cast(), 0), 3);
            assert_eq!(&b[..3], b"ABC");
            nzbget_rs_decoder_free(d);
        }
    }
}
