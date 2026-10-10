#!/usr/bin/env python3
"""Compare Scheduler::CheckTasks with its Rust timing (rust/src/scheduler.rs),
and its C++ fallback, against the pre-port C++: the CheckTasks bodies are compiled into a mock
Scheduler and driven through the same task sets, clocks (minute ticks, clock
jumps both ways, local time offsets) and days, comparing the tasks run (and
whether processes may start), the tasks' last runs and the last check time.
Runs under ASan and UBSan and without sanitizers.

Run at idle priority: chrt -i 0 nice -n 19 python3 rust/tests/scheduler_differential.py
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "02c80b7b"


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
#include <utility>
#include <vector>
#include "Container.h"
#include "nzbget_rs.h"
#define debug(...)
struct Mutex {};
struct Guard { Guard(Mutex&) {} };
static time_t g_now;
static int g_offset;
struct WorkState { int GetLocalTimeOffset() { return g_offset; } };
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

int main()
{
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
			a.CheckTasks();
			b.CheckTasks();
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
    cargo = subprocess.run(["cargo", "rustc", "--lib", "--release", "--locked", "--target-dir", str(temp / "target"),
                            "--", "--print", "native-static-libs"], cwd=ROOT / "rust", env=env,
                           capture_output=True, text=True, check=True)
    native = shlex.split(re.search(r"native-static-libs: ([^\r\n]+)", cargo.stdout + cargo.stderr).group(1))
    source = temp / "scheduler.cpp"
    source.write_text(harness)
    for flags in (["-O1", "-fsanitize=address,undefined"], ["-O2"]):
        binary = temp / "scheduler"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-g", "-w", *flags,
                        "-I", str(ROOT / "rust/include"), "-I", str(ROOT / "daemon/util"), str(source),
                        str(temp / "target/release/libnzbget_rs.a"), *native, "-o", str(binary)], check=True, env=env)
        subprocess.run([str(binary)], check=True, env=env)
