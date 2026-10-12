# Latin1 caller conversion

The candidate writes Latin1 conversion directly into one C++-owned CString allocation. The old Rust-owned compatibility API remains unchanged. Eight-byte SSSE3 blocks use runtime feature detection, with the portable scalar fallback preserving the same bytes. There is no JSON optimization.

## Complete caller matrix

Baseline: c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e. Times are ns/call: median of nine process medians, each with 21 alternating C++/Rust rounds. Negative changes mean faster. Four JSON rows are unchanged controls; only Latin1 is changed.

| Fixture | C++ | Default Rust caller | Candidate | Paired vs C++ (95% CI) | Paired vs default (95% CI) |
|---|---:|---:|---:|---:|---:|
| JSON ASCII name, actual CString | 108.45 | 110.85 | 110.68 | +1.86% [+1.48, +2.08] | +0.19% [-3.11, +1.23] |
| JSON accented title, actual CString | 472.86 | 400.60 | 396.55 | -16.53% [-17.11, -14.05] | -0.06% [-2.86, +11.72] |
| JSON4KiB, actual CString | 6796.88 | 5658.17 | 5621.15 | -16.74% [-17.04, -15.58] | -0.36% [-3.59, +3.01] |
| JSON64KiB, actual CString | 104365.88 | 121734.12 | 124876.65 | +16.29% [+14.72, +19.59] | +0.06% [-3.01, +4.63] |
| Latin1 name, actual CString | 32.96 | 86.29 | 31.22 | -5.37% [-6.64, -4.64] | -63.84% [-64.69, -62.12] |

Latin1 is 5.366% faster than C++ (descriptive 95% interval 4.640–6.636%) and 63.838% faster than the current-default Rust caller (62.115–64.690%) on this fixture and host. This replaces the earlier 13.6% embedded-glue result. JSON ASCII and JSON 64 KiB remain slower than C++ controls; neither is claimed to pass a replacement gate.

All three C++ entry variants use equivalent shared-object calls. Default/candidate invoke their exact WebUtil wrappers in separate translation units. One identical driver object is linked to each Rust provider. Every provider binds defined functions locally, so internal Rust FFI calls are direct. The pre-port C++ bodies are unchanged from 78dcb938, with fixed placement and one reference provider reused. Production static linking can have different placement and call costs. Intervals describe observed variation and exclude systematic compiler/layout bias.

C++ comparisons pair each candidate round's observations; default comparisons pair before/after process medians. A percentile bootstrap resamples whole process pairs: nine pairs, 20,000 draws, seed 5c9e5af5. Rounds are not treated as independent. Raw files include timestamps and compiler-process inventories; none was observed at admission. CPU 2, idle scheduling, nice 19 and the exclusive common lock were used per process. Fixtures/call counts are identical. Allocations, complete conversion and destruction are timed; equality checks run outside timers. Shared-object calls prevent driver folding of known results.

## Prior controls and uncertainty

The C++-normalized Latin1 change versus default is -63.764%, interval [-64.484%, -62.929%]. Unchanged accented JSON has a normalized +4.960% interval [+0.524%, +6.777%], while its direct comparison includes zero. This exposes layout/control uncertainty, without a JSON optimization claim. Both C++ before/after controls and every normalized result are in evidence/latin-whole-summary.json.

The original min-only stand-in/inlined Latin control is retained: median C++ 26.2 ns, candidate 25.8 ns, about a 1.5% margin across three trials. Raw-sample instrumentation changes that generated timer's layout: min-only C++ median 30.6 ns, candidate 26.0 ns. Its larger apparent gain is not a production claim. Original rows, embedded-glue trials and retired mixed-candidate rows remain in evidence/prior. Mixed JSON 4 KiB was rejected for a roughly 12% Rust regression, and JSON was restored exactly to default. The historical decoder 49.3% claim was withdrawn after a control-placement audit; no decoder change/claim is included.

## Correctness and ownership

CString Reserve(bound) allocates bound + 1 actual bytes; NUL defines Length. C++ establishes first-NUL length once and reserves at most 2 * input length plus NUL, retaining ownership. Rust accepts uninitialized caller storage, checks null/empty inputs, arithmetic/endpoints and overlap including source NUL before borrows, and never allocates/frees output. Insufficient capacity returns required length; retry uses length + 1. SIZE_MAX is rejection, never retry. Length/Empty/Append/move and ownership are checked. Invalid UTF8 remains Latin1 bytes.

Fresh scoped gates: text differential signedness/locale/sanitizer configurations each matched 1,600,000 inputs; nine extracted Rust ASan tests passed; 10/10 compiled Rust mutations and 2/2 CPP mutations were caught. Actual CString ASan/UBSan and optimized checks passed 50,000 random inputs plus boundaries, capacity, nulls, int overflow and SIZE_MAX rejection. CTest passed 11/11; Rust-disabled Util.cpp compiled. After inheriting fresh default: 211 release tests passed, one ignored, one integration passed; Clippy with denied warnings, archives, ports benchmark compile and CMake passed. The five runtime files are byte-identical to the reviewed snapshot.

Independent Astra/high review of runtime patch 5c9e5af53f1c108114db050892259d7f6a26cc7df17dee1bdab43893b76532b2 returned CLEAN. Runtime manifest SHA256: 30c54ba5f0b8d6897dba7da23b9f3efc4ca25bb8769c34e91efa9e755341cf5f. Evidence contains raw samples, fixture hashes, archive/binary hashes and source/artifact manifests.

## Reproduce

Use Linux with the crate MSRV, cached Cargo dependencies, GNU-compatible C++/ld, chrt, nice, flock and taskset. Configure a Release CMake build with Rust enabled, providing build/CMakeFiles/libnzbget.dir/flags.make. From the repository root:

    python3 rust/tests/latin1_caller/run.py --baseline c2316ef5 --build-dir build --output rust/tests/latin1_caller/artifacts --cpu 2 --trials 9

The tool archives baseline Rust, builds both archives/providers with at most three Cargo jobs, and writes every round and deterministic statistics. It runs offline conversion kernels only. --emit-only generates caller sources without builds/timing. Syntax/help checks and byte-for-byte equality of its four emitted C++ sources against the measured recipe passed; no extra timing run was needed.

Summary JSON retains per-process statistics; every per-round sample remains unmodified in the current/prior logs. Duplicate raw arrays are omitted from the summary for readability.

The immutable runtime patch is losslessly stored as evidence/reviewed-runtime.patch.b64 to preserve required diff-context whitespace. Decode it with base64 -d; its SHA256 remains 5c9e5af53f1c108114db050892259d7f6a26cc7df17dee1bdab43893b76532b2.

Builds acquire i7-heavy.lock exclusively, then nzbget-rust-benchmark.lock shared, both under the process temporary directory. Prebuilt timing uses only the benchmark lock exclusively and never acquires the heavy lock or compiles.

Use a fresh output directory: a nonempty or symlinked default baseline directory is rejected before extraction, preserving existing user output. Relative output paths are resolved internally before subprocess cwd changes. Runtime patch hashing pins eight-character indexes and disables color/external diff/text conversion. Focused reproducibility tests run with compiler/timing commands mocked: python3 rust/tests/latin1_caller/test_runner.py.
