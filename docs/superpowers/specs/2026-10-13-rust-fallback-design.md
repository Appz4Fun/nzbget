# Staged Rust fallback and repair migration

## Intent and authorization

The user approved staged migration on 2026-10-13 and explicitly requested the spec, plan, implementation, thorough testing, native C++ comparison, PRs, Codex approval and squash integration. The target is Appz4Fun/nzbget:dupe-article-fallback. Earlier goal text naming main is superseded. Implement inline in this isolated worktree. Architectural paperwork does not add another permission gate to that explicit continuous-execution instruction.

## Baseline and full scope

Correctness baseline: 4cf19abdb8f084a384769a15cf57e56acf86f363. It contains the develop merge and verified completion, duplicate-health and failed-stat fixes. The qualification report is docs/FALLBACK_VALIDATION_2026-10-13.md. Fresh target changes must be composed and qualified before integration.

Move the complete fallback/repair behavior into Rust: article donor discovery/matching, pinned source order, cutover, lead rotation, PAR deferral and borrowed-article validation; stream geometry, donor verification, fetching, patching and whole-file recovery; live overlap, persistence/retry, archive/encrypted/decompression repair, ordinary and duplicate PAR repair. Temporary C++ adapters remain explicitly incomplete until their responsibilities move to Rust. This project contributes these recovery components to the separate full-application migration; it does not claim that migrating recovery removes every application's C++ file.

## Architecture

Rust owns recovery records and transitions; host queue mutations, disk/network adapters and existing codecs are moved in subsequent stages. Batch immutable article/file snapshots at operation boundaries, use indices or stable IDs across the ABI, and never retain pointers to C++ objects. Snapshots preserve article-list order, duplicate part semantics and byte strings. Synchronization remains under the DownloadQueue lock until queue ownership moves. A stale result must not mutate a changed/deleted file.

The first stage supplies dependency-free safe Rust geometry and identity routines plus differential contracts, before wiring complete donor matching. It is a foundation, not an accepted performance replacement. Geometry must preserve the historical early return on incomplete states, negative/unknown decoded-size handling, borrower preference at seams, signed representable endpoints, and last-list-article semantics. Raw computed negative boundaries are preserved: only the exact -1 sentinel maps to None, and alignment ignores all negative boundaries just as C++ does. Endpoint and part-number overflow outside defined C++ behavior is handled with checked arithmetic and documented separately. Do not eagerly compute a seam endpoint before the borrower-preference return.

The donor-state stage keeps pinned slot-to-source mapping immutable through lead rotation and queue/history changes. Failures count only for round 1 whose pinned donor is still the file lead. Three verified recoveries trigger cutover; three current-lead failures can rotate it within the existing budget. Unknown alignment does not rearm that budget. PAR objects are excluded from target/donor selection. Unavailable or ambiguous identity stays unknown; matching size/name is not checksum authority.

Stream repair Rust owners consume explicit ranges and provider interfaces, preserve offsets and partial writes, and verify candidate bytes before patching. Cancellation, budgets, watchdogs, retry names, cleanup and reporting remain observable contracts. Decompression preserves caps, password retries, crypto geometry and negative behavior. PAR quick/full, duplicate parity and insufficient recovery remain independent test gates.

## Stage boundaries

1. Rust article geometry and identity with source-bound C++ oracle, then complete article donor matching/state/recovery integration.
2. Complete stream and live operation ownership, retaining current-Rust baselines independently.
3. Archive, encrypted, decompression and PAR coordination ownership; retire recovery C++ implementations after supported-platform parity.
4. Exact integrated builds, offline/live qualification, performance, current-head review and signed integration.

Each stage has its own decision record. Failing speed or correctness keeps that stage open; a helper, fallback, green kernel benchmark or partial PR cannot satisfy this specification.

## Correctness acceptance

Translate the 47 article fallback and 30 stream geometry cases at baseline. Preserve the postprocessing completion and health-selection contracts. Differential checks cover normal/malformed geometry, missing/duplicate parts, ambiguity, short final part, uniform sizes, non-UTF8/NUL byte inputs, stale donor results, restart, cancellation, no PAR index, PAR-first deferral and unrelated donors.

Run the full unit and functional sets against each final candidate, including final receipts for isolated reruns. Exercise off/article/stream/live, quick/full PAR, duplicate parity, insufficient parity, decompression yes/no, archive stall/password retry, history retry and restart. Live tests use isolated queues and retained genuine NZBs/providers; generated or altered NZBs are labeled. Every successful repair requires exact output size/hash against a healthy reference, and negative controls must remain failed. Production data/configuration are preserved; testing is not deployment.

## Performance acceptance

Before timing, freeze real complete-caller boundaries, source/binary/fixture/toolchain hashes, algorithm-equivalent C++ controls, existing Rust controls, process/round balance, calibration, duration floor and stopping rule. Native worker timing includes conversion, FFI, copying, allocation, ownership/destruction and result handling. Compare original C++, optimized/equally improved C++, and Rust; unchanged controls must pass drift checks. Every required changed fixture must have a paired 95% elapsed-ratio upper confidence bound strictly below 1 against both C++ controls; current Rust may not regress. Any stricter inherited campaign gate remains applicable. Emulator results establish correctness only. I/O waits or algorithm changes are reported separately from language effects. A result that misses a gate is HOLD, never silently narrowed or averaged away.

## Execution and integration

Heavy validation uses assigned remote worker admission, canonical /tmp/i7-heavy.lock EX then /tmp/nzbget-rust-benchmark.lock SH, at most three jobs. Prebuilt timing uses benchmark lock EX only. Preserve failed/partial runs. No held neighboring lane is switched without fresh qualification.

All commits use signed xbmc4lyfe identity and verified HTTPS credentials. PRs target dupe-article-fallback. Obtain Codex review of the exact published final head; repair findings and applicable CI. Prepare source-equivalent locally signed squash on the fresh target base; verify tree, signature and GitHub verification. Coordinate integration ownership. The inherited AI policy requires contributor-written PR template text and personal testing unless the human explicitly overrides that policy; prepare all reviewable work before that publication step. No automatic deployment follows merge.
