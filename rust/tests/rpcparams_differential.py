#!/usr/bin/env python3
"""Compare XmlCommand's request parameter parsing (rust/src/rpcparams.rs with
the C++ wrappers of XmlRpc.cpp), and its C++ fallback, with the pre-port C++:
PrepareParams and NextParamAsInt/Bool/Str on generated and mutated GET query
strings, JSON-RPC, JSONP-RPC and XML-RPC requests, comparing every result,
the returned strings, the read position and the request buffer afterwards.

Each version's method bodies are compiled into a stand-in XmlCommand with the
members they use (in its own namespace). The reference and fallback use the
original C++ WebUtil helpers, independent of the build's Rust-backed WebUtil.

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
old_util = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)


def helper(signature):
    start = old_util.rindex(signature + "\n{")
    end = old_util.index("\n}\n", start) + 3
    return old_util[start:end]


helpers = r'''
class WebUtil {
public:
    static const char* XmlFindTag(const char*, const char*, int*);
    static const char* JsonNextValue(const char*, int*);
    static void UrlDecode(char*);
};
''' + "\n".join(helper(signature) for signature in (
    "const char* WebUtil::XmlFindTag(const char* xml, const char* tag, int* valueLength)",
    "const char* WebUtil::JsonNextValue(const char* jsonText, int* valueLength)",
    "void WebUtil::UrlDecode(char* raw)",
))

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
#include <memory>
#include <cassert>
#include <clocale>

struct XmlRpcProcessor
{
	enum ERpcProtocol { rpUndefined, rpXmlRpc, rpJsonRpc, rpJsonPRpc };
	enum EHttpMethod { hmPost, hmGet };
};

namespace oldimpl {
''' + helpers + command + methods(old_src) + r'''
}
namespace newimpl {
''' + command + methods(new_src) + r'''
}
#undef NZBGET_USE_RUST
namespace fallbackimpl {
''' + helpers + command + methods(new_src) + r'''
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
	// Exact allocation: ASan must catch reads/writes after the single terminator.
	std::unique_ptr<char[]> storage(new char[req.size() + 1]);
	char* const base = storage.get();
	memcpy(base, req.data(), req.size());
	base[req.size()] = 0;
	// An embedded NUL ends the request too; trailing allocated bytes are not
	// permission to advance the cursor past the original C string.
	const char* const requestEnd = (const char*)memchr(base, 0, req.size() + 1);
	auto checked = [&](const char* p) {
		assert(p >= base && p <= requestEnd);
		assert(memchr(p, 0, requestEnd + 1 - p));
	};
	C c;
	c.m_request = c.m_requestPtr = base;
	c.m_protocol = (XmlRpcProcessor::ERpcProtocol)protocol;
	c.m_httpMethod = get ? XmlRpcProcessor::hmGet : XmlRpcProcessor::hmPost;
	std::string log;
	c.PrepareParams();
	checked(c.m_requestPtr);
	if (c.m_callbackFunc) checked(c.m_callbackFunc);
	log += "cb:" + (c.m_callbackFunc ? std::to_string(c.m_callbackFunc - base) + "=" + c.m_callbackFunc : std::string("-"));
	log.append(base, req.size() + 1);
	size_t opIndex = 0;
	for (int op : ops)
	{
		checked(c.m_requestPtr);
		log += "|" + std::to_string(c.m_requestPtr - base) + ":";
		if (op == 0) { int v = 12345; bool ok = c.NextParamAsInt(&v); log += "i" + std::to_string(ok) + "," + std::to_string(v); }
		else if (op == 1) { bool v = (opIndex % 2) != 0; bool ok = c.NextParamAsBool(&v); log += "b" + std::to_string(ok) + "," + std::to_string(v); }
		// A non-null sentinel detects incorrectly clearing the output on failure.
		else { char* v = base; bool ok = c.NextParamAsStr(&v); if (v) checked(v); log += "s" + std::to_string(ok) + "," + (v ? std::to_string(v - base) + "=" + v : std::string("-")); }
		opIndex++;
		log.append(base, req.size() + 1);
	}
	log += "|end " + std::to_string(c.m_requestPtr - base) + "|";
	checked(c.m_requestPtr);
	log.append(base, req.size() + 1);
	return log;
}

static long cases = 0, calls = 0;
static void compare(const std::string& req, int protocol, bool get, const std::vector<int>& ops)
{
    std::string a = run<oldimpl::XmlCommand>(req, protocol, get, ops);
    std::string b = run<newimpl::XmlCommand>(req, protocol, get, ops);
    std::string c = run<fallbackimpl::XmlCommand>(req, protocol, get, ops);
    if (a != b || a != c)
    {
        fprintf(stderr, "mismatch: protocol %d get %d request hex:", protocol, get);
        for (unsigned char ch : req) fprintf(stderr, "%02x", ch);
        fprintf(stderr, "\nold: %s\nrust: %s\nfallback: %s\n", a.c_str(), b.c_str(), c.c_str());
        exit(1);
    }
    cases++;
    calls += ops.size();
}

static void sequences(const std::string& req, int protocol, bool get)
{
    // Every three-operation sequence, including continued parsing after failure.
    for (int i = 0; i < 27; i++) compare(req, protocol, get, {i % 3, i / 3 % 3, i / 9});
}

static void directed()
{
    const char* inputs[] = {
        "", "=", "a=&b=", "a=%00abc&b=true", "a= \t+12&b=7", "a=1&&&b=-2",
        "\"params\"", "\"params\":[\"\",1,true]", "\"params\":[\"a\\\"\",false]",
        "\"params\":[\"a\\", "\"params\":[\"a\\x", "\"params\":[12abc,+5,1e3]",
        "\"params\":[truex,false,true]", "\"params\":[\v1,\f2,3]",
        "<value/>", "<value><string/></value>", "<value><boolean/></value>",
        "<value><i4/></value>", "<value><int>2</int><i4>1</i4></value>",
        "<value><i4>invalid</i4><int>2</int></value>",
        "<value><string></value>outside</string>",
        "<value><boolean></value>1</boolean>",
        "<value><string>x</string></value><value><int>7</int></value>",
        "<value><value><string>nested</string></value></value>",
        "<value></value><string>outside</string>"
    };
    for (const char* input : inputs)
    {
        std::string req(input);
        // Every truncation, including exactly at a terminator or escape boundary.
        for (size_t n = 0; n <= req.size(); n++)
            for (int protocol = 1; protocol <= 3; protocol++)
                for (bool get : {false, true}) sequences(req.substr(0, n), protocol, get);
    }
    for (int byte = 0; byte < 256; byte++)
    {
        std::string ch(1, (char)byte);
        for (int protocol = 1; protocol <= 3; protocol++)
        {
            sequences("a=" + ch + "12&b=true&c=last", protocol, true);
            sequences("a=%" + ch + "1&b=%1" + ch, protocol, true);
            if (protocol != 1) {
                sequences("\"params\":[" + ch + "12,true,\"s\"]", protocol, false);
                sequences("\"params\":[\"a" + ch + "b\",false,1]", protocol, false);
            } else {
                sequences("<value><string>" + ch + "</string></value><value><int>2</int></value>", protocol, false);
            }
        }
    }
    // Adjacent escapes/quotes and each possible ending expose cursor mistakes
    // that inserting single random bytes into ordinary requests rarely reaches.
    for (int n = 0; n <= 7; n++)
        for (int bits = 0; bits < (1 << n); bits++)
        {
            std::string body;
            for (int i = 0; i < n; i++) body += (bits & (1 << i)) ? '\\' : '"';
            for (const char* end : {"", "x", "\"", "\",1,true]", "\" true false", "\"}1"})
                for (int protocol : {2, 3})
                    sequences("\"params\":[\"" + body + end, protocol, false);
        }
    // The legacy XML search permits misplaced closing tags, prefers the first
    // opening/self-closing tag, and can find a type past </value>.
    for (const char* tag : {"i4", "int", "boolean", "string"})
        for (const char* prefix : {"<value>", "<value/>", "<value></value>", "<value><value>"})
            for (const char* content : {"", "1", "-2", "true", "</value>", "</value>1"})
                for (const char* end : {"", "</value>", "<value><int>3</int></value>"})
                {
                    std::string open = std::string("<") + tag + ">";
                    std::string close = std::string("</") + tag + ">";
                    sequences(prefix + open + content + close + end, 1, false);
                    sequences(prefix + std::string("<") + tag + "/>" + open + content + close + end, 1, false);
                }
}

int main(int argc, char** argv)
{
    // Preserve the classic C++ locale; exercise C's active locale separately.
    for (const char* locale : {"C", "C.UTF-8", "en_US.UTF-8"}) {
        if (!setlocale(LC_ALL, locale)) continue;
        directed();
        printf("directed cases agree in %s\n", locale);
    }
    setlocale(LC_ALL, "C");
    long rounds = atol(argv[1]);
    for (long round = 0; round < rounds; round++)
    {
        int protocol = 1 + below(3);
        bool get = below(3) == 0;
        std::string req = request(protocol, get);
        std::vector<int> ops(1 + below(7));
        for (int& op : ops) op = below(3);
        compare(req, protocol, get, ops);
    }
    printf("%ld requests, %ld calls agree (reference %s)\n", cases, calls, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-rpcparams-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "rpcparams"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-UNDEBUG", "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS], check=True)
