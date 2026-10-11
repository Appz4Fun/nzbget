//! The binary remote protocol's frame (BinRpc.cpp): the checks
//! BinRpcProcessor makes on a request's base - credentials compared as the
//! C++ strcmp compared them, the request type, its size - the request names
//! for the log, the bool responses and the check of a request's trailing
//! data length. Integers on the wire are big-endian (htonl/ntohl). Reading
//! from and writing to the connection, and what each command does, stay C++.

use std::ffi::CStr;
use std::mem::MaybeUninit;

/// NZBMESSAGE_SIGNATURE ("nzb1").
pub const SIGNATURE: i32 = 0x6E7A_6231;
/// NZBREQUESTPASSWORDSIZE.
const PASSWORD_SIZE: usize = 32;
/// sizeof(SNzbRequestBase): signature, struct size, type, user, password.
pub const BASE_SIZE: usize = 12 + 2 * PASSWORD_SIZE;
const USER_AT: usize = 12;
const PASSWORD_AT: usize = USER_AT + PASSWORD_SIZE;
/// rrHistory, the last request type.
pub const LAST_TYPE: u32 = 14;

/// g_MessageRequestNames.
const NAMES: [&CStr; LAST_TYPE as usize + 1] = [c"N/A", c"Download", c"Pause/Unpause", c"List", c"Set download rate",
    c"Dump debug", c"Edit queue", c"Log", c"Quit", c"Reload", c"Version", c"Post-queue", c"Write log", c"Scan", c"History"];

fn be32(base: &[u8; BASE_SIZE], at: usize) -> u32 {
    u32::from_be_bytes(base[at..at + 4].try_into().unwrap())
}

/// A C string in the base from `at`: strcmp read on past an unterminated
/// field (the user name into the password); the base's end stops it here.
fn c_field(base: &[u8; BASE_SIZE], at: usize) -> &[u8] {
    let rest = &base[at..];
    &rest[..rest.iter().position(|&b| b == 0).unwrap_or(rest.len())]
}

/// BinRpcProcessor::Execute's credential check: true when the request may
/// go on (an empty ControlUsername isn't compared).
pub fn credentials_ok(base: &[u8; BASE_SIZE], control_user: &[u8], control_password: &[u8]) -> bool {
    !((!control_user.is_empty() && c_field(base, USER_AT) != control_user) || c_field(base, PASSWORD_AT) != control_password)
}

/// The request type (ntohl(m_type)).
pub fn request_type(base: &[u8; BASE_SIZE]) -> u32 {
    be32(base, 8)
}

/// The request's name in the debug line ("Unknown" past rrHistory).
pub fn request_name(kind: u32) -> &'static CStr {
    NAMES.get(kind as usize).copied().unwrap_or(c"Unknown")
}

/// Dispatch's size check: Some((expected, received)) when a known request
/// type comes with another struct size than g_MessageRequestSizes gives.
pub fn size_error(base: &[u8; BASE_SIZE], sizes: &[u32]) -> Option<(u32, u32)> {
    let kind = request_type(base);
    let size = be32(base, 4);
    if (1..=LAST_TYPE).contains(&kind) {
        let expected = sizes.get(kind as usize).copied()?;
        if expected != size {
            return Some((expected, size));
        }
    }
    None
}

/// SendBoolResponse's bytes: SNzbDownloadResponse (signature, struct size,
/// success, text length) then the text and its NUL.
pub fn bool_response(success: bool, text: &[u8]) -> Vec<u8> {
    let text = &text[..text.iter().position(|&b| b == 0).unwrap_or(text.len())];
    let mut out = Vec::with_capacity(16 + text.len() + 1);
    out.extend_from_slice(&(SIGNATURE as u32).to_be_bytes());
    out.extend_from_slice(&16u32.to_be_bytes());
    out.extend_from_slice(&(success as u32).to_be_bytes());
    out.extend_from_slice(&((text.len() + 1) as u32).to_be_bytes());
    out.extend_from_slice(text);
    out.push(0);
    out
}

/// ReceiveTrailing's check of the client's data length.
pub fn trailing_ok(len: i64, max: i64) -> bool {
    !(len < 0 || len > max)
}

/// One entry of a list response as the remote client reads it (the existing wire layout): `ints.len()` big-endian ints at `at` into
/// `ints` (host order), and the start of each string, whose length is in
/// field `fields[k]`, into `starts[k]`. Returns the offset after the entry
/// (the header and every length in `fields`), or None (outputs untouched)
/// when the entry or one of its strings, up to its NUL, doesn't fit in
/// `data`.
pub fn read_entry(data: &[u8], at: usize, ints: &mut [u32], fields: &[usize], starts: &mut [usize]) -> Option<usize> {
    let header = at.checked_add(ints.len().checked_mul(4)?)?;
    let raw = data.get(at..header)?;
    let value = |k: usize| u32::from_be_bytes(raw[4 * k..4 * k + 4].try_into().unwrap()) as usize;
    let mut next = header;
    for &field in fields {
        if field >= ints.len() {
            return None;
        }
        let start = next;
        // the string ends within the data
        crate::bytes::find_byte(data.get(start..)?, 0)?;
        next = next.checked_add(value(field))?;
    }
    if next > data.len() {
        return None;
    }
    let mut start = header;
    for (k, &field) in fields.iter().enumerate() {
        if let Some(out) = starts.get_mut(k) {
            *out = start;
        }
        start += value(field);
    }
    for (k, out) in ints.iter_mut().enumerate() {
        *out = value(k) as u32;
    }
    Some(next)
}

/// A string of an entry: `len` bytes at `data`, without a NUL (the NUL is
/// the encoder's). `data` may be null for length 0.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Text {
    pub data: *const u8,
    pub len: usize,
}

impl Text {
    pub const EMPTY: Text = Text { data: std::ptr::null(), len: 0 };

    pub fn new(bytes: &[u8]) -> Text {
        Text { data: bytes.as_ptr(), len: bytes.len() }
    }

    /// # Safety
    /// `data` is readable for `len` bytes (or null with `len` 0) while the
    /// result is used.
    pub unsafe fn bytes<'a>(&self) -> &'a [u8] {
        if self.len == 0 { &[] } else { std::slice::from_raw_parts(self.data, self.len) }
    }
}

/// The most ints in an entry's header (an NZB's) and the most strings.
pub const MAX_HEADER: usize = 17;
pub const MAX_STRINGS: usize = 5;

/// One kind of a list response's entries (List, Log, PostQueue, History):
/// a header of big-endian ints, among them the lengths (with their NULs) of
/// the strings that follow, each with its NUL, then zeros to a 4-byte
/// boundary counted in the length at `PAD`, as the C++ aligned the entries
/// (its buffer started aligned, so the offset decides). The values are in
/// host order here; fields the entry doesn't set are 0.
pub trait Entry: Copy {
    /// The ints in the header.
    const HEADER: usize;
    /// The header index of each string's length, in the strings' order.
    const FIELDS: &'static [usize];
    /// The index of the length that takes the padding.
    const PAD: usize;
    /// Sets the header's ints other than the strings' lengths (h is 0).
    fn header(&self, h: &mut [u32; MAX_HEADER]);
    fn texts(&self) -> &[Text];
    /// The entry as read: the header's ints and the strings.
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self;
}

/// An NZB of the queue (SNzbListResponseNzbEntry).
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct NzbEntry {
    pub id: u32,
    pub kind: u32,
    pub size_lo: u32,
    pub size_hi: u32,
    pub remaining_size_lo: u32,
    pub remaining_size_hi: u32,
    pub paused_size_lo: u32,
    pub paused_size_hi: u32,
    pub paused_count: u32,
    pub remaining_par_count: u32,
    pub priority: u32,
    pub matched: u32,
    /// filename, name, dest dir, category, queued filename
    pub texts: [Text; 5],
}

/// A parameter of an NZB (SNzbListResponsePPPEntry); `nzb_index` counts from 1.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct ParamEntry {
    pub nzb_index: u32,
    /// name, value
    pub texts: [Text; 2],
}

