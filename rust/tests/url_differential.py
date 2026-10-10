#!/usr/bin/env python3
"""Compare URL::ParseUrl (rust/src/url.rs) with the pre-port C++: every
field (validity, protocol, user, password, host, resource, port) on random
and edge-case addresses, with and without ASan/UBSan (which intercepts atoi),
in several locales (isalpha, isalnum, atoi) and with signed and unsigned char.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/url_differential.py
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
new = (ROOT / "daemon/util/Util.cpp").read_text()
new_parse = new[new.index("#ifdef NZBGET_USE_RUST\nvoid URL::ParseUrl()"):]
new_parse = new_parse[len("#ifdef NZBGET_USE_RUST\n"):new_parse.index("\n#else\n") + 1]

harness = r'''
#include <cctype>
#include <clocale>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include "nzbget_rs.h"
struct CString {
    char* m_data = nullptr;
    CString() {}
    CString(const char* s) { Set(s); }
    ~CString() { free(m_data); }
    CString& operator=(const char* s) { Set(s); return *this; }
    operator char*() const { return m_data; }
    void Set(const char* str, int len = 0) {
        if (str) { if (len <= 0) len = strlen(str); char* d = (char*)realloc(m_data, len + 1); if (d) { m_data = d; strncpy(m_data, str, len); m_data[len] = 0; } }
        else { free(m_data); m_data = nullptr; }
    }
};
'''
cls = '''
class NAME {
public:
    NAME(const char* address);
    CString m_address, m_protocol, m_user, m_password, m_host, m_resource;
    int m_port = 0;
    bool m_tls = false;
    bool m_valid = false;
    void ParseUrl();
};
NAME::NAME(const char* address) : m_address(address) { if (address) ParseUrl(); }
'''
harness += cls.replace("NAME", "OldURL") + cls.replace("NAME", "URL")
harness += block(old, "void URL::ParseUrl()\n{").replace("URL::", "OldURL::")
harness += new_parse
harness += r'''
static unsigned state = 0xabcdef01;
static unsigned next() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; }
static bool same(const char* a, const char* b) { return (!a && !b) || (a && b && !strcmp(a, b)); }
int main(int argc, char** argv) {
    const char* pieces[] = {"http", "https", "h+t-t.p", "1x", "\xe9", "://", ":", "/", "@", "?", "a", "b", "host",
                            "80", "-1", " 7", "99999999999", "+5", "user", "pw", "", "\t3", "\xa0" "8"};
    long cases = 0;
    for (int l = 1; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) std::abort();
        for (int i = 0; i < 300000; ++i) {
            std::string a;
            int n = next() % 9;
            for (int k = 0; k < n; ++k) a += pieces[next() % (sizeof pieces / sizeof *pieces)];
            OldURL o(a.c_str());
            URL r(a.c_str());
            if (o.m_valid != r.m_valid || o.m_port != r.m_port || !same(o.m_protocol, r.m_protocol) ||
                !same(o.m_user, r.m_user) || !same(o.m_password, r.m_password) || !same(o.m_host, r.m_host) ||
                !same(o.m_resource, r.m_resource)) {
                std::fprintf(stderr, "mismatch (locale %s): [%s]\n", setlocale(LC_CTYPE, nullptr), a.c_str());
                std::abort();
            }
            ++cases;
        }
        std::printf("locale %s passed\n", argv[l]);
    }
    std::printf("%ld addresses agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-url-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/en_US").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "en_US", "-f", "ISO-8859-1", str(locdir / "en_US.ISO8859-1")], check=True)
        locales.append("en_US.ISO8859-1")
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--release", "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "url.cpp"
    source.write_text(harness)
    for sanitize in (True, False):
        for char_flag in ("-fsigned-char", "-funsigned-char"):
            binary = temp / "url"
            flags = ["-fsanitize=address,undefined"] if sanitize else []
            subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-O1", "-g", "-w", char_flag, *flags,
                            "-I", str(ROOT / "rust/include"), str(source), str(temp / "target/release/libnzbget_rs.a"),
                            *native, "-o", str(binary)], check=True, env=env)
            print("sanitizers" if sanitize else "no sanitizers", char_flag, flush=True)
            subprocess.run([str(binary), *(["C"] if sanitize else locales)], check=True, env=env)
