//! FeedFilter: the RSS feed filter language (rules separated by '%', each an
//! optional command such as "A(options):" or "R:", then terms joined by
//! spaces, braces and '|'). It matches the C++ FeedFilter, quirks included.
//!
//! The feed item stays in C++: the matcher reads its fields, applies a rule's
//! options and sets the match result through `Item`, in the same order as the
//! C++ code (an Options rule changes fields later rules read). Names compare
//! as the C library's strcasecmp/strncasecmp and numbers parse as its
//! atof/atoi, in the current locale; regular expressions use the C++ RegEx.

use std::ffi::{c_char, c_int, CStr, CString};

use crate::wildmask::{wild_match, Lower};

extern "C" {
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
    fn atof(s: *const c_char) -> f64;
    fn atoi(s: *const c_char) -> c_int;
}

/// A C string of `b` (texts here have no NUL: they come from C strings).
fn c(b: &[u8]) -> CString {
    CString::new(b).unwrap_or_default()
}

fn case_eq(a: &[u8], lit: &str) -> bool {
    unsafe { strcasecmp(c(a).as_ptr(), c(lit.as_bytes()).as_ptr()) == 0 }
}

fn case_prefix(a: &[u8], lit: &str) -> bool {
    unsafe { strncasecmp(c(a).as_ptr(), c(lit.as_bytes()).as_ptr(), lit.len()) == 0 }
}

fn c_atof(b: &[u8]) -> f64 {
    unsafe { atof(c(b).as_ptr()) }
}

fn c_atoi(b: &[u8]) -> i32 {
    unsafe { atoi(c(b).as_ptr()) }
}

/// The C cast (int64)double: x86 gives INT64_MIN out of range (and for NaN);
/// elsewhere (as Rust) the conversion saturates.
fn to_i64(f: f64) -> i64 {
    if cfg!(any(target_arch = "x86_64", target_arch = "x86")) && !(f > i64::MIN as f64 && f < -(i64::MIN as f64)) {
        i64::MIN
    } else {
        f as i64
    }
}

/// Util::Trim of a C string: spaces, tabs, CR and LF off both ends.
fn trim(b: &[u8]) -> &[u8] {
    let ws = |c: &u8| matches!(c, b'\n' | b'\r' | b' ' | b'\t');
    let start = b.iter().position(|c| !ws(c)).unwrap_or(b.len());
    let end = b.iter().rposition(|c| !ws(c)).map_or(start, |e| e + 1);
    &b[start..end.max(start)]
}

/// A feed item field, resolved using the current C locale.
#[derive(Clone, Copy, PartialEq, Debug)]
#[repr(C)]
pub enum Field {
    Title = 0,
    Filename,
    Category,
    Url,
    Size,
    Age,
    ImdbId,
    RageId,
    TvdbId,
    TvmazeId,
    Description,
    Season,
    Episode,
    Priority,
    DupeKey,
    DupeScore,
    DupeStatus,
    /// "attr-<name>": the attribute named by the rest
    Attr,
}

/// GetFieldData's names; None for an unknown one.
fn field_of(name: Option<&[u8]>) -> Option<Field> {
    let Some(n) = name else { return Some(Field::Title) };
    let table: &[(&str, Field)] = &[
        ("title", Field::Title),
        ("filename", Field::Filename),
        ("category", Field::Category),
        ("link", Field::Url),
        ("url", Field::Url),
        ("size", Field::Size),
        ("age", Field::Age),
        ("imdbid", Field::ImdbId),
        ("rageid", Field::RageId),
        ("tvdbid", Field::TvdbId),
        ("tvmazeid", Field::TvmazeId),
        ("description", Field::Description),
        ("season", Field::Season),
        ("episode", Field::Episode),
        ("priority", Field::Priority),
        ("dupekey", Field::DupeKey),
        ("dupescore", Field::DupeScore),
        ("dupestatus", Field::DupeStatus),
    ];
    if let Some(&(_, f)) = table.iter().find(|(lit, _)| case_eq(n, lit)) {
        return Some(f);
    }
    case_prefix(n, "attr-").then_some(Field::Attr)
}

