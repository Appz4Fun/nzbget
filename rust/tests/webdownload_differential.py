#!/usr/bin/env python3
"""Compare WebDownloader's HTTP decisions (rust/src/webdownload.rs with the
C++ wrappers of WebDownloader.cpp), and their C++ fallback, with the pre-port
C++: CheckResponse (result, status, warnings), ProcessHeader (lengths, gzip,
file names, redirects) and ParseRedirect (the new address and its log line)
on generated and mutated status lines, headers and URLs, in the C, C.UTF-8
and tr_TR.ISO8859-9 locales. Relative-path redirects from an invalid address
compare Rust with the repaired fallback only: the original C++ dereferenced
a null resource there.

Each version's methods are compiled into a stand-in WebDownloader (in its
own namespace) that records complete log messages. The oracle and fallback
use the original C++ URL parser; WebUtil and FileSystem come from the build.

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
		va_list ap;
		va_start(ap, format);
		va_list copy;
		va_copy(copy, ap);
		int len = vsnprintf(nullptr, 0, format, copy);
		va_end(copy);
		if (len < 0) abort();
		std::vector<char> buf(len + 1);
		vsnprintf(buf.data(), buf.size(), format, ap);
		va_end(ap);
		m_log += std::string(kind) + buf.data() + "\n";
	}
	EStatus CheckResponse(const char* response);
	void ProcessHeader(const char* line);
	void ParseFilename(const char* contentDisposition);
	void ParseRedirect(const char* location);
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/connect/WebDownloader.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/connect/WebDownloader.cpp").read_text()

# Use the actual C++ URL parser for the oracle. Linking every stand-in to
# the build's Rust-backed URL class would mask shared parsing mistakes.
util_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
util_h = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.h"], cwd=ROOT, text=True)
url_class = util_h[util_h.index("class URL\n{"):util_h.index("\nclass RegEx")]
ctor = util_src.index("URL::URL(const char* address)")
parser = util_src.rindex("void URL::ParseUrl()")
legacy_url = url_class + util_src[ctor:util_src.index("\n}\n", ctor) + 3] + util_src[parser:util_src.index("\n}\n", parser) + 3]

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
''' + legacy_url + STANDIN + bodies(old_src, "last") + r'''
}
namespace newimpl {
''' + STANDIN + bodies(new_src, "first") + r'''
}
namespace fallbackimpl {
using oldimpl::URL;
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
	"HTTP/1.1 -5", "HTTP/1.1 99999999999", "http/1.1 200 OK", "garbage", "", "ICY 200 OK", "HTTP/2 200",
	"HTTP 4000", "HTTP 499x", "HTTP 4040", "HTTP 200x", "HTTP +200", "HTTP \t200", "HTTP 2147483648",
	"HTTP -2147483649", "HTTP 18446744073709551616", "HTTP \v302", "HTTP \xff"};
static const char* const HEADERS[] = {"Content-Length: 1234", "content-length: 0", "CONTENT-LENGTH: -1",
	"Content-Length: 99999999999", "Content-Length:5", "Content-Length: ", "Content-Encoding: gzip",
	"content-encoding: GZIP", "Content-Encoding: deflate", "Content-Disposition: attachment; filename=\"a b.nzb\"",
	"content-disposition: inline; filename*=UTF-8''%E2%82%AC.nzb", "Content-Disposition: ", "Location: http://x.org/a?k=1",
	"location: /abs/path?q", "Location: rel/file.nzb", "Location: //cdn.example.net/f?x", "Location: ", "Location:x",
	"Server: nginx", "", "Content-Lengths: 7", "Location: https://user:pw@h.org:8443/p", "Location: ?only=query",
	"Location: ../up", "LOCATION: HTTP://UPPER.ORG/X", "Content-Encoding: gzipjunk", "Content-Length: +12junk",
	"CONTENT-DISPOSITION: filename=x", "Content-D\xddSposition: filename=y", "LOCAT\xddON: /x"};
static const char* const URLS[] = {"https://indexer.org/api?t=get&id=1&apikey=secret", "http://h.org", "http://h.org/",
	"https://h.org:8443/a/b/c?x=1", "http://user:pw@h.org:81/dir/file.nzb", "bad", "", "ftp://x/y", "http://h.org/a?b/c",
	"http://", "http:///", "http://:80/x", "http://@/x", "http://h:/x", "http://h:0/x", "http://h:-1/x",
	"http://h:+42/x", "http://h:2147483648/x", "http://h:4294967297/x", "http://[::1]:80/x",
	"http://h:", "http://h:/", "http://h:9/", "http://h: 81/a/b", "http://h:999999999999999999999/x",
	"http://@", "http://:pw@/", "http://user:@:80/a", "http://h?query", "http://h#fragment"};
static const char* const LOCATIONS[] = {"", "next", "?q/a", "../x", "/", "//", "///x", "//h/x?q",
	"https://", "http:///", "x+1.2://h", "1x://h", "/x?url=https://h", "\xdd://h/x", "\nhttp://h",
	"http://@", "http://:80", "http://h:", "http://h:0/", "http://h:2147483648/", "http://h/a\r\nb"};

template <class W> static std::string run(const std::string& status, bool stopped, const std::string& url,
	const std::string& h1, const std::string& h2, bool redirecting, bool closed)
{
	W w;
	w.m_stopped = stopped;
	w.m_httpStatus = 418;
	w.m_redirecting = redirecting;
	w.SetUrl(url.c_str());
	std::string out;
	int st = (int)w.CheckResponse(closed ? nullptr : status.c_str());
	out += std::to_string(st) + "," + std::to_string(w.m_httpStatus) + "," + std::to_string(w.m_redirecting) + "|";
	for (const std::string* h : {&h1, &h2})
	{
		// Only this branch dereferences a null resource in the original.
		if (w.m_redirecting && !strncasecmp(h->c_str(), "Location: ", 10) &&
			!oldimpl::URL(w.m_url).IsValid() && h->c_str()[10] != '/' &&
			!oldimpl::URL(h->c_str() + 10).IsValid()) continue;
		std::vector<char> line(h->begin(), h->end());
		line.push_back('\0');
		w.ProcessHeader(line.data());
	}
	out += std::to_string(w.m_contentLen) + "," + std::to_string(w.m_confirmedLength) + "," + std::to_string(w.m_gzip) + "," +
		std::to_string(w.m_redirected) + "," + (w.m_originalFilename ? std::string(w.m_originalFilename) : std::string("-")) + "," +
		std::string(w.m_url ? (const char*)w.m_url : "-") + "|" + w.m_log;
	return out;
}

template <class W> static std::string redirect(const std::string& url, const std::string& location)
{
	W w;
	// Deliberately bypass SetUrl: test raw bytes and the URL class's parts,
	// including locale-dependent schemes, before URL encoding changes them.
	w.m_url = url.c_str();
	w.ParseRedirect(location.c_str());
	return std::string(w.m_url) + "|" + w.m_log;
}

static void check_redirect(const std::string& url, const std::string& location)
{
	bool legacyUndefined = !oldimpl::URL(url.c_str()).IsValid() && !oldimpl::URL(location.c_str()).IsValid() &&
		(location.empty() || location[0] != '/');
	auto y = redirect<newimpl::WebDownloader>(url, location);
	auto z = redirect<fallbackimpl::WebDownloader>(url, location);
	auto x = legacyUndefined ? y : redirect<oldimpl::WebDownloader>(url, location);
	if (x != y || x != z)
	{
		fprintf(stderr, "redirect mismatch: url [%s] location [%s]\nold: %s\nrust: %s\nfallback: %s\n",
			url.c_str(), location.c_str(), x.c_str(), y.c_str(), z.c_str());
		exit(1);
	}
}

static void check_headers(const std::string& status, bool stopped, const std::string& url,
	const std::string& h1, const std::string& h2, bool redirecting, bool closed)
{
	std::string x = run<oldimpl::WebDownloader>(status, stopped, url, h1, h2, redirecting, closed);
	std::string y = run<newimpl::WebDownloader>(status, stopped, url, h1, h2, redirecting, closed);
	std::string z = run<fallbackimpl::WebDownloader>(status, stopped, url, h1, h2, redirecting, closed);
	if (x != y || x != z)
	{
		fprintf(stderr, "mismatch in %s: status [%s] url [%s] headers [%s] [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
			setlocale(LC_ALL, nullptr), status.c_str(), url.c_str(), h1.c_str(), h2.c_str(), x.c_str(), y.c_str(), z.c_str());
		exit(1);
	}
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	for (int l = 2; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		for (const char* url : URLS)
			for (const char* location : LOCATIONS)
				check_redirect(url, location);
		// Every truncation of the known prefixes, both stopped states and
		// redirect states, without randomly substituting a closed connection.
		for (const char* status : STATUS)
			for (size_t n = 0; n <= strlen(status); ++n)
				for (bool stopped : {false, true})
					for (bool redirecting : {false, true})
						check_headers(std::string(status, n), stopped, "http://h/a", "", "", redirecting, false);
		for (bool stopped : {false, true})
			check_headers("", stopped, "http://h/a", "", "", false, true);
		for (const char* header : HEADERS)
			for (size_t n = 0; n <= strlen(header); ++n)
				for (bool redirecting : {false, true})
					check_headers("HTTP 200", false, "http://h/a", std::string(header, n), "", redirecting, false);
		for (int byte = 1; byte <= 255; ++byte)
		{
			std::string scheme(1, (char)byte);
			check_redirect(scheme + "://h:81/a/b?q", "/x");
			check_redirect("http://h/a/b?q", scheme + "://other/x");
		}
		check_redirect("http://h/" + std::string(10000, 'x') + "/file?q", std::string(10000, 'y'));
		for (long round = 0; round < rounds; round++)
		{
			std::string status = mutate(pick(STATUS));
			std::string url = mutate(pick(URLS));
			std::string h1 = mutate(pick(HEADERS)), h2 = mutate(pick(HEADERS));
			bool stopped = below(4) == 0, redirecting = below(2);
			check_headers(status, stopped, url, h1, h2, redirecting, below(15) == 0);
			check_redirect(mutate(pick(URLS)), mutate(pick(LOCATIONS)));
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