/// A file of an NZB (SNzbListResponseFileEntry); `nzb_index` counts from 1.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct FileEntry {
    pub id: u32,
    pub nzb_index: u32,
    pub size_lo: u32,
    pub size_hi: u32,
    pub remaining_size_lo: u32,
    pub remaining_size_hi: u32,
    pub paused: u32,
    pub filename_confirmed: u32,
    pub active_downloads: u32,
    pub matched: u32,
    /// subject, filename
    pub texts: [Text; 2],
}

/// A log message (SNzbLogResponseEntry).
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct LogEntry {
    pub id: u32,
    pub kind: u32,
    pub time: u32,
    pub texts: [Text; 1],
}

/// A post-processing job (SNzbPostQueueResponseEntry).
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct PostEntry {
    pub id: u32,
    pub stage: u32,
    pub stage_progress: u32,
    pub file_progress: u32,
    pub start_time: u32,
    pub stage_time: u32,
    /// nzb filename, name, dest dir, progress label
    pub texts: [Text; 4],
}

/// A history item (SNzbHistoryResponseEntry).
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct HistoryEntry {
    pub id: u32,
    pub kind: u32,
    pub time: u32,
    pub size_lo: u32,
    pub size_hi: u32,
    pub file_count: u32,
    pub par_status: u32,
    pub script_status: u32,
    pub url_status: u32,
    /// name
    pub texts: [Text; 1],
}

fn texts_from<const N: usize>(texts: &[Text; MAX_STRINGS]) -> [Text; N] {
    std::array::from_fn(|k| texts[k])
}

impl Entry for NzbEntry {
    const HEADER: usize = 17;
    const FIELDS: &'static [usize] = &[12, 13, 14, 15, 16];
    const PAD: usize = 16;
    fn header(&self, h: &mut [u32; MAX_HEADER]) {
        h[..12].copy_from_slice(&[self.id, self.kind, self.size_lo, self.size_hi, self.remaining_size_lo,
            self.remaining_size_hi, self.paused_size_lo, self.paused_size_hi, self.paused_count, self.remaining_par_count,
            self.priority, self.matched]);
    }
    fn texts(&self) -> &[Text] {
        &self.texts
    }
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self {
        NzbEntry { id: h[0], kind: h[1], size_lo: h[2], size_hi: h[3], remaining_size_lo: h[4], remaining_size_hi: h[5],
            paused_size_lo: h[6], paused_size_hi: h[7], paused_count: h[8], remaining_par_count: h[9], priority: h[10],
            matched: h[11], texts: *texts }
    }
}

impl Entry for ParamEntry {
    const HEADER: usize = 3;
    const FIELDS: &'static [usize] = &[1, 2];
    const PAD: usize = 2;
    fn header(&self, h: &mut [u32; MAX_HEADER]) {
        h[0] = self.nzb_index;
    }
    fn texts(&self) -> &[Text] {
        &self.texts
    }
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self {
        ParamEntry { nzb_index: h[0], texts: texts_from(texts) }
    }
}

impl Entry for FileEntry {
    const HEADER: usize = 12;
    const FIELDS: &'static [usize] = &[10, 11];
    const PAD: usize = 11;
    fn header(&self, h: &mut [u32; MAX_HEADER]) {
        h[..10].copy_from_slice(&[self.id, self.nzb_index, self.size_lo, self.size_hi, self.remaining_size_lo,
            self.remaining_size_hi, self.paused, self.filename_confirmed, self.active_downloads, self.matched]);
    }
    fn texts(&self) -> &[Text] {
        &self.texts
    }
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self {
        FileEntry { id: h[0], nzb_index: h[1], size_lo: h[2], size_hi: h[3], remaining_size_lo: h[4],
            remaining_size_hi: h[5], paused: h[6], filename_confirmed: h[7], active_downloads: h[8], matched: h[9],
            texts: texts_from(texts) }
    }
}

impl Entry for LogEntry {
    const HEADER: usize = 4;
    const FIELDS: &'static [usize] = &[3];
    const PAD: usize = 3;
    fn header(&self, h: &mut [u32; MAX_HEADER]) {
        h[..3].copy_from_slice(&[self.id, self.kind, self.time]);
    }
    fn texts(&self) -> &[Text] {
        &self.texts
    }
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self {
        LogEntry { id: h[0], kind: h[1], time: h[2], texts: texts_from(texts) }
    }
}

impl Entry for PostEntry {
    const HEADER: usize = 10;
    const FIELDS: &'static [usize] = &[6, 7, 8, 9];
    const PAD: usize = 9;
    fn header(&self, h: &mut [u32; MAX_HEADER]) {
        h[..6].copy_from_slice(&[self.id, self.stage, self.stage_progress, self.file_progress, self.start_time,
            self.stage_time]);
    }
    fn texts(&self) -> &[Text] {
        &self.texts
    }
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self {
        PostEntry { id: h[0], stage: h[1], stage_progress: h[2], file_progress: h[3], start_time: h[4],
            stage_time: h[5], texts: texts_from(texts) }
    }
}

impl Entry for HistoryEntry {
    const HEADER: usize = 10;
    const FIELDS: &'static [usize] = &[3];
    const PAD: usize = 3;
    fn header(&self, h: &mut [u32; MAX_HEADER]) {
        h[..3].copy_from_slice(&[self.id, self.kind, self.time]);
        h[4..10].copy_from_slice(&[self.size_lo, self.size_hi, self.file_count, self.par_status, self.script_status,
            self.url_status]);
    }
    fn texts(&self) -> &[Text] {
        &self.texts
    }
    fn from_wire(h: &[u32; MAX_HEADER], texts: &[Text; MAX_STRINGS]) -> Self {
        HistoryEntry { id: h[0], kind: h[1], time: h[2], size_lo: h[4], size_hi: h[5], file_count: h[6],
            par_status: h[7], script_status: h[8], url_status: h[9], texts: texts_from(texts) }
    }
}

// Check the POD layouts on both 32-bit and 64-bit targets. The text
// arrays follow the integers at the next pointer-aligned offset.
const _: () = {
    use std::mem::{align_of, offset_of, size_of};
    const fn texts_at(ints: usize) -> usize {
        let align = align_of::<Text>();
        (4 * ints + align - 1) & !(align - 1)
    }
    assert!(size_of::<Text>() == 2 * size_of::<usize>());
    assert!(offset_of!(NzbEntry, texts) == texts_at(12));
    assert!(offset_of!(ParamEntry, texts) == texts_at(1));
    assert!(offset_of!(FileEntry, texts) == texts_at(10));
    assert!(offset_of!(LogEntry, texts) == texts_at(3));
    assert!(offset_of!(PostEntry, texts) == texts_at(6));
    assert!(offset_of!(HistoryEntry, texts) == texts_at(9));
    assert!(size_of::<NzbEntry>() == texts_at(12) + 5 * size_of::<Text>());
    assert!(size_of::<ParamEntry>() == texts_at(1) + 2 * size_of::<Text>());
    assert!(size_of::<FileEntry>() == texts_at(10) + 2 * size_of::<Text>());
    assert!(size_of::<LogEntry>() == texts_at(3) + size_of::<Text>());
    assert!(size_of::<PostEntry>() == texts_at(6) + 4 * size_of::<Text>());
    assert!(size_of::<HistoryEntry>() == texts_at(9) + size_of::<Text>());
};

/// The size of one entry with its strings and padding: the offset after the
/// header is the same for every entry, so each is 4-aligned by itself.
/// Saturates.
unsafe fn entry_len<E: Entry>(entry: &E) -> usize {
    let mut n = 4 * E::HEADER;
    for text in entry.texts() {
        n = n.saturating_add(text.len).saturating_add(1);
    }
    n.saturating_add(3) & !3
}

/// The bytes `encode` writes for `entries`, saturating above MAX_RESPONSE.
///
/// # Safety
/// The entries' strings are readable for their lengths.
pub unsafe fn encoded_len<E: Entry>(entries: &[E]) -> u64 {
    entries.iter().fold(0u64, |n, e| n.saturating_add(entry_len(e) as u64))
}

