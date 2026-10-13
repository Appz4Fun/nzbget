# Rust Duplicate-Family Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete a selected download, its associated duplicates, their owned disk files and all entries through one Rust operation with only Delete/Cancel, qualify it faster than fair optimized C++, remove replaced C++ business bodies, and obtain final-head Codex signoff before Root merges into `dupe-article-fallback`.

**Architecture:** Rust owns family/ownership planning, durable state transitions and cleanup policy. C++ supplies bounded daemon snapshots, lifecycle/serialization primitives and descriptor operations. The fallback owner alone implements shared recovery fences; purge waits outside daemon locks and publishes success only after filesystem and persistence acknowledgments.

**Tech Stack:** Existing Rust 1.99.0 crate (edition 2021, aborting panic), C++20 daemon, POSIX descriptor primitives, authenticated XML/JSON RPC, existing jQuery WebUI and Playwright fixture checks; no new product dependency.

**Spec:** `docs/superpowers/specs/2026-10-13-duplicate-family-purge-design.md`, signed commit `345097648e26f4758b1b9aad69261dc30dfa621f`, approved by the maintainer on 2026-10-13.

## Global Constraints

- Source planning base: `7d3d6412f93cd43452f1b390b4ed705c7691df54`; preserve merged toolbar PR #99 and Settings PR #98. Refresh the actual default before composition.
- The operation phases are `prepared`, `stopping`, `quiescent`, `cleaning`, `persisting`, `complete`, and `failed`.
- Cancel starts no purge and sends no mutating RPC. Confirmed success requires the complete family, files and entries removed; safe rejection is not delivery of that outcome.
- No title/key transitive closure, guessed paths, global `StopAll/WaitAll`, stale-result success, C++ full-purge production fallback or BinRPC seven-field change.
- Fixed worker-global locks are `/tmp/i7-heavy.lock` exclusive followed by `/tmp/nzbget-rust-benchmark.lock` shared for builds/tests. Prebuilt bounded timing holds only the benchmark lock exclusively and releases it after each process. Admission cap defaults to 120 seconds; assigned cap may be stricter; no stage exceeds three jobs.
- Only Twin admits heavy work; Root owns default integration. Existing native v7 work retains priority. No production filesystem scan/traffic/deletion or deployment is authorized.
- Every new commit: author and committer `xbmc4lyfe <273732874+xbmc4lyfe@users.noreply.github.com>`, registered local SSH signature, canonical HTTPS remote and verified credential-helper override. Verify each published commit through GitHub before integration.
- Preserve existing Rust `fsdelete`/`fsops` callers independently. C++ instrumentation around an ordinary Rust archive is not Rust sanitizer coverage.
- Each changed compared caller requires the paired Rust/C++ ratio's upper confidence bound below 1 against the fair optimized comparator. Applicable Rust preservation requires an upper bound at most 1.
- Control drift, failure, under-floor or invalid rows, missing evidence, and an interval admitting regression produce HOLD. Preserve every raw attempt; changed source/method gets a new prospective identifier.
- Approval of this plan does not waive missing legacy ownership, owner agreement, worker admission, speed qualification, fresh final-head reviews or backend deployment holds.

## Review Focus

1. Same numeric IDs after restart or a fresh download: stale token/ack must never erase the new incarnation (Tasks 1, 3, 6, 10).
2. A lost HTTP response or two clients selecting overlapping families: one durable operation or explicit conflict, never duplicate cleanup (Tasks 3, 8, 9).
3. A rename replaces a child between inspection and unlink: capture must preserve the replacement and report conflict; inode precheck alone is insufficient (Task 5).
4. Worker output arrives after initial intent, or shutdown happens between cleanup and publication: durable inventory/receipts precede destruction and survive restart (Tasks 3, 4, 6, 7).
5. Rust/platform support is unavailable, or a legacy client invokes the old path: explicit unsupported response, no silent incomplete fallback (Tasks 8, 9, 10).

## File and Interface Map

