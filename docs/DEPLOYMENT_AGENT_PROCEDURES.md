## Deployment and preservation

### Ownership and authorization

- The designated integration coordinator owns the canonical default branch and
  backend qualification/hold release. Each PR owner performs that PR's authorized
  deployment and verifies the result. The designated operations coordinator
  schedules shared-worker work; there is no central redeployer to take over
  unfinished PR delivery.
- Carry existing direct human authorization forward. Surface changed scope or
  conflicting instructions; do not introduce blanket reapproval flows.
- A source merge, UI release, signed identity repair, installed tool, or skipped
  benchmark check does not release a backend performance hold.
- Keep this guidance additive when consolidating other lanes' procedures. Preserve
  dirty work and immutable reviewed candidates through isolated worktrees.

### PR owner delivery lifecycle

1. Own the PR from implementation through deployment. Fix actionable review
   comments, resolve discussions with supporting evidence, and request review
   again after fixes. Refresh the actual upstream default, resolve conflicts, and
   repeat affected checks and review after head or base changes.
2. Require g2g review of the actual final head and green required pre-merge checks
   before integration. Prepare the locally signed squash against the fresh default
   using the identity and reviewed-tree safeguards below. Coordinate the default
   write with the integration owner.
3. Follow required default-branch CI/CD after merge. Investigate and fix failures
   through the same review and validation process. Deploy the exact merged,
   qualified artifact yourself under the existing authorization and release holds;
   request the shared execution slot rather than handing off to a central agent.
   When CD installs the artifact automatically, trigger it if needed and monitor
   its actual terminal result.
4. Verify the installed artifact or revision, service health, preservation of
   existing state, and the changed behavior. Preserve rollback material and record
   what was deployed, the checks performed, their results, and remaining limits.
   A successful job alone does not establish the deployed artifact's identity or
   the correctness of the live behavior.
5. Keep ownership when access, scheduling, or a release hold blocks deployment.
   Report the concrete blocker and required next action; do not silently delegate
   deployment or archive the chat. A different owner may take over only through
   an explicit human-accepted handoff.
6. If no artifact requires deployment, record that scope decision and its reason.
   For published documentation, follow the applicable publishing pipeline and
   verify publication. Finish or archive only after verified delivery or explicit
   human acceptance of a handoff or an undeployed outcome.

### GitHub identity and immutable input

Before a GitHub action, verify the active HTTPS credential belongs to
`xbmc4lyfe`. These commands were used for identity and fresh-ref checks:

```sh
github_actor=$(gh api --hostname github.com user --jq .login) || exit 1
test "$github_actor" = xbmc4lyfe || exit 1
canonical_remote=$(git remote get-url origin) || exit 1
case "$canonical_remote" in
  https://github.com/Appz4Fun/nzbget.git|https://github.com/Appz4Fun/nzbget) ;;
  *) printf "%s\n" "Expected project HTTPS remote" >&2; exit 1 ;;
esac
git status --porcelain
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
  fetch origin dupe-article-fallback
```

- Keep the demonstrated credential-helper override for authorized Git mutations
  as well as fetches; checking the API account alone does not establish Git
  transport identity. Do not expose credential values or credential-bearing URLs.
- Verify both raw author and committer names are exactly `xbmc4lyfe`, with the
  canonical account email, a valid locally verified registered SSH signature,
  and GitHub verification. GitHub's verified badge alone is insufficient.
- Retain the immutable source commit/tree and executable/package hashes, final-head
  review result, resolved discussions, validation receipts, and caller/workload
  scope. Reuse demonstrated source-equivalent evidence with explicit blob/hash
  comparisons; do not silently reinterpret old results as fresh-composition tests.
- The integration coordinator preserves the reviewed, original signed single
  squash commit with a checked fast-forward. Avoid GitHub-generated merge/squash
  commits. Published identity repairs require the applicable direct human
  authorization and exact-ref safeguards; retain the original object and explain
  the historical PR merge record separately.

### Storage and worker boundaries

- Use the human-designated remote NVMe build root for unique owner/job source,
  build, target, and temporary outputs. Its existence is not a build admission.
  Preserve existing jobs/artifacts when changing destinations.
- Keep the host-wide `i7-heavy.lock` and `nzbget-rust-benchmark.lock` at their
  canonical shared system-temp locations. Per-job `TMPDIR` must never change
  lock identity. Do not resolve shared locks from a relocated job temp directory.
