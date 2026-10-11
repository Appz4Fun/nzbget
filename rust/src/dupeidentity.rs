//! Identity and conservative admission policy for a bounded, decoded first article.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Identity {
    pub name: Vec<u8>,
    pub extension: Vec<u8>,
    pub bytes: u64,
}

use crate::releasename::{self, Attrs};

fn extension(name: &[u8]) -> Option<Vec<u8>> {
    let dot = name.iter().rposition(|&b| b == b'.')?;
    Some(name[dot + 1..].iter().map(u8::to_ascii_lowercase).collect())
}

pub fn is_media(name: &[u8]) -> bool {
    let Some(ext) = extension(name) else {
        return false;
    };
    if ![
        b"mkv".as_slice(),
        b"mp4",
        b"m4v",
        b"avi",
        b"ts",
        b"m2ts",
        b"wmv",
        b"mov",
    ]
    .contains(&ext.as_slice())
    {
        return false;
    }
    // Python's sample boundaries: punctuation and underscores delimit a token.
    !name
        .split(|b| !b.is_ascii_alphanumeric())
        .any(|s| s.eq_ignore_ascii_case(b"sample"))
}

fn identity(name: &[u8], bytes: u64, min_size: u64) -> Option<Identity> {
    if bytes == 0 || bytes < min_size || !is_media(name) {
        return None;
    }
    Some(Identity {
        name: name.to_vec(),
        extension: extension(name)?,
        bytes,
    })
}

fn le16(data: &[u8], pos: usize) -> Option<u16> {
    Some(u16::from_le_bytes(
        data.get(pos..pos.checked_add(2)?)?.try_into().ok()?,
    ))
}
fn le32(data: &[u8], pos: usize) -> Option<u32> {
    Some(u32::from_le_bytes(
        data.get(pos..pos.checked_add(4)?)?.try_into().ok()?,
    ))
}
fn vint(data: &[u8], pos: &mut usize) -> Option<u64> {
    let mut value = 0;
    for shift in (0..=63).step_by(7) {
        let byte = *data.get(*pos)?;
        *pos = pos.checked_add(1)?;
        if shift == 63 && byte > 1 {
            return None;
        }
        value |= u64::from(byte & 127) << shift;
        if byte & 128 == 0 {
            return Some(value);
        }
    }
    None
}
fn advance(end: usize, packed: u64, data: &[u8]) -> Option<usize> {
    let next = end.checked_add(usize::try_from(packed).ok()?)?;
    (next <= data.len()).then_some(next)
}

