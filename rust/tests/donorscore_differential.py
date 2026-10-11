#!/usr/bin/env python3
"""Compare DonorScore (rust/src/donorscore.rs through its C ABI) with the
pre-port C++ of daemon/dupesearch/DonorScore.cpp, taken verbatim from the
reference: Base, Target and Rerank. Random picks, shares (unknown, out of
range, the halves nearbyint sends to even), twins, sizes around the pick and
grabs, with dead entries mixed in.

Usage: donorscore_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "bdd093e0"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "400000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/dupesearch/DonorScore.cpp"], cwd=ROOT, text=True)
for needle in ("return std::max(0, pickScore - 1000);",
               "double share = alive < 0 ? 1.0 : std::min(1.0, alive);",
               "return std::min(Top, 9 + (int)std::nearbyint(80 * share) + (twin ? 1 : 0));",
               "auto percent = [&](const Entry& e) { return (int)std::nearbyint(100 * (e.alive < 0 ? 1.0 : e.alive)); };",
               "std::stable_sort(live.begin(), live.end(), [&](size_t a, size_t b)",
               "int want = std::max(Dead + 1, std::min(Target(entries[i].alive, entries[i].twin), previous - 1));"):
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


old = "\n".join(body(s) for s in ("int DonorScore::Base(int pickScore)", "int DonorScore::Target(double alive, bool twin)",
                                  "std::vector<int> DonorScore::Rerank(const std::vector<Entry>& entries, long long pickBytes)"))

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))

main = r'''
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <set>
#include <vector>
#include "nzbget_rs.h"

namespace old_impl {
struct DonorScore
{
	static constexpr int Dead = 1;
	static constexpr int Top = 90;
	static int Base(int pickScore);
	static int Target(double alive, bool twin);
	struct Entry { int score = 0; double alive = -1; bool twin = false; long long bytes = 0; int grabs = 0; };
	static std::vector<int> Rerank(const std::vector<Entry>& entries, long long pickBytes);
};
''' + old + r'''
}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static double share()
{
	switch (below(8))
	{
		case 0: return -1.0;
		case 1: return below(2) ? 1.0 : 0.0;
		case 2: return (2 * below(80) + 1) / 160.0;       // 80 * share lands on a half (nearbyint: to even)
		case 3: return (2 * below(100) + 1) / 200.0;      // 100 * share lands on a half
		case 4: return 1.0 + below(1000) / 100.0;         // above whole
		case 5: return -below(1000) / 100.0;              // other negatives
		default: return below(1000001) / 1000000.0;
	}
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	long failures = 0;
	for (long round = 0; round < rounds; round++)
	{
		int pick = below(3) ? below(2000000) : (int)(next() % 2000000000) - 1000000000;
		if (old_impl::DonorScore::Base(pick) != nzbget_rs_donorscore_base(pick)) { printf("base %d\n", pick); failures++; }
		double a = share();
		bool twin = below(2);
		if (old_impl::DonorScore::Target(a, twin) != nzbget_rs_donorscore_target(a, twin)) { printf("target %.17g %d\n", a, twin); failures++; }

		long long pickBytes = below(4) ? 1000000000LL + below(1000) : (long long)(next() % 100000000000ULL);
		std::vector<old_impl::DonorScore::Entry> entries;
		std::vector<NzbgetRsDonorEntry> raw;
		for (int n = below(12); n > 0; n--)
		{
			old_impl::DonorScore::Entry e;
			e.score = below(5) ? 2 + below(89) : below(2);
			e.alive = share();
			e.twin = below(4) == 0;
			e.bytes = below(3) ? pickBytes + below(21) - 10 : (long long)(next() % 100000000000ULL);
			e.grabs = below(3) ? below(4) : below(5000);
			entries.push_back(e);
			raw.push_back({e.score, e.alive, e.twin ? 1 : 0, (int64_t)e.bytes, e.grabs});
		}
		std::vector<int> want = old_impl::DonorScore::Rerank(entries, pickBytes);
		std::vector<int> got(raw.size());
		nzbget_rs_donorscore_rerank(raw.data(), raw.size(), (int64_t)pickBytes, got.data());
		if (want != got) { printf("rerank mismatch round %ld\n", round); failures++; }
		if (failures > 5) return 1;
	}
	nzbget_rs_donorscore_rerank(nullptr, 0, 0, nullptr);  // empty: nothing read or written
	// the ties must really occur, or the halves-to-even rule goes untested
	int ties = 0;
	for (int n = 0; n < 80; n++) ties += std::fabs(80 * ((2 * n + 1) / 160.0) - (n + 0.5)) == 0;
	if (ties < 40) { printf("only %d exact halves among the 80 tie shares\n", ties); return 1; }
	printf("%ld rounds agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");

	// timing: 1M Rerank calls of 8 entries each, C++ and Rust in one binary
	std::vector<old_impl::DonorScore::Entry> entries(8);
	std::vector<NzbgetRsDonorEntry> raw(8);
	for (int i = 0; i < 8; i++)
	{
		entries[i] = {2 + below(89), share(), below(4) == 0, 1000000000LL + below(1000), below(4)};
		raw[i] = {entries[i].score, entries[i].alive, entries[i].twin ? 1 : 0, (int64_t)entries[i].bytes, entries[i].grabs};
	}
	long sink = 0;
	std::vector<int> out(8);
	auto t0 = std::chrono::steady_clock::now();
	for (int i = 0; i < 1000000; i++) sink += old_impl::DonorScore::Rerank(entries, 1000000000LL + (i & 255))[i & 7];
	auto t1 = std::chrono::steady_clock::now();
	for (int i = 0; i < 1000000; i++) { nzbget_rs_donorscore_rerank(raw.data(), 8, 1000000000LL + (i & 255), out.data()); sink += out[i & 7]; }
	auto t2 = std::chrono::steady_clock::now();
	printf("Rerank x1M (8 entries): C++ %.1f ms, Rust %.1f ms (sink %ld)\n",
		std::chrono::duration<double, std::milli>(t1 - t0).count(), std::chrono::duration<double, std::milli>(t2 - t1).count(), sink);
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-donorscore-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "donorscore"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/dupesearch/DonorScore.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary), str(rust_lib),
                        "-lpthread", "-ldl", "-lm"], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True)
