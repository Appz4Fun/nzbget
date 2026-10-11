#!/usr/bin/env python3
"""Compare ReleaseName (rust/src/releasename.rs through its C ABI) with the
pre-port C++ of daemon/dupesearch/ReleaseName.cpp, taken verbatim from the
reference: Clean, Normalize, ShortQuery, Parse (every attribute), Readable and
SameRelease. Inputs: real release names (CORPUS, one per line, optional) and
random names built from release-name parts: titles, years, episodes and ranges,
resolutions, sources, codecs, audio and channels, HDR tags, networks,
editions, groups, extensions and volume suffixes, indexer junk, [tags] and
{tags}, separators, bytes above 0x7f and NULs, beyond MaxNameLength.

The harness runs under the environment's LC_CTYPE, as nzbget does.

Usage: releasename_differential.py BUILD_DIR [ROUNDS] [CORPUS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "9c36443d"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "400000"
CORPUS = Path(sys.argv[3]) if len(sys.argv) > 3 else None

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/dupesearch/ReleaseName.cpp"], cwd=ROOT, text=True)
old_hdr = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/dupesearch/ReleaseName.h"], cwd=ROOT, text=True)
for needle in ('"\\\\.(part\\\\d+\\\\.rar|vol\\\\d+\\\\+\\\\d+\\\\.par2|7z\\\\.\\\\d{3}|r\\\\d{2}|z\\\\d{2}|nzb|mkv|mp4|m4v|avi|ts|"',
               '"chamele0n|sample|repost))+$", std::regex::icase);',
               'static const std::regex episodeRange("([sS]\\\\d{1,3}(?:[eE]\\\\d{1,4})*[eE](\\\\d{1,4}))-[eE]?(\\\\d{1,4})(?![0-9A-Za-z])");',
               'static const std::regex audioRegex("^(ddpa|ddp|dd|eac3|ac3|aac|dtshd|dtsx|dtses|dts|truehd|flac|opus|mp3|lpcm|pcm)(\\\\d?)$");',
               'if (isspace((unsigned char)ch) || strchr("._-()+,", ch))',
               'for (size_t pos = text.find(join.first); pos != std::string::npos; pos = text.find(join.first, pos + join.second.size()))'):
    assert needle in old_src, needle
body = old_src[old_src.index("namespace\n{\n\nbool IsDigits"):]
decl = old_hdr[old_hdr.index("class ReleaseName"):old_hdr.index("#endif")]

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))

corpus = []
if CORPUS and CORPUS.exists():
    corpus = [l for l in CORPUS.read_bytes().split(b"\n") if l]
corpus_c = "".join('"%s",\n' % "".join("\\x%02x" % b for b in l) for l in corpus[:20000]) or '"",\n'

main = r'''
#include "nzbget.h"
#include <chrono>
#include <clocale>
#include <cstring>
#include <regex>
#include <set>
#include <string>
#include <vector>
#include "DupeUtil.h"
#include "nzbget_rs.h"
using DupeUtil::Lower;
using DupeUtil::Trim;

namespace old_impl {
''' + decl + body + r'''
}

typedef old_impl::ReleaseName::Attrs Attrs;

static std::string Take(NzbgetRsBuf buf) { std::string s(buf.data, buf.len); nzbget_rs_free(buf); return s; }

static std::string Encode(const Attrs& a)
{
	std::string out;
	auto u32 = [&](uint32_t v) { out.append((const char*)&v, 4); };
	auto str = [&](const std::string& s) { u32((uint32_t)s.size()); out += s; };
	for (const std::set<std::string>* set : {&a.resolution, &a.quality, &a.codec, &a.bitDepth, &a.audio, &a.channels,
		&a.network, &a.edition, &a.hdr})
	{
		u32((uint32_t)set->size());
		for (const std::string& v : *set) str(v);
	}
	str(a.title);
	str(a.group);
	for (const std::vector<int>* list : {&a.seasons, &a.episodes})
	{
		u32((uint32_t)list->size());
		for (int v : *list) u32((uint32_t)v);
	}
	u32((uint32_t)a.year);
	out += (char)a.repack;
	out += (char)a.proper;
	return out;
}

static const char* CORPUS[] = {
''' + corpus_c + r'''};

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static std::string RandomName()
{
	static const char* const TITLES[] = {"Show", "The.Show", "Dark Matter 2024", "1917", "2001.A.Space.Odyssey",
		"13.Reasons.Why", "Game.of.Thrones", "Star_City", "Mr.Robot", "Der Tatort", "x", "", "Quiet Harbour"};
	static const char* const MARKS[] = {"S01E02", "s1e2", "S01", "S01E01E02", "S01E01-E03", "S01E01-03", "S01E05-02",
		"S01E01-2023", "1x02", "12x105", "S1234", "S01E12345", "2019", "1999", "2024", "", "S02E14-E70", "S01E01-e03x"};
	static const char* const PARTS[] = {"1080p", "2160p", "720p", "1080i", "4K", "UHD", "FHD", "WEB-DL", "WEB", "WEBRip",
		"BluRay", "Blu-Ray", "BDRip", "REMUX", "HDTV", "x265", "H.265", "H 264", "HEVC", "AV1", "10bit", "Hi10P", "8bit",
		"DDP5.1", "DD+5.1", "EAC3", "E-AC-3", "DTS-HD.MA.5.1", "DTS-X", "TrueHD.7.1", "Atmos", "AAC2.0", "6ch", "DV",
		"Dolby Vision", "DoVi", "HDR", "HDR10", "HDR10+", "HDR10Plus", "HLG", "SDR", "REPACK", "REPACK2", "RERIP",
		"PROPER", "AMZN", "NF", "Netflix", "HMAX", "ATVP", "DSNP", "Extended", "IMAX", "Hybrid", "DC", "MA", "HD", "5",
		"1", "Title", "Part", "Love.and.Be.Loved", "DDPA5.1", "dts", "hd"};
	static const char* const GROUPS[] = {"-GRP", "-FLUX", "-NTb", "-playWEB", "-x", "-hd", "-DL", "-e", "", "-",
		"-\"GRP\"", "-GRP.Name", "-Fr334ALL", "- GRP"};
	static const char* const TAILS[] = {"", ".mkv", ".nzb", ".part01.rar", ".vol07+08.par2", ".7z.001", ".r01", ".001",
		".h.265", ".x.264", "-xpost", "-obfuscated", ".sample", "-rakuvFIN_x", " [nzbgeek]", "{tag}", "[01/17]",
		".PAR2", ".Rar", "-RePost", "-AsRequested", ".mkv.nzb", "[unclosed", "{a}{b}"};
	static const char* const SEPS[] = {".", " ", "_", "-", "..", " - ", "+", ",", "(", ")"};
	std::string s;
	if (below(6) == 0) s += pick(TAILS);
	s += pick(TITLES);
	int parts = below(10);
	if (below(3)) { s += pick(SEPS); s += pick(MARKS); }
	for (int i = 0; i < parts; i++) { s += pick(SEPS); s += pick(PARTS); }
	s += pick(GROUPS);
	for (int n = below(3); n > 0; n--) s += pick(TAILS);
	// noise: case flips, odd bytes, NULs, length
	for (int n = below(4) == 0 ? 1 + below(4) : 0; n > 0 && !s.empty(); n--)
	{
		size_t at = below((int)s.size());
		switch (below(5))
		{
			case 0: s[at] = (char)(0x80 + below(128)); break;
			case 1: s[at] = 0; break;
			case 2: s[at] ^= 0x20; break;
			case 3: s.insert(at, std::string(1, "[]{}-.\"' \t"[below(10)])); break;
			default: s.insert(at, std::string(1, (char)(1 + below(126)))); break;
		}
	}
	if (below(200) == 0) s = std::string(400 + below(400), 'a') + s;
	return s;
}

int main(int argc, char** argv)
{
	setlocale(LC_CTYPE, "");
	long rounds = atol(argv[1]);
	long failures = 0;
	size_t corpusSize = sizeof(CORPUS) / sizeof(CORPUS[0]);
	std::string previous = "Show.S01E02.1080p.WEB.H264-GRP";
	for (long round = 0; round < rounds; round++)
	{
		std::string name = (round < (long)corpusSize) ? std::string(CORPUS[round]) : RandomName();
		auto fail = [&](const char* what) { printf("%s mismatch round %ld: ", what, round);
			for (unsigned char c : name) printf(c >= 32 && c < 127 ? "%c" : "\\x%02x", c); printf("\n"); failures++; };
		if (old_impl::ReleaseName::Clean(name) != Take(nzbget_rs_releasename_clean(name.data(), name.size()))) fail("Clean");
		if (old_impl::ReleaseName::Normalize(name) != Take(nzbget_rs_releasename_normalize(name.data(), name.size()))) fail("Normalize");
		if (old_impl::ReleaseName::ShortQuery(name) != Take(nzbget_rs_releasename_short_query(name.data(), name.size()))) fail("ShortQuery");
		if (Encode(old_impl::ReleaseName::Parse(name)) != Take(nzbget_rs_releasename_parse(name.data(), name.size()))) fail("Parse");
		if (old_impl::ReleaseName::Readable(name) != (nzbget_rs_releasename_readable(name.data(), name.size()) != 0)) fail("Readable");
		// SameRelease against the previous name, a near variant and itself
		std::string other = below(3) == 0 ? name : below(2) ? previous : RandomName();
		if (old_impl::ReleaseName::SameRelease(name, other) !=
			(nzbget_rs_releasename_same_release(name.data(), name.size(), other.data(), other.size()) != 0)) fail("SameRelease");
		previous = name;
		if (failures > 8) return 1;
	}
	printf("%ld names agree (%zu from the corpus; reference %s)\n", rounds, corpusSize, "''' + REFERENCE + r'''");

	std::vector<std::string> names;
	for (int i = 0; i < 2000; i++) names.push_back(RandomName());
	long sink = 0;
	auto t0 = std::chrono::steady_clock::now();
	for (int r = 0; r < 20; r++) for (auto& n : names) sink += old_impl::ReleaseName::Parse(n).title.size();
	auto t1 = std::chrono::steady_clock::now();
	for (int r = 0; r < 20; r++) for (auto& n : names) sink += Take(nzbget_rs_releasename_parse(n.data(), n.size())).size();
	auto t2 = std::chrono::steady_clock::now();
	printf("Parse x40k: C++ %.1f ms, Rust %.1f ms (sink %ld)\n",
		std::chrono::duration<double, std::milli>(t1 - t0).count(), std::chrono::duration<double, std::milli>(t2 - t1).count(), sink);
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-releasename-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "releasename"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/dupesearch/ReleaseName.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary), str(rust_lib),
                        "-lssl", "-lcrypto", "-lpthread", "-ldl", "-lm"], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True)
