# TLS Cipher Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Rust-backed Optimize TLS ciphers action and deliver a tested isolated local instance with screenshots before PR creation.

**Architecture:** Rust owns policy, benchmarking, jobs and byte-preserving config patches. Typed callbacks reuse the daemon's linked OpenSSL and NNTP implementation. The WebUI polls a control-account-only RPC service and renders its bounded results.

**Tech Stack:** Existing Rust 1.99 static library, C++20 daemon adapters, linked OpenSSL, existing JavaScript/Bootstrap WebUI, Boost tests, Python loopback TLS/NNTP fixtures, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-19-tls-cipher-optimizer-design.md`

## Global Constraints

- Work only in the existing isolated `codex/tls-cipher-optimizer` worktree; preserve other owners' work.
- All commits: signed, author and committer `xbmc4lyfe <273732874+xbmc4lyfe@users.noreply.github.com>`.
- No PR or review process before the user's local-test handoff and g2g; the user has granted approval to proceed through implementation without further checkpoints.
- Eligible suites: certificate-authenticated TLS 1.2/1.3 AEAD, at least 128-bit security, ephemeral TLS 1.2 key exchange; no PSK/SRP/anonymous/legacy modes.
- Records: 16,384 bytes; warmup 50 ms; five balanced rotating rounds; each sample elapsed at least 200,000,000 ns; median throughput ranking; no replacement samples.
- Caps: 256 encrypted servers, 128 eligible suites, 64 algorithms, 16 MiB config snapshot, 1 MiB status response, ten seconds per probe, ten minutes per job, one active job and one probe connection.
- Exact ties: current supported single cipher, then TLS 1.3, then lexical suite name.
- Unknown or unmeasured candidates prevent saving that server; confirmed unsupported candidates do not.
- Apply only cipher values; byte-preserve unrelated config; reject concurrent edits and nonregular/symlink targets; atomic file replacement; no automatic reload.
- Heavy Rust/native stages use the designated scheduling owner, fixed global locks, at most three jobs and bounded admission (default 120 seconds). No unscheduled heavy local build.
- Fresh evidence directory and plan, raw precreated streams, command/completion records and hashes before each validation run. Preserve all failed attempts.
- Existing backend/migration holds remain independent; this is a new feature with no old optimizer baseline.

## Review Focus

- Mixed-case or duplicate Cipher lines must all resolve to the saved choice without changing any unrelated bytes (Task 2).
- DNS stalls and shutdown must leave no resolver process, probe connection or job touching cleaned-up TLS state (Task 3/4).
- A TLS 1.2-only pin against a TLS 1.3-capable provider must not silently use its TLS 1.3 defaults (Task 3).
- A completed old dialog must not overwrite server reordering or unsaved edits in another browser (Task 4/5).
- A delayed cancel after atomic replacement must report saved, never imply the file was left untouched (Task 2/4).

## File Structure and Shared Interfaces

- `rust/src/tlscipher/mod.rs`: policy types, sample validation, ranking, per-server decisions and config byte patching; no native dependencies, independently testable with `rustc --test`.
- `rust/src/tlscipher/job.rs`: one-job worker service, bounded status JSON, cancellation, measurements and probe orchestration using `Backend`.
- `rust/src/tlscipher/native.rs`: owned typed C callback adapter and self-executable bounded resolver subprocess.
- `rust/include/nzbget_tls_cipher.h`: ABI dedicated to this feature; consumed by the existing umbrella `nzbget_rs.h`.
- `daemon/connect/TlsCipherBackend.{h,cpp}`: OpenSSL/NNTP callback implementations and native lifecycle facade.
- `daemon/connect/Connection.{h,cpp}` and `TlsSocket.{h,cpp}`: resolved-address override, absolute probe deadline, negotiated-cipher inspection, exact-suite pinning; normal custom lists retain behavior.
- `daemon/extension/ScriptConfig.{h,cpp}`: common config write lock and checked snapshot/atomic patch commit.
- `daemon/remote/XmlRpc.cpp`: optimizer RPC registration/access/transport checks, small adapter command.
- `daemon/main/nzbget.cpp`: early internal resolver entry and worker shutdown before cleanup, including reload.
- `webui/tlscipher.js`, `webui/index.html`, `webui/config.js`, `webui/skin.css`, locale catalogs: dialog, section action, saved-result reconciliation and styling.
- `tests/connect/TlsCipher.cpp`, `tests/functional/tlscipher/fixture.py`, `tests/webui/tls-cipher.js`: native integration, loopback end-to-end and UI regression.

Rust policy interfaces:

```rust
enum Protocol { Tls12, Tls13 }
struct Suite { name: String, algorithm: String, protocol: Protocol, security_bits: u16, aead: bool, ephemeral: bool, certificate: bool }
struct Sample { round: u8, bytes: u64, elapsed_ns: u64, correct: bool }
enum Support { Supported, Unsupported, Unknown }
struct Choice { cipher: String, bytes_per_second: f64 }
fn eligible(suite: &Suite) -> bool;
fn throughput(samples: &[Sample]) -> Result<f64, Error>;
fn choose(suites: &[Suite], rates: &BTreeMap<String, f64>, support: &BTreeMap<String, Support>, current: &str) -> Result<Option<Choice>, Error>;
fn patch_config(original: &[u8], changes: &BTreeMap<u32, String>) -> Result<Vec<u8>, Error>;
```

Job `Backend: Send + Sync + 'static` exposes `snapshot() -> Result<Snapshot, Error>`,
`suites() -> Result<Vec<Suite>, Error>`, `prepare(algorithm: &str) -> Result<Box<dyn Decryptor>, Error>`,
`probe(server: &Server, suite: &Suite, cancel: &AtomicBool, deadline: Instant) -> Support`,
and `commit(snapshot: &Snapshot, changes: &BTreeMap<u32, String>, cancel: &AtomicBool) -> Result<bool, Error>`.
`Decryptor::record(&mut self, sequence: u64) -> Result<u64, Error>` processes one verified record; setup stays outside timers.
`Snapshot` owns original config bytes plus parsed `Server` values (id, name, host, port, username, password, cipher, IP version and verification level).
No credential-bearing `Debug` or status serialization derives.

