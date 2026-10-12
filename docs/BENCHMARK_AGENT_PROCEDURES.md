# Benchmark infrastructure and qualification procedures

These procedures combine source-verified infrastructure owner contributions.
Framework-specific command examples require the reviewed migration infrastructure
and its scripts to be available in the checkout. They are not installed by the
local evidence-tool setup. Check the exact committed version and its command-line help
before use; do not substitute an unrelated runner or treat absent tooling as a
passed prerequisite. An example command does not grant worker admission.

## Worker execution and controlled validation

Run heavy Rust/Cargo and native C++ work on the designated existing worker through
the single scheduling owner. Lightweight Python checks may run locally when
allowed. Controlled probes use private directories; private locks and synthetic
controls prove the probe's behavior, not native product performance. Do not
bypass locks, duplicate queues, interrupt progressing jobs, or silently retry.

Validate changed workflows with actionlint. An assigned full infrastructure
Python gate can use the bounded runner invocation below. Respect a stricter
assigned job or timeout cap; historical test counts are not acceptance criteria.

```sh
actionlint .github/workflows/bench_base.yml .github/workflows/bench_pr.yml .github/workflows/bench_pr_closed.yml
python3 scripts/bench/run.py --mode build --jobs 3 --lock-timeout-seconds 120 --timeout-seconds 240 --testbed i7-smoke --metadata infrastructure-check.json -- python3 -m unittest discover -s scripts/bench/tests
```

The canonical shared lock namespace is independent of per-job TMPDIR. Heavy
stages take the heavy lock exclusively, then the benchmark lock shared. Prebuilt
timing takes only the benchmark lock exclusively. Release between bounded
stages; after cancellation, keep custody until descendants are quiescent.
Alternate lock roots are controlled-test overrides, not qualifying worker
serialization. The cooperative runner is not a sandbox for unreviewed code.

## Complete-caller comparisons

Match and interleave complete caller measurements, including FFI, allocation,
required cloning/reset, ownership, and observable output. Verify full correctness
outside timers and retain every sample and outlier. Select the declared current
or equally optimized C++ baseline; a kernel or a Rust-only comparison cannot
qualify a runtime replacement. Separate algorithm/ownership gains from language
attribution.

The reviewed qualification contract requires a changed caller's paired time-ratio
upper confidence bound below 1 against its selected C++ baseline. A tie is
inconclusive for this migration gate. Preserve an existing Rust caller separately
where applicable, using balanced, sufficiently precise evidence, and an upper
bound at most 1. Significant unchanged-control drift is HOLD. Sufficiency controls
must be prospective; defaults are not statistical guarantees or retroactive
judgments about old ports. The existing history alert threshold is not a waiver.

Declare current-Rust preservation applicability explicitly: `required` needs a
measured `rust_current`; `not_applicable` needs a nonempty, source-bound reviewed
rationale and cannot contradict a declared Rust baseline. Keep all controls
visible. Missing, slower, noisy, or inconclusive evidence remains HOLD. Inspect
`qualification.json`: a successful summarizer process can legitimately report
HOLD.

Conditional runner/analysis examples:

```sh
python3 scripts/bench/run.py --mode build --jobs 3 --metadata BUILD_METADATA --testbed TESTBED --fixture FIXTURE --toolchain-binary COMPILER -- COMMAND ARGS
python3 scripts/bench/run.py --mode time --metadata TIME_METADATA --testbed TESTBED --fixture FIXTURE -- PREBUILT_EXECUTABLE ARGS
python3 scripts/bench/summarize.py --manifest MANIFEST --samples SAMPLES --output-dir OUTPUT
```

## Input safety, provenance, and publication

Use runner captures, collector bindings, and analysis artifacts from the same
immutable source/fixture identities. Hash runner/executable, inputs, and declared
toolchain before and after execution under the locks. Bound regular-file reads
through validated descriptors by bytes and lifecycle deadlines; reject incomplete
hashes, nonregular inputs and aliases through protected inputs before cleanup.
Preserve a child's failure status and the caller's alarm semantics. Do not invent
missing measurements or legacy provenance fields.

