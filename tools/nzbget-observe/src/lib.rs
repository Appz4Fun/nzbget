use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
pub mod runtime;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Job {
    pub id: u64,
    pub stage: String,
    pub remaining: u64,
    pub success: u64,
    pub failed: u64,
    pub progress: u64,
    pub active: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Sample {
    pub elapsed_secs: u64,
    pub uptime_secs: u64,
    pub jobs: Vec<Job>,
    pub daemon: BTreeMap<String, Option<u64>>,
    pub pauses: BTreeMap<String, bool>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Alert {
    pub job_id: u64,
    pub stage: String,
    pub no_progress_secs: u64,
    pub symptom: &'static str,
    pub next_check: &'static str,
}

#[derive(Default)]
pub struct Detector {
    previous: HashMap<u64, (Job, u64, bool)>,
    uptime: Option<(u64, u64)>,
}

impl Detector {
    pub fn observe(&mut self, sample: &Sample, threshold: u64) -> Vec<Alert> {
        if self.uptime.is_some_and(|(uptime, elapsed)| {
            sample.uptime_secs < uptime
                || sample.elapsed_secs < elapsed
                || sample
                    .elapsed_secs
                    .saturating_sub(elapsed)
                    .saturating_sub(sample.uptime_secs.saturating_sub(uptime))
                    > 10
        }) {
            self.reset();
        }
        self.uptime = Some((sample.uptime_secs, sample.elapsed_secs));
        self.previous
            .retain(|id, _| sample.jobs.iter().any(|j| j.id == *id));
        let mut alerts = Vec::new();
        for job in &sample.jobs {
            if !job.active {
                self.previous.remove(&job.id);
                continue;
            }
            let entry =
                self.previous
                    .entry(job.id)
                    .or_insert((job.clone(), sample.elapsed_secs, false));
            let previous = &entry.0;
            if job.stage != previous.stage
                || job.remaining != previous.remaining
                || job.success != previous.success
                || job.failed != previous.failed
                || job.progress != previous.progress
                || sample.elapsed_secs < entry.1
            {
                *entry = (job.clone(), sample.elapsed_secs, false);
            }
            let age = sample.elapsed_secs.saturating_sub(entry.1);
            if age >= threshold && !entry.2 {
                alerts.push(Alert {
                    job_id: job.id, stage: job.stage.clone(), no_progress_secs: age,
                    symptom: "observed_progress_unchanged",
                    next_check: match job.stage.as_str() {
                        "DOWNLOADING" | "FETCHING" => "Compare provider/socket waiting, decoder CPU and writer/cache progress.",
                        "UNPACKING" | "MOVING" => "Check child-process progress and storage I/O deltas.",
                        "LOADING_PARS" | "VERIFYING_SOURCES" | "VERIFYING_REPAIRED" | "REPAIRING" | "STREAM_REPAIRING" =>
                            "Separate hash/scan CPU, storage waits and recovery arithmetic; verify actual backend and repair geometry.",
                        _ => "Inspect the active stage's work and waits; unchanged progress does not prove a hang.",
                    },
                });
                entry.2 = true;
            }
        }
        alerts
    }
    pub fn reset(&mut self) {
        self.previous.clear();
        self.uptime = None;
    }
}

pub fn normalize(status: &Value, groups: &Value, elapsed: u64) -> Result<Sample, &'static str> {
    let number = |v: &Value, k: &str| v[k].as_u64().ok_or("missing or invalid numeric RPC field");
    let flag = |k: &str| {
        status[k]
            .as_bool()
            .ok_or("missing or invalid pause RPC field")
    };
    let uptime_secs = number(status, "UpTimeSec")?;
    let download_paused = flag("DownloadPaused")?;
    let post_paused = flag("PostPaused")?;
    let quota = flag("QuotaReached")?;
    let groups = groups.as_array().ok_or("invalid groups RPC shape")?;
    if groups.len() > 128 {
        return Err("queue exceeds 128-job observation limit");
    }
    let mut jobs = Vec::with_capacity(groups.len());
    for g in groups {
        let id = number(g, "NZBID")?;
        if id == 0 || jobs.iter().any(|j: &Job| j.id == id) {
            return Err("invalid or duplicate job ID");
        }
        let hi = u32::try_from(number(g, "RemainingSizeHi")?).map_err(|_| "invalid size word")?;
        let lo = u32::try_from(number(g, "RemainingSizeLo")?).map_err(|_| "invalid size word")?;
        let stage = g["Status"].as_str().ok_or("missing job stage")?;
        // listgroups exports NzbInfo::GetPriority as MaxPriority. The daemon's
        // GetForcePriority threshold is 900; URL fetching instead uses UrlForce.
        let force_priority = g["MaxPriority"]
            .as_i64()
            .and_then(|p| i32::try_from(p).ok())
            .ok_or("missing or invalid priority RPC field")?
            >= 900;
        let download = matches!(stage, "DOWNLOADING" | "FETCHING");
        let post = matches!(
            stage,
            "LOADING_PARS"
                | "VERIFYING_SOURCES"
                | "VERIFYING_REPAIRED"
                | "REPAIRING"
                | "STREAM_REPAIRING"
                | "UNPACKING"
                | "MOVING"
                | "RENAMING"
                | "POST_UNPACK_RENAMING"
                | "POST_DOWNLOAD_RENAMING"
                | "EXECUTING_SCRIPT"
                | "QS_EXECUTING"
        );
        let inactive = matches!(
            stage,
            "QUEUED" | "PP_QUEUED" | "QS_QUEUED" | "PAUSED" | "PP_FINISHED"
        );
        jobs.push(Job {
            id,
            stage: if download || post || inactive {
                stage.into()
            } else {
                "UNKNOWN".into()
            },
            remaining: (u64::from(hi) << 32) | u64::from(lo),
            success: number(g, "SuccessArticles")?,
            failed: number(g, "FailedArticles")?,
            progress: number(g, "PostStageProgress")?,
            active: (download
                && ((!download_paused && !quota) || (stage == "DOWNLOADING" && force_priority)))
                || (post && (!post_paused || force_priority)),
        });
    }
    let daemon = [
        "ArticleCache",
        "DownloadRate",
        "DownloadedSize",
        "FreeDiskSpace",
    ]
    .into_iter()
    .map(|name| {
        let value = status[format!("{name}Hi")]
            .as_u64()
            .and_then(|hi| u32::try_from(hi).ok())
            .zip(
                status[format!("{name}Lo")]
                    .as_u64()
                    .and_then(|lo| u32::try_from(lo).ok()),
            )
            .map(|(hi, lo)| (u64::from(hi) << 32) | u64::from(lo));
        (name.into(), value)
    })
    .collect();
    Ok(Sample {
        elapsed_secs: elapsed,
        uptime_secs,
        jobs,
        daemon,
        pauses: [
            ("download".into(), download_paused),
            ("post".into(), post_paused),
            ("quota".into(), quota),
        ]
        .into_iter()
        .collect(),
    })
}

pub fn pressure(text: &str) -> Option<f64> {
    let line = text.lines().find(|s| s.starts_with("some "))?;
    let n: f64 = line
        .split_whitespace()
        .find_map(|s| s.strip_prefix("avg10="))?
        .parse()
        .ok()?;
    (n.is_finite() && (0.0..=100.0).contains(&n)).then_some(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample(t: u64) -> Sample {
        Sample {
            elapsed_secs: t,
            uptime_secs: 100 + t,
            daemon: BTreeMap::new(),
            pauses: BTreeMap::new(),
            jobs: vec![Job {
                id: 7,
                stage: "DOWNLOADING".into(),
                remaining: 1000,
                success: 2,
                failed: 0,
                progress: 0,
                active: true,
            }],
        }
    }

    // Removing per-job state must expose a stall even while a different job progresses.
    #[test]
    fn unrelated_progress_cannot_hide_a_stalled_job_and_alerts_deduplicate() {
        let mut d = Detector::default();
        assert!(d.observe(&sample(0), 60).is_empty());
        let mut s = sample(59);
        let mut other = s.jobs[0].clone();
        other.id = 8;
        other.remaining = 900;
        s.jobs.push(other);
        assert!(d.observe(&s, 60).is_empty());
        s.elapsed_secs = 60;
        s.uptime_secs = 160;
        s.jobs[1].remaining = 800;
        let alerts = d.observe(&s, 60);
        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].job_id, 7);
        assert_eq!(alerts[0].no_progress_secs, 60);
        s.elapsed_secs = 120;
        s.uptime_secs = 220;
        s.jobs[1].remaining = 700;
        assert!(d.observe(&s, 60).is_empty());
    }

