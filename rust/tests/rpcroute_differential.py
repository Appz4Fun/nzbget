#!/usr/bin/env python3
"""Compare XmlRpcProcessor's routing (rust/src/rpcroute.rs with the C++
wrappers of XmlRpc.cpp), and its C++ fallback, with the pre-port C++: the
protocol from the URL (Execute), the method name, where the parameters start
and the JSON request id (Dispatch's parsing), and the response envelope
(BuildResponse), on generated and mutated URLs and GET, JSON-RPC and XML-RPC
requests.

Each version's code is compiled into a stand-in XmlRpcProcessor (in its own
namespace). The reference and fallback use the original C++ WebUtil helpers,
so a shared Rust helper cannot mask a mismatch. Includes deterministic boundary
cases and checks the FFI's borrowed pointers and 100-byte output buffer.

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


def original_helpers(src):
    declarations = []
    definitions = []
    for name in ("XmlFindTag", "XmlParseTagValue", "JsonFindField", "JsonNextValue"):
        # The reference already has Rust-backed WebUtil wrappers; take the last
        # definition, which is the actual C++ fallback, not that wrapper.
        match = list(re.finditer(r"^(?:const char\*|bool) WebUtil::" + name + r"\([^\n]+\)", src, re.M))[-1]
        signature = match.group()
        declarations.append("static " + signature.replace("WebUtil::", "") + ";")
        definitions.append(src[match.start():src.index("\n}\n", match.end()) + 3])
    return "struct WebUtil {\n" + "\n".join(declarations) + "\n};\n" + "\n".join(definitions)


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
		// POST retains the request; GET points into the URL. Do not order or
		// subtract pointers to unrelated allocations to guess their provenance.
		const char* origin = m_httpMethod == hmGet ? *m_url : base;
		std::string where = !request ? "null" :
			std::string(m_httpMethod == hmGet ? "u" : "r") + std::to_string(request - origin);
		return std::string(methodName) + "|" + where + "|" + (requestId ? std::string("id:") + *requestId : "-");
	}
	void BuildResponse(const char* response, const char* callbackFunc, bool fault, const char* requestId);
};
''' + build


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/XmlRpc.cpp"], cwd=ROOT, text=True)
helpers = original_helpers(subprocess.check_output(
    ["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True))
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
#include <array>
#include <clocale>
#include <climits>
#ifdef __linux__
#include <sys/mman.h>
#endif
#undef debug
#define debug(...)
#undef error
#define error(...)

namespace oldimpl {
''' + helpers + parts(old_src) + r'''
}
namespace newimpl {
''' + parts(new_src) + r'''
}
#undef NZBGET_USE_RUST
namespace fallbackimpl {
''' + helpers + parts(new_src) + r'''
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

static void check(const std::string& u, const std::string& req, bool get)
{
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
		exit(1);
	}
	// Independently verify the raw FFI outputs, before CString::Set can
	// obscure a wrong id length (zero means 'copy the whole suffix').
	const char* params = nullptr;
	const char* id = nullptr;
	int idLen = -1;
	std::array<unsigned char, 102> method;
	method.fill(0xa5);
	int protocol = nzbget_rs_rpc_protocol(u.c_str());
	nzbget_rs_rpc_route(u.c_str(), req.c_str(), get, protocol,
		reinterpret_cast<char*>(method.data() + 1), &params, &id, &idLen);
	if (method.front() != 0xa5 || method.back() != 0xa5 ||
		!memchr(method.data() + 1, 0, 100)) abort();
	int expectedLen = 0;
	const char* expectedId = !get && protocol == 2 ?
		oldimpl::WebUtil::JsonFindField(req.c_str(), "id", &expectedLen) : nullptr;
	if (!expectedId || expectedLen > 4096) { expectedId = nullptr; expectedLen = 0; }
	if (id != expectedId || idLen != expectedLen) abort();
	const char* expectedParams = req.c_str();
	if (get)
	{
		expectedParams = u.c_str() + 1;
		if (const char* slash = strchr(expectedParams, '/'))
		{
			const char* query = strchr(slash + 1, '?');
			expectedParams = query ? query + 1 : u.c_str() + strlen(u.c_str());
		}
	}
	if (params != expectedParams) abort();
}

static void boundaries()
{
	for (int n : {0, 1, 2, 3, 96, 97, 98, 99, 100, 101, 4095, 4096, 4097})
	{
		std::string s(n, 'x');
		for (const char* prefix : {"/xmlrpc", "/jsonrpc", "/jsonprpc"})
		{
			check(std::string(prefix) + "/" + s, "", true);
			check(std::string(prefix) + "/" + s + "?a=1", "", true);
		}
		check("/xmlrpc", "<methodName>" + s + "</methodName>", false);
		for (const auto& token : {s, "\"" + s + "\"", "\"" + s})
		{
			check("/jsonrpc", "{\"method\":" + token + ",\"id\":" + token + "}", false);
			check("/jsonrpc", "\"method\":" + token, false);
		}
	}
	for (const char* token : {"", "}", "]", ",", "7", "-", "null", "\"", "\"\"", "\"x\\", "\"x\\a",
		"\"x\\\"y\"", "\"x\\\\\"", "\v", "\r\n\t\f", "[[1]]", "{\"id\":2}"})
	{
		check("/jsonrpc", std::string("\"method\":") + token + ",\"id\":" + token, false);
		check("/jsonrpc", std::string("\"id\":") + token + ",\"method\":" + token, false);
	}
	for (int byte = 1; byte < 256; ++byte)
	{
		std::string s(1, static_cast<char>(byte));
		check("/jsonrpc/" + s + "?x=1", "", true);
		check("/jsonrpc", "\"method\":" + s + "\"a\",\"id\":" + s + "7", false);
		check("/xmlrpc", "<methodName>" + s + "</methodName>", false);
	}
	for (const char* xml : {"<methodName/>", "<methodName/><methodName>x</methodName>",
		"<methodName>x</methodName><methodName/>", "<methodName><methodName/>",
		"</methodName><methodName>x", "<methodName></methodName>", "<methodName >x</methodName>"})
		check("/xmlrpc", xml, false);
	const char nulBody[] = "\"method\":\"a\"\0,\"id\":7";
	check("/jsonrpc", std::string(nulBody, sizeof(nulBody) - 1), false);
	for (int protocol : {0, 1, 2, 3})
		for (bool fault : {false, true})
			for (const char* callback : {static_cast<const char*>(nullptr), "", "cb", "\xff("})
				for (const char* id : {static_cast<const char*>(nullptr), "", "0", "\"x\"", "}malformed"})
				{
					oldimpl::XmlRpcProcessor old;
					newimpl::XmlRpcProcessor rust;
					fallbackimpl::XmlRpcProcessor fallback;
					old.m_protocol = static_cast<oldimpl::XmlRpcProcessor::ERpcProtocol>(protocol);
					rust.m_protocol = static_cast<newimpl::XmlRpcProcessor::ERpcProtocol>(protocol);
					fallback.m_protocol = static_cast<fallbackimpl::XmlRpcProcessor::ERpcProtocol>(protocol);
					old.m_response.Append("prefix"); rust.m_response.Append("prefix"); fallback.m_response.Append("prefix");
					old.BuildResponse("body", callback, fault, id);
					rust.BuildResponse("body", callback, fault, id);
					fallback.BuildResponse("body", callback, fault, id);
					if (strcmp(old.m_response, rust.m_response) || strcmp(old.m_response, fallback.m_response) ||
						strcmp(old.m_contentType, rust.m_contentType) || strcmp(old.m_contentType, fallback.m_contentType)) abort();
				}
}

static void wide_length()
{
#ifdef __linux__
	if (sizeof(size_t) < 8) return;
	// A >INT_MAX token without committing gigabytes of RAM: repeat the same
	// 1 MiB file mapping, with private first/last pages for the delimiters.
	// The HTTP layer caps bodies below this size, but the C ABI does not.
	const size_t chunk = 1024 * 1024;
	const size_t tokenLen = static_cast<size_t>(INT_MAX) + 3;
	const char prefix[] = "\"method\":";
	const size_t start = strlen(prefix);
	const size_t size = ((start + tokenLen + 1 + chunk - 1) / chunk) * chunk;
	FILE* file = tmpfile();
	if (!file) abort();
	std::string page(chunk, 'x');
	if (fwrite(page.data(), 1, chunk, file) != chunk || fflush(file)) abort();
	char* data = static_cast<char*>(mmap(nullptr, size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
	if (data == MAP_FAILED) abort();
	for (size_t at = 0; at < size; at += chunk)
		if (mmap(data + at, chunk, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_FIXED, fileno(file), 0) == MAP_FAILED) abort();
	memcpy(data, prefix, start);
	data[start] = '"';
	data[start + tokenLen - 1] = '"';
	data[start + tokenLen] = 0;
	oldimpl::XmlRpcProcessor old;
	newimpl::XmlRpcProcessor rust;
	fallbackimpl::XmlRpcProcessor fallback;
	old.m_url = "/jsonrpc"; rust.m_url = "/jsonrpc"; fallback.m_url = "/jsonrpc";
	old.m_request = rust.m_request = fallback.m_request = data;
	old.Protocol(); rust.Protocol(); fallback.Protocol();
	std::string a = old.Route(data), b = rust.Route(data), c = fallback.Route(data);
	if (a != b || a != c)
	{
		fprintf(stderr, "wide length mismatch: old [%s], Rust [%s], fallback [%s]\n", a.c_str(), b.c_str(), c.c_str());
		exit(1);
	}
	// The id length uses the same narrowing. Check the borrowed range directly:
	// passing a negative length to the old CString can request a huge allocation.
	memcpy(data, "\"id\"    :", start);
	int expectedLen = 0, idLen = 0;
	const char* expected = oldimpl::WebUtil::JsonFindField(data, "id", &expectedLen);
	const char* id = nullptr;
	const char* params = nullptr;
	char method[100];
	nzbget_rs_rpc_route("/jsonrpc", data, 0, 2, method, &params, &id, &idLen);
	if (id != expected || idLen != expectedLen || params != data || method[0]) abort();
	munmap(data, size);
	fclose(file);
#endif
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	if (!setlocale(LC_CTYPE, "")) abort();
	boundaries();
	if (argc > 2) wide_length();
	for (long round = 0; round < rounds; round++)
	{
		std::string u = url();
		int protocol = 1 + below(3);
		std::string req = request(protocol);
		bool get = below(3) == 0;
		check(u, req, get);
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
        subprocess.run([str(binary), ROUNDS, *([] if extra else ["wide"])], check=True)
