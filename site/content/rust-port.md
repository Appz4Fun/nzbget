+++
title = "Rust port status"
nav_title = "Rust port"
description = "How RustyGet moves from C++ to Rust one module at a time, which modules are already in Rust, and the remaining checklist toward zero C++."
eyebrow = "Reference"
generated = "porting"
lede = "RustyGet replaces NZBGet's C++ with Rust one module at a time, while the program stays in daily use. Each step keeps the output identical, so the rewrite never trades correctness for progress."
+++

## How the port works

The Rust code lives in `rust/` as a library crate that builds into the same binary. C++ calls it through a C interface declared in `rust/include/nzbget_rs.h`. Over time, more of the program moves behind that interface, until the C++ is only glue and then gone.

<ol class="steps">
<li><strong>Pick a module.</strong> Hot paths first, measured with real downloads. Whole modules are preferred over single functions.</li>
<li><strong>Port it byte for byte.</strong> The Rust code reproduces the C++ output exactly, quirks included.</li>
<li><strong>Prove it.</strong> A differential test links the old C++ and the new Rust side by side and feeds both the same inputs. Every run includes random and mutated inputs. The tests run under AddressSanitizer and UndefinedBehaviorSanitizer.</li>
<li><strong>Review it.</strong> Each port is a pull request with an automated review, fixed until it's clean.</li>
<li><strong>Ship it.</strong> The port is squash-merged as one signed commit and goes into daily use.</li>
</ol>

When a port finds a bug in the C++ code, the port keeps the bug, and the fix follows as a separate commit. Bugs found this way include an error message that glibc left empty, and a RAR header parser that kept going on a block that doesn't advance.

The C++ version of each ported routine stays behind `NZBGET_USE_RUST`, so builds without Rust still work during migration. Removing those fallbacks is a separate final phase below. New features, such as twin detection, exist only in Rust.

<!-- vale Google.Headings = NO -->
## Zero C++ checklist
<!-- vale Google.Headings = YES -->

This is the remaining-work inventory, checked against source revision `29fdbe88`. The [app source list](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/daemon/sources.cmake), headers, Rust call boundaries, dependency definitions, and platform packaging define its scope. Keep this inventory current when adding code or dependencies. The [per-file migration inventory](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/docs/RUST_MIGRATION_STATUS.md), [caller boundary map](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/docs/rust-migration/BOUNDARY_MAP.md), and [dependency retirement audit](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/docs/rust-migration/DEPENDENCY_RETIREMENT.md) retain detailed evidence and existing holds; this checklist doesn't change their qualification or ownership gates.

The module table below lists Rust code that exists. A listed module can replace only selected routines: C++ can still own its objects, locks, transport, callbacks, and callers. A module's presence or a benchmark result doesn't complete a checklist item.

Track three milestones separately:

1. **App:** no project-owned C++ in the daemon, clients, or retained companion programs.
2. **Linked dependencies:** no C++ in the executable or libraries it loads, including transitive dependencies, static archives, and optional libraries.
3. **Distribution:** no bundled C++ helper executables or required C++ runtime components in supported release artifacts and container images.

All items start open. An open item can contain Rust code already; it means the whole remaining boundary hasn't been retired. Update the checkboxes in this page's source, with the reviewed commit or pull request and qualification evidence beside each completed item. The rendered checkboxes are read-only. Complete an item only after its C++ paths and fallbacks are removed from the retained scope. A proposed port, open pull request, feature that is turned off, or unused Rust replacement doesn't qualify. Explicitly record any approved feature or platform retirement.

### Startup, configuration, and runtime ownership