/// Pause, dupe mode: as the C++ enums.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum DupeMode {
    Score = 0,
    All = 1,
    Force = 2,
}

/// What the matcher needs of the C++ side.
pub trait Item {
    /// A field's text (None: a null C string) or number.
    fn field(&mut self, field: Field, attr: &[u8]) -> (Option<Vec<u8>>, i64);
    /// The item's season or episode text (GetSeason/GetEpisode after the
    /// title is parsed).
    fn season_episode(&mut self, episode: bool) -> Option<Vec<u8>>;
    /// RegEx(pattern, buffer size) for a term: a handle.
    fn regex_new(&mut self, pattern: &[u8], buf_size: i32) -> usize;
    /// RegEx::Match, and when matched GetMatchCount/Start/Len.
    fn regex_match(&mut self, handle: usize, text: &[u8]) -> Option<Vec<(i32, i32)>>;
    /// FeedItemInfo's setters, as ApplyOptions calls them.
    fn apply(&mut self, options: &Applied<'_>);
    /// SetMatchStatus/SetMatchRule: 0 ignored, 1 accepted, 2 rejected.
    fn set_match(&mut self, status: i32, rule: i32);
    /// Case folding for the WildMask matches.
    fn lower(&self) -> &Lower<'_>;
}

/// A matched rule's options, for ApplyOptions (C strings may be null).
#[derive(Default, Debug)]
pub struct Applied<'a> {
    pub pause: Option<bool>,
    pub category: Option<Option<&'a [u8]>>,
    pub priority: Option<i32>,
    pub add_priority: Option<i32>,
    pub dupe_score: Option<i32>,
    pub add_dupe_score: Option<i32>,
    /// rageid, tvdbid, tvmazeid, series (BuildDupeKey), when any is set
    pub build_dupe_key: Option<[Option<&'a [u8]>; 4]>,
    pub dupe_key: Option<Option<&'a [u8]>>,
    pub add_dupe_key: Option<Option<&'a [u8]>>,
    pub dupe_mode: Option<DupeMode>,
}

#[derive(Clone, Copy, PartialEq, PartialOrd, Debug)]
enum Cmd {
    Text,
    Regex,
    Equal,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    OpeningBrace,
    ClosingBrace,
    Or,
}

struct Term {
    positive: bool,
    field_name: Option<Vec<u8>>,
    cmd: Cmd,
    param: Vec<u8>,
    int_param: i64,
    float_param: f64,
    is_float: bool,
    /// the rule wants reference values (${1}...)
    refs: bool,
    regex: Option<usize>,
}

const WORD_SEPARATORS: &[u8] = b" !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";

/// CString(str, len): a length of 0 or less takes the rest of the text.
fn ref_value(s: &[u8], start: i32, len: i32) -> Vec<u8> {
    let start = (start.max(0) as usize).min(s.len());
    if len <= 0 {
        s[start..].to_vec()
    } else {
        s[start..(start + len as usize).min(s.len())].to_vec()
    }
}

impl Term {
    fn compile(token: &[u8], refs: bool) -> Option<Term> {
        let mut t = Term {
            positive: token.first() != Some(&b'-'),
            field_name: None,
            cmd: Cmd::Equal,
            param: Vec::new(),
            int_param: 0,
            float_param: 0.0,
            is_float: false,
            refs,
            regex: None,
        };
        let mut sv = token;
        if matches!(sv.first(), Some(b'-' | b'+')) {
            sv = &sv[1..];
        }
        let &ch0 = sv.first()?;
        if matches!(ch0, b'(' | b')' | b'|') && (sv.len() < 2 || sv[1] == b' ') {
            t.cmd = match ch0 {
                b'(' => Cmd::OpeningBrace,
                b')' => Cmd::ClosingBrace,
                _ => Cmd::Or,
            };
            return Some(t);
        }
        t.cmd = Cmd::Text;
        let mut ch = ch0;
        let mut field_name: Option<&[u8]> = None;
        if !matches!(ch, b'@' | b'$' | b'<' | b'>' | b'=') {
            if let Some(pos) = sv.iter().position(|&b| b == b':') {
                // CString::Set(text, 0) takes the whole text: a name that
                // starts with ':', which no field has
                if pos == 0 {
                    return None;
                }
                field_name = Some(&sv[..pos]);
                sv = &sv[pos + 1..];
                ch = *sv.first()?;
            }
        }
        let two = |sv: &[u8], c: u8| sv.len() > 1 && sv[1] == c;
        let (cmd, skip) = match ch {
            b'@' => (Cmd::Text, 1),
            b'$' => (Cmd::Regex, 1),
            b'=' => (Cmd::Equal, 1),
            b'<' if two(sv, b'=') => (Cmd::LessEqual, 2),
            b'>' if two(sv, b'=') => (Cmd::GreaterEqual, 2),
            b'<' => (Cmd::Less, 1),
            b'>' => (Cmd::Greater, 1),
            _ => (Cmd::Text, 0),
        };
        t.cmd = cmd;
        sv = &sv[skip..];

        field_of(field_name)?;
        t.field_name = field_name.map(<[u8]>::to_vec);
        if let Some(f) = field_name {
            if !t.parse_param(f, sv) {
                return None;
            }
        }
        t.param = sv.to_vec();
        Some(t)
    }

