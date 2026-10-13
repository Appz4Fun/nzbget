# Rust fallback migration progress

## Goal and target

The 2026-10-13 human instruction authorizes continuous staged implementation, tests, speed qualification, milestone PRs, local Codex review and exact published-head Codex review before signed squash into **Appz4Fun/nzbget:dupe-article-fallback**. Remove replaced production C++ after each passing replacement; helpers and temporary adapters remain incomplete.

## Current source and work

- C++ correctness baseline: `4cf19abd`, already pushed; full validation in `FALLBACK_VALIDATION_2026-10-13.md`.
- Working branch: `codex/rust-fallback-migration`, separate from the target and the user's rust-posting checkout.
- Signed design/plan: `c31879c6`, `superpowers/specs/2026-10-13-rust-fallback-design.md` and `superpowers/plans/2026-10-13-rust-fallback.md`.
- Task 1 foundation implemented: safe geometry plus a batch C ABI. Expanded missing-API RED then 19/19 core GREEN; missing-ABI RED then 22/22 total GREEN; exact C++ extraction matched Rust on 20,240 fixtures. Tests ran in the retained amd64 Linux container under macOS emulation, not a native speed qualification. No daemon recovery caller switched, C++ algorithm deleted, PR opened or deployment performed.
- Local and PR Codex review are required for each qualified milestone; a documentation/foundation commit is not the first runtime milestone.

## Remaining milestones

1. Complete article geometry/identity/pinned-donor state and recovery ownership; original and fair C++ caller controls; remove replaced algorithms only after parity and speed qualify.
2. Complete stream/live repair and preserve current Rust independently.
3. Complete archive/encrypted/decompression/PAR coordination and supported-platform contracts.
4. Immutable offline/live qualification, native performance, local Codex review, milestone PR into the target, published-head Codex approval and signed squash integration.

## Coordination and decisions

Human authorized messaging the existing migration chats. Scope handoff sent to the full-application inventory owner and Root; operations is a subagent inaccessible by direct app message, so admission request was forwarded through Root. No worker payload starts from a lock file alone.

Ruling: the human's explicit instruction to write spec/plan and keep implementing overrides additional paperwork permission checkpoints. Costs if wrong: rework the written design if the human corrects it; no deployment or production mutation is implied.

Ruling: Task 1 is an unqualified foundation. Its C++ remains until a complete recovery caller passes parity/performance; no tiny-wrapper speed claim substitutes for the end state. Cost if wrong: larger integration/test boundary, not a falsely accepted replacement.

## Local source review, preparatory checkpoint

Codex reviewed the extraction, test contracts and design locally before implementation. It confirmed exact baseline body/getter fidelity and found five contract gaps: computed negative boundaries versus the exact -1 sentinel; lazy endpoint overflow branches; checked extreme part numbers; borrower precedence before endpoint/incomplete-neighbor inspection; ABI layout/error/canary contracts. These are retained findings to pin in the Rust tests/ABI before GREEN qualification, not approval of an implementation. Review made no runtime/performance claim. The current oracle is an extracted-body correctness fixture, not the full production caller performance control.

The feature branch preparation commits c31879c6 and d0713ba0 are pushed and GitHub verified. No milestone PR is open yet; the first replacement still needs code, tests, speed proof, deletion and fresh local review.

## Foundation implementation evidence

- `rust/src/articlegeometry.rs`: safe geometry and raw-integer/flag C ABI, checked spans/overlap/capacity, lazy boundary checks, raw writes into caller-owned output.
- `rust/tests/articlegeometry_boundary_contracts.rs` and `articlegeometry_abi_contracts.rs`: local-review gaps now pinned; zero-length NULL, invalid capacity, canaries, nonzero flags, overlap/misalignment/span overflow.
- `articlegeometry_differential.cpp`: 20,240 defined-domain fixtures using exact historical getter-based C++ bodies; not a complete caller benchmark.
- `articlegeometry_oracle_guard.py`: verifies custody of all five copied bodies against immutable 4cf19abd.
- Private raw receipts: `rust-geometry-local-v1`, local Docker correctness only. Initial missing tool mount attempt is preserved as setup failure, not RED. Expanded source RED and ABI RED have specific missing-API diagnostics, each followed by GREEN.
- Earlier proposed native RED packet was rejected before launch for recorder/cleanup defects and withdrawn. Native GREEN/differential will use the coordinating owner's existing reviewed recorder, not that runner.
- Fresh target now includes toolbar-only badf75a2 after the 4cf19abd baseline. Compose the fresh target before qualification/integration; the baseline oracle remains immutable.

