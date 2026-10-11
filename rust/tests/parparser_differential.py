#!/usr/bin/env python3
"""Compare ParParser's name checks (rust/src/parparser.rs with the C++
wrappers of ParParser.cpp), and their C++ fallback, with the pre-port C++:
ParseParFilename (result, base length, block count) and SameParCollection on
generated and mutated par2 names, confirmed or not, in the C, C.UTF-8 and
tr_TR.ISO8859-9 locales (tolower folds 'I' differently there).

Usage: parparser_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "300000"

SIGS = [
    "bool ParParser::SameParCollection(const char* filename1, const char* filename2, bool confirmedFilenames)",
    "bool ParParser::ParseParFilename(const char* parFilename, bool confirmedFilename, int* baseNameLen, int* blocks)",
]


def bodies(src):
    out = []
    for sig in SIGS:
        i = src.rindex(sig + "\n{")
        out.append(src[i:src.index("\n}\n", i) + 3])
    return "".join(out)


STANDIN = r'''
class ParParser
{
public:
	static bool SameParCollection(const char* filename1, const char* filename2, bool confirmedFilenames);
	static bool ParseParFilename(const char* parFilename, bool confirmedFilename, int* baseNameLen, int* blocks);
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/ParParser.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/postprocess/ParParser.cpp").read_text()

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
#include "ParParser.h"
#include <clocale>
#include <string>
''' + globals_block + r'''
namespace oldimpl {
''' + STANDIN + bodies(old_src) + r'''
}
namespace fallbackimpl {
''' + STANDIN + bodies(new_src) + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static const char* const BASES[] = {"Movie", "movie", "MOVIE", "I", "i", "Il", "a.b", "", "x", "\xc9t\xe9", "\xdd", "\xfd", "name with space"};
static const char* const VOLS[] = {"", ".vol00+01", ".VOL07+08", ".vol-06", ".vol+", ".vol-", ".vol", ".volx", ".vol1", ".vol12+", ".vol99999999999+1",
	".vol07-08", ".v", ".Vol3+4", ".vOl-"};
static const char* const EXTS[] = {".par2", ".PAR2", ".Par2", ".par", ".par2.1", ".par2.par2", ".par2x", "par2", ".par2.", ".PAR2.bak", ""};

static std::string name()
{
	std::string s = std::string(pick(BASES)) + pick(VOLS) + pick(EXTS);
	if (below(20) == 0) s = std::string(1020 + below(10), 'a') + ".par2";
	int m = below(4) == 0 ? 1 + below(3) : 0;
	for (int i = 0; i < m && !s.empty(); i++)
	{
		size_t at = below((int)s.size());
		switch (below(3))
		{
			case 0: s[at] = (char)(1 + below(255)); break;
			case 1: s.erase(at, 1); break;
			default: s.insert(at, below(2) ? "." : "I");
		}
	}
	return s;
}

template <class P> static std::string run(const std::string& a, const std::string& b, bool confirmed)
{
	int len = 77, blocks = 77;
	bool ok = P::ParseParFilename(a.c_str(), confirmed, &len, &blocks);
	int len2 = 55;
	bool ok2 = P::ParseParFilename(b.c_str(), confirmed, &len2, nullptr);
	bool same = P::SameParCollection(a.c_str(), b.c_str(), confirmed);
	return std::to_string(ok) + "," + std::to_string(len) + "," + std::to_string(blocks) + "|" + std::to_string(ok2) + "," +
		std::to_string(len2) + "|" + std::to_string(same);
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	for (int l = 2; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		for (long round = 0; round < rounds; round++)
		{
			std::string a = name(), b = below(3) ? name() : a;
			bool confirmed = below(2);
			std::string x = run<oldimpl::ParParser>(a, b, confirmed);
			std::string y = run<::ParParser>(a, b, confirmed);
			std::string z = run<fallbackimpl::ParParser>(a, b, confirmed);
			if (x != y || x != z)
			{
				fprintf(stderr, "mismatch in %s: [%s] [%s] confirmed %d\nold:      %s\nrust:     %s\nfallback: %s\n",
					argv[l], a.c_str(), b.c_str(), confirmed, x.c_str(), y.c_str(), z.c_str());
				return 1;
			}
		}
		printf("%s: %ld rounds agree (reference %s)\n", argv[l], rounds, "''' + REFERENCE + r'''");
	}
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-parparser-") as temp:
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
    binary = temp / "parparser"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, *locales], check=True, env=env)
