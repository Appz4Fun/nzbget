//! ExtensionLoader::V1 (ExtensionLoader.cpp): the header of a pre-manifest
//! extension script - its kind, about text, queue events, task time,
//! description, requirements, and the options and commands of its OPTIONS
//! section with their select values - parsed as the C++ did: lines as
//! std::getline splits them, prefix and substring tests that stop at a NUL
//! where the C++ used strncmp/strstr, std::string positions elsewhere, the
//! locale's isspace for trims and strtod for numbers.

use std::ffi::{c_char, c_int, CString};

extern "C" {
    fn isspace(c: c_int) -> c_int;
    fn strtod(s: *const c_char, end: *mut *mut c_char) -> f64;
}

/// A select value or an option value: ManifestFile::SelectOption.
#[derive(Clone, Debug, PartialEq)]
pub enum Select {
    Num(f64),
    Str(Vec<u8>),
}

/// ManifestFile::Section
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Section {
    pub multi: bool,
    pub name: Vec<u8>,
    pub prefix: Vec<u8>,
}

/// An option (`#Name=value`) or a command (`#Name@action`); display names
/// are the names.
#[derive(Clone, Debug, PartialEq)]
pub struct Item {
    pub section: Section,
    pub name: Vec<u8>,
    pub description: Vec<Vec<u8>>,
    /// commands: the action
    pub action: Vec<u8>,
    /// options: the value and the select values
    pub value: Select,
    pub select: Vec<Select>,
}

/// What V1::Load reads from a script.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Script {
    /// bits: 1 post-processing, 2 scan, 4 queue, 8 scheduler, 16 feed
    pub kind: i32,
    /// untrimmed: V1::Load trims its end
    pub about: Vec<u8>,
    pub queue_events: Vec<u8>,
    pub task_time: Vec<u8>,
    pub description: Vec<Vec<u8>>,
    pub requirements: Vec<Vec<u8>>,
    pub options: Vec<Item>,
    pub commands: Vec<Item>,
}

/// The C string of a line: up to its first NUL.
fn c(line: &[u8]) -> &[u8] {
    &line[..line.iter().position(|&b| b == 0).unwrap_or(line.len())]
}

/// strstr(line.c_str(), needle)
fn contains(line: &[u8], needle: &[u8]) -> bool {
    c(line).windows(needle.len()).any(|w| w == needle)
}

/// std::string::find / rfind
fn find(s: &[u8], needle: &[u8]) -> Option<usize> {
    s.windows(needle.len()).position(|w| w == needle)
}

fn rfind(s: &[u8], b: u8) -> Option<usize> {
    s.iter().rposition(|&x| x == b)
}

/// std::string::substr(pos, count): the count clipped at the end.
fn substr(s: &[u8], pos: usize, count: usize) -> Vec<u8> {
    s[pos..pos + count.min(s.len() - pos)].to_vec()
}

fn space_left(b: u8) -> bool {
    unsafe { isspace(b as c_int) != 0 }
}

/// std::isspace of the C++ char (signed or not) as Util::TrimRight tests it.
fn space_right(b: u8) -> bool {
    let ch = b as c_char as c_int;
    if cfg!(target_env = "gnu") || ch >= 0 {
        unsafe { isspace(ch) != 0 }
    } else {
        false
    }
}

fn trim_right(s: &mut Vec<u8>) {
    while s.last().is_some_and(|&b| space_right(b)) {
        s.pop();
    }
}

fn trim(s: &mut Vec<u8>) {
    let start = s.iter().take_while(|&&b| space_left(b)).count();
    s.drain(..start);
    trim_right(s);
}

/// TextAfter: the text from `pos`, or nothing.
fn text_after(line: &[u8], pos: usize) -> Vec<u8> {
    if line.len() > pos { line[pos..].to_vec() } else { Vec::new() }
}

/// RemoveTailAndTrim
fn remove_tail_and_trim(s: &mut Vec<u8>, tail: &[u8]) {
    if let Some(i) = find(s, tail) {
        s.truncate(i);
    }
    trim_right(s);
}

/// ExtensionLoader::GetScriptKind
pub fn script_kind(line: &[u8]) -> i32 {
    [&b"POST-PROCESSING"[..], b"SCAN", b"QUEUE", b"SCHEDULER", b"FEED"]
        .iter()
        .enumerate()
        .filter(|(_, s)| contains(line, s))
        .fold(0, |k, (i, _)| k | 1 << i)
}

/// std::getline's lines: split at '\n'; a last line without one counts
/// unless empty.
fn lines(data: &[u8]) -> Vec<&[u8]> {
    let mut v: Vec<&[u8]> = data.split(|&b| b == b'\n').collect();
    if v.last().is_some_and(|l| l.is_empty()) {
        v.pop();
    }
    v
}

