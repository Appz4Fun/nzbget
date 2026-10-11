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
FSOPS_RUST_ARCHIVE and FSOPS_CXX_FLAGS can select a Debug archive and flags
while reusing the application dependencies from BUILD_DIR.
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
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text()
link = shlex.split(link)
libs = link[link.index("liblibnzbget.a"):]
if os.environ.get("FSOPS_RUST_ARCHIVE"):
    libs = [os.environ["FSOPS_RUST_ARCHIVE"] if lib.endswith("/libnzbget_rs.a") else lib for lib in libs]

main = r'''
#include "nzbget.h"
#include "FileSystem.h"
#include <filesystem>
#include <string>
#include <vector>
#include <sys/stat.h>
#include <clocale>
#include <climits>
#if defined(__GLIBC__) || defined(__UCLIBC__) || defined(__CYGWIN__)
extern "C" int __xpg_strerror_r(int, char*, size_t);
static bool longError = false;
extern "C" int __real___xpg_strerror_r(int, char*, size_t);
extern "C" int __wrap___xpg_strerror_r(int e, char* buf, size_t len)
{
	if (!longError) return __real___xpg_strerror_r(e, buf, len);
	// Model a long translated libc error, including the ERANGE result.
	if (len) { memset(buf, 'E', len - 1); buf[len - 1] = 0; }
	return ERANGE;
}
#endif
#include "nzbget_rs.h"

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
	"f.duplicate1.txt", "d", "e", "..", ".", "a.b.c", "v.VOL1.par2", "vol.par2", ".vol1.par2", "f.vol.par2", "f.volgarbage.PAR2", "\xffraw", "f\n.vol+PAR.par2"};

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
		struct stat st{};
		if (lstat(it->path().c_str(), &st) == 0) {
			std::string entry = it->path().string().substr(root.size()) + ":" + std::to_string(st.st_mode);
			if (S_ISLNK(st.st_mode)) entry += ":" + fs::read_symlink(it->path(), ec).string();
			v.push_back(entry);
		}
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
	errno = 123;
	bool file = F::FileExists(p.c_str());
	int fileErr = errno;
	errno = 123;
	bool directory = F::DirectoryExists(p.c_str());
	int dirErr = errno;
	out += std::to_string(file) + ":" + std::to_string(fileErr) + "," +
		std::to_string(directory) + ":" + std::to_string(dirErr) + "|";
	std::string d = root + (dir.empty() ? "" : "/" + dir);
	errno = 123;
	CString unique = F::MakeUniqueFilename(d.c_str(), base.c_str());
	int uniqueErr = errno;
	out += std::string(unique) + ":" + std::to_string(uniqueErr) + "|";
	CString errmsg = "stale";
	errno = 123;
	bool ok = F::ForceDirectories(p.c_str(), errmsg);
	int forceErr = errno;
	out += std::to_string(forceErr) + ":" + std::to_string(ok) + ":" + (errmsg ? (const char*)errmsg : "(null)") + "|";
	if (home == "-") unsetenv("HOME"); else setenv("HOME", home.c_str(), 1);
	std::string tilde = below(2) ? "~/" + path : below(2) ? path : "~" + path;
	out += std::string(F::ExpandHomePath(tilde.c_str())) + "," + std::string(F::ExpandHomePath(nullptr)) + "|";
	std::string top = root.substr(0, root.size() - std::string("/1/2/3/r").size());
	return strip(out, root) + listing(top);
}


static int nativeStat(const char* path)
{
	struct stat st;
	if (stat(path, &st)) return -errno;
	return S_ISREG(st.st_mode) ? 1 : S_ISDIR(st.st_mode) ? 2 : 0;
}

static void require(bool ok, const char* message)
{
	if (!ok) { fprintf(stderr, "%s\n", message); exit(1); }
}

static void ffiChecks()
{
	NzbgetRsBuf msg;
	require(!nzbget_rs_force_directories(nullptr, &msg, nativeStat), "NULL path status");
	require(msg.data && msg.len == 0 && msg.data[0] == 0, "NULL path output not initialized");
	nzbget_rs_free(msg);
	require(!nzbget_rs_force_directories(".", &msg, nullptr), "NULL stat status");
	require(msg.data && msg.len == 0, "NULL stat output not initialized");
	nzbget_rs_free(msg);
	require(!nzbget_rs_force_directories(".", nullptr, nativeStat), "NULL output");
	require(!nzbget_rs_file_exists(nullptr, nativeStat), "NULL FileExists");
	require(!nzbget_rs_directory_exists(nullptr, nativeStat), "NULL DirectoryExists");
	require(!nzbget_rs_directory_exists(".", nullptr), "NULL stat DirectoryExists");
	auto empty = nzbget_rs_expand_home_path(nullptr, nullptr);
	require(empty.data && !empty.len && !empty.data[0], "NULL home expansion");
	nzbget_rs_free(empty);
	auto unchanged = nzbget_rs_expand_home_path("~/\xff", nullptr);
	require(std::string(unchanged.data) == "~/\xff", "missing home expansion");
	nzbget_rs_free(unchanged);
	auto expanded = nzbget_rs_expand_home_path("~/\xff", "");
	require(std::string(expanded.data) == "/\xff", "empty home expansion");
	nzbget_rs_free(expanded);
	auto unique = nzbget_rs_make_unique_filename(nullptr, nullptr, nativeStat);
	require(std::string(unique.data) == "/", "NULL unique inputs");
	nzbget_rs_free(unique);
	nzbget_rs_error_message(ENOENT, nullptr);
	for (int e : {0, ENOENT, EACCES, ENAMETOOLONG, -1, INT_MAX, INT_MIN}) {
		char expected[1024] = {};
#if defined(__GLIBC__) || defined(__UCLIBC__) || defined(__CYGWIN__)
		__xpg_strerror_r(e, expected, 1023);
#else
		strerror_r(e, expected, 1023);
#endif
		struct { char text[1024]; char guard; } actual{};
		actual.guard = 'G';
		nzbget_rs_error_message(e, actual.text);
		require(std::string(expected) == actual.text && actual.guard == 'G', "strerror_r mismatch/overflow");
	}
#if defined(__GLIBC__) || defined(__UCLIBC__) || defined(__CYGWIN__)
	longError = true;
	errno = ENOENT;
	CString cut = ::FileSystem::GetLastErrorMessage();
	longError = false;
	require(cut.Length() == 1022 && std::string(cut) == std::string(1022, 'E'), "strerror_r capacity cut");
#endif
	CString cppMsg = "stale";
	require(!::FileSystem::ForceDirectories(nullptr, cppMsg), "C++ NULL ForceDirectories");
}

static std::string nested(size_t length)
{
	std::string out;
	while (length > 201) { out += std::string(200, 'x') + "/"; length -= 201; }
	return out + std::string(length, 'x');
}

static void deterministic(const std::string& base)
{
	namespace fs = std::filesystem;
	std::string saved = fs::current_path().string();
	std::vector<std::string> paths = {"", ".", "..", "/", "//", "///", "regular", "regular/", "regular/child",
		"dir", "dir/", "dir//", "dirlink/child", "filelink", "dangling", "loop", "fifo", "denied/child",
		"fresh/a/b", "fresh\\a\\b", "missing/../new", "missing//leaf", "\\", "\xff/\xfe", "raw\\name"};
	for (size_t length : {1022, 1023, 1024, 1200, 4096}) paths.push_back(nested(length));
	paths.push_back(std::string(256, 'L'));
	std::string deep;
	for (int i = 0; i < 510; ++i) deep += "a/";
	paths.push_back(deep + "b");
	std::vector<std::string> names = {"regular", ".hidden", "f.", "f.txt", "f.vol01+02.par2", "f.VOL.PAR2",
		"f.volnonsense.par2", ".vol1.par2", "f.\xff.PAR2", "dir", "filelink", "dangling", "fifo", "a.b/c.par2"};
	for (size_t length : {1022, 1023, 1024, 1100}) {
		names.push_back(nested(length) + ".txt");
		names.push_back(nested(length) + ".vol01+02.par2");
	}
	const char* homes[] = {"", "/", "/home/u/", "relative", "\xff/home", "-"};
	for (const char* locale : {"C", "C.UTF-8", "en_US.UTF-8"}) {
		if (!setlocale(LC_ALL, locale)) continue;
		for (size_t i = 0; i < paths.size() + names.size(); ++i) {
			std::string results[3];
			for (int impl = 0; impl < 3; ++impl) {
				std::string root = base + "/edge" + std::to_string(impl);
				fs::create_directories(root);
				fs::current_path(root);
				fs::create_directory("dir");
				fs::create_directory("denied");
				for (auto name : names) {
					if (name == "dir" || name == "filelink" || name == "dangling" || name == "fifo") continue;
					fs::path parent = fs::path(name).parent_path();
					if (!parent.empty()) fs::create_directories(parent);
					FILE* f = fopen(name.c_str(), "w"); require(f, "creating collision file"); fclose(f);
				}
				FILE* f = fopen("f.duplicate1.txt", "w"); require(f, "creating duplicate"); fclose(f);
				symlink("dir", "dirlink"); symlink("regular", "filelink");
				symlink("missing-target", "dangling"); symlink("loop", "loop");
				mkfifo("fifo", 0600); chmod("denied", 0);
				std::string p = paths[i % paths.size()];
				std::string name = i < paths.size() ? "f.txt" : names[i - paths.size()];
				// Exercise bare relative paths, especially the empty path and
				// the original parent/strlen recursion.
				std::string out;
#define EDGE(F) do { \
					errno = 123; bool exists = F::FileExists(p.c_str()); int e = errno; \
					out += std::to_string(exists) + ":" + std::to_string(e) + "|"; \
					errno = 123; exists = F::DirectoryExists(p.c_str()); e = errno; \
					out += std::to_string(exists) + ":" + std::to_string(e) + "|"; \
					errno = 123; CString u = F::MakeUniqueFilename(".", name.c_str()); e = errno; \
					out += std::string(u) + ":" + std::to_string(e) + "|"; \
					CString message = "stale"; errno = 123; bool ok = F::ForceDirectories(p.c_str(), message); e = errno; \
					out += std::to_string(ok) + ":" + std::to_string(e) + ":" + message.Str() + "|"; \
					for (const char* home : homes) { \
						if (std::string(home) == "-") unsetenv("HOME"); else setenv("HOME", home, 1); \
						for (const char* filename : {"", "~", "~user/x", "~/", "~//x", "~/\xff"}) \
							out += std::string(F::ExpandHomePath(filename)) + "|"; \
					} \
				} while (0)
				if (impl == 0) EDGE(oldimpl::FileSystem);
				if (impl == 1) EDGE(::FileSystem);
				if (impl == 2) EDGE(fallbackimpl::FileSystem);
#undef EDGE
				results[impl] = out + listing(root);
				fs::current_path(saved);
				unlock(root);
			}
			if (results[0] != results[1] || results[0] != results[2]) {
				fprintf(stderr, "edge mismatch %zu, locale %s\nold: %s\nrust: %s\nfallback: %s\n",
					i, locale, results[0].c_str(), results[1].c_str(), results[2].c_str());
				exit(1);
			}
		}
	}
	setlocale(LC_ALL, "C");
	puts("deterministic edge cases, errno, locale and FFI checks agree");
}

int main(int argc, char** argv)
{
	// Run before any successful Rust metadata lookup: its statx probe used to
	// replace ENOENT with EFAULT on the first failed call.
	errno = 0;
	bool missing = ::FileSystem::FileExists("");
	if (missing || errno != ENOENT) {
		fprintf(stderr, "FileExists(empty) errno: expected %d, got %d\n", ENOENT, errno);
		return 1;
	}
	long rounds = atol(argv[1]);
	std::string base = argv[2];
	ffiChecks();
	deterministic(base);
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
                        *shlex.split(os.environ.get("FSOPS_CXX_FLAGS", "")), *extra, *(["-Wl,--wrap=__xpg_strerror_r"] if sys.platform.startswith(("linux", "cygwin", "gnu")) else []), "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, str(temp / "t")], check=True)
