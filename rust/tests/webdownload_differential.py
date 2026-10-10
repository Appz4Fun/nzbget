#!/usr/bin/env python3
"""Compare WebDownloader's HTTP decisions (rust/src/webdownload.rs with the
C++ wrappers of WebDownloader.cpp), and their C++ fallback, with the pre-port
C++: CheckResponse (result, status, warnings), ProcessHeader (lengths, gzip,
file names, redirects) and ParseRedirect (the new address and its log line)
on generated and mutated status lines, headers and URLs, in the C, C.UTF-8
and tr_TR.ISO8859-9 locales. A redirect from an invalid address is left out:
the C++ dereferenced a null resource there (Rust reads it as empty).

Each version's methods are compiled into a stand-in WebDownloader (in its
own namespace) that records what it logs, against the build's WebUtil, URL
and FileSystem.

Usage: webdownload_differential.py BUILD_DIR [ROUNDS]
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
REFERENCE = "02c80b7b"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "200000"

SIGS = [
    "WebDownloader::EStatus WebDownloader::CheckResponse(const char* response)",
    "void WebDownloader::ProcessHeader(const char* line)",
    "void WebDownloader::ParseFilename(const char* contentDisposition)",
    "void WebDownloader::ParseRedirect(const char* location)",
]


def bodies(src, which):
    out = []
    for sig in SIGS:
        i = src.index(sig + "\n{") if which == "first" else src.rindex(sig + "\n{")
        out.append(src[i:src.index("\n}\n", i) + 3])
    return "".join(out)


STANDIN = r'''
class WebDownloader
{
public:
	enum EStatus { adUndefined, adRunning, adFinished, adFailed, adRetry, adNotFound, adRedirect, adConnectError, adFatalError };
	CString m_infoName = "nzb";
	CString m_url;
	int m_contentLen = -1;
	bool m_confirmedLength = false;
	int m_httpStatus = 0;
	CString m_originalFilename;
	bool m_redirecting = false;
	bool m_redirected = false;
	bool m_gzip = false;
	bool m_stopped = false;
	std::string m_log;
	bool IsStopped() { return m_stopped; }
	void SetUrl(const char* url) { m_url = WebUtil::UrlEncode(url); }
	void Record(const char* kind, const char* format, ...)
	{
		char buf[4096];
		va_list ap;
		va_start(ap, format);
		vsnprintf(buf, sizeof buf, format, ap);
		va_end(ap);
		m_log += std::string(kind) + buf + "\n";
	}
	EStatus CheckResponse(const char* response);
	void ProcessHeader(const char* line);
	void ParseFilename(const char* contentDisposition);
	void ParseRedirect(const char* location);
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/connect/WebDownloader.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/connect/WebDownloader.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]

main = r'''
#include "nzbget.h"
#include "Util.h"
#include "FileSystem.h"
#include "nzbget_rs.h"
#include <clocale>
#include <cstdarg>
#include <string>
''' + globals_block + r'''
#undef warn
#undef detail
#undef debug
#define warn(...) Record("W:", __VA_ARGS__)
#define detail(...) Record("D:", __VA_ARGS__)
#define debug(...) Record("G:", __VA_ARGS__)

namespace oldimpl {
''' + STANDIN + bodies(old_src, "last") + r'''
}
namespace newimpl {
''' + STANDIN + bodies(new_src, "first") + r'''
}
namespace fallbackimpl {
''' + STANDIN + bodies(new_src, "last") + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static std::string mutate(std::string s)
{
	int m = below(4) == 0 ? 1 + below(3) : 0;
	for (int i = 0; i < m && !s.empty(); i++)
	{
		size_t at = below((int)s.size());
		switch (below(4))
		{
			case 0: s[at] = (char)(1 + below(255)); break;
			case 1: s.erase(at, 1 + below(3)); break;
			case 2: s.insert(at, below(2) ? "/" : "?"); break;
			default: s.resize(at);
		}
	}
	return s;
}

static const char* const STATUS[] = {"HTTP/1.1 200 OK", "HTTP/1.0 200", "HTTP/1.1 301 Moved", "HTTP/1.1 302 Found",
	"HTTP/1.1 303 See", "HTTP/1.1 307 Temp", "HTTP/1.1 308 Perm", "HTTP/1.1 304 Not Modified", "HTTP/1.1 400 Bad",
	"HTTP/1.1 404 Not Found", "HTTP/1.1 499 x", "HTTP/1.1 500 Error", "HTTP/1.1  200", "HTTP/1.1 2000", "HTTP", "HTTP ",
	"HTTP/1.1 -5", "HTTP/1.1 99999999999", "http/1.1 200 OK", "garbage", "", "ICY 200 OK", "HTTP/2 200"};
static const char* const HEADERS[] = {"Content-Length: 1234", "content-length: 0", "CONTENT-LENGTH: -1",
	"Content-Length: 99999999999", "Content-Length:5", "Content-Length: ", "Content-Encoding: gzip",
	"content-encoding: GZIP", "Content-Encoding: deflate", "Content-Disposition: attachment; filename=\"a b.nzb\"",
	"content-disposition: inline; filename*=UTF-8''%E2%82%AC.nzb", "Content-Disposition: ", "Location: http://x.org/a?k=1",
	"location: /abs/path?q", "Location: rel/file.nzb", "Location: //cdn.example.net/f?x", "Location: ", "Location:x",
	"Server: nginx", "", "Content-Lengths: 7", "Location: https://user:pw@h.org:8443/p", "Location: ?only=query",
	"Location: ../up", "LOCATION: HTTP://UPPER.ORG/X"};
static const char* const URLS[] = {"https://indexer.org/api?t=get&id=1&apikey=secret", "http://h.org", "http://h.org/",
	"https://h.org:8443/a/b/c?x=1", "http://user:pw@h.org:81/dir/file.nzb", "bad", "", "ftp://x/y", "http://h.org/a?b/c"};

template <class W> static std::string run(const std::string& status, bool stopped, const std::string& url,
	const std::string& h1, const std::string& h2, bool redirecting)
{
	W w;
	w.m_stopped = stopped;
	w.SetUrl(url.c_str());
	std::string out;
	int st = (int)w.CheckResponse(below(15) ? status.c_str() : nullptr);
	out += std::to_string(st) + "," + std::to_string(w.m_httpStatus) + "," + std::to_string(w.m_redirecting) + "|";
	if (redirecting) w.m_redirecting = true;
	for (const std::string* h : {&h1, &h2})
	{
		std::vector<char> line(h->begin(), h->end());
		line.push_back('\0');
		w.ProcessHeader(line.data());
	}
	out += std::to_string(w.m_contentLen) + "," + std::to_string(w.m_confirmedLength) + "," + std::to_string(w.m_gzip) + "," +
		std::to_string(w.m_redirected) + "," + (w.m_originalFilename ? std::string(w.m_originalFilename) : std::string("-")) + "," +
		std::string(w.m_url ? (const char*)w.m_url : "-") + "|" + w.m_log;
	return out;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	for (int l = 2; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		for (long round = 0; round < rounds; round++)
		{
			std::string status = mutate(pick(STATUS));
			std::string url = mutate(pick(URLS));
			std::string h1 = mutate(pick(HEADERS)), h2 = mutate(pick(HEADERS));
			bool stopped = below(4) == 0, redirecting = below(2);
			// a relative redirect from an invalid address dereferenced its null
			// resource in the C++ (undefined): no Location then
			if (!URL(WebUtil::UrlEncode(url.c_str())).IsValid())
				for (std::string* h : {&h1, &h2})
					if (!strncasecmp(h->c_str(), "Location: ", 10)) *h = "Server: x";
			unsigned long long seed = state;
			std::string x = run<oldimpl::WebDownloader>(status, stopped, url, h1, h2, redirecting);
			state = seed;
			std::string y = run<newimpl::WebDownloader>(status, stopped, url, h1, h2, redirecting);
			state = seed;
			std::string z = run<fallbackimpl::WebDownloader>(status, stopped, url, h1, h2, redirecting);
			if (x != y || x != z)
			{
				fprintf(stderr, "mismatch in %s: status [%s] url [%s] headers [%s] [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
					argv[l], status.c_str(), url.c_str(), h1.c_str(), h2.c_str(), x.c_str(), y.c_str(), z.c_str());
				return 1;
			}
		}
		printf("%s: %ld rounds agree (reference %s)\n", argv[l], rounds, "''' + REFERENCE + r'''");
	}
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-webdownload-") as temp:
    temp = Path(temp)
    env = dict(os.environ)
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/tr_TR").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
        subprocess.run(["localedef", "--no-archive", "-i", "tr_TR", "-f", "ISO-8859-9", str(locdir / "tr_TR.ISO8859-9")], check=True)
        locales.append("tr_TR.ISO8859-9")
    (temp / "main.cpp").write_text(main)
    binary = temp / "webdownload"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, *locales], check=True, env=env)
