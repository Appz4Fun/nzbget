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
/// `raw` is null or a writable NUL-terminated string. `lower`, if supplied,
/// takes an ASCII hex letter and returns the caller's tolower result; it must
/// not unwind or access `raw`. A null callback leaves the buffer unchanged.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_decode(raw: *mut c_char, lower: Option<extern "C" fn(c_int) -> c_int>) {
    let Some(lower) = lower else { return };
    in_place(raw, |b| crate::text::xml_decode(b, &|c| lower(c as c_int)))
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

/// WebUtil::XmlRemoveEntities, in place; `is_alpha` takes a byte in 0..=255
/// and classifies it in the caller's locale and char signedness.
/// A null callback leaves the buffer unchanged.
///
/// # Safety
/// `raw` is null or a writable NUL-terminated string; `is_alpha`, if supplied,
/// doesn't unwind or access `raw`.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_remove_entities(raw: *mut c_char, is_alpha: Option<extern "C" fn(c_int) -> c_int>) {
    let Some(is_alpha) = is_alpha else { return };
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

/// WebUtil::XmlFindTag: a pointer into `xml` and the value length, or null
/// (`value_length` untouched).
///
/// # Safety
/// `xml` and `tag` are null or NUL-terminated; `value_length` is null or writable.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_xml_find_tag(xml: *const c_char, tag: *const c_char, value_length: *mut c_int) -> *const c_char {
    if xml.is_null() || tag.is_null() || value_length.is_null() {
        return std::ptr::null();
    }
    match crate::webutil::xml_find_tag(input(xml), input(tag)) {
        Some((start, len)) => {
            // the C++ (int) of a pointer difference
            *value_length = len as c_int;
            xml.add(start)
        }
        None => std::ptr::null(),
    }
}

/// WebUtil::JsonFindField: a pointer into `text` and the value length, or
/// null (`value_length` untouched).
///
/// # Safety
/// `text` and `field` are null or NUL-terminated; `value_length` is null or writable.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_json_find_field(text: *const c_char, field: *const c_char, value_length: *mut c_int) -> *const c_char {
    if text.is_null() || field.is_null() || value_length.is_null() {
        return std::ptr::null();
    }
    match crate::webutil::json_find_field(input(text), input(field)) {
        Some((start, len)) => {
            *value_length = len as c_int;
            text.add(start)
        }
        None => std::ptr::null(),
    }
}

/// WebUtil::ParseContentDispositionFilename; `data` is null for no file name
/// (the C++ null CString). Case folds as strncasecmp: glibc's tolower `table`
/// (entries -128..=255, pointing at entry zero) indexed by unsigned byte, or
/// `fold` (tolower of a byte 0..=255) when `table` is null.
///
/// # Safety
/// `cd` is null or NUL-terminated; `table` is null or as described; `fold`
/// doesn't unwind.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_content_disposition_filename(
    cd: *const c_char,
    table: *const c_int,
    fold: Option<extern "C" fn(c_int) -> c_int>,
) -> RsBuf {
    let none = RsBuf { data: std::ptr::null_mut(), len: 0, cap: 0 };
    if table.is_null() && fold.is_none() {
        return none;
    }
    let call = |b: u8| fold.expect("callback checked above")(b as c_int);
    let lower = if table.is_null() {
        crate::wildmask::Lower::Fold(&call)
    } else {
        crate::wildmask::Lower::Table(&*table.sub(128).cast::<[c_int; 384]>(), false)
    };
    match crate::webutil::content_disposition_filename(input(cd), &lower) {
        Some(v) => into_buf(v),
        None => none,
    }
}

/// Util::FormatSize; free the result with nzbget_rs_free.
#[no_mangle]
pub extern "C" fn nzbget_rs_format_size(size: i64) -> RsBuf {
    into_buf(crate::util::format_size(size))
}

/// Util::FormatSpeed; free the result with nzbget_rs_free.
#[no_mangle]
pub extern "C" fn nzbget_rs_format_speed(bytes_per_second: i64) -> RsBuf {
    into_buf(crate::util::format_speed(bytes_per_second))
}

/// Util::AlphaNum.
///
/// # Safety
/// `s` is null or NUL-terminated.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_alpha_num(s: *const c_char) -> c_int {
    crate::util::alpha_num(input(s)) as c_int
}

/// Util::HashBJ96 over `len` bytes (the C++ uint32 of an int length).
///
/// # Safety
/// `buf` is null or readable for `len` bytes (as uint32), at most isize::MAX.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_hash_bj96(buf: *const c_char, len: c_int, init: u32) -> u32 {
    let len = len as u32 as usize;
    if buf.is_null() || len == 0 {
        return crate::util::hash_bj96(&[], init);
    }
    crate::util::hash_bj96(std::slice::from_raw_parts(buf.cast(), len), init)
}

/// Util::ReduceStr, in place.
///
/// # Safety
/// `s` is null or a writable NUL-terminated string; `from` and `to` are null
/// or NUL-terminated. Operands may alias `s`; any null argument is a no-op.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_reduce_str(s: *mut c_char, from: *const c_char, to: *const c_char) {
    crate::util::reduce_str(s, from, to)
}

/// Util::MatchFileExt. Case folding: glibc's tolower `table` (entries
/// -128..=255, pointing at entry zero) when not null, indexed by unsigned
/// byte for the extension compare (strcasecmp) and as the C++ char
/// (`char_signed`) for wildcard extensions (WildMask); else the callbacks
/// `case_fold` (a byte 0..=255) and `mask_fold` (as WildMask's).
///
/// # Safety
/// The strings are null or NUL-terminated; `table` is null or as described;
/// the callbacks don't unwind or mutate inputs. Callbacks may be null when
/// a table is supplied.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_match_file_ext(
    filename: *const c_char,
    list: *const c_char,
    separators: *const c_char,
    table: *const c_int,
    char_signed: c_int,
    case_fold: Option<extern "C" fn(c_int) -> c_int>,
    mask_fold: Option<extern "C" fn(c_int) -> c_int>,
) -> c_int {
    use crate::wildmask::Lower;
    if table.is_null() && (case_fold.is_none() || mask_fold.is_none()) {
        return 0;
    }
    let case_call = |b: u8| case_fold.expect("callback checked above")(b as c_int);
    let mask_call = |b: u8| mask_fold.expect("callback checked above")(b as c_int);
    let (case_lower, mask_lower) = if table.is_null() {
        (Lower::Fold(&case_call), Lower::Fold(&mask_call))
    } else {
        let t = &*table.sub(128).cast::<[c_int; 384]>();
        (Lower::Table(t, false), Lower::Table(t, char_signed != 0))
    };
    crate::util::match_file_ext(input(filename), input(list), input(separators), &case_lower, &mask_lower) as c_int
}

