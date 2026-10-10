#!/usr/bin/env python3
"""Compare WebProcessor's request decisions (rust/src/webserver.rs with the
C++ wrappers of WebServer.cpp) with the pre-port C++: ParseHeaders, ParseUrl,
CheckCredentials and IsAuthorizedIp on random header sets, URLs and
credentials, in the C, C.UTF-8 and tr_TR.ISO8859-9 locales.

Both versions' method bodies are compiled into a stand-in class with the
members they use, a scripted connection and options.

Usage: webserver_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "fdc741d2"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "200000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/WebServer.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/remote/WebServer.cpp").read_text()
util_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
METHODS = ["void WebProcessor::ParseHeaders()", "bool WebProcessor::ParseUrl()", "bool WebProcessor::CheckCredentials()",
           "bool WebProcessor::IsAuthorizedIp(const char* remoteAddr)"]


def body(src, sig, cls):
    start = src.index(sig + "\n{")
    return src[start:src.index("\n}\n", start) + 3].replace("WebProcessor::", cls + "::")


new_rust = new_src[new_src.index("#ifdef NZBGET_USE_RUST\nvoid WebProcessor::ParseHeaders()"):]
fold = new_src[new_src.index("namespace\n{\n\t// tolower as WildMask's C++ code did"):]
fold = fold[:fold.index("\n}\n") + 3]

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

shim = r'''
inline constexpr int TOKEN_SIZE = 48 + 1;
struct FakeConnection {
    std::vector<std::string> lines; size_t next = 0; std::string remote; char line[1100];
    char* ReadLine(char* buffer, int size, int*) {
        if (next >= lines.size()) return nullptr;
        snprintf(buffer, size, "%s", lines[next++].c_str());
        return buffer;
    }
    const char* GetRemoteAddr() { return remote.c_str(); }
};
struct FakeOptions {
    std::string cu, cp, ru, rp, au, ap, ip; int port = 6789;
    // Options never gives null strings (unset ones are "")
    static const char* s(const std::string& v) { return v.c_str(); }
    const char* GetControlUsername() { return s(cu); } const char* GetControlPassword() { return s(cp); }
    const char* GetRestrictedUsername() { return s(ru); } const char* GetRestrictedPassword() { return s(rp); }
    const char* GetAddUsername() { return s(au); } const char* GetAddPassword() { return s(ap); }
    const char* GetAuthorizedIp() { return s(ip); } int GetControlPort() { return port; } bool GetFormAuth() { return false; }
};
static FakeOptions fakeOptions;
static int warnings;
#define g_Options (&fakeOptions)
#define warn(...) (++warnings)
#define error(...) (++warnings)
#undef debug
#define debug(...) ((void)0)
'''
cls = '''
struct NAME {
    enum EUserAccess { uaControl, uaRestricted, uaAdd };
    FakeConnection* m_connection;
    EUserAccess m_userAccess = uaControl;
    CString m_url, m_origin, m_forwardedFor, m_oldETag;
    char m_authInfo[256+1] = "";
    char m_authToken[TOKEN_SIZE] = "";
    static inline char m_serverAuthToken[3][TOKEN_SIZE] = {"tokcontrol", "tokrestricted", "tokadd"};
    int m_contentLen = -1; bool m_gzip = false, m_keepAlive = false;
    std::string m_redirect;
    void SendRedirectResponse(const char* url) { m_redirect = url; }
    void ParseHeaders(); bool ParseUrl(); bool CheckCredentials(); bool IsAuthorizedIp(const char* remoteAddr);
    std::string State() {
        return std::string(m_url ? *m_url : "(null)") + "|" + m_authInfo + "|" + m_authToken + "|" + std::to_string(m_userAccess) +
            "|" + std::to_string(m_contentLen) + std::to_string(m_gzip) + std::to_string(m_keepAlive) + "|" +
            (m_origin ? *m_origin : "-") + "|" + (m_forwardedFor ? *m_forwardedFor : "-") + "|" + (m_oldETag ? *m_oldETag : "-") + "|" + m_redirect;
    }
};
'''
harness = '#include "nzbget.h"\n#include "Util.h"\n#include "nzbget_rs.h"\n#include <climits>\n#include <clocale>\n#include <random>\n#include <vector>\n' + shim
harness += r'''
// Use the actual C++ wildcard oracle, even when libnzbget uses Rust.
struct LegacyWildMask {
    const char* m_pattern;
    bool m_wantsPositions = false;
    int m_wildCount = 0;
    std::vector<int> m_wildStart, m_wildLen;
    LegacyWildMask(const char* p) : m_pattern(p) {}
    void ExpandArray();
    bool Match(const char* text);
};
'''
legacy_mask = util_src[util_src.index("void WildMask::ExpandArray()") :]
for method in ("void WildMask::ExpandArray()", "bool WildMask::Match(const char* text)"):
    harness += body(legacy_mask, method, "unused").replace("WildMask::", "LegacyWildMask::")
harness += cls.replace("NAME", "OldWP") + cls.replace("NAME", "NewWP")
harness += "".join(body(old_src, m, "OldWP").replace("WildMask mask", "LegacyWildMask mask") for m in METHODS)
harness += fold.replace("WebFold", "WebFold") + "".join(body(new_rust, m, "NewWP") for m in METHODS)
harness += r'''
int main(int argc, char** argv) {
    std::mt19937 rng(23);
    auto pick = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); };
    auto bytes = [&](int max) {
        std::string s(pick(max + 1), '\0');
        for (char& c : s) c = static_cast<char>(pick(256));
        return s;
    };
    const char* heads[] = {"Content-Length: ", "content-length: ", "Authorization: Basic ", "X-Authorization: Basic ",
        "Accept-Encoding: ", "Origin: ", "Cookie: ", "X-Forwarded-For: ", "If-None-Match: ", "Connection: keep-alive",
        "CONNECTION: Keep-Alive", "Host: ", "", "AUTHORIZATION: basic ", "Cookie: a=1; Auth-Token=", "IDE: "};
    const std::string vals[] = {"42", "-1", "abc", "bnpiZ2V0OnNlY3JldA==", "dXNlcjpwdw==", "gzip, deflate", "tokcontrol", "tokadd",
        "x; Auth-Token=tokrestricted; y=1", "Auth-Token=;", "1.2.3.4", "\"etag\"", std::string(300, 'Q'), "\xe9", ""};
    const char* urls[] = {"/", "/nzbget", "/nzbget/", "/nzbget/jsonrpc", "/u:p/jsonrpc", "/nzbget/nzbget:secret/xmlrpc",
        "/jsonrpc?a=b:c", "/a:b", "/%41dmin:p%3A%40/x", "/user%00x:pw/x", "/:x/y", "//"};
    const char* names[] = {"", "", "nzbget", "secret", "user", "pw", "add", "IDE"};
    const char* ips[] = {"", "", "192.168.1.*", "10.0.0.1, 127.0.0.1", "*", "192.168.1.9?", "IDE"};
    const char* remotes[] = {"192.168.1.93", "10.0.0.1", "127.0.0.1", "::1"};
    long cases = 0;
    int rounds = atoi(argv[1]);
    for (int l = 2; l < argc; ++l) {
        if (!setlocale(LC_CTYPE, argv[l])) { printf("locale %s unavailable\n", argv[l]); return 1; }
        for (int r = 0; r < rounds; ++r) {
            FakeConnection a, b;
            int n = pick(6);
            for (int k = 0; k < n; ++k) a.lines.push_back(std::string(heads[pick(16)]) + vals[pick(15)] + (pick(3) ? "\r" : ""));
            if (r % 2) {
                a.lines.push_back(std::string(heads[pick(16)]) + bytes(1100));
                // Exhaust the auth limit and token truncation boundaries.
                a.lines.push_back(std::string(heads[2 + pick(2)]) + std::string(254 + pick(6), 'Q'));
            }
            a.remote = remotes[pick(4)];
            b = a;
            fakeOptions.cu = names[pick(8)]; fakeOptions.cp = names[pick(8)]; fakeOptions.ru = names[pick(8)]; fakeOptions.rp = names[pick(8)];
            fakeOptions.au = names[pick(8)]; fakeOptions.ap = names[pick(8)]; fakeOptions.ip = ips[pick(7)];
            if (r % 3 == 0) {
                a.remote = bytes(40);
                fakeOptions.ip = bytes(50) + ",; \t" + (pick(2) ? a.remote : "*") + "\r\n";
                b.remote = a.remote;
            }
            OldWP o; NewWP w;
            o.m_connection = &a; w.m_connection = &b;
            { const char* u = urls[pick(12)]; o.m_url = u; w.m_url = u; }
            if (r % 2) {
                std::string u = std::string(pick(2) ? "/nzbget/" : "/") + bytes(300) + ":" + bytes(300) + "/jsonrpc";
                o.m_url = u.c_str(); w.m_url = u.c_str();
            }
            if (r % 5 == 0) {
                std::string auth = std::string(names[pick(8)]) + ":" + names[pick(8)];
                strcpy(o.m_authInfo, auth.c_str()); strcpy(w.m_authInfo, auth.c_str());
                o.m_userAccess = OldWP::uaAdd; w.m_userAccess = NewWP::uaAdd;
            }
            int headerWarnings = warnings;
            o.ParseHeaders();
            int afterOldHeaders = warnings;
            w.ParseHeaders();
            if (o.State() != w.State() || a.next != b.next ||
                afterOldHeaders - headerWarnings != warnings - afterOldHeaders) {
                printf("Header mismatch (locale %s, round %d)\n", argv[l], r);
                return 1;
            }
            bool ou = o.ParseUrl(), nu = w.ParseUrl();
            int warnOld = warnings; bool oc = ou && o.CheckCredentials(); int warnMid = warnings; bool nc = nu && w.CheckCredentials();
            bool oi = o.IsAuthorizedIp(nullptr), ni = w.IsAuthorizedIp(nullptr);
            if (ou != nu || oc != nc || oi != ni || o.State() != w.State() || warnMid - warnOld != warnings - warnMid) {
                printf("MISMATCH (locale %s)\n  C++:  %d%d%d %s\n  Rust: %d%d%d %s\n", argv[l], ou, oc, oi, o.State().c_str(), nu, nc, ni, w.State().c_str());
                for (auto& x : a.lines) printf("  header [%s]\n", x.c_str());
                return 1;
            }
            ++cases;
        }
    }
    printf("%ld requests agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-web-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(harness)
    env = dict(os.environ)
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/tr_TR").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "tr_TR", "-f", "ISO-8859-9", str(locdir / "tr_TR.ISO8859-9")], check=True)
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
        locales.append("tr_TR.ISO8859-9")
    binary = temp / "web"
    for char_flag in ("-fsigned-char", "-funsigned-char"):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        char_flag, *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, *locales], check=True, env=env)
