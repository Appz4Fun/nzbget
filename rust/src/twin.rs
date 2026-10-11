//! Twins and alts: duplicates of a download told apart by the files their par2
//! sets describe. A twin holds files byte-identical to the primary's (its
//! articles, par2-files and bytes can stand in for the primary's); a near-twin
//! shares most of them (a re-packed archive header); an alt is another encode.
//!
//! The C++ side (TwinCheck) fetches articles and walks the queue; everything
//! else lives here: reading nzb-files, parsing par2 FileDesc packets (with
//! rust-par2), fingerprints, the per-posting file lists kept in the queue
//! directory, labels, and picking a duplicate's file by content.

use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::sync::Mutex;

/// One file of a par2 set: what identifies its bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileSig {
    pub name: String,
    pub length: u64,
    /// MD5 of the whole file, lower-case hex
    pub md5: String,
}

/// PAR2 packet types the walk reads (the 16 bytes after the set id).
const TYPE_MAIN: &[u8; 16] = b"PAR 2.0\0Main\0\0\0\0";
const TYPE_FILE_DESC: &[u8; 16] = b"PAR 2.0\0FileDesc";
const PACKET_MAGIC: &[u8; 8] = b"PAR2\0PKT";

// File IDs come from untrusted PAR2 packets: use the standard keyed,
// randomized hasher and include every byte of each ID.
type IdMap<V> = HashMap<[u8; 16], V>;

/// The first packet magic in `hay`: memchr for its first byte (SIMD, and
/// rare in par2 data), then the other 7 compared.
fn find_magic(hay: &[u8]) -> Option<usize> {
    let mut at = 0;
    while let Some(p) = crate::bytes::find_byte(&hay[at..], PACKET_MAGIC[0]) {
        let start = at + p;
        match hay.get(start..start + 8) {
            Some(window) if window == PACKET_MAGIC => return Some(start),
            Some(_) => at = start + 1,
            None => return None,
        }
    }
    None
}

/// What the walk of a par2-file's packets found: the Main packet's block
/// size and file ids, and the FileDesc packets' files by file id.
struct Walked {
    slice_size: u64,
    file_order: Vec<[u8; 16]>,
    files: IdMap<FileSig>,
}

/// The packets of a par2-file, framed and read as rust-par2's parser
/// (parse_par2_reader) reads them: the packet magic found wherever it is,
/// lengths a multiple of 4 and at least 64, a damaged packet (its MD5 not
/// the one in its header) skipped by its length, a Main packet's block size
/// and all file ids taken from the last intact one (including non-recoverable
/// ids after the recoverable count), a FileDesc packet from the
/// first intact one of its file id. Only the packets that make the result
/// get their MD5 checked: the parser also read and hashed every IFSC,
/// recovery and creator packet, and megabytes of recovery blocks, for
/// nothing in the result. `files` is false when only the block size is
/// wanted. None where the parser had an error: no intact Main packet, or a
/// packet cut short inside its header. A packet whose length runs past the
/// data ends the walk. The flag is whether a packet magic was seen at all.
fn walk(data: &[u8], files: bool) -> (Option<Walked>, bool) {
    use md5::{Digest, Md5};
    let mut walked = Walked { slice_size: 0, file_order: Vec::new(), files: IdMap::default() };
    let mut have_main = false;
    let mut seen = false;
    let mut pos = 0usize;
    while pos < data.len() {
        // the magic; elsewhere, the next one
        let Some(magic) = data.get(pos..pos + 8) else { break };
        if magic != PACKET_MAGIC {
            match find_magic(&data[pos + 8..]) {
                Some(at) => {
                    pos += 8 + at;
                    continue;
                }
                None => break,
            }
        }
        seen = true;
        let Some(length) = data.get(pos + 8..pos + 16) else { break };
        let length = u64::from_le_bytes(length.try_into().unwrap());
        pos += 16;
        if length < 64 || length % 4 != 0 {
            continue;
        }
        let rest = (data.len() - pos) as u64;
        if length - 16 > 10 * 1024 * 1024 {
            // a recovery slice's size: only its header is read, then it is skipped
            if rest < 48 {
                return (None, true);
            }
            if length - 16 > rest {
                break;
            }
            pos += (length - 16) as usize;
            continue;
        }
        // the header's MD5, and the rest of the packet
        if rest < 16 {
            return (None, true);
        }
        if length - 16 > rest {
            break;
        }
        let stored = &data[pos..pos + 16];
        let packet = &data[pos + 16..pos + (length - 16) as usize];
        pos += (length - 16) as usize;
        let kind = &packet[16..32];
        let main = kind == TYPE_MAIN;
        if !main && !(files && kind == TYPE_FILE_DESC) {
            continue;
        }
        if Md5::digest(packet).as_slice() != stored {
            continue;
        }
        if main {
            if packet.len() < 44 {
                continue;
            }
            // The count field covers recoverable files only. Non-recoverable
            // IDs follow them and also require FileDesc packets for completeness.
            let count = (packet.len() - 44) / 16;
            walked.slice_size = u64::from_le_bytes(packet[32..40].try_into().unwrap());
            walked.file_order = (0..count).map(|i| packet[44 + 16 * i..60 + 16 * i].try_into().unwrap()).collect();
            have_main = true;
        } else if packet.len() >= 88 {
            let id: [u8; 16] = packet[32..48].try_into().unwrap();
            walked.files.entry(id).or_insert_with(|| {
                let name = &packet[88..];
                let name = &name[..name.iter().position(|&b| b == 0).unwrap_or(name.len())];
                FileSig {
                    name: String::from_utf8_lossy(name).into_owned(),
                    length: u64::from_le_bytes(packet[80..88].try_into().unwrap()),
                    md5: hex(&packet[48..64]),
                }
            });
        }
    }
    (have_main.then_some(walked), seen)
}

/// The files the FileDesc packets in `data` describe (a par2-file, or the part
/// of one that arrived: lost articles leave gaps, the parser skips to the next
/// packet). Empty when there's no usable set. Names are the PAR2's own (twin
/// par-repair compares them); matching makes them valid file names first.
pub fn par2_sigs(data: &[u8]) -> Vec<FileSig> {
    par2_set(data).0
}

/// The files of the par2 set in `data`, and whether the list is complete: the
/// Main packet arrived and every file it names has its FileDesc packet. A
/// partial list proves nothing about a file it doesn't name.
pub fn par2_set(data: &[u8]) -> (Vec<FileSig>, bool) {
    let (mut sigs, complete) = match walk(data, true).0 {
        Some(set) if !set.files.is_empty() => {
            let complete = !set.file_order.is_empty() && set.file_order.iter().all(|id| set.files.contains_key(id));
            (set.files.into_values().collect(), complete)
        }
        // its Main packet lost (the first article of the par2-file missing): the
        // FileDesc packets that arrived still tell the files, but maybe not all
        _ => (scan_file_descs(data), false),
    };
    sigs.sort_by(|a, b| a.name.cmp(&b.name));
    (sigs, complete)
}

