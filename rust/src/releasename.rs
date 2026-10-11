//! ReleaseName (daemon/dupesearch/ReleaseName.cpp): release names as indexers
//! list them, parsed into the attributes the duplicate search compares.
//!
//! Parity notes. The C++ used `std::regex` (ECMAScript, the classic "C" locale:
//! ASCII `\d`, `\w` and case folding) for a few anchored patterns; they are
//! matched by hand here, trying alternatives in the order the regex engine
//! does, so the matches and captures are the same. Everything else used the C
//! library's ctype (`isalnum`, `isdigit`, `isspace`, `tolower`, `isalpha`),
//! which nzbget sets from the environment (`setlocale(LC_CTYPE, "")`); those
//! are called through libc here too.

use std::collections::BTreeSet;
use std::ffi::c_int;

extern "C" {
    fn isalnum(c: c_int) -> c_int;
    fn isalpha(c: c_int) -> c_int;
    fn isdigit(c: c_int) -> c_int;
    fn isspace(c: c_int) -> c_int;
    fn tolower(c: c_int) -> c_int;
}

fn c_alnum(b: u8) -> bool {
    unsafe { isalnum(b as c_int) != 0 }
}
fn c_alpha(b: u8) -> bool {
    unsafe { isalpha(b as c_int) != 0 }
}
fn c_digit(b: u8) -> bool {
    unsafe { isdigit(b as c_int) != 0 }
}
fn c_space(b: u8) -> bool {
    unsafe { isspace(b as c_int) != 0 }
}
fn c_lower(b: u8) -> u8 {
    unsafe { tolower(b as c_int) as u8 }
}

/// Longer input is cut before any pattern sees it.
pub const MAX_NAME_LENGTH: usize = 512;

/// DupeUtil::Lower: `tolower` on every byte.
pub fn lower(text: &[u8]) -> Vec<u8> {
    text.iter().map(|&b| c_lower(b)).collect()
}

/// DupeUtil::Trim: without any of `chars` at the start and end.
pub fn trim<'a>(text: &'a [u8], chars: &[u8]) -> &'a [u8] {
    match text.iter().position(|b| !chars.contains(b)) {
        None => &[],
        Some(begin) => {
            let end = text.iter().rposition(|b| !chars.contains(b)).unwrap_or(begin);
            &text[begin..=end]
        }
    }
}

fn is_digits(text: &[u8]) -> bool {
    !text.is_empty() && text.iter().all(|&b| c_digit(b))
}

// ---- the std::regex patterns, by hand (ASCII, as the classic locale) ----

fn ascii_digit(b: u8) -> bool {
    b.is_ascii_digit()
}

/// Bytes at `pos` equal `word` ignoring ASCII case (std::regex::icase).
fn eq_icase(text: &[u8], pos: usize, word: &[u8]) -> bool {
    text.len() >= pos + word.len() && text[pos..pos + word.len()].eq_ignore_ascii_case(word)
}

/// Does the extension alternation match `text[pos..]` exactly to its end
/// (`(part\d+\.rar|vol\d+\+\d+\.par2|7z\.\d{3}|r\d{2}|z\d{2}|nzb|...)$`, icase)?
fn extension_tail(text: &[u8], pos: usize) -> bool {
    let rest = &text[pos..];
    let words: [&[u8]; 19] = [b"nzb", b"mkv", b"mp4", b"m4v", b"avi", b"ts", b"rar", b"par2", b"7z", b"zip",
                              b"nfo", b"sfv", b"srr", b"srt", b"sub", b"idx", b"jpg", b"png", b"txt"];
    let digits = |s: &[u8]| s.iter().take_while(|&&b| ascii_digit(b)).count();
    // part\d+\.rar
    if eq_icase(rest, 0, b"part") {
        let n = digits(&rest[4..]);
        if n > 0 && rest.len() == 4 + n + 4 && eq_icase(rest, 4 + n, b".rar") {
            return true;
        }
    }
    // vol\d+\+\d+\.par2
    if eq_icase(rest, 0, b"vol") {
        let n = digits(&rest[3..]);
        if n > 0 && rest.get(3 + n) == Some(&b'+') {
            let m = digits(&rest[4 + n..]);
            if m > 0 && rest.len() == 4 + n + m + 5 && eq_icase(rest, 4 + n + m, b".par2") {
                return true;
            }
        }
    }
    // 7z\.\d{3}
    if rest.len() == 6 && eq_icase(rest, 0, b"7z.") && rest[3..].iter().all(|&b| ascii_digit(b)) {
        return true;
    }
    // r\d{2}, z\d{2}
    if rest.len() == 3 && (rest[0] | 0x20 == b'r' || rest[0] | 0x20 == b'z') && ascii_digit(rest[1]) && ascii_digit(rest[2]) {
        return true;
    }
    words.iter().any(|w| rest.len() == w.len() && rest.eq_ignore_ascii_case(w))
}

