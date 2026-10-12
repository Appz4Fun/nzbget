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
