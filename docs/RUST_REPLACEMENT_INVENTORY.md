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
| Rust test C++ implementations | 7 |
| Rust test C++ include fragments | 2 |
| Rust test Python drivers | 63 |
| public Rust C ABI headers | 2 |

The supplemental test audit binds all nine checked-in C++ implementations/fragments and all 63 Python drivers individually in `source-inventory.json`, with unchecked dispositions in `RUST_MIGRATION_STATUS.md`. Python can emit, build, import or orchestrate C++ references; absence of a literal include is not proof of independence. These sources match both the original inventory commit and supplemental audit commit `7d3d6412f93cd43452f1b390b4ed705c7691df54`. Their presence does not establish current harness build readiness or native execution. Preserve differential contracts and historical oracles, translate required regressions to Rust, and retire the C++ test/build paths before marking final removal complete.

Both public boundary headers, `rust/include/nzbget_rs.h` and `rust/include/nzbget_rs_dupesearch_nzb.h`, also have individual immutable bindings and unchecked ABI/ownership dispositions. Header presence is not compiled ABI validation.

## Reproduce the lexical derivation

Use a supported POSIX Python environment (macOS, Linux, or WSL) with `O_DIRECTORY`, `O_NOFOLLOW`, and directory-relative `os.open`. Native Windows Python is unsupported; run from a WSL checkout instead. This source verifier requirement does not establish native Windows runtime/build coverage.

Run `python3 docs/rust-migration/verify_inventory.py --inventory docs/rust-migration/source-inventory.json` from the repository root. The inventory records the verifier's version and SHA-256. Version 7 limits Git tree requests to the declared source roots and streams output through a 2 MiB stdout cap, 4,096-entry cap, 64 KiB stderr cap and 30-second deadline before constructing tables, with owned-child kill/reap and pipe cleanup on failures. It separately verifies all 77 ancillary Rust-test input declarations and preserves the 70 Latin1 historical evidence artifacts and Cargo allocation regression without interpreting their recorded claims. It rejects duplicate JSON object members at every nesting level and nonstandard JSON constants, validates every supplemental row against its complete supported schema and constant readiness/disposition values, and requires supported inventory schema version exactly integer `1` (not missing, boolean, float or unknown), checks the supported inventory key set and method/functional source declarations plus the exact supported derivation key set/types/values (capture declaration, canonical reproduction invocation, scope and working-directory label included), disables Git replacement objects for every Git read, requires main and supplemental source IDs to name commit objects before accepting tree identities, rejects symlinked path components through pinned directory descriptors, verifies and returns the exact derived summary key set/types/counts, preserves the recovered original export/call/module regex rules, verifies every derived field/count against immutable Git objects, and checks supplemental source sets/blobs and Python literal classifications. Recovery of the original commands was retrospective; the verifier is preserved as reproducible source, without describing old generation as prospectively recorded. Earlier version 1 and its unsupported-schema acceptance, version 2 before commit-object rejection, version 3 before ancestor-symlink and summary-key rejection, version 4 before complete derivation-contract and replacement-object rejection, version 5 before complete supplemental-row and duplicate-member rejection, and version 6 before bounded tree collection and complete ancillary-input preservation, are retained in signed history and negative evidence.

The export pattern matches public optionally unsafe `extern "C"` functions named `nzbget_rs_*`; C++ call-like occurrences match a word boundary, that symbol, optional whitespace and `(`. Module cross-references match `crate::` followed by the Rust filename stem; `ffi`/`lib` cross-reference scans are excluded. Line counts use UTF-8 source `splitlines()` and include comments/tests. Supplemental Python flags match include/build/artifact literals; they are not a transitive dependency graph. The exact regexes, path/size limits and type-preserving comparisons are in [verify_inventory.py](rust-migration/verify_inventory.py). Manual boundary/dependency descriptions still require independent source review. The command reads local Git objects and metadata; it builds/runs no native code and does not rewrite the inventory.

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
- `TwinCheck` disables twin labels and content matching without Rust (`#else` in `daemon/queue/TwinCheck.cpp`); remaining legacy C++ PAR-repair helpers do not supply equivalent feature behavior. A non-Rust build cannot qualify a twin feature speed comparison by omitting that work.
- `DupeIdentity` returns empty identity/fetch results and constant missing/PAR decisions without Rust, with simplified health/matching fallbacks. `DupeSearch` also omits native preparation/ranking/Expand work. These are not equivalent C++ controls; the boundary map records feature absence separately from retained C++ work.

The complete machine-readable occurrence locations and immutable Git blob identities are in [source-inventory.json](rust-migration/source-inventory.json).

## Separately indexed functional sources

The original508 immutable bindings and13 metrics remain unchanged; version5 adds40 checked-in `tests/functional` source inputs and two derived counts (all40 and nine `dupefallback` inputs), giving548 source bindings and15 derived metrics. This source audit is separately recorded; original generation recovery remains retrospective. The nine fallback inputs comprise the real-daemon harness, generator, four focused tests and Local/Linux-Docker/Android runners. Preserve their stream/live/retry/encrypted/decompression/cleanup and surrounding daemon contracts; translate assertions/setup before native source/build retirement. These are source-presence statements, not executed checks, current binary or Rust-route proof, supported-platform readiness, equivalent C++ control or speed. The derivation verifier enforces the supported declaration, while authenticating capture events and manual operation/dependency annotations remains an independent review requirement.

## Ancillary Rust test and evidence preservation

All 149 tracked `rust/tests` inputs are now represented: nine C++ sources/fragments, 63 Python drivers and 77 ancillary inputs. The latter comprise 70 checked-in Latin1 evidence files, one Rust integration test and six documentation/ignore inputs. All are identical in the original source commit, supplemental audit commit and reachable source. Their independent original-byte bindings and pending preservation gates cover raw before/after logs, fixture/artifact hashes, metadata, summaries, review verdict and encoded reviewed runtime patch. These are retained historical artifacts, not a new replay or current performance decision. Original 548 bindings and 15 metrics are preserved; the expanded inventory has 625 bindings and 18 derived metrics.