fn rar4(data: &[u8], min_size: u64) -> Option<Identity> {
    let mut i: usize = 7;
    while i < data.len() {
        let prefix = data.get(i..i.checked_add(7)?)?;
        let kind = prefix[2];
        let flags = le16(prefix, 3)?;
        let size = usize::from(le16(prefix, 5)?);
        if size < 7 {
            return None;
        }
        let end = i.checked_add(size)?;
        let h = data.get(i..end)?; // the entire header must be in the decoded article
        let mut packed = if flags & 0x8000 != 0 {
            u64::from(le32(h, 7)?)
        } else {
            0
        };
        if kind == 0x74 {
            if size < 32 || flags & 0x8000 == 0 {
                return None;
            }
            let mut bytes = u64::from(le32(h, 11)?);
            let n = usize::from(le16(h, 26)?);
            let mut j = 32;
            if flags & 0x100 != 0 {
                packed |= u64::from(le32(h, j)?) << 32;
                bytes |= u64::from(le32(h, j + 4)?) << 32;
                j += 8;
            }
            if n == 0 {
                return None;
            }
            let raw = h.get(j..j.checked_add(n)?)?;
            let name = if flags & 0x200 != 0 {
                raw.split(|&b| b == 0).next()?
            } else {
                raw
            };
            if bytes == u64::from(u32::MAX) || bytes == u64::MAX {
                return None;
            }
            if flags & 0xe0 != 0xe0 {
                if let Some(id) = identity(name, bytes, min_size) {
                    return Some(id);
                }
            }
        } else if kind == 0x73 {
            if flags & 0x80 != 0 {
                return None;
            } // encrypted headers
        } else if !matches!(kind, 0x72 | 0x75..=0x7a) {
            return None;
        }
        i = advance(end, packed, data)?;
    }
    None
}
fn rar5(data: &[u8], min_size: u64) -> Option<Identity> {
    let mut i: usize = 8;
    while i < data.len() {
        let mut j = i.checked_add(4)?;
        let size = usize::try_from(vint(data, &mut j)?).ok()?;
        if size == 0 {
            return None;
        }
        let end = j.checked_add(size)?;
        let h = data.get(j..end)?;
        let mut p = 0;
        let kind = vint(h, &mut p)?;
        let flags = vint(h, &mut p)?;
        let extra = if flags & 1 != 0 {
            usize::try_from(vint(h, &mut p)?).ok()?
        } else {
            0
        };
        let packed = if flags & 2 != 0 { vint(h, &mut p)? } else { 0 };
        let body_end = h.len().checked_sub(extra)?;
        let body = h.get(..body_end)?;
        if p > body_end {
            return None;
        }
        if kind == 2 {
            let fileflags = vint(body, &mut p)?;
            if fileflags & 1 == 0 {
                if fileflags & 8 != 0 {
                    return None;
                }
                let bytes = vint(body, &mut p)?;
                vint(body, &mut p)?; // attributes
                if fileflags & 2 != 0 {
                    p = p.checked_add(4)?;
                }
                if fileflags & 4 != 0 {
                    p = p.checked_add(4)?;
                }
                vint(body, &mut p)?; // compression
                vint(body, &mut p)?; // OS
                let n = usize::try_from(vint(body, &mut p)?).ok()?;
                let name = body.get(p..p.checked_add(n)?)?;
                if let Some(id) = identity(name, bytes, min_size) {
                    return Some(id);
                }
            }
        } else if kind != 1 && kind != 3 {
            return None; // includes encrypted headers, end marker and unsupported block types
        }
        i = advance(end, packed, data)?;
    }
    None
}

/// A complete media header is enough; its packed payload can extend beyond this article.
/// No decompression, NNTP, filesystem access, or whole-volume allocation occurs here.
/// The general RAR reader cannot preserve unknown-size/directory flags or full u64 sizes;
/// this path therefore validates the bounded header directly instead of using its callback.
pub fn inner_entry(data: &[u8], name: &[u8], total: u64, min_size: u64) -> Option<Identity> {
    if data.starts_with(b"Rar!\x1a\x07\x01\x00") {
        rar5(data, min_size)
    } else if data.starts_with(b"Rar!\x1a\x07\x00") {
        rar4(data, min_size)
    } else {
        identity(name, total, min_size)
    }
}