| Files | Responsibility |
| --- | --- |
| New `rust/src/dupepurge.rs` | Owned identity/ownership planner, phase machine, action ordering and outcomes |
| New `rust/src/purgejournal.rs` | Bounded versioned intent/inventory/action framing, retry/recovery policy |
| New `rust/src/purgefs.rs` | Rust descriptor traversal/capture/cleanup policy through mechanical host primitives |
| `rust/src/lib.rs`, `rust/src/ffi.rs`, `rust/include/nzbget_rs.h` | Module registration and version-1 bounded ABI |
| New `daemon/queue/DupePurgeCoordinator.{h,cpp}` | Snapshot, host callbacks, progress tick and durable operation registry |
| New `daemon/util/PurgeFileOps.{h,cpp}` and `PurgeJournalOps.{h,cpp}` | Platform descriptor/capture and checked journal publication primitives; no family or recursive-cleanup policy |
| `daemon/queue/DownloadInfo.{h,cpp}`, `DiskState.{h,cpp}`, `HistoryCoordinator.{h,cpp}` | Immutable incarnation/marker, ownership retention, acknowledged persistence and final object erasure |
| Queue/Post/URL/Scanner adapters and `daemon/main/nzbget.cpp` | Affected-writer registration, startup recovery before admission, shutdown custody |
| Fallback-owner `DupeArticleFallback`, `TwinCheck`, `DupeProbe`, `DupeSearch`, repair adapters | Owner-implemented scoped admission/cancel/drain/publication/cache interfaces |
| `daemon/remote/XmlRpc.cpp`, `webui/downloads.js`, `webui/index.html`, locale catalogs | Dedicated purge/status RPC and two-choice UI |
| `daemon/sources.cmake`, test CMake lists | Source/test registration and explicit unsupported build behavior |
| New queue/remote/WebUI tests and `rust/tests/dupepurge/` | Actual caller fixtures, error/restart cases, fair reference controls and preserved-boundary evidence |

Proposed common types (freeze with the fallback owner in Task 1): `RequestToken = [u8;16]`; `Generation = u64` (zero invalid); `MemberBinding { collection_id:i32, file_id:Option<i32>, incarnation:u64, posting_source:Vec<u8> }`; `PurgeToken { request:RequestToken, generation:Generation, members:Vec<MemberBinding> }`. C ABI uses flat POD records and counted byte slices, never Rust vectors or C++ object pointers. Posting/source bytes are independently validated immutable bindings, not a title authority.

Shared proposed interfaces are `FenceAndCancel(const PurgeToken&) -> FenceReply`, `PollPurgeQuiescence(const PurgeToken&) -> DrainReply`, `RemovePurgeArtifacts(const PurgeToken&) -> CleanupReply`, and `ReleasePurgeFence(const PurgeToken&) -> ReleaseReply`. `DrainReply` distinguishes pending, exact-token `QuiescedAck`, and error; cancellation acceptance is not drain completion. These names are proposals until joint declaration review; do not wire substitute APIs independently.

Rust interfaces: `prepare(snapshot: Snapshot, request: RequestToken) -> Result<Plan,PurgeError>`, `advance(plan: &mut Plan, host: &mut dyn Host) -> Result<Progress,PurgeError>`, and `recover(frame: &[u8], host: &mut dyn Host) -> Result<Plan,PurgeError>`. `Snapshot` owns member bindings, raw name/key bytes, validated root/entry identities, outside claims and directed anchor matches. `Plan` owns that snapshot, token, phase, actions and receipts. `PurgeError` distinguishes invalid input, missing inventory, conflict, pending/timeout, unsupported platform, I/O and persistence failure.

Initial bounded limits: 4,096 seeds, 65,536 members, 1,000,000 inventory entries, 64 MiB total snapshot/frame payload, 1,023 path bytes, 65,535 identity bytes. Reject embedded NUL, truncation, arithmetic overflow, unsupported objects and allocation failure before mutation. Any limit change is reviewed and reflected in tests and frozen fixtures.

---

### Task 1: Freeze Shared Tokens and Ownership Authority

**Files:** Create `docs/dupepurge-contract.md`, `rust/tests/dupepurge/source-map.json`; inspect `DownloadInfo`, `DupeCoordinator`, `HistoryCoordinator`, `DiskState`, fallback-owner interfaces.

**Interfaces:** Produces the source-bound token/lock/call-site agreement and inventory applicability map consumed by every task.

