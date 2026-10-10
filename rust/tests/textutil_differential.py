#!/usr/bin/env python3
"""Compare Util's text helpers (rust/src/util.rs with the C++ wrappers of
Util.cpp), and their C++ fallback, with the pre-port C++: SplitCommandLine,
TrimRight/TrimLeft/Trim (char* and std::string), SanitizeLine, EndsWith,
FormatBuffer and WebUtil::ParseRfc822DateTime, on random and mutated text in
the C, C.UTF-8, tr_TR.ISO8859-9 and en_US.ISO-8859-1 locales.

The pre-port and fallback bodies are compiled into stand-in Util classes (in
their own namespaces); the Rust-backed ones are the build's. With ASan/UBSan
the dates stay in the range where the C++ int arithmetic doesn't overflow
(undefined there); the build without sanitizers also tries extreme numbers,
which the Rust code computes as the wrapping int arithmetic they compile to.
The wrapper-only pass also overrides C++ char signedness independently of
Rust, with a custom locale that maps a whitespace character to byte 255.

Usage: textutil_differential.py BUILD_DIR [ROUNDS]
"""
import gzip
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
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "200000"

SIGS = [
    "CString Util::FormatBuffer(const char* buf, int len)",
    "std::vector<CString> Util::SplitCommandLine(const char* commandLine)",
    "void Util::TrimRight(char* str)",
    "void Util::TrimRight(std::string& str)",
    "void Util::TrimLeft(std::string& str)",
    "char* Util::Trim(char* str)",
    "void Util::Trim(std::string& str)",
    "void Util::SanitizeLine(std::string& str)",
    "bool Util::EndsWith(std::string_view str, std::string_view suffix, bool caseSensitive)",
    "bool Util::EndsWith(const char* str, const char* suffix, bool caseSensitive)",
    "bool Util::StrCaseCmp(std::string_view a, std::string_view b)",
    "time_t WebUtil::ParseRfc822DateTime(const char* dateTimeStr)",
]


def bodies(src, rust=False):
    out = []
    for sig in SIGS:
        i = (src.index if rust else src.rindex)(sig + "\n{")
        out.append(src[i:src.index("\n}\n", i) + 3])
    if "\tint TextRightSpace(int byte)" in src:
        i = src.index("\tint TextRightSpace(int byte)")
        out.insert(0, src[i:src.index("\n\t}\n", i) + 4])
    boost = src[src.index("/* From boost */"):src.index("time_t Util::Timegm")]
    return boost + "time_t Util::Timegm(tm const* t) { return internal_timegm(t); }\n" + "".join(out)


STANDIN = r'''
class Util
{
public:
	static CString FormatBuffer(const char* buf, int len);
	static std::vector<CString> SplitCommandLine(const char* commandLine);
	static void TrimRight(char* str);
	static void TrimRight(std::string& str);
	static void TrimLeft(std::string& str);
	static char* Trim(char* str);
	static void Trim(std::string& str);
	static void SanitizeLine(std::string& str);
	static bool EndsWith(std::string_view str, std::string_view suffix, bool caseSensitive);
	static bool EndsWith(const char* str, const char* suffix, bool caseSensitive);
	static bool StrCaseCmp(std::string_view a, std::string_view b);
	static time_t Timegm(tm const* t);
	static constexpr bool IsControlChar(char c) noexcept { return ::Util::IsControlChar(c); }
	static bool EmptyStr(const char* str) { return !str || !*str; }
};
class WebUtil
{
public:
	static time_t ParseRfc822DateTime(const char* dateTimeStr);
};
'''

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/Util.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/util/Util.cpp").read_text()

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
#include <clocale>
#include <string>
#include <vector>

namespace oldimpl {
''' + STANDIN + bodies(old_src) + r'''
}
namespace fallbackimpl {
''' + STANDIN + bodies(new_src) + r'''
}
namespace portimpl {
''' + STANDIN + bodies(new_src, rust=True) + r'''
}

