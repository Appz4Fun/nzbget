#!/usr/bin/env python3
"""Compare UrlCoordinator's X-DNZB header handling and the statuses
UrlCompleted leaves (rust/src/urlcoord.rs through its C ABI) with the
pre-port C++ of UrlCoordinator.cpp, taken verbatim from the reference, and
with this tree's Rust branches: UrlDownloader::ProcessHeader's body (with
Util::Trim/TrimRight and WebUtil::Latin1ToUtf8 from their C++ fallbacks)
and UrlCompleted's status block, run against stand-in objects. Random
header lines (X-DNZB- names and values with spaces, tabs, CR/LF, Latin-1
bytes, colons, long names) and every combination of statuses.

Usage: urlcoord_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "3843520c"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "500000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/queue/UrlCoordinator.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/queue/UrlCoordinator.cpp").read_text()
util_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)


def body(src, signature, nth=0):
    """The braces-balanced body after the nth occurrence of signature."""
    at = -1
    for _ in range(nth + 1):
        at = src.index(signature, at + 1)
    start = src.index("\n{", at) + 1
    depth = 0
    for k in range(start, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[start:k + 1]
    raise ValueError(signature)


def fallback(src, signature):
    """The body of signature's #else (C++ fallback) definition."""
    return body(src, signature, 1)


STATUS_START = "\t\tretry = urlDownloader->GetStatus() == WebDownloader::adRetry && !nzbInfo->GetDeleting();"
STATUS_END = "\t\tif (!retry)\n"
old_status = old_src[old_src.index(STATUS_START):old_src.index(STATUS_END)]
rs_start = new_src.index("\t\t// rust/src/urlcoord.rs\n\t\tint urlStatus")
new_status = new_src[rs_start:new_src.index("#else", rs_start)]
assert "WebUtil::Latin1ToUtf8(value)" in body(old_src, "void UrlDownloader::ProcessHeader(const char* line)")

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))

STANDINS = r'''
struct Params
{
	std::vector<std::pair<std::string, std::string>> set;
	void SetParameter(const char* name, const char* value) { set.emplace_back(name, value); }
};
struct NzbInfo
{
	enum EDeleteStatus { dsNone, dsManual, dsHealth, dsDupe, dsBad, dsGood, dsCopy, dsScan };
	enum EUrlStatus { lsNone, lsRunning, lsFinished, lsFailed, lsRetry, lsScanSkipped, lsScanFailed };
	Params params;
	EUrlStatus urlStatus = lsNone;
	EDeleteStatus deleteStatus = dsNone;
	bool deleting = false;
	int sets = 0;
	Params* GetParameters() { return &params; }
	EUrlStatus GetUrlStatus() { return urlStatus; }
	void SetUrlStatus(EUrlStatus s) { urlStatus = s; }
	EDeleteStatus GetDeleteStatus() { return deleteStatus; }
	void SetDeleteStatus(EDeleteStatus s) { deleteStatus = s; }
	bool GetDeleting() { return deleting; }
	void SetDeleting(bool d) { deleting = d; }
};
struct WebDownloader
{
	enum EStatus { adUndefined, adRunning, adFinished, adFailed, adRetry, adNotFound, adRedirect, adConnectError, adFatalError };
	EStatus status;
	EStatus GetStatus() { return status; }
	static void ProcessHeader(const char*) {}
};
struct Downloader
{
	CString m_category;
	NzbInfo* m_nzbInfo;
	void ProcessHeader(const char* line);
};
'''

