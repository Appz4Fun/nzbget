//! ManifestFile::Load (daemon/extension/ManifestFile.cpp): an extension's
//! manifest.json read into the manifest, as the C++ did it - the same
//! required keys in the same order, strings cut at their first NUL (they went
//! through c_str), entries of the wrong kind skipped, a section named
//! "options" (any case, the C library's tolower) ignored, and an option,
//! command or section that is not an object refusing the whole manifest
//! where Boost's as_object threw.

use crate::json::{self, Value};
use std::ffi::c_int;

extern "C" {
    fn tolower(c: c_int) -> c_int;
}

pub const DEFAULT_SECTION_NAME: &[u8] = b"options";

#[derive(Debug, Clone, PartialEq)]
pub enum Select {
    Number(f64),
    String(Vec<u8>),
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Section {
    pub multi: bool,
    pub name: Vec<u8>,
    pub prefix: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ManifestOption {
    pub section: Section,
    pub name: Vec<u8>,
    pub display_name: Vec<u8>,
    pub description: Vec<Vec<u8>>,
    pub value: Select,
    pub select: Vec<Select>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Command {
    pub section: Section,
    pub name: Vec<u8>,
    pub display_name: Vec<u8>,
    pub action: Vec<u8>,
    pub description: Vec<Vec<u8>>,
}

/// The string fields, in the order of `FIELDS`.
pub const FIELDS: [&[u8]; 12] = [b"author", b"main", b"homepage", b"about", b"version", b"name", b"displayName", b"kind",
    b"license", b"taskTime", b"queueEvents", b"nzbgetMinVersion"];

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Manifest {
    /// Writes performed before validation stopped; missing fields remain unchanged.
    pub fields: [Option<Vec<u8>>; 12],
    pub description: Vec<Vec<u8>>,
    pub requirements: Vec<Vec<u8>>,
    pub options: Vec<ManifestOption>,
    pub commands: Vec<Command>,
    /// Valid sections in input order, also applied to entries already in the C++ destination.
    pub sections: Vec<Section>,
}

#[derive(Debug, PartialEq)]
pub enum Outcome {
    Loaded(Box<Manifest>),
    /// a required key missing or of another kind
    Refused(Box<Manifest>),
    /// "Failed to parse %s. Syntax error."
    Syntax,
    /// "The manifest isn't a JSON object."
    NotObject,
    /// an option, command or section that isn't an object (as_object threw)
    ElementNotObject(Box<Manifest>),
}

/// An option, command or section entry where the C++ called as_object.
struct Thrown;

fn c_str(s: &[u8]) -> Vec<u8> {
    s.iter().take_while(|&&b| b != 0).copied().collect()
}

fn string(json: &Value, key: &[u8]) -> Option<Vec<u8>> {
    match json.get(key) {
        Some(Value::String(s)) => Some(c_str(s)),
        _ => None,
    }
}

fn select(v: &Value) -> Option<Select> {
    match v {
        Value::String(s) => Some(Select::String(c_str(s))),
        v => v.to_f64().map(Select::Number),
    }
}

/// ValidateTxtAndSet: the strings of an array (None when not an array).
fn texts(json: &Value, key: &[u8]) -> Option<Vec<Vec<u8>>> {
    match json.get(key) {
        Some(Value::Array(items)) => Some(items.iter().filter_map(|v| match v {
            Value::String(s) => Some(c_str(s)),
            _ => None,
        }).collect()),
        _ => None,
    }
}

fn as_object(v: &Value) -> Result<&Value, Thrown> {
    match v {
        Value::Object(_) => Ok(v),
        _ => Err(Thrown),
    }
}

/// CheckKeyAndSet with DEFAULT_SECTION_NAME.
fn section_name(json: &Value) -> Vec<u8> {
    string(json, b"section").unwrap_or_else(|| DEFAULT_SECTION_NAME.to_vec())
}

fn options(json: &Value, options: &mut Vec<ManifestOption>) -> Result<bool, Thrown> {
    let Some(Value::Array(items)) = json.get(b"options") else { return Ok(false) };
    for item in items {
        let item = as_object(item)?;
        let Some(Value::Array(selects)) = item.get(b"select") else { continue };
        let section = Section { name: section_name(item), ..Section::default() };
        let Some(name) = string(item, b"name") else { continue };
        let Some(display_name) = string(item, b"displayName") else { continue };
        let Some(value) = item.get(b"value").and_then(select) else { continue };
        let Some(description) = texts(item, b"description") else { continue };
        options.push(ManifestOption { section, name, display_name, description, value, select: selects.iter().filter_map(select).collect() });
    }
    Ok(true)
}

fn commands(json: &Value, commands: &mut Vec<Command>) -> Result<bool, Thrown> {
    let Some(Value::Array(items)) = json.get(b"commands") else { return Ok(false) };
    for item in items {
        let item = as_object(item)?;
        let section = Section { name: section_name(item), ..Section::default() };
        let Some(name) = string(item, b"name") else { continue };
        let Some(display_name) = string(item, b"displayName") else { continue };
        let Some(description) = texts(item, b"description") else { continue };
        let Some(action) = string(item, b"action") else { continue };
        commands.push(Command { section, name, display_name, action, description });
    }
    Ok(true)
}

/// Util::StrCaseCmp: equal lengths and equal bytes after tolower.
fn str_case_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(&x, &y)| unsafe { tolower(x as c_int) == tolower(y as c_int) })
}

fn sections(json: &Value, sections: &mut Vec<Section>) -> Result<(), Thrown> {
    let Some(Value::Array(items)) = json.get(b"sections") else { return Ok(()) };
    for item in items {
        let item = as_object(item)?;
        let Some(name) = string(item, b"name") else { continue };
        if str_case_eq(&name, DEFAULT_SECTION_NAME) {
            continue;
        }
        let Some(prefix) = string(item, b"prefix") else { continue };
        let Some(&Value::Bool(multi)) = item.get(b"multi") else { continue };
        let section = Section { multi, name, prefix };
        sections.push(section);
    }
    Ok(())
}

/// ValidateAndSet.
fn validate(json: &Value, manifest: &mut Manifest) -> Result<bool, Thrown> {
    for (field, key) in manifest.fields.iter_mut().zip(FIELDS).take(11) {
        let Some(s) = string(json, key) else { return Ok(false) };
        *field = Some(s);
    }
    if !options(json, &mut manifest.options)? { return Ok(false) }
    if !commands(json, &mut manifest.commands)? { return Ok(false) }
    sections(json, &mut manifest.sections)?;
    let Some(description) = texts(json, b"description") else { return Ok(false) };
    manifest.description = description;
    let Some(requirements) = texts(json, b"requirements") else { return Ok(false) };
    manifest.requirements = requirements;
    manifest.fields[11] = string(json, b"nzbgetMinVersion");
    Ok(true)
}

/// Load, from the text the C++ read.
pub fn load(text: &[u8], limits: json::Limits) -> Outcome {
    let Some(json) = json::parse(text, limits) else { return Outcome::Syntax };
    if !matches!(json, Value::Object(_)) {
        return Outcome::NotObject;
    }
    let mut manifest = Box::<Manifest>::default();
    match validate(&json, &mut manifest) {
        Ok(true) => Outcome::Loaded(manifest),
        Ok(false) => Outcome::Refused(manifest),
        Err(Thrown) => Outcome::ElementNotObject(manifest),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE: &str = r#""author":"A","main":"m.py","homepage":"h","about":"ab","version":"1","name":"N",
        "displayName":"D","kind":"POST-PROCESSING","license":"GPL","taskTime":"","queueEvents":"",
        "description":["d1",2,"d\u00002"],"requirements":[]"#;

    fn load_str(s: &str) -> Outcome {
        load(s.as_bytes(), json::TEST_LIMITS)
    }

    #[test]
    fn loads_and_refuses() {
        let Outcome::Loaded(m) = load_str(&format!("{{{BASE},\"options\":[],\"commands\":[]}}")) else { panic!() };
        assert_eq!(m.fields[0].as_deref(), Some(&b"A"[..]));
        assert_eq!(m.fields[11], None);
        assert_eq!(m.description, vec![b"d1".to_vec(), b"d".to_vec()]);
        assert!(matches!(load_str(&format!("{{{BASE},\"options\":[]}}")), Outcome::Refused(_)));
        assert_eq!(load_str("[]"), Outcome::NotObject);
        assert_eq!(load_str("{"), Outcome::Syntax);
        assert!(matches!(load_str(&format!("{{{BASE},\"options\":[],\"commands\":[\"x\"]}}")), Outcome::ElementNotObject(_)));
        // a required key missing before the commands: refused, not thrown
        assert!(matches!(load_str("{\"options\":[1],\"commands\":[\"x\"]}"), Outcome::Refused(_)));
    }

    #[test]
    fn options_commands_and_sections() {
        let text = format!(r#"{{{BASE},"nzbgetMinVersion":"24",
            "options":[{{"name":"o1","displayName":"O1","value":5,"description":[],"select":[1,"a",true,null,2.5]}},
                       {{"section":"S","name":"o2","displayName":"O2","value":"v","description":["x"],"select":[]}},
                       {{"name":"o3","displayName":"O3","value":true,"description":[],"select":[]}},
                       {{"name":"o4","displayName":"O4","value":1,"description":[]}}],
            "commands":[{{"section":"S","name":"c","displayName":"C","description":[],"action":"go"}}],
            "sections":[{{"name":"S","prefix":"P","multi":true}},{{"name":"OPTIONS","prefix":"Q","multi":false}},
                        {{"name":"S","prefix":"P2"}}]}}"#);
        let Outcome::Loaded(m) = load_str(&text) else { panic!() };
        assert_eq!(m.fields[11].as_deref(), Some(&b"24"[..]));
        assert_eq!(m.options.len(), 2);
        assert_eq!(m.options[0].select, vec![Select::Number(1.0), Select::String(b"a".to_vec()), Select::Number(2.5)]);
        assert_eq!(m.options[0].section, Section { multi: false, name: b"options".to_vec(), prefix: vec![] });
        assert_eq!(m.sections, vec![Section { multi: true, name: b"S".to_vec(), prefix: b"P".to_vec() }]);
        assert_eq!(m.options[1].section, Section { multi: false, name: b"S".to_vec(), prefix: vec![] });
        assert_eq!(m.commands[0].section, m.options[1].section);
    }
}
