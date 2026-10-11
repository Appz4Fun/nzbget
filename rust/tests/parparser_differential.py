#!/usr/bin/env python3
"""Compare ParParser's name checks (rust/src/parparser.rs with the C++
wrappers of ParParser.cpp), and their C++ fallback, with the pre-port C++:
ParseParFilename (result, base length, block count) and SameParCollection on
generated and mutated par2 names, confirmed or not, in the C, C.UTF-8 and
tr_TR.ISO8859-9 locales (tolower folds 'I' differently there). A generated
locale also exercises NUL-producing folds and the distinction between EOF
and unsigned byte 255. Both C++ char signedness modes, bounded reads, NULL
outputs and aliased outputs are checked. Requires a Unix Makefiles build.
Run this script under chrt -i 0 nice -n 19 to keep compiles/tests at idle priority.

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
#include "nzbget_rs.h"
#include <clocale>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>
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

template <class P> static std::string run(const char* a, const char* b, bool confirmed)
{
	int len = 77, blocks = 77;
	bool ok = P::ParseParFilename(a, confirmed, &len, &blocks);
	int len2 = 55;
	bool ok2 = P::ParseParFilename(b, confirmed, &len2, nullptr);
	bool same = P::SameParCollection(a, b, confirmed);
    int only_blocks = 33, aliased = 44;
    bool ok3 = P::ParseParFilename(a, confirmed, nullptr, &only_blocks);
    bool ok4 = P::ParseParFilename(a, confirmed, &aliased, &aliased);
    bool ok5 = P::ParseParFilename(a, confirmed, nullptr, nullptr);
	return std::to_string(ok) + "," + std::to_string(len) + "," + std::to_string(blocks) + "|" + std::to_string(ok2) + "," +
		std::to_string(len2) + "|" + std::to_string(same) + "|" + std::to_string(ok3) + "," +
        std::to_string(only_blocks) + "|" + std::to_string(ok4) + "," + std::to_string(aliased) + "|" + std::to_string(ok5);
}

static bool check(const std::string& a, const std::string& b, bool confirmed, const char* locale)
{
    std::string x = run<oldimpl::ParParser>(a.c_str(), b.c_str(), confirmed);
    std::string y = run<::ParParser>(a.c_str(), b.c_str(), confirmed);
    std::string z = run<fallbackimpl::ParParser>(a.c_str(), b.c_str(), confirmed);
    if (x == y && x == z) return true;
    fprintf(stderr, "mismatch in %s: [%s] [%s] confirmed %d\nold: %s\nrust: %s\nfallback: %s\n",
        locale, a.c_str(), b.c_str(), confirmed, x.c_str(), y.c_str(), z.c_str());
    return false;
}

static int fold(int b) { return tolower(b); }

static bool ffi_checks()
{
    int len = 11, blocks = 22;
    if (nzbget_rs_parse_par_filename(nullptr, 1, &len, &blocks, fold) != 0 || len != 11 || blocks != 22 ||
        nzbget_rs_parse_par_filename("a.par2", 1, &len, &blocks, nullptr) != 0 || len != 11 || blocks != 22 ||
        nzbget_rs_same_par_collection(nullptr, "a.par2", 0, fold) != 0 ||
        nzbget_rs_same_par_collection("a.par2", nullptr, 0, fold) != 0 ||
        nzbget_rs_same_par_collection("a.par2", "a.par2", 0, nullptr) != 0 ||
        nzbget_rs_parse_par_filename("a.vol+2.par2", -7, &len, &blocks, fold) != 1 || len != 1 || blocks != -1)
        return false;

    // Like strncpy in BString<1024>, neither entry point may read byte 1023.
    long page = sysconf(_SC_PAGESIZE);
    if (page < 1024) return false;
    char* mem = static_cast<char*>(mmap(nullptr, page * 2, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    if (mem == MAP_FAILED) return false;
    if (mprotect(mem + page, page, PROT_NONE)) { munmap(mem, page * 2); return false; }
    char* name = mem + page - 1023;
    memset(name, 'a', 1023);
    memcpy(name + 1018, ".par2", 5);
    bool ok = true;
    for (bool confirmed : {false, true})
    {
        auto old = run<oldimpl::ParParser>(name, name, confirmed);
        ok = ok && old == run<::ParParser>(name, name, confirmed) &&
            old == run<fallbackimpl::ParParser>(name, name, confirmed);
    }
    // A very short input at the page boundary must stop on its first NUL.
    mem[page - 1] = 0;
    ok = ok && nzbget_rs_parse_par_filename(mem + page - 1, 0, &len, &blocks, fold) == 0;
    munmap(mem, page * 2);
    return ok;
}

int main(int argc, char** argv)
{
    if (!ffi_checks()) { fprintf(stderr, "FFI regression failed\n"); return 1; }
	long rounds = atol(argv[1]);
	for (int l = 2; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
        std::vector<std::string> cases = {"", ".par2", "a.par2", "a.par2Xjunk", "a.vol1+X8.par2",
            "a\xffpar2", "a.vol1+2147483648.par2", "a.vol1+9223372036854775808.par2",
            "a.vol1+-9223372036854775809.par2", "a.vol1+-2147483649.par2", "a.vol1+\r\n\v\f 8.par2", "a.vol1+  +12junk.par2", "a.vol1+\t-12.par2",
            "a.vol1-2+3.par2", "a.vol+2-3.par2", "a.vol-2+3.par2", "a.vol+.par2", "a.vol-.par2",
            "a.vol1+.par2", "a.vol1+999999999999999999999999999999999999.par2", "a.vol1-.par2", ".vol+1.par2", "a.vol1+2.x.par2", "a.par2x.par2tail"};
        // ".vol-NN" (a volume numbered without a block count): blocks must stay -1,
        // the par code estimates the count from the size then (c722c38b)
        // (a '+' is looked for first: ".vol-+3" counts 3 and ".vol-06+07" 7, compared below)
        cases.push_back("Movie.vol-+3.par2");
        cases.push_back("Movie.vol-06+07.par2");
        for (const char* vol : {"Movie.vol-06.par2", "Movie.VOL-6.PAR2", "Movie.vol-06.par2.1", "a.b.vol-123.par2", "x.vol-.par2"})
        {
            cases.push_back(vol);
            int len = 0, blocks = 0;
            bool unconfirmed = strstr(vol, ".par2.") != nullptr;
            if (!::ParParser::ParseParFilename(vol, !unconfirmed, &len, &blocks) || blocks != -1)
            {
                fprintf(stderr, "%s: blocks %d, expected -1\n", vol, blocks);
                return 1;
            }
        }
        for (int n = 1008; n <= 1025; ++n)
            for (const char* tail : {".par2", ".par2trailing", ".vol1+2.par2", ".par2.par2"})
                cases.push_back(std::string(n, 'a') + tail);
        for (int byte = 0; byte <= 255; ++byte)
            for (const char* text : {"a?.par2", "a.?ar2", "a.p?r2", "a.pa?2", "a.par?",
                                    "a.?ol1+2.par2", "a.v?l1+2.par2", "a.vo?1+2.par2", "a.vol1+?2.par2"})
            {
                std::string s = text;
                s[s.find('?')] = (char)byte;
                cases.push_back(s);
            }
        for (const auto& a : cases)
            for (bool confirmed : {false, true})
                for (const auto& b : {a, std::string("a.par2")})
                    if (!check(a, b, confirmed, argv[l])) return 1;
		for (long round = 0; round < rounds; round++)
		{
			std::string a = name(), b = below(3) ? name() : a;
			bool confirmed = below(2);
            if (!check(a, b, confirmed, argv[l])) return 1;
		}
		printf("%s: %ld rounds agree (reference %s)\n", argv[l], rounds, "''' + REFERENCE + r'''");
        fflush(stdout);
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
        ctype = Path("/usr/share/i18n/locales/i18n_ctype").read_text()
        ctype = ctype[ctype.index("LC_CTYPE\n"):ctype.index("END LC_CTYPE") + len("END LC_CTYPE")]
        ctype = ctype.replace("tolower /", "tolower (<U00FF>,<U002E>);/")
        ctype = ctype.replace("(<U0058>,<U0078>)", "(<U0058>,<U0000>)")
        custom = Path("/usr/share/i18n/locales/en_US").read_text()
        custom = re.sub(r"LC_CTYPE\n.*?END LC_CTYPE", lambda _: ctype, custom, flags=re.S)
        source = temp / "custom"
        source.write_text(custom)
        subprocess.run(["localedef", "--no-archive", "-i", str(source), "-f", "ISO-8859-1",
                        str(locdir / "custom")], check=True)
        locales.append("custom")
    (temp / "main.cpp").write_text(main)
    binary = temp / "parparser"
    # Recompile the actual wrapper (without the build's PCH) so that the C++
    # char flags also apply there, while linking the same Rust archive.
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fsigned-char"],
                  ["-O0", "-g", "-funsigned-char"], ["-O3", "-fsigned-char"], ["-O3", "-funsigned-char"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(ROOT / "daemon/postprocess/ParParser.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, *locales], check=True, env=env)