fn valid_name(name: &str) -> String {
    String::from_utf8_lossy(&crate::paths::make_valid_filename(name.as_bytes(), false)).into_owned()
}

/// Whether a packet's bytes are its own: the MD5 in its header (bytes 16-31)
/// covers the rest from the set id on. A lost article leaves zeros that pass
/// the magic and length checks, not this one.
fn packet_intact(packet: &[u8]) -> bool {
    use md5::{Digest, Md5};
    let digest = Md5::digest(&packet[32..]);
    digest.as_slice() == &packet[16..32]
}

/// FileDesc packets read wherever they are in `data` (no Main packet needed),
/// each checked against its MD5.
fn scan_file_descs(data: &[u8]) -> Vec<FileSig> {
    let mut files: HashMap<[u8; 16], FileSig> = HashMap::new();
    let mut pos = 0usize;
    while pos + 64 <= data.len() {
        if &data[pos..pos + 8] != b"PAR2\0PKT" {
            pos += 4;
            continue;
        }
        let length = u64::from_le_bytes(data[pos + 8..pos + 16].try_into().unwrap()) as usize;
        if length < 64 || !length.is_multiple_of(4) || length > data.len() - pos || !packet_intact(&data[pos..pos + length]) {
            pos += 4;
            continue;
        }
        if &data[pos + 48..pos + 64] == b"PAR 2.0\0FileDesc" && length >= 64 + 56 {
            // file id, MD5 of the file, MD5 of its first 16 KB, length, name
            let body = &data[pos + 64..pos + length];
            let id: [u8; 16] = body[0..16].try_into().unwrap();
            let name = &body[56..];
            let name = &name[..name.iter().position(|&b| b == 0).unwrap_or(name.len())];
            files.insert(id, FileSig {
                name: String::from_utf8_lossy(name).into_owned(),
                length: u64::from_le_bytes(body[48..56].try_into().unwrap()),
                md5: hex(&body[16..32]),
            });
        }
        pos += length;
    }
    let mut sigs: Vec<FileSig> = files.into_values().collect();
    sigs.sort_by(|a, b| a.name.cmp(&b.name));
    sigs
}

/// The block size of the par2 set in `data` (its Main packet), 0 if none.
pub fn block_size(data: &[u8]) -> u64 {
    let (set, seen) = walk(data, false);
    if let Some(set) = set {
        if set.slice_size > 0 {
            return set.slice_size;
        }
    }
    // the walk saw no packet magic: it looks from the 9th byte on, so only a
    // magic in the first 8 bytes' shadow (at 4) is left for the scan below
    let data = if seen { data } else { &data[..data.len().min(80)] };
    // the set didn't parse: the Main packet alone may still be there
    let mut pos = 0usize;
    while pos + 72 <= data.len() {
        if &data[pos..pos + 8] == b"PAR2\0PKT" && &data[pos + 48..pos + 64] == b"PAR 2.0\0Main\0\0\0\0" {
            return u64::from_le_bytes(data[pos + 64..pos + 72].try_into().unwrap());
        }
        pos += 4;
    }
    0
}

/// The recovery blocks a par2-volume's name gives ("x.vol03+04.par2": 4), None if none.
pub fn volume_blocks(filename: &str) -> Option<u32> {
    volume_blocks_bytes(filename.as_bytes())
}

/// `volume_blocks` over the name's bytes (no copy: the last ".vol", in any
/// case, then the first '+' after it, then the digits that follow).
pub fn volume_blocks_bytes(name: &[u8]) -> Option<u32> {
    let at = (0..name.len().checked_sub(3)?).rev().find(|&i| name[i] == b'.' && name[i + 1..i + 4].eq_ignore_ascii_case(b"vol"))?;
    let plus = at + crate::bytes::find_byte(&name[at..], b'+')?;
    let mut blocks: u32 = 0;
    let mut any = false;
    for &b in &name[plus + 1..] {
        if !b.is_ascii_digit() {
            break;
        }
        blocks = blocks.checked_mul(10)?.checked_add(u32::from(b - b'0'))?;
        any = true;
    }
    any.then_some(blocks)
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(DIGITS[(b >> 4) as usize] as char);
        out.push(DIGITS[(b & 15) as usize] as char);
    }
    out
}

/// The posting's fingerprint: equal for postings of byte-identical files,
/// whatever their names. FNV-1a over the sorted "md5:length" lines, so the
/// values TwinCheck stored before (in C++) stay valid. "" for no files.
pub fn fingerprint(sigs: &[FileSig]) -> String {
    fingerprint_of(sigs.iter().map(|s| (s.md5.as_str(), s.length)))
}

/// `fingerprint` over (md5, length) pairs: the sorted, distinct "md5:length"
/// lines hashed, without a string for each.
pub fn fingerprint_of<'a>(files: impl Iterator<Item = (&'a str, u64)>) -> String {
    fingerprint_cow(files.map(|(md5, length)| (std::borrow::Cow::Borrowed(md5), length)))
}

pub fn fingerprint_cow<'a>(files: impl Iterator<Item = (std::borrow::Cow<'a, str>, u64)>) -> String {
    let mut arena: Vec<u8> = Vec::new();
    let mut spans: Vec<(usize, usize)> = Vec::new();
    for (md5, length) in files {
        let mut digits = [0u8; 20];
        let mut at = digits.len();
        let mut rest = length;
        loop {
            at -= 1;
            digits[at] = b'0' + (rest % 10) as u8;
            rest /= 10;
            if rest == 0 {
                break;
            }
        }
        let start = arena.len();
        arena.extend_from_slice(md5.as_bytes());
        arena.push(b':');
        arena.extend_from_slice(&digits[at..]);
        spans.push((start, arena.len()));
    }
    // the sorted, distinct "md5:length" lines, as a BTreeSet<String> held them
    spans.sort_unstable_by(|a, b| arena[a.0..a.1].cmp(&arena[b.0..b.1]));
    spans.dedup_by(|a, b| arena[a.0..a.1] == arena[b.0..b.1]);
    if spans.is_empty() {
        return String::new();
    }
    let mut hash: u64 = 14695981039346656037;
    for &(start, end) in &spans {
        for &byte in arena[start..end].iter().chain(std::iter::once(&b'\n')) {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(1099511628211);
        }
    }
    format!("{hash:016x}-{}", spans.len())
}

/// How many of `primary`'s files `dupe` holds (by MD5 and length), each file
/// of `dupe` standing in for one of `primary`'s at most.
pub fn shared_files(primary: &[FileSig], dupe: &[FileSig]) -> usize {
    let mut held: HashMap<(&str, u64), usize> = HashMap::new();
    for s in dupe {
        *held.entry((s.md5.as_str(), s.length)).or_default() += 1;
    }
    primary
        .iter()
        .filter(|s| match held.get_mut(&(s.md5.as_str(), s.length)) {
            Some(count) if *count > 0 => {
                *count -= 1;
                true
            }
            _ => false,
        })
        .count()
}

