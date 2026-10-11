# Benchmark evidence for Rust ports

Keep three measurement scopes distinct. Bencher publishes history; it does not
turn a kernel result or a tolerated monitoring alert into migration approval.

| Evidence | What it measures | Use |
| --- | --- | --- |
| `ports.rs` | Rust functions on generated inputs | Existing Rust-only regression history |
| `criterion_ports.rs` | Selected Rust kernels with explicit setup boundaries | Attribution and kernel experiments |
| Matched complete caller | C++, current Rust where present, and the candidate with real caller ownership/costs | Runtime replacement qualification |

## Activation status

At the 2026-10-11 foundation handoff, the shared runner/statistics contracts are
frozen and source reviewed. That is tool setup evidence, not timing proof.

| Component | Recorded state |
| --- | --- |
| Existing `ports.rs` and three benchmark workflows | Present on the default branch; Rust-only definitions |
| Shared v1 collection, validation and publication | Incoming foundation integration; availability follows its reviewed merge |
| Criterion | Maintained 0.8.2, development dependency only; 12 kernel IDs covering RPC JSON parameters, JSON encode/decode and Base64 at 32, 4096 and 65536 actual input bytes |
| Criterion build/smoke | Build completed and all 12 prebuilt smoke cases passed; `--test` is not speed proof |
| Bencher project/API configuration | Absent at preflight; publication `ready=false` |
| GitHub publication identity | `BENCHMARK_GITHUB_TOKEN` must authenticate as `xbmc4lyfe`; a default `GITHUB_TOKEN` bot is insufficient |

The dedicated GitHub credential and `BENCH_TESTBED=i7-8700k-linux-x86_64` were
configured through the verified GitHub account. Historical `i7-smoke` receipts
remain validation records under their original identifier. Bencher project/key
configuration and an observed successful publication are separate activation
requirements.

No successful Bencher activation or timing run is inferred from workflow files,
configuration names, a signed commit, or a source-review verdict. Activation
needs validated configuration and an observed successful trusted publication.
Do not expose secret values or provision a new paid/cloud testbed as a fallback.

## Build first, then run prebuilt programs

Heavy work runs on the configured remote testbed. Build commands acquire
`i7-heavy.lock` exclusively, then `nzbget-rust-benchmark.lock` shared, both under
the process temporary directory. Use at most three build jobs. Timing acquires
only the benchmark lock exclusively, executes a prebuilt program, and never
subsequently compiles or requests the heavy lock. Release between bounded suites.

From the repository root, using the shared runner:

```sh
python3 scripts/bench/run.py --mode build -- cargo bench --manifest-path rust/Cargo.toml --locked --jobs 3 --bench ports --no-run --message-format=json
```

Select the executable from the matching Cargo `compiler-artifact` record; do not
guess a hashed filename or use a binary left from another source/configuration.
Set `PORTS_BIN` to that recorded executable, then:

```sh
python3 scripts/bench/run.py --mode time -- "$PORTS_BIN"
python3 scripts/bench/run.py --mode time -- "$PORTS_BIN" twin/
```

Runner provenance distinguishes `lock_scope=worker_default` from
`lock_scope=test_override`. Overrides exist for controlled runner tests; the
canonical publisher rejects them. Tests of locks are not production timing.

## Criterion kernel pilot

Criterion 0.8.2 is pinned as a development dependency and does not enter the
daemon runtime. Build under the build locks and select the matching executable
from Cargo's JSON artifact output:

```sh
python3 scripts/bench/run.py --mode build -- cargo bench --manifest-path rust/Cargo.toml --locked --jobs 3 --bench criterion_ports --no-run --message-format=json > criterion-artifacts.json
```

With `CRITERION_BIN` set to that executable:

```sh
python3 scripts/bench/run.py --mode time -- "$CRITERION_BIN" --test
python3 scripts/bench/run.py --mode time -- "$CRITERION_BIN" --bench
```

`--test` exercises the 12 smoke cases without timing proof. `--bench` collects
real kernel measurements. State which input preparation, allocation, reset,
copy and destruction costs are included or excluded. Kernel throughput can
identify a candidate hotspot; it cannot qualify a C++ runtime replacement.
Use observable results and inspect optimized work when constant folding is a
concern; a `black_box` call alone is not complete-caller evidence.

## Shared evidence v1

