//! Twins and alts: duplicates of a download told apart by the files their par2
//! sets describe. A twin holds files byte-identical to the primary's (its
//! articles, par2-files and bytes can stand in for the primary's); a near-twin
//! shares most of them (a re-packed archive header); an alt is another encode.
//!
//! The C++ side (TwinCheck) fetches articles and walks the queue; everything
//! else lives here: reading nzb-files, parsing par2 FileDesc packets (with
//! rust-par2), fingerprints, the per-posting file lists kept in the queue
//! directory, labels, and picking a duplicate's file by content.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Cursor, Write};
use std::sync::Mutex;

/// One file of a par2 set: what identifies its bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileSig {
    pub name: String,
    pub length: u64,
    /// MD5 of the whole file, lower-case hex
    pub md5: String,
}

/// The files the FileDesc packets in `data` describe (a par2-file, or the part
/// of one that arrived: lost articles leave gaps, the parser skips to the next
/// packet). Empty when there's no usable set.
pub fn par2_sigs(data: &[u8]) -> Vec<FileSig> {
    let len = data.len() as u64;
    let mut reader = Cursor::new(data);
    match rust_par2::parse_par2_reader(&mut reader, len) {
        Ok(set) if !set.files.is_empty() => {
            let mut sigs: Vec<FileSig> = set
                .files
                .values()
                .map(|f| FileSig { name: f.filename.clone(), length: f.size, md5: hex(&f.hash) })
                .collect();
            sigs.sort_by(|a, b| a.name.cmp(&b.name));
            sigs
        }
        // its Main packet lost (the first article of the par2-file missing): the
        // FileDesc packets that arrived still tell the files
        _ => scan_file_descs(data),
    }
}