`Service::start(Arc<dyn Backend>) -> Result<String, Error>`,
`Service::status(id: Option<&str>) -> Result<String, Error>`,
`Service::cancel(id: &str) -> Result<(), Error>`, and `Service::shutdown()`
are the only public job controls. An absent status id queries availability/current job.

ABI callbacks use borrowed length-tagged strings/buffers and explicit success/error
codes; every created native context has exactly one destroy callback. Rust copies
snapshots before returning from start and retains an owned native backend context
until its joined worker exits. All callbacks are nonthrowing; no borrowed RPC or
Options pointer crosses a thread lifetime. Publish exact ABI declarations beside
the matching Rust `#[repr(C)]` structs and test field/ownership correspondence.

---

### Task 1: Cipher policy and measured selection

**Files:** Create `rust/src/tlscipher/mod.rs`; modify `rust/src/lib.rs`.
**Interfaces:** Produces the policy interfaces above; Task 4 consumes them.

- [ ] Write tests `filters_unsafe_suites`, `requires_five_unique_valid_rounds`, `rejects_underfloor_and_nonfinite_rates`, `selects_fastest_per_server`, `unknown_prevents_choice`, `ties_retain_current_then_tls13_then_name`.
  Assert elapsed `199_999_999` rejects and `200_000_000` accepts; samples with rounds `[0,1,2,3,3]` reject; algorithms at 300/200/100 choose the best in each independent support set; unsupported differs from unknown.
- [ ] Under scheduler admission, run `rustc --edition=2021 --test rust/src/tlscipher/mod.rs -o POLICY_TEST` then `POLICY_TEST`; retain the expected failing assertions before implementing behavior.
- [ ] Implement `eligible`, `throughput` and `choose` with the shared signatures. Require finite positive rates and exact sample keys; every candidate's support must be known before selection.
- [ ] Run the same admitted test commands; expected: all policy tests pass. Commit signed as `feat: add TLS cipher ranking policy` after reading the actual output.

### Task 2: Cipher-only configuration transaction

**Files:** Modify `rust/src/tlscipher/mod.rs`, `daemon/extension/ScriptConfig.{h,cpp}`, `tests/extension/ScriptConfig.cpp`.
**Interfaces:** Consumes `patch_config`; produces `ScriptConfig::ReadCipherSnapshot(std::string&)` and `ScriptConfig::CommitCipherPatch(std::string_view expected, std::string_view replacement, const std::atomic<bool>& cancel)` with typed result `Saved/Unchanged/Conflict/Cancelled/Failed`.

- [ ] Write Rust tests `patch_preserves_unrelated_bytes`, `patches_duplicate_case_insensitive_cipher_lines`, `appends_missing_cipher_with_matching_newline`, `rejects_invalid_patch_values`.
  Assert comments, CRLF, non-UTF8 unrelated bytes, credentials, no-final-newline and all non-Cipher fields remain byte-identical. Reject ids zero, unknown server ids and values containing line breaks/NUL or cipher-list syntax.
