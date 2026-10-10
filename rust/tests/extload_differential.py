#!/usr/bin/env python3
"""Compare ExtensionLoader::V1::Load (rust/src/extload.rs with the C++ wrapper
of ExtensionLoader.cpp), and its C++ fallback, with the pre-port C++ on
generated and mutated pre-manifest extension scripts: the result, the kind,
about text, queue events, task time, description, requirements, options
(sections, names, descriptions, values, select values) and commands, in the
C, C.UTF-8, tr_TR.ISO8859-9 and de_DE.UTF-8 locales (strtod's decimal comma).

The three loaders are compiled as separate translation units with renamed
namespaces and link the build's Rust archive. Trims are compiled locally so
both C++ char modes are exercised. Includes structured byte/delimiter cases,
a locale with high-byte whitespace, and callback exception injection.

Usage: extload_differential.py BUILD_DIR [ROUNDS]
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

header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/extension/ExtensionLoader.h"], cwd=ROOT, text=True)
decls = header[header.index("namespace ExtensionLoader"):header.rindex("#endif")]


# Keep trims in the test translation units, so -f[un]signed-char really
# exercises the caller rather than the build archive's default char mode.
trim_helpers = r'''
extern int extloadFailAt;
static std::istream& testGetline(std::istream& file, std::string& line) {
    if (extloadFailAt == 0) throw std::bad_alloc();
    if (extloadFailAt > 0) --extloadFailAt;
    return std::getline(file, line);
}
struct ExtloadTestUtil {
    static void TrimRight(std::string& s) {
        while (!s.empty()) {
            int ch = s.back();
#ifndef __GLIBC__
            if (ch < 0) break;
#endif
            if (!std::isspace(ch)) break;
            s.pop_back();
        }
    }
    static void Trim(std::string& s) {
        s.erase(s.begin(), std::find_if(s.begin(), s.end(), [](unsigned char b) { return !std::isspace(b); }));
        TrimRight(s);
    }
};
'''


def renamed(src, name, fallback=False):
    body = src.replace("namespace ExtensionLoader", f"namespace {name}")
    # the declarations (and the template) first, in the renamed namespace
    i = body.index(f"namespace {name}")
    out = body[:i] + trim_helpers + decls.replace("namespace ExtensionLoader", f"namespace {name}") + body[i:]
    out = out.replace("Util::Trim", "ExtloadTestUtil::Trim")
    out = out.replace("std::getline(r.file, r.line)", "testGetline(r.file, r.line)")
    return ("#undef NZBGET_USE_RUST\n" if fallback else "") + out


tests_main = (ROOT / "tests/main.cpp").read_text()
# the globals liblibnzbget expects (nzbget.cpp defines them in the daemon)
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/extension/ExtensionLoader.cpp"], cwd=ROOT, text=True)
new_src = (ROOT / "daemon/extension/ExtensionLoader.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = shlex.split((BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text())
libs = link[link.index("liblibnzbget.a"):]

main = r'''
#include "nzbget.h"
#include "Extension.h"
#include "ExtensionLoader.h"
#include <clocale>
#include <fstream>
#include <string>
#include <variant>
#include <vector>
''' + globals_block + r'''

namespace RustExtensionLoader::V1 { bool Load(Extension::Script& script, const char* location, const char* rootDir); }
namespace OldExtensionLoader::V1 { bool Load(Extension::Script& script, const char* location, const char* rootDir); }
namespace FallbackExtensionLoader::V1 { bool Load(Extension::Script& script, const char* location, const char* rootDir); }

int extloadFailAt = -1;

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }
template <size_t N> static const char* pick(const char* const (&a)[N]) { return a[below(N)]; }

static const char* const LINES[] = {
	"##############################################################################",
	"### NZBGET POST-PROCESSING SCRIPT                                          ###",
	"### NZBGET SCAN SCRIPT ###", "### NZBGET QUEUE/SCHEDULER SCRIPT ###", "### NZBGET FEED SCRIPT",
	"### NZBGET SCRIPT", "### NZBGET ", "### NZBGET POST-PROCESSING", " SCRIPT", "### SCRIPT",
	"### TASK TIME: *;*:00;*:30 ###", "### TASK TIME:", "### TASK TIME: ", "### TASK TIME: 1:00 ### x ###",
	"### QUEUE EVENTS: NZB_ADDED, NZB_DOWNLOADED ###", "### QUEUE EVENTS:", "### QUEUE EVENTS:x",
	"# Sorts movies and tv shows.", "# About line two", "#", "# ", "#x", "# NOTE: Requires Python.", "# NOTE: ",
	"# This is a description.", "### OPTIONS                                                                ###",
	"### OPTIONS", "### CATEGORIES ###", "###", "### ", "###x###", "# Enable this (yes, no).", "# Mode (Always, OnFailure, Never).",
	"# Port (1-65535).", "# Values (1, 2-5, 10).", "# Range (0.5-2.5).", "# Decimal (1,5-2,5).", "# Words (some text).",
	"# Empty ().", "# Spaces ( a , b ).", "# Odd (a-b c).", "# Dash (-5).", "# Tail (x) y", "#(a, b).", "# (a, b).",
	"# ((a, b)).", "# Neg (-1--5).", "# Inf (1e999-2).", "# NaN (nan-inf).",
	"#Enable=yes", "#Port=119", "#Port= 1e3 ", "#Mode=Always", "#Category1.Name=Movies", "#Category1.DestDir=",
	"#Server1.Host=x1.y", "# Category1.Name=Movies", "#Name =  value with spaces  ", "#=x", "#@x", "=x", "@x", "#A@B=C",
	"#ConnectionTest@Send Test E-Mail", "#Cmd@", "#Cmd @ Do it", "#x1.y1.z=1", "#1.=v", "plain text", "", " ", "\t"};

static std::string script()
{
	std::string s;
	if (below(3)) s += "#!/usr/bin/env python\n";
	int n = 1 + below(40);
	for (int i = 0; i < n; i++)
	{
		std::string line = pick(LINES);
		if (below(25) == 0 && !line.empty()) line[below((int)line.size())] = (char)below(256);
		if (below(30) == 0) line.insert(below((int)line.size() + 1), 1, '\0');
		if (below(20) == 0) line += "\r";
		if (below(30) == 0) line += " ###";
		s += line;
		if (i < n - 1 || below(2)) s += "\n";
	}
	return s;
}

// Always reach the parser states being tested, unlike random line shuffling.
static std::vector<std::string> cases()
{
    const std::string head = "### NZBGET POST-PROCESSING SCRIPT\n### OPTIONS\n";
    std::vector<std::string> v = {"", "\n", "###", "### TASK TIME:", "### QUEUE EVENTS:"};
    for (const char* line : LINES) v.push_back(head + line + "\n#X=value\n");
    for (const char* text : {"# )(", "# ().", "# (a,b).", "=", "@", "###", "### TASK TIME:", "### QUEUE EVENTS:"})
        v.push_back(head + text); // no terminal newline
    for (int b = 0; b < 256; ++b)
    {
        std::string x(1, (char)b);
        v.push_back("### TASK TIME: " + x + "\n### QUEUE EVENTS: x" + x + "\n" + head +
            "### Sec" + x + "\n#" + x + "Name" + x + "=" + x + "value" + x + "\n#Cmd@" + x + "action" + x);
        v.push_back(head + "# Desc (1-2).\n#X=" + x + "1" + x + "\n");
        v.push_back(head + "#Name" + x + "=before" + x + "after\n#Cmd" + x + "@action\n");
        v.push_back("### NZBGET POST-PROCESSING" + x + " SCRIPT\n# About" + x + "\n#\n# Desc" + x + "\n# NOTE: Req" + x + "\n");
    }
    for (const char* n : {"nan", "-nan", "nan(123)", "inf", "-inf", "1e999", "-1e999", "1e-999",
            "-0", "0x1p2", " 2junk", "1,5", "1.7976931348623157e308", "1.7976931348623159e308", "4.9406564584124654e-324"})
    {
        v.push_back(head + "# Range (1-2).\n#X=" + n);
        v.push_back(head + "# Range (" + n + "-2).\n#X=" + n);
    }
    // Exhaust ExtractElements' short delimiter/space/NUL paths.
    const char alphabet[] = {'a', ' ', '-', ',', '\0'};
    for (int len = 0, count = 1; len <= 5; ++len, count *= 5)
        for (int code = 0; code < count; ++code)
        {
            std::string inner;
            for (int i = 0, n = code; i < len; ++i, n /= 5) inner += alphabet[n % 5];
            v.push_back(head + "# (" + inner + ").\n#X=1\n");
        }
    // CString operations stop at NUL; string positions do not.
    v.push_back(head + std::string("# D\0(a,b).\n#N\0=V\0tail\n", sizeof("# D\0(a,b).\n#N\0=V\0tail\n") - 1));
    v.push_back(head + "# )(" + "\n#X=1\n"); // size_t count underflow
    return v;
}

static std::string bytes(const std::string& s) {
    return std::to_string(s.size()) + ":" + s;
}
static std::string hex(const std::string& s) {
    const char* digits = "0123456789abcdef";
    std::string out;
    for (unsigned char b : s) { out += digits[b >> 4]; out += digits[b & 15]; }
    return out;
}

static std::string sel(const ManifestFile::SelectOption& o)
{
	if (const double* d = std::get_if<double>(&o)) {
        // Compare exact bits, including signed zero and NaN payloads.
        return "n" + std::string(reinterpret_cast<const char*>(d), sizeof(*d));
    }
	return "s" + std::get<std::string>(o);
}

static std::string dump(bool ok, const Extension::Script& s)
{
	std::string out = std::to_string(ok) + "|";
	if (!ok) return out;
	out += std::to_string(s.GetPostScript()) + std::to_string(s.GetScanScript()) + std::to_string(s.GetQueueScript()) +
		std::to_string(s.GetSchedulerScript()) + std::to_string(s.GetFeedScript()) + "|";
	out += bytes(s.GetDisplayName()) + bytes(s.GetLocation()) + bytes(s.GetRootDir()) + bytes(s.GetAbout()) +
		bytes(s.GetQueueEvents()) + bytes(s.GetTaskTime());
	for (const auto& d : s.GetDescription()) out += bytes(d);
	out += "|";
	for (const auto& r : s.GetRequirements()) out += bytes(r);
	out += "|";
	for (const auto& o : s.GetOptions())
	{
		out += std::to_string(o.section.multi) + bytes(o.section.name) + bytes(o.section.prefix) + bytes(o.name) + bytes(o.displayName);
		for (const auto& d : o.description) out += bytes(d);
		out += "/" + bytes(sel(o.value)) + "/";
		for (const auto& v : o.select) out += bytes(sel(v));
		out += "\x02";
	}
	out += "|";
	for (const auto& c : s.GetCommands())
	{
		out += std::to_string(c.section.multi) + bytes(c.section.name) + bytes(c.section.prefix) + bytes(c.name) + bytes(c.displayName) + bytes(c.action);
		for (const auto& d : c.description) out += bytes(d);
		out += "\x02";
	}
	return out;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	std::string path = argv[2];
	const auto fixed = cases();
	// Simulate getline's allocation failure with a partial Rust parse alive.
	{ std::ofstream f(path); f << "### NZBGET SCAN SCRIPT\n### OPTIONS\n#X=value\n"; }
	for (int fail : {0, 1, 2, 3}) {
		Extension::Script s;
		s.SetEntry(path);
		extloadFailAt = fail;
		try { RustExtensionLoader::V1::Load(s, "/loc", "/root"); return 2; }
		catch (const std::bad_alloc&) {}
	}
	extloadFailAt = -1;
	for (int l = 3; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		long scripts = 0;
		for (long round = 0; round < rounds + (long)fixed.size(); round++)
		{
			std::string text = round < (long)fixed.size() ? fixed[round] : script();
			{ std::ofstream f(path, std::ios::binary); f << text; }
			std::string results[3];
			for (int k = 0; k < 3; k++)
			{
				Extension::Script s;
				s.SetEntry(path);
				s.SetName("dir/My.Script.py");
				try {
				bool ok = k == 0 ? OldExtensionLoader::V1::Load(s, "/loc", "/root")
					: k == 1 ? RustExtensionLoader::V1::Load(s, "/loc", "/root")
					: FallbackExtensionLoader::V1::Load(s, "/loc", "/root");
				results[k] = dump(ok, s);
				} catch (const std::out_of_range&) { results[k] = "out_of_range"; }
			}
			if (results[0] != results[1] || results[0] != results[2])
			{
				fprintf(stderr, "mismatch in %s, script:\n%s\nold:      %s\nrust:     %s\nfallback: %s\n", argv[l],
					hex(text).c_str(), hex(results[0]).c_str(), hex(results[1]).c_str(), hex(results[2]).c_str());
				return 1;
			}
			scripts += results[0][0] == '1';
		}
		printf("%s: %ld files agree, %ld scripts (reference %s)\n", argv[l], rounds + (long)fixed.size(), scripts, "''' + REFERENCE + r'''");
	}
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-extload-") as temp:
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
        for name, src, charset in (("tr_TR.ISO8859-9", "tr_TR", "ISO-8859-9"), ("de_DE.UTF-8", "de_DE", "UTF-8")):
            if Path(f"/usr/share/i18n/locales/{src}").exists():
                subprocess.run(["localedef", "--no-archive", "-i", src, "-f", charset, str(locdir / name)], check=True)
                locales.append(name)
        if Path("/usr/share/i18n/locales/en_US").exists():
            custom = temp / "custom-locale"
            custom.write_text(Path("/usr/share/i18n/locales/en_US").read_text().replace(
                'copy "i18n"', 'space <U0009>..<U000D>;<U0020>;<U00FF>\n'
                'blank <U0009>;<U0020>;<U00FF>\n'))
            subprocess.run(["localedef", "--no-archive", "-i", str(custom), "-f", "ISO-8859-1",
                            str(locdir / "custom.ISO8859-1")], check=True)
            locales.append("custom.ISO8859-1")
    (temp / "main.cpp").write_text(main)
    (temp / "old.cpp").write_text(renamed(old_src, "OldExtensionLoader"))
    (temp / "fallback.cpp").write_text(renamed(new_src, "FallbackExtensionLoader", fallback=True))
    (temp / "rust.cpp").write_text(renamed(new_src, "RustExtensionLoader"))
    binary = temp / "extload"
    for extra in (["-fsigned-char", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-funsigned-char"]):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "old.cpp"),
                        str(temp / "fallback.cpp"), str(temp / "rust.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, str(temp / "script.py"), *locales], check=True, env=env)
