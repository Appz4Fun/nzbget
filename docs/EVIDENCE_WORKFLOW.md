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

## Complete staging and child output contracts

Before dispatch, enumerate every run-local input the frozen controller reads
and the plan requires, including auxiliary manifests outside the source-freeze
member list. Verify each required file at the actual execution prefix using a
bounded regular-file descriptor read and the expected size and hash. A verified
source copy or a manifest hashed elsewhere does not establish complete staging.
Preserve an incomplete attempt and its consumed marker. Corrected staging needs
a fresh exclusive execution prefix, new once-only admission and authorization
from the designated owner; do not fill the failed prefix or reuse its marker.

Freeze stdout and stderr expectations from the actual child emission path and
source contract. A successful helper can write bounded diagnostics to stdout
while its test summary appears on stderr. Retain the raw streams, native exit,
test summary, and controller decision as separate evidence. If those records
expose a parser or output-oracle mismatch, preserve the whole attempt's HOLD
and any unreached final checks as UNKNOWN. Review a newly identified source or
control correction before separately authorized execution. Changed source or
output-oracle contracts need a new prospective plan and every check that plan
requires; earlier passes remain historical evidence and do not qualify the
corrected attempt. Never waive the old check, relabel the old attempt PASS, or
silently replay passing suites to replace its evidence. This guidance does not
authorize execution or waive required checks under the corrected plan.

These lessons came from two investigations spanning three retained attempts.
V26 omitted the plan-bound
`readonly-artifact-guards.json` despite staging every source-freeze member,
and failed before locks, Docker, or provider work. A separately admitted
`execution-v2` staged the complete set and captured a healthy reference only;
it established neither repair nor speed qualification. PR #104's continuation
had three native exits of zero and four helper tests reported OK on stderr,
but a legitimate 42-byte stdout diagnostic violated the controller's
empty-stdout assumption. The continuation remained HOLD and its final runtime
afterguard was unreached and UNKNOWN.

### Retained evidence references

The scheduling owner holds the following original records outside Git. Their
record labels and SHA-256 digests identify the evidence supporting the examples
in the preceding paragraphs; request those exact records from the owner. Access
requires owner coordination. Public availability, backup, and independent
restoration remain unverified.

| Owner-held record label | SHA-256 |
| --- | --- |
| `V26-required-guard-staging-prelock-HOLD-1792037951018840000/receipt.json` | `f78df75572d3c03eb3ece80f39543694b98e6c529786b78bf6662ee31ad9c09c` |
| `nzbget-root-v26-staging-correction-fresh-once-grant-1792037953126509000/grant.json` | `5d12e8bab8ffff8baf69b84673f6ba4e8dc493a96a03e2a7f94348a221702340` |
| `V26-execution-v2-staging-closure-acceptance-v1/acceptance.json` | `0bca16c971b3a5d99c0c04c125331c6b66923741781bfa99278e05757df9071a` |
| `V26-healthy-reference-terminal-1792038501804381000/receipt.json` | `b3d6f50d7447f43f947cd998f043cb83e556e09320d9450f70bfafb2c1493883` |
| `PR104-continuation3-native0-helper-oracle-HOLD-1792037328807135000/receipt.json` | `e6213a011ce4083662d5a1259fc131f7a202ab41fbb8449435b4fcef7dbc3909` |
| `committed-capture-contract-tests.stdout` | `4a1e0d1a64e4aeaa45f6685371c518969c698602cd6cdcefcd89f36d12b5b02d` |

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
