//! Native callback ownership and a bounded self-executable resolver.
use crate::tlscipher::{self, *, job::*};
use std::ffi::{c_char, c_int, c_void, CStr, CString};
use std::io::{Read, Write};
use std::net::{SocketAddr, ToSocketAddrs};
use std::process::{Command, Stdio};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, OnceLock, atomic::{AtomicBool, Ordering}};
use std::time::{Duration, Instant};

pub type Cancel = unsafe extern "C" fn(*mut c_void) -> c_int;
type Emit = unsafe extern "C" fn(*mut c_void, *const c_char, *const c_char, c_int, u32, u32) -> c_int;
#[repr(C)]
pub struct NativeServer {
    id: u32, host: *const c_char, port: u16, ip_version: u8, verification: u8,
    username: *const c_char, password: *const c_char,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Io {
    context: *mut c_void,
    snapshot: unsafe extern "C" fn(*mut c_void, *mut *const u8, *mut usize) -> c_int,
    suites: unsafe extern "C" fn(*mut c_void, Emit, *mut c_void) -> c_int,
    prepare: unsafe extern "C" fn(*mut c_void, *const c_char) -> *mut c_void,
    prepare_batch: unsafe extern "C" fn(*mut c_void, u64, u32) -> c_int,
    record: unsafe extern "C" fn(*mut c_void, u64) -> c_int,
    free_decryptor: unsafe extern "C" fn(*mut c_void),
    probe: unsafe extern "C" fn(*mut c_void, *const NativeServer, *const c_char, c_int, *const c_char, u64, Cancel, *mut c_void) -> c_int,
    commit: unsafe extern "C" fn(*mut c_void, *const u8, usize, *const u8, usize, Cancel, *mut c_void) -> c_int,
    destroy: unsafe extern "C" fn(*mut c_void),
}
pub struct Native { io: Io, addresses: Mutex<BTreeMap<String, Vec<String>>> }
// The ABI context is owned, immutable except for callbacks, and used by exactly
// one worker after start. Status/cancel never call through it. destroy follows join.
unsafe impl Send for Native {}
unsafe impl Sync for Native {}
impl Drop for Native { fn drop(&mut self) { unsafe { (self.io.destroy)(self.io.context); } } }
unsafe extern "C" fn cancelled(context: *mut c_void) -> c_int {
    i32::from(unsafe { &*context.cast::<AtomicBool>() }.load(Ordering::Acquire))
}
struct Engine { context: *mut c_void, io: Io }
impl Drop for Engine { fn drop(&mut self) { unsafe { (self.io.free_decryptor)(self.context); } } }
impl Decryptor for Engine {
    fn prepare_batch(&mut self, first: u64, count: u32) -> Result<(), Error> {
        if unsafe { (self.io.prepare_batch)(self.context, first, count) } == 1 { Ok(()) } else { Err(Error("Could not prepare authenticated records.")) }
    }
    fn record(&mut self, sequence: u64) -> Result<u64, Error> {
        let bytes = unsafe { (self.io.record)(self.context, sequence) };
        if bytes == RECORD_BYTES as c_int { Ok(RECORD_BYTES) } else { Err(Error("Authenticated record validation failed.")) }
    }
}

fn parse_snapshot(bytes: Vec<u8>) -> Result<Snapshot, Error> {
    let mut options: BTreeMap<String, Option<String>> = BTreeMap::new();
    let mut expanded_bytes = 0usize;
    for line in bytes.split(|&b| b == b'\n') {
        if let Some((name, value, _)) = tlscipher::option(line) {
            let name = std::str::from_utf8(name).map_err(|_| Error("Invalid configuration option name."))?.to_ascii_lowercase();
            let mut value = std::str::from_utf8(value).ok().map(str::to_owned);
            if let Some(value) = &mut value {
                // Match Options::SetOption's sequential saved-variable expansion.
                // Unknown variables remain unresolved; never send unresolved
                // credentials to a provider or guess runtime-only defaults.
                for _ in 0..32 {
                    let Some(start) = value.find("${") else { break; };
                    let Some(end) = value[start + 2..].find('}').map(|n| start + 2 + n) else { break; };
                    let variable = &value[start + 2..end];
                    if variable.len() > 99 { break; }
                    let Some(Some(replacement)) = options.get(&variable.to_ascii_lowercase()) else { break; };
                    if value.len().saturating_add(replacement.len()) > 16 * 1024 * 1024 { return Err(Error("Expanded server configuration exceeds size limits.")); }
                    value.replace_range(start..=end, replacement);
                }
            }
            let previous = options.get(&name).and_then(|s| s.as_ref()).map_or(0, String::len);
            expanded_bytes = expanded_bytes.saturating_sub(previous).saturating_add(value.as_ref().map_or(0, String::len));
            if expanded_bytes > 32 * 1024 * 1024 { return Err(Error("Expanded configuration exceeds size limits.")); }
            options.insert(name, value);
        }
    }
    let mut ids = std::collections::BTreeSet::new();
    for name in options.keys() {
        if let Some((prefix, suffix)) = name.split_once('.') {
            if prefix.starts_with("server") {
                let id = tlscipher::server_option(name.as_bytes(), suffix.as_bytes())
                    .ok_or(Error("Invalid saved server identifier."))?;
                ids.insert(id);
            }
        }
    }
    if ids.iter().enumerate().any(|(index, id)| *id as usize != index + 1) {
        return Err(Error("Saved server definitions must be consecutively numbered; no provider probes were started."));
    }
    let mut servers = Vec::new();
    for id in ids {
        let get = |field: &str| -> Result<&str, Error> {
            match options.get(&format!("server{id}.{field}")) {
                Some(Some(value)) if !value.contains('\0') => Ok(value), None => Ok(""),
                _ => Err(Error("Server fields must be valid UTF-8 without NUL bytes.")),
            }
        };
        let host = get("host")?;
        let encryption = get("encryption")?.to_ascii_lowercase();
        if ["", "no", "false", "off", "0"].contains(&encryption.as_str()) { continue; }
        if !["yes", "true", "on", "1"].contains(&encryption.as_str()) {
            return Err(Error("Invalid server encryption setting."));
        }
        if host.is_empty() || get("connections")?.parse::<u32>().is_err() {
            return Err(Error("Saved encrypted server definition is incomplete; no provider probes were started."));
        }
        if [host, get("username")?, get("password")?].iter().any(|s| s.contains("${")) {
            return Err(Error("Server variable references could not be resolved; no provider probes were started."));
        }
        let port = get("port")?.parse::<u16>().map_err(|_| Error("Invalid server port."))?;
        let verification = match get("certverification")?.to_ascii_lowercase().as_str() {
            "" | "strict" => 2, "minimal" => 1, "none" => 0, _ => return Err(Error("Invalid certificate verification level.")),
        };
        let ip_version = match get("ipversion")?.to_ascii_lowercase().as_str() {
            "" | "auto" => 0, "ipv4" => 4, "ipv6" => 6, _ => return Err(Error("Invalid server IP version.")),
        };
        servers.push(Server { id, name: get("name")?.to_owned(), host: host.to_owned(), port,
            username: get("username")?.to_owned(), password: get("password")?.to_owned(),
            cipher: get("cipher")?.to_owned(), ip_version, verification });
    }
    servers.sort_by_key(|s| s.id);
    Ok(Snapshot { bytes, servers })
}

impl Backend for Native {
    fn snapshot(&self) -> Result<Snapshot, Error> {
        let mut pointer = std::ptr::null(); let mut length = 0;
        if unsafe { (self.io.snapshot)(self.io.context, &mut pointer, &mut length) } != 1 || length > 16 * 1024 * 1024 || pointer.is_null() && length > 0 {
            return Err(Error("Could not read a regular configuration file."));
        }
        let bytes = if length == 0 { Vec::new() } else { unsafe { std::slice::from_raw_parts(pointer, length) }.to_vec() };
        parse_snapshot(bytes)
    }
    fn suites(&self) -> Result<Vec<Suite>, Error> {
        unsafe extern "C" fn emit(context: *mut c_void, name: *const c_char, algorithm: *const c_char, protocol: c_int, bits: u32, flags: u32) -> c_int {
            let suites = unsafe { &mut *context.cast::<Vec<Suite>>() };
            if suites.len() >= 4096 || name.is_null() || algorithm.is_null() { return 0; }
            let name = unsafe { CStr::from_ptr(name) }.to_string_lossy().into_owned();
            let algorithm = unsafe { CStr::from_ptr(algorithm) }.to_string_lossy().into_owned();
            let protocol = match protocol { 12 => Protocol::Tls12, 13 => Protocol::Tls13, _ => return 0 };
            suites.push(Suite { name, algorithm, protocol, security_bits: bits.min(u16::MAX.into()) as u16,
                aead: flags & 1 != 0, certificate: flags & 2 != 0, ephemeral: flags & 4 != 0 }); 1
        }
        let mut suites = Vec::new();
        if unsafe { (self.io.suites)(self.io.context, emit, (&mut suites as *mut Vec<Suite>).cast()) } != 1 {
            return Err(Error("Could not enumerate the linked TLS library."));
        }
        Ok(suites)
    }
    fn prepare(&self, algorithm: &str) -> Result<Box<dyn Decryptor>, Error> {
        let algorithm = CString::new(algorithm).map_err(|_| Error("Invalid bulk algorithm."))?;
        let context = unsafe { (self.io.prepare)(self.io.context, algorithm.as_ptr()) };
        if context.is_null() { return Err(Error("No validated decryption adapter is available.")); }
        Ok(Box::new(Engine { context, io: self.io }))
    }
    fn probe(&self, server: &Server, suite: &Suite, cancel: &AtomicBool, deadline: Instant) -> Probe {
        let unknown = |message| Probe { support: Support::Unknown, message };
        let key = format!("{}:{}:{}", server.host, server.port, server.ip_version);
        let cached = self.addresses.lock().unwrap().get(&key).cloned();
        let addresses = match cached {
            Some(addresses) => addresses,
            None => match resolve(&server.host, server.port, server.ip_version, cancel, deadline) {
                Ok(addresses) => { self.addresses.lock().unwrap().insert(key, addresses.clone()); addresses },
                Err(error) => return unknown(error.0),
            },
        };
        if cancel.load(Ordering::Acquire) { return unknown("Cancelled."); }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() { return unknown("Server probe deadline exceeded."); }
        let strings: Result<Vec<_>, _> = [&server.host, &server.username, &server.password, &suite.name, &addresses.join("\n")]
            .into_iter().map(|s| CString::new(s.as_bytes())).collect();
        let Ok(strings) = strings else { return unknown("Invalid server configuration."); };
        let native = NativeServer { id: server.id, host: strings[0].as_ptr(), port: server.port,
            ip_version: server.ip_version, verification: server.verification,
            username: strings[1].as_ptr(), password: strings[2].as_ptr() };
        let code = unsafe { (self.io.probe)(self.io.context, &native, strings[3].as_ptr(),
            if suite.protocol == Protocol::Tls13 { 13 } else { 12 }, strings[4].as_ptr(),
            remaining.as_millis().min(10_000) as u64, cancelled, (cancel as *const AtomicBool).cast_mut().cast()) };
        match code {
            1 => Probe { support: Support::Supported, message: "Supported" },
            0 => Probe { support: Support::Unsupported, message: "Unsupported cipher suite" },
            -2 => unknown("DNS resolution failed."), -3 => unknown("Server probe deadline exceeded."),
            -4 => unknown("Certificate verification failed."), -5 => unknown("Server authentication failed."),
            -6 => unknown("Cancelled."), _ => unknown("TLS or NNTP compatibility could not be established."),
        }
    }
    fn commit(&self, snapshot: &Snapshot, changes: &BTreeMap<u32, String>, cancel: &AtomicBool) -> Result<bool, Error> {
        let replacement = patch_config(&snapshot.bytes, changes)?;
        match unsafe { (self.io.commit)(self.io.context, snapshot.bytes.as_ptr(), snapshot.bytes.len(), replacement.as_ptr(), replacement.len(),
            cancelled, (cancel as *const AtomicBool).cast_mut().cast()) } {
            1 => Ok(true), 0 => Ok(false), -2 => Err(Error("Configuration changed during testing; no ciphers were saved.")),
            -3 => Err(Error("Tests cancelled; cipher settings were not changed.")),
            _ => Err(Error("Could not atomically save cipher settings; configuration was retained.")),
        }
    }
}

fn resolve(host: &str, port: u16, family: u8, cancel: &AtomicBool, deadline: Instant) -> Result<Vec<String>, Error> {
    let executable = std::env::current_exe().map_err(|_| Error("Resolver executable is unavailable."))?;
    let mut command = Command::new(executable);
    command.args(["--internal-tls-cipher-resolve", host, &port.to_string(), &family.to_string()])
        .env_clear().stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    if let Some(root) = std::env::var_os("SystemRoot") { command.env("SystemRoot", root); }
    let mut child = command.spawn().map_err(|_| Error("Could not launch bounded DNS resolver."))?;
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => { let _ = child.kill(); let _ = child.wait(); return Err(Error("Resolver output is unavailable.")); },
    };
    let reader = std::thread::Builder::new().name("tls-dns-output".into()).spawn(move || {
        let mut data = Vec::new(); stdout.take(4097).read_to_end(&mut data).map(|_| data)
    });
    let reader = match reader {
        Ok(reader) => reader,
        Err(_) => { let _ = child.kill(); let _ = child.wait(); return Err(Error("Could not capture DNS resolver output.")); },
    };
    let status = loop {
        if cancel.load(Ordering::Acquire) || Instant::now() >= deadline {
            let _ = child.kill(); let _ = child.wait(); let _ = reader.join();
            return Err(Error("DNS resolution was cancelled or exceeded its deadline."));
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => std::thread::sleep(Duration::from_millis(10)),
            Err(_) => { let _ = child.kill(); let _ = child.wait(); let _ = reader.join(); return Err(Error("DNS resolver completion is unknown.")); },
        }
    };
    let bytes = reader.join().map_err(|_| Error("DNS resolver capture failed."))?
        .map_err(|_| Error("DNS resolver capture failed."))?;
    if !status.success() || bytes.len() > 4096 { return Err(Error("DNS resolution failed.")); }
    let text = std::str::from_utf8(&bytes).map_err(|_| Error("Invalid DNS resolver output."))?;
    let mut addresses = Vec::new();
    for line in text.lines() {
        let address = line.parse::<SocketAddr>().map_err(|_| Error("Invalid DNS resolver address."))?;
        if address.port() != port || family == 4 && !address.is_ipv4() || family == 6 && !address.is_ipv6() || addresses.len() >= 16 {
            return Err(Error("Invalid DNS resolver address set."));
        }
        let numeric = match address {
            SocketAddr::V6(a) if a.scope_id() != 0 => format!("{}%{}", a.ip(), a.scope_id()),
            _ => address.ip().to_string(),
        };
        if !addresses.contains(&numeric) { addresses.push(numeric); }
    }
    if addresses.is_empty() { return Err(Error("DNS resolution returned no usable addresses.")); }
    Ok(addresses)
}

