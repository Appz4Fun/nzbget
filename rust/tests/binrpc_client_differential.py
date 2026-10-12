#!/usr/bin/env python3
"""Compare the remote client's reading of list responses (rust/src/binrpc.rs
through its C ABI, as RemoteClient.cpp's Rust branches use it) with the
pre-port C++ of RemoteClient.cpp, taken verbatim from the reference:
BuildFileList's NZB, parameter and file entries, and the Log, PostQueue and
History listings' loops with their printed lines. Responses are built by
an encoder written here, byte by byte as the pre-port server wrote them, from
random queues, logs and histories (names with any bytes, every stage, status
and kind the old tables cover); the queues
are compared field by field and the listings line by line. Cut and
malformed responses (short data, strings without their NUL) are read by the
Rust branches from buffers of exactly their size (under ASan), and compared
with the old code reading the entries that fit.

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


def new_loop(listing):
    start = new_src.index(f"RS_PRINT_LISTING(nzbget_rs_binrpc_{listing}_listing(")
    start = new_src.rindex("#ifdef NZBGET_USE_RUST\n", 0, start) + len("#ifdef NZBGET_USE_RUST\n")
    return new_src[start:new_src.index("#else\n", start)]


helper_at = new_src.index("// One entry of a list response")
helper = new_src[helper_at:new_src.index("#endif", helper_at)]
loops = {
    "Log": (old_loop("LogResponse", "\t\t\tbufPtr += sizeof(SNzbLogResponseEntry) + ntohl(logAnswer->m_textLen);\n\t\t}\n"), new_loop("log")),
    "PostQueue": (old_loop("PostQueueResponse", "\t\t\t\tntohl(postQueueAnswer->m_progressLabelLen);\n\t\t}\n"), new_loop("post_queue")),
    "History": (old_loop("HistoryResponse", "\t\t\tbufPtr += sizeof(SNzbHistoryResponseEntry) + ntohl(listAnswer->m_nicenameLen);\n\t\t}\n"), new_loop("history")),
}
build_old = body(old_src, "void RemoteClient::BuildFileList(")
build_new = body(new_src, "void RemoteClient::BuildFileList(")
assert "RsEntry<" in build_new and "nzbget_rs_binrpc_read" not in build_old

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))


def client(ns, build, extra=""):
    # the Rust loops over data of any size (a CharBuffer stand-in)
    raw = "\tstruct Raw { const char* p; size_t n; operator const char*() const { return p; } size_t Size() const { return n; } };\n"
    for name, response, loop in (("Log", "SNzbLogResponse& LogResponse", loops["Log"][1]),
                                 ("PostQueue", "SNzbPostQueueResponse& PostQueueResponse", loops["PostQueue"][1]),
                                 ("History", "SNzbHistoryResponse& HistoryResponse", loops["History"][1])):
        raw += f"\tvoid {name}Raw({response}, const char* data, size_t len)\n\t{{\n\t\tRaw buf{{data, len}};\n" + loop + "\t}\n"
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
		// any length: the new loops print a whole listing at once
		va_list ap, again;
		va_start(ap, format);
		va_copy(again, ap);
		char line[4096];
		int n = vsnprintf(line, sizeof(line), format, ap);
		va_end(ap);
		if (n < (int)sizeof(line))
		{{
			out.append(line, n);
		}}
		else
		{{
			std::string big(n + 1, '\\0');
			vsnprintf(big.data(), big.size(), format, again);
			out.append(big.data(), n);
		}}
		va_end(again);
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

// the response's bytes as the pre-port server wrote them: an entry's ints
// (host order here, the strings' lengths with their NULs put into their
// fields), the strings, zeros to 4 bytes counted in the last string's length
struct WireBuf { std::string bytes; };
static WireBuf* WireNew() { return new WireBuf; }

static void Add(WireBuf* buf, std::vector<uint32> ints, std::vector<std::pair<std::string, size_t>> strings)
{
	size_t body = ints.size() * 4;
	for (auto& s : strings) { ints[s.second] = s.first.size() + 1; body += s.first.size() + 1; }
	size_t pad = (4 - body % 4) % 4;
	ints[strings.back().second] += pad;
	for (uint32 v : ints) { uint32 be = htonl(v); buf->bytes.append((const char*)&be, 4); }
	for (auto& s : strings) { buf->bytes.append(s.first); buf->bytes.push_back(0); }
	buf->bytes.append(pad, 0);
}

// the response's data as the client receives it (a buffer of its length)
static void Take(WireBuf* buf, CharBuffer& out, uint32& len)
{
	len = buf->bytes.size();
	out.Clear();
	if (len)
	{
		out.Reserve(len);
		memcpy(out, buf->bytes.data(), len);
	}
	delete buf;
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

// The Rust loops over every cut of a response (a buffer of exactly the cut's
// size), with the strings' NULs after the header kept or not, against the old
// loop over the entries that fit: the prefix of the data with their count.
template <class Resp, void (old_impl::Client::*OldFn)(Resp&, CharBuffer&),
	void (new_impl::Client::*RawFn)(Resp&, const char*, size_t)>
static long Cuts(const char* what, Resp& response, const CharBuffer& data, uint32 len, const std::vector<size_t>& ends,
	size_t header, bool noNul)
{
	long reads = 0;
	for (uint32 cut = 0; cut < len; cut++)
	{
		for (int dropNul = 0; dropNul <= (noNul ? 1 : 0); dropNul++)
		{
			std::vector<char> shortData(data + 0, data + cut);
			// the NULs of the entries' strings (after each header)
			if (dropNul)
				for (size_t k = 0, start = 0; k < ends.size(); start = ends[k++])
					for (size_t p = start + header; p < ends[k] && p < cut; p++)
						if (shortData[p] == 0) shortData[p] = 'x';
			new_impl::Client b;
			(b.*RawFn)(response, shortData.data(), shortData.size());
			// Let the old loop read only entries whose declared lengths and
			// string terminators fit in the actual data. A NUL can be in a
			// later entry's header, so compare the modified bytes themselves.
			size_t fit = 0;
			while (fit < ends.size() && ends[fit] <= cut)
			{
				size_t name = (fit ? ends[fit - 1] : 0) + header;
				if (noNul && !memchr(shortData.data() + name, 0, cut - name)) break;
				fit++;
			}
			Resp fitted = response;
			fitted.m_nrTrailingEntries = htonl(fit);
			CharBuffer prefix;
			if (fit) { prefix.Reserve(cut); memcpy(prefix, shortData.data(), cut); }
			old_impl::Client a;
			(a.*OldFn)(fitted, prefix);
			if (a.out != b.out) { printf("%s: cut %u, noNul %i mismatch:\n%s--\n%s", what, cut, dropNul, a.out.c_str(), b.out.c_str()); failures++; }
			reads++;
		}
	}
	return reads;
}

static void AddNzb(WireBuf* buf)
{
	Add(buf, {Int(), (uint32)below(2), Int(), Int(), Int(), Int(), Int(), Int(), Int(), Int(), Int(), (uint32)below(2), 0, 0, 0, 0, 0},
		{{Text(), 12}, {Text(), 13}, {Text(), 14}, {Text(), 15}, {Text(), 16}});
}
static void AddPpp(WireBuf* buf, int nzbs) { Add(buf, {(uint32)(1 + below(nzbs)), 0, 0}, {{Text(), 1}, {Text(), 2}}); }
static void AddFile(WireBuf* buf, int nzbs)
{
	Add(buf, {Int(), (uint32)(1 + below(nzbs)), Int(), Int(), Int(), Int(), (uint32)below(2), (uint32)below(2), (uint32)below(20), (uint32)below(2), 0, 0},
		{{Text(), 10}, {Text(), 11}});
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]), lists = 0, malformed = 0;
	for (long round = 0; round < rounds; round++)
	{
		// a queue
		SNzbListResponse list = {};
		WireBuf* buf = WireNew();
		std::vector<size_t> listEnds;
		int nzbs = below(4), ppps = nzbs ? below(4) : 0, files = nzbs ? below(5) : 0;
		for (int i = 0; i < nzbs; i++) { AddNzb(buf); listEnds.push_back(buf->bytes.size()); }
		for (int i = 0; i < ppps; i++) { AddPpp(buf, nzbs); listEnds.push_back(buf->bytes.size()); }
		for (int i = 0; i < files; i++) { AddFile(buf, nzbs); listEnds.push_back(buf->bytes.size()); }
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
		// the same with more entries than the batches the client reads at a time
		if (round % 16 == 0)
		{
			WireBuf* big = WireNew();
			int bn = 33 + below(40), bp = 33 + below(40), bf = 33 + below(80);
			for (int i = 0; i < bn; i++) AddNzb(big);
			for (int i = 0; i < bp; i++) AddPpp(big, bn);
			for (int i = 0; i < bf; i++) AddFile(big, bn);
			CharBuffer bigData; uint32 bigLen;
			Take(big, bigData, bigLen);
			SNzbListResponse bigList = {};
			bigList.m_trailingDataLength = htonl(bigLen);
			bigList.m_nrTrailingNzbEntries = htonl(bn);
			bigList.m_nrTrailingPPPEntries = htonl(bp);
			bigList.m_nrTrailingFileEntries = htonl(bf);
			old_impl::DQ a; new_impl::DQ b;
			old_impl::Client().BuildFileList(&bigList, bigData, &a);
			new_impl::Client().BuildFileList(&bigList, bigData, &b);
			Same(Dump<old_impl::Client>(a), Dump<new_impl::Client>(b), "big queue");
			// more files announced than the data holds: the old loop reads the ones sent, the new stops there
			bigList.m_nrTrailingFileEntries = htonl(bf + 100);
			new_impl::DQ d;
			new_impl::Client().BuildFileList(&bigList, bigData, &d);
			Same(Dump<old_impl::Client>(a), Dump<new_impl::Client>(d), "queue with more files announced than sent");

			// listings of more than a printf buffer's lines
			int many = 40 + below(60);
			WireBuf* manyLog = WireNew(); WireBuf* manyPost = WireNew(); WireBuf* manyHistory = WireNew();
			for (int i = 0; i < many; i++)
			{
				Add(manyLog, {Int(), (uint32)below(6), Int(), 0}, {{Text(), 3}});
				Add(manyPost, {Int(), (uint32)below(15), (uint32)below(1200), Int(), Int(), Int(), 0, 0, 0, 0},
					{{Text(), 6}, {Text(), 7}, {Text(), 8}, {Text(), 9}});
				Add(manyHistory, {Int(), (uint32)below(4), Int(), 0, Int(), Int(), Int(), (uint32)below(6), (uint32)below(4), (uint32)below(7)},
					{{Text(), 3}});
			}
			CharBuffer d1, d2, d3; uint32 l1, l2, l3;
			Take(manyLog, d1, l1); Take(manyPost, d2, l2); Take(manyHistory, d3, l3);
			SNzbLogResponse bl = {}; bl.m_nrTrailingEntries = htonl(many); bl.m_trailingDataLength = htonl(l1);
			SNzbPostQueueResponse bp2 = {}; bp2.m_nrTrailingEntries = htonl(many); bp2.m_trailingDataLength = htonl(l2);
			SNzbHistoryResponse bh = {}; bh.m_nrTrailingEntries = htonl(many); bh.m_trailingDataLength = htonl(l3);
			{ old_impl::Client x; new_impl::Client y; x.Log(bl, d1); y.Log(bl, d1); Same(x.out, y.out, "big log"); }
			{ old_impl::Client x; new_impl::Client y; x.PostQueue(bp2, d2); y.PostQueue(bp2, d2); Same(x.out, y.out, "big post-queue"); }
			{ old_impl::Client x; new_impl::Client y; x.History(bh, d3); y.History(bh, d3); Same(x.out, y.out, "big history"); }
		}

		// a log, a post-queue, a history
		SNzbLogResponse log = {};
		buf = WireNew();
		std::vector<size_t> logEnds;
		int n = below(5);
		for (int i = 0; i < n; i++) { Add(buf, {Int(), (uint32)below(6), Int(), 0}, {{Text(), 3}}); logEnds.push_back(buf->bytes.size()); }
		CharBuffer logData; uint32 logLen;
		Take(buf, logData, logLen);
		log.m_nrTrailingEntries = htonl(n);
		log.m_trailingDataLength = htonl(logLen);
		{ old_impl::Client a; new_impl::Client b; a.Log(log, logData); b.Log(log, logData); Same(a.out, b.out, "log"); }

		SNzbPostQueueResponse post = {};
		buf = WireNew();
		std::vector<size_t> postEnds;
		n = below(5);
		for (int i = 0; i < n; i++)
		{
			Add(buf, {Int(), (uint32)below(15), below(3) ? (uint32)below(1200) : (uint32)next(), Int(), Int(), Int(), 0, 0, 0, 0},
				{{Text(), 6}, {Text(), 7}, {Text(), 8}, {Text(), 9}});
			postEnds.push_back(buf->bytes.size());
		}
		CharBuffer postData; uint32 postLen;
		Take(buf, postData, postLen);
		post.m_nrTrailingEntries = htonl(n);
		post.m_trailingDataLength = htonl(postLen);
		{ old_impl::Client a; new_impl::Client b; a.PostQueue(post, postData); b.PostQueue(post, postData); Same(a.out, b.out, "post-queue"); }

		SNzbHistoryResponse history = {};
		buf = WireNew();
		n = below(5);
		std::vector<size_t> ends;
		for (int i = 0; i < n; i++)
		{
			Add(buf, {Int(), (uint32)below(4), Int(), 0, Int(), below(2) ? 0 : Int(), Int(), (uint32)below(6), (uint32)below(4), (uint32)below(7)},
				{{Text(), 3}});
			ends.push_back(buf->bytes.size());
		}
		CharBuffer histData; uint32 histLen;
		Take(buf, histData, histLen);
		history.m_nrTrailingEntries = htonl(n);
		history.m_trailingDataLength = htonl(histLen);
		{ old_impl::Client a; new_impl::Client b; a.History(history, histData); b.History(history, histData); Same(a.out, b.out, "history"); }
		// more entries announced than the data holds: the listing ends with the data
		if (logLen)
		{
			SNzbLogResponse more = log;
			more.m_nrTrailingEntries = htonl(logEnds.size() + 5);
			new_impl::Client b; b.LogRaw(more, logData, logLen);
			old_impl::Client a; a.Log(log, logData);
			Same(a.out, b.out, "log with more entries announced than sent");
		}
		if (postLen)
		{
			SNzbPostQueueResponse more = post;
			more.m_nrTrailingEntries = htonl(postEnds.size() + 5);
			new_impl::Client b; b.PostQueueRaw(more, postData, postLen);
			old_impl::Client a; a.PostQueue(post, postData);
			Same(a.out, b.out, "post-queue with more entries announced than sent");
		}

		// malformed: every cut of the data (into a buffer of exactly that
		// size), with its strings' NULs or without them. The Rust branch
		// prints the entries that fit and stops, reading nothing past the data
		if (round % 8 == 0)
		{
			// the queue: the entries before the cut
			for (uint32 cut = 0; cut < len; cut++)
			{
				size_t fit = 0;
				while (fit < listEnds.size() && listEnds[fit] <= cut) fit++;
				SNzbListResponse fitted = list;
				fitted.m_nrTrailingNzbEntries = htonl(std::min<size_t>(nzbs, fit));
				fitted.m_nrTrailingPPPEntries = htonl(std::min<size_t>(ppps, fit > (size_t)nzbs ? fit - nzbs : 0));
				fitted.m_nrTrailingFileEntries = htonl(std::min<size_t>(files, fit > (size_t)(nzbs + ppps) ? fit - nzbs - ppps : 0));
				std::vector<char> shortData(data + 0, data + cut);
				SNzbListResponse cutList = list;
				cutList.m_trailingDataLength = htonl(cut);
				old_impl::DQ a; new_impl::DQ b;
				old_impl::Client().BuildFileList(&fitted, data, &a);
				new_impl::Client().BuildFileList(&cutList, shortData.data(), &b);
				Same(Dump<old_impl::Client>(a), Dump<new_impl::Client>(b), "cut queue");
				malformed++;
			}
			malformed += Cuts<SNzbLogResponse, &old_impl::Client::Log, &new_impl::Client::LogRaw>(
				"log", log, logData, logLen, logEnds, sizeof(SNzbLogResponseEntry), true);
			malformed += Cuts<SNzbPostQueueResponse, &old_impl::Client::PostQueue, &new_impl::Client::PostQueueRaw>(
				"post-queue", post, postData, postLen, postEnds, sizeof(SNzbPostQueueResponseEntry), false);
			malformed += Cuts<SNzbHistoryResponse, &old_impl::Client::History, &new_impl::Client::HistoryRaw>(
				"history", history, histData, histLen, ends, sizeof(SNzbHistoryResponseEntry), true);
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