- [ ] Capture fresh default/source hashes and preserve current Rust/C++ boundary sources, signed history and existing adverse evidence.
- [ ] Freeze the proposed bounded types/declarations with Root and the fallback owner. Specify every queued/active/pinned/publication registration and release, scanner admission, stop result, output delta and cache removal acknowledgment. Queue/provider/fallback/network waits never nest.
- [ ] Define incarnation assignment on creation/load and persistent monotonic generation allocation; max `u64` fails before admission. Pin numeric IDs to parent membership and immutable posting/source identity. Record locale comparison semantics of `SameNameOrKey` without closure.
- [ ] Resolve legacy `hkDup` ownership applicability from an independently validated historical snapshot/catalog if one exists. Record immutable custody, ID/incarnation/posting/path binding and outside ownership claims before import. Title, size, content hash, current category and NZB-internal filename alone are insufficient.
- [ ] Record missing legacy authority as a delivery GAP. Do not invent an importer input, use an unknown file path, or count future retention/rejection as fulfillment. Full-goal delivery remains held until this gap has an independently reviewed resolution or explicit human acceptance of unsupported scope.
- [ ] Review and sign the contract/source map. No shared runtime edits precede the declaration agreement.

### Task 2: Rust Family and Ownership Planner

**Files:** Create `rust/src/dupepurge.rs`, `rust/tests/dupepurge/planner.rs`; modify `rust/src/lib.rs`, `rust/src/ffi.rs`, `rust/include/nzbget_rs.h`.

**Interfaces:** Implements `prepare`; produces owned `Plan`, selected `MemberBinding` set and ordered ownership actions. Locale byte comparison uses the existing caller's mechanical `strcasecmp` primitive; family policy remains Rust-owned. Add version-1 `nzbget_rs_purge_prepare` and `nzbget_rs_purge_destroy` with bounded POD snapshots and owned handles now, before C++ callers need them.

- [ ] Write `anchors_do_not_bridge_conflicting_keys`, `direct_bindings_include_queue_post_history_compact`, `outside_claim_prevents_recursive_cleanup`, `reused_seed_and_unknown_inventory_fail`, and bounded-input tests. Assertions: keyed A and B never join through an unkeyed title; verified direct binding joins; absent/changed seed and unknown compact inventory yield error with zero actions; shared roots stay intact.
- [ ] Under Twin admission, run the new planner tests and retain RED output proving the missing planner, not a fixture/tool failure.
- [ ] Implement bounded owned snapshots, direct anchored matching, deduplication and outside ownership conflict detection. Allocate all necessary initial planning storage with checked `try_reserve`; preserve non-UTF8/case/locale behavior and reject malformed IDs/paths before mutation.
- [ ] Run the exact tests GREEN plus the preserved identity callers; inspect action/member lists, not only exit status.
- [ ] Commit signed planner and tests; record immutable source/tree and test receipts.

### Task 3: Durable State Machine, Idempotency and Overlap Leases

**Files:** Create `rust/src/purgejournal.rs`, `rust/tests/dupepurge/journal.rs`; modify `dupepurge.rs`, `rust/src/ffi.rs`, `rust/include/nzbget_rs.h`; create `daemon/util/PurgeJournalOps.{h,cpp}` and `tests/queue/PurgeJournal.cpp`; register in source/test CMake lists.

**Interfaces:** `encode(plan:&Plan) -> Result<Vec<u8>,PurgeError>` and `decode(bytes:&[u8]) -> Result<Plan,PurgeError>`; `reserve(request, snapshot) -> Existing|New|Conflict`; `append_inventory` and pending/completed action receipts. Host durable-write callbacks return explicit sync/publication acknowledgments. Add version-1 `nzbget_rs_purge_tick` and `nzbget_rs_purge_inventory_store(binding, delta, host_ops, out_error)` now. The latter writes a bounded binding/inventory frame through a checked journal callback; operation frames and retained inventory frames have distinct tags.

