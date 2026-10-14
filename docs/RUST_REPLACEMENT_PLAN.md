# Rust Replacement Candidate Plan

## Goal

Identify NZBGet daemon routines that can be completely replaced by Rust, remove their C++ implementations after parity is proven, and accept a replacement only when the matched complete-caller benchmark demonstrates at least a 2.0x speedup over both current and fairly optimized C++ on every required fixture. A 3.0x result is a stronger target, not a reason to accept a regression on another fixture.

## Scope and decision

The user has now authorized execution through complete Rust migration and C++ removal, with largest measured wins first and Codex approval before signed squash integration. The confirmed fork target is `Appz4Fun/nzbget:dupe-article-fallback`; this remote has neither `master` nor `main`. Refresh that branch before each implementation/integration stage. Follow existing runtime lane ownership, worker scheduling, and backend holds. Deployment still belongs to its separately authorized owner.

The user explicitly requires thorough local Codex review and then PR-level Codex sign-off. Repair and resolve all findings before squash integration into `dupe-article-fallback`. Bind both review stages to the actual resulting source; if review fixes or fresh-base composition change the head, obtain applicable validation and PR-level review of that final head. Preserve the signed working history and prepare the locally signed canonical squash before its final published-head review.

Work is ordered by evidence value. Each candidate receives a written decision: `reject`, `defer`, `Rust-only helper`, or `replacement-ready`. `replacement-ready` means code, correctness evidence, whole-caller performance evidence, integrated checks, and review are complete; integration and deployment still follow their separate owners and gates. An interim helper, fallback, or faster kernel does not complete a component's migration. Track every remaining application implementation, C++ adapter/header, test harness, platform build, and C++ dependency in `docs/RUST_MIGRATION_STATUS.md` until the final C++ removal audit passes.

## Phase 1: Build a source-bound inventory

For every Rust module, record:

- Rust implementation and ABI symbols, if any.
- C++ implementation and exact call sites.
- Whether the Rust function is linked into the daemon and reachable on the target build/platform.
- Whether it is a complete routine, a partial/helper port, or Rust-only functionality.
- Fallback behavior and the platforms that require it.
- Features disabled or stubbed without Rust, including DupeIdentity identity/fetch/PAR decisions, DupeSearch native preparation/ranking/Expand and TwinCheck labels/content matching. A baseline that omits required behavior is not an equivalent C++ control; source-bound review must select a real equivalent implementation or explicitly record comparison nonapplicability before measurement. Retained fallback source in any other row also needs operation-specific equivalence review.
- Available differential tests and complete-caller benchmark evidence, with source revisions.
- Existing correctness, review, performance, or deployment holds.

Classify each as `wired`, `unwired`, `test/benchmark only`, `fallback only`, or `Rust-only`. Do not equate a `pub` module, ABI declaration, archive link, or passing kernel benchmark with runtime reachability. Use call-graph inspection and a bounded instrumentation/coverage run against representative offline daemon fixtures to confirm the path; never use production traffic as a discovery fixture.

Deliverable: `docs/RUST_REPLACEMENT_INVENTORY.md`, with locations and immutable Git blob evidence in `docs/rust-migration/source-inventory.json`. Record unknowns as unknown. Static lexical references are the first pass; they cannot mark linked/runtime reachability complete.

## Phase 2: Rank candidates by measured opportunity

First use existing approved telemetry or deterministic offline workloads to find CPU hot paths. Profile the existing C++ release build before choosing what to port; prioritize routines by their measured contribution to end-to-end work, not by how fast an isolated kernel looks. For each selected hot path, collect a bounded release-build CPU profile and, where material, allocation and off-CPU data. Profiles select candidates; they are not speedup proof. Keep workloads representative and sanitized, preserve hashes and toolchain/machine metadata, and use the approved remote worker for compute-heavy collection.

