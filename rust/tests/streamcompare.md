# RequiredCompareFloor qualification

Reference: `c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e`. The reference include
contains the exact TotalSize, SubtractCovered, RequiredCompareFloor,
BaseCompareFloor and RangesIntersect bodies, with only the class name changed. The reference declaration is marked noinline
so timing calls the full method directly, just as it calls the separately
compiled production method; it introduces no extra wrapper call.
The harness separately compiles the **actual** production DupeStreamRepair.cpp
adapter using the CMake integration definitions and include paths.

Run remotely (not on the development Mac), after configuring/building with
`-DCMAKE_BUILD_TYPE=Release -DENABLE_TESTS=ON`:

```
python3 rust/tests/streamcompare_differential.py build --sanitize --rounds 100000
python3 rust/tests/streamcompare_differential.py build --sanitize --mutation
python3 rust/tests/streamcompare_differential.py build --sanitize --mutation-threshold
python3 rust/tests/streamcompare_differential.py build --tag timing --rounds 100000
# After compilation/parity ends, run the prebuilt timer under benchmark EX alone.
taskset -c 0 evidence/release-timing/caller bench > evidence/release-timing/raw.csv
python3 rust/tests/streamcompare_analyze.py evidence/release-timing/raw.csv
```

Compilation/tests acquire exclusive `/tmp/i7-heavy.lock`, then shared
`/tmp/nzbget-rust-benchmark.lock`. Release both after that bounded stage.
Prebuilt timers acquire exclusive `/tmp/nzbget-rust-benchmark.lock` alone;
never compile or acquire the heavy lock while holding that timing lock.
Use Cargo build jobs 3 and CMake `-j3` maximum. The recorded qualification
runs predate this final coordinator refinement: they acquired heavy EX first,
then benchmark EX for their bounded compile/timing stage, which was the active
protocol at the time. Their prebuilt binaries remain available for replay.

No-probe calls retain the exact C++ base-only calculation to avoid an FFI
regression. Selected probes with no holes sum raw donor sizes, including
negative sizes. Both candidates scan small hole lists linearly and use binary
search only for more than eight holes.

The production ABI borrows the original vector storage and returns an i64
scalar. There is no conversion allocation and no result allocation. C++ layout
assertions check size, alignment and member offsets. Non-Rust platforms retain
the original implementation.

`ComputeHoles` normally supplies sorted, disjoint positive ranges, and
`ProbeCount` is 2; `MaxProbeFetches` is 8. These patterns explain the sorted path
and two-probe benchmark cases. Unordered/overlapping holes are accepted and
merged only to count surviving bytes; the base floor uses the original raw
hole-size sum, including duplicate/overlapping holes. Duplicate probe indexes
are counted repeatedly. Negative ranges or holes use exact repeated subtraction
because reversed holes can split a range into overlapping pieces and expand
its total size. Endpoints whose addition would overflow also select exact
subtraction: the original may never evaluate them after a prior hole removes
the range. Both classifiers detect these endpoints without signed-overflow
arithmetic. Tests preserve these defined short-circuit cases. Zero-size holes can split ranges but preserve total bytes.

Invalid probe indexing and actually evaluated overflowing signed C++ arithmetic
are undefined reference inputs and excluded from the differential corpus. An
overflowing endpoint that the original never evaluates is still a defined input
and is included. Rust checks donor
indexes before reading them (invalid indexes abort in production), and uses
wrapping operations to avoid creating Rust signed-overflow panics outside the
reference arithmetic domain. Neither behavior establishes parity for undefined
C++ inputs. Pointer/count validity and lifetime remain caller obligations.

The benchmark's fair C++ control uses the same ordered-input fast path,
lower-bound search, unordered union and raw base-size sum. Reversed inputs use
the same exact subtraction with reusable buffers as Rust. All three accept and return the same C++ values, with
fresh temporary storage inside each invocation. Timings include the complete
production caller and FFI. Allocation counters wrap C++ new and the Rust
allocator's malloc/calloc/realloc calls; allocated bytes count requests, not
peak live memory. Fixed fixture construction is excluded for all candidates.
Each implementation calibrates its iteration count to at least 5 ms; 31 paired
samples rotate and reverse order. Raw samples preserve invocation order,
iteration counts, latency and allocations. Deterministic 10,000-resample
bootstrap intervals describe median paired speed ratios; these finite samples
are evidence for this host and workload, not universal performance claims.

Bencher's `streamcompare/` cases are regression metrics, not qualification by
isolated-kernel timing. A Rust language benefit must be established against the
fair optimized C++ caller; avoiding the original's allocations alone cannot
establish that benefit. Held candidates must not be deployed as performance
improvements.
