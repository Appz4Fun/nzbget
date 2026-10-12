# Evidence and retrospective knowledge

The goal is to preserve what ran, what it produced, what was concluded, and why.
An evidence packet and its interpretation are distinct: a valid signature or a
reproducible command does not establish the correctness of a performance claim.

## Run lifecycle

1. Record a prospective plan with a question, exact source baseline, fixture
   identity, real caller boundary, controls, scenarios, repetition hierarchy,
   analysis method and stopping rule. Hash the plan before execution.
2. Confirm tools, uploads, hashes, free storage, and execution ownership. Reserve
   a new run identifier and directory with exclusive creation. If admission or
   evidence capture cannot succeed, do not start the payload.
3. Create per-process command records and raw output sinks before spawning.
   Write completion or failure status before interpreting output. A launch
   failure has no child exit code; record that distinction. Preserve partial
   streams after timeout or interruption and keep the attempt discoverable.
4. Verify correctness and route coverage, then evaluate unchanged-code controls
   before drawing performance conclusions. Keep every trial and negative result.
   A changed method creates a separate prospective plan, not a replacement run.
5. Seal a manifest of artifact hashes and retain the original evidence. Analysis
   records identify the parser/version and inputs they used. Redaction is an
   exported derivative with its own hash; it never modifies the private original.
6. Write a short decision record: observation, hypothesis, discriminator,
   result, decision, uncertainty, and conditions for reconsideration. Link the
   evidence and any superseded decision. Distinguish an observed result from
   reproduced, verified, reviewed, integrated, and deployed behavior.
7. Preserve sealed packets in an approved separate store and check restorability.
   Capacity checks are not reservations: handle write failure at every stage.
   Never delete earlier evidence to make a current attempt appear complete.

## Minimal record

Use one structured record per run and one per process. At minimum retain:

```json
{
  "run_id": "unique-run-id",
  "plan_sha256": "digest-of-frozen-plan",
  "source_revision": "exact-commit",
  "source_state": "clean-or-dirty-with-source-manifest",
  "binary_sha256": "digest-of-executed-binary",
  "fixture_sha256": "digest-of-fixture-or-generation-specification",
  "tool_versions": {},
  "machine_configuration": {},
  "process_records": [],
  "artifact_hashes": {},
  "capture_provenance": "prospective-or-explicitly-recovered",
  "calibration": "passed-failed-or-inconclusive",
  "analysis_version": "exact-analysis-source-digest",
  "conclusion": "supported-claim-and-limitations",
  "supersedes": []
}
```

Process records include the command, working-directory label, start/end time,
exit code or launch/interruption status, stdout/stderr artifact references, and
the scenario and trial identity. Public labels are repository-relative. Do not
collect private provider configuration or credentials into shared packets.

## Tool roles

| Tool | Role | Boundary |
| --- | --- | --- |
| RO-Crate | Describe inputs, software, executions, outputs, and decisions | Metadata links do not authenticate claims |
| in-toto | Record materials/products and sign provenance | An approved signer and verification policy are required; this is separate from GitHub commit verification |
| restic | Snapshot approved evidence storage with deduplication | Installation does not configure a backup destination, authorize pruning, or free the original worker |
| rr, on Linux | Replay a captured fixture failure and debug backward | Traced execution is diagnostic, not native timing evidence |
| ReproZip, on Linux | Discover runtime dependencies and package a reproducer | Capture in an untimed run; it does not reproduce CPU/cache/SMT state |
| Git bisect | Locate a classifiable correctness or performance regression | Skip inconclusive or untestable revisions with exit 125; do not misclassify noise as failure |

Use existing benchmark/report infrastructure rather than creating competing
dashboards. Tools are optional according to the question: routine runs need raw
capture, hashes and decisions; record/replay and dependency tracing are focused
diagnostics. Never automatically start heavy work because a tool is available.

## Installation and checks

The local macOS core tools use isolated Python 3.12 environments and a Homebrew
bottle. Exact installed versions are recorded in the verification packet; pin
them when recreating that environment:

```sh
uv tool install --python 3.12 'rocrate==0.16.0'
uv tool install --python 3.12 'in-toto==3.1.0'
brew install --force-bottle restic
rocrate --help
in-toto-run --help
restic version
git bisect -h
```

The Homebrew package is currently restic 0.19.1. A future bottle may differ;
record its actual version rather than presenting a version expectation as fact.
Keep the Python tool environments separate from NZBGet dependencies.

RO-Crate command-line examples, executed inside a fresh packet directory:

```sh
rocrate init
rocrate add file run.json
rocrate write-zip ../packet.zip
```

Check command-line help for the installed version before using examples. Packaging does
not certify a specialized Workflow Run profile; represent execution/decision
relationships explicitly and validate the chosen profile separately when needed.

`in-toto-run` captures materials/products and can record streams, but it is not
the primary crash-safe evidence writer. Keep pre-created raw files independent
of its final metadata. Its command-line tool requires a signing key or GPG identity. Use an
approved provenance signer; do not silently reuse, convert, or replace the Git
SSH signing key. Do not create a production trust identity as an installation
side effect. Disposable test keys are only for verification and convey no
`xbmc4lyfe` identity or release approval.

Before Linux rr/ReproZip installation, ask the scheduling owner to verify worker
capacity (at least 1 GiB available for admission, or a larger assigned budget),
package availability, and platform support. Use official distribution
packages or an isolated environment, record versions, and run only a bounded
offline diagnostic when explicitly assigned. An unavailable Linux tool is a
reported limitation; do not silently substitute a traced timing result.

The Ubuntu 24.04 worker's approved setup installed `reprozip` and
`python3-reprozip` 1.3-2build1, `python3-rpaths` 0.13-2, and
`python3-usagestats` 1.0.1-1. Exact package versions and ReproZip version/help
readiness were verified; no trace or pack operation was performed. Refresh
readiness before a future diagnostic. `rr` remains deferred; installation does
not authorize hardware-counter permission changes or host tuning.

For restic, a real backup needs an approved repository, credentials, and retention
policy. Verify a disposable fixture backup, integrity check, and restore before
depending on an evidence repository. Production backup initialization, remote
uploads, credential changes and destructive retention operations are separate
actions from installing the executable.

## References

- [RO-Crate Python implementation](https://pypi.org/project/rocrate/)
- [in-toto command-line implementation](https://pypi.org/project/in-toto/)
- [in-toto statement format](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
- [restic backup documentation](https://restic.readthedocs.io/en/stable/040_backup.html)
- [rr project](https://rr-project.org/)
- [ReproZip documentation](https://docs.reprozip.org/en/latest/)
- [Git bisect](https://git-scm.com/docs/git-bisect)
- [Decision records](https://martinfowler.com/bliki/ArchitectureDecisionRecord.html)