- [ ] Replace the entry point and app startup, reload, shutdown, signal handling, and global object ownership (`main/nzbget.cpp`).
- [ ] Finish options loading, validation, defaults, categories, server settings, configuration writes, and reload behavior (`main/Options.*`); the Rust value parsers cover only part of this area.
- [ ] Replace remaining command-line execution and remote-client dispatch around the Rust argument parser (`main/CommandLineParser.*`).
- [ ] Replace runtime work state, disk-space monitoring, maintenance and update operations, and stack traces (`main/WorkState.*`, `DiskService.*`, `Maintenance.*`, `StackTrace.*`).
- [ ] Replace scheduler ownership, task execution, cancellation, and shutdown (`main/Scheduler.*`); Rust timing decisions alone don't complete the scheduler.

### Connections and article downloads

- [ ] Replace socket ownership, DNS, connection lifecycle, TLS integration, HTTP transport, and network-speed tests (`connect/Connection.*`, `TlsSocket.*`, `HttpClient.*`, `NetworkSpeedTest.*`).
- [ ] Finish HTTP downloads, redirects, body handling, retries, cancellation, and file output (`connect/WebDownloader.*`); header and status decisions are already partly in Rust.
- [ ] Replace NNTP socket I/O, connection state, server selection, connection pools, limits, and retry/failover ownership (`nntp/NntpConnection.*`, `NewsServer.*`, `ServerPool.*`).
- [ ] Replace article download/fetch workers and their queue interactions, cancellation, and lifetimes (`nntp/ArticleDownloader.*`, `ArticleFetcher.*`).
- [ ] Replace article writing, buffering, allocation, partial-file handling, assembly, and durable completion (`nntp/ArticleWriter.*`).
- [ ] Remove C++ decoder wrappers and callbacks; qualify the retained yEnc/CRC backend separately (`nntp/Decoder.*`).
- [ ] Finish statistics accumulation, persistence, synchronization, and speed/volume accounting (`nntp/StatMeter.*`); Rust slot arithmetic is only part of it.

<!-- vale Google.Headings = NO -->
### NZB intake, queue, history, and persistence
<!-- vale Google.Headings = YES -->

- [ ] Replace NZB XML parsing and its callbacks, object construction, filenames, and error handling (`queue/NzbFile.*`). The parked Rust XML parser isn't an adopted replacement.
- [ ] Replace incoming-directory scanning, archive intake, NZB backup, and URL-to-queue admission (`queue/Scanner.*`, `ArchiveProcessor.*`, `UrlCoordinator.*`).
- [ ] Transfer download/file/article models, IDs, ownership, inline header logic, and shared queue locks into Rust (`queue/DownloadInfo.*`).
- [ ] Replace queue coordination, scheduling, pause/resume, completion transitions, and editing (`queue/QueueCoordinator.*`, `QueueEditor.*`).
- [ ] Replace queue/history state serialization, loading, migration compatibility, crash recovery, and ID persistence (`queue/DiskState.*`).
- [ ] Replace history coordination, retention, redownload, and return-to-queue operations (`queue/HistoryCoordinator.*`).
- [ ] Finish direct-renaming orchestration, file access, queue updates, and deobfuscation ownership (`queue/DirectRenamer.*`, `Deobfuscation.*`).

### Duplicate discovery, fleets, and recovery

- [ ] Replace duplicate coordination, ranking/admission callers, backup promotion, and twin-check integration (`queue/DupeCoordinator.*`, `TwinCheck.*`).
- [ ] Replace article fallback, probing, background rechecks, worker cancellation, and retained recovery state (`queue/DupeArticleFallback.*`, `DupeProbe.*`).
- [ ] Finish stream-repair queue integration, range/part ownership, and PAR damage tracking (`queue/DupeStreamRepair.*`, `ParDamage.*`).
- [ ] Replace duplicate-search and fleet controllers, locks, deadlines, caches, persisted metadata, and edits (`dupesearch/DupeSearch.*`, `Fleet.*`, `DupeIdentity.*`).
- [ ] Replace Newznab queries, HTTP/NZB fetching, XML/NZB readers, donor-health checks, and NNTP probing (`dupesearch/Newznab.*`, `HttpGet.*`, `NzbFetcher.*`, `XmlReader.*`, `NzbReader.*`, `DonorHealth.*`, `NntpHealthServer.*`).
- [ ] Finish dead-posting storage/locking, score callers, posting file/cache access, and release-name wrappers (`dupesearch/DeadPostings.*`, `DonorScore.*`, `Posting.*`, `ReleaseName.*`). Existing Rust policy and parsing routines don't replace these controllers.