    #[test]
    fn pause_and_resume_start_a_new_observation_window() {
        let mut d = Detector::default();
        d.observe(&sample(0), 60);
        let mut s = sample(60);
        s.jobs[0].active = false;
        assert!(d.observe(&s, 60).is_empty());
        assert!(d.observe(&sample(120), 60).is_empty());
        assert_eq!(d.observe(&sample(180), 60).len(), 1);
    }

    #[test]
    fn stage_changes_counters_and_daemon_restart_reset_the_window() {
        let mut d = Detector::default();
        d.observe(&sample(0), 60);
        let mut s = sample(60);
        s.jobs[0].success += 1;
        assert!(d.observe(&s, 60).is_empty());
        s.elapsed_secs = 120;
        s.uptime_secs = 220;
        s.jobs[0].stage = "UNPACKING".into();
        assert!(d.observe(&s, 60).is_empty());
        s.elapsed_secs = 180;
        s.uptime_secs = 1;
        assert!(d.observe(&s, 60).is_empty());
        s.elapsed_secs = 240;
        s.uptime_secs = 61;
        assert_eq!(d.observe(&s, 60).len(), 1);
    }

    #[test]
    fn restart_between_samples_resets_even_when_new_uptime_exceeds_old_uptime() {
        let mut d = Detector::default();
        let mut s = sample(0);
        s.uptime_secs = 10;
        d.observe(&s, 60);
        s.elapsed_secs = 120;
        s.uptime_secs = 30;
        assert!(d.observe(&s, 60).is_empty());
    }

