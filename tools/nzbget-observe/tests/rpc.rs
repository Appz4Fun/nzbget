use nzbget_observe::runtime::Rpc;
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::TcpListener;

// An actual HTTP endpoint proves our request method/params and response projection,
// independently of reqwest's own transport tests.
#[test]
fn read_only_rpc_pair_normalizes_real_http_replies_without_private_job_data() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let client = Rpc::new(&url, "test-user".into(), "test-secret".into()).unwrap();
    let server = std::thread::spawn(move || {
        let mut methods = Vec::new();
        for _ in 0..2 {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            let mut header = Vec::new();
            while !header.ends_with(b"\r\n\r\n") {
                let mut b = [0];
                stream.read_exact(&mut b).unwrap();
                header.push(b[0]);
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
            let mut body = vec![0; length];
            stream.read_exact(&mut body).unwrap();
            let request: Value = serde_json::from_slice(&body).unwrap();
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
    assert_eq!(server.join().unwrap(), ["status", "listgroups"]);
}

#[test]
fn finite_cli_observation_failure_exits_nonzero_without_echoing_remote_error_data() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let body = r#"{"id":1,"error":{"message":"private-password-from-server"}}"#;
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
    let result = std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
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
        .output()
        .unwrap();
    server.join().unwrap();
    let stdout = String::from_utf8(result.stdout).unwrap();
    let stderr = String::from_utf8(result.stderr).unwrap();
    assert!(!stdout.contains("private-password-from-server"));
    assert!(!stderr.contains("private-password-from-server"));
    assert!(stdout.contains("observation_unknown"));
    assert!(!result.status.success());
    std::fs::remove_dir_all(output).unwrap();
}

fn read_request(stream: &mut std::net::TcpStream) -> Value {
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(20)))
        .unwrap();
    let mut header = Vec::new();
    while !header.ends_with(b"\r\n\r\n") {
        let mut byte = [0];
        stream.read_exact(&mut byte).unwrap();
        header.push(byte[0]);
        assert!(header.len() < 8192);
    }
    let header = String::from_utf8(header).unwrap();
    let length: usize = header
        .lines()
        .find_map(|l| {
            l.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(|n| n.trim().parse().unwrap())
        })
        .unwrap();
    let mut body = vec![0; length];
    stream.read_exact(&mut body).unwrap();
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
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let request = read_request(&mut stream);
        assert_eq!(request["method"], "status");
        let body = r#"{"private":"secret-response-marker""#;
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
    let result = std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
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
        .output()
        .unwrap();
    server.join().unwrap();
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
    use std::io::BufRead;
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/jsonrpc", listener.local_addr().unwrap());
    let started = std::time::Instant::now();
    let server = std::thread::spawn(move || {
        for index in 0..4 {
            let (mut stream, _) = listener.accept().unwrap();
            let request = read_request(&mut stream);
            let result = if index % 2 == 0 {
                assert_eq!(request["method"], "status");
                json!({"UpTimeSec":100+started.elapsed().as_secs(),"DownloadPaused":false,"PostPaused":false,"QuotaReached":false})
            } else {
                assert_eq!(request["method"], "listgroups");
                json!([{"NZBID":7,"Status":"DOWNLOADING","RemainingSizeHi":0,"RemainingSizeLo":123,
                    "SuccessArticles":2,"FailedArticles":0,"PostStageProgress":0,"MaxPriority":0}])
            };
            let body = json!({"id":request["id"],"result":result}).to_string();
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
    let mut child = std::process::Command::new(env!("CARGO_BIN_EXE_nzbget-observe"))
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
        .unwrap();
    let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
    let mut first = String::new();
    reader.read_line(&mut first).unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&first).unwrap()["event"],
        "sample"
    );
    drop(reader);
    let result = child.wait_with_output().unwrap();
    server.join().unwrap();
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
    std::fs::remove_dir_all(output).unwrap();
}
