use nzbget_observe::runtime::Rpc;
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};
const FIXTURE_BUDGET: Duration = Duration::from_secs(25);

fn remaining(deadline: Instant) -> std::io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::TimedOut, "fixture deadline expired")
        })
}

fn accept_before(listener: &TcpListener, deadline: Instant) -> std::io::Result<TcpStream> {
    listener.set_nonblocking(true)?;
    loop {
        remaining(deadline)?;
        match listener.accept() {
            Ok((stream, _)) => {
                stream.set_nonblocking(false)?;
                let budget = remaining(deadline)?;
                stream.set_read_timeout(Some(budget))?;
                stream.set_write_timeout(Some(budget))?;
                return Ok(stream);
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(2))
            }
            Err(e) => return Err(e),
        }
    }
}

struct OwnedChild(Option<std::process::Child>);
impl std::ops::Deref for OwnedChild {
    type Target = std::process::Child;
    fn deref(&self) -> &Self::Target {
        self.0.as_ref().unwrap()
    }
}
impl std::ops::DerefMut for OwnedChild {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.0.as_mut().unwrap()
    }
}
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if let Some(child) = self.0.as_mut() {
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

fn output_before(
    child: std::process::Child,
    deadline: Instant,
) -> std::io::Result<std::process::Output> {
    output_owned_before(OwnedChild(Some(child)), deadline)
}
fn output_owned_before(
    mut child: OwnedChild,
    deadline: Instant,
) -> std::io::Result<std::process::Output> {
    loop {
        if child.try_wait()?.is_some() {
            return child.0.take().unwrap().wait_with_output();
        }
        remaining(deadline)?; // timeout drops the guard, killing and reaping.
        std::thread::sleep(Duration::from_millis(2));
    }
}
fn join_before<T>(server: std::thread::JoinHandle<T>, deadline: Instant) -> std::io::Result<T> {
    // Server I/O uses the same deadline. Allow bounded scheduling/cleanup grace
    // before joining only an already-finished thread.
    while !server.is_finished() {
        remaining(deadline + Duration::from_secs(1))?;
        std::thread::sleep(Duration::from_millis(2));
    }
    server
        .join()
        .map_err(|_| std::io::Error::other("fixture server panicked"))
}

fn first_line_before(
    child: &mut OwnedChild,
    deadline: Instant,
) -> std::io::Result<(String, std::io::BufReader<std::process::ChildStdout>)> {
    use std::io::BufRead;
    let stdout = child.stdout.take().unwrap();
    let (sender, receiver) = std::sync::mpsc::channel();
    let reader = std::thread::spawn(move || {
        let mut reader = std::io::BufReader::new(stdout);
        let mut line = String::new();
        let result = reader.read_line(&mut line).and_then(|n| {
            if n == 0 {
                Err(std::io::Error::new(
                    std::io::ErrorKind::UnexpectedEof,
                    "observer exited without sample",
                ))
            } else {
                Ok((line, reader))
            }
        });
        let _ = sender.send(result);
    });
    match receiver.recv_timeout(remaining(deadline)?) {
        Ok(result) => {
            join_before(reader, deadline)?;
            result
        }
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            join_before(reader, Instant::now() + Duration::from_secs(1))?;
            Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                "sample stdout deadline expired",
            ))
        }
    }
}

#[test]
fn fixture_accept_rejects_a_request_after_its_global_deadline() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    // A bounded late wake lets the old blocking implementation terminate and
    // fail without leaving a stuck test thread behind.
    let wake = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(200));
        TcpStream::connect_timeout(&address, Duration::from_millis(200)).unwrap()
    });
    let result = accept_before(&listener, Instant::now() + Duration::from_millis(30));
    drop(join_before(wake, Instant::now() + Duration::from_secs(1)).unwrap());
    assert!(matches!(result, Err(e) if e.kind() == std::io::ErrorKind::TimedOut));
}

#[test]
fn fixture_child_timeout_kills_and_reaps_the_owned_process() {
    let child = std::process::Command::new("sleep")
        .arg("0.25")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let pid = child.id();
    let result = output_before(child, Instant::now() + Duration::from_millis(30));
    assert!(matches!(result, Err(e) if e.kind() == std::io::ErrorKind::TimedOut));
    #[cfg(target_os = "linux")]
    assert!(
        !std::path::Path::new(&format!("/proc/{pid}")).exists(),
        "timed-out child was reaped"
    );
}

