#!/usr/bin/env python3
"""Compare TestServerXmlCommand's JSON body parsing (rust/src/rpcparams.rs
with rust/src/json.rs, the C++ of XmlRpc.cpp's Rust branch) and its C++
fallback with the pre-port C++ (Json::Deserialize and ParseRequestParams):
random request bodies - objects with "params" arrays of every length and
entry kind, integers and doubles around int's range, strings with NULs and
escapes, duplicate keys, other JSON and broken JSON. Compares the error
response and every parameter.

Usage: testserver_differential.py BUILD_DIR [ROUNDS]
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "200000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/XmlRpc.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/remote/XmlRpc.cpp").read_text()


def between(src, start, end, include_start=True):
    i = src.index(start)
    j = src.index(end, i + len(start))
    return src[i if include_start else i + len(start):j]


parse_params = between(old_src, "	std::optional<ServerParams> ParseRequestParams(const Json::value& value)", "\n};\n")
old_block = between(old_src, "		const auto jsonResult = Json::Deserialize(m_request);", "\n	}\n	else if")
rust_block = between(new_src, "#ifdef NZBGET_USE_RUST\n		// rust/src/rpcparams.rs", "#else\n")[len("#ifdef NZBGET_USE_RUST\n"):]
fallback_block = between(new_src, "#else\n		const auto jsonResult = Json::Deserialize(m_request);", "#endif\n	}\n	else if")[len("#else\n"):]


def impl(name, block):
    return f'''
namespace {name}
{{
	struct Command
	{{
		using ServerParams = ::ServerParams;
{parse_params}
		std::string Run(const char* m_request)
		{{
			std::string error;
			ServerParams params{{}};
			auto BuildErrorResponse = [&](int, const char* text) {{ error = text; }};
			[&]()
			{{
{block}
			}}();
			return error.empty() ? Dump(params) : "error: " + error;
		}}
	}};
}}
'''


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
#include "Json.h"
#include "nzbget_rs.h"
#include <cstring>
#include <exception>
#include <optional>
#include <string>
''' + globals_block + r'''
struct ServerParams
{
	std::string host;
	std::string username;
	std::string password;
	std::string cipher;
	int port;
	int timeout;
	int certVerifLevel;
	bool encryption;
};

static std::string Bytes(const std::string& s)
{
	std::string out = "[";
	for (unsigned char c : s) { char b[8]; snprintf(b, sizeof(b), c < 32 || c > 126 ? "\\x%02x" : "%c", c); out += b; }
	return out + "]";
}

static std::string Dump(const ServerParams& p)
{
	return Bytes(p.host) + std::to_string(p.port) + Bytes(p.username) + Bytes(p.password) + std::to_string(p.encryption) +
		Bytes(p.cipher) + std::to_string(p.timeout) + "/" + std::to_string(p.certVerifLevel);
}
''' + impl("oldimpl", old_block) + impl("newimpl", rust_block) + impl("fallbackimpl", fallback_block) + r'''
static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }
template <class T, size_t N> static const T& pick(const T (&a)[N]) { return a[below(N)]; }

static std::string str()
{
	static const char* S[] = {"\"news.example.com\"", "\"\"", "\"a\\u0000b\"", "\"\\u00e9\\ud83d\\ude00\"", "\"x\\\"y\"", "\"\\n\"",
		"\"\xc3\xa9\"", "\"\\ud800\"", "\"\xff\"", "\"tls\"", "\"RC4-MD5\""};
	return pick(S);
}

static std::string num()
{
	static const char* N[] = {"0", "-0", "1", "119", "563", "-1", "2147483647", "2147483648", "-2147483648", "-2147483649",
		"4294967296", "18446744073709551615", "9223372036854775808", "-9223372036854775809", "1.0", "1.5", "-0.0", "1e2",
		"1e10", "1e-300", "2147483647.0", "2147483648.0", "-2147483648.0", "-2147483648.5", "2147483646.9999999999", "1e400",
		"2", "3", "30", "1E1", "0.5e1", "21474836470e-1", "-21474836480e-1", "2.147483647e9", "2.1474836475e9"};
	static const char* VALID[] = {"0", "1", "119", "563", "30", "2", "-1", "1.0", "1e2", "2147483647", "-2147483648"};
	return below(3) ? pick(VALID) : pick(N);
}

static std::string anyValue()
{
	switch (below(8))
	{
		case 0: case 1: return str();
		case 2: case 3: return num();
		case 4: return below(2) ? "true" : "false";
		case 5: return "null";
		case 6: return "[" + (below(2) ? num() : "") + "]";
		default: return "{}";
	}
}

static std::string params()
{
	// mostly the right kinds, in order: host, port, username, password, encryption, cipher, timeout, certVerifLevel
	static const char KINDS[] = "snssbsnn";
	std::string s = "[";
	int n = below(5) == 0 ? below(12) : 8 + below(2);
	for (int i = 0; i < n; i++)
	{
		std::string v;
		if (below(12) == 0 || i >= 8) v = anyValue();
		else if (KINDS[i] == 's') v = str();
		else if (KINDS[i] == 'n') v = num();
		else v = below(2) ? "true" : "false";
		s += (i ? "," : "") + v;
	}
	return s + "]";
}

static std::string body()
{
	std::string p = "\"params\":" + (below(15) ? params() : anyValue());
	switch (below(12))
	{
		case 0: return params();
		case 1: return anyValue();
		case 2: return "{\"method\":\"testserver\"}";
		case 3: return "{\"method\":\"testserver\"," + p + ",\"params\":" + params() + "}";
		case 4: return "{" + p + ",\"id\":1";
		case 5: return " {" + p + "} x";
		default: return std::string(below(3), ' ') + "{\"method\":\"testserver\"," + p + ",\"id\":" + num() + "}" + std::string(below(40), '\n');
	}
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	long ok = 0;
	for (long round = 0; round < rounds; round++)
	{
		std::string text = body();
		std::string a = oldimpl::Command().Run(text.c_str());
		std::string b = newimpl::Command().Run(text.c_str());
		std::string c = fallbackimpl::Command().Run(text.c_str());
		if (a.rfind("error", 0) != 0) ok++;
		if (a != b || a != c)
		{
			fprintf(stderr, "mismatch on %s\n  old:      %s\n  rust:     %s\n  fallback: %s\n", text.c_str(), a.c_str(), b.c_str(), c.c_str());
			return 1;
		}
	}
	printf("%ld bodies agree, %ld parsed (reference %s)\n", rounds, ok, "''' + REFERENCE + r'''");
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-testserver-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "testserver"
    subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")),
                    *shlex.split(get("CXX_DEFINES")), "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                    str(ROOT / "daemon/remote/XmlRpc.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]],
                       check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True)
