use crate::Sample;
use reqwest::Url;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

pub const RESPONSE_LIMIT: usize = 1024 * 1024;

pub struct Rpc {
    client: reqwest::blocking::Client,
    url: Url,
    user: String,
    password: String,
}
impl Rpc {
    pub fn new(url: &str, user: String, password: String) -> Result<Self, &'static str> {
        let url = endpoint(url)?;
        if user.is_empty() && !password.is_empty() {
            return Err("password requires a user");
        }
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(3))
            .connect_timeout(std::time::Duration::from_secs(3))
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .build()
            .map_err(|_| "HTTP client initialization failed")?;
        Ok(Self {
            client,
            url,
            user,
            password,
        })
    }
    fn call(
        &self,
        method: &str,
        params: serde_json::Value,
        id: u64,
    ) -> Result<serde_json::Value, &'static str> {
        let mut request = self.client.post(self.url.clone()).json(&serde_json::json!({
            "version":"1.1", "id":id, "method":method, "params":params
        }));
        if !self.user.is_empty() {
            request = request.basic_auth(&self.user, Some(&self.password));
        }
        let response = request
            .send()
            .map_err(|_| "RPC transport failed or timed out")?;
        if !response.status().is_success() {
            return Err("RPC HTTP status is not successful");
        }
        let bytes = bounded_read(response, RESPONSE_LIMIT)?;
        let envelope: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| "RPC JSON is invalid")?;
        if envelope["id"].as_u64() != Some(id)
            || envelope.get("error").is_some_and(|e| !e.is_null())
        {
            return Err("RPC error or response ID mismatch");
        }
        envelope
            .get("result")
            .cloned()
            .ok_or("RPC result is missing")
    }
    pub fn snapshot(&self, elapsed: u64) -> Result<Sample, &'static str> {
        let status = self.call("status", serde_json::json!([]), 1)?;
        let groups = self.call("listgroups", serde_json::json!([0]), 2)?;
        crate::normalize(&status, &groups, elapsed)
    }
}

pub fn endpoint(s: &str) -> Result<Url, &'static str> {
    let u = Url::parse(s).map_err(|_| "invalid RPC endpoint")?;
    let loopback = u
        .host_str()
        .and_then(|h| {
            h.trim_start_matches('[')
                .trim_end_matches(']')
                .parse::<std::net::IpAddr>()
                .ok()
        })
        .is_some_and(|ip| ip.is_loopback());
    if !(u.scheme() == "https" || (u.scheme() == "http" && loopback))
        || !u.username().is_empty()
        || u.password().is_some()
        || u.query().is_some()
        || u.fragment().is_some()
        || u.path() != "/jsonrpc"
        || u.host().is_none()
    {
        return Err("use credential-free HTTPS or literal loopback HTTP /jsonrpc endpoint");
    }
    Ok(u)
}
pub fn bounded_read(r: impl Read, limit: usize) -> Result<Vec<u8>, &'static str> {
    let mut bytes = Vec::new();
    r.take(limit.saturating_add(1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "bounded read failed")?;
    if bytes.len() > limit {
        return Err("observation exceeds byte limit");
    }
    Ok(bytes)
}

pub struct Evidence {
    pub directory: PathBuf,
    next: usize,
}
impl Evidence {
    pub fn new(parent: &Path) -> Result<Self, &'static str> {
        if !cfg!(unix) {
            return Err("private evidence directories require a Unix host");
        }
        std::fs::create_dir_all(parent).map_err(|_| "cannot create evidence parent")?;
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "system clock predates Unix epoch")?
            .as_nanos();
        let directory = parent.join(format!("run-{nonce}-{}", std::process::id()));
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder
            .create(&directory)
            .map_err(|_| "cannot create private evidence directory")?;
        Ok(Self { directory, next: 0 })
    }
    pub fn save(&mut self, bytes: &[u8]) -> Result<(), &'static str> {
        if bytes.len() > RESPONSE_LIMIT {
            return Err("evidence exceeds byte limit");
        }
        let pending = self.directory.join("pending.json");
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&pending)
            .map_err(|_| "cannot create pending evidence")?;
        file.write_all(bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| "evidence write failed; partial evidence preserved")?;
        std::fs::rename(
            pending,
            self.directory.join(format!("evidence-{}.json", self.next)),
        )
        .map_err(|_| "evidence rotation failed; pending evidence preserved")?;
        self.next = (self.next + 1) % 8;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn endpoint_rejects_credential_leaks_and_insecure_remote_transport() {
        for good in [
            "http://127.0.0.1:6789/jsonrpc",
            "http://[::1]:6789/jsonrpc",
            "https://host.example/jsonrpc",
        ] {
            assert!(endpoint(good).is_ok());
        }
        for bad in [
            "http://host.example/jsonrpc",
            "https://user:password@host.example/jsonrpc",
            "https://host.example/jsonrpc?token=secret",
            "https://host.example/jsonrpc#secret",
            "file:///jsonrpc",
            "http://localhost:6789/jsonrpc",
            "https://host.example/config",
        ] {
            assert!(endpoint(bad).is_err());
        }
    }

    #[test]
    fn reads_stop_at_the_cap_and_reject_truncation_instead_of_parsing_it() {
        assert_eq!(bounded_read(&b"abcd"[..], 4).unwrap(), b"abcd");
        assert!(bounded_read(&b"abcde"[..], 4).is_err());
        assert!(bounded_read(std::io::repeat(0), 4).is_err());
    }

    #[test]
    fn evidence_rotation_is_private_bounded_and_keeps_existing_parent_files() {
        let parent =
            std::env::temp_dir().join(format!("observe-evidence-test-{}", std::process::id()));
        std::fs::create_dir_all(&parent).unwrap();
        std::fs::write(parent.join("keep"), b"original").unwrap();
        let mut e = Evidence::new(&parent).unwrap();
        for i in 0..10 {
            e.save(format!("sample{i}").as_bytes()).unwrap();
        }
        assert_eq!(std::fs::read_dir(&e.directory).unwrap().count(), 8);
        assert_eq!(
            std::fs::read(e.directory.join("evidence-0.json")).unwrap(),
            b"sample8"
        );
        assert!(e.save(&vec![0; RESPONSE_LIMIT + 1]).is_err());
        assert_eq!(std::fs::read(parent.join("keep")).unwrap(), b"original");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&e.directory)
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o700
            );
            assert_eq!(
                std::fs::metadata(e.directory.join("evidence-0.json"))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
        std::fs::remove_dir_all(parent).unwrap();
    }
}