### Repair, unpacking, and post-processing

- [ ] Replace post-processing orchestration, status transitions, concurrency, pause/cancel, and shutdown (`postprocess/PrePostProcessor.*`).
- [ ] Replace PAR checking and repair orchestration, packet loading, callbacks, file verification, and repairer ownership (`postprocess/ParChecker.*`, `Repair.*`, `ParParser.*`). Track the PAR library replacement separately below.
- [ ] Finish PAR/RAR parsing and renaming callers, metadata, regular expression use, directory walks, and actual file moves (`postprocess/ParRenamer.*`, `RarReader.*`, `RarRenamer.*`).
- [ ] Replace unpacking and direct-unpack controllers, subprocess supervision, password handling, output parsing, and cancellation (`postprocess/UnpackController.*`, `DirectUnpack.*`).
- [ ] Replace post-download/post-unpack renaming, cleanup, moving, and collection-analysis integration (`postprocess/PostDownloadRenamer.*`, `PostUnpackRenamer.*`, `Rename.*`, `Cleanup.*`, `CollectionAnalyzer.*`).
- [ ] Replace content maps, duplicate archive matching, stream crypto, and stream-repair orchestration (`postprocess/ContentMap.*`, `DupeMatcher.*`, `StreamCrypto.*`, `StreamRepair.*`), including compressed/encrypted donor paths.

### Web server, APIs, and clients

- [ ] Replace listener/socket ownership, HTTP request/body handling, static asset serving, authentication integration, compression, and TLS control (`remote/WebServer.*`, `RemoteServer.*`).
- [ ] Replace all JSON/XML-RPC command implementations, response collection, serialization, and queue/configuration mutations (`remote/XmlRpc.*`). Rust routing and parameter parsing don't complete the API.
- [ ] Finish binary RPC commands, transport, response snapshots, locks, and remote-client operations (`remote/BinRpc.*`, `RemoteClient.*`, `MessageBase.h`).
- [ ] Replace terminal client/frontends, rendering, input, and ncurses integration (`frontend/Frontend.*`, `ColoredFrontend.*`, `LoggableFrontend.*`, `NCursesFrontend.*`).
- [ ] Verify the existing web UI, automation clients, Kodi streaming, NZBHydra2, and other supported integrations work against the Rust-owned APIs. JavaScript/HTML/CSS assets don't need a Rust rewrite to meet the C++ target.

### Feeds, extensions, and system health

- [ ] Replace feed fetching, XML parsing, feed/history models, polling, and filter callers (`feed/FeedCoordinator.*`, `FeedFile.*`, `FeedInfo.*`, `FeedFilter.*`).
- [ ] Replace extension discovery, manifest/header loading integration, installation/removal, configuration, and lifecycle (`extension/Extension.*`, `ExtensionLoader.*`, `ExtensionManager.*`, `ManifestFile.*`, `ScriptConfig.*`).
- [ ] Replace command, feed, NZB, post, queue, scan, and scheduler script controllers, environment contracts, exit statuses, and process cleanup (`extension/*Script.*`). Extension scripts can remain in their supported languages.
- [ ] Replace system-health service/status and every validator in `systemhealth/`, including configuration, paths, servers/connections, security, feeds, scheduling, queue, repair, unpacking, logging, display, and extensions.

### Shared utilities and platform interfaces