    fn parse_param(&mut self, field: &[u8], param: &[u8]) -> bool {
        if case_eq(field, "size") {
            self.parse_unit(param, &[("K", 1024.0), ("KB", 1024.0), ("M", 1048576.0), ("MB", 1048576.0), ("G", 1073741824.0), ("GB", 1073741824.0)], 1.0)
        } else if case_eq(field, "age") {
            self.parse_unit(param, &[("m", 60.0), ("h", 3600.0), ("d", 86400.0)], 86400.0)
        } else if self.cmd >= Cmd::Equal {
            self.float_param = c_atof(param);
            self.int_param = to_i64(self.float_param);
            self.is_float = param.contains(&b'.');
            param.iter().all(|&b| b.is_ascii_digit() || b == b'.' || b == b'-')
        } else {
            true
        }
    }

    /// ParseSizeParam/ParseAgeParam: a number, then a unit (or the default).
    fn parse_unit(&mut self, param: &[u8], units: &[(&str, f64)], default: f64) -> bool {
        let f = c_atof(param);
        let rest = &param[param.iter().position(|&b| !(b.is_ascii_digit() || b == b'.')).unwrap_or(param.len())..];
        if rest.is_empty() {
            // the C++ multiplied by the factors one after another
            self.int_param = to_i64(if default == 86400.0 { f * 60.0 * 60.0 * 24.0 } else { f });
            return true;
        }
        match units.iter().find(|(u, _)| case_eq(rest, u)) {
            Some(&(u, _)) => {
                self.int_param = to_i64(match u {
                    "K" | "KB" => f * 1024.0,
                    "M" | "MB" => f * 1024.0 * 1024.0,
                    "G" | "GB" => f * 1024.0 * 1024.0 * 1024.0,
                    "m" => f * 60.0,
                    "h" => f * 60.0 * 60.0,
                    _ => f * 60.0 * 60.0 * 24.0,
                });
                true
            }
            None => false,
        }
    }

    fn matches(&mut self, item: &mut dyn Item, refs: &mut Vec<Vec<u8>>) -> bool {
        // GetFieldData resolves the name again at match time. A filter may
        // be matched under a different thread locale than it was compiled
        // in (notably, Turkish changes how uppercase I compares).
        let Some(field) = field_of(self.field_name.as_deref()) else { return false };
        let attr = if field == Field::Attr {
            &self.field_name.as_deref().unwrap_or_default()[5..]
        } else {
            &[]
        };
        let (s, i) = item.field(field, attr);
        let m = self.match_value(item, s, i, refs);
        self.positive == m
    }

