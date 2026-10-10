#!/usr/bin/env python3
"""Compare WebUtil::XmlFindTag, JsonFindField and
ParseContentDispositionFilename (rust/src/webutil.rs) with the pre-port C++
under ASan and UBSan, in several locales (strncasecmp). Locale comparisons
also run without ASan: its strncasecmp interceptor uses ASCII case folding.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/webutil_differential.py
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
harness = r'''
#include <cctype>
#include <clocale>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <strings.h>
#include "nzbget_rs.h"
typedef unsigned char uchar;
// nzbget's CString and BString, as far as these functions use them
struct CString {
    char* m_data = nullptr;
    CString() {}
    CString(const char* s, int len = 0) { Set(s, len); }
    CString(CString&& o) noexcept { m_data = o.m_data; o.m_data = nullptr; }
    ~CString() { free(m_data); }
    CString& operator=(CString&& o) noexcept { if (this != &o) { free(m_data); m_data = o.m_data; o.m_data = nullptr; } return *this; }
    CString& operator=(const char* s) { Set(s); return *this; }
    operator char*() const { return m_data; }
    bool Empty() const { return !m_data || !*m_data; }
    void Reserve(int n) { m_data = (char*)realloc(m_data, n + 1); m_data[0] = 0; }
    void Set(const char* str, int len = 0) {
        if (str) { if (len <= 0) len = strlen(str); char* d = (char*)realloc(m_data, len + 1); if (d) { m_data = d; strncpy(m_data, str, len); m_data[len] = 0; } }
        else { free(m_data); m_data = nullptr; }
    }
};
template <int size> struct BString {
    char m_data[size];
    BString(const char* format, ...) { va_list ap; va_start(ap, format); vsnprintf(m_data, size, format, ap); va_end(ap); }
    operator const char*() const { return m_data; }
};
struct WebUtil {
    static const char* XmlFindTag(const char*, const char*, int*);
    static const char* JsonFindField(const char*, const char*, int*);
    static const char* JsonNextValue(const char*, int*);
    static void HttpUnquote(char*);
    static void UrlDecode(char*);
    static CString Latin1ToUtf8(const char*);
    static CString ParseContentDispositionFilename(const char*);
};
'''
for sig in ("const char* WebUtil::XmlFindTag(const char* xml, const char* tag, int* valueLength)",
            "const char* WebUtil::JsonFindField(const char* jsonText, const char* fieldName, int* valueLength)",
            "const char* WebUtil::JsonNextValue(const char* jsonText, int* valueLength)",
            "void WebUtil::HttpUnquote(char* raw)", "void WebUtil::UrlDecode(char* raw)",
            "CString WebUtil::Latin1ToUtf8(const char* str)",
            "CString WebUtil::ParseContentDispositionFilename(const char* contentDisposition)"):
    harness += block(old, sig + "\n{")
harness += r'''
static int CaseFold(int byte) { return tolower(byte); }
static unsigned state = 0xc0ffee11;
static unsigned next() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; }
static void fail(const char* what, const std::string& a, const std::string& b) {
    std::fprintf(stderr, "mismatch %s (locale %s): [%s] [%s]\n", what, setlocale(LC_CTYPE, nullptr), a.c_str(), b.c_str());
    std::abort();
}
static std::string rnd(const char* alphabet, int max) {
    std::string s(next() % max, '\0');
    for (char& c : s) c = alphabet[next() % strlen(alphabet)];
    return s;
}
static void check_finders(const std::string& xml, const std::string& json, const std::string& tag) {
    int l1 = -7, l2 = -7;
    const char* p1 = WebUtil::XmlFindTag(xml.c_str(), tag.c_str(), &l1);
    const char* p2 = nzbget_rs_xml_find_tag(xml.c_str(), tag.c_str(), &l2);
    if (p1 != p2 || l1 != l2) fail("XmlFindTag", xml, tag);
    l1 = l2 = -7;
    p1 = WebUtil::JsonFindField(json.c_str(), tag.c_str(), &l1);
    p2 = nzbget_rs_json_find_field(json.c_str(), tag.c_str(), &l2);
    if (p1 != p2 || l1 != l2) fail("JsonFindField", json, tag);
}
static void check_cd(const std::string& cd, const int* table) {
    CString c = WebUtil::ParseContentDispositionFilename(cd.c_str());
    // Exercise both the glibc table and the callback used on other platforms.
    for (const int* t : {table, static_cast<const int*>(nullptr)}) {
        NzbgetRsBuf r = nzbget_rs_content_disposition_filename(cd.c_str(), t, CaseFold);
        bool same = (!c.m_data && !r.data) || (c.m_data && r.data && strlen(c.m_data) == r.len && !memcmp(c.m_data, r.data, r.len));
        if (!same) fail("ParseContentDispositionFilename", cd, r.data ? r.data : "(null)");
        nzbget_rs_free(r);
    }
}
int main(int argc, char** argv) {
    long cases = 0;
    for (int l = 1; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) std::abort();
#ifdef __GLIBC__
        const int* table = reinterpret_cast<const int*>(*__ctype_tolower_loc());
#else
        const int* table = nullptr;
#endif
        // Random short texts cannot match long names: construct hits at every
        // BString truncation boundary, including overlapping open/close tags.
        for (int n : {0, 1, 96, 97, 98, 99, 100, 120, 4096}) {
            for (char byte : {'a', '/', '"', static_cast<char>(0xff)}) {
                std::string tag(n, byte);
                for (const char* value : {"", "12", "\"x\\\"y\"", "\"x\\a", "}"}) {
                    check_finders("<" + tag + ">v</" + tag + ">", "\"" + tag + "\": " + value, tag);
                    check_finders("<" + tag + "/><" + tag + ">v</" + tag + ">", "\"" + tag + "\": " + value, tag);
                }
            }
        }
        for (const char* cd : {"filename=\"\"", "filename=\"x\\\"y\"", "filename=\"x\\",
                              "filename=x; filename*=UTF-8''%00y", "filename*=ISO-8859-1''caf%E9",
                              "filename*=UTF-8''first; filename*=UTF-8''%00; filename=last",
                              "filename*=\"UTF-8''quoted\"", "FILENAME=x", "filename*=iso-8859-1''%FF"}) {
            check_cd(cd, table);
        }
        // Force locale-sensitive comparisons, including Turkish dotted I and
        // every high byte, instead of hoping random parameter names match.
        for (int byte = 1; byte <= 255; ++byte) {
            for (int pos = 0; pos < 8; ++pos) {
                std::string name = "filename";
                name[pos] = static_cast<char>(byte);
                check_cd(name + "=x; " + name + "*=UTF-8''y", table);
            }
            for (int pos = 0; pos < 10; ++pos) {
                std::string charset = "ISO-8859-1";
                charset[pos] = static_cast<char>(byte);
                check_cd("filename*=" + charset + "''%E9", table);
            }
        }
        for (int i = 0; i < 300000; ++i) {
            // XmlFindTag and JsonFindField (tags up to 120 bytes: past BString<100>)
            std::string tag = (next() % 50 == 0) ? rnd("ab", 120) : rnd("ab/<>", 3);
            std::string xml = rnd("ab<>/ ", 40);
            std::string json = rnd("ab\":, {}[]\\", 40);
            check_finders(xml, json, tag);
            // ParseContentDispositionFilename
            std::string cd = rnd("filenameFILENAME*='\"\;= \t\r\nxy%2Ez0ISO-8859-1UTF8\xe9", 48);
            if (next() % 4 == 0) cd = "attachment; filename" + std::string(next() % 2 ? "*" : "") + "=" + rnd("\"'\\%E9a ;ISO-8859-1", 24);
            check_cd(cd, table);
            ++cases;
        }
        std::printf("locale %s passed\n", argv[l]);
    }
    std::printf("%ld inputs agree on all three functions (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-webutil-") as temp:
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
    source = temp / "webutil.cpp"
    source.write_text(harness)
    for char_mode in ("-fsigned-char", "-funsigned-char"):
        # ASan replaces strncasecmp with an ASCII comparison, which would give
        # a false oracle in e.g. Turkish. UBSan leaves libc's locale semantics
        # intact; retain ASan coverage in the C locale where they agree.
        for sanitizer, test_locales in (("address,undefined", ["C"]), ("undefined", locales)):
            binary = temp / ("webutil" + char_mode + sanitizer)
            subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g", "-w", char_mode,
                            "-fsanitize=" + sanitizer, "-fno-sanitize-recover=all", "-I", str(ROOT / "rust/include"), str(source),
                            str(temp / "target/release/libnzbget_rs.a"), *native, "-o", str(binary)], check=True, env=env)
            print(char_mode, sanitizer, flush=True)
            subprocess.run([str(binary), *test_locales], check=True, env=env)