// An actual HTTP endpoint proves our request method/params and response projection,
// independently of reqwest's own transport tests.
#[test]
fn read_only_rpc_pair_normalizes_real_http_replies_without_private_job_data() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let deadline = Instant::now() + FIXTURE_BUDGET;
    let client = Rpc::new(&url, "test-user".into(), "test-secret".into()).unwrap();
    let server = std::thread::spawn(move || {
        let mut methods = Vec::new();
        for _ in 0..2 {
            let mut stream = accept_before(&listener, deadline).unwrap();
            let request = read_request(&mut stream, deadline);
            let method = request["method"].as_str().unwrap().to_owned();
            let result = if method == "status" {
                assert_eq!(request["params"], json!([]));
                json!({"UpTimeSec":100,"DownloadPaused":false,"PostPaused":false,"QuotaReached":false})
            } else {
                assert_eq!(method, "listgroups");
                assert_eq!(request["params"], json!([0]));
                json!([{"NZBID":7,"Status":"DOWNLOADING","RemainingSizeHi":0,"RemainingSizeLo":123,
                    "SuccessArticles":2,"FailedArticles":0,"PostStageProgress":0,"MaxPriority":0,"NZBName":"secret release"}])
            };
            methods.push(method);
            let reply = json!({"version":"1.1","id":request["id"],"result":result}).to_string();
            stream
                .set_write_timeout(Some(remaining(deadline).unwrap()))
                .unwrap();
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                reply.len(),
                reply
            )
            .unwrap();
        }
        methods
    });
    let sample = client.snapshot(15).unwrap();
    assert_eq!(sample.jobs[0].remaining, 123);
    assert_eq!(sample.elapsed_secs, 15);
    assert!(!serde_json::to_string(&sample).unwrap().contains("secret"));
    assert_eq!(
        join_before(server, deadline).unwrap(),
        ["status", "listgroups"]
    );
}

#[test]
fn finite_cli_observation_failure_exits_nonzero_without_echoing_remote_error_data() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let deadline = Instant::now() + FIXTURE_BUDGET;
    let server = std::thread::spawn(move || {
        let mut stream = accept_before(&listener, deadline).unwrap();
        let body = r#"{"id":1,"error":{"message":"private-password-from-server"}}"#;
        stream
            .set_write_timeout(Some(remaining(deadline).unwrap()))
            .unwrap();
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        )
        .unwrap();
        // Drain the request so closing does not turn this into a TCP reset test.
        stream
            .set_read_timeout(Some(std::time::Duration::from_millis(100)))
            .unwrap();
        let mut request = [0; 4096];
        let _ = stream.read(&mut request);
    });
    let output = std::env::temp_dir().join(format!("observe-cli-error-{}", std::process::id()));
    let result = output_before(
        std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
            .args([
                "--url",
                &url,
                "--samples",
                "1",
                "--output",
                output.to_str().unwrap(),
            ])
            .env_remove("NZBGET_OBSERVE_USER")
            .env_remove("NZBGET_OBSERVE_PASSWORD")
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap(),
        deadline,
    )
    .unwrap();
    join_before(server, deadline).unwrap();
    let stdout = String::from_utf8(result.stdout).unwrap();
    let stderr = String::from_utf8(result.stderr).unwrap();
    assert!(!stdout.contains("private-password-from-server"));
    assert!(!stderr.contains("private-password-from-server"));
    assert!(stdout.contains("observation_unknown"));
    assert!(!result.status.success());
    std::fs::remove_dir_all(output).unwrap();
}

fn read_request(stream: &mut std::net::TcpStream, deadline: Instant) -> Value {
    let mut header = Vec::new();
    while !header.ends_with(b"\r\n\r\n") {
        stream
            .set_read_timeout(Some(remaining(deadline).unwrap()))
            .unwrap();
        let mut byte = [0];
        stream.read_exact(&mut byte).unwrap();
        header.push(byte[0]);
        assert!(header.len() < 8192);
    }
    let header = String::from_utf8(header).unwrap();
    assert!(header.starts_with("POST /jsonrpc HTTP/1.1"));
    let length: usize = header
        .lines()
        .find_map(|l| {
            l.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(|n| n.trim().parse().unwrap())
        })
        .unwrap();
    assert!(length < 8192);
    let mut body = vec![0; length];
    let mut filled = 0;
    while filled < body.len() {
        stream
            .set_read_timeout(Some(remaining(deadline).unwrap()))
            .unwrap();
        let n = stream.read(&mut body[filled..]).unwrap();
        assert!(n > 0, "request body ended early");
        filled += n;
    }
    serde_json::from_slice(&body).unwrap()
}

