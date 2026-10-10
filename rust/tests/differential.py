#!/usr/bin/env python3
"""Compare the Rust C ABI with the exact pre-port C++ encoder bodies.

Run from any directory: python3 rust/tests/differential.py
Requires git, cargo and a C++ compiler. Generated files live in a temp directory.
"""
import os
import re
import shlex
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "78dcb938"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


old = subprocess.check_output(
    ["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True
)
bodies = []
for name in ("JsonEncode", "XmlEncode"):
    start = old.index(f"CString WebUtil::{name}(const char* raw)")
    end = old.index("\n}\n", start) + 3
    bodies.append(old[start:end])

# This stand-in supplies only the allocation interface used by the old bodies.
# The encoder code itself is extracted verbatim, not reimplemented in the test.
harness = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "nzbget_rs.h"
using uchar = unsigned char;
using uint32 = uint32_t;
struct CString {
    std::vector<char> bytes;
    void Reserve(int n) { bytes.resize(static_cast<size_t>(n) + 1); }
    operator char*() { return bytes.data(); }
};
struct WebUtil {
    static CString JsonEncode(const char*);
    static CString XmlEncode(const char*);
};
'''
harness += "\n".join(bodies)
harness += r'''
static size_t cases = 0;
static void check(const std::string& input) {
    for (bool xml : {false, true}) {
        CString expected = xml ? WebUtil::XmlEncode(input.c_str()) : WebUtil::JsonEncode(input.c_str());
        NzbgetRsBuf actual = xml ? nzbget_rs_xml_encode(input.c_str()) : nzbget_rs_json_encode(input.c_str());
        size_t len = std::strlen(expected);
        if (!actual.data || actual.len != len || actual.cap <= len ||
            std::memcmp(actual.data, expected, len + 1)) {
            std::fprintf(stderr, "%s mismatch for input:", xml ? "XML" : "JSON");
            for (unsigned char b : input) std::fprintf(stderr, " %02x", b);
            std::fprintf(stderr, "\n");
            std::abort();
        }
        nzbget_rs_free(actual);
    }
    ++cases;
}
int main() {
    check("");
    for (int a = 0; a < 256; ++a) {
        check(std::string{char(a)});
        for (int b = 0; b < 256; ++b) check(std::string{char(a), char(b)});
    }
    for (int a = 0xe0; a <= 0xef; ++a)
        for (int b = 0x80; b <= 0xbf; ++b)
            for (int c = 0; c < 256; ++c)
                check(std::string{char(a), char(b), char(c)});
    for (int a = 0xf0; a <= 0xf7; ++a)
        for (int b = 0x80; b <= 0xbf; ++b)
            for (int c = 0; c < 256; ++c) {
                check(std::string{char(a), char(b), char(c)});
                for (int d : {0, 1, 0x3f, 0x40, 0x7f, 0x80, 0xbf, 0xc0, 0xff})
                    check(std::string{'x', char(a), char(b), char(c), char(d), 'y'});
            }
    uint32_t state = 0x12345678;
    auto next = [&] { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; };
    for (int trial = 0; trial < 200000; ++trial) {
        std::string input(next() % 128, '\0');
        for (char& b : input) b = char(next());
        check(input);
    }
    std::printf("%zu inputs matched for both JSON and XML (reference 78dcb938)\n", cases);
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-rust-differential-") as tmp:
    tmp = Path(tmp)
    cargo = run("cargo", "rustc", "--lib", "--release", "--locked", "--target-dir",
                str(tmp / "target"), "--", "--print", "native-static-libs",
                cwd=ROOT / "rust", capture_output=True, text=True)
    native_libs = shlex.split(re.search(
        r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr
    ).group(1))
    source = tmp / "differential.cpp"
    source.write_text(harness)
    binary = tmp / "differential"
    run(*shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-O1", "-g",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        "-I", str(ROOT / "rust/include"), str(source),
        str(tmp / "target/release/libnzbget_rs.a"), *native_libs, "-o", str(binary))
    run(str(binary))
