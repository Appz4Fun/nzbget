# Full Rust migration status

Initial refreshed source: `4cf19abdb8f084a384769a15cf57e56acf86f363`. Target confirmed by user: `Appz4Fun/nzbget:dupe-article-fallback`.

Completion requires all application C++ implementations, adapters, headers, and build dependencies to be replaced, corresponding C++ test harnesses retired after their contracts are carried into Rust tests, and remaining C++ removed. Every implementation PR needs thorough local Codex review followed by Codex sign-off at the PR level on the current published head. Fix and resolve all findings before integration; changes after review require renewed applicable validation and review of the final head. Required validation, a locally signed squash with exact xbmc4lyfe identities, GitHub signature verification, and owner-approved integration into `dupe-article-fallback` remain separate gates. Backend deployment remains a separately authorized operation.

Source file checkboxes record deletion after replacement and integration, not investigation or source inclusion. Related external C/C++ dependencies and platform code are tracked separately and cannot silently disappear from the completion audit.

## Completed preparatory work

- [x] Verify API and effective HTTPS Git actor as `xbmc4lyfe`.
- [x] Fetch the canonical fork and verify this worktree starts at the actual remote default (`0 0` divergence).
- [x] Confirm `dupe-article-fallback` as the user-approved target; `master` and `main` do not exist in this remote.
- [x] Capture a source inventory over every daemon C++ file and Rust source module with immutable Git blob identities.
- [x] Ask current source/integration owners for the single worker scheduler, reserved lanes, holds, and largest measured opportunities.
- [x] Receive scheduling ownership and a concrete nonoverlapping runtime task: the article decode/CRC/write data-plane comparison described below.
- [x] Map all 36 source-level Rust-backed caller boundaries, retained C++ work and build/bypass guards; classify the 11 exports without call-shaped references.
- [x] Audit linked C++ dependency targets, verify pinned RapidYenc/PAR2 source identities, and identify remaining platform/package surfaces without claiming native execution.
- [ ] Confirm compiled Rust route coverage on representative offline daemon fixtures.
- [ ] Rank candidates with current profile evidence and complete-caller cost.
- [ ] Freeze and review the first candidate qualification plan.
- [ ] Implement, qualify, review, and integrate the first C++ deletion.

Source boundary details and partial-check coverage gaps are in [BOUNDARY_MAP.md](rust-migration/BOUNDARY_MAP.md).

Linked dependencies and final package/platform retirement gates are in [DEPENDENCY_RETIREMENT.md](rust-migration/DEPENDENCY_RETIREMENT.md).

## Assigned first comparison boundary

The integration coordinator assigned this lane the real `ArticleDownloader` decode/check/write path and `ArticleWriter` allocation, buffer copy, cache/disk output and cleanup. The first deliverable is an isolated source-bound parity/benchmark harness and a bounded worker payload; production changes wait for initial measurements. Preserve the existing Rust decoder independently, including its native RapidYenc callbacks, and compare original and equivalently improved C++ using fixed tiny, normal and large offline articles. Observe complete decoded bytes, CRC, partial-output/failure behavior and actual boundary hits before timing. A direct decoder kernel cannot qualify the complete article caller.

The existing scheduling owner controls worker admission. Heavy builds, correctness runs and profiling require the exact payload and coordinator grant. Health/NNTP scheduling, recovery geometry/matching/pinned donor state and PAR work remain with their current owners. This assignment does not clear their holds or establish a Rust speedup.

Ruling: execute the approved differential-benchmark plan through an isolated harness first; do not infer a production replacement from a kernel result or change production source before the assigned initial measurement identifies a slice.

## Initial investigation priority

1. Current four-NZB submission critical path: existing owners hold capacity/network candidate and profiling work; obtain their exact source-bound raw evidence before allocating a duplicate lane.
2. PAR checksum/hash/recovery boundaries: existing Text/PAR lane holds matched correctness evidence, with performance still unmeasured; no speed claim transfers to this fresh source.
3. Already wired high historical multipliers (`crc`, NZB file accounting/duplicate names, release names, posting ordering): require fair C++ algorithm controls and complete-caller measurements before scheduling deletion. These are leads, not measured priority rankings.
4. Remaining daemon subsystems: inventory includes all files below; ranking awaits observed cost. Lightweight paths remain in scope for full migration even if they cannot produce a 2x win; the current hard performance gate is not waived.

## Daemon C++ deletion checklist

