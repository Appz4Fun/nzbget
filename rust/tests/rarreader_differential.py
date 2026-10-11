#!/usr/bin/env python3
"""Compare RarVolume's header parsing (rust/src/rarreader.rs with the C++
wrapper of RarReader.cpp), and its C++ fallback, with the pre-port C++: every
RAR3/RAR5 volume of tests/testdata (plain, encrypted data, encrypted headers),
with and without the password, then the same volumes mutated (byte flips,
truncations, insertions, deletions) - comparing the result, the volume state
and every file's fields.

The pre-port and fallback readers are compiled as separate translation units
with the classes renamed; the Rust-backed one is the build's. The volumes are
read from memory through a ContentSource.

Usage: rarreader_differential.py BUILD_DIR [ROUNDS]
(NZBGET_TEST_VERBOSE=1 prints each volume and round; NZBGET_TEST_WRAPPER runs
the binary under a tool, e.g. "gdb -batch -ex run -ex bt --args".)
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "400"

header = (ROOT / "daemon/postprocess/RarReader.h").read_text()
old_header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/RarReader.h"], cwd=ROOT, text=True)


def renamed(src, hdr, prefix, fallback=False):
    def r(text):
        for name in ("RarSourceCursor", "RarVolume", "RarFile"):
            text = re.sub(rf"\b{name}\b", prefix + name, text)
        return text.replace("RARREADER_H", prefix.upper() + "RARREADER_H")
    body = r(src).replace('#include "RarReader.h"', r(hdr))
    return ("#undef NZBGET_USE_RUST\n" if fallback else "") + body


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/RarReader.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/postprocess/RarReader.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]
volumes = sorted(str(p) for p in (ROOT / "tests/testdata").rglob("*") if re.search(r"\.(rar|r\d\d)$", p.name))

decls = "\n".join(renamed("", h, p)[0:0] + re.sub(r"\b(RarSourceCursor|RarVolume|RarFile)\b", lambda m: p + m.group(1), h)
                  .replace("RARREADER_H", p.upper() + "RARREADER_H") for h, p in ((old_header, "Old"), (header, "Fallback")))

main = r'''
#include "nzbget.h"
#include "RarReader.h"
#include "ContentMap.h"
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
''' + globals_block + r'''
#undef NZBGET_USE_RUST
''' + decls + r'''

struct MemSource : ContentSource
{
	std::string data;
	int64 Size() override { return (int64)data.size(); }
	bool Read(int64 offset, void* buffer, int64 size) override
	{
		if (offset < 0 || size < 0 || offset + size > (int64)data.size()) return false;
		memcpy(buffer, data.data() + offset, (size_t)size);
		return true;
	}
};

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return n <= 0 ? 0 : (int)(next() % (unsigned long long)n); }

static std::string hex(const uint8* p, int n) { std::string s; char b[3]; for (int i = 0; i < n; i++) { snprintf(b, 3, "%02x", p[i]); s += b; } return s; }

template <class V> static std::string run(const std::string& data, const char* password)
{
	MemSource source;
	source.data = data;
	V volume("vol.rar");
	if (password) volume.SetPassword(password);
	bool ok = volume.ReadFrom(source);
	std::string s = std::to_string(ok) + "|" + std::to_string(volume.GetVersion()) + "," + std::to_string(volume.GetVolumeNo()) + "," +
		std::to_string(volume.GetNewNaming()) + std::to_string(volume.GetHasNextVolume()) + std::to_string(volume.GetMultiVolume()) +
		std::to_string(volume.GetEncrypted()) + "|";
	for (auto& f : *volume.GetFiles())
	{
		s += std::string(f.GetFilename()) + "/" + std::to_string(f.GetTime()) + "/" + std::to_string(f.GetAttr()) + "/" +
			std::to_string(f.GetSize()) + "/" + std::to_string(f.GetSplitBefore()) + std::to_string(f.GetSplitAfter()) + "/" +
			std::to_string(f.GetMethod()) + "/" + std::to_string(f.GetStored()) + "/" + std::to_string(f.GetPackedSize()) + "/" +
			std::to_string(f.GetDataOffset()) + "/" + std::to_string(f.GetEncryptedData()) + "/" + std::to_string(f.GetHasSalt()) +
			hex(f.GetSalt(), 8) + "/";
		if (auto* c = f.GetCrypt())
			s += std::to_string(c->Version) + "," + std::to_string(c->Flags) + "," + std::to_string(c->KdfCount) + "," +
				hex(c->Salt, 16) + hex(c->Iv, 16) + hex(c->CheckValue, 12) + std::to_string(c->HasCheck);
		s += ";";
	}
	return s;
}

static bool check(const std::string& data, const char* password, const std::string& what)
{
	std::string a = run<OldRarVolume>(data, password);
	std::string b = run<RarVolume>(data, password);
	std::string c = run<FallbackRarVolume>(data, password);
	if (a != b || a != c)
	{
		fprintf(stderr, "mismatch: %s (password %s)\nold:      %s\nrust:     %s\nfallback: %s\n", what.c_str(),
			password ? password : "-", a.c_str(), b.c_str(), c.c_str());
		return false;
	}
	return true;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	std::vector<std::string> files;
	for (int i = 2; i < argc; i++)
	{
		std::ifstream f(argv[i], std::ios::binary);
		files.emplace_back(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
		for (const char* pw : {(const char*)nullptr, "123", "wrong"})
		{
			if (getenv("NZBGET_TEST_VERBOSE")) fprintf(stderr, "volume %s pw %s\n", argv[i], pw ? pw : "-");
			if (!check(files.back(), pw, argv[i])) return 1;
		}
	}
	long parsed = 0;
	for (long round = 0; round < rounds; round++)
	{
		int which = below((int)files.size());
		// the headers sit at the start: mutate mostly there
		std::string data = files[which].substr(0, below(4) == 0 ? files[which].size() : std::min<size_t>(files[which].size(), 512 + below(4096)));
		int m = 1 + below(6);
		for (int i = 0; i < m && !data.empty(); i++)
		{
			size_t at = below(below(3) ? std::min<int>(256, (int)data.size()) : (int)data.size());
			switch (below(5))
			{
				case 0: data[at] = (char)next(); break;
				case 1: data[at] ^= (char)(1 << below(8)); break;
				case 2: data.erase(at, 1 + below(8)); break;
				case 3: data.insert(at, std::string(1 + below(8), (char)next())); break;
				default: data.resize(at);
			}
		}
		const char* pw = below(3) ? "123" : below(2) ? nullptr : "x";
		if (getenv("NZBGET_TEST_VERBOSE")) fprintf(stderr, "round %ld file %d size %zu pw %s\n", round, which, data.size(), pw ? pw : "-");
		if (!check(data, pw, "mutated " + std::string(argv[2 + which]) + " round " + std::to_string(round))) return 1;
		parsed++;
	}
	printf("%zu volumes and %ld mutations agree (reference %s)\n", files.size(), parsed, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-rarreader-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    (temp / "old.cpp").write_text(renamed(old_src, old_header, "Old"))
    (temp / "fallback.cpp").write_text(renamed(new_src, header, "Fallback", fallback=True))
    binary = temp / "rarreader"
    # an encrypted volume derives its key (PBKDF2) on every read: the sanitizer
    # build gets a quarter of the mutations
    for extra, rounds in ((["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], str(max(1, int(ROUNDS) // 4))), ([], ROUNDS)):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "old.cpp"),
                        str(temp / "fallback.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        # NZBGET_TEST_WRAPPER (e.g. "gdb -batch -ex run -ex bt --args") runs the binary under a tool
        subprocess.run([*shlex.split(os.environ.get("NZBGET_TEST_WRAPPER", "")), str(binary), rounds, *volumes], check=True)