/// The label of `dupe` against `primary`: "twin" (every file, and no other),
/// "twin:N/M" (N of the primary's M files, more than half: a near-twin, a
/// re-packed archive header), "alt" (fewer: a shared NFO or sample doesn't make
/// a twin), "" when a list is empty, or when an incomplete list would make an alt.
pub fn kind(primary: &Listed, dupe: &Listed) -> String {
    if primary.sigs.is_empty() || dupe.sigs.is_empty() {
        return String::new();
    }
    let shared = shared_files(&primary.sigs, &dupe.sigs);
    let total = primary.sigs.len();
    if primary.complete && dupe.complete && shared == total && dupe.sigs.len() == total {
        "twin".into()
    } else if primary.complete && shared * 2 > total {
        // the primary's complete list gives the denominator; the donor's may lack
        // files it has (more of them only makes it more of a twin)
        format!("twin:{shared}/{total}")
    } else if primary.complete && dupe.complete {
        "alt".into()
    } else {
        String::new()
    }
}

/// The files of two partial lists of one posting together (each file once):
/// retries that saw other articles of the par2-file add what they found.
pub fn merge(a: &[FileSig], b: &[FileSig]) -> Vec<FileSig> {
    let mut seen: std::collections::HashSet<(&str, &str, u64)> = std::collections::HashSet::new();
    let mut merged: Vec<FileSig> = Vec::with_capacity(a.len() + b.len());
    for sig in a.iter().chain(b) {
        if seen.insert((sig.name.as_str(), sig.md5.as_str(), sig.length)) {
            merged.push(sig.clone());
        }
    }
    merged.sort_by(|x, y| x.name.cmp(&y.name));
    merged
}

/// The name of the duplicate's file holding the same bytes as our file named
/// `target` (or `target_alt`, the name our nzb gives it). `None`: not known (our
/// list is partial or doesn't have the file, the name fits several, several donor files hold the
/// bytes, or the donor's list is incomplete and doesn't have them). `Some("")`:
/// the donor's complete list has no file with these bytes.
pub fn match_by_content(own: &Listed, target: &str, target_alt: &str, donor: &Listed) -> Option<String> {
    // our name is known to be unique only in our complete list: a FileDesc the
    // partial one lacks may make the same valid name
    if !own.complete {
        return None;
    }
    let ours = find_sig(&own.sigs, target).or_else(|| find_sig(&own.sigs, target_alt))?;
    let mut found = donor.sigs.iter().filter(|s| s.md5 == ours.md5 && s.length == ours.length);
    match (found.next(), found.next()) {
        (Some(one), None) => Some(valid_name(&one.name)),
        (Some(_), Some(_)) => None,
        (None, _) if donor.complete => Some(String::new()),
        (None, _) => None,
    }
}

/// The file named `name`: the one with this exact name, else the only one that
/// differs in case; `None` when there's none or the case leaves it open.
fn find_sig<'a>(sigs: &'a [FileSig], name: &str) -> Option<&'a FileSig> {
    if name.is_empty() {
        return None;
    }
    // the names the queue gives files: PAR2 names made valid file names. Two
    // PAR2 names can make one valid name ("a:b.rar", "a?b.rar"): then it's open
    let mut exact = sigs.iter().filter(|s| valid_name(&s.name) == name);
    match (exact.next(), exact.next()) {
        (Some(one), None) => return Some(one),
        (Some(_), Some(_)) => return None,
        _ => {}
    }
    let mut folded = sigs.iter().filter(|s| valid_name(&s.name).eq_ignore_ascii_case(name));
    match (folded.next(), folded.next()) {
        (Some(one), None) => Some(one),
        _ => None,
    }
}

/// A posting's file list as stored: bound to the fingerprint it was made for.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Listed {
    pub sigs: Vec<FileSig>,
    pub complete: bool,
    pub print: String,
}

/// The par2 file lists of the postings fingerprinted so far, by download id,
/// appended to a file in the queue directory. A record is a line
/// "id\tnew\tfingerprint\tcomplete", its "id\tlength\tmd5\tname" lines and a
/// line "id\tend\tcount": a record cut short (a full disk) has no end line with
/// its count and is ignored. A later record of an id replaces the earlier one.
/// A list is only used for the posting it was made for, given by its identity
/// (the C++ side passes the fingerprint and the posting's message-id hash): a
/// fingerprint alone is shared by differently named twins, and download ids
/// start over when the queue and history are emptied while the file stays
/// (`prune` keeps it to the postings still there).
#[derive(Default)]
pub struct Store {
    path: std::path::PathBuf,
    lists: HashMap<i32, Listed>,
}

static EMPTY: Listed = Listed { sigs: Vec::new(), complete: false, print: String::new() };

fn record(id: i32, listed: &Listed) -> String {
    let mut text = format!("{id}\tnew\t{}\t{}\n", listed.print, u8::from(listed.complete));
    for s in &listed.sigs {
        let name = s.name.replace(['\n', '\t', '\r'], "_");
        text.push_str(&format!("{id}\t{}\t{}\t{name}\n", s.length, s.md5));
    }
    text.push_str(&format!("{id}\tend\t{}\n", listed.sigs.len()));
    text
}

impl Store {
    pub fn open(path: std::path::PathBuf) -> Store {
        let mut store = Store { path, lists: HashMap::new() };
        let mut pending: HashMap<i32, Listed> = HashMap::new();
        if let Ok(file) = std::fs::File::open(&store.path) {
            for line in BufReader::new(file).lines().map_while(Result::ok) {
                let parts: Vec<&str> = line.splitn(4, '\t').collect();
                let Some(Ok(id)) = parts.first().map(|id| id.parse::<i32>()) else {
                    continue;
                };
                match parts.get(1) {
                    Some(&"new") => {
                        pending.insert(id, Listed {
                            sigs: Vec::new(),
                            print: parts.get(2).unwrap_or(&"").to_string(),
                            complete: parts.get(3) == Some(&"1"),
                        });
                    }
                    Some(&"end") => {
                        let count = parts.get(2).and_then(|c| c.parse::<usize>().ok());
                        if let Some(listed) = pending.remove(&id) {
                            if count == Some(listed.sigs.len()) {
                                store.lists.insert(id, listed);
                            }
                        }
                    }
                    _ => {
                        let (Some(length), Some(md5), Some(name)) = (parts.get(1), parts.get(2), parts.get(3)) else {
                            continue;
                        };
                        let Ok(length) = length.parse::<u64>() else {
                            continue;
                        };
                        if let Some(listed) = pending.get_mut(&id) {
                            listed.sigs.push(FileSig { name: name.to_string(), length, md5: md5.to_string() });
                        }
                    }
                }
            }
        }
        store
    }

    pub fn put(&mut self, id: i32, listed: Listed) {
        if let Ok(mut out) = OpenOptions::new().create(true).append(true).open(&self.path) {
            let _ = out.write_all(record(id, &listed).as_bytes());
        }
        self.lists.insert(id, listed);
    }

