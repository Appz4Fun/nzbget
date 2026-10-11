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
| BinRpc's frame (`BinRpcProcessor::Execute` credential check, request names, `Dispatch` size check, `SendBoolResponse`, `ReceiveTrailing` length check), list responses (List, Log, PostQueue, History entries), EditQueue's trailing data (size check, ids, names), Download's URL test, and the remote client's reading of list responses (`RemoteClient` entries, the log, post-queue and history lines) | `binrpc` | port; the client stops at an entry that doesn't fit the data, unknown stages and statuses print no text; entry fields a kind doesn't set are 0, a negative Log line count asks for no entries |
| `NzbFile::AddFileInfo` (segments in part order, the declared parts and tail, sizes), `DeclaredParts`, `HasDuplicateFilenames` (one pass instead of every pair); the XML handlers, the queue objects and the filenames stay C++ | `nzbfile` | 17x at 20,000 files |
| `DonorScore::Base`, `Target`, `Rerank` (duplicate scores under a pick; `Ranks` stays C++ and calls `Target`) | `donorscore` | 1.2x |
| `ReleaseName::Clean`, `Normalize`, `ShortQuery`, `Parse`, `Readable`, `SameRelease` (the std::regex patterns matched by hand in the engine's order; C ctype as nzbget sets it) | `releasename` | 2.6x |
| `Posting::MakeSketch`, `SameSketch`, `SamePosting`, `GroupListings`, `ListingMismatch`, `OrderPostings` (CRC-32, stable ordering and first matching listing's rank; file reading and its cache stay C++) | `posting` | 2.3x ordering |

Each port has a differential test in `rust/tests/` that compares it with the
pre-port C++ under ASan and UBSan.

Each port also adds its hot function to `rust/benches/ports.rs`, and its pull
request shows the C++ time, the Rust time and the percentage change. A Rust port
more than 10% slower than the C++ it replaces is optimized further before it is
merged; a slowdown that can't be removed is explained in the pull request. CI
tracks the benchmarks with Bencher (see `rust/benches/README.md`).

## Native duplicate discovery

`dupeidentity` reads bounded RAR4/RAR5 first-article headers or a bare media
file's yEnc size. It rejects samples, unknown sizes, encrypted headers and
conflicting release names. The daemon retains article transport and queue
ownership. `DupeSameSize` hints compare data-file counts and bytes independently
of parity overhead; existing and newly discovered backups use the same rule.
The hints select candidates for the existing checksum validation, rather than
establishing byte identity. The broader discovery integration follows separately.

The offline differential test compares the pure Python proxy reference with
Rust. It deliberately never imports proxy configuration or performs indexer
requests. The Bencher suite includes the new identity function.

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
