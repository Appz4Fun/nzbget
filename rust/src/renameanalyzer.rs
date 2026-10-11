//! DirectRenamer's RenameContentAnalyzer (DirectRenamer.cpp): the first
//! bytes of a downloaded file - whether it starts with a PAR2 packet (and its
//! set id) and the MD5 of its first 16 KiB - fed article by article, exactly
//! as the C++ did it (the packet header looked at once more than its 64 bytes
//! were read, Reset keeping what it found).

use md5::{Digest, Md5};

const HEADER: usize = 64;
const MAGIC: &[u8; 8] = b"PAR2\0PKT";
const LIMIT: i64 = 16 * 1024;

/// Par2::MD5Hash::print: the bytes from last to first, upper-case hex.
fn print(hash: &[u8]) -> String {
    hash.iter().rev().map(|b| format!("{b:02X}")).collect()
}

pub struct Analyzer {
    md5: Md5,
    signature: [u8; HEADER],
    pub(crate) data_size: i32,
    pub par_file: bool,
    pub par_set_id: Option<String>,
}

impl Default for Analyzer {
    fn default() -> Self {
        Analyzer { md5: Md5::new(), signature: [0; HEADER], data_size: 0, par_file: false, par_set_id: None }
    }
}

impl Analyzer {
    /// Reset: a new MD5 and size (what was found and the header bytes stay)
    pub fn reset(&mut self) {
        self.md5 = Md5::new();
        self.data_size = 0;
    }

    /// Append; true when it (re)recognized a PAR2 packet header
    pub fn append(&mut self, buf: &[u8]) -> bool {
        let len = buf.len() as i32;
        let size = self.data_size;
        // (size_t)m_dataSize: an overflowed (negative) size reads as huge
        if (size as usize) < HEADER {
            let n = buf.len().min(HEADER - size as usize);
            self.signature[size as usize..size as usize + n].copy_from_slice(&buf[..n]);
        }
        let mut matched = false;
        // checked against the size before this piece: a header read with the
        // first piece is recognized from the second on
        if size as usize >= HEADER && &self.signature[..8] == MAGIC {
            self.par_file = true;
            self.par_set_id = Some(print(&self.signature[32..48]));
            matched = true;
        }
        let rem = (len as i64).min(LIMIT - size as i64);
        if rem > 0 {
            self.md5.update(&buf[..rem as usize]);
        }
        self.data_size = self.data_size.wrapping_add(len);
        matched
    }

    /// Finish: the MD5 of the first 16 KiB, printed
    pub fn finish(&mut self) -> String {
        let hash = std::mem::replace(&mut self.md5, Md5::new()).finalize();
        print(&hash)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn par_header_and_hash() {
        let mut header = [0u8; 64];
        header[..8].copy_from_slice(MAGIC);
        for (i, b) in header[32..48].iter_mut().enumerate() {
            *b = i as u8;
        }
        let mut a = Analyzer::default();
        assert!(!a.append(&header));
        assert!(!a.par_file);
        assert!(a.append(b"more"));
        assert_eq!(a.par_set_id.as_deref(), Some("0F0E0D0C0B0A09080706050403020100"));
        let mut b = Analyzer::default();
        b.append(b"");
        // MD5("") = d41d8cd98f00b204e9800998ecf8427e, printed backwards
        assert_eq!(b.finish(), "7E42F8EC980980E904B2008FD98C1DD4");
    }
}