- [ ] Write `lost_response_same_token_same_operation`, `changed_request_token_conflict`, `overlapping_namespaces_one_lease`, `generation_overflow_no_mutation`, `truncated_frame_retained_failure`, and restart tests for all seven phases. An old completed receipt must not authorize a new replacement object.
- [ ] Run RED and preserve each attempt.
- [ ] Implement version-1 length-prefixed frames with explicit counts, raw bytes and a checksum using the existing `md-5` dependency (corruption detection, not authentication). Persist generation high-water mark, request fingerprint, bindings, inventory and per-action outcomes. Validate all bounds before allocation; no panic/OOM recovery fiction.
- [ ] Implement `advance` phase transitions with test hosts, plus descriptor-anchored private journal publication in `PurgeJournalOps` (checked write, sync, immutable sequence-frame no-replace publication and directory sync). Missing host capabilities return unsupported; no production RPC exposes partial support. Acknowledge prepared intent/overlap reservation before cancellation; acknowledge appended output inventory before destruction; persist pending action before mutation and completed receipt afterward. Pending/completed receipts may be durably batched while retaining every action identity/outcome. Retain fences on error/shutdown; intentional fresh work uses a new incarnation/token after explicit successful release.
- [ ] Run GREEN including write/sync/rename failures and replay with substituted identities. Sign the state machine/journal tests.

### Task 4: Retain Authoritative Inventory Before Metadata Loss

**Files:** Modify `HistoryCoordinator.{h,cpp}`, `DiskState.{h,cpp}`, `DownloadInfo.{h,cpp}`, `daemon/nntp/ArticleWriter.cpp`, `daemon/postprocess/UnpackController.cpp`, `PrePostProcessor.cpp`; create `tests/queue/PurgeInventory.cpp`; register in `tests/queue/queue.cmake`.

**Interfaces:** `RecordPurgeInventory(const MemberBinding&, const InventoryDelta&) -> DurableAck`; `LoadPurgeInventory(const MemberBinding&) -> InventoryReply`. Delta contains actual recorded output/queued NZB/intermediate/state paths, descriptor identity and namespace ownership claims. Rust journal owns framing/policy (Task 3); C++ captures concrete writer metadata.

- [ ] Write `history_hide_retains_success_paths`, `merged_nzb_paths_all_retained`, `shared_final_directory_only_owned_names`, `late_unpack_output_precedes_compaction`, and `inventory_save_failure_retains_full_record`. Check actual DestDir/FinalDir/hardlink/completed outputs; reject title reconstruction.
- [ ] Run RED on the approved worker. The compaction test must show historical path loss on the original source.
- [ ] Add acknowledged inventory capture at actual creation/move/unpack/complete boundaries and before every full-record compaction/destruction. If inventory acknowledgment fails, preserve the full source record and explicit failure. For shared output namespaces retain specific names; unknown writer output cannot become broad recursive authority.
- [ ] Connect only the authoritative legacy recovery source accepted in Task 1. If none exists, keep GAP/error behavior and delivery hold; never silently erase compact rows.
- [ ] Run GREEN with ordinary history retention/failover controls unchanged; sign the inventory adapters/tests.

### Task 5: Descriptor-Safe Rust Cleanup

**Files:** Create `rust/src/purgefs.rs`, `daemon/util/PurgeFileOps.{h,cpp}`, `rust/tests/dupepurge/filesystem.rs`, `tests/util/PurgeFileOps.cpp`; register sources/tests.

**Interfaces:** `execute_action(action:&Action, host:&mut dyn FileOps) -> ActionOutcome`. Host primitives: open root/child no-follow, enumerate with explicit EOF/error, stat identity, atomically capture child into a private no-replace quarantine, sync namespace, remove captured object, and preserve/restore mismatches without overwrite. Handles are owned integers scoped to the call/operation, not unchecked path strings.

