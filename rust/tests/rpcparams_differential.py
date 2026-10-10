#!/usr/bin/env python3
"""Compare XmlCommand's request parameter parsing (rust/src/rpcparams.rs with
the C++ wrappers of XmlRpc.cpp), and its C++ fallback, with the pre-port C++:
PrepareParams and NextParamAsInt/Bool/Str on generated and mutated GET query
strings, JSON-RPC, JSONP-RPC and XML-RPC requests, comparing every result,
the returned strings, the read position and the request buffer afterwards.

Each version's method bodies are compiled into a stand-in XmlCommand with the
members they use (in its own namespace), against the build's WebUtil.

Usage: rpcparams_differential.py BUILD_DIR [ROUNDS]
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


def methods(src):
    start = src.index("void XmlCommand::PrepareParams()\n{")
    end = src.index("const char* XmlCommand::BoolToStr(bool value)")
    return src[start:end]


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/XmlRpc.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/remote/XmlRpc.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

command = r'''
class XmlCommand
{
public:
	char* m_request = nullptr;
	char* m_requestPtr = nullptr;
	char* m_callbackFunc = nullptr;
	XmlRpcProcessor::ERpcProtocol m_protocol = XmlRpcProcessor::rpUndefined;
	XmlRpcProcessor::EHttpMethod m_httpMethod = XmlRpcProcessor::hmPost;
	bool IsJson() { return m_protocol == XmlRpcProcessor::rpJsonRpc || m_protocol == XmlRpcProcessor::rpJsonPRpc; }
	void PrepareParams();
	char* XmlNextValue(char* xml, const char* tag, int* valueLength);
	int JsonStep(const char* param, int len);
	bool NextParamAsInt(int* value);
	bool NextParamAsBool(bool* value);
	bool NextParamAsStr(char** value);
};
'''

main = r'''
#include "nzbget.h"
#include "Util.h"
#include "nzbget_rs.h"
#include <cerrno>
#include <climits>
#include <string>
#include <vector>

struct XmlRpcProcessor
{
	enum ERpcProtocol { rpUndefined, rpXmlRpc, rpJsonRpc, rpJsonPRpc };
	enum EHttpMethod { hmPost, hmGet };
};

namespace oldimpl {
''' + command + methods(old_src) + r'''
}
namespace newimpl {
''' + command + methods(new_src) + r'''
}
#undef NZBGET_USE_RUST
namespace fallbackimpl {
''' + command + methods(new_src) + r'''
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static const char* const INTS[] = {"0", "1", "-1", "+5", "42", "2147483647", "-2147483648", "2147483648",
	"-2147483649", "9223372036854775807", "9223372036854775808", "-9223372036854775809", " 7", "\t-3",
	"12abc", "abc", "", "-", "+", "0x10", "007", "1e3", "99999999999999999999999"};
static const char* const STRS[] = {"", "a", "hello world", "x%20y", "%41%4", "%zz", "a+b", "\"q\"", "&",
	"=", "]", ",", "<", ">", "&amp;", "\\u00e9", "\xc3\xa9", "\xff", "true", "false", "1", "0", "TRUE"};
static const char* const BOOLS[] = {"true", "false", "1", "0", "True", "truex", "fals", "", "yes"};

static std::string jsonValue()
{
	switch (below(6))
	{
		case 0: return pick(INTS);
		case 1: return std::string("\"") + pick(STRS) + "\"";
		case 2: return pick(BOOLS);
		case 3: return "[1, 2]";
		case 4: return "{\"a\": 1}";
		default: return pick(STRS);
	}
}

static std::string xmlValue()
{
	const char* tags[] = {"i4", "int", "boolean", "string", "double"};
	const char* tag = tags[below(5)];
	std::string content = below(2) ? pick(INTS) : below(2) ? pick(STRS) : pick(BOOLS);
	if (below(12) == 0) return std::string("<value><") + tag + "/></value>";
	if (below(12) == 0) return std::string("<value><") + tag + ">" + content + "</value>";
	if (below(12) == 0) return std::string("<value/><") + tag + ">" + content + "</" + tag + ">";
	return std::string("<value><") + tag + ">" + content + "</" + tag + "></value>";
}

static std::string request(int protocol, bool get)
{
	std::string r;
	int n = below(6);
	if (get)
	{
		r = below(4) ? "?" : "";
		for (int i = 0; i < n; i++)
		{
			if (i) r += below(10) ? "&" : "";
			r += below(3) ? "p" + std::to_string(i) : "";
			r += below(15) ? "=" : "";
			r += below(2) ? pick(INTS) : below(2) ? pick(STRS) : pick(BOOLS);
		}
	}
	else if (protocol == 1)
	{
		r = "<?xml version=\"1.0\"?><methodCall><methodName>m</methodName><params>";
		for (int i = 0; i < n; i++) r += "<param>" + xmlValue() + "</param>";
		r += "</params></methodCall>";
	}
	else
	{
		r = below(8) ? "{\"method\": \"m\", \"params\" : [" : "{\"method\": \"m\", \"para\": [";
		for (int i = 0; i < n; i++) r += (i ? (below(10) ? ", " : " ") : "") + jsonValue();
		r += below(8) ? "]}" : "";
	}
	// mutations
	int m = below(4) == 0 ? 1 + below(4) : 0;
	for (int i = 0; i < m && !r.empty(); i++)
	{
		size_t at = below((int)r.size());
		switch (below(4))
		{
			case 0: r[at] = (char)(1 + below(255)); break;
			case 1: r.erase(at, 1 + below(4)); break;
			case 2: r.insert(at, pick(STRS)); break;
			default: r.resize(at);
		}
	}
	return r;
}

template <class C> static std::string run(const std::string& req, int protocol, bool get, const std::vector<int>& ops)
{
	std::vector<char> buf(req.begin(), req.end());
	buf.push_back('\0');
	buf.push_back('\0'); // stand-in for what follows the request
	C c;
	c.m_request = c.m_requestPtr = buf.data();
	c.m_protocol = (XmlRpcProcessor::ERpcProtocol)protocol;
	c.m_httpMethod = get ? XmlRpcProcessor::hmGet : XmlRpcProcessor::hmPost;
	std::string log;
	c.PrepareParams();
	log += "cb:" + (c.m_callbackFunc ? std::to_string(c.m_callbackFunc - buf.data()) + "=" + c.m_callbackFunc : std::string("-"));
	for (int op : ops)
	{
		log += "|" + std::to_string(c.m_requestPtr - buf.data()) + ":";
		if (op == 0) { int v = 12345; bool ok = c.NextParamAsInt(&v); log += "i" + std::to_string(ok) + "," + std::to_string(v); }
		else if (op == 1) { bool v = true; bool ok = c.NextParamAsBool(&v); log += "b" + std::to_string(ok) + "," + std::to_string(v); }
		else { char* v = nullptr; bool ok = c.NextParamAsStr(&v); log += "s" + std::to_string(ok) + "," + (v ? std::to_string(v - buf.data()) + "=" + v : std::string("-")); }
	}
	log += "|end " + std::to_string(c.m_requestPtr - buf.data()) + "|";
	log.append(buf.begin(), buf.end());
	return log;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]), calls = 0, hits = 0;
	for (long round = 0; round < rounds; round++)
	{
		int protocol = 1 + below(3);
		bool get = below(3) == 0;
		std::string req = request(protocol, get);
		std::vector<int> ops(1 + below(7));
		for (int& op : ops) op = below(3);
		std::string a = run<oldimpl::XmlCommand>(req, protocol, get, ops);
		std::string b = run<newimpl::XmlCommand>(req, protocol, get, ops);
		std::string c = run<fallbackimpl::XmlCommand>(req, protocol, get, ops);
		if (a != b || a != c)
		{
			fprintf(stderr, "mismatch: protocol %d get %d request [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
				protocol, get, req.c_str(), a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
		calls += ops.size();
		for (size_t i = 0; (i = a.find("1,", i)) != std::string::npos; i++) hits++;
	}
	printf("%ld requests, %ld calls agree (~%ld values) (reference %s)\n", rounds, calls, hits, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-rpcparams-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "rpcparams"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS], check=True)
