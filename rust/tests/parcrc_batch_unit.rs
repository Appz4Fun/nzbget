use nzbget_rs::parcrc_batch::{fold, nzbget_rs_parcrc_batch};

fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &byte in bytes {
        crc ^= u32::from(byte);
        for _ in 0..8 {
            crc = (crc >> 1) ^ if crc & 1 != 0 { 0xedb8_8320 } else { 0 };
        }
    }
    !crc
}

#[test]
fn empty_one_and_zero_length() {
    assert_eq!(fold(&[], 20, 0, 512), Some(0));
    assert_eq!(
        fold(&[0x78, 0x56, 0x34, 0x12], 20, 1, 512),
        Some(0x1234_5678)
    );
    let two = [0x78, 0x56, 0x34, 0x12, 0xef, 0xcd, 0xab, 0x90];
    assert_eq!(fold(&two, 4, 2, 0), Some(0x1234_5678));
}

#[test]
fn concatenated_bytes_and_padding() {
    // Catches reversed folding, CRC endianness and incorrect block lengths.
    for size in [1usize, 4, 17, 512, 716800] {
        for count in [1usize, 2, 7] {
            let mut whole = Vec::new();
            let mut entries = vec![0xa5; count * 20 + 1];
            for block in 0..count {
                let mut data: Vec<u8> = (0..size).map(|i| (i * 7 + block * 13) as u8).collect();
                if block == count - 1 {
                    data[size / 2..].fill(0);
                }
                entries[1 + block * 20..5 + block * 20]
                    .copy_from_slice(&crc32(&data).to_le_bytes());
                whole.extend(data);
            }
            assert_eq!(
                fold(&entries[1..], 20, count, size as u32),
                Some(crc32(&whole))
            );
        }
    }
}

#[test]
fn bounds_reject_before_read() {
    let bytes = [0u8; 24];
    assert_eq!(fold(&bytes, 3, 2, 512), None);
    assert_eq!(fold(&bytes, 20, 3, 512), None);
    assert_eq!(fold(&bytes, usize::MAX, 2, 512), None);
    assert_eq!(fold(&bytes, 20, usize::MAX, 512), None);
}

#[test]
fn abi_null_short_and_overflow_preserve_output() {
    let bytes = [0x78, 0x56, 0x34, 0x12];
    let mut out = 0xfeed_face;
    unsafe {
        assert_eq!(
            nzbget_rs_parcrc_batch(std::ptr::null(), 0, 20, 0, 512, &mut out),
            1
        );
        assert_eq!(out, 0);
        assert_eq!(
            nzbget_rs_parcrc_batch(bytes.as_ptr(), 4, 20, 1, 512, &mut out),
            1
        );
        assert_eq!(out, 0x1234_5678);
        for (ptr, len, stride, count) in [
            (std::ptr::null(), 4, 20, 1),
            (bytes.as_ptr(), 3, 20, 1),
            (bytes.as_ptr(), 4, 3, 1),
            (bytes.as_ptr(), 4, usize::MAX, 2),
            (bytes.as_ptr(), usize::MAX, 4, 1),
            (bytes.as_ptr(), 4, 20, usize::MAX),
        ] {
            assert_eq!(
                nzbget_rs_parcrc_batch(ptr, len, stride, count, 512, &mut out),
                0
            );
            assert_eq!(out, 0x1234_5678);
        }
        assert_eq!(
            nzbget_rs_parcrc_batch(bytes.as_ptr(), 4, 4, 1, 512, std::ptr::null_mut()),
            0
        );
    }
}
