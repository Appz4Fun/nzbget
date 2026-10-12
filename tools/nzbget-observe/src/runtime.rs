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
    failure_metadata: std::cell::RefCell<Option<serde_json::Value>>,
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
            failure_metadata: std::cell::RefCell::new(None),
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
        let status = response.status();
        let bytes = match bounded_read(response, RESPONSE_LIMIT) {
            Ok(bytes) => bytes,
            Err(reason) => {
                self.record_failure(method, id, status.as_u16(), "body_unavailable", None);
                return Err(reason);
            }
        };
        if !status.is_success() {
            self.record_failure(method, id, status.as_u16(), "http_error", Some(&bytes));
            return Err("RPC HTTP status is not successful");
        }
        let envelope: serde_json::Value = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(error) => {
                // Malformed JSON cannot be reliably redacted. Retain only a
                // bounded fingerprint and parser location, never its payload.
                let category = match error.classify() {
                    serde_json::error::Category::Io => "io",
                    serde_json::error::Category::Syntax => "syntax",
                    serde_json::error::Category::Data => "data",
                    serde_json::error::Category::Eof => "eof",
                };
                self.record_failure(method, id, status.as_u16(), "invalid_json", Some(&bytes));
                if let Some(metadata) = self.failure_metadata.borrow_mut().as_mut() {
                    metadata["parse_category"] = category.into();
                    metadata["line"] = error.line().into();
                    metadata["column"] = error.column().into();
                }
                return Err("RPC JSON is invalid");
            }
        };
        if envelope.get("error").is_some_and(|e| !e.is_null()) {
            self.record_failure(method, id, status.as_u16(), "rpc_error", Some(&bytes));
            return Err("RPC error or response ID mismatch");
        }
        if envelope["id"].as_u64() != Some(id) {
            self.record_failure(method, id, status.as_u16(), "id_mismatch", Some(&bytes));
            return Err("RPC error or response ID mismatch");
        }
        envelope
            .get("result")
            .cloned()
            .ok_or("RPC result is missing")
    }
    fn record_failure(
        &self,
        method: &str,
        id: u64,
        status: u16,
        category: &str,
        bytes: Option<&[u8]>,
    ) {
        if !matches!(method, "status" | "listgroups") {
            return;
        }
        *self.failure_metadata.borrow_mut() = Some(serde_json::json!({
            "method":method,"request_id":id,"http_status":status,"failure_category":category,
            "response_bytes":bytes.map(<[u8]>::len),"response_sha256":bytes.map(sha256)
        }));
    }
    pub fn snapshot(&self, elapsed: u64) -> Result<Sample, &'static str> {
        self.failure_metadata.borrow_mut().take();
        let status = self.call("status", serde_json::json!([]), 1)?;
        let groups = self.call("listgroups", serde_json::json!([0]), 2)?;
        crate::normalize(&status, &groups, elapsed)
    }
    pub fn take_failure_metadata(&self) -> Option<serde_json::Value> {
        self.failure_metadata.borrow_mut().take()
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

pub fn sha256(bytes: &[u8]) -> String {
    ring::digest::digest(&ring::digest::SHA256, bytes)
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Hash the running executable once from its opened, bounded regular descriptor.
pub fn executable_sha256() -> Result<String, &'static str> {
    #[cfg(target_os = "linux")]
    let path = PathBuf::from("/proc/self/exe");
    #[cfg(not(target_os = "linux"))]
    let path = std::env::current_exe().map_err(|_| "cannot locate running executable")?;
    let mut file = std::fs::File::open(path).map_err(|_| "cannot open running executable")?;
    let metadata = file
        .metadata()
        .map_err(|_| "cannot inspect running executable")?;
    const LIMIT: u64 = 128 * 1024 * 1024;
    if !metadata.is_file() || metadata.len() > LIMIT {
        return Err("running executable must be a bounded regular file");
    }
    let mut context = ring::digest::Context::new(&ring::digest::SHA256);
    let mut buffer = [0u8; 65536];
    let mut total = 0u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| "cannot hash running executable")?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > LIMIT {
            return Err("running executable exceeds byte limit");
        }
        context.update(&buffer[..count]);
    }
    Ok(context
        .finish()
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

pub struct Evidence {
    pub directory: PathBuf,
    #[cfg(unix)]
    directory_handle: std::fs::File,
    next: usize,
}

#[cfg(unix)]
fn open_directory_at(
    parent: &std::fs::File,
    name: &std::ffi::CStr,
) -> std::io::Result<std::fs::File> {
    use std::os::fd::{AsRawFd, FromRawFd};
    // The returned descriptor is fresh, owned once, and closed by File. No
    // component symlink is followed; names remain alive for the syscall.
    let fd = unsafe {
        libc::openat(
            parent.as_raw_fd(),
            name.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
        )
    };
    if fd < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(unsafe { std::fs::File::from_raw_fd(fd) })
    }
}

