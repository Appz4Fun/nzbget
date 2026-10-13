# Rust fallback migration progress

## Goal and target

The 2026-10-13 human instruction authorizes continuous staged implementation, tests, speed qualification, milestone PRs, local Codex review and exact published-head Codex review before signed squash into **Appz4Fun/nzbget:dupe-article-fallback**. Remove replaced production C++ after each passing replacement; helpers and temporary adapters remain incomplete.

## Current source and work

- C++ correctness baseline: `4cf19abd`, already pushed; full validation in `FALLBACK_VALIDATION_2026-10-13.md`.
- Working branch: `codex/rust-fallback-migration`, separate from the target and the user's rust-posting checkout.
- Signed design/plan: `c31879c6`, `superpowers/specs/2026-10-13-rust-fallback-design.md` and `superpowers/plans/2026-10-13-rust-fallback.md`.
- Task 1: article geometry regression tests authored; RED execution awaiting assigned remote admission. No Rust runtime switch, speed claim, C++ deletion, PR or deployment yet.
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
