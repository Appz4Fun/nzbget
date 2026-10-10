#!/usr/bin/env python3
"""Compare the RPC request decoders (DecodeBase64, JsonDecode, JsonNextValue)
with the pre-port C++ code under ASan and UBSan.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/decode_differential.py
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
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
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
int main() {
    const char* b64 = "ABCXYZabcxyz0189+/====\n\r -_.\x80\xff";
    const char* js = "\\\\\\\\\\uuu\"\"/bfnrt0123456789abcdefABCDEFdDxX \x01\xc3\xa9,:[]{}\x80";
    long cases = 0;
    for (int round = 0; round < 3000000; ++round) {
        bool base = round & 1;
        std::string in(next() % 40, '\0');
        for (char& c : in) c = base ? b64[next() % strlen(b64)] : js[next() % strlen(js)];
        if (base) {
            // separate buffers, in place, and an explicit length
            std::vector<char> a(in.begin(), in.end()), b = a, oa(in.size() + 1), ob(in.size() + 1);
            a.push_back(0); b.push_back(0);
            uint32 n1 = WebUtil::DecodeBase64(a.data(), 0, oa.data());
            uint32 n2 = nzbget_rs_decode_base64(b.data(), 0, ob.data());
            if (n1 != n2 || memcmp(oa.data(), ob.data(), n1)) fail("base64", in);
            int len = in.empty() ? 0 : (int)(next() % in.size()) + 1;
            n1 = WebUtil::DecodeBase64(a.data(), len, a.data());
            n2 = nzbget_rs_decode_base64(b.data(), len, b.data());
            if (n1 != n2 || memcmp(a.data(), b.data(), n1)) fail("base64 in place", in);
        } else {
            std::string a = in, b = in;
            WebUtil::JsonDecode(a.data());
            nzbget_rs_json_decode(b.data());
            if (strcmp(a.c_str(), b.c_str())) fail("JsonDecode", in);
            int l1 = -7, l2 = -7;
            const char* p1 = WebUtil::JsonNextValue(in.c_str(), &l1);
            const char* p2 = nzbget_rs_json_next_value(in.c_str(), &l2);
            if (p1 != p2 || (p1 && l1 != l2)) fail("JsonNextValue", in);
            std::string q = "\"" + in;
            p1 = WebUtil::JsonNextValue(q.c_str(), &l1);
            p2 = nzbget_rs_json_next_value(q.c_str(), &l2);
            if (p1 != p2 || (p1 && l1 != l2)) fail("JsonNextValue string", q);
        }
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
