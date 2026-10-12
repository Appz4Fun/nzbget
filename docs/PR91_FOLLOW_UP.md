# PR91 validation and review follow-up

The maintainer authorized squash integration before complete validation on
2026-10-12. This records remaining work rather than claiming final qualification.
Bencher activation, measured runtime performance, and backend deployment remain
subject to their existing holds.

## Evidence already available

- The earlier combined Python run at `f5f630ae` ran 339 tests: 337 passed and
  two helper-output contract checks errored. Its logs and source-bound receipts
  remain preserved. It is not a passing result for the integrated revision.
- The signed publisher repair at `10f30215` passed all 111 publisher and pipeline
  tests with zero skips, unchanged pipeline assertions, and stable captured
  inputs. Its existing publication peer completed a scoped source review with
  no findings. This is component evidence, not whole-tree clearance.
- The final earlier whole-tree review found retained-archive alias data loss in
  both RPC and postprocessing cleanup, plus the publisher helper-output issue.
  Candidate adapter repairs are included for follow-up verification; their
  presence alone does not establish remediation.
- Earlier runner and workflow repairs have scoped reviews and validation.
  Rust executable inputs retain separate source-equality and previously recorded
  native validation evidence. No new production speedup is established here.

## TODO after integration

- [ ] Collect the admitted retained-archive baseline regression run and bind its
  actual result, source/test hashes, raw logs and terminal lock-custody receipt.
  Keep setup failures separate from reproduced behavioral failures.
- [ ] Run the repaired RPC and postprocessing suites on the coordinated Linux
  worker. Verify every retained raw filename and lexical, intermediate symlink,
  resolved-target and inode alias before cleanup, derived writes and HOLD paths.
  Preserve existing cleanup of unaliased derived exports.
- [ ] Complete the existing adapter peers' reviews of the integrated repairs.
- [ ] Run `python3 -m unittest discover -s scripts/bench/tests -v` through the
  coordinated runner on the exact integrated source and record actual outcomes.
  Preserve the earlier failing evidence; do not substitute component passes.
- [ ] Complete a whole-tree review and a fresh GitHub Codex review of the signed
  integrated revision. Keep unresolved review findings visible until verified.
- [ ] Recheck Rust executable input equality before reusing prior native results;
  renew affected validation if those inputs change.
- [ ] Verify workflow raw-artifact retention with an actual trusted workflow run.
  The existing artifact-selector check used a synthetic transport and model.
- [ ] Configure and observe trusted Bencher publication before declaring it
  active. Keep incomplete or failed qualification in HOLD.

The five original GitHub review threads cover descendant lock custody, actual
source-content binding, Cargo configuration overrides, explicit Rust
applicability, and bounded source capture. Source repairs and earlier checks
exist, but those threads must not be represented as current-head review approval
or resolved merely because integration was authorized.
