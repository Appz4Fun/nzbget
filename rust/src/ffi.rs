//! C ABI. Strings come in as NUL-terminated C strings; results go out as a
//! buffer the caller copies and then frees with nzbget_rs_free.

use std::ffi::{c_char, c_int, CStr};

#[repr(C)]
pub struct RsBuf {
    pub data: *mut c_char,
    pub len: usize,
    cap: usize,
}

fn into_buf(mut v: Vec<u8>) -> RsBuf {
    v.push(0);
    let len = v.len() - 1;
    let mut v = std::mem::ManuallyDrop::new(v);
    RsBuf { data: v.as_mut_ptr() as *mut c_char, len, cap: v.capacity() }
}

unsafe fn input<'a>(raw: *const c_char) -> &'a [u8] {
    if raw.is_null() { &[] } else { CStr::from_ptr(raw).to_bytes() }
}

/// # Safety
/// `raw` is null or a valid NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_json_encode(raw: *const c_char) -> RsBuf {
    let mut v = Vec::new();
    crate::escape::json_encode(input(raw), &mut v);
    into_buf(v)
}

/// # Safety
/// `raw` is null or a valid NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_encode(raw: *const c_char) -> RsBuf {
    let mut v = Vec::new();
    crate::escape::xml_encode(input(raw), &mut v);
    into_buf(v)
}

/// # Safety
/// `buf` came from an nzbget_rs_* function and wasn't freed yet.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_free(buf: RsBuf) {
    if !buf.data.is_null() {
        drop(Vec::from_raw_parts(buf.data as *mut u8, buf.len + 1, buf.cap));
    }
}

/// Both fields are meaningful on failure, too: the legacy matcher retains
/// partial captures. Count can exceed capacity after backtracking.
#[repr(C)]
pub struct WildResult {
    pub matched: c_int,
    pub count: usize,
}

/// Match, folding case with glibc's tolower table `table` (indexed -128..=255)
/// when it isn't null, else with the caller's `fold` (tolower of a byte in the
/// current locale). Writes up to capacity
/// pairs and returns the total count; retry with that capacity if needed.
/// NULL positions disables capture collection, irrespective of capacity.
///
/// # Safety
/// `pattern` and `text` are null (empty) or valid NUL-terminated strings.
/// `table` is null or valid for indexes -128..=255 (`char_signed`: whether the
/// caller's char is signed, which picks the index of bytes from 0x80); `fold`,
/// when supplied, takes a byte value 0..=255 and must not unwind. A null `fold`
/// is ignored when a table is supplied; with neither, the result is (0, 0).
/// `positions` is null or points to
/// `capacity` writable pairs of C ints, disjoint from all the input storage.
/// All buffers remain caller-owned. Panics abort rather than crossing the ABI.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_wild_match(
    pattern: *const c_char,
    text: *const c_char,
    positions: *mut [c_int; 2],
    capacity: usize,
    table: *const c_int,
    char_signed: c_int,
    fold: Option<extern "C" fn(c_int) -> c_int>,
) -> WildResult {
    if table.is_null() && fold.is_none() {
        return WildResult { matched: 0, count: 0 };
    }
    let call = |b: u8| fold.expect("callback checked above")(b as c_int);
    let lower = if table.is_null() {
        crate::wildmask::Lower::Fold(&call)
    } else {
        // SAFETY: the caller supplies entries -128..=255, with `table`
        // pointing at entry zero. Keep raw-pointer handling at the FFI edge.
        crate::wildmask::Lower::Table(&*table.sub(128).cast::<[c_int; 384]>(), char_signed != 0)
    };
    let mut v = Vec::new();
    let matched = crate::wildmask::wild_match(
        &lower, input(pattern), input(text),
        if positions.is_null() { None } else { Some(&mut v) },
    );
    let count = v.len();
    // Avoid even constructing a slice from NULL for zero-length output.
    if !positions.is_null() && capacity != 0 && count != 0 {
        let out = std::slice::from_raw_parts_mut(positions, count.min(capacity));
        for (slot, (start, len)) in out.iter_mut().zip(v) {
            *slot = [start, len];
        }
    }
    WildResult { matched: matched.into(), count }
}