- [ ] `daemon/connect/Connection.cpp` — 1398 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/connect/HttpClient.cpp` — 202 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/connect/NetworkSpeedTest.cpp` — 177 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/connect/TlsSocket.cpp` — 329 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/connect/WebDownloader.cpp` — 765 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/DeadPostings.cpp` — 163 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/DonorHealth.cpp` — 508 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/dupesearch/DonorScore.cpp` — 115 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/DupeIdentity.cpp` — 187 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/DupeSearch.cpp` — 2028 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/Fleet.cpp` — 556 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/dupesearch/HttpGet.cpp` — 137 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/dupesearch/Newznab.cpp` — 474 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/dupesearch/NntpHealthServer.cpp` — 248 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/dupesearch/NzbFetcher.cpp` — 278 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/NzbReader.cpp` — 365 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/Posting.cpp` — 310 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/ReleaseName.cpp` — 595 source lines; Rust call-like symbols present.
- [ ] `daemon/dupesearch/XmlReader.cpp` — 116 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/CommandScript.cpp` — 131 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/Extension.cpp` — 445 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/ExtensionLoader.cpp` — 620 source lines; Rust call-like symbols present.
- [ ] `daemon/extension/ExtensionManager.cpp` — 459 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/FeedScript.cpp` — 80 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/ManifestFile.cpp` — 508 source lines; Rust call-like symbols present.
- [ ] `daemon/extension/NzbScript.cpp` — 90 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/PostScript.cpp` — 321 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/QueueScript.cpp` — 502 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/ScanScript.cpp` — 217 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/SchedulerScript.cpp` — 114 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/extension/ScriptConfig.cpp` — 200 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/feed/FeedCoordinator.cpp` — 781 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/feed/FeedFile.cpp` — 382 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/feed/FeedFilter.cpp` — 1253 source lines; Rust call-like symbols present.
- [ ] `daemon/feed/FeedInfo.cpp` — 230 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/frontend/ColoredFrontend.cpp` — 162 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/frontend/Frontend.cpp` — 340 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/frontend/LoggableFrontend.cpp` — 112 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/frontend/NCursesFrontend.cpp` — 1395 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/main/CommandLineParser.cpp` — 1178 source lines; Rust call-like symbols present.
- [ ] `daemon/main/DiskService.cpp` — 131 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/main/Maintenance.cpp` — 419 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/main/Options.cpp` — 2155 source lines; Rust call-like symbols present.
- [ ] `daemon/main/Scheduler.cpp` — 403 source lines; Rust call-like symbols present.
- [ ] `daemon/main/StackTrace.cpp` — 296 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/main/WorkState.cpp` — 27 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/main/nzbget.cpp` — 1190 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nntp/ArticleDownloader.cpp` — 732 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nntp/ArticleFetcher.cpp` — 657 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nntp/ArticleWriter.cpp` — 1264 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nntp/Decoder.cpp` — 529 source lines; Rust call-like symbols present.
- [ ] `daemon/nntp/NewsServer.cpp` — 37 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nntp/NntpConnection.cpp` — 420 source lines; Rust call-like symbols present.
- [ ] `daemon/nntp/ServerPool.cpp` — 422 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nntp/StatMeter.cpp` — 633 source lines; Rust call-like symbols present.
- [ ] `daemon/nserv/NServFrontend.cpp` — 146 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nserv/NServMain.cpp` — 279 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nserv/NntpServer.cpp` — 475 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nserv/NzbGenerator.cpp` — 131 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/nserv/YEncoder.cpp` — 129 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/Cleanup.cpp` — 368 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/CollectionAnalyzer.cpp` — 681 source lines; Rust call-like symbols present.
- [ ] `daemon/postprocess/ContentMap.cpp` — 1950 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/DirectUnpack.cpp` — 602 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/DupeMatcher.cpp` — 207 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/ParChecker.cpp` — 1633 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/ParParser.cpp` — 181 source lines; Rust call-like symbols present.
- [ ] `daemon/postprocess/ParRenamer.cpp` — 770 source lines; Rust call-like symbols present.
- [ ] `daemon/postprocess/PostDownloadRenamer.cpp` — 176 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/PostUnpackRenamer.cpp` — 175 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/PrePostProcessor.cpp` — 1401 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/RarReader.cpp` — 982 source lines; Rust call-like symbols present.
- [ ] `daemon/postprocess/RarRenamer.cpp` — 485 source lines; Rust call-like symbols present.
- [ ] `daemon/postprocess/Rename.cpp` — 229 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/Repair.cpp` — 858 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/StreamCrypto.cpp` — 263 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/StreamRepair.cpp` — 3656 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/postprocess/UnpackController.cpp` — 1051 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/ArchiveProcessor.cpp` — 239 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/Deobfuscation.cpp` — 503 source lines; Rust call-like symbols present.
- [ ] `daemon/queue/DirectRenamer.cpp` — 881 source lines; Rust call-like symbols present.
- [ ] `daemon/queue/DiskState.cpp` — 3188 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/DownloadInfo.cpp` — 1046 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/DupeArticleFallback.cpp` — 1543 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/DupeCoordinator.cpp` — 879 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/DupeProbe.cpp` — 599 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/DupeStreamRepair.cpp` — 1029 source lines; Rust call-like symbols present.
- [ ] `daemon/queue/HistoryCoordinator.cpp` — 1062 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/NzbFile.cpp` — 758 source lines; Rust call-like symbols present.
- [ ] `daemon/queue/ParDamage.cpp` — 231 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/QueueCoordinator.cpp` — 2679 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/QueueEditor.cpp` — 1368 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/Scanner.cpp` — 1070 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/queue/TwinCheck.cpp` — 1107 source lines; Rust call-like symbols present.
- [ ] `daemon/queue/UrlCoordinator.cpp` — 515 source lines; Rust call-like symbols present.
- [ ] `daemon/remote/BinRpc.cpp` — 1803 source lines; Rust call-like symbols present.
- [ ] `daemon/remote/RemoteClient.cpp` — 1246 source lines; Rust call-like symbols present.
- [ ] `daemon/remote/RemoteServer.cpp` — 340 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/remote/WebServer.cpp` — 917 source lines; Rust call-like symbols present.
- [ ] `daemon/remote/XmlRpc.cpp` — 4687 source lines; Rust call-like symbols present.
- [ ] `daemon/system/CPU.cpp` — 253 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/system/Network.cpp` — 51 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/system/OS.cpp` — 309 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/system/SystemInfo.cpp` — 466 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/CategoriesValidator.cpp` — 69 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/CategoryValidator.cpp` — 65 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/CheckAndRepairValidator.cpp` — 237 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/ConnectionValidator.cpp` — 230 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/DisplayValidator.cpp` — 91 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/DownloadQueueValidator.cpp` — 279 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/ExtensionScriptsValidator.cpp` — 143 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/FeedValidator.cpp` — 106 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/FeedsValidator.cpp` — 71 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/IncomingNzbValidator.cpp` — 133 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/LoggingValidator.cpp` — 108 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/NewsServerValidator.cpp` — 253 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/NewsServersValidator.cpp` — 95 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/PathsValidator.cpp` — 332 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/SchedulerTaskValidator.cpp` — 72 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/SchedulerTasksValidator.cpp` — 29 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/SectionGroupValidator.cpp` — 55 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/SectionValidator.cpp` — 180 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/SecurityValidator.cpp` — 331 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/Status.cpp` — 68 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/SystemHealthService.cpp` — 252 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/UnpackValidator.cpp` — 166 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/systemhealth/Validators.cpp` — 356 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Benchmark.cpp` — 184 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/DataAnalytics.cpp` — 82 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/FileSystem.cpp` — 2200 source lines; Rust call-like symbols present.
- [ ] `daemon/util/FileTypes.cpp` — 695 source lines; Rust call-like symbols present.
- [ ] `daemon/util/Json.cpp` — 62 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Log.cpp` — 471 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/NString.cpp` — 473 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Observer.cpp` — 48 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/OpenSSL.cpp` — 37 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/ScriptController.cpp` — 1061 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Service.cpp` — 122 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/SevenZip.cpp` — 97 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Thread.cpp` — 128 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Unpack.cpp` — 133 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Unrar.cpp` — 138 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Utf8.cpp` — 70 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/util/Util.cpp` — 2979 source lines; Rust call-like symbols present.
- [ ] `daemon/util/Xml.cpp` — 87 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/windows/StdAfx.cpp` — 21 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/windows/WinConsole.cpp` — 1050 source lines; no direct Rust call-like symbol found.
- [ ] `daemon/windows/WinService.cpp` — 209 source lines; no direct Rust call-like symbol found.

