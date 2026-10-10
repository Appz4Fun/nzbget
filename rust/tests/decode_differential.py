#!/usr/bin/env python3
"""Compare the RPC request decoders (DecodeBase64, JsonDecode, JsonNextValue)
with the pre-port C++ code under ASan and UBSan.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/decode_differential.py
On 64-bit Linux, NZBGET_TEST_LARGE_BASE64=1 also checks the uint32 length
boundary using repeated mappings of a 1 MiB file (no 4 GiB physical allocation).
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "1e1a9441"


def block(source, start_marker):
    start = source.index(start_marker)
    return source[start:source.index("\n}\n", start) + 3]


old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
table = old[old.index("const static char BASE64_DEALPHABET"):]
table = table[:table.index("};") + 2]
helpers = block(old, "namespace\n{\n\t// a code point as UTF-8")
harness = r'''
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#ifdef __linux__
#include <sys/mman.h>
#include <unistd.h>
#endif
#include "nzbget_rs.h"
typedef unsigned int uint32;
'''
harness += table + "\n" + block(old, "uint32 DecodeByteQuartet(char* inputBuffer, char* outputBuffer)")
harness += helpers
harness += "struct WebUtil {\n static uint32 DecodeBase64(char*, int, char*);\n static void JsonDecode(char*);\n static const char* JsonNextValue(const char*, int*);\n};\n"
for sig in ("uint32 WebUtil::DecodeBase64(char* inputBuffer, int inputBufferLength, char* outputBuffer)",
            "void WebUtil::JsonDecode(char* raw)",
            "const char* WebUtil::JsonNextValue(const char* jsonText, int* valueLength)"):
    harness += block(old, sig)
harness += r'''
static unsigned state = 0x51ed2701;
static unsigned next() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; }
static void fail(const char* what, const std::string& in) {
    std::fprintf(stderr, "mismatch %s:", what);
    for (unsigned char c : in) std::fprintf(stderr, " %02x", c);
    std::fprintf(stderr, "\n");
    std::abort();
}
static void check(const std::string& in, bool base) {
    if (base) {
        // Compare all storage, including bytes beyond the returned length.
        std::vector<char> a(in.begin(), in.end()), b = a, oa(in.size() + 1, '\x55'), ob = oa;
        a.push_back(0); b.push_back(0);
        for (int length : {0, -1, (int)in.size()}) {
            uint32 n1 = WebUtil::DecodeBase64(a.data(), length, oa.data());
            uint32 n2 = nzbget_rs_decode_base64(b.data(), length, ob.data());
            if (n1 != n2 || oa != ob) fail("base64", in);
        }
        int len = in.empty() ? 0 : (int)(next() % in.size()) + 1;
        uint32 n1 = WebUtil::DecodeBase64(a.data(), len, a.data());
        uint32 n2 = nzbget_rs_decode_base64(b.data(), len, b.data());
        if (n1 != n2 || a != b) fail("base64 in place", in);
    } else {
        std::string a = in, b = in;
        WebUtil::JsonDecode(a.data());
        nzbget_rs_json_decode(b.data());
        if (a != b) fail("JsonDecode", in);
        int l1 = -7, l2 = -7;
        const char* p1 = WebUtil::JsonNextValue(in.c_str(), &l1);
        const char* p2 = nzbget_rs_json_next_value(in.c_str(), &l2);
        if (p1 != p2 || l1 != l2) fail("JsonNextValue", in);
        std::string q = "\"" + in;
        p1 = WebUtil::JsonNextValue(q.c_str(), &l1);
        p2 = nzbget_rs_json_next_value(q.c_str(), &l2);
        if (p1 != p2 || l1 != l2) fail("JsonNextValue string", q);
    }
}
static void large_base64() {
#ifdef __linux__
    if (sizeof(size_t) <= 4 || !std::getenv("NZBGET_TEST_LARGE_BASE64")) return;
    const size_t boundary = (uint64_t)1 << 32;
    const size_t block = 1 << 20, size = boundary + (size_t)sysconf(_SC_PAGESIZE);
    FILE* backing = tmpfile();
    if (!backing) std::abort();
    std::vector<char> fill(block, '-');
    if (fwrite(fill.data(), 1, block, backing) != block || fflush(backing)) std::abort();
    char* in = (char*)mmap(nullptr, size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (in == MAP_FAILED) std::abort();
    for (size_t i = 0; i < boundary; i += block) {
        if (mmap(in + i, block, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_FIXED,
                 fileno(backing), 0) == MAP_FAILED) std::abort();
    }
    if (mmap(in + boundary, size - boundary, PROT_READ | PROT_WRITE,
             MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == MAP_FAILED) std::abort();
    memcpy(in, "YWJj", 4);
    memcpy(in + boundary, "YQ==", 5);
    // C++ truncates strlen to 4: only the initial quartet is decoded.
    char a[16] = {}, b[16] = {};
    uint32 n1 = WebUtil::DecodeBase64(in, 0, a);
    uint32 n2 = nzbget_rs_decode_base64(in, 0, b);
    if (n1 != 3 || n1 != n2 || memcmp(a, b, sizeof(a))) fail("base64 uint32 length", "4 GiB + 4");
    munmap(in, size);
    fclose(backing);
    std::puts("base64 uint32 length boundary agrees");
#endif
}
int main() {
    large_base64();
    for (const char* in : {"", "\\", "\\u", "\\u123", "\\u0000", "\\u007f", "\\u0080",
                          "\\u07ff", "\\u0800", "\\ud800", "\\udfff", "\\ud800\\udc00",
                          "\\udbff\\udfff", "\\ud800\\u123", "\\u12x4", "\"x\\", "\"x\\a",
                          " ,[{:\r\n\t\f", "}", "]", "\vfoo", "\"unterminated"}) check(in, false);
    std::string alphabet = "Aa9+/=";
    for (char a : alphabet) for (char b : alphabet) for (char c : alphabet) for (char d : alphabet)
        check(std::string({a, b, c, d}), true);
    check(std::string("YWJj\0YQ==", 9), true);
    const char* b64 = "ABCXYZabcxyz0189+/====\n\r -_.\x80\xff";
    const char* js = "\\\\\\\\\\uuu\"\"/bfnrt0123456789abcdefABCDEFdDxX \x01\xc3\xa9,:[]{}\x80";
    long cases = 0;
    for (int round = 0; round < 3000000; ++round) {
        bool base = round & 1;
        std::string in(next() % 40, '\0');
        for (char& c : in) c = base ? b64[next() % strlen(b64)] : js[next() % strlen(js)];
        check(in, base);
        ++cases;
    }
    std::printf("%ld inputs agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-decode-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--release", "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "decode.cpp"
    source.write_text(harness)
    binary = temp / "decode"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g", "-w",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(ROOT / "rust/include"),
                    str(source), str(temp / "target/release/libnzbget_rs.a"), *native, "-o", str(binary)],
                   check=True, env=env)
    subprocess.run([str(binary)], check=True, env=env)