/// Base64-decodes `input` into `output` (WebUtil::DecodeBase64); a length of
/// 0 or less means up to the NUL, with the legacy uint32 length truncation.
/// `output` may be `input`.
///
/// # Safety
/// `input` is null or readable for its length (or through its NUL). Null input
/// returns zero without accessing output. Otherwise `output` is writable for
/// `len / 4 * 3` bytes and is `input` or doesn't overlap it. No terminator is
/// written. Both buffers remain caller-owned.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_decode_base64(input: *const c_char, length: c_int, output: *mut c_char) -> u32 {
    if input.is_null() {
        return 0;
    }
    // C++ stores strlen's result in uint32 before reading any quartets.
    let len = if length > 0 { length as usize } else { CStr::from_ptr(input).to_bytes().len() as u32 as usize };
    crate::decode::base64_in_place(input.cast(), len, output.cast()) as u32
}

/// Decodes a JSON string body in place (WebUtil::JsonDecode).
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_json_decode(raw: *mut c_char) {
    if raw.is_null() {
        return;
    }
    let len = CStr::from_ptr(raw).to_bytes().len();
    let buf = std::slice::from_raw_parts_mut(raw.cast::<u8>(), len);
    let n = crate::decode::json_decode(buf);
    *raw.add(n) = 0;
}

/// The next JSON value in `text` (WebUtil::JsonNextValue): its start, with
/// its length in `value_length`, or null.
///
/// # Safety
/// `text` is null or a NUL-terminated string; `value_length` is null or
/// writable.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_json_next_value(text: *const c_char, value_length: *mut c_int) -> *const c_char {
    if text.is_null() || value_length.is_null() {
        return std::ptr::null();
    }
    match crate::decode::json_next_value(CStr::from_ptr(text).to_bytes()) {
        Some((start, len)) => {
            *value_length = len as c_int;
            text.add(start)
        }
        None => std::ptr::null(),
    }
}

/// Crc32::Combine: the CRC of A then B from CRC(A), CRC(B) and B's length.
#[no_mangle]
pub extern "C" fn nzbget_rs_crc32_combine(crc1: u32, crc2: u32, len2: u32) -> u32 {
    crate::crc::combine(crc1, crc2, len2)
}

/// Runs an in-place text helper on the NUL-terminated `raw` and puts the NUL
/// at the new end.
unsafe fn in_place(raw: *mut c_char, f: impl FnOnce(&mut [u8]) -> usize) {
    if raw.is_null() {
        return;
    }
    let len = CStr::from_ptr(raw).to_bytes().len();
    let n = f(std::slice::from_raw_parts_mut(raw.cast::<u8>(), len));
    *raw.add(n) = 0;
}

/// WebUtil::XmlDecode, in place (rust/src/text.rs).
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_decode(raw: *mut c_char) {
    in_place(raw, crate::text::xml_decode)
}

/// WebUtil::XmlStripTags, in place.
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_strip_tags(raw: *mut c_char) {
    in_place(raw, |b| {
        crate::text::xml_strip_tags(b);
        b.len()
    })
}

/// WebUtil::XmlRemoveEntities, in place; `is_alpha` is isalpha of the
/// current locale for a byte from 0x80, given as the C++ char would be.
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string; `is_alpha` doesn't unwind.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_remove_entities(raw: *mut c_char, is_alpha: extern "C" fn(c_int) -> c_int) {
    in_place(raw, |b| crate::text::xml_remove_entities(b, &|c| is_alpha(c as c_int) != 0))
}

/// WebUtil::HttpUnquote, in place.
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_http_unquote(raw: *mut c_char) {
    in_place(raw, crate::text::http_unquote)
}

/// WebUtil::UrlDecode, in place.
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_url_decode(raw: *mut c_char) {
    in_place(raw, crate::text::url_decode)
}

/// WebUtil::UrlEncode; free the result with nzbget_rs_free.
///
/// # Safety
/// `raw` is null or a NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_url_encode(raw: *const c_char) -> RsBuf {
    let mut v = Vec::new();
    crate::text::url_encode(input(raw), &mut v);
    into_buf(v)
}