fn evidence_files(output: &std::path::Path) -> Vec<std::path::PathBuf> {
    std::fs::read_dir(output)
        .unwrap()
        .flat_map(|run| {
            std::fs::read_dir(run.unwrap().path())
                .unwrap()
                .map(|f| f.unwrap().path())
                .collect::<Vec<_>>()
        })
        .filter(|p| {
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("evidence-")
        })
        .collect()
}

#[test]
fn malformed_rpc_preserves_bounded_failure_metadata_without_private_response_bytes() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let deadline = Instant::now() + FIXTURE_BUDGET;
    let server = std::thread::spawn(move || {
        let mut stream = accept_before(&listener, deadline).unwrap();
        let request = read_request(&mut stream, deadline);
        assert_eq!(request["method"], "status");
        let body = r#"{"private":"secret-response-marker""#;
        stream
            .set_write_timeout(Some(remaining(deadline).unwrap()))
            .unwrap();
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        )
        .unwrap();
    });
    let output =
        std::env::temp_dir().join(format!("observe-invalid-metadata-{}", std::process::id()));
    let result = output_before(
        std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
            .args([
                "--url",
                &url,
                "--samples",
                "1",
                "--output",
                output.to_str().unwrap(),
            ])
            .env_remove("NZBGET_OBSERVE_USER")
            .env_remove("NZBGET_OBSERVE_PASSWORD")
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap(),
        deadline,
    )
    .unwrap();
    join_before(server, deadline).unwrap();
    assert!(!result.status.success());
    let files = evidence_files(&output);
    assert_eq!(
        files.len(),
        1,
        "failure must have private bounded metadata evidence"
    );
    let bytes = std::fs::read(&files[0]).unwrap();
    let record: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(record["event"], "observation_failure");
    assert_eq!(record["metadata"]["method"], "status");
    assert_eq!(record["metadata"]["request_id"], 1);
    assert_eq!(record["metadata"]["response_bytes"], 35);
    assert_eq!(
        record["metadata"]["response_sha256"],
        "9ef5fe054a9e8011f5f1f0c3e9440c9d06633eee5388ed8f409d8cefa3f94fe8"
    );
    assert_eq!(record["metadata"]["parse_category"], "eof");
    assert_eq!(record["metadata"]["line"], 1);
    for data in [&result.stdout, &result.stderr, &bytes] {
        assert!(!String::from_utf8_lossy(data).contains("secret-response-marker"));
    }
    assert!(bytes.len() < 1024);
    std::fs::remove_dir_all(output).unwrap();
}

#[test]
fn closed_stdout_cannot_discard_an_already_detected_alert_capture() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let deadline = Instant::now() + FIXTURE_BUDGET;
    let started = std::time::Instant::now();
    let server = std::thread::spawn(move || {
        for index in 0..4 {
            let mut stream = accept_before(&listener, deadline).unwrap();
            let request = read_request(&mut stream, deadline);
            let result = if index % 2 == 0 {
                assert_eq!(request["method"], "status");
                json!({"UpTimeSec":100+started.elapsed().as_secs(),"DownloadPaused":false,"PostPaused":false,"QuotaReached":false})
            } else {
                assert_eq!(request["method"], "listgroups");
                json!([{"NZBID":7,"Status":"DOWNLOADING","RemainingSizeHi":0,"RemainingSizeLo":123,
                    "SuccessArticles":2,"FailedArticles":0,"PostStageProgress":0,"MaxPriority":0}])
            };
            let body = json!({"id":request["id"],"result":result}).to_string();
            stream
                .set_write_timeout(Some(remaining(deadline).unwrap()))
                .unwrap();
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        }
    });
    let output =
        std::env::temp_dir().join(format!("observe-stdout-failure-{}", std::process::id()));
    let mut child = OwnedChild(Some(
        std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
            .args([
                "--url",
                &url,
                "--samples",
                "2",
                "--interval",
                "10",
                "--stall-seconds",
                "10",
                "--output",
                output.to_str().unwrap(),
            ])
            .env_remove("NZBGET_OBSERVE_USER")
            .env_remove("NZBGET_OBSERVE_PASSWORD")
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap(),
    ));
    let (first, reader) = first_line_before(&mut child, deadline).unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&first).unwrap()["event"],
        "sample"
    );
    drop(reader);
    let result = output_owned_before(child, deadline).unwrap();
    join_before(server, deadline).unwrap();
    assert!(!result.status.success());
    let files = evidence_files(&output);
    assert_eq!(
        files.len(),
        1,
        "computed alert must survive a closed stdout pipe"
    );
    let record: Value = serde_json::from_slice(&std::fs::read(&files[0]).unwrap()).unwrap();
    assert_eq!(record["event"], "symptom");
    assert_eq!(record["alerts"][0]["job_id"], 7);
    assert_eq!(record["window"].as_array().unwrap().len(), 2);
    assert_eq!(record["observer"]["version"], "0.1.0");
    let hash = record["observer"]["executable_sha256"]
        .as_str()
        .expect("executed observer identity");
    assert_eq!(hash.len(), 64);
    assert!(hash.bytes().all(|b| b.is_ascii_hexdigit()));
    let executable = std::fs::read(env!("CARGO_BIN_EXE_nzbget-observe")).unwrap();
    let expected = ring::digest::digest(&ring::digest::SHA256, &executable);
    let expected_hex: String = expected
        .as_ref()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    assert_eq!(
        hash, expected_hex,
        "identity binds the actual CLI executable"
    );
    assert_eq!(record["observer"]["sampling"]["interval_secs"], 10);
    assert_eq!(record["observer"]["sampling"]["stall_secs"], 10);
    assert_eq!(record["observer"]["sampling"]["samples"], 2);
    assert_eq!(record["observer"]["limits"]["response_bytes"], 1024 * 1024);
    std::fs::remove_dir_all(output).unwrap();
}

