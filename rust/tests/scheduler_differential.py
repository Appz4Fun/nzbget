#!/usr/bin/env python3
"""Compare Scheduler::CheckTasks with its Rust timing (rust/src/scheduler.rs),
and its C++ fallback, against the pre-port C++: the CheckTasks bodies are compiled into a mock
Scheduler and driven through the same task sets, clocks (minute ticks, clock
jumps both ways, local time offsets) and days, comparing the tasks run (and
whether processes may start), the tasks' last runs and the last check time.
Runs under ASan and UBSan and without sanitizers.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/scheduler_differential.py
Add --debug to exercise Rust's dev profile with overflow checks enabled.
"""
import argparse
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "02c80b7b"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()


def check_tasks(source):
    start = source.index("void Scheduler::CheckTasks()\n{")
    return source[start:source.index("\n}\n", start) + 3]


old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/main/Scheduler.cpp"], cwd=ROOT, text=True)
new = (ROOT / "daemon/main/Scheduler.cpp").read_text()
util = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
timegm = util[util.index("/* From boost */"):util.index("time_t Util::Timegm")]

scheduler = r'''
// range-for over &m_taskList finds Container.h's adapters by ADL: forward them here
template <typename T> auto begin(std::vector<std::unique_ptr<T>>* c) { return ::begin(c); }
template <typename T> auto end(std::vector<std::unique_ptr<T>>* c) { return ::end(c); }
class Scheduler
{
public:
	class Task
	{
	public:
		static const int STARTUP_TASK = -1;
		int m_hours, m_minutes, m_weekDaysBits;
		time_t m_lastExecuted = 0;
	};
	std::vector<std::unique_ptr<Task>> m_taskList;
	Mutex m_taskListMutex;
	time_t m_lastCheck = 0;
	bool m_executeProcess = true;
	std::vector<std::pair<int, bool>> m_run;
	void ExecuteTask(Task* task)
	{
		for (size_t i = 0; i < m_taskList.size(); i++)
			if (m_taskList[i].get() == task) m_run.emplace_back((int)i, m_executeProcess);
	}
	void PrepareLog() {}
	void PrintLog() {}
	void CheckTasks();
};
'''

harness = r'''
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <deque>
#include <list>
#include <memory>
#include <limits>
#include <utility>
#include <vector>
#include "Container.h"
#include "nzbget_rs.h"
#define debug(...)
struct Mutex {};
struct Guard { Guard(Mutex&) {} };
static time_t g_now;
static int g_offset, g_lastOffset, g_offsetReads;
struct WorkState { int GetLocalTimeOffset() { return g_offsetReads++ == 0 ? g_offset : g_lastOffset; } };
static WorkState workState;
static WorkState* g_WorkState = &workState;
''' + timegm + r'''
struct Util
{
	static time_t CurrentTime() { return g_now; }
	static time_t Timegm(tm const* t) { return internal_timegm(t); }
};
namespace oldimpl {
''' + scheduler + check_tasks(old) + r'''
}
namespace newimpl {
#define NZBGET_USE_RUST
''' + scheduler + check_tasks(new) + r'''
#undef NZBGET_USE_RUST
}
namespace fallbackimpl {
''' + scheduler + check_tasks(new) + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }

