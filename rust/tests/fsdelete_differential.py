#!/usr/bin/env python3
"""Compare FileSystem::DeleteDirectory, DeleteDirectoryWithContent, RenameBak
and GetFileExtension (rust/src/fsdelete.rs with the C++ of FileSystem.cpp's
Rust branch) and their C++ fallback with the pre-port C++ on real trees:
nested folders, hidden and visible files, empty folders, links to a folder
outside the tree, to files and dangling ones, read-only and unreadable
folders (failing deletes), taken backup names. Every version runs on the
same tree, rebuilt at the same path; compares the result, the error message,
errno afterwards, the tree left (link targets and modes included) and the
folder outside, which must never change.

Usage: fsdelete_differential.py BUILD_DIR [ROUNDS]
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

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/FileSystem.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/util/FileSystem.cpp").read_text()


def region(src, start, end_marker):
    i = src.index(start)
    j = src.index(end_marker, src.index("bool FileSystem::RenameBak(", i))
    return src[i:j + len(end_marker)]


old_region = region(old_src, "std::optional<std::string> FileSystem::GetFileExtension", "return MoveFile(filename, newName);\n}\n")
new_region = region(new_src, "#ifdef NZBGET_USE_RUST\nstd::optional<std::string> FileSystem::GetFileExtension", "return MoveFile(filename, newName);\n}\n")
fallback_region = new_region.replace("#if defined(NZBGET_USE_RUST) && !defined(WIN32)", "#if 0").replace(
    "#ifdef NZBGET_USE_RUST\nstd::optional", "#if 0\nstd::optional")

STAND_IN = r'''
struct FileSystem : ::FileSystem
{
	static std::optional<std::string> GetFileExtension(std::string_view filename);
	static bool IsLink(const char* filename);
	static bool DeleteDirectory(const char* dirFilename);
	static bool DeleteDirectoryWithContent(const char* dirFilename, CString& errmsg);
	static int64 FileSize(const char* filename);
	static bool RenameBak(const char* filename, const char* bakPart, bool removeOldExtension, CString& newName);
};
'''


def drop_disk_state(text):
    # unchanged, and its type is private to FileSystem
    i = text.index("std::optional<FileSystem::DiskState> FileSystem::GetDiskState")
    return text[:i] + text[text.index("\n}\n", i) + 3:]


def impl(name, text):
    text = drop_disk_state(text)
    return f"namespace {name}\n{{\n{STAND_IN}\n{text}\n}}\n"


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
#include "FileSystem.h"
#include "Util.h"
#include "nzbget_rs.h"
#include <cerrno>
#include <exception>
#include <filesystem>
#include <cstdlib>
#include <fstream>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include <vector>
''' + globals_block + impl("oldimpl", old_region) + impl("newimpl", new_region) + impl("fallbackimpl", fallback_region) + r'''
namespace stdfs = std::filesystem;

// where an exception that escapes a comparison came from
static std::string g_phase = "start";

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static void Unlock(const stdfs::path& dir)
{
	// each folder made accessible before it is listed
	struct stat st;
	if (lstat(dir.c_str(), &st) != 0 || !S_ISDIR(st.st_mode)) return;
	chmod(dir.c_str(), 0755);
	std::error_code ec;
	for (auto& entry : stdfs::directory_iterator(dir, ec))
	{
		Unlock(entry.path());
	}
}

static void Clean(const stdfs::path& dir)
{
	Unlock(dir);
	std::error_code ec;
	stdfs::remove_all(dir, ec);
	if (stdfs::exists(stdfs::symlink_status(dir, ec)))
	{
		fprintf(stderr, "could not clean %s\n", dir.c_str());
		exit(2);
	}
}

static std::vector<std::string> g_paths;

static void Build(const stdfs::path& root, const stdfs::path& outside, int depth, std::vector<stdfs::path>& locked)
{
	stdfs::create_directories(root);
	g_paths.push_back(root.string());
	static const char* NAMES[] = {"a", "b.txt", ".hidden", ".h2", "sub", ".git", "c.nzb", "d.bak", "e.tar.gz", "f"};
	for (int n = below(5); n > 0; --n)
	{
		std::string name = NAMES[below(10)];
		if (below(3) == 0) name += std::to_string(below(3));
		stdfs::path p = root / name;
		if (stdfs::exists(stdfs::symlink_status(p))) continue;
		int kind = below(10);
		if (kind < 4) std::ofstream(p) << "x";
		else if (kind < 7 && depth < 3) Build(p, outside, depth + 1, locked);
		else if (kind == 7) stdfs::create_directory_symlink(outside, p);
		else if (kind == 8) stdfs::create_symlink(outside / "file", p);
		else stdfs::create_symlink(root / "missing", p);
		g_paths.push_back(p.string());
	}
	if (depth > 0 && below(4) == 0) locked.push_back(root);
}

static std::string Snapshot(const stdfs::path& dir)
{
	std::map<std::string, std::string> entries;
	std::error_code ec;
	if (!stdfs::exists(stdfs::symlink_status(dir, ec))) return "(gone)\n";
	for (auto it = stdfs::recursive_directory_iterator(dir, stdfs::directory_options::skip_permission_denied, ec);
		it != stdfs::recursive_directory_iterator(); it.increment(ec))
	{
		// relative() resolves links, merging distinct entries with the same
		// target in this map and potentially hiding a deletion mismatch.
		std::string rel = it->path().lexically_relative(dir).string();
		struct stat st;
		if (lstat(it->path().c_str(), &st) != 0) throw std::runtime_error("snapshot lstat failed");
		std::string what;
		if (S_ISLNK(st.st_mode)) what = "link->" + stdfs::read_symlink(it->path()).string();
		else if (S_ISDIR(st.st_mode)) what = "dir";
		else if (S_ISREG(st.st_mode))
		{
			// Read only regular files: opening a FIFO can block, and opening a
			// link would inspect data outside the tree. Hex keeps binary bytes
			// (including NUL and newline) unambiguous in diagnostics.
			std::ifstream file(it->path(), std::ios::binary);
			if (!file) throw std::runtime_error("snapshot open failed");
			what = "file:";
			static const char* hex = "0123456789abcdef";
			for (int byte; (byte = file.get()) != EOF; )
			{
				what += hex[(unsigned char)byte >> 4];
				what += hex[(unsigned char)byte & 15];
			}
			if (file.bad()) throw std::runtime_error("snapshot read failed");
		}
		else what = "special:" + std::to_string(st.st_mode & S_IFMT);
		entries[rel] = what + " " + std::to_string(st.st_mode & 0777);
	}
	std::string out;
	for (auto& [k, v] : entries) out += k + " " + v + "\n";
	return out;
}

struct Op
{
	int kind;
	std::string path;
	bool removeExt;
};

template <class FS> static std::string Run(const stdfs::path& work, const stdfs::path& outside, unsigned long long seed, Op& op)
{
	// the box holds the tree and every name a backup rename can create beside it
	Clean(work.parent_path());
	Clean(outside);
	stdfs::create_directories(outside / "inner");
	std::ofstream(outside / "file") << "keep";
	std::ofstream(outside / "inner" / ".hidden") << "keep";
	const std::string outsideBefore = Snapshot(outside);
	state = seed;
	g_paths.clear();
	std::vector<stdfs::path> locked;
	Build(work, outside, 0, locked);
	// taken backup names
	for (int n = below(3); n > 0; --n)
	{
		std::string p = g_paths[below(g_paths.size())];
		std::string base = p;
		if (below(2)) { size_t dot = base.rfind('.'); if (dot != std::string::npos) base.resize(dot); }
		std::string taken = base + (below(2) ? ".bak" : "." + std::to_string(2 + below(2)) + ".bak");
		std::error_code ec;
		if (!stdfs::exists(stdfs::symlink_status(taken, ec)) && stdfs::exists(stdfs::path(taken).parent_path(), ec))
			below(2) ? (void)(std::ofstream(taken) << "t") : (void)stdfs::create_directory(taken, ec);
	}
	op.kind = below(10);
	op.path = below(12) == 0 ? (work / "missing").string() : g_paths[below(g_paths.size())];
	op.removeExt = below(2);
	// read-only (deletes fail), listable but not searchable (lstat fails), closed
	static const mode_t MODES[] = {0555, 0444, 0};
	for (const stdfs::path& dir : locked) chmod(dir.c_str(), MODES[below(3)]);

	std::string result;
	errno = 1000 + below(5);
	int savedErrno;
	try
	{
		if (op.kind < 4)
		{
			bool ok = FS::DeleteDirectory(op.path.c_str());
			savedErrno = errno;
			result = "DeleteDirectory " + std::to_string(ok);
		}
		else if (op.kind < 8)
		{
			CString errmsg = "previous";
			bool ok = FS::DeleteDirectoryWithContent(op.path.c_str(), errmsg);
			savedErrno = errno;
			result = "DeleteDirectoryWithContent " + std::to_string(ok) + " [" + (errmsg ? *errmsg : "(null)") + "]";
		}
		else
		{
			CString newName;
			bool ok = FS::RenameBak(op.path.c_str(), below(4) ? "bak" : "", op.removeExt, newName);
			savedErrno = errno;
			result = "RenameBak " + std::to_string(ok) + " [" + (newName ? *newName : "(null)") + "]";
		}
	}
	catch (const std::exception& e)
	{
		savedErrno = errno;
		result = std::string("exception ") + e.what();
	}
	result += " errno " + std::to_string(savedErrno) + "\n";
	Unlock(work.parent_path());
	const std::string outsideAfter = Snapshot(outside);
	if (outsideAfter != outsideBefore)
	{
		fprintf(stderr, "outside tree changed for %s\n", op.path.c_str());
		exit(1);
	}
	return result + Snapshot(work.parent_path()) + "outside:\n" + outsideAfter;
}

// a failing entry next to a folder deleted fine (the inner call clears the
// message), in both listing orders, and the same one level down
template <class FS> static std::string Fixed(const stdfs::path& work, int variant)
{
	Clean(work.parent_path());
	const char* first = variant & 1 ? "a" : "b";
	const char* second = variant & 1 ? "b" : "a";
	stdfs::path base = variant & 2 ? work / "deeper" : work;
	stdfs::create_directories(base / first / "inner");
	std::ofstream(base / first / "inner" / "f") << "x";
	stdfs::create_directories(base / second / "empty");
	std::ofstream(base / second / "g") << "x";
	chmod((base / first / "inner").c_str(), 0555);
	errno = 1234;
	CString errmsg = "previous";
	bool ok = FS::DeleteDirectoryWithContent(work.c_str(), errmsg);
	int savedErrno = errno;
	std::string result = std::to_string(ok) + " [" + (errmsg ? *errmsg : "(null)") + "] errno " + std::to_string(savedErrno) + "\n";
	Unlock(work.parent_path());
	return result + Snapshot(work.parent_path());
}

// Real paths around BString<1024>'s byte cut, with collisions and dots on
// either side of the cut. No directory is itself truncated into an ancestor.
template <class FS> static std::string Boundaries(const stdfs::path& box, int variant)
{
	Clean(box);
	stdfs::path dir = box;
	while (dir.string().size() < 1000)
	{
		size_t left = 1000 - dir.string().size() - 1;
		dir /= std::string(std::min(left, size_t(180)), 'd');
	}
	stdfs::create_directories(dir);
	std::string result;
	CString output = "previous";
	errno = 1234;
	if (variant < 2)
	{
		std::string prefix = "." + std::string(21, 'h');
		std::ofstream(dir / prefix) << "short";
		std::ofstream(dir / (prefix + "suffix")) << "long";
		errno = 1234;
		bool ok = variant ? FS::DeleteDirectory(dir.c_str()) : FS::DeleteDirectoryWithContent(dir.c_str(), output);
		int saved = errno;
		result = std::to_string(ok) + " [" + (output ? *output : "(null)") + "] errno " + std::to_string(saved) + "\n";
	}
	else
	{
		std::string leaf(45, 'a');
		leaf[variant == 2 ? 21 : 22] = '.';
		leaf[30] = static_cast<char>(0xff);
		std::string filename = (dir / leaf).string();
		std::ofstream(filename) << "source";
		bool removeExt = variant != 4;
		std::string base = removeExt ? filename.substr(0, 1023) : filename;
		if (removeExt && base.rfind('.') != std::string::npos) base.resize(base.rfind('.'));
		std::ofstream(base + ".bak") << "taken";
		for (int i = 2; i < 12; i++) stdfs::create_directory(base + "." + std::to_string(i) + ".bak");
		errno = 1234;
		bool ok = FS::RenameBak(filename.c_str(), "bak", removeExt, output);
		int saved = errno;
		result = std::to_string(ok) + " [" + (output ? *output : "(null)") + "] errno " + std::to_string(saved) + "\n";
	}
	return result + Snapshot(box);
}

// NULL backup suffixes historically use the platform printf's %s behavior.
// Compare NULL and empty sources/suffixes separately. A NULL source with
// removeExt=true is excluded: the legacy BString copy dereferences NULL.
template <class FS> static std::string NullBackup(const stdfs::path& box, int variant)
{
	Clean(box);
	stdfs::create_directories(box);
	std::string filename = (box / "source.nzb").string();
	std::ofstream(filename) << "source";
	CString output = "previous";
	errno = 1234;
	const char* source = variant < 4 ? filename.c_str() : variant < 6 ? nullptr : "";
	const char* suffix = variant & 1 ? "" : nullptr;
	bool removeExt = variant < 4 && (variant & 2);
	bool ok = FS::RenameBak(source, suffix, removeExt, output);
	int saved = errno;
	return std::to_string(ok) + " [" + (output ? *output : "(null)") + "] errno " + std::to_string(saved) + "\n" + Snapshot(box);
}

template <class FS> static std::string EmptyDelete(bool content, const char* path)
{
	CString output = "previous";
	errno = 1234;
	bool ok = content ? FS::DeleteDirectoryWithContent(path, output) : FS::DeleteDirectory(path);
	int saved = errno;
	return std::to_string(ok) + " [" + (output ? *output : "(null)") + "] errno " + std::to_string(saved);
}

template <class FS> static std::string BackupLinks(const stdfs::path& box, int variant)
{
	Clean(box);
	stdfs::create_directories(box / "outside" / "dir");
	stdfs::create_directories(box / "work");
	std::ofstream(box / "outside" / "file") << "keep";
	std::string source = (box / "work" / "source").string();
	std::ofstream(source) << "move";
	std::string backup = source + ".bak";
	if (variant == 0) stdfs::create_symlink(box / "outside" / "file", backup);
	else if (variant == 1) stdfs::create_directory_symlink(box / "outside" / "dir", backup);
	else if (variant == 2) stdfs::create_symlink(box / "outside" / "missing", backup);
	else if (variant == 3) stdfs::create_hard_link(box / "outside" / "file", backup);
	else if (mkfifo(backup.c_str(), 0600) != 0) throw std::runtime_error("mkfifo failed");
	const std::string outside = Snapshot(box / "outside");
	CString output = "previous";
	errno = 1234;
	bool ok = FS::RenameBak(source.c_str(), "bak", false, output);
	int saved = errno;
	if (Snapshot(box / "outside") != outside) throw std::runtime_error("backup changed outside data");
	return std::to_string(ok) + " [" + (output ? *output : "(null)") + "] errno " + std::to_string(saved) + "\n" + Snapshot(box);
}

// Root spellings (trailing separators and "." components, on a folder and on
// a link) and roots at the path buffers' limit next to a folder that shares
// their leading part: the Rust branch and the fallback agree, and nothing but
// the root's own content changes.
template <class FS> static std::string Roots(const stdfs::path& box, int variant, std::string& kept)
{
	Clean(box);
	stdfs::create_directories(box / "outside" / "inner");
	std::ofstream(box / "outside" / "inner" / ".keep") << "keep";
	std::ofstream(box / "outside" / "file") << "keep";
	stdfs::create_directories(box / "plain" / "sub");
	std::ofstream(box / "plain" / "sub" / "f") << "x";
	stdfs::create_directory_symlink(box / "outside", box / "link");
	static const char* SPELLINGS[] = {"", "/", "//", "/.", "/./", "/./."};
	std::string path;
	if (variant < 12)
	{
		path = (box / (variant < 6 ? "plain" : "link")).string() + SPELLINGS[variant % 6];
	}
	else
	{
		// a root of 1023 or more bytes and a sibling named by its first 1023
		stdfs::path dir = box;
		while (dir.string().size() < 900) dir /= std::string(std::min<size_t>(200, 900 - dir.string().size() - 1), 'd');
		stdfs::create_directories(dir);
		size_t leaf = 1023 - dir.string().size() - 1 + (variant - 12);
		std::string name(leaf, 'r');
		stdfs::create_directories(dir / name);
		std::ofstream(dir / name / "f") << "x";
		stdfs::create_directories(dir / name.substr(0, 1023 - dir.string().size() - 1));
		std::ofstream(dir / name.substr(0, 1023 - dir.string().size() - 1) / "sibling") << "keep";
		path = (dir / name).string();
	}
	kept = Snapshot(box / "outside");
	CString output = "previous";
	errno = 1234;
	bool ok = variant % 2 ? FS::DeleteDirectory(path.c_str()) : FS::DeleteDirectoryWithContent(path.c_str(), output);
	int saved = errno;
	std::string result = std::to_string(ok) + " [" + (output ? *output : "(null)") + "] errno " + std::to_string(saved) + "\n";
	if (Snapshot(box / "outside") != kept)
	{
		fprintf(stderr, "roots %d: the folder outside changed\n", variant);
		exit(1);
	}
	return result + Snapshot(box);
}

int main(int argc, char** argv)
{
	std::set_terminate([]
	{
		fprintf(stderr, "terminated in %s\n", g_phase.c_str());
		if (std::current_exception())
		{
			try { std::rethrow_exception(std::current_exception()); }
			catch (const std::exception& e) { fprintf(stderr, "  %s\n", e.what()); }
			catch (...) {}
		}
		abort();
	});
	long rounds = atol(argv[1]);
	stdfs::path temp = argv[2];
	stdfs::path work = temp / "box" / "work";
	stdfs::path outside = temp / "outside";
	if (geteuid() == 0) printf("note: running as root, permission failures don't happen\n");

	// An overwrite preserving the name, mode and length must change a snapshot.
	stdfs::create_directories(temp / "snapshot");
	std::ofstream(temp / "snapshot" / "file") << "old";
	std::string before = Snapshot(temp / "snapshot");
	std::ofstream(temp / "snapshot" / "file") << "new";
	if (before == Snapshot(temp / "snapshot")) throw std::runtime_error("snapshot missed overwritten bytes");
	Clean(temp / "snapshot");

	for (int variant = 0; variant < 5; variant++)
	{
		std::string a = BackupLinks<oldimpl::FileSystem>(temp / "backup-links", variant);
		std::string b = BackupLinks<newimpl::FileSystem>(temp / "backup-links", variant);
		std::string c = BackupLinks<fallbackimpl::FileSystem>(temp / "backup-links", variant);
		if (a != b || a != c)
		{
			fprintf(stderr, "backup links %d mismatch\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", variant, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	Clean(temp / "backup-links");

	for (int variant = 0; variant < 3; variant++)
	{
		// The platform's lstat(NULL) behavior is checked only without UBSan:
		// libc headers may declare its path nonnull. DeleteDirectory(NULL)
		// is excluded because the legacy opendir(NULL) can crash.
		if (variant == 2 && argc < 4)
		{
			CString error = "previous";
			errno = 1234;
			if (newimpl::FileSystem::DeleteDirectoryWithContent(nullptr, error) || errno != EFAULT ||
				!error || strncmp(*error, "could not delete (null): ", 24))
			{
				fprintf(stderr, "NULL delete in Rust branch failed\n");
				return 1;
			}
			continue;
		}
		bool content = variant != 0;
		const char* path = variant == 2 ? nullptr : "";
		std::string a = EmptyDelete<oldimpl::FileSystem>(content, path);
		std::string b = EmptyDelete<newimpl::FileSystem>(content, path);
		std::string c = EmptyDelete<fallbackimpl::FileSystem>(content, path);
		if (a != b || a != c)
		{
			fprintf(stderr, "empty/NULL delete %d mismatch\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", variant, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}

	// GetFileExtension
	for (const char* s : {"", ".", "a", "a.", ".a", "a.b.c", "/d.x/a", "a.tar.gz", "..", "x/.y"})
	{
		auto a = oldimpl::FileSystem::GetFileExtension(s), b = newimpl::FileSystem::GetFileExtension(s),
			c = fallbackimpl::FileSystem::GetFileExtension(s);
		if (a != b || a != c) { fprintf(stderr, "GetFileExtension mismatch on [%s]\n", s); return 1; }
	}
	for (std::string_view s : {std::string_view{}, std::string_view("a.\0b.c", 6), std::string_view("\xff.\xfe", 3)})
	{
		auto a = oldimpl::FileSystem::GetFileExtension(s), b = newimpl::FileSystem::GetFileExtension(s),
			c = fallbackimpl::FileSystem::GetFileExtension(s);
		if (a != b || a != c) { fprintf(stderr, "GetFileExtension byte-view mismatch\n"); return 1; }
	}
	for (int variant = 0; variant < 5; variant++)
	{
		// paths beyond the path buffers are refused since the pre-port code:
		// those deletes compare the Rust branch with the fallback only
		std::string a = Boundaries<oldimpl::FileSystem>(temp / "long", variant);
		std::string b = Boundaries<newimpl::FileSystem>(temp / "long", variant);
		std::string c = Boundaries<fallbackimpl::FileSystem>(temp / "long", variant);
		if (variant < 2) a = b;
		if (a != b || a != c)
		{
			fprintf(stderr, "boundary %d mismatch\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", variant, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	Clean(temp / "long");

	for (int variant = 0; variant < 4; variant++)
	{
		stdfs::path fixedWork = temp / "box" / "work";
		std::string a = Fixed<oldimpl::FileSystem>(fixedWork, variant);
		std::string b = Fixed<newimpl::FileSystem>(fixedWork, variant);
		std::string c = Fixed<fallbackimpl::FileSystem>(fixedWork, variant);
		if (a != b || a != c)
		{
			fprintf(stderr, "fixed %d mismatch\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", variant, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}

	for (int variant = 0; variant < 8; variant++)
	{
		std::string a = NullBackup<oldimpl::FileSystem>(temp / "null-backup", variant);
		std::string b = NullBackup<newimpl::FileSystem>(temp / "null-backup", variant);
		std::string c = NullBackup<fallbackimpl::FileSystem>(temp / "null-backup", variant);
		if (a != b || a != c)
		{
			fprintf(stderr, "NULL backup mismatch\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	Clean(temp / "null-backup");

	for (int variant = 0; variant < 16; variant++)
	{
		std::string kept;
		g_phase = "roots " + std::to_string(variant);
		std::string b = Roots<newimpl::FileSystem>(temp / "roots", variant, kept);
		std::string c = Roots<fallbackimpl::FileSystem>(temp / "roots", variant, kept);
		if (b != c)
		{
			fprintf(stderr, "roots %d mismatch\n--- rust:\n%s\n--- fallback:\n%s\n", variant, b.c_str(), c.c_str());
			return 1;
		}
		if (variant >= 12 && b.find("sibling") == std::string::npos)
		{
			fprintf(stderr, "roots %d: the neighbouring folder changed\n%s\n", variant, b.c_str());
			return 1;
		}
	}
	Clean(temp / "roots");

	long counts[3] = {0, 0, 0};
	unsigned long long seed = 88172645463325252ull;
	for (long round = 0; round < rounds; round++)
	{
		seed = seed * 6364136223846793005ull + 1442695040888963407ull;
		Op op{};
		g_phase = "round " + std::to_string(round) + " old";
		std::string a = Run<oldimpl::FileSystem>(work, outside, seed, op);
		g_phase = "round " + std::to_string(round) + " rust " + std::to_string(op.kind) + " " + op.path;
		std::string b = Run<newimpl::FileSystem>(work, outside, seed, op);
		g_phase = "round " + std::to_string(round) + " fallback " + std::to_string(op.kind) + " " + op.path;
		std::string c = Run<fallbackimpl::FileSystem>(work, outside, seed, op);
		counts[op.kind < 4 ? 0 : op.kind < 8 ? 1 : 2]++;
		if (a != b || a != c)
		{
			fprintf(stderr, "round %ld mismatch (%s)\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", round, op.path.c_str(), a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	Clean(work.parent_path());
	Clean(outside);
	printf("%ld trees agree: %ld DeleteDirectory, %ld DeleteDirectoryWithContent, %ld RenameBak (reference %s)\n",
		rounds, counts[0], counts[1], counts[2], "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-fsdelete-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "fsdelete"
    subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")),
                    *shlex.split(get("CXX_DEFINES")), "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/util/FileSystem.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]],
                       check=True, cwd=BUILD)
        run = temp / "run"
        run.mkdir(exist_ok=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS, str(run),
                        *([] if "-fsanitize=address,undefined" in extra else ["check-null-path"])], check=True)