/// regex_search for `\.(alternation)$`: the leftmost '.' after which an
/// alternative fills the rest.
fn find_extension(text: &[u8]) -> Option<usize> {
    (0..text.len()).find(|&i| text[i] == b'.' && extension_tail(text, i + 1))
}

const JUNK: [&[u8]; 12] = [b"xpost", b"postbot", b"obfuscated", b"scrambled", b"asrequested", b"rp", b"rakuv",
                           b"buymore", b"chamele0n", b"sample", b"repost", b""];

/// Can `([.\-_ ](xpost|...|rakuv\w*|...))+$` (icase) match from `pos` to the end?
fn junk_from(text: &[u8], pos: usize) -> bool {
    // positions after one or more repetitions; a repetition is a separator and a word
    let mut reachable = vec![false; text.len() + 1];
    let mut todo = vec![pos];
    let mut seen = vec![false; text.len() + 1];
    while let Some(p) = todo.pop() {
        if seen[p] || p >= text.len() || !matches!(text[p], b'.' | b'-' | b'_' | b' ') {
            continue;
        }
        seen[p] = true;
        let q = p + 1;
        for w in JUNK.iter().take(11) {
            if eq_icase(text, q, w) {
                let mut ends = vec![q + w.len()];
                if *w == b"rakuv" {
                    // rakuv\w*: any run of [A-Za-z0-9_] after it
                    let mut e = q + w.len();
                    while e < text.len() && (text[e].is_ascii_alphanumeric() || text[e] == b'_') {
                        e += 1;
                        ends.push(e);
                    }
                }
                for e in ends {
                    if !reachable[e] {
                        reachable[e] = true;
                        todo.push(e);
                    }
                }
            }
        }
    }
    reachable[text.len()]
}

/// regex_search for the junk pattern: the leftmost start that reaches the end.
fn find_junk(text: &[u8]) -> Option<usize> {
    (0..text.len()).find(|&i| junk_from(text, i))
}

/// ReleaseName::Clean: without extensions, volume suffixes, [tags], {tags} and indexer junk.
pub fn clean(name: &[u8]) -> Vec<u8> {
    let cut = &name[..name.len().min(MAX_NAME_LENGTH)];
    let mut text = trim(cut, b" \t\r\n").to_vec();
    loop {
        let before = text.clone();
        if let Some(pos) = find_extension(&text) {
            text.truncate(pos);
        } else if text.len() > 4
            && text[text.len() - 4] == b'.'
            && is_digits(&text[text.len() - 3..])
            && c_lower(text[text.len() - 5]) != b'h'
            && c_lower(text[text.len() - 5]) != b'x'
        {
            text.truncate(text.len() - 4); // a split volume ".001", but not the codec of "H.265"
        }
        if text == before {
            break;
        }
    }
    // [tags] and {tags}
    let mut stripped = Vec::with_capacity(text.len());
    let mut depth = 0;
    let mut closer = 0u8;
    for &ch in &text {
        if depth == 0 && (ch == b'[' || ch == b'{') {
            depth = 1;
            closer = if ch == b'[' { b']' } else { b'}' };
            stripped.push(b' ');
        } else if depth == 1 {
            if ch == closer {
                depth = 0;
            }
        } else {
            stripped.push(ch);
        }
    }
    if depth == 1 {
        stripped = text.clone(); // an unclosed bracket is no tag
    }
    let mut text = trim(&stripped, b" \t\r\n").to_vec();
    if let Some(pos) = find_junk(&text) {
        text.truncate(pos);
    }
    trim(&text, b" ._-").to_vec()
}

