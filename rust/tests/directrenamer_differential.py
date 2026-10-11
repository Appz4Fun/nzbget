#!/usr/bin/env python3
"""Compare DirectRenamer's new names (rust/src/directrenamer.rs with the C++
wrappers of DirectRenamer.cpp), and their C++ fallback, with the pre-port
C++: BuildNewRegularName on random par2 hash lists, BuildNewParName against
random sets of files already in the destination directory (the new name and
the volume counter), and NeedRenamePars on random downloads of par2 and
other files, in progress and completed - in several locales, with signed and
unsigned char.

Each version's functions are compiled into their own namespace from their
source, as members of a stand-in class with DirectRenamer's types. The old
ParParser and Util helpers are compiled independently for the oracle and
fallback. Scripted callbacks cover exceptions and paths, and a C++ numeric
locale checks stringstream formatting separately from C ctype locales.

Usage: directrenamer_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "20000"
FUNCTIONS = ("std::string DirectRenamer::BuildNewRegularName(", "std::string DirectRenamer::BuildNewParName(",
             "bool DirectRenamer::NeedRenamePars(", "void DirectRenamer::CollectPars(")


def definitions(src, signatures=FUNCTIONS):
    out = []
    for sig in signatures:
        j = src.index(sig)
        out.append(src[j:src.index("\n}\n", j) + 3])
    return "\n".join(out)


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/queue/DirectRenamer.cpp"], cwd=ROOT, text=True)
old_parser = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/ParParser.cpp"], cwd=ROOT, text=True)
old_util = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
# The oracle must not resolve these calls to the Rust-backed library.
oracle_helpers = r'''
class ParParser {
public:
    static bool ParseParFilename(const char*, bool, int*, int*);
    static bool SameParCollection(const char*, const char*, bool);
};
class Util : public ::Util {
public:
    static bool EndsWith(std::string_view, std::string_view, bool);
    static bool EndsWith(const char*, const char*, bool);
    static bool StrCaseCmp(std::string_view, std::string_view);
};
''' + definitions(old_parser, ("bool ParParser::SameParCollection(", "bool ParParser::ParseParFilename(")) + definitions(
    old_util, ("bool Util::EndsWith(std::string_view", "bool Util::EndsWith(const char*", "bool Util::StrCaseCmp("))
new_src = (ROOT / "daemon/queue/DirectRenamer.cpp").read_text()
start = new_src.index("#ifdef NZBGET_USE_RUST\nstd::string DirectRenamer::BuildNewRegularName(")
middle = new_src.index("\n#else\n", start)
end = new_src.index("\n#endif\n", middle)
collect = new_src[new_src.index(FUNCTIONS[3]):]
rust_src = new_src[start:middle] + "\n" + collect
fallback_src = new_src[middle:end] + "\n" + collect

STAND_IN = r'''
class DirectRenamer
{
public:
	typedef ::DirectRenamer::FileHash FileHash;
	typedef ::DirectRenamer::FileHashList FileHashList;
	typedef ::DirectRenamer::ParFile ParFile;
	typedef ::DirectRenamer::ParFileList ParFileList;
	bool NeedRenamePars(NzbInfo* nzbInfo);
	void CollectPars(NzbInfo* nzbInfo, ParFileList* parFiles);
	std::string BuildNewRegularName(const char* oldName, FileHashList* parHashes, const char* hash16k);
	std::string BuildNewParName(const char* oldName, const char* destDir, const char* setId, int& vol);
};
'''

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
#include "DirectRenamer.h"
#include "DownloadInfo.h"
#include "FileSystem.h"
#include "ParParser.h"
#include "nzbget_rs.h"
#include <algorithm>
#include <clocale>
#include <cstddef>
#include <exception>
#include <iomanip>
#include <memory>
#include <locale>
#include <stdexcept>
#include <sstream>
#include <string>
#include <vector>
''' + globals_block + r'''
// A scripted FileExists also records paths and injects exceptions before
// the Rust callback boundary; ordinary randomized cases use the filesystem.
static bool scripted = false;
static int collisions = 0, throwAt = -1;
static std::vector<std::string> paths;
class FileSystemProbe : public FileSystem {
public:
    static bool FileExists(const char* path) {
        if (!scripted) return ::FileSystem::FileExists(path);
        int index = paths.size();
        paths.emplace_back(path);
        if (index == throwAt) throw std::runtime_error("FileExists injected exception");
        return index < collisions;
    }
};
namespace oldimpl { using FileSystem = FileSystemProbe;
''' + oracle_helpers + STAND_IN + definitions(old_src) + r'''}
namespace newimpl { using FileSystem = FileSystemProbe;
''' + STAND_IN + definitions(rust_src) + r'''}
namespace fallbackimpl { using FileSystem = FileSystemProbe;
''' + oracle_helpers + STAND_IN + definitions(fallback_src) + r'''}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static const char* PIECES[] = {"a", "A", "b", "B", ".vol", ".VOL", ".Vol", ".par2", ".PAR2", ".Par2", ".par", "+", "-",
	"01", "1", "+02", ".", "x", "X", "y", "Y", "z", "Z", "I", "i", "\xe9", "\xc9", "\xfd", "\xdd", "\xff", "\xcc", " "};

static std::string name(int min, int max)
{
	std::string s;
	for (int n = min + below(max - min + 1); n > 0; --n) s += PIECES[below(sizeof(PIECES) / sizeof(*PIECES))];
	return s;
}

static std::string parName()
{
	static const char* ENDS[] = {".par2", ".PAR2", ".vol1+2.par2", ".vol01+02.PAR2", ".VOL1-2.par2", ".vol+3.par2", ".par2.1", ".par", ""};
	return name(0, 3) + ENDS[below(sizeof(ENDS) / sizeof(*ENDS))];
}

static const char* SETS[] = {"S", "s", "T", "0123456789ABCDEF0123456789ABCDEF", "\xe9"};
static int failures = 0;

static void fail(const char* what, const std::string& a, const std::string& b, const std::string& c)
{
	fprintf(stderr, "%s mismatch\n  old:      [%s]\n  rust:     [%s]\n  fallback: [%s]\n", what, a.c_str(), b.c_str(), c.c_str());
	if (++failures > 5) exit(1);
}

static void regular()
{
	DirectRenamer::FileHashList hashes;
	static const char* HASHES[] = {"H1", "H2", "h1", "0123456789ABCDEF0123456789ABCDEF"};
	for (int n = below(7); n > 0; --n)
	{
		std::string filename = name(1, 5);
		hashes.emplace_back(filename.c_str(), HASHES[below(4)]);
	}
	const char* hash16k = below(6) == 0 ? "" : HASHES[below(4)];
	std::string oldName = name(0, 5);
	if (!hashes.empty() && below(2))
	{
		// often the name the hash gives, in another case (ASCII, Latin-1, and
		// letters only some locales fold, like I and i in Turkish)
		DirectRenamer::FileHash& parHash = hashes[below(hashes.size())];
		oldName = parHash.GetFilename();
		if (below(3)) hash16k = parHash.GetHash();
		for (char& ch : oldName)
		{
			if (below(2) && ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (unsigned char)ch >= 0xc0)) ch ^= 0x20;
		}
	}
	std::string a = oldimpl::DirectRenamer().BuildNewRegularName(oldName.c_str(), &hashes, hash16k);
	std::string b = newimpl::DirectRenamer().BuildNewRegularName(oldName.c_str(), &hashes, hash16k);
	std::string c = fallbackimpl::DirectRenamer().BuildNewRegularName(oldName.c_str(), &hashes, hash16k);
	if (a != b || a != c) fail("BuildNewRegularName", a, b, c);
}

static void par(const std::string& dir)
{
	std::string oldName = below(4) ? name(0, 3) + parName() : name(0, 6);
	const char* setId = SETS[below(sizeof(SETS) / sizeof(*SETS))];
	static const int VOLS[] = {1, 1, 1, 2, 7, 98, 99, 100, 998, 999, 1000, 12345, 0, -1, -3, -100};
	int vol = VOLS[below(sizeof(VOLS) / sizeof(*VOLS))];

	// files already in the destination: the reused suffix and the first volumes
	DirBrowser browser(dir.c_str());
	std::vector<std::string> existing;
	while (const char* filename = browser.Next()) existing.push_back(filename);
	for (const std::string& filename : existing) FileSystem::DeleteFile((dir + PATH_SEPARATOR + filename).c_str());
	const char* suffix = strstr(oldName.c_str(), ".vol");
	for (int n = below(5); n > 0; --n)
	{
		std::string taken;
		if (suffix && below(3) == 0)
		{
			taken = std::string(below(4) ? setId : SETS[below(sizeof(SETS) / sizeof(*SETS))]) + suffix;
		}
		else
		{
			std::stringstream ss;
			ss << setId << ".vol" << std::setfill('0') << std::setw(3) << vol + below(4) << (below(6) ? "+01.PAR2" : "+01.par2");
			taken = ss.str();
		}
		if (FILE* file = fopen((dir + PATH_SEPARATOR + taken).c_str(), "wb")) fclose(file);
	}

	int va = vol, vb = vol, vc = vol;
	std::string a = oldimpl::DirectRenamer().BuildNewParName(oldName.c_str(), dir.c_str(), setId, va);
	std::string b = newimpl::DirectRenamer().BuildNewParName(oldName.c_str(), dir.c_str(), setId, vb);
	std::string c = fallbackimpl::DirectRenamer().BuildNewParName(oldName.c_str(), dir.c_str(), setId, vc);
	a += " vol " + std::to_string(va); b += " vol " + std::to_string(vb); c += " vol " + std::to_string(vc);
	if (a != b || a != c) fail(("BuildNewParName " + oldName).c_str(), a, b, c);
}

static void need()
{
	NzbInfo nzbInfo;
	int id = 1;
	for (int n = below(6); n > 0; --n)
	{
		std::unique_ptr<FileInfo> fileInfo = std::make_unique<FileInfo>(id++);
		bool parFile = below(4) != 0;
		fileInfo->SetFilename(parFile && below(8) ? parName() : name(1, 5));
		fileInfo->SetParFile(parFile);
		fileInfo->SetParSetId(SETS[below(3)]);
		fileInfo->SetNzbInfo(&nzbInfo);
		nzbInfo.GetFileList()->Add(std::move(fileInfo));
	}
	for (int n = below(5); n > 0; --n)
	{
		bool parFile = below(4) != 0;
		nzbInfo.GetCompletedFiles()->emplace_back(id++, parFile && below(8) ? parName() : name(1, 5), "",
			CompletedFile::cfSuccess, 0, parFile, "", SETS[below(3)]);
	}
	bool a = oldimpl::DirectRenamer().NeedRenamePars(&nzbInfo);
	bool b = newimpl::DirectRenamer().NeedRenamePars(&nzbInfo);
	bool c = fallbackimpl::DirectRenamer().NeedRenamePars(&nzbInfo);
	if (a != b || a != c)
	{
		std::string files;
		DirectRenamer::ParFileList parFiles;
		oldimpl::DirectRenamer().CollectPars(&nzbInfo, &parFiles);
		for (DirectRenamer::ParFile& parFile : parFiles) files += std::string(" [") + parFile.GetFilename() + "/" + parFile.GetSetId() + "]";
		fail(("NeedRenamePars" + files).c_str(), std::to_string(a), std::to_string(b), std::to_string(c));
	}
}

static void edges()
{
    scripted = true;
    for (const char* oldName : {"", "a.vol", "a.VOL1+2.par2", "a.vol.par2", "a.vol1.par2.x", "a.vol.b.vol1.PAR2"})
    for (const char* dir : {"", "/d/", "relative", "C:\\dest"})
    for (int start : {-1000, -10, -1, 0, 99, 999, 1000, 2147483644})
    for (int stop : {-1, 0, 2})
    {
        collisions = 2;
        throwAt = stop;
        auto run = [&](auto impl) {
            paths.clear();
            int vol = start;
            std::string result;
            try { result = impl.BuildNewParName(oldName, dir, "S", vol); }
            catch (const std::runtime_error& e) { result = e.what(); }
            result += " vol " + std::to_string(vol);
            for (const auto& path : paths) result += " [" + path + "]";
            return result;
        };
        auto a = run(oldimpl::DirectRenamer());
        auto b = run(newimpl::DirectRenamer());
        auto c = run(fallbackimpl::DirectRenamer());
        if (a != b || a != c) fail("scripted BuildNewParName", a, b, c);
    }
    scripted = false;
    for (size_t len : {0, 1, 1010, 1018, 1022, 1023, 1024, 4096})
    for (const char* suffix : {".par2", ".vol1+2.par2", ".vol-2.par2", ".par2X.PAR2", "\xffpar2"})
    {
        NzbInfo nzbInfo;
        std::string prefix(len, 'a');
        nzbInfo.GetCompletedFiles()->emplace_back(1, prefix + ".par2", "", CompletedFile::cfSuccess, 0, true, "", "S");
        nzbInfo.GetCompletedFiles()->emplace_back(2, prefix + suffix, "", CompletedFile::cfSuccess, 0, true, "", "S");
        bool a = oldimpl::DirectRenamer().NeedRenamePars(&nzbInfo);
        bool b = newimpl::DirectRenamer().NeedRenamePars(&nzbInfo);
        bool c = fallbackimpl::DirectRenamer().NeedRenamePars(&nzbInfo);
        if (a != b || a != c) fail("long NeedRenamePars", std::to_string(a), std::to_string(b), std::to_string(c));
    }
}

class GroupedNumbers : public std::numpunct<char> {
    char do_thousands_sep() const override { return ','; }
    std::string do_grouping() const override { return "\3"; }
};

// A stream must retain facet state between collisions, and the returned
// name must retain embedded NULs even though FileExists sees a C string.
class StatefulNumbers : public std::num_put<char> {
    iter_type do_put(iter_type out, std::ios_base& stream, char_type, long value) const override {
        static const int slot = std::ios_base::xalloc();
        std::string text = std::to_string(++stream.iword(slot)) + ':' + std::to_string(value);
        text += std::string("\0tail", 5);
        stream.width(0);
        return std::copy(text.begin(), text.end(), out);
    }
};

// ostream normally swallows a facet exception and sets badbit. Clearing
// the stream for the next candidate must preserve that original behavior.
class ThrowingNumbers : public std::num_put<char> {
    iter_type do_put(iter_type, std::ios_base&, char_type, long) const override {
        throw std::runtime_error("num_put injected exception");
    }
};

static void ffiEdges()
{
    auto check = [](bool ok) { if (!ok) throw std::runtime_error("FFI edge failed"); };
    check(nzbget_rs_direct_regular_name(nullptr, nullptr, 99, nullptr, nullptr) == -1);
    check(nzbget_rs_direct_need_rename_pars(nullptr, 99, ParParser::FilenameFold) == 0);
    NzbgetRsParName nullName = {nullptr, nullptr};
    check(nzbget_rs_direct_need_rename_pars(&nullName, 1, ParParser::FilenameFold) == 1);
    check(nzbget_rs_direct_need_rename_pars(&nullName, 1, nullptr) == 0);
    NzbgetRsBuf name = nzbget_rs_direct_par_name(nullptr, nullptr, nullptr, '\\', nullptr, nullptr, nullptr, nullptr);
    check(std::string(name.data, name.len) == ".vol001+01.PAR2");
    check(name.data[name.len] == 0);
    nzbget_rs_free(name);
    int vol = 7;
    auto stop = [](void*, int, const char**, size_t*) { return 0; };
    name = nzbget_rs_direct_par_name("x.par2", "", "S", '/', &vol, nullptr, stop, nullptr);
    check(name.len == 0 && vol == 7);
    nzbget_rs_free(name);
    auto format = [](void*, int, const char** data, size_t* len) {
        *data = "A\0B";
        *len = 3;
        return 1;
    };
    name = nzbget_rs_direct_par_name("x.par2", "", "S", '/', &vol, nullptr, format, nullptr);
    check(std::string(name.data, name.len) == std::string("A\0B", 3) && vol == 8);
    nzbget_rs_free(name);
    int calls = 0;
    auto at = [](void* ctx, size_t index, const char** filename, const char** hash) {
        ++*static_cast<int*>(ctx);
        *filename = index == 0 ? "A" : "B";
        *hash = "H";
    };
    check(nzbget_rs_direct_regular_name("A", "H", 10, at, &calls) == -1 && calls == 1);
    calls = 0;
    check(nzbget_rs_direct_regular_name("A", nullptr, 10, at, &calls) == -1 && calls == 0);
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	std::string dir = argv[2];
	for (int l = 3; l < argc; ++l)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
        ffiEdges();
        edges();
		for (long round = 0; round < rounds; round++)
		{
			regular();
			par(dir);
			need();
		}
		printf("%s: %ld rounds agree (reference %s)\n", argv[l], rounds, "''' + REFERENCE + r'''");
	}
    std::locale saved = std::locale::global(std::locale(std::locale::classic(), new GroupedNumbers));
    edges();
    std::locale::global(std::locale(std::locale::classic(), new StatefulNumbers));
    edges();
    std::locale::global(std::locale(std::locale::classic(), new ThrowingNumbers));
    edges();
    std::locale::global(saved);
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-directrenamer-") as temp:
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
        # A locale whose tolower turns 'X' into a NUL and folds 'Y' and 'Z' to
        # other letters (strcasecmp and ParParser's fold both follow it).
        ctype = Path("/usr/share/i18n/locales/i18n_ctype").read_text()
        ctype = ctype[ctype.index("LC_CTYPE\n"):ctype.index("END LC_CTYPE") + len("END LC_CTYPE")]
        ctype = ctype.replace("tolower /", "tolower (<U00FF>,<U002E>);/")
        ctype = ctype.replace("(<U0058>,<U0078>)", "(<U0058>,<U0000>)")
        ctype = ctype.replace("(<U0059>,<U0079>)", "(<U0059>,<U0050>)")
        ctype = ctype.replace("(<U005A>,<U007A>)", "(<U005A>,<U0056>)")
        custom = Path("/usr/share/i18n/locales/en_US").read_text()
        custom = re.sub(r"LC_CTYPE\n.*?END LC_CTYPE", lambda _: ctype, custom, flags=re.S)
        source = temp / "custom"
        source.write_text(custom)
        subprocess.run(["localedef", "--no-archive", "-i", str(source), "-f", "ISO-8859-1",
                        str(locdir / "custom")], check=True)
        locales.append("custom")
    (temp / "main.cpp").write_text(main)
    dest = temp / "dest"
    dest.mkdir()
    binary = temp / "directrenamer"
    # Compile the actual translation units too: DISABLE_PARCHECK and the
    # fallback must build, and ParParser's fold must see the test's char flags.
    for defines in (["-UNZBGET_USE_RUST"], ["-DDISABLE_PARCHECK"], ["-DDISABLE_PARCHECK", "-UNZBGET_USE_RUST"]):
        includes = shlex.split(get("CXX_INCLUDES"))
        if "-DDISABLE_PARCHECK" in defines:
            includes = [flag for flag in includes if "par2-turbo" not in flag]
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *defines, *includes, "-fsyntax-only", str(ROOT / "daemon/queue/DirectRenamer.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fsigned-char"],
                  ["-O2", "-funsigned-char"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        # libstdc++ installs our derived numpunct facet using RTTI.
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-frtti", "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(ROOT / "daemon/postprocess/ParParser.cpp"),
                        "-o", str(binary), *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]],
                       check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS,
                        str(dest), *locales], check=True, env=env)
