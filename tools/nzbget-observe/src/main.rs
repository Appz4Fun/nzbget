use nzbget_observe::{
    runtime::{bounded_read, Evidence, Rpc},
    Detector,
};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::path::PathBuf;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

struct Config {
    url: String,
    output: PathBuf,
    interval: u64,
    threshold: u64,
    samples: Option<u64>,
    pid: Option<u32>,
    cgroup: Option<PathBuf>,
}
impl Config {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self, &'static str> {
        let mut config = Self {
            url: "http://127.0.0.1:6789/jsonrpc".into(),
            output: "observe-evidence".into(),
            interval: 15,
            threshold: 300,
            samples: None,
            pid: None,
            cgroup: None,
        };
        while let Some(key) = args.next() {
            let value = args.next().ok_or("each option requires a value")?;
            let number = || value.parse::<u64>().map_err(|_| "invalid option number");
            match key.as_str() {
                "--url" => {
                    nzbget_observe::runtime::endpoint(&value)?;
                    config.url = value;
                }
                "--output" => config.output = value.into(),
                "--interval" => config.interval = number()?,
                "--stall-seconds" => config.threshold = number()?,
                "--samples" => config.samples = Some(number()?),
                "--pid" => config.pid = Some(u32::try_from(number()?).map_err(|_| "invalid PID")?),
                "--cgroup" => {
                    let path = PathBuf::from(value);
                    if path.as_os_str().is_empty()
                        || path
                            .components()
                            .any(|c| !matches!(c, std::path::Component::Normal(_)))
                    {
                        return Err("cgroup must be a relative directory without dot components");
                    }
                    config.cgroup = Some(path);
                }
                _ => return Err("unknown option"),
            }
        }
        if config.interval < 10
            || config.interval > 3600
            || config.threshold < config.interval
            || config.threshold > 86400
            || config.samples == Some(0)
            || config.pid == Some(0)
        {
            return Err("invalid sampling bounds: interval 10..3600, stall interval..86400, nonzero samples/PID");
        }
        Ok(config)
    }
}

fn text(path: impl AsRef<std::path::Path>) -> Option<String> {
    let path = path.as_ref();
    if !std::fs::metadata(path).ok()?.is_file() {
        return None;
    }
    let file = std::fs::File::open(path).ok()?;
    String::from_utf8(bounded_read(file, 8192).ok()?).ok()
}

fn counters(path: impl AsRef<std::path::Path>, allowed: &[&str]) -> Value {
    let Some(text) = text(path) else {
        return Value::Null;
    };
    let mut result = serde_json::Map::new();
    for key in allowed {
        let value = text.lines().find_map(|line| {
            let mut parts = line.split_whitespace();
            (parts.next()?.trim_end_matches(':') == *key)
                .then(|| parts.next()?.parse::<u64>().ok())
                .flatten()
        });
        result.insert((*key).into(), json!(value));
    }
    Value::Object(result)
}

fn linux_observations(config: &Config) -> Value {
    let psi = |base: &std::path::Path| {
        let mut values = serde_json::Map::new();
        for resource in ["cpu", "memory", "io"] {
            let reading = text(base.join(resource)).and_then(|s| nzbget_observe::pressure(&s));
            values.insert(resource.into(), json!(reading));
        }
        Value::Object(values)
    };
    let process = config.pid.map(|pid| {
        let base = PathBuf::from(format!("/proc/{pid}"));
        // Read start time twice; do not combine observations from different PID instances.
        let stat = || {
            text(base.join("stat")).and_then(|s| {
                let (_, fields) = s.rsplit_once(") ")?;
                let f: Vec<_> = fields.split_whitespace().collect();
                Some((
                    f.get(19)?.parse::<u64>().ok()?,
                    json!({
                        "utime_ticks":f.get(11)?.parse::<u64>().ok(),
                        "stime_ticks":f.get(12)?.parse::<u64>().ok(),
                        "rss_pages":f.get(21)?.parse::<i64>().ok(),
                    }),
                ))
            })
        };
        let before = stat();
        let io = counters(
            base.join("io"),
            &[
                "rchar",
                "wchar",
                "read_bytes",
                "write_bytes",
                "cancelled_write_bytes",
            ],
        );
        match (before, stat()) {
            (Some((start, cpu)), Some((end, _))) if start == end => {
                json!({"pid":pid,"start_ticks":start,"cpu":cpu,"io":io})
            }
            _ => Value::Null,
        }
    });
    let cgroup = config.cgroup.as_ref().map(|relative| {
        let base = PathBuf::from("/sys/fs/cgroup").join(relative);
        let mut pressure = serde_json::Map::new();
        for resource in ["cpu", "memory", "io"] {
            pressure.insert(resource.into(), json!(text(base.join(format!("{resource}.pressure")))
                .and_then(|s| nzbget_observe::pressure(&s))));
        }
        json!({"pressure_some_avg10":pressure,
            "cpu":counters(base.join("cpu.stat"), &["usage_usec","user_usec","system_usec","nr_throttled","throttled_usec"]),
            "memory_events":counters(base.join("memory.events"), &["low","high","max","oom","oom_kill"])})
    });
    json!({"scope":"watcher_visible_host; correlate with daemon only when colocated",
        "pressure_some_avg10":psi(std::path::Path::new("/proc/pressure")),"process":process,"cgroup":cgroup})
}