/// ReleaseName::Normalize: the lowercase clean name, every run of separators a dot.
pub fn normalize(name: &[u8]) -> Vec<u8> {
    let text = lower(&clean(name));
    let mut out = Vec::with_capacity(text.len());
    let mut separator = false;
    for &ch in &text {
        // strchr("._-()+,", ch) also finds the terminating NUL
        if c_space(ch) || matches!(ch, b'.' | b'_' | b'-' | b'(' | b')' | b'+' | b',' | 0) {
            separator = true;
            continue;
        }
        if separator && !out.is_empty() {
            out.push(b'.');
        }
        separator = false;
        out.push(ch);
    }
    out
}

/// `^s\d{1,3}(e\d{1,4})*$` (and its captures: the season digits and the e-groups' digits).
fn season_episode(tok: &[u8]) -> Option<(&[u8], Vec<&[u8]>)> {
    if tok.first() != Some(&b's') {
        return None;
    }
    let n = tok[1..].iter().take_while(|&&b| ascii_digit(b)).count();
    if n == 0 || n > 3 {
        return None;
    }
    let mut episodes = Vec::new();
    let mut p = 1 + n;
    while p < tok.len() {
        if tok[p] != b'e' {
            return None;
        }
        let m = tok[p + 1..].iter().take_while(|&&b| ascii_digit(b)).count();
        if m == 0 || m > 4 {
            return None;
        }
        episodes.push(&tok[p + 1..p + 1 + m]);
        p += 1 + m;
    }
    Some((&tok[1..1 + n], episodes))
}

fn is_episode_token(tok: &[u8]) -> bool {
    season_episode(tok).is_some() && tok.len() > 1
}

fn is_year_token(tok: &[u8]) -> bool {
    tok.len() == 4 && is_digits(tok) && (tok.starts_with(b"19") || tok.starts_with(b"20"))
}

/// `^(\d{3,4})[pi]$|^4k$|^uhd$|^fhd$`
fn is_resolution_token(tok: &[u8]) -> bool {
    let n = tok.len();
    (n == 4 || n == 5) && tok[..n - 1].iter().all(|&b| ascii_digit(b)) && matches!(tok[n - 1], b'p' | b'i')
        || tok == b"4k"
        || tok == b"uhd"
        || tok == b"fhd"
}

/// ReleaseName::ShortQuery: the title up to the season/episode or year plus the resolution; empty without either.
pub fn short_query(title: &[u8]) -> Vec<u8> {
    let normalized = normalize(title);
    let tokens: Vec<&[u8]> = normalized.split(|&b| b == b'.').collect();
    let cut = tokens
        .iter()
        .position(|t| (is_episode_token(t) && t.contains(&b'e')) || is_year_token(t));
    let Some(cut) = cut else { return Vec::new() };
    let mut query = Vec::new();
    for (i, t) in tokens[..=cut].iter().enumerate() {
        if i > 0 {
            query.push(b' ');
        }
        query.extend_from_slice(t);
    }
    // ^(\d{3,4}p|4k|uhd)$
    let resolution = |t: &[u8]| {
        let n = t.len();
        (n == 4 || n == 5) && t[..n - 1].iter().all(|&b| ascii_digit(b)) && t[n - 1] == b'p' || t == b"4k" || t == b"uhd"
    };
    if let Some(t) = tokens[cut + 1..].iter().find(|t| resolution(t)) {
        query.push(b' ');
        query.extend_from_slice(t);
    }
    query
}

/// The attributes Parse finds.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Attrs {
    pub resolution: BTreeSet<Vec<u8>>,
    pub quality: BTreeSet<Vec<u8>>,
    pub codec: BTreeSet<Vec<u8>>,
    pub bit_depth: BTreeSet<Vec<u8>>,
    pub audio: BTreeSet<Vec<u8>>,
    pub channels: BTreeSet<Vec<u8>>,
    pub network: BTreeSet<Vec<u8>>,
    pub edition: BTreeSet<Vec<u8>>,
    pub hdr: BTreeSet<Vec<u8>>,
    pub title: Vec<u8>,
    pub group: Vec<u8>,
    pub seasons: Vec<i32>,
    pub episodes: Vec<i32>,
    pub year: i32,
    pub repack: bool,
    pub proper: bool,
}