Next: local implementation Codex review, scheduled native correctness, then whole article matching/pinned-state Rust ownership and complete-caller speed proof. This foundation does not satisfy a runtime replacement milestone and does not clear neighboring holds.

## Local implementation review and follow-up

Signed foundation head 17051f8e received a high-effort local Codex source review. No correctness, UB/lifetime, aliasing, output-initialization or ABI-layout defect was found within that supplied source. Three low coverage gaps were addressed with explicit tests for genuinely uninitialized output, address-plus-length overflow, and exactly adjacent input/output. The expanded suite passed **25/25**. The production implementation is unchanged by those coverage additions. Full Cargo/native/platform/runtime/performance review is still pending; this local review is not PR approval.

Next-stage donor-state contracts are authored in `rust/src/articlefallback.rs` (five tests for rotation threshold, stale pinned results, first-round gating, exhausted/single-donor budget and provisional/verified success). Its implementation and RED execution remain pending. The file is not exported by `lib.rs`, so it is not a runtime path.

## Article donor-state implementation

- Refreshed target `7d3d6412` merged into the feature with locally verified signed merge `ad471098`; target changes are WebUI/policy only, with no daemon/Rust delta from 4cf19abd. Removed AI policy no longer imposes a description-authorship gate.
- `rust/src/articlefallback.rs` now owns lead transitions, immutable source bytes, first-contributor bookkeeping and blocked-source advancement/primary revert selection. It is compiled by the Rust crate but **not called by the daemon**.
- Staged RED/GREEN: five lead cases, then ten pin/state cases, then **13/13** including blocked donors and source exhaustion. Initial pin RED compiler output was correct but its recorder used the wrong classifier; that failed classification is retained separately, and a new identified classifier/run recorded the expected missing pin API.
- Source-bound C++ comparison: **200,000 state events** plus **2,048 pinned-source byte and advancement fixtures** passed against exact historical function bodies/loop with fixture getters. Geometry remains a separate 25-test/20,240-fixture foundation. Neither fixture harness is a complete production caller performance control.
- `articlefallback_oracle_guard.py` guards four copied bodies and the blocked-source loop. `articlefallback_differential.rs` is a test-only bridge; it is not exported by the production crate.
- Pending joint purge contract is documented in the spec and accepted in source-only coordination: new persisted daemon generation/validated binding, durable intent, separate cancel versus drain/cleanup acknowledgements, no waits/callbacks under locks, no stale commit or guessed family. No shared lifecycle code implements that proposal yet.

Next: local Codex review of this owner, Rust donor identity/matching, then full recovery caller integration with the approved generation/cancellation handoff. Native complete-caller speed and supported-platform/full-Cargo/runtime/live gates remain open. No production C++ replacement has been removed or milestone PR opened.

## Donor matcher foundation

- Restored missing managed checkout from pushed ff5df91f; the primary rust-posting checkout was preserved. Uncommitted matcher recovered from its retained test-source snapshot, without recreating already-pushed work.
- `rust/src/articleidentity.rs` owns complete donor-file selection, sparse/duplicate-part structural comparison, declared part-count parsing, and size-step match/FNV hash. Known content authority is supplied by the existing validated content owner; metadata heuristics are not checksum proof.
- Full `std::string` authority checks versus C-string filename comparison are distinct. Empty/dash sentinel regressions and embedded-NUL authority regressions were observed RED then corrected GREEN.
- **15/15** bounded single-file Rust1.99 Mac tests passed; **20,000** exact historical C++/Rust matcher fixtures passed on Mac. Six copied source bodies are guarded by `articleidentity_oracle_guard.py`.
- An independent local Codex reviewer found no actionable defined-domain semantic regression and explicitly left locale capture/integration, native worker/full Cargo/caller/performance/live gates unproven.
- The current host locale fold/whitespace tables must be supplied to the production matcher; ASCII/C-locale wrappers are for standalone fixtures. Source integer/endpoint overflow outside the C++ defined domain is handled conservatively and not labeled C++ parity.
- Local Docker startup failed even for an empty container; source-build and startup timeouts are preserved separately, owned containers removed. Light dependency-free single-file Mac validation continued, without Cargo builds or performance measurements. The shared worker is disconnected and its last build outcome is unknown; no native stage or replacement was inferred complete.

