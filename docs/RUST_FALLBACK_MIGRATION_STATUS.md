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
