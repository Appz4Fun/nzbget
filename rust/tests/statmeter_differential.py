#!/usr/bin/env python3
"""Compare ServerVolume's slot arithmetic (rust/src/statmeter.rs with the C++
wrappers of StatMeter.cpp), and its C++ fallback, with the pre-port C++:
CalcSlots and AddStats driven through the same clocks (second ticks, jumps
both ways, local offset changes, loaded first days) and stats, comparing
every slot, counter array and total after each call.

Each version's CalcSlots and AddStats are compiled into a stand-in
ServerVolume (in its own namespace) with a scripted clock. Directed cases
cover int truncation, ring/day boundaries and deltas in both directions.
Where the original indexes negative slots, only Rust and the guarded fallback
are run. Original abs(INT_MIN), backward secDelta overflow, and time_t
subtraction overflow are excluded from the differential comparison.

Usage: statmeter_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "4000"


def bodies(src):
    out = []
    for sig in ("void ServerVolume::CalcSlots(time_t locCurTime)", "void ServerVolume::AddStats(Stats stats)"):
        i = src.index(sig + "\n{")
        out.append(src[i:src.index("\n}\n", i) + 3])
    consts = src[src.index("static const int DAYS_UP_TO_2013_JAN_1"):src.index("#ifdef NZBGET_USE_RUST\nvoid ServerVolume::CalcSlots")
                 if "#ifdef NZBGET_USE_RUST\nvoid ServerVolume::CalcSlots" in src else src.index("void ServerVolume::CalcSlots")]
    return consts + "".join(out)


def rust_and_fallback(src):
    """The new file's two definitions of each function: the Rust one (under
    NZBGET_USE_RUST) and the C++ fallback (after #else)."""
    return src[src.index("static const int DAYS_UP_TO_2013_JAN_1"):src.index("void ServerVolume::Reset()")]


STANDIN = r'''
static time_t g_now;
static int g_offset;
struct Util
{
	static time_t CurrentTime() { return g_now; }
	template <typename From, typename To> static constexpr To SafeIntCast(From num) noexcept { return ::Util::SafeIntCast<From, To>(num); }
};
struct WorkState { int GetLocalTimeOffset() { return g_offset; } };
static WorkState workState;
static WorkState* g_WorkState = &workState;
class ServerVolume
{
public:
	struct Articles { uint32 failed; uint32 success; };
	struct Stats { uint32 bytes; Articles articles; };
	using VolumeArray = std::vector<int64>;
	using ArticlesArray = std::vector<Articles>;
	void AddStats(Stats stats);
	void CalcSlots(time_t locCurTime);
	VolumeArray m_bytesPerSeconds = VolumeArray(60);
	VolumeArray m_bytesPerMinutes = VolumeArray(60);
	VolumeArray m_bytesPerHours = VolumeArray(24);
	VolumeArray m_bytesPerDays;
	ArticlesArray m_articlesPerDays;
	int m_firstDay = 0;
	int64 m_totalBytes = 0;
	int64 m_customBytes = 0;
	time_t m_dataTime = 0;
	int m_secSlot = 0;
	int m_minSlot = 0;
	int m_hourSlot = 0;
	int m_daySlot = 0;
	std::string State() const
	{
		// the scalars, and a hash of the arrays (the days ones can be long)
		unsigned long long h = 1469598103934665603ull;
		auto mix = [&h](unsigned long long v) { h = (h ^ v) * 1099511628211ull; };
		for (const VolumeArray* a : {&m_bytesPerSeconds, &m_bytesPerMinutes, &m_bytesPerHours, &m_bytesPerDays})
		{
			mix(a->size());
			for (int64 v : *a) mix((unsigned long long)v);
		}
		mix(m_articlesPerDays.size());
		for (const Articles& a : m_articlesPerDays) mix(((unsigned long long)a.failed << 32) | a.success);
		return std::to_string(m_secSlot) + "," + std::to_string(m_minSlot) + "," + std::to_string(m_hourSlot) + "," +
			std::to_string(m_daySlot) + "," + std::to_string(m_firstDay) + "," + std::to_string(m_totalBytes) + "," +
			std::to_string(m_customBytes) + "," + std::to_string((long long)m_dataTime) + "|" + std::to_string(h) + "|" +
			std::to_string(m_bytesPerSeconds[0]) + "," + std::to_string(m_bytesPerMinutes[0]) + "," + std::to_string(m_bytesPerHours[0]);
	}
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/nntp/StatMeter.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/nntp/StatMeter.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

main = r'''
#include "nzbget.h"
#include "Util.h"
#include "nzbget_rs.h"
#include <string>
#include <vector>
#include <limits>

namespace oldimpl {
''' + STANDIN + bodies(old_src) + r'''
}
namespace newimpl {
''' + STANDIN + rust_and_fallback(new_src) + r'''
}
#undef NZBGET_USE_RUST
namespace fallbackimpl {
''' + STANDIN + rust_and_fallback(new_src) + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static long long below(long long n) { return (long long)(next() % (unsigned long long)n); }

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]), calls = 0;
	// CalcSlots itself is defined for negative int times; it must retain C's
	// signed remainders and truncation toward zero, not Euclidean division.
	const long long WRAP = 1LL << 32;
	const long long times[] = {
		std::numeric_limits<long long>::min(), std::numeric_limits<long long>::max(),
		-2147483649LL, -2147483648LL, -86401, -86400, -86399, -3601, -3600,
		-3599, -61, -60, -59, -1, 0, 1, 59, 60, 61, 3599, 3600, 3601,
		86399, 86400, 86401, 2147483646, 2147483647, 2147483648LL,
		WRAP - 1, WRAP, WRAP + 1, WRAP + 1791635696, -WRAP + 1791635696,
		15705LL * 86400 - 1, 15705LL * 86400, 15706LL * 86400,
		23025LL * 86400 - 1, 23025LL * 86400, 23025LL * 86400 + 1,
	};
	const long long deltas[] = {
		-2 * WRAP - 61, -WRAP, -WRAP + 61, -2147483646LL, -86401, -86400,
		-86399, -3601, -3600, -3599, -61, -60, -59, -1, 0, 1, 59, 60, 61,
		3599, 3600, 3601, 86399, 86400, 86401, 2147483647, WRAP - 61,
		WRAP, 2 * WRAP + 61,
	};
	for (long long t : times)
	{
		// This harness may also be used with a 32-bit time_t build.
		if (t < std::numeric_limits<time_t>::min() || t > std::numeric_limits<time_t>::max()) continue;
		for (int first : {-400, 0, 1, 15705, 20700, 23025, 30000})
		{
			oldimpl::ServerVolume a;
			newimpl::ServerVolume b;
			fallbackimpl::ServerVolume c;
			a.m_firstDay = b.m_firstDay = c.m_firstDay = first;
			// Day arrays grow independently and never shrink.
			a.m_bytesPerDays.resize(7); b.m_bytesPerDays.resize(7); c.m_bytesPerDays.resize(7);
			a.m_articlesPerDays.resize(13); b.m_articlesPerDays.resize(13); c.m_articlesPerDays.resize(13);
			a.CalcSlots(t); b.CalcSlots(t); c.CalcSlots(t);
			if (a.State() != b.State() || a.State() != c.State())
			{
				fprintf(stderr, "CalcSlots mismatch: t %lld first %d\n", t, first);
				return 1;
			}
			calls++;
		}
		for (long long delta : deltas)
		{
			if (delta < std::numeric_limits<time_t>::min() || delta > std::numeric_limits<time_t>::max()) continue;
			if (delta > 0 && t < std::numeric_limits<time_t>::min() + delta) continue;
			if (delta < 0 && t > std::numeric_limits<time_t>::max() + delta) continue;
			for (int previous : {0, 1, 23, 59})
			{
				oldimpl::ServerVolume a;
				newimpl::ServerVolume b;
				fallbackimpl::ServerVolume c;
				a.m_dataTime = b.m_dataTime = c.m_dataTime = t - delta;
				a.m_minSlot = b.m_minSlot = c.m_minSlot = previous;
				a.m_hourSlot = b.m_hourSlot = c.m_hourSlot = previous;
				for (auto* array : {&a.m_bytesPerSeconds, &a.m_bytesPerMinutes, &a.m_bytesPerHours,
					&b.m_bytesPerSeconds, &b.m_bytesPerMinutes, &b.m_bytesPerHours,
					&c.m_bytesPerSeconds, &c.m_bytesPerMinutes, &c.m_bytesPerHours})
					for (size_t i = 0; i < array->size(); i++) (*array)[i] = (1LL << 40) + i;
				oldimpl::g_now = newimpl::g_now = fallbackimpl::g_now = t;
				oldimpl::g_offset = newimpl::g_offset = fallbackimpl::g_offset = 0;
				a.CalcSlots(t);
				// Restore the previous slots after checking whether the old writes are defined.
				bool defined = a.m_secSlot >= 0 && a.m_minSlot >= 0 && a.m_hourSlot >= 0;
				a.m_minSlot = a.m_hourSlot = previous;
				if (defined) a.AddStats({0xffffffffu, {3, 5}});
				b.AddStats({0xffffffffu, {3, 5}});
				c.AddStats({0xffffffffu, {3, 5}});
				if ((defined && a.State() != b.State()) || b.State() != c.State())
				{
					fprintf(stderr, "AddStats mismatch: t %lld delta %lld previous %d\n", t, delta, previous);
					return 1;
				}
				calls++;
			}
		}
	}
	const long long LIMIT = 2147483647LL - 50400;  // local times stay within a C int
	for (long round = 0; round < rounds; round++)
	{
		oldimpl::ServerVolume a;
		newimpl::ServerVolume b;
		fallbackimpl::ServerVolume c;
		long long now = below(5) == 0 ? 50400 + below(1000000) : 1356998400LL + below(LIMIT - 1356998400LL - 86400 * 400);
		// a loaded first day: none, recent, or anywhere (long day arrays)
		int firstDay = below(3) == 0 ? 0 : below(4) ? (int)(now / 86400 - below(400)) : (int)below(30000);
		a.m_firstDay = b.m_firstDay = c.m_firstDay = firstDay;
		long long dataTime = below(4) == 0 ? 0 : now - below(200000) + 100000;
		if (dataTime < 50400) dataTime = 50400;
		a.m_dataTime = b.m_dataTime = c.m_dataTime = dataTime;
		static const int OFFSETS[] = {0, 3600, -3600, 7200, -18000, 19800, 20700, 34200, 46800, 50400, -36000, -43200};
		int offset = OFFSETS[below(12)];
		int steps = 1 + (int)below(round % 10 == 0 ? 2000 : 150);
		for (int step = 0; step < steps; step++)
		{
			switch (below(30))
			{
				case 0: now += 60 * 60 + below(86400 * 3); break;
				case 1: now -= 1 + below(86400); break;
				case 2: now += 60 * below(120); break;
				case 3: offset = OFFSETS[below(12)]; break;
				case 4: break;
				default: now += below(3);
			}
			if (now < 50400) now = 50400;
			if (now > LIMIT) now = LIMIT;
			oldimpl::g_now = newimpl::g_now = fallbackimpl::g_now = now;
			oldimpl::g_offset = newimpl::g_offset = fallbackimpl::g_offset = offset;
			uint32 bytes = below(10) == 0 ? (uint32)next() : (uint32)below(800000);
			uint32 failed = (uint32)below(3), success = (uint32)below(5);
			if (below(20) == 0)
			{
				long long t = now + offset + below(86400 * 2) - 86400;
				if (t < 0) t = 0;
				a.CalcSlots(t);
				b.CalcSlots(t);
				c.CalcSlots(t);
			}
			else
			{
				a.AddStats({bytes, {failed, success}});
				b.AddStats({bytes, {failed, success}});
				c.AddStats({bytes, {failed, success}});
			}
			std::string x = a.State(), y = b.State(), z = c.State();
			if (x != y || x != z)
			{
				fprintf(stderr, "mismatch: round %ld step %d now %lld offset %d\nold:      %s\nrust:     %s\nfallback: %s\n",
					round, step, now, offset, x.c_str(), y.c_str(), z.c_str());
				return 1;
			}
			calls++;
		}
	}
	printf("%ld calls agree (reference %s)\n", calls, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-statmeter-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "statmeter"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS], check=True)
