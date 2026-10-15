//! DirectRenamer's RenameContentAnalyzer (DirectRenamer.cpp): the first
//! bytes of a downloaded file - whether it starts with a PAR2 packet (and its
//! set id) and the MD5 of its first 16 KiB - fed article by article. Recognize
//! the header on the piece that completes it, before QueueCoordinator reads
//! the PAR flag. Reset keeps the identity already found, as in C++.

use md5::{Digest, Md5};
use md5::block_api::Md5Core;
use md5::digest::{block_api::CoreProxy, common::hazmat::SerializableState};

const HEADER: usize = 64;
const MAGIC: &[u8; 8] = b"PAR2\0PKT";
const LIMIT: i32 = 16 * 1024;

/// Par2::MD5Hash::print: the bytes from last to first, upper-case hex.
pub(crate) fn print(hash: &[u8]) -> [u8; 33] {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = [0; 33];
    for (pair, b) in out[..32].as_chunks_mut::<2>().0.iter_mut().zip(hash.iter().rev()) {
        pair[0] = HEX[(b >> 4) as usize];
        pair[1] = HEX[(b & 15) as usize];
    }
    out
}

pub struct Analyzer {
    md5: Md5,
    signature: [u8; HEADER],
    data_size: i32,
    pub par_file: bool,
    pub par_set_id: Option<[u8; 33]>,
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
        let header_ready = if (size as usize) < HEADER {
            let n = buf.len().min(HEADER - size as usize);
            self.signature[size as usize..size as usize + n].copy_from_slice(&buf[..n]);
            size as usize + n == HEADER
        } else {
            true
        };
        let mut matched = false;
        if header_ready && &self.signature[..8] == MAGIC {
            self.par_file = true;
            self.par_set_id = Some(print(&self.signature[32..48]));
            matched = true;
        }
        // Match the legacy 32-bit arithmetic, including the subtraction after
        // the cumulative size wraps. Widening this subtraction changes hashing.
        let rem = len.min(LIMIT.wrapping_sub(size));
        if rem > 0 {
            self.md5.update(&buf[..rem as usize]);
        }
        self.data_size = self.data_size.wrapping_add(len);
        matched
    }

    /// Finish: the MD5 of the first 16 KiB, printed
    pub fn finish(&mut self) -> [u8; 33] {
        let hash = self.md5.clone().finalize();
        // Par2::MD5Context::Final replaces the chaining words with the digest,
        // but retains the byte count and buffered input. Neither finalize_reset
        // nor simply finalizing a clone preserves subsequent Finish/Append calls.
        // Md5Core serializes four little-endian words followed by its block count.
        let (core, buffer) = self.md5.clone().decompose();
        let mut state = core.serialize();
        state[..16].copy_from_slice(&hash);
        // libpar2 also byte-swaps its live state when printing on big endian.
        #[cfg(target_endian = "big")]
        for word in state[..16].as_chunks_mut::<4>().0 {
            word.reverse();
        }
        self.md5 = Md5::compose(Md5Core::deserialize(&state).expect("valid MD5 core state"), buffer);
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
        assert!(a.append(&header));
        assert!(a.par_file);
        assert!(a.append(b"more"));
        assert_eq!(a.par_set_id.as_ref(), Some(b"0F0E0D0C0B0A09080706050403020100\0"));
        let mut b = Analyzer::default();
        b.append(b"");
        // MD5("") = d41d8cd98f00b204e9800998ecf8427e, printed backwards
        assert_eq!(&b.finish(), b"7E42F8EC980980E904B2008FD98C1DD4\0");
    }

    #[test]
    fn size_wrap_keeps_legacy_md5_window() {
        let mut a = Analyzer { data_size: i32::MAX, ..Analyzer::default() };
        a.append(b"x");
        assert_eq!(a.data_size, i32::MIN);
        a.append(&[b'y'; 16 * 1024]);
        a.append(b"y");
        a.append(b"z");
        // The wrapped subtraction is negative through INT_MIN + 16384.
        assert_eq!(a.finish(), print(&Md5::digest(b"z")));
    }

    #[test]
    fn ffi_buffers_and_invalid_inputs() {
        use crate::ffi::*;
        use std::ptr::{null, null_mut};
        // Exercise the real ABI, including caller-owned buffers with canaries.
        unsafe {
            nzbget_rs_rename_analyzer_free(null_mut());
            nzbget_rs_rename_analyzer_reset(null_mut());
            nzbget_rs_rename_analyzer_finish(null_mut(), null_mut());
            assert_eq!(nzbget_rs_rename_analyzer_append(null_mut(), null(), 0, null_mut()), 0);
            let a = nzbget_rs_rename_analyzer_new();
            let mut out = [0x55u8; 35];
            let dest = out.as_mut_ptr().add(1).cast();
            assert_eq!(nzbget_rs_rename_analyzer_append(a, null(), 99, dest), 0);
            assert_eq!(nzbget_rs_rename_analyzer_append(a, null(), -1, dest), 0);
            assert_eq!(nzbget_rs_rename_analyzer_append(a, null(), 0, dest), 0);
            assert_eq!(out, [0x55; 35]);
            nzbget_rs_rename_analyzer_finish(a, null_mut());
            nzbget_rs_rename_analyzer_finish(a, dest);
            assert_eq!(&out[1..34], b"7E42F8EC980980E904B2008FD98C1DD4\0");
            assert_eq!((out[0], out[34]), (0x55, 0x55));

            nzbget_rs_rename_analyzer_reset(a);
            let mut header = [0u8; 64];
            header[..8].copy_from_slice(MAGIC);
            for (i, b) in header[32..48].iter_mut().enumerate() { *b = i as u8; }
            assert_eq!(nzbget_rs_rename_analyzer_append(a, header.as_ptr().cast(), 64, dest), 1);
            assert_eq!(nzbget_rs_rename_analyzer_append(a, null(), 0, null_mut()), 1);
            assert_eq!(nzbget_rs_rename_analyzer_append(a, null(), 0, dest), 1);
            assert_eq!(&out[1..34], b"0F0E0D0C0B0A09080706050403020100\0");
            assert_eq!((out[0], out[34]), (0x55, 0x55));
            nzbget_rs_rename_analyzer_reset(a);
            assert!((*a).par_file);
            assert_eq!((*a).par_set_id.as_ref().unwrap(), &out[1..34]);
            nzbget_rs_rename_analyzer_free(a);
        }
    }

    #[test]
    fn complete_par_header_is_recognized_in_its_first_piece() {
        for size in [HEADER, 2472] {
            let mut bytes=vec![0u8;size];bytes[..8].copy_from_slice(MAGIC);
            for (i,b) in bytes[32..48].iter_mut().enumerate() {*b=i as u8;}
            let mut a=Analyzer::default();
            assert!(a.append(&bytes), "complete PAR2 header in one piece must be visible immediately");
            assert!(a.par_file);
            assert_eq!(a.par_set_id.as_ref(),Some(b"0F0E0D0C0B0A09080706050403020100\0"));
            assert_eq!(a.finish(),print(&Md5::digest(&bytes)));
        }
    }

    #[test]
    fn split_header_is_recognized_when_the_last_header_byte_arrives() {
        let mut header=[0u8;HEADER];header[..8].copy_from_slice(MAGIC);
        for split in [HEADER-1,47] {
            let mut a=Analyzer::default();
            assert!(!a.append(&header[..split]));assert!(!a.par_file);
            assert!(a.append(&header[split..]));assert!(a.par_file);
            assert_eq!(a.finish(),print(&Md5::digest(header)));
        }
    }

    #[test]
    fn early_recognition_preserves_ffi_set_id_canaries() {
        use crate::ffi::*;
        let mut header=[0u8;HEADER];header[..8].copy_from_slice(MAGIC);
        for (i,b) in header[32..48].iter_mut().enumerate() {*b=i as u8;}
        unsafe {
            let a=nzbget_rs_rename_analyzer_new();
            let mut out=[0x55u8;35];
            assert_eq!(nzbget_rs_rename_analyzer_append(a,header.as_ptr().cast(),HEADER as i32,out.as_mut_ptr().add(1).cast()),1);
            assert_eq!(&out[1..34],b"0F0E0D0C0B0A09080706050403020100\0");
            assert_eq!((out[0],out[34]),(0x55,0x55));
            nzbget_rs_rename_analyzer_free(a);
        }
    }

    #[test]
    fn partial_or_nonpar_first_piece_remains_unrecognized() {
        let mut header=[0u8;HEADER];header[..8].copy_from_slice(MAGIC);
        for length in 0..HEADER {
            let mut a=Analyzer::default();assert!(!a.append(&header[..length]));assert!(!a.par_file);
        }
        let mut a=Analyzer::default();assert!(!a.append(&[b'x';2472]));assert!(!a.par_file);
    }
}