/// WebUtil::Latin1ToUtf8; free the result with nzbget_rs_free.
///
/// # Safety
/// `raw` is null or a NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_latin1_to_utf8(raw: *const c_char) -> RsBuf {
    let mut v = Vec::new();
    crate::text::latin1_to_utf8(input(raw), &mut v);
    into_buf(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decoder_null_arguments_and_failed_value_preserve_length() {
        unsafe {
            assert_eq!(nzbget_rs_decode_base64(std::ptr::null(), 4, std::ptr::null_mut()), 0);
            nzbget_rs_json_decode(std::ptr::null_mut());
            let mut length = -7;
            for text in [std::ptr::null(), b"\0".as_ptr().cast(), b"\"x\\a\0".as_ptr().cast()] {
                assert!(nzbget_rs_json_next_value(text, &mut length).is_null());
                assert_eq!(length, -7);
            }
            assert!(nzbget_rs_json_next_value(b"123\0".as_ptr().cast(), std::ptr::null_mut()).is_null());
        }
    }

    #[test]
    fn decoder_in_place_buffers_and_borrowed_value_pointer() {
        unsafe {
            let mut base64 = *b"YWJj\0YQ==!";
            let ptr = base64.as_mut_ptr().cast();
            assert_eq!(nzbget_rs_decode_base64(ptr, 9, ptr), 4);
            assert_eq!(&base64, b"abca\0YQ==!");

            let mut json = *b"\\ud83d\\ude00\\u0000\0!";
            nzbget_rs_json_decode(json.as_mut_ptr().cast());
            assert_eq!(&json[..8], b"\xf0\x9f\x98\x80\xef\xbf\xbd\0");
            assert_eq!(json[19], b'!');

            let text = b" ,\"x\\\"y\", rest\0";
            let mut length = -7;
            assert_eq!(nzbget_rs_json_next_value(text.as_ptr().cast(), &mut length), text.as_ptr().add(2).cast());
            assert_eq!(length, 6);
        }
    }

    extern "C" fn lower(b: c_int) -> c_int {
        (b as u8).to_ascii_lowercase() as c_int
    }

    #[test]
    fn wildcard_null_callback() {
        let mut table = [0; 384];
        for (i, slot) in table.iter_mut().enumerate() {
            *slot = lower((i as c_int - 128) as u8 as c_int);
        }
        let mut positions = [[-99; 2]; 2];
        unsafe {
            let result = nzbget_rs_wild_match(
                b"A?\0".as_ptr().cast(), b"ab\0".as_ptr().cast(),
                positions.as_mut_ptr(), positions.len(), table.as_ptr().add(128), 1, None,
            );
            assert_eq!((result.matched, result.count), (1, 1));
            assert_eq!(positions, [[1, 1], [-99; 2]]);
            let result = nzbget_rs_wild_match(
                b"A?\0".as_ptr().cast(), b"ab\0".as_ptr().cast(),
                positions.as_mut_ptr(), positions.len(), std::ptr::null(), 1, None,
            );
            assert_eq!((result.matched, result.count), (0, 0));
            assert_eq!(positions, [[1, 1], [-99; 2]]);
        }
    }

    #[test]
    fn wildcard_null_inputs_and_output() {
        unsafe {
            let result = nzbget_rs_wild_match(
                std::ptr::null(), std::ptr::null(), std::ptr::null_mut(), usize::MAX, std::ptr::null(), 1, Some(lower),
            );
            assert_eq!((result.matched, result.count), (1, 0));
            let result = nzbget_rs_wild_match(
                b"?\0".as_ptr().cast(), std::ptr::null(), std::ptr::null_mut(), 0, std::ptr::null(), 1, Some(lower),
            );
            assert_eq!((result.matched, result.count), (0, 0));
        }
    }

    #[test]
    fn wildcard_failure_preserves_partial_positions() {
        let mut positions = [[-99; 2]; 3];
        unsafe {
            let result = nzbget_rs_wild_match(
                b"?x\0".as_ptr().cast(), b"ay\0".as_ptr().cast(),
                positions.as_mut_ptr(), positions.len(), std::ptr::null(), 1, Some(lower),
            );
            assert_eq!((result.matched, result.count), (0, 1));
            assert_eq!(positions, [[0, 1], [-99; 2], [-99; 2]]);
        }
    }

    #[test]
    fn wildcard_reports_untruncated_count_without_overwriting_capacity() {
        let mut positions = [[-99; 2]; 2];
        unsafe {
            let result = nzbget_rs_wild_match(
                b"*?ab\0".as_ptr().cast(), b"aaaaaaaaab\0".as_ptr().cast(),
                positions.as_mut_ptr(), 1, std::ptr::null(), 1, Some(lower),
            );
            assert_eq!(result.matched, 1);
            assert!(result.count > 5);
            assert_eq!(positions[1], [-99; 2]);
            let mut full = vec![[0; 2]; result.count];
            let retried = nzbget_rs_wild_match(
                b"*?ab\0".as_ptr().cast(), b"aaaaaaaaab\0".as_ptr().cast(),
                full.as_mut_ptr(), full.len(), std::ptr::null(), 1, Some(lower),
            );
            assert_eq!((retried.matched, retried.count), (1, result.count));
            assert_eq!(full[0], positions[0]);
            let zero = nzbget_rs_wild_match(
                b"*?ab\0".as_ptr().cast(), b"aaaaaaaaab\0".as_ptr().cast(),
                positions.as_mut_ptr(), 0, std::ptr::null(), 1, Some(lower),
            );
            assert_eq!(zero.count, result.count);
            assert_eq!(positions[1], [-99; 2]);
        }
    }

    type Encoder = unsafe extern "C" fn(*const c_char) -> RsBuf;

    fn check(encode: Encoder, input: *const c_char, expected: &[u8]) {
        unsafe {
            let buf = encode(input);
            assert!(!buf.data.is_null());
            assert_eq!(buf.len, expected.len());
            assert!(buf.cap > buf.len);
            assert_eq!(CStr::from_ptr(buf.data).to_bytes(), expected);
            nzbget_rs_free(buf);
        }
    }

    #[test]
    fn null_and_empty_input_return_owned_empty_strings() {
        for encode in [nzbget_rs_json_encode as Encoder, nzbget_rs_xml_encode] {
            check(encode, std::ptr::null(), b"");
            check(encode, b"\0".as_ptr().cast(), b"");
        }
    }

    #[test]
    fn input_stops_at_first_nul_including_inside_utf8() {
        for encode in [nzbget_rs_json_encode as Encoder, nzbget_rs_xml_encode] {
            check(encode, b"abc\0ignored\0".as_ptr().cast(), b"abc");
            check(encode, b"a\xe2\x82\0ignored\0".as_ptr().cast(), b"a");
            check(encode, b"a\xf0\x9f\x98\0ignored\0".as_ptr().cast(), b"a");
        }
    }

    #[test]
    fn preserves_legacy_malformed_utf8() {
        check(nzbget_rs_json_encode, b"\xc0\x80\0".as_ptr().cast(), b"\\u0000");
        check(nzbget_rs_xml_encode, b"\xc0\x80\0".as_ptr().cast(), b".");
        // Only the first continuation byte is validated by the old C++.
        check(nzbget_rs_json_encode, b"\xe2\x82A\0".as_ptr().cast(), b"\\u2081");
        check(nzbget_rs_xml_encode, b"\xe2\x82A\0".as_ptr().cast(), b"&#x002081;");
        check(nzbget_rs_json_encode, b"\xf7\xbf\xbf\xbf\0".as_ptr().cast(), b"\\udfbf\\udfff");
        check(nzbget_rs_xml_encode, b"\xf7\xbf\xbf\xbf\0".as_ptr().cast(), b".");
    }

    #[test]
    fn result_owns_storage_independently_of_input() {
        for encode in [nzbget_rs_json_encode as Encoder, nzbget_rs_xml_encode] {
            let mut input = b"plain\0".to_vec();
            unsafe {
                let first = encode(input.as_ptr().cast());
                input[0] = b'P';
                let second = encode(input.as_ptr().cast());
                drop(input);
                assert_eq!(CStr::from_ptr(first.data).to_bytes(), b"plain");
                nzbget_rs_free(first);
                assert_eq!(CStr::from_ptr(second.data).to_bytes(), b"Plain");
                nzbget_rs_free(second);
            }
        }
    }

    #[test]
    fn null_buffer_can_be_freed() {
        unsafe { nzbget_rs_free(RsBuf { data: std::ptr::null_mut(), len: 0, cap: 0 }) };
    }
}
