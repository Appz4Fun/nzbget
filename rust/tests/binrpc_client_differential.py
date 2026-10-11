#!/usr/bin/env python3
"""Compare the remote client's reading of list responses (rust/src/binrpc.rs
through its C ABI, as RemoteClient.cpp's Rust branches use it) with the
pre-port C++ of RemoteClient.cpp, taken verbatim from the reference:
BuildFileList's NZB, parameter and file entries, and the Log, PostQueue and
History listings' loops with their printed lines. Responses are built by the
server's entry encoder from random queues, logs and histories (names with
any bytes, every stage, status and kind the old tables cover); the queues
are compared field by field and the listings line by line. Malformed
responses (short data, lengths past the end, strings without their NUL)
are read by the Rust branches only, which must stop without reading past
the data (under ASan).

Usage: binrpc_client_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "100000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/RemoteClient.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/remote/RemoteClient.cpp").read_text()


def body(src, signature):
    start = src.index("\n{", src.index(signature)) + 1
    depth = 0
    for k in range(start, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[start:k + 1]
    raise ValueError(signature)


def old_loop(name, end):
    start = old_src.index(f"\t\tchar* bufPtr = (char*)buf;\n\t\tfor (uint32 i = 0; i < ntohl({name}.m_nrTrailingEntries); i++)")
    return old_src[start:old_src.index(end, start) + len(end)]


def new_loop(name):
    start = new_src.index(f"for (uint32 i = 0; i < ntohl({name}.m_nrTrailingEntries); i++)\n\t\t{{\n\t\t\tRsEntry")
    start = new_src.rindex("#ifdef NZBGET_USE_RUST\n", 0, start) + len("#ifdef NZBGET_USE_RUST\n")
    return new_src[start:new_src.index("#else\n", start)]


helper_at = new_src.index("// One entry of a list response, read by rust/src/binrpc.rs")
helper = new_src[helper_at:new_src.index("#endif", helper_at)]
loops = {
    "Log": (old_loop("LogResponse", "\t\t\tbufPtr += sizeof(SNzbLogResponseEntry) + ntohl(logAnswer->m_textLen);\n\t\t}\n"), new_loop("LogResponse")),
    "PostQueue": (old_loop("PostQueueResponse", "\t\t\t\tntohl(postQueueAnswer->m_progressLabelLen);\n\t\t}\n"), new_loop("PostQueueResponse")),
    "History": (old_loop("HistoryResponse", "\t\t\tbufPtr += sizeof(SNzbHistoryResponseEntry) + ntohl(listAnswer->m_nicenameLen);\n\t\t}\n"), new_loop("HistoryResponse")),
}
build_old = body(old_src, "void RemoteClient::BuildFileList(")
build_new = body(new_src, "void RemoteClient::BuildFileList(")
assert "RsEntry" in build_new and "RsEntry" not in build_old

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))


def client(ns, build, extra=""):
    # the Rust loop over data of any size (a CharBuffer stand-in)
    raw = "\tstruct Raw { const char* p; size_t n; operator const char*() const { return p; } size_t Size() const { return n; } };\n" \
        "\tvoid HistoryRaw(SNzbHistoryResponse& HistoryResponse, const char* data, size_t len)\n\t{\n\t\tRaw buf{data, len};\n" + \
        loops["History"][1] + "\t}\n"
    return f'''
namespace {ns} {{
{extra}
struct DQ {{ NzbList queue; NzbList* GetQueue() {{ return &queue; }} }};
struct Client
{{
	class MatchedNzbInfo: public NzbInfo {{ public: bool m_match; }};
	class MatchedFileInfo: public FileInfo {{ public: bool m_match; }};
	std::string out;
	void printf(const char* format, ...)
	{{
		va_list ap;
		va_start(ap, format);
		char line[4096];
		vsnprintf(line, sizeof(line), format, ap);
		va_end(ap);
		out += line;
	}}
	void BuildFileList(SNzbListResponse* listResponse, const char* trailingData, DQ* downloadQueue)
{build}
	void Log(SNzbLogResponse& LogResponse, CharBuffer& buf)
	{{
{loops["Log"][0 if ns == "old_impl" else 1]}	}}
	void PostQueue(SNzbPostQueueResponse& PostQueueResponse, CharBuffer& buf)
	{{
{loops["PostQueue"][0 if ns == "old_impl" else 1]}	}}
	void History(SNzbHistoryResponse& HistoryResponse, CharBuffer& buf)
	{{
{loops["History"][0 if ns == "old_impl" else 1]}	}}
{raw if ns == "new_impl" else ""}
}};
}}
'''


main = r'''
#include "nzbget.h"
#include "DownloadInfo.h"
#include "MessageBase.h"
#include "Log.h"
#include "Util.h"
#include "nzbget_rs.h"
#include <arpa/inet.h>
#include <cstdarg>
#include <cstring>
#include <string>
#include <vector>

// the daemon's globals the linked objects refer to (unused here)
class Options; Options* g_Options = nullptr;
Log* g_Log = nullptr;
class DiskState; DiskState* g_DiskState = nullptr;
''' + client("old_impl", build_old) + client("new_impl", build_new, helper) + r'''

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }
static uint32 Int() { return below(3) ? below(20) : (uint32)next(); }

static std::string Text()
{
	std::string s;
	for (int n = below(4) ? below(12) : below(300); n > 0; n--) s += (char)(1 + below(255));
	return s;
}

// one entry as the server encodes it
static void Add(NzbgetRsBinBuf* buf, std::vector<uint32> ints, std::vector<std::pair<std::string, size_t>> strings)
{
	std::vector<const char*> texts;
	std::vector<size_t> fields;
	for (auto& s : strings) { texts.push_back(s.first.c_str()); fields.push_back(s.second); }
	nzbget_rs_binrpc_entry(buf, ints.data(), ints.size(), texts.data(), fields.data(), texts.size(), fields.back());
}

// the response's data as the client receives it (a buffer of its length)
static void Take(NzbgetRsBinBuf* buf, CharBuffer& out, uint32& len)
{
	NzbgetRsBuf bytes = nzbget_rs_binrpc_buf_take(buf);
	len = bytes.len;
	out.Clear();
	if (bytes.len)
	{
		out.Reserve(bytes.len);
		memcpy(out, bytes.data, bytes.len);
	}
	nzbget_rs_free(bytes);
}

static long failures = 0;
static void Same(const std::string& a, const std::string& b, const char* what)
{
	if (a != b) { printf("%s mismatch:\n--old--\n%s--new--\n%s", what, a.c_str(), b.c_str()); failures++; }
}

template <class Client, class Q> static std::string Dump(Q& q)
{
	std::string out;
	for (auto& nzb : q.queue)
	{
		auto* m = static_cast<typename Client::MatchedNzbInfo*>(nzb.get());
		out += *CString::FormatStr("nzb %i %i %lli %lli %lli %i %i %i %i %i [%s][%s][%s][%s][%s]\n", nzb->GetId(), (int)nzb->GetKind(),
			nzb->GetSize(), nzb->GetRemainingSize(), nzb->GetPausedSize(), nzb->GetPausedFileCount(), nzb->GetRemainingParCount(),
			nzb->GetPriority(), (int)m->m_match, nzb->GetActiveDownloads(), nzb->GetFilename(), nzb->GetName(), nzb->GetDestDir(),
			nzb->GetCategory(), nzb->GetQueuedFilename());
		for (NzbParameter& p : nzb->GetParameters()) out += *CString::FormatStr(" par [%s]=[%s]\n", p.GetName(), p.GetValue());
		for (FileInfo* file : nzb->GetFileList())
		{
			auto* f = static_cast<typename Client::MatchedFileInfo*>(file);
			out += *CString::FormatStr(" file %i %lli %lli %i %i %i %i [%s][%s]\n", file->GetId(), file->GetSize(),
				file->GetRemainingSize(), (int)file->GetPaused(), (int)file->GetFilenameConfirmed(), file->GetActiveDownloads(),
				(int)f->m_match, file->GetSubject(), file->GetFilename());
		}
	}
	return out;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]), lists = 0, malformed = 0;
	for (long round = 0; round < rounds; round++)
	{
		// a queue
		SNzbListResponse list = {};
		NzbgetRsBinBuf* buf = nzbget_rs_binrpc_buf_new();
		int nzbs = below(4), ppps = nzbs ? below(4) : 0, files = nzbs ? below(5) : 0;
		for (int i = 0; i < nzbs; i++)
			Add(buf, {Int(), (uint32)below(2), Int(), Int(), Int(), Int(), Int(), Int(), Int(), Int(), Int(), (uint32)below(2), 0, 0, 0, 0, 0},
				{{Text(), 12}, {Text(), 13}, {Text(), 14}, {Text(), 15}, {Text(), 16}});
		for (int i = 0; i < ppps; i++) Add(buf, {(uint32)(1 + below(nzbs)), 0, 0}, {{Text(), 1}, {Text(), 2}});
		for (int i = 0; i < files; i++)
			Add(buf, {Int(), (uint32)(1 + below(nzbs)), Int(), Int(), Int(), Int(), (uint32)below(2), (uint32)below(2), (uint32)below(20), (uint32)below(2), 0, 0},
				{{Text(), 10}, {Text(), 11}});
		uint32 len;
		CharBuffer data;
		Take(buf, data, len);
		list.m_trailingDataLength = htonl(len);
		list.m_nrTrailingNzbEntries = htonl(nzbs);
		list.m_nrTrailingPPPEntries = htonl(ppps);
		list.m_nrTrailingFileEntries = htonl(files);
		{
			old_impl::DQ a; new_impl::DQ b;
			old_impl::Client().BuildFileList(&list, data, &a);
			new_impl::Client().BuildFileList(&list, data, &b);
			Same(Dump<old_impl::Client>(a), Dump<new_impl::Client>(b), "queue");
			lists++;
		}

		// a log, a post-queue, a history
		SNzbLogResponse log = {};
		buf = nzbget_rs_binrpc_buf_new();
		int n = below(5);
		for (int i = 0; i < n; i++) Add(buf, {Int(), (uint32)below(6), Int(), 0}, {{Text(), 3}});
		Take(buf, data, len);
		log.m_nrTrailingEntries = htonl(n);
		log.m_trailingDataLength = htonl(len);
		{ old_impl::Client a; new_impl::Client b; a.Log(log, data); b.Log(log, data); Same(a.out, b.out, "log"); }

		SNzbPostQueueResponse post = {};
		buf = nzbget_rs_binrpc_buf_new();
		n = below(5);
		for (int i = 0; i < n; i++)
			Add(buf, {Int(), (uint32)below(15), below(3) ? (uint32)below(1200) : (uint32)next(), Int(), Int(), Int(), 0, 0, 0, 0},
				{{Text(), 6}, {Text(), 7}, {Text(), 8}, {Text(), 9}});
		Take(buf, data, len);
		post.m_nrTrailingEntries = htonl(n);
		post.m_trailingDataLength = htonl(len);
		{ old_impl::Client a; new_impl::Client b; a.PostQueue(post, data); b.PostQueue(post, data); Same(a.out, b.out, "post-queue"); }

		SNzbHistoryResponse history = {};
		buf = nzbget_rs_binrpc_buf_new();
		n = below(5);
		std::vector<size_t> ends;
		for (int i = 0; i < n; i++)
		{
			Add(buf, {Int(), (uint32)below(4), Int(), 0, Int(), below(2) ? 0 : Int(), Int(), (uint32)below(6), (uint32)below(4), (uint32)below(7)},
				{{Text(), 3}});
			ends.push_back(nzbget_rs_binrpc_buf_len(buf));
		}
		Take(buf, data, len);
		history.m_nrTrailingEntries = htonl(n);
		history.m_trailingDataLength = htonl(len);
		{ old_impl::Client a; new_impl::Client b; a.History(history, data); b.History(history, data); Same(a.out, b.out, "history"); }

		// malformed: every cut of the data (into a buffer of exactly that
		// size), with its strings' NULs or without them. The Rust branch
		// prints the entries that fit and stops, reading nothing past the data
		if (round % 8 == 0 && len > 0)
		{
			for (uint32 cut = 0; cut < len; cut++)
			{
				for (int noNul = 0; noNul < 2; noNul++)
				{
					std::vector<char> shortData(data + 0, data + cut);
					// the NULs of the entries' strings (after each 40-byte header)
					if (noNul)
						for (size_t k = 0, start = 0; k < ends.size(); start = ends[k++])
							for (size_t p = start + sizeof(SNzbHistoryResponseEntry); p < ends[k] && p < cut; p++)
								if (shortData[p] == 0) shortData[p] = 'x';
					new_impl::Client b;
					b.HistoryRaw(history, shortData.data(), shortData.size());
					// Let the old loop read only entries whose declared lengths and
					// string terminators fit in the actual data. A NUL can be in a
					// later entry's header, so compare the modified bytes themselves.
					size_t fit = 0;
					while (fit < ends.size() && ends[fit] <= cut)
					{
						size_t name = (fit ? ends[fit - 1] : 0) + sizeof(SNzbHistoryResponseEntry);
						if (!memchr(shortData.data() + name, 0, cut - name)) break;
						fit++;
					}
					SNzbHistoryResponse fitted = history;
					fitted.m_nrTrailingEntries = htonl(fit);
					CharBuffer prefix;
					if (fit) { prefix.Reserve(cut); memcpy(prefix, shortData.data(), cut); }
					old_impl::Client a;
					a.History(fitted, prefix);
					if (a.out != b.out) { printf("cut %u, noNul %i mismatch:\n%s--\n%s", cut, noNul, a.out.c_str(), b.out.c_str()); failures++; }
					malformed++;
				}
			}
		}
		if (failures > 3) return 1;
	}
	printf("%ld queues, %ld rounds of log/post-queue/history listings agree, %ld malformed read (reference %s)\n",
		lists, rounds, malformed, "''' + REFERENCE + r'''");
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-binrpc-client-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "binrpc-client"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only", str(ROOT / "daemon/remote/RemoteClient.cpp")],
                   check=True, cwd=BUILD)
    # the old loops read the data through struct pointers at any offset
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize=alignment", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        str(BUILD / "liblibnzbget.a"), str(rust_lib), *map(str, BUILD.glob("rapidyenc/**/librapidyenc.a")),
                        "-lssl", "-lcrypto", "-lpthread", "-ldl", "-lm", "-lz", "-lxml2", "-lboost_json"], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True,
                       # the client's Matched entries are freed through their bases' pointers, in both versions
                       env={**os.environ, "ASAN_OPTIONS": "new_delete_type_mismatch=0"})
