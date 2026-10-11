#!/usr/bin/env python3
"""Compare Posting (rust/src/posting.rs through its C ABI) with the pre-port
C++ of daemon/dupesearch/Posting.cpp, taken verbatim from the reference:
MakeSketch, SameSketch, SamePosting, GroupListings, ListingMismatch and
OrderPostings (SketchOfFile stays C++). Random message-id sets with shared
parts, sketches cut to any length, listings with repeated links, sizes and
dates, relistings inside and just outside the window, missing sizes or dates,
and caps.

Usage: posting_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "ea40c202"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "400000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/dupesearch/Posting.cpp"], cwd=ROOT, text=True)
old_hdr = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/dupesearch/Posting.h"], cwd=ROOT, text=True)
for needle in ("hashes.insert((uint32_t)crc32(0, (const Bytef*)id.data(), (uInt)id.size()));",
               "return common.size() >= std::max((size_t)1, k / 8);",
               "return (double)common.size() > SamePostingShare * (double)std::min(a.size(), b.size());",
               "result.date - first.date <= RelistWindowSec)",
               "return listing.size > 0 && std::llabs(nzbBytes - listing.size) > ListingMismatchShare * (double)listing.size;",
               "if (maxPostings > 0 && ordered.size() > (size_t)(3 * maxPostings))"):
    assert needle in old_src, needle


def body(signature):
    start = old_src.index(signature)
    i = old_src.index("{", start)
    depth = 0
    for j in range(i, len(old_src)):
        depth += {"{": 1, "}": -1}.get(old_src[j], 0)
        if depth == 0:
            return old_src[start:j + 1]
    raise ValueError(signature)


old = "\n".join(body(s) for s in (
    "Posting::Sketch Posting::MakeSketch(const std::vector<std::string>& messageIds)",
    "bool Posting::SameSketch(const Sketch& a, const Sketch& b)",
    "bool Posting::SamePosting(const std::vector<std::string>& a, const std::vector<std::string>& b)",
    "std::vector<Posting::Group> Posting::GroupListings(std::vector<Newznab::Result> results)",
    "bool Posting::ListingMismatch(const Newznab::Result& listing, long long nzbBytes)",
    "std::vector<Posting::Group> Posting::OrderPostings("))
decl = old_hdr[old_hdr.index("class Posting"):old_hdr.index("#endif")]
decl = decl.replace("static bool SketchOfFile(const std::string& path, Sketch& sketch);", "")

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))

main = r'''
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <iterator>
#include <map>
#include <set>
#include <string>
#include <vector>
#include <zlib.h>
#include "nzbget_rs.h"

namespace old_impl {
struct Newznab { struct Result { std::string title, link; long long size = 0; int grabs = 0; time_t date = 0; std::string indexer; }; };
''' + decl + old + r'''
}
using old_impl::Posting;
using Result = old_impl::Newznab::Result;

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static std::vector<std::string> Ids(int base)
{
	std::vector<std::string> ids;
	for (int n = below(5) == 0 ? below(3) : below(400); n > 0; n--)
		ids.push_back("<" + std::to_string(below(3) ? base + below(300) : below(100000)) + "@" + (below(2) ? "x" : "y.z") + ">");
	return ids;
}

static std::vector<Result> Listings()
{
	std::vector<Result> rs;
	static const char* LINKS[] = {"http://h/1", "http://h/2", "http://h/3", "http://i/1", ""};
	for (int n = below(14); n > 0; n--)
	{
		Result r;
		r.link = below(4) ? LINKS[below(5)] : "http://h/" + std::to_string(below(1000));
		r.size = below(6) == 0 ? 0 : below(3) ? 1000000000LL + below(3) * 1000 : (long long)(next() % 100000000000ULL);
		r.date = below(6) == 0 ? 0 : 1700000000 + (below(2) ? below(250) : (long long)below(1000000));
		r.grabs = below(3) ? below(4) : below(10000);
		rs.push_back(r);
		if (below(4) == 0) rs.push_back(r);   // the very same listing twice
	}
	return rs;
}

static std::vector<NzbgetRsListing> Raw(const std::vector<Result>& rs)
{
	std::vector<NzbgetRsListing> raw;
	for (const Result& r : rs) raw.push_back({r.link.data(), r.link.size(), (int64_t)r.size, (int32_t)r.grabs, (int64_t)r.date});
	return raw;
}

typedef std::vector<std::vector<std::string>> Shape;
static Shape Of(const std::vector<Posting::Group>& groups)
{
	Shape s;
	for (const auto& g : groups)
	{
		std::vector<std::string> v;
		for (const Result& r : g) v.push_back(r.link + "|" + std::to_string(r.size) + "|" + std::to_string(r.date) + "|" + std::to_string(r.grabs));
		s.push_back(v);
	}
	return s;
}
static Shape Of(const std::vector<Result>& rs, const std::vector<size_t>& idx, const std::vector<size_t>& sizes, size_t count)
{
	std::vector<Posting::Group> groups;
	size_t at = 0;
	for (size_t g = 0; g < count; g++) { Posting::Group group; for (size_t k = 0; k < sizes[g]; k++) group.push_back(rs[idx[at++]]); groups.push_back(group); }
	return Of(groups);
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	long failures = 0;
	for (long round = 0; round < rounds; round++)
	{
		int base = below(100000);
		std::vector<std::string> a = Ids(base), b = Ids(base);
		Posting::Sketch sa = Posting::MakeSketch(a), sb = Posting::MakeSketch(b);
		std::vector<const char*> ap, bp; std::vector<size_t> al, bl;
		for (auto& s : a) { ap.push_back(s.data()); al.push_back(s.size()); }
		for (auto& s : b) { bp.push_back(s.data()); bl.push_back(s.size()); }
		uint32_t out[64]; size_t len = 99;
		nzbget_rs_posting_sketch(ap.data(), al.data(), ap.size(), out, &len);
		if (std::vector<uint32_t>(out, out + len) != sa) { printf("sketch mismatch round %ld\n", round); failures++; }
		if (below(3) == 0) { sa.resize(below((int)sa.size() + 1)); }
		if (Posting::SameSketch(sa, sb) != (nzbget_rs_posting_same_sketch(sa.data(), sa.size(), sb.data(), sb.size()) != 0)) { printf("same sketch mismatch\n"); failures++; }
		std::sort(a.begin(), a.end()); a.erase(std::unique(a.begin(), a.end()), a.end());
		std::sort(b.begin(), b.end()); b.erase(std::unique(b.begin(), b.end()), b.end());
		ap.clear(); al.clear(); bp.clear(); bl.clear();
		for (auto& s : a) { ap.push_back(s.data()); al.push_back(s.size()); }
		for (auto& s : b) { bp.push_back(s.data()); bl.push_back(s.size()); }
		if (Posting::SamePosting(a, b) != (nzbget_rs_posting_same_posting(ap.data(), al.data(), ap.size(), bp.data(), bl.data(), bp.size()) != 0)) { printf("same posting mismatch\n"); failures++; }

		std::vector<Result> rs = Listings();
		std::vector<NzbgetRsListing> raw = Raw(rs);
		std::vector<size_t> idx(rs.size()), sizes(rs.size()); size_t count = 0;
		nzbget_rs_posting_group(raw.data(), raw.size(), idx.data(), sizes.data(), &count);
		if (Of(Posting::GroupListings(rs)) != Of(rs, idx, sizes, count)) { printf("group mismatch round %ld\n", round); failures++; }
		long long pick = below(2) ? 1000000000LL : (long long)(next() % 100000000000ULL);
		int maxPostings = below(3) ? 0 : below(4) - 1;
		nzbget_rs_posting_order(raw.data(), raw.size(), (int64_t)pick, maxPostings, idx.data(), sizes.data(), &count);
		if (Of(Posting::OrderPostings(rs, pick, maxPostings)) != Of(rs, idx, sizes, count)) { printf("order mismatch round %ld\n", round); failures++; }
		Result listing; listing.size = below(5) == 0 ? -below(100) : below(3) ? 1000 : (long long)(next() % 100000000000ULL);
		long long bytes = below(2) ? listing.size + below(61) - 30 : (long long)(next() % 100000000000ULL);
		if (Posting::ListingMismatch(listing, bytes) != (nzbget_rs_posting_listing_mismatch(listing.size, bytes) != 0)) { printf("mismatch mismatch %lld %lld\n", listing.size, bytes); failures++; }
		if (failures > 5) return 1;
	}
	printf("%ld rounds agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");

	std::vector<std::vector<Result>> sets; for (int i = 0; i < 2000; i++) sets.push_back(Listings());
	std::vector<std::vector<NzbgetRsListing>> raws; for (auto& s : sets) raws.push_back(Raw(s));
	long sink = 0;
	auto t0 = std::chrono::steady_clock::now();
	for (int r = 0; r < 50; r++) for (auto& s : sets) sink += Posting::OrderPostings(s, 1000000000LL, 2).size();
	auto t1 = std::chrono::steady_clock::now();
	std::vector<size_t> idx(64), sizes(64); size_t count;
	for (int r = 0; r < 50; r++) for (auto& s : raws) { nzbget_rs_posting_order(s.data(), s.size(), 1000000000LL, 2, idx.data(), sizes.data(), &count); sink += count; }
	auto t2 = std::chrono::steady_clock::now();
	printf("OrderPostings x100k: C++ %.1f ms, Rust %.1f ms (sink %ld)\n",
		std::chrono::duration<double, std::milli>(t1 - t0).count(), std::chrono::duration<double, std::milli>(t2 - t1).count(), sink);
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-posting-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "posting"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/dupesearch/Posting.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary), str(rust_lib),
                        "-lz", "-lpthread", "-ldl", "-lm"], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True)
