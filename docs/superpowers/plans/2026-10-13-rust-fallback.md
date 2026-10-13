# Rust Fallback Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Move all fallback and repair processing into Rust with preserved behavior and qualified native speed before reviewed signed integration.

**Architecture:** Safe Rust recovery owners consume explicit article/file snapshots and provider contracts. C++ adapters are transitional and do not complete the migration. Qualification covers complete operations.

**Tech Stack:** Rust 1.99.0, existing C ABI, C++ differential oracle, Boost tests, Python functional/live drivers, existing benchmark infrastructure.

**Spec:** docs/superpowers/specs/2026-10-13-rust-fallback-design.md

## Global Constraints

- Base 4cf19abdb8f084a384769a15cf57e56acf86f363; PR into Appz4Fun/nzbget:dupe-article-fallback.
- Signed xbmc4lyfe author/committer; canonical scheduling/locks; at most three build jobs.
- No runtime acceptance from helper/kernel evidence; no production deployment implied.
- Defined caller behavior, output bytes and partial/error/cleanup semantics must agree.
- Native complete-caller 95% ratio upper bound below 1 for each required changed fixture against both C++ controls; preserve current Rust independently and stricter applicable campaign gates.

## Review Focus

- Incomplete geometry before a later broken seam must return unknown without eager rejection.
- Borrowed article preference at a seam must choose the same article as C++.
- Stale lead failures must not demote a donor that was never fetched.
- Missing NZB parts, declared subject count and a short final part must retain distinct semantics.
- Final paused PAR files and healthy duplicate selection must still trigger completion/backup after Rust integration.

### Task 1: Rust geometry foundation

**Files:** Create rust/src/articlegeometry.rs and rust/tests/articlegeometry_differential.cpp; modify rust/src/lib.rs, rust/include/nzbget_rs.h. Evidence runner uses the existing approved process/evidence framework.

**Interfaces:** Produce Article {part:i32, size:i32, offset:i64, segment_size:i32, finished:bool, borrowed:bool}, expected_offset(&[Article], index:usize)->Option<i64>, expected_end(&[Article], index:usize, decoded_size:i64)->Option<i64>, segment_aligned(&[Article], index:usize, decoded_size:i64)->bool, first_untiled(&[Article], decoded_size:i64)->Option<usize>. No C++ pointers survive a call. Checked endpoint overflow conservatively rejects rather than reproducing undefined behavior.

- [ ] Write Rust tests first: contiguous, gaps/overlaps, borrowed seam preference, incomplete early return, unknown sizes, missing neighbors, last article and out-of-range index; assertions mirror baseline tests/queue/DupeArticleFallback.cpp.
- [ ] Run dependency-free remote rustc --edition=2021 --test rust/src/articlegeometry.rs and read the expected unresolved/missing implementation RED result; record command, output and source hash.
- [ ] Implement the declared safe functions, preserving source ordering and lazy checks.
- [ ] Run the same tests GREEN, then differential real baseline C++ extraction over deterministic valid/malformed snapshots. Expected: equal indices/alignment/unknown results for every defined-domain fixture; overflow cases labeled separately.
- [ ] Add ABI only with explicit length, index and output/error contracts; invalid spans do not retain or dereference invalid pointers. Test zero-length null and index bounds before wiring.
- [ ] Commit signed; ledger foundation status as not yet performance-qualified and not complete recovery ownership.

### Task 2: Article donor identity and recovery ownership

**Files:** Create rust/src/articlefallback.rs; modify rust/src/ffi.rs, rust/include/nzbget_rs.h, daemon/queue/DupeArticleFallback.cpp/.h, daemon/queue/DownloadInfo.cpp/.h and tests/queue/DupeArticleFallback.cpp. Keep Rust owners split by geometry versus mutable donor state.

**Interfaces:** Consume Task 1 Article geometry; produce Rust-owned recovery context keyed by file ID/generation and pinned article source snapshots. Host callbacks use stable IDs and explicit success/failure responses, not retained object addresses. Freeze the exact context ABI in this task's source-bound packet before writing its adapters.