- [ ] Write real-tree tests `ancestor_symlink_refused`, `root_and_traversal_refused`, `swap_before_capture_preserves_replacement`, `occupied_restore_preserves_both`, `mount_boundary_refused`, `shared_extra_file_survives`, `unrelated_hardlink_name_survives`, and `read_error_not_absence`.
- [ ] Run RED under approved worker custody; seed unrelated sentinels and compare their bytes/metadata after every attempt.
- [ ] Implement Rust traversal/action policy over no-follow anchored descriptors. Capture names atomically before destructive work and compare the captured object's expected identity. Reject mismatches; retain durable recovery location and never overwrite an occupied restoration name. An inode precheck followed by name-based unlink is not an accepted implementation.
- [ ] Recursion is permitted only for proved exclusive, fenced namespaces with complete inventory. Unknown/mount/external-writer entries fail explicitly; shared namespaces delete only recorded owned entries. Platform primitives without proved capture/confinement return unsupported before mutation.
- [ ] Run GREEN with repeated deterministic swaps, interrupted capture/restore and permission failures. Independently run the current `fsdelete` differential caller; preserve those bodies and semantics. Sign cleanup and mechanical primitives.

### Task 6: Register and Drain Actual Affected Writers

**Files:** Create `DupePurgeCoordinator.{h,cpp}`, `tests/queue/DupePurgeDrain.cpp`; modify `QueueCoordinator`, `PrePostProcessor`, `UrlCoordinator`, Scanner adapters. Shared fallback API changes belong to the fallback owner under Task 1 agreement.

**Interfaces:** Implements host `FenceAndCancel`, `PollPurgeQuiescence`, `RemovePurgeArtifacts` and `ReleasePurgeFence`; `DupePurgeCoordinator::Tick()` supplies fresh bounded host context to Rust `advance`.

- [ ] Write `stop_acceptance_not_quiescence`, `active_article_post_url_and_live_writer_drain`, `stale_pinned_result_refused`, `late_scanner_submission_refused`, `unrelated_donor_continues`, and `timeout_retains_fence`. Require actual queued/active/pinned/publication accounting plus output inventory acknowledgments, not `IsRunning`/`GetActiveDownloads` alone.
- [ ] Run RED against owner-approved source foundations and retain registration hit counts.
- [ ] Install purge marker under Guard after prepared intent; request scoped stops then release Guard. Poll outside queue/provider/Rust locks with a bounded service tick. Reacquire Guard and revalidate exact generation/incarnation/posting token before mutation; never retain `NzbInfo*` across unlocked work.
- [ ] Integrate fallback-owner drain and separate cache/pending cleanup ACK. Suppress purge-owned ordinary history/retry/script/donor admissions; fence future Scanner/AddExternalFile publication for exact bindings. No global stop API substitute.
- [ ] Run GREEN including completions concurrent with cancellation, reused IDs and two unrelated active families. Sign only purge-owned adapters; bind the exact fallback-owner dependency commit and review.

### Task 7: Acknowledged Final Erasure and Startup Recovery

**Files:** Modify `DiskState.{h,cpp}`, `HistoryCoordinator.{h,cpp}`, `QueueCoordinator.cpp`, `daemon/main/nzbget.cpp`; create `tests/queue/DupePurgeRecovery.cpp`.

**Interfaces:** `PersistPurgeRemoval(const PurgeToken&) -> DurableAck`; `RestorePurgeFencesBeforeAdmission() -> RecoveryReply`. The purge persistence route checks actual write/flush/sync/rename/directory sync results rather than the existing void save/warning-only contract.

- [ ] Write `cleanup_failure_keeps_entries_inventory`, `queue_save_failure_not_complete`, `history_publish_failure_recoverable`, `restart_before_any_worker_admission`, and `shutdown_status_retained`. Restart from every recorded mutation boundary.
- [ ] Run RED and prove the original save/erase boundaries do not meet acknowledgments.
- [ ] Implement checked purge publication of queue/history with retained in-memory ownership until successful acknowledgment. Erase numeric file/article/log and scoped discovery state through Rust actions with checked outcomes, including success-state remnants and all kept/merged NZB inputs independent of ordinary cleanup preference.
- [ ] Restore retained intent, high-water generation, overlap leases and error/status lookup before ordinary worker/scanner/post admission. Reconcile partial publication from durable receipts; corrupt/mismatched intent remains explicit retained failure, not stale queue activation.
- [ ] Run GREEN; assert exact entries/files absent only on complete and all unrelated state preserved. Sign acknowledged persistence/recovery changes.

### Task 8: Bounded FFI and Authenticated Purge RPC

