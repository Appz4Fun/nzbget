#!/usr/bin/env python3
"""Compare WebUtil::XmlFindTag, JsonFindField and
ParseContentDispositionFilename (rust/src/webutil.rs) with the pre-port C++
under ASan and UBSan, in several locales (strncasecmp).

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
int main(int argc, char** argv) {
    long cases = 0;
    for (int l = 1; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) std::abort();
#ifdef __GLIBC__
        const int* table = reinterpret_cast<const int*>(*__ctype_tolower_loc());
#else
        const int* table = nullptr;
#endif
        for (int i = 0; i < 300000; ++i) {
            // XmlFindTag and JsonFindField (tags up to 120 bytes: past BString<100>)
            std::string tag = (next() % 50 == 0) ? rnd("ab", 120) : rnd("ab/<>", 3);
            std::string xml = rnd("ab<>/ ", 40);
            int l1 = -7, l2 = -7;
            const char* p1 = WebUtil::XmlFindTag(xml.c_str(), tag.c_str(), &l1);
            const char* p2 = nzbget_rs_xml_find_tag(xml.c_str(), tag.c_str(), &l2);
            if (p1 != p2 || l1 != l2) fail("XmlFindTag", xml, tag);
            std::string json = rnd("ab\":, {}[]\\", 40);
            p1 = WebUtil::JsonFindField(json.c_str(), tag.c_str(), &l1);
            p2 = nzbget_rs_json_find_field(json.c_str(), tag.c_str(), &l2);
            if (p1 != p2 || l1 != l2) fail("JsonFindField", json, tag);
            // ParseContentDispositionFilename
            std::string cd = rnd("filenameFILENAME*='\"\;= \t\r\nxy%2Ez0ISO-8859-1UTF8\xe9", 48);
            if (next() % 4 == 0) cd = "attachment; filename" + std::string(next() % 2 ? "*" : "") + "=" + rnd("\"'\\%E9a ;ISO-8859-1", 24);
            CString c = WebUtil::ParseContentDispositionFilename(cd.c_str());
            NzbgetRsBuf r = nzbget_rs_content_disposition_filename(cd.c_str(), table, CaseFold);
            bool same = (!c.m_data && !r.data) || (c.m_data && r.data && strlen(c.m_data) == r.len && !memcmp(c.m_data, r.data, r.len));
            if (!same) fail("ParseContentDispositionFilename", cd, r.data ? r.data : "(null)");
            nzbget_rs_free(r);
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
    binary = temp / "webutil"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g", "-w",
                    "-fsanitize=address,undefined", "-I", str(ROOT / "rust/include"), str(source),
                    str(temp / "target/release/libnzbget_rs.a"), *native, "-o", str(binary)], check=True, env=env)
    subprocess.run([str(binary), *locales], check=True, env=env)