/// GetSelectOpt: a number (strtod, finite or NaN) when it can be one.
fn select_opt(val: &[u8], can_be_num: bool) -> Select {
    if !can_be_num {
        return Select::Str(val.to_vec());
    }
    let cs = CString::new(c(val)).expect("no NUL");
    let mut end: *mut c_char = std::ptr::null_mut();
    let value = unsafe { strtod(cs.as_ptr(), &mut end) };
    if value < f64::MIN || value > f64::MAX || end.cast_const() == cs.as_ptr() {
        return Select::Str(val.to_vec());
    }
    Select::Num(value)
}

/// ExtractElements: the select values and their delimiter ("," a list, "-"
/// a range, "" none).
pub fn extract_elements(s: &[u8]) -> (Vec<Vec<u8>>, &'static str) {
    let mut elements: Vec<Vec<u8>> = Vec::new();
    let mut word = Vec::new();
    let n = s.len();
    let mut i = 0;
    while i < n {
        if i == n - 1 {
            word.push(s[i]);
            elements.push(std::mem::take(&mut word));
            break;
        }
        if s[i] == b',' {
            elements.push(std::mem::take(&mut word));
            i += 1;
            continue;
        }
        if s[i] == b' ' && word.is_empty() {
            i += 1;
            continue;
        }
        if s[i] == b' ' {
            return (vec![s.to_vec()], "");
        }
        if s[i] == b'-' && elements.is_empty() {
            let mut rest = Vec::new();
            let mut j = i + 1;
            while j < n {
                if j >= n - 1 {
                    rest.push(s[j]);
                    elements.push(std::mem::take(&mut word));
                    elements.push(rest);
                    return (elements, "-");
                }
                if s[j] == b' ' {
                    elements.push(s.to_vec());
                    return (elements, "");
                }
                if s[j] == b',' {
                    word.push(b'-');
                    word.extend_from_slice(&rest);
                    elements.push(std::mem::take(&mut word));
                    i = j;
                    break;
                }
                rest.push(s[j]);
                j += 1;
            }
            i += 1;
            continue;
        }
        word.push(s[i]);
        i += 1;
    }
    if elements.len() == 1 {
        (elements, "")
    } else {
        (elements, ",")
    }
}

/// ParseSectionAndSet
fn item(section_name: &[u8], line: &[u8], sep: usize) -> Item {
    let mut name = substr(line, 1, sep.wrapping_sub(1));
    trim(&mut name);
    let mut section = Section { multi: false, name: section_name.to_vec(), prefix: Vec::new() };
    if let Some(digit) = find(&name, b"1.") {
        section.prefix = name[..digit].to_vec();
        section.multi = true;
        name = name[digit + 2..].to_vec();
    }
    Item { section, name, description: Vec::new(), action: Vec::new(), value: Select::Str(Vec::new()), select: Vec::new() }
}

/// ParseOptionsAndCommands over the lines after `### OPTIONS`.
fn options_and_commands(lines: &[&[u8]], script: &mut Script) {
    let mut select: Vec<Select> = Vec::new();
    let mut description: Vec<Vec<u8>> = Vec::new();
    let mut section = b"options".to_vec();
    for &line in lines {
        if contains(line, b" SCRIPT") {
            break;
        }
        if line.is_empty() {
            continue;
        }
        if c(line).starts_with(b"###") {
            section = text_after(line, 4);
            remove_tail_and_trim(&mut section, b"###");
            continue;
        }
        let starts_hash_space = c(line).starts_with(b"# ");
        let start = rfind(line, b'(');
        let end = rfind(line, b')');
        if let (true, true, Some(start), Some(end)) = (description.is_empty(), starts_hash_space, start, end) {
            if end == line.len() - 2 {
                let inner = substr(line, start + 1, end.wrapping_sub(start).wrapping_sub(1));
                let (elements, delimiter) = extract_elements(&inner);
                if delimiter.is_empty() {
                    description.push(line[2..].to_vec());
                    continue;
                }
                let can_be_num = delimiter == "-";
                if can_be_num {
                    description.push(line[2..].to_vec());
                } else {
                    let mut d = substr(line, 2, start.wrapping_sub(3));
                    d.push(b'.');
                    description.push(d);
                }
                select = elements.iter().map(|e| select_opt(e, can_be_num)).collect();
                continue;
            }
        }
        if starts_hash_space {
            description.push(line[2..].to_vec());
            continue;
        }
        let eq = find(line, b"=");
        let at = find(line, b"@");
        if let (Some(at), None) = (at, eq) {
            let mut command = item(&section, line, at);
            command.action = line[at + 1..].to_vec();
            trim(&mut command.action);
            command.description = std::mem::take(&mut description);
            script.commands.push(command);
            select.clear();
            continue;
        }
        if let Some(eq) = eq {
            let mut option = item(&section, line, eq);
            let can_be_num = matches!(select.first(), Some(Select::Num(_)));
            let mut value = line[eq + 1..].to_vec();
            trim(&mut value);
            option.value = select_opt(&value, can_be_num);
            option.description = std::mem::take(&mut description);
            option.select = std::mem::take(&mut select);
            script.options.push(option);
        }
    }
}

