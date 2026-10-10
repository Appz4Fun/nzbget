#!/usr/bin/env python3
"""Compare Util's string helpers (rust/src/util.rs) with the pre-port C++:
FormatSize, FormatSpeed, AlphaNum, HashBJ96, ReduceStr and MatchFileExt
(with the Tokenizer and WildMask it uses), with signed and unsigned char.

Builds with ASan and UBSan run in the C locale only: ASan replaces strcasecmp
with ASCII folding. Builds without them compare MatchFileExt in several
locales.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/util_differential.py
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "6fb9189c"


def block(source, marker):
    start = source.index(marker)
    return source[start:source.index("\n}\n", start) + 3]


old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
# WildMask was ported before REFERENCE: its C++ from the commit before
old_wildmask = subprocess.check_output(["git", "show", "1e1a9441:daemon/util/Util.cpp"], cwd=ROOT, text=True)
harness = r'''
#include <cctype>
#include <cinttypes>
#include <climits>
#include <clocale>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <strings.h>
#include <vector>
#include "nzbget_rs.h"
typedef int64_t int64;
typedef uint32_t uint32;
typedef uint8_t uint8;
struct CString {
    char* m_data = nullptr;
    CString() {}
    CString(const char* s) { Set(s); }
    CString(CString&& o) noexcept { m_data = o.m_data; o.m_data = nullptr; }
    ~CString() { free(m_data); }
    CString& operator=(const char* s) { Set(s); return *this; }
    operator char*() const { return m_data; }
    int Capacity() const { return 0; }
    void Set(const char* s, int len = 0) { if (len <= 0) len = strlen(s); m_data = (char*)realloc(m_data, len + 1); memcpy(m_data, s, len); m_data[len] = 0; }
    void Format(const char* f, ...) { char b[200]; va_list ap; va_start(ap, f); vsnprintf(b, sizeof b, f, ap); va_end(ap); Set(b); }
};
template <int size> struct BString {
    char m_data[size] = "";
    int Capacity() const { return size - 1; }
    void Set(const char* s) { strncpy(m_data, s, size - 1); m_data[size - 1] = 0; }
    operator char*() { return m_data; }
};
struct Util {
    static CString FormatSize(int64); static CString FormatSpeed(int64); static bool AlphaNum(const char*);
    static uint32 HashBJ96(const char*, int, uint32); static char* ReduceStr(char*, const char*, const char*);
    static bool MatchFileExt(const char*, const char*, const char*);
    static void TrimRight(char*); static char* Trim(char*);
};
class Tokenizer {
public:
    Tokenizer(const char* dataString, const char* separators);
    char* Next();
private:
    BString<1024> m_shortString;
    CString m_longString;
    char* m_dataString;
    const char* m_separators;
    char* m_savePtr = nullptr;
    bool m_working = false;
};
class WildMask {
public:
    WildMask(const char* pattern, bool wantsPositions = false) : m_pattern(pattern), m_wantsPositions(wantsPositions), m_wildCount(0) {}
    bool Match(const char* text);
private:
    typedef std::vector<int> IntList;
    CString m_pattern; bool m_wantsPositions; int m_wildCount; IntList m_wildStart; IntList m_wildLen;
    void ExpandArray();
};
'''
start = old.index("#define mix(a,b,c)")
harness += old[start:old.index("\n}\n", old.index("uint32 hash(uint8 *k")) + 3]
for sig in ("CString Util::FormatSize(int64 fileSize)", "CString Util::FormatSpeed(int64 bytesPerSecond)",
            "bool Util::AlphaNum(const char* str)", "uint32 Util::HashBJ96(const char* buffer, int bufSize, uint32 initValue)",
            "char* Util::ReduceStr(char* str, const char* from, const char* to)",
            "bool Util::MatchFileExt(const char* filename, const char* extensionList, const char* listSeparator)",
            "void Util::TrimRight(char* str)", "char* Util::Trim(char* str)",
            "Tokenizer::Tokenizer(const char* dataString, const char* separators)", "char* Tokenizer::Next()",
            ):
    harness += block(old, sig) if sig.startswith("Tokenizer::Tokenizer") else block(old, sig + "\n{")
for sig in ("void WildMask::ExpandArray()", "bool WildMask::Match(const char* text)"):
    harness += block(old_wildmask, sig + "\n{")
harness += r'''
static int CaseFold(int byte) { return tolower(byte); }
static int MaskFold(int byte) { int ch = static_cast<char>(byte); return tolower(ch); }
static unsigned long long state = 0x1234567890abcdefull;
static unsigned next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return (unsigned)state; }
static std::string rnd(const char* a, int max) { std::string s(next() % max, '\0'); for (char& c : s) c = a[next() % strlen(a)]; return s; }
static std::string take(NzbgetRsBuf b) { std::string s(b.data, b.len); nzbget_rs_free(b); return s; }
static void fail(const char* what, const std::string& a) { std::fprintf(stderr, "mismatch %s (locale %s): [%s]\n", what, setlocale(LC_CTYPE, nullptr), a.c_str()); std::abort(); }
int main(int argc, char** argv) {
    long cases = 0;
    // sizes and speeds: every threshold +-2, powers, random values, extremes
    std::vector<int64> v = {0, 1, -1, 1000, 1001, INT64_MAX, INT64_MIN, (int64)1 << 40};
    for (int64 t : {1000ll, 1024ll * 1000, 1024ll * 1024 * 1000, 1024ll * 1024, 10ll * 1024 * 1024, 100ll * 1024 * 1024,
                    1024ll * 1024 * 1024, 10ll * 1024 * 1024 * 1024, 100ll * 1024 * 1024 * 1024})
        for (int d = -2; d <= 2; ++d) v.push_back(t + d);
    for (int i = 0; i < 500000; ++i) {
        int64 x = ((int64)next() << 32 | next()) >> (next() % 64);
        v.push_back(i & 1 ? -x : x);
    }
    for (int64 x : v) {
        if (std::string(Util::FormatSize(x).m_data) != take(nzbget_rs_format_size(x))) fail("FormatSize", std::to_string(x));
        if (std::string(Util::FormatSpeed(x).m_data) != take(nzbget_rs_format_speed(x))) fail("FormatSpeed", std::to_string(x));
        ++cases;
    }
    for (int i = 0; i < 300000; ++i) {
        std::string s = rnd("aZ09-_.\xe9 ", 40);
        if (Util::AlphaNum(s.c_str()) != (nzbget_rs_alpha_num(s.c_str()) != 0)) fail("AlphaNum", s);
        uint32 init = next();
        int len = s.size();
        if (Util::HashBJ96(s.c_str(), len, init) != nzbget_rs_hash_bj96(s.c_str(), len, init)) fail("HashBJ96", s);
        std::string r = rnd("TF|()-x", 30), from = rnd("TF|()-", 3), to = from.substr(0, from.empty() ? 0 : next() % from.size());  // shorter, as all callers (an equal one looped forever)
        if (!from.empty()) {
            std::string a = r, b = r;
            Util::ReduceStr(a.data(), from.c_str(), to.c_str());
            nzbget_rs_reduce_str(b.data(), from.c_str(), to.c_str());
            if (strcmp(a.c_str(), b.c_str())) fail("ReduceStr", r + " " + from + " " + to);
        }
        cases += 3;
    }
    for (int l = 1; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) std::abort();
#ifdef __GLIBC__
        const int* table = reinterpret_cast<const int*>(*__ctype_tolower_loc());
#else
        const int* table = nullptr;
#endif
        for (int i = 0; i < 200000; ++i) {
            std::string f = rnd("aAiIr.0zZ\xe9\xc9\xfd", 10), list = rnd(".aAiIr0*?#, ;\t\xe9\xc9", 20);
            bool c = Util::MatchFileExt(f.c_str(), list.c_str(), ",;");
            bool r = nzbget_rs_match_file_ext(f.c_str(), list.c_str(), ",;", table, CHAR_MIN < 0, CaseFold, MaskFold) != 0;
            if (c != r) fail("MatchFileExt", f + " | " + list);
            ++cases;
        }
        std::printf("locale %s passed\n", argv[l]);
    }
    std::printf("%ld inputs agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-util-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/tr_TR").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "tr_TR", "-f", "ISO-8859-9", str(locdir / "tr_TR.ISO8859-9")], check=True)
        locales.append("tr_TR.ISO8859-9")
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--release", "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "util.cpp"
    source.write_text(harness)
    for sanitize in (True, False):
        for char_flag in ("-fsigned-char", "-funsigned-char"):
            binary = temp / "util"
            flags = ["-fsanitize=address,undefined"] if sanitize else []
            subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g", "-w", char_flag,
                            *flags, "-I", str(ROOT / "rust/include"), str(source),
                            str(temp / "target/release/libnzbget_rs.a"), *native, "-o", str(binary)], check=True, env=env)
            print("sanitizers" if sanitize else "no sanitizers", char_flag, flush=True)
            subprocess.run([str(binary), *(["C"] if sanitize else locales)], check=True, env=env)