## Remaining application and test surface

- [ ] `daemon/connect/Connection.h` — header contract and callers must move to Rust.
- [ ] `daemon/connect/HttpClient.h` — header contract and callers must move to Rust.
- [ ] `daemon/connect/NetworkSpeedTest.h` — header contract and callers must move to Rust.
- [ ] `daemon/connect/TlsSocket.h` — header contract and callers must move to Rust.
- [ ] `daemon/connect/WebDownloader.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/DeadPostings.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/DonorHealth.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/DonorScore.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/DupeIdentity.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/DupeSearch.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/DupeUtil.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/Fleet.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/HttpGet.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/Newznab.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/NntpHealthServer.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/NzbFetcher.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/NzbReader.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/Posting.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/ReleaseName.h` — header contract and callers must move to Rust.
- [ ] `daemon/dupesearch/XmlReader.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/CommandScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/Extension.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/ExtensionLoader.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/ExtensionManager.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/FeedScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/ManifestFile.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/NzbScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/PostScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/QueueScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/ScanScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/SchedulerScript.h` — header contract and callers must move to Rust.
- [ ] `daemon/extension/ScriptConfig.h` — header contract and callers must move to Rust.
- [ ] `daemon/feed/FeedCoordinator.h` — header contract and callers must move to Rust.
- [ ] `daemon/feed/FeedFile.h` — header contract and callers must move to Rust.
- [ ] `daemon/feed/FeedFilter.h` — header contract and callers must move to Rust.
- [ ] `daemon/feed/FeedInfo.h` — header contract and callers must move to Rust.
- [ ] `daemon/frontend/ColoredFrontend.h` — header contract and callers must move to Rust.
- [ ] `daemon/frontend/Frontend.h` — header contract and callers must move to Rust.
- [ ] `daemon/frontend/LoggableFrontend.h` — header contract and callers must move to Rust.
- [ ] `daemon/frontend/NCursesFrontend.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/CommandLineParser.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/DiskService.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/Maintenance.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/Options.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/Scheduler.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/StackTrace.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/WorkState.h` — header contract and callers must move to Rust.
- [ ] `daemon/main/nzbget.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/ArticleDownloader.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/ArticleFetcher.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/ArticleWriter.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/Decoder.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/NewsServer.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/NntpConnection.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/ServerPool.h` — header contract and callers must move to Rust.
- [ ] `daemon/nntp/StatMeter.h` — header contract and callers must move to Rust.
- [ ] `daemon/nserv/NServFrontend.h` — header contract and callers must move to Rust.
- [ ] `daemon/nserv/NServMain.h` — header contract and callers must move to Rust.
- [ ] `daemon/nserv/NntpServer.h` — header contract and callers must move to Rust.
- [ ] `daemon/nserv/NzbGenerator.h` — header contract and callers must move to Rust.
- [ ] `daemon/nserv/YEncoder.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/Cleanup.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/CollectionAnalyzer.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/ContentMap.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/DirectUnpack.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/DupeMatcher.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/ParChecker.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/ParParser.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/ParRenamer.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/PostDownloadRenamer.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/PostUnpackRenamer.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/PrePostProcessor.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/RarReader.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/RarRenamer.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/Rename.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/Repair.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/StreamCrypto.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/StreamRepair.h` — header contract and callers must move to Rust.
- [ ] `daemon/postprocess/UnpackController.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/ArchiveProcessor.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/Deobfuscation.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DirectRenamer.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DiskState.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DownloadInfo.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DupeArticleFallback.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DupeCoordinator.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DupeProbe.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/DupeStreamRepair.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/HistoryCoordinator.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/NzbFile.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/ParDamage.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/QueueCoordinator.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/QueueEditor.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/Scanner.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/TwinCheck.h` — header contract and callers must move to Rust.
- [ ] `daemon/queue/UrlCoordinator.h` — header contract and callers must move to Rust.
- [ ] `daemon/remote/BinRpc.h` — header contract and callers must move to Rust.
- [ ] `daemon/remote/MessageBase.h` — header contract and callers must move to Rust.
- [ ] `daemon/remote/RemoteClient.h` — header contract and callers must move to Rust.
- [ ] `daemon/remote/RemoteServer.h` — header contract and callers must move to Rust.
- [ ] `daemon/remote/WebServer.h` — header contract and callers must move to Rust.
- [ ] `daemon/remote/XmlRpc.h` — header contract and callers must move to Rust.
- [ ] `daemon/system/CPU.h` — header contract and callers must move to Rust.
- [ ] `daemon/system/Network.h` — header contract and callers must move to Rust.
- [ ] `daemon/system/OS.h` — header contract and callers must move to Rust.
- [ ] `daemon/system/SystemInfo.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/CategoriesValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/CategoryValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/CheckAndRepairValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/ConnectionValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/DisplayValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/DownloadQueueValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/ExtensionScriptsValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/FeedValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/FeedsValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/IncomingNzbValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/LoggingValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/NewsServerValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/NewsServersValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/PathsValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SchedulerTaskValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SchedulerTasksValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SectionGroupValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SectionValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SecurityValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/Status.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SystemHealth.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/SystemHealthService.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/UnpackValidator.h` — header contract and callers must move to Rust.
- [ ] `daemon/systemhealth/Validators.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Benchmark.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Container.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/DataAnalytics.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/FileSystem.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/FileTypes.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Json.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Log.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/NString.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Observer.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/OpenSSL.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/ScriptController.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Service.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Thread.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Unpack.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Utf8.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Util.h` — header contract and callers must move to Rust.
- [ ] `daemon/util/Xml.h` — header contract and callers must move to Rust.
- [ ] `daemon/windows/WinConsole.h` — header contract and callers must move to Rust.
- [ ] `daemon/windows/WinService.h` — header contract and callers must move to Rust.
- [ ] `platforms/macos/DaemonController.h` — platform or test support remains in completion scope.
- [ ] `platforms/macos/MainApp.h` — platform or test support remains in completion scope.
- [ ] `platforms/macos/PFMoveApplication.h` — platform or test support remains in completion scope.
- [ ] `platforms/macos/PreferencesDialog.h` — platform or test support remains in completion scope.
- [ ] `platforms/macos/RPC.h` — platform or test support remains in completion scope.
- [ ] `platforms/macos/WebClient.h` — platform or test support remains in completion scope.
- [ ] `platforms/macos/WelcomeDialog.h` — platform or test support remains in completion scope.