- Builds use heavy-exclusive then benchmark-shared locking, at most three jobs,
  bounded admission/payloads, and release locks between stages. Prebuilt timing
  uses benchmark-exclusive locking alone. Use the approved scheduler and payload;
  do not add duplicate queues, silent retries, or interrupts of progressing jobs.
- Inspect available bytes for the user and relevant filesystem, inodes, projected
  writes, and the approved safety floor immediately before admission. Historical
  capacity readings and root-reserved free blocks are not ordinary-user headroom.
- Record unsuccessful admissions and ENOSPC separately from executed test failures.
  Never remove source, failed/raw evidence, or release/rollback artifacts to make
  room. Generated cache cleanup requires owner coordination and integrity checks.

### UI-only launch

1. Confirm the exact canonical signed candidate is actually merged by the authorized
   account; inspect the complete runtime diff and current default. UI-only launch
   excludes daemon/Rust implementation changes from installation.
2. Capture fresh service identity, configuration/proxy settings, history/twin fields,
   stored lists, queue/post-processing state, and health/error baseline. Recheck idle
   immediately before the swap. Avoid production provider activity during validation.
3. Back up configuration, queue state, and installed assets with restricted access.
   Check archive readability and record hashes. Configuration/authentication values
   and production content stay out of public evidence.
4. Stage all immutable WebUI files as a sibling of the effective installed WebUI
   directory. Verify the complete staged manifest. The stage must share the
   installation filesystem even when the source checkout is on NVMe.
5. The tested Linux procedure uses `renameat2(RENAME_EXCHANGE)` to exchange the
   complete directories atomically. Keep the former assets for rollback. An
   unsupported host/filesystem requires its separately established installation
   procedure; do not silently perform a partial copy into the live directory.
6. Preserve the running daemon PID/executable and configuration, queue/history,
   provider settings, and twin state. UI-only launch does not restart the daemon.
7. Verify installed hashes and authenticated HTTP fingerprints for changed assets
   plus startup, typography, and relevant locale assets. Perform immediate, warm,
   and post-UI-QA checks; record each phase without overwriting earlier evidence.
8. Coordinate read-only desktop/phone QA with the UI owner: page/section navigation,
   overflow, keyboard/ARIA behavior, editors, search/help, and health notices. Avoid
   saves, add/delete/reorder, queue/history changes, and provider requests.
9. Report the terminal receipt and explicitly release any temporary default-write
   UI-QA hold. Keep independent backend holds in force.

### Backend launch and rollback

- Accept an exact frozen, reviewed, signed complete runtime composition only after
  the coordinator releases its backend hold and required offline qualification and
  isolated-canary gates pass. Identify every bundled runtime change; do not install
  a descendant simply because a different optimization is validated.
- Retain a known-good compatible executable/package and UI assets. Confirm the loaded
  process executable hash after the supported install/restart, not only its version
  string. Repeat fresh idle/backup and immediate/warm preservation checks.
- Compare all captured twin/history fields and decoded stored-list identities,
  completion flags, file metadata, and within-list ordering. If raw serialization
  order changes, explain the validated semantic comparison; do not claim byte
  equality from a line multiset alone.
- New crashes, protocol/byte corruption, false repair success, unexpected config or
  twin-state changes, or breached approved health/resource/performance budgets fail
  the release. Preserve bounded incident evidence and use the known-good recovery
  procedure.
- Revert code/assets first as appropriate. Never blindly overwrite newer completed
  queue/history state with an older backup; reconcile persisted changes according to
  the established state-compatibility plan.

### Evidence scope

- Preserve raw success, failure, malformed, and inconclusive artifacts before parsing
  or aggregation. Capture exact commands, source/fixture/binary identity, toolchain,
  environment roles, declared units, exit status, admission, and output verification.
- C++-instrumented ASan/UBSan checks do not instrument an ordinary Rust archive.
  Width-substitution models do not constitute native cross-platform execution.
  Record these limits and separate diagnostic, correctness, performance, and live
  deployment claims.
- Research proposals and tools that have not run are not established procedures.
  Documentation permission authorizes documentation, not tool installation,
  instrumentation, extra timing, backend rollout, or release of existing holds.
- Public prose, docs, comments, and assets contain no secrets, running configuration
  values, provider/history content, or absolute filesystem paths. Use logical roles,
  relative artifact identifiers, and sanitized examples.
