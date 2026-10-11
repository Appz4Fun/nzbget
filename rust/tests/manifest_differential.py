#!/usr/bin/env python3
"""Compare ManifestFile::Load (rust/src/manifest.rs and rust/src/json.rs with
the C++ wrapper of ManifestFile.cpp), and its C++ fallback, with the
pre-port C++ on random manifest.json files: required keys missing, of other
kinds or duplicated, options/commands/sections (some not objects), strings
with escapes, NULs, surrogates and invalid UTF-8, numbers of every shape
(followed by more or less input, Boost's fast and slow paths), deep nesting
and random byte edits. Compares the result, the logged error and the whole
manifest (doubles bit for bit) in several locales.

Each version's functions are compiled into their own namespace from their
source; error() is captured.

Usage: manifest_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "02c80b7b"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "20000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/extension/ManifestFile.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/extension/ManifestFile.cpp").read_text()
header = (ROOT / "daemon/extension/ManifestFile.h").read_text()
declarations = header[header.index("	bool Load(Manifest& manifest"):header.rindex("};")]


def wrap(name, src, fallback=False):
    body = src[src.index("namespace ManifestFile\n{"):]
    if fallback:
        body = body.replace("#ifdef NZBGET_USE_RUST", "#ifndef NZBGET_USE_RUST")
    body = re.sub(r"\berror\(", "TestError(", body)
    if name == "newimpl":
        body = body.replace("Copy(*from, *context.manifest);",
                            'if (failCopy) throw std::runtime_error("injected copy exception"); Copy(*from, *context.manifest);')
    body = body.replace("namespace ManifestFile\n{", "namespace ManifestFile\n{\n" + declarations, 1)
    # renamed, so that lookup through the argument types can't reach the library's functions
    body = re.sub(r"\b(Load|ValidateAndSet|ValidateCommandsAndSet|ValidateOptionsAndSet|ValidateSectionsAndSet|ValidateTxtAndSet|CheckKeyAndSet)\(",
                  r"Test\1(", body)
    return f'''namespace {name} {{
namespace ManifestFile
{{
	using ::ManifestFile::Manifest;
	using ::ManifestFile::Option;
	using ::ManifestFile::Command;
	using ::ManifestFile::Section;
	using ::ManifestFile::SelectOption;
	using ::ManifestFile::BUFFER_SIZE;
	using ::ManifestFile::MANIFEST_FILE;
	using ::ManifestFile::DEFAULT_SECTION_NAME;
}}
{body}
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
#include "ManifestFile.h"
#include "Json.h"
#include "FileSystem.h"
#include "Log.h"
#include "nzbget_rs.h"
#include <boost/json/basic_parser_impl.hpp>
#include <boost/json/detail/impl/handler.ipp>
#include <clocale>
#include <cstdarg>
#include <cstring>
#include <exception>
#include <stdexcept>
#include <map>
#include <string>
#include <vector>
''' + globals_block + r'''
static std::string logged;
static bool failCopy = false;
static void TestError(const char* format, ...)
{
	char buf[4096];
	va_list ap;
	va_start(ap, format);
	vsnprintf(buf, sizeof(buf), format, ap);
	va_end(ap);
	logged += buf;
	logged += "\n";
}
''' + wrap("oldimpl", old_src) + wrap("newimpl", new_src) + wrap("fallbackimpl", new_src, True) + r'''
static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }
template <class T, size_t N> static const T& pick(const T (&a)[N]) { return a[below(N)]; }

static std::string ws()
{
	static const char* WS[] = {"", "", "", " ", "\n", "\t", "\r\n", "  ", "\f"};
	std::string s = below(40) ? pick(WS) : "";
	if (below(30) == 0) s = std::string(below(40), ' ');
	if (s == "\f" && below(60)) s = " ";
	return s;
}

static std::string str()
{
	static const char* PIECES[] = {"a", "x", "options", "OPTIONS", "Options", "optIons", "S", "T", "P", "\\u0000", "\\ud83d\\ude00",
		"\\ud800", "\\udc00", "\\ud800\\u0041", "\xc3\xa9", "\xc4\xb0", "\xff", "\xc0\x80", "\\n", "\\\"", "\\\\", "\\/", "\\b",
		"\\u00e9", "\\u0130", "\\u12", "\\q", "\t", " ", "main.py", "POST-PROCESSING", "\\uDBFF\\uDFFF"};
	std::string s = "\"";
	int n = below(4);
	for (int i = 0; i < n; i++)
	{
		const char* p = pick(PIECES);
		// keep most strings valid
		if (below(60) && (!strcmp(p, "\\ud800") || !strcmp(p, "\\udc00") || !strcmp(p, "\\ud800\\u0041") || !strcmp(p, "\xff") ||
			!strcmp(p, "\xc0\x80") || !strcmp(p, "\\u12") || !strcmp(p, "\\q") || !strcmp(p, "\t"))) p = "b";
		s += p;
	}
	return s + "\"";
}

static std::string digits(int n, bool lead = false)
{
	std::string s;
	for (int i = 0; i < n; i++) s += (char)('0' + (i == 0 && lead ? 1 + below(9) : below(10)));
	return s;
}

static std::string num()
{
	static const char* FIXED[] = {"0", "-0", "-0.0", "1", "18446744073709551615", "18446744073709551616", "9223372036854775807",
		"9223372036854775808", "-9223372036854775808", "-9223372036854775809", "2.2250738585072011e-308", "1e400", "1e-400",
		"1.7976931348623157e308", "4.9e-324", "1e99999999999", "1e-99999999999", "123456789012345678901234567890e-2147483647",
		"0.000000000000000000000000000001e2147483647", "9007199254740993", "9007199254740993.5", "1E5", "1e+5", "01", "1.",
		".5", "+1", "-", "1e", "1e+", "-a", "1.5e-0"};
	// around 2^53, where Boost stops taking digits after the point
	static const char* LIMITS[] = {"0.90071992547409925", "0.90071992547409915", "-0.90071992547409925", "9007199254740991.5",
		"9007199254740992.5", "900719925474099.15", "900719925474099.25", "90071992547409.9255", "1.0000000000000000001",
		"0.000090071992547409925", "0.90071992547409929", "-0.90071992547409929", "9007199254740992.9", "0.0000090071992547409929e3", "12345678.901234567", "1234567890123.4567", "1234567890123456.78", "0.12345678901234567"};
	if (below(10) == 0) return pick(LIMITS);
	if (below(5) == 0)
	{
		const char* n = pick(FIXED);
		// the invalid ones rarely
		while (below(8) && (!strcmp(n, "01") || !strcmp(n, "1.") || !strcmp(n, ".5") || !strcmp(n, "+1") || !strcmp(n, "-") ||
			!strcmp(n, "1e") || !strcmp(n, "1e+") || !strcmp(n, "-a"))) n = pick(FIXED);
		return n;
	}
	std::string s = below(3) == 0 ? "-" : "";
	int n1 = below(4) == 0 ? below(26) : below(8);
	s += n1 == 0 ? "0" : digits(n1, true);
	if (below(2)) s += "." + digits(below(4) == 0 ? below(30) : 1 + below(6));
	if (below(3) == 0)
	{
		s += below(2) ? "e" : "E";
		s += below(3) == 0 ? "-" : below(3) == 0 ? "+" : "";
		s += digits(below(5) == 0 ? below(13) : 1 + below(3));
	}
	return s;
}

static std::string value(int depth);

static std::string array(int depth)
{
	if (depth > 34) return "[]";
	std::string s = "[" + ws();
	int n = below(4);
	for (int i = 0; i < n; i++) s += (i ? "," + ws() : "") + value(depth + 1) + ws();
	if (n && below(200) == 0) s += ",";
	return s + "]";
}

static std::string member(const std::string& key, const std::string& v)
{
	return "\"" + key + "\"" + ws() + ":" + ws() + v + ws();
}

static std::string object(std::vector<std::string> members)
{
	// random order, some duplicates
	for (size_t i = 0; i + 1 < members.size(); i++) std::swap(members[i], members[i + below(members.size() - i)]);
	// a duplicate key, with another value (Boost keeps the last value, in the first one's place)
	if (!members.empty() && below(6) == 0)
	{
		const std::string& m = members[below(members.size())];
		members.push_back(m.substr(0, m.find(':') + 1) + ws() + (below(2) ? str() : value(2)) + ws());
	}
	std::string s = "{" + ws();
	for (size_t i = 0; i < members.size(); i++) s += (i ? "," + ws() : "") + members[i];
	return s + "}";
}

static std::string value(int depth)
{
	switch (below(depth > 33 ? 6 : 8))
	{
		case 0: case 1: return str();
		case 2: case 3: return num();
		case 4: return below(2) ? "true" : "false";
		case 5: return "null";
		case 6: return array(depth);
		default:
		{
			std::vector<std::string> m;
			for (int n = below(3); n > 0; --n) m.push_back(member(below(2) ? "a" : "name", value(depth + 1)));
			return object(m);
		}
	}
}

static std::string nested(int depth)
{
	return depth == 0 ? value(0) : below(2) ? "[" + nested(depth - 1) + "]" : "{\"a\":" + nested(depth - 1) + "}";
}

static std::string strOr(int bad = 12)
{
	return below(bad) ? str() : value(1);
}

static std::string texts()
{
	if (below(15) == 0) return value(1);
	std::string s = "[";
	int n = below(4);
	for (int i = 0; i < n; i++) s += (i ? "," : "") + (below(4) ? str() : value(2));
	return s + "]";
}

static std::string selectValue()
{
	return below(2) ? str() : below(8) ? num() : value(2);
}

static const char* SECTION_NAMES[] = {"\"S\"", "\"T\"", "\"options\"", "\"OPTIONS\"", "\"Options\"", "\"S\\u0000x\"", "\"\xc3\xa9\"", "\"\xc3\x89\""};

static std::string option()
{
	if (below(20) == 0) return value(2);
	std::vector<std::string> m;
	if (below(10)) m.push_back(member("select", below(10) ? "[" + [] { std::string s; int n = below(4); for (int i = 0; i < n; i++) s += (i ? "," : "") + selectValue(); return s; }() + "]" : value(2)));
	if (below(2)) m.push_back(member("section", below(2) ? pick(SECTION_NAMES) : strOr(4)));
	if (below(15)) m.push_back(member("name", strOr()));
	if (below(15)) m.push_back(member("displayName", strOr()));
	if (below(15)) m.push_back(member("value", selectValue()));
	if (below(15)) m.push_back(member("description", texts()));
	return object(m);
}

static std::string command()
{
	if (below(20) == 0) return value(2);
	std::vector<std::string> m;
	if (below(2)) m.push_back(member("section", below(2) ? pick(SECTION_NAMES) : strOr(4)));
	if (below(15)) m.push_back(member("name", strOr()));
	if (below(15)) m.push_back(member("displayName", strOr()));
	if (below(15)) m.push_back(member("description", texts()));
	if (below(15)) m.push_back(member("action", strOr()));
	return object(m);
}

static std::string section()
{
	if (below(20) == 0) return value(2);
	std::vector<std::string> m;
	if (below(15)) m.push_back(member("name", below(6) ? pick(SECTION_NAMES) : value(2)));
	if (below(15)) m.push_back(member("prefix", strOr()));
	if (below(15)) m.push_back(member("multi", below(10) ? (below(2) ? "true" : "false") : value(2)));
	return object(m);
}

static std::string list(std::string (*item)(), int bad = 25)
{
	if (below(bad) == 0) return value(1);
	std::string s = "[" + ws();
	int n = below(5);
	for (int i = 0; i < n; i++) s += (i ? "," + ws() : "") + item() + ws();
	return s + "]";
}

static std::string manifest()
{
	if (below(30) == 0) return below(2) ? value(0) : nested(28 + below(8));
	std::vector<std::string> m;
	static const char* FIELDS[] = {"author", "main", "homepage", "about", "version", "name", "displayName", "kind", "license",
		"taskTime", "queueEvents"};
	for (const char* field : FIELDS)
	{
		if (below(60)) m.push_back(member(field, strOr(80)));
	}
	if (below(2)) m.push_back(member("nzbgetMinVersion", strOr(6)));
	if (below(40)) m.push_back(member("options", list(option)));
	if (below(40)) m.push_back(member("commands", list(command)));
	if (below(3)) m.push_back(member("sections", list(section, 10)));
	if (below(40)) m.push_back(member("description", texts()));
	if (below(40)) m.push_back(member("requirements", texts()));
	if (below(10) == 0) m.push_back(member("deep", nested(below(36))));
	return ws() + object(m) + ws();
}

static std::string edit(std::string s)
{
	static const char* INSERTS[] = {",", "]", "}", "\"", "\\", "\x00", "\n", "0", "e", "-", ".", "\xff", "[", "{"};
	for (int n = 1 + below(3); n > 0 && !s.empty(); --n)
	{
		size_t at = below(s.size());
		switch (below(3))
		{
			case 0: s.erase(at, 1); break;
			case 1: s.insert(at, 1, pick(INSERTS)[0]); break;
			default: s[at] = pick(INSERTS)[0]; break;
		}
	}
	return s;
}

static std::string sel(const ManifestFile::SelectOption& v)
{
	char buf[64];
	if (const double* d = std::get_if<double>(&v))
	{
		uint64_t bits;
		static_assert(sizeof(bits) == sizeof(*d));
		memcpy(&bits, d, sizeof(bits));
		snprintf(buf, sizeof(buf), "%016llx", (unsigned long long)bits);
		return buf;
	}
	const auto& text = std::get<std::string>(v);
	return std::to_string(text.size()) + ":" + text;
}

static std::string dump(bool ok, const ManifestFile::Manifest& m)
{
	std::string s = std::string(ok ? "OK\n" : "FAIL\n") + logged;

	auto text = [&](const std::string& value) { s += std::to_string(value.size()) + ":" + value; };
	for (const std::string* f : {&m.author, &m.main, &m.kind, &m.name, &m.homepage, &m.displayName, &m.version,
		&m.nzbgetMinVersion, &m.license, &m.about, &m.queueEvents, &m.taskTime}) text(*f);
	auto texts = [&](const std::vector<std::string>& v) { s += "{" + std::to_string(v.size()) + ":"; for (auto& t : v) text(t); s += "}"; };
	auto section = [&](const ManifestFile::Section& sec) { s += "(" + std::to_string(sec.multi); text(sec.name); text(sec.prefix); s += ")"; };
	texts(m.description);
	texts(m.requirements);
	for (auto& o : m.options)
	{
		s += "\nO";
		section(o.section);
		text(o.name); text(o.displayName); text(sel(o.value));
		texts(o.description);
		s += "SELECT" + std::to_string(o.select.size()) + ":";
		for (auto& v : o.select) text(sel(v));
	}
	for (auto& c : m.commands)
	{
		s += "\nC";
		section(c.section);
		text(c.name); text(c.displayName); text(c.action);
		texts(c.description);
	}
	return s;
}

template <class Load> static std::string run(Load load, const char* dir)
{
	logged.clear();
	ManifestFile::Manifest m{};
	bool ok = load(m, dir);
	std::string result = dump(ok, m);
	// Reuse a populated destination, including entries whose sections must
	// be updated by the next Load even if that load eventually fails.
	m.nzbgetMinVersion = "old minimum";
	m.description.emplace_back("old description");
	m.requirements.emplace_back("old requirement");
	for (const char* name : {"S", "OPTIONS", "options"})
	{
		ManifestFile::Option o{};
		o.section = {true, name, "old prefix"};
		o.name = "old option";
		m.options.push_back(o);
		ManifestFile::Command c{};
		c.section = o.section;
		c.name = "old command";
		m.commands.push_back(c);
	}
	logged.clear();
	ok = load(m, dir);
	return result + "\nRELOAD\n" + dump(ok, m);
}

static int failures = 0;
static std::map<std::string, long> stats;

static void compare(const std::string& text, const std::string& dir)
{
	std::string path = dir + "/manifest.json";
	FILE* f = fopen(path.c_str(), "wb");
	fwrite(text.data(), 1, text.size(), f);
	fclose(f);
	std::string a = run(oldimpl::ManifestFile::TestLoad, dir.c_str());
	std::string b = run(newimpl::ManifestFile::TestLoad, dir.c_str());
	std::string c = run(fallbackimpl::ManifestFile::TestLoad, dir.c_str());
	std::string kind = a.substr(0, 2) == "OK" ? "loaded" : a.find("Syntax error") != std::string::npos ? "syntax" :
		a.find("isn't a JSON object") != std::string::npos ? "not an object" : a.find("not an object") != std::string::npos ? "entry not an object" :
		"refused";
	stats[kind]++;
	if (a != b || a != c)
	{
		fprintf(stderr, "mismatch on:\n%s\n--- old:\n%s\n--- rust:\n%s\n--- fallback:\n%s\n", text.c_str(), a.c_str(), b.c_str(), c.c_str());
		if (++failures > 3) exit(1);
	}
}

// Exercise Boost's actual limit checks with a small handler, avoiding
// multi-gigabyte allocations. Duplicate keys count before deduplication.
struct LimitedHandler : boost::json::detail::handler
{
	using handler::handler;
	static constexpr size_t max_string_size = 4, max_key_size = 4;
	static constexpr size_t max_array_size = 2, max_object_size = 2;
};
static void checkLimits()
{
	for (const char* input : {"{}", "[]", "[0,0]", "[0,0,0]", R"({"a":0,"a":1})", R"({"a":0,"a":1,"a":2})",
		R"("abcd")", R"("abcde")", R"("\ud83d\ude00")", R"("a\ud83d\ude00")", R"("\ud83d\ude00a")", R"({"abcde":0})"})
	{
		boost::json::basic_parser<LimitedHandler> parser({}, boost::json::storage_ptr(), nullptr, 0);
		parser.handler().st.reset({});
		boost::json::error_code ec;
		size_t consumed = parser.write_some(false, input, strlen(input), ec);
		bool boostOK = !ec && consumed == strlen(input);
		int rust = nzbget_rs_manifest_load(input, strlen(input), {4, 2, 2}, nullptr, nullptr);
		if (boostOK != (rust != -1))
		{
			fprintf(stderr, "size limit mismatch on %s\n", input);
			exit(1);
		}
	}
}

int main(int argc, char** argv)
{
	checkLimits();
	long rounds = atol(argv[1]);
	std::string dir = argv[2];
	for (int l = 3; l < argc; ++l)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		const std::string base = R"({"author":"a","main":"m","homepage":"h","about":"b","version":"1","name":"n","displayName":"d","kind":"k","license":"l","taskTime":"","queueEvents":"","description":[],"requirements":[],"commands":[],"options":[{"name":"o","displayName":"O","description":[],"select":[],"value":)";
		// Deterministic regressions: partial writes, section updates on reload,
		// and failure after description but before requirements/minimum version.
		compare("{\"author\":\"written before failure\"}", dir);
		compare(base + R"(1},{"select":[]},false]})", dir);
		compare(base + R"(1}],"sections":[{"name":"S","prefix":"new","multi":false},0]})", dir);
		compare(base + R"(1}],"description":["new"],"requirements":false,"nzbgetMinVersion":"new"})", dir);
		// Grammar boundaries (including UTF-8 scalar boundaries and depth 32).
		for (int depth : {31, 32, 33}) compare(std::string(depth, '[') + "0" + std::string(depth, ']'), dir);
		for (const char* value : {R"("\u0000")", R"("\ud800")", R"("\udc00")", R"("\udbff\udfff")",
			R"("\ud800\u0041")", "\"\xc0\x80\"", "\"\xed\xa0\x80\"", "\"\xf4\x90\x80\x80\"",
			"\"\xef\xbf\xbf\"", "\"\xf4\x8f\xbf\xbf\"", "NaN", "Infinity", "+1", "01", "-01", "1.", "1e+"})
		{
			compare(base + value + "}]}", dir);
		}
		// Sweep the pow10 table, overflow/underflow and zero * infinity (NaN).
		for (int e = -650; e <= 650; ++e)
		{
			for (const char* m : {"0", "-0", "1", "-1", "9007199254740993", "18446744073709551616"})
			{
				std::string n = std::string(m) + "e" + std::to_string(e);
				compare(base + n + "}]}", dir);
				compare(base + n + std::string(40, ' ') + "}]}", dir);
			}
		}
		// Both sides of Boost's 33-byte fast-path boundary, for each sign.
		for (const char* n : {"0.90071992547409929", "-0.90071992547409929", "1.23456789012345678",
			"-123456789012345.6789", "0e2147483647", "-0e2147483648", "1e-2147483648",
			"123456789012345678901234567890e-2147483647", "0.000000000000000000001e2147483647"})
		{
			for (int pad = 0; pad <= 40; ++pad) compare(base + n + std::string(pad, ' ') + "}]}", dir);
		}
		// numbers alone and in an option value, followed by 0..40 more bytes
		for (int i = 0; i < 3000; i++)
		{
			std::string n = num();
			std::string base = "{\"author\":\"a\",\"main\":\"m\",\"homepage\":\"h\",\"about\":\"b\",\"version\":\"1\",\"name\":\"n\","
				"\"displayName\":\"d\",\"kind\":\"k\",\"license\":\"l\",\"taskTime\":\"\",\"queueEvents\":\"\",\"description\":[],"
				"\"requirements\":[],\"commands\":[],\"options\":[{\"name\":\"o\",\"displayName\":\"O\",\"description\":[],"
				"\"select\":[" + n + "],\"value\":" + n;
			compare(base + "}]" + std::string(below(40), ' ') + "}", dir);
			compare(base + std::string(below(40), ' ') + "}]}", dir);
		}
		for (long round = 0; round < rounds; round++)
		{
			std::string text = manifest();
			if (below(8) == 0) text = edit(text);
			compare(text, dir);
		}
		// C++ must catch a copy exception inside the callback before Rust
		// destroys the borrowed view, then log it after returning from Rust.
		compare(base + "1}]}", dir);
		failCopy = true;
		std::string copyError = run(newimpl::ManifestFile::TestLoad, dir.c_str());
		failCopy = false;
		if (copyError.find("injected copy exception") == std::string::npos)
		{
			fprintf(stderr, "copy exception was not reported\n");
			return 1;
		}
		// a missing file
		remove((dir + "/manifest.json").c_str());
		std::string a = run(oldimpl::ManifestFile::TestLoad, dir.c_str());
		std::string b = run(newimpl::ManifestFile::TestLoad, dir.c_str());
		std::string c = run(fallbackimpl::ManifestFile::TestLoad, dir.c_str());
		if (a != b || a != c) { fprintf(stderr, "missing file mismatch\n"); return 1; }
		long compared = 0;
		for (auto& [kind, count] : stats) { printf("  %s: %ld\n", kind.c_str(), count); compared += count; }
		stats.clear();
		printf("%s: %ld manifests agree, including reloads (reference %s)\n", argv[l], compared, "''' + REFERENCE + r'''");
	}
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-manifest-") as temp:
    temp = Path(temp)
    env = dict(os.environ)
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/tr_TR").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
        # Turkish: tolower('I') is the dotless i, so "OPTIONS" is not "options"
        subprocess.run(["localedef", "--no-archive", "-i", "tr_TR", "-f", "ISO-8859-9", str(locdir / "tr_TR.ISO8859-9")], check=True)
        locales.append("tr_TR.ISO8859-9")
    (temp / "main.cpp").write_text(main)
    dest = temp / "ext"
    dest.mkdir()
    binary = temp / "manifest"
    for defines in (["-UNZBGET_USE_RUST"],):
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")),
                        *shlex.split(get("CXX_DEFINES")), *defines, *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only",
                        str(ROOT / "daemon/extension/ManifestFile.cpp")], check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]],
                       check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS,
                        str(dest), *locales], check=True, env=env)
