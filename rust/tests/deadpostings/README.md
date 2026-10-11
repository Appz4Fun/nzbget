# Dead-posting state loader Rust boundary

Only persisted-line parsing crosses into Rust. C++ retains mutexes, file I/O,
owned record vectors, pruning, IsDead/SameSketch and atomic state writes. The
complete existing C++ loader is retained when Rust is disabled. This path runs
when dead-posting state is loaded; it does not improve article download or
post-processing throughput.

The callback receives one complete sorted/deduplicated sketch and the original
signed timestamp, with the target unsigned-long width's conversion semantics.
The original reader ignores numeric errno; its saturation, current-libc LC_CTYPE whitespace,
signs, NUL termination and trailing delimiters are preserved. One invalid hash
rejects the complete record, never a partially appended sketch.

## Matched full Load measurements

Linux native harness extracts the immutable C++ Load/Prune bodies from
2f0840a2 and the current Rust-enabled caller from source. It links the actual
CMake Release Rust archive: Rust 1.99.0, opt-level 3, LTO, one codegen unit and
panic=abort. Both C++ wrappers use g++ -O3 -DNDEBUG -fPIC -std=c++17 in one
binary. Fixed synthetic clock, 64-hash input records with periodic expired
entries, identical fixtures and observable digest of every retained field.
Timing includes construction, file read, parse/sort/allocation, existing C++
prune, checksum and destruction. File generation is outside timing.

Each row has three native process runs with 15 alternating paired rounds each,
pinned to CPU 2. A system-temporary i7-heavy.lock is acquired exclusively before the shared
benchmark lock for heavy validation/build stages; each bounded timing process
holds only the benchmark-exclusive lock, released between processes. Values are medians
on the shared benchmark host, not universal latency promises. The change column
is the ratio of the Rust and C++ medians; raw paired ratios are also retained.

| Input records | Retained after pruning | C++ | Rust | Change | Rust faster pairs |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 (unchanged control) | 0 | 2.830 us | 2.856 us | +0.91% | 21/45 |
| 1 (expired) | 0 | 7.071 us | 5.379 us | -23.93% | 45/45 |
| 1 (nonexpired) | 1 | 12.517 us | 8.674 us | -30.70% | 45/45 |
| 10 | 9 | 40.655 us | 23.927 us | -41.15% | 45/45 |
| 1,000 | 923 | 4.721 ms | 2.292 ms | -51.45% | 45/45 |
| 10,000 | 9,230 | 48.434 ms | 23.643 ms | -51.19% | 45/45 |

The additional nonexpired singleton uses the same unchanged prebuilt driver
and production release archive, preserving all 63 sorted unique hashes and
the complete record digest. All 45 paired samples are faster; process-median
changes span -31.04% to -30.35%. Its raw results are retained separately.

The original one-record fixture expires and retains no record; its measurement
covers read/parse/sort/prune but not a retained record.
The empty control never calls Rust; its +0.91% median difference is
file-I/O/timing variation rather than added FFI work. No statistical
significance claim is made for that control. Every nonempty paired sample
and every nonempty process median is faster. Process-median changes:
0 records -0.80% to +1.59%; 1 records -25.52% to -23.24%; 10 records -41.98% to -41.22%; 1,000 records -52.35% to -51.20%; 10,000 records -51.99% to -50.47%.

## Replay

From the repository root after a Release CMake build:

```sh
python3 rust/tests/deadpostings_cpp_differential.py --library   build/rust/Release/x86_64-unknown-linux-gnu/release/libnzbget_rs.a   --artifacts evidence/deadpostings-release --benchmark
python3 rust/tests/deadpostings_cpp_differential.py --library   build/rust/Release/x86_64-unknown-linux-gnu/release/libnzbget_rs.a   --artifacts evidence/deadpostings-sanitizer --sanitize
python3 rust/tests/deadpostings_mutations.py --artifacts evidence/deadpostings-mutations
```

Artifact directories must be new: the runners refuse to overwrite evidence.
Metadata contains source/library/driver/fixture/raw-sample hashes. The complete
output differential covers 81,832 records, including 40,000 additional valid
records so rejection cases do not dominate coverage. Sanitizer mode instruments
the C++ adapter/reference with ASan/UBSan; the supplied Rust release archive is
not sanitizer-instrumented. Rust unit cases explicitly cover 32-bit unsigned
long behavior; these Linux results do not claim native Windows runtime coverage.
Four semantic mutants cover omitted sorting/dedup, accepting numeric tails and
rejecting the original timestamp-saturation behavior. A native public-API
regression checks that loaded fields survive the next atomic Save correctly.

Locale compatibility replay uses an isolated valid ISO-8859-1 LC_CTYPE fixture
with additional byte0xA0 whitespace, plus C/C.UTF-8/en_US.UTF-8 controls. It does
not alter the host or production locale. All 2,819 complete records match C++
in each of the four locale runs (11,276 comparisons total). The production parser queries libc for
leading whitespace with an unsigned-byte argument; native test streams are
closed before removal for Windows sharing compatibility.

```sh
python3 rust/tests/deadpostings_locale.py --library \
  build/rust/Release/x86_64-unknown-linux-gnu/release/libnzbget_rs.a \
  --artifacts evidence/deadpostings-locale
```
