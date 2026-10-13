# Agent working instructions

Read [the evidence workflow](docs/EVIDENCE_WORKFLOW.md) before changing or validating
this project. Human instructions and current coordination ownership take priority.

## Preserve work and identity

- Preserve dirty work and earlier evidence. Use isolated work when necessary;
  do not create unsigned stash commits or reset another owner's checkout.
- Refresh the actual remote default before integration. This fork uses
  `dupe-article-fallback`; do not assume `main` or silently substitute another ref.
- Every new Git commit must have author and committer `xbmc4lyfe`, email
  `273732874+xbmc4lyfe@users.noreply.github.com`, and the configured signing key.
  Verify GitHub reports the pushed commit as verified before integration.
- GitHub writes must use the `xbmc4lyfe` account. Tools that generate commits or
  publish automatically require an identity/signing audit before use.
- Verify the canonical HTTPS remote and effective Git credentials as well as
  the API actor. Use the verified GitHub credential-helper override for fetches
  and authorized Git mutations; an API identity check alone is insufficient.
- Preserve signed working history before a source-equivalent squash. Verify
  the reviewed tree, fresh sole-parent base and actual final-head reviews.
  Never substitute a GitHub-generated merge or squash commit for the locally
  signed canonical commit; lease only an owned feature ref when rewriting.
- Integration and deployment belong to their designated coordinating owners.
  A source fix, tool installation, or documentation change does not release a
  performance or deployment hold.

## Capture evidence before interpreting it

- Freeze the question, baseline, fixtures, controls, analysis, and stopping rule
  before an experiment. A changed plan gets a new identifier.
- Use a fresh exclusive run directory. Create command metadata and raw stdout /
  stderr files before spawning; record exit, timeout, interruption, or launch
  failure before parsing. Retain failed, malformed, and inconclusive attempts.
- Check storage and tool readiness before admission. For uploads and asynchronous
  commands, inspect completion and exit status, then verify file hashes before
  running dependent work. An incomplete upload is never executable evidence.
- Record source, executable, fixture and dependency hashes, tool versions,
  machine configuration, process boundaries, and limitations. Preserve original
  raw evidence; derived analysis and redacted exports are separate artifacts.
- Hash only bounded regular files through validated descriptors; reject
  incomplete reads and protect inputs, including traversed symlink entries,
  before replacing or cleaning outputs. Checkout identity is descriptive,
  not proof that a particular executable was built from that source.
- Link conclusions and decision records to the evidence that supports them.
  Mark retrospective recovery explicitly; never describe recovered output as
  prospectively captured. Supersede old conclusions instead of rewriting history.
- Report observed, reproduced, verified, merged, and deployed states separately.
  Use repository-relative labels in user-facing text and published metadata.

## Measure the real behavior

Read [the benchmark procedures](docs/BENCHMARK_AGENT_PROCEDURES.md) when the
reviewed migration infrastructure is present. Framework-specific examples are
conditional, not worker admission or proof that the tooling is installed.

- Use offline fixture providers while retaining the actual caller, cache,
  mapping, crypto and ABI boundary being evaluated. Verify bytes, failure
  semantics and active-boundary hit counts before timing.
- Compare original C++, equivalent optimized C++ and Rust. Separate ownership /
  algorithm improvements from language effects. Include unchanged-code controls.
- Preserve independent-process trials and every sample; do not pool nested
  samples as independent executions or silently discard unfavorable results.
- Preserve an existing Rust implementation independently when applicable.
  Declare and measure that baseline, or obtain source-bound review of an
  explicit nonapplicability rationale. A default regression alert threshold
  is not permission to weaken migration or preservation requirements.
- Calibration failure or an interval admitting regression is inconclusive.
  Profiling, instruction counts, signatures and reproducibility do not prove
  native speed or release readiness. Do not retune a frozen plan to make it pass;
  method changes require a new identified plan and preservation of old results.
- Inspect the qualification artifact, not just a summarizer's exit code.
  A clean collection or analysis command can legitimately produce HOLD.
- Keep measured PR/evidence processes separate from authenticated publication.
  Recheck live same-repository PR/base/head identity before writes; missing
  configuration or incomplete publication must invalidate stale success.

## Runtime replacements and output contracts

Read [the Rust conversion procedures](docs/RUST_CONVERSION_PROCEDURES.md) for
reviewed-branch commands and build-lineage pitfalls.