fn emit(value: &Value) -> Result<(), &'static str> {
    use std::io::Write;
    let mut out = std::io::stdout().lock();
    serde_json::to_writer(&mut out, value).map_err(|_| "stdout write failed")?;
    writeln!(out).map_err(|_| "stdout write failed")
}

fn run(config: Config) -> Result<(), &'static str> {
    let user = std::env::var("NZBGET_OBSERVE_USER").unwrap_or_default();
    let password = std::env::var("NZBGET_OBSERVE_PASSWORD").unwrap_or_default();
    let rpc = Rpc::new(&config.url, user, password)?;
    let mut evidence = Evidence::new(&config.output)?;
    let started = Instant::now();
    let mut detector = Detector::default();
    let mut window = VecDeque::with_capacity(20);
    let mut failure = None;
    let mut count = 0u64;
    loop {
        let cycle = Instant::now();
        let observation = rpc.snapshot(started.elapsed().as_secs());
        let collection_ms = cycle.elapsed().as_secs_f64() * 1000.0;
        let unix_secs = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "invalid system clock")?
            .as_secs();
        match observation {
            Ok(sample) => {
                if failure.take().is_some() {
                    emit(&json!({"event":"observation_recovered","unix_secs":unix_secs}))?;
                }
                let alerts = detector.observe(&sample, config.threshold);
                let record = json!({"event":"sample","schema_version":1,"unix_secs":unix_secs,
                    "rpc_collection_ms":collection_ms,"sample":sample,"linux":linux_observations(&config)});
                emit(&record)?;
                if window.len() == 20 {
                    window.pop_front();
                }
                window.push_back(record);
                if !alerts.is_empty() {
                    let capture = json!({"schema_version":1,"event":"symptom","alerts":alerts,"window":window});
                    let bytes =
                        serde_json::to_vec(&capture).map_err(|_| "evidence encoding failed")?;
                    evidence.save(&bytes)?;
                    emit(&json!({"event":"symptom","unix_secs":unix_secs,"alerts":alerts}))?;
                }
            }
            Err(reason) => {
                detector.reset();
                window.clear();
                if failure != Some(reason) {
                    emit(
                        &json!({"event":"observation_unknown","unix_secs":unix_secs,"reason":reason}),
                    )?;
                }
                failure = Some(reason);
            }
        }
        count = count.saturating_add(1);
        if config.samples.is_some_and(|limit| count >= limit) {
            return if failure.is_some() {
                Err("final RPC observation is unknown")
            } else {
                Ok(())
            };
        }
        std::thread::sleep(Duration::from_secs(config.interval).saturating_sub(cycle.elapsed()));
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() == 1 && args[0] == "--help" {
        println!("nzbget-observe [--url URL] [--output DIR] [--interval SECONDS] [--stall-seconds SECONDS] [--samples COUNT] [--pid PID] [--cgroup RELATIVE_DIRECTORY]\nRead-only status/listgroups watcher. Credentials: NZBGET_OBSERVE_USER and NZBGET_OBSERVE_PASSWORD. See tools/nzbget-observe/README.md.");
        return;
    }
    if let Err(reason) = Config::parse(args.into_iter()).and_then(run) {
        eprintln!("nzbget-observe: {reason}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn parse(args: &[&str]) -> Result<Config, &'static str> {
        Config::parse(args.iter().map(|s| (*s).to_owned()))
    }
    #[test]
    fn cli_accepts_bounded_sampling_and_rejects_invalid_or_mutating_options() {
        let c = parse(&[
            "--samples",
            "1",
            "--interval",
            "10",
            "--stall-seconds",
            "60",
            "--pid",
            "7",
            "--cgroup",
            "system.slice/nzbget.service",
        ])
        .unwrap();
        assert_eq!(c.samples, Some(1));
        assert_eq!(c.interval, 10);
        assert_eq!(c.pid, Some(7));
        for args in [
            &["--samples", "0"][..],
            &["--interval", "0"],
            &["--interval", "9"],
            &["--stall-seconds", "0"],
            &["--pid", "0"],
            &["--cgroup", "../other"],
            &["--cgroup", "/absolute"],
            &["--password", "secret"],
            &["--restart", "yes"],
        ] {
            assert!(parse(args).is_err());
        }
    }
}
