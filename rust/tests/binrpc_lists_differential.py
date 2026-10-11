#!/usr/bin/env python3
"""Compare the binary remote protocol's list responses - List (nzb, pp
parameter and file entries, with and without a regex), Log, PostQueue and
History - built through rust/src/binrpc.rs with the pre-port C++ writers,
both compiled from source with a fake connection that feeds the request
and records every byte sent, on the same random queue, history and log:
strings of every length (all padding cases), parameters, files, post jobs,
history entries of every kind. Allocations are zeroed (malloc
interposed, ASan's fill byte 0) so fields a kind doesn't set compare as 0.
A negative Log line count is compared with the old answer for 0.

Usage: binrpc_lists_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "1f762c4e"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "3000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/BinRpc.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/remote/BinRpc.cpp").read_text()


def function(src, name):
    """A command's Execute with its #ifdef NZBGET_USE_RUST / #else / #endif
    pair when it has one."""
    a = src.index("void %s::Execute()" % name)
    head = "#ifdef NZBGET_USE_RUST\n"
    if src[:a].endswith(head):
        a -= len(head)
        b = src.index("#endif\n", src.index("#else\n", a)) + len("#endif\n")
    else:
        b = src.index("\n}\n", a) + 3
    return src[a:b]


def extract(src):
    # the command classes, the helpers and the four list commands
    parts = [src[src.index("class BinCommand\n{"):src.index("BinRpcProcessor::BinRpcProcessor()")]]
    helper = "#ifdef NZBGET_USE_RUST\n// The trailing data of a list response"
    i = src.index(helper) if helper in src else src.index("//*****************************************************************\n// Commands")
    parts.append(src[i:src.index("void PauseUnpauseBinCommand::Execute()")])
    for name in ("ListBinCommand", "LogBinCommand", "PostQueueBinCommand", "HistoryBinCommand"):
        parts.append(function(src, name))
    return re.sub(r"\bRegEx\b", "RecordingRegEx",
                  re.sub(r"\bConnection\*", "FakeConnection*", "\n".join(parts)))


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
#include "BinRpc.h"
#include "Log.h"
#include "Options.h"
#include "WorkState.h"
#include "QueueEditor.h"
#include "Util.h"
#include "FileSystem.h"
#include "DownloadInfo.h"
#include "Scanner.h"
#include "StatMeter.h"
#include "UrlCoordinator.h"
#include "nzbget_rs.h"
#include <arpa/inet.h>
#include <malloc.h>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
''' + globals_block + r'''

#ifndef __SANITIZE_ADDRESS__
// zero every allocation, so fields a kind doesn't set compare
extern "C" void* __libc_malloc(size_t);
extern "C" void* __libc_realloc(void*, size_t);
extern "C" void* malloc(size_t n) { void* p = __libc_malloc(n); if (p) memset(p, 0, n); return p; }
extern "C" void* realloc(void* p, size_t n)
{
	size_t old = p ? malloc_usable_size(p) : 0;
	void* q = __libc_realloc(p, n);
	if (q && n > old) memset((char*)q + old, 0, n - old);
	return q;
}
#endif

// the request after its base, then every byte sent
class FakeConnection
{
public:
	std::string input;
	size_t at = 0;
	std::string sent;
	std::vector<int> sends;
	bool Recv(char* buffer, int size)
	{
		if (size < 0 || at + size > input.size()) return false;
		memcpy(buffer, input.data() + at, size);
		at += size;
		return true;
	}
	bool Send(const char* buffer, int size) { sends.push_back(size); sent.append(buffer, size); return true; }
	const char* GetRemoteAddr() { return "127.0.0.1"; }
};

class QueueMock final : public DownloadQueue
{
public:
	QueueMock() { Init(this); Loaded(); }
	~QueueMock() { Final(); }
	bool EditEntry(int, EEditAction, const char*) override { return false; }
	bool EditList(IdList*, NameList*, EMatchMode, EEditAction, const char*) override { return false; }
	void HistoryChanged() override {}
	void Save() override {}
	void SaveChanged() override {}
};

static std::vector<std::string> matchCalls;
class RecordingRegEx : public RegEx
{
public:
	using RegEx::RegEx;
	bool Match(const char* text)
	{
		matchCalls.emplace_back(text);
		return RegEx::Match(text);
	}
};

struct Result
{
	std::string bytes;
	std::vector<int> sends;
	std::vector<std::string> matches;
	bool operator==(const Result&) const = default;
};

namespace oldimpl {
''' + extract(old_src) + r'''
}
namespace newimpl {
''' + extract(new_src) + r'''
}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static std::string Text(int max)
{
	std::string s;
	for (int n = below(max + 1); n > 0; n--) s += "abcXYZ.-_ /\xc3\xa9"[below(13)];
	return s;
}

static void Fill(QueueMock& queue)
{
	queue.GetQueue()->clear();
	queue.GetHistory()->clear();
	for (int n = below(5); n > 0; n--)
	{
		auto nzb = std::make_unique<NzbInfo>();
		nzb->SetKind(below(5) ? NzbInfo::nkNzb : NzbInfo::nkUrl);
		nzb->SetFilename(Text(9).c_str());
		nzb->SetName(Text(9).c_str());
		nzb->SetDestDir(Text(9).c_str());
		nzb->SetCategory(Text(5).c_str());
		nzb->SetQueuedFilename(Text(9).c_str());
		nzb->SetPriority(below(200) - 100);
		nzb->SetSize(((int64)next() >> below(40)));
		nzb->SetRemainingSize((int64)next() >> below(40));
		nzb->SetPausedSize((int64)next() >> below(40));
		nzb->SetRemainingParCount(below(20));
		for (int p = below(3); p > 0; p--) nzb->GetParameters()->SetParameter(Text(6).c_str(), Text(6).c_str());
		for (int f = below(4); f > 0; f--)
		{
			auto file = std::make_unique<FileInfo>();
			file->SetSubject(Text(12).c_str());
			file->SetFilename(Text(9).c_str());
			file->SetSize(((int64)next() >> below(40)));
			file->SetRemainingSize(((int64)next() >> below(40)));
			file->SetPaused(below(2));
			file->SetFilenameConfirmed(below(2));
			file->SetNzbInfo(nzb.get());
			nzb->GetFileList()->Add(std::move(file));
		}
		if (below(3) == 0)
		{
			nzb->EnterPostProcess();
			PostInfo* post = nzb->GetPostInfo();
			post->SetStage((PostInfo::EStage)below(5));
			post->SetStageProgress(below(1001));
			post->SetFileProgress(below(1001));
			post->SetProgressLabel(Text(10).c_str());
		}
		queue.GetQueue()->Add(std::move(nzb), false);
	}
	for (int n = below(5); n > 0; n--)
	{
		int kind = below(3);
		if (kind < 2)
		{
			auto nzb = std::make_unique<NzbInfo>();
			nzb->SetKind(kind == 0 ? NzbInfo::nkNzb : NzbInfo::nkUrl);
			nzb->SetName(Text(11).c_str());
			nzb->SetSize(((int64)next() >> below(40)));
			nzb->SetFileCount(below(100));
			nzb->SetParStatus((NzbInfo::EParStatus)below(4));
			nzb->SetUrlStatus((NzbInfo::EUrlStatus)below(4));
			auto history = std::make_unique<HistoryInfo>(std::move(nzb));
			history->SetTime(below(1000000));
			queue.GetHistory()->Add(std::move(history), false);
		}
		else
		{
			auto dup = std::make_unique<DupInfo>();
			dup->SetName(Text(11).c_str());
			dup->SetSize(((int64)next() >> below(40)));
			auto history = std::make_unique<HistoryInfo>(std::move(dup));
			history->SetTime(below(1000000));
			queue.GetHistory()->Add(std::move(history), false);
		}
	}
	GuardedMessageList messages = g_Log->GuardMessages();
	messages->clear();
	for (int n = below(6); n > 0; n--)
		messages->emplace_back(1000 + n, (Message::EKind)below(5), (time_t)below(100000), Text(14).c_str());
}

template <class Req> static std::string Request(int type, Req& request)
{
	memset(&request, 0, sizeof(request));
	SNzbRequestBase& base = request.m_messageBase;
	base.m_signature = htonl(NZBMESSAGE_SIGNATURE);
	base.m_structSize = htonl(sizeof(request));
	base.m_type = htonl(type);
	return std::string();
}

template <class Command, class Req> static Result Run(Req& request)
{
	matchCalls.clear();
	FakeConnection connection;
	connection.input.assign((const char*)&request + sizeof(SNzbRequestBase), sizeof(request) - sizeof(SNzbRequestBase));
	Command command;
	command.SetConnection(&connection);
	command.SetMessageBase(&request.m_messageBase);
	command.Execute();
	return {connection.sent, connection.sends, matchCalls};
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	g_Log = new Log();
	QueueMock queue;
	long failures = 0;
	// A negative line count asks for no entries: the answer is the old one
	// for a count of 0.
	for (int lines : {-1, -134217728, -268435457, -268435456, -268435455, INT_MIN, INT_MIN + 1, INT_MAX})
	{
		for (uint32 idFrom : {0u, 1u, 1000u, 1003u, 1008u, 0x80000000u, 0xffffffffu})
		{
			Fill(queue);
			SNzbLogRequest req;
			Request(rrLog, req);
			req.m_lines = htonl(lines);
			req.m_idFrom = htonl(idFrom);
			SNzbLogRequest oracle = req;
			oracle.m_lines = htonl(std::max(lines, 0));
			if (Run<oldimpl::LogBinCommand>(oracle) != Run<newimpl::LogBinCommand>(req))
			{
				printf("log boundary mismatch: lines %d idFrom %u\n", lines, idFrom);
				return 1;
			}
		}
	}
	for (long round = 0; round < rounds; round++)
	{
		Fill(queue);
		Result a, b;
		int which = below(4);
		if (which == 0)
		{
			SNzbListRequest req;
			Request(rrList, req);
			req.m_fileList = htonl(below(5) != 0);
			req.m_serverState = 0;
			int mode = below(3);
			req.m_matchMode = htonl(mode == 2 ? rmRegEx : rmId);
			req.m_matchGroup = htonl(below(2));
			const char* patterns[] = {"a", "[", "", "^", "a|X", "[[:alpha:]]", "(ab)+", "\\\\"};
			strcpy(req.m_pattern, patterns[below(8)]);
			a = Run<oldimpl::ListBinCommand>(req);
			b = Run<newimpl::ListBinCommand>(req);
		}
		else if (which == 1)
		{
			SNzbLogRequest req;
			Request(rrLog, req);
			int choice = below(4);
			int lines = choice == 0 ? 0 : choice == 1 ? below(8) : choice == 2 ? -below(5) : 0;
			req.m_lines = htonl(lines);
			req.m_idFrom = htonl(choice == 3 ? 1000 + below(8) : 0);
			SNzbLogRequest oracle = req;
			oracle.m_lines = htonl(std::max(lines, 0));
			a = Run<oldimpl::LogBinCommand>(oracle);
			b = Run<newimpl::LogBinCommand>(req);
		}
		else if (which == 2)
		{
			SNzbPostQueueRequest req;
			Request(rrPostQueue, req);
			a = Run<oldimpl::PostQueueBinCommand>(req);
			b = Run<newimpl::PostQueueBinCommand>(req);
		}
		else
		{
			SNzbHistoryRequest req;
			Request(rrHistory, req);
			req.m_hidden = htonl(below(2));
			a = Run<oldimpl::HistoryBinCommand>(req);
			b = Run<newimpl::HistoryBinCommand>(req);
		}
		if (a != b)
		{
			printf("mismatch round %ld command %d: %zu vs %zu bytes\n", round, which, a.bytes.size(), b.bytes.size());
			for (size_t i = 0; i < std::max(a.bytes.size(), b.bytes.size()); i++)
				if (i >= a.bytes.size() || i >= b.bytes.size() || a.bytes[i] != b.bytes[i]) { printf("  first difference at byte %zu\n", i); break; }
			if (++failures > 5) return 1;
		}
	}
	printf("%ld responses agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-binrpc-lists-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "lists"
    env = dict(os.environ, ASAN_OPTIONS="malloc_fill_byte=0:max_malloc_fill_size=1073741824:detect_leaks=0")
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]],
                       check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS],
                       check=True, env=env)
