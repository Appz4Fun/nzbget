//! Single owned worker; native facilities are injected and never borrowed from an RPC.
use super::*;
use std::fmt::Write;
use std::sync::{Arc, Mutex, atomic::{AtomicBool, AtomicU64, Ordering}};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Clone)]
pub struct Server {
    pub id: u32, pub name: String, pub host: String, pub port: u16,
    pub username: String, pub password: String, pub cipher: String,
    pub ip_version: u8, pub verification: u8,
}
pub struct Snapshot { pub bytes: Vec<u8>, pub servers: Vec<Server> }
pub struct Probe { pub support: Support, pub message: &'static str }
pub trait Decryptor {
    fn prepare_batch(&mut self, first: u64, count: u32) -> Result<(), Error>;
    fn record(&mut self, sequence: u64) -> Result<u64, Error>;
}
pub trait Backend: Send + Sync + 'static {
    fn snapshot(&self) -> Result<Snapshot, Error>;
    fn suites(&self) -> Result<Vec<Suite>, Error>;
    fn prepare(&self, algorithm: &str) -> Result<Box<dyn Decryptor>, Error>;
    fn probe(&self, server: &Server, suite: &Suite, cancel: &AtomicBool, deadline: Instant) -> Probe;
    fn commit(&self, snapshot: &Snapshot, changes: &BTreeMap<u32, String>, cancel: &AtomicBool) -> Result<bool, Error>;
}

#[derive(Clone)]
struct AlgorithmResult {
    name: String, rate: Option<f64>, samples: Vec<Sample>, message: &'static str,
}
#[derive(Clone)]
struct ServerResult {
    id: u32, name: String, host: String, port: u16, old: String, selected: String,
    outcome: &'static str, message: &'static str,
    support: Vec<Option<bool>>,
}
struct Report {
    id: String, state: &'static str, message: &'static str, saved: bool,
    algorithms: Vec<AlgorithmResult>, servers: Vec<ServerResult>, common: Option<Vec<String>>,
    excluded: Vec<String>, current_algorithm: String, current_server: u32,
    current_cipher: String, completed_probes: u32, total_probes: u32,
    ciphers: Vec<String>,
}
fn quote(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""), '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"), '\r' => out.push_str("\\r"), '\t' => out.push_str("\\t"),
            c if c < ' ' => { let _ = write!(out, "\\u{:04x}", c as u32); },
            c => out.push(c),
        }
    }
    out.push('"'); out
}
impl Report {
    fn active(&self) -> bool { matches!(self.state, "measuring" | "probing" | "saving") }
    fn json(&self) -> Result<String, Error> {
        let mut out = format!("{{\"Available\":true,\"JobID\":{},\"State\":{},\"Message\":{},\"Saved\":{},\"ReloadRequired\":{},\"Algorithms\":[",
            quote(&self.id), quote(self.state), quote(self.message), self.saved, self.saved);
        for (i, a) in self.algorithms.iter().enumerate() {
            if i > 0 { out.push(','); }
            let sample_rates: Vec<_> = a.samples.iter().filter(|s| s.elapsed_ns > 0)
                .map(|s| s.bytes as f64 * 1e9 / s.elapsed_ns as f64).collect();
            let min = sample_rates.iter().copied().reduce(f64::min).unwrap_or(0.0);
            let max = sample_rates.iter().copied().reduce(f64::max).unwrap_or(0.0);
            let _ = write!(out, "{{\"Algorithm\":{},\"BytesPerSecond\":{},\"Minimum\":{},\"Maximum\":{},\"Message\":{},\"Samples\":[",
                quote(&a.name), a.rate.map_or_else(|| "null".into(), |v| v.to_string()), min, max, quote(a.message));
            for (j, s) in a.samples.iter().enumerate() {
                if j > 0 { out.push(','); }
                let _ = write!(out, "{{\"Round\":{},\"Bytes\":{},\"ElapsedNS\":{},\"Correct\":{}}}", s.round, s.bytes, s.elapsed_ns, s.correct);
            }
            out.push_str("]}");
        }
        let _ = write!(out, "],\"CurrentAlgorithm\":{},\"CurrentServer\":{},\"CurrentCipher\":{},\"CompletedProbes\":{},\"TotalProbes\":{},\"ExcludedSuites\":[",
            quote(&self.current_algorithm), self.current_server, quote(&self.current_cipher), self.completed_probes, self.total_probes);
        out.push_str(&self.excluded.iter().map(|s| quote(s)).collect::<Vec<_>>().join(","));
        out.push_str("],\"CipherSuites\":[");
        out.push_str(&self.ciphers.iter().map(|s| quote(s)).collect::<Vec<_>>().join(","));
        out.push_str("],\"Servers\":[");
        for (i, s) in self.servers.iter().enumerate() {
            if i > 0 { out.push(','); }
            let _ = write!(out, "{{\"ID\":{},\"Name\":{},\"Host\":{},\"Port\":{},\"OldCipher\":{},\"SelectedCipher\":{},\"Outcome\":{},\"Message\":{},\"CipherSupport\":[",
                s.id, quote(&s.name), quote(&s.host), s.port, quote(&s.old), quote(&s.selected), quote(s.outcome), quote(s.message));
            out.push_str(&s.support.iter().map(|s| match s { Some(true) => "true", Some(false) => "false", None => "null" }).collect::<Vec<_>>().join(","));
            out.push_str("]}");
        }
        out.push_str("],\"CommonSupported\":");
        match &self.common {
            Some(names) => { out.push('['); out.push_str(&names.iter().map(|s| quote(s)).collect::<Vec<_>>().join(",")); out.push(']'); },
            None => out.push_str("null"),
        }
        out.push('}');
        if out.len() > 1024 * 1024 { return Err(Error("status exceeds size limit")); }
        Ok(out)
    }
}