fn failed_reply_capture(status: u16, body: String, label: &str) -> (Value, std::process::Output) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let deadline = Instant::now() + FIXTURE_BUDGET;
    let server = std::thread::spawn(move || {
        let mut stream = accept_before(&listener, deadline).unwrap();
        let request = read_request(&mut stream, deadline);
        assert_eq!(request["method"], "status");
        stream
            .set_write_timeout(Some(remaining(deadline).unwrap()))
            .unwrap();
        write!(
            stream,
            "HTTP/1.1 {status} Failure\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        )
        .unwrap();
    });
    let output = std::env::temp_dir().join(format!("observe-reply-{label}-{}", std::process::id()));
    let result = output_before(
        std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
            .args([
                "--url",
                &url,
                "--samples",
                "1",
                "--output",
                output.to_str().unwrap(),
            ])
            .env_remove("NZBGET_OBSERVE_USER")
            .env_remove("NZBGET_OBSERVE_PASSWORD")
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap(),
        deadline,
    )
    .unwrap();
    join_before(server, deadline).unwrap();
    assert!(!result.status.success());
    let files = evidence_files(&output);
    assert_eq!(
        files.len(),
        1,
        "failed reply requires bounded private metadata"
    );
    let bytes = std::fs::read(&files[0]).unwrap();
    assert!(bytes.len() < 2048);
    let record: Value = serde_json::from_slice(&bytes).unwrap();
    for data in [&bytes, &result.stdout, &result.stderr] {
        assert!(!String::from_utf8_lossy(data).contains("secret-failure-payload"));
    }
    std::fs::remove_dir_all(output).unwrap();
    (record, result)
}

#[test]
fn http_error_replies_preserve_status_fingerprints_without_body_secrets() {
    for status in [401, 403, 500] {
        let (record, result) = failed_reply_capture(
            status,
            "secret-failure-payload".into(),
            &format!("http-{status}"),
        );
        assert_eq!(record["metadata"]["method"], "status");
        assert_eq!(record["metadata"]["request_id"], 1);
        assert_eq!(record["metadata"]["http_status"], status);
        assert_eq!(record["metadata"]["failure_category"], "http_error");
        assert_eq!(record["metadata"]["response_bytes"], 22);
        assert_eq!(
            record["metadata"]["response_sha256"]
                .as_str()
                .unwrap()
                .len(),
            64
        );
        assert!(String::from_utf8_lossy(&result.stdout).contains("observation_unknown"));
    }
}

#[test]
fn valid_rpc_error_preserves_metadata_without_private_error_message() {
    let (record, _) = failed_reply_capture(
        200,
        json!({"id":1,"error":{"code":-32000,"message":"secret-failure-payload"}}).to_string(),
        "rpc",
    );
    assert_eq!(record["metadata"]["method"], "status");
    assert_eq!(record["metadata"]["request_id"], 1);
    assert_eq!(record["metadata"]["http_status"], 200);
    assert_eq!(record["metadata"]["failure_category"], "rpc_error");
    assert_eq!(
        record["metadata"]["response_sha256"]
            .as_str()
            .unwrap()
            .len(),
        64
    );
    assert!(record["metadata"].get("message").is_none());
}