/// V1::Load's parsing of the script file `data`; None when it isn't an
/// extension script (no kind).
pub fn parse(data: &[u8]) -> Option<Script> {
    let lines = lines(data);
    let mut s = Script::default();
    let (mut before_config, mut in_config, mut in_about, mut in_description) = (false, false, false, false);
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        i += 1;
        if line.is_empty() {
            continue;
        }
        let cl = c(line);
        if !before_config && cl.starts_with(b"###") {
            before_config = true;
        }
        if !before_config && !in_config {
            continue;
        }
        if cl.starts_with(b"### TASK TIME:") {
            s.task_time = text_after(line, 15);
            remove_tail_and_trim(&mut s.task_time, b"###");
            continue;
        }
        if cl.starts_with(b"### NZBGET ") && contains(line, b" SCRIPT") {
            if in_config {
                break;
            }
            before_config = false;
            in_config = true;
            s.kind = script_kind(line);
            continue;
        }
        if cl.starts_with(b"### QUEUE EVENTS:") {
            s.queue_events = text_after(line, 18);
            remove_tail_and_trim(&mut s.queue_events, b"###");
            continue;
        }
        if in_config && cl.starts_with(b"# ") && !in_description {
            in_about = true;
            s.about.extend_from_slice(&line[2..]);
            s.about.push(b'\n');
            continue;
        }
        if in_config && cl.starts_with(b"#") && in_about {
            in_about = false;
            in_description = true;
            continue;
        }
        if in_config && cl.starts_with(b"# NOTE: ") && in_description {
            s.requirements.push(line[8..].to_vec());
            continue;
        }
        if in_config && cl.starts_with(b"# ") && in_description {
            s.description.push(line[2..].to_vec());
            continue;
        }
        if cl.starts_with(b"### OPTIONS") {
            options_and_commands(&lines[i..], &mut s);
            break;
        }
    }
    (s.kind != 0).then_some(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SCRIPT: &[u8] = b"#!/usr/bin/env python\n\
##############################################################################\n\
### NZBGET POST-PROCESSING SCRIPT                                          ###\n\
\n\
# Sorts movies and tv shows.\n\
#\n\
# This is a script for downloaded TV shows and movies.\n\
#\n\
# NOTE: This script requires Python to be installed on your system.\n\
\n\
##############################################################################\n\
### OPTIONS                                                                ###\n\
\n\
# Enable this (yes, no).\n\
#Enable=yes\n\
\n\
# Port (1-65535).\n\
#Port=119\n\
\n\
### CATEGORIES ###\n\
# Category1.Name=Movies\n\
#Category1.Name=Movies\n\
\n\
#ConnectionTest@Send Test E-Mail\n\
\n\
### NZBGET POST-PROCESSING SCRIPT                                          ###\n";

    #[test]
    fn script() {
        let s = parse(SCRIPT).unwrap();
        assert_eq!(s.kind, 1);
        assert_eq!(s.about, b"Sorts movies and tv shows.\n");
        assert_eq!(s.requirements, [b"This script requires Python to be installed on your system.".to_vec()]);
        assert_eq!(s.description, [b"This is a script for downloaded TV shows and movies.".to_vec(), b"".to_vec()].iter().take(1).cloned().collect::<Vec<_>>());
        assert_eq!(s.options.len(), 3);
        assert_eq!(s.options[0].name, b"Enable");
        assert_eq!(s.options[0].select, [Select::Str(b"yes".to_vec()), Select::Str(b"no".to_vec())]);
        assert_eq!(s.options[1].value, Select::Num(119.0));
        assert_eq!(s.options[1].select, [Select::Num(1.0), Select::Num(65535.0)]);
        assert_eq!((s.options[2].section.prefix.as_slice(), s.options[2].section.multi), (b"Category".as_slice(), true));
        assert_eq!(s.options[2].section.name, b"CATEGORIES");
        assert_eq!((s.commands[0].name.as_slice(), s.commands[0].action.as_slice()), (b"ConnectionTest".as_slice(), b"Send Test E-Mail".as_slice()));
        assert!(parse(b"just text\n").is_none());
    }

    #[test]
    fn elements() {
        assert_eq!(extract_elements(b"Always, OnFailure"), (vec![b"Always".to_vec(), b"OnFailure".to_vec()], ","));
        assert_eq!(extract_elements(b"1-65535"), (vec![b"1".to_vec(), b"65535".to_vec()], "-"));
        assert_eq!(extract_elements(b"1, 2-5, 10"), (vec![b"1".to_vec(), b"2-5".to_vec(), b"10".to_vec()], ","));
        assert_eq!(extract_elements(b"some text"), (vec![b"some text".to_vec()], ""));
        assert_eq!(extract_elements(b""), (vec![], ","));
    }
}