/// C atoi on a run of at most 4 ASCII digits.
fn atoi(digits: &[u8]) -> i32 {
    digits.iter().fold(0, |n, &b| n * 10 + (b - b'0') as i32)
}

/// (end of group 1, group 2's span, group 3's span, end of the match)
type RangeMatch = (usize, (usize, usize), (usize, usize), usize);
/// After the final e-group: group 3's span and the end of the match.
type Tail<'a> = &'a dyn Fn(usize) -> Option<((usize, usize), usize)>;

/// One match of `([sS]\d{1,3}(?:[eE]\d{1,4})*[eE](\d{1,4}))-[eE]?(\d{1,4})(?![0-9A-Za-z])`
/// starting at `start`, in the regex engine's order: (end of group 1, group 2, group 3, end).
fn episode_range_at(s: &[u8], start: usize) -> Option<RangeMatch> {
    if !matches!(s.get(start), Some(b's') | Some(b'S')) {
        return None;
    }
    let run = |p: usize| s[p.min(s.len())..].iter().take_while(|&&b| ascii_digit(b)).count();
    let is_e = |p: usize| matches!(s.get(p), Some(b'e') | Some(b'E'));
    // after the final [eE](\d{1,4}) group: -[eE]?(\d{1,4})(?![0-9A-Za-z])
    let tail = |g1_end: usize| -> Option<((usize, usize), usize)> {
        if s.get(g1_end) != Some(&b'-') {
            return None;
        }
        let p = g1_end + 1;
        for with_e in [true, false] {
            if with_e && !is_e(p) {
                continue;
            }
            let q = p + usize::from(with_e);
            let n = run(q).min(4);
            for k in (1..=n).rev() {
                let end = q + k;
                if !s.get(end).is_some_and(|b| b.is_ascii_alphanumeric()) {
                    return Some(((q, end), end));
                }
            }
        }
        None
    };
    // (?:[eE]\d{1,4})* greedily, then [eE](\d{1,4}) and the tail: backtracking order
    fn groups(p: usize, run: &dyn Fn(usize) -> usize, is_e: &dyn Fn(usize) -> bool, tail: Tail) -> Option<RangeMatch> {
        if is_e(p) {
            let n = run(p + 1).min(4);
            // one more repetition first (greedy), digits greedy
            for k in (1..=n).rev() {
                if let Some(m) = groups(p + 1 + k, run, is_e, tail) {
                    return Some(m);
                }
            }
            // or end the repetitions here: this is the last [eE](\d{1,4})
            for k in (1..=n).rev() {
                let g1_end = p + 1 + k;
                if let Some((g3, end)) = tail(g1_end) {
                    return Some((g1_end, (p + 1, g1_end), g3, end));
                }
            }
        }
        None
    }
    let n = run(start + 1).min(3);
    for k in (1..=n).rev() {
        if let Some(m) = groups(start + 1 + k, &run, &is_e, &tail) {
            return Some(m);
        }
    }
    None
}

/// "S01E01-E03" and "S01E01-03" written as "S01E01E02E03" (a forward range of at most 50).
fn rewrite_episode_ranges(clean: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(clean.len());
    let mut rest = 0;
    let mut pos = 0;
    while pos <= clean.len() {
        let found = (pos..clean.len()).find_map(|i| episode_range_at(clean, i).map(|m| (i, m)));
        let Some((start, (g1_end, g2, g3, end))) = found else { break };
        let first = atoi(&clean[g2.0..g2.1]);
        let last = atoi(&clean[g3.0..g3.1]);
        out.extend_from_slice(&clean[rest..start]);
        if first < last && last - first <= 50 {
            out.extend_from_slice(&clean[start..g1_end]);
            for episode in first + 1..=last {
                out.push(b'e');
                out.extend_from_slice(episode.to_string().as_bytes());
            }
        } else {
            out.extend_from_slice(&clean[start..end]);
        }
        rest = end;
        pos = end;
        if end == start {
            break;
        }
    }
    out.extend_from_slice(&clean[rest..]);
    out
}

