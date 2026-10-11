#!/usr/bin/env python3
"""Compare XmlRpcProcessor's Access and Decide (rust/src/rpcroute.rs with the
C++ wrappers of XmlRpc.cpp) and Options::OptEntry::Restricted
(rust/src/options.rs with its Options.cpp wrapper), and their C++ fallbacks,
with the pre-port C++.

The reference's access step (from Execute) and dispatch decision (the end of
Dispatch) are copied verbatim into a stand-in XmlRpcProcessor with a recording
command, BuildResponse, BuildJsonPRefusal and BuildErrorResponse. The new
side runs this tree's Access line and its switch over Decide in the same
stand-in. Every combination of protocol, HTTP method, user access, reading
method, error command and option JsonP is compared, and Decide's outputs are
also compared directly, with each combination of NULL output pointers.
Extraction checks keep the Rust wrappers separate from the C++ fallbacks and
verify that moving Access leaves the rest of Execute and Dispatch unchanged,
with Access still unconditional and before command creation.

Restricted runs in a stand-in OptEntry on every option name of Options.h and
on generated and mutated names: case changes, ':' anywhere, the words it
looks for spelled with every byte, and words around the end of its 1023-byte
copy. Everything runs in C and UTF-8 plus Turkish and German locales when
available, with and without ASan/UBSan on the C++ stand-ins (the linked Rust
library is not instrumented).

--bench times Restricted and the access/decision stand-ins, including input
loads and volatile stores of their results (best of 15 rounds of 200,000 calls).
It excludes parsing, command creation and response serialization. The C++
stand-ins use -O3 -DNDEBUG; linked libraries retain BUILD_DIR's build profile.

Usage: rpcaccess_differential.py BUILD_DIR [ROUNDS]
       rpcaccess_differential.py --bench BUILD_DIR
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
REFERENCE = "b6c4a4fe"
BENCH = sys.argv[1:2] == ["--bench"]
args = sys.argv[2:] if BENCH else sys.argv[1:]
BUILD = Path(args[0]).resolve()
ROUNDS = args[1] if len(args) > 1 else "200000"


def show(path):
    return subprocess.check_output(["git", "show", f"{REFERENCE}:{path}"], cwd=ROOT, text=True)


def definition(src, sig, which):
    # the Rust wrapper is the first definition, the C++ (or pre-port) the last
    i = src.index(sig + "\n{") if which == "first" else src.rindex(sig + "\n{")
    return src[i:src.index("\n}\n", i) + 3]


def block(src, start, last):
    # from the line holding `start` to the end of the block closing after `last`
    i = src.rindex("\n", 0, src.index(start)) + 1
    j = src.index("\t\t}\n", src.index(last, i)) + 4
    return src[i:j]


def enums(header):
    return "".join(m.group() + "\n" for m in re.finditer(r"\tenum \w+\n\t\{\n.*?\n\t\};", header, re.S))


old_rpc, new_rpc = show("daemon/remote/XmlRpc.cpp"), (ROOT / "daemon/remote/XmlRpc.cpp").read_text()
old_opt, new_opt = show("daemon/main/Options.cpp"), (ROOT / "daemon/main/Options.cpp").read_text()
old_enums, new_enums = enums(show("daemon/remote/XmlRpc.h")), enums((ROOT / "daemon/remote/XmlRpc.h").read_text())
old_execute = definition(old_rpc, "void XmlRpcProcessor::Execute()", "last")
new_execute = definition(new_rpc, "void XmlRpcProcessor::Execute()", "last")
old_dispatch = definition(old_rpc, "void XmlRpcProcessor::Dispatch()", "last")
new_dispatch = definition(new_rpc, "void XmlRpcProcessor::Dispatch()", "last")

i = old_execute.index("\tif (m_protocol == rpJsonPRpc && m_userAccess == uaControl)\n")
old_access = old_execute[i:old_execute.index("\tDispatch();", i)]
old_decision = block(old_dispatch, "bool safeToExecute =",
    'BuildErrorResponse(4, "Not safe procedure for HTTP-Method GET. Use Method POST instead");')
new_access = "\tm_userAccess = Access(m_protocol, m_userAccess);\n"
if new_rpc.count(new_access) != 1 or new_dispatch.count(new_access) != 1:
    sys.exit("expected one Access call in Dispatch")
new_access = new_dispatch[new_dispatch.index(new_access):new_dispatch.index(new_access) + len(new_access)]
new_decision = block(new_dispatch, "int errCode = 0;", "BuildErrorResponse(errCode, errText);")
# Access must run unconditionally before the multicall/command branch (which
# reads m_userAccess). Check all code omitted from the stand-in as well.
code = lambda s: re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", s))
if code(old_execute.replace(old_access, "")) != code(new_execute):
    sys.exit("Execute changed beyond moving Access: review the extraction")
branch = '\tif (!strcasecmp(methodName, "system.multicall")'
if code(new_dispatch[:new_dispatch.index(new_access)]) != code(old_dispatch[:old_dispatch.index(branch)]):
    sys.exit("Access must precede the multicall/command branch unconditionally")
if code(old_dispatch.replace(old_decision, "DECISION;")) != code(
        new_dispatch.replace(new_access, "").replace(new_decision, "DECISION;")):
    sys.exit("Dispatch changed beyond Access and Decide: review the extraction")

ACCESS_SIG = "XmlRpcProcessor::EUserAccess XmlRpcProcessor::Access(ERpcProtocol protocol, EUserAccess userAccess)"
DECIDE_SIG = ("XmlRpcProcessor::EDispatch XmlRpcProcessor::Decide(ERpcProtocol protocol, EHttpMethod httpMethod,\n"
              "\tbool safeMethod, bool error, bool jsonP, int* errCode, const char** errText)")
RESTRICTED_SIG = "bool Options::OptEntry::Restricted()"

for src, sig, symbol in ((new_rpc, ACCESS_SIG, "nzbget_rs_rpc_access"),
                         (new_rpc, DECIDE_SIG, "nzbget_rs_rpc_decide"),
                         (new_opt, RESTRICTED_SIG, "nzbget_rs_option_restricted")):
    if (src.count(sig + "\n{") != 2 or symbol not in definition(src, sig, "first")
            or "nzbget_rs_" in definition(src, sig, "last")):
        sys.exit(f"expected a Rust wrapper and a separate C++ fallback for {sig}")
    guarded = ("#ifdef NZBGET_USE_RUST\n" + definition(src, sig, "first")
               + "#else\n" + definition(src, sig, "last") + "#endif")
    if guarded not in src:
        sys.exit(f"expected NZBGET_USE_RUST to select the Rust wrapper for {sig}")

header = (ROOT / "daemon/main/Options.h").read_text()
names = re.findall(r"static constexpr std::string_view (\w+) =", header)
constants = "".join(f"\tstatic constexpr std::string_view {n} = ::Options::{n};\n" for n in names)
old_constants = "\n".join(re.findall(r'\tstatic constexpr std::string_view \w+ = "[^"]*";',
                                     show("daemon/main/Options.h"))) + "\n"
option_names = re.findall(r'static constexpr std::string_view \w+ = "([^"]*)";', header)
if not option_names or not old_constants.strip():
    sys.exit("no option names extracted")


def standin(enum_text, ported, access, decision, restricted):
    statics = r'''
	static EUserAccess Access(ERpcProtocol protocol, EUserAccess userAccess);
	static EDispatch Decide(ERpcProtocol protocol, EHttpMethod httpMethod, bool safeMethod, bool error,
		bool jsonP, int* errCode, const char** errText);
''' if ported else ""
    return r'''
class XmlRpcProcessor
{
public:
''' + enum_text + statics + r'''
	ERpcProtocol m_protocol;
	EHttpMethod m_httpMethod;
	EUserAccess m_userAccess;
	bool m_safeMethod;
	bool m_jsonP;
	std::string m_log;
	// --bench consumes the branch, code and text without serializing a response.
	void Note(const std::string& s) { m_log += s + ";"; }
	void BuildResponse(const char* response, const char* callbackFunc, bool fault, const char* requestId)
	{
		if (quiet) { Record(0, 0, nullptr); return; }
		Note(std::string("response:") + response + ":" + callbackFunc + ":" + std::to_string(fault) + ":" + requestId);
	}
	void BuildJsonPRefusal(Command* command, int errCode, const char* errText, const char* requestId)
	{
		if (quiet) { Record(1, errCode, errText); return; }
		Note("callback:" + std::to_string(errCode) + ":" + errText + ":" + command->GetCallbackFunc() + ":" + requestId);
	}
	void BuildErrorResponse(int errCode, const char* errText)
	{
		if (quiet) { Record(2, errCode, errText); return; }
		Note("error:" + std::to_string(errCode) + ":" + errText);
	}
	void Step(int protocol, int httpMethod, int userAccess, bool safe, bool error, bool jsonP, Command& cmd)
	{
		m_protocol = (ERpcProtocol)protocol;
		m_httpMethod = (EHttpMethod)httpMethod;
		m_userAccess = (EUserAccess)userAccess;
		m_safeMethod = safe;
		m_jsonP = jsonP;
		cmd.m_error = error;
		CommandRef command{&cmd};
		const char* requestId = "7";
''' + access + "\t{\n" + decision + "\t}\n" + r'''
	}
	std::string Run(int protocol, int httpMethod, int userAccess, bool safe, bool error, bool jsonP)
	{
		m_log.clear();
		Command cmd{false, this};
		Step(protocol, httpMethod, userAccess, safe, error, jsonP, cmd);
		return m_log + "access:" + std::to_string(m_userAccess);
	}
};

class Options
{
public:
''' + (constants if ported else old_constants) + r'''
	class OptEntry
	{
	public:
		CString m_name;
		bool Restricted();
	};
};
''' + restricted


def impl(namespace, enum_text, ported, access, decision, rpc_src, which, opt_src):
    defs = (definition(rpc_src, ACCESS_SIG, which) + definition(rpc_src, DECIDE_SIG, which)) if ported else ""
    return (f"namespace {namespace} {{\n"
            + standin(enum_text, ported, access, decision, definition(opt_src, RESTRICTED_SIG, which))
            + defs + "\n}\n")


main = r'''
#include "nzbget.h"
#include "Util.h"
#include "Options.h"
#include "FeedInfo.h"
#include "nzbget_rs.h"
#include <chrono>
#include <clocale>
#include <string>
#include <vector>

#ifdef NZBGET_STRICT_CTYPE
// glibc accepts negative signed-byte arguments as an extension. An unsigned-char
// C++ caller never needs that extension: expose Rust's accidental dependence on
// it by leaving negative inputs unchanged, as stricter C libraries can do.
extern "C" int __real_tolower(int);
extern "C" int __wrap_tolower(int c) { return c < 0 ? c : __real_tolower(c); }
#endif

static bool quiet = false;
static volatile unsigned long sink = 0;
static volatile int sinkKind, sinkCode, sinkAccess;
static const char* volatile sinkText;

static void Record(int kind, int code, const char* text)
{
	sinkKind = kind;
	sinkCode = code;
	sinkText = text;
}

// the command Dispatch made: whether it is the error command, and what it was asked
template <class P> struct CommandOf
{
	bool m_error;
	P* m_owner;
	bool IsError() { return m_error; }
	void Execute() { if (quiet) sink++; else m_owner->Note("execute"); }
	const char* GetResponse() { return "result"; }
	const char* GetCallbackFunc() { return "cb"; }
	bool GetFault() { return false; }
};

''' + "".join(
    f"namespace {ns} {{ class XmlRpcProcessor; typedef CommandOf<XmlRpcProcessor> Command;\n"
    "struct CommandRef { Command* p; Command* get() { return p; } Command* operator->() { return p; } }; }\n"
    for ns in ("oldimpl", "newimpl", "fallbackimpl")) + (
    impl("oldimpl", old_enums, False, old_access, old_decision, old_rpc, "last", old_opt)
    + impl("newimpl", new_enums, True, new_access, new_decision, new_rpc, "first", new_opt)
    + impl("fallbackimpl", new_enums, True, new_access, new_decision, new_rpc, "last", new_opt)) + r'''

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % (unsigned long long)n); }

static const char* const OPTION_NAMES[] = {''' + ", ".join(f'"{n}"' for n in option_names) + r'''};
static const char* const WORDS[] = {"username", "password", "apikey", "UserName", "PASSWORD", "ApiKey", "APIKEY",
	"user", "pass", "api", "key", "usernam", "assword", "pikey", ":", "."};
static const char* const PARTS[] = {"Server", "Server1.", "Category2.", "Feed3.", "Task4.", "Control", "Secure",
	"DupeSearch", "Host", "Port", "Name", "Ext.py", "Daemon", "IP", "Ip", "Mask", "Json", "P", ""};

static std::string recase(std::string s)
{
	if (below(3) == 0)
		for (char& c : s) c = below(2) ? toupper((unsigned char)c) : tolower((unsigned char)c);
	return s;
}

static int checked = 0;

static void compareName(const std::string& name)
{
	oldimpl::Options::OptEntry a{name.c_str()};
	newimpl::Options::OptEntry b{name.c_str()};
	fallbackimpl::Options::OptEntry c{name.c_str()};
	bool x = a.Restricted(), y = b.Restricted(), z = c.Restricted();
	if (x != y || x != z)
	{
		fprintf(stderr, "Restricted mismatch in %s: [%s] (%zu bytes) old %d rust %d fallback %d\n",
			setlocale(LC_ALL, nullptr), name.c_str(), name.size(), x, y, z);
		exit(1);
	}
	checked++;
}

static void compareDecisions()
{
	oldimpl::XmlRpcProcessor a;
	newimpl::XmlRpcProcessor b;
	fallbackimpl::XmlRpcProcessor c;
	for (int protocol = 0; protocol <= 3; protocol++)
	for (int method = 0; method <= 1; method++)
	for (int access = 0; access <= 2; access++)
	for (int safe = 0; safe <= 1; safe++)
	for (int error = 0; error <= 1; error++)
	for (int jsonP = 0; jsonP <= 1; jsonP++)
	{
		std::string x = a.Run(protocol, method, access, safe, error, jsonP);
		std::string y = b.Run(protocol, method, access, safe, error, jsonP);
		std::string z = c.Run(protocol, method, access, safe, error, jsonP);
		if (x != y || x != z)
		{
			fprintf(stderr, "dispatch mismatch: protocol %d method %d access %d safe %d error %d jsonP %d\nold:      %s\nrust:     %s\nfallback: %s\n",
				protocol, method, access, safe, error, jsonP, x.c_str(), y.c_str(), z.c_str());
			exit(1);
		}
		int codes[2] = {-1, -1};
		const char* texts[2] = {"sentinel", "sentinel"};
		int d1 = newimpl::XmlRpcProcessor::Decide((newimpl::XmlRpcProcessor::ERpcProtocol)protocol,
			(newimpl::XmlRpcProcessor::EHttpMethod)method, safe, error, jsonP, &codes[0], &texts[0]);
		int d2 = fallbackimpl::XmlRpcProcessor::Decide((fallbackimpl::XmlRpcProcessor::ERpcProtocol)protocol,
			(fallbackimpl::XmlRpcProcessor::EHttpMethod)method, safe, error, jsonP, &codes[1], &texts[1]);
		if (d1 != d2 || codes[0] != codes[1] || !texts[0] != !texts[1] ||
			(texts[0] && strcmp(texts[0], texts[1])) || (d1 == 0) != (codes[0] == 0 && !texts[0]))
		{
			fprintf(stderr, "Decide mismatch: protocol %d method %d safe %d error %d jsonP %d\n", protocol, method, safe, error, jsonP);
			exit(1);
		}
		for (int mask = 0; mask < 4; mask++)
		{
			int code1 = -1, code2 = -1;
			const char* text1 = "sentinel";
			const char* text2 = "sentinel";
			int d3 = newimpl::XmlRpcProcessor::Decide((newimpl::XmlRpcProcessor::ERpcProtocol)protocol,
				(newimpl::XmlRpcProcessor::EHttpMethod)method, safe, error, jsonP,
				mask & 1 ? &code1 : nullptr, mask & 2 ? &text1 : nullptr);
			int d4 = fallbackimpl::XmlRpcProcessor::Decide((fallbackimpl::XmlRpcProcessor::ERpcProtocol)protocol,
				(fallbackimpl::XmlRpcProcessor::EHttpMethod)method, safe, error, jsonP,
				mask & 1 ? &code2 : nullptr, mask & 2 ? &text2 : nullptr);
			int expectedCode = mask & 1 ? codes[0] : -1;
			const char* expectedText = mask & 2 ? texts[0] : "sentinel";
			auto sameText = [&](const char* text) {
				return text && expectedText ? !strcmp(text, expectedText) : text == expectedText;
			};
			if (d3 != d1 || d4 != d1 || code1 != expectedCode || code2 != expectedCode ||
				!sameText(text1) || !sameText(text2))
			{
				fprintf(stderr, "Decide NULL output mismatch: mask %d\n", mask);
				exit(1);
			}
		}
		checked++;
	}
}

template <class R> static double best(R run)
{
	double fastest = 1e30;
	for (int round = 0; round < 15; round++)
	{
		auto start = std::chrono::steady_clock::now();
		for (int i = 0; i < 200000; i++)
		{
			// Keep reads and pure calls inside each iteration even for fixed names.
			asm volatile("" ::: "memory");
			run();
		}
		double ns = std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now() - start).count() / 200000;
		if (ns < fastest) fastest = ns;
	}
	return fastest;
}

static void bench()
{
	quiet = true;
	for (const char* name : {"ControlIP", "Server1.Password", "Server1.Host", "Category1.Extensions"})
	{
		volatile bool restricted;
		oldimpl::Options::OptEntry a{name};
		newimpl::Options::OptEntry b{name};
		double x = best([&] { restricted = a.Restricted(); });
		double y = best([&] { restricted = b.Restricted(); });
		printf("Restricted %-22s C++ %6.1f ns  Rust %6.1f ns  %.2fx\n", name, x, y, x / y);
	}
	struct Case { const char* name; int protocol, method, access, safe, jsonP; };
	for (Case k : {Case{"JSON-RPC POST", 2, 0, 0, 0, 0}, Case{"JSON-P GET, reading", 3, 1, 0, 1, 1},
		Case{"JSON-P GET, JsonP off", 3, 1, 0, 1, 0}, Case{"XML-RPC GET, writing", 1, 1, 0, 0, 0}})
	{
		volatile int protocol = k.protocol, method = k.method, access = k.access, safe = k.safe, jsonP = k.jsonP;
		oldimpl::XmlRpcProcessor a;
		newimpl::XmlRpcProcessor b;
		oldimpl::Command ca{false, &a};
		newimpl::Command cb{false, &b};
		double x = best([&] { a.Step(protocol, method, access, safe, false, jsonP, ca); sinkAccess = a.m_userAccess; });
		double y = best([&] { b.Step(protocol, method, access, safe, false, jsonP, cb); sinkAccess = b.m_userAccess; });
		printf("Access/Decide %-22s C++ %6.1f ns  Rust %6.1f ns  %.2fx\n", k.name, x, y, x / y);
	}
}

int main(int argc, char** argv)
{
	if (!strcmp(argv[1], "bench")) { bench(); return 0; }
	if (nzbget_rs_option_restricted(nullptr, (char)-1 < 0) != 0)
	{
		fprintf(stderr, "Restricted NULL input mismatch\n");
		return 1;
	}
	long rounds = atol(argv[1]);
	for (int l = 2; l < argc; l++)
	{
		if (!setlocale(LC_ALL, argv[l])) { fprintf(stderr, "no locale %s\n", argv[l]); return 1; }
		checked = 0;
		compareDecisions();
		for (const char* name : OPTION_NAMES)
		{
			compareName(name);
			for (int i = 0; i < 4; i++) compareName(recase(name));
			std::string lower(name), upper(name);
			for (char& c : lower) c = tolower((unsigned char)c);
			for (char& c : upper) c = toupper((unsigned char)c);
			compareName(lower);
			compareName(upper);
			compareName(std::string(name) + "x");
			compareName(std::string(name).substr(0, strlen(name) ? strlen(name) - 1 : 0));
		}
		// every byte in place of each letter of the words, and around them
		for (const char* word : {"username", "password", "apikey", "UMASK", "ControlIP", "JsonP"})
			for (size_t at = 0; at <= strlen(word); at++)
				for (int byte = 1; byte <= 255; byte++)
				{
					std::string w(word);
					std::string replaced = w.substr(0, at) + (char)byte + (at < w.size() ? w.substr(at + 1) : "");
					compareName(replaced);
					compareName("Server1." + replaced);
					compareName(w.substr(0, at) + (char)byte + w.substr(at));
				}
		// the words are searched in the first 1023 bytes; ':' in the whole name
		for (int len = 1000; len <= 1030; len++)
			for (const char* word : {"username", "PassWord", "apikey", ":"})
			{
				compareName(std::string(len, 'a') + word);
				compareName(std::string(len, 'A') + word + std::string(3000, 'b'));
			}
		compareName("");
		for (long round = 0; round < rounds; round++)
		{
			std::string name;
			int n = 1 + below(5);
			for (int i = 0; i < n; i++)
			{
				int kind = below(10);
				if (kind < 4) name += recase(PARTS[below(sizeof(PARTS) / sizeof(*PARTS))]);
				else if (kind < 7) name += recase(WORDS[below(sizeof(WORDS) / sizeof(*WORDS))]);
				else if (kind < 8) name += recase(OPTION_NAMES[below(sizeof(OPTION_NAMES) / sizeof(*OPTION_NAMES))]);
				else if (kind < 9) name += std::to_string(below(100));
				else name += (char)(1 + below(255));
			}
			if (below(50) == 0) name = std::string(1000 + below(40), 'x') + name;
			compareName(name);
		}
		printf("%s: %d decisions and names agree (reference %s)\n", argv[l], checked, "''' + REFERENCE + r'''");
	}
}
'''

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]


def build(temp, extra, cxx_flags):
    binary = temp / "rpcaccess"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *cxx_flags, *shlex.split(get("CXX_DEFINES")),
                    *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                    *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
    return binary


with tempfile.TemporaryDirectory(prefix="nzbget-rpcaccess-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    if BENCH:
        release = [f for f in shlex.split(get("CXX_FLAGS")) if not re.fullmatch(r"-O\S*|-g\S*", f)]
        subprocess.run([str(build(temp, ["-O3", "-DNDEBUG"], release)), "bench"], check=True)
        sys.exit(0)
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
        subprocess.run(["localedef", "--no-archive", "-i", "tr_TR", "-f", "ISO-8859-9", str(locdir / "tr_TR.ISO8859-9")], check=True)
        locales.append("tr_TR.ISO8859-9")
        for source, charset, name in [("tr_TR", "UTF-8", "tr_TR.UTF-8"), ("de_DE", "ISO-8859-1", "de_DE.ISO8859-1")]:
            if Path(f"/usr/share/i18n/locales/{source}").exists():
                subprocess.run(["localedef", "--no-archive", "-i", source, "-f", charset, str(locdir / name)], check=True)
                locales.append(name)
    char_modes = [[], ["-fsigned-char"], ["-funsigned-char"]]
    if sys.platform.startswith("linux"):
        char_modes.append(["-funsigned-char", "-DNZBGET_STRICT_CTYPE", "-Wl,--wrap=tolower"])
    for char_flags in char_modes:
        print("C++ char mode: " + " ".join(char_flags or ["target default"]), flush=True)
        for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], []):
            subprocess.run([str(build(temp, [*extra, *char_flags], shlex.split(get("CXX_FLAGS")))), ROUNDS, *locales], check=True, env=env)
