# Porting nzbget to Rust

nzbget moves to Rust one routine at a time. The Rust code lives in `rust/` and
builds as a static library (`cmake/rust.cmake`). C++ calls it through the C ABI
in `rust/include/nzbget_rs.h`.

## Rules

- Each port matches the C++ output byte for byte, quirks included. A behavior
  change is a separate commit.
- Before each swap, a differential fuzz runs the old C++ against the Rust code.
  The C++ version remains as a fallback for platforms without Rust integration.
- Measure before and after; port the hot paths first.

## Done

| C++                      | Rust                 | Speed-up |
|--------------------------|----------------------|----------|
| `WebUtil::JsonEncode`    | `escape::json_encode`| 1.9x     |
| `WebUtil::XmlEncode`     | `escape::xml_encode` | 1.6x     |

## Next

1. Remaining `WebUtil` text routines (decoders, URL, base64, RFC 822 dates).
2. `WildMask`, `Util::MatchFileExt`, and the `Tokenizer` used by filters.
3. NZB parsing (`NzbFile`): a Rust parser behind the existing interface.
4. JSON/XML-RPC response building (`XmlRpc.cpp`), then the RPC server.
5. The download path (NNTP connection, article writer), then queue and
   post-processing. Each step leaves nzbget a working program.

## Build and verification

Native POSIX builds use Rust when Cargo, rustc, and the target standard library
are available; otherwise they retain the C++ encoders. Debug selects Cargo's dev
profile; other CMake configurations select release. Cargo is invoked on each build to track its own
sources, lockfile, build scripts, and configuration. Both the daemon and test
executable inherit the archive and Rust's native link dependencies.

Windows keeps the original C++ encoders, so its existing build does not acquire a
Rust dependency. Non-macOS cross builds also keep C++ unless a matching target is
provided with `-DNZBGET_RUST_TARGET=<triple>`. macOS selects the target from the
CMake architecture and forwards `CMAKE_OSX_DEPLOYMENT_TARGET`. Install the Rust
standard library for the chosen target to enable Rust for that architecture.
An explicit `NZBGET_RUST_TARGET` requires a working Rust toolchain and standard
library; a missing dependency is an error rather than an automatic fallback.

Run `cargo test --release` in `rust/` for encoder and FFI tests. On POSIX with a
C++ compiler supporting ASan/UBSan, run `python3 rust/tests/differential.py` from
the repository root for a deterministic comparison against the exact encoder
bodies in commit `78dcb938`. This covers arbitrary bytes, embedded NULs, invalid
continuations, truncations, and out-of-range code points.
