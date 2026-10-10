#!/usr/bin/env python3
"""Compare Crc32::Combine (rust/src/crc.rs) with the pre-port C++ (zlib's
GF(2) matrix method) on random and edge-case inputs, and time both.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/crc_differential.py
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "1e1a9441"

old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
start = old.index("/* From zlib/crc32.c")
end = old.index("\n}\n", old.index("uint32 Crc32::Combine(uint32 crc1, uint32 crc2, uint32 len2)\n{")) + 3
harness = r'''
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include "nzbget_rs.h"
typedef unsigned int uint32;
struct Crc32 { static uint32 Combine(uint32 crc1, uint32 crc2, uint32 len2); };
''' + old[start:end] + r'''
static unsigned long long state = 0x9e3779b97f4a7c15ull;
static uint32 next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return (uint32)state; }
int main() {
    const uint32 lengths[] = {0, 1, 2, 3, 4, 7, 8, 255, 256, 384000, 750000, 0x7fffffff, 0x80000000u, 0xffffffffu};
    long cases = 0;
    for (int i = 0; i < 2000000; ++i) {
        uint32 a = next(), b = next();
        uint32 len = i < 200000 ? lengths[i % (sizeof lengths / sizeof *lengths)]
                   : (i & 1) ? next() : next() % 1000000;
        if (Crc32::Combine(a, b, len) != nzbget_rs_crc32_combine(a, b, len)) {
            std::fprintf(stderr, "mismatch crc1=%08x crc2=%08x len=%u\n", a, b, len);
            return 1;
        }
        ++cases;
    }
    std::printf("%ld combinations agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
    // article-sized lengths, as ArticleWriter combines them
    uint32 sink = 0;
    auto time = [&](auto f) {
        auto t = std::chrono::steady_clock::now();
        for (int i = 0; i < 1000000; ++i) sink ^= f(sink + i, 0x12345678u + i, 750000u + (i & 1023));
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count();
    };
    double c = time(Crc32::Combine), r = time(nzbget_rs_crc32_combine);
    std::printf("1,000,000 combines: C++ %.0f ms, Rust %.0f ms (%u)\n", c, r, sink & 1);
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-crc-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--release", "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "crc.cpp"
    source.write_text(harness)
    for flags in (["-O1", "-fsanitize=address,undefined"], ["-O2"]):
        binary = temp / "crc"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-g", "-w", *flags,
                        "-I", str(ROOT / "rust/include"), str(source), str(temp / "target/release/libnzbget_rs.a"),
                        *native, "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary)], check=True, env=env)
