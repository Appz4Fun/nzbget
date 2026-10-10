#!/usr/bin/env python3
"""Compare XmlRpcProcessor's routing (rust/src/rpcroute.rs with the C++
wrappers of XmlRpc.cpp), and its C++ fallback, with the pre-port C++: the
protocol from the URL (Execute), the method name, where the parameters start
and the JSON request id (Dispatch's parsing), and the response envelope
(BuildResponse), on generated and mutated URLs and GET, JSON-RPC and XML-RPC
requests.

Each version's code is compiled into a stand-in XmlRpcProcessor (in its own
namespace), against the build's WebUtil.

Usage: rpcroute_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "300000"


def between(src, start, end):
    i = src.index(start) + len(start)
    return src[i:src.index(end, i)]


def parts(src):
    protocol = between(src, "void XmlRpcProcessor::Execute()\n{", "\tDispatch();")
    route = between(src, "void XmlRpcProcessor::Dispatch()\n{", '\tdebug("MethodName=%s", *methodName);')
    i = src.index("void XmlRpcProcessor::BuildResponse(")
    build = src[i:src.index("\n}\n", i) + 3]
    return r'''
struct XmlRpcProcessor
{
	enum ERpcProtocol { rpUndefined, rpXmlRpc, rpJsonRpc, rpJsonPRpc };
	enum EHttpMethod { hmPost, hmGet };
	char* m_request = nullptr;
	const char* m_contentType = nullptr;
	ERpcProtocol m_protocol = rpUndefined;
	EHttpMethod m_httpMethod = hmPost;
	CString m_url;
	StringBuilder m_response;
	void Protocol()
	{''' + protocol + r'''	}
	std::string Route(const char* base)
	{''' + route + r'''
		std::string where = !request ? "null" : request >= base && request <= base + strlen(base) ?
			"r" + std::to_string(request - base) : "u" + std::to_string(request - m_url);
		return std::string(methodName) + "|" + where + "|" + (requestId ? std::string("id:") + *requestId : "-");
	}
	void BuildResponse(const char* response, const char* callbackFunc, bool fault, const char* requestId);
};
''' + build


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/XmlRpc.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/remote/XmlRpc.cpp").read_text()

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
#undef debug
#define debug(...)
#undef error
#define error(...)

namespace oldimpl {
''' + parts(old_src) + r'''
}
namespace newimpl {
''' + parts(new_src) + r'''
}
#undef NZBGET_USE_RUST
namespace fallbackimpl {
''' + parts(new_src) + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static const char* const PREFIXES[] = {"/xmlrpc", "/jsonrpc", "/jsonprpc", "/xmlrpcx", "/jsonrpc2", "/JSONRPC", "/",
	"", "/jsonp", "xmlrpc", "/jsonprpc/", "/jsonrpc/", "/xmlrpc/"};
static const char* const NAMES[] = {"", "status", "listgroups", "system.multicall", "System.MultiCall", "a/b", "?",
	"x?y", "averyveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryverylongmethodname1234",
	"%41", "\"", "\xff"};
static const char* const VALUES[] = {"\"status\"", "\"\"", "\"x\"", "7", "\"abc", "[1,2]", "{\"a\":1}", "null", "-",
	"\"averyveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryverylongmethodname1234\"",
	"", " ", "\"a\\\"b\""};

static std::string mutate(std::string r)
{
	int m = below(4) == 0 ? 1 + below(4) : 0;
	for (int i = 0; i < m && !r.empty(); i++)
	{
		size_t at = below((int)r.size());
		switch (below(4))
		{
			case 0: r[at] = (char)(1 + below(255)); break;
			case 1: r.erase(at, 1 + below(4)); break;
			case 2: r.insert(at, pick(VALUES)); break;
			default: r.resize(at);
		}
	}
	return r;
}

static std::string url()
{
	std::string u = pick(PREFIXES);
	if (below(3)) u += std::string(below(5) ? "/" : "") + pick(NAMES);
	if (below(2)) u += std::string("?") + (below(2) ? "a=1&b=x" : pick(NAMES));
	u = mutate(u);
	// Dispatch runs for RPC URLs only: never empty (GET reads from its second byte)
	return u.empty() ? "/" : u;
}

static std::string request(int protocol)
{
	std::string r;
	if (protocol == 1)
	{
		r = below(6) ? std::string("<?xml version=\"1.0\"?><methodCall><methodName>") + pick(NAMES) + "</methodName><params/></methodCall>"
			: below(2) ? "<methodCall><methodName/></methodCall>" : "<methodName>x";
	}
	else
	{
		r = "{";
		if (below(6)) r += std::string("\"method\"") + (below(2) ? ": " : ":") + pick(VALUES) + ", ";
		if (below(2)) r += std::string("\"id\"") + (below(2) ? " : " : ":") + (below(10) ? pick(VALUES) : std::string(4096 + below(3) - 1, '9')) + ", ";
		r += "\"params\": [1]}";
	}
	return mutate(r);
}

template <class P> static std::string run(const std::string& u, const std::string& req, bool get)
{
	P p;
	p.m_url = u.c_str();
	std::vector<char> buf(req.begin(), req.end());
	buf.push_back('\0');
	p.m_request = buf.data();
	p.m_httpMethod = get ? P::hmGet : P::hmPost;
	p.Protocol();
	std::string log = std::to_string((int)p.m_protocol) + "|";
	if (p.m_protocol == P::rpUndefined)
	{
		// Dispatch for every protocol, as the URL and the body needn't agree
		p.m_protocol = (typename P::ERpcProtocol)(1 + below(3));
	}
	log += p.Route(buf.data());
	static const char* const RESPONSES[] = {"true", "", "<i4>1</i4>", "[1,2]"};
	static const char* const CALLBACKS[] = {"cb", "", "x(y"};
	static const char* const IDS[] = {"7", "", "\"a\"", "{1}"};
	p.BuildResponse(RESPONSES[below(4)], below(3) ? CALLBACKS[below(3)] : nullptr, below(2), below(3) ? IDS[below(4)] : nullptr);
	return log + "|" + (const char*)p.m_response + "|" + p.m_contentType;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	for (long round = 0; round < rounds; round++)
	{
		std::string u = url();
		int protocol = 1 + below(3);
		std::string req = request(protocol);
		bool get = below(3) == 0;
		unsigned long long seed = state;
		std::string a = run<oldimpl::XmlRpcProcessor>(u, req, get);
		state = seed;
		std::string b = run<newimpl::XmlRpcProcessor>(u, req, get);
		state = seed;
		std::string c = run<fallbackimpl::XmlRpcProcessor>(u, req, get);
		if (a != b || a != c)
		{
			fprintf(stderr, "mismatch: get %d url [%s] request [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
				get, u.c_str(), req.c_str(), a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	printf("%ld requests agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-rpcroute-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "rpcroute"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS], check=True)