- [ ] Write native tests `CipherPatchConflictPreservesOriginal`, `CipherPatchRejectsSymlinkAndDirectory`, `CipherPatchWriteFailurePreservesOriginal`, `CipherPatchSerializesOrdinarySave`, `CipherPatchPreservesMode`, `CancelAfterCommitReportsSaved` using temporary files only.
- [ ] Run these through the admitted Rust and Boost `ExtensionTest` commands; expected: relevant tests fail against unimplemented APIs/old behavior.
- [ ] Implement parsing/patch construction in Rust. In native code use a shared ScriptConfig write mutex, descriptor-bound bounded snapshot, original-byte comparison, exclusive sibling temp creation, mode/ownership preservation, checked write/flush/close, cancellation check and atomic replacement. Use platform-native replacement semantics; unsupported ownership/ACL preservation rejects before replacement. Ordinary SaveConfig takes the same mutex.
- [ ] Run admitted policy and `nzbget_tests --run_test=ExtensionTest --log_level=message`; expected: all named tests and existing config regressions pass. Commit signed.

### Task 3: Linked-library crypto and exact bounded NNTP probes

**Files:** Create ABI header and `TlsCipherBackend.{h,cpp}`; modify `TlsSocket.{h,cpp}`, `Connection.{h,cpp}`, `daemon/sources.cmake`, `rust/include/nzbget_rs.h`; create native tests/fixture and add CMake registration.
**Interfaces:** Produces the native callbacks consumed by Task 4, exact-suite pinning for normal downloads, and `Connection::SetResolvedAddresses(...)` plus `SetDeadline(...)`; ordinary connections have neither override by default.

- [ ] Write native/loopback tests for TLS 1.2/1.3 accepted/rejected suites, actual selected name/version, greeting/authentication, bad certificate, stalled greeting, shutdown/cancel, multiple IPv4/IPv6 answers and empty DNS result. Assert no ARTICLE/BODY/GROUP command is sent.
- [ ] Write EVP correctness tests for supported AEAD adapters, corrupt tags, malformed lengths, per-record distinct nonces and nonconstant plaintext; no invalid plaintext is accepted. Mark unsupported algorithm adapters unmeasured.
- [ ] Run admitted native tests against existing behavior; expected: exact TLS 1.2 pin test fails if TLS 1.3 defaults remain usable, and new probe/deadline tests fail until implemented.
- [ ] Implement metadata enumeration through the linked OpenSSL, reusable authenticated-decryption contexts and adapter callbacks. Rank/filter policy stays in Rust. Bound callbacks and clear OpenSSL errors locally without printing secrets.
- [ ] Add exact eligible single-suite recognition/version bounds and getters for negotiated version/name. Preserve empty/custom-list behavior. Keep certificate validation on the real existing TlsSocket path.
- [ ] Implement absolute monotonic probe deadline and cancellation-aware socket waits; deadline covers connect, handshake, greeting and login, not a fresh timeout for every phase. Use numeric pre-resolved addresses while retaining original hostname for SNI/certificate checks.
- [ ] Run admitted native tests plus unchanged NNTP/Remote/Extension suites; expected: all pass, including no-TLS/no-Rust compile branches. Commit signed.

### Task 4: Rust job service, resolver custody and protected RPC

**Files:** Create `rust/src/tlscipher/job.rs`, `native.rs`; modify `ffi.rs`, ABI header, `XmlRpc.cpp`, `nzbget.cpp` and native facade; add tests to `tests/remote/XmlRpc.cpp`.
**Interfaces:** Consumes Tasks 1–3; produces RPCs `tlscipherstart([])`, `tlscipherstatus([optional_job_id])`, `tlsciphercancel([job_id])`, each returning a structured JSON object over authenticated JSON-RPC POST only.

