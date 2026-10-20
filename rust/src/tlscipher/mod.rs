//! Local TLS cipher policy. Native crypto and provider I/O are injected separately.
use std::collections::BTreeMap;
pub mod job;

pub const RECORD_BYTES: u64 = 16_384;
pub const SAMPLE_NS: u64 = 200_000_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Protocol { Tls12, Tls13 }

#[derive(Clone, Debug)]
pub struct Suite {
    pub name: String,
    pub algorithm: String,
    pub protocol: Protocol,
    pub security_bits: u16,
    pub aead: bool,
    pub ephemeral: bool,
    pub certificate: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct Sample {
    pub round: u8,
    pub bytes: u64,
    pub elapsed_ns: u64,
    pub correct: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Support { Supported, Unsupported, Unknown }

#[derive(Clone, Debug, PartialEq)]
pub struct Choice { pub cipher: String, pub bytes_per_second: f64 }

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error(pub &'static str);

pub fn eligible(suite: &Suite) -> bool {
    suite.security_bits >= 128 && suite.aead && suite.certificate &&
        (suite.protocol == Protocol::Tls13 || suite.ephemeral)
}

pub fn throughput(samples: &[Sample]) -> Result<f64, Error> {
    if samples.len() != 5 { return Err(Error("five rounds are required")); }
    let mut seen = [false; 5];
    let mut rates = [0.0; 5];
    for (i, sample) in samples.iter().enumerate() {
        let round = usize::from(sample.round);
        if round >= 5 || seen[round] || !sample.correct || sample.elapsed_ns < SAMPLE_NS ||
            sample.bytes == 0 || sample.bytes % RECORD_BYTES != 0 {
            return Err(Error("invalid or incomplete measurement"));
        }
        seen[round] = true;
        rates[i] = sample.bytes as f64 * 1_000_000_000.0 / sample.elapsed_ns as f64;
    }
    rates.sort_by(f64::total_cmp);
    Ok(rates[2])
}

pub fn choose(suites: &[Suite], rates: &BTreeMap<String, f64>,
    support: &BTreeMap<String, Support>, current: &str) -> Result<Option<Choice>, Error> {
    let mut candidates = Vec::new();
    let mut names = std::collections::BTreeSet::new();
    for suite in suites.iter().filter(|s| eligible(s)) {
        if !names.insert(&suite.name) { return Err(Error("duplicate cipher suite")); }
        match support.get(&suite.name) {
            Some(Support::Supported) => (),
            Some(Support::Unsupported) => continue,
            _ => return Err(Error("server compatibility is incomplete")),
        }
        let rate = *rates.get(&suite.algorithm).ok_or(Error("unmeasured algorithm"))?;
        if !rate.is_finite() || rate <= 0.0 { return Err(Error("invalid algorithm rate")); }
        candidates.push((suite, rate));
    }
    candidates.sort_by(|(a, ar), (b, br)| {
        br.total_cmp(ar)
            .then_with(|| (b.name == current).cmp(&(a.name == current)))
            .then_with(|| (b.protocol == Protocol::Tls13).cmp(&(a.protocol == Protocol::Tls13)))
            .then_with(|| a.name.cmp(&b.name))
    });
    Ok(candidates.first().map(|(s, rate)| Choice { cipher: s.name.clone(), bytes_per_second: *rate }))
}

pub(crate) fn option(line: &[u8]) -> Option<(&[u8], &[u8], usize)> {
    let eq = line.iter().position(|&b| b == b'=')?;
    let name = trim(&line[..eq]);
    if name.starts_with(b"#") { return None; }
    Some((name, trim(&line[eq + 1..]), eq))
}

fn trim(bytes: &[u8]) -> &[u8] {
    let start = bytes.iter().position(|b| !b.is_ascii_whitespace()).unwrap_or(bytes.len());
    let end = bytes.iter().rposition(|b| !b.is_ascii_whitespace()).map_or(start, |i| i + 1);
    &bytes[start..end]
}

pub(crate) fn server_option(name: &[u8], suffix: &[u8]) -> Option<u32> {
    if name.len() <= 7 + suffix.len() || !name[..6].eq_ignore_ascii_case(b"server") { return None; }
    let dot = name.iter().position(|&b| b == b'.')?;
    if !name.get(dot + 1..)?.eq_ignore_ascii_case(suffix) { return None; }
    let id = std::str::from_utf8(name.get(6..dot)?).ok()?.parse::<u32>().ok()?;
    (id > 0 && name.get(6..dot)? == id.to_string().as_bytes()).then_some(id)
}

/// Change only the requested cipher lines; do not parse/re-emit other values.
pub fn patch_config(original: &[u8], changes: &BTreeMap<u32, String>) -> Result<Vec<u8>, Error> {
    if original.len() > 16 * 1024 * 1024 { return Err(Error("configuration exceeds size limit")); }
    if changes.is_empty() { return Ok(original.to_vec()); }
    let hosts: std::collections::BTreeSet<_> = original.split(|&b| b == b'\n')
        .filter_map(option).filter_map(|(name, _, _)| server_option(name, b"host")).collect();
    for (id, value) in changes {
        if !hosts.contains(id) || value.is_empty() || value.len() > 128 ||
            !value.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-') {
            return Err(Error("invalid cipher patch"));
        }
    }
    let newline: &[u8] = if original.windows(2).any(|s| s == b"\r\n") { b"\r\n" } else { b"\n" };
    let mut out = Vec::with_capacity(original.len());
    let mut written = std::collections::BTreeSet::new();
    for line in original.split_inclusive(|&b| b == b'\n') {
        if let Some((name, _, eq)) = option(line) {
            if let Some((id, value)) = server_option(name, b"cipher").and_then(|id| changes.get(&id).map(|v| (id, v))) {
                out.extend_from_slice(&line[..=eq]);
                out.extend_from_slice(value.as_bytes());
                if line.ends_with(b"\r\n") { out.extend_from_slice(b"\r\n"); }
                else if line.ends_with(b"\n") { out.push(b'\n'); }
                written.insert(id);
                continue;
            }
        }
        out.extend_from_slice(line);
    }
    for (id, value) in changes.iter().filter(|(id, _)| !written.contains(id)) {
        if !out.is_empty() && !out.ends_with(b"\n") { out.extend_from_slice(newline); }
        out.extend_from_slice(format!("Server{id}.Cipher={value}").as_bytes());
        out.extend_from_slice(newline);
    }
    if out.len() > 16 * 1024 * 1024 { return Err(Error("patched configuration exceeds size limit")); }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn suite(name: &str, algorithm: &str, protocol: Protocol) -> Suite {
        Suite { name: name.into(), algorithm: algorithm.into(), protocol,
            security_bits: 128, aead: true, ephemeral: true, certificate: true }
    }
    fn suites() -> Vec<Suite> {
        vec![suite("TLS_AES_128_GCM_SHA256", "AES-128-GCM", Protocol::Tls13),
            suite("TLS_CHACHA20_POLY1305_SHA256", "CHACHA20-POLY1305", Protocol::Tls13),
            suite("ECDHE-RSA-AES128-GCM-SHA256", "AES-128-GCM", Protocol::Tls12)]
    }
    fn rates() -> BTreeMap<String, f64> {
        BTreeMap::from([("AES-128-GCM".into(), 300.0), ("CHACHA20-POLY1305".into(), 200.0)])
    }
    fn supported() -> BTreeMap<String, Support> {
        suites().iter().map(|s| (s.name.clone(), Support::Supported)).collect()
    }
    fn samples() -> Vec<Sample> {
        (0..5).map(|round| Sample { round, bytes: RECORD_BYTES * (round as u64 + 1),
            elapsed_ns: SAMPLE_NS, correct: true }).collect()
    }

    #[test]
    fn eligible_secure_suites() {
        for s in suites() { assert!(eligible(&s), "secure suite must be eligible: {}", s.name); }
        let mut s = suites()[0].clone();
        s.ephemeral = false; // TLS 1.3 has its own key exchange policy.
        assert!(eligible(&s));
    }
    #[test]
    fn excludes_unsafe_suites() {
        for field in 0..4 {
            let mut s = suites()[2].clone();
            match field { 0 => s.security_bits = 127, 1 => s.aead = false,
                2 => s.ephemeral = false, _ => s.certificate = false }
            assert!(!eligible(&s));
        }
    }
    #[test]
    fn requires_five_unique_valid_rounds() {
        let rate = throughput(&samples()).expect("five complete samples must produce a rate");
        assert_eq!(rate, (RECORD_BYTES * 3) as f64 * 5.0);
    }
    #[test]
    fn rejects_invalid_samples() {
        let mut s = samples();
        s[0].elapsed_ns = 199_999_999;
        assert!(throughput(&s).is_err());
        s = samples(); s[4].round = 3;
        assert!(throughput(&s).is_err());
        s = samples(); s[2].correct = false;
        assert!(throughput(&s).is_err());
        s = samples(); s[2].bytes = RECORD_BYTES - 1;
        assert!(throughput(&s).is_err());
        assert!(throughput(&samples()[..4]).is_err());
    }
    #[test]
    fn selects_fastest_per_server() {
        let s = suites(); let r = rates(); let mut support = supported();
        assert_eq!(choose(&s, &r, &support, "").unwrap().unwrap().cipher, s[0].name);
        support.insert(s[0].name.clone(), Support::Unsupported);
        support.insert(s[2].name.clone(), Support::Unsupported);
        assert_eq!(choose(&s, &r, &support, "").unwrap().unwrap().cipher, s[1].name);
        support.insert(s[1].name.clone(), Support::Unsupported);
        support.insert(s[2].name.clone(), Support::Supported);
        assert_eq!(choose(&s, &r, &support, "").unwrap().unwrap().cipher, s[2].name);
    }
    #[test]
    fn unknown_prevents_choice() {
        let s = suites(); let mut support = supported();
        support.insert(s[1].name.clone(), Support::Unknown);
        assert!(choose(&s, &rates(), &support, "").is_err());
        support.remove(&s[1].name);
        assert!(choose(&s, &rates(), &support, "").is_err());
    }
    #[test]
    fn rejects_missing_or_nonfinite_rates() {
        for rate in [f64::NAN, f64::INFINITY, 0.0, -1.0] {
            let mut r = rates(); r.insert("AES-128-GCM".into(), rate);
            assert!(choose(&suites(), &r, &supported(), "").is_err());
        }
        assert!(choose(&suites(), &BTreeMap::new(), &supported(), "").is_err());
    }
    #[test]
    fn unsupported_unmeasured_suites_do_not_block_known_fallback() {
        let s = suites();
        // A confirmed rejected suite cannot win for this server, regardless
        // of whether its algorithm could be measured on this computer.
        for unusable_rate in [None, Some(f64::NAN), Some(f64::INFINITY), Some(0.0), Some(-1.0)] {
            let mut r = rates();
            r.remove("CHACHA20-POLY1305");
            if let Some(value) = unusable_rate { r.insert("CHACHA20-POLY1305".into(), value); }
            let mut support = supported();
            support.insert(s[1].name.clone(), Support::Unsupported);
            assert_eq!(choose(&s, &r, &support, "").unwrap().unwrap().cipher, s[0].name);
            // An unmeasured possible winner remains inconclusive.
            support.insert(s[1].name.clone(), Support::Supported);
            assert!(choose(&s, &r, &support, "").is_err());
            support.insert(s[1].name.clone(), Support::Unknown);
            assert!(choose(&s, &r, &support, "").is_err());
            support.remove(&s[1].name);
            assert!(choose(&s, &r, &support, "").is_err());
        }
        let rejected = s.iter().map(|suite| (suite.name.clone(), Support::Unsupported)).collect();
        assert_eq!(choose(&s, &BTreeMap::new(), &rejected, "").unwrap(), None);
    }
    #[test]
    fn ties_retain_current() {
        let s = suites();
        assert_eq!(choose(&s, &rates(), &supported(), &s[2].name).unwrap().unwrap().cipher, s[2].name);
    }
    #[test]
    fn ties_prefer_tls13_then_name() {
        let mut r = rates(); r.insert("CHACHA20-POLY1305".into(), 300.0);
        assert_eq!(choose(&suites(), &r, &supported(), "").unwrap().unwrap().cipher, suites()[0].name);
    }
    #[test]
    fn no_supported_cipher_leaves_server_unchanged() {
        let support = suites().iter().map(|s| (s.name.clone(), Support::Unsupported)).collect();
        assert_eq!(choose(&suites(), &rates(), &support, "old cipher").unwrap(), None);
    }

    #[test]
    fn patch_preserves_unrelated_bytes() {
        let original = b"# private \xff\r\nServer1.Host=news.example.invalid\r\nServer1.Password=secret\r\nServer1.Cipher=old\r\nOther=x\r\n";
        let actual = patch_config(original, &BTreeMap::from([(1, "TLS_AES_128_GCM_SHA256".into())])).unwrap();
        assert_eq!(actual, b"# private \xff\r\nServer1.Host=news.example.invalid\r\nServer1.Password=secret\r\nServer1.Cipher=TLS_AES_128_GCM_SHA256\r\nOther=x\r\n");
    }
    #[test]
    fn patches_duplicate_case_insensitive_cipher_lines() {
        let original = b"Server1.Host=example.invalid\nserver1.cipher=old\n Server1.Cipher =wrong\n#Server1.Cipher=comment\n";
        assert_eq!(patch_config(original, &BTreeMap::from([(1,"NEW_SUITE".into())])).unwrap(),
            b"Server1.Host=example.invalid\nserver1.cipher=NEW_SUITE\n Server1.Cipher =NEW_SUITE\n#Server1.Cipher=comment\n");
    }
    #[test]
    fn appends_missing_cipher_with_matching_newline() {
        let original = b"Server1.Host=example.invalid\r\n# tail";
        let result = patch_config(original, &BTreeMap::from([(1,"NEW_SUITE".into())])).unwrap();
        assert!(result.starts_with(original));
        assert!(result.ends_with(b"# tail\r\nServer1.Cipher=NEW_SUITE\r\n"));
    }
    #[test]
    fn rejects_invalid_patch_values() {
        let original = b"Server1.Host=example.invalid\n";
        for value in ["", "a:b", "a\nOther=yes", "a\0b"] {
            assert!(patch_config(original, &BTreeMap::from([(1,value.into())])).is_err());
        }
        assert!(patch_config(original, &BTreeMap::from([(2,"NEW_SUITE".into())])).is_err());
        assert!(patch_config(original, &BTreeMap::from([(0,"NEW_SUITE".into())])).is_err());
    }
}