    fn status() -> Value {
        json!({"UpTimeSec":100,"DownloadPaused":false,"PostPaused":false,"QuotaReached":false})
    }
    fn group() -> Value {
        json!({"NZBID":7,"Status":"DOWNLOADING","RemainingSizeHi":1,"RemainingSizeLo":3,
            "SuccessArticles":2,"FailedArticles":0,"PostStageProgress":0,"MaxPriority":0,
            "NZBName":"private release","DestDir":"/private/media","Password":"secret"})
    }

    #[test]
    fn normalization_preserves_large_counters_and_drops_private_fields() {
        let s = normalize(&status(), &json!([group()]), 0).unwrap();
        assert_eq!(s.jobs[0].remaining, 4_294_967_299);
        let out = serde_json::to_string(&s).unwrap();
        for private in [
            "private release",
            "/private/media",
            "secret",
            "Password",
            "DestDir",
        ] {
            assert!(!out.contains(private));
        }
    }

    #[test]
    fn queued_paused_and_unknown_stages_are_not_stalls() {
        for stage in ["QUEUED", "PP_QUEUED", "PAUSED", "PP_FINISHED", "NEW_STAGE"] {
            let mut g = group();
            g["Status"] = json!(stage);
            assert!(!normalize(&status(), &json!([g]), 0).unwrap().jobs[0].active);
        }
        let mut st = status();
        st["DownloadPaused"] = json!(true);
        assert!(!normalize(&st, &json!([group()]), 0).unwrap().jobs[0].active);
    }