/// URL::ParseUrl's result: each part as a start and length in the address,
/// start -1 for a part not set.
#[repr(C)]
pub struct UrlParts {
    pub valid: c_int,
    pub port: c_int,
    /// protocol, user, password, host, resource: [start, length]
    pub parts: [[isize; 2]; 5],
}

/// URL::ParseUrl (rust/src/url.rs). A valid URL without a resource has
/// resource start -1: the caller uses "/".
///
/// # Safety
/// `address` is null or NUL-terminated; `out` is writable.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_parse_url(address: *const c_char, out: *mut UrlParts) {
    if out.is_null() {
        return;
    }
    let mut r = UrlParts { valid: 0, port: 0, parts: [[-1, 0]; 5] };
    if !address.is_null() {
        let u = crate::url::parse_url(CStr::from_ptr(address));
        r.valid = u.valid as c_int;
        r.port = u.port;
        for (k, p) in [u.protocol, u.user, u.password, u.host, u.resource].into_iter().enumerate() {
            if let Some((start, len)) = p {
                r.parts[k] = [start as isize, len as isize];
            }
        }
    }
    *out = r;
}

/// A FeedFilter's view of the C++ feed item (rust/src/feedfilter.rs).
#[repr(C)]
pub struct FeedItemCallbacks {
    pub user: *mut std::ffi::c_void,
    /// a field's text (null for a null C string) and number; `attr` is the
    /// attribute name for "attr-" fields
    pub field: Option<unsafe extern "C" fn(*mut std::ffi::c_void, c_int, *const c_char, *mut *const c_char, *mut i64)>,
    /// GetSeason (0) or GetEpisode (1) after the title is parsed
    pub season_episode: Option<unsafe extern "C" fn(*mut std::ffi::c_void, c_int) -> *const c_char>,
    /// RegEx(pattern, bufSize): a handle
    pub regex_new: Option<unsafe extern "C" fn(*mut std::ffi::c_void, *const c_char, c_int) -> usize>,
    /// RegEx::Match: -1 when it doesn't match, else GetMatchCount, with up to
    /// `capacity` (start, length) pairs written
    pub regex_match: Option<unsafe extern "C" fn(*mut std::ffi::c_void, usize, *const c_char, *mut [c_int; 2], c_int) -> c_int>,
    pub apply: Option<unsafe extern "C" fn(*mut std::ffi::c_void, *const FeedOptions)>,
    pub set_match: Option<unsafe extern "C" fn(*mut std::ffi::c_void, c_int, c_int)>,
    /// case folding for WildMask: glibc's tolower table (entries -128..=255,
    /// pointing at entry zero) or null for `fold`
    pub lower_table: *const c_int,
    pub char_signed: c_int,
    pub fold: Option<extern "C" fn(c_int) -> c_int>,
}

/// A matched rule's options for ApplyOptions; strings may be null.
#[repr(C)]
pub struct FeedOptions {
    pub has_pause: c_int,
    pub pause: c_int,
    pub has_category: c_int,
    pub category: *const c_char,
    pub has_priority: c_int,
    pub priority: c_int,
    pub has_add_priority: c_int,
    pub add_priority: c_int,
    pub has_dupe_score: c_int,
    pub dupe_score: c_int,
    pub has_add_dupe_score: c_int,
    pub add_dupe_score: c_int,
    pub has_build_dupe_key: c_int,
    /// rageid, tvdbid, tvmazeid, series
    pub ids: [*const c_char; 4],
    pub has_dupe_key: c_int,
    pub dupe_key: *const c_char,
    pub has_add_dupe_key: c_int,
    pub add_dupe_key: *const c_char,
    pub has_dupe_mode: c_int,
    pub dupe_mode: c_int,
}

struct CItem<'c> {
    cb: &'c FeedItemCallbacks,
    lower: crate::wildmask::Lower<'c>,
}

unsafe fn c_text(p: *const c_char) -> Option<Vec<u8>> {
    (!p.is_null()).then(|| CStr::from_ptr(p).to_bytes().to_vec())
}

