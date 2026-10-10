#!/usr/bin/env python3
"""Compare Deobfuscation (rust/src/deobfuscation.rs) with the pre-port C++:
Deobfuscate and IsExcessivelyObfuscated on the lines of the given files (real
subjects and file names), what Deobfuscate makes of them, and generated
names, in the C, C.UTF-8 and en_US.ISO8859-1 locales.

The pre-port code is compiled as OldDeobfuscation and linked with a built
libnzbget (FileTypes, FileSystem).

Usage: deobfuscation_differential.py BUILD_DIR [TEXT_FILE ...]
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
REFERENCE = "75817c42"
BUILD = Path(sys.argv[1]).resolve()
INPUTS = [str(Path(a).resolve()) for a in sys.argv[2:]]

old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/queue/Deobfuscation.cpp"], cwd=ROOT, text=True)
old = old.replace('#include "Deobfuscation.h"', '#include "OldDeobfuscation.h"').replace("namespace Deobfuscation", "namespace OldDeobfuscation")
header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/queue/Deobfuscation.h"], cwd=ROOT, text=True)
header = header.replace("namespace Deobfuscation", "namespace OldDeobfuscation").replace("DEOBFUSCATION_H", "OLDDEOBFUSCATION_H")

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

harness = r'''
#include "nzbget.h"
#include "Deobfuscation.h"
#include "OldDeobfuscation.h"
#include <chrono>
#include <clocale>
#include <fstream>
#include <random>

static long cases = 0;
static void check(const std::string& s) {
    std::string a = OldDeobfuscation::Deobfuscate(s), b = Deobfuscation::Deobfuscate(s);
    if (a != b) { printf("MISMATCH Deobfuscate [%s]: [%s] vs [%s]\n", s.c_str(), a.c_str(), b.c_str()); exit(1); }
    for (const std::string& t : {s, a}) {
        if (OldDeobfuscation::IsExcessivelyObfuscated(t) != Deobfuscation::IsExcessivelyObfuscated(t)) {
            printf("MISMATCH IsExcessivelyObfuscated [%s]: %d vs %d\n", t.c_str(),
                OldDeobfuscation::IsExcessivelyObfuscated(t), Deobfuscation::IsExcessivelyObfuscated(t));
            exit(1);
        }
    }
    ++cases;
}

int main(int argc, char** argv) {
    std::vector<std::string> lines;
    for (int i = 2; i < argc; ++i) {
        std::ifstream in(argv[i]);
        for (std::string l; std::getline(in, l);) lines.push_back(l);
    }
    std::mt19937 rng(7);
    auto pick = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); };
    const char* parts[] = {"Interstellar", "OPPENHEIMER", "The", "Of", "Into", "MQHeRbSCIoPs", "BCDFGHJKLMNP", "5KzdcWdGVGUG83Q9jv8KXht4O2k57w",
        "1234567890123456", "abc", "xyz", "123", "b00bs", "Backup_12345S01-02", "123456_01", "ABCDEFGHIJK123", "abcdefghijkl123",
        "part01", "vol01+02", ".rar", ".par2", ".001", ".mkv", ".7z", ".r01", ".sfv", "2014", "II", "XIV", "\xe9t\xe9", "S01E02",
        " yEnc (1/50)", "\"", "\"\"", "[PRiVATE]-[", "]-[", " - \"\"", "[", "]", "-", "/", "Re: ", " (", ".", "_", " ", "1080p"};
    for (const char* loc : {"C", "C.UTF-8", "en_US.ISO8859-1"}) {
        if (!setlocale(LC_CTYPE, loc)) { printf("locale %s unavailable\n", loc); continue; }
        for (auto& l : lines) check(l);
        for (int i = 0; i < 300000; ++i) {
            std::string s;
            int n = pick(6) + 1;
            for (int k = 0; k < n; ++k) s += parts[pick(sizeof parts / sizeof *parts)];
            check(s);
        }
        printf("locale %s passed\n", loc);
    }
    printf("%ld inputs agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
    // timing on the input lines
    setlocale(LC_CTYPE, "C.UTF-8");
    for (int side = 0; side < 2; ++side) {
        auto t = std::chrono::steady_clock::now();
        long hits = 0;
        for (auto& l : lines) hits += side ? Deobfuscation::IsExcessivelyObfuscated(Deobfuscation::Deobfuscate(l))
                                           : OldDeobfuscation::IsExcessivelyObfuscated(OldDeobfuscation::Deobfuscate(l));
        printf("%s: %.0f ms for %zu names (%ld obfuscated)\n", side ? "Rust" : "C++ ", std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count(), lines.size(), hits);
    }
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-deobf-") as temp:
    temp = Path(temp)
    (temp / "OldDeobfuscation.h").write_text(header)
    (temp / "OldDeobfuscation.cpp").write_text(old)
    (temp / "main.cpp").write_text(harness)
    env = dict(os.environ)
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/en_US").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "en_US", "-f", "ISO-8859-1", str(locdir / "en_US.ISO8859-1")], check=True)
        # C.UTF-8 from the system archive is not found under LOCPATH: link it
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
    binary = temp / "deobf"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-w", f"-I{temp}", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "OldDeobfuscation.cpp"),
                    "-o", str(binary), *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
    subprocess.run([str(binary), "x", *INPUTS], check=True, env=env)