#[cfg(unix)]
fn private_parent(
    path: &Path,
    sync: &impl Fn(&std::fs::File) -> std::io::Result<()>,
) -> Result<std::fs::File, &'static str> {
    use std::os::fd::AsRawFd;
    use std::os::unix::{
        ffi::OsStrExt,
        fs::{MetadataExt, OpenOptionsExt},
    };
    let anchor = if path.is_absolute() { "/" } else { "." };
    let mut directory = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(anchor)
        .map_err(|_| "cannot anchor evidence parent")?;
    for component in path.components() {
        let name = match component {
            std::path::Component::RootDir | std::path::Component::CurDir => continue,
            std::path::Component::Normal(name) => name.as_bytes(),
            std::path::Component::ParentDir => b"..",
            _ => return Err("invalid evidence parent component"),
        };
        let name = std::ffi::CString::new(name).map_err(|_| "invalid evidence parent component")?;
        directory = match open_directory_at(&directory, &name) {
            Ok(opened) => opened,
            Err(error) if error.raw_os_error() == Some(libc::ENOENT) => {
                if unsafe { libc::mkdirat(directory.as_raw_fd(), name.as_ptr(), 0o700) } != 0
                    && std::io::Error::last_os_error().raw_os_error() != Some(libc::EEXIST)
                {
                    return Err("cannot create private evidence parent");
                }
                sync(&directory).map_err(|_| "cannot sync evidence parent entry")?;
                open_directory_at(&directory, &name)
                    .map_err(|_| "cannot open private evidence parent")?
            }
            Err(_) => return Err("evidence parent must use real directories without symlinks"),
        };
    }
    let metadata = directory
        .metadata()
        .map_err(|_| "cannot validate evidence parent")?;
    if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o022 != 0 {
        return Err("evidence parent must be owned by the watcher and not writable by other users");
    }
    Ok(directory)
}