main = r'''
#include "nzbget.h"
#include "NString.h"
#include "Log.h"
#include "nzbget_rs.h"
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace old_impl {
struct Util
{
	static void TrimRight(char* str)
''' + fallback(util_src, "void Util::TrimRight(char* str)") + r'''
	static char* Trim(char* str)
''' + fallback(util_src, "char* Util::Trim(char* str)") + r'''
};
struct WebUtil
{
	static CString Latin1ToUtf8(const char* str)
''' + fallback(util_src, "CString WebUtil::Latin1ToUtf8(const char* str)") + r'''
};
''' + STANDINS + r'''
void Downloader::ProcessHeader(const char* line)
''' + body(old_src, "void UrlDownloader::ProcessHeader(const char* line)") + r'''
static bool Completed(WebDownloader* urlDownloader, NzbInfo* nzbInfo)
{
	bool retry;
''' + old_status + r'''	return retry;
}
}

namespace new_impl {
''' + STANDINS + r'''
void Downloader::ProcessHeader(const char* line)
''' + body(new_src, "void UrlDownloader::ProcessHeader(const char* line)") + r'''
static bool Completed(WebDownloader* urlDownloader, NzbInfo* nzbInfo)
{
	bool retry;
''' + new_status + r'''	return retry;
}
}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static std::string Line()
{
	static const char* HEADS[] = {"X-DNZB-Category:", "X-DNZB-Name:", "X-DNZB-", "X-DNZB-MoreInfo: ", "X-DNZB-category:",
		"x-dnzb-name:", "X-DNZB", "Content-Type: ", "X-DNZB-Category", "X-DNZB-:", ""};
	static const char PIECES[] = " \t\r\n:aZ0.\xe9\xff\x80-";
	std::string line = HEADS[below(11)];
	int n = below(8) ? below(24) : below(260);
	for (int i = 0; i < n; i++)
	{
		line += below(3) ? PIECES[below(sizeof(PIECES) - 1)] : (char)(1 + below(255));
	}
	if (below(10) == 0) line = std::string("X-DNZB-") + std::string(below(200), 'n') + ":" + line;
	return line;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	long failures = 0;
	for (long round = 0; round < rounds; round++)
	{
		std::string line = Line();
		old_impl::NzbInfo oldInfo; new_impl::NzbInfo newInfo;
		old_impl::Downloader a; a.m_nzbInfo = &oldInfo;
		new_impl::Downloader b; b.m_nzbInfo = &newInfo;
		if (below(2)) { a.m_category = "keep"; b.m_category = "keep"; }
		a.ProcessHeader(line.c_str());
		b.ProcessHeader(line.c_str());
		if (strcmp(a.m_category ? *a.m_category : "(null)", b.m_category ? *b.m_category : "(null)") ||
			oldInfo.params.set != newInfo.params.set)
		{
			printf("header mismatch: '%s'\n", line.c_str());
			failures++;
		}
	}
	long combos = 0;
	for (int status = 0; status <= 8; status++)
	for (int deleting = 0; deleting < 2; deleting++)
	for (int url = 0; url <= 6; url++)
	for (int del = 0; del <= 7; del++)
	{
		old_impl::WebDownloader od{(old_impl::WebDownloader::EStatus)status};
		new_impl::WebDownloader nd{(new_impl::WebDownloader::EStatus)status};
		old_impl::NzbInfo o; o.urlStatus = (old_impl::NzbInfo::EUrlStatus)url; o.deleteStatus = (old_impl::NzbInfo::EDeleteStatus)del; o.deleting = deleting;
		new_impl::NzbInfo n; n.urlStatus = (new_impl::NzbInfo::EUrlStatus)url; n.deleteStatus = (new_impl::NzbInfo::EDeleteStatus)del; n.deleting = deleting;
		bool r1 = old_impl::Completed(&od, &o), r2 = new_impl::Completed(&nd, &n);
		combos++;
		if (r1 != r2 || (int)o.urlStatus != (int)n.urlStatus || (int)o.deleteStatus != (int)n.deleteStatus || o.deleting != n.deleting)
		{
			printf("status mismatch %d %d %d %d\n", status, deleting, url, del);
			failures++;
		}
	}
	printf("%ld header lines and %ld status combinations agree (reference %s)\n", rounds, combos, "''' + REFERENCE + r'''");
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-urlcoord-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "urlcoord"
    # the fallback, and both branches with debug() compiled in
    for defines in (["-UNZBGET_USE_RUST"], ["-DDEBUG"], ["-UNZBGET_USE_RUST", "-DDEBUG"]):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *defines, *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only", str(ROOT / "daemon/queue/UrlCoordinator.cpp")],
                       check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        str(BUILD / "liblibnzbget.a"), str(rust_lib),
                        "-lssl", "-lcrypto", "-lpthread", "-ldl", "-lm", "-lz", "-lxml2", "-lboost_json"], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True)