fn not_a_group(word: &[u8]) -> bool {
    const WORDS: [&[u8]; 15] = [b"hd", b"ma", b"dl", b"rip", b"ray", b"dts", b"hdr", b"dv", b"ac3", b"eac3", b"dd",
                                b"ddp", b"x", b"e", b"es"];
    word.len() < 2 && !c_alpha(word[0]) || WORDS.contains(&word)
}

/// `^(ddpa|ddp|dd|eac3|ac3|aac|dtshd|dtsx|dtses|dts|truehd|flac|opus|mp3|lpcm|pcm)(\d?)$`: (kind, digit).
fn audio(tok: &[u8]) -> Option<(&[u8], &[u8])> {
    const KINDS: [&[u8]; 16] = [b"ddpa", b"ddp", b"dd", b"eac3", b"ac3", b"aac", b"dtshd", b"dtsx", b"dtses", b"dts",
                                b"truehd", b"flac", b"opus", b"mp3", b"lpcm", b"pcm"];
    KINDS.iter().find_map(|k| {
        let rest = tok.strip_prefix(*k)?;
        (rest.is_empty() || rest.len() == 1 && ascii_digit(rest[0])).then_some((&tok[..k.len()], rest))
    })
}

/// ReleaseName::Parse.
pub fn parse(name: &[u8]) -> Attrs {
    let mut attrs = Attrs::default();
    let clean = rewrite_episode_ranges(&clean(name));

    // the release group follows the last hyphen
    let mut body: &[u8] = &clean;
    if let Some(hyphen) = clean.iter().rposition(|&b| b == b'-') {
        let tail = trim(&clean[hyphen + 1..], b"\"' ");
        let lower_tail = lower(tail);
        if !tail.is_empty() && !tail.iter().any(|b| b" .\"'".contains(b)) && !not_a_group(&lower_tail) {
            attrs.group = lower_tail;
            body = &clean[..hyphen];
        } else if tail.is_empty() {
            body = &clean[..hyphen];
        }
    }

    // spellings that contain separators become one word
    let mut text = lower(body);
    const JOINS: [(&[u8], &[u8]); 19] = [(b"hdr10+", b"hdr10plus"), (b"dd+", b"ddp"), (b"e-ac-3", b"eac3"),
        (b"e-ac3", b"eac3"), (b"blu-ray", b"bluray"), (b"web-dl", b"webdl"), (b"dts-hd", b"dtshd"), (b"dts-x", b"dtsx"),
        (b"dts-es", b"dtses"), (b"ac-3", b"ac3"), (b"dolby vision", b"dovi"), (b"dolby.vision", b"dovi"),
        (b"dolby-vision", b"dovi"), (b"dolby_vision", b"dovi"), (b"dolbyvision", b"dovi"), (b"hdr 10", b"hdr10"),
        (b"web dl", b"webdl"), (b"dts hd", b"dtshd"), (b"blu ray", b"bluray")];
    for (from, to) in JOINS {
        let mut pos = crate::bytes::find(&text, from);
        while let Some(p) = pos {
            text.splice(p..p + from.len(), to.iter().copied());
            let next = p + to.len();
            pos = if next <= text.len() { crate::bytes::find(&text[next..], from).map(|q| q + next) } else { None };
        }
    }

    let tokens: Vec<&[u8]> = text.split(|&b| !c_alnum(b)).filter(|t| !t.is_empty()).collect();
    let set = |s: &mut BTreeSet<Vec<u8>>, v: &[u8]| {
        s.insert(v.to_vec());
    };
    const NETWORKS: [&[u8]; 22] = [b"amzn", b"nf", b"max", b"atvp", b"dsnp", b"hulu", b"pcok", b"pmtp", b"cr", b"stan",
        b"itv", b"bbc", b"red", b"sho", b"hbo", b"pmnt", b"ctv", b"crav", b"nbc", b"abc", b"cbs", b"ifc"];
    const EDITIONS: [&[u8]; 9] = [b"extended", b"unrated", b"uncut", b"remastered", b"theatrical", b"imax",
                                  b"criterion", b"hybrid", b"dc"];

    let mut title_done = false;
    let mut title: Vec<u8> = Vec::new();
    let mut last_audio: i64 = -100;
    let mut i = 0;
    while i < tokens.len() {
        let tok = tokens[i];
        let next: &[u8] = tokens.get(i + 1).copied().unwrap_or(b"");
        let mut marker = true;
        if let Some((season, episodes)) = season_episode(tok).filter(|_| tok.len() > 1) {
            attrs.seasons.push(atoi(season));
            attrs.episodes.extend(episodes.iter().map(|e| atoi(e)));
        } else if let Some((s, e)) = alt_episode(tok) {
            attrs.seasons.push(atoi(s));
            attrs.episodes.push(atoi(e));
        } else if is_year_token(tok) && title.is_empty() && !title_done {
            marker = false; // a title can start with a year-like number
        } else if is_year_token(tok) {
            if attrs.year == 0 {
                attrs.year = atoi(tok);
            } else {
                marker = false;
            }
        } else if is_resolution_token(tok) {
            match tok {
                b"4k" | b"uhd" => set(&mut attrs.resolution, b"2160p"),
                b"fhd" => set(&mut attrs.resolution, b"1080p"),
                _ => set(&mut attrs.resolution, tok),
            }
        } else if tok == b"webdl" {
            set(&mut attrs.quality, b"web");
            set(&mut attrs.quality, b"dl");
        } else if tok == b"web" || tok == b"webhd" {
            set(&mut attrs.quality, b"web");
        } else if tok == b"webrip" {
            set(&mut attrs.quality, b"webrip");
        } else if tok == b"bluray" || tok == b"bd" {
            set(&mut attrs.quality, b"bluray");
        } else if tok == b"bdrip" || tok == b"brrip" {
            set(&mut attrs.quality, b"bdrip");
        } else if matches!(tok, b"remux" | b"hdtv" | b"dvdrip" | b"hdrip" | b"hdlight") {
            set(&mut attrs.quality, tok);
        } else if matches!(tok, b"x265" | b"h265" | b"hevc") {
            set(&mut attrs.codec, b"hevc");
        } else if matches!(tok, b"x264" | b"h264" | b"avc") {
            set(&mut attrs.codec, b"avc");
        } else if (tok == b"h" || tok == b"x") && (next == b"265" || next == b"264") {
            set(&mut attrs.codec, if next == b"265" { b"hevc" } else { b"avc" });
            i += 1;
        } else if matches!(tok, b"av1" | b"xvid" | b"vc1" | b"mpeg2") {
            set(&mut attrs.codec, tok);
        } else if let Some(bits) = bit_depth(tok) {
            attrs.bit_depth.insert(bits);
        } else if let Some((kind, digit)) = audio(tok) {
            match kind {
                b"ddpa" => {
                    set(&mut attrs.audio, b"ddp");
                    set(&mut attrs.audio, b"atmos");
                }
                b"ddp" | b"eac3" => set(&mut attrs.audio, b"ddp"),
                b"dd" | b"ac3" => set(&mut attrs.audio, b"dd"),
                b"dtshd" => {
                    set(&mut attrs.audio, b"dts");
                    set(&mut attrs.audio, b"hd");
                }
                _ => set(&mut attrs.audio, kind),
            }
            last_audio = i as i64;
            if !digit.is_empty() && (next == b"1" || next == b"0") {
                attrs.channels.insert([digit, b".", next].concat());
                i += 1;
            }
        } else if tok == b"atmos" {
            set(&mut attrs.audio, b"atmos");
            last_audio = i as i64;
        } else if tok == b"ma" && i as i64 - last_audio <= 2 {
            set(&mut attrs.audio, b"ma");
            last_audio = i as i64;
        } else if tok == b"hd" && i as i64 - last_audio <= 1 {
            set(&mut attrs.audio, b"hd");
            last_audio = i as i64;
        } else if matches!(tok, b"5" | b"7" | b"2" | b"6" | b"1") && (next == b"1" || next == b"0") && i as i64 - last_audio <= 3 {
            attrs.channels.insert([tok, b".", next].concat());
            i += 1;
        } else if tok.len() == 3 && tok[1] == b'c' && tok[2] == b'h' && c_digit(tok[0]) {
            set(&mut attrs.channels, tok);
        } else if tok == b"dv" || tok == b"dovi" {
            set(&mut attrs.hdr, b"dv");
        } else if tok == b"hdr" || tok == b"hdr10" {
            set(&mut attrs.hdr, b"hdr");
        } else if tok == b"hdr10plus" || tok == b"hdr10p" {
            set(&mut attrs.hdr, b"hdr10+");
        } else if tok == b"hlg" {
            set(&mut attrs.hdr, b"hlg");
        } else if tok == b"sdr" {
            // a name without an HDR tag is SDR
        } else if word_digit(tok, &[b"repack", b"rerip"]) {
            attrs.repack = true;
        } else if word_digit(tok, &[b"proper"]) {
            attrs.proper = true;
        } else if tok == b"netflix" {
            set(&mut attrs.network, b"nf");
        } else if tok == b"amazon" {
            set(&mut attrs.network, b"amzn");
        } else if tok == b"hmax" {
            set(&mut attrs.network, b"max");
        } else if NETWORKS.contains(&tok) && title_done {
            set(&mut attrs.network, tok);
        } else if EDITIONS.contains(&tok) && title_done {
            set(&mut attrs.edition, tok);
        } else {
            marker = false;
        }
        if marker {
            title_done = true;
        } else if !title_done {
            title.extend_from_slice(tok);
        }
        i += 1;
    }
    attrs.seasons.sort();
    attrs.episodes.sort();
    attrs.title = title;
    attrs
}