// Compare a single independently initialized check, including a directly
// guarded FFI buffer. Random walks rarely hit these exact calendar boundaries.
static void boundary_offsets(time_t now, time_t last, int offset, int lastOffset, int hours, int minutes, int mask, time_t executed)
{
	oldimpl::Scheduler a;
	newimpl::Scheduler b;
	fallbackimpl::Scheduler c;
	a.m_lastCheck = b.m_lastCheck = c.m_lastCheck = last;
	a.m_taskList.push_back(std::make_unique<oldimpl::Scheduler::Task>(oldimpl::Scheduler::Task{hours, minutes, mask, executed}));
	b.m_taskList.push_back(std::make_unique<newimpl::Scheduler::Task>(newimpl::Scheduler::Task{hours, minutes, mask, executed}));
	c.m_taskList.push_back(std::make_unique<fallbackimpl::Scheduler::Task>(fallbackimpl::Scheduler::Task{hours, minutes, mask, executed}));
	g_now = now;
	g_offset = offset;
	g_lastOffset = lastOffset;
	g_offsetReads = 0;
	a.CheckTasks();
	int oldOffsetReads = g_offsetReads;
	g_offsetReads = 0;
	b.CheckTasks();
	int newOffsetReads = g_offsetReads;
	g_offsetReads = 0;
	c.CheckTasks();
	int fallbackOffsetReads = g_offsetReads;
	NzbgetRsSchedTask task{hours, minutes, mask, (long long)executed};
	long long check = last;
	int reset = -1;
	const size_t sentinel = std::numeric_limits<size_t>::max();
	std::vector<size_t> guarded(11, sentinel);
	auto calendar = [](long long value, NzbgetRsSchedTm* result) {
			time_t time = value;
			tm fields{};
			gmtime_r(&time, &fields);
			*result = {(long long)fields.tm_year + 1900, fields.tm_mon, fields.tm_mday,
				fields.tm_hour, fields.tm_min, fields.tm_sec, fields.tm_wday};
		};
	size_t n = nzbget_rs_scheduler_check(&task, 1, &check, now, offset, lastOffset, guarded.data() + 1, 9, &reset, calendar);
	bool same = oldOffsetReads == 2 && newOffsetReads == 2 && fallbackOffsetReads == 2;
	if (n > 9)
	{
		same = same && check == last && task.lastExecuted == executed && reset == -1 &&
			std::all_of(guarded.begin(), guarded.end(), [=](size_t value) { return value == sentinel; });
		guarded.assign(n + 2, sentinel);
		n = nzbget_rs_scheduler_check(&task, 1, &check, now, offset, lastOffset, guarded.data() + 1, n, &reset, calendar);
	}
	same = same && a.m_run == b.m_run && a.m_run == c.m_run && n == a.m_run.size() && n <= guarded.size() - 2 &&
		guarded.front() == sentinel && guarded.back() == sentinel &&
		a.m_lastCheck == b.m_lastCheck && a.m_lastCheck == c.m_lastCheck && check == a.m_lastCheck &&
		a.m_executeProcess == b.m_executeProcess && a.m_executeProcess == c.m_executeProcess &&
		(reset == 0) == a.m_executeProcess &&
		a.m_taskList[0]->m_lastExecuted == b.m_taskList[0]->m_lastExecuted &&
		a.m_taskList[0]->m_lastExecuted == c.m_taskList[0]->m_lastExecuted &&
		task.lastExecuted == a.m_taskList[0]->m_lastExecuted;
	for (size_t i = 0; i < n; i++) same = same && guarded[i + 1] == 0;
	if (!same)
	{
		std::fprintf(stderr, "boundary mismatch: now %lld last %lld offsets %d/%d task %d:%d mask %d executed %lld\n",
			(long long)now, (long long)last, offset, lastOffset, hours, minutes, mask, (long long)executed);
		std::exit(1);
	}
}

static void boundary(time_t now, time_t last, int offset, int hours, int minutes, int mask, time_t executed)
{
	boundary_offsets(now, last, offset, offset, hours, minutes, mask, executed);
}