pub fn resolver(args: &[String]) -> i32 {
    if args.len() != 4 || args[0] != "--internal-tls-cipher-resolve" || args[1].is_empty() || args[1].len() > 255 { return 2; }
    let Ok(port) = args[2].parse::<u16>() else { return 2; };
    let Ok(family) = args[3].parse::<u8>() else { return 2; };
    if port == 0 || !matches!(family, 0 | 4 | 6) { return 2; }
    let Ok(found) = (args[1].as_str(), port).to_socket_addrs() else { return 1; };
    let mut addresses = std::collections::BTreeSet::new();
    for address in found {
        if family == 4 && !address.is_ipv4() || family == 6 && !address.is_ipv6() { continue; }
        addresses.insert(address); if addresses.len() > 16 { return 1; }
    }
    if addresses.is_empty() { return 1; }
    let mut output = String::new();
    for address in addresses { output.push_str(&format!("{address}\n")); }
    if std::io::stdout().lock().write_all(output.as_bytes()).is_err() { 1 } else { 0 }
}

pub fn service() -> &'static Service { static SERVICE: OnceLock<Service> = OnceLock::new(); SERVICE.get_or_init(Service::default) }
pub fn start(io: Io) -> Result<String, Error> {
    let id = service().start(Arc::new(Native { io, addresses: Mutex::new(BTreeMap::new()) }))?;
    service().status(Some(&id))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn snapshot_uses_saved_tls_servers_including_disabled_backups() {
        let snapshot = parse_snapshot(b"Server1.Connections=1\nServer1.Host=example.invalid\nServer1.Port=563\nServer1.Encryption=yes\nServer1.Active=no\nServer1.Password=private\nServer2.Host=plain.invalid\nServer2.Port=119\nServer2.Encryption=no\n".to_vec()).unwrap();
        assert_eq!(snapshot.servers.len(), 1); assert_eq!(snapshot.servers[0].verification, 2);
        assert_eq!(snapshot.servers[0].password, "private");
    }
    #[test]
    fn snapshot_rejects_ambiguous_security_values() {
        assert!(parse_snapshot(b"Server1.Connections=1\nServer1.Host=example.invalid\nServer1.Port=563\nServer1.Encryption=yes\nServer1.CertVerification=unknown\n".to_vec()).is_err());
        assert_eq!(resolver(&["--internal-tls-cipher-resolve".into(), "example.invalid".into(), "0".into(), "4".into()]), 2);
    }
    #[test]
    fn saved_variable_expansion_is_sequential_and_unknown_credentials_reject() {
        let snapshot = parse_snapshot(b"UnpackPassword=original\n$Login=${UnpackPassword}\nUnpackPassword=changed\nServer1.Connections=1\nServer1.Host=example.invalid\nServer1.Port=563\nServer1.Encryption=yes\nServer1.Password=${$Login}\n".to_vec()).unwrap();
        assert_eq!(snapshot.servers[0].password, "original");
        assert!(parse_snapshot(b"Server1.Connections=1\nServer1.Host=example.invalid\nServer1.Port=563\nServer1.Encryption=yes\nServer1.Password=${Unknown}\n".to_vec()).is_err());
    }
    #[test]
    fn orphan_or_incomplete_saved_servers_do_not_start_probes() {
        for bytes in [
            b"Server2.Host=example.invalid\nServer2.Port=563\nServer2.Connections=1\nServer2.Encryption=yes\n".as_slice(),
            b"Server1.Host=example.invalid\nServer1.Port=563\nServer1.Encryption=yes\n".as_slice(),
            b"Server1.Host=example.invalid\nServer1.Port=563\nServer1.Connections=1\nServer1.Encryption=maybe\n".as_slice(),
        ] { assert!(parse_snapshot(bytes.to_vec()).is_err()); }
    }
}
