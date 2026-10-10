//! C ABI. Strings come in as NUL-terminated C strings; results go out as a
//! buffer the caller copies and then frees with nzbget_rs_free.

use std::ffi::{c_char, CStr};

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