## macOS application implementations

- [ ] `platforms/macos/DaemonController.m` — Objective-C application implementation; Rust replacement and native macOS lifecycle proof pending.
- [ ] `platforms/macos/MainApp.m` — Objective-C application implementation; Rust replacement and native macOS lifecycle proof pending.
- [ ] `platforms/macos/PFMoveApplication.m` — Objective-C application implementation; Rust replacement and native macOS installation/relocation proof pending.
- [ ] `platforms/macos/PreferencesDialog.m` — Objective-C application implementation; Rust replacement and native macOS preferences/UI proof pending.
- [ ] `platforms/macos/RPC.m` — Objective-C application implementation; Rust replacement and native macOS RPC/failure proof pending.
- [ ] `platforms/macos/WebClient.m` — Objective-C application implementation; Rust replacement and native macOS request/ownership proof pending.
- [ ] `platforms/macos/WelcomeDialog.m` — Objective-C application implementation; Rust replacement and native macOS UI lifecycle proof pending.
- [ ] `platforms/windows/resources/resource.h` — platform or test support remains in completion scope.
- [ ] `tests/dupesearch/DeadPostings.cpp` — platform or test support remains in completion scope.
- [ ] `tests/dupesearch/DonorHealth.cpp` — platform or test support remains in completion scope.
- [ ] `tests/dupesearch/DonorScore.cpp` — platform or test support remains in completion scope.
- [ ] `tests/dupesearch/Newznab.cpp` — platform or test support remains in completion scope.
- [ ] `tests/dupesearch/Posting.cpp` — platform or test support remains in completion scope.
- [ ] `tests/dupesearch/ReleaseName.cpp` — platform or test support remains in completion scope.
- [ ] `tests/extension/Extension.cpp` — platform or test support remains in completion scope.
- [ ] `tests/extension/ExtensionLoader.cpp` — platform or test support remains in completion scope.
- [ ] `tests/extension/ExtensionManager.cpp` — platform or test support remains in completion scope.
- [ ] `tests/extension/ManifestFile.cpp` — platform or test support remains in completion scope.
- [ ] `tests/extension/ScanScript.cpp` — platform or test support remains in completion scope.
- [ ] `tests/extension/ScriptConfig.cpp` — platform or test support remains in completion scope.
- [ ] `tests/feed/FeedFile.cpp` — platform or test support remains in completion scope.
- [ ] `tests/feed/FeedFilter.cpp` — platform or test support remains in completion scope.
- [ ] `tests/feed/FeedInfo.cpp` — platform or test support remains in completion scope.
- [ ] `tests/feed/NzbInfoCreator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/main.cpp` — platform or test support remains in completion scope.
- [ ] `tests/main/CommandLineParser.cpp` — platform or test support remains in completion scope.
- [ ] `tests/main/Options.cpp` — platform or test support remains in completion scope.
- [ ] `tests/nntp/ArticleFetcher.cpp` — platform or test support remains in completion scope.
- [ ] `tests/nntp/ArticleWriter.cpp` — platform or test support remains in completion scope.
- [ ] `tests/nntp/Decoder.cpp` — platform or test support remains in completion scope.
- [ ] `tests/nntp/ServerPool.cpp` — platform or test support remains in completion scope.
- [ ] `tests/nntp/StatMeter.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/CollectionAnalyzer.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/ContentMap.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/DirectUnpack.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/DupeMatcher.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/MoveController.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/ParChecker.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/ParRenamer.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/PrePostProcessor.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/RarReader.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/RarRenamer.cpp` — platform or test support remains in completion scope.
- [ ] `tests/postprocess/StreamCrypto.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/ArchiveProcessor.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/CompletedFile.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/Deobfuscation.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/DupeArticleFallback.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/DupeCoordinator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/DupeProbe.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/DupeStreamRepair.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/HistoryCoordinator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/NzbFile.cpp` — platform or test support remains in completion scope.
- [ ] `tests/queue/PropagationDelay.cpp` — platform or test support remains in completion scope.
- [ ] `tests/remote/XmlRpc.cpp` — platform or test support remains in completion scope.
- [ ] `tests/system/SystemInfo.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/ConnectionValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/ExtensionScriptsValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/FeedValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/LoggingValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/NewsServerValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/PathsValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/SecurityValidator.cpp` — platform or test support remains in completion scope.
- [ ] `tests/systemhealth/Validators.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/Benchmark.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/DataAnalytics.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/FileSystem.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/FileTypes.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/Json.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/NString.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/ScriptController.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/Unpack.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/Utf8.cpp` — platform or test support remains in completion scope.
- [ ] `tests/util/Util.cpp` — platform or test support remains in completion scope.