Next runtime milestone remains actual article recovery-caller integration and source-bound original/fair C++/Rust benchmarking, then Linux/full build/offline/live qualification, removal of replaced C++, local and final-head PR Codex review and signed integration. No production C++ algorithm has been deleted or Runtime PR accepted from these foundation tests.

## Actual caller candidate (disabled by default)

A candidate route now exists inside the real `DupeArticleFallback::MatchDonorFile`, enabled only by `NZBGET_RS_EXPERIMENTAL_ARTICLE_MATCH` on a Rust-enabled build. It captures the real FileInfo/ArticleInfo names, subject, encoded geometry and parity flags under the existing lock, preserves counted std::string content evidence, captures actual LC_CTYPE fold/whitespace, and dispatches through `nzbget_rs_article_match`. Rejected numeric snapshots invalidate the candidate rather than silently falling back to C++.

The bridge test observed missing API RED then passed **16/16** matching tests. The actual guarded function body/adapter compiled in the bounded getter fixture and passed **20,000** capture/ABI route cases. These getter objects are not a full libnzbget/daemon build or a production-caller speed control; the earlier immutable historical-body comparison remains a separate artifact. The candidate has not been enabled in production, qualified, or used to delete its C++ implementation.

Next: compile the entire candidate with the real library, prove active-route counts and actual bytes/errors, compare original C++, a fairly optimized C++ control and Rust across complete caller fixtures, and retain any HOLD. Heavy Linux/full Cargo/build/live and native benchmark stages remain with the coordinating worker; its last remote build outcome is unknown until connectivity/custody recovery.

## Candidate activation review

Local Codex follow-up reviewed the new C ABI, nested snapshot ownership, locale/authority transfer and disabled-by-default caller route. It found no pointer-lifetime or DTO-layout regression in that synchronous scope, and identified two P2 activation issues. Both have source fixes: explicit ON rejects every Rust-unavailable early return; the fixture now requires the enabled macro and a separately enabled untimed Rust boundary counter.

The trace fixture passed 20,000 cases with **18,823 actual Rust bridge calls**, and compilation without the candidate definitions failed as required. The source guard confirms the actual guarded production function is the fixture body. CMake script execution is still unverified locally because `cmake` is absent; its failed launch is retained and is not counted as a RED or pass. The candidate's unexpected negative/out-of-range result also fails qualification explicitly.

The matcher plus internal bridge/numeric span tests passed **17/17**. Trace collection is a separate Cargo feature, disabled for all eventual timing. Full library/Cargo/platform builds, real daemon route proof, complete-caller original/fair CPP/Rust timing, live repair and published-head PR gates remain open. Original production C++ remains the default and no replacement deletion or performance HOLD release has occurred.

## Portability follow-up and refreshed checkpoint

The option is now declared in the root CMake file before platform includes. Explicit ON/Windows fails there, because the Windows path does not include the Rust configuration module. The matcher validates its returned ordinal in uint64 before narrowing to size_t, so a 32-bit conversion cannot turn an out-of-range result into donor zero. The independent Codex source reviewer confirmed both findings are addressed, with no remaining actionable finding in that focused source scope.

Fresh bounded Mac checks after these changes passed **20,000 matcher fixtures with 18,823 actual Rust boundary calls**, and compilation without the candidate definitions failed as required. The combined dependency-free geometry, donor-state and matcher suite passed **55/55**. The production-function guard and all historical body guards passed. Private prospective packets are `rust-geometry-local-v1/identity-portable-trace-mac-v2` and `combined-owner-mac-v2`; inputs, commands, raw output, statuses and hashes are retained.

These checks establish Mac fixture correctness only. CMake execution, native 32-bit behavior, full Cargo/library/daemon builds, real cache and authority caller coverage, live recovery, original/fair C++ speed comparisons and final-head PR approval remain unverified. The shared worker remains offline; its interrupted build outcome remains unknown. Root retains admission and default-branch integration ownership. No alternative heavy route, target write, C++ retirement or deployment was performed.