    /// A partial list of download `id` stored for the posting `posting` (the part
    /// of its identity after '#'): retries add to it until a complete list comes.
    pub fn partial_of(&self, id: i32, posting: &str) -> Option<&Listed> {
        self.lists
            .get(&id)
            .filter(|listed| !listed.complete && listed.print.rsplit_once('#').map(|(_, p)| p) == Some(posting))
    }

    /// The list of download `id` if it was made for posting identity `print`, else an empty one.
    pub fn get(&self, id: i32, print: &str) -> &Listed {
        match self.lists.get(&id) {
            Some(listed) if !print.is_empty() && listed.print == print => listed,
            _ => &EMPTY,
        }
    }

    /// Keeps the lists of the postings still in queue or history (`live`: id and
    /// fingerprint), the rest dropped, and rewrites the file with them (to a
    /// temporary file renamed over it: never half written).
    pub fn prune(&mut self, live: &[(i32, String)]) {
        let keep: HashMap<i32, &str> = live.iter().map(|(id, print)| (*id, print.as_str())).collect();
        self.lists.retain(|id, listed| keep.get(id) == Some(&listed.print.as_str()));
        let mut ids: Vec<&i32> = self.lists.keys().collect();
        ids.sort();
        let text: String = ids.iter().map(|id| record(**id, &self.lists[id])).collect();
        let mut temp = self.path.clone().into_os_string();
        temp.push(".new");
        let temp = std::path::PathBuf::from(temp);
        // rename replaces the file in one step, also on Windows (MoveFileExW with
        // MOVEFILE_REPLACE_EXISTING), so a reader sees the old or the new store
        if std::fs::write(&temp, text).is_ok() {
            let _ = std::fs::rename(&temp, &self.path);
        }
    }
}

/// The one store of the process (the queue directory's); `None` until opened.
pub static STORE: Mutex<Option<Store>> = Mutex::new(None);

/// One `<file>` of an nzb-file: what fetching it needs.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NzbEntry {
    pub subject: String,
    /// the quoted name in the subject, path separators replaced; "" if none
    pub filename: String,
    pub groups: Vec<String>,
    /// bytes and message-id (with angle brackets, sanitized for NNTP commands)
    pub segments: Vec<(u64, String)>,
}

impl NzbEntry {
    pub fn size(&self) -> u64 {
        self.segments.iter().map(|s| s.0).sum()
    }
    pub fn is_par2(&self) -> bool {
        let name = if self.filename.is_empty() { &self.subject } else { &self.filename };
        name.to_ascii_lowercase().contains(".par2")
    }
}

/// The `<file>` entries of an nzb-file, read without the queue's parser (that
/// one writes the article lists to the queue directory in server mode).
// the replacement needs the XML version, which nzb-files don't vary
#[allow(deprecated)]
pub fn read_nzb(xml: &[u8]) -> Vec<NzbEntry> {
    use quick_xml::events::Event;
    let mut reader = quick_xml::Reader::from_reader(xml);
    let mut entries = Vec::new();
    let mut entry: Option<NzbEntry> = None;
    let mut text = String::new();
    let mut bytes: u64 = 0;
    let mut buf = Vec::new();
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => {
                text.clear();
                match e.local_name().as_ref() {
                    b"file" => {
                        let mut new = NzbEntry::default();
                        for a in e.attributes().flatten() {
                            if a.key.local_name().as_ref() == b"subject" {
                                new.subject = a.decode_and_unescape_value(reader.decoder()).map(|v| v.into_owned()).unwrap_or_default();
                            }
                        }
                        new.filename = quoted_name(&new.subject);
                        entry = Some(new);
                    }
                    b"segment" => {
                        bytes = e
                            .attributes()
                            .flatten()
                            .find(|a| a.key.local_name().as_ref() == b"bytes")
                            .and_then(|a| String::from_utf8_lossy(&a.value).parse().ok())
                            .unwrap_or(0);
                    }
                    _ => {}
                }
            }
            Ok(Event::Text(t)) => text.push_str(&t.decode().map(|v| v.into_owned()).unwrap_or_default()),
            Ok(Event::GeneralRef(r)) => {
                let name = r.decode().map(|v| v.into_owned()).unwrap_or_default();
                match name.as_str() {
                    "lt" => text.push('<'),
                    "gt" => text.push('>'),
                    "amp" => text.push('&'),
                    "quot" => text.push('"'),
                    "apos" => text.push('\''),
                    _ => {
                        if let Ok(Some(c)) = r.resolve_char_ref() {
                            text.push(c);
                        }
                    }
                }
            }
            Ok(Event::End(e)) => match e.local_name().as_ref() {
                b"group" => {
                    if let Some(entry) = entry.as_mut() {
                        entry.groups.push(text.trim().to_string());
                    }
                }
                b"segment" => {
                    if let Some(entry) = entry.as_mut() {
                        entry.segments.push((bytes, message_id(text.trim())));
                    }
                }
                b"file" => {
                    if let Some(done) = entry.take() {
                        if !done.segments.is_empty() {
                            entries.push(done);
                        }
                    }
                }
                _ => {}
            },
            Ok(Event::Eof) | Err(_) => break,
            _ => {}
        }
        buf.clear();
    }
    entries
}

fn quoted_name(subject: &str) -> String {
    let mut parts = subject.splitn(3, '"');
    match (parts.next(), parts.next(), parts.next()) {
        (Some(_), Some(name), Some(_)) => name.replace(['/', '\\'], "_"),
        _ => String::new(),
    }
}

/// It goes into NNTP commands as is (see NzbFile): no line breaks, spaces or
/// control characters, and bounded.
fn message_id(raw: &str) -> String {
    let id: String = raw.chars().take(1000).map(|c| if (c as u32) <= 0x20 || c == '\x7f' { '_' } else { c }).collect();
    format!("<{id}>")
}

/// The crate's parser, as par2_set and block_size used it before the walk
/// (the comparison tests below).
#[cfg(test)]
type CrateSet = (u64, Vec<[u8; 16]>, Vec<(String, u64, String)>);

