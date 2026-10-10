#!/usr/bin/env python3
"""Compare Options' value parsers (rust/src/options.rs with the C++ wrappers
of Options.cpp), and their C++ fallback, with the pre-port C++: ParseTime,
ParseWeekDays, ValidateOptionName (its result and what it logs),
ConvertOldOption, HasScript and ParseCategorySource on generated and mutated
names and values, in the C, C.UTF-8 and tr_TR.ISO8859-9 locales (strcasecmp
folds 'I' differently there).

Each version's methods are compiled into a stand-in Options (in its own
namespace) with a recording ConfigWarn/ConfigError and a fixed GetOption.
The pre-port ValidateOptionName passed string_views to ConfigError's "%s"
(undefined); the stand-in records the format and the option name only.

Usage: options_differential.py BUILD_DIR [ROUNDS]
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
    "bool Options::ParseTime(const char* time, int* hours, int* minutes)",
    "bool Options::ParseWeekDays(const char* weekDays, int* weekDaysBits)",
    "bool Options::ValidateOptionName(const char* optname, const char* optvalue)",
    "void Options::ConvertOldOption(CString& option, CString& value)",
    "bool Options::HasScript(const char* scriptList, const char* scriptName)",
    "FeedInfo::CategorySource Options::ParseCategorySource(const char* value)",
]


def bodies(src, which):
    out = []
    for sig in SIGS:
        # the Rust wrapper is the first definition, the C++ (or pre-port) the last
        i = src.index(sig + "\n{") if which == "first" else src.rindex(sig + "\n{")
        out.append(src[i:src.index("\n}\n", i) + 3])
    return "".join(out)


header = (ROOT / "daemon/main/Options.h").read_text()
names = re.findall(r"static constexpr std::string_view (\w+) =", header)
constants = "".join(f"\tstatic constexpr std::string_view {n} = ::Options::{n};\n" for n in names)

STANDIN = r'''
class Options
{
public:
''' + constants + r'''
	std::string m_log;
	void ConfigWarn(const char* msg, ...)
	{
		va_list ap;
		va_start(ap, msg);
		m_log += std::string("W:") + msg + ":" + va_arg(ap, const char*) + ";";
		va_end(ap);
	}
	void ConfigError(const char* msg, ...)
	{
		va_list ap;
		va_start(ap, msg);
		m_log += std::string("E:") + msg + ":" + va_arg(ap, const char*) + ";";
		va_end(ap);
	}
	const char* GetOption(const char* optname)
	{
		for (const char* known : {"MainDir", "DestDir", "ParCheck", "Server1.Host", "Extensions"})
			if (!strcasecmp(optname, known)) return "x";
		return nullptr;
	}
	bool ParseTime(const char* time, int* hours, int* minutes);
	bool ParseWeekDays(const char* weekDays, int* weekDaysBits);
	bool ValidateOptionName(const char* optname, const char* optvalue);
	static void ConvertOldOption(CString& option, CString& value);
	static bool HasScript(const char* scriptList, const char* scriptName);
	FeedInfo::CategorySource ParseCategorySource(const char* value);
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/main/Options.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/main/Options.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

main = r'''
#include "nzbget.h"
#include "Util.h"
#include "Options.h"
#include "FeedInfo.h"
#include "nzbget_rs.h"
#include <clocale>
#include <cstdarg>
#include <string>
#include <vector>

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

static std::string recase(std::string s)
{
	if (below(3) == 0)
		for (char& c : s) c = below(2) ? toupper((unsigned char)c) : tolower((unsigned char)c);
	return s;
}

static std::string chars(const char* alphabet, int maxLen)
{
	std::string s;
	int n = below(maxLen + 1);
	for (int i = 0; i < n; i++) s += below(12) ? alphabet[below((int)strlen(alphabet))] : (char)(1 + below(255));
	return s;
}

static const char* const PREFIXES[] = {"Server", "Task", "Category", "Feed", "server", "TASK", "Serv", "Feeds", "x", ""};
static const char* const SUFFIXES[] = {".Active", ".Name", ".Level", ".Host", ".Port", ".Username", ".Password",
	".JoinGroup", ".Encryption", ".Connections", ".Cipher", ".Group", ".Retention", ".Optional", ".Notes",
	".IpVersion", ".CertVerification", ".Time", ".WeekDays", ".Command", ".Param", ".DownloadRate", ".Process",
	".DestDir", ".Extensions", ".Unpack", ".Aliases", ".Url", ".Interval", ".Filter", ".Backlog", ".PauseNzb",
	".Category", ".CategorySource", ".Priority", ".DefScript", ".PostScript", ".FeedScript", ".Bogus", "", "."};
static const char* const NAMES[] = {"ConfigFile", "AppBin", "AppDir", "Version", "MainDir", "DestDir", "RetryOnCrcError",
	"AllowReProcess", "LoadPars", "ThreadLimit", "PostLogKind", "NZBLogKind", "ProcessLogKind", "AppendNzbDir",
	"RenameBroken", "MergeNzb", "StrictParName", "ReloadUrlQueue", "ReloadPostQueue", "ParCleanupQueue",
	"DeleteCleanupDisk", "HistoryCleanupDisk", "SaveQueue", "ReloadQueue", "TerminateTimeout", "AccurateRate",
	"CreateBrokenLog", "BrokenLog", "PostProcess", "NZBProcess", "NZBAddedProcess", "ScanScript", "QueueScript",
	"FeedScript", "CreateLog", "ResetLog", "Script.py:Option", ":", "$MAINDIR", "ServerIP", "ServerPort",
	"ServerPassword", "PostPauseQueue", "ParCheck", "ParScan", "DefScript", "PostScript", "WriteBufferSize",
	"ConnectionTimeout", "Retries", "RetryInterval", "DumpCore", "Decode", "LogBufferSize", "Bogus", "", "INFO"};
static const char* const VALUES[] = {"yes", "no", "YES", "No", "auto", "Auto", "", "-1", "0", "1023", "1024", "2048",
	"99999999999", "-2147483649", " 12", "abc", "12abc", "x"};

static std::string name()
{
	if (below(2)) return recase(pick(NAMES));
	std::string s = recase(pick(PREFIXES));
	if (below(3)) s += std::to_string(below(1000));
	s += recase(pick(SUFFIXES));
	if (below(10) == 0) s += recase(pick(SUFFIXES));
	if (below(10) == 0) s = chars("abcIi.:019", 12);
	return s;
}

template <class O> static std::string run(const std::string& time, const std::string& days, const std::string& opt,
	const std::string& value, const std::string& list, const std::string& script, const std::string& source)
{
	O o;
	std::string out;
	int h = 77, m = 77;
	bool ok = o.ParseTime(time.c_str(), &h, &m);
	out += std::to_string(ok) + "," + std::to_string(h) + "," + std::to_string(m) + "|";
	int bits = 77;
	ok = o.ParseWeekDays(days.c_str(), &bits);
	out += std::to_string(ok) + "," + std::to_string(bits) + "|";
	ok = o.ValidateOptionName(opt.c_str(), value.c_str());
	out += std::to_string(ok) + "," + o.m_log + "|";
	CString co(opt.c_str()), cv(value.c_str());
	O::ConvertOldOption(co, cv);
	out += std::string(co) + "=" + std::string(cv) + "|";
	out += std::to_string(O::HasScript(list.c_str(), script.c_str())) + "|";
	out += std::to_string((int)o.ParseCategorySource(below(10) ? source.c_str() : nullptr));
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
			std::string time = below(4) == 0 ? std::string(pick(VALUES)) : below(2) ? std::to_string(below(30)) + ":" + std::to_string(below(70)) : chars("0123456789: *x-", 7);
			if (below(10) == 0) time = "*";
			std::string days = chars("1234567890,- x", 9);
			std::string opt = name();
			std::string value = below(3) ? pick(VALUES) : chars("ab 019-", 5);
			std::string list = chars("ab.py,; \tIi", 14), script = below(2) ? chars("ab.pyIi", 5) : std::string("a.py");
			std::string source = below(2) ? recase(below(2) ? "auto" : below(2) ? "nzbfile" : "feedfile") + chars("xI", 2) : chars("aeIfnz", 9);
			unsigned long long seed = state;
			std::string x = run<oldimpl::Options>(time, days, opt, value, list, script, source);
			state = seed;
			std::string y = run<newimpl::Options>(time, days, opt, value, list, script, source);
			state = seed;
			std::string z = run<fallbackimpl::Options>(time, days, opt, value, list, script, source);
			if (x != y || x != z)
			{
				fprintf(stderr, "mismatch in %s: time [%s] days [%s] opt [%s] value [%s] list [%s] script [%s] source [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
					argv[l], time.c_str(), days.c_str(), opt.c_str(), value.c_str(), list.c_str(), script.c_str(), source.c_str(), x.c_str(), y.c_str(), z.c_str());
				return 1;
			}
		}
		printf("%s: %ld rounds agree (reference %s)\n", argv[l], rounds, "''' + REFERENCE + r'''");
	}
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-options-") as temp:
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
    binary = temp / "options"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, *locales], check=True, env=env)
