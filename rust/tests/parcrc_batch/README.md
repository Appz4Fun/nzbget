# PAR success CRC caller validation

Status: HOLD. The final full caller is about 14-15% slower than the production
loop for three 512-byte blocks and about 18% slower than optimized C++; four
512-byte blocks also regress against optimized C++. Large-packet gains do not
qualify this prototype for integration. Keep it as evidence; do not land it.

The candidate folds the little-endian CRC bytes in contiguous PAR2 verification
entries. It keeps first-block initialization, empty results, zero-length
behavior, uint32 block-length truncation, ordering and CRC representation.
C++ retains packet loading/ownership, zero-padding, diagnostics and comparison.
The candidate obtains the uniform length operator through the existing public
`crc::combine(1 << 31, 0, blocksize)` primitive and applies it to each subsequent
CRC. The first CRC initializes directly, and a zero block length ignores later
CRCs exactly as the existing primitive does. Packets of at most two blocks keep
the direct C++ loop to avoid batch setup costs. This is precomputation and ABI
batching; it does not establish a language-specific speed advantage.

`reference.inc` contains the unmodified fold from commit
`c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e`. It already calls the existing Rust
`Crc32::Combine` port. `run.py` extracts the candidate fold directly from the
current daemon source, so the harness includes its descriptor construction and
fallback rather than a hand-written approximation. The C++ control computes
zlib's length operator once per fold and applies the polynomial inline.

The tests include loaded repository PAR2 packets, ordered arbitrary CRCs,
uint32 length truncation, zero blocks/lengths, concatenated data with a padded
last block, unaligned LE byte fixtures and a protected page between CRCs.
ASan/UBSan instrument the C++ reference/candidate/control caller; the linked
release Rust library is not sanitizer-instrumented. The protected-page test
checks Rust reads independently of that limitation. Forged non-null pointers,
misaligned output pointers or falsely advertised allocations violate the ABI
contract and are excluded from the parity corpus.

Use the remote task directory and PATH `/home/allen/.cargo/bin`. Build/test
stages acquire `/tmp/i7-heavy.lock`, then shared
`/tmp/nzbget-rust-benchmark.lock`. Following the controller's final lock protocol,
prebuilt timing stages acquire only exclusive benchmark lock and never compile
or request the heavy lock while holding it.

```
CARGO_BUILD_JOBS=3 CARGO_TARGET_DIR=$PWD/target cargo test --release --locked --manifest-path rust/Cargo.toml
CARGO_BUILD_JOBS=3 CARGO_TARGET_DIR=$PWD/target cargo build --release --locked --manifest-path rust/Cargo.toml
python3 rust/tests/parcrc_batch/run.py --build "$PWD/build" --rust-lib "$PWD/target/release/libnzbget_rs.a" --out "$PWD/caller"
python3 rust/tests/parcrc_batch/mutations.py
```

Under the exclusive timing locks, run `caller/release bench > samples.csv` and
`python3 rust/tests/parcrc_batch/summarize.py samples.csv`. The benchmark creates
the already-loaded packet outside timing for every variant, then times the
complete fold caller (packet access, conversion/descriptor, FFI, folding,
result and equality). No candidate allocation is hidden: it allocates none.
It alternates old/Rust/control and control/Rust/old for 31 paired samples. Full-body timing also includes the minimum eligible batch sizes 3, 4 and 8.
Each old calibration sample targets at least 20 ms. Summary intervals are
95% bootstrap intervals of the median paired percentage change, not guarantees
about future daemon workloads. Saved raw samples are the primary evidence.

Bencher's `parcrc_batch/` cases retain Rust ABI descriptor/validation/fold costs
for empty, one, 3, 4, 8, 16, 1024 and 32768 blocks; they are not a replacement for the C++
full-caller comparison or the daemon integration tests.


`full-caller/release full-bench` times the complete release
`VerifySuccessDataFile` body, including its unchanged CRC zero-padding,
`std::string` filename copy/destruction and boolean comparison. `run.py` copies
the candidate body from the daemon and uses `reference-full.inc` for the exact
old body; the C++ control changes only the block fold. Real PAR2 main, source,
verification and disk objects supply the getters. Fixture subclasses initialize
main/disk metadata outside timing; a small fixture engine view supplies the
same main-packet pointer lookup. No file is created/opened inside the timing.
The pre-existing filename allocation is timed for all three variants.

The cropped fold and full-body measurements are both retained. On this Ubuntu
compiler the candidate's CRC-output pointer triggers stack protection in the
cropped helper, while the complete old body already has a stack canary due to
its filename local. Disassembly is retained to substantiate that difference;
the cropped tiny-path regressions are not discarded or waived. Full-body
parity also covers true/false equality and independently computed CRCs for
short files requiring zero-padding. Release logging uses the same disabled
`debug` macro as the daemon build.
