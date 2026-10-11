#!/usr/bin/env python3
"""Compare FileSystem's file operations (rust/src/fsops.rs with the C++
wrappers of FileSystem.cpp), and their C++ fallback, with the pre-port C++:
FileExists, DirectoryExists, ForceDirectories (result, message and the tree
it leaves), MakeUniqueFilename and ExpandHomePath, on the same random trees
(files, directories, symlinks, unreadable directories, long names) built
under three roots of equal length, results compared with the root replaced.

GetLastErrorMessage is the fixed one in all three (its fix is a deliberate
change: glibc's GNU strerror_r left the C++ buffer empty).

Usage: fsops_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "3000"

SIGS = [
    "bool FileSystem::FileExists(const char* filename)",
    "bool FileSystem::DirectoryExists(const char* dirFilename)",
    "bool FileSystem::ForceDirectories(const char* path, CString& errmsg)",
    "CString FileSystem::MakeUniqueFilename(const char* destDir, const char* basename)",
    "CString FileSystem::ExpandHomePath(const char* filename)",
]


def bodies(src):
    out = []
    for sig in SIGS:
        i = src.rindex(sig + "\n{")  # the POSIX C++ one: the last definition
        out.append(src[i:src.index("\n}\n", i) + 3])
    return "".join(out)


STANDIN = r'''
class FileSystem
{
public:
	static bool FileExists(const char* filename);
	static bool DirectoryExists(const char* dirFilename);
	static bool ForceDirectories(const char* path, CString& errmsg);
	static CString MakeUniqueFilename(const char* destDir, const char* basename);
	static CString ExpandHomePath(const char* filename);
	static void NormalizePathSeparators(char* path) { ::FileSystem::NormalizePathSeparators(path); }
	static CString GetLastErrorMessage() { return ::FileSystem::GetLastErrorMessage(); }
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/FileSystem.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/util/FileSystem.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

main = r'''
#include "nzbget.h"
#include "FileSystem.h"
#include <filesystem>
#include <string>
#include <vector>
#include <sys/stat.h>

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

static const char* const NAMES[] = {"a", "b", "f.txt", "f.vol01+02.par2", "f.par2", "x.PAR2", "noext", ".hidden", "f.",
	"f.duplicate1.txt", "d", "e", "..", ".", "a.b.c", "v.VOL1.par2", "vol.par2", ".vol1.par2"};

static std::string rel(int depth)
{
	std::string p;
	int n = 1 + below(depth);
	for (int i = 0; i < n; i++)
	{
		if (i) p += below(15) ? "/" : below(2) ? "//" : "\\";
		p += below(40) ? pick(NAMES) : std::string(260, 'L');
	}
	if (below(6) == 0) p += "/";
	return p;
}

static void build(const std::string& root, unsigned long long seed)
{
	namespace fs = std::filesystem;
	unsigned long long saved = state;
	state = seed;
	fs::create_directories(root);
	int n = below(12);
	for (int i = 0; i < n; i++)
	{
		std::string p = root + "/" + rel(3);
		std::error_code ec;
		switch (below(5))
		{
			case 0: case 1: fs::create_directories(p, ec); break;
			case 2: { fs::create_directories(fs::path(p).parent_path(), ec); FILE* f = fopen(p.c_str(), "w"); if (f) fclose(f); break; }
			case 3: fs::create_directory_symlink(pick(NAMES), p, ec); break;
			default: { fs::create_directories(p, ec); if (below(3) == 0) chmod(p.c_str(), 0); }
		}
	}
	state = saved;
}

static std::string listing(const std::string& root)
{
	namespace fs = std::filesystem;
	std::vector<std::string> v;
	std::error_code ec;
	for (auto it = fs::recursive_directory_iterator(root, fs::directory_options::skip_permission_denied, ec);
		it != fs::recursive_directory_iterator(); it.increment(ec))
	{
		if (ec) break;
		v.push_back(it->path().string().substr(root.size()) + (it->is_directory(ec) ? "/" : ""));
	}
	std::sort(v.begin(), v.end());
	std::string s;
	for (auto& x : v) s += x + ";";
	return s;
}

static void unlock(const std::string& root)
{
	namespace fs = std::filesystem;
	std::error_code ec;
	for (int pass = 0; pass < 4; pass++)
		for (auto it = fs::recursive_directory_iterator(root, fs::directory_options::skip_permission_denied, ec);
			it != fs::recursive_directory_iterator(); it.increment(ec))
			if (!ec && !it->is_symlink(ec)) chmod(it->path().c_str(), 0755);
	fs::remove_all(root, ec);
}

static std::string strip(std::string s, const std::string& root)
{
	for (size_t at; (at = s.find(root)) != std::string::npos;) s.replace(at, root.size(), "<ROOT>");
	return s;
}

template <class F> static std::string run(const std::string& root, const std::string& path, const std::string& dir,
	const std::string& base, const std::string& home)
{
	std::string out;
	std::string p = root + "/" + path;
	out += std::to_string(F::FileExists(p.c_str())) + std::to_string(F::DirectoryExists(p.c_str())) + "|";
	std::string d = root + (dir.empty() ? "" : "/" + dir);
	out += std::string(F::MakeUniqueFilename(d.c_str(), base.c_str())) + "|";
	CString errmsg = "stale";
	bool ok = F::ForceDirectories(p.c_str(), errmsg);
	out += std::to_string(ok) + ":" + (errmsg ? (const char*)errmsg : "(null)") + "|";
	if (home == "-") unsetenv("HOME"); else setenv("HOME", home.c_str(), 1);
	std::string tilde = below(2) ? "~/" + path : below(2) ? path : "~" + path;
	out += std::string(F::ExpandHomePath(tilde.c_str())) + "," + std::string(F::ExpandHomePath(nullptr)) + "|";
	std::string top = root.substr(0, root.size() - std::string("/1/2/3/r").size());
	return strip(out, root) + listing(top);
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	std::string base = argv[2];
	const char* homes[] = {"/home/u", "/home/u/", "/", "", "rel", "-"};
	for (long round = 0; round < rounds; round++)
	{
		unsigned long long seed = next();
		// four levels down: a path's ".." (at most four) stays in its own tree
		std::string roots[3] = {base + "/A/1/2/3/r", base + "/B/1/2/3/r", base + "/C/1/2/3/r"};
		for (auto& r : roots) build(r, seed);
		std::string path = rel(4);
		std::string dir = below(3) ? rel(2) : "";
		std::string name = pick(NAMES);
		std::string home = homes[below(6)];
		unsigned long long s2 = state;
		std::string a = run<oldimpl::FileSystem>(roots[0], path, dir, name, home);
		state = s2;
		std::string b = run<::FileSystem>(roots[1], path, dir, name, home);
		state = s2;
		std::string c = run<fallbackimpl::FileSystem>(roots[2], path, dir, name, home);
		for (const char* t : {"/A", "/B", "/C"}) unlock(base + t);
		if (strip(a, roots[0]) != strip(b, roots[1]) || strip(a, roots[0]) != strip(c, roots[2]))
		{
			fprintf(stderr, "mismatch: path [%s] dir [%s] name [%s] home [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
				path.c_str(), dir.c_str(), name.c_str(), home.c_str(), a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	printf("%ld trees agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-fsops-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "fsops"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, str(temp / "t")], check=True)