## Public Rust C ABI headers

These headers are part of the real daemon/generated-oracle boundary. Immutable bindings are in `source-inventory.json`; struct layout, callbacks, ownership and declarations require a reviewed disposition, independently of compiled ABI proof.

- [ ] `rust/include/nzbget_rs.h` — preserve struct/callback/ownership/ABI contracts; replace C++ consumers/adapters and migrate required interface declarations under reviewed Rust ownership before final retirement.
- [ ] `rust/include/nzbget_rs_dupesearch_nzb.h` — preserve struct/callback/ownership/ABI contracts; replace C++ consumers/adapters and migrate required interface declarations under reviewed Rust ownership before final retirement.

## C++ oracles and drivers under Rust tests

Every retained source below has an immutable identity in `source-inventory.json`. Preserve and translate its contracts before retiring C++ compilation; source classification does not establish readiness or runtime execution. Python analysis/orchestration needs an explicit C++-coupling disposition, including transitive imports, rather than an assumed whole-file deletion.

- [ ] `rust/tests/deobfuscation_ownership.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/dupesearch_nzb/caller.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/latin1_caller/driver.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/paths_ownership.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/rarrenamer_metadata.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/streamcompare_caller.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/streamcompare_improved_control.inc` — C++ include fragment; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/streamcompare_reference.inc` — C++ include fragment; preserve/translate contracts and retire C++ source after validation.
- [ ] `rust/tests/streampatchparts_harness.cpp` — C++ test/caller harness; preserve/translate contracts and retire C++ source after validation.

### Python test-driver C++ coupling

- [ ] `rust/tests/binrpc_client_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/binrpc_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/binrpc_edit_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/binrpc_lists_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/cmdline_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/collection_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/crc_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/deadpostings_cpp_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/deadpostings_locale.py` — C++-related driver candidate; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/deadpostings_mutations.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/decode_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/decoder_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/deobfuscation_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/directrenamer_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/donorscore_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupeidentity_differential.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupesearch_nzb/mutations.py` — C++-related driver candidate; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupesearch_nzb/run.py` — C++-related driver candidate; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupesearch_nzb/summarize.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupesearch_nzb/test_evidence.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupewatch_cpp_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/dupewatch_differential.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/extload_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/feedfilter_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/filetypes_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/fsdelete_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/fsops_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/latin1_caller/run.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/latin1_caller/summarize.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/latin1_caller/test_runner.py` — C++-related driver candidate; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/manifest_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/nntp_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/nzbfile_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/options_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/parparser_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/parrenamer_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/paths_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/posting_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/rarreader_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/rarrenamer_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/releasename_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/renameanalyzer_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/rpcaccess_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/rpcparams_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/rpcroute_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/scheduler_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/statmeter_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/streamcompare_analyze.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/streamcompare_differential.py` — C++-related driver candidate; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/streampatchparts_benchmark_summary.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/streampatchparts_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/streampatchparts_mutations.py` — analysis/orchestration source; transitive C++ dependency review pending; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/testserver_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/text_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/textutil_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/url_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/urlcoord_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/util_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/webdownload_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/webserver_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/webutil_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.
- [ ] `rust/tests/wildmask_differential.py` — emitted C++ source; preserve contracts and resolve C++ coupling before native retirement.