- [ ] Finish filesystem/path operations, deletes, links, permissions, errors, backup renames, metadata, and file-type callers (`util/FileSystem.*`, `FileTypes.*`).
- [ ] Replace remaining string, encoding, date, formatting, regular expression, JSON/XML, and checksum callers and header implementations (`util/Util.*`, `NString.*`, `Utf8.*`, `Json.*`, `Xml.*`, `Crc32.h`, `Container.h`).
- [ ] Replace threads, locks, observers, service control, script/process control, logging, analytics, and benchmark support (`util/Thread.*`, `Observer.*`, `Service.*`, `ScriptController.*`, `Log.*`, `DataAnalytics.*`, `Benchmark.*`).
- [ ] Replace app-owned crypto, hashing, archive-command, and unpack wrappers (`util/OpenSSL.*`, `Unrar.*`, `SevenZip.*`, `Unpack.*`); a Rust wrapper around C++ doesn't complete dependency removal.
- [ ] Replace OS, CPU, network, and system-information abstractions (`system/OS.*`, `CPU.*`, `Network.*`, `SystemInfo.*`).
- [ ] Audit all remaining headers, templates, inline functions, conditional branches, and generated sources; the `.cpp` list alone isn't a complete inventory.

### Companion programs and supported platforms

- [ ] Replace the bundled test/news server, its frontend, NZB generator, and yEnc encoder (`nserv/NntpServer.*`, `NServMain.*`, `NServFrontend.*`, `NzbGenerator.*`, `YEncoder.*`).
- [ ] Replace Windows console, service, encoding, and resource/build integration if Windows remains supported (`daemon/windows/`, `util/Utf8.*`, `platforms/windows/`, `cmake/windows.cmake`). Windows currently retains the C++ implementation.
- [ ] Verify the macOS app launcher, daemon controller, RPC bridge, packaging, signing, and universal builds (`platforms/macos/`). Its Objective-C sources aren't C++, but still require a compatibility and native-dependency audit.
- [ ] Qualify every retained OS, architecture, and build combination. Include Linux, macOS, Windows, FreeBSD, Android, static builds, and cross builds. Record explicit support retirements before removing a platform's fallback.
- [ ] Update Docker images, Linux packages, installers, Flatpak, Snap, QNAP packaging, and platform build scripts to use the Rust executable and approved helper set.

### Linked and native dependencies

Inventory [POSIX dependencies](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/cmake/posix.cmake), [Windows dependencies](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/cmake/windows.cmake), `cmake/*.cmake`, `lib/sources.cmake`, `rust/Cargo.toml`, and `rust/Cargo.lock`. Record versions, transitive dependencies, feature flags, static/dynamic linkage, and shipped artifacts for each retained target. Rust crate names and C interfaces don't establish implementation language.

- [ ] Replace PAR2-Turbo and its `par2-turbo`, `gf16`, and `hasher` build targets; qualify full verification/repair and renaming. The existing `rust-par2` dependency doesn't prove the C++ repair engine is gone.
- [ ] Remove Boost headers and compiled components from app builds, including JSON and any remaining algorithm/container use; track `Boost.Test` separately below.
- [ ] Audit rapidyenc and its CRC/SIMD backend, callbacks, build languages, and transitive native code; remove any C++ requirement or replace the backend with a qualified alternative.
- [ ] Decide and record the retained OpenSSL TLS/crypto, libxml2 XML, zlib compression, ncurses terminal, and bundled POSIX regular expression dependencies. These C libraries don't by themselves block zero C++, but are separate work if the target becomes Rust-only.
- [ ] Audit Rust dependencies, their feature-selected transitive dependencies, `build.rs` scripts, native bindings, generated code, and downloaded/prebuilt archives for hidden C++.
- [ ] Audit system/runtime linkage per target, including the C++ standard library, compiler/unwind runtimes, platform frameworks, and optional OpenMP or other dependency runtimes. Remove C++ runtime requirements that remain after app ports.
- [ ] Verify optional feature combinations, system-library builds, and pinned source builds independently; removing one default dependency path doesn't retire another.

### External tools and distribution contents