    fn match_value(&mut self, item: &mut dyn Item, s: Option<Vec<u8>>, mut int_value: i64, refs: &mut Vec<Vec<u8>>) -> bool {
        let mut float_value = int_value as f64;
        let mut s = s;
        if self.cmd < Cmd::Equal && s.is_none() {
            s = Some(int_value.to_string().into_bytes());
        } else if self.cmd >= Cmd::Equal {
            if let Some(v) = &s {
                float_value = c_atof(v);
                int_value = to_i64(float_value);
            }
        }
        let (fl, fp, ip) = (self.is_float, self.float_param, self.int_param);
        match self.cmd {
            Cmd::Text => self.match_text(item, s.as_deref().unwrap_or_default(), refs),
            Cmd::Regex => self.match_regex(item, s.as_deref().unwrap_or_default(), refs),
            Cmd::Equal => if fl { float_value == fp } else { int_value == ip },
            Cmd::Less => if fl { float_value < fp } else { int_value < ip },
            Cmd::LessEqual => if fl { float_value <= fp } else { int_value <= ip },
            Cmd::Greater => if fl { float_value > fp } else { int_value > ip },
            Cmd::GreaterEqual => if fl { float_value >= fp } else { int_value >= ip },
            _ => false,
        }
    }

    fn match_text(&mut self, item: &mut dyn Item, value: &[u8], refs: &mut Vec<Vec<u8>>) -> bool {
        let p = &self.param;
        let n = p.len();
        let both = n >= 2 && p[0] == b'*' && p[n - 1] == b'*';
        let substr = both || p.iter().any(|&ch| WORD_SEPARATORS.contains(&ch) && ch != b'*' && ch != b'?' && ch != b'#');
        let want = self.refs;
        let mut positions = Vec::new();
        if !substr {
            // word search: each word of the value
            for word in crate::util::tokens(value, WORD_SEPARATORS) {
                if wild_match(item.lower(), p, word, want.then_some(&mut positions)) {
                    if want {
                        refs.extend(positions.iter().map(|&(s, l)| ref_value(word, s, l)));
                    }
                    return true;
                }
            }
            false
        } else {
            // substring search
            let (pattern, ref_offset) = if both {
                (p.clone(), 0)
            } else if n >= 1 && p[0] == b'*' {
                ([&p[..], b"*"].concat(), 0)
            } else if n >= 1 && p[n - 1] == b'*' {
                ([b"*", &p[..]].concat(), 1)
            } else {
                ([b"*", &p[..], b"*"].concat(), 1)
            };
            let m = wild_match(item.lower(), &pattern, value, want.then_some(&mut positions));
            if m && want {
                refs.extend(positions.iter().skip(ref_offset).map(|&(s, l)| ref_value(value, s, l)));
            }
            m
        }
    }