- [ ] Write fake-backend job tests for rotating five rounds, one worker, duplicate starts, all admission caps, snapshot ownership, unknown/unmeasured handling, partial fleet success, exact common-set/unknown reporting, cancellation before/during/after commit, stale ids, status size and shutdown join.
- [ ] Write RPC tests for control versus restricted/add access, POST versus GET/JSONP, wrong parameter types/extra arguments, backend absence, wrong job id and bounded escaped responses. Assert denied requests cannot start crypto/provider work or mutate config.
- [ ] Write resolver tests with a synthetic self-executable mode: success, stalled resolver killed/reaped by deadline, cancellation, malformed/oversized output and launch failure. Assert no resolver thread survives shutdown.
- [ ] Run admitted failing tests before implementing the worker and RPC bodies.
- [ ] Implement Service, bounded serializable public models, one owned thread, cancellation and callback lifetimes; measurements use `Instant` and batches bounded for responsiveness. Require returned processed bytes equal record size.
- [ ] Implement bounded DNS through a fixed internal mode of the current executable (`--internal-tls-cipher-resolve`), entered before daemon initialization. Spawn with argument lists, private bounded stdout, no inherited credentials/stdin, null stderr; poll deadline/cancel, kill and reap the exact child on failure. Parse only numeric socket addresses, preserving IP-version filtering. This avoids uncancellable blocking getaddrinfo in the worker; it does not perform TLS or require an external executable.
- [ ] Register POST-only control RPCs with a disabled result when unavailable. Ensure reload/shutdown joins the worker before native objects or TLS are cleaned up. Commit only fully tested per-server choices via Task 2.
- [ ] Run admitted Rust job tests and native RPC/NNTP/config suites; expected: all pass with no secret strings in public responses. Commit signed.

### Task 5: WebUI action, progress and saved-result reconciliation

**Files:** Create `webui/tlscipher.js`, `tests/webui/tls-cipher.js`; modify `index.html`, `config.js`, `skin.css`, locale source and generated catalogs, `tests/webui/README.md`.
**Interfaces:** Consumes Task 4 RPC schema; produces `TlsCipherDialog.init()`, `showModal()` and `Config.applyCipherResults(results)`.

- [ ] Write loopback-only Playwright tests exercising real committed templates/JS with intercepted RPC: button availability, unsaved-server guard, unrelated unsaved preservation, pending/cancel/reopen, duplicate clicks, stale job, escaped names/errors, results saved versus active, browser reorder conflict, keyboard focus and last row/column at 1280/390/320 in both themes.
- [ ] Run `node tests/webui/tls-cipher.js http://127.0.0.1:17689/` with prospective capture; expected: assertions fail before implementation, with no network mutations.
- [ ] Implement the dialog and News Servers action, reuse existing rendering/locale patterns, poll at a bounded interval and stop timers on terminal state/page unload. Reopening queries current state rather than starting another run.
- [ ] Disable action for unsaved server edits or missing backend; preserve unrelated dirty values. Match server snapshot fields before applying confirmed cipher values to browser state; conflicting browser changes are reported and retained. Add existing reload-required notice after saved results.
- [ ] Run the new check plus Settings density, lists, compact tiles, locales and phone navigation against the isolated fixture; expected: zero assertion/page errors. Commit signed.

### Task 6: End-to-end validation, local instance and screenshots

**Files:** Complete `tests/functional/tlscipher/fixture.py`; document invocation and local handoff in `tests/functional/tlscipher/README.md`; retain private evidence outside Git.
**Interfaces:** Consumes the complete candidate; produces the local runnable artifact and handoff.

- [ ] Freeze source/fixtures/commands and get scheduling-owner admission for a fresh native TLS/Rust build and focused tests; no stale archive timestamps or borrowed build-lineage claims.
- [ ] Run the real button/RPC against synthetic loopback servers with different support sets. Verify measured rank, negotiated suite, per-server persisted cipher, untouched other config bytes, reload-required state, unknown/error preservation and cancellation. Inspect actual files and RPC outcomes, not just screenshots.
- [ ] Run relevant native and UI regressions; inspect full completion records and all failures. Unsupported platform coverage is a declared limitation, never a pass.
- [ ] Prepare a separate local loopback service serving the exact built backend and candidate assets, with separate config/queue/state and synthetic providers. Record executable and source hashes, URL, start/stop commands and process ownership.
- [ ] Capture real sanitized JPEGs of initial, running and completed dialog at desktop/phone and light/dark; verify viewport, final row/column, no clipping/private values and image dimensions/hashes. Open the local instance for the user.
- [ ] Announce readiness audibly with `/usr/bin/say`, deliver screenshots and local test instructions, and stop before PR/review pending the user's g2g. Preserve all evidence and the plan ledger at this handoff.

### Task 7: Review and PR after g2g

**Files:** Candidate runtime/docs and retained evidence as required by findings.
**Interfaces:** Consumes explicit g2g, fresh source, evidence and current remote.

- [ ] Only after g2g, obtain the required fresh independent whole-branch review, fix actionable findings with meaningful tests and rerun affected validation. Follow existing integration-owner and final-head review procedures.
- [ ] Refresh canonical default, preserve signed history, verify exact final tree/identity/signature and current-head tests. Publish only the owned feature ref using the verified HTTPS helper; verify GitHub signing and create/attach the PR.
- [ ] Integration/deployment remain with designated owners and their applicable holds; do not equate PR creation with installation.