## Packaged unpacker source and release inputs

Each input is bound in `dependency-sources.json`. These rows track selected native assets/configuration and their required Rust retirement contracts; source presence is not package/image content or execution proof.

- [ ] `docker/Dockerfile` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `docker/docker-compose.yml` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `linux/build-nzbget.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `linux/installer.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `linux/pkg/build-pkg.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `linux/pkg/deb/DEBIAN/control` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `linux/pkg/rpm/nzbget.spec` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `platforms/android/build.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `platforms/android/installer.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `platforms/macos/build.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `platforms/macos/sign/nzbget-sign.sh` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `platforms/windows/build.ps1` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.
- [ ] `unpackers.env` — replace native unpacker packaging/recommendations/configuration while preserving supported extraction, error, license and target contracts.

- [ ] `nzbget.conf` — migrate shipped extractor defaults and config upgrade/stream-repair command contracts with qualified Rust extraction owners; preserve user overrides.

## Windows installer, resource and update inputs

- [ ] `platforms/windows/nzbget-setup.nsi` — retain installer language/assets or replace installer owner with Rust-compatible packaging; preserve the source-bound lifecycle/resource contract before completion.
- [ ] `platforms/windows/version.nsi.in` — retain generated installer version metadata through replacement build; preserve the source-bound lifecycle/resource contract before completion.
- [ ] `platforms/windows/version-uninstall.nsi.in` — retain generated uninstall registry version through replacement build; preserve the source-bound lifecycle/resource contract before completion.
- [ ] `platforms/windows/resources/nzbget.rc` — retain menu/dialog/icon assets and resource identifiers; replace native controller/build integration; preserve the source-bound lifecycle/resource contract before completion.
- [ ] `platforms/windows/resources/version.rc.in` — retain executable version resources through replacement build; preserve the source-bound lifecycle/resource contract before completion.
- [ ] `platforms/windows/install-update.bat` — retain or replace updater with the same lifecycle and authenticity contract; preserve the source-bound lifecycle/resource contract before completion.
- [ ] `platforms/windows/nzbget-command-shell.bat` — retain or replace Windows command-shell convenience entrypoint; preserve the source-bound lifecycle/resource contract before completion.

