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
python3 scripts/bench/collect_receipt.py --manifest benchmark-results/manifest.json --samples benchmark-results/samples.jsonl --build-metadata BUILD_METADATA --time-metadata TIME_METADATA --bindings BINDINGS --review-record REVIEW_RECORD --output RECEIPT
```

Repeat `--build-metadata` and `--time-metadata` for multiple captured records.
Bindings and the reviewed collection record must refer to the actual captured
source, compiler, binary and input identities; do not invent missing references.

Measured PR executables receive no publisher credentials. Authentication and
Bencher publication happen after artifact validation in the trusted stage.
GitHub writes require verified `xbmc4lyfe` identity and valid commit signatures
with that exact author and committer. Use the verified HTTPS credential helper,
not an SSH transport whose account differs. Never print credentials.

Configuration names include `BENCHER_PROJECT`, `BENCHER_API_KEY` and optional
`BENCHER_HOST`; discover presence without values. Report `ready=false` and
preserve reviewable artifacts when unavailable. No silent activation claim.
