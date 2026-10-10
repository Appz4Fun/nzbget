#!/usr/bin/env python3
"""Compare ExtensionLoader::V1::Load (rust/src/extload.rs with the C++ wrapper
of ExtensionLoader.cpp), and its C++ fallback, with the pre-port C++ on
generated and mutated pre-manifest extension scripts: the result, the kind,
about text, queue events, task time, description, requirements, options
(sections, names, descriptions, values, select values) and commands, in the
C, C.UTF-8, tr_TR.ISO8859-9 and de_DE.UTF-8 locales (strtod's decimal comma).

The pre-port and fallback loaders are compiled as separate translation units
with the namespace renamed; the Rust-backed one is the build's.

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

header = (ROOT / "daemon/extension/ExtensionLoader.h").read_text()
decls = header[header.index("namespace ExtensionLoader"):header.rindex("#endif")]


def renamed(src, name, fallback=False):
    body = src.replace("namespace ExtensionLoader", f"namespace {name}")
    # the declarations (and the template) first, in the renamed namespace
    i = body.index(f"namespace {name}")
    out = body[:i] + decls.replace("namespace ExtensionLoader", f"namespace {name}") + body[i:]
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
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
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

namespace OldExtensionLoader::V1 { bool Load(Extension::Script& script, const char* location, const char* rootDir); }
namespace FallbackExtensionLoader::V1 { bool Load(Extension::Script& script, const char* location, const char* rootDir); }

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

static std::string sel(const ManifestFile::SelectOption& o)
{
	if (const double* d = std::get_if<double>(&o)) { char b[64]; snprintf(b, sizeof b, "n%a", *d); return b; }
	return "s" + std::get<std::string>(o);
}

static std::string dump(bool ok, const Extension::Script& s)
{
	std::string out = std::to_string(ok) + "|";
	if (!ok) return out;
	out += std::to_string(s.GetPostScript()) + std::to_string(s.GetScanScript()) + std::to_string(s.GetQueueScript()) +
		std::to_string(s.GetSchedulerScript()) + std::to_string(s.GetFeedScript()) + "|";
	out += std::string(s.GetDisplayName()) + "|" + s.GetLocation() + "|" + s.GetRootDir() + "|" + s.GetAbout() + "|" +
		s.GetQueueEvents() + "|" + s.GetTaskTime() + "|";
	for (const auto& d : s.GetDescription()) out += d + "\x01";
	out += "|";
	for (const auto& r : s.GetRequirements()) out += r + "\x01";
	out += "|";
	for (const auto& o : s.GetOptions())
	{
		out += std::to_string(o.section.multi) + o.section.name + "/" + o.section.prefix + "/" + o.name + "/" + o.displayName + "/";
		for (const auto& d : o.description) out += d + "\x01";
		out += "/" + sel(o.value) + "/";
		for (const auto& v : o.select) out += sel(v) + "\x01";
		out += "\x02";
	}
	out += "|";
	for (const auto& c : s.GetCommands())
	{
		out += std::to_string(c.section.multi) + c.section.name + "/" + c.section.prefix + "/" + c.name + "/" + c.displayName + "/" + c.action + "/";
		for (const auto& d : c.description) out += d + "\x01";
		out += "\x02";
	}
	return out;
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	std::string path = argv[2];
	for (int l = 3; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		long scripts = 0;
		for (long round = 0; round < rounds; round++)
		{
			std::string text = script();
			{ std::ofstream f(path, std::ios::binary); f << text; }
			std::string results[3];
			for (int k = 0; k < 3; k++)
			{
				Extension::Script s;
				s.SetEntry(path);
				s.SetName("dir/My.Script.py");
				bool ok = k == 0 ? OldExtensionLoader::V1::Load(s, "/loc", "/root")
					: k == 1 ? ExtensionLoader::V1::Load(s, "/loc", "/root")
					: FallbackExtensionLoader::V1::Load(s, "/loc", "/root");
				results[k] = dump(ok, s);
			}
			if (results[0] != results[1] || results[0] != results[2])
			{
				fprintf(stderr, "mismatch in %s, script:\n%s\nold:      %s\nrust:     %s\nfallback: %s\n", argv[l],
					text.c_str(), results[0].c_str(), results[1].c_str(), results[2].c_str());
				return 1;
			}
			scripts += results[0][0] == '1';
		}
		printf("%s: %ld files agree, %ld scripts (reference %s)\n", argv[l], rounds, scripts, "''' + REFERENCE + r'''");
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
    (temp / "main.cpp").write_text(main)
    (temp / "old.cpp").write_text(renamed(old_src, "OldExtensionLoader"))
    (temp / "fallback.cpp").write_text(renamed(new_src, "FallbackExtensionLoader", fallback=True))
    binary = temp / "extload"
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "old.cpp"),
                        str(temp / "fallback.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        subprocess.run([str(binary), ROUNDS, str(temp / "script.py"), *locales], check=True, env=env)