impl crate::feedfilter::Item for CItem<'_> {
    fn field(&mut self, field: crate::feedfilter::Field, attr: &[u8]) -> (Option<Vec<u8>>, i64) {
        let attr = std::ffi::CString::new(attr).unwrap_or_default();
        let mut s: *const c_char = std::ptr::null();
        let mut n: i64 = 0;
        unsafe {
            (self.cb.field.expect("callbacks validated"))(self.cb.user, field as c_int, attr.as_ptr(), &mut s, &mut n);
            (c_text(s), n)
        }
    }

    fn season_episode(&mut self, episode: bool) -> Option<Vec<u8>> {
        unsafe { c_text((self.cb.season_episode.expect("callbacks validated"))(self.cb.user, episode as c_int)) }
    }

    fn regex_new(&mut self, pattern: &[u8], buf_size: i32) -> usize {
        let p = std::ffi::CString::new(pattern).unwrap_or_default();
        unsafe { (self.cb.regex_new.expect("callbacks validated"))(self.cb.user, p.as_ptr(), buf_size) }
    }

    fn regex_match(&mut self, handle: usize, text: &[u8]) -> Option<Vec<(i32, i32)>> {
        let t = std::ffi::CString::new(text).unwrap_or_default();
        let mut groups = [[0 as c_int; 2]; 100];
        let n = unsafe { (self.cb.regex_match.expect("callbacks validated"))(self.cb.user, handle, t.as_ptr(), groups.as_mut_ptr(), 100) };
        (n >= 0).then(|| groups[..(n as usize).min(100)].iter().map(|g| (g[0], g[1])).collect())
    }

    fn apply(&mut self, o: &crate::feedfilter::Applied<'_>) {
        // C strings for the call; None (a null C string) stays null
        let keep: Vec<Option<std::ffi::CString>> = [
            o.category.flatten(),
            o.dupe_key.flatten(),
            o.add_dupe_key.flatten(),
        ]
        .into_iter()
        .chain(o.build_dupe_key.unwrap_or_default())
        .map(|v| v.map(|b| std::ffi::CString::new(b).unwrap_or_default()))
        .collect();
        let ptr = |k: usize| keep[k].as_ref().map_or(std::ptr::null(), |c| c.as_ptr());
        let flag = |b: bool| b as c_int;
        let opts = FeedOptions {
            has_pause: flag(o.pause.is_some()),
            pause: flag(o.pause.unwrap_or(false)),
            has_category: flag(o.category.is_some()),
            category: ptr(0),
            has_priority: flag(o.priority.is_some()),
            priority: o.priority.unwrap_or(0),
            has_add_priority: flag(o.add_priority.is_some()),
            add_priority: o.add_priority.unwrap_or(0),
            has_dupe_score: flag(o.dupe_score.is_some()),
            dupe_score: o.dupe_score.unwrap_or(0),
            has_add_dupe_score: flag(o.add_dupe_score.is_some()),
            add_dupe_score: o.add_dupe_score.unwrap_or(0),
            has_build_dupe_key: flag(o.build_dupe_key.is_some()),
            ids: [ptr(3), ptr(4), ptr(5), ptr(6)],
            has_dupe_key: flag(o.dupe_key.is_some()),
            dupe_key: ptr(1),
            has_add_dupe_key: flag(o.add_dupe_key.is_some()),
            add_dupe_key: ptr(2),
            has_dupe_mode: flag(o.dupe_mode.is_some()),
            dupe_mode: o.dupe_mode.map_or(0, |m| m as c_int),
        };
        unsafe { (self.cb.apply.expect("callbacks validated"))(self.cb.user, &opts) }
    }

    fn set_match(&mut self, status: i32, rule: i32) {
        unsafe { (self.cb.set_match.expect("callbacks validated"))(self.cb.user, status, rule) }
    }

    fn lower(&self) -> &crate::wildmask::Lower<'_> {
        &self.lower
    }
}

/// FeedFilter(filter): a compiled filter; free it with
/// nzbget_rs_feed_filter_free.
///
/// # Safety
/// `filter` is null (an empty filter) or NUL-terminated.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_feed_filter_new(filter: *const c_char) -> *mut crate::feedfilter::FeedFilter {
    Box::into_raw(Box::new(crate::feedfilter::FeedFilter::new(input(filter))))
}

/// # Safety
/// `filter` is null or from nzbget_rs_feed_filter_new, not yet freed and
/// not currently being matched.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_feed_filter_free(filter: *mut crate::feedfilter::FeedFilter) {
    if !filter.is_null() {
        drop(Box::from_raw(filter));
    }
}

/// FeedFilter::Match.
///
/// # Safety
/// `filter` is null or an exclusively accessed handle from
/// nzbget_rs_feed_filter_new. `item` is null or a valid callback table for
/// the duration of this call. Callbacks must not unwind, reenter/free this
/// filter, or invalidate the table. Returned strings must be null or valid
/// NUL-terminated strings until the next callback; passed strings are only
/// borrowed for the callback. Regex handles must remain valid across calls.
/// A nonnull lower_table spans entries -128..255 as described above.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_feed_filter_match(filter: *mut crate::feedfilter::FeedFilter, item: *const FeedItemCallbacks) {
    if filter.is_null() || item.is_null() {
        return;
    }
    let cb = &*item;
    if cb.field.is_none() || cb.season_episode.is_none() || cb.regex_new.is_none()
        || cb.regex_match.is_none() || cb.apply.is_none() || cb.set_match.is_none()
        || (cb.lower_table.is_null() && cb.fold.is_none())
    {
        return;
    }
    let fold = cb.fold;
    let call = move |b: u8| fold.expect("callbacks validated")(b as c_int);
    let lower = if cb.lower_table.is_null() {
        crate::wildmask::Lower::Fold(&call)
    } else {
        crate::wildmask::Lower::Table(&*cb.lower_table.sub(128).cast::<[c_int; 384]>(), cb.char_signed != 0)
    };
    let mut c_item = CItem { cb, lower };
    (*filter).matches(&mut c_item);
}

unsafe fn bytes<'a>(p: *const c_char, len: usize) -> &'a [u8] {
    if p.is_null() || len == 0 { &[] } else { std::slice::from_raw_parts(p.cast(), len) }
}

/// Deobfuscation::IsExcessivelyObfuscated (rust/src/deobfuscation.rs).
///
/// # Safety
/// `s` is null or readable for `len` bytes.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_is_excessively_obfuscated(s: *const c_char, len: usize) -> c_int {
    crate::deobfuscation::is_excessively_obfuscated(bytes(s, len)) as c_int
}

/// Deobfuscation::Deobfuscate; free the result with nzbget_rs_free.
///
/// # Safety
/// `s` is null or readable for `len` bytes.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_deobfuscate(s: *const c_char, len: usize) -> RsBuf {
    into_buf(crate::deobfuscation::deobfuscate(bytes(s, len)))
}