    fn match_regex(&mut self, item: &mut dyn Item, value: &[u8], refs: &mut Vec<Vec<u8>>) -> bool {
        let handle = *self.regex.get_or_insert_with(|| item.regex_new(&self.param, if self.refs { 100 } else { 0 }));
        match item.regex_match(handle, value) {
            Some(groups) => {
                if self.refs {
                    refs.extend(groups.iter().skip(1).map(|&(s, l)| ref_value(value, s, l)));
                }
                true
            }
            None => false,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum RuleCmd {
    Accept,
    Reject,
    Require,
    Options,
    Comment,
}

#[derive(Default)]
struct Options {
    category: Option<Option<Vec<u8>>>,
    pause: Option<bool>,
    priority: Option<i32>,
    add_priority: Option<i32>,
    dupe_score: Option<i32>,
    add_dupe_score: Option<i32>,
    dupe_key: Option<Option<Vec<u8>>>,
    add_dupe_key: Option<Option<Vec<u8>>>,
    dupe_mode: Option<DupeMode>,
    rage_id: Option<Vec<u8>>,
    tvdb_id: Option<Vec<u8>>,
    tvmaze_id: Option<Vec<u8>>,
    series: Option<Vec<u8>>,
    /// patterns with ${...}, expanded at each match
    pat_category: Option<Vec<u8>>,
    pat_dupe_key: Option<Vec<u8>>,
    pat_add_dupe_key: Option<Vec<u8>>,
}

struct Rule {
    valid: bool,
    cmd: RuleCmd,
    opts: Options,
    has_pat: [bool; 3],
    terms: Vec<Term>,
}

impl Rule {
    fn compile(text: &[u8]) -> Rule {
        let mut rule = Rule { valid: true, cmd: RuleCmd::Accept, opts: Options::default(), has_pat: [false; 3], terms: Vec::new() };
        let text = trim(text);
        let Some(terms) = rule.compile_command(text) else {
            rule.valid = false;
            return rule;
        };
        if rule.cmd == RuleCmd::Comment {
            return rule;
        }
        let terms = trim(terms);
        let refs = rule.has_pat.iter().any(|&p| p);
        // terms separated by spaces; the last one may be empty (invalid)
        let mut parts = terms.split(|&b| b == b' ').filter(|t| !t.is_empty()).peekable();
        if terms.is_empty() {
            rule.valid = false;
        }
        while rule.valid {
            let Some(t) = parts.next() else { break };
            match Term::compile(t, refs) {
                Some(term) => rule.terms.push(term),
                None => rule.valid = false,
            }
        }
        if rule.valid {
            let o = &mut rule.opts;
            if rule.has_pat[0] {
                o.pat_category = o.category.take().flatten();
                o.category = Some(None);
            }
            if rule.has_pat[1] {
                o.pat_dupe_key = o.dupe_key.take().flatten();
                o.dupe_key = Some(None);
            }
            if rule.has_pat[2] {
                o.pat_add_dupe_key = o.add_dupe_key.take().flatten();
                o.add_dupe_key = Some(None);
            }
        }
        rule
    }

    /// The command; returns the text of the terms, or None for an error.
    fn compile_command<'t>(&mut self, rule: &'t [u8]) -> Option<&'t [u8]> {
        let commands: &[(&[&str], RuleCmd, usize)] = &[
            (&["A:", "Accept:", "A(", "Accept("], RuleCmd::Accept, 7),
            (&["O(", "Options("], RuleCmd::Options, 8),
            (&["R:", "Reject:"], RuleCmd::Reject, 7),
            (&["Q:", "Require:"], RuleCmd::Require, 8),
        ];
        let mut rest = rule;
        let mut found = false;
        for (prefixes, cmd, long) in commands {
            if prefixes.iter().any(|p| case_prefix(rule, p)) {
                self.cmd = *cmd;
                let short = matches!(rule.get(1), Some(b':' | b'('));
                rest = &rule[if short { 2 } else { *long }..];
                found = true;
                break;
            }
        }
        if !found {
            if rule.first() == Some(&b'#') {
                self.cmd = RuleCmd::Comment;
            }
            return Some(rule);
        }
        let opened = rule.len() - rest.len();
        if matches!(self.cmd, RuleCmd::Accept | RuleCmd::Options) && rule[opened - 1] == b'(' {
            return self.compile_options(rest);
        }
        Some(rest)
    }

    fn compile_options<'t>(&mut self, rule: &'t [u8]) -> Option<&'t [u8]> {
        let close = rule.iter().position(|&b| b == b')')?;
        let numeric = |v: &[u8]| v.first().is_none_or(|c| b"0123456789-+".contains(c));
        for option in crate::util::tokens(&rule[..close], b",") {
            let (option, value): (&[u8], &[u8]) = match option.iter().position(|&b| b == b':') {
                Some(k) => (&option[..k], trim(&option[k + 1..])),
                None => (option, b""),
            };
            let is = |names: &[&str]| names.iter().any(|n| case_eq(option, n));
            let o = &mut self.opts;
            let has_pat = value.windows(2).any(|w| w == b"${");
            if is(&["category", "cat", "c"]) {
                o.category = Some(Some(value.to_vec()));
                self.has_pat[0] = has_pat;
            } else if is(&["pause", "p"]) {
                let pause = value.is_empty() || case_eq(value, "yes") || case_eq(value, "y");
                if !pause && !(case_eq(value, "no") || case_eq(value, "n")) {
                    return None;
                }
                o.pause = Some(pause);
            } else if is(&["priority", "pr", "r"]) {
                if !numeric(value) {
                    return None;
                }
                o.priority = Some(c_atoi(value));
            } else if is(&["priority+", "pr+", "r+"]) {
                if !numeric(value) {
                    return None;
                }
                o.add_priority = Some(c_atoi(value));
            } else if is(&["dupescore", "ds", "s"]) {
                if !numeric(value) {
                    return None;
                }
                o.dupe_score = Some(c_atoi(value));
            } else if is(&["dupescore+", "ds+", "s+"]) {
                if !numeric(value) {
                    return None;
                }
                o.add_dupe_score = Some(c_atoi(value));
            } else if is(&["dupekey", "dk", "k"]) {
                o.dupe_key = Some(Some(value.to_vec()));
                self.has_pat[1] = has_pat;
            } else if is(&["dupekey+", "dk+", "k+"]) {
                o.add_dupe_key = Some(Some(value.to_vec()));
                self.has_pat[2] = has_pat;
            } else if is(&["dupemode", "dm", "m"]) {
                o.dupe_mode = Some(if case_eq(value, "score") || case_eq(value, "s") {
                    DupeMode::Score
                } else if case_eq(value, "all") || case_eq(value, "a") {
                    DupeMode::All
                } else if case_eq(value, "force") || case_eq(value, "f") {
                    DupeMode::Force
                } else {
                    return None;
                });
            } else if is(&["rageid"]) {
                o.rage_id = Some(value.to_vec());
            } else if is(&["tvdbid"]) {
                o.tvdb_id = Some(value.to_vec());
            } else if is(&["tvmazeid"]) {
                o.tvmaze_id = Some(value.to_vec());
            } else if is(&["series"]) {
                o.series = Some(value.to_vec());
            } else if is(&["paused", "unpaused"]) {
                // older versions' options
                o.pause = Some(case_eq(option, "paused"));
            } else if option.first().is_none_or(|c| b"0123456789-+".contains(c)) {
                // strchr also finds the NUL of an empty option name
                o.priority = Some(c_atoi(option));
            } else {
                o.category = Some(Some(option.to_vec()));
            }
        }
        let mut rest = &rule[close + 1..];
        if rest.first() == Some(&b':') {
            rest = &rest[1..];
        }
        Some(rest)
    }

