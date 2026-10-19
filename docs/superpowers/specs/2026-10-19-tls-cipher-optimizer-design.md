# Rust TLS cipher optimizer

Status: proposed specification for human review; implementation has not started.

## Intent and acceptance

Add an **Optimize TLS ciphers** button to Settings > News Servers. On the
computer running NZBGet, measure local cipher throughput, discover which
candidates each configured encrypted news server accepts, and automatically
save the fastest measured supported cipher separately for each server. A server
that accepts the overall winner gets that winner; another gets its own fastest
supported candidate. Show the results, errors and whether a reload is required.

The user approved this approach in chat. The user additionally requires a
tested isolated local version and real screenshots before any pull request,
an audible readiness announcement, and their explicit **g2g** before opening
the PR and beginning the review process. This specification is the next review
artifact, followed by an implementation plan. No production installation,
provider test, integration, or release of an existing backend hold is implied.

Source baseline: `8cb2a02d46b6f596e75ff183050b740ed84c609e`, freshly fetched
from `origin/dupe-article-fallback`, canonical repository `Appz4Fun/nzbget`.
Existing boundaries are `rust/`, `daemon/remote/XmlRpc.cpp`,
`daemon/connect/TlsSocket.cpp`, `daemon/extension/ScriptConfig.cpp`, and
`webui/config.js`. The guide is `docs/FINDING_BEST_TLS_CIPHER.md`.

## Chosen approach and alternatives

Implement orchestration, measurement loops, selection, job state, cancellation
and validation in the existing Rust library. Add narrowly typed C ABI callbacks
for the existing daemon's OpenSSL, NNTP and configuration facilities. C++ remains
the adapter to existing native facilities; JavaScript renders the dialog and
polls the job. Do not introduce a second crypto library or an executable lookup.

A separate `openssl speed` process is simpler but could measure a different
OpenSSL build and requires an external executable. Downloading articles under
each cipher would include network and provider variability and need a content
fixture. Neither is the selected implementation. This tool estimates local
crypto throughput and validates compatibility; it does not claim to measure
end-to-end download speed or guarantee a unique fastest cipher under all loads.

## Cipher scope and measurement

Enumerate candidates from the linked OpenSSL implementation under its existing
security policy. Eligible suites use TLS 1.2 or TLS 1.3, authenticated encryption
with at least 128-bit security, and certificate authentication usable by NZBGet.
TLS 1.2 additionally requires ephemeral key exchange. Exclude anonymous,
NULL, export, legacy CBC/RC4/3DES, PSK and SRP suites; NNTP credentials are not
TLS PSK credentials. Report exclusions and unavailable algorithms explicitly.
Benchmark each distinct eligible bulk algorithm once and associate its results
with every matching suite. Cover AES-128-GCM, AES-256-GCM and
ChaCha20-Poly1305 when available, plus other eligible algorithms actually exposed
by the linked library with a validated authenticated-decryption adapter.
An algorithm without that adapter is reported as unmeasured and cannot win.

Measure authenticated decryption of valid synthetic 16,384-byte records with
fresh record nonces, matching Usenet's receive direction. Generate and validate
reference plaintext/ciphertext outside timing; consume decrypted outputs so work
cannot be removed. Use one worker and the same reusable-context lifecycle for
all algorithms, including per-record initialization and tag verification.
Do not include allocation or fixture generation in the timed region.

Freeze the job's candidate list and method before collection: a 50 ms warmup
per algorithm followed by five rounds, rotating candidate order each round.
Each sample runs until the integer elapsed duration is at least 200,000,000 ns.
Store every round's bytes, elapsed nanoseconds and correctness outcome; a failed,
missing, duplicate or under-floor sample invalidates that algorithm. No adaptive
retries or silent replacement samples. Rank valid algorithms by median bytes
per second. Exact ties prefer the existing single cipher if it is supported,
then TLS 1.3, then lexical suite name for a reproducible result. Show measured
rates as estimates, including sample spread, rather than a precision guarantee.

## Server compatibility and exact selection

Operate on the saved configuration, taking an immutable server snapshot at
start. Include configured servers with encryption enabled and a nonempty host,
including disabled backup servers; skip plaintext servers without modifying
their encryption setting. Reject a start from unsaved server edits, with a
message to save those edits first. Preserve unrelated unsaved browser edits.
Server credentials stay inside the daemon and never enter job responses.

Probe each eligible suite separately using the configured host, port, SNI,
certificate store and certificate-verification level. Reuse the actual NNTP
connection path and validate greeting/authentication without requesting articles.
Offer exactly one suite in exactly its TLS version, check the negotiated version
and suite, and close the probe connection. A successful handshake under a
different suite does not establish compatibility. Ordinary default cipher lists
must not leak into a supposedly pinned TLS 1.2 or TLS 1.3 probe.

Use sequential probes, at most one connection at a time, a maximum ten-second
connection/handshake/NNTP deadline per probe and a ten-minute overall job
deadline. Bound DNS resolution as part of the probe deadline. Check cancellation
between measurement batches and during network waits. Keep unsupported-suite
rejection separate from timeout, DNS, certificate and authentication errors;
ambiguous failures are unknown, not evidence of non-support. If any eligible
candidate for a server remains unknown or unmeasured, do not claim its optimum
is established and leave that server unchanged. Preserve successful compatibility
observations in the report. Other fully tested servers can still receive results.

Choose the highest ranked measured suite among each fully tested server's
accepted suites. Report the common supported suites for the complete fleet only
when all included servers have a complete compatibility result; otherwise mark
that intersection unknown. Do not force a slower common cipher onto a server
that supports a faster one. A server with no eligible supported suite is left
unchanged, with an explanation.

