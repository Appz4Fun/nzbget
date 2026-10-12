# Porting nzbget to Rust

nzbget moves to Rust one routine at a time. The Rust code lives in `rust/` and
builds as a static library (`cmake/rust.cmake`). C++ calls it through the C ABI
in `rust/include/nzbget_rs.h`.

## Rules

- Each port matches the C++ output byte for byte, quirks included. A behavior
  change is a separate commit.
- Before each swap, a differential fuzz runs the old C++ against the Rust code.
  The C++ version remains as a fallback for platforms without Rust integration.
- Measure before and after; port the hot paths first.

## Done

| C++                                   | Rust                       | Speed-up |
|---------------------------------------|----------------------------|----------|
| `WebUtil::JsonEncode`                 | `escape::json_encode`      | 1.9x     |
| `WebUtil::XmlEncode`                  | `escape::xml_encode`       | 1.6x     |
| `WildMask::Match`                     | `wildmask::wild_match`     | 1.4x     |
| `WebUtil::DecodeBase64`               | `decode::base64_in_place`  | 3.2x     |
| `WebUtil::JsonNextValue`              | `decode::json_next_value`  | 4.5x     |
| `WebUtil::JsonDecode`                 | `decode::json_decode`      | 2.3x     |
| `Crc32::Combine`                      | `crc::combine`             | 135x     |
| `WebUtil::XmlDecode`, `XmlStripTags`, `XmlRemoveEntities`, `HttpUnquote`, `UrlDecode`, `UrlEncode`, `Latin1ToUtf8` | `text` | port only |
| `WebProcessor` header, URL, credential and IP checks | `webserver` | port only |
| `Decoder` (yEnc, UU, raw; rapidyenc kept) | `decoder` | parity |
| `Scheduler::CheckTasks` timing (tasks run in C++) | `scheduler` | port only |
| `XmlCommand` request parameters (`PrepareParams`, `NextParamAsInt/Bool/Str`) | `rpcparams` | port only |
| `XmlRpcProcessor` routing (`Execute` protocol, `Dispatch` method/id/params) and `BuildResponse` envelope | `rpcroute` | port only |
| `Util::SplitCommandLine`, `Trim*`, `SanitizeLine`, `EndsWith`, `FormatBuffer`, `WebUtil::ParseRfc822DateTime` | `util` | port only |
| `ServerVolume::CalcSlots` and `AddStats` slot clearing (StatMeter) | `statmeter` | port only |
| `Options::ParseTime`, `ParseWeekDays`, `ValidateOptionName`, `ConvertOldOption`, `HasScript`, `ParseCategorySource` | `options` | port only |
| `ExtensionLoader::V1` (pre-manifest script headers: kind, about, options, commands, select values) | `extload` | port only |
| `WebDownloader::CheckResponse`, `ProcessHeader`, `ParseRedirect` | `webdownload` | port only |
| `UrlDownloader::ProcessHeader` (X-DNZB headers), `UrlCoordinator::UrlCompleted` statuses | `urlcoord` | port only |
| `NntpConnection` protocol: `Request` (480 re-login), `AUTHINFO USER/PASS`, the greeting, `GROUP` (C++ does the I/O) | `nntp` | port only |
| `CommandLineParser` (getopt over the same argv, the file argument, ID and name lists) | `cmdline` | port only |
| `FileSystem::FileExists`, `DirectoryExists`, `ForceDirectories`, `MakeUniqueFilename`, `ExpandHomePath`, `GetLastErrorMessage` (fixed: XSI strerror_r) | `fsops` | port only |
| `ParParser::ParseParFilename`, `SameParCollection` | `parparser` | port only |
| `RarVolume` header parsing (RAR3/RAR5 blocks, files, encryption records; the source and OpenSSL stay C++) | `rarreader` | port only |
| `RarRenamer::RenameFiles` (sets, proper names, main file, new names; the regex, file checks and moves stay C++) | `rarrenamer` | port only |
| DirectRenamer's `RenameContentAnalyzer` (PAR2 header and set id, MD5 of the first 16 KiB) | `renameanalyzer` | port only |
| DirectRenamer's new names (`BuildNewRegularName`, `BuildNewParName`, `NeedRenamePars`) | `directrenamer` | port only |
| `ManifestFile::Load` (an extension's manifest.json; with a Boost.JSON-compatible parser: strict grammar, depth 32, duplicate keys, Boost's imprecise numbers) | `manifest`, `json` | port only |
| `TestServerXmlCommand`'s JSON body (`Json::Deserialize`, `ParseRequestParams`: value_to<std::string/int/bool>) | `rpcparams`, `json` | port only |
| `ParRenamer::Execute` (par-rename: par2 files by header and set id, regular files by the MD5 of their first 16 KiB, .bad par2 files, missing files; par2 loading, file IO and moves stay C++) | `parrenamer` | port only |
| `FileSystem::DeleteDirectory`, `DeleteDirectoryWithContent`, `RenameBak`, `GetFileExtension` (links never followed, first error kept, errno as before; the file system calls stay C++) | `fsdelete` | port only |
| BinRpc's frame (`BinRpcProcessor::Execute` credential check, request names, `Dispatch` size check, `SendBoolResponse`, `ReceiveTrailing` length check), list responses (List, Log, PostQueue, History: the C++ collects a response's entries under its locks into plain structs, one call encodes them into caller scratch or one owned allocation), EditQueue's trailing data (size check, ids, names), Download's URL test, and the remote client's reading of list responses (`RemoteClient`: the existing single-entry queue reader, the log, post-queue and history listings printed from one call each) | `binrpc` | port; the client stops at an entry that doesn't fit the data, unknown stages and statuses print no text; entry fields a kind doesn't set are 0, a negative Log line count asks for no entries |
| `NzbFile::AddFileInfo` (segments in part order, the declared parts and tail, sizes), `DeclaredParts`, `HasDuplicateFilenames` (one pass instead of every pair); the XML handlers, the queue objects and the filenames stay C++ | `nzbfile` | 17x at 20,000 files |
| `DonorScore::Base`, `Target`, `Rerank` (duplicate scores under a pick; `Ranks` stays C++ and calls `Target`) | `donorscore` | 1.2x |
| `ReleaseName::Clean`, `Normalize`, `ShortQuery`, `Parse`, `Readable`, `SameRelease` (the std::regex patterns matched by hand in the engine's order; C ctype as nzbget sets it) | `releasename` | 2.6x |
| `Posting::MakeSketch`, `SameSketch`, `SamePosting`, `GroupListings`, `ListingMismatch`, `OrderPostings` (CRC-32, stable ordering and first matching listing's rank; file reading and its cache stay C++) | `posting` | 2.3x ordering |

Each port has a differential test in `rust/tests/` that compares it with the
pre-port C++ under ASan and UBSan.

Each port adds representative Rust kernel coverage to rust/benches/ports.rs or
the selective development-only Criterion pilot. Kernel results support
attribution and regression history; they do not qualify a runtime replacement.

Before each replacement, the PR shows matched complete C++/current-Rust/candidate
caller timings and percentage changes for every representative fixture, with raw
samples, verified observable output, immutable source/compiler/binary/input
hashes and reproduction instructions. Include the real external C++/FFI call
boundaries, allocation, mutable input clone/reset and ownership/destruction costs.
Retain original and stronger optimized C++ controls, slower rows, unchanged-control
drift and layout/host uncertainty. The replacement must be independently faster
than the C++ it replaces and preserve existing Rust caller performance where
already ported. Missing or inconclusive complete-caller evidence is HOLD; rework
or hold/split slower functions instead of advancing a broad patch.

Bencher's inherited 10% historical regression alert is monitoring only, never a
migration waiver. Passing that alert is not proof that a replacement is faster.
The historical figures above describe their recorded fixtures, not standing
approval for later changes. New shared qualification defaults apply
prospectively; partial legacy archives retain unknown fields and raw rows rather
than inventing native v1 evidence.

See rust/benches/README.md for the shared remote runner, resource-lock order,
schema, whole-process paired statistics, Criterion limits, data-only trusted
publication and verified xbmc4lyfe identity. Current Bencher configuration is
absent and publication ready=false; workflow definitions or a signed evidence
commit alone do not establish activation or attest a measurement.

## Native duplicate discovery

`dupeidentity` reads bounded RAR4/RAR5 first-article headers or a bare media
file's yEnc size. It rejects samples, unknown sizes, encrypted headers and
conflicting release names. The daemon retains article transport and queue
ownership. `DupeSameSize` hints compare data-file counts and bytes independently
of parity overhead; existing and newly discovered backups use the same rule.
The hints select candidates for the existing checksum validation, rather than
establishing byte identity.

`dupewatch` owns queue/history eligibility, repeat-search suppression, broader
queries, a shared atomic fetch budget, partial-NZB health normalization and PAR2
repairability estimates. The daemon retains queue locks, HTTP/NNTP transport and
the existing failover controller. A search shares one deadline and a budget of
three HTTP attempts per configured donor across strict and broader passes; zero
keeps the existing unlimited mode. Broader candidates need conservative release
compatibility and matching decoded packed-media identity. Generated duplicate
keys follow renamed picks only when the persisted per-NZB ownership marker
matches; client key edits clear that marker. Explicit client keys remain intact. Empty searches
can retry without losing the title needed to recognize generated keys, while a
usable existing backup suppresses those retries.

The offline differential test compares the pure Python proxy reference with
Rust. It deliberately never imports proxy configuration or performs indexer
requests. The watcher differential suite likewise runs only local pure-function
fixtures. Isolated fake NNTP/Newznab functional scenarios exercise broader
identity proof, data-only hints and rename tracking. The Bencher suite includes
identity, queue decisions, broader queries and partial health normalization.

The source-extracted pre-port `Prepare` prefix matches 184,320 C++ ASan/UBSan
fixtures. A separate same-feature C++ control performs the required identity,
cache, ownership, fleet and history work with the faithful pre-port C++
normalizer and an independent allocation-free policy. This control is a
counterfactual implementation, not the old production controller. Parity checks
cover normalization, signed-time extremes, ownership and active/retired fleets.

Decision-prefix measurements include normalization, runtime name-cache work,
peer/history snapshots, allocation and the real Rust C ABI. Both callers stop
before accepted-search stamp writes, edits, saving, packed-media proof and
transport. Cold/restart and warm eligible/cooldown fixtures are measured under
the exclusive shared-worker lock. Prebuilt snapshots separately compare the
best direct C++ policy with Rust; a second opaque C++ translation-unit experiment
makes the ABI boundary comparable. Generic lower-score peer snapshots are valid
API stress cases, while the production caller normally filters those
peers before the call. These are synthetic fixtures, not deployment measurements.

Earlier comparisons against the old production controller perform different
work and are retained only as historical experiments. The context-bearing old
C++ policy prefix and the scalar Rust function also have different boundaries;
their timings do not establish a language speedup. Wrapper experiments are kept
separate from the best direct C++ control. Final gates use paired changes for
each row and retain slower and noisy results.

Later complete `PrepareNative` measurements use the actual native library,
metadata, collection, logging and isolated state/progress writes. The alternative
C++ controller changes only watch/normalization boundaries; existing `SameRelease`
remains shared production behavior. Tiny (2 live/0 history), normal (4/2) and large
(128/1024) fixtures pass 28 parity cases, including generated-key cold/warm writes.
Ordinary optimized C++ policy remains machine-outlined; no control is handicapped.
Five alternating process pairs preserve every sample. A second fixed experiment
removes backend-specific normalization from untimed fixture resets/assertions and
uses a new composed archive; differences cannot be attributed to that repair alone.
Its paired medians still show tiny warm IO +4.97%, generated warm IO +4.44% and
large warm IO +1.94%. The candidate remains held; no overall faster claim follows.
Matched IO bytes do not independently prove every atomic write or fsync succeeded.
Full raw process pairs and compiler/source provenance are retained in PR #80.

Restarted searches bind donor proof to the original title, key and posting
fingerprint; changed/unbound saved state is searched again. Legacy three-field
stamps refresh once and preserve ambiguous client keys; only an independently
persisted per-NZB marker proves generated ownership. Manual name edits notify only the watcher,
while DirectRename retains its queue-script event. Inferred absent parts mark
unusable donors dead, including fast additions and existing history members.
Generated keys and managed score floors persist without client edits.

## Parked

- NZB parsing (`NzbFile::Parse`, libxml2 SAX1): a Rust parser that matches
  libxml2's callbacks exactly. All 5,929 NZBs on the test server plus 9,000
  mutated documents match or are left to libxml2. It is still about 25%
  slower than libxml2 on a 17.6 MB NZB, so it is not merged.

## Next

1. The rest of `WebUtil` and `Util`: RFC 822 dates, URL parsing,
   `Util::MatchFileExt`, `SplitCommandLine`, `Tokenizer`, size and speed
   formatting.
2. JSON/XML-RPC response building (`XmlRpc.cpp`), then the RPC server.
3. Queue state files (`DiskState`).
4. The download path (NNTP connection, article writer), then queue and
   post-processing. Each step leaves nzbget a working program.

## Build and verification

Native POSIX builds use Rust when Cargo, rustc, and the target standard library
are available; otherwise they retain the C++ encoders. Debug selects Cargo's dev
profile; other CMake configurations select release. Cargo is invoked on each build to track its own
sources, lockfile, build scripts, and configuration. Both the daemon and test
executable inherit the archive and Rust's native link dependencies.
Static executable builds select Rust's static CRT dependencies as well.

Windows keeps the original C++ encoders, so its existing build does not acquire a
Rust dependency. Non-macOS cross builds also keep C++ unless a matching target is
provided with `-DNZBGET_RUST_TARGET=<triple>`. macOS selects the target from the
CMake architecture and forwards `CMAKE_OSX_DEPLOYMENT_TARGET`. Install the Rust
standard library for the chosen target to enable Rust for that architecture.
An explicit `NZBGET_RUST_TARGET` requires a working Rust toolchain and standard
library; a missing dependency is an error rather than an automatic fallback.

Run `cargo test --release` in `rust/` for encoder and FFI tests. On POSIX with a
C++ compiler supporting ASan/UBSan, run `python3 rust/tests/differential.py` from
the repository root for a deterministic comparison against the exact encoder
bodies in commit `78dcb938`. This covers arbitrary bytes, embedded NULs, invalid
continuations, truncations, and out-of-range code points.