    fn matches(&mut self, item: &mut dyn Item) -> bool {
        let mut refs = Vec::new();
        let mut expr = Vec::with_capacity(self.terms.len());
        for term in &mut self.terms {
            expr.push(match term.cmd {
                Cmd::OpeningBrace => b'(',
                Cmd::ClosingBrace => b')',
                Cmd::Or => b'|',
                _ => if term.matches(item, &mut refs) { b'T' } else { b'F' },
            });
        }
        // reduce the result to one element (longer for a syntax error); no
        // operator priorities: braces group
        const STEPS: [(&[u8], &[u8]); 13] = [
            (b"TT", b"T"), (b"TF", b"F"), (b"FT", b"F"), (b"FF", b"F"), (b"||", b"|"), (b"(|", b"("), (b"|)", b")"),
            (b"T|T", b"T"), (b"T|F", b"T"), (b"F|T", b"T"), (b"F|F", b"F"), (b"(T)", b"T"), (b"(F)", b"F"),
        ];
        loop {
            let old = expr.len();
            for (from, to) in STEPS {
                reduce(&mut expr, from, to);
            }
            if expr.len() == old {
                break;
            }
        }
        if !(expr.len() == 1 && expr[0] == b'T') {
            return false;
        }
        let pats = [self.opts.pat_category.clone(), self.opts.pat_dupe_key.clone(), self.opts.pat_add_dupe_key.clone()];
        for (k, pat) in pats.iter().enumerate() {
            if self.has_pat[k] {
                let v = expand(item, pat.as_deref(), &refs);
                let slot = match k {
                    0 => &mut self.opts.category,
                    1 => &mut self.opts.dupe_key,
                    _ => &mut self.opts.add_dupe_key,
                };
                *slot = Some(v);
            }
        }
        true
    }
}

/// Util::ReduceStr for a NUL-free text: replace, then look again from just
/// before the replacement (same result as from the start).
fn reduce(s: &mut Vec<u8>, from: &[u8], to: &[u8]) {
    let mut at = 0;
    while let Some(k) = s.get(at..).and_then(|r| r.windows(from.len()).position(|w| w == from)) {
        let p = at + k;
        s.splice(p..p + from.len(), to.iter().copied());
        at = (p + 1).saturating_sub(from.len());
    }
}

