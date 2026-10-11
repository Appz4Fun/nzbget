//! Ordered folding of little-endian CRC bytes in PAR2 verification entries.
//! Hashes, packet ownership, padding and file reads remain in C++.

use crate::crc;

fn required_len(stride: usize, count: usize) -> Option<usize> {
    if count == 0 {
        return Some(0);
    }
    if stride < 4 {
        return None;
    }
    (count - 1).checked_mul(stride)?.checked_add(4)
}

/// Fold CRCs starting at byte zero, `stride` bytes apart. The first CRC
/// initializes the accumulator directly, including when `blocksize` is zero.
pub fn fold(bytes: &[u8], stride: usize, count: usize, blocksize: u32) -> Option<u32> {
    if required_len(stride, count)? > bytes.len() {
        return None;
    }
    // The validated slice bounds every CRC read.
    Some(unsafe { fold_raw(bytes.as_ptr(), stride, count, blocksize) })
}

// Multiply a uniform CRC length operator by a CRC in the reflected polynomial.
// The operator is obtained through crc::combine, keeping its length semantics.
fn apply_operator(operator: u32, mut value: u32) -> u32 {
    if operator == 0 {
        return 0;
    }
    let mut mask = 1u32 << 31;
    let mut product = 0;
    loop {
        if operator & mask != 0 {
            product ^= value;
            if operator & (mask - 1) == 0 {
                break;
            }
        }
        mask >>= 1;
        value = (value >> 1) ^ if value & 1 != 0 { 0xedb8_8320 } else { 0 };
    }
    product
}

// Reads exactly the four CRC bytes per entry, allowing unreadable MD5 gaps
// in a foreign allocation and avoiding native-u32 alignment assumptions.
unsafe fn fold_raw(bytes: *const u8, stride: usize, count: usize, blocksize: u32) -> u32 {
    // CRC multiplication uses bit 31 as the identity. Asking the existing
    // primitive to combine it with zero yields x^(blocksize * 8) modulo POLY.
    let operator = if count > 1 && blocksize != 0 {
        crc::combine(1 << 31, 0, blocksize)
    } else {
        0
    };
    let mut result = 0;
    for i in 0..count {
        let block = u32::from_le_bytes(bytes.add(i * stride).cast::<[u8; 4]>().read_unaligned());
        result = if i == 0 {
            block
        } else if blocksize == 0 {
            result
        } else {
            apply_operator(operator, result) ^ block
        };
    }
    result
}

/// Fold packet CRCs with no allocation or native-u32 alignment assumption.
/// Returns 1 on success, 0 for an invalid descriptor; errors leave `out` untouched.
///
/// # Safety
/// For nonzero `count`, `bytes` must name one allocation containing at least
/// `(count - 1) * stride + 4` bytes. `len` bounds that span; each four-byte
/// CRC must be readable and initialized. Gaps need not be readable.
/// `out` must be a writable, aligned u32 disjoint from the input. No input
/// bytes are read except the four-byte little-endian CRC at each stride.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_parcrc_batch(
    bytes: *const u8,
    len: usize,
    stride: usize,
    count: usize,
    blocksize: u32,
    out: *mut u32,
) -> i32 {
    if out.is_null() || len > isize::MAX as usize {
        return 0;
    }
    let Some(required) = required_len(stride, count) else {
        return 0;
    };
    if required > len || (count != 0 && bytes.is_null()) {
        return 0;
    }
    let result = fold_raw(bytes, stride, count, blocksize);
    out.write(result);
    1
}
