#!/usr/bin/env python3
"""Compare DirectRenamer's RenameContentAnalyzer (rust/src/renameanalyzer.rs
with the C++ wrapper of DirectRenamer.cpp), and its C++ fallback, with the
pre-port C++: random sequences of pieces (PAR2 packet headers, other data,
empty and large pieces, Reset/Finish cycles and wrapping sizes), comparing the PAR2 flag and set
id after every piece and the 16 KiB hash after every Finish.

Each version's class is compiled into its own namespace from its source.

Usage: renameanalyzer_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "20000"


def extract(src):
    i = src.index("class RenameContentAnalyzer : public ArticleContentAnalyzer")
    decl = src[i:src.index("\n};", i) + 3]
    out = [decl]
    for sig in ("void RenameContentAnalyzer::Reset()", "void RenameContentAnalyzer::Append(const void* buffer, int len)",
                "void RenameContentAnalyzer::Finish()"):
        j = src.index(sig + "\n{")
        out.append(src[j:src.index("\n}\n", j) + 3])
    return "\n".join(out)


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/queue/DirectRenamer.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/queue/DirectRenamer.cpp").read_text()


def new_first(src):
    # the Rust-backed definitions (the first of each pair)
    return extract(src)


def new_fallback(src):
    # the class declaration is shared; the fallback's methods are the last definitions
    i = src.index("class RenameContentAnalyzer : public ArticleContentAnalyzer")
    decl = src[i:src.index("\n};", i) + 3]
    parts = [decl]
    for sig in ("void RenameContentAnalyzer::Reset()", "void RenameContentAnalyzer::Append(const void* buffer, int len)",
                "void RenameContentAnalyzer::Finish()"):
        j = src.rindex(sig + "\n{")
        parts.append(src[j:src.index("\n}\n", j) + 3])
    return "\n".join(parts)


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
#include "ArticleDownloader.h"
#include "nzbget_rs.h"
#include <cstddef>
#include <memory>
#include <string>
#include <vector>
#include <par2/libpar2.h>
#include <par2/par2repairer.h>
#include <par2/par2fileformat.h>
#include <par2/md5.h>
''' + globals_block + r'''
namespace oldimpl {
''' + extract(old_src) + r'''
}
namespace newimpl {
#define NZBGET_RS_RENAME_ANALYZER
''' + new_first(new_src) + r'''
#undef NZBGET_RS_RENAME_ANALYZER
}
namespace fallbackimpl {
''' + new_fallback(new_src) + r'''
}
// These definitions must remain inert with parcheck disabled, even when the
// application otherwise links Rust. This also checks the conditional members.
#define DISABLE_PARCHECK
namespace disabledold {
''' + extract(old_src) + r'''
}
namespace disablednew {
''' + new_fallback(new_src) + r'''
}
#undef DISABLE_PARCHECK

template<class A> static void check_disabled()
{
	A a;
	a.Reset(); a.Append("PAR2\0PKT", 8); a.Append("", 0); a.Finish();
	if (a.GetParFile() || a.GetParSetId() || a.GetHash16k()) std::abort();
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return n <= 0 ? 0 : (int)(next() % (unsigned long long)n); }

template <class A> static std::string run(const std::vector<std::vector<char>>& pieces, const std::vector<int>& resets)
{
	A a;
	std::string out;
	char empty = 0; // The legacy memcpy requires a real pointer even for zero bytes.
	a.Reset();
	for (size_t i = 0; i < pieces.size(); i++)
	{
		if (resets[i] == 1 || resets[i] == 2 || resets[i] == 4)
		{
			a.Finish(); out += std::string("H") + a.GetHash16k() + ";";
			if (resets[i] == 4) { a.Finish(); out += std::string("H") + a.GetHash16k() + ";"; }
		}
		if (resets[i] == 1 || resets[i] == 3) { a.Reset(); }
		a.Append(pieces[i].empty() ? &empty : pieces[i].data(), (int)pieces[i].size());
		out += std::to_string(a.GetParFile()) + (a.GetParSetId() ? a.GetParSetId() : "-") + ",";
	}
	a.Finish();
	return out + "H" + a.GetHash16k();
}

static void compare(const std::vector<std::vector<char>>& pieces, const std::vector<int>& resets)
{
	std::string a = run<oldimpl::RenameContentAnalyzer>(pieces, resets);
	std::string b = run<newimpl::RenameContentAnalyzer>(pieces, resets);
	std::string c = run<fallbackimpl::RenameContentAnalyzer>(pieces, resets);
	if (a != b || a != c)
	{
		fprintf(stderr, "mismatch:\nold:      %s\nrust:     %s\nfallback: %s\n", a.c_str(), b.c_str(), c.c_str());
		exit(1);
	}
}

#ifdef TEST_SIZE_WRAP
// Reuse a modest real buffer: after 16 KiB the positive-size calls only count.
// The reference is built with -fwrapv in this run because its signed arithmetic
// is undefined at these boundaries. This records the intended legacy wrapping.
template<class A> static std::string wrap()
{
	A a;
	a.Reset();
	std::vector<char> buf(1024 * 1024, 'x');
	memcpy(buf.data(), "PAR2\0PKT", 8);
	for (int i = 0; i < 2048; ++i) a.Append(buf.data(), (int)buf.size());
	// INT_MIN, INT_MIN+8192, INT_MIN+16384, INT_MIN+16385.
	a.Append(buf.data(), 8192);
	a.Append(buf.data(), 8192);
	a.Append(buf.data(), 1);
	a.Append(buf.data(), 63);
	a.Finish();
	return std::to_string(a.GetParFile()) + a.GetParSetId() + a.GetHash16k();
}
#endif

int main(int argc, char** argv)
{
	check_disabled<disabledold::RenameContentAnalyzer>();
	check_disabled<disablednew::RenameContentAnalyzer>();
#ifdef TEST_SIZE_WRAP
	auto a = wrap<oldimpl::RenameContentAnalyzer>();
	auto b = wrap<newimpl::RenameContentAnalyzer>();
	auto c = wrap<fallbackimpl::RenameContentAnalyzer>();
	if (a != b || a != c) { fprintf(stderr, "size wrap mismatch\n%s\n%s\n%s\n", a.c_str(), b.c_str(), c.c_str()); return 1; }
#endif
	std::vector<char> empty;
	empty.reserve(1);
	std::vector<char> header(64);
	memcpy(header.data(), "PAR2\0PKT", 8);
	for (int i = 8; i < 64; ++i) header[i] = (char)i;
	// Every split through the magic and the 64-byte header, with empty pieces.
	for (int split = 0; split <= 64; ++split)
	{
		std::vector<char> first(header.begin(), header.begin() + split);
		std::vector<char> second(header.begin() + split, header.end());
		first.reserve(1); second.reserve(1);
		compare({first, empty, second, empty, {'x'}, header, empty}, {0, 0, 0, 0, 1, 3, 0});
	}
	for (int byte = 0; byte < 8; ++byte)
	{
		auto bad = header; bad[byte] ^= 1;
		compare({bad, empty}, {0, 0});
	}
	for (int value = 0; value < 256; ++value)
	{
		auto h = header;
		std::fill(h.begin() + 32, h.begin() + 48, (char)value);
		compare({h, empty, {'x'}, empty, header, empty}, {0, 0, 3, 0, 3, 0});
	}
	for (int size : {0, 1, 7, 8, 31, 32, 55, 56, 63, 64, 65, 127, 128, 16383, 16384, 16385, 40000})
	{
		std::vector<char> p(size, 'a'); p.reserve(1);
		for (int mode = 0; mode <= 4; ++mode)
			compare({p, empty, {'b'}, empty, p, empty}, {0, mode, 2, 4, 1, 0});
	}
	long rounds = atol(argv[1]);
	for (long round = 0; round < rounds; round++)
	{
		std::vector<std::vector<char>> pieces;
		std::vector<int> resets;
		int n = 1 + below(8);
		for (int i = 0; i < n; i++)
		{
			int size = below(4) == 0 ? 0 : below(3) == 0 ? below(70) : below(3) == 0 ? below(40000) : below(5000);
			std::vector<char> p(size);
			p.reserve(1);  // a real buffer even when empty (the C++ memcpy'd from it)
			for (char& c : p) c = (char)next();
			if (i == 0 && size >= 8 && below(2)) memcpy(p.data(), "PAR2\0PKT", 8);
			if (i > 0 && size >= 8 && below(8) == 0) memcpy(p.data(), "PAR2\0PKT", 8);
			pieces.push_back(std::move(p));
			resets.push_back(below(3) == 0 ? below(5) : 0);
		}
		compare(pieces, resets);
	}
	printf("%ld sequences agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-renameanalyzer-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "renameanalyzer"
    # Compile the actual translation unit as well as extracted classes. In
    # particular, DISABLE_PARCHECK must not require the PAR2 headers or Rust ABI.
    for defines in (["-UNZBGET_USE_RUST"], ["-DDISABLE_PARCHECK"],
                    ["-DDISABLE_PARCHECK", "-UNZBGET_USE_RUST"]):
        includes = shlex.split(get("CXX_INCLUDES"))
        if "-DDISABLE_PARCHECK" in defines:
            includes = [flag for flag in includes if "par2-turbo" not in flag]
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *defines, *includes, "-fsyntax-only", str(ROOT / "daemon/queue/DirectRenamer.cpp")],
                       check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"],
                  ["-fwrapv", "-DTEST_SIZE_WRAP"]):
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary), ROUNDS], check=True)