#ifdef TEXTUTIL_WRAPPERS_ONLY
using PortUtil = portimpl::Util;
using PortWebUtil = portimpl::WebUtil;
#else
using PortUtil = ::Util;
using PortWebUtil = ::WebUtil;
#endif

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static std::string text(int maxLen)
{
	static const char ALPHABET[] = " \t\r\n\v\f'\"aIiZz.,:-+09\x01\x1f\x7f\x80\x85\xa0\xc0\xdd\xfd\xff";
	std::string s;
	int n = below(maxLen + 1);
	for (int i = 0; i < n; i++)
		s += below(4) ? ALPHABET[below(sizeof ALPHABET - 1)] : (char)below(256);
	return s;
}

static std::string number(bool extreme)
{
	static const char* const BIG[] = {"2147483647", "-2147483648", "2147483648", "99999999999", "-99999999999",
		"4294967296", "596524", "-596524", "35791395", "5880000", "-5880000"};
	if (extreme && below(4) == 0) return pick(BIG);
	switch (below(6))
	{
		case 0: return std::to_string(below(32));
		case 1: return std::to_string(1900 + below(300));
		case 2: return std::to_string(below(100000) - 50000);
		case 3: return "0" + std::to_string(below(10));
		case 4: return std::to_string(below(24)) ;
		default: return std::to_string(below(60));
	}
}

static std::string date(bool extreme)
{
	static const char* const DAYS[] = {"Wed,", "Wed", "Thu, ", "x,", "", "", "Mon ,", "  Sun,"};
	static const char* const MONTHS[] = {"Jan", "feb", "MAR", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
		"Dec", "Xyz", "J", "Janu", "\xddul", "Ju"};
	static const char* const ZONES[] = {"", "GMT", "UT", "Z", "A", "EST", "edt", "CST", "CDT", "MST", "MDT", "pst",
		"PDT", "ESTX", "+0000", "-0600", "+0530", "+99", "-1", "+", "-x", "+2400", "+12345", "ES"};
	std::string s = pick(DAYS);
	s += (below(3) ? " " : "") + number(extreme) + " " + pick(MONTHS) + " " + number(extreme) + " " + number(extreme) + ":" + number(extreme);
	if (below(2)) s += ":" + (below(8) ? number(extreme) : std::string("x"));
	s += (below(4) ? " " : below(2) ? "  " : "") + std::string(pick(ZONES));
	// mutations
	int m = below(4) == 0 ? 1 + below(3) : 0;
	for (int i = 0; i < m && !s.empty(); i++)
	{
		size_t at = below((int)s.size());
		switch (below(3))
		{
			case 0: s[at] = (char)(1 + below(255)); break;
			case 1: s.erase(at, 1 + below(3)); break;
			default: s.insert(at, " ");
		}
	}
	return s;
}

static bool longDigits(const std::string& s)
{
	int run = 0;
	for (char c : s)
	{
		run = isdigit((unsigned char)c) ? run + 1 : 0;
		if (run > 5) return true;
	}
	return false;
}

