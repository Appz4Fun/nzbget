//! Pure persisted dead-posting line parsing; C++ owns storage and locking.

unsafe extern "C" {
    #[link_name = "isspace"]
    fn c_isspace(value: std::ffi::c_int) -> std::ffi::c_int;
}

// strto* uses C-string termination, accepts leading space and a sign, and the
// caller ignores errno. Keep those rules without creating temporary C strings.
fn decimal(field: &[u8]) -> Option<(bool, u64, bool)> {
    if field.is_empty() { return None; }
    let text = field.split(|&b| b == 0).next()?;
    if text.is_empty() { return Some((false, 0, false)); }
    let mut i = 0;
    while let Some(&byte) = text.get(i) {
        // Decimal digits and signs are not locale whitespace. Avoid a libc call
        // on the normal saved format, while querying C's current LC_CTYPE for
        // every possible leading whitespace byte (including extended bytes).
        if byte.is_ascii_digit() || matches!(byte, b'+' | b'-') { break; }
        // ctype requires EOF or an unsigned-char value; u8 -> int is always valid.
        if unsafe { c_isspace(i32::from(byte)) } == 0 { break; }
        i += 1;
    }
    let negative = text.get(i) == Some(&b'-');
    if matches!(text.get(i), Some(b'+' | b'-')) { i += 1; }
    let start = i;
    let mut value = 0u64;
    let mut overflow = false;
    while let Some(&digit) = text.get(i) {
        if !digit.is_ascii_digit() { return None; }
        match value.checked_mul(10).and_then(|n| n.checked_add(u64::from(digit - b'0'))) {
            Some(n) => value = n,
            None => { value = u64::MAX; overflow = true; }
        }
        i += 1;
    }
    (i > start).then_some((negative, value, overflow))
}

/// Matches the two tab-delimited fields read by the C++ loader. Hashes are
/// converted with the target's unsigned-long width, then sorted and deduped.
/// `strtoll` overflow saturates, since the persisted C++ reader ignores errno.
pub fn parse_line(line: &[u8], ulong_bits: u32) -> Option<(i64, Vec<u32>)> {
    let tab = line.iter().position(|&b| b == b'\t')?;
    let (negative, magnitude, overflow) = decimal(&line[..tab])?;
    let limit = if negative { 1u64 << 63 } else { i64::MAX as u64 };
    let magnitude = if overflow { limit } else { magnitude.min(limit) };
    let stamp = if negative {
        if magnitude == 1u64 << 63 { i64::MIN } else { -(magnitude as i64) }
    } else { magnitude as i64 };
    let hashes = &line[tab + 1..];
    let hashes = hashes.split(|&b| b == b'\t').next()?;
    if hashes.is_empty() { return None; }
    let hashes = hashes.strip_suffix(b",").unwrap_or(hashes);
    let mut sketch = Vec::with_capacity(64);
    for field in hashes.split(|&b| b == b',') {
        let (negative, magnitude, overflow) = decimal(field)?;
        let max = if ulong_bits == 32 { u32::MAX as u64 } else { u64::MAX };
        let value = if overflow || magnitude > max { max }
            else if negative { magnitude.wrapping_neg() & max } else { magnitude };
        sketch.push(u32::try_from(value).ok()?);
    }
    sketch.sort_unstable();
    sketch.dedup();
    Some((stamp, sketch))
}

/// Parse one persisted line and visit its complete sorted sketch once.
///
/// # Safety
/// `data` must identify `len` readable bytes (or be null with zero length).
/// `visit` must not unwind and must use the borrowed sketch only during the
/// callback; `context` is passed through unchanged to that callback.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_deadpostings_parse(
    data: *const u8, len: usize, context: *mut std::ffi::c_void,
    visit: unsafe extern "C" fn(*mut std::ffi::c_void, i64, *const u32, usize),
) -> bool {
    let line = if len == 0 { &[] } else { unsafe { std::slice::from_raw_parts(data, len) } };
    let Some((stamp, sketch)) = parse_line(line, std::ffi::c_ulong::BITS) else { return false; };
    unsafe { visit(context, stamp, sketch.as_ptr(), sketch.len()); }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sorted_unique_and_trailing_delimiters() {
        assert_eq!(parse_line(b"123\t9,2,9,1,\tignored",64),Some((123,vec![1,2,9])));
        assert_eq!(parse_line(b"123\t7",64),Some((123,vec![7])));
    }
    #[test]
    fn signed_timestamp_and_leading_space() {
        assert_eq!(parse_line(b" \x0b-123\t +7,\t",64),Some((-123,vec![7])));
    }
    #[test]
    fn nul_terminates_numbers_not_fields() {
        assert_eq!(parse_line(b"123\0junk\t5\0junk,2\t",64),Some((123,vec![2,5])));
        assert_eq!(parse_line(b"\0\t\0\t",64),Some((0,vec![0])));
        assert_eq!(parse_line(b" \0\t1\t",64),None);
    }
    #[test]
    fn timestamp_overflow_saturates_like_strtoll() {
        assert_eq!(parse_line(b"99999999999999999999999\t1\t",64),Some((i64::MAX,vec![1])));
        assert_eq!(parse_line(b"-99999999999999999999999\t1\t",64),Some((i64::MIN,vec![1])));
    }
    #[test]
    fn signed_hash_and_ulong_width() {
        assert_eq!(parse_line(b"1\t-18446744073709551615\t",64),Some((1,vec![1])));
        assert_eq!(parse_line(b"1\t-1\t",64),None);
        assert_eq!(parse_line(b"1\t-1\t",32),Some((1,vec![u32::MAX])));
        assert_eq!(parse_line(b"1\t4294967296\t",32),Some((1,vec![u32::MAX])));
        assert_eq!(parse_line(b"1\t4294967296\t",64),None);
    }
    #[test]
    fn invalid_fields_reject_whole_record() {
        for line in [b"".as_slice(),b"1",b"1\t",b"1\t\t",b"\t1\t",b"+\t1\t",b"1 \t1\t",b"1\t1,x,2\t",b"1\t,1\t",b"1\t1,,2\t",b"1\t1 \t",b"1\t18446744073709551616\t"] {
            assert_eq!(parse_line(line,64),None,"{line:?}");
        }
    }
}