Collection produces immutable `benchmark-results/manifest.json` and
`benchmark-results/samples.jsonl`. The manifest has `schema_version=1`, full
`base_sha` and `candidate_sha`, stable `testbed`, string-valued `toolchain`,
`fixtures` with `id`, `sha256` and `scope`, and a `comparison` naming baseline
and candidate variants. Scope is `complete_caller` or `kernel`. Preserve source,
compiler, binary and input hashes in provenance.

Variants are `cpp_current`, `cpp_optimized`, `rust_current`, `rust_candidate`.
Omit unused variants, but never manufacture a required missing baseline. Keep
the original C++ rows and any stronger optimized control visible.
Set each fixture's `required_variants` explicitly. For an already-ported caller,
include `rust_current` alongside the selected C++ and candidate variants so the
preservation gate runs. Omitting this field defaults to the selected pair and
does not establish current-Rust preservation.

Each JSONL sample records `case`, `variant`, integer `process`, `round` and
`order`, positive finite `elapsed_ns`, positive integer `iterations`, and the
SHA256 `observable_digest` of verified output. Latency is elapsed/iterations.
The process/round block and order describe the actual interleaved measurements;
do not invent pairing from aggregate times. Equivalent variants must have
matching output digests. Retain all samples and outliers unchanged.

Validate and summarize with the frozen interface:

```sh
python3 scripts/bench/summarize.py --manifest benchmark-results/manifest.json --samples benchmark-results/samples.jsonl --output-dir benchmark-summary
```

Outputs are `summary.json`, `bencher.json`, `qualification.json` and `report.md`.
The paired ratio bootstrap resamples whole processes: 5000 draws, fixed seed
20261011. Preserve configured prospective policy and fixture roles in the
receipt/report. A valid exit 0 can mean HOLD; consumers must read qualification.
Exit 2 means invalid evidence. Missing fields, nonfinite times, duplicate rows,
mismatched outputs or unmatched required pairs are not fabricated into PASS.

The legacy Rust suite emits Bencher Metric Format `latency` in ns/op: median
of 21 samples, fastest as `lower_value`, p90 as `upper_value`. Fastest/p90 are
distribution summaries, not confidence intervals. Shared BMF exports must
label their actual interval method honestly.

## Complete caller qualification

A migration PR includes C++/current-Rust/candidate times, percentage changes,
raw samples, immutable source/compiler/binary/input identities and reproduction
instructions. Time the real external C++/FFI boundaries, allocations, mutable
input clone/reset costs and ownership/destruction that the caller requires.
Keep costs equal across variants; verify full observable output outside timers.
Show all representative fixtures, slower rows and unchanged-control drift.

The replacement must be independently faster than the C++ it replaces and
must preserve existing Rust caller performance where that boundary is already
ported. Inconclusive or missing complete-caller evidence is HOLD. Rework slower
paths or hold/split them out; a kernel win cannot rescue a slower caller.

For a changed complete caller, the selected C++ comparison needs a paired ratio
95% interval with upper bound below 1. When `rust_current` is required and differs
from the candidate, preservation also needs an upper bound at most 1, with the
same process-count, order-balance and interval-width checks. An optimized C++ tie
remains inconclusive for speedup even when Rust preservation passes. An unchanged
control needs intervals containing 1 against both the selected baseline and any
required distinct current-Rust baseline. Reports expose the separate
`rust_preservation` result; comparing current Rust with itself adds no extra gate.

Disclose fixed-object/DSO/static-link differences, compiler placement sensitivity
and host noise. Bootstrap intervals do not remove systematic layout bias.

The inherited Bencher 10% historical alert threshold is regression monitoring,
not permission to migrate a routine up to 10% slower. Passing that alert check
is not migration qualification. Shared hosted-runner results may monitor/smoke
but cannot approve a replacement on the stable remote testbed's behalf.

New prospective defaults do not retroactively invalidate the independently
reviewed legacy evidence for PRs #84/#86. Partial legacy imports are explicit
`legacy-metadata.json` with `artifact_kind=legacy_hold_archive` and
`archive_schema_version=1`: unknown identities/hashes remain unknown, empty
samples are explicit, and original rows, units and raw hashes are preserved.
These archives are not native v1 qualification or fabricated complete evidence.

## Trusted publication

Initial transport is an evidence commit signed by `xbmc4lyfe` with the fixed
`benchmark-results` files. The trusted default workflow fetches data only and
validates the reviewed collection receipt plus source/compiler/binary/input
hashes. A signature proves commit identity, not measurement attestation.