int main()
{
	tzset();
	// StatMeter can update the atomic offset between the two reads in
	// CheckTasks. Preserve each reading, including across an FFI retry.
	for (int offset : {-3600, 0, 3600})
	for (int lastOffset : {-3600, 0, 3600})
	for (int gap : {-1, 0, 60, 5400, 5401})
	for (int hour : {-1, 0, 1, 12, 23})
		boundary_offsets(1791676800, 1791676800 - gap, offset, lastOffset, hour, 0, 0, 0);
	// Different readings can expand the local interval beyond a week even
	// without a UTC clock reset or leap seconds. Exercise capacity retries
	// with processes still enabled, plus the reversed (empty) interval.
	for (int offset : {std::numeric_limits<int>::min(), std::numeric_limits<int>::max()})
	for (int lastOffset : {std::numeric_limits<int>::min(), std::numeric_limits<int>::max()})
	for (int gap : {0, 5400, 5401})
	for (int hour : {-1, 0, 23})
	for (time_t executed : {0, 1})
		boundary_offsets(1791676800, 1791676800 - gap, offset, lastOffset, hour, 0, 0, executed);
	if (std::getenv("NZBGET_SCHEDULER_LEAP_STRESS"))
	{
		// libc accepts TZif corrections larger than a second. Repeated calendar
		// dates can then produce more than nine runs of an unnormalized task.
		boundary(80049600, 0, 0, 336, 0, 0, 0);
		std::puts("large leap-correction check agrees");
		return 0;
	}
	for (time_t now : {78796799, 78796800, 78796801, 78796860})
	for (int gap : {0, 1, 60, 5400, 5401})
	for (int hour : {-1, 0, 23})
		boundary(now, now - gap, 0, hour, 0, 0, 0);
	if (std::getenv("NZBGET_SCHEDULER_LEAP_BOUNDARIES"))
	{
		std::puts("negative leap-second checks agree");
		return 0;
	}
	// The zero last-execution sentinel also denotes the epoch loop day.
	// Exercise it explicitly, along with full-width offsets/masks and the
	// largest task fields whose multiplications are defined in old Timegm.
	for (time_t now : {-86401, -86400, -1, 0, 1, 86399, 86400, 86401})
	for (int gap : {-1, 0, 5400, 5401})
	for (int offset : {0, std::numeric_limits<int>::min(), std::numeric_limits<int>::max()})
	for (int mask : {0, std::numeric_limits<int>::min(), std::numeric_limits<int>::max()})
	for (auto hm : {std::pair<int, int>{-1, 0}, {0, 0},
		{std::numeric_limits<int>::max() / 3600, std::numeric_limits<int>::max() / 60},
		{std::numeric_limits<int>::min() / 3600, std::numeric_limits<int>::min() / 60}})
		boundary(now, now - gap, offset, hm.first, hm.second, mask, 0);
	// Leap and non-leap centuries, year zero and negative years exercise the
	// truncating division in nzbget's Timegm (not libc timegm). All arithmetic
	// stays within the defined range of the original C++ int expressions.
	const int years[] = {-5000000, -400, -100, -4, -1, 0, 1, 4, 100, 400, 1600, 1900, 1969, 1970, 2000, 2038, 2100, 2400, 5000000};
	const int masks[] = {0, 1, 2, 4, 8, 16, 32, 64, 127, 128, -1};
	const int offsets[] = {0, -43200, 50400, 20700, -1, 1};
	const int gaps[] = {-1, 0, 1, 60, 5399, 5400, 5401, 604800};
	long boundaries = 0;
	for (int year : years)
	for (int month : {0, 1, 2, 11})
	for (int day : {1, 28, 29})
	{
		tm t{};
		t.tm_year = year - 1900;
		t.tm_mon = month;
		t.tm_mday = day;
		time_t midnight = internal_timegm(&t);
		for (int second : {-1, 0, 1, 86399})
		for (int gap : gaps)
		for (int offset : offsets)
		for (int mask : masks)
		{
			// Include unnormalized task times: Timegm doesn't recompute the
			// weekday after moving an appointment into the preceding/next day.
			for (auto hm : {std::pair<int, int>{-1, 0}, {-2, 0}, {0, 0}, {23, 59}, {24, 0}, {0, -1}, {12, 60}})
			{
				time_t now = midnight + second;
				time_t executed = boundaries % 3 == 0 ? now + offset : boundaries % 3 == 1 ? 0 : now - 86400;
				boundary(now, now - gap, offset, hm.first, hm.second, mask, executed);
				boundaries++;
			}
		}
	}
	std::printf("%ld boundary checks agree (guarded output with capacity retry)\n", boundaries);
	long checks = 0, runs = 0, resets = 0;
	for (int scenario = 0; scenario < 4000; scenario++)
	{
		oldimpl::Scheduler a;
		newimpl::Scheduler b;
		fallbackimpl::Scheduler c;
		int count = scenario % 50 == 0 ? 0 : 1 + below(scenario % 7 == 0 ? 40 : 6);
		for (int i = 0; i < count; i++)
		{
			int hours = below(10) == 0 ? -1 : below(24);
			int minutes = hours == -1 ? 0 : below(4) == 0 ? 0 : below(60);
			int weekDays = below(3) == 0 ? 0 : below(128);
			a.m_taskList.push_back(std::make_unique<oldimpl::Scheduler::Task>(oldimpl::Scheduler::Task{hours, minutes, weekDays}));
			b.m_taskList.push_back(std::make_unique<newimpl::Scheduler::Task>(newimpl::Scheduler::Task{hours, minutes, weekDays}));
			c.m_taskList.push_back(std::make_unique<fallbackimpl::Scheduler::Task>(fallbackimpl::Scheduler::Task{hours, minutes, weekDays}));
		}
		// 1970 .. 2200, a few before 1970
		g_now = below(20) == 0 ? -(time_t)below(1 << 30) : (time_t)(next() % 7258118400ull);
		const int offsets[] = {0, 3600, -3600, 7200, -18000, 19800, 20700, 34200, 46800, 50400, -36000, -43200, 1800};
		g_offset = offsets[below(sizeof offsets / sizeof *offsets)];
		int steps = 1 + below(scenario % 5 == 0 ? 3000 : 300);
		for (int step = 0; step < steps; step++)
		{
			a.m_executeProcess = b.m_executeProcess = c.m_executeProcess = step > 0;
			a.m_run.clear();
			b.m_run.clear();
			c.m_run.clear();
			g_lastOffset = g_offset;
			g_offsetReads = 0;
			a.CheckTasks();
			g_offsetReads = 0;
			b.CheckTasks();
			g_offsetReads = 0;
			c.CheckTasks();
			bool same = a.m_run == b.m_run && a.m_lastCheck == b.m_lastCheck && a.m_executeProcess == b.m_executeProcess &&
				a.m_run == c.m_run && a.m_lastCheck == c.m_lastCheck && a.m_executeProcess == c.m_executeProcess;
			for (int i = 0; i < count; i++)
				same = same && a.m_taskList[i]->m_lastExecuted == b.m_taskList[i]->m_lastExecuted &&
					a.m_taskList[i]->m_lastExecuted == c.m_taskList[i]->m_lastExecuted;
			if (!same)
			{
				std::fprintf(stderr, "mismatch: scenario %d step %d now %lld offset %d: runs %zu/%zu\n",
					scenario, step, (long long)g_now, g_offset, a.m_run.size(), b.m_run.size());
				return 1;
			}
			checks++;
			runs += a.m_run.size();
			resets += !a.m_executeProcess;
			// mostly minute ticks; sometimes seconds, hours, days, jumps back
			switch (below(40))
			{
				case 0: g_now += 60 * 91 + below(86400 * 9); break;
				case 1: g_now -= 1 + below(86400 * 3); break;
				case 2: g_now += 60 * 90; break;
				case 3: g_now += 60 * 90 + 1; break;
				case 4: g_now += below(60); break;
				case 5: g_offset = offsets[below(sizeof offsets / sizeof *offsets)]; break;
				default: g_now += 60 - 1 + below(3);
			}
		}
	}
	std::printf("%ld checks agree, %ld task runs, %ld resets (reference %s)\n", checks, runs, resets, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-scheduler-") as temp:
    temp = Path(temp)
    env = dict(os.environ, CARGO_BUILD_JOBS="3")
    # UBSan normally reports and continues, which could let a bad oracle or
    # bridge pass this comparison. Make every sanitizer finding fail the run.
    for option in ("ASAN_OPTIONS", "UBSAN_OPTIONS"):
        env[option] = env.get(option, "") + ":halt_on_error=1"
    # A minimal TZif v1 fixture, independent of the host's optional right/*
    # zoneinfo package: one leap second at the end of June 1972. gmtime_r
    # honors this on libc implementations supporting leap-aware timezones.
    leap_zone = temp / "leap-utc"
    leap_zone.write_bytes(b"TZif\0" + bytes(15) + struct.pack(">6I", 0, 0, 1, 0, 1, 4)
                          + struct.pack(">lBB", 0, 0, 0) + b"UTC\0"
                          + struct.pack(">li", 78796800, 1))
    negative_leap_zone = temp / "negative-leap-utc"
    negative_leap_zone.write_bytes(b"TZif\0" + bytes(15) + struct.pack(">6I", 0, 0, 1, 0, 1, 4)
                                   + struct.pack(">lBB", 0, 0, 0) + b"UTC\0"
                                   + struct.pack(">li", 78796800, -1))
    stress_zone = temp / "leap-stress"
    stress_zone.write_bytes(b"TZif\0" + bytes(15) + struct.pack(">6I", 0, 0, 15, 0, 1, 4)
                            + struct.pack(">lBB", 0, 0, 0) + b"UTC\0"
                            + b"".join(struct.pack(">li", 78796800 + i * 86400, 1 + i * 86400)
                                       for i in range(15)))
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--profile", "dev" if args.debug else "release",
                            "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "scheduler.cpp"
    source.write_text(harness)
    for flags in (["-O1", "-fsanitize=address,undefined"], ["-O2"]):
        binary = temp / "scheduler"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-g", "-w", *flags,
                        "-I", str(ROOT / "rust/include"), "-I", str(ROOT / "daemon/util"), str(source),
                        str(temp / "target" / ("debug" if args.debug else "release") / "libnzbget_rs.a"),
                        *native, "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary)], check=True,
                       env=dict(env, TZ=f":{stress_zone}", NZBGET_SCHEDULER_LEAP_STRESS="1"))
        subprocess.run([str(binary)], check=True,
                       env=dict(env, TZ=f":{negative_leap_zone}", NZBGET_SCHEDULER_LEAP_BOUNDARIES="1"))
        for timezone in ("UTC0", f":{leap_zone}"):
            print(f"Checking {'Debug' if args.debug else 'Release'}, {flags}, TZ={timezone}", flush=True)
            subprocess.run([str(binary)], check=True, env=dict(env, TZ=timezone))