struct Running { report: Arc<Mutex<Report>>, cancel: Arc<AtomicBool>, handle: Option<JoinHandle<()>> }
#[derive(Default)]
pub struct Service { running: Mutex<Option<Running>> }
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

impl Service {
    pub fn start(&self, backend: Arc<dyn Backend>) -> Result<String, Error> {
        let mut slot = self.running.lock().map_err(|_| Error("job state is unavailable"))?;
        if let Some(job) = slot.as_ref() {
            let report = job.report.lock().map_err(|_| Error("job state is unavailable"))?;
            if report.active() { return Ok(report.id.clone()); }
        }
        if let Some(mut previous) = slot.take() {
            if let Some(handle) = previous.handle.take() { handle.join().map_err(|_| Error("previous worker failed"))?; }
        }
        let snapshot = backend.snapshot()?;
        if snapshot.bytes.len() > 16 * 1024 * 1024 || snapshot.servers.len() > 256 { return Err(Error("configuration exceeds admission limits")); }
        if snapshot.servers.is_empty() { return Err(Error("no encrypted news servers are configured")); }
        let mut ids = std::collections::BTreeSet::new();
        for server in &snapshot.servers {
            if server.id == 0 || !ids.insert(server.id) || server.host.is_empty() || server.host.len() > 255 || server.name.len() > 256 ||
                server.cipher.len() > 4096 || server.port == 0 || server.verification > 2 || !matches!(server.ip_version, 0 | 4 | 6) {
                return Err(Error("invalid server snapshot"));
            }
        }
        let all = backend.suites()?;
        if all.len() > 4096 || all.iter().any(|s| s.name.len() > 128 || s.algorithm.len() > 128) { return Err(Error("cipher catalog exceeds admission limits")); }
        let excluded = all.iter().filter(|s| !eligible(s)).map(|s| s.name.clone()).collect();
        let suites: Vec<_> = all.into_iter().filter(eligible).collect();
        let mut names = std::collections::BTreeSet::new();
        if suites.is_empty() || suites.len() > 128 || suites.iter().any(|s| s.name.is_empty() || s.name.len() > 128 || s.algorithm.is_empty() ||
            s.algorithm.len() > 128 || !s.name.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-')) || !names.insert(s.name.clone())) {
            return Err(Error("invalid or excessive cipher inventory"));
        }
        let algorithms: std::collections::BTreeSet<_> = suites.iter().map(|s| s.algorithm.clone()).collect();
        if algorithms.len() > 64 { return Err(Error("too many bulk algorithms")); }
        let id = format!("{:x}-{:x}", SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos(), NEXT_ID.fetch_add(1, Ordering::Relaxed));
        let report = Arc::new(Mutex::new(Report { id: id.clone(), state: "measuring", message: "Measuring local authenticated-decryption speed.", saved: false,
            algorithms: algorithms.into_iter().map(|name| AlgorithmResult { name, rate: None, samples: Vec::new(), message: "Waiting" }).collect(),
            servers: snapshot.servers.iter().map(|s| ServerResult { id: s.id, name: s.name.clone(), host: s.host.clone(), port: s.port,
                old: s.cipher.clone(), selected: String::new(), outcome: "waiting", message: "", support: vec![None; suites.len()] }).collect(), common: None,
            excluded, current_algorithm: String::new(), current_server: 0, current_cipher: String::new(), completed_probes: 0,
            total_probes: (snapshot.servers.len() * suites.len()) as u32, ciphers: suites.iter().map(|s| s.name.clone()).collect() }));
        // Reserve room for sample details/common suites/final outcomes before
        // spawning; a job must never become unobservable after being admitted.
        if report.lock().map_err(|_| Error("job state is unavailable"))?.json()?.len() > 512 * 1024 {
            return Err(Error("server descriptions exceed status admission limits"));
        }
        let cancel = Arc::new(AtomicBool::new(false));
        let result = report.clone(); let flag = cancel.clone();
        let handle = thread::Builder::new().name("tls-cipher-optimizer".into()).spawn(move || {
            let outcome = run(backend.as_ref(), &snapshot, &suites, &flag, &result);
            let mut report = result.lock().unwrap_or_else(|e| e.into_inner());
            match outcome {
                Ok(()) => { report.state = "completed"; report.message = if report.saved { "Saved the fastest measured supported cipher for each fully tested server." } else { "Tests completed; no cipher settings were changed." }; },
                Err(error) => {
                    report.state = if flag.load(Ordering::Acquire) { "cancelled" } else { "failed" }; report.message = error.0;
                    for server in &mut report.servers {
                        if server.outcome == "ready" { server.outcome = "unchanged"; server.message = "No configuration commit was completed."; }
                    }
                },
            }
        }).map_err(|_| Error("could not start cipher worker"))?;
        *slot = Some(Running { report, cancel, handle: Some(handle) });
        Ok(id)
    }