/// Writes the entries into `out`, which is `encoded_len` bytes at least:
/// the header's ints big-endian, each string's length with its NUL in its
/// field, the strings with their NULs, and zeros to a 4-byte boundary
/// counted in the field at `E::PAD`. Returns the bytes written, all of them
/// initialized (the rest of `out` isn't touched).
///
/// # Safety
/// The entries' strings are readable for their lengths, each less than 2^31.
pub unsafe fn encode<E: Entry>(entries: &[E], out: &mut [MaybeUninit<u8>]) -> usize {
    let base = out.as_mut_ptr().cast::<u8>();
    let mut at = 0;
    for entry in entries {
        let mut h = [0u32; MAX_HEADER];
        entry.header(&mut h);
        let texts = entry.texts();
        let mut body = 4 * E::HEADER;
        for (text, &field) in texts.iter().zip(E::FIELDS) {
            h[field] = (text.len + 1) as u32;
            body += text.len + 1;
        }
        let pad = body.wrapping_neg() & 3;
        h[E::PAD] = h[E::PAD].wrapping_add(pad as u32);
        assert!(body + pad <= out.len() - at, "the entries don't fit the response");
        let mut p = base.add(at);
        for value in &h[..E::HEADER] {
            p.cast::<u32>().write_unaligned(value.to_be());
            p = p.add(4);
        }
        for text in texts {
            // A null pointer is permitted for an empty string, but even a
            // zero-byte copy requires non-null pointers.
            if text.len != 0 {
                std::ptr::copy_nonoverlapping(text.data, p, text.len);
            }
            p.add(text.len).write(0);
            p = p.add(text.len + 1);
        }
        // Padding is at most three bytes. Explicit stores avoid a libc
        // memset call for each entry while initializing every padding byte.
        if pad & 2 != 0 {
            p.cast::<u16>().write_unaligned(0);
        }
        if pad & 1 != 0 {
            p.add(pad - 1).write(0);
        }
        at += body + pad;
    }
    at
}

/// The largest response (an int, as the C++ counted it).
pub const MAX_RESPONSE: u64 = i32::MAX as u64;

/// EditQueue's check of the client's counts and lengths against each other
/// and the trailing data's length (64-bit sums).
pub fn edit_sizes_ok(ids: i32, names: i32, names_len: i32, text_len: i32, data_len: u32) -> bool {
    ids >= 0
        && names >= 0
        && text_len >= 0
        && names_len >= 0
        && ids <= 10_000_000
        && names <= names_len
        && i64::from(ids) * 4 + i64::from(text_len) + i64::from(names_len) == i64::from(data_len)
}

/// EditQueue's trailing data after the size check: the text, then
/// `ids_out.len()` big-endian ids, then `names` NUL-terminated names to the
/// data's end. Checks that the parts fit and that each name ends within the
/// names' part, then writes the ids to `ids_out` in host order; false (with
/// `ids_out` untouched) when they don't. Nothing is allocated, whatever the
/// counts.
pub fn edit_split(data: &[u8], text_len: usize, ids_out: &mut [u32], names: usize) -> bool {
    let Some(ids_end) = ids_out.len().checked_mul(4).and_then(|n| n.checked_add(text_len)) else { return false };
    let Some(id_bytes) = data.get(text_len..ids_end) else { return false };
    let mut at = ids_end;
    for _ in 0..names {
        let Some(len) = data.get(at..).and_then(|rest| crate::bytes::find_byte(rest, 0)) else { return false };
        at += len + 1;
    }
    for (out, id) in ids_out.iter_mut().zip(id_bytes.as_chunks::<4>().0) {
        *out = u32::from_be_bytes(*id);
    }
    true
}

/// Download's test of the request's content for a URL to fetch rather than
/// an NZB: "http:/" or "https:/" in any case, as strncasecmp compared them.
pub fn is_url(content: &[u8]) -> bool {
    let starts = |prefix: &[u8]| content.get(..prefix.len()).is_some_and(|head| head.eq_ignore_ascii_case(prefix));
    starts(b"http:/") || starts(b"https:/")
}

/// The C-string URL predicate without scanning the complete NZB body.
/// At each byte, a mismatch (including NUL) stops the read before the next
/// byte. At most seven prefix bytes are read.
///
/// # Safety
/// content is null or points to a readable NUL-terminated string.
pub unsafe fn is_url_cstr(content: *const u8) -> bool {
    if content.is_null() {
        return false;
    }
    for (at, &expected) in b"http".iter().enumerate() {
        if !content.add(at).read().eq_ignore_ascii_case(&expected) {
            return false;
        }
    }
    let next = content.add(4).read();
    if next == b':' {
        content.add(5).read() == b'/'
    } else if next.eq_ignore_ascii_case(&b's') {
        content.add(5).read() == b':' && content.add(6).read() == b'/'
    } else {
        false
    }
}

/// One entry of a list response as the remote client reads it (the
/// reverse of `encode`): the entry at `at`, its strings pointing into
/// `data` (up to their NULs), and the offset after it (the header and every
/// string's length in its field). None when the entry, or one of its strings
/// up to its NUL, doesn't fit in `data`. With `LENS` the strings' `len` is
/// their length up to the NUL (the data is searched for it); without, it
/// is 0 and the NUL is looked for at the end of the string's field first,
/// where an encoder puts it: the strings are used as C strings.
pub fn read<E: Entry, const LENS: bool>(data: &[u8], at: usize) -> Option<(E, usize)> {
    let header_end = at.checked_add(4 * E::HEADER)?;
    let raw = data.get(at..header_end)?;
    let mut h = [0u32; MAX_HEADER];
    for (value, word) in h.iter_mut().zip(raw.as_chunks::<4>().0) {
        *value = u32::from_be_bytes(*word);
    }
    // Validate the complete declared entry once. Every subsequent string
    // start/end is a nonnegative prefix of this checked total, so it fits
    // without repeating the offset and remaining-length checks per field.
    let end = E::FIELDS.iter().take(MAX_STRINGS).try_fold(header_end, |end, &field| end.checked_add(h[field] as usize))?;
    if end > data.len() {
        return None;
    }
    let mut texts = [Text::EMPTY; MAX_STRINGS];
    let mut next = header_end;
    for (text, &field) in texts.iter_mut().zip(E::FIELDS) {
        // SAFETY: next is a prefix of the checked total end <= data.len().
        // Keep the whole remainder for NUL searches, including malformed
        // length fields whose terminator follows their declared extent.
        let rest = unsafe { data.get_unchecked(next..) };
        let field_len = h[field] as usize;
        text.data = rest.as_ptr();
        if LENS {
            text.len = crate::bytes::find_byte(rest, 0)?;
        } else if field_len == 0 || unsafe { *rest.get_unchecked(field_len - 1) } != 0 {
            // SAFETY above: with field_len > 0, next + field_len <= end.
            crate::bytes::find_byte(rest, 0)?;
        }
        next += field_len;
    }
    Some((E::from_wire(&h, &texts), end))
}

/// Up to `max` entries read from `*at` on into `out` (as `read` does
/// without lengths, the strings pointing into `data`), `*at` after them.
/// Fewer than `max` when an entry doesn't fit in `data`: the count read,
/// `*at` after them.
///
/// # Safety
/// `out` is writable for `max` entries (it may be uninitialized).
pub unsafe fn read_many<E: Entry>(data: &[u8], at: &mut usize, out: *mut E, max: usize) -> usize {
    for k in 0..max {
        let Some((entry, next)) = read::<E, false>(data, *at) else { return k };
        out.add(k).write(entry);
        *at = next;
    }
    max
}

fn append_listing(out: &mut Vec<u8>, bytes: &[u8]) {
    crate::util::reserve_bytes(out, bytes.len());
    out.extend_from_slice(bytes);
}

fn push_listing(out: &mut Vec<u8>, byte: u8) {
    crate::util::reserve_bytes(out, 1);
    out.push(byte);
}

/// An int as printf's %i printed it.
fn push_int(out: &mut Vec<u8>, value: i32) {
    let mut digits = [0u8; 11];
    let mut at = digits.len();
    let mut rest = value.unsigned_abs();
    loop {
        at -= 1;
        digits[at] = b'0' + (rest % 10) as u8;
        rest /= 10;
        if rest == 0 {
            break;
        }
    }
    if value < 0 {
        at -= 1;
        digits[at] = b'-';
    }
    append_listing(out, &digits[at..]);
}

const MAX_LISTING_INITIAL_CAPACITY: usize = 1024 * 1024;