/// Rule::ExpandRefValues: "${1}" (a reference value), "${season}",
/// "${episode}" replaced; stops at the first one it can't resolve, after
/// 100 replacements, or at a "${" without '}'.
fn expand(item: &mut dyn Item, pat: Option<&[u8]>, refs: &[Vec<u8>]) -> Option<Vec<u8>> {
    let mut cur = pat?.to_vec();
    let mut attempts = 0;
    while let Some(dollar) = cur.windows(2).position(|w| w == b"${") {
        attempts += 1;
        if attempts > 100 {
            break;
        }
        let Some(end) = cur[dollar..].iter().position(|&b| b == b'}').map(|k| dollar + k) else { break };
        let varlen = end as isize - dollar as isize - 2;
        // BString<100>::Set(dollar + 2, varlen)
        let after = &cur[dollar + 2..];
        let take = if varlen > 0 { (varlen as usize).min(99) } else { 99 };
        let var = after[..take.min(after.len())].to_vec();
        let value = if case_eq(&var, "season") {
            item.season_episode(false)
        } else if case_eq(&var, "episode") {
            item.season_episode(true)
        } else {
            let index = c_atoi(&var) as i64 - 1;
            (index >= 0 && (index as usize) < refs.len()).then(|| refs[index as usize].clone())
        };
        let Some(value) = value else { break };
        // CString::Replace(dollar, 2 + varlen + 1, value)
        let del = (2 + varlen + 1).max(0) as usize;
        let del_end = (dollar + del).min(cur.len());
        let value_c = value.iter().position(|&b| b == 0).map_or(&value[..], |n| &value[..n]).to_vec();
        cur.splice(dollar..del_end, value_c);
    }
    Some(cur)
}

/// A compiled filter.
pub struct FeedFilter {
    rules: Vec<Rule>,
}

impl FeedFilter {
    pub fn new(filter: &[u8]) -> FeedFilter {
        FeedFilter { rules: filter.split(|&b| b == b'%').map(Rule::compile).collect() }
    }

    /// FeedFilter::Match.
    pub fn matches(&mut self, item: &mut dyn Item) {
        for (n, rule) in self.rules.iter_mut().enumerate() {
            let index = n as i32 + 1;
            if !rule.valid {
                continue;
            }
            let m = rule.matches(item);
            match rule.cmd {
                RuleCmd::Accept | RuleCmd::Options => {
                    if m {
                        item.set_match(1, index);
                        let o = &rule.opts;
                        let ids = [&o.rage_id, &o.tvdb_id, &o.tvmaze_id, &o.series];
                        let applied = Applied {
                            pause: o.pause,
                            category: o.category.as_ref().map(|c| c.as_deref()),
                            priority: o.priority,
                            add_priority: o.add_priority,
                            dupe_score: o.dupe_score,
                            add_dupe_score: o.add_dupe_score,
                            build_dupe_key: ids.iter().any(|i| i.is_some()).then(|| ids.map(|i| i.as_deref())),
                            dupe_key: o.dupe_key.as_ref().map(|c| c.as_deref()),
                            add_dupe_key: o.add_dupe_key.as_ref().map(|c| c.as_deref()),
                            dupe_mode: o.dupe_mode,
                        };
                        item.apply(&applied);
                        if rule.cmd == RuleCmd::Accept {
                            return;
                        }
                    }
                }
                RuleCmd::Reject => {
                    if m {
                        item.set_match(2, index);
                        return;
                    }
                }
                RuleCmd::Require => {
                    if !m {
                        item.set_match(2, index);
                        return;
                    }
                }
                RuleCmd::Comment => {}
            }
        }
        item.set_match(0, 0);
    }
}

/// For the C side: the field of a text (a C string) of a term, unused here.
#[doc(hidden)]
pub fn field_name_known(name: &CStr) -> bool {
    field_of(Some(name.to_bytes())).is_some()
}
