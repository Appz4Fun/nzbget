#!/usr/bin/env python3
"""Compare ParRenamer::Execute (rust/src/parrenamer.rs with the C++ of
ParRenamer.cpp's Rust branch) and its C++ fallback with the pre-port C++ on
real par2 sets (tests/testdata/parchecker, parchecker2) under obfuscated,
case-changed and fragment names, in subdirectories, with files missing,
duplicated or colliding with their correct names, par2 files damaged or
truncated, junk files with par2 headers, stops and exceptions part way.
Every version runs on an identical copy at the same path; compares the
files left (names and contents), every message, progress update and
registered name, and the counters. Also covers callback-visible state,
repeated Execute calls, callback/translation exceptions, and bounded paths.
Explicit cases cover a destination changed by initial progress, hash16k-only
matching and first-entry precedence, and one warning/.bad move per damaged par.
Inputs that made the original C++ read uninitialized memory are compared
only between Rust and the initialized fallback.

Usage: parrenamer_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "1500"

old_cpp = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/ParRenamer.cpp"], cwd=ROOT, text=True)
old_h = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/ParRenamer.h"], cwd=ROOT, text=True)
new_cpp = (ROOT / "daemon/postprocess/ParRenamer.cpp").read_text()
new_h = (ROOT / "daemon/postprocess/ParRenamer.h").read_text()


def impl(name, header, cpp, fallback=False):
    i = header.index("class ParRenamer\n{")
    cls = header[i:header.index("\n};", i) + 3]
    body = cpp[cpp.index("class ParRenamerRepairer"):cpp.rindex("#endif")]
    if fallback:
        body = body.replace("#ifdef NZBGET_USE_RUST\nvoid ParRenamer::Execute()", "#ifndef NZBGET_USE_RUST\nvoid ParRenamer::Execute()")
    # Inject an exception at the same operation in every implementation.
    body = body.replace("std::string filename = Par2::DescriptionPacket::TranslateFilenameFromPar2ToLocal(",
                        "BeforeTranslate();\n\t\tstd::string filename = Par2::DescriptionPacket::TranslateFilenameFromPar2ToLocal(")
    return f"namespace {name}\n{{\n{cls}\n{body}\n}}\n"


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
#include <par2/libpar2.h>
#include <par2/par2repairer.h>
#include <par2/md5.h>
#include "ParParser.h"
#include "Log.h"
#include "Options.h"
#include "Util.h"
#include "FileSystem.h"
#include "nzbget_rs.h"
#include <clocale>
#include <cstdarg>
#include <exception>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
static int translateAfter = -1;
static void BeforeTranslate()
{
	if (translateAfter == 0) throw std::runtime_error("translation failed");
	if (translateAfter > 0) --translateAfter;
}
''' + globals_block + impl("oldimpl", old_h, old_cpp) + impl("newimpl", new_h, new_cpp) + impl("fallbackimpl", new_h, new_cpp, True) + r'''
namespace stdfs = std::filesystem;

struct Plan
{
	int stopAfter = -1;
	int throwAfter = -1;
	int throwEvent = -1;
	int throwTranslate = -1;
	bool detectMissing = false;
	int executions = 1;
	bool setMissing = false;
	bool redirectDest = false;
};

template <class Base> struct Recorder : Base
{
	std::string log;
	Plan plan;
	int stopCalls = 0;
	int renames = 0;
	int events = 0;
	std::string selectedDest;

	void Observe()
	{
		log += "S " + std::to_string(Base::GetRenamedCount()) + " " +
			std::to_string(Base::HasMissedFiles()) + " " + std::to_string(Base::HasDamagedParFiles()) + "\n";
		if (plan.throwEvent >= 0 && events++ == plan.throwEvent) throw std::runtime_error("callback failed");
	}

	void UpdateProgress() override
	{
		Observe();
		log += "P " + std::string(Base::GetProgressLabel()) + " " + std::to_string(Base::GetStageProgress()) + "\n";
		if (plan.redirectDest)
		{
			Base::SetDestDir(selectedDest.c_str());
			plan.redirectDest = false;
		}
	}
	bool IsStopped() override
	{
		Observe();
		return plan.stopAfter >= 0 && ++stopCalls > plan.stopAfter;
	}
	void PrintMessage(Message::EKind kind, const char* format, ...) override
	{
		Observe();
		char buf[4096];
		va_list ap;
		va_start(ap, format);
		vsnprintf(buf, sizeof(buf), format, ap);
		va_end(ap);
		log += "M" + std::to_string((int)kind) + " " + buf + "\n";
	}
	void RegisterParredFile(const char* filename) override
	{
		Observe();
		if (plan.setMissing) Base::SetDetectMissing(true);
		log += "R " + std::string(filename) + "\n";
	}
	void RegisterRenamedFile(const char* oldFilename, const char* newFilename) override
	{
		Observe();
		log += "N " + std::string(oldFilename) + " -> " + newFilename + "\n";
		if (plan.throwAfter >= 0 && ++renames > plan.throwAfter)
		{
			throw std::runtime_error("registering failed");
		}
	}
};

static std::string Snapshot(const stdfs::path& dir)
{
	std::map<std::string, std::string> files;
	for (auto& entry : stdfs::recursive_directory_iterator(dir))
	{
		std::string rel = stdfs::relative(entry.path(), dir).string();
		if (entry.is_directory()) { files[rel] = "<dir>"; continue; }
		std::ifstream in(entry.path(), std::ios::binary);
		std::string content((std::istreambuf_iterator<char>(in)), {});
		unsigned long long h = 1469598103934665603ull;
		for (unsigned char c : content) h = (h ^ c) * 1099511628211ull;
		files[rel] = std::to_string(content.size()) + ":" + std::to_string(h);
	}
	std::string out;
	for (auto& [name, sum] : files) out += name + " " + sum + "\n";
	return out;
}

template <class Impl> static std::string Run(const stdfs::path& scenario, const stdfs::path& work, const Plan& plan)
{
	stdfs::remove_all(work);
	stdfs::copy(scenario, work, stdfs::copy_options::recursive);
	Recorder<Impl> renamer;
	renamer.plan = plan;
	translateAfter = plan.throwTranslate;
	renamer.selectedDest = work.string();
	renamer.SetDestDir((plan.redirectDest ? work / "unused" : work).string().c_str());
	renamer.SetInfoName("scenario");
	renamer.SetDetectMissing(plan.detectMissing);
	std::string result;
	for (int n = 0; n < plan.executions; n++)
	{
		try { renamer.Execute(); }
		catch (const std::exception& e) { result += std::string("exception: ") + e.what() + "\n"; }
	}
	return result + renamer.log + "renamed " + std::to_string(renamer.GetRenamedCount()) + " missed " +
		std::to_string(renamer.HasMissedFiles()) + " damaged " + std::to_string(renamer.HasDamagedParFiles()) + "\n" + Snapshot(work);
}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static std::string ReadFile(const stdfs::path& p)
{
	std::ifstream in(p, std::ios::binary);
	return std::string((std::istreambuf_iterator<char>(in)), {});
}

static void WriteFile(const stdfs::path& p, const std::string& content)
{
	stdfs::create_directories(p.parent_path());
	std::ofstream(p, std::ios::binary) << content;
}

static std::string Hex(int n)
{
	std::string s;
	for (int i = 0; i < n; i++) s += "0123456789abcdef"[below(16)];
	return s;
}

static std::string Header(unsigned long long length, bool fullSetId)
{
	std::string h("PAR2\0PKT", 8);
	for (int i = 0; i < 8; i++) h += (char)(length >> (8 * i));
	for (int i = 0; i < 48; i++) h += (char)(fullSetId || i < 16 ? next() : 0);
	return h;
}

static void Build(const stdfs::path& dir, const std::vector<stdfs::path>& sets)
{
	stdfs::remove_all(dir);
	stdfs::create_directories(dir);
	static const char* EXTS[] = {"", "", ".bin", ".par2", ".PAR2", ".dat", ".vol01+02.par2", ".7z"};
	static const char* SUBDIRS[] = {"sub", "sub/deeper", "other"};
	for (const stdfs::path& set : sets)
	{
		for (auto& entry : stdfs::directory_iterator(set))
		{
			std::string name = entry.path().filename().string();
			if (name == "crc.txt") continue;
			std::string content = ReadFile(entry.path());
			bool par = name.find(".par2") != std::string::npos || name.find(".PAR2") != std::string::npos;
			if (par && below(5) == 0)
			{
				// description packets dropped (their packet hash broken): a par2
				// file missing several is listed once
				for (size_t at = 0; at + 64 <= content.size(); )
				{
					unsigned long long length = 0;
					for (int i = 0; i < 8; i++) length |= (unsigned long long)(unsigned char)content[at + 8 + i] << (8 * i);
					if (content.compare(at, 8, std::string("PAR2\0PKT", 8)) || length < 64 || at + length > content.size()) break;
					if (!content.compare(at + 48, 16, std::string("PAR 2.0\0FileDesc", 16)) && below(4)) content[at + 16] ^= 1;
					at += length;
				}
			}
			else if (par && below(5) == 0)
			{
				int how = below(4);
				if (how == 0)
				{
					// truncated: not into the length field (the C++ read it uninitialized)
					size_t size = below(3) == 0 ? below(8) : 16 + below((int)content.size() - 16);
					content.resize(size);
				}
				else if (how == 1) content[below(64)] ^= (char)(1 + below(255));
				else if (how == 2) content[64 + below((int)content.size() - 64)] ^= (char)(1 + below(255));
				else content.clear();
			}
			std::string newName = name;
			stdfs::path where = dir;
			int r = below(100);
			if (r < 30) {}
			else if (r < 55) newName = Hex(16) + EXTS[below(8)];
			else if (r < 62) { for (char& ch : newName) ch = toupper(ch); }
			else if (r < 68) newName = name + (below(3) == 0 ? ".000" : below(2) ? ".001" : ".002");
			else if (r < 74) continue;
			else if (r < 80) { where = dir / SUBDIRS[below(3)]; newName = below(2) ? Hex(12) : name; }
			else if (r < 86) WriteFile(dir / (Hex(10) + EXTS[below(8)]), content);
			else newName = name + "." + std::to_string(below(3));
			WriteFile(where / newName, content);
		}
	}
	if (below(4) == 0) WriteFile(dir / (std::string(100, 'x') + ".par2"), Header(64, true));
	// junk, files with par2 headers and files at the names the par2 files give
	for (int n = below(4); n > 0; --n)
	{
		std::string junk;
		switch (below(5))
		{
			case 0: for (int i = below(200); i > 0; --i) junk += (char)next(); break;
			case 1: junk = Header(64, true); break;
			case 2: junk = Header(64 + 4 * below(4), true) + std::string(below(3) * 4, 'x'); break;
			case 3: junk = Header(0x100000000ull + 64 * below(2), true) + std::string(below(3) * 4, 'x'); break;
			default: junk = Header(66, true) + "xx"; break;
		}
		static const char* NAMES[] = {"testfile.dat", "testfile.nfo", "testfile.7z.001", "junk.par2", "JUNK", "testfile.par2.bad"};
		WriteFile((below(4) == 0 ? dir / "sub" : dir) / (below(2) ? std::string(NAMES[below(6)]) : Hex(8)), junk);
	}
}

int main(int argc, char** argv)
{
	setlocale(LC_ALL, "");
	Options::CmdOptList cmdOpts;
	cmdOpts.push_back("ParIgnoreExt=.nfo,.sfv");
	Options options(&cmdOpts, nullptr);
	long rounds = atol(argv[1]);
	stdfs::path data = argv[2];
	stdfs::path temp = argv[3];
	std::vector<stdfs::path> all = {data / "parchecker", data / "parchecker2"};
	long renamedRounds = 0;
	for (long round = 0; round < rounds; round++)
	{
		std::vector<stdfs::path> sets;
		int pick = below(4);
		if (pick != 1) sets.push_back(all[0]);
		if (pick != 0) sets.push_back(all[1]);
		Build(temp / "scenario", sets);
		Plan plan;
		plan.detectMissing = below(2);
		plan.executions = below(5) == 0 ? 2 : 1;
		plan.setMissing = below(5) == 0;
		if (below(10) == 0) plan.stopAfter = below(40);
		if (below(12) == 0) plan.throwAfter = below(4);
		if (below(8) == 0) plan.throwEvent = below(100);
		if (below(8) == 0) plan.throwTranslate = below(6);
		stdfs::path work = temp / "work";
		if (round % 20 == 0)
		{
			// Leave enough suffix space for volume numbers while crossing the
			// 1023-byte limit for long source/description names.
			while (work.string().size() < 960)
			{
				size_t n = std::min<size_t>(180, 960 - work.string().size() - 1);
				work /= std::string(n, 'd');
			}
			stdfs::create_directories(work.parent_path());
		}
		std::string a = Run<oldimpl::ParRenamer>(temp / "scenario", work, plan);
		std::string b = Run<newimpl::ParRenamer>(temp / "scenario", work, plan);
		std::string c = Run<fallbackimpl::ParRenamer>(temp / "scenario", work, plan);
		if (a.find("\nN ") != std::string::npos) renamedRounds++;
		if (a != b || a != c)
		{
			fprintf(stderr, "round %ld mismatch\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", round, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	{
		// The initial UpdateProgress callback may change the destination before
		// BuildDirList reads it. The old destination must not be cached early.
		Plan plan;
		plan.redirectDest = true;
		std::string a = Run<oldimpl::ParRenamer>(all[0], temp / "work", plan);
		std::string b = Run<newimpl::ParRenamer>(all[0], temp / "work", plan);
		std::string c = Run<fallbackimpl::ParRenamer>(all[0], temp / "work", plan);
		if (a != b || a != c)
		{ fprintf(stderr, "initial destination callback mismatch\n%s\n%s\n%s", a.c_str(), b.c_str(), c.c_str()); return 1; }
	}
	{
		stdfs::path dir = temp / "same-size";
		stdfs::remove_all(dir);
		stdfs::copy(all[0], dir, stdfs::copy_options::recursive);
		std::string original = ReadFile(dir / "testfile.dat");
		stdfs::remove(dir / "testfile.dat");
		WriteFile(dir / "wrong-content", std::string(original.size(), 'x'));
		Plan plan;
		plan.detectMissing = true;
		std::string a = Run<oldimpl::ParRenamer>(dir, temp / "work", plan);
		std::string b = Run<newimpl::ParRenamer>(dir, temp / "work", plan);
		std::string c = Run<fallbackimpl::ParRenamer>(dir, temp / "work", plan);
		if (a != b || a != c || b.find("File testfile.dat is missing") == std::string::npos)
		{ fprintf(stderr, "same-size mismatch\n"); return 1; }
	}
	{
		// Matching intentionally ignores the rest of the contents and file size.
		stdfs::path dir = temp / "same-prefix";
		stdfs::remove_all(dir);
		stdfs::copy(all[0], dir, stdfs::copy_options::recursive);
		std::string original = ReadFile(dir / "testfile.dat");
		stdfs::remove(dir / "testfile.dat");
		WriteFile(dir / "obfuscated", original.substr(0, 16384) + "different tail");
		Plan plan;
		plan.detectMissing = true;
		std::string a = Run<oldimpl::ParRenamer>(dir, temp / "work", plan);
		std::string b = Run<newimpl::ParRenamer>(dir, temp / "work", plan);
		std::string c = Run<fallbackimpl::ParRenamer>(dir, temp / "work", plan);
		if (a != b || a != c || b.find("N obfuscated -> testfile.dat") == std::string::npos)
		{ fprintf(stderr, "same-prefix mismatch\n"); return 1; }
	}
	{
		// Two entries with the same hash16k keep the first source-map entry,
		// even though its described size and full-file hash are different.
		stdfs::path dir = temp / "first-hash";
		stdfs::remove_all(dir);
		std::string original = ReadFile(all[0] / "testfile.dat");
		Par2::MD5Context prefix;
		Par2::MD5Hash prefixHash;
		prefix.Update(original.data(), 16384);
		prefix.Final(prefixHash);
		std::string content = ReadFile(all[0] / "testfile.par2");
		for (size_t at = 0; at + 64 <= content.size(); )
		{
			unsigned long long length = 0;
			for (int i = 0; i < 8; i++) length |= (unsigned long long)(unsigned char)content[at + 8 + i] << (8 * i);
			if (length < 64 || length > content.size() - at) return 1;
			if (length > 120 && !content.compare(at + 48, 16, std::string("PAR 2.0\0FileDesc", 16)))
			{
				// Short descriptions need equal full/16k hashes to pass libpar2's checks.
				memcpy(content.data() + at + 80, &prefixHash, 16);
				memcpy(content.data() + at + 96, &prefixHash, 16);
				Par2::MD5Context md5;
				Par2::MD5Hash hash;
				md5.Update(content.data() + at + 32, length - 32);
				md5.Final(hash);
				memcpy(content.data() + at + 16, &hash, 16);
			}
			at += length;
		}
		WriteFile(dir / "testfile.par2", content);
		WriteFile(dir / "obfuscated", original);
		Plan plan;
		std::string a = Run<oldimpl::ParRenamer>(dir, temp / "work", plan);
		std::string b = Run<newimpl::ParRenamer>(dir, temp / "work", plan);
		std::string c = Run<fallbackimpl::ParRenamer>(dir, temp / "work", plan);
		if (a != b || a != c || b.find("N obfuscated -> testfile.nfo") == std::string::npos ||
			b.find("R testfile.dat") != std::string::npos)
		{ fprintf(stderr, "first-hash mismatch\n%s\n", b.c_str()); return 1; }
	}
	{
		// Several missing descriptions must produce one warning and one .bad move.
		stdfs::path dir = temp / "damaged-descriptions";
		stdfs::remove_all(dir);
		std::string content = ReadFile(all[0] / "testfile.par2");
		for (size_t at = 0; at + 64 <= content.size(); )
		{
			unsigned long long length = 0;
			for (int i = 0; i < 8; i++) length |= (unsigned long long)(unsigned char)content[at + 8 + i] << (8 * i);
			if (length < 64 || length > content.size() - at) return 1;
			if (!content.compare(at + 48, 16, std::string("PAR 2.0\0FileDesc", 16))) content[at + 16] ^= 1;
			at += length;
		}
		WriteFile(dir / "obfuscated", content);
		Plan plan;
		std::string a = Run<oldimpl::ParRenamer>(dir, temp / "work", plan);
		std::string b = Run<newimpl::ParRenamer>(dir, temp / "work", plan);
		std::string c = Run<fallbackimpl::ParRenamer>(dir, temp / "work", plan);
		std::string warning = "Damaged par2-file detected:";
		size_t first = b.find(warning);
		if (a != b || a != c || first == std::string::npos || b.find(warning, first + 1) != std::string::npos ||
			b.find("renamed 2 missed 0 damaged 1") == std::string::npos || b.find("Failed to rename") != std::string::npos)
		{ fprintf(stderr, "damaged descriptions mismatch\n%s\n", b.c_str()); return 1; }
	}
	{
		// A valid packet checksum with an empty description name makes the
		// real libpar2 translator throw (string::at(0)), after IsStopped.
		stdfs::path dir = temp / "empty-description";
		stdfs::remove_all(dir);
		std::string content = ReadFile(all[0] / "testfile.par2");
		for (size_t at = 0; at + 64 <= content.size(); )
		{
			unsigned long long length = 0;
			for (int i = 0; i < 8; i++) length |= (unsigned long long)(unsigned char)content[at + 8 + i] << (8 * i);
			if (length < 64 || length > content.size() - at) break;
			if (length > 120 && !content.compare(at + 48, 16, std::string("PAR 2.0\0FileDesc", 16)))
			{
				content[at + 120] = 0;
				Par2::MD5Context md5;
				Par2::MD5Hash hash;
				md5.Update(content.data() + at + 32, length - 32);
				md5.Final(hash);
				memcpy(content.data() + at + 16, &hash, 16);
			}
			at += length;
		}
		WriteFile(dir / "testfile.par2", content);
		for (int stopped = 0; stopped < 2; stopped++)
		{
			Plan plan;
			if (stopped) plan.stopAfter = 0;
			std::string a = Run<oldimpl::ParRenamer>(dir, temp / "work", plan);
			std::string b = Run<newimpl::ParRenamer>(dir, temp / "work", plan);
			std::string c = Run<fallbackimpl::ParRenamer>(dir, temp / "work", plan);
			if (a != b || a != c || (b.find("exception:") != std::string::npos) != !stopped)
			{ fprintf(stderr, "empty-description mismatch\n%s\n%s\n%s", a.c_str(), b.c_str(), c.c_str()); return 1; }
		}
	}
	for (int n = 0; n < 3; n++)
	{
		stdfs::path dir = temp / "undefined-input";
		stdfs::remove_all(dir);
		stdfs::create_directories(dir);
		std::string h = Header(0x80000000ull, false);
		if (n < 2) h.resize(n == 0 ? 8 : 16);
		WriteFile(dir / ".par2", h);
		WriteFile(dir / "a.par2", h);
		Plan plan;
		std::string b = Run<newimpl::ParRenamer>(dir, temp / "work", plan);
		std::string c = Run<fallbackimpl::ParRenamer>(dir, temp / "work", plan);
		if (b != c) { fprintf(stderr, "initialized fallback mismatch %d\n", n); return 1; }
	}
	printf("%ld scenarios agree, %ld with renames (reference %s)\n", rounds, renamedRounds, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-parrenamer-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "parrenamer"
    subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")),
                    *shlex.split(get("CXX_DEFINES")), "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/postprocess/ParRenamer.cpp")], check=True, cwd=BUILD)
    subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")),
                    *shlex.split(get("CXX_DEFINES")), "-DDISABLE_PARCHECK", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/postprocess/ParRenamer.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]],
                       check=True, cwd=BUILD)
        work = temp / "run"
        work.mkdir(exist_ok=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS,
                        str(ROOT / "tests/testdata"), str(work)], check=True)