fn listing_capacity(input_len: usize) -> usize {
    // Preserve the estimate for ordinary responses, but avoid an eager
    // reservation above the 32-bit Vec limit for a large received buffer.
    // Formatting grows the buffer only when output actually needs it.
    input_len.saturating_add(input_len / 2).saturating_add(64)
        .min(MAX_LISTING_INITIAL_CAPACITY)
}

/// The lines of a listing: each of the first `count` entries `data` holds
/// from its start, through `line`, which adds the entry's text and its
/// newline or nothing. The listing ends at an entry that doesn't fit the
/// data, whatever `count` says.
fn listing<E: Entry>(data: &[u8], count: u32, line: impl Fn(&mut Vec<u8>, &E)) -> Vec<u8> {
    // a line is about as long as its entry; the buffer grows if it isn't
    let mut out = Vec::with_capacity(listing_capacity(data.len()));
    let mut at = 0;
    for _ in 0..count {
        let Some((entry, next)) = read::<E, true>(data, at) else { break };
        line(&mut out, &entry);
        at = next;
    }
    // into_buf appends the FFI terminator after this return. Prevent that
    // final byte from triggering an unrepresentable amortized doubling.
    crate::util::reserve_bytes(&mut out, 1);
    out
}

/// Message::EKind's labels in the remote client's log listing.
const LOG_LABELS: [&[u8]; 5] = [b"[INFO] ", b"[WARNING] ", b"[ERROR] ", b"[DEBUG] ", b"[DETAIL] "];

/// The remote client's log listing: "[INFO] text" and so on for each
/// message; an unknown kind has no line.
pub fn log_listing(data: &[u8], count: u32) -> Vec<u8> {
    listing(data, count, |out, e: &LogEntry| {
        if let Some(label) = LOG_LABELS.get(e.kind as usize) {
            append_listing(out, label);
            // SAFETY: the text points into `data`, up to a NUL within it
            append_listing(out, unsafe { e.texts[0].bytes() });
            push_listing(out, b'\n');
        }
    })
}

/// PostInfo::EStage's names in the post-processing listing.
const STAGE_NAMES: [&[u8]; 15] = [b"", b", Loading Pars", b", Verifying source files", b", Repairing",
    b", Verifying repaired files", b", Par-Renaming", b", Rar-Renaming", b", Unpacking", b", Cleaning up", b", Moving",
    b", Post-unpack renaming", b", Executing postprocess-script", b"", b", Post-download renaming",
    b", Repairing from duplicates"];
/// PostInfo::ptExecutingScript.
const EXECUTING_SCRIPT: u32 = 11;

/// The remote client's post-processing listing: "[id] name, stage, n%" (no
/// percentage while a script runs or before progress). An unknown stage has
/// no name.
pub fn post_queue_listing(data: &[u8], count: u32) -> Vec<u8> {
    listing(data, count, |out, e: &PostEntry| {
        push_listing(out, b'[');
        push_int(out, e.id as i32);
        append_listing(out, b"] ");
        // SAFETY: the name points into `data`, up to a NUL within it
        append_listing(out, unsafe { e.texts[1].bytes() });
        append_listing(out, STAGE_NAMES.get(e.stage as usize).copied().unwrap_or(b""));
        let progress = e.stage_progress as i32;
        if progress > 0 && e.stage != EXECUTING_SCRIPT {
            append_listing(out, b", ");
            push_int(out, progress / 10);
            push_listing(out, b'%');
        }
        push_listing(out, b'\n');
    })
}