    pub fn status(&self, id: Option<&str>) -> Result<String, Error> {
        let slot = self.running.lock().map_err(|_| Error("job state is unavailable"))?;
        match slot.as_ref() {
            Some(job) => {
                let report = job.report.lock().map_err(|_| Error("job state is unavailable"))?;
                if id.is_some_and(|id| id != report.id) { return Err(Error("unknown cipher job")); }
                report.json()
            },
            None if id.is_some() => Err(Error("unknown cipher job")),
            None => Ok("{\"Available\":true,\"JobID\":\"\",\"State\":\"idle\",\"Saved\":false,\"Algorithms\":[],\"Servers\":[],\"CommonSupported\":null}".into()),
        }
    }

    pub fn cancel(&self, id: &str) -> Result<(), Error> {
        let slot = self.running.lock().map_err(|_| Error("job state is unavailable"))?;
        let job = slot.as_ref().ok_or(Error("unknown cipher job"))?;
        if job.report.lock().map_err(|_| Error("job state is unavailable"))?.id != id { return Err(Error("unknown cipher job")); }
        job.cancel.store(true, Ordering::Release); Ok(())
    }

    pub fn shutdown(&self) {
        let mut slot = self.running.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(mut job) = slot.take() {
            job.cancel.store(true, Ordering::Release);
            if let Some(handle) = job.handle.take() { let _ = handle.join(); }
        }
    }
}
impl Drop for Service { fn drop(&mut self) { self.shutdown(); } }

fn guard(cancel: &AtomicBool, deadline: Instant) -> Result<(), Error> {
    if cancel.load(Ordering::Acquire) { Err(Error("Tests cancelled; cipher settings were not changed.")) }
    else if Instant::now() >= deadline { Err(Error("Cipher test deadline exceeded; settings were not changed.")) }
    else { Ok(()) }
}

fn measure(engine: &mut dyn Decryptor, round: u8, floor: u64, sequence: &mut u64,
    cancel: &AtomicBool, deadline: Instant, partial: &mut Sample) -> Result<Sample, Error> {
    let mut sample = Sample { round, bytes: 0, elapsed_ns: 0, correct: true };
    while sample.elapsed_ns < floor {
        guard(cancel, deadline)?;
        engine.prepare_batch(*sequence, 64)?;
        guard(cancel, deadline)?;
        let start = Instant::now();
        let mut records = 0;
        let batch = (|| {
            for n in 0..64 {
                if engine.record(*sequence + n)? != RECORD_BYTES { return Err(Error("record decryption correctness check failed")); }
                records += 1;
            }
            Ok(())
        })();
        sample.elapsed_ns = sample.elapsed_ns.checked_add(u64::try_from(start.elapsed().as_nanos()).map_err(|_| Error("elapsed duration overflow"))?).ok_or(Error("elapsed duration overflow"))?;
        sample.bytes = sample.bytes.checked_add(records * RECORD_BYTES).ok_or(Error("byte count overflow"))?;
        *partial = sample;
        batch?;
        *sequence = sequence.checked_add(64).ok_or(Error("record sequence overflow"))?;
    }
    Ok(sample)
}