fn basename(name: &[u8]) -> &[u8] {
    name.rsplit(|&b| b == b'/' || b == b'\\')
        .next()
        .unwrap_or(name)
}
fn compatible_sets(a: &Attrs, b: &Attrs) -> bool {
    [
        (&a.resolution, &b.resolution),
        (&a.quality, &b.quality),
        (&a.codec, &b.codec),
        (&a.bit_depth, &b.bit_depth),
        (&a.audio, &b.audio),
        (&a.channels, &b.channels),
        (&a.network, &b.network),
        (&a.edition, &b.edition),
    ]
    .into_iter()
    .all(|(a, b)| a.is_empty() || b.is_empty() || a.is_subset(b) || b.is_subset(a))
}
pub fn conflicts(primary: &[u8], candidate: &[u8]) -> bool {
    let a = releasename::parse(primary);
    let b = releasename::parse(basename(candidate));
    (a.year != 0 && b.year != 0 && a.year != b.year)
        || (b.repack && !a.repack)
        || (b.proper && !a.proper)
        || !compatible_sets(&a, &b)
        || (!b.group.is_empty() && a.group != b.group)
        || (!b.resolution.is_empty() && a.resolution != b.resolution)
        || (!b.seasons.is_empty() && a.seasons != b.seasons)
        || (!b.episodes.is_empty() && a.episodes != b.episodes)
        || (!b.hdr.is_empty() && a.hdr != b.hdr)
}
pub fn consistent(primary: &[u8], candidate: &[u8]) -> bool {
    let a = releasename::parse(primary);
    let b = releasename::parse(candidate);
    !a.title.is_empty()
        && a.title == b.title
        && a.seasons == b.seasons
        && a.episodes == b.episodes
        && !(a.year != 0 && b.year != 0 && a.year != b.year)
        && (b.group.is_empty() || a.group == b.group)
        && (b.resolution.is_empty() || a.resolution == b.resolution)
        && (b.hdr.is_empty() || a.hdr == b.hdr)
}
pub fn other_title(primary: &[u8], candidate: &[u8]) -> bool {
    let candidate = basename(candidate);
    let a = releasename::parse(primary);
    let b = releasename::parse(candidate);
    !b.title.is_empty()
        && b.title != a.title
        && (!b.seasons.is_empty()
            || !b.episodes.is_empty()
            || b.year != 0
            || releasename::readable(candidate))
}
pub fn names_compatible(primary: &[u8], candidate: &[u8]) -> bool {
    consistent(primary, candidate) && !conflicts(primary, candidate)
}
fn digest_rest(name: &[u8]) -> (&[u8], &[u8]) {
    let name = releasename::trim(basename(name), b" \t\r\n");
    let n = name
        .iter()
        .position(|b| b.is_ascii_whitespace() || b"._-()[]".contains(b))
        .unwrap_or(name.len());
    let mut end = n;
    while end < name.len() && (name[end].is_ascii_whitespace() || b"._-()[]".contains(&name[end])) {
        end += 1;
    }
    (&name[..n], &name[end..])
}
pub fn hashlike(name: &[u8]) -> bool {
    let (first, rest) = digest_rest(name);
    if first.len() < 12
        || !first.iter().all(u8::is_ascii_hexdigit)
        || !first.iter().any(u8::is_ascii_digit)
        || !first
            .iter()
            .any(|b| matches!(b.to_ascii_lowercase(), b'a'..=b'f'))
    {
        return false;
    }
    let a = releasename::parse(rest);
    if !a.seasons.is_empty() || !a.episodes.is_empty() || a.year != 0 {
        return false;
    }
    a.title.is_empty()
        || a.title == a.group
        || [
            b"remux".as_slice(),
            b"hybrid",
            b"proper",
            b"repack",
            b"internal",
            b"multi",
            b"dubbed",
            b"subbed",
            b"uhd",
            b"extended",
            b"uncut",
            b"imax",
            b"complete",
            b"remastered",
            b"unrated",
        ]
        .contains(&a.title.as_slice())
}
/// Listing admission only: any lenient hit still requires `lenient_ok` after inspection.
pub fn candidate_ok(
    primary: &[u8],
    primary_bytes: u64,
    candidate: &[u8],
    candidate_bytes: u64,
    tolerance: f64,
    lenient: bool,
) -> bool {
    if !tolerance.is_finite() || tolerance < 0.0 {
        return false;
    }
    let diff = primary_bytes.abs_diff(candidate_bytes) as f64;
    if tolerance != 0.0 && primary_bytes != 0 && diff > tolerance * primary_bytes as f64 {
        return false;
    }
    if releasename::same_release(primary, candidate) {
        return true;
    }
    if !lenient {
        return false;
    }
    if names_compatible(primary, candidate) {
        return true;
    }
    let hashed = hashlike(candidate);
    let named = if hashed {
        digest_rest(candidate).1
    } else {
        candidate
    };
    (!releasename::readable(candidate) || hashed)
        && !conflicts(primary, named)
        && (hashed || !other_title(primary, candidate))
        && primary_bytes != 0
        && candidate_bytes != 0
        && diff <= 0.01 * primary_bytes as f64
}
/// Exact inner extension/size is proof only after the inner name's contradictions are rejected.
/// Unknown inner identities require a readable, strictly matching NZB main filename.
pub fn lenient_ok(
    title: &[u8],
    candidate_main_name: &[u8],
    mine: Option<&Identity>,
    theirs: Option<&Identity>,
) -> bool {
    if let Some(theirs) = theirs {
        if conflicts(title, &theirs.name) || other_title(title, &theirs.name) {
            return false;
        }
    }
    if let (Some(mine), Some(theirs)) = (mine, theirs) {
        return mine.bytes != 0 && mine.bytes == theirs.bytes && mine.extension == theirs.extension;
    }
    releasename::readable(candidate_main_name)
        && releasename::same_release(title, candidate_main_name)
}

