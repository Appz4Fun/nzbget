# Rust replacement source inventory

Source commit: `4cf19abdb8f084a384769a15cf57e56acf86f363`; tree: `e6d29b14b9eee1e7400118ac64767030233bd1e0`. Canonical repository: `Appz4Fun/nzbget`; confirmed integration target: `dupe-article-fallback`.

Bounded Git blob reads; lexical public C ABI export and call-like symbol occurrence inventory. Comments, preprocessor branches and dead code can match. No compile, linking, reachability, benchmark, or deployment result inferred. Rust source line counts include test code and comments. No language percentage inferred.

## Snapshot counts

| Measure | Count |
|---|---:|
| rust src files | 50 |
| rust src total lines including tests comments | 24487 |
| c abi exports | 195 |
| c abi exports with cpp call like occurrence | 184 |
| c abi exports without cpp call like occurrence | 11 |
| daemon cpp files | 148 |
| daemon cpp total lines including comments | 87451 |
| daemon cpp with rust call like occurrence | 36 |
| daemon headers | 149 |

## Rust modules

This table records text occurrences only. A module referenced from `ffi.rs` can be reached indirectly, so zero exports in the module does not mean dormant code. Runtime coverage and build configuration remain separate pending evidence.

| Module | Total source lines | C ABI exports defined here | Daemon C++ files mentioning those exports | Other Rust files mentioning this module |
|---|---:|---:|---|---|
| `binrpc` | 1350 | 0 | — | `rust/src/ffi.rs` |
| `bytes` | 64 | 0 | — | `rust/src/binrpc.rs`, `rust/src/decoder.rs`, `rust/src/nzbfile.rs`, `rust/src/parparser.rs`, `rust/src/releasename.rs`, `rust/src/rpcparams.rs`, `rust/src/twin.rs`, `rust/src/urlcoord.rs`, `rust/src/webserver.rs`, `rust/src/webutil.rs` |
| `cmdline` | 820 | 0 | — | `rust/src/ffi.rs` |
| `collection` | 342 | 0 | — | `rust/src/ffi.rs` |
| `crc` | 93 | 0 | — | `rust/src/ffi.rs` |
| `deadpostings` | 122 | 1 | `daemon/dupesearch/DeadPostings.cpp` | — |
| `decode` | 289 | 0 | — | `rust/src/ffi.rs`, `rust/src/rpcparams.rs`, `rust/src/webutil.rs` |
| `decoder` | 691 | 0 | — | `rust/src/ffi.rs` |
| `deobfuscation` | 421 | 0 | — | `rust/src/collection.rs`, `rust/src/ffi.rs` |
| `directrenamer` | 140 | 0 | — | `rust/src/ffi.rs` |
| `donorscore` | 93 | 0 | — | `rust/src/ffi.rs` |
| `dupeidentity` | 464 | 0 | — | `rust/src/ffi.rs` |
| `dupesearch_nzb` | 182 | 2 | `daemon/dupesearch/NzbReader.cpp` | — |
| `dupewatch` | 635 | 0 | — | `rust/src/ffi.rs` |
| `escape` | 160 | 0 | — | `rust/src/ffi.rs` |
| `extload` | 418 | 0 | — | `rust/src/ffi.rs` |
| `feedfilter` | 743 | 0 | — | `rust/src/ffi.rs` |
| `ffi` | 6545 | 190 | `daemon/connect/WebDownloader.cpp`, `daemon/dupesearch/DonorScore.cpp`, `daemon/dupesearch/DupeIdentity.cpp`, `daemon/dupesearch/DupeSearch.cpp`, `daemon/dupesearch/NzbFetcher.cpp`, `daemon/dupesearch/NzbReader.cpp`, `daemon/dupesearch/Posting.cpp`, `daemon/dupesearch/ReleaseName.cpp`, `daemon/extension/ExtensionLoader.cpp`, `daemon/extension/ManifestFile.cpp`, `daemon/feed/FeedFilter.cpp`, `daemon/main/CommandLineParser.cpp`, `daemon/main/Options.cpp`, `daemon/main/Scheduler.cpp`, `daemon/nntp/Decoder.cpp`, `daemon/nntp/NntpConnection.cpp`, `daemon/nntp/StatMeter.cpp`, `daemon/postprocess/CollectionAnalyzer.cpp`, `daemon/postprocess/ParParser.cpp`, `daemon/postprocess/ParRenamer.cpp`, `daemon/postprocess/RarReader.cpp`, `daemon/postprocess/RarRenamer.cpp`, `daemon/queue/Deobfuscation.cpp`, `daemon/queue/DirectRenamer.cpp`, `daemon/queue/NzbFile.cpp`, `daemon/queue/TwinCheck.cpp`, `daemon/queue/UrlCoordinator.cpp`, `daemon/remote/BinRpc.cpp`, `daemon/remote/RemoteClient.cpp`, `daemon/remote/WebServer.cpp`, `daemon/remote/XmlRpc.cpp`, `daemon/util/FileSystem.cpp`, `daemon/util/FileTypes.cpp`, `daemon/util/Util.cpp` | — |
| `filetypes` | 323 | 0 | — | `rust/src/collection.rs`, `rust/src/deobfuscation.rs`, `rust/src/ffi.rs` |
| `fsdelete` | 391 | 0 | — | `rust/src/ffi.rs` |
| `fsops` | 202 | 0 | — | `rust/src/ffi.rs` |
| `json` | 598 | 0 | — | `rust/src/ffi.rs`, `rust/src/manifest.rs`, `rust/src/rpcparams.rs` |
| `lib` | 55 | 0 | — | — |
| `manifest` | 249 | 0 | — | `rust/src/ffi.rs` |
| `nntp` | 359 | 0 | — | `rust/src/ffi.rs` |
| `nzbfile` | 264 | 0 | — | `rust/src/ffi.rs` |
| `options` | 403 | 0 | — | `rust/src/ffi.rs` |
| `parparser` | 114 | 0 | — | `rust/src/directrenamer.rs`, `rust/src/ffi.rs`, `rust/src/parrenamer.rs` |
| `parrenamer` | 482 | 0 | — | `rust/src/ffi.rs` |
| `paths` | 205 | 0 | — | `rust/src/collection.rs`, `rust/src/ffi.rs`, `rust/src/fsops.rs`, `rust/src/parrenamer.rs`, `rust/src/rarrenamer.rs`, `rust/src/twin.rs` |
| `posting` | 190 | 0 | — | `rust/src/ffi.rs` |
| `rarreader` | 942 | 0 | — | `rust/src/ffi.rs` |
| `rarrenamer` | 306 | 0 | — | `rust/src/ffi.rs` |
| `releasename` | 718 | 0 | — | `rust/src/dupeidentity.rs`, `rust/src/dupewatch.rs`, `rust/src/ffi.rs` |
| `renameanalyzer` | 165 | 0 | — | `rust/src/ffi.rs`, `rust/src/parrenamer.rs` |
| `rpcparams` | 562 | 0 | — | `rust/src/ffi.rs` |
| `rpcroute` | 265 | 0 | — | `rust/src/ffi.rs` |
| `scheduler` | 187 | 0 | — | `rust/src/ffi.rs` |
| `statmeter` | 149 | 0 | — | `rust/src/ffi.rs` |
| `streamcompare` | 185 | 1 | `daemon/queue/DupeStreamRepair.cpp` | — |
| `streampatchparts` | 250 | 1 | `daemon/queue/DupeStreamRepair.cpp` | — |
| `text` | 380 | 0 | — | `rust/src/decoder.rs`, `rust/src/ffi.rs`, `rust/src/rpcparams.rs`, `rust/src/urlcoord.rs`, `rust/src/webserver.rs`, `rust/src/webutil.rs` |
| `twin` | 1335 | 0 | — | `rust/src/ffi.rs` |
| `url` | 117 | 0 | — | `rust/src/ffi.rs`, `rust/src/webdownload.rs` |
| `urlcoord` | 111 | 0 | — | `rust/src/ffi.rs` |
| `util` | 525 | 0 | — | `rust/src/binrpc.rs`, `rust/src/directrenamer.rs`, `rust/src/feedfilter.rs`, `rust/src/ffi.rs`, `rust/src/options.rs`, `rust/src/urlcoord.rs`, `rust/src/webserver.rs` |
| `webdownload` | 169 | 0 | — | `rust/src/ffi.rs` |
| `webserver` | 283 | 0 | — | `rust/src/ffi.rs` |
| `webutil` | 203 | 0 | — | `rust/src/ffi.rs`, `rust/src/rpcparams.rs`, `rust/src/rpcroute.rs` |
| `wildmask` | 228 | 0 | — | `rust/src/feedfilter.rs`, `rust/src/ffi.rs`, `rust/src/util.rs`, `rust/src/webserver.rs`, `rust/src/webutil.rs` |