/// `^(\d{1,2})x(\d{2,3})$`
fn alt_episode(tok: &[u8]) -> Option<(&[u8], &[u8])> {
    let x = tok.iter().position(|&b| b == b'x')?;
    let (s, e) = (&tok[..x], &tok[x + 1..]);
    ((1..=2).contains(&s.len()) && s.iter().all(|&b| ascii_digit(b)) && (2..=3).contains(&e.len())
        && e.iter().all(|&b| ascii_digit(b)))
    .then_some((s, e))
}

/// `^(\d{1,2})bit$|^hi10p?$`: the bit depth it names.
fn bit_depth(tok: &[u8]) -> Option<Vec<u8>> {
    if let Some(d) = tok.strip_suffix(b"bit") {
        if (1..=2).contains(&d.len()) && d.iter().all(|&b| ascii_digit(b)) {
            return Some(tok.to_vec());
        }
    }
    (tok == b"hi10" || tok == b"hi10p").then(|| b"10bit".to_vec())
}

/// `^(w1|w2)\d?$`
fn word_digit(tok: &[u8], words: &[&[u8]]) -> bool {
    words.iter().any(|w| {
        tok.strip_prefix(*w).is_some_and(|rest| rest.is_empty() || rest.len() == 1 && ascii_digit(rest[0]))
    })
}