**Files:** Modify `rust/src/ffi.rs`, `rust/include/nzbget_rs.h`, `daemon/remote/XmlRpc.cpp`, `daemon/sources.cmake`, `cmake/rust.cmake`; create `tests/remote/DupePurgeRpc.cpp`; register in `tests/remote/remote.cmake`.

**Interfaces:** Harden the ABI v1 from Tasks 2–3: `nzbget_rs_purge_prepare(snapshot, token, out_handle, out_error)`, `nzbget_rs_purge_tick(handle, host_ops, out_progress)`, `nzbget_rs_purge_destroy(handle)`. RPC `purgedownloads(token_hex, ids)` and read-only `purgedownloadstatus(token_hex)`/`purgedownloadoperations(ids)` return operation ID, phase, error code and counts, not private path/provider contents.

- [ ] Write malformed pointer/count/overflow/allocation/callback-exception/lifetime tests and RPC tests for POST-only mutation, auth, same-token replay, overlap conflict, pending-versus-complete, restart status and `legacy_group_delete_rpc_requires_purge`. Unsupported builds/platforms must report explicit unsupported, never invoke legacy deletion.
- [ ] Run RED through the actual C ABI and XML/JSON dispatcher.
- [ ] Implement owned opaque handles and bounded POD slices. C++ callbacks catch/store exceptions and return structured abort; no C++ unwind through Rust. Borrowed input exists only during synchronous capture; per-tick host context expires after the call.
- [ ] Register dedicated RPC commands under existing control authentication and mutating-method rules; reject mutating GET. External `editqueue` group-deletion variants and `PostDelete` return an explicit migration error requiring the idempotent purge RPC; they cannot silently preserve the old incomplete user deletion. Keep direct internal QueueEditor/failover/retention call meanings unchanged and audit all callers. Tick the real coordinator without busy waits; status lookup remains read-only and authenticated. Preserve BinRPC fields.
- [ ] Run GREEN, including Rust-unavailable and forced-platform-unsupported configurations. Sign FFI/RPC and required build registration.

### Task 9: One Delete/Cancel WebUI Flow

**Files:** Modify `webui/downloads.js`, `webui/index.html`, `webui/locales.source.json`, `webui/_locales/*/messages.json`; create `tests/webui/downloads-purge.js`; update `tests/webui/README.md`.

**Interfaces:** Shared `DownloadsUI.deleteConfirm` receives selected IDs, sends `purgedownloads`, reconnects/polls status and invokes the terminal-complete callback. No `GroupParkDelete`/`GroupDelete`/`GroupDupeDelete`/`GroupFinalDelete` selection or post-delete chaining remains in this user flow.

- [ ] Write Playwright tests `only_delete_cancel`, `toolbar_item_and_keyboard_same_rpc`, `cancel_escape_close_zero_mutations`, `pending_not_deleted`, `lost_response_reload_same_token`, `failed_retry_same_token`, and `reused_ids_never_stale_success`. Reject non-loopback target before launching destructive interactions.
- [ ] Run RED against the exact candidate assets served by a private loopback fixture; intercept mock-RPC browser cases and use real isolated RPC for integration cases.
- [ ] Replace all radio/help variants with one warning: “Delete this download, all its duplicates, their files on disk, and their entries?” Use singular/plural new keys. Remove `DownloadsDeleteHelp`, its dispatch/obsolete locale keys and unused legacy selection handlers after checking callers.
- [ ] Generate a 16-byte request token using browser cryptographic randomness before sending; retain it per backend/selection for response-loss/reload recovery. Unsupported token storage/randomness fails visibly before submission. Server operation lookup is authoritative when browser state is missing. Disable repeated admission, show pending/error and notify success only on confirmed complete.
- [ ] Run GREEN at 1640/1280 desktop and 390/320 phone, light/dark, keyboard/programmatic navigation and repeated English/German/Turkish locale returns. Preserve the merged toolbar row and Settings behavior. Sign UI/locale tests and changes.

### Task 10: Whole-Caller Correctness and Replaced C++ Audit

**Files:** Create `rust/tests/dupepurge/fixture.py`, `rust/tests/dupepurge/caller.cpp`, `rust/tests/dupepurge/replacement-map.json`; modify only migrated C++ business boundaries named by the reviewed map.

