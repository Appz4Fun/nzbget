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

## Retained all-Rust native allocator timing supplement

The instrumented allocation suite is retained separately. To measure native
latency without allocator-counter overhead, compile the companion with both
C++ new/delete overrides/counters and malloc/calloc/realloc/free linker wrappers
removed. `--uninstrumented` adds a harness-only preprocessing flag; the actual
production object uses the same CMake flags and links the same Rust archive.
Allocation columns are `NA` and the analyzer reports null allocation data,
never zero allocations. Run build/parity under heavy EX then benchmark SH:

```
python3 rust/tests/streamcompare_differential.py build --uninstrumented --extended-fixtures --fixtures-only --tag native
```

After releasing both build locks, run the prebuilt timer under benchmark EX alone:

```
taskset -c 0 evidence/release-native/caller bench > evidence/release-native/raw.csv
python3 rust/tests/streamcompare_analyze.py evidence/release-native/raw.csv > evidence/release-native/summary.json
```

The extended set keeps all original ten fixtures and adds three tiny single-probe
cases (no holes with 64 bytes, one hole leaving 64 bytes, one hole leaving 63
bytes) plus medium sparse/dense geometry with 2, 4 and 8 accumulated probes.
Each medium case has 32 contiguous 800000-byte donors and 64 ordered disjoint
holes spaced 400000 bytes apart, with size 1000 or 380000. These are synthetic
representative geometries covering the fetched-batch caller's probe-count range,
not a measured production distribution. All inputs are built outside timing.
`caller fixtures` checks exact old/actual/fair results for all extended fixtures
without rerunning the already-passed exhaustive/random correctness suites.

Only empty/no-probe fixtures bypass Rust in the C++ method. In the retained all-Rust candidate, all nonempty-probe
fixtures called the actual RequiredCompareFloor method and FFI. Source and linked
ELF evidence establish VerifyDonor -> RequiredCompareFloor ->
nzbget_rs_stream_compare_floor, and an offline debugger trace can confirm FFI
reach for each fixture. VerifyDonor itself performs fetches and is not executed
by this offline benchmark; its network/disk work is outside this scoped routine's
latency. Kernel-only metrics do not qualify the conversion. A statistically
slower native complete caller against either control is a HOLD gate; an interval
spanning 1 is a tie/inconclusive result, not a demonstrated improvement.


## Fixed hybrid candidate on fresh base0dd7

The all-Rust candidate is held. One prospective hybrid candidate keeps native
C++ accounting for nonempty probes with fewer than4096 holes, and dispatches
to Rust only for at least4096 holes. No-probe calls remain base-only C++, and
no-hole calls sum raw donor sizes in C++ before the size dispatch. This boundary
was chosen from prior4096-hole native wins before any hybrid timing; no new
threshold or layout tuning is permitted. The small C++ algorithm reuses the
fair native control's geometry, raw base sum, lazy-safe unsigned endpoint
classifier, union and reusable exact subtraction buffers. SubtractCovered and
the original non-Rust RequiredCompareFloor fallback stay unchanged.

Correctness adds a route-only linker wrapper (not used for timing) which counts
calls to the actual FFI and requires0 below the boundary and1 at/above it for
nonempty probes. Its small_clear assertion failed against the held all-Rust
candidate before implementation. Boundary parity covers4095/4096/4097 with
2/4/8 probes, duplicates and reversed order, sparse/dense/unordered holes,
raw overlapping sums, zero/reversed ranges, thresholds63/64/65, base floors
16383/16384/16385, and endpoints that remain unevaluated after full coverage.
120 directed cases and128 deterministic large-hole cases complement the
existing100000 low-hole fuzz cases and3969 exhaustive cases. Both C++ and Rust
routes are exercised, rather than assuming low-hole fuzz reaches Rust.

Remote correctness replay, under heavyEX then benchmarkSH with max3 jobs:

```
python3 rust/tests/streamcompare_differential.py build --sanitize --uninstrumented --extended-fixtures --route-check --tag hybrid --rounds 100000
python3 rust/tests/streamcompare_differential.py build --sanitize --uninstrumented --extended-fixtures --fallback --tag hybrid --rounds 100000
python3 rust/tests/streamcompare_differential.py build --sanitize --uninstrumented --extended-fixtures --mutation --tag hybrid
python3 rust/tests/streamcompare_differential.py build --sanitize --uninstrumented --extended-fixtures --mutation-threshold --tag hybrid
```

Also run the C++64-to65 threshold mutation with `--mutation-cpp-threshold`;
mutations run the numeric mode, which executes CheckBoundaries before fuzz.
Route checking is rejected for fallback or timing modes. The legacy harness
implementation column `rust` means the complete candidate; in hybrid mode its
active route can be C++, as the correctness route oracle demonstrates. The independent peer
predeclared52 native full-caller cases: existing19, six large4/8-probe cases,
and27 matched4095/4096/4097 boundary sparse/dense/unordered cases with2/4/8
probes. Boundary cases keep2001 donors/decoded1600800000 across hole counts,
spacing390625, and probe indexes100+floor(i*1800/(P-1)). Below4096 measures the
active C++ route; at/above4096 measures the active Rust route. Source is frozen
and signed before independent timing and review. Production ownership stays
C++, no dependencies are removed, and the final verdict is HOLD if any
statistically resolved slowdown against original or fair optimized C++ remains.