/// FileTypes' name checks (rust/src/filetypes.rs), by number (see nzbget_rs.h).
///
/// # Safety
/// `s` is null or readable for `len` bytes.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_file_type(which: c_int, s: *const c_char, len: usize) -> c_int {
    use crate::filetypes::*;
    const CHECKS: [fn(&[u8]) -> bool; 25] = [
        is_seven_zip_ext, is_rar_ext, is_rar_volume_ext, is_numeric_volume_ext, is_all_digits_ext, is_archive_ext,
        is_disc_structure_ext, is_disc_structure_dir, is_disc_descriptor_ext, is_disc_image_ext,
        is_generic_disc_image_ext, is_clutter_dir, is_clutter_file, is_parity_ext, is_video_ext, is_audio_ext,
        is_subtitle_ext, is_nfo_ext, is_book_ext, is_image_ext, is_sample_stem, is_seven_zip_file, is_rar_file,
        is_archive_file, is_sample_file,
    ];
    match usize::try_from(which).ok().and_then(|w| CHECKS.get(w)) {
        Some(check) => check(bytes(s, len)) as c_int,
        None => 0,
    }
}

fn static_str(e: &'static CStr, out_len: *mut usize) -> *const c_char {
    if !out_len.is_null() {
        unsafe { *out_len = e.to_bytes().len() };
    }
    e.as_ptr()
}

/// FileTypes::SniffExtension of a header: a static extension ("" for none),
/// its length in `out_len`.
///
/// # Safety
/// `header` is null or readable for `len` bytes; `out_len` null or writable.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_sniff_extension(header: *const u8, len: usize, out_len: *mut usize) -> *const c_char {
    let h = if header.is_null() || len == 0 { &[][..] } else { std::slice::from_raw_parts(header, len) };
    static_str(crate::filetypes::sniff_extension(h), out_len)
}

/// FileSystem's path texts (rust/src/paths.rs): 0 MakeValidFilename (`flag`:
/// allow slashes), 1 SanitizePathSegment, 2 SanitizeRelativePath,
/// 3 EscapePathForShell; free the result with nzbget_rs_free.
///
/// # Safety
/// `s` is null or readable for `len` bytes within one allocation, with
/// `len <= isize::MAX`. Null means empty regardless of `len`. Panics abort
/// rather than unwinding across the ABI.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_path_text(op: c_int, s: *const c_char, len: usize, flag: c_int) -> RsBuf {
    let b = bytes(s, len);
    into_buf(match op {
        0 => crate::paths::make_valid_filename(b, flag != 0),
        1 => crate::paths::sanitize_path_segment(b),
        2 => crate::paths::sanitize_relative_path(b),
        3 => crate::paths::escape_path_for_shell(b),
        _ => Vec::new(),
    })
}

/// FileSystem's path positions (rust/src/paths.rs): 0 BaseFileName (where
/// the name starts), 1 SplitPathAndFilename (the last '/' or '\\', or
/// SIZE_MAX), 2 ExtractFilePathFromCmd (the length of the path).
///
/// # Safety
/// `s` is null or readable for `len` bytes within one allocation, with
/// `len <= isize::MAX`. Null means empty regardless of `len`.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_path_position(op: c_int, s: *const c_char, len: usize) -> usize {
    let b = bytes(s, len);
    match op {
        0 => crate::paths::base_file_name(b),
        1 => {
            let (path, name) = crate::paths::split_path_and_filename(b);
            if name.is_empty() && path.len() == b.len() { usize::MAX } else { path.len() }
        }
        2 => crate::paths::extract_file_path_from_cmd(b).len(),
        _ => 0,
    }
}

/// FileSystem::ReservedChar.
#[no_mangle]
pub extern "C" fn nzbget_rs_reserved_char(c: c_char) -> c_int {
    crate::paths::reserved_char(c as u8) as c_int
}

/// FileSystem::NormalizePathSeparators, in place.
///
/// # Safety
/// `path` is null or a writable NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_normalize_path_separators(path: *mut c_char) {
    in_place(path, |b| {
        crate::paths::normalize_path_separators(b);
        b.len()
    })
}

/// A CollectionAnalyzer::FileEntry (rust/src/collection.rs).
#[repr(C)]
pub struct FileEntryC {
    pub path: *const c_char,
    pub path_len: usize,
    pub rename_prefix: *const c_char,
    pub rename_prefix_len: usize,
    pub filename: *const c_char,
    pub filename_len: usize,
    pub stem: *const c_char,
    pub stem_len: usize,
    pub ext: *const c_char,
    pub ext_len: usize,
    pub size: u64,
}

unsafe fn entries(files: *const FileEntryC, count: usize) -> Vec<crate::collection::Entry> {
    if files.is_null() || count == 0 {
        return Vec::new();
    }
    std::slice::from_raw_parts(files, count)
        .iter()
        .map(|f| crate::collection::Entry {
            path: bytes(f.path, f.path_len).to_vec(),
            rename_prefix: bytes(f.rename_prefix, f.rename_prefix_len).to_vec(),
            filename: bytes(f.filename, f.filename_len).to_vec(),
            stem: bytes(f.stem, f.stem_len).to_vec(),
            ext: bytes(f.ext, f.ext_len).to_vec(),
            size: f.size,
        })
        .collect()
}

/// AnalysisResult by index into the files (-1: an empty FileEntry); the
/// index arrays have room for `count` each.
#[repr(C)]
pub struct AnalysisC {
    pub main_video: isize,
    pub sample_video: isize,
    pub main_book: isize,
    pub subtitles: *mut usize,
    pub subtitle_count: usize,
    pub nfos: *mut usize,
    pub nfo_count: usize,
    pub other_files: *mut usize,
    pub other_count: usize,
    pub ambiguous: c_int,
    pub disc_structure: c_int,
    pub has_audio: c_int,
}

