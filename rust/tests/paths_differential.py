#!/usr/bin/env python3
"""Compare FileSystem's path text functions (rust/src/paths.rs) with the
pre-port C++: NormalizePathSeparators, BaseFileName, SplitPathAndFilename,
ReservedChar, MakeValidFilename (with and without slashes),
SanitizePathSegment, SanitizeRelativePath, ExtractFilePathFromCmd and
EscapePathForShell, on the lines of the given files and generated paths, in
the C, C.UTF-8 and tr_TR.ISO8859-9 locales (strncasecmp).

The pre-port functions are compiled as OldFS and linked with a built
libnzbget.

Usage: paths_differential.py BUILD_DIR [TEXT_FILE ...]
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
REFERENCE = "80c9afb7"
BUILD = Path(sys.argv[1]).resolve()
TEXTS = [str(Path(a).resolve()) for a in sys.argv[2:]]
if not all(Path(t).is_file() for t in TEXTS):
    sys.exit("missing input")

src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/FileSystem.cpp"], cwd=ROOT, text=True)


def block(sig):
    start = src.index(sig + "\n{")
    return src[start:src.index("\n}\n", start) + 3].replace("FileSystem::", "OldFS::")


sigs = ["void FileSystem::NormalizePathSeparators(char* path)", "char* FileSystem::BaseFileName(const char* filename)",
        "std::pair<std::string, std::string> FileSystem::SplitPathAndFilename(const std::string& fullPath)",
        "bool FileSystem::ReservedChar(char ch)", "CString FileSystem::MakeValidFilename(const char* filename, bool allowSlashes)",
        "std::string FileSystem::SanitizePathSegment(std::string_view name)",
        "std::string FileSystem::SanitizeRelativePath(std::string_view path)",
        "std::string FileSystem::ExtractFilePathFromCmd(const std::string& path)",
        "std::string FileSystem::EscapePathForShell(const std::string& path)"]
names = src[src.index("const char* RESERVED_DEVICE_NAMES[]"):]
names = names[:names.index("};") + 2].replace("RESERVED_DEVICE_NAMES", "OLD_RESERVED_DEVICE_NAMES")

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

harness = r'''
#include "nzbget.h"
#include "FileSystem.h"
#include "Util.h"
#include <clocale>
#include <fstream>
#include <random>
''' + names + r'''
struct OldFS {
    static void NormalizePathSeparators(char*); static char* BaseFileName(const char*);
    static std::pair<std::string, std::string> SplitPathAndFilename(const std::string&); static bool ReservedChar(char);
    static CString MakeValidFilename(const char*, bool); static std::string SanitizePathSegment(std::string_view);
    static std::string SanitizeRelativePath(std::string_view); static std::string ExtractFilePathFromCmd(const std::string&);
    static std::string EscapePathForShell(const std::string&);
};
#define RESERVED_DEVICE_NAMES OLD_RESERVED_DEVICE_NAMES
''' + "".join(block(s) for s in sigs) + r'''
#undef RESERVED_DEVICE_NAMES
static long cases = 0;
static void fail(const char* what, const std::string& s) { printf("MISMATCH %s [%s]\n", what, s.c_str()); exit(1); }
static void check(const std::string& s) {
    std::string a = s, b = s;
    OldFS::NormalizePathSeparators(a.data()); FileSystem::NormalizePathSeparators(b.data());
    if (strcmp(a.c_str(), b.c_str())) fail("NormalizePathSeparators", s);
    if (OldFS::BaseFileName(s.c_str()) != FileSystem::BaseFileName(s.c_str())) fail("BaseFileName", s);
    if (OldFS::SplitPathAndFilename(s) != FileSystem::SplitPathAndFilename(s)) fail("SplitPathAndFilename", s);
    for (bool slashes : {false, true}) {
        CString x = OldFS::MakeValidFilename(s.c_str(), slashes), y = FileSystem::MakeValidFilename(s.c_str(), slashes);
        if (strcmp(x, y)) fail("MakeValidFilename", s);
    }
    if (OldFS::SanitizePathSegment(s) != FileSystem::SanitizePathSegment(s)) fail("SanitizePathSegment", s);
    if (OldFS::SanitizeRelativePath(s) != FileSystem::SanitizeRelativePath(s)) fail("SanitizeRelativePath", s);
    if (OldFS::ExtractFilePathFromCmd(s) != FileSystem::ExtractFilePathFromCmd(s)) fail("ExtractFilePathFromCmd", s);
    if (OldFS::EscapePathForShell(s) != FileSystem::EscapePathForShell(s)) fail("EscapePathForShell", s);
    ++cases;
}
int main(int argc, char** argv) {
    for (int c = -128; c < 128; ++c)
        if (OldFS::ReservedChar((char)c) != FileSystem::ReservedChar((char)c)) { printf("MISMATCH ReservedChar %d\n", c); return 1; }
    std::vector<std::string> lines;
    for (int i = 1; i < argc; ++i) { std::ifstream in(argv[i]); for (std::string l; std::getline(in, l);) lines.push_back(l); }
    std::mt19937 rng(13);
    auto pick = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); };
    const char* parts[] = {"/", "\\", ".", "..", "...", " ", "\t", "a", "Movie", "con", "CON", "com1", "LPT9", "nul", "aux", "prn",
        "Con", "console", "COM10", ":", "*", "?", "\"", "<", ">", "|", "\x01", "\x7f", "\xe9", "\xc3\xa9", "\xe2\x82\xac", "-v",
        " --opt", "/usr/bin/x", "C:\\Program Files\\x.exe", "IDE", "\xfd", "i"};
    for (const char* loc : {"C", "C.UTF-8", "tr_TR.ISO8859-9"}) {
        if (!setlocale(LC_CTYPE, loc)) { printf("locale %s unavailable\n", loc); return 1; }
        for (auto& l : lines) check(l);
        for (int i = 0; i < 300000; ++i) {
            std::string s;
            int n = pick(8);
            for (int k = 0; k < n; ++k) s += parts[pick(sizeof parts / sizeof *parts)];
            check(s);
        }
        // long names: the 1024-byte cut at a UTF-8 boundary
        for (int i = 0; i < 2000; ++i) {
            std::string s(1000 + pick(40), 'x');
            for (int k = 0; k < 30; ++k) s[pick(s.size())] = "\xc3\xa9\xe2\x82\xac./ "[pick(9)];
            check(s);
        }
        printf("locale %s passed\n", loc);
    }
    printf("%ld inputs agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-paths-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(harness)
    env = dict(os.environ)
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/tr_TR").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "tr_TR", "-f", "ISO-8859-9", str(locdir / "tr_TR.ISO8859-9")], check=True)
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
    binary = temp / "paths"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                    *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
    subprocess.run([str(binary), *TEXTS], check=True, env=env)
