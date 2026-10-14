# Full Rust migration status

Initial refreshed source: `4cf19abdb8f084a384769a15cf57e56acf86f363`. Target confirmed by user: `Appz4Fun/nzbget:dupe-article-fallback`.

Completion requires all application C++ implementations, adapters, headers, and build dependencies to be replaced, corresponding C++ test harnesses retired after their contracts are carried into Rust tests, and remaining C++ removed. Every implementation PR needs thorough local Codex review followed by Codex sign-off at the PR level on the current published head. Fix and resolve all findings before integration; changes after review require renewed applicable validation and review of the final head. Required validation, a locally signed squash with exact xbmc4lyfe identities, GitHub signature verification, and owner-approved integration into `dupe-article-fallback` remain separate gates. Backend deployment remains a separately authorized operation.

Source file checkboxes record deletion after replacement and integration, not investigation or source inclusion. Related external C/C++ dependencies and platform code are tracked separately and cannot silently disappear from the completion audit.

For identity review, first read the live same-repository GitHub PR `head.sha` and compare it with the owned feature ref. Inspect that exact canonical commit’s raw author/committer, local SSH signature and GitHub verification. A review service’s local `HEAD` can be an unsigned internal mirror with a different object ID; mirror identity is not evidence that the published canonical object is unsigned. A mismatch must remain explicit and does not waive the actual-head review gate.

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

## Rust crate and toolchain inputs

All three production Cargo/toolchain inputs have immutable bindings and individual pending dispositions in `dependency-sources.json`. Source declarations do not prove compiler availability, actual archive lineage or qualified native behavior.

- [ ] `rust/Cargo.toml` — Preserve or deliberately replace crate/dependency features, staticlib/rlib exports, rust-version, release/dev panic, opt/LTO/codegen/debug settings and registered diagnostic benchmark targets. Prove selected target/profile/archive/ABI and native/transitive dependency closure; no kernel benchmark substitutes for caller qualification.
- [ ] `rust/Cargo.lock` — Preserve independently bound locked resolution, versions/checksums and immutable Git dependency revisions; review any replacement lock and selected platform features/transitive native content. cargo --locked success does not prove C++-free or performance-qualified binaries.
- [ ] `rust/rust-toolchain.toml` — Preserve or deliberately replace pinned compiler/channel/target/component selection and supported CMake Cargo/rustc compatibility, cross-platform availability and actual compiler identity. A toolchain source pin is not installed readiness or build lineage.

## Shipped dependency disclosure assets

Each source/generated asset and its generation/selection consumer is bound in `dependency-sources.json`. Both RapidYenc and PAR2-turbo retirement require reviewed retention or replacement notices and consistent generated/rendered localization.