Keep a descriptive checkout SHA separate from each required variant's captured
source-content hash. A source review must approve the exact source identity and
complete-caller applicability maps. Captures do not create review approval or
prove build-to-binary lineage. Preserve raw downloaded bytes on errors and reuse
rejection; replace only derived status/qualification outputs with HOLD.

Measured PR/evidence subprocesses receive no publication credentials. Trusted
canonical publication code must recheck live same-repository PR/base/head state
and the verified GitHub actor immediately before writes. Use the dedicated
publication credential; check presence without displaying its value. Missing
configuration, mismatches or incomplete publication fail closed and invalidate
stale success. Preserve per-PR serialization and pending/HOLD transitions. Do
not silently provision another service or testbed.

## Signed composition and release ownership

Before any source-equivalent squash, durably preserve the signed working history
and raw evidence. Freshly fetch canonical default and the owned feature tip;
prove the final tree matches reviewed source and the sole parent is the intended
fresh base. Sign with exact xbmc4lyfe author and committer identities and verify
both the local signature and GitHub verification. Lease only an owned feature
tip when rewriting; do not rewrite default. Final independent and Codex review
must cover the actual final published head; resolve findings before integration.
Composition that changes tested source requires renewed relevant checks, while
earlier receipts remain historical evidence.

```sh
: "${OWNED_FEATURE_BRANCH:?Set the owned feature branch name}"
: "${REVIEWED_HEAD:?Set the immutable reviewed commit}"
: "${SQUASH_HEAD:?Set the final published squash commit}"
github_actor=$(gh api --hostname github.com user --jq .login) || exit 1
test "$github_actor" = xbmc4lyfe || exit 1
canonical_remote=$(git remote get-url origin) || exit 1
case "$canonical_remote" in
  https://github.com/Appz4Fun/nzbget.git|https://github.com/Appz4Fun/nzbget) ;;
  *) printf "%s\n" "Expected project HTTPS remote" >&2; exit 1 ;;
esac
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
  fetch origin \
  refs/heads/dupe-article-fallback:refs/remotes/origin/dupe-article-fallback \
  "refs/heads/$OWNED_FEATURE_BRANCH:refs/remotes/origin/$OWNED_FEATURE_BRANCH" || exit 1
base_commit=$(git rev-parse --verify origin/dupe-article-fallback) || exit 1
feature_commit=$(git rev-parse --verify "origin/$OWNED_FEATURE_BRANCH") || exit 1
squash_commit=$(git rev-parse --verify "$SQUASH_HEAD^{commit}") || exit 1
test "$feature_commit" = "$squash_commit" || exit 1
git diff --exit-code "$feature_commit" "$REVIEWED_HEAD" -- || exit 1
squash_parents=$(git show -s --format=%P "$SQUASH_HEAD") || exit 1
test "$squash_parents" = "$base_commit" || exit 1
git verify-commit "$SQUASH_HEAD" || exit 1
commit_identity=$(git show -s --format='%an <%ae>|%cn <%ce>' "$SQUASH_HEAD") || exit 1
test "$commit_identity" = 'xbmc4lyfe <273732874+xbmc4lyfe@users.noreply.github.com>|xbmc4lyfe <273732874+xbmc4lyfe@users.noreply.github.com>' || exit 1
git show --show-signature --format=fuller "$SQUASH_HEAD" || exit 1
git diff --exit-code "$REVIEWED_HEAD" "$SQUASH_HEAD" -- || exit 1
github_verified=$(gh api --hostname github.com "repos/Appz4Fun/nzbget/commits/$SQUASH_HEAD" \
  --jq '.commit | .verification.verified == true and .verification.reason == "valid" and .author.name == "xbmc4lyfe" and .committer.name == "xbmc4lyfe" and .author.email == "273732874+xbmc4lyfe@users.noreply.github.com" and .committer.email == "273732874+xbmc4lyfe@users.noreply.github.com"') || exit 1
test "$github_verified" = true || exit 1
```

Confirm that origin names the canonical repository before fetching. Root owns
scope, qualification, hold release and default integration; LIVE owns separately
authorized installation/restart and deployment checks. Report source review,
controlled validation, numerical qualification, configured publication, observed
activation, integration, and live verification separately. No signature, smoke
test or pinned tool setup alone proves faster behavior or a deployed release.