fn run(backend: &dyn Backend, snapshot: &Snapshot, suites: &[Suite], cancel: &AtomicBool, report: &Mutex<Report>) -> Result<(), Error> {
    let deadline = Instant::now() + Duration::from_secs(600);
    guard(cancel, deadline)?;
    let names: Vec<_> = report.lock().unwrap().algorithms.iter().map(|a| a.name.clone()).collect();
    let mut engines = Vec::new();
    for name in &names { guard(cancel, deadline)?; engines.push(backend.prepare(name).ok()); }
    let mut sequences = vec![0u64; names.len()];
    for i in 0..names.len() {
        guard(cancel, deadline)?;
        report.lock().unwrap().current_algorithm = names[i].clone();
        if let Some(engine) = engines[i].as_mut() {
            if let Err(error) = measure(engine.as_mut(), 0, 50_000_000, &mut sequences[i], cancel, deadline,
                &mut Sample { round: 0, bytes: 0, elapsed_ns: 0, correct: false }) {
                report.lock().unwrap().algorithms[i].message = error.0; engines[i] = None;
            }
        } else { report.lock().unwrap().algorithms[i].message = "No validated authenticated-decryption adapter is available."; }
    }
    for round in 0..5 {
        for offset in 0..names.len() {
            let i = (offset + round as usize) % names.len();
            guard(cancel, deadline)?;
            report.lock().unwrap().current_algorithm = names[i].clone();
            if let Some(engine) = engines[i].as_mut() {
                let mut partial = Sample { round, bytes: 0, elapsed_ns: 0, correct: false };
                match measure(engine.as_mut(), round, SAMPLE_NS, &mut sequences[i], cancel, deadline, &mut partial) {
                    Ok(sample) => report.lock().unwrap().algorithms[i].samples.push(sample),
                    Err(error) => {
                        let mut r = report.lock().unwrap(); partial.correct = false;
                        r.algorithms[i].samples.push(partial); r.algorithms[i].message = error.0; engines[i] = None;
                    },
                }
            }
        }
    }
    drop(engines);
    let mut rates = BTreeMap::new();
    {
        let mut r = report.lock().unwrap();
        for a in &mut r.algorithms {
            if let Ok(rate) = throughput(&a.samples) { a.rate = Some(rate); a.message = "Estimated local decryption throughput"; rates.insert(a.name.clone(), rate); }
        }
        r.state = "probing"; r.message = "Testing each server's cipher support without downloading articles.";
    }
    let mut changes = BTreeMap::new();
    let mut common: Option<std::collections::BTreeSet<String>> = None;
    let mut complete = true;
    for (i, server) in snapshot.servers.iter().enumerate() {
        let mut support = BTreeMap::new(); let mut problem = "";
        for (suite_index, suite) in suites.iter().enumerate() {
            guard(cancel, deadline)?;
            { let mut r = report.lock().unwrap(); r.current_server = server.id; r.current_cipher = suite.name.clone(); }
            let probe_deadline = deadline.min(Instant::now() + Duration::from_secs(10));
            let probe = backend.probe(server, suite, cancel, probe_deadline);
            { let mut r = report.lock().unwrap(); r.completed_probes += 1;
                r.servers[i].support[suite_index] = match probe.support { Support::Supported => Some(true), Support::Unsupported => Some(false), Support::Unknown => None }; }
            let unknown = probe.support == Support::Unknown;
            if unknown { problem = probe.message; complete = false; }
            support.insert(suite.name.clone(), probe.support);
            // An inconclusive server cannot receive a choice. Avoid repeating
            // bad logins or broken certificate/network attempts; missing keys
            // stay unknown and never turn into an unsupported-cipher claim.
            if unknown { break; }
        }
        let accepted: std::collections::BTreeSet<_> = support.iter().filter(|(_, s)| **s == Support::Supported).map(|(n, _)| n.clone()).collect();
        common = Some(common.map_or_else(|| accepted.clone(), |previous| previous.intersection(&accepted).cloned().collect()));
        let choice = choose(suites, &rates, &support, &server.cipher);
        let mut r = report.lock().unwrap(); let result = &mut r.servers[i];
        result.outcome = "unchanged";
        match choice {
            Ok(Some(choice)) => {
                result.selected = choice.cipher.clone();
                if choice.cipher == server.cipher { result.message = "Already using the fastest measured supported cipher."; }
                else { changes.insert(server.id, choice.cipher); result.outcome = "ready"; result.message = "Tested; awaiting configuration commit."; }
            },
            Ok(None) => result.message = "No eligible supported cipher was found; existing setting retained.",
            Err(error) => result.message = if problem.is_empty() { error.0 } else { problem },
        }
    }
    guard(cancel, deadline)?;
    {
        let mut r = report.lock().unwrap(); r.common = if complete { Some(common.unwrap_or_default().into_iter().collect()) } else { None };
        r.state = "saving"; r.message = "Saving cipher settings without changing other configuration.";
    }
    let saved = if changes.is_empty() { false } else { backend.commit(snapshot, &changes, cancel)? };
    let mut r = report.lock().unwrap(); r.saved = saved;
    for server in &mut r.servers {
        if server.outcome == "ready" {
            server.outcome = if saved { "saved" } else { "unchanged" };
            server.message = if saved { "Saved; reload required." } else { "Configuration was not changed." };
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn status_escapes_untrusted_names_and_omits_credentials() {
        let report = Report { id: "example".into(), state: "completed", message: "done", saved: false, algorithms: vec![],
            servers: vec![ServerResult { id: 1, name: "quote\"\n<script>".into(), host: "example.invalid".into(), port: 563,
                old: "".into(), selected: "".into(), outcome: "unchanged", message: "", support: vec![Some(true), Some(false), None] }], common: None,
            excluded: vec![], current_algorithm: String::new(), current_server: 0, current_cipher: String::new(), completed_probes: 0, total_probes: 0,
            ciphers: vec!["one".into(), "two".into(), "three".into()] };
        let json = report.json().unwrap();
        assert!(json.contains("quote\\\"\\n<script>"));
        assert!(!json.contains("Password")); assert!(!json.contains("Username"));
        assert!(json.contains("\"CipherSupport\":[true,false,null]"));
    }
    #[test]
    fn unknown_job_ids_do_not_cancel_anything() {
        let service = Service::default();
        assert!(service.cancel("stale").is_err());
        assert!(service.status(Some("stale")).is_err());
        assert!(service.status(None).unwrap().contains("\"State\":\"idle\""));
    }
    #[test]
    fn cancelled_measurement_never_prepares_records() {
        struct Forbidden;
        impl Decryptor for Forbidden {
            fn prepare_batch(&mut self, _: u64, _: u32) -> Result<(), Error> { panic!("cancelled work ran") }
            fn record(&mut self, _: u64) -> Result<u64, Error> { panic!("cancelled work ran") }
        }
        let flag = AtomicBool::new(true);
        assert!(measure(&mut Forbidden, 0, SAMPLE_NS, &mut 0, &flag, Instant::now() + Duration::from_secs(1),
            &mut Sample { round: 0, bytes: 0, elapsed_ns: 0, correct: false }).is_err());
    }

    #[test]
    fn duplicate_start_cancel_and_shutdown_share_one_owned_worker() {
        use std::sync::{mpsc, atomic::AtomicUsize};
        struct Fake {
            entered: mpsc::Sender<()>, release: Mutex<mpsc::Receiver<()>>,
            snapshots: AtomicUsize, probes: AtomicUsize, commits: AtomicUsize,
        }
        impl Backend for Fake {
            fn snapshot(&self) -> Result<Snapshot, Error> {
                self.snapshots.fetch_add(1, Ordering::SeqCst);
                Ok(Snapshot { bytes: b"Server1.Host=example.invalid\n".to_vec(), servers: vec![Server {
                    id: 1, name: "Example".into(), host: "example.invalid".into(), port: 563,
                    username: "private-user".into(), password: "private-pass".into(), cipher: "".into(), ip_version: 0, verification: 2,
                }] })
            }
            fn suites(&self) -> Result<Vec<Suite>, Error> {
                Ok(vec![Suite { name: "TLS_AES_128_GCM_SHA256".into(), algorithm: "AES-128-GCM".into(),
                    protocol: Protocol::Tls13, security_bits: 128, aead: true, ephemeral: true, certificate: true }])
            }
            fn prepare(&self, _: &str) -> Result<Box<dyn Decryptor>, Error> {
                self.entered.send(()).unwrap();
                self.release.lock().unwrap().recv_timeout(Duration::from_secs(5)).unwrap();
                Err(Error("cancelled synthetic preparation"))
            }
            fn probe(&self, _: &Server, _: &Suite, _: &AtomicBool, _: Instant) -> Probe {
                self.probes.fetch_add(1, Ordering::SeqCst); Probe { support: Support::Unknown, message: "unexpected" }
            }
            fn commit(&self, _: &Snapshot, _: &BTreeMap<u32,String>, _: &AtomicBool) -> Result<bool, Error> {
                self.commits.fetch_add(1, Ordering::SeqCst); Ok(false)
            }
        }
        let (entered_tx, entered_rx) = mpsc::channel(); let (release_tx, release_rx) = mpsc::channel();
        let backend = Arc::new(Fake { entered: entered_tx, release: Mutex::new(release_rx),
            snapshots: AtomicUsize::new(0), probes: AtomicUsize::new(0), commits: AtomicUsize::new(0) });
        let service = Service::default(); let id = service.start(backend.clone()).unwrap();
        let entered = entered_rx.recv_timeout(Duration::from_secs(5));
        if entered.is_err() { let _ = release_tx.send(()); service.shutdown(); panic!("worker preparation was not reached"); }
        assert_eq!(service.start(backend.clone()).unwrap(), id);
        assert_eq!(backend.snapshots.load(Ordering::SeqCst), 1);
        let status = service.status(Some(&id)).unwrap();
        assert!(!status.contains("private-pass")); assert!(!status.contains("private-user"));
        service.cancel(&id).unwrap(); release_tx.send(()).unwrap(); service.shutdown();
        assert_eq!(backend.probes.load(Ordering::SeqCst), 0);
        assert_eq!(backend.commits.load(Ordering::SeqCst), 0);
        assert!(service.status(Some(&id)).is_err());
    }

    // Added after the report-retention correction was authored. These use only
    // the pre-existing Backend/Service API: the old report implementation can
    // compile them and fails the serialized-behavior assertions below.
    struct CompatibilityBackend {
        gate: Option<(std::sync::mpsc::Sender<()>, Mutex<std::sync::mpsc::Receiver<()>>)>,
        large: usize,
    }
    struct SyntheticRecords;
    impl Decryptor for SyntheticRecords {
        fn prepare_batch(&mut self, _: u64, _: u32) -> Result<(), Error> { Ok(()) }
        fn record(&mut self, sequence: u64) -> Result<u64, Error> {
            // Test-only elapsed time, never a crypto or performance result.
            if sequence % 64 == 0 { thread::sleep(Duration::from_millis(1)); }
            Ok(RECORD_BYTES)
        }
    }
    impl Backend for CompatibilityBackend {
        fn snapshot(&self) -> Result<Snapshot, Error> {
            let count = if self.large == 0 { 2 } else { self.large };
            Ok(Snapshot { bytes: b"owned synthetic snapshot".to_vec(), servers: (1..=count).map(|id| Server {
                id: id as u32, name: "Example \"name\"\n<script>".into(), host: "example.invalid".into(), port: 563,
                username: "PRIVATE_TEST_USERNAME".into(), password: "PRIVATE_TEST_PASSWORD".into(),
                cipher: "a".repeat(if self.large == 256 { 4096 } else if self.large > 0 { 2048 } else { 0 }),
                ip_version: 0, verification: 2,
            }).collect() })
        }
        fn suites(&self) -> Result<Vec<Suite>, Error> {
            Ok(["A", "B", "C", "D"].into_iter().map(|name| Suite { name: name.into(), algorithm: "synthetic".into(),
                protocol: Protocol::Tls13, security_bits: 128, aead: true, certificate: true, ephemeral: true }).collect())
        }
        fn prepare(&self, _: &str) -> Result<Box<dyn Decryptor>, Error> { Ok(Box::new(SyntheticRecords)) }
        fn probe(&self, server: &Server, suite: &Suite, _: &AtomicBool, _: Instant) -> Probe {
            if server.id == 2 && suite.name == "A" {
                if let Some((entered, release)) = &self.gate {
                    entered.send(()).unwrap();
                    release.lock().unwrap().recv_timeout(Duration::from_secs(3)).unwrap();
                }
            }
            Probe { support: match (server.id, suite.name.as_str()) {
                (1, "A") | (2, "B") => Support::Supported, (1, "C") => Support::Unknown, _ => Support::Unsupported,
            }, message: "Synthetic compatibility observation" }
        }
        fn commit(&self, _: &Snapshot, changes: &BTreeMap<u32, String>, _: &AtomicBool) -> Result<bool, Error> {
            assert_eq!(*changes, BTreeMap::from([(2, "B".into())])); Ok(true)
        }
    }
    fn compatibility_report_assertions(report: &str) {
        assert!(report.contains("\"CipherSuites\":[\"A\",\"B\",\"C\",\"D\"]"));
        assert!(report.contains("\"CipherSupport\":[true,false,null,null]"), "Earlier observations were discarded: {report}");
        assert!(report.contains("\"CommonSupported\":null"));
        assert!(!report.contains("PRIVATE_TEST_"));
        assert!(report.contains("Example \\\"name\\\"\\n<script>"));
        assert!(report.len() <= 1024 * 1024 && report.starts_with('{') && report.ends_with('}'));
    }
    #[test]
    fn compatibility_observations_survive_unknown_and_other_server_commit() {
        let service = Service::default();
        let id = service.start(Arc::new(CompatibilityBackend { gate: None, large: 0 })).unwrap();
        let end = Instant::now() + Duration::from_secs(4);
        let report = loop {
            let report = service.status(Some(&id)).unwrap();
            if report.contains("\"State\":\"completed\"") { break report; }
            if Instant::now() >= end { service.shutdown(); panic!("synthetic job did not complete"); }
            thread::sleep(Duration::from_millis(5));
        };
        compatibility_report_assertions(&report);
        assert!(report.contains("\"CipherSupport\":[false,true,false,false]"));
        assert!(report.contains("\"Saved\":true"));
        assert!(report.contains("\"SelectedCipher\":\"B\",\"Outcome\":\"saved\""));
        assert_eq!(service.status(Some(&id)).unwrap(), report, "Polling mutated terminal observations");
        eprintln!("TLS_COMPATIBILITY_REPORT {report}");
        service.shutdown();
    }
    #[test]
    fn cancellation_retains_completed_compatibility_observations() {
        let (entered_tx, entered_rx) = std::sync::mpsc::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        let service = Service::default();
        let id = service.start(Arc::new(CompatibilityBackend { gate: Some((entered_tx, Mutex::new(release_rx))), large: 0 })).unwrap();
        if entered_rx.recv_timeout(Duration::from_secs(4)).is_err() {
            let _ = release_tx.send(()); service.shutdown(); panic!("second provider not reached");
        }
        let before = service.status(Some(&id)).unwrap();
        service.cancel(&id).unwrap(); release_tx.send(()).unwrap();
        let end = Instant::now() + Duration::from_secs(1);
        let report = loop {
            let report = service.status(Some(&id)).unwrap();
            if report.contains("\"State\":\"cancelled\"") { break report; }
            if Instant::now() >= end { service.shutdown(); panic!("synthetic cancellation did not complete"); }
            thread::sleep(Duration::from_millis(5));
        };
        // Both snapshots retain the first provider's earlier known facts.
        compatibility_report_assertions(&before); compatibility_report_assertions(&report);
        assert!(report.contains("\"Saved\":false"));
        eprintln!("TLS_CANCELLED_COMPATIBILITY_REPORT {report}");
        service.shutdown();
    }
    #[test]
    fn admitted_large_status_is_complete_and_oversize_rejects_before_worker() {
        let service = Service::default();
        let id = service.start(Arc::new(CompatibilityBackend { gate: None, large: 128 })).unwrap();
        let report = service.status(Some(&id)).unwrap();
        assert!(report.len() > 256 * 1024 && report.len() <= 1024 * 1024);
        assert!(report.starts_with('{') && report.ends_with('}') && report.contains("\"ID\":128,"));
        assert!(!report.contains("PRIVATE_TEST_"));
        service.cancel(&id).unwrap(); service.shutdown();
        assert!(service.start(Arc::new(CompatibilityBackend { gate: None, large: 256 })).is_err());
        assert!(service.status(None).unwrap().contains("\"State\":\"idle\""));
    }
}