/// ReleaseName::Readable: does the name carry release information?
pub fn readable(name: &[u8]) -> bool {
    let a = parse(name);
    !a.title.is_empty() && (!a.group.is_empty() || !a.resolution.is_empty())
}

fn compatible(a: &BTreeSet<Vec<u8>>, b: &BTreeSet<Vec<u8>>) -> bool {
    a.is_empty() || b.is_empty() || a.is_subset(b) || b.is_subset(a)
}

/// ReleaseName::SameRelease.
pub fn same_release(a_name: &[u8], b_name: &[u8]) -> bool {
    let a = parse(a_name);
    let b = parse(b_name);
    if a.group.is_empty() {
        return normalize(a_name) == normalize(b_name); // nothing to anchor on
    }
    if a.title != b.title || a.group != b.group || a.seasons != b.seasons || a.episodes != b.episodes
        || a.repack != b.repack || a.proper != b.proper || a.hdr != b.hdr
    {
        return false;
    }
    if a.year != 0 && b.year != 0 && a.year != b.year {
        return false;
    }
    compatible(&a.resolution, &b.resolution) && compatible(&a.quality, &b.quality) && compatible(&a.codec, &b.codec)
        && compatible(&a.bit_depth, &b.bit_depth) && compatible(&a.audio, &b.audio)
        && compatible(&a.channels, &b.channels) && compatible(&a.network, &b.network)
        && compatible(&a.edition, &b.edition)
}

