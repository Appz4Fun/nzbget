#!/usr/bin/env python3
"""Compare WebUtil's text helpers (rust/src/text.rs) with the pre-port C++:
XmlDecode, XmlStripTags, XmlRemoveEntities, HttpUnquote, UrlDecode, UrlEncode
and Latin1ToUtf8, under ASan and UBSan, in several locales (isalpha) and with
signed and unsigned char.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/text_differential.py
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
#include <algorithm>
#include <cctype>
#include <clocale>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
#include "nzbget_rs.h"
typedef unsigned int uint32;
typedef unsigned char uchar;
// the C++ CString, as far as these functions use it
struct CString {
    char* p = nullptr;
    ~CString() { free(p); }
    void Reserve(int n) { p = (char*)realloc(p, n + 1); p[0] = 0; }
    operator char*() { return p; }
};
'''
harness += block(old, "namespace\n{\n\t// a code point as UTF-8")
harness += "struct WebUtil {\n static void XmlDecode(char*); static void XmlStripTags(char*); static void XmlRemoveEntities(char*);\n static void HttpUnquote(char*); static void UrlDecode(char*); static CString UrlEncode(const char*); static CString Latin1ToUtf8(const char*);\n};\n"
for sig in ("void WebUtil::XmlDecode(char* raw)", "void WebUtil::XmlStripTags(char* xml)",
            "void WebUtil::XmlRemoveEntities(char* raw)", "void WebUtil::HttpUnquote(char* raw)",
            "void WebUtil::UrlDecode(char* raw)", "CString WebUtil::UrlEncode(const char* raw)",
            "CString WebUtil::Latin1ToUtf8(const char* str)"):
    harness += block(old, sig + "\n{")
# Exercise the actual production classifier, including its platform guards.
harness += block((ROOT / "daemon/util/Util.cpp").read_text(),
                 "namespace\n{\n\t// Classify the byte")
harness += block((ROOT / "daemon/util/Util.cpp").read_text(),
                 "namespace\n{\n\t// Numeric XML references")
harness += r'''
static unsigned state = 0x7e57da7a;
static unsigned next() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; }
static void fail(const char* what, const std::string& in) {
    std::fprintf(stderr, "mismatch %s (locale %s):", what, setlocale(LC_CTYPE, nullptr));
    for (unsigned char c : in) std::fprintf(stderr, " %02x", c);
    std::fprintf(stderr, "\n");
    std::abort();
}
template <class F, class G> static void same(const char* what, const std::string& in, F c, G r) {
    std::vector<char> a(in.size() + 1), b(in.size() + 1);
    memcpy(a.data(), in.data(), in.size());
    memcpy(b.data(), in.data(), in.size());
    c(a.data()); r(b.data());
    // Compare the entire in-place buffer, including bytes after decoded NULs
    // and the untouched tail. strcmp would hide these differences.
    if (memcmp(a.data(), b.data(), in.size() + 1)) fail(what, in);
}
static void check(const std::string& in) {
    same("XmlDecode", in, WebUtil::XmlDecode, [](char* s) { nzbget_rs_xml_decode(s, XmlDigitLower); });
    same("XmlStripTags", in, WebUtil::XmlStripTags, nzbget_rs_xml_strip_tags);
    same("XmlRemoveEntities", in, WebUtil::XmlRemoveEntities, [](char* s) { nzbget_rs_xml_remove_entities(s, XmlEntityAlpha); });
    same("HttpUnquote", in, WebUtil::HttpUnquote, nzbget_rs_http_unquote);
    same("UrlDecode", in, WebUtil::UrlDecode, nzbget_rs_url_decode);
    for (int w = 0; w < 2; ++w) {
        CString c = w ? WebUtil::UrlEncode(in.c_str()) : WebUtil::Latin1ToUtf8(in.c_str());
        NzbgetRsBuf r = w ? nzbget_rs_url_encode(in.c_str()) : nzbget_rs_latin1_to_utf8(in.c_str());
        if (strlen(c.p) != r.len || memcmp(c.p, r.data, r.len + 1)) fail(w ? "UrlEncode" : "Latin1ToUtf8", in);
        nzbget_rs_free(r);
    }
}
int main(int argc, char** argv) {
    const char* alphabet = "&&&;;##xX<<>>!![[CDATA]]]\"\"\\\\%%  aAzZ09fF:/lt;gt;amp;apos;quot;\xc3\xa9\xe9\xff\x80\x01";
    long cases = 0;
    for (int l = 1; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) std::abort();
        for (const char* in : {"", "&", "&#", "&#x", "&#;", "&#x;", "&#0", "&#0;tail",
                "&#xA;", "&#xa;", "&#xAB;", "&#xD800;", "&#x10ffff;", "&#1114112;", "&#999999999999999999999999;",
                "&#xFFFFFFFFFFFFFFFFFFF;", "&lt;&gt;&amp;&apos;&quot;", "&&amp;", "&@;",
                "<![CDATA[&lt;<tag>]]>tail", "<![CDATA[unclosed", "<![CDATA[]]>",
                "<open", "<a><b>tail", "\"a\\\"b\\\\c\"tail", "\"trailing\\", "\"",
                "%", "%4", "%00tail%41", "%zztail", "a b  c"}) check(in);
        check(std::string("%00a%41\0&@;tail", 15));
        // Every possible URL escape pair, including invalid and high bytes.
        for (int a = 1; a < 256; ++a)
            for (int b = 1; b < 256; ++b)
                check(std::string("%") + char(a) + char(b) + "tail%00end");
        for (int i = 0; i < 400000; ++i) {
            std::string in(next() % 32, '\0');
            for (char& c : in) c = alphabet[next() % strlen(alphabet)];
            check(in);
            ++cases;
        }
        // every byte after '&' and before ';'
        for (int b = 1; b < 256; ++b) { check(std::string("&") + char(b) + ";"); check(std::string("&a") + char(b) + "b;"); }
        std::printf("locale %s passed\n", argv[l]);
    }
    std::printf("%ld inputs agree on all seven functions (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-text-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/en_US").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "en_US", "-f", "ISO-8859-15", str(locdir / "en_US.ISO8859-15")], check=True)
        locales.append("en_US.ISO8859-15")
        # POSIX permits additional alphabetic characters outside the C locale,
        # including ASCII punctuation. Do not assume bytes < 0x80 are invariant.
        custom = temp / "custom-locale"
        custom.write_text(Path("/usr/share/i18n/locales/en_US").read_text().replace(
            'copy "i18n"', 'alpha <U0041>..<U005A>;<U0061>..<U007A>;<U0040>\n'
            # XmlDecode also uses locale-sensitive tolower for hex letters.
            'tolower (<U0041>,<U0062>);(<U0042>,<U0061>)'))
        subprocess.run(["localedef", "--no-archive", "-i", str(custom), "-f", "ISO-8859-15",
                        str(locdir / "custom.ISO8859-15")], check=True)
        locales.append("custom.ISO8859-15")
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--release", "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "text.cpp"
    source.write_text(harness)
    for char_flag in ("-fsigned-char", "-funsigned-char"):
        binary = temp / "text"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g", "-w", char_flag,
                        "-fsanitize=address,undefined", "-I", str(ROOT / "rust/include"), str(source),
                        str(temp / "target/release/libnzbget_rs.a"), *native, "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary), *locales], check=True, env=env)
