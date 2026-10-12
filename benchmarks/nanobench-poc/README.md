# Paired benchmark viewer and evidence

Explore the existing fixture-only archive-read experiment without building
NZBGet, installing dependencies, or contacting providers. Open `index.html`
directly in a browser, or serve this directory from the repository root:

```sh
python3 -m http.server 8766 --bind 127.0.0.1 --directory benchmarks/nanobench-poc
```

Visit <http://127.0.0.1:8766/index.html>. Select a scenario, independent process,
and chart to inspect paired speed intervals, median latency, and all raw rounds.
The viewer embeds its data and needs no network connection. Its buttons download
the results JSON and the adjacent `proof-of-concept.zip` source/evidence bundle.

Verify the export using Python 3.9 or newer, with no third-party packages, on
a platform providing directory-relative reads and `O_DIRECTORY`, `O_NOFOLLOW`,
and `O_NONBLOCK` (such as Linux or macOS).
The verifier fails closed without these flags; viewing the static page is
independent of this platform requirement:

```sh
python3 benchmarks/nanobench-poc/verify.py
python3 benchmarks/nanobench-poc/test_verify.py
```

The verifier checks file and archive hashes, archive inventories, exact measured
candidate source hashes, the retained broken-route capture, embedded viewer data,
unique scenario/process keys, raw sample/result validity, scenario-specific
scratch-boundary counts, and the recorded control diagnostic. It does not recompute the
framework's statistical intervals or certify the original experiment. The regression suite covers file admission, launch receipts, and malformed
result/boundary data. Child processes are bounded; FIFO and POSIX symlink checks are skipped
where their required platform support is unavailable. Their small raw command,
output, and completion records remain in uniquely named temporary directories.
The probe harness supports standalone single-threaded POSIX command-line use.
It preserves signal policies and masks SIGINT only for ownership bookkeeping
and bounded child cleanup plus the terminal receipt. In-process `Popen`
construction has no timeout; bound the complete suite externally. An exception
without a returned child handle leaves ownership and reap state unknown.
Unexpected cleanup or receipt failures are unsuccessful, with retained raw
evidence and incomplete custody reported instead of a passing result.

## What the evidence establishes

The existing pilot contains seven scenarios and three independent process
executions each: 21 comparisons and 4,368 timed samples. All alternatives share
one executable and the real `StreamRepairController::ReadDonorInner` caller.
The fixture seed is `0x51c0ffee`; crypto is RAR3/AES-128. Original C++, equivalent
single-buffer C++, Rust scratch ownership, and an identical-original control
are compared. Key derivation and fixture preparation are outside timing;
fresh-output allocation and scratch lifetime remain inside the measured call.

Fourteen controls met the pilot's diagnostic: the interval contains 1 and fits
within the reported ±2% band. Its prospective status is unverified: neither
the pre-run plan nor a prospective plan digest is included in this public packet.
Embedded plan values and recorder source show the reported method, not when it
was frozen. That band is a historical precision diagnostic. Intervals
remain conditional on the framework's assumptions and separate for each process.
No combined interval across processes or Rust-specific speed advantage is
established. Large-read results and production qualification remain inconclusive.
The cryptoread performance hold is unchanged. Exact integer elapsed times and
a prospective duration floor required by the current qualification workflow are
absent from this pilot. Do not reconstruct elapsed time from rounded averages.
The verifier reports `ARTIFACT INTEGRITY OK` separately from `QUALIFICATION HOLD`;
a successful archive inspection exit is never benchmark acceptance.

## Capture and publication provenance

These are the original retained successful outputs, published retrospectively.
Attempt 001 completed all 21 measured invocations. Its recorder retained stdout
and stderr only after exit and parsing checks; it did not guarantee retention
of failed or malformed output. The recovered outputs must not be described as
prospectively crash-safe captures. The separately repaired recorder passed
synthetic success, failure, malformed-output, and directory-collision checks.
No second timing suite executed. These statements describe the historical pilot,
not a fresh benchmark of the current default branch.

`index.html` is a separately identified publication view derived from the
unchanged historical `proof.html`. It makes the unverified prospective-plan
custody and missing environment evidence visible and links the supplements.
Original wording in `proof.html` and the historical ZIP remains as evidence of
what was previously reported, not an endorsement of its prospective claims.

The public packet does not include captured CPU/machine configuration, OS/kernel
information, compiler version, exact compilation flags, or separate per-process
zero-exit receipts from the original timing attempt. These are unavailable for
this publication. Library/source hashes and a build adapter that reads an
unbundled `compile_commands.json` do not establish that execution environment.
Do not substitute the current worker's configuration or reconstruct missing
receipts. This limitation is separate from the newly captured verifier-test
receipts and is recorded explicitly in `export-manifest.json`.

The public export preserves the original viewer, results, source manifest, and
ZIP byte for byte. Their text was checked for private host addresses, machine
paths, and credentials; no content redaction was required. Private originals and
earlier evidence remain separate. `export-manifest.json` identifies this export;
`original-evidence-manifest.json` identifies the historical source bundle.
The verifier pins the historical ZIP inventory and core artifact hashes
independently of the exported checksum tables. It is specific to this fixed
pilot, not a validator for newly generated benchmark packets.
Hashes establish artifact identity. Experimental correctness and release
readiness require their separate checks. The shipping executable is excluded; its recorded hash remains.

## Additive captures and candidate sources

The [retained broken-route capture](negative-route-check.json) is an original
134-byte worker artifact recovered read-only. Its SHA-256 is
`95da5a556322362d455b42b4724076376f54d3641b541e118c9aaa08383fcdae`.
It records exit 1, preflight-only stdout, and the preflight failure on stderr.
The verifier checks these contents and the absence of timing rows. This recovered
file corroborates the historical control; it does not establish prospective
crash-safe custody for the original recorder. No control was rerun.

The [measured source snapshot](source-snapshot.zip) adds exact held C++ and Rust
candidate bytes, their ABI and context sources, the original baseline C++ file,
and the project license. `source-snapshot-manifest.json` identifies every member.
The candidate C++ and Rust hashes and the original C++ hash match the historical
measurement manifest. These source bytes were preserved privately before the
documentation work and are published for inspection, with no runtime integration
or claim of a portable rebuild. They supplement the unchanged original ZIP.

## Source bundle and dependencies

The ZIP contains the executed driver, symbolic driver template, pinned
nanobench v4.6.0 header, original and repaired recorders, recorder check,
build adapter, original README, results, source manifest, and viewer. The header
retains its complete MIT license and copyright notice. Project-derived source
remains subject to the repository's license. The historical manifest records
source, executable, archive, and linked-library hashes.

Inspect these sources as evidence. The archived adapter depends on an existing
configured Linux native/Rust checkout and the held cryptoread candidate; it is
not a clean-checkout reproduction command. The archived recorders predate the
current shared-worker admission and fixed-lock procedures and are not supported
launchers. Do not run them as part of viewing or verifying this export. A future
reproduction needs its own prospective plan, reviewed source/build lineage,
correctness checks, and the scheduling owner's bounded admission under
[the evidence workflow](../../docs/EVIDENCE_WORKFLOW.md) and
[benchmark procedures](../../docs/BENCHMARK_AGENT_PROCEDURES.md).

This publication changes no runtime, workflow, provider behavior, or deployment.
It grants no new benchmark admission and releases no performance hold.