Rank only routines where Rust can own the full expensive boundary. Favor routines with a large share of total workload cost, stable byte/value contracts, bounded inputs, and limited external-library coupling. Exclude or defer candidates dominated by I/O, network waits, libxml2/OpenSSL/regex calls that remain in C++, or tiny functions where FFI/allocation cost dominates. Existing kernel claims (including 135x CRC combine) are leads, not rankings, until measured inside the real caller.

For each candidate, freeze a plan before timing: exact baseline and candidate commits, real caller boundary, fixtures, required output/failure observations, variants, process/round design, duration floor, stopping rule, and analysis. Compare `cpp_current`, `cpp_optimized`, and `rust_candidate`; include `rust_current` when replacing an already-Rust-backed path. Timing must include the real C++/FFI boundary, allocations, copies, ownership/destruction, and result handling. Preserve every sample and failed or inconclusive attempt.

## Benchmark and build controls

- Use deterministic, fixed inputs representing typical, boundary, and expensive cases. Include a whole-operation workload in addition to focused fixtures, so a large local speedup is not mistaken for a meaningful daemon improvement.
- Build both implementations with the project's supported production compilers, optimization, target architecture, and link settings. Record exact compiler versions, flags, target features, LTO/codegen settings, allocator, and panic/exception behavior. Match settings where the production toolchains allow it, but do not change allocator or production build policy solely to make a benchmark look symmetric. The candidate must also be evaluated in the configuration intended for release.
- Use the existing shared runner and paired complete-caller schema as the qualification path. Criterion is useful for selected Rust kernel attribution; it is not a C++ comparison or a migration gate by itself. Add Google Benchmark, `cxx`/`bindgen`, `iai-callgrind`, or Hyperfine only when a frozen plan demonstrates a specific need that the existing harness cannot meet. Avoid maintaining competing benchmark frameworks for the same boundary.
- Use the existing C ABI unless a measured and reviewed need justifies another bridge. Benchmark both sides through equivalent boundaries; include FFI, allocation, conversion, and ownership costs that production pays.
- CPU profiles, perf counters, Callgrind instruction counts, cache-miss counts, and assembly inspection can explain a result or locate a bottleneck. They do not establish native wall-clock speedup or qualify a replacement. Retain their exact tool/configuration and keep diagnostic runs separate from timing runs when instrumentation changes execution.
- Treat bounds-check removal, unchecked indexing, `MaybeUninit`, SIMD, allocator changes, and alternate synchronization as hypotheses to test after profiling. Prefer safe code until data identifies the cost; any unsafe optimization needs explicit invariants and boundary tests. Do not presume these patterns are common causes of Rust regressions.
- CI may run bounded correctness checks and stable kernel regression diagnostics. Do not use instruction-count changes as a substitute for the complete-caller gate, and do not publish flaky wall-clock thresholds from shared/general-purpose CI as a release qualification.

## Phase 3: Prove parity before performance acceptance

Keep the old C++ implementation available as a test oracle until replacement review is complete. Differential tests must cover normal and malformed inputs, boundaries, overlaps, embedded NUL/non-UTF8 bytes where applicable, partial output, errors, cleanup/ownership, and platform-specific behavior. Add mutation checks for important branches and execute the real caller path, not only direct Rust unit tests.

Define correctness equivalence at the observable caller boundary: output bytes/fields/order, side effects, error codes, logging/flush behavior, and resource ownership. Undefined C++ behavior is explicitly excluded and documented; it is not silently converted into a parity claim.

## Phase 4: Apply the speed gate

A candidate passes only when all required changed-path fixtures have valid samples and the paired complete-caller Rust/C++ speedup is at least 2.0x against both C++ controls. For each comparison, require the 95% interval's upper bound on Rust/C++ elapsed-time ratio to be at most 0.5. For an independently required current-Rust preservation comparison, its upper bound must also be at most 1. Unchanged-code controls must satisfy the existing drift checks; they are not changed paths expected to accelerate. Report per-fixture ratios and intervals; do not average away slow cases or use workload weights to conceal them. A 3.0x minimum may be selected in a future frozen plan, but this plan uses 2.0x as the hard floor within the requested 2–3x band. The existing general summarizer's speedup PASS threshold is weaker than this campaign gate: inspect the numeric results against 0.5 for both C++ controls before recording campaign acceptance.

