#!/usr/bin/env python3
"""Compare both WildMask results and captures with the verbatim pre-port C++.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/wildmask_differential.py
Builds with at most three Cargo jobs. Requires git, Cargo and an ASan C++ compiler.
Optional localedef supplies single-byte locales without changing the host locale.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "1e1a9441"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def method(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]


old = subprocess.check_output(
    ["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True
)
current = (ROOT / "daemon/util/Util.cpp").read_text()
harness = r'''
#include <algorithm>
#include <array>
#include <cctype>
#include <climits>
#include <clocale>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "nzbget_rs.h"
'''
for name in ("WildMask", "LegacyWildMask"):
    harness += f'''
struct {name} {{
    const char* m_pattern;
    bool m_wantsPositions;
    int m_wildCount = 0;
    std::vector<int> m_wildStart, m_wildLen;
    {name}(const char* p, bool want) : m_pattern(p), m_wantsPositions(want) {{}}
    bool Match(const char*);
    void ExpandArray();
}};
'''
harness += method(current, "namespace\n{\n\t// tolower of a byte as WildMask")
harness += method(current, "bool WildMask::Match(const char* text)")
harness += method(old, "void WildMask::ExpandArray()").replace("WildMask::", "LegacyWildMask::")
harness += method(old, "bool WildMask::Match(const char* text)").replace("WildMask::", "LegacyWildMask::")
harness += r'''
static size_t cases = 0;
static void check(const std::string& p, const std::string& t) {
    for (bool want : {false, true}) {
        WildMask actual(p.c_str(), want);
        LegacyWildMask expected(p.c_str(), want);
        // Repeat on the same instance, including failure and empty input.
        for (const char* text : {t.c_str(), "", "mismatch", t.c_str()}) {
            bool a = actual.Match(text), e = expected.Match(text);
            if (a != e || actual.m_wildCount != expected.m_wildCount ||
                !std::equal(actual.m_wildStart.begin(), actual.m_wildStart.end(), expected.m_wildStart.begin()) ||
                !std::equal(actual.m_wildLen.begin(), actual.m_wildLen.end(), expected.m_wildLen.begin())) {
                std::fprintf(stderr, "mismatch locale=%s want=%d p=", setlocale(LC_CTYPE, nullptr), want);
                for (unsigned char b : p) std::fprintf(stderr, "%02x ", b);
                std::fprintf(stderr, " t=");
                for (const unsigned char* c = (const unsigned char*)text; *c; ++c) std::fprintf(stderr, "%02x ", *c);
                std::fprintf(stderr, " result=%d/%d count=%d/%d\n", a, e, actual.m_wildCount, expected.m_wildCount);
                std::abort();
            }
            ++cases;
        }
    }
}
static std::vector<std::string> words(const std::string& alphabet, int depth) {
    std::vector<std::string> result{""};
    size_t start = 0, end = 1;
    for (int n = 0; n < depth; ++n) {
        for (size_t i = start; i < end; ++i)
            for (char c : alphabet) result.push_back(result[i] + c);
        start = end;
        end = result.size();
    }
    return result;
}
int main(int argc, char** argv) {
    check("*?ab", std::string(200, 'a') + 'b');
    check("?x", "ay");
    check("*?#ab*?", "123aab12");
    for (const auto& p : words("aA*?#0", 4))
        for (const auto& t : words("aA#0", 3)) check(p, t);
    unsigned state = 0x28182818;
    auto next = [&] { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; };
    for (int i = 0; i < 30000; ++i) {
        std::string p(next() % 24, '\0'), t(next() % 96, '\0');
        for (char& c : p) c = "aA*?#0bB"[next() % 8];
        for (char& c : t) c = "aA*?#0bB"[next() % 8];
        check(p, t);
    }
    // Switch after first use, and test every byte pair in each locale.
    for (int l = 1; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) std::abort();
        for (int p = 1; p < 256; ++p)
            for (int t = 1; t < 256; ++t) check(std::string(1, char(p)), std::string(1, char(t)));
        std::printf("locale %s passed\n", argv[l]);
    }
    std::printf("%zu matches and capture lists agree (reference 1e1a9441)\n", cases);
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-wildmask-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/tr_TR").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        for name, source, charset in [("en_US.ISO8859-15", "en_US", "ISO-8859-15"),
                                      ("tr_TR.ISO8859-9", "tr_TR", "ISO-8859-9")]:
            run("localedef", "--no-archive", "-i", source, "-f", charset, str(locdir / name))
            locales.append(name)
    cargo = run("cargo", "rustc", "--lib", "--release", "--locked", "--target-dir",
                str(temp / "target"), "--", "--print", "native-static-libs",
                cwd=ROOT / "rust", env=env, capture_output=True, text=True)
    native_libs = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "differential.cpp"
    source.write_text(harness)
    for char_flag in ("-fsigned-char", "-funsigned-char"):
        binary = temp / "differential"
        run(*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", char_flag,
            "-I", str(ROOT / "rust/include"), str(source),
            str(temp / "target/release/libnzbget_rs.a"), *native_libs, "-o", str(binary), env=env)
        run(str(binary), *locales, env=env)