/// The remote client's history listing: "[id] name (...)" (HistoryInfo::EKind:
/// 1 an NZB, 2 a URL, 3 a hidden duplicate; no line for other kinds).
/// Unknown statuses have no text.
pub fn history_listing(data: &[u8], count: u32) -> Vec<u8> {
    const PAR: [&[u8]; 6] = [b"", b"", b", Par failed", b", Par successful", b", Repair possible", b", Repair needed"];
    const SCRIPT: [&[u8]; 4] = [b"", b", Script status unknown", b", Script failed", b", Script successful"];
    const URL: [&[u8]; 7] =
        [b"", b"", b"Url download successful", b"Url download failed", b"", b"Nzb scan skipped", b"Nzb scan failed"];
    let text = |table: &[&'static [u8]], k: u32| table.get(k as usize).copied().unwrap_or(b"");
    listing(data, count, |out, e: &HistoryEntry| {
        if !matches!(e.kind, 1..=3) {
            return;
        }
        push_listing(out, b'[');
        push_int(out, e.id as i32);
        append_listing(out, b"] ");
        // SAFETY: the name points into `data`, up to a NUL within it
        append_listing(out, unsafe { e.texts[0].bytes() });
        if e.kind == 2 {
            append_listing(out, b" (URL, ");
            append_listing(out, text(&URL, e.url_status));
        } else {
            let hidden = e.kind == 3;
            append_listing(out, b" (");
            if hidden {
                append_listing(out, b"Hidden, ");
            } else {
                // BString<100>: never cut, an int's text is short
                push_int(out, e.file_count as i32);
                append_listing(out, b" files, ");
            }
            crate::util::format_size_into(out, ((e.size_hi as i64) << 32) + e.size_lo as i64);
            if !hidden {
                append_listing(out, text(&PAR, e.par_status));
                append_listing(out, text(&SCRIPT, e.script_status));
            }
        }
        append_listing(out, b")\n");
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The credential check with the control names as C strings.




    fn base(kind: u32, size: u32, user: &[u8], password: &[u8]) -> [u8; BASE_SIZE] {
        let mut b = [0u8; BASE_SIZE];
        b[..4].copy_from_slice(&(SIGNATURE as u32).to_be_bytes());
        b[4..8].copy_from_slice(&size.to_be_bytes());
        b[8..12].copy_from_slice(&kind.to_be_bytes());
        b[USER_AT..USER_AT + user.len()].copy_from_slice(user);
        b[PASSWORD_AT..PASSWORD_AT + password.len()].copy_from_slice(password);
        b
    }

    #[test]
    fn credentials() {
        assert!(credentials_ok(&base(1, 0, b"nzbget", b"tegbzn6789"), b"nzbget", b"tegbzn6789"));
        assert!(credentials_ok(&base(1, 0, b"anyone", b"tegbzn6789"), b"", b"tegbzn6789"));
        assert!(!credentials_ok(&base(1, 0, b"nzbget", b"wrong"), b"nzbget", b"tegbzn6789"));
        assert!(!credentials_ok(&base(1, 0, b"other", b"tegbzn6789"), b"nzbget", b"tegbzn6789"));
        // an unterminated user name runs on into the password, as strcmp read it
        let full = [b'u'; PASSWORD_SIZE];
        let b = base(1, 0, &full, b"pw");
        assert!(!credentials_ok(&b, &full, b"pw"));
        assert!(credentials_ok(&b, &[&full[..], b"pw"].concat(), b"pw"));
        // No read beyond the base when neither field is terminated. The old
        // strcmp could read out of bounds here; the bounded port stops here.
        let b = base(1, 0, &full, &full);
        assert!(credentials_ok(&b, &[b'u'; 64], &full));
        assert!(!credentials_ok(&b, b"", &[b'u'; 33]));
        assert!(!credentials_ok(&b, b"", &[b'u'; 31]));
    }

    #[test]
    fn sizes_and_names() {
        let sizes: Vec<u32> = (0..=LAST_TYPE).map(|t| 100 + t).collect();
        assert_eq!(size_error(&base(3, 103, b"", b""), &sizes), None);
        assert_eq!(size_error(&base(3, 99, b"", b""), &sizes), Some((103, 99)));
        assert_eq!(size_error(&base(0, 99, b"", b""), &sizes), None);
        assert_eq!(size_error(&base(15, 99, b"", b""), &sizes), None);
        assert_eq!(request_name(14), c"History");
        assert_eq!(request_name(15), c"Unknown");
        assert_eq!(request_name(u32::MAX), c"Unknown");
        for kind in [0x7fff_ffff, 0x8000_0000, u32::MAX] {
            assert_eq!(size_error(&base(kind, 99, b"", b""), &sizes), None);
            assert_eq!(request_name(kind), c"Unknown");
        }
        assert_eq!(size_error(&base(14, u32::MAX, b"", b""), &sizes), Some((114, u32::MAX)));
    }

    #[test]
    fn entries() {
        let mut buf = Vec::new();
        reference_entry(&mut buf, &[7, 0, 9], &[(b"ab", 1)], 1);
        assert_eq!(buf, [0, 0, 0, 7, 0, 0, 0, 4, 0, 0, 0, 9, b'a', b'b', 0, 0]);
        // 33 bytes: 3 bytes of padding, counted in the empty string's length
        reference_entry(&mut buf, &[1, 0, 0], &[(b"xyz", 1), (b"", 2)], 2);
        assert_eq!(&buf[16..], [0, 0, 0, 1, 0, 0, 0, 4, 0, 0, 0, 4, b'x', b'y', b'z', 0, 0, 0, 0, 0]);

        // a log entry, by hand
        let log = [LogEntry { id: 7, kind: 2, time: 99, texts: [Text::new(b"ab")] }];
        assert_eq!(unsafe { encoded_len(&log) }, 20);
        let out = encode_all(&log);
        assert_eq!(out, [0, 0, 0, 7, 0, 0, 0, 2, 0, 0, 0, 99, 0, 0, 0, 3 + 1, b'a', b'b', 0, 0]);
        // nothing, an empty text (a NULL pointer too)
        assert_eq!(unsafe { encoded_len::<LogEntry>(&[]) }, 0);
        assert_eq!(unsafe { encode::<LogEntry>(&[], &mut []) }, 0);
        assert!(encode_all::<LogEntry>(&[]).is_empty());
        let empty = [LogEntry { id: 1, kind: 0, time: 0, texts: [Text::EMPTY] }];
        assert_eq!(unsafe { encoded_len(&empty) }, 20);
        let out = encode_all(&empty);
        assert_eq!(out, [0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1 + 3, 0, 0, 0, 0]);
        // The saturating sum of lengths no response can hold.
        let huge = [LogEntry { id: 1, kind: 0, time: 0, texts: [Text { data: std::ptr::null(), len: usize::MAX }] }; 2];
        assert!(unsafe { encoded_len(&huge) } > MAX_RESPONSE);
    }

    /// A small deterministic generator.
    struct Random(u64);

    impl Random {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            self.0
        }
        fn below(&mut self, n: usize) -> usize {
            (self.next() % n as u64) as usize
        }
        fn int(&mut self) -> u32 {
            if self.below(3) == 0 { self.next() as u32 } else { self.below(20) as u32 }
        }
        /// A text of any length 0..=9 (every padding), sometimes long, never a NUL.
        fn text(&mut self) -> Vec<u8> {
            let n = if self.below(8) == 0 { self.below(300) } else { self.below(10) };
            (0..n).map(|_| 1 + self.below(255) as u8).collect()
        }
    }

    /// The entry kinds with the encoder's reference (the old one-entry-at-a-time
    /// layout written out from the wire's order of ints) and the entries as
    /// they come back from the wire.
    fn reference_entry(buf: &mut Vec<u8>, ints: &[u32], strings: &[(&[u8], usize)], pad_field: usize) {
        let start = buf.len();
        let mut fields = ints.to_vec();
        for &(text, field) in strings {
            fields[field] = (text.len() + 1) as u32;
        }
        buf.resize(start + fields.len() * 4, 0);
        for &(text, _) in strings {
            buf.extend_from_slice(text);
            buf.push(0);
        }
        let pad = (4 - buf.len() % 4) % 4;
        if pad > 0 {
            buf.resize(buf.len() + pad, 0);
            fields[pad_field] += pad as u32;
        }
        for (k, f) in fields.iter().enumerate() {
            buf[start + 4 * k..start + 4 * k + 4].copy_from_slice(&f.to_be_bytes());
        }
    }

    fn encode_all<E: Entry>(entries: &[E]) -> Vec<u8> {
        unsafe {
            let n = encoded_len(entries) as usize;
            // not zeroed: every byte must be written by encode
            let mut out: Vec<u8> = Vec::with_capacity(n);
            out.spare_capacity_mut().fill(MaybeUninit::new(0xAA));
            assert_eq!(encode(entries, &mut out.spare_capacity_mut()[..n]), n);
            out.set_len(n);
            out
        }
    }

    #[test]
    fn batch_encoders_match_the_entry_by_entry_encoder() {
        let mut r = Random(88172645463325252);
        for round in 0..400 {
            let n = r.below(6);
            // NZBs
            let (mut texts, mut expected) = (Vec::new(), Vec::new());
            let mut nzbs = Vec::new();
            for _ in 0..n {
                let ints: Vec<u32> = (0..12).map(|_| r.int()).collect();
                let strings: Vec<Vec<u8>> = (0..5).map(|_| r.text()).collect();
                let mut wire = ints.clone();
                wire.extend([0; 5]);
                let pairs: Vec<(&[u8], usize)> = strings.iter().enumerate().map(|(k, s)| (&s[..], 12 + k)).collect();
                reference_entry(&mut expected, &wire, &pairs, 16);
                nzbs.push(NzbEntry { id: ints[0], kind: ints[1], size_lo: ints[2], size_hi: ints[3],
                    remaining_size_lo: ints[4], remaining_size_hi: ints[5], paused_size_lo: ints[6], paused_size_hi: ints[7],
                    paused_count: ints[8], remaining_par_count: ints[9], priority: ints[10], matched: ints[11],
                    texts: std::array::from_fn(|k| Text::new(&strings[k])) });
                texts.push(strings);
            }
            assert_eq!(encode_all(&nzbs), expected, "nzbs, round {round}");
            // parameters
            let (mut texts, mut expected, mut params) = (Vec::new(), Vec::new(), Vec::new());
            for _ in 0..n {
                let (index, a, b) = (r.int(), r.text(), r.text());
                reference_entry(&mut expected, &[index, 0, 0], &[(&a, 1), (&b, 2)], 2);
                texts.push((a, b));
                params.push(index);
            }
            let params: Vec<ParamEntry> = params.iter().zip(&texts)
                .map(|(&i, (a, b))| ParamEntry { nzb_index: i, texts: [Text::new(a), Text::new(b)] }).collect();
            assert_eq!(encode_all(&params), expected, "params, round {round}");
            // files
            let (mut texts, mut expected, mut ints_of) = (Vec::new(), Vec::new(), Vec::new());
            for _ in 0..n {
                let ints: Vec<u32> = (0..10).map(|_| r.int()).collect();
                let (a, b) = (r.text(), r.text());
                let mut wire = ints.clone();
                wire.extend([0; 2]);
                reference_entry(&mut expected, &wire, &[(&a, 10), (&b, 11)], 11);
                texts.push((a, b));
                ints_of.push(ints);
            }
            let files: Vec<FileEntry> = ints_of.iter().zip(&texts).map(|(i, (a, b))| FileEntry { id: i[0], nzb_index: i[1],
                size_lo: i[2], size_hi: i[3], remaining_size_lo: i[4], remaining_size_hi: i[5], paused: i[6],
                filename_confirmed: i[7], active_downloads: i[8], matched: i[9], texts: [Text::new(a), Text::new(b)] }).collect();
            assert_eq!(encode_all(&files), expected, "files, round {round}");
            // log
            let (mut texts, mut expected, mut ints_of) = (Vec::new(), Vec::new(), Vec::new());
            for _ in 0..n {
                let ints: Vec<u32> = (0..3).map(|_| r.int()).collect();
                let a = r.text();
                reference_entry(&mut expected, &[ints[0], ints[1], ints[2], 0], &[(&a, 3)], 3);
                texts.push(a);
                ints_of.push(ints);
            }
            let log: Vec<LogEntry> = ints_of.iter().zip(&texts)
                .map(|(i, a)| LogEntry { id: i[0], kind: i[1], time: i[2], texts: [Text::new(a)] }).collect();
            assert_eq!(encode_all(&log), expected, "log, round {round}");
            // post-queue
            let (mut texts, mut expected, mut ints_of) = (Vec::new(), Vec::new(), Vec::new());
            for _ in 0..n {
                let ints: Vec<u32> = (0..6).map(|_| r.int()).collect();
                let t: Vec<Vec<u8>> = (0..4).map(|_| r.text()).collect();
                let mut wire = ints.clone();
                wire.extend([0; 4]);
                let pairs: Vec<(&[u8], usize)> = t.iter().enumerate().map(|(k, s)| (&s[..], 6 + k)).collect();
                reference_entry(&mut expected, &wire, &pairs, 9);
                texts.push(t);
                ints_of.push(ints);
            }
            let jobs: Vec<PostEntry> = ints_of.iter().zip(&texts).map(|(i, t)| PostEntry { id: i[0], stage: i[1],
                stage_progress: i[2], file_progress: i[3], start_time: i[4], stage_time: i[5],
                texts: std::array::from_fn(|k| Text::new(&t[k])) }).collect();
            assert_eq!(encode_all(&jobs), expected, "post-queue, round {round}");
            // history: the name's length is the fourth int
            let (mut texts, mut expected, mut ints_of) = (Vec::new(), Vec::new(), Vec::new());
            for _ in 0..n {
                let ints: Vec<u32> = (0..9).map(|_| r.int()).collect();
                let a = r.text();
                reference_entry(&mut expected,
                    &[ints[0], ints[1], ints[2], 0, ints[3], ints[4], ints[5], ints[6], ints[7], ints[8]], &[(&a, 3)], 3);
                texts.push(a);
                ints_of.push(ints);
            }
            let history: Vec<HistoryEntry> = ints_of.iter().zip(&texts).map(|(i, a)| HistoryEntry { id: i[0], kind: i[1],
                time: i[2], size_lo: i[3], size_hi: i[4], file_count: i[5], par_status: i[6], script_status: i[7],
                url_status: i[8], texts: [Text::new(a)] }).collect();
            assert_eq!(encode_all(&history), expected, "history, round {round}");
        }
    }

    #[test]
    fn every_padding_lands_in_the_last_length() {
        // the strings' lengths 0..=7 of a log entry: header 16, text, NUL, zeros to 4
        for len in 0..8usize {
            let text = vec![b'x'; len];
            let out = encode_all(&[LogEntry { id: 1, kind: 2, time: 3, texts: [Text::new(&text)] }]);
            let padded = (len + 1 + 3) & !3;
            assert_eq!(out.len(), 16 + padded);
            assert_eq!(&out[12..16], &(padded as u32).to_be_bytes());
            assert_eq!(&out[16..16 + len], &text[..]);
            assert!(out[16 + len..].iter().all(|&b| b == 0));
        }
        // padding of a history entry sits in the name's length, in the middle of the header
        let out = encode_all(&[HistoryEntry { id: 1, kind: 2, time: 3, size_lo: 4, size_hi: 5, file_count: 6, par_status: 7,
            script_status: 8, url_status: 9, texts: [Text::new(b"abcd")] }]);
        assert_eq!(&out[..40], [0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0, 8, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 6, 0, 0, 0, 7,
            0, 0, 0, 8, 0, 0, 0, 9]);
        assert_eq!(&out[40..], b"abcd\0\0\0\0");
    }

    #[test]
    fn edits() {
        assert!(edit_sizes_ok(2, 1, 3, 4, 15));
        assert!(!edit_sizes_ok(2, 1, 3, 4, 16));
        assert!(!edit_sizes_ok(-1, 0, 0, 4, 0));
        assert!(!edit_sizes_ok(0, 2, 1, 0, 1));
        assert!(!edit_sizes_ok(10_000_001, 0, 0, 0, 40_000_004));
        assert!(!edit_sizes_ok(i32::MAX, 0, 0, i32::MAX, u32::MAX));
        assert!(edit_sizes_ok(0, 0, 0, 0, 0));
        let data = b"tx\0\0\0\0\0\x07\xff\xff\xff\xfeab\0\0c\0";
        let mut ids = [0u32; 2];
        assert!(edit_split(data, 4, &mut ids, 3));
        assert_eq!(ids, [7, 0xffff_fffe]);
        // a name running to the end, or past it: the ids stay untouched
        let mut ids = [1u32; 2];
        assert!(!edit_split(&data[..17], 4, &mut ids, 3));
        assert!(!edit_split(data, 4, &mut ids, 4));
        assert!(!edit_split(&data[..8], 4, &mut ids, 0));
        assert_eq!(ids, [1, 1]);
        assert!(edit_split(b"", 0, &mut [], 0));
        assert!(!edit_split(b"", 1, &mut [], 0));
    }

    #[test]
    fn urls() {
        for yes in [&b"http://x"[..], b"HTTPS://x", b"http:/", b"hTtPs:/", b"http:/\0"] {
            assert!(is_url(yes), "{yes:?}");
        }
        for no in [&b""[..], b"http:", b"https:", b"ftp://x", b"<?xml", b"http\0:/", b"https:\\"] {
            assert!(!is_url(no), "{no:?}");
        }
    }

    /// The entries as read, strings as bytes.
    fn log_texts(data: &[u8], entries: &[LogEntry]) -> Vec<Vec<u8>> {
        let _ = data;
        entries.iter().map(|e| unsafe { e.texts[0].bytes() }.to_vec()).collect()
    }

    #[test]
    fn client_entries() {
        // the encoder's output reads back
        let nzb = |id: u32, texts: &[&[u8]; 5]| NzbEntry { id, kind: 1, size_lo: 2, size_hi: 3, remaining_size_lo: 4,
            remaining_size_hi: 5, paused_size_lo: 6, paused_size_hi: 7, paused_count: 8, remaining_par_count: 9, priority: 10,
            matched: 11, texts: std::array::from_fn(|k| Text::new(texts[k])) };
        let buf = encode_all(&[nzb(7, &[b"ab", b"", b"xyz", b"1234", b"x"]), nzb(8, &[b"", b"", b"", b"", b""])]);
        let (first, next) = read::<NzbEntry, true>(&buf, 0).unwrap();
        assert_eq!((first.id, first.kind, first.size_lo, first.size_hi, first.remaining_size_lo, first.remaining_size_hi,
            first.paused_size_lo, first.paused_size_hi, first.paused_count, first.remaining_par_count, first.priority,
            first.matched), (7, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11));
        let strings: Vec<&[u8]> = first.texts.iter().map(|t| unsafe { t.bytes() }).collect();
        assert_eq!(strings, [&b"ab"[..], b"", b"xyz", b"1234", b"x"]);
        // the first text starts right after the 68-byte header
        assert_eq!(first.texts[0].data, buf[68..].as_ptr());
        let (second, end) = read::<NzbEntry, true>(&buf, next).unwrap();
        assert_eq!((second.id, end), (8, buf.len()));
        assert!(second.texts.iter().all(|t| t.len == 0));

        // read_many: stops at the first entry that doesn't fit, with the ones before it read
        let mut out = [std::mem::MaybeUninit::<NzbEntry>::uninit(); 3];
        let mut at = 0;
        assert_eq!(unsafe { read_many(&buf, &mut at, out.as_mut_ptr().cast::<NzbEntry>(), 3) }, 2);
        assert_eq!(at, buf.len());
        assert_eq!(unsafe { out[1].assume_init() }.id, 8);
        at = 0;
        assert_eq!(unsafe { read_many(&buf[..buf.len() - 4], &mut at, out.as_mut_ptr().cast::<NzbEntry>(), 3) }, 1);
        assert_eq!(at, next);
        at = 0;
        assert_eq!(unsafe { read_many(&buf, &mut at, out.as_mut_ptr().cast::<NzbEntry>(), 1) }, 1);
        assert_eq!(at, next);
        assert_eq!(unsafe { read_many(&buf, &mut at, out.as_mut_ptr().cast::<NzbEntry>(), 0) }, 0);
        assert_eq!(at, next);
    }

    /// The previous reader, an entry at a time: the oracle of `read` for
    /// data that is cut or made up.
    fn reference_read(data: &[u8], at: usize, nints: usize, fields: &[usize]) -> Option<(Vec<u32>, Vec<usize>, usize)> {
        let header = at.checked_add(nints.checked_mul(4)?)?;
        let raw = data.get(at..header)?;
        let value = |k: usize| u32::from_be_bytes(raw[4 * k..4 * k + 4].try_into().unwrap()) as usize;
        let mut next = header;
        for &field in fields {
            let start = next;
            data.get(start..)?.iter().position(|&b| b == 0)?;
            next = next.checked_add(value(field))?;
        }
        if next > data.len() {
            return None;
        }
        let mut start = header;
        let mut starts = Vec::new();
        for &field in fields {
            starts.push(start);
            start += value(field);
        }
        Some(((0..nints).map(|k| value(k) as u32).collect(), starts, next))
    }

    #[test]
    fn reading_matches_the_entry_by_entry_reader_on_cut_and_made_up_data() {
        let mut r = Random(1234567);
        for round in 0..3000 {
            // a real entry, cut anywhere, or random bytes with a small-length header
            let text = r.text();
            let history = [HistoryEntry { id: r.int(), kind: 1, time: 5, size_lo: 6, size_hi: 7, file_count: 8, par_status: 9,
                script_status: 10, url_status: 11, texts: [Text::new(&text)] }];
            let mut data = encode_all(&history);
            match r.below(3) {
                0 => data.truncate(r.below(data.len() + 1)),
                1 => {
                    let k = r.below(data.len());
                    data[k] = r.next() as u8;
                }
                _ => {
                    data = (0..r.below(60)).map(|_| if r.below(3) == 0 { r.next() as u8 } else { 0 }).collect();
                }
            }
            let at = if r.below(4) == 0 { r.below(data.len() + 3) } else { 0 };
            let ours = read::<HistoryEntry, true>(&data, at);
            // without lengths: the same entries, with the NUL looked for at the end of the field first
            match (&ours, read::<HistoryEntry, false>(&data, at)) {
                (None, None) => {}
                (Some((a, next)), Some((b, next2))) => {
                    assert_eq!(*next, next2, "round {round}");
                    assert_eq!((a.id, a.kind, a.time, a.size_lo, a.size_hi, a.file_count, a.par_status, a.script_status,
                        a.url_status), (b.id, b.kind, b.time, b.size_lo, b.size_hi, b.file_count, b.par_status,
                        b.script_status, b.url_status));
                    assert_eq!((a.texts[0].data, b.texts[0].len), (b.texts[0].data, 0));
                }
                _ => panic!("round {round}: the flavors differ on {data:?} at {at}"),
            }
            let theirs = reference_read(&data, at, 10, &[3]);
            match (ours, theirs) {
                (None, None) => {}
                (Some((e, next)), Some((ints, starts, next2))) => {
                    assert_eq!(next, next2, "round {round}");
                    assert_eq!([e.id, e.kind, e.time, e.size_lo, e.size_hi, e.file_count, e.par_status, e.script_status,
                        e.url_status], [ints[0], ints[1], ints[2], ints[4], ints[5], ints[6], ints[7], ints[8], ints[9]]);
                    assert_eq!(e.texts[0].data, data[starts[0]..].as_ptr(), "round {round}");
                    // the string is the C string at the start
                    let c_len = data[starts[0]..].iter().position(|&b| b == 0).unwrap();
                    assert_eq!(e.texts[0].len, c_len);
                }
                (a, b) => panic!("round {round}: {:?} vs {:?}, data {data:?}", a.map(|x| x.1), b.map(|x| x.2)),
            }
        }
        // overflowing offsets
        assert!(read::<LogEntry, true>(&[], usize::MAX - 2).is_none());
        assert!(read::<LogEntry, true>(&[0; 16], usize::MAX).is_none());
        assert!(read::<LogEntry, true>(b"", 0).is_none());
        // The NUL at the end of the string's field is taken for the string's end; where it isn't
        // (an empty field, a field ending at a letter, past the data) the data is searched for one.
        let mut e = encode_all(&[LogEntry { id: 1, kind: 2, time: 3, texts: [Text::new(b"abc")] }]);
        assert!(read::<LogEntry, false>(&e, 0).is_some());
        e[12..16].copy_from_slice(&2u32.to_be_bytes());
        // field 2: ends at "b", the NUL is after: read, to the end of the field
        assert_eq!(read::<LogEntry, false>(&e, 0).unwrap().1, 18);
        e[12..16].copy_from_slice(&0u32.to_be_bytes());
        assert_eq!(read::<LogEntry, false>(&e, 0).unwrap().1, 16);
        // no NUL anywhere after the start
        let mut e = encode_all(&[LogEntry { id: 1, kind: 2, time: 3, texts: [Text::new(b"abc")] }]);
        e[19] = b'x';
        for len in [0u32, 1, 3, 4] {
            e[12..16].copy_from_slice(&len.to_be_bytes());
            assert!(read::<LogEntry, false>(&e, 0).is_none(), "field {len}");
            assert!(read::<LogEntry, true>(&e, 0).is_none(), "field {len}");
        }
        // a field past the data
        e[19] = 0;
        e[12..16].copy_from_slice(&5u32.to_be_bytes());
        assert!(read::<LogEntry, false>(&e, 0).is_none());
        // a length past the end, a string without its NUL, a length of 0 with a NUL later
        let mut e = encode_all(&[LogEntry { id: 1, kind: 2, time: 3, texts: [Text::new(b"abc")] }]);
        assert!(read::<LogEntry, true>(&e, 0).is_some());
        e[12..16].copy_from_slice(&u32::MAX.to_be_bytes());
        assert!(read::<LogEntry, true>(&e, 0).is_none());
        e[12..16].copy_from_slice(&4u32.to_be_bytes());
        assert!(read::<LogEntry, true>(&e[..19], 0).is_none());
        e[12..16].copy_from_slice(&0u32.to_be_bytes());
        let (short, next) = read::<LogEntry, true>(&e, 0).unwrap();
        assert_eq!((next, short.texts[0].len), (16, 3));
        assert_eq!(log_texts(&e, &[short]), [b"abc"]);
    }

    /// The previous line writers: the oracles of the listings.
    fn reference_log_line(kind: u32, text: &[u8]) -> Option<Vec<u8>> {
        let label: &[u8] = match kind {
            0 => b"[INFO] ",
            1 => b"[WARNING] ",
            2 => b"[ERROR] ",
            3 => b"[DEBUG] ",
            4 => b"[DETAIL] ",
            _ => return None,
        };
        Some([label, text, b"\n"].concat())
    }

    fn reference_post_line(id: u32, stage: u32, progress: u32, info_name: &[u8]) -> Vec<u8> {
        let names = ["", ", Loading Pars", ", Verifying source files", ", Repairing", ", Verifying repaired files",
            ", Par-Renaming", ", Rar-Renaming", ", Unpacking", ", Cleaning up", ", Moving", ", Post-unpack renaming",
            ", Executing postprocess-script", "", ", Post-download renaming", ", Repairing from duplicates"];
        let mut line = format!("[{}] ", id as i32).into_bytes();
        line.extend_from_slice(info_name);
        line.extend_from_slice(names.get(stage as usize).copied().unwrap_or("").as_bytes());
        if (progress as i32) > 0 && stage != 11 {
            line.extend_from_slice(format!(", {}%", progress as i32 / 10).as_bytes());
        }
        line.push(b'\n');
        line
    }

    fn reference_history_line(e: &HistoryEntry, name: &[u8]) -> Option<Vec<u8>> {
        let par = ["", "", ", Par failed", ", Par successful", ", Repair possible", ", Repair needed"];
        let script = ["", ", Script status unknown", ", Script failed", ", Script successful"];
        let url = ["", "", "Url download successful", "Url download failed", "", "Nzb scan skipped", "Nzb scan failed"];
        let mut line = format!("[{}] ", e.id as i32).into_bytes();
        line.extend_from_slice(name);
        let size = ((e.size_hi as i64) << 32) + e.size_lo as i64;
        let text = |t: &[&str], k: u32| t.get(k as usize).copied().unwrap_or("").to_string();
        let tail = match e.kind {
            1 => format!(" ({} files, {}{}{})", e.file_count as i32, String::from_utf8(crate::util::format_size(size)).unwrap(),
                text(&par, e.par_status), text(&script, e.script_status)),
            3 => format!(" (Hidden, {})", String::from_utf8(crate::util::format_size(size)).unwrap()),
            2 => format!(" (URL, {})", text(&url, e.url_status)),
            _ => return None,
        };
        line.extend_from_slice(tail.as_bytes());
        line.push(b'\n');
        Some(line)
    }

    #[test]
    fn listings_match_the_line_by_line_writers() {
        let mut r = Random(42);
        for round in 0..600 {
            let n = r.below(6);
            let texts: Vec<Vec<u8>> = (0..n).map(|_| r.text()).collect();
            // log
            let log: Vec<LogEntry> = texts.iter().map(|t| LogEntry { id: r.int(), kind: r.below(7) as u32, time: r.int(),
                texts: [Text::new(t)] }).collect();
            let mut expected = Vec::new();
            for e in &log {
                expected.extend(reference_log_line(e.kind, unsafe { e.texts[0].bytes() }).unwrap_or_default());
            }
            let data = encode_all(&log);
            assert_eq!(log_listing(&data, n as u32), expected, "log, round {round}");
            // more entries than the data holds: the listing ends with the data
            assert_eq!(log_listing(&data, n as u32 + 3), expected);
            // fewer: just those
            if n > 1 {
                let first = reference_log_line(log[0].kind, unsafe { log[0].texts[0].bytes() }).unwrap_or_default();
                assert_eq!(log_listing(&data, 1), first);
            }
            // post-queue
            let jobs: Vec<PostEntry> = texts.iter().map(|t| PostEntry { id: r.int(), stage: r.below(18) as u32,
                stage_progress: if r.below(3) == 0 { r.next() as u32 } else { r.below(1200) as u32 }, file_progress: 0,
                start_time: 0, stage_time: 0, texts: [Text::new(b"f"), Text::new(t), Text::EMPTY, Text::new(b"label")] }).collect();
            let mut expected = Vec::new();
            for (e, t) in jobs.iter().zip(&texts) {
                expected.extend(reference_post_line(e.id, e.stage, e.stage_progress, t));
            }
            assert_eq!(post_queue_listing(&encode_all(&jobs), n as u32), expected, "post-queue, round {round}");
            // history
            let history: Vec<HistoryEntry> = texts.iter().map(|t| HistoryEntry { id: r.int(), kind: r.below(5) as u32,
                time: r.int(), size_lo: r.int(), size_hi: if r.below(2) == 0 { 0 } else { r.below(4) as u32 },
                file_count: r.int(), par_status: r.below(8) as u32, script_status: r.below(6) as u32,
                url_status: r.below(9) as u32, texts: [Text::new(t)] }).collect();
            let mut expected = Vec::new();
            for (e, t) in history.iter().zip(&texts) {
                expected.extend(reference_history_line(e, t).unwrap_or_default());
            }
            assert_eq!(history_listing(&encode_all(&history), n as u32), expected, "history, round {round}");
        }
        // fixed examples
        let post = |stage, progress| encode_all(&[PostEntry { id: 3, stage, stage_progress: progress, file_progress: 0,
            start_time: 0, stage_time: 0, texts: [Text::EMPTY, Text::new(b"Show"), Text::EMPTY, Text::EMPTY] }]);
        assert_eq!(post_queue_listing(&post(7, 455), 1), b"[3] Show, Unpacking, 45%\n");
        assert_eq!(post_queue_listing(&post(11, 455), 1), b"[3] Show, Executing postprocess-script\n");
        assert_eq!(post_queue_listing(&post(12, 0), 1), b"[3] Show\n");
        assert_eq!(post_queue_listing(&post(99, 9), 1), b"[3] Show, 0%\n");
        let history = |kind, url_status| encode_all(&[HistoryEntry { id: 4, kind, time: 0, size_lo: 2048, size_hi: 0, file_count: 12,
            par_status: 3, script_status: 3, url_status, texts: [Text::new(b"N")] }]);
        assert_eq!(history_listing(&history(1, 0), 1), b"[4] N (12 files, 2.00 KB, Par successful, Script successful)\n");
        assert_eq!(history_listing(&history(3, 0), 1), b"[4] N (Hidden, 2.00 KB)\n");
        assert_eq!(history_listing(&history(2, 6), 1), b"[4] N (URL, Nzb scan failed)\n");
        assert_eq!(history_listing(&history(2, 70), 1), b"[4] N (URL, )\n");
        assert_eq!(history_listing(&history(0, 0), 1), b"");
        // an entry that doesn't fit ends the listing, with the lines before it kept
        let mut data = encode_all(&[LogEntry { id: 1, kind: 0, time: 0, texts: [Text::new(b"ok")] },
            LogEntry { id: 2, kind: 0, time: 0, texts: [Text::new(b"cut")] }]);
        data.truncate(data.len() - 2);
        assert_eq!(log_listing(&data, 2), b"[INFO] ok\n");
        assert_eq!(log_listing(&data, 0), b"");
        assert_eq!(log_listing(b"", 5), b"");
        // an unknown kind has no line but doesn't end the listing
        let data = encode_all(&[LogEntry { id: 1, kind: 5, time: 0, texts: [Text::new(b"x")] },
            LogEntry { id: 2, kind: 4, time: 0, texts: [Text::new(b"")] }]);
        assert_eq!(log_listing(&data, 2), b"[DETAIL] \n");
    }

    #[test]
    fn listing_growth_covers_32_bit_newline_and_final_nul() {
        let limit = i32::MAX as usize;
        let text_end = (1usize << 30) + 7; // INFO prefix plus a 1 GiB text
        assert!(text_end + 2 <= limit);
        assert!(text_end * 2 > limit);
        assert!(crate::util::byte_vec_needs_exact_growth(text_end, text_end, 1, limit));
        let newline_end = text_end + 1;
        assert!(crate::util::byte_vec_needs_exact_growth(newline_end, newline_end, 1, limit));
        assert!(!crate::util::byte_vec_needs_exact_growth(text_end, text_end - 8, 1, limit));
        assert!(!crate::util::byte_vec_needs_exact_growth(1024, 1024, 1, limit));
        assert!(!crate::util::byte_vec_needs_exact_growth(limit / 2, limit / 2, 1, limit));
    }

    #[test]
    fn listing_reservation_handles_32_bit_large_lengths() {
        // A valid input whose old eager reserve exceeded a 32-bit Vec limit,
        // without allocating a multi-gigabyte fixture.
        let input_len = 1_500_000_000usize;
        assert!(input_len <= i32::MAX as usize);
        assert!(input_len as u64 + input_len as u64 / 2 + 64 > i32::MAX as u64);
        assert!(listing_capacity(input_len) <= MAX_LISTING_INITIAL_CAPACITY);
        assert!(listing_capacity(usize::MAX) <= MAX_LISTING_INITIAL_CAPACITY);
        for len in [0usize, 1, 100, 4096, 100_000] {
            assert_eq!(listing_capacity(len), len + len / 2 + 64);
        }
    }

    #[test]
    fn listing_reservation_follows_output_growth_for_unused_input() {
        let payload = vec![b'x'; 2 * MAX_LISTING_INITIAL_CAPACITY];
        let data = encode_all(&[LogEntry { id: 1, kind: u32::MAX, time: 0,
            texts: [Text::new(&payload)] }]);
        let listing = log_listing(&data, 1);
        assert!(listing.is_empty());
        assert!(listing.capacity() <= MAX_LISTING_INITIAL_CAPACITY);
        // Formatting and growth still work when an actual line exceeds the
        // bounded initial reserve.
        let data = encode_all(&[LogEntry { id: 1, kind: 0, time: 0,
            texts: [Text::new(&payload)] }]);
        let listing = log_listing(&data, 1);
        assert!(listing.starts_with(b"[INFO] "));
        assert_eq!(&listing[7..listing.len() - 1], payload);
        assert_eq!(listing.last(), Some(&b'\n'));
    }

    #[test]
    fn ints_print_as_printf_did() {
        for v in [0, 1, -1, 9, 10, -10, 12345, i32::MAX, i32::MIN, -2147483647] {
            let mut out = Vec::new();
            push_int(&mut out, v);
            assert_eq!(out, v.to_string().as_bytes());
        }
    }





    #[test]
    fn responses() {
        let r = bool_response(true, b"ok");
        assert_eq!(r, [0x6e, 0x7a, 0x62, 0x31, 0, 0, 0, 16, 0, 0, 0, 1, 0, 0, 0, 3, b'o', b'k', 0]);
        assert!(trailing_ok(0, 10) && trailing_ok(10, 10) && !trailing_ok(-1, 10) && !trailing_ok(11, 10));
        assert!(trailing_ok(0, 0));
        assert!(!trailing_ok(0, -1));
        assert!(!trailing_ok(i64::MIN, i64::MAX));
        assert!(trailing_ok(i64::MAX, i64::MAX));
        assert!(!trailing_ok(i64::MAX, i64::MAX - 1));
    }
}
