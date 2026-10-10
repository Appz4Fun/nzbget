# Porting nzbget to Rust

nzbget moves to Rust one routine at a time. The Rust code lives in `rust/` and
builds as a static library (`cmake/rust.cmake`). C++ calls it through the C ABI
in `rust/include/nzbget_rs.h`.

## Rules

- Each port matches the C++ output byte for byte, quirks included. A behavior
  change is a separate commit.
- Before each swap, a differential fuzz runs the old C++ against the Rust code.
  The C++ version is deleted once the fuzz shows no mismatches.
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
