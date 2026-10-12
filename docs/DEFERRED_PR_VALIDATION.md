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
