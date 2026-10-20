# Rust conversion and performance evidence

These source-bound owner procedures supplement the shared agent policy; candidate correctness, performance qualification,
merge, and deployment remain separate outcomes.

- Preserve existing branches, dirty work, adverse results, failed stages, and
  incomplete raw output. A renewed fix uses a new identified source revision
  and a prospective plan; it does not erase an earlier HOLD.
- In coordinated migration work, the designated Root approves scope and
  qualification and alone integrates the default branch. The operations
  coordinator owns worker admissions; the PR owner performs authorized deployment
  and verifies the result under the shared PR delivery policy in AGENTS.md. Use
  the current canonical remote ref rather than an old announcement.
- Keep exact `xbmc4lyfe` author and committer identities. Verify local Git
  signatures, HTTPS GitHub identity, and GitHub signature verification for
  each published commit. Prepare a signed squash before exact-head reviews;
  avoid a server-generated merge with a different committer.
- Run heavy validation on the approved worker. Builds/tests acquire the
  canonical heavy lock exclusively, then the canonical benchmark lock shared,
  with at most three jobs. Prebuilt timing acquires the benchmark lock
  exclusively, without compilation or heavy-lock acquisition. Release locks
  between bounded stages. Never relocate shared locks with a job's temporary
  directory. Check fresh space and use the operations-provided build output
  destination where practical.
- Freeze exact source, extracted caller, controls, inputs, compiler flags,
  archives, objects, executables, plans, validators, and analyzers before
  timing. Hashes of source alone do not prove the executable used that source.
  Snapshot a held archive before reusing its Cargo target. Git archives can
  preserve old timestamps and cause false freshness in a reused target;
  discard preserved timestamps during extraction or use an isolated target,
  and retain evidence of the required recompilation. A reconstructed archive
  with a different hash is a reconstruction, not the original artifact.
- Compare the complete caller, including dispatch, conversion, allocation,
  padding, ownership, FFI, and result handling. Retain the original production
  and previous optimized C++ controls. Add an equally improved C++ control for
  every substantive algorithm or ownership improvement. Describe shared
  algorithm gains separately from Rust gains. Trace actual paths outside
  latency measurement; keep allocation instrumentation separate.
- Use subprocess argument lists and checked exits. Create raw files and run
  directories exclusively and claim each approved process slot once before
  launch. Persist launch intent and completion receipts. Missing or failed
  receipts never authorize a replacement. Keep the benchmark lease alive
  while the child runs, including a recorder crash; reap only owned children
  on caught recording or timeout failures.
- Validate exact fixture/method/round keys, uniqueness, ordering balance,
  finite positive measurements, and the plan's integer elapsed-duration floor.
  Do not reconstruct elapsed time from a rounded per-operation average.
  Retain initial calibration trials. An invalid or under-floor row rejects
  the packet, preserving raw and partial data without filtering, adaptive
  resampling, recalibration, or replay.
- Declare calibration, retained sampling, control ordering, process count,
  time/output/space bounds, and analysis before measurement. Preserve nesting
  across processes and builds. Identical rebuilt binaries do not establish
  compiler/layout variation; reused Rust archives do not establish independent
  Rust-build variation. Pinning and similar CPU/wall times do not establish
  stable frequency or identical-work cost.
- Preserve defined C++ quirks, byte order, lazy overflow evaluation, and
  non-Rust fallbacks. Differential checks, real packet tests, bounded scratch
  tests, and explicit mutation assertion failures support parity. State which
  components were sanitizer-instrumented and which architectures were tested.
- For a qualifying delivery, compose from the freshly fetched target, resolve
  conflicts without overwriting disjoint owner work, validate the resulting
  source, obtain immutable whole-change and exact-head GitHub reviews, and
  clear applicable CI. Deployment evidence must connect the merged source to
  the tested build and installed/running executable hashes, followed by
  relevant offline and live health checks. No skipped check is a pass.

Known commands for reviewed conversion branches, executed on the approved
worker with job limits and task-specific paths configured. Run Cargo from
`rust/` so rustup discovers `rust-toolchain.toml`; verify the active toolchain
matches that pin and no environment/directory override supersedes it. Build jobs
and libtest threads are separate caps; lower both for a stricter assigned slot:

```sh
(cd rust && CARGO_BUILD_JOBS=3 cargo test --release --locked --manifest-path Cargo.toml -- --test-threads=3)
(cd rust && CARGO_BUILD_JOBS=3 cargo clippy --release --locked --manifest-path Cargo.toml --lib -- -D warnings)
cmake --build "$TASK_BUILD_DIR" -j3
ctest --test-dir "$TASK_BUILD_DIR" --output-on-failure -j3
```

The stream comparison and PAR batch differential programs are branch-specific
until their ports are integrated. Use their reviewed instructions and source
hashes rather than assuming those programs exist on the default branch.

## Duplicate discovery and PROXY migration

PR #80 remains an unmerged, performance-held candidate. Its added helpers and
checkpoint formats are branch-specific until integration; source review or
isolated parity does not prove production readiness, speed, or deployment.

- Keep posting fingerprints over all retained article IDs. For PAR feasibility,
  measure data article IDs and data-only listed/declared part counts separately;
  present recovery articles are capacity, not proof of data availability.
  Resolve duplicate segment numbers with keep-last ID/byte semantics. Unknown
  geometry stays unknown, and identity hints never replace checksum authority
  or weaken `main_valid` handling.
- Preserve suppression independently for each duplicate key and normalized
  title. Recovery must use the original checkpoint binding; an unknown binding
  cannot invalidate another edition's completed stamp. Distinguish discovery
  from rank-only work so interrupted health checks do not repeat paid grabs.
- Test cap and retry races with isolated loopback NNTP/Newznab/RPC and private
  queues. Include dead fast-donor replacement, nondead partial cap occupancy,
  failed-history exclusion, owned history rename/redownload, title suppression
  across restart, and ranking-checkpoint recovery. Actual-library private-method
  drivers can assert pending state without production test knobs or a real
  15-minute wait. Keep old, first-fix, and final RED/GREEN evidence separate.
- Query unresolved GitHub threads directly: a completed or newer clean summary
  can coexist with earlier findings. Bind review to the actual current head,
  answer and resolve findings with scoped evidence, and request
  one supported `@codex review` request after repairs; avoid duplicating an
  automatic review already running on that head.
- A matching persisted file can be left over from an earlier write. Record
  per-call write outcomes and errors before claiming durability; content parity
  alone does not prove atomic-write success or fsync.