/// CollectionAnalyzer::Analyze.
///
/// # Safety
/// `files` is null (empty) or holds `count` valid entries. Entry strings
/// are null (empty) or readable for their lengths. `out` is null or writable;
/// its arrays are null (counts only) or have room for `count` indices and
/// are disjoint from `out`. All storage remains caller-owned.
/// Panics abort rather than crossing the ABI.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_collection_analyze(files: *const FileEntryC, count: usize, out: *mut AnalysisC) {
    if out.is_null() {
        return;
    }
    let a = crate::collection::analyze(&entries(files, count));
    let o = &mut *out;
    let idx = |i: Option<usize>| i.map_or(-1, |k| k as isize);
    o.main_video = idx(a.main_video);
    o.sample_video = idx(a.sample_video);
    o.main_book = idx(a.main_book);
    let fill = |dst: *mut usize, src: &[usize]| {
        if !dst.is_null() {
            for (k, &v) in src.iter().take(count).enumerate() {
                *dst.add(k) = v;
            }
        }
        src.len().min(count)
    };
    o.subtitle_count = fill(o.subtitles, &a.subtitles);
    o.nfo_count = fill(o.nfos, &a.nfos);
    o.other_count = fill(o.other_files, &a.other_files);
    o.ambiguous = a.ambiguous as c_int;
    o.disc_structure = a.disc_structure as c_int;
    o.has_audio = a.has_audio as c_int;
}

/// What CollectionAnalyzer::BuildPlan asks of the C++ side, and where it
/// puts the plan.
#[repr(C)]
pub struct PlanCallbacks {
    pub user: *mut std::ffi::c_void,
    pub exists: Option<unsafe extern "C" fn(*mut std::ffi::c_void, *const c_char, usize) -> c_int>,
    pub ignored: Option<unsafe extern "C" fn(*mut std::ffi::c_void, *const c_char, usize) -> c_int>,
    /// a rename: the file's index, the new path, the new file name
    pub action: Option<unsafe extern "C" fn(*mut std::ffi::c_void, usize, *const c_char, usize, *const c_char, usize)>,
}

/// RenamePlan's flags; the effective base name is returned.
#[repr(C)]
#[derive(Default)]
pub struct PlanFlagsC {
    pub ambiguous: c_int,
    pub disc_structure: c_int,
    pub can_rename: c_int,
    pub target_name_obfuscated: c_int,
}

struct CDisk<'c>(&'c PlanCallbacks);

impl crate::collection::Disk for CDisk<'_> {
    fn exists(&mut self, path: &[u8]) -> bool {
        self.0.exists.is_some_and(|f| unsafe { f(self.0.user, path.as_ptr().cast(), path.len()) != 0 })
    }
    fn ignored(&mut self, path: &[u8]) -> bool {
        self.0.ignored.is_some_and(|f| unsafe { f(self.0.user, path.as_ptr().cast(), path.len()) != 0 })
    }
}

/// CollectionAnalyzer::BuildPlan for the walked files; free the returned
/// effective base name with nzbget_rs_free.
///
/// # Safety
/// `files` is null (empty) or holds `count` valid entries, with strings null
/// (empty) or readable for their lengths. `target` is null (empty) or readable
/// for `target_len`. `callbacks` is null or a valid table; its functions must
/// not unwind or invalidate the table/flags. Callback strings are borrowed
/// only for the call. `flags` is null or writable and disjoint from the table.
/// Null table/flags returns an empty buffer, clearing non-null flags. Null
/// exists/ignored means false; null action discards actions. Panics abort.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_collection_plan(
    files: *const FileEntryC,
    count: usize,
    disc_dir: c_int,
    target: *const c_char,
    target_len: usize,
    callbacks: *const PlanCallbacks,
    flags: *mut PlanFlagsC,
) -> RsBuf {
    if !flags.is_null() {
        *flags = PlanFlagsC::default();
    }
    if callbacks.is_null() || flags.is_null() {
        return into_buf(Vec::new());
    }
    let cb = &*callbacks;
    let plan = crate::collection::build_plan(&entries(files, count), disc_dir != 0, bytes(target, target_len), &mut CDisk(cb));
    for a in &plan.actions {
        if let Some(action) = cb.action {
            action(cb.user, a.src, a.dst_path.as_ptr().cast(), a.dst_path.len(), a.new_filename.as_ptr().cast(), a.new_filename.len());
        }
    }
    *flags = PlanFlagsC {
        ambiguous: plan.ambiguous as c_int,
        disc_structure: plan.disc_structure as c_int,
        can_rename: plan.can_rename as c_int,
        target_name_obfuscated: plan.target_name_obfuscated as c_int,
    };
    into_buf(plan.effective_base_name)
}