The persisted single-suite value must also constrain the normal download TLS
path to that suite and version. Add a targeted exact-suite path for optimizer
candidates in `TlsSocket`; preserve existing behavior for empty values and
custom colon-separated lists. Cover fallback/version isolation in integration
tests. Saving a cipher that the normal connection path can ignore is a failure.

## Jobs, RPC and configuration transaction

Expose control-account-only start, status and cancel RPCs through the existing
RPC transport. Deny add/restricted accounts and unsafe GET/JSONP entry paths
for all optimizer operations. The client sends no arbitrary host or command.
Use opaque job identifiers, bounded result sizes, one active job per daemon,
and one retained terminal result until a later run replaces it. Repeated status
requests have no side effects. A duplicate start returns the existing active
job, never another benchmark. Cancellation never creates a replacement run.
Admission caps are 256 encrypted servers, 128 eligible suites, 64 distinct bulk
algorithms and a 16 MiB configuration snapshot. Reject an over-cap job before
starting work rather than silently truncating the candidate or server list.
Status responses are at most 1 MiB, with bounded diagnostic strings and no
per-record payloads; per-algorithm five-round samples remain available there.

States are measuring, probing, saving, completed, cancelled and failed.
Report completed with per-server unchanged/error results for partial outcomes.
Daemon shutdown cancels and joins the owned worker before native TLS cleanup.
Never hold a configuration mutex while benchmarking or waiting on a provider.

At commit, compare the saved configuration with the original snapshot under
the same synchronization used by ordinary configuration writes. Any change
invalidates the transaction; save nothing and report the conflict. Serialize
ordinary `saveconfig` with this commit so compare-and-write is meaningful.
Rust prepares a patch containing only accepted `ServerN.Cipher` values.
Apply it to the original complete file, preserving all other bytes, comments,
credentials and permissions. Do not pass a sparse list to existing `saveconfig`,
which removes omitted options. Write a sibling temporary file, check complete
writes/flushes, then atomically replace the config through a platform-supported
operation. Preserve the original on any pre-replacement failure; report storage
and replacement failures as failures. Reject symlink/nonregular configuration
targets rather than silently replacing a different object. Keep file ownership
and platform behavior explicit in the implementation and tests.

Cancellation before the commit changes nothing. Once the atomic commit happens,
report saved even if cancellation arrives afterward. Saving does not restart the
daemon or reconnect active downloads. Use the existing reload-required notice,
and clearly distinguish saved values from active connections. Browser cipher
fields and saved baselines update only for values confirmed committed; unrelated
unsaved changes and their dirty-state indicators remain intact.

## WebUI and error presentation

Place the fleet button near the News Servers section controls. Open an accessible
dialog explaining the brief CPU work, provider connections, automatic cipher-only
save and later reload. Start from the button's explicit user action without a
second approval dialog. Show progress, algorithm rates, compatibility and each
server's old cipher, selected cipher and outcome. Provide Cancel while running
and Close after completion. Closing the dialog does not silently cancel or
restart a job; reopening resumes its status. Prevent misleading double starts.

Use text insertion for server names and native error messages. Keep credentials
out of diagnostics. Follow existing locale conventions, keyboard focus handling
and light/dark styling. Support a bounded horizontally scrollable result table
at phone widths, with access to its final column and final server row.
When Rust or TLS support is absent, disable the action and explain why.

## Validation and local handoff

Before test execution, create a fresh exclusive evidence directory, a frozen
test plan, source/fixture hashes and per-process command metadata with raw
stdout/stderr sinks. Record launch failures, timeout, native exit and all failed
attempts before interpreting output. Preserve evidence outside tracked source;
public reports and screenshots use sanitized examples only.

Rust tests cover candidate filtering, exact sample floors/keys, ranking and ties,
different server support sets, unknown outcomes, no common cipher, cancellation,
duplicate starts, bounded status and configuration conflicts. Native integration
tests use local TLS/NNTP fixture servers with controlled supported suites,
certificates and authentication outcomes. Assert the exact negotiated cipher,
normal-download pinning, version fallback prevention, and failure behavior.
Exercise config byte preservation, permissions, concurrent ordinary saves,
write failures, replacement failures and cancellation around commit.

WebUI checks retain the committed loopback-only guards and intercept mutations
outside the isolated end-to-end test. Cover desktop/phone, both themes, keyboard,
progress/cancel, partial failure, backend absence, escaping, unsaved edits,
reload-required messaging, duplicate starts and final-row/column visibility.
Capture and inspect real sanitized JPEGs from the candidate's actual dialog.
Run relevant existing Settings regressions after the new checks pass.

Heavy native/Rust builds and tests require the designated scheduling owner and
worker admission under the repository's fixed lock namespace and job caps.
Use fresh targets and retain actual build-to-binary lineage. This is new
functionality, not a replacement of an existing C++ implementation; there is no
prior C++ or Rust optimizer baseline to qualify. Existing migration and backend
release holds remain unchanged. Do not manufacture comparative speed claims.

Prepare an isolated loopback local NZBGet instance with its own configuration,
queue/state directories and candidate WebUI/backend. Synthetic providers prove
the feature; they do not prove the user's providers support a particular suite.
Give the user its URL, start/stop instructions, screenshots, evidence summary,
and exact tested source/binary identity. On readiness, speak a short macOS
announcement. Wait for the user's **g2g** before PR creation or the review process.
