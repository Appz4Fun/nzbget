#!/usr/bin/env python3
"""Compare CommandLineParser (rust/src/cmdline.rs with the C++ wrapper of
CommandLineParser.cpp), and its C++ fallback, with the pre-port C++ on
generated command lines: every field it exposes, the ID and name lists, the
options, and what it prints (ReportError writes to stdout).

All three parsers are compiled as separate translation units; the Rust
archive and other dependencies come from the build. getopt's own
messages, getopt globals, and the permuted/moved argument array are compared too.

Usage: cmdline_differential.py BUILD_DIR [ROUNDS]
Set CMDLINE_SHORT_ONLY=1 to test the build without getopt_long.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "02c80b7b"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "100000"
# Also exercise the HAVE_GETOPT_LONG=0 build, against the same host libc.
SHORT_ONLY = os.environ.get("CMDLINE_SHORT_ONLY") == "1"

header = (ROOT / "daemon/main/CommandLineParser.h").read_text()
old_header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/main/CommandLineParser.h"], cwd=ROOT, text=True)


def renamed(src, hdr, name, fallback=False):
    h = hdr.replace("private:", "public:").replace("COMMANDLINEPARSER_H", name.upper() + "_H").replace("CommandLineParser", name)
    body = src.replace("CommandLineParser", name).replace(f'#include "{name}.h"', h)
    if SHORT_ONLY:
        body = body.replace('#include "nzbget.h"', '#include "nzbget.h"\n#undef HAVE_GETOPT_LONG')
    return ("#undef NZBGET_USE_RUST\n" if fallback else "") + body


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/main/CommandLineParser.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/main/CommandLineParser.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]
# Exercise an independently configured Debug Rust archive with the same C++
# dependencies, without rebuilding the whole application a second time.
if os.environ.get("CMDLINE_RUST_ARCHIVE"):
    libs = [os.environ["CMDLINE_RUST_ARCHIVE"] if l.endswith("/libnzbget_rs.a") else l for l in libs]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]

decls = "\n".join(renamed("", h, n)[0:0] + h.replace("private:", "public:").replace("COMMANDLINEPARSER_H", n.upper() + "_H").replace("CommandLineParser", n)
                  for h, n in ((old_header, "OldCommandLineParser"), (header, "FallbackCommandLineParser")))

main = r'''
#include "nzbget.h"
#include "NString.h"
#define private public
#include "CommandLineParser.h"
#undef private
#include <string>
#include <vector>
#include <unistd.h>
#include <clocale>
''' + globals_block + r'''
#undef NZBGET_USE_RUST
''' + decls + r'''

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static const char* const ARGS[] = {"-c", "conf", "-n", "-p", "-s", "-D", "-v", "-h", "-o", "Opt=1", "-A", "F", "U",
	"T", "P", "I", "5", "C", "cat", "N", "name", "DK", "key", "DS", "10", "DM", "score", "all", "force", "x", "-L", "FR",
	"G", "GR", "O", "S", "H", "HA", "-P", "-U", "D", "-R", "1.5", "1e30", "nan", "-2", "-B", "dump", "trace", "webget",
	"verify", "-G", "0", "-T", "-C", "-E", "GN", "FN", "B", "A", "R", "DP", "SF", "K", "CP", "M", "I", "3", "00", "-5",
	"Opt=v", "-Q", "-O", "-V", "-W", "E", "W", "-K", "-S", "--help", "--configfile=x", "--option", "--append",
	"--edit=G", "--rate", "2", "--bogus", "-X", "file.nzb", "/abs.nzb", "http://x/y", "HTTP:/z", "https://z", "1,2-5",
	"3-1", "-", "1-", "a", "5,,6", " ", "--", "-ZZ", "-Ac", "-cA", "-oX", "-E", "-L", "-S", "relative/f.nzb", "", "(null)", "\xff", "1,5", "1.25", "0x1p2", "\t2", "2147483648"};

template <class P> static std::string dumpList(P& p)
{
	std::string s;
	for (CString& o : *p.GetOptionList()) s += std::string(o ? (const char*)o : "(null)") + ",";
	s += "|";
	for (int id : *p.GetEditQueueIdList()) s += std::to_string(id) + ",";
	s += "|";
	for (CString& n : *p.GetEditQueueNameList()) s += std::string(n ? (const char*)n : "(null)") + ",";
	return s;
}

static std::string str(const char* s) { return s ? s : "(null)"; }

template <class P> static std::string run(const std::vector<const char*>& args, int captureFd)
{
	fflush(stdout);
	int saved = dup(1);
	int savedErr = dup(2);
	ftruncate(captureFd, 0);
	lseek(captureFd, 0, SEEK_SET);
	dup2(captureFd, 1);
	dup2(captureFd, 2);
	std::vector<const char*> argv = args;
	P p((int)argv.size(), argv.data());
	fflush(stdout);
	fflush(stderr);
	dup2(saved, 1);
	dup2(savedErr, 2);
	close(savedErr);
	close(saved);
	char out[8192] = "";
	lseek(captureFd, 0, SEEK_SET);
	ssize_t n = read(captureFd, out, sizeof out - 1);
	out[n > 0 ? n : 0] = 0;
	std::string s = std::string("printed:") + out + "|";
	s += std::to_string(p.GetErrors()) + std::to_string(p.GetNoConfig()) + std::to_string(p.GetServerMode()) +
		std::to_string(p.GetDaemonMode()) + std::to_string(p.GetRemoteClientMode()) + std::to_string(p.GetPrintOptions()) +
		std::to_string(p.GetPrintVersion()) + std::to_string(p.GetPrintUsage()) + std::to_string(p.GetPauseDownload()) +
		std::to_string(p.GetAutoCategory()) + std::to_string(p.GetAddPaused()) + std::to_string(p.GetAddTop()) +
		std::to_string(p.GetTestBacktrace()) + std::to_string(p.GetWebGet()) + std::to_string(p.GetSigVerify()) + "|";
	s += std::to_string((int)p.GetClientOperation()) + "," + std::to_string(p.GetEditQueueAction()) + "," +
		std::to_string(p.GetEditQueueOffset()) + "," + std::to_string((int)p.GetMatchMode()) + "," +
		std::to_string(p.GetAddPriority()) + "," + std::to_string(p.GetAddDupeScore()) + "," + std::to_string(p.GetAddDupeMode()) + "," +
		std::to_string(p.GetSetRate()) + "," + std::to_string(p.GetLogLines()) + "," + std::to_string(p.GetWriteLogKind()) + "|";
	s += str(p.GetConfigFilename()) + "|" + str(p.GetEditQueueText()) + "|" + str(p.GetArgFilename()) + "|" +
		str(p.GetAddCategory()) + "|" + str(p.GetLastArg()) + "|" + str(p.GetAddNzbFilename()) + "|" + str(p.GetAddDupeKey()) + "|" +
		str(p.GetWebGetFilename()) + "|" + str(p.GetPubKeyFilename()) + "|" + str(p.GetSigFilename()) + "|" + dumpList(p);
	s += "|optind=" + std::to_string(optind) + "|optarg=" + str(optarg);
	for (CString& arg : p.m_args) s += "|argv=" + str(arg);
	return s;
}

void TestSinkExceptions();

int main(int argc, char** argv)
{
	TestSinkExceptions();
	if (getenv("CMDLINE_DELETED_CWD"))
	{
		char dir[] = "/tmp/nzbget-cmdline-cwd-XXXXXX";
		if (!mkdtemp(dir) || chdir(dir) || rmdir(dir)) return 2;
	}
	long rounds = atol(argv[1]);
	FILE* capture = tmpfile();
	int fd = fileno(capture);
	setlocale(LC_ALL, "");
	std::vector<std::vector<const char*>> cases;
	for (auto mode : {"F", "FN", "FR", "G", "GN", "GR", "O", "H"})
		for (auto action : {"T", "B", "P", "A", "R", "U", "D", "DP", "SF", "C", "K", "CP", "N", "M", "S", "O", "I", "+2", "-2", "0", "x"})
			for (auto value : {"1,3-5,7-6", "0", "00", "-1", "Opt=v", "[[:alpha:]]", "\\d+", "", " 2", "2147483647"})
				cases.push_back({"nzbget", "-E", mode, action, value, "1", "-c", "conf"});
	for (auto option : {"I", "C", "N", "DK", "DS", "DM"})
		for (auto value : {"0", "-2", "2147483648", "score", "all", "force", "", "\xff"})
			cases.push_back({"nzbget", "file.nzb", "-A", option, value, "-c", "conf"});
	for (long round = 0; round < rounds + (long)cases.size(); round++)
	{
		std::vector<const char*> args{"nzbget"};
		if (round < (long)cases.size()) args = cases[round];
		else { int n = below(15); for (int i = 0; i < n; i++) args.push_back(pick(ARGS)); }
		std::string a = run<OldCommandLineParser>(args, fd);
		std::string b = run<CommandLineParser>(args, fd);
		std::string c = run<FallbackCommandLineParser>(args, fd);
		if (a != b || a != c)
		{
			std::string line;
			for (const char* x : args) line += std::string("[") + x + "] ";
			fprintf(stdout, "mismatch: %s\nold:      %s\nrust:     %s\nfallback: %s\n", line.c_str(), a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	printf("%ld command lines agree (reference %s)\n", rounds + (long)cases.size(), "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-cmdline-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    # Inject failures inside the actual C++ exception barrier in this test TU.
    # Ordinary differential runs leave the hook disabled.
    instrumented = "static int failAt = 0, calls = 0;\n" + new_src.replace(
        "f(sink->parser);",
        'if (failAt && ++calls == failAt) throw std::runtime_error("injected");\n\t\t\tf(sink->parser);')
    instrumented += r'''
void TestSinkExceptions()
{
    for (auto args : {
        std::vector<const char*>{"nzbget", "-A", "N", "name", "-c", "conf", "-o", "X=1", "-E", "G", "D", "1,3-5"},
        std::vector<const char*>{"nzbget", "-E", "GN", "D", "name"}})
    {
        for (failAt = 1; failAt < 100; ++failAt)
        {
            calls = 0;
            try
            {
                CommandLineParser parser((int)args.size(), args.data());
                if (calls != failAt - 1) std::abort();
                break;
            }
            catch (const std::runtime_error& e)
            {
                if (std::string(e.what()) != "injected" || calls != failAt) std::abort();
            }
        }
        if (failAt == 100) std::abort();
    }
    failAt = 0;
}
'''
    (temp / "new.cpp").write_text(renamed(instrumented, header, "CommandLineParser"))
    (temp / "old.cpp").write_text(renamed(old_src, old_header, "OldCommandLineParser"))
    (temp / "fallback.cpp").write_text(renamed(new_src, header, "FallbackCommandLineParser", fallback=True))
    binary = temp / "cmdline"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "old.cpp"),
                        str(temp / "fallback.cpp"), str(temp / "new.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS], check=True)
        deep = temp
        while len(str(deep)) < 1100:
            deep /= "directory" * 10
            deep.mkdir(exist_ok=True)
        subprocess.run([str(binary), "2000"], check=True, cwd=deep)
        subprocess.run([str(binary), "2000"], check=True, env={**os.environ, "CMDLINE_DELETED_CWD": "1"})
        # Locale-sensitive libc conversion and POSIX getopt ordering.
        for env in ({"LC_ALL": "C"}, {"LC_ALL": "en_DK.utf8"}, {"POSIXLY_CORRECT": "1"}):
            if "LC_ALL" in env:
                import locale
                try:
                    locale.setlocale(locale.LC_ALL, env["LC_ALL"])
                except locale.Error:
                    continue
            subprocess.run([str(binary), "2000"], check=True, env={**os.environ, **env})