impl Evidence {
    pub fn new(parent: &Path) -> Result<Self, &'static str> {
        Self::new_with_sync(parent, &std::fs::File::sync_all)
    }
    fn new_with_sync(
        parent: &Path,
        sync: &impl Fn(&std::fs::File) -> std::io::Result<()>,
    ) -> Result<Self, &'static str> {
        #[cfg(not(unix))]
        {
            let _ = (parent, sync);
            Err("private evidence directories require a Unix host")
        }
        #[cfg(unix)]
        {
            use std::os::fd::AsRawFd;
            use std::os::unix::fs::MetadataExt;
            let parent_handle = private_parent(parent, sync)?;
            let nonce = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| "system clock predates Unix epoch")?
                .as_nanos();
            let name = format!("run-{nonce}-{}", std::process::id());
            let directory = parent.join(&name);
            let name = std::ffi::CString::new(name).map_err(|_| "invalid run directory")?;
            if unsafe { libc::mkdirat(parent_handle.as_raw_fd(), name.as_ptr(), 0o700) } != 0 {
                return Err("cannot create private evidence directory");
            }
            sync(&parent_handle).map_err(|_| "cannot sync run directory entry")?;
            let directory_handle = open_directory_at(&parent_handle, &name)
                .map_err(|_| "cannot anchor private run directory")?;
            let metadata = directory_handle
                .metadata()
                .map_err(|_| "cannot validate private run directory")?;
            if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o077 != 0 {
                return Err("run directory is not private to the watcher");
            }
            Ok(Self {
                directory,
                directory_handle,
                next: 0,
            })
        }
    }
    pub fn save(&mut self, bytes: &[u8]) -> Result<(), &'static str> {
        if bytes.len() > RESPONSE_LIMIT {
            return Err("evidence exceeds byte limit");
        }
        #[cfg(not(unix))]
        {
            Err("private evidence requires a Unix host")
        }
        #[cfg(unix)]
        {
            use std::os::fd::{AsRawFd, FromRawFd};
            let directory_fd = self.directory_handle.as_raw_fd();
            let pending = c"pending.json";
            let fd = unsafe {
                libc::openat(
                    directory_fd,
                    pending.as_ptr(),
                    libc::O_WRONLY
                        | libc::O_CREAT
                        | libc::O_EXCL
                        | libc::O_NOFOLLOW
                        | libc::O_CLOEXEC,
                    0o600,
                )
            };
            if fd < 0 {
                return Err("cannot create pending evidence");
            }
            let mut file = unsafe { std::fs::File::from_raw_fd(fd) };
            file.write_all(bytes)
                .and_then(|()| file.sync_all())
                .map_err(|_| "evidence write failed; partial evidence preserved")?;
            let destination = std::ffi::CString::new(format!("evidence-{}.json", self.next))
                .map_err(|_| "invalid evidence slot")?;
            if unsafe {
                libc::renameat(
                    directory_fd,
                    pending.as_ptr(),
                    directory_fd,
                    destination.as_ptr(),
                )
            } != 0
            {
                return Err("evidence rotation failed; pending evidence preserved");
            }
            self.directory_handle
                .sync_all()
                .map_err(|_| "evidence directory sync failed")?;
            self.next = (self.next + 1) % 8;
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    #[test]
    fn parent_sync_failure_prevents_a_durable_run_success() {
        let base = std::env::temp_dir().join(format!("observe-sync-fault-{}", std::process::id()));
        std::fs::create_dir(&base).unwrap();
        use std::os::unix::fs::MetadataExt;
        for fail_at in 1..=4 {
            let anchor = base.join(format!("case-{fail_at}"));
            std::fs::create_dir(&anchor).unwrap();
            let first = anchor.join("new-parent");
            let parent = first.join("output");
            let calls = std::cell::Cell::new(0);
            let result = Evidence::new_with_sync(&parent, &|directory| {
                let index = calls.get() + 1;
                calls.set(index);
                // Each newly created entry must sync its containing descriptor,
                // in creation order, including the final private run entry.
                let expected = match index {
                    1 => &anchor,
                    2 => &first,
                    3 => &parent,
                    _ => panic!("unexpected sync"),
                };
                let expected = std::fs::metadata(expected).unwrap();
                let actual = directory.metadata().unwrap();
                assert_eq!(
                    (actual.dev(), actual.ino()),
                    (expected.dev(), expected.ino())
                );
                if index == fail_at {
                    Err(std::io::Error::other("injected directory sync failure"))
                } else {
                    directory.sync_all()
                }
            });
            assert_eq!(calls.get(), fail_at.min(3));
            assert_eq!(result.is_err(), fail_at <= 3);
            // Retain created entries on failure; never hide an incomplete run.
            assert!(first.is_dir());
            if fail_at >= 2 {
                assert!(parent.is_dir());
            }
            if fail_at >= 3 {
                assert_eq!(std::fs::read_dir(&parent).unwrap().count(), 1);
            }
        }
        std::fs::remove_dir_all(base).unwrap();
    }
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
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            // This case supplies a trusted existing parent, independently of
            // the worker's inherited umask; unsafe parents are not supported.
            std::fs::set_permissions(&parent, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
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

    #[cfg(unix)]
    #[test]
    fn evidence_rotation_cannot_follow_replaced_run_or_ancestor_symlinks() {
        use std::os::unix::fs::symlink;
        for replace_parent in [false, true] {
            let base = std::env::temp_dir().join(format!(
                "observe-evidence-anchor-{}-{replace_parent}",
                std::process::id()
            ));
            std::fs::create_dir(&base).unwrap();
            let parent = base.join("output");
            let outside = base.join("outside");
            std::fs::create_dir(&outside).unwrap();
            let mut evidence = Evidence::new(&parent).unwrap();
            let original_run = evidence.directory.clone();
            let run_name = original_run.file_name().unwrap();
            let moved = base.join("moved");
            let (pinned_run, decoy) = if replace_parent {
                std::fs::rename(&parent, &moved).unwrap();
                let decoy = outside.join(run_name);
                std::fs::create_dir(&decoy).unwrap();
                symlink(&outside, &parent).unwrap();
                (moved.join(run_name), decoy)
            } else {
                std::fs::rename(&original_run, &moved).unwrap();
                symlink(&outside, &original_run).unwrap();
                (moved.clone(), outside.clone())
            };
            let victim = decoy.join("evidence-0.json");
            std::fs::write(&victim, b"untouched outside sentinel").unwrap();
            evidence.save(b"private capture").unwrap();
            assert_eq!(
                std::fs::read(&victim).unwrap(),
                b"untouched outside sentinel"
            );
            assert_eq!(
                std::fs::read(pinned_run.join("evidence-0.json")).unwrap(),
                b"private capture"
            );
            drop(evidence);
            std::fs::remove_dir_all(&base).unwrap();
        }
    }
}