/// The caller supplies counts of data files after excluding parity files.
pub fn same_data(a_bytes: u64, a_files: u32, b_bytes: u64, b_files: u32) -> bool {
    a_bytes != 0 && a_bytes == b_bytes && a_files == b_files
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn same_data_requires_positive_bytes_and_exact_file_count() {
        assert!(same_data(1234, 2, 1234, 2));
        assert!(!same_data(0, 2, 0, 2));
        assert!(!same_data(1234, 2, 1235, 2));
        assert!(!same_data(1234, 2, 1234, 3));
    }
    #[test]
    fn inner_size_proof_does_not_override_contradictory_name() {
        let title = b"Show.S01E02.2025.1080p.WEB-DL.x264-GRP";
        let mine = Identity {
            name: title.to_vec(),
            extension: b"mkv".to_vec(),
            bytes: 1234,
        };
        for name in [
            b"Show.S01E03.2025.1080p.WEB-DL.x264-GRP".as_slice(),
            b"Show.S01E02.2024.1080p.WEB-DL.x264-GRP",
            b"Show.S01E02.2025.720p.WEB-DL.x264-GRP",
            b"Show.S01E02.2025.1080p.WEB-DL.x265-GRP",
            b"Show.S01E02.2025.1080p.WEB-DL.x264.HDR-GRP",
            b"Show.S01E02.2025.1080p.WEB-DL.x264-OTHER",
        ] {
            let theirs = Identity {
                name: name.to_vec(),
                ..mine.clone()
            };
            assert!(
                !lenient_ok(title, title, Some(&mine), Some(&theirs)),
                "{:?}",
                name
            );
        }
        let hashed = Identity {
            name: b"abcdef1234567890.mkv".to_vec(),
            ..mine.clone()
        };
        assert!(lenient_ok(title, title, Some(&mine), Some(&hashed)));
        assert!(!lenient_ok(title, b"abcdef1234567890.rar", None, None));
        assert!(lenient_ok(title, title, None, None));
    }
    fn rar4(name: &[u8], bytes: u32) -> Vec<u8> {
        let mut out = b"Rar!\x1a\x07\x00".to_vec();
        let mut h = vec![0; 32];
        h[2] = 0x74;
        h[3..5].copy_from_slice(&0x8000u16.to_le_bytes());
        h[5..7].copy_from_slice(&((32 + name.len()) as u16).to_le_bytes());
        h[11..15].copy_from_slice(&bytes.to_le_bytes());
        h[26..28].copy_from_slice(&(name.len() as u16).to_le_bytes());
        out.extend(h);
        out.extend(name);
        out
    }
    #[test]
    fn bare_media_requires_known_size() {
        assert_eq!(
            inner_entry(b"bytes", b"Show.mkv", 1234, 1000)
                .unwrap()
                .bytes,
            1234
        );
        assert!(inner_entry(b"bytes", b"Show.mkv", 0, 0).is_none());
        assert!(inner_entry(b"bytes", b"Show.mkv", 999, 1000).is_none());
        assert!(inner_entry(b"bytes", b"Show.sample.mkv", 1234, 0).is_none());
    }
    #[test]
    fn header_identity_does_not_require_packed_payload() {
        let data = rar4(b"movie.mkv", 1234);
        let id = inner_entry(&data, b"archive.rar", 8888, 1000).unwrap();
        assert_eq!(id.name, b"movie.mkv");
        assert_eq!(id.extension, b"mkv");
        assert_eq!(id.bytes, 1234);
        for n in 0..data.len() {
            assert!(inner_entry(&data[..n], b"archive.rar", 8888, 0).is_none());
        }
    }
    #[test]
    fn rejects_unknown_size_and_skips_sidecars() {
        let mut data = rar4(b"notes.nfo", 3);
        data.extend_from_slice(&rar4(b"movie.mkv", 1234)[7..]);
        assert_eq!(
            inner_entry(&data, b"archive.rar", 0, 1000).unwrap().bytes,
            1234
        );
        assert!(inner_entry(&rar4(b"movie.mkv", u32::MAX), b"archive.rar", 0, 0).is_none());
    }
}