Create the collection receipt from captured references using the frozen CLI:

```sh
mkdir -p benchmark-results
python3 scripts/bench/collect_receipt.py --manifest benchmark-results/manifest.json --samples benchmark-results/samples.jsonl --build-metadata BUILD_METADATA --time-metadata TIME_METADATA --bindings BINDINGS --review-record REVIEW_RECORD --output benchmark-results/collection-receipt.json
```

Repeat `--build-metadata` and `--time-metadata` for multiple captured records.
Bindings and the reviewed collection record must refer to the actual captured
source, compiler, binary and input identities; do not invent missing references.

Capture the build and prebuilt execution for each reviewed complete-caller
variant. Set `CXX_BIN`, `BUILD_ARGS`, `CALLER_BIN` and `RUN_ARGS` from that caller's
reviewed compiler command and native measurement interface. Set `SOURCE_ARCHIVE`,
`INPUT_FIXTURE` and `RUST_LIBRARY` to the actual source bundle, input and linked
Rust archive. The arrays below preserve the reviewed argument vectors; they are
not a new harness interface. Run from the recorded variant checkout, then repeat
with distinct metadata files for the other required variants:

```sh
mkdir -p benchmark-captures benchmark-results
python3 scripts/bench/run.py --mode build --jobs 3 --metadata benchmark-captures/build.json --testbed i7-8700k-linux-x86_64 --fixture "$SOURCE_ARCHIVE" --fixture "$INPUT_FIXTURE" --fixture "$RUST_LIBRARY" --toolchain-binary "$CXX_BIN" -- "$CXX_BIN" "${BUILD_ARGS[@]}"
python3 scripts/bench/run.py --mode time --metadata benchmark-captures/time.json --testbed i7-8700k-linux-x86_64 --fixture "$SOURCE_ARCHIVE" --fixture "$INPUT_FIXTURE" --toolchain-binary "$CXX_BIN" -- "$CALLER_BIN" "${RUN_ARGS[@]}" > benchmark-captures/caller-output.log
```

This example captures a Rust-enabled caller. For a C++ variant that does not
link a Rust archive, omit that unused fixture and its binding.

Build captures identify the compiler as `executable` and `tool-0`, source bundle
as `fixture-0`, input as `fixture-1`, and Rust archive as `fixture-2`. Time captures
identify the prebuilt caller as `executable`, source/input as `fixture-0`/`fixture-1`,
and compiler as `tool-0`. A reviewed source binding combines the captured source
fixture and descriptive checkout SHA. Stable captures establish recorded file
identity; they do not attest a clean checkout or prove build-to-binary linkage.
The caller's genuine samples still need the v1 manifest/JSONL contract; capturing
a kernel executable or a legacy log does not produce complete-caller qualification.
After recording the bindings and operator review, use the actual metadata paths:

```sh
python3 scripts/bench/collect_receipt.py --manifest benchmark-results/manifest.json --samples benchmark-results/samples.jsonl --build-metadata benchmark-captures/build.json --time-metadata benchmark-captures/time.json --bindings "$BINDINGS" --review-record "$REVIEW_RECORD" --output benchmark-results/collection-receipt.json
```

Add repeated metadata arguments for every record referenced by the bindings.

Measured PR executables receive no publisher credentials. Authentication and
Bencher publication happen after artifact validation in the trusted stage.
GitHub writes require verified `xbmc4lyfe` identity and valid commit signatures
with that exact author and committer. Use the verified HTTPS credential helper,
not an SSH transport whose account differs. Never print credentials.

Trusted default-branch code handles lifecycle events without checking out PR
code. Base pushes and PR updates invalidate outdated qualification; automatic
invalidation preserves a newer trusted PASS already bound to the current base.
Manual validation begins pending and reports HOLD when evidence or publication
does not complete. These GitHub statuses require the dedicated verified identity
independently of Bencher configuration. Publication and archival serialize their
writes by canonical PR number; fork heads are ineligible for publication.

The frozen Rust-source validation passed 219 unit tests (one ignored) and the
allocation test. Clippy for the library and new Criterion benchmark passed with
warnings denied. Strict Clippy across all targets failed on 30 existing test-code
lints; this is retained as a failed check rather than reported as a full pass.

Configuration names include `BENCHER_PROJECT`, `BENCHER_API_KEY` and optional
`BENCHER_HOST`; discover presence without values. Report `ready=false` and
preserve reviewable artifacts when unavailable. No silent activation claim.
