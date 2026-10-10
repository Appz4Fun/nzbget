#!/usr/bin/env python3
"""Compare NntpConnection's protocol (rust/src/nntp.rs with the C++ wrappers
of NntpConnection.cpp), and its C++ fallback, with the pre-port C++: Connect
(greeting and login), Request (with the re-login a 480 asks for), JoinGroup
and Disconnect, driven by scripted server answers (2xx/381/480/481/502,
closed connections, long and CR-laden lines), long credentials (BString's
1023-byte cut), cancellation and callback exceptions, comparing every line
written, every error/debug message, the answers returned and the login state.
Targeted cases also cover aliased input/answer buffers, exact truncation and
recursion boundaries, buffer identity and exceptions at every callback.

Each version's methods are compiled into a stand-in NntpConnection (in its
own namespace) over a scripted connection.

Usage: nntp_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "100000"

SIGS = [
    "const char* NntpConnection::Request(const char* req)",
    "bool NntpConnection::Authenticate()",
    "bool NntpConnection::AuthInfoUser(int recur)",
    "bool NntpConnection::AuthInfoPass(int recur)",
    "const char* NntpConnection::JoinGroup(const char* grp)",
    "bool NntpConnection::Connect()",
    "bool NntpConnection::Disconnect()",
    "void NntpConnection::ReportErrorAnswer(const char* msgPrefix, const char* answer)",
]


def bodies(src, which):
    out = []
    for sig in SIGS:
        i = src.index(sig + "\n{") if which == "first" else src.rindex(sig + "\n{")
        out.append(src[i:src.index("\n}\n", i) + 3].replace("!Connection::Connect()", "!ScriptedConnection::Connect()")
                   .replace("return Connection::Disconnect()", "return ScriptedConnection::Disconnect()"))
    if which == "first":
        h = src.index("#ifdef NZBGET_USE_RUST\n// a callback that threw")
        out.insert(0, src[h:src.index("#endif\n", h) + 7])
    return "".join(out)


STANDIN = r'''
struct NewsServer
{
	std::string user, password, name, host;
	const char* GetUser() { return user.c_str(); }
	const char* GetPassword() { return password.c_str(); }
	const char* GetName() { return name.c_str(); }
	const char* GetHost() { return host.c_str(); }
};
struct ScriptedConnection
{
	enum EStatus { csConnected, csDisconnected, csListening, csCancelled, csBroken };
	EStatus m_status = csDisconnected;
	std::deque<std::optional<std::string>> m_answers;
	std::string m_log;
	bool m_connectOk = true;
	bool m_cancelAfterRead = false;
	int m_throwAt = -1;
	int m_calls = 0;
	void Debug(const char* fmt, ...)
	{
		Step();
		char buf[1024];
		va_list ap;
		va_start(ap, fmt);
		vsnprintf(buf, sizeof buf, fmt, ap);
		va_end(ap);
		m_log += std::string("L:") + buf + "\n";
	}
	void Step()
	{
		if (m_calls++ == m_throwAt) throw std::runtime_error("callback");
	}
	int WriteLine(const char* line) { Step(); m_log += std::string("W:") + line + "\n"; return 1; }
	char* ReadLine(char* buffer, int size, int*)
	{
		Step();
		if (m_answers.empty() || !m_answers.front())
		{
			if (!m_answers.empty()) m_answers.pop_front();
			m_log += "R:-\n";
			return nullptr;
		}
		snprintf(buffer, size, "%s", m_answers.front()->c_str());
		m_answers.pop_front();
		if (m_cancelAfterRead) m_status = csCancelled;
		m_log += std::string("R:") + buffer + "\n";
		return buffer;
	}
	void ReportError(const char* prefix, const char* arg, bool, int = 0)
	{
		Step();
		char buf[1024];
		snprintf(buf, sizeof buf, prefix, arg);
		m_log += std::string("E:") + buf + "\n";
	}
	const char* GetHost() const { return "conn.host"; }
	EStatus GetStatus() { Step(); return m_status; }
	bool Connect() { Step(); if (m_connectOk) m_status = csConnected; return m_connectOk; }
	bool Disconnect() { m_status = csDisconnected; m_log += "D\n"; return true; }
};
class NntpConnection : public ScriptedConnection
{
public:
	using Server = NewsServer;
	NewsServer* m_newsServer;
	CString m_activeGroup;
	CharBuffer m_lineBuf;
	bool m_authError = false;
	bool m_authRejected = false;
	NntpConnection(NewsServer* server) : m_newsServer(server) { m_lineBuf.Reserve(1024 * 10); m_lineBuf[0] = 0; }
	const char* Request(const char* req);
	const char* JoinGroup(const char* grp);
	bool Connect();
	bool Disconnect();
	void ReportErrorAnswer(const char* msgPrefix, const char* answer);
	bool Authenticate();
	bool AuthInfoUser(int recur);
	bool AuthInfoPass(int recur);
	struct RsExchange;
	static int RsWriteLine(void* ctx, const char* line);
	static int RsReadLine(void* ctx, char** line);
	static int RsReportError(void* ctx, const char* prefix, const char* arg);
	static int RsDebug(void* ctx, const char* msg);
	static int RsCancelled(void* ctx, int* cancelled);
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/nntp/NntpConnection.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/nntp/NntpConnection.cpp").read_text()

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
#include "Util.h"
#include "Connection.h"
#include "nzbget_rs.h"
#include <deque>
#include <exception>
#include <optional>
#include <stdexcept>
#include <string>
''' + globals_block + r'''
#undef debug
#ifdef TEST_DEBUG
#define debug(...) Debug(__VA_ARGS__)
#define RS_DEBUG(c, msg) c->Debug("%s", msg)
#else
#define debug(...) (void)0
#define RS_DEBUG(c, msg) (void)0
#endif

namespace oldimpl {
''' + STANDIN + bodies(old_src, "last") + r'''
}
namespace newimpl {
''' + STANDIN + bodies(new_src, "first").replace("debug(\"%s\", msg)", "RS_DEBUG(c, msg)").replace("[msg](NntpConnection*)", "[msg](NntpConnection* c)") + r'''
}
#undef NZBGET_USE_RUST
namespace fallbackimpl {
''' + STANDIN + bodies(new_src, "last") + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static const char* const ANSWERS[] = {"200 news ready\r\n", "201 no posting\r\n", "281 ok\r\n", "381 more\r\n", "480 auth\r\n",
	"481 too many\r\n", "482 bad\r\n", "502 refused\r\n", "502 refused", "2", "", "\r\n", "211 5 1 5 alt.bin\r\n",
	"411 no such group\r\n", "222 body\r\n", "430 no article\r\n", "205 bye\r\n", "500 x\r\ny\r\n", "5\r", "28", "38", "48", "281\0ignored", "502\r\0ignored", "\xff\xfe\r\n"};
static const char* const GROUPS[] = {"alt.binaries.test", "alt.binaries.x", "", "a b"};

template <class C> static std::string run(unsigned long long seed, int ops)
{
	state = seed;
	typename C::Server server;
	server.user = below(5) == 0 ? "" : below(10) == 0 ? std::string(1100, 'u') : "user";
	server.password = below(5) == 0 ? "" : below(10) == 0 ? std::string(1100, 'p') : "secret";
	server.name = below(10) == 0 ? std::string(1100, 'n') : "news1";
	server.host = "news.example.com";
	C c(&server);
	// sometimes long runs of 480/381 (the login's recursion limit)
	bool loop = below(4) == 0;
	for (int i = 0; i < 60; i++)
		c.m_answers.push_back(below(12) == 0 ? std::nullopt : std::optional<std::string>(
			loop && below(8) ? (below(3) ? "381 more\r\n" : "480 auth\r\n") : pick(ANSWERS)));
	c.m_connectOk = below(8) != 0;
	c.m_cancelAfterRead = below(10) == 0;
	c.m_throwAt = below(6) == 0 ? below(12) : -1;
	std::string out;
	for (int op = 0; op < ops; op++)
	{
		try
		{
			switch (below(4))
			{
				case 0: out += std::string("C") + std::to_string(c.Connect()); break;
				case 1: { const char* a = c.Request(below(8) ? "BODY <x@y>\r\n" : nullptr); out += std::string("Q") + (a ? a : "-"); break; }
				case 2: { const char* a = c.JoinGroup(pick(GROUPS)); out += std::string("J") + (a ? a : "-"); break; }
				default: out += std::string("D") + std::to_string(c.Disconnect());
			}
		}
		catch (const std::exception& e)
		{
			out += std::string("X") + e.what();
		}
		out += "/" + std::to_string(c.m_authError) + std::to_string(c.m_authRejected) + std::to_string((int)c.m_status) +
			(c.m_activeGroup ? (const char*)c.m_activeGroup : "-") + "|";
	}
	return out + "\n" + c.m_log;
}

// Explicit boundaries and aliasing cases, including each callback throwing.
template <class C> static std::string targeted(int kind, int length, int throwAt)
{
	typename C::Server server;
	server.user = std::string(length, 'u');
	server.password = std::string(length, 'p');
	server.name = "news%sn";
	server.host = "host%n";
	C c(&server);
	c.m_status = C::csConnected;
	c.m_authError = c.m_authRejected = true;
	c.m_throwAt = throwAt;
	std::string input(length, 'g');
	std::string out;
	if (kind == 0 || kind == 1)
	{
		// A caller can pass a previous answer back as a request or group.
		strcpy(c.m_lineBuf, "previous server answer used as input");
		c.m_answers = {"480 auth\r\n", "281 ok\r\n", "211 x\r\n"};
	}
	else if (kind == 2)
		c.m_answers = {"480 auth\r\n", "381 pass\r\n", "502%sn\rX\r\n"};
	else if (kind == 3)
		c.m_answers = {"480 auth\r\n", "381 pass\r\n", std::nullopt};
	else if (kind == 4 || kind == 5)
	{
		c.m_answers.push_back("480 auth\r\n");
		for (int i = 0; i < length; ++i) c.m_answers.push_back(kind == 4 ? "480 again\r\n" : "381 again\r\n");
		c.m_answers.push_back("281 ok\r\n");
		c.m_answers.push_back("480 no second login\r\n");
	}
	else if (kind == 6)
	{
		c.m_cancelAfterRead = true;
		c.m_answers = {"480 auth\r\n", "502 refused\r\r\n"};
	}
	else if (kind == 7)
	{
		c.m_status = C::csDisconnected;
		c.m_answers = {"500 " + std::string(length, 'x') + "\r\n", "205 bye\r\n"};
	}
	else
	{
		strcpy(c.m_lineBuf, "x");
		c.m_answers = {"211 " + std::string(length, '\xff') + "\r\n"};
	}
	try
	{
		const char* a = nullptr;
		if (kind == 0) a = c.Request(c.m_lineBuf);
		else if (kind == 1 || kind == 9) a = c.JoinGroup(c.m_lineBuf);
		else if (kind == 7) out += std::to_string(c.Connect());
		else if (kind == 8) a = c.JoinGroup(input.c_str());
		else a = c.Request("BODY <x>\r\n");
		out += std::string(a ? a : "-") + (a == (char*)c.m_lineBuf ? "same" : "null");
		if (kind == 8) { a = c.JoinGroup(input.c_str()); out += a ? a : "-"; }
	}
	catch (const std::exception& e) { out += std::string("X") + e.what(); }
	return out + "/" + std::to_string(c.m_authError) + std::to_string(c.m_authRejected) +
		std::to_string((int)c.m_status) + (c.m_activeGroup ? (const char*)c.m_activeGroup : "-") +
		"|" + (const char*)c.m_lineBuf + "|" + std::to_string(c.m_calls) + "\n" + c.m_log;
}

int main(int argc, char** argv)
{
	int targetedCases = 0;
	for (int kind = 0; kind < 10; ++kind)
	for (int len : {0, 1, 9, 10, 11, 12, 1007, 1008, 1009, 1010, 1011, 1012, 1015, 1016, 1017, 1018, 1023, 1024, 10232, 10233, 10234, 10239, 10240})
	for (int at = -1; at < 32; ++at)
	{
		++targetedCases;
		auto a = targeted<oldimpl::NntpConnection>(kind, len, at);
		auto b = targeted<newimpl::NntpConnection>(kind, len, at);
		auto c = targeted<fallbackimpl::NntpConnection>(kind, len, at);
		if (a != b || a != c)
		{
			fprintf(stderr, "targeted mismatch: kind %d length %d throw %d\nold:\n%s\nrust:\n%s\nfallback:\n%s\n", kind, len, at, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	long rounds = atol(argv[1]);
	for (long round = 0; round < rounds; round++)
	{
		unsigned long long seed = next();
		int ops = 1 + below(8);
		std::string a = run<oldimpl::NntpConnection>(seed, ops);
		std::string b = run<newimpl::NntpConnection>(seed, ops);
		std::string c = run<fallbackimpl::NntpConnection>(seed, ops);
		state = seed + 1;
		if (a != b || a != c)
		{
			fprintf(stderr, "mismatch: round %ld\nold:\n%s\nrust:\n%s\nfallback:\n%s\n", round, a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	printf("%d targeted cases and %ld sessions agree (reference %s)\n", targetedCases, rounds, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-nntp-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "nntp"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-DTEST_DEBUG"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS], check=True)
