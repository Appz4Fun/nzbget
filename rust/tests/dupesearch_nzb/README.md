# Duplicate-search filename port validation

This bounded port replaces terminal unquoted yEnc subject parsing and PAR classification.
The existing C++ quoted-filename fast path, message-ID checks, libxml2 parsing and complete
summary/geometry construction remain in place. Rust-disabled builds keep the C++ implementation.

`caller.cpp` compiles an independent reference from commit
`2f0840a2e5d2528aca427061ad5d7778ac1e255f` beside the real Rust-enabled C++ caller.
It compares acceptance and every summary field, including donor geometry, each head,
metadata, groups, filenames and fingerprints. Required locale coverage is C, C.UTF-8,
English ISO-8859-1, Turkish ISO-8859-9 and English UTF-8. Missing locales/fixtures fail.
There are 200,000 random/generated helper cases, exhaustive byte positions and 3,007
XML summaries/mutations, including namespace, CDATA and declared-entity inputs.

The benchmark times the entire `NzbReader::Parse` call with identical synthetic XML,
matched compiler flags and observable output checksums, using the actual CMake Release
Rust archive (opt-level 3, LTO, one codegen unit). The reference and candidate share one
binary and libxml2. The eight cases include quoted/unquoted data files and PAR-only
small inputs, plus 30×10 and 100×100 file/segment workloads. Eight warm-up comparisons
precede 15 paired rounds; C++/Rust order alternates. Batch counts are 20,000 small,
500 medium and 25 large calls. Timing uses a frozen executable named by its SHA256,
pinned to CPU 2 under the shared team's exclusive benchmark lock. Builds use shared
locks. Raw samples are retained; `summarize.py` validates all cases/rounds/pairs and
reports paired-median relative changes with a percentile-bootstrap 95% interval.
An interval containing zero does not demonstrate a speed change. These measurements
are caller benchmarks on a shared Linux host, not end-to-end download throughput.

Run in an isolated GNU/Linux checkout with Rust 1.99 and configured CMake dependencies.
The reference commit must be available in Git history. From the repository root:

```sh
mkdir -p rust/tests/dupesearch_nzb/artifacts/locales
localedef --no-archive -i en_US -f ISO-8859-1 rust/tests/dupesearch_nzb/artifacts/locales/en_US.ISO8859-1
localedef --no-archive -i tr_TR -f ISO-8859-9 rust/tests/dupesearch_nzb/artifacts/locales/tr_TR.ISO8859-9
localedef --no-archive -i en_US -f UTF-8 rust/tests/dupesearch_nzb/artifacts/locales/en_US.UTF-8
python3 rust/tests/dupesearch_nzb/run.py --config-dir build --library build/rust/Release/x86_64-unknown-linux-gnu/release/libnzbget_rs.a --locales rust/tests/dupesearch_nzb/artifacts/locales --bench > rust/tests/dupesearch_nzb/artifacts/samples.csv
python3 rust/tests/dupesearch_nzb/summarize.py rust/tests/dupesearch_nzb/artifacts/samples.csv
python3 rust/tests/dupesearch_nzb/mutations.py
python3 rust/tests/dupesearch_nzb/test_evidence.py
```

Use `--sanitize` instead of `--bench` for the C++ ASan/UBSan differential; the linked
Rust archive remains the production Release archive. Use `--cpp-only` for the unchanged
C++ fallback. Both still require the complete locale/XML corpus. Mutation checks link
four deliberately broken Rust implementations against the same real caller object and
must reject incorrect part counts, PAR case folding, yEnc whitespace and trim whitespace.
Run mutations after a regular Rust-enabled build of the caller, not a fallback-only run.
The evidence tests prove that empty, omitted, duplicated, mismatched-output and nonfinite
timing data cannot produce a successful report, including with Python assertions disabled.
