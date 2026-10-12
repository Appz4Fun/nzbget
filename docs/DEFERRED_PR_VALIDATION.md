# Deferred PR validation

On 2026-10-12 the maintainer explicitly requested signed squash integration of
the open PRs before complete validation, with unfinished work recorded here.
These integrations do not assert review approval, correctness completion,
performance qualification, or deployment readiness. Preserve all earlier failed
checks and raw measurements. Do not mark unresolved review findings as fixed
solely because their PR was merged.

## PR #86 — caller-owned Latin1 conversion

Source snapshot: `bced81e17ab9df87abd7567e999ecd4ca41a1337`.

- [ ] Revisit production reachability: the active Rust-enabled filename and
  header callers bypass the optimized C++ compatibility wrapper. Existing
  wrapper benchmarks do not qualify those production callers.
- [ ] Complete matched whole-caller C++, fair optimized C++, and applicable
  current-Rust measurements before claiming a production speed improvement.
- [ ] Validate the final integrated source; this squash received source merge
  and whitespace checks only, with the full validation deferred by request.
- [ ] Keep backend deployment and performance qualification held.

Benchmarks and earlier evidence remain in `rust/tests/latin1_caller/`.

## PR #93 — optional progress observer

Source snapshot: `31e197612b3570e55ca9ea525a358e8ccdc06da7`.

- [ ] Run the prepared 37-test, strict Clippy and formatting checks on the
  consolidated repairs. Previous passing tests and source reviews apply to
  earlier snapshots; the five new regression checks failed on old code.
- [ ] Review the final transport failure metadata, unknown stages, progress
  bounds, PAR pause uncertainty, process counter units and formatting-only CI
  fixes, then respond to the still-open GitHub findings without claiming
  unexecuted fixes are validated.
- [ ] Follow `tools/nzbget-observe/TODO.md` for the remaining evidence and
  deployment checks. The source merge does not start the observer, exercise
  production RPC, or qualify its production overhead.
- [ ] Normalize the extra trailing blank line in the observer Cargo manifest
  during follow-up; the integration whitespace check reported it.

## PR #80 — native proxy discovery and watcher

Published source: `59f3408a32dc1ba9a6c4f6d72a9cad427be29fae`, with the
frozen held-member eligibility repair tree
`14fad1a2ecf575e780b2753d266cbf6798d6818d`.

- [ ] Fix the three unresolved Codex findings: infer whole size per file, pass
  inferred full data extent to PAR feasibility, and reschedule eligible old
  history picks after an interrupted SEARCHING checkpoint. These repairs are
  not implemented in this snapshot.
- [ ] Validate the included placement-eligibility checks before and after probe
  work. Only the original held-BAD failure was executed; the repaired code and
  FORCE, healthy and asynchronous BAD controls remain unexecuted.
- [ ] Complete the excluded size/PAR regression fixtures alongside their
  matching implementation. Private proof drivers and unfinished tests were
  preserved in the owner workspace, not added to this squash.
- [ ] Revisit slower and inconclusive complete-caller results and incomplete
  per-call I/O instrumentation. This latest source has not been timed.
- [ ] Complete integrated correctness checks and current-head review; leave
  outstanding review discussions truthful. Backend deployment remains held.