template <class U, class W> static std::string run(const std::string& a, const std::string& b, const std::string& d, int len)
{
	std::string out;
	CString f = U::FormatBuffer(a.data(), std::min(len, (int)a.size()));
	out += std::string(f) + "|";
	for (CString& w : U::SplitCommandLine(a.c_str())) out += std::string(w) + "\x01";
	out += "|";
	{ std::string s = a; s.resize(strlen(s.c_str())); std::vector<char> c(s.begin(), s.end()); c.push_back(0);
	  U::TrimRight(c.data()); out.append(c.data(), c.size()); out += "|";
	  std::vector<char> c2(s.begin(), s.end()); c2.push_back(0); char* t = U::Trim(c2.data());
	  out += std::to_string(t - c2.data()) + ":"; out.append(c2.data(), c2.size()); out += "|"; }
	{ std::string s = a; U::TrimRight(s); out += s + "|"; }
	{ std::string s = a; U::TrimLeft(s); out += s + "|"; }
	{ std::string s = a; U::Trim(s); out += s + "|"; }
	{ std::string s = a; U::SanitizeLine(s); out += s + "|"; }
	out += std::to_string(U::EndsWith(std::string_view(a), std::string_view(b), true));
	out += std::to_string(U::EndsWith(std::string_view(a), std::string_view(b), false));
	out += std::to_string(U::EndsWith(a.c_str(), b.c_str(), false));
	out += std::to_string(U::EndsWith(nullptr, b.c_str(), false));
	out += std::to_string(U::EndsWith(a.c_str(), nullptr, true)) + "|";
	out += std::to_string((long long)W::ParseRfc822DateTime(d.c_str()));
	return out;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	bool extreme = !strcmp(argv[2], "extreme");
	for (int l = 3; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		for (int a = 0; a < 256; a++) for (int b = 0; b < 256; b++)
		{
			std::string s(1, (char)a), suffix(1, (char)b);
			bool x = oldimpl::Util::EndsWith(s, suffix, false);
			if (x != PortUtil::EndsWith(s, suffix, false) || x != fallbackimpl::Util::EndsWith(s, suffix, false))
			{
				fprintf(stderr, "case-fold mismatch in %s: %d / %d\n", argv[l], a, b);
				return 1;
			}
		}
		std::vector<std::string> dates = {"", " ", "Wed,", "26 Jun 2013 01:02:", "26 Jun 2013 01:02 +",
			"26 Jun 2013 01:02 -", "29 Feb 2000 00:00", "29 Feb 1900 00:00", "1 Jan -1 00:00",
			"1 Jan 0 00:00", "31 Dec 1969 23:59:59", "1 Jan 1970 00:00:01"};
		for (int byte = 1; byte < 256; byte++)
		{
			dates.push_back(std::string(1, (char)byte) + ", 26 Jun 2013 01:02 GMT");
			dates.push_back("26 Jun 2013 01:" + std::string(1, (char)byte) + "02 GMT");
		}
		if (extreme)
		{
			for (const std::string n : {"2147483647", "-2147483648", "2147483648", "-2147483649",
				"4294967296", "5880000", "596524", "35791395", "9223372036854775808",
				"999999999999999999999999999999999999999999999999999999999999999999"})
			{
				dates.push_back(n + " Dec 2013 01:02 GMT");
				dates.push_back("29 Feb " + n + " 01:02 GMT");
				dates.push_back("26 Jun 2013 " + n + ":02 GMT");
				dates.push_back("26 Jun 2013 01:" + n + " GMT");
				dates.push_back("26 Jun 2013 01:02:" + n + " GMT");
				dates.push_back("26 Jun 2013 01:02 +" + n);
				dates.push_back("26 Jun 2013 01:02 -" + n);
			}
		}
		for (const auto& d : dates)
		{
			time_t x = oldimpl::WebUtil::ParseRfc822DateTime(d.c_str());
			time_t y = PortWebUtil::ParseRfc822DateTime(d.c_str());
			time_t z = fallbackimpl::WebUtil::ParseRfc822DateTime(d.c_str());
			if (x != y || x != z)
			{
				fprintf(stderr, "date mismatch in %s: [%s], old %lld, Rust %lld, fallback %lld\n",
					argv[l], d.c_str(), (long long)x, (long long)y, (long long)z);
				return 1;
			}
		}
		std::vector<std::string> edges = {"", " ", " \t\r\n", " x \t\r\n", "''", std::string(4, 39), "'a''b'c", std::string("a\0b \t", 6)};
		for (int n : {1022, 1023, 1024, 2048})
		{
			edges.push_back(std::string(n, 'a') + " b");
			edges.push_back("'" + std::string(n, 'a') + "''b' c");
		}
		for (int byte = 0; byte < 256; byte++)
		{
			edges.push_back(std::string(1, (char)byte));
			edges.push_back(std::string(1, (char)byte) + "x" + (char)byte);
		}
		for (const auto& a : edges)
		{
			std::string x = run<oldimpl::Util, oldimpl::WebUtil>(a, a, "26 Jun 2013 01:02 GMT", (int)a.size());
			std::string y = run<PortUtil, PortWebUtil>(a, a, "26 Jun 2013 01:02 GMT", (int)a.size());
			std::string z = run<fallbackimpl::Util, fallbackimpl::WebUtil>(a, a, "26 Jun 2013 01:02 GMT", (int)a.size());
			if (x != y || x != z)
			{
				fprintf(stderr, "edge mismatch in %s: %zu input bytes, first byte %u\n", argv[l], a.size(), a.empty() ? 0 : (unsigned char)a[0]);
				return 1;
			}
		}
		for (long round = 0; round < rounds; round++)
		{
			std::string a = text(below(10) ? 24 : 1500);
			std::string b = below(3) ? a.substr(a.size() - std::min(a.size(), (size_t)below(6))) : text(4);
			if (below(4) == 0) for (char& c : b) c = below(2) ? toupper((unsigned char)c) : tolower((unsigned char)c);
			std::string d = below(8) ? date(extreme) : text(40);
			// bounded: no number long enough to overflow the old C++ int arithmetic
			while (!extreme && longDigits(d)) d = date(extreme);
			int len = below(40);
			std::string x = run<oldimpl::Util, oldimpl::WebUtil>(a, b, d, len);
			std::string y = run<PortUtil, PortWebUtil>(a, b, d, len);
			std::string z = run<fallbackimpl::Util, fallbackimpl::WebUtil>(a, b, d, len);
			if (x != y || x != z)
			{
				fprintf(stderr, "mismatch in %s: text [%s] suffix [%s] date [%s]\nold:      %s\nrust:     %s\nfallback: %s\n",
					argv[l], a.c_str(), b.c_str(), d.c_str(), x.c_str(), y.c_str(), z.c_str());
				return 1;
			}
		}
		printf("%s: %ld rounds agree (%s, reference %s)\n", argv[l], rounds, argv[2], "''' + REFERENCE + r'''");
	}
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-textutil-") as temp:
    temp = Path(temp)
    env = dict(os.environ)
    locales = ["C", "C.UTF-8"]
    if shutil.which("localedef"):
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
        for name, src, charset in (("tr_TR.ISO8859-9", "tr_TR", "ISO-8859-9"), ("en_US.ISO-8859-1", "en_US", "ISO-8859-1")):
            if Path(f"/usr/share/i18n/locales/{src}").exists():
                subprocess.run(["localedef", "--no-archive", "-i", src, "-f", charset, str(locdir / name)], check=True)
                locales.append(name)
        # U+1680 is whitespace. Map it to 0xff to expose the distinction
        # between unsigned char 255 and signed char -1 (EOF) in glibc ctype.
        charmap = Path("/usr/share/i18n/charmaps/ISO-8859-1.gz")
        if charmap.exists() and Path("/usr/share/i18n/locales/en_US").exists():
            custom = temp / "space255.charmap"
            with gzip.open(charmap, "rb") as source:
                custom.write_bytes(source.read().replace(b"<U00FF>", b"<U1680>"))
            subprocess.run(["localedef", "--no-archive", "-i", "en_US", "-f", str(custom),
                            str(locdir / "space255")], check=True)
            locales.append("space255")
    (temp / "main.cpp").write_text(main)
    binary = temp / "textutil"
    sanitizer_flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    for extra, mode in ((sanitizer_flags, "bounded"), ([], "extreme"),
                        (sanitizer_flags + ["-funsigned-char", "-DTEXTUTIL_WRAPPERS_ONLY"], "bounded"),
                        (sanitizer_flags + ["-fsigned-char", "-DTEXTUTIL_WRAPPERS_ONLY"], "bounded")):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, mode, *locales], check=True, env=env)