/// FileDesc packets read wherever they are in `data` (no Main packet needed).
fn scan_file_descs(data: &[u8]) -> Vec<FileSig> {
    let mut files: HashMap<[u8; 16], FileSig> = HashMap::new();
    let mut pos = 0usize;
    while pos + 64 <= data.len() {
        if &data[pos..pos + 8] != b"PAR2\0PKT" {
            pos += 4;
            continue;
        }
        let length = u64::from_le_bytes(data[pos + 8..pos + 16].try_into().unwrap()) as usize;
        if length < 64 || !length.is_multiple_of(4) || length > data.len() - pos {
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
    let mut reader = Cursor::new(data);
    if let Ok(set) = rust_par2::parse_par2_reader(&mut reader, data.len() as u64) {
        if set.slice_size > 0 {
            return set.slice_size;
        }
    }
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
    let name = filename.to_ascii_lowercase();
    let at = name.rfind(".vol")?;
    let plus = name[at..].find('+')? + at;
    let digits: String = name[plus + 1..].chars().take_while(char::is_ascii_digit).collect();
    digits.parse().ok()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// The posting's fingerprint: equal for postings of byte-identical files,
/// whatever their names. FNV-1a over the sorted "md5:length" lines, so the
/// values TwinCheck stored before (in C++) stay valid. "" for no files.
pub fn fingerprint(sigs: &[FileSig]) -> String {
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

/// How many of `primary`'s files `dupe` holds (by MD5 and length).
pub fn shared_files(primary: &[FileSig], dupe: &[FileSig]) -> usize {
    let held: HashSet<(&str, u64)> = dupe.iter().map(|s| (s.md5.as_str(), s.length)).collect();
    primary.iter().filter(|s| held.contains(&(s.md5.as_str(), s.length))).count()
}

/// The label of `dupe` against `primary`: "twin" (every file), "twin:N/M" (N of
/// the primary's M files: a near-twin), "alt" (none), "" when a list is empty.
pub fn kind(primary: &[FileSig], dupe: &[FileSig]) -> String {
    if primary.is_empty() || dupe.is_empty() {
        return String::new();
    }
    let shared = shared_files(primary, dupe);
    if shared == 0 {
        "alt".into()
    } else if shared == primary.len() && primary.len() == dupe.len() {
        "twin".into()
    } else {
        format!("twin:{shared}/{}", primary.len())
    }
}

/// The name of the duplicate's file holding the same bytes as our file named
/// `target` (or `target_alt`, the name our nzb gives it). `None`: we don't know
/// our file's content. `Some("")`: we do, and no duplicate file holds it (or
/// two do). Names compare without regard to case, like the C++ matching.
pub fn match_by_content(own: &[FileSig], target: &str, target_alt: &str, donor: &[FileSig]) -> Option<String> {
    let ours = own.iter().find(|s| {
        s.name.eq_ignore_ascii_case(target) || (!target_alt.is_empty() && s.name.eq_ignore_ascii_case(target_alt))
    })?;
    let mut found = donor.iter().filter(|s| s.md5 == ours.md5 && s.length == ours.length);
    match (found.next(), found.next()) {
        (Some(one), None) => Some(one.name.clone()),
        _ => Some(String::new()),
    }
}

/// The par2 file lists of the postings fingerprinted so far, by download id,
/// appended to a file in the queue directory: each list starts with a line
/// "id\tnew" and has "id\tlength\tmd5\tname" lines; a later list of an id
/// replaces the earlier one.
#[derive(Default)]
pub struct Store {
    path: String,
    sigs: HashMap<i32, Vec<FileSig>>,
}

impl Store {
    pub fn open(path: &str) -> Store {
        let mut store = Store { path: path.to_string(), sigs: HashMap::new() };
        if let Ok(file) = std::fs::File::open(path) {
            for line in BufReader::new(file).lines().map_while(Result::ok) {
                if let Some(id) = line.strip_suffix("\tnew").and_then(|id| id.parse::<i32>().ok()) {
                    store.sigs.insert(id, Vec::new());
                    continue;
                }
                let mut parts = line.splitn(4, '\t');
                let (Some(id), Some(length), Some(md5), Some(name)) = (parts.next(), parts.next(), parts.next(), parts.next())
                else {
                    continue;
                };
                let (Ok(id), Ok(length)) = (id.parse::<i32>(), length.parse::<u64>()) else {
                    continue;
                };
                store.sigs.entry(id).or_default().push(FileSig { name: name.to_string(), length, md5: md5.to_string() });
            }
        }
        store
    }

    pub fn put(&mut self, id: i32, sigs: Vec<FileSig>) {
        if let Ok(mut out) = OpenOptions::new().create(true).append(true).open(&self.path) {
            let mut text = format!("{id}\tnew\n");
            for s in &sigs {
                let name = s.name.replace(['\n', '\t', '\r'], "_");
                text.push_str(&format!("{id}\t{}\t{}\t{name}\n", s.length, s.md5));
            }
            let _ = out.write_all(text.as_bytes());
        }
        self.sigs.insert(id, sigs);
    }

    pub fn get(&self, id: i32) -> &[FileSig] {
        self.sigs.get(&id).map(Vec::as_slice).unwrap_or(&[])
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

#[cfg(test)]
mod tests {
    use super::*;

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

    #[test]
    fn kinds() {
        let primary = vec![sig("a", "1", 1), sig("b", "2", 2), sig("c", "3", 3)];
        assert_eq!(kind(&primary, &primary), "twin");
        assert_eq!(kind(&primary, &[sig("x", "1", 1), sig("y", "2", 2), sig("z", "9", 3)]), "twin:2/3");
        assert_eq!(kind(&primary, &[sig("x", "7", 1)]), "alt");
        assert_eq!(kind(&primary, &[]), "");
    }

    #[test]
    fn content_match() {
        let own = vec![sig("QnL.7z.002", "80a3", 500), sig("QnL.7z.001", "9f9b", 500)];
        let donor = vec![sig("TA7.7z.001", "d512", 500), sig("TA7.7z.002", "80a3", 500)];
        assert_eq!(match_by_content(&own, "QnL.7z.002", "", &donor), Some("TA7.7z.002".into()));
        assert_eq!(match_by_content(&own, "qnl.7Z.001", "", &donor), Some(String::new()));
        assert_eq!(match_by_content(&own, "other", "", &donor), None);
        assert_eq!(match_by_content(&own, "other", "QnL.7z.002", &donor), Some("TA7.7z.002".into()));
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
        let sigs = par2_sigs(&par2);
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
        assert_eq!(par2_sigs(&damaged).len(), 1);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn store_round_trip() {
        let path = std::env::temp_dir().join(format!("twincheck-test-{}", std::process::id()));
        let path = path.to_str().unwrap();
        let _ = std::fs::remove_file(path);
        let mut store = Store::open(path);
        store.put(7, vec![sig("a\tb", "1", 1)]);
        store.put(7, vec![sig("c", "2", 2)]);
        store.put(8, vec![sig("d", "3", 3)]);
        let again = Store::open(path);
        assert_eq!(again.get(7), &[sig("c", "2", 2)]);
        assert_eq!(again.get(8), &[sig("d", "3", 3)]);
        assert!(again.get(9).is_empty());
        let _ = std::fs::remove_file(path);
    }
}