- Match the actual caller's bytes, fields, partial output, failure, ownership
  and cleanup behavior. Include malformed inputs, overlap, boundary sizes,
  canaries, exceptions and allocation failure where the API permits them.
- Preserve existing text/logging emission, buffering, flush, and error behavior.
  A raw byte-write replacement can differ from historical formatted stdio even
  when a formatting helper returns equal text. Validate the real emission path,
  including embedded NUL, non-UTF8 and quiet-mode behavior where applicable.
- Prove the optimized boundary is reached under the live build configuration.
  A helper bypassed by the enabled Rust caller cannot qualify that caller.
- Snapshot held Cargo archives before reusing targets. Preserved archive
  timestamps can cause false freshness; use isolated targets or discard those
  timestamps and retain proof of required recompilation.
- Enforce the plan's exact integer elapsed-duration floor and unique balanced
  fixture/round keys. Invalid or under-floor rows reject the packet; keep raw
  data instead of filtering, replaying, or adaptively collecting replacements.

## WebUI and illustrated documentation

Read [the WebUI procedures](docs/WEBUI_AGENT_PROCEDURES.md) for tested commands.

- Exercise editor mutations only in an isolated loopback fixture; intercept
  saves and preserve the committed tests' non-loopback rejection guards.
- Test native keyboard and programmatic/search navigation separately. Native
  focus can conceal menu-scroll bugs. Cover desktop/phone, light/dark themes,
  repeated localized headings, editor payloads, and unsaved summaries.
- After each UI action, refresh the cheapest relevant current state. If a
  snapshot disagrees with visible content, check fresh accessibility state and
  direct selected/expanded attributes before diagnosing a defect or toggling
  the control again.
- Capture real JPEGs from sanitized examples, never private production values.
  Wait for asynchronous content and verify the actual active-tab viewport.
  Full-page capture does not expand internally scrolling content; inspect the
  final row/option as well as the first screen.
- Track picture dimensions/hashes and every relevant UI/config source asset.
  Keep accessible full-size links and complete print pictures. Validate the
  locked site build, links, and prose before claiming publication.
- For an explicitly authorized UI-only deployment, preserve backend, process,
  configuration and providers; the live owner installs exact assets atomically
  with recovery evidence. Post-deployment UI checks are read-only. UI approval
  never clears a backend rollout hold.

## Observers and future investigations

Read [the observer procedures](docs/OBSERVER_AGENT_PROCEDURES.md) for daemon
contract and privacy checks, and [the investigation options](docs/CONVERSION_INVESTIGATION.md)
for researched methods that have not been executed or installed by this work.

- Require actual progress signals for a stall detector. Distinguish scheduling
  flags from work already in progress, and article/post behavior from URL fetching.
- Restricted RPC credentials are not inherently read-only. Limit methods at an
  enforced boundary and keep private raw RPC content out of shared evidence.
- Keep invalid or missing values unknown. Validate bounds and stages against
  daemon contracts, and label sequential replies as non-atomic observations.
- Separate observer collection cost, daemon observer effect, and migration
  qualification. PSI or cumulative counters alone do not identify a cause.
- State instrumentation coverage precisely: an ordinary Rust archive linked
  into a C++ sanitizer harness is not Rust sanitizer coverage; a width model
  is not native cross-platform execution. Research permission is not execution
  permission, and diagnostic counts are not native latency.

## Respect execution ownership

Read [the deployment procedures](docs/DEPLOYMENT_AGENT_PROCEDURES.md) for
identity, preservation, rollback, and exact-artifact handoff requirements.

- Coordinate remote work through the single worker scheduling owner. Heavy
  stages take `i7-heavy.lock` exclusively, then
  `nzbget-rust-benchmark.lock` shared at the fixed worker-global lock root.
  Per-job `TMPDIR`, build/target folders and NVMe destinations must never
  relocate or split the shared locks.
  Admission waits default to 120 seconds unless the coordinating owner has
  explicitly assigned another bounded cap. Respect the assigned stage's job
  cap, never exceeding three, including `CARGO_BUILD_JOBS`.
- Prebuilt timing takes only the benchmark lock exclusively and releases it
  after each bounded process. Never acquire the heavy lock afterward.
- Tracing, packaging and backup work must also be scheduled according to cost
  and available storage. No default writes, deployment, host tuning, production
  traffic or repeated benchmark runs follow merely from installing a tool.
- The designated NVMe build destination is already created and verified. Use
  unique owner/job output folders for already-approved work; do not add another
  folder-setup approval process or migrate/delete existing evidence implicitly.