- [ ] `webui/index.html` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/locales.source.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/cs/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/da/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/de/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/el/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/es/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/fi/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/fr/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/hu/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/it/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/nb/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/nl/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/pl/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/pt-BR/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/pt-PT/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/ro/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/ru/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/sr/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/sv/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/tr/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/_locales/uk/messages.json` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `scripts/generate_locales.py` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.
- [ ] `webui/i18n.js` — Preserve required notices/attribution and reconcile actual dependency names/licenses, heading/message/link arguments and generated/default/localized behavior before retiring either backend.

## Supplemental platform, release and foreign-code inputs

Exact source scopes, Git blob and entry-mode identities and pending dispositions are in `dependency-sources.json`: production presets; complete macOS source/bundle tree; updater metadata/trust; bundled C regex; Snap/Flatpak; all checked-in platform/release/toolchain/QNAP/active and disabled workflow roots; generated capability-header input and installed license document. Existing rows for the same paths remain required; supporting resource/docs/placeholders may be retained only under their explicit source-bound disposition. Disabled workflows stay inactive. Generated/fetched/system/SDK/binary closure and actual build/package/runtime behavior remain separate.

- [ ] `.github/workflows-disabled/README.md` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/android.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/build.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/docker-debug.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/docker.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/flatpak.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/freebsd.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/linux-pkg.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/linux.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/osx.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/qnap-repack.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/snap.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/tests.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows-disabled/windows.yml` — Preserve as explicitly inactive historical release/test configuration or deliberately retire; reconcile native build/package assumptions if ever re-enabled. This binding does not activate a workflow or demonstrate execution; separately verify future selected authenticated publication and payload lineage.
- [ ] `.github/workflows/bench_base.yml` — Preserve existing active workflow, evidence/identity/lifecycle/publication contract; review any native build/source/target/package coupling for Rust replacement without turning skipped or diagnostic jobs into qualification. Actual runner configuration, selected source/artifact and execution remain separate.
- [ ] `.github/workflows/bench_pr.yml` — Preserve existing active workflow, evidence/identity/lifecycle/publication contract; review any native build/source/target/package coupling for Rust replacement without turning skipped or diagnostic jobs into qualification. Actual runner configuration, selected source/artifact and execution remain separate.
- [ ] `.github/workflows/bench_pr_closed.yml` — Preserve existing active workflow, evidence/identity/lifecycle/publication contract; review any native build/source/target/package coupling for Rust replacement without turning skipped or diagnostic jobs into qualification. Actual runner configuration, selected source/artifact and execution remain separate.
- [ ] `.github/workflows/id-persistence.yml` — Preserve existing active workflow, evidence/identity/lifecycle/publication contract; review any native build/source/target/package coupling for Rust replacement without turning skipped or diagnostic jobs into qualification. Actual runner configuration, selected source/artifact and execution remain separate.
- [ ] `.github/workflows/observe.yml` — Preserve existing active workflow, evidence/identity/lifecycle/publication contract; review any native build/source/target/package coupling for Rust replacement without turning skipped or diagnostic jobs into qualification. Actual runner configuration, selected source/artifact and execution remain separate.
- [ ] `.github/workflows/pages.yml` — Preserve existing active workflow, evidence/identity/lifecycle/publication contract; review any native build/source/target/package coupling for Rust replacement without turning skipped or diagnostic jobs into qualification. Actual runner configuration, selected source/artifact and execution remain separate.
- [ ] `CMakePresets.json` — Translate supported configure/build preset inheritance, names, architectures/toolchains, feature/dependency-source selections, tests/sanitizers and LTO into mandatory Rust target/build contracts; preserve script callers or update them together, prove selected flags/ABI/target closure and release payload. No named preset run or Rust archive linkage inferred.
- [ ] `COPYING` — Preserve repository copyright/license/attribution text and actual shipped notices; reconcile retained/replaced dependencies under separately reviewed licensing and package contracts, without a source-only claim of legal or installed-license qualification.
- [ ] `cmake/config.h.in` — Preserve generated platform/capability/native-selection header semantics while replacing obsolete C/C++ macro/config wiring; prove selected supported Rust target features rather than deleting config detection blindly.
- [ ] `docker/README.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `docker/entrypoint.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `lib/regex/regex.c` — Replace or explicitly reconcile bundled C regex implementation/interface and no-system-regex conditional static target; preserve regex syntax/locale/flags/matching/captures/errors/allocation/lifetime/ABI and native/transitive content proof for every supported system/bundled configuration. A conditional C library is a foreign-code input, not evidence of Rust-only operation.
- [ ] `lib/regex/regex.h` — Replace or explicitly reconcile bundled C regex implementation/interface and no-system-regex conditional static target; preserve regex syntax/locale/flags/matching/captures/errors/allocation/lifetime/ABI and native/transitive content proof for every supported system/bundled configuration. A conditional C library is a foreign-code input, not evidence of Rust-only operation.
- [ ] `linux/android/build-toolchain.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/build-info.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/buildroot/build-toolchain.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/buildroot/config/.config-aarch64` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/config/.config-armel` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/config/.config-armhf` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/config/.config-i686` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/config/.config-ppc6xx` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/config/.config-riscv64` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/config/.config-x86_64` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/patch/arm_acle.h.aarch64.patch` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/patch/musl.hash.patch` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/buildroot/patch/musl.mk.patch` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `linux/flatpak/README.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/build-flatpak.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/build-info.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/com.nzbget.nzbget.desktop` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/com.nzbget.nzbget.metainfo.xml` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/com.nzbget.nzbget.svg` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/com.nzbget.nzbget.yml` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/flatpak/nzbget-launcher.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/freebsd/build-toolchain.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/install-update.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/package-info.json` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/pkg/build-info.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/pkg/deb/DEBIAN/postinst` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/pkg/deb/DEBIAN/postrm` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/pkg/deb/DEBIAN/prerm` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/pkg/nzbget.service` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `linux/snap/snapcraft.yaml` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/android/build-info.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/android/install-update.sh` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/android/package-info.json` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/macos/App_Prefix.pch` — Replace native platform/controller/bridge implementation and compile coupling with qualified Rust ownership or explicitly adjudicated retained supported-platform interface; preserve app/daemon/window/RPC lifecycle, callbacks, cleanup and exceptions.
- [ ] `platforms/macos/MainApp.xib` — Preserve or deliberately replace window/dialog/control/menu/outlet/action wiring, accessibility and localized UI behavior for the Rust-owned app; prove actual resource loading and supported app lifecycle.
- [ ] `platforms/macos/NZBGet-Info.plist` — Preserve or deliberately replace bundle identifiers/version/executable/icon/document/OS and app metadata with supported Rust packaging; verify installed bundle behavior and actual selected payload.
- [ ] `platforms/macos/NZBGet.xcodeproj/project.pbxproj` — Replace native Objective-C source/link/precompile registration or explicitly reviewed retained platform bridge with supported Rust bundle build; preserve source/resource/copy phases, SDK/framework/architecture/deployment/ARC and executable/signing settings, then prove actual bundle closure.
- [ ] `platforms/macos/PreferencesDialog.xib` — Preserve or deliberately replace window/dialog/control/menu/outlet/action wiring, accessibility and localized UI behavior for the Rust-owned app; prove actual resource loading and supported app lifecycle.
- [ ] `platforms/macos/Resources/Credits.rtf` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/macos/Resources/Images/mainicon.icns` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/macos/Resources/Images/statusicon.png` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/macos/Resources/Images/statusicon@2x.png` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/macos/Resources/Localizable.strings` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/macos/Resources/Welcome.rtf` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/macos/Resources/licenses/license-bootstrap.txt` — Retain required shipped license notices and attribution for retained code; explicitly reconcile notices for actual replacement/removal without dropping obligations. Source presence is not replacement-license or installed-bundle proof.
- [ ] `platforms/macos/Resources/licenses/license-jquery-GPL.txt` — Retain required shipped license notices and attribution for retained code; explicitly reconcile notices for actual replacement/removal without dropping obligations. Source presence is not replacement-license or installed-bundle proof.
- [ ] `platforms/macos/Resources/licenses/license-jquery-MIT.txt` — Retain required shipped license notices and attribution for retained code; explicitly reconcile notices for actual replacement/removal without dropping obligations. Source presence is not replacement-license or installed-bundle proof.
- [ ] `platforms/macos/WelcomeDialog.xib` — Preserve or deliberately replace window/dialog/control/menu/outlet/action wiring, accessibility and localized UI behavior for the Rust-owned app; prove actual resource loading and supported app lifecycle.
- [ ] `platforms/macos/brew-info.md` — Retain or update supported macOS build/install documentation and metadata to match qualified Rust application/bundle/toolchain contracts; no old native instructions count as Rust build proof.
- [ ] `platforms/macos/build-info.md` — Retain or update supported macOS build/install documentation and metadata to match qualified Rust application/bundle/toolchain contracts; no old native instructions count as Rust build proof.
- [ ] `platforms/macos/sign/backgound.png` — Retain required bundle image/text/localization/credit/welcome/DMG assets or explicitly replace them under reviewed behavior and attribution; preserve referenced names, scales, translation and resource/signing/package inclusion.
- [ ] `platforms/windows/README-WINDOWS.txt` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/windows/build-info.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/windows/package-info.json` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/windows/pkgs-info.md` — Replace or explicitly reconcile native build/toolchain/dependency-fetch/unpacker/install/package/service/entrypoint coupling with exact qualified Rust runtime artifacts; preserve supported architecture, versions, feature/config/queue/provider safety, permissions, update authenticity, required assets/licenses and start/stop/error behavior. Documentation/placeholder assets may be retained after explicit review; generated/fetched contents and installed behavior remain unproved.
- [ ] `platforms/windows/resources/install.bmp` — Preserve or deliberately replace Windows dialog/menu/tray/icon/installer bitmap/resource IDs/version assets and native resource registration for supported Rust executable/installer packages; verify actual UI/service and package behavior with required attribution.
- [ ] `platforms/windows/resources/mainicon.ico` — Preserve or deliberately replace Windows dialog/menu/tray/icon/installer bitmap/resource IDs/version assets and native resource registration for supported Rust executable/installer packages; verify actual UI/service and package behavior with required attribution.
- [ ] `platforms/windows/resources/trayicon_idle.ico` — Preserve or deliberately replace Windows dialog/menu/tray/icon/installer bitmap/resource IDs/version assets and native resource registration for supported Rust executable/installer packages; verify actual UI/service and package behavior with required attribution.
- [ ] `platforms/windows/resources/trayicon_paused.ico` — Preserve or deliberately replace Windows dialog/menu/tray/icon/installer bitmap/resource IDs/version assets and native resource registration for supported Rust executable/installer packages; verify actual UI/service and package behavior with required attribution.
- [ ] `platforms/windows/resources/trayicon_working.ico` — Preserve or deliberately replace Windows dialog/menu/tray/icon/installer bitmap/resource IDs/version assets and native resource registration for supported Rust executable/installer packages; verify actual UI/service and package behavior with required attribution.
- [ ] `platforms/windows/resources/uninstall.bmp` — Preserve or deliberately replace Windows dialog/menu/tray/icon/installer bitmap/resource IDs/version assets and native resource registration for supported Rust executable/installer packages; verify actual UI/service and package behavior with required attribution.
- [ ] `pubkey.pem` — Preserve existing public update-verification trust anchor and authenticity compatibility; replacing it requires a separately reviewed release/key-transition contract. Do not substitute the Git signing key or disable package verification; capture the actually shipped key and signature/installer binding.
- [ ] `qnap/README.md` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/arm-x19/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/arm-x31/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/arm-x41/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/arm_64/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/build_sign.csv` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/config/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/icons/nzbget.gif` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/icons/nzbget_gray.gif` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/package_routines` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/qpkg.cfg` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/shared/nzbget.sh` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/x86/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/x86_64/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/package/x86_ce53xx/.gitkeep` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/repack-info.md` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `qnap/repack-nzbget.sh` — Replace or explicitly reconcile QNAP repacked installer/native daemon/unpacker payload with exact qualified Rust artifacts; preserve architecture/platform package metadata, signing, icons, service/install/uninstall/config/upgrade and user data contracts. Placeholder or documentation source is retained metadata, not observed package contents.
- [ ] `toolchains/android/build-toolchain.sh` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `toolchains/android/setup-android-toolchain.sh` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.
- [ ] `toolchains/macos/build-libcxx.sh` — Replace or explicitly reconcile native compiler/libc/libstdc++/SDK/cross-toolchain build/config/patch inputs with supported Rust targets; preserve architectures, ABI/libc/linker/features/hardening and target support. Audit generated/downloaded toolchain and linked foreign-language artifacts independently.