**Interfaces:** Fixture validates loopback/private roots/offline providers, drives actual purge RPC, restarts owned daemon and emits phase/route/action/persistence receipts plus observable digests. Reference selection is test-only, never a production runtime fallback.

- [ ] Add full scenarios for queue/paused/post/URL/success/failed/compact history, repaired/unpacked/moved outputs, kept/merged NZBs, cache/pending state, non-UTF8/locale identities, conflicting-key bridges, shared/nested outputs, root/link/swap/hardlink failures, I/O/allocation/exception errors and concurrent drain/restart/overlap.
- [ ] Demonstrate RED for each missing actual caller boundary, then GREEN after Tasks 2–9. Every terminal success must prove full family bytes/entries absent, unrelated sentinels unchanged, acknowledged publication and no late recreation. Legacy missing inventory remains GAP; never mark that scenario passed as full cleanup.
- [ ] Audit each original user-delete branch and migrated planning/order/result body with source hash, old call sites, new live Rust symbol and route hits. Remove replaced production C++ bodies; retain mechanical callbacks and internal automatic/retention callers only with explicit source-bound rationale.
- [ ] Preserve original migrated C++ bodies in test references, existing Rust filesystem caller baselines and signed working history. Run full relevant Cargo/C++/WebUI suites on admitted stages; record sanitizer/platform limits and all failed attempts.
- [ ] Commit signed correctness fixtures/removal map and obtain independent source-bound whole-caller review before timing.

### Task 11: Native Speed and Existing-Rust Preservation Qualification

**Files:** Create `rust/tests/dupepurge/benchmark.cpp`, `reference.cpp`, `optimized.cpp`, `validate_packet.py`, `qualification-plan.json`; use existing `scripts/bench/run.py` and `summarize.py` schemas.

**Interfaces:** Test-only C++ reference implements the full contract; equally optimized C++ receives every indexing/batching/ownership/traversal improvement used by Rust. Historical single-item boundaries are separate diagnostic/preservation comparisons, not labeled an equivalent historical full purge.

- [ ] Validate equivalent bytes, errors, logging/flush behavior, action results, queue/cache/crypto/ABI work, real filesystem and durable publication across variants outside timers. Require actual route-hit counts and reviewed existing-Rust applicability for every changed caller.
- [ ] Freeze exact source/fixture/compiler/archive/object/executable hashes and commands after independent review. Proposed first finite packet: 12 independent process blocks, 10 balanced paired rounds per block, 64 independent complete purges per measured batch, integer elapsed floor 200,000,000 ns; five rounds each primary order. Full-purge fixtures: tiny family, large file inventory, overlapping selected anchors, successful-history output; unchanged existing-filesystem caller control separately.
- [ ] Freeze exact fixtures/reset cost, process/round keys, nested hierarchy, clock boundary, 95% process-cluster ratio interval, relative interval width limit 0.05, control budget and stage time/storage caps with Root/Twin before admission. The schema defaults alone do not establish adequacy. Use the existing summarizer and a strict pre-validator enforcing integer floor, unique balanced keys and completeness. No timing starts with unresolved fields.
- [ ] Retain one planned calibration per fixture/variant. Fixed batch under-floor, excessive drift or insufficient precision makes this packet HOLD, not permission to retune/filter/replay/replace its rows. Any renewed source/method gets a new plan and preserves this attempt.
- [ ] Obtain Twin admission; build isolated fresh targets with heavy-EX then benchmark-SH, preserve current Rust archive separately, prove Rust 1.99.0 recompilation and complete dependency lineage. Prebuilt timing uses only benchmark-EX and releases per bounded process; measured subprocesses receive no publication credentials.
- [ ] Inspect raw rows and `qualification.json`. Full changed callers require upper ratio bound <1 against optimized C++; applicable current Rust requires <=1. Any failure/noise/regression/missing evidence is HOLD. Optimize only through a new reviewed source/plan, apply equivalent algorithm gains to C++, and requalify the full operation; never claim helper speed as delivery.
- [ ] Sign evidence metadata and narrow decision records. No merge recommendation without the entire correctness/legacy inventory/speed/preservation packet accepted by Root.

