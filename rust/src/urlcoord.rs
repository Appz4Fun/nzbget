//! UrlCoordinator's own logic (UrlCoordinator.cpp): what a fetched NZB's
//! X-DNZB headers set and the statuses a finished fetch leaves. The fetch,
//! the queue and the scan stay C++.

/// What UrlDownloader::ProcessHeader takes from a header line.
#[derive(Debug, PartialEq, Eq)]
pub enum Dnzb {
    /// Not an X-DNZB header, or one without a colon.
    None,
    /// X-DNZB-Category's value, trimmed of CR, LF, space and tab: its start
    /// and end in the line.
    Category(usize, usize),
    /// Another X-DNZB- header: its parameter name ("*DNZB:" and the
    /// header's name, cut to 99 bytes as BString<100> cut it) and its value
    /// (from after the colon's spaces, right-trimmed, Latin-1 to UTF-8).
    Param(Vec<u8>, Vec<u8>),
}

pub fn dnzb_header(line: &[u8]) -> Dnzb {
    if let Some(value) = line.strip_prefix(b"X-DNZB-Category:") {
        let (start, end) = crate::util::trim_line(value);
        let prefix = line.len() - value.len();
        return Dnzb::Category(prefix + start, prefix + end);
    }
    if !line.starts_with(b"X-DNZB-") {
        return Dnzb::None;
    }
    let Some(colon) = crate::bytes::find_byte(line, b':') else { return Dnzb::None };
    let mut name = Vec::with_capacity(6 + colon - 7);
    name.extend_from_slice(b"*DNZB:");
    name.extend_from_slice(&line[7..colon]);
    name.truncate(99);
    let mut value = &line[colon + 1..];
    while let [b' ', rest @ ..] = value {
        value = rest;
    }
    // only the right end is trimmed: the left trim's result went unused
    let value = &value[..crate::util::trim_right_line(value)];
    let mut utf8 = Vec::new();
    crate::text::latin1_to_utf8(value, &mut utf8);
    Dnzb::Param(name, utf8)
}

/// WebDownloader::EStatus values UrlCompleted tests.
const AD_FINISHED: i32 = 2;
const AD_FAILED: i32 = 3;
const AD_RETRY: i32 = 4;
/// NzbInfo::EUrlStatus and EDeleteStatus values it sets.
const LS_NONE: i32 = 0;
const LS_FINISHED: i32 = 2;
const LS_FAILED: i32 = 3;
const DS_NONE: i32 = 0;
const DS_MANUAL: i32 = 1;

/// The statuses UrlCoordinator::UrlCompleted leaves on the NZB for the
/// downloader's status: (url status, delete status, retry). A deleted
/// NZB's fetch ends with no URL status and a manual delete unless it had
/// another; other statuses than finished, failed and retry keep the URL
/// status.
pub fn completed(downloader: i32, deleting: bool, url_status: i32, delete_status: i32) -> (i32, i32, bool) {
    let retry = downloader == AD_RETRY && !deleting;
    if deleting {
        return (LS_NONE, if delete_status == DS_NONE { DS_MANUAL } else { delete_status }, retry);
    }
    let url_status = match downloader {
        AD_FINISHED => LS_FINISHED,
        AD_FAILED => LS_FAILED,
        AD_RETRY => LS_NONE,
        _ => url_status,
    };
    (url_status, delete_status, retry)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn param(name: &[u8], value: &[u8]) -> Dnzb {
        Dnzb::Param(name.to_vec(), value.to_vec())
    }

    #[test]
    fn headers() {
        assert_eq!(dnzb_header(b"X-DNZB-Category: \tTV \r\n"), Dnzb::Category(18, 20));
        assert_eq!(dnzb_header(b"X-DNZB-Category:"), Dnzb::Category(16, 16));
        assert_eq!(dnzb_header(b"X-DNZB-Category: \r\n"), Dnzb::Category(16, 16));
        assert_eq!(dnzb_header(b"X-DNZB-Name:  Some Show \r\n"), param(b"*DNZB:Name", b"Some Show"));
        // a tab after the spaces stays: only spaces are skipped on the left
        assert_eq!(dnzb_header(b"X-DNZB-Name: \tx"), param(b"*DNZB:Name", b"\tx"));
        assert_eq!(dnzb_header(b"X-DNZB-MoreInfo:http://a:b"), param(b"*DNZB:MoreInfo", b"http://a:b"));
        assert_eq!(dnzb_header(b"X-DNZB-:v"), param(b"*DNZB:", b"v"));
        assert_eq!(dnzb_header(b"X-DNZB-Name:caf\xe9"), param(b"*DNZB:Name", "café".as_bytes()));
        assert_eq!(dnzb_header(b"X-DNZB-Name"), Dnzb::None);
        assert_eq!(dnzb_header(b"x-dnzb-name: v"), Dnzb::None);
        assert_eq!(dnzb_header(b"Content-Type: x"), Dnzb::None);
        assert_eq!(dnzb_header(b"X-DNZB-category: v"), param(b"*DNZB:category", b"v"));
        let long = [b"X-DNZB-".as_slice(), &[b'n'; 200], b": v"].concat();
        let Dnzb::Param(name, _) = dnzb_header(&long) else { panic!() };
        assert_eq!(name.len(), 99);
    }

    #[test]
    fn statuses() {
        assert_eq!(completed(AD_FINISHED, false, 1, 0), (LS_FINISHED, 0, false));
        assert_eq!(completed(AD_FAILED, false, 1, 0), (LS_FAILED, 0, false));
        assert_eq!(completed(AD_RETRY, false, 1, 0), (LS_NONE, 0, true));
        assert_eq!(completed(8, false, 1, 0), (1, 0, false));
        assert_eq!(completed(AD_RETRY, true, 1, 0), (LS_NONE, DS_MANUAL, false));
        assert_eq!(completed(AD_FINISHED, true, 1, 3), (LS_NONE, 3, false));
    }
}