## Build and installation guides

Immutable snapshot bindings and pending guide dispositions are in `dependency-sources.json`. Update native dependency/compiler/link/package requirements, mandatory Rust target/preset instructions and evidence-backed feature/performance statements with the actual replacement; verify final links and generated/published site separately. Other documentation/publication reconciliation remains part of final retirement.

- [ ] `docs/POSIX.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `docs/WINDOWS.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `docs/MACOS.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `docs/ANDROID.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `site/content/install.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `README.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `INSTALLATION.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `docs/CONTRIBUTING.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `site/content/contributing.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `site/content/rust-port.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `site/content/performance.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.
- [ ] `docs/PERFORMANCE.md` — Preserve or update supported build/install/contribution/performance documentation and published site source to match qualified mandatory Rust targets and actual retained dependencies, compiler/toolchain/version/features/platforms/commands/link flags/presets/packages/ABI and config/upgrade contracts. Remove obsolete C++/Boost/native instructions and unsupported equivalence or speed claims only with source-bound replacement evidence. Verify links and generated publication separately; source documentation is not an executed build or deployed site.

## Complete-daemon functional contract sources

All40 checked-in `tests/functional` source inputs have immutable bindings and pending preservation rows, including the nine `dupefallback` harness/generator/focused/platform inputs. The fallback harness drives a scratch daemon and its NNTP fixture; its stream/live/retry/encrypted/decompression/cleanup contracts supplement partial helper sources. Source availability is not test execution, Rust boundary coverage, equivalent C++ behavior or qualification. Run admission, fixture isolation, exact binary/source lineage and supported Local/Docker/ADB architectures remain required.

- [ ] `tests/functional/conftest.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/conftest.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/download_base_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/download_filename_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/download_opt1_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/download_opt2_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/download_opt3_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/dupecheck_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/health_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/propagation_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/retry_base_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/retry_opt1_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/retry_opt2_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/download/unpack_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/archive_stall_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/generators.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/harness.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/history_retry_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/par_first_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/queue_format_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/run-android.sh` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/run-linux-docker.sh` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/dupefallback/run-local.sh` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/editqueue/editqueue_move_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/conftest.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_base_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt1_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt2_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt3_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt4_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt5_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt6_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/parcheck/parcheck_opt7_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/conftest.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/rename_base_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/rename_opt1_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/rename_opt2_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/rename_opt3_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/rename_opt4_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.
- [ ] `tests/functional/rename/rename_opt5_test.py` — Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.

## Build and dependency retirement

- [ ] Replace optional Rust build selection and every C++ fallback with supported mandatory Rust builds on all supported targets.
- [ ] Replace C++ application CMake/source registration and C++ ABI adapters once their Rust owners exist.
- [ ] Inventory third-party libraries and downloads in build scripts; record which dependencies still compile C++ and replace or eliminate them before claiming C++-free operation.
- [ ] Replace RapidYenc's C++ decode/CRC/platform backend and remove its library and callbacks after full caller qualification.
- [ ] Replace PAR2-turbo repair interfaces and inventory/retire its GF16/hasher nested native targets after qualification; reconcile every shipped license/disclosure asset.
- [ ] Replace runtime Boost JSON/Asio and carry Boost Test assertions into Rust before removing the C++ targets and test entry point.
- [ ] Audit and retire or explicitly reconcile packaged unpacker executables against the complete Rust migration objective.
- [ ] Retire checked-in C++ differential harnesses under `rust/tests` after preserving historical evidence and translating regression assertions into Rust.
- [ ] Audit Objective-C/platform wrappers, packaging, installer entry points, and cross-compilation support; record every retained non-Rust surface and resolve it against the full migration objective.
- [ ] Prove final source inventory and runtime build contain no remaining application C++ or C++ dependencies covered by the objective.

## Remaining holds and current contribution policy

- The 2x hard floor against both original and equally improved C++ cannot be presumed for every routine. A failed gate keeps that candidate open; it must not be marked migrated or replaced by an indefinitely retained fallback.
- Deferred PR #80/#86/#87/#91/#93 validation and backend holds are preserved. A new default source tree requires fresh applicability/lineage decisions.
- Canonical commit `7d3d6412` removed `docs/AI_POLICY.md` and its references from `AGENTS.md` and the PR template. The earlier human-authored-description/testing restriction is superseded; new PRs follow the current template, evidence requirements and both Codex review gates.

## Preserve ancillary Rust test inputs and original evidence

These preservation gates require retention of the original bytes and source identities before any test-directory cleanup or native-target retirement. Checking a row records reviewed preservation/disposition, not deletion of historical evidence or current execution. The 77 inputs (70 Latin1 evidence artifacts, one Cargo integration test and six ancillary inputs) match the original snapshot, supplemental audit and reachable source. Historical logs, metadata, summaries, verdicts and encoded runtime patch remain independent; their stored claims are not promoted to current qualification.

- [ ] `rust/tests/deadpostings/README.md` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/dupesearch_nzb/.gitignore` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/dupesearch_nzb/README.md` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/.gitignore` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/README.md` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/artifact-sha256.txt` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-0-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-0-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-1-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-1-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-2-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-2-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-3-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-3-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-4-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-4-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-5-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-5-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-6-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-6-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-7-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-7-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-8-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/current/latin-whole-8-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/fixture-sha256.json` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/latin-ci-summary.json` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/latin-whole-summary.json` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/metadata.json` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-0-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-0-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-0-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-1-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-1-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-1-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-2-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-2-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-2-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-3-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-3-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-3-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-4-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-4-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-4-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-5-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-5-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-5-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-6-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-6-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-6-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-7-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-7-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-7-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-8-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-8-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-ci-8-standin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-native-0-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-native-0-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-native-1-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-native-1-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-native-2-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-native-2-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-standin-0.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-standin-1.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/latin-standin-2.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-native-0-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-native-0-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-native-1-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-native-1-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-native-2-after.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-native-2-before.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-standin-differential.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/prior/ready-standin-readylatin.log` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/review-verdict.txt` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/reviewed-runtime.patch.b64` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/latin1_caller/evidence/runtime-source-sha256.txt` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/renameanalyzer_allocations.rs` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.
- [ ] `rust/tests/streamcompare.md` — Preserve original bytes and immutable binding independently; carry required Rust test/documentation contracts forward under reviewed ownership before directory/target retirement. Stored evidence is not requalified.

## Preserve native fixtures and Rust benchmark inputs

Before retiring C++ tests or Cargo/native benchmark targets, retain these independently bound original bytes and translate required input/regression contracts under reviewed ownership. The entire 70-file native fixture corpus and three registered Rust benchmark inputs match the original source, supplemental audit and fresh default. Fixtures are opaque bytes, including archives and malformed/encoding inputs. Benchmark registration is source evidence: Rust-only histories and kernel diagnostics do not qualify a matched complete caller or establish current execution.

- [ ] `tests/testdata/dupematcher1/testfile.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupematcher1/testfile.part24.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupematcher2/testfile.part04.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupematcher2/testfile.part43.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupesearch/error_bad_apikey.xml` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupesearch/release_matching.tsv` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupesearch/search_industry_s03e07.xml` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/dupesearch/short_query.tsv` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/V1/Extension.py` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/manifest/invalid/manifest.json` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/manifest/valid/manifest.json` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/scripts/Email/email.py` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/scripts/Email/manifest.json` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/scripts/Extension1.py` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/scripts/Extension2/Extension2.py` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/extension/scripts/Extension3.py` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/feed/feed.xml` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/feed/feed2.xml` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/dotless.nzb` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/dotless.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/literal_gt.nzb` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/literal_gt.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/passwdEntity.nzb` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/passwdEntity.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/passwdMeta.nzb` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/passwdMeta.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/passwd{{thisisthepassword}}.nzb` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/passwd{{thisisthepassword}}.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/plain.nzb` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/nzbfile/plain.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/crc.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/testfile.dat` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/testfile.nfo` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/testfile.par2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/testfile.vol00+1.PAR2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/testfile.vol01+2.PAR2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker/testfile.vol03+3.PAR2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/crc.txt` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.001` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.002` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.003` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.par2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.vol0+1.PAR2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.vol1+2.PAR2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parchecker2/testfile.7z.vol3+3.PAR2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parcheckerUtf8/ä½ å¥½ä¸ç.par2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parcheckerUtf8/ä½ å¥½ä¸ç.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parcheckerUtf8/ä½ å¥½ä¸ç.vol000+128.par2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/parcheckerUtf8/ä½ å¥½ä¸ç.vol128+071.par2` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3.part02.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3.part03.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3encdata.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3encdata.part02.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3encdata.part03.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3encnam.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3encnam.part02.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3encnam.part03.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3oldnam.r00` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3oldnam.r01` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile3oldnam.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5.part02.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5.part03.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5encdata.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5encdata.part02.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5encdata.part03.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5encnam.part01.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5encnam.part02.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `tests/testdata/rarrenamer/testfile5encnam.part03.rar` — Preserve exact original fixture bytes and immutable identity; carry required malformed/archive/repair/encoding and caller input contracts into reviewed replacement tests before native target retirement. UNRUN in this audit.
- [ ] `rust/benches/README.md` — Preserve registered Rust benchmark/toolchain/feature/documentation contracts and independent existing Rust regression/diagnostic history before target retirement; keep Rust-only/kernel and complete-caller qualification distinct. UNRUN in this audit.
- [ ] `rust/benches/criterion_ports.rs` — Preserve registered Rust benchmark/toolchain/feature/documentation contracts and independent existing Rust regression/diagnostic history before target retirement; keep Rust-only/kernel and complete-caller qualification distinct. UNRUN in this audit.
- [ ] `rust/benches/ports.rs` — Preserve registered Rust benchmark/toolchain/feature/documentation contracts and independent existing Rust regression/diagnostic history before target retirement; keep Rust-only/kernel and complete-caller qualification distinct. UNRUN in this audit.

## Preserve migration controllers and canonical documentation

The entire tracked shared benchmark and coverage-controller inputs, their schemas/regression fixtures, canonical Rust-port content and site generator have independent immutable pending dispositions. These rows preserve source contracts; they do not prove controller execution, tool activation, coverage, performance, or generated-site publication. The benchmark target inputs also remain separately bound in the source inventory.

- [ ] `docs/RUST_COVERAGE_PROCEDURES.md` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `rust/PORTING.md` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/adapters/postprocess.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/adapters/rpc.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/collect_receipt.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/preflight.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/publish.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/run.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/schema/manifest.schema.json` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/schema/qualification.schema.json` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/schema/sample.schema.json` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/summarize.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/fixtures/action-resolution.json` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/fixtures/synthetic-manifest.json` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/fixtures/synthetic-samples.jsonl` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_action_pins.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_archive.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_collect_receipt.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_pipeline.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_postprocess_adapter.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_preflight.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_publish.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_rpc_adapter.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_run.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/bench/tests/test_summarize.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/coverage/assess.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/coverage/schema/scope.schema.json` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `scripts/coverage/tests/test_assess.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.
- [ ] `site/build.py` — Preserve or update required migration measurement/validation/schema/fixture/authenticated-publication, benchmark or canonical documentation/generation contracts under reviewed ownership. Retain historical evidence independently; source-only UNRUN, no execution/qualification/site publication inferred.

## Historical nanobench evidence preservation

Separate from the active benchmark pipeline, preserve the exact original packet and additive source snapshots independently before ContentMap/ReadDonorInner/cryptoread retirement. The immutable Git/byte/SHA-256 identities and historical limitations are recorded in `dependency-sources.json`. These rows stay unchecked until preservation and required contract translation are reviewed; no original benchmark, archived recorder, verifier or regression was executed by this audit and cryptoread remains held.

- [ ] `benchmarks/nanobench-poc/README.md` — historical source/capture/publication limitations and current qualification hold; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/export-manifest.json` — retrospective export identity and missing original environment/receipts; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/index.html` — additive publication viewer with historical limits; embedded historical data; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/manifest.json` — historical measured source/executable/library identities and methods; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/negative-route-check.json` — retained 134-byte failed-route capture, no timing rows; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/original-evidence-manifest.json` — original historical source/evidence bundle member identities; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/proof-of-concept.zip` — opaque original historical source/recorder/template/header/results/viewer archive; preserve byte for byte; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/proof.html` — original historical viewer and claims retained as evidence, not endorsed qualification; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/results.json` — original historical per-process results and all sample rows; preserve without reanalysis/replay; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/source-snapshot-manifest.json` — additive measured candidate/baseline C++/Rust/ABI/context source member identities; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/source-snapshot.zip` — opaque additive measured held candidate/baseline C++/Rust/ABI/context/license source archive; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/test_verify.py` — packet-specific bounded integrity/custody regression source; UNRUN here; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
- [ ] `benchmarks/nanobench-poc/verify.py` — packet-specific artifact-integrity verifier source; integrity success separate from qualification HOLD; UNRUN here; preserve original bytes, historical failed/partial evidence and required integrity/caller contracts independently. Source-only UNRUN, no current native or >=2x qualification.
