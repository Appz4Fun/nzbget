# Rust caller and C++ deletion boundaries

Source: `4cf19abdb8f084a384769a15cf57e56acf86f363`; tree: `e6d29b14b9eee1e7400118ac64767030233bd1e0`. All 36 daemon C++ files with call-like Rust symbols in the reviewed inventory are represented.

Manual caller ownership inspection over the 36 files from the reviewed lexical inventory. Modules listed can include their internal dependencies. This is not a compiler-derived call graph or executed boundary coverage; no speed/deployment claim follows. Correctness-entrypoint availability is source presence only, not an executed check.

## Build and route selection

- `cmake/posix.cmake:128` includes the optional Rust integration. `cmake/rust.cmake` selects a supported Cargo/rustc/target configuration and adds `NZBGET_USE_RUST` through the Rust interface target. Its return paths keep C++ when implicit Rust selection is unavailable.
- The current `cmake/windows.cmake` does not include `cmake/rust.cmake`; current Windows builds retain C++ paths. Mandatory supported Rust target/build wiring remains part of full migration.
- `rust/src/fsops.rs` is gated by `cfg(unix)` in `rust/src/lib.rs`; filesystem callers also retain native-stat ABI/error behavior in C++ callbacks. A Windows filesystem port and real target-width validation are required before deleting that support.
- Direct rename content analysis requires `NZBGET_USE_RUST` and enabled PAR checking. Custom-locale PAR names still format through the C++ stringstream callback; classic-locale results do not prove that callback can be removed.
- Stream compare floor uses Rust only for nonempty probes/holes with at least 4096 holes. Small inputs and no-probe/no-hole branches remain C++; tests must observe each branch independently. PatchParts already invokes Rust in a Rust-enabled build.
- Filename/header Latin1 routines in `rust/src/webutil.rs`/`rust/src/urlcoord.rs` and Rust text helpers may bypass the optimized C++ WebUtil wrapper; qualifying that wrapper cannot qualify those callers.

## Complete deletion units

Each row has an existing Rust-backed operation and C++ work that remains. Replacement of a Rust kernel or deletion of a fallback alone does not complete the row. Listed checks cover partial operations; new complete-operation parity checks must include the retained C++ work before deletion. Exact ABI reference locations and original source blobs remain in [source-inventory.json](source-inventory.json).