    // Canonical daemon contracts: NzbInfo::GetForcePriority uses >=900;
    // QueueCoordinator and PrePostProcessor bypass global pauses for force work.
    // These literal expectations exercise normalization AND the real detector.
    #[test]
    fn force_priority_stalls_survive_global_pause_and_quota() {
        let cases = [
            ("DOWNLOADING", 899, true, false, false, 0),
            ("DOWNLOADING", 900, true, false, false, 1),
            ("DOWNLOADING", 901, false, true, false, 1),
            ("DOWNLOADING", 900, true, true, false, 1),
            ("DOWNLOADING", -100, false, true, false, 0),
            ("DOWNLOADING", -100, false, false, false, 1),
            ("UNPACKING", 899, false, false, true, 0),
            ("UNPACKING", 900, false, false, true, 1),
            ("REPAIRING", 901, true, true, true, 1),
            ("QUEUED", 900, true, true, true, 0),
            ("PP_QUEUED", 900, true, true, true, 0),
            ("PAUSED", 900, true, true, true, 0),
            ("PP_FINISHED", 900, true, true, true, 0),
            ("NEW_STAGE", 900, true, true, true, 0),
            // URL downloads use UrlForce, not NzbInfo's force priority.
            ("FETCHING", 900, true, false, false, 0),
        ];
        for (stage, priority, download_pause, quota, post_pause, count) in cases {
            let mut st = status();
            let mut g = group();
            g["Status"] = json!(stage);
            g["MaxPriority"] = json!(priority);
            let mut detector = Detector::default();
            assert!(detector
                .observe(&normalize(&st, &json!([g.clone()]), 0).unwrap(), 60)
                .is_empty());
            st["DownloadPaused"] = json!(download_pause);
            st["QuotaReached"] = json!(quota);
            st["PostPaused"] = json!(post_pause);
            st["UpTimeSec"] = json!(160);
            let paused = normalize(&st, &json!([g.clone()]), 60).unwrap();
            let alerts = detector.observe(&paused, 60);
            assert_eq!(
                alerts.len(),
                count,
                "{stage} priority {priority}, pauses {download_pause}/{quota}/{post_pause}"
            );
            if count == 1 {
                assert_eq!(alerts[0].job_id, 7);
                assert_eq!(alerts[0].no_progress_secs, 60);
            }
            st["UpTimeSec"] = json!(220);
            assert!(detector
                .observe(&normalize(&st, &json!([g]), 120).unwrap(), 60)
                .is_empty());
        }
    }

    #[test]
    fn invalid_or_missing_priority_is_unknown_instead_of_suppressing_work() {
        for priority in [
            json!(null),
            json!("900"),
            json!(900.5),
            json!(true),
            json!(2147483648_i64),
            json!(-2147483649_i64),
        ] {
            let mut g = group();
            g["MaxPriority"] = priority;
            assert!(normalize(&status(), &json!([g]), 0).is_err());
        }
        let mut g = group();
        g.as_object_mut().unwrap().remove("MaxPriority");
        assert!(normalize(&status(), &json!([g]), 0).is_err());
    }

    #[test]
    fn malformed_or_incomplete_observation_is_unknown_not_zero() {
        assert!(normalize(&json!({}), &json!([]), 0).is_err());
        let mut g = group();
        g.as_object_mut().unwrap().remove("SuccessArticles");
        assert!(normalize(&status(), &json!([g]), 0).is_err());
        assert!(normalize(&status(), &json!([group(), group()]), 0).is_err());
    }

    #[test]
    fn malformed_pressure_is_unknown() {
        assert_eq!(
            pressure("some avg10=12.50 avg60=2 total=100\nfull avg10=0.0"),
            Some(12.5)
        );
        for s in [
            "",
            "some total=0",
            "some avg10=NaN",
            "some avg10=-1",
            "some avg10=101",
        ] {
            assert_eq!(pressure(s), None);
        }
    }
}