/// Parse's attributes as bytes for the C ABI: each set as a u32 count and its
/// strings, each string as a u32 length and its bytes (LE), in Attrs order; then
/// title, group, the seasons and episodes (u32 count, i32 each), year, repack, proper.
pub fn encode(a: &Attrs) -> Vec<u8> {
    let mut out = Vec::new();
    let n = |out: &mut Vec<u8>, v: usize| out.extend_from_slice(&(v as u32).to_le_bytes());
    let string = |out: &mut Vec<u8>, s: &[u8]| {
        out.extend_from_slice(&(s.len() as u32).to_le_bytes());
        out.extend_from_slice(s);
    };
    for set in [&a.resolution, &a.quality, &a.codec, &a.bit_depth, &a.audio, &a.channels, &a.network, &a.edition, &a.hdr] {
        n(&mut out, set.len());
        for v in set {
            string(&mut out, v);
        }
    }
    string(&mut out, &a.title);
    string(&mut out, &a.group);
    for list in [&a.seasons, &a.episodes] {
        n(&mut out, list.len());
        for v in list {
            out.extend_from_slice(&v.to_le_bytes());
        }
    }
    out.extend_from_slice(&a.year.to_le_bytes());
    out.push(a.repack as u8);
    out.push(a.proper as u8);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cleans_extensions_tags_and_junk() {
        assert_eq!(clean(b"[01/17] \"Show.S01E02.1080p.WEB-GRP.part01.rar\" yEnc"), b"\"Show.S01E02.1080p.WEB-GRP.part01.rar\" yEnc".to_vec());
        assert_eq!(clean(b"Show.S01E02.1080p.WEB-GRP.mkv"), b"Show.S01E02.1080p.WEB-GRP".to_vec());
        assert_eq!(clean(b"Show.S01E02.H.265-GRP-xpost"), b"Show.S01E02.H.265-GRP".to_vec());
        assert_eq!(clean(b"Show.S01E02-GRP.7z.001"), b"Show.S01E02-GRP".to_vec());
        assert_eq!(clean(b"Show-GRP-rakuvFIN_sample"), b"Show-GRP".to_vec());
    }

    #[test]
    fn parses_attributes() {
        let a = parse(b"Show.S01E02.Title.2160p.WEB-DL.DDP5.1.Atmos.DV.H.265-GRP");
        assert_eq!(a.title, b"show".to_vec());
        assert_eq!(a.group, b"grp".to_vec());
        assert_eq!((a.seasons, a.episodes), (vec![1], vec![2]));
        assert!(a.hdr.contains(b"dv".as_slice()) && a.codec.contains(b"hevc".as_slice()));
        assert!(a.channels.contains(b"5.1".as_slice()) && a.audio.contains(b"atmos".as_slice()));
    }

    #[test]
    fn expands_episode_ranges() {
        assert_eq!(parse(b"Show.S01E01-E03.1080p-GRP").episodes, vec![1, 2, 3]);
        assert_eq!(parse(b"Show.S01E01-2023.1080p-GRP").episodes, vec![1]);
    }

    #[test]
    fn short_query_and_same_release() {
        assert_eq!(short_query(b"Lucifer.S02E14.Candy.Morningstar.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeST"), b"lucifer s02e14 1080p".to_vec());
        assert!(same_release(b"Show.S01E02.1080p.WEB.H264-GRP", b"Show S01E02 1080p WEB-DL x264-GRP"));
        assert!(!same_release(b"Show.S01E02.1080p.WEB.H264-GRP", b"Show.S01E02.1080p.WEB.H264-OTHER"));
    }
}