| ID / C++ source | Rust-owned operation | C++ work still required | Available partial check source |
|---|---|---|---|
| B01 / `daemon/connect/WebDownloader.cpp` | HTTP response/header/redirect decisions (`webdownload, url`) | Connection I/O, body/file writes, warnings and downloader lifecycle | `rust/tests/webdownload_differential.py` |
| B02 / `daemon/dupesearch/DeadPostings.cpp` | Persisted-record text parsing (`deadpostings`) | File reads, mutex-protected records, prune/save and time handling | `rust/tests/deadpostings_cpp_differential.py` |
| B03 / `daemon/dupesearch/DonorScore.cpp` | Base/target scores and reranking (`donorscore`) | C++ donor snapshots/results and Ranks caller | `rust/tests/donorscore_differential.py` |
| B04 / `daemon/dupesearch/DupeIdentity.cpp` | Inner identity and conservative health/PAR decisions (`dupeidentity, dupewatch, twin, releasename`) | Article transport, C++ metadata, health snapshots and caller decisions | `rust/tests/dupeidentity_differential.py` |
| B05 / `daemon/dupesearch/DupeSearch.cpp` | Watch/stamp decision, broader query text and expansion decision (`dupewatch, releasename`) | Queue/history locks, searches, transport, caching, state/progress writes and failover orchestration | `rust/tests/dupewatch_cpp_differential.py` |
| B06 / `daemon/dupesearch/NzbFetcher.cpp` | Shared atomic HTTP fetch budget (`dupewatch`) | HTTP fetch, admission/cooldown persistence, donor-health checks and C++ stats | `rust/src/dupewatch.rs` (module tests; complete fetch caller coverage pending) |
| B07 / `daemon/dupesearch/NzbReader.cpp` | Subject/PAR-name classification and part geometry (`dupesearch_nzb, dupewatch`) | libxml2 XML parse, C++ summary ownership and transport caller | `rust/tests/dupesearch_nzb/README.md` |
| B08 / `daemon/dupesearch/Posting.cpp` | Sketches, comparisons, grouping and ordering (`posting`) | SketchOfFile I/O/cache/mutex, input/output conversions and listing ownership | `rust/tests/posting_differential.py` |
| B09 / `daemon/dupesearch/ReleaseName.cpp` | Clean/normalize/parse/compatibility routines (`releasename`) | C++ string allocation and conversion of serialized attributes to sets/vectors | `rust/tests/releasename_differential.py` |
| B10 / `daemon/extension/ExtensionLoader.cpp` | V1 script header parsing (`extload`) | Script discovery, C++ line-read callback, item copies and extension registry | `rust/tests/extload_differential.py` |
| B11 / `daemon/extension/ManifestFile.cpp` | Manifest JSON grammar and interpretation (`manifest, json`) | C++ file read, copy callback, object containers and exception translation | `rust/tests/manifest_differential.py` |
| B12 / `daemon/feed/FeedFilter.cpp` | Filter parse/match decisions (`feedfilter, wildmask`) | Feed item getter/mutator callbacks, regex engine/capture callbacks, locale folding and filter lifecycle | `rust/tests/feedfilter_differential.py` |
| B13 / `daemon/main/CommandLineParser.cpp` | CLI option/list parse (`cmdline`) | C++ argv/result ownership and native getopt interface invoked by the Rust parser | `rust/tests/cmdline_differential.py` |
| B14 / `daemon/main/Options.cpp` | Selected time/day/name/conversion/category routines (`options`) | Main configuration loading, validation callbacks, registry and mutation | `rust/tests/options_differential.py` |
| B15 / `daemon/main/Scheduler.cpp` | Task time-matching (`scheduler`) | Snapshot/result adaptation, task execution and scheduler state | `rust/tests/scheduler_differential.py` |
| B16 / `daemon/nntp/Decoder.cpp` | Stateful yEnc/UU/raw protocol processing (`decoder`) | Decoder lifecycle adapter, enabled rapidyenc decode/CRC callbacks and downstream article writer | `rust/tests/decoder_differential.py` |
| B17 / `daemon/nntp/NntpConnection.cpp` | Handshake/auth/request/group protocol decisions (`nntp`) | Network/TLS I/O, line-buffer callbacks, reporting and exception translation | `rust/tests/nntp_differential.py` |
| B18 / `daemon/nntp/StatMeter.cpp` | Volume-slot arithmetic and clearing/addition (`statmeter`) | Stat collection, volume objects, time source, persistence and locks | `rust/tests/statmeter_differential.py` |
| B19 / `daemon/postprocess/CollectionAnalyzer.cpp` | Collection classification, name/rename planning (`collection, deobfuscation, filetypes, paths`) | Recursive filesystem walk, metadata/error handling, UTF-8 conversion, sniffing and result ownership | `rust/tests/collection_differential.py` |
| B20 / `daemon/postprocess/ParParser.cpp` | PAR filename and same-collection classification (`parparser`) | Filename locale-fold callback and surrounding PAR parser/file ownership | `rust/tests/parparser_differential.py` |
| B21 / `daemon/postprocess/ParRenamer.cpp` | Rename control decisions (`parrenamer, renameanalyzer, parparser`) | C++ PAR loading, file/hash callbacks, filesystem mutation, errors and reporting | `rust/tests/parrenamer_differential.py` |
| B22 / `daemon/postprocess/RarReader.cpp` | RAR3/RAR5 header interpretation (`rarreader`) | Content-source reads, OpenSSL decrypt callbacks, C++ file results and exception/cleanup behavior | `rust/tests/rarreader_differential.py` |
| B23 / `daemon/postprocess/RarRenamer.cpp` | File-set naming and rename selection (`rarrenamer`) | Regex/metadata/filesystem callbacks, C++ result ownership and logging | `rust/tests/rarrenamer_differential.py` |
| B24 / `daemon/queue/Deobfuscation.cpp` | Obfuscation classification and title transformation (`deobfuscation`) | Rust-result to C++ string ownership and original non-Rust fallback | `rust/tests/deobfuscation_differential.py` |
| B25 / `daemon/queue/DirectRenamer.cpp` | Name selection, classic-locale PAR formatting and content analysis (`directrenamer, renameanalyzer`) | Queue objects, file-existence/hash getters, custom-locale C++ formatting, exception translation and rename events | `rust/tests/directrenamer_differential.py` |
| B26 / `daemon/queue/DupeStreamRepair.cpp` | PatchParts and floor only for the selected large-input route (`streampatchparts, streamcompare`) | Small/no-probe/no-hole floor bypasses, remaining range/probe/donor/job logic and C++ buffers | `rust/tests/streamcompare.md` |
| B27 / `daemon/queue/NzbFile.cpp` | Declared parts, per-file totals and duplicate filenames (`nzbfile`) | libxml2 SAX handlers, queue FileInfo/ArticleInfo objects, subject/password parsing and caller ownership | `rust/tests/nzbfile_differential.py` |
| B28 / `daemon/queue/TwinCheck.cpp` | PAR/NZB signatures, fingerprints, persisted store and matching (`twin`) | Queue coordination, article/provider I/O, C++ adapters and failover integration | `rust/src/twin.rs` (module tests; complete caller coverage pending) |
| B29 / `daemon/queue/UrlCoordinator.cpp` | X-DNZB header normalization and completion status decisions (`urlcoord, text`) | Downloader lifecycle, queue metadata mutations, URL scheduling and persistence | `rust/tests/urlcoord_differential.py` |
| B30 / `daemon/remote/BinRpc.cpp` | Frame validation and response entry encoding (`binrpc`) | Socket transport, collection under locks, scratch/adapters, command execution and protocol dispatch lifecycle | `rust/tests/binrpc_lists_differential.py` |
| B31 / `daemon/remote/RemoteClient.cpp` | Queue entry parse and rendered list text (`binrpc`) | Socket receive, payload lifetime, actual formatted stdio emission and client orchestration | `rust/tests/binrpc_client_differential.py` |
| B32 / `daemon/remote/WebServer.cpp` | Header/URL/credential/IP checks (`webserver`) | HTTP I/O/server lifecycle, tokens/config state, static-file/compression/RPC responses and logging | `rust/tests/webserver_differential.py` |
| B33 / `daemon/remote/XmlRpc.cpp` | Parameter parsing, protocol/routing decisions and response envelope (`rpcparams, rpcroute, json`) | C++ command objects, JSON response payload assembly, queue operations and output ownership | `rust/tests/rpcroute_differential.py` |
| B34 / `daemon/util/FileSystem.cpp` | Selected POSIX file/path/deletion routines (`fsops, fsdelete, paths`) | Native stat ABI callbacks, deletion/rename adapters, unported filesystem operations and Windows fallbacks | `rust/tests/fsops_differential.py` |
| B35 / `daemon/util/FileTypes.cpp` | Extension/magic classification (`filetypes`) | C++ sniff-file reads and path/string wrapper ownership | `rust/tests/filetypes_differential.py` |
| B36 / `daemon/util/Util.cpp` | Selected text/URL/format/wildcard/CRC routines (`escape, decode, text, webutil, util, url, wildmask, crc`) | CString/string adapters, locale callbacks, regex and other unported utility bodies | `rust/tests/textutil_differential.py` |