#[cfg(test)]
fn crate_set(data: &[u8]) -> Option<CrateSet> {
    let mut reader = std::io::Cursor::new(data);
    let set = rust_par2::parse_par2_reader(&mut reader, data.len() as u64).ok()?;
    let mut files: Vec<(String, u64, String)> =
        set.files.values().map(|f| (f.filename.clone(), f.size, hex(&f.hash))).collect();
    files.sort();
    Some((set.slice_size, set.file_order, files))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    fn sig(name: &str, md5: &str, length: u64) -> FileSig {
        FileSig { name: name.into(), md5: md5.into(), length }
    }

    #[test]
    fn fingerprint_matches_the_cpp_values() {
        // ignores names and order, counts distinct files
        let a = vec![sig("x.part01.rar", "aa", 10), sig("x.part02.rar", "bb", 20)];
        let b = vec![sig("RANDOM2", "bb", 20), sig("RANDOM1", "aa", 10)];
        assert_eq!(fingerprint(&a), fingerprint(&b));
        assert!(fingerprint(&a).ends_with("-2"));
        assert_eq!(fingerprint(&[]), "");
        // FNV-1a of "aa:10\n" then "bb:20\n"
        let mut hash: u64 = 14695981039346656037;
        for byte in "aa:10\nbb:20\n".bytes() {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(1099511628211);
        }
        assert_eq!(fingerprint(&a), format!("{hash:016x}-2"));
    }

    #[test]
    fn volumes() {
        assert_eq!(volume_blocks("x.vol03+04.par2"), Some(4));
        assert_eq!(volume_blocks("X.VOL00+128.PAR2"), Some(128));
        assert_eq!(volume_blocks("x.vol-08.par2"), None);
        assert_eq!(volume_blocks("x.par2"), None);
    }

    fn listed(sigs: Vec<FileSig>, complete: bool) -> Listed {
        Listed { print: fingerprint(&sigs), sigs, complete }
    }

    #[test]
    fn kinds() {
        let primary = listed(vec![sig("a", "1", 1), sig("b", "2", 2), sig("c", "3", 3)], true);
        assert_eq!(kind(&primary, &primary), "twin");
        // two of three files: a near-twin
        let near = listed(vec![sig("x", "1", 1), sig("y", "2", 2), sig("z", "9", 3)], true);
        assert_eq!(kind(&primary, &near), "twin:2/3");
        // one shared file (an NFO) of three: an alt, not a near-twin
        let nfo = listed(vec![sig("x", "1", 1), sig("y", "8", 2), sig("z", "9", 3)], true);
        assert_eq!(kind(&primary, &nfo), "alt");
        // ... unless a list is incomplete: then it can't tell
        assert_eq!(kind(&primary, &listed(nfo.sigs.clone(), false)), "");
        assert_eq!(kind(&primary, &listed(vec![], true)), "");
        // two partial lists of the same first files: not a twin, not known
        let part = listed(vec![sig("a", "1", 1)], false);
        assert_eq!(kind(&part, &part), "");
        // a partial primary list gives no ratio
        assert_eq!(kind(&listed(primary.sigs.clone(), false), &near), "");
        // a complete primary, the donor's list partial: a near-twin still shows
        assert_eq!(kind(&primary, &listed(near.sigs.clone(), false)), "twin:2/3");
        assert_eq!(kind(&primary, &listed(primary.sigs.clone(), false)), "twin:3/3");
    }

    #[test]
    fn identical_files_count_once() {
        // two identical files in the primary; the dupe holds one of them and an
        // unrelated file: one shared, not two (no exact twin)
        let primary = listed(vec![sig("a", "1", 1), sig("b", "1", 1)], true);
        let dupe = listed(vec![sig("x", "1", 1), sig("y", "7", 7)], true);
        assert_eq!(shared_files(&primary.sigs, &dupe.sigs), 1);
        assert_eq!(kind(&primary, &dupe), "alt");
    }

    #[test]
    fn content_match() {
        let own = listed(vec![sig("QnL.7z.002", "80a3", 500), sig("QnL.7z.001", "9f9b", 500)], true);
        let donor = listed(vec![sig("TA7.7z.001", "d512", 500), sig("TA7.7z.002", "80a3", 500)], true);
        assert_eq!(match_by_content(&own, "QnL.7z.002", "", &donor), Some("TA7.7z.002".into()));
        // a complete donor list without the bytes: authoritative
        assert_eq!(match_by_content(&own, "QnL.7z.001", "", &donor), Some(String::new()));
        // case differs, one candidate: found
        assert_eq!(match_by_content(&own, "qnl.7Z.002", "", &donor), Some("TA7.7z.002".into()));
        assert_eq!(match_by_content(&own, "other", "", &donor), None);
        assert_eq!(match_by_content(&own, "other", "QnL.7z.002", &donor), Some("TA7.7z.002".into()));
        // an incomplete donor list without the bytes: not known
        let partial = listed(vec![sig("TA7.7z.001", "d512", 500)], false);
        assert_eq!(match_by_content(&own, "QnL.7z.002", "", &partial), None);
        // no donor list (not fingerprinted yet): not known
        assert_eq!(match_by_content(&own, "QnL.7z.002", "", &listed(vec![], false)), None);
        // two donor files hold the bytes: left to the structure
        let twice = listed(vec![sig("P.001", "80a3", 500), sig("P.002", "80a3", 500)], true);
        assert_eq!(match_by_content(&own, "QnL.7z.002", "", &twice), None);
    }

    #[test]
    fn par2_names_made_valid() {
        // the names the queue gives files: a PAR2 name with a separator or a colon
        assert_eq!(valid_name("dir/file.rar"), "dir_file.rar");
        assert_eq!(valid_name("a:b.rar"), "a_b.rar");
        // matched by the valid name, the PAR2 name kept as it is
        let own = listed(vec![sig("a:b.rar", "1", 1)], true);
        let donor = listed(vec![sig("x?y.rar", "1", 1)], true);
        assert_eq!(match_by_content(&own, "a_b.rar", "", &donor), Some("x_y.rar".into()));
        assert_eq!(own.sigs[0].name, "a:b.rar");
    }

    #[test]
    fn partial_own_list_matches_nothing() {
        let own = listed(vec![sig("a?b.rar", "2", 1)], false);
        let donor = listed(vec![sig("y", "2", 1)], true);
        assert_eq!(match_by_content(&own, "a_b.rar", "", &donor), None);
    }

    #[test]
    fn partial_lists_merge() {
        let first = vec![sig("a", "1", 1), sig("b", "2", 2)];
        let third = vec![sig("b", "2", 2)];
        assert_eq!(merge(&first, &third), first);
        assert_eq!(merge(&third, &[sig("c", "3", 3)]), vec![sig("b", "2", 2), sig("c", "3", 3)]);
    }

    #[test]
    fn colliding_valid_names_are_open() {
        let own = listed(vec![sig("a:b.rar", "1", 1), sig("a?b.rar", "2", 1)], true);
        let donor = listed(vec![sig("x", "1", 1), sig("y", "2", 1)], true);
        assert_eq!(match_by_content(&own, "a_b.rar", "", &donor), None);
    }

    #[test]
    fn exact_case_first() {
        let own = listed(vec![sig("A.rar", "1", 1), sig("a.rar", "2", 1)], true);
        let donor = listed(vec![sig("x", "1", 1), sig("y", "2", 1)], true);
        assert_eq!(match_by_content(&own, "a.rar", "", &donor), Some("y".into()));
        assert_eq!(match_by_content(&own, "A.rar", "", &donor), Some("x".into()));
        // folded only, two candidates: not known
        assert_eq!(match_by_content(&own, "A.RAR", "", &donor), None);
    }

    #[test]
    fn nzb_reading() {
        let xml = br#"<?xml version="1.0"?><nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
<file poster="p" date="1" subject="[1/2] - &quot;rel/x.par2&quot; yEnc (1/1)"><groups><group>a.b</group></groups>
<segments><segment bytes="100" number="1">id1@x</segment></segments></file>
<file subject="&quot;movie.mkv&quot; yEnc (1/2)"><groups><group>a.b</group><group>c.d</group></groups>
<segments><segment bytes="5" number="1">a b
c@x</segment><segment bytes="7" number="2">id3@x</segment></segments></file>
<file subject="empty"><segments></segments></file></nzb>"#;
        let entries = read_nzb(xml);
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].filename, "rel_x.par2");
        assert!(entries[0].is_par2());
        assert_eq!(entries[1].groups, vec!["a.b", "c.d"]);
        assert_eq!(entries[1].segments, vec![(5, "<a_b_c@x>".into()), (7, "<id3@x>".into())]);
        assert_eq!(entries[1].size(), 12);
    }

    #[test]
    fn par2_of_a_real_set() {
        // made by par2cmdline when it's there: rust-par2 reads the FileDesc packets
        let dir = std::env::temp_dir().join(format!("twin-par2-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let data: Vec<u8> = (0..300_000u32).map(|i| (i.wrapping_mul(2654435761) >> 24) as u8).collect();
        std::fs::write(dir.join("movie.mkv"), &data).unwrap();
        let made = std::process::Command::new("par2")
            .args(["create", "-q", "-q", "-s65536", "-c2", "m.par2", "movie.mkv"])
            .current_dir(&dir)
            .status();
        if !matches!(made, Ok(s) if s.success()) {
            return; // no par2cmdline here
        }
        let par2 = std::fs::read(dir.join("m.par2")).unwrap();
        let (sigs, complete) = par2_set(&par2);
        assert!(complete);
        assert_eq!(sigs.len(), 1);
        assert_eq!(sigs[0].name, "movie.mkv");
        assert_eq!(sigs[0].length, 300_000);
        let md5 = std::process::Command::new("md5sum").arg(dir.join("movie.mkv")).output().unwrap();
        assert_eq!(sigs[0].md5, String::from_utf8_lossy(&md5.stdout)[..32]);
        // a lost article took the Main packet's header (it comes first): the
        // FileDesc packet after it still tells the file
        let mut damaged = par2.clone();
        for b in damaged.iter_mut().take(64) {
            *b = 0;
        }
        let (sigs, complete) = par2_set(&damaged);
        assert_eq!(sigs.len(), 1);
        assert!(!complete, "without its Main packet a list can't be known complete");
        // zeros through the FileDesc packet too (a lost article): not taken
        let desc = par2.windows(16).position(|w| w == b"PAR 2.0\0FileDesc").unwrap() - 48;
        let mut torn = damaged.clone();
        for b in torn.iter_mut().skip(desc + 70).take(16) {
            *b = 0;
        }
        assert!(par2_set(&torn).0.is_empty(), "a FileDesc packet with zeros in it is rejected");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn nzb_in_a_declared_legacy_encoding() {
        // ISO-8859-1, "r\xe9lease.par2": still read, still a par2-file
        let mut xml = b"<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?><nzb><file subject=\"&quot;r".to_vec();
        xml.push(0xe9);
        xml.extend_from_slice(b"lease.par2&quot; yEnc (1/1)\"><groups><group>a.b</group></groups><segments><segment bytes=\"9\" number=\"1\">id@x</segment></segments></file></nzb>");
        let entries = read_nzb(&xml);
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].filename, "r\u{e9}lease.par2");
        assert!(entries[0].is_par2());
    }

    #[test]
    fn store_round_trip() {
        let path = std::env::temp_dir().join(format!("twincheck-test-{}", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let mut store = Store::open(path.clone());
        store.put(7, listed(vec![sig("a\tb", "1", 1)], true));
        let second = listed(vec![sig("c", "2", 2)], false);
        store.put(7, second.clone());
        let third = listed(vec![sig("d", "3", 3)], true);
        store.put(8, third.clone());
        // a record cut short (no end line): ignored, the earlier one stays
        std::fs::OpenOptions::new().append(true).open(&path).unwrap()
            .write_all(b"8\tnew\tother\t1\n8\t9\t9\tz\n").unwrap();
        let again = Store::open(path.clone());
        assert_eq!(again.get(7, &second.print), &second);
        assert_eq!(again.get(8, &third.print), &third);
        // another posting under a reused id: its list isn't this one
        assert!(again.get(8, "other").sigs.is_empty());
        assert!(again.get(9, &third.print).sigs.is_empty());
        // pruned to the postings still there: the file keeps them alone
        let mut again = again;
        again.prune(&[(8, third.print.clone()), (7, "replaced".into())]);
        let pruned = Store::open(path.clone());
        assert_eq!(pruned.get(8, &third.print), &third);
        assert!(pruned.get(7, &second.print).sigs.is_empty());
        let _ = std::fs::remove_file(&path);
    }

    /// fingerprint as it was before: a BTreeSet of "md5:length" strings.
    fn fingerprint_before(sigs: &[FileSig]) -> String {
        let files: BTreeSet<String> = sigs.iter().map(|s| format!("{}:{}", s.md5, s.length)).collect();
        if files.is_empty() {
            return String::new();
        }
        let mut hash: u64 = 14695981039346656037;
        for file in &files {
            for byte in file.bytes().chain(std::iter::once(b'\n')) {
                hash ^= u64::from(byte);
                hash = hash.wrapping_mul(1099511628211);
            }
        }
        format!("{hash:016x}-{}", files.len())
    }

    #[test]
    fn fingerprint_is_the_one_stored_before() {
        // values the C++ stored for these lists (and the first version of this port)
        let sig = |md5: &str, length| FileSig { name: String::new(), length, md5: md5.to_string() };
        assert_eq!(fingerprint(&[]), "");
        let mut rng = Rng(0xD1B54A32D192ED03);
        for round in 0..20000 {
            let n = rng.below(40) as usize;
            let sigs: Vec<FileSig> = (0..n)
                .map(|_| {
                    // md5 texts of 32 hex digits, short and long ones, repeated and prefix-sharing, lengths of 1 to 20 digits
                    let width = [32, 32, 32, 1, 2, 3, 31, 33, 40, 60, 70][rng.below(11) as usize];
                    let md5: String = (0..width).map(|_| b"0123456789abcdef:"[rng.below(if width > 3 { 16 } else { 17 }) as usize] as char).collect();
                    let md5 = if rng.below(4) == 0 { md5[..md5.len().min(2)].to_string() } else { md5 };
                    let length = [0u64, 9, 10, 99, 100, 1000, rng.next(), rng.next() >> 40, u64::MAX][rng.below(9) as usize];
                    sig(&md5, length)
                })
                .collect();
            let mut doubled = sigs.clone();
            if rng.below(3) == 0 {
                doubled.extend(sigs.iter().take(5).cloned());
            }
            assert_eq!(fingerprint(&doubled), fingerprint_before(&doubled), "round {round}");
        }
        // sorted as text: "9" after "10" under one md5
        let same = [sig("aa", 9), sig("aa", 10), sig("aa", 100)];
        assert_eq!(fingerprint(&same), fingerprint_before(&same));
    }

    #[test]
    fn main_non_recoverable_files_require_descriptions() {
        let mut rng = Rng(1);
        let mut data = main_packet(65536, &[1, 2], 1);
        data.extend(file_desc(1, "movie.mkv", 1024, &mut rng));
        let (sigs, complete) = par2_set(&data);
        assert_eq!(sigs.len(), 1);
        assert!(!complete, "the non-recoverable file description is missing");
        assert_eq!(walk(&data, true).0.unwrap().file_order, vec![[1; 16], [2; 16]]);
        data.extend(file_desc(2, "release.nfo", 128, &mut rng));
        let (sigs, complete) = par2_set(&data);
        assert_eq!(sigs.len(), 2);
        assert!(complete);

        let mut data = main_packet(65536, &[2], 0);
        data.extend(file_desc(2, "release.nfo", 128, &mut rng));
        assert!(par2_set(&data).1, "a set with only non-recoverable files is complete");
    }

    #[test]
    fn file_id_hashing_uses_every_byte_and_randomized_state() {
        use std::hash::BuildHasher;
        let map: IdMap<()> = IdMap::default();
        let hashes: std::collections::HashSet<_> = (0..256u32).map(|i| {
            let mut id = [7u8; 16];
            id[8..12].copy_from_slice(&i.to_le_bytes());
            map.hasher().hash_one(id)
        }).collect();
        assert_eq!(hashes.len(), 256, "distinct IDs must use their second half");
        let hashes: std::collections::HashSet<_> = (0..8).map(|_| {
            IdMap::<()>::default().hasher().hash_one([7u8; 16])
        }).collect();
        assert!(hashes.len() > 1, "independent maps must use randomized hash state");
    }

    // ---- the walk against rust-par2's parser ----

    struct Rng(u64);

    impl Rng {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            self.0
        }
        fn below(&mut self, n: u64) -> u64 {
            self.next() % n
        }
    }

    fn packet(set_id: [u8; 16], kind: &[u8; 16], body: &[u8]) -> Vec<u8> {
        use md5::{Digest, Md5};
        let mut data = set_id.to_vec();
        data.extend_from_slice(kind);
        data.extend_from_slice(body);
        let mut out = b"PAR2\0PKT".to_vec();
        out.extend_from_slice(&((data.len() + 32) as u64).to_le_bytes());
        out.extend_from_slice(&Md5::digest(&data));
        out.extend_from_slice(&data);
        out
    }

    fn file_desc(id: u8, name: &str, size: u64, rng: &mut Rng) -> Vec<u8> {
        let mut body = vec![id; 16];
        body.extend((0..32).map(|_| rng.next() as u8));
        body.extend_from_slice(&size.to_le_bytes());
        body.extend_from_slice(name.as_bytes());
        body.resize(body.len().div_ceil(4) * 4, 0);
        packet([7; 16], TYPE_FILE_DESC, &body)
    }

    fn main_packet(slice: u64, ids: &[u8], count: u32) -> Vec<u8> {
        let mut body = slice.to_le_bytes().to_vec();
        body.extend_from_slice(&count.to_le_bytes());
        for &id in ids {
            body.extend_from_slice(&[id; 16]);
        }
        packet([7; 16], TYPE_MAIN, &body)
    }

    fn random_set(rng: &mut Rng) -> Vec<u8> {
        let files = 1 + rng.below(6) as u8;
        let ids: Vec<u8> = (1..=files).collect();
        let mut packets: Vec<Vec<u8>> = Vec::new();
        packets.push(main_packet(1 << (10 + rng.below(8)), &ids, files as u32 + rng.below(2) as u32));
        for &id in &ids {
            let name = ["a.mkv", "b.rar", "caf\u{e9}.nfo", "x y.part01.rar", ""][rng.below(5) as usize];
            packets.push(file_desc(id, name, rng.next() >> 20, rng));
            let mut body = vec![id; 16];
            body.extend((0..20 * rng.below(5)).map(|_| rng.next() as u8));
            packets.push(packet([7; 16], b"PAR 2.0\0IFSC\0\0\0\0", &body));
        }
        for _ in 0..rng.below(4) {
            let mut body = vec![0u8; 4];
            body.extend((0..4 * (1 + rng.below(300))).map(|_| rng.next() as u8));
            packets.push(packet([7; 16], b"PAR 2.0\0RecvSlic", &body));
        }
        packets.push(packet([7; 16], b"PAR 2.0\0Creator\0", b"test\0\0\0\0"));
        // mutations
        for _ in 0..rng.below(4) {
            let n = rng.below(packets.len() as u64) as usize;
            let kind = rng.below(9);
            if matches!(kind, 0 | 1 | 6 | 7) && packets[n].len() < 64 {
                continue; // junk inserted earlier: nothing to damage
            }
            match kind {
                0 => {
                    let at = 16 + rng.below(16) as usize;
                    packets[n][at] ^= 1 + rng.below(255) as u8; // header MD5 wrong
                }
                1 => {
                    let at = 32 + rng.below(packets[n].len() as u64 - 32) as usize;
                    packets[n][at] ^= 1 + rng.below(255) as u8; // body damaged
                }
                2 => packets.insert(n, vec![0x55; rng.below(30) as usize]), // junk between
                3 => packets.insert(n, b"PAR2\0PKT".to_vec()), // a magic with nothing after
                4 => {
                    let dup = packets[n].clone();
                    packets.insert(n, dup); // a duplicate packet
                }
                5 => {
                    // the same packet again, other values: a second Main or FileDesc
                    packets.push(if rng.below(2) == 0 {
                        main_packet(1 << (10 + rng.below(8)), &ids[..(rng.below(files as u64) as usize + 1)], files as u32)
                    } else {
                        file_desc(ids[rng.below(files as u64) as usize], "dup.bin", 1, rng)
                    });
                }
                6 => {
                    let len = [0u64, 8, 63, 65, 66, 100, 4096, 1 << 30, 1 << 40][rng.below(9) as usize];
                    packets[n][8..16].copy_from_slice(&len.to_le_bytes()); // a wrong length
                }
                7 => {
                    // a huge declared length with the header's bytes after it
                    let mut p = packets[n].clone();
                    p[8..16].copy_from_slice(&(10 * 1024 * 1024 + 64 + 4 * rng.below(100)).to_le_bytes());
                    p.truncate(16 + rng.below(80) as usize);
                    packets.insert(n, p);
                }
                _ => {
                    packets.remove(n);
                }
            }
        }
        let mut data: Vec<u8> = packets.concat();
        if rng.below(3) == 0 && !data.is_empty() {
            data.truncate(rng.below(data.len() as u64 + 1) as usize); // cut short anywhere
        }
        if rng.below(4) == 0 {
            data.splice(0..0, (0..rng.below(20)).map(|_| 0x11u8)); // junk first
        }
        data
    }

    #[test]
    fn walk_matches_the_crate() {
        let mut rng = Rng(0x9E3779B97F4A7C15);
        let (mut ok, mut err) = (0, 0);
        for round in 0..20000 {
            let data = random_set(&mut rng);
            let expected = crate_set(&data);
            for files in [true, false] {
                let got = walk(&data, files).0;
                match (&expected, &got) {
                    (None, None) => {}
                    (Some((slice, order, sigs)), Some(w)) => {
                        assert_eq!((*slice, order), (w.slice_size, &w.file_order), "round {round}");
                        if files {
                            let mut mine: Vec<_> = w.files.values().map(|f| (f.name.clone(), f.length, f.md5.clone())).collect();
                            mine.sort();
                            assert_eq!(sigs, &mine, "round {round}");
                        }
                    }
                    _ => panic!("round {round}: crate {:?}, walk {:?}", expected.is_some(), got.is_some()),
                }
            }
            if expected.is_some() { ok += 1 } else { err += 1 }
        }
        assert!(ok > 3000 && err > 3000, "{ok} sets parsed, {err} didn't");
    }

    /// par2_set and block_size as they were with rust-par2's parser.
    fn par2_set_before(data: &[u8]) -> (Vec<FileSig>, bool) {
        let (mut sigs, complete) = {
            let mut reader = std::io::Cursor::new(data);
            match rust_par2::parse_par2_reader(&mut reader, data.len() as u64) {
                Ok(set) if !set.files.is_empty() => {
                    let complete = !set.file_order.is_empty() && set.file_order.iter().all(|id| set.files.contains_key(id));
                    let sigs = set
                        .files
                        .values()
                        .map(|f| FileSig { name: f.filename.clone(), length: f.size, md5: hex(&f.hash) })
                        .collect();
                    (sigs, complete)
                }
                _ => (scan_file_descs(data), false),
            }
        };
        sigs.sort_by(|a, b| (&a.name, a.length, &a.md5).cmp(&(&b.name, b.length, &b.md5)));
        (sigs, complete)
    }

    fn block_size_before(data: &[u8]) -> u64 {
        let mut reader = std::io::Cursor::new(data);
        if let Ok(set) = rust_par2::parse_par2_reader(&mut reader, data.len() as u64) {
            if set.slice_size > 0 {
                return set.slice_size;
            }
        }
        let mut pos = 0usize;
        while pos + 72 <= data.len() {
            if &data[pos..pos + 8] == b"PAR2\0PKT" && &data[pos + 48..pos + 64] == b"PAR 2.0\0Main\0\0\0\0" {
                return u64::from_le_bytes(data[pos + 64..pos + 72].try_into().unwrap());
            }
            pos += 4;
        }
        0
    }

    #[test]
    fn par2_set_and_block_size_are_as_before() {
        let mut rng = Rng(0xA0761D6478BD642F);
        let mut sizes = 0;
        for round in 0..30000 {
            let mut data = random_set(&mut rng);
            if rng.below(6) == 0 {
                // a packet at a 4-byte offset in the shadow of the first 8 bytes, or past junk
                let junk = [4usize, 1, 2, 3, 5, 6, 7, 8, 12][rng.below(9) as usize];
                data.splice(0..0, std::iter::repeat_n(0x22u8, junk));
            }
            if rng.below(8) == 0 {
                data.splice(0..0, std::iter::repeat_n(0u8, 4 * rng.below(40) as usize)); // zeros, as lost articles leave
            }
            let (mut sigs, complete) = par2_set(&data);
            sigs.sort_by(|a, b| (&a.name, a.length, &a.md5).cmp(&(&b.name, b.length, &b.md5)));
            assert_eq!((sigs, complete), par2_set_before(&data), "par2_set, round {round}");
            let size = block_size(&data);
            assert_eq!(size, block_size_before(&data), "block_size, round {round}");
            if size > 0 {
                sizes += 1;
            }
        }
        assert!(sizes > 8000, "{sizes} sets with a block size");
    }

    #[test]
    fn walk_ends_at_a_length_past_the_data() {
        // a length that wraps negative ended in a loop in the crate
        let mut data = main_packet(4096, &[1], 1);
        let mut bad = b"PAR2\0PKT".to_vec();
        bad.extend_from_slice(&0xFFFF_FFFF_FFFF_FFC0u64.to_le_bytes());
        bad.extend_from_slice(&[0u8; 64]);
        data.extend_from_slice(&bad);
        data.extend_from_slice(&file_desc(1, "a", 1, &mut Rng(1)));
        let set = walk(&data, true).0.unwrap();
        assert_eq!(set.slice_size, 4096);
        assert!(set.files.is_empty());
    }
}

#[cfg(test)]
mod timing {
    use super::*;
    use std::time::Instant;

    fn best(f: impl Fn()) -> f64 {
        let mut best = f64::MAX;
        for _ in 0..21 {
            let t = Instant::now();
            for _ in 0..200 {
                f();
            }
            best = best.min(t.elapsed().as_secs_f64() / 200.0);
        }
        best * 1e9
    }

    #[test]
    #[ignore]
    fn par2_timing() {
        let dir = "/tmp/claude-1000/perf-a/";
        for name in ["par2_small.bin", "par2_idx.bin", "par2_vol.bin"] {
            let data = std::fs::read(format!("{dir}{name}")).unwrap();
            let walk_files = best(|| drop(std::hint::black_box(walk(&data, true).0)));
            let walk_main = best(|| drop(std::hint::black_box(walk(&data, false).0)));
            let set = best(|| drop(std::hint::black_box(par2_set(&data))));
            let sigs = par2_set(&data).0;
            let text = best(|| {
                let t: String = sigs.iter().map(|s| format!("{}\t{}\t{}\n", s.length, s.md5, s.name)).collect();
                std::hint::black_box(t);
            });
            let md5_only = best(|| {
                use md5::{Digest, Md5};
                let mut pos = 0;
                let mut n = 0;
                while pos + 16 <= data.len() {
                    let len = u64::from_le_bytes(data[pos + 8..pos + 16].try_into().unwrap()) as usize;
                    if len < 64 || pos + len > data.len() {
                        break;
                    }
                    if &data[pos + 48..pos + 64] == TYPE_FILE_DESC {
                        std::hint::black_box(Md5::digest(&data[pos + 32..pos + len]));
                        n += 1;
                    }
                    pos += len;
                }
                std::hint::black_box(n);
            });
            let sigs0 = par2_set(&data).0;
            if sigs0.len() == 30 {
                let fp = best(|| drop(std::hint::black_box(fingerprint(&sigs0))));
                let text: String = sigs0.iter().map(|s| format!("{}\t{}\n", s.length, s.md5)).collect();
                let parse = best(|| {
                    let files = text.lines().filter_map(|line| {
                        let mut parts = line.splitn(3, '\t');
                        let length: u64 = parts.next()?.parse().ok()?;
                        Some((parts.next()?, length))
                    });
                    std::hint::black_box(files.count());
                });
                eprintln!("fingerprint of 30: {fp:.0} ns, parsing its lines: {parse:.0} ns");
            }
            eprintln!("md5 of the FileDesc packets: {md5_only:.0} ns");
            eprintln!("{name}: walk(files) {walk_files:.0} ns, walk(main) {walk_main:.0} ns, par2_set {set:.0} ns, text {text:.0} ns");
        }
    }
}