Any missing/invalid sample, calibration failure, confidence interval crossing the 2.0x threshold, control drift, or slower required fixture means `HOLD` or `reject`, not a pass. Kernel-only speed, a proxy caller, synthetic microbenchmark, test-suite speed, or old result from a different source tree cannot satisfy the gate.

## Phase 5: Replace and delete C++ only after the gate passes

For a passing candidate, prepare a narrow change that routes the production caller to Rust and removes the now-unused C++ implementation from runtime source. Temporary platform fallbacks keep that component's checklist open. Complete its supported Rust build path before removing the fallback; do not drop a supported platform to claim completion. During comparison, keep the C++ oracle available as explicitly non-production test evidence. Carry the regression contracts into Rust tests and preserve the original C++ oracle in immutable historical evidence before the final repository-wide C++ deletion. Update the Rust port inventory, ABI/header, build wiring, documentation, and differential harness together.

Re-run parity, build, relevant test/sanitizer/differential suites, and the frozen complete-caller benchmark against the exact integrated tree. Review must confirm there is no duplicate production implementation, bypass path, stale C++ declaration, or unsupported platform regression. If the final source composition differs materially from the measured candidate, performance qualification is invalid and must be redone under a new plan.

## Candidate order

1. **Inventory and call-graph pass** across existing `rust/src` modules and FFI symbols; identify unwired ports and partial ports.
2. **Profile-backed triage** of actual daemon CPU hotspots using deterministic offline workloads and short release profiles; do not presume the largest historical kernel multiplier is the largest application gain.
3. **Small, isolated candidates** whose full caller is measurable and whose external work can be included faithfully.
4. **Larger stateful candidates** (duplicate search, stream repair, parsing, storage) only after their current correctness/review holds are resolved and their full production boundaries can be reproduced offline.

Immediate held work: PR #80 native duplicate watcher has unresolved correctness and caller-performance findings. PR #87 stream repair has a dense PatchParts result about 24.6% slower than fair C++ and an invalid revised floor packet. Do not switch those production paths or treat them as candidates that merely need a call-site edit.

Current Rust-enabled source already routes PatchParts to Rust for nonempty donor ranges and holes with nonnegative margin, including zero margin and ordinary inputs below 4096 holes. Only the separate coverage-floor helper has a 4096-hole threshold, after the no-probe/no-hole bypasses. Inventory source wiring independently from compiled route coverage, performance qualification and deployment; a held candidate is not proof that its Rust source is unwired.

## Required deliverables

- Rust/C++ ownership and reachability inventory.
- Profile-backed ordered candidate list with estimated share of real workload cost and measurement limitations.
- One frozen qualification plan and evidence packet per selected candidate.
- Per-candidate decision record with parity, C++ deletion scope, per-fixture speedup and interval, review state, and remaining integration/deployment owner actions.
- Updated source inventory identifying completed Rust replacements, temporary fallbacks still awaiting removal, and final mandatory Rust platform builds.

## Project constraints

- Follow the current `AGENTS.md`, PR template, `docs/EVIDENCE_WORKFLOW.md`, `docs/BENCHMARK_AGENT_PROCEDURES.md`, `docs/RUST_CONVERSION_PROCEDURES.md`, and `docs/DEPLOYMENT_AGENT_PROCEDURES.md`. Canonical commit `7d3d6412` removed `docs/AI_POLICY.md`; do not impose the superseded policy on new PRs.
- Heavy compilation and Rust validation belong on the designated remote worker; obey the shared lock order, assigned job cap, and evidence retention rules.
- Do not run unapproved profiling/benchmark payloads, alter a frozen plan to make it pass, delete prior evidence, or infer deployment from source integration.
- Keep signed identity, fresh-base integration, current-head review, CI, deployment authorization, installed binary identity, and live checks as separate gates.