## Eleven exports without call-shaped C++ references

Two are live source-level deleter registrations and were missed by the deliberately narrow call-shaped occurrence scan. They must remain in the ownership contract until the corresponding C++ object is replaced.

| Export | Static classification |
|---|---|
| `nzbget_rs_ext_v1_free` | C++ function-pointer deleter at `daemon/extension/ExtensionLoader.cpp:108` |
| `nzbget_rs_rename_analyzer_free` | C++ function-pointer deleter at `daemon/queue/DirectRenamer.cpp:63` |
| `nzbget_rs_binrpc_encode_history` | Owned-buffer encoder API retained; daemon selects the caller-scratch _into variant. |
| `nzbget_rs_binrpc_encode_list` | Owned-buffer encoder API retained; daemon selects the caller-scratch _into variant. |
| `nzbget_rs_binrpc_encode_log` | Owned-buffer encoder API retained; daemon selects the caller-scratch _into variant. |
| `nzbget_rs_binrpc_encode_post_queue` | Owned-buffer encoder API retained; daemon selects the caller-scratch _into variant. |
| `nzbget_rs_binrpc_read_files` | Bulk reader API with Rust regression coverage; no direct daemon call identified. |
| `nzbget_rs_binrpc_read_nzbs` | Bulk reader API with Rust regression coverage; daemon uses the single-entry reader in the current queue-list path. |
| `nzbget_rs_binrpc_read_params` | Bulk reader API with Rust regression coverage; no direct daemon call identified. |
| `nzbget_rs_ext_v1_parse` | Buffer parser API retained; daemon selects the callback-based ext_v1_read path. |
| `nzbget_rs_latin1_to_utf8` | Rust-owned buffer API retained; C++ WebUtil selects the caller-owned _n API, while Rust header callers call text routines directly. |

None of these classifications authorizes deleting an API from ABI/test consumers. The nine compatibility exports are not evidence that their whole Rust modules are dormant.

## Qualification applicability

- Corresponding current Rust routes need independently preserved `rust_current` controls as well as original and equally improved C++. C++-only or bypassed routes need a source-bound reviewed nonapplicability decision rather than omission of the Rust preservation gate.
- Reuse of a differential script here means its source is present. The exact integrated source, archive, callers and enabled routes still need bounded correctness execution before timing.
- Current default changes after `cbda2e4f` altered caller/build/dependency inputs while leaving the 50 Rust source files unchanged. Those unchanged module blobs do not establish binary lineage, coverage, or transferable performance qualification.
- No source row is yet checked off as a completed C++ deletion; measured priority and the >=2x campaign gate remain pending.

## Next runtime admission

The integration coordinator assigned this lane the `ArticleDownloader` decode/check/write and `ArticleWriter` data-plane comparison. Prepare an isolated source-bound harness and exact bounded payload first; heavy validation, profiling and timing still require scheduling-owner admission and coordinator grant. The recovered four-NZB loopback evidence identifies health scheduling as that fixture's largest observed cost, not article-decoder throughput. Do not select a production replacement based only on archive names, source identity, or historical kernel multipliers; production edits wait for the assigned initial measurements.