- [ ] Replace required or bundled `unrar` executables, including `unrar` and `unrar7`, with qualified alternatives covering listing, extraction, encryption, passwords, multipart archives, and failure/cancellation behavior.
- [ ] Replace required or bundled 7-Zip executables, including `7za`, `7z`, and `7zz` where used, with qualified alternatives covering every retained archive format and extension-installation path.
- [ ] Audit all installers, packages, app bundles, container layers, and runtime images for unpackers, native libraries, C++ runtimes, and other C++ executables pulled in through base images or package dependencies.
- [ ] Define the external extension/user-tool boundary. A user-supplied C++ script helper or unpacker prevents an unrestricted whole-environment claim; document any exclusions and provide a C++-free supported path.
- [ ] Keep licenses, notices, settings/defaults, helper discovery, upgrade behavior, and release dependency manifests consistent with each replacement.

### Qualification and development tooling

- [ ] For each replacement, retain byte-for-byte differential coverage, fuzz/mutated inputs, ownership/lifetime checks, and applicable sanitizer runs while the C++ reference is available.
- [ ] Meet the current [replacement performance gates](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/docs/RUST_REPLACEMENT_PLAN.md) with matched complete callers, real I/O/FFI/allocation costs, reproducible inputs, and retained slower/inconclusive results. A module benchmark alone isn't acceptance.
- [ ] Verify queue/state upgrade and restart compatibility, IDs, partial downloads, failure recovery, signals, concurrency, and process cleanup across supported platforms.
- [ ] Replace app C++ unit/integration tests and `Boost.Test` with coverage of the Rust-owned behavior; retain end-to-end API, download, repair, unpack, and duplicate-recovery scenarios.
- [ ] Decide the historical reference-tooling boundary. C++ differential/benchmark harnesses can remain in an archived migration reference, but must leave the required build/test/release path before claiming a C++-free development toolchain.
- [ ] Audit CI actions, build containers, package builders, signing tools, and developer prerequisites separately from shipped runtime dependencies. If a claim includes those tools, identify and remove their C++ requirements too.

### Final C++ removal and acceptance

- [ ] Make Rust own the executable entry point, state, object lifetimes, synchronization, I/O, and error propagation; prove there are no remaining calls into app C++.
- [ ] Replace C++ callbacks and ownership bridges with Rust calls, then remove obsolete exports and `rust/include/nzbget_rs.h` interfaces. Retained C-library interfaces can remain for a zero-C++ target.
- [ ] Retire builds without Rust and every `NZBGET_USE_RUST` C++ fallback, following the platform/support decisions in this checklist; remove obsolete configuration switches.
- [ ] Delete retired app C++ sources/headers, generated C++ bindings, targets, precompiled headers, and compiler/link settings. Update CMake or its replacement and all release/CI entry points.
- [ ] Build, test, and package every retained target in a clean environment without a C++ compiler or C++ development headers. Audit transitive and prebuilt inputs as well; this test alone can't detect precompiled C++.
- [ ] Inspect compile commands, link maps, static archive members, dynamic/import dependencies, symbols, and packaged files for C++ code/runtime linkage. Static linkage or stripped symbols alone aren't proof of absence.
- [ ] Publish per-target dependency and artifact evidence with immutable source, lockfile, toolchain, binary, and image identities; independently review the evidence for each of the three milestones.
- [ ] Verify an authorized rollout of the exact qualified artifacts, including fresh downloads, restart/resume, duplicate recovery, repair/unpack, and supported integrations. Record deployment evidence separately from source/build completion.
- [ ] Mark **zero app C++**, **zero linked C++ dependencies**, and **zero distributed C++ helpers/runtime components** complete separately, and state the supported targets and exclusions. Claim **zero C++** only for the scope all three evidence sets actually cover.

## Modules in Rust

This table is generated from the crate's source on every build. Each module's first doc comment says what it does. The `ffi` module is the C interface that the C++ code calls.

<!-- modules -->

## Porting notes

The notes below come from `rust/PORTING.md` in the repository. Its table of finished ports lists the measured speed-ups; the module table on this page lists all current Rust modules. Use the preceding checklist to track the remaining app and dependency work.

<!-- porting -->