### Task 12: Exact-Head Reviews and Canonical Integration

**Files:** Final signed branch, PR body, source/replacement/qualification manifests and review receipts; no production deployment files.

**Interfaces:** Produces final published canonical single commit on fresh default, tree-equivalence evidence, GitHub verification, independent/Codex findings and Root integration receipt.

- [ ] Freshly fetch canonical `dupe-article-fallback` with the verified `xbmc4lyfe` credential-helper override. Compose owner dependencies without overwriting dirty/disjoint work; source changes invalidate relevant previous checks and require renewed qualification.
- [ ] Preserve signed working history/evidence before source-equivalent squash. Create the canonical locally signed single commit with fresh sole parent; prove reviewed-tree equality, exact author/committer and local signature, push only owned feature ref with an exact lease if rewriting, and verify GitHub `verified=true`, `reason=valid`.
- [ ] Create/attach the PR targeting `dupe-article-fallback`; describe observed tests and limitations without claiming deployment. Obtain independent complete-change review and one supported Codex review of the actual final published head.
- [ ] Repair actionable findings, verify the repairs, answer/resolve every discussion, and re-request review after changed heads until Codex explicitly acknowledges that actual final head clean. Do not duplicate an already-running automatic review or use synthetic checkout metadata/old-head approval as signoff.
- [ ] Inspect live unresolved threads, required CI, full qualification and legacy ownership acceptance. Pending/skipped/HOLD is not pass; preserve unfavorable evidence. Send exact signed tuple and review/qualification receipts to Root.
- [ ] Root integrates the original signed canonical object with checked fast-forward. Re-fetch and prove default contains that exact commit/tree and GitHub PR merged state. Report deletion merged separately from toolbar PR #99 and any deployment. Mark the full goal complete only when every acceptance requirement is proved.

## Planned Commands and Admission

These are verification payloads for Twin to admit, not commands executed by writing this plan. Exact per-stage output paths, source/fixture manifests and bounded raw sinks are created before launch. Never run Cargo/native workloads on the local Mac.

```sh
(cd rust && CARGO_BUILD_JOBS=3 cargo test --release --locked --manifest-path Cargo.toml -- --test-threads=3)
(cd rust && CARGO_BUILD_JOBS=3 cargo clippy --release --locked --manifest-path Cargo.toml --lib -- -D warnings)
cmake --build "$TASK_BUILD_DIR" -j3
ctest --test-dir "$TASK_BUILD_DIR" --output-on-failure -j3
python3 rust/tests/fsdelete_differential.py "$TASK_BUILD_DIR" 3000
python3 rust/tests/dupepurge/fixture.py --daemon "$TASK_DAEMON" --root "$TASK_FIXTURE_ROOT" --all
node tests/webui/downloads-purge.js http://127.0.0.1:17689/
python3 rust/tests/dupepurge/validate_packet.py --plan "$TASK_PLAN" --manifest "$TASK_MANIFEST" --samples "$TASK_SAMPLES"
python3 scripts/bench/summarize.py --manifest "$TASK_MANIFEST" --samples "$TASK_SAMPLES" --output-dir "$TASK_ANALYSIS"
```

Run new focused RED/GREEN tests through the same admitted Cargo/C++ suite with their exact filter names. Fixture binds loopback on the assigned free port; do not reuse an occupied service or substitute the user's remote preview URL. The full existing WebUI suite is listed in `tests/webui/README.md`. Verification commands and tooling availability are inspected again before execution.

## Coverage and Current State

Spec acceptance 1 → Tasks 8–9; 2–3 → Tasks 1–2/4; 4 → Task 6; 5–6 → Tasks 4–5/7; 7–8 → Tasks 3/6–8/10; 9 → Tasks 10–11; 10 → Task 11; 11 → Task 12. All five Review Focus cases have named owning tests.

This is a written plan only. No task box is checked, no test/build/timing was run, and no purge product code was written. Root and fallback owner agree the source-only ownership/lock/durability direction; exact shared declarations and registration contract remain Task 1 prerequisites. Human written-plan review and execution-method choice are required before implementation. The legacy ownership information-loss finding remains an explicit full-delivery gap, not an accepted narrowing of the goal.
