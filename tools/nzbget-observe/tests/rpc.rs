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
                    "SuccessArticles":2,"FailedArticles":0,"PostStageProgress":0,"NZBName":"secret release"}])
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