## Exports with no daemon C++ call-like occurrence

These require individual classification as benchmark-only, helper/indirect ABI usage, obsolete, or genuinely unwired. No automatic deletion follows.

- `nzbget_rs_binrpc_encode_history` (rust/src/ffi.rs:4054)
- `nzbget_rs_binrpc_encode_list` (rust/src/ffi.rs:4016)
- `nzbget_rs_binrpc_encode_log` (rust/src/ffi.rs:4034)
- `nzbget_rs_binrpc_encode_post_queue` (rust/src/ffi.rs:4044)
- `nzbget_rs_binrpc_read_files` (rust/src/ffi.rs:4193)
- `nzbget_rs_binrpc_read_nzbs` (rust/src/ffi.rs:4173)
- `nzbget_rs_binrpc_read_params` (rust/src/ffi.rs:4183)
- `nzbget_rs_ext_v1_free` (rust/src/ffi.rs:2064)
- `nzbget_rs_ext_v1_parse` (rust/src/ffi.rs:2018)
- `nzbget_rs_latin1_to_utf8` (rust/src/ffi.rs:509)
- `nzbget_rs_rename_analyzer_free` (rust/src/ffi.rs:3099)

## Corrections to earlier chat estimates

- Stream patch selection invokes Rust for nonempty donor ranges and holes with nonnegative margin, including zero margin and inputs below 4096 holes. The separate coverage floor invokes Rust for nonempty probes and at least 4096 holes in `daemon/queue/DupeStreamRepair.cpp`. These are wired source paths; compiled coverage and recorded performance holds remain unresolved.
- `Crc32::Combine` already routes to Rust in Rust-enabled builds; its historical 135x claim compares a different algorithm. `rust/src/crc.rs` explicitly identifies its later-zlib multiplication method, so qualification requires the same improved algorithm in the fair C++ control.
- `NzbFile` retains libxml2 SAX parsing and C++ queue objects; the 17x duplicate-name claim is not proof that the whole parser or submission path is 17x faster.

The complete machine-readable occurrence locations and immutable Git blob identities are in [source-inventory.json](rust-migration/source-inventory.json).
