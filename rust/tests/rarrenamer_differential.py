#!/usr/bin/env python3
"""Compare RarRenamer's renaming (rust/src/rarrenamer.rs with the C++
wrapper of RarRenamer.cpp), and its C++ fallback, with the pre-port C++: the
same directories of real RAR3/RAR5 test volumes (plain and encrypted) under
random, obfuscated, partly renamed or colliding names, with and without the
password, comparing the files each leaves (names and contents), the messages,
the renames registered and the renamed count. Synthetic metadata cases also
compare exact regex/check/rename traces, bounded strings and exceptions.

The pre-port and fallback renamers are compiled as separate translation units
with the class renamed; the Rust-backed one is the build's.

Usage: rarrenamer_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "200"

header = (ROOT / "daemon/postprocess/RarRenamer.h").read_text()
old_header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/RarRenamer.h"], cwd=ROOT, text=True)


def renamed(src, hdr, prefix, fallback=False):
    def r(text):
        return re.sub(r"\bRarRenamer\b", prefix + "RarRenamer", text).replace("RARRENAMER_H", prefix.upper() + "RARRENAMER_H")
    body = r(src).replace(f'#include "{prefix}RarRenamer.h"', r(hdr))
    return ("#undef NZBGET_USE_RUST\n" if fallback else "") + body


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/RarRenamer.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/postprocess/RarRenamer.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]
volumes = sorted(str(p) for p in (ROOT / "tests/testdata").rglob("*") if re.search(r"\.(rar|r\d\d)$", p.name))

decls = "\n".join(re.sub(r"\bRarRenamer\b", p + "RarRenamer", h).replace("RARRENAMER_H", p.upper() + "RARRENAMER_H")
                  for h, p in ((old_header, "Old"), (header, "Fallback")))

main = r'''
#include "nzbget.h"
#include "RarRenamer.h"
#include "FileSystem.h"
#include <cstdarg>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>
''' + globals_block + r'''
#undef NZBGET_USE_RUST
''' + decls + r'''

template <class R> class Recorder : public R
{
public:
	std::string m_log;
protected:
	void PrintMessage(Message::EKind kind, const char* format, ...) override
	{
		char buf[2048];
		va_list ap;
		va_start(ap, format);
		vsnprintf(buf, sizeof buf, format, ap);
		va_end(ap);
		m_log += std::to_string((int)kind) + ":" + buf + "\n";
	}
	void RegisterRenamedFile(const char* oldFilename, const char* newFileName) override
	{
		m_log += std::string("R:") + oldFilename + ">" + newFileName + "\n";
	}
};

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return n <= 0 ? 0 : (int)(next() % (unsigned long long)n); }

static std::string listing(const std::string& root)
{
	std::map<std::string, size_t> files;
	for (auto& e : fs::recursive_directory_iterator(root))
	{
		if (!e.is_regular_file()) continue;
		std::ifstream f(e.path(), std::ios::binary);
		std::string data((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
		files[e.path().string().substr(root.size())] = std::hash<std::string>()(data);
	}
	std::string s;
	for (auto& [name, hash] : files) s += name + "=" + std::to_string(hash) + ";";
	return s;
}

static std::string strip(std::string s, const std::string& root)
{
	for (size_t at; (at = s.find(root)) != std::string::npos;) s.replace(at, root.size(), "<ROOT>");
	return s;
}

template <class R> static std::string run(const std::string& root, const char* password, const char* ignore)
{
	Recorder<R> renamer;
	renamer.SetDestDir(root.c_str());
	renamer.SetInfoName("test");
	if (password) renamer.SetPassword(password);
	if (ignore) renamer.SetIgnoreExt(ignore);
	renamer.Execute();
	return strip(renamer.m_log + "|" + std::to_string(renamer.GetRenamedCount()) + "|" + listing(root), root);
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	std::string base = argv[2];
	std::vector<std::string> vols(argv + 3, argv + argc);
	const char* names[] = {"a", "b", "abc123", "x.part1.rar", "x.part01.rar", "x.part02.rar", "x.rar", "x.r00", "x.r01",
		"testfile3.part01.rar", "testfile5.part02.rar", "Movie.vol00+01.par2", "y", "z.bin", "x.part0001.rar", "X.PART01.RAR"};
	for (long round = 0; round < rounds; round++)
	{
		std::string roots[3] = {base + "/A", base + "/B", base + "/C"};
		for (auto& r : roots) { fs::remove_all(r); fs::create_directories(r); }
		// a set of volumes from one archive (sometimes several), named at random
		int n = 1 + below(7);
		int pick = below((int)vols.size());
		for (int i = 0; i < n; i++)
		{
			const std::string& src = vols[below(3) ? (pick + i) % vols.size() : below((int)vols.size())];
			std::string name = below(3) ? std::string(names[below(16)]) : "f" + std::to_string(next() % 100000);
			if (below(4) == 0) name = "sub/" + name;
			// sometimes the same volume twice: two sets then want the same new names
			std::string twin = below(3) == 0 ? "t" + std::to_string(next() % 100000) : "";
			for (auto& r : roots)
			{
				fs::create_directories(fs::path(r + "/" + name).parent_path());
				fs::copy_file(src, r + "/" + name, fs::copy_options::overwrite_existing);
				if (!twin.empty()) fs::copy_file(src, r + "/" + twin, fs::copy_options::overwrite_existing);
			}
		}
		// files in the way of new names
		if (below(3) == 0)
			for (auto& r : roots)
			{
				std::ofstream(r + "/testfile3.part01.rar") << "x";
				std::ofstream(r + "/testfile.part0001.rar") << "y";
			}
		const char* password = below(2) ? "123" : nullptr;
		const char* ignore = below(6) == 0 ? ".par2,.r00" : nullptr;
		std::string a = run<OldRarRenamer>(roots[0], password, ignore);
		std::string b = run<RarRenamer>(roots[1], password, ignore);
		std::string c = run<FallbackRarRenamer>(roots[2], password, ignore);
		if (a != b || a != c)
		{
			fprintf(stderr, "mismatch: round %ld\nold:      %s\nrust:     %s\nfallback: %s\n", round, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	printf("%ld directories agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");
}
'''

# Instrument the actual sources (including the Rust C++ callback wrapper), so
# metadata outside the on-disk fixtures can be tested without touching files.
probe_prelude = r"""
#include "nzbget.h"
#include "Util.h"
#include <stdexcept>
#include <clocale>
""" + (ROOT / "daemon/postprocess/RarReader.h").read_text().replace("private:", "public:") + globals_block + r"""
static std::vector<std::string> probeTrace;
static int probeChecks, probeCollisions, probeFail;
static bool ProbeExists(const char* path)
{
    probeTrace.push_back(std::string("exists:") + path);
    if (probeFail == 1) throw std::runtime_error("exists");
    return ++probeChecks <= probeCollisions;
}
static void ProbeRename(const char* src, const char* dest)
{
    probeTrace.push_back(std::string("rename:") + src + ">" + dest);
    if (probeFail == 2) throw std::runtime_error("rename");
}
struct ProbeRegEx : RegEx
{
    using RegEx::RegEx;
    bool Match(const char* name)
    {
        probeTrace.push_back(std::string("match:") + name);
        if (probeFail == 3) throw std::runtime_error("match");
        return RegEx::Match(name);
    }
};
"""


def instrument(src, hdr, prefix, fallback=False):
    start = src.index("void RarRenamer::RenameFile(")
    end = src.index("\n}", start) + 2
    src = src[:start] + """void RarRenamer::RenameFile(const char* src, const char* dest)
{ ProbeRename(src, dest); }""" + src[end:]
    src = src.replace("FileSystem::FileExists(", "ProbeExists(")
    src = src.replace("RegEx regExPart", "ProbeRegEx regExPart")
    return renamed(src, hdr.replace("private:", "public:"), prefix, fallback)


probe_source = (probe_prelude + instrument(old_src, old_header, "ProbeOld")
                + instrument(new_src, header, "ProbeRust")
                + instrument(new_src, header, "ProbeFallback", fallback=True)
                + (ROOT / "rust/tests/rarrenamer_metadata.cpp").read_text())

with tempfile.TemporaryDirectory(prefix="nzbget-rarrenamer-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    (temp / "metadata.cpp").write_text(probe_source)
    (temp / "old.cpp").write_text(renamed(old_src, old_header, "Old"))
    (temp / "fallback.cpp").write_text(renamed(new_src, header, "Fallback", fallback=True))
    binary = temp / "rarrenamer"
    for extra, rounds in ((["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], str(max(1, int(ROUNDS) // 4))), ([], ROUNDS)):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "old.cpp"),
                        str(temp / "fallback.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), rounds, str(temp / "t"), *volumes], check=True)
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "metadata.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary)], check=True)
