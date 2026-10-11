//! Terminal unquoted filename parsing and PAR classification for duplicate search.

fn trim_range(bytes: &[u8], mut start: usize, mut end: usize) -> (usize, usize) {
    let trim = |b| matches!(b, b' ' | b'\t' | b'\r' | b'\n');
    while start < end && trim(bytes[start]) {
        start += 1;
    }
    while end > start && trim(bytes[end - 1]) {
        end -= 1;
    }
    (start, end)
}

fn regex_space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\r' | b'\n' | 0x0b | 0x0c)
}

/// Strip a terminal yEnc decoration after C++ has handled the first quoted filename.
/// Return a borrowed range; quoting inside this input is left untouched.
pub fn unquoted_subject_range(subject: &[u8]) -> (usize, usize) {
    let mut end = subject.len();
    while end > 0 && regex_space(subject[end - 1]) {
        end -= 1;
    }
    // Match the optional parenthesized part count backwards, without allocating.
    let mut marker_end = end;
    if end > 0 && subject[end - 1] == b')' {
        let mut pos = end - 1;
        while pos > 0 && subject[pos - 1].is_ascii_digit() {
            pos -= 1;
        }
        if pos < end - 1 && pos > 0 && subject[pos - 1] == b'/' {
            let slash = pos - 1;
            pos = slash;
            while pos > 0 && subject[pos - 1].is_ascii_digit() {
                pos -= 1;
            }
            if pos < slash && pos > 0 && subject[pos - 1] == b'(' {
                pos -= 1;
                let space_end = pos;
                while pos > 0 && regex_space(subject[pos - 1]) {
                    pos -= 1;
                }
                if pos < space_end {
                    marker_end = pos;
                }
            }
        }
    }
    if marker_end >= 4 && subject[marker_end - 4..marker_end].eq_ignore_ascii_case(b"yEnc") {
        let mut start = marker_end - 4;
        let space_end = start;
        while start > 0 && regex_space(subject[start - 1]) {
            start -= 1;
        }
        if start < space_end {
            return trim_range(subject, 0, start);
        }
    }
    trim_range(subject, 0, subject.len())
}

#[cfg(not(all(target_os = "linux", target_env = "gnu")))]
unsafe extern "C" {
    fn tolower(ch: std::ffi::c_int) -> std::ffi::c_int;
}

#[cfg(all(target_os = "linux", target_env = "gnu"))]
unsafe extern "C" {
    fn __ctype_tolower_loc() -> *const *const std::ffi::c_int;
}

/// Keep C locale case folding used by DupeUtil::Lower, including unsigned bytes.
pub fn is_par_name(name: &[u8]) -> bool {
    if name.len() < 5 {
        return false;
    }
    let tail = &name[name.len() - 5..];
    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    {
        // glibc's inline C/C++ tolower uses this per-thread locale table. Obtain it once,
        // preserving every byte's locale mapping without five separate native calls.
        // SAFETY: glibc guarantees entries for all unsigned char values; nothing escapes.
        let table = unsafe { *__ctype_tolower_loc() };
        tail.iter()
            .zip(b".par2")
            .all(|(&a, &b)| unsafe { *table.add(usize::from(a)) == i32::from(b) })
    }
    #[cfg(not(all(target_os = "linux", target_env = "gnu")))]
    {
        tail.iter().zip(b".par2").all(|(&a, &b)| {
            // SAFETY: an unsigned byte is always in the C tolower argument domain.
            unsafe { tolower(a.into()) == i32::from(b) }
        })
    }
}

#[repr(C)]
pub struct SubjectRange {
    pub start: usize,
    pub len: usize,
}

unsafe fn bytes<'a>(data: *const u8, len: usize) -> Option<&'a [u8]> {
    if len == 0 {
        return Some(&[]);
    }
    if data.is_null() || len > isize::MAX as usize {
        return None;
    }
    // SAFETY: callers promise a readable allocation of len bytes for this call.
    Some(unsafe { std::slice::from_raw_parts(data, len) })
}

/// # Safety
/// data must point to len readable bytes (or be null for zero len).
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_dupesearch_unquoted_subject(
    data: *const u8,
    len: usize,
) -> SubjectRange {
    let (start, end) = unsafe { bytes(data, len) }
        .map(unquoted_subject_range)
        .unwrap_or((0, 0));
    SubjectRange {
        start,
        len: end - start,
    }
}

/// # Safety
/// data must point to len readable bytes (or be null for zero len).
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_dupesearch_par_name(data: *const u8, len: usize) -> i32 {
    i32::from(unsafe { bytes(data, len) }.is_some_and(is_par_name))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn strips_only_complete_terminal_yenc() {
        for (input, want) in [
            (&b" \"\" data.bin yEnc (1/2) \t"[..], &b"\"\" data.bin"[..]),
            (&b"data.bin\tYeNc\x0b(01/002)\x0c"[..], &b"data.bin"[..]),
            (&b"data.bin yEnc"[..], &b"data.bin"[..]),
            (&b"a yEnc (1/2)\0tail"[..], &b"a yEnc (1/2)\0tail"[..]),
            (&b"data.bin yEnc(1/2)"[..], &b"data.bin yEnc(1/2)"[..]),
            (&b"data.bin yEnc (1/)"[..], &b"data.bin yEnc (1/)"[..]),
            (
                &b"data.bin yEnc (1/2)junk"[..],
                &b"data.bin yEnc (1/2)junk"[..],
            ),
            (&b"\x0bdata.bin\x0c"[..], &b"\x0bdata.bin\x0c"[..]),
            (&b"\"unterminated yEnc"[..], &b"\"unterminated"[..]),
        ] {
            let (start, end) = unquoted_subject_range(input);
            assert_eq!(&input[start..end], want, "{input:?}");
        }
    }
    #[test]
    fn ffi_rejects_null_nonempty_and_unrepresentable_lengths() {
        // These inputs must be rejected before constructing a slice.
        unsafe {
            for len in [0, 1, usize::MAX] {
                let range = nzbget_rs_dupesearch_unquoted_subject(std::ptr::null(), len);
                assert_eq!((range.start, range.len), (0, 0));
                assert_eq!(nzbget_rs_dupesearch_par_name(std::ptr::null(), len), 0);
            }
            let range = nzbget_rs_dupesearch_unquoted_subject(b"a".as_ptr(), usize::MAX);
            assert_eq!((range.start, range.len), (0, 0));
        }
    }
    #[test]
    fn only_terminal_par2_extension_classifies_recovery() {
        assert!(is_par_name(b"x.PaR2"));
        assert!(is_par_name(b".par2"));
        for name in [b"par2".as_slice(), b"a.vol1+2.mkv", b"a.par2 ", b"a.par2\0"] {
            assert!(!is_par_name(name));
        }
    }
}