## Individually tracked CMake build inputs

Source-bound dispositions in `dependency-sources.json` cover all 31 checked-in CMake inputs. Each remains pending; retaining/replacing necessary feature/install/toolchain behavior and translating native tests precedes deletion or completion. Generated/fetched/system target closure is separate.

- [ ] `CMakeLists.txt` — Replace C++ project/language/targets/source registration and native linking once qualified Rust owners exist; preserve executable/version/config/platform-resource generation, supported feature options and test/install entrypoints.
- [ ] `cmake/FindZLIB.cmake` — Preserve or replace system compression-library discovery/version/link contract with reviewed Rust packaging; reconcile remaining native/transitive code rather than declaring C++-free from a finder deletion.
- [ ] `cmake/boost.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `cmake/common.cmake` — Translate needed platform/architecture detection, optimization/LTO, hardening/warnings and sanitizer/target configuration into supported Rust build settings; C++ target retirement must not erase required behavior or imply Rust instrumentation.
- [ ] `cmake/install.cmake` — Preserve install/uninstall/config-template/config-install locations, WebUI/docs/permissions and executable contracts with Rust packaging; retire obsolete native target wiring without clobbering user config.
- [ ] `cmake/libxml2.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `cmake/ncurses.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `cmake/openssl.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `cmake/par2-turbo.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `cmake/posix.cmake` — Replace POSIX native feature/dependency/link and optional Rust integration wiring with supported mandatory Rust builds; preserve platform/library/transport/terminal/compression/repair capability and errors.
- [ ] `cmake/rapidyenc.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `cmake/rust.cmake` — Replace optional-return C++ fallback selection with mandatory supported Rust targets; preserve explicit target, compiler/Cargo/toolchain/CRT/static-native-library checks, archive freshness and correct interface/relink dependencies until adapters are retired.
- [ ] `cmake/toolchain.cmake` — Replace C/C++ compiler/tool selection with supported Rust target/SDK/ABI/static/cross-build configuration; preserve platform threading/root-search and architecture behavior.
- [ ] `cmake/windows.cmake` — Replace Windows native dependency/feature/target wiring and absent Rust integration with supported Rust builds; preserve resource/CLI/service/filesystem/repair/link/runtime contracts.
- [ ] `cmake/zlib.cmake` — Replace or explicitly reconcile this dependency discovery/fetch/build/include/link/native-feature contract with qualified Rust owners and supported target settings; preserve required behavior/version/license/error metadata and audit actual selected source/binary/transitive language contents before retirement.
- [ ] `daemon/sources.cmake` — Retire every C++ daemon and conditional platform translation-unit registration only after corresponding Rust caller/platform contracts are qualified; keep source inventory and target closure aligned.
- [ ] `lib/sources.cmake` — Replace or explicitly reconcile conditional bundled/system regex selection and native target/include/link/sanitizer wiring; preserve matching/errors/locale and supported platform behavior. Source alone does not identify downloaded/transitive language content.
- [ ] `tests/CMakeLists.txt` — Retire native test target/Boost discovery/link and C++ registration after preserving historical evidence and translating assertions into independent Rust regressions; preserve supported test dispatch/options and required coverage.
- [ ] `tests/dupesearch/dupesearch.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/extension/extension.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/feed/feed.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/main/main.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/nntp/nntp.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/postprocess/postprocess.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/queue/queue.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/remote/remote.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/system/system.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/systemhealth/systemhealth.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `tests/util/util.cmake` — Translate these native test-suite/source registrations and assertions into independent Rust regressions before retiring C++ compiler/library/Boost coupling; preserve original evidence and suite behavior.
- [ ] `toolchains/android/android-llvm.cmake` — Replace C/C++/LLVM cross-tool/SDK/architecture selection with supported Rust target tooling; preserve documented supported platform/ABI/SDK deployment and linker/package behavior.
- [ ] `toolchains/macos/macos-llvm.cmake` — Replace C/C++/LLVM cross-tool/SDK/architecture selection with supported Rust target tooling; preserve documented supported platform/ABI/SDK deployment and linker/package behavior.

## Build and dependency retirement

- [ ] Replace optional Rust build selection and every C++ fallback with supported mandatory Rust builds on all supported targets.
- [ ] Replace C++ application CMake/source registration and C++ ABI adapters once their Rust owners exist.
- [ ] Inventory third-party libraries and downloads in build scripts; record which dependencies still compile C++ and replace or eliminate them before claiming C++-free operation.
- [ ] Replace RapidYenc's C++ decode/CRC/platform backend and remove its library and callbacks after full caller qualification.
- [ ] Replace PAR2-turbo repair interfaces and inventory/retire its GF16/hasher nested native targets after qualification.
- [ ] Replace runtime Boost JSON/Asio and carry Boost Test assertions into Rust before removing the C++ targets and test entry point.
- [ ] Audit and retire or explicitly reconcile packaged unpacker executables against the complete Rust migration objective.
- [ ] Retire checked-in C++ differential harnesses under `rust/tests` after preserving historical evidence and translating regression assertions into Rust.
- [ ] Audit Objective-C/platform wrappers, packaging, installer entry points, and cross-compilation support; record every retained non-Rust surface and resolve it against the full migration objective.
- [ ] Prove final source inventory and runtime build contain no remaining application C++ or C++ dependencies covered by the objective.

## Remaining holds and current contribution policy

- The 2x hard floor against both original and equally improved C++ cannot be presumed for every routine. A failed gate keeps that candidate open; it must not be marked migrated or replaced by an indefinitely retained fallback.
- Deferred PR #80/#86/#87/#91/#93 validation and backend holds are preserved. A new default source tree requires fresh applicability/lineage decisions.
- Canonical commit `7d3d6412` removed `docs/AI_POLICY.md` and its references from `AGENTS.md` and the PR template. The earlier human-authored-description/testing restriction is superseded; new PRs follow the current template, evidence requirements and both Codex review gates.