- [ ] Translate baseline donor-match/lead/PAR tests before implementation. Include ambiguous content/name matches, uniform fingerprints, subject count/missing segments, three-failure rotation bound, stale pinned donor failures, unknown geometry and PAR target/donor exclusion.
- [ ] Observe RED with the missing Rust context; implement batched matching, pinned source ownership, cutover, rotation, invalidation and PAR decision semantics.
- [ ] Wire full operation adapters under queue lock with generation checks; demonstrate active Rust operation hit counts on deterministic daemon fixtures.
- [ ] Run all article tests and article/PAR-first functional scenarios GREEN, including postprocessing and failed-health backup contracts.
- [ ] Freeze complete-caller benchmark with original, equally improved C++ and Rust before timing; include dense/sparse/missing-part matching and full fallback source transitions. Obtain scheduled native evidence and record PASS/HOLD per fixture.
- [ ] Commit only source with evidence-bound status; retire production article C++ algorithm only after full parity/performance acceptance.

### Task 3: Stream and live Rust ownership

**Files:** Create rust/src/streamrepair.rs; modify daemon/queue/DupeStreamRepair.cpp/.h, daemon/postprocess/StreamRepair.cpp/.h and existing Rust stream modules only within agreed lane ownership.

**Interfaces:** Consume recovery context and geometry; Rust owns target/donor ranges, verification/probe selection and operation state. Provider adapter reads explicit ranges and returns bytes/error/cancellation; disk adapter reports actual partial writes.

- [ ] Translate all 30 stream contracts and controller functional contracts, including sparse missing entries, overlap, unknown geometry, whole-file repair, unrelated donor and live rename/retry.
- [ ] RED then implement complete donor fetch/verify/patch ownership; preserve existing Rust baseline independently.
- [ ] GREEN differential and offline real daemon tests; verify cancellation, watchdog, budgets, byte hashes and no stale writes after queue deletion.
- [ ] Freeze and run complete stream/live caller benchmark against both C++ controls and existing Rust; retain HOLDs.
- [ ] Signed commit with evidence; delete migrated C++ operation code only after gates pass.

### Task 4: Archive, decompression, crypto and PAR coordination

**Files:** Create focused Rust archive/repair orchestration modules; migrate ArchiveProcessor and corresponding StreamRepair archive/encrypted/decompress/PAR branches. Reuse existing reviewed Rust PAR parser rather than duplicating another owner's work.

**Interfaces:** Explicit content reader/extractor and PAR result contracts with caps, passwords, offsets and cleanup. Finalize codec ownership on supported targets before retiring C++ dependencies.

- [ ] RED assertions for enabled/disabled decompression, cap overflow, password retry, empty/failed extraction, encrypted offsets, PAR quick/full/duplicate/insufficient parity and archive stall.
- [ ] Implement Rust owners and verify GREEN with exact bytes and negative controls.
- [ ] Native complete-caller comparison includes extraction/crypto and adapter ownership costs; report external I/O separately; hold slower cases.
- [ ] Signed commit and supported-platform parity before source retirement.

### Task 5: Full qualification, Codex review and integration

**Files:** Update docs/FALLBACK_VALIDATION_2026-10-13.md with distinct Rust evidence; source-bound manifests and ledger, never credentials or private release names.

- [ ] Freshly compose target and run complete Rust/C++ unit, all functional scenarios and live matrix against immutable binary/source receipts. No skipped mode is a pass.
- [ ] Verify every recovery runtime path is Rust-owned and every remaining adapter is explicitly accounted for; do not declare completion with retained C++ algorithms.
- [ ] Repeat native qualification only for material final composition changes under a new frozen packet; every required fixture passes.
- [ ] Use the refreshed target PR template (AI description policy removed at 7d3d6412), disclose actual scope/validation, then push signed feature head and verify GitHub signatures.
- [ ] Create PR into dupe-article-fallback and attach it. Request one Codex review of final published head; fix findings, resolve discussions, verify approval and applicable CI.
- [ ] Coordinate locally signed squash against fresh sole-parent base, verify source-equivalent tree and exact-head review, integrate and verify remote parity. Preserve original signed working history.

## Execution ledger

User requested continuous inline execution on 2026-10-13. Paperwork approval is covered by that direct instruction; remaining operational scheduling and publication requirements are distinct. Geometry is a foundation, not a substitute for the complete-operation goal. Each task stays open until its named evidence exists. If benchmark rejects a candidate, optimize/retest under a fresh plan instead of claiming completion.