/// CollectionAnalyzer's names: 0 ResolveTargetName(a: meta, b: nzb),
/// 1 ResolveSubtitleName(a: base, b: stem, c: ext), 2 ResolveSampleName(a:
/// base, b: ext); free the result with nzbget_rs_free.
///
/// # Safety
/// Each text is null or readable for its length.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_collection_name(
    op: c_int,
    a: *const c_char,
    a_len: usize,
    b: *const c_char,
    b_len: usize,
    c: *const c_char,
    c_len: usize,
) -> RsBuf {
    let (a, b, c) = (bytes(a, a_len), bytes(b, b_len), bytes(c, c_len));
    into_buf(match op {
        0 => crate::collection::resolve_target_name(a, b),
        1 => crate::collection::resolve_subtitle_name(a, b, c),
        2 => crate::collection::resolve_sample_name(a, b),
        _ => Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn collection_null_inputs_and_callbacks() {
        unsafe {
            let mut out = AnalysisC {
                main_video: 0, sample_video: 0, main_book: 0,
                subtitles: std::ptr::null_mut(), subtitle_count: 99,
                nfos: std::ptr::null_mut(), nfo_count: 99,
                other_files: std::ptr::null_mut(), other_count: 99,
                ambiguous: 1, disc_structure: 1, has_audio: 1,
            };
            nzbget_rs_collection_analyze(std::ptr::null(), usize::MAX, &mut out);
            assert_eq!((out.main_video, out.sample_video, out.main_book), (-1, -1, -1));
            assert_eq!((out.subtitle_count, out.nfo_count, out.other_count), (0, 0, 0));
            assert_eq!((out.ambiguous, out.disc_structure, out.has_audio), (0, 0, 0));
            nzbget_rs_collection_analyze(std::ptr::null(), 0, std::ptr::null_mut());

            let cb = PlanCallbacks { user: std::ptr::null_mut(), exists: None, ignored: None, action: None };
            let mut flags = PlanFlagsC { can_rename: 1, ..PlanFlagsC::default() };
            let empty = nzbget_rs_collection_plan(std::ptr::null(), 99, 0, std::ptr::null(), 99, std::ptr::null(), &mut flags);
            assert_eq!(empty.len, 0);
            assert_eq!(flags.can_rename, 0);
            nzbget_rs_free(empty);
            let empty = nzbget_rs_collection_plan(std::ptr::null(), 99, 1, std::ptr::null(), 99, &cb, &mut flags);
            assert_eq!(flags.disc_structure, 1);
            assert_eq!(flags.can_rename, 0);
            nzbget_rs_free(empty);
            let empty = nzbget_rs_collection_plan(std::ptr::null(), 0, 0, std::ptr::null(), 0, &cb, std::ptr::null_mut());
            nzbget_rs_free(empty);

            let file = FileEntryC {
                path: c"/d/abc.mkv".as_ptr(), path_len: 10,
                rename_prefix: c"/d/".as_ptr(), rename_prefix_len: 3,
                filename: c"abc.mkv".as_ptr(), filename_len: 7,
                stem: c"abc".as_ptr(), stem_len: 3,
                ext: c".mkv".as_ptr(), ext_len: 4, size: 1,
            };
            let base = nzbget_rs_collection_plan(&file, 1, 0, c"Movie.2026".as_ptr(), 10, &cb, &mut flags);
            assert_eq!(flags.can_rename, 1);
            assert_eq!(std::slice::from_raw_parts(base.data.cast::<u8>(), base.len), b"Movie.2026");
            // Another result must neither overwrite nor free the first one.
            for op in 0..=2 {
                let name = nzbget_rs_collection_name(op, std::ptr::null(), 99, std::ptr::null(), 99, std::ptr::null(), 99);
                let expected: &[u8] = if op == 2 { b"-sample" } else { b"" };
                assert_eq!(std::slice::from_raw_parts(name.data.cast::<u8>(), name.len), expected);
                nzbget_rs_free(name);
            }
            assert_eq!(std::slice::from_raw_parts(base.data.cast::<u8>(), base.len), b"Movie.2026");
            nzbget_rs_free(base);
        }
    }

    #[test]
    fn path_nulls_lengths_and_owned_results() {
        unsafe {
            for len in [0, 42, usize::MAX] {
                for op in -1..=4 {
                    let result = nzbget_rs_path_text(op, std::ptr::null(), len, 0);
                    assert_eq!(result.len, 0);
                    assert_eq!(*result.data, 0);
                    nzbget_rs_free(result);
                }
                for (op, expected) in [(0, 0), (1, usize::MAX), (2, 0)] {
                    assert_eq!(nzbget_rs_path_position(op, std::ptr::null(), len), expected);
                }
            }
            nzbget_rs_normalize_path_separators(std::ptr::null_mut());
            let mut raw = [b'a', crate::paths::ALT_PATH_SEPARATOR, 0, crate::paths::ALT_PATH_SEPARATOR];
            nzbget_rs_normalize_path_separators(raw.as_mut_ptr().cast());
            assert_eq!(raw, [b'a', crate::paths::PATH_SEPARATOR, 0, crate::paths::ALT_PATH_SEPARATOR]);

            // Length-bounded input need not have a terminator. The result
            // owns its bytes, including embedded NULs, and an extra terminator.
            let mut input = b"a\0b".to_vec();
            let first = nzbget_rs_path_text(3, input.as_ptr().cast(), input.len(), 0);
            let second = nzbget_rs_path_text(1, input.as_ptr().cast(), input.len(), 0);
            input.fill(b'x');
            drop(input);
            assert_eq!(std::slice::from_raw_parts(first.data.cast::<u8>(), first.len + 1), b"\"a\0b\"\0");
            assert_eq!(CStr::from_ptr(second.data), c"a");
            nzbget_rs_free(second);
            nzbget_rs_free(first);
            let path = b"a/b";
            assert_eq!(nzbget_rs_path_position(0, path.as_ptr().cast(), path.len()), 2);
            assert_eq!(nzbget_rs_path_position(1, path.as_ptr().cast(), path.len()), 1);
            assert_eq!(nzbget_rs_path_position(1, path.as_ptr().cast(), 1), usize::MAX);
        }
    }

    #[test]
    fn filetypes_nulls_lengths_and_static_results() {
        unsafe {
            for len in [0, 42, usize::MAX] {
                for which in -1..=25 {
                    assert_eq!(nzbget_rs_file_type(which, std::ptr::null(), len), 0);
                }
                let mut out_len = usize::MAX;
                let ext = nzbget_rs_sniff_extension(std::ptr::null(), len, &mut out_len);
                assert!(!ext.is_null());
                assert_eq!(out_len, 0);
                assert_eq!(CStr::from_ptr(ext), c"");
            }
            let name = b".rar\0.mkv";
            assert_eq!(nzbget_rs_file_type(1, name.as_ptr().cast(), 4), 1);
            assert_eq!(nzbget_rs_file_type(1, name.as_ptr().cast(), name.len()), 0);
            let header = b"%PDF-".to_vec();
            let mut out_len = 0;
            let ext = nzbget_rs_sniff_extension(header.as_ptr(), header.len(), &mut out_len);
            assert_eq!(out_len, 4);
            drop(header);
            assert_eq!(CStr::from_ptr(ext), c".pdf");
            assert_eq!(CStr::from_ptr(nzbget_rs_sniff_extension(b"ID3".as_ptr(), 3, std::ptr::null_mut())), c".mp3");
            // Later calls and destruction of the input do not invalidate results.
            assert_eq!(CStr::from_ptr(ext), c".pdf");
        }
    }

    #[test]
    fn deobfuscation_nulls_lengths_and_owned_buffers() {
        unsafe {
            for len in [0, 10, usize::MAX] {
                assert_eq!(nzbget_rs_is_excessively_obfuscated(std::ptr::null(), len), 0);
                let result = nzbget_rs_deobfuscate(std::ptr::null(), len);
                assert_eq!(result.len, 0);
                assert_eq!(*result.data, 0);
                nzbget_rs_free(result);
            }
            let mut input = b"prefix \"a\0b\" suffix".to_vec();
            let first = nzbget_rs_deobfuscate(input.as_ptr().cast(), input.len());
            let second = nzbget_rs_deobfuscate(input.as_ptr().cast(), 6);
            input.fill(b'x');
            drop(input);
            assert_eq!(std::slice::from_raw_parts(first.data.cast::<u8>(), first.len + 1), b"a\0b\0");
            assert_eq!(std::slice::from_raw_parts(second.data.cast::<u8>(), second.len + 1), b"prefix\0");
            nzbget_rs_free(second);
            nzbget_rs_free(first);
            assert_eq!(nzbget_rs_is_excessively_obfuscated(b"abcx".as_ptr().cast(), 3), 1);
            assert_eq!(nzbget_rs_is_excessively_obfuscated(b"abcx".as_ptr().cast(), 4), 0);
        }
    }

    #[test]
    fn feed_filter_nulls_ownership_and_callback_order() {
        use std::ffi::c_void;
        #[derive(Default)]
        struct Probe {
            events: Vec<String>,
            category: Vec<u8>,
            priority: i64,
        }
        unsafe fn probe<'a>(user: *mut c_void) -> &'a mut Probe {
            &mut *user.cast::<Probe>()
        }
        unsafe extern "C" fn field(user: *mut c_void, f: c_int, _: *const c_char, s: *mut *const c_char, n: *mut i64) {
            let p = probe(user);
            p.events.push(format!("field {f}"));
            *s = std::ptr::null();
            *n = if f == 13 { p.priority } else { 0 };
        }
        unsafe extern "C" fn season(user: *mut c_void, episode: c_int) -> *const c_char {
            probe(user).events.push(format!("season {episode}"));
            c"02".as_ptr()
        }
        unsafe extern "C" fn regex_new(_: *mut c_void, _: *const c_char, _: c_int) -> usize { 0 }
        unsafe extern "C" fn regex_match(_: *mut c_void, _: usize, _: *const c_char, _: *mut [c_int; 2], _: c_int) -> c_int { -1 }
        unsafe extern "C" fn apply(user: *mut c_void, o: *const FeedOptions) {
            let p = probe(user);
            let o = &*o;
            p.events.push("apply".into());
            if o.has_category != 0 {
                p.category = c_text(o.category).unwrap_or_default();
            }
            if o.has_priority != 0 { p.priority = o.priority as i64; }
        }
        unsafe extern "C" fn set_match(user: *mut c_void, status: c_int, rule: c_int) {
            probe(user).events.push(format!("match {status} {rule}"));
        }
        extern "C" fn fold(c: c_int) -> c_int { c }
        let mut p = Probe::default();
        let cb = FeedItemCallbacks {
            user: (&mut p as *mut Probe).cast(), field: Some(field),
            season_episode: Some(season), regex_new: Some(regex_new), regex_match: Some(regex_match),
            apply: Some(apply), set_match: Some(set_match), lower_table: std::ptr::null(),
            char_signed: 1, fold: Some(fold),
        };
        unsafe {
            nzbget_rs_feed_filter_free(std::ptr::null_mut());
            nzbget_rs_feed_filter_match(std::ptr::null_mut(), std::ptr::null());
            let empty = nzbget_rs_feed_filter_new(std::ptr::null());
            nzbget_rs_feed_filter_match(empty, &cb);
            nzbget_rs_feed_filter_free(empty);
            assert_eq!(p.events, ["match 0 0"]);
            p.events.clear();

            let input = std::ffi::CString::new("O(c:${season},r:7): **%A: priority:=7").unwrap();
            let filter = nzbget_rs_feed_filter_new(input.as_ptr());
            drop(input);
            nzbget_rs_feed_filter_match(filter, std::ptr::null());
            // A zero-initialized C callback table and each missing callback
            // must be representable and rejected without invoking anything.
            let zero: FeedItemCallbacks = std::mem::zeroed();
            nzbget_rs_feed_filter_match(filter, &zero);
            for missing in 0..7 {
                let mut bad = FeedItemCallbacks { ..cb };
                match missing {
                    0 => bad.field = None,
                    1 => bad.season_episode = None,
                    2 => bad.regex_new = None,
                    3 => bad.regex_match = None,
                    4 => bad.apply = None,
                    5 => bad.set_match = None,
                    _ => bad.fold = None,
                }
                nzbget_rs_feed_filter_match(filter, &bad);
            }
            assert!(p.events.is_empty());
            nzbget_rs_feed_filter_match(filter, &cb);
            nzbget_rs_feed_filter_free(filter);
            assert_eq!(p.category, b"02");
            assert_eq!(p.events, ["field 0", "season 0", "match 1 1", "apply", "field 13", "match 1 2", "apply"]);
        }
    }

    #[test]
    fn util_ffi_nulls_ownership_and_table_without_callbacks() {
        unsafe {
            assert_eq!(nzbget_rs_alpha_num(std::ptr::null()), 1);
            assert_eq!(nzbget_rs_hash_bj96(std::ptr::null(), 7, 42), crate::util::hash_bj96(&[], 42));
            nzbget_rs_reduce_str(std::ptr::null_mut(), std::ptr::null(), std::ptr::null());
            let mut raw = *b"abc\0";
            nzbget_rs_reduce_str(raw.as_mut_ptr().cast(), std::ptr::null(), c"".as_ptr());
            assert_eq!(&raw, b"abc\0");
            for (format, expected) in [
                (nzbget_rs_format_size as extern "C" fn(i64) -> RsBuf, &b"512 B\0"[..]),
                (nzbget_rs_format_speed, &b"0 KB/s\0"[..]),
            ] {
                let first = format(512);
                let second = format(12345);
                nzbget_rs_free(second);
                assert_eq!(std::slice::from_raw_parts(first.data.cast::<u8>(), first.len + 1), expected);
                nzbget_rs_free(first);
            }
            let mut table = [0; 384];
            for (i, entry) in table.iter_mut().enumerate() {
                *entry = if i >= 128 { ((i - 128) as u8).to_ascii_lowercase() as c_int } else { i as c_int - 128 };
            }
            for list in [c".NZB", c"*.NZ?"] {
                assert_eq!(nzbget_rs_match_file_ext(c"a.nzb".as_ptr(), list.as_ptr(), c",".as_ptr(),
                    table.as_ptr().add(128), 1, None, None), 1);
            }
            assert_eq!(nzbget_rs_match_file_ext(std::ptr::null(), std::ptr::null(), std::ptr::null(),
                std::ptr::null(), 1, None, None), 0);
        }
    }

    extern "C" fn entity_alpha(byte: c_int) -> c_int {
        assert!((0..=255).contains(&byte));
        (byte == b'@' as c_int || byte == 0xe9 || (byte as u8).is_ascii_alphabetic()) as c_int
    }

    extern "C" fn digit_lower(byte: c_int) -> c_int {
        (byte as u8).to_ascii_lowercase() as c_int
    }

    #[test]
    fn webutil_nulls_borrowing_and_ownership() {
        unsafe {
            for find in [nzbget_rs_xml_find_tag, nzbget_rs_json_find_field] {
                let mut length = -7;
                for (text, name) in [(std::ptr::null(), c"x".as_ptr()),
                                     (c"".as_ptr(), std::ptr::null()),
                                     (c"".as_ptr(), c"x".as_ptr())] {
                    assert!(find(text, name, &mut length).is_null());
                    assert_eq!(length, -7);
                }
                assert!(find(c"".as_ptr(), c"x".as_ptr(), std::ptr::null_mut()).is_null());
            }
            let xml = c"<x>abc</x>";
            let json = c"\"x\": 123";
            let mut length = -7;
            assert_eq!(nzbget_rs_xml_find_tag(xml.as_ptr(), c"x".as_ptr(), &mut length), xml.as_ptr().add(3));
            assert_eq!(length, 3);
            assert_eq!(nzbget_rs_json_find_field(json.as_ptr(), c"x".as_ptr(), &mut length), json.as_ptr().add(5));
            assert_eq!(length, 3);

            for fold in [None, Some(digit_lower as extern "C" fn(c_int) -> c_int)] {
                let result = nzbget_rs_content_disposition_filename(std::ptr::null(), std::ptr::null(), fold);
                assert!(result.data.is_null());
                nzbget_rs_free(result);
            }
            for (mut raw, expected) in [(b"filename=\"\"\0".to_vec(), &b"\0"[..]),
                                         (b"FILENAME=abc\0".to_vec(), &b"abc\0"[..])] {
                let result = nzbget_rs_content_disposition_filename(raw.as_ptr().cast(), std::ptr::null(), Some(digit_lower));
                raw.fill(b'!');
                assert!(!result.data.is_null());
                assert_eq!(result.len, expected.len() - 1);
                assert_eq!(std::slice::from_raw_parts(result.data.cast::<u8>(), result.len + 1), expected);
                nzbget_rs_free(result);
            }
        }
    }

    #[test]
    fn text_null_inputs_and_callback() {
        unsafe {
            for f in [nzbget_rs_xml_strip_tags,
                      nzbget_rs_http_unquote, nzbget_rs_url_decode] {
                f(std::ptr::null_mut());
            }
            nzbget_rs_xml_decode(std::ptr::null_mut(), Some(digit_lower));
            nzbget_rs_xml_decode(std::ptr::null_mut(), None);
            let mut xml = *b"&#xA;\0tail";
            nzbget_rs_xml_decode(xml.as_mut_ptr().cast(), None);
            assert_eq!(&xml, b"&#xA;\0tail");
            nzbget_rs_xml_remove_entities(std::ptr::null_mut(), Some(entity_alpha));
            nzbget_rs_xml_remove_entities(std::ptr::null_mut(), None);
            let mut raw = *b"&amp;\0tail";
            nzbget_rs_xml_remove_entities(raw.as_mut_ptr().cast(), None);
            assert_eq!(&raw, b"&amp;\0tail");
            for f in [nzbget_rs_url_encode, nzbget_rs_latin1_to_utf8] {
                let result = f(std::ptr::null());
                assert_eq!(result.len, 0);
                assert!(!result.data.is_null());
                assert_eq!(*result.data, 0);
                nzbget_rs_free(result);
            }
        }
    }

    #[test]
    fn text_locale_callback_and_embedded_nuls() {
        unsafe {
            let mut raw = *b"&@;&\xe9;&#12;\0tail";
            nzbget_rs_xml_remove_entities(raw.as_mut_ptr().cast(), Some(entity_alpha));
            assert_eq!(&raw[..4], b"   \0");
            assert_eq!(&raw[11..], b"\0tail");
            let mut url = *b"%00a%41\0tail";
            nzbget_rs_url_decode(url.as_mut_ptr().cast());
            assert_eq!(&url, b"\0aA\0%41\0tail");
        }
    }

    #[test]
    fn text_encoders_return_independently_owned_buffers() {
        unsafe {
            for (f, expected) in [
                (nzbget_rs_url_encode as unsafe extern "C" fn(*const c_char) -> RsBuf, &b"\xe9%20x\0"[..]),
                (nzbget_rs_latin1_to_utf8, &b"\xc3\xa9 x\0"[..]),
            ] {
                let mut raw = *b"\xe9 x\0ignored";
                let result = f(raw.as_ptr().cast());
                raw.fill(b'!');
                assert_eq!(result.len, expected.len() - 1);
                assert_eq!(std::slice::from_raw_parts(result.data.cast::<u8>(), result.len + 1), expected);
                nzbget_rs_free(result);
            }
        }
    }

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
