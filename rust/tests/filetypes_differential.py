#!/usr/bin/env python3
"""Compare FileTypes (rust/src/filetypes.rs) with the pre-port C++: the 25
name checks on the lines of the given text files and generated names, in the
C, C.UTF-8 and en_US.ISO8859-1 locales, and SniffExtension on the files of
the given header directory (their first bytes), truncations and mutations of
them, generated headers, and on files (the path overload).
On Linux, also inject a short read followed by an I/O error.

The pre-port code is compiled as OldFileTypes and linked with a built
libnzbget.

Usage: filetypes_differential.py BUILD_DIR HEADER_DIR [TEXT_FILE ...]
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
REFERENCE = "89efb7c5"
BUILD = Path(sys.argv[1]).resolve()
HEADERS = Path(sys.argv[2]).resolve()
TEXTS = [str(Path(a).resolve()) for a in sys.argv[3:]]
if not HEADERS.is_dir() or not all(Path(t).is_file() for t in TEXTS):
    sys.exit("missing input")

old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/FileTypes.cpp"], cwd=ROOT, text=True)
old = old.replace('#include "FileTypes.h"', '#include "OldFileTypes.h"').replace("namespace FileTypes", "namespace OldFileTypes")
header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/util/FileTypes.h"], cwd=ROOT, text=True)
header = header.replace("namespace FileTypes", "namespace OldFileTypes").replace("FILETYPES_H", "OLDFILETYPES_H")
names = re.findall(r"bool (Is\w+)\(std::string_view \w+\);", header)
assert len(names) == 25, names

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

checks = "\n".join(f'    if (OldFileTypes::{n}(s) != FileTypes::{n}(s)) fail("{n}", s);' for n in names)
harness = r'''
#include "nzbget.h"
#include "FileTypes.h"
#include "OldFileTypes.h"
#include <clocale>
#include <filesystem>
#include <fstream>
#include <random>
#ifdef __linux__
#include <cerrno>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

// Inject a short read followed by EIO on one regular file. Both sides must
// preserve ifstream::read/gcount behavior when a read fails after some bytes.
static bool injectReadError = false;
static struct stat faultFile;
static size_t remaining = 0;
extern "C" ssize_t read(int fd, void* buf, size_t len) {
    struct stat st;
    if (injectReadError && fstat(fd, &st) == 0 &&
        st.st_dev == faultFile.st_dev && st.st_ino == faultFile.st_ino) {
        if (!remaining) { errno = EIO; return -1; }
        len = std::min(len, remaining);
        ssize_t n = syscall(SYS_read, fd, buf, len);
        if (n > 0) remaining -= static_cast<size_t>(n);
        return n;
    }
    return syscall(SYS_read, fd, buf, len);
}
#endif

static long cases = 0;
static void fail(const char* what, std::string_view s) {
    printf("MISMATCH %s hex [", what);
    for (unsigned char c : s) printf("%02x", c);
    printf("]\n");
    exit(1);
}
static void names(std::string_view s) {
''' + checks + r'''
    ++cases;
}
static void sniff(std::span<const uint8_t> h) {
    if (OldFileTypes::SniffExtension(h) != FileTypes::SniffExtension(h)) {
        printf("MISMATCH SniffExtension (%zu bytes): %s vs %s\n", h.size(),
            std::string(OldFileTypes::SniffExtension(h)).c_str(), std::string(FileTypes::SniffExtension(h)).c_str());
        exit(1);
    }
    ++cases;
}

int main(int argc, char** argv) {
#ifdef __linux__
    const auto faultPath = std::filesystem::path(argv[2]) / "read-error";
    { std::ofstream out(faultPath, std::ios::binary); out << "%PDF-0123456789"; }
    if (stat(faultPath.c_str(), &faultFile) != 0) return 1;
    injectReadError = true;
    remaining = 5;
    auto oldFault = OldFileTypes::SniffExtension(faultPath);
    remaining = 5;
    auto newFault = FileTypes::SniffExtension(faultPath);
    injectReadError = false;
    if (!oldFault.empty() || oldFault != newFault) {
        printf("MISMATCH read error: [%s] vs [%s]\n",
            std::string(oldFault).c_str(), std::string(newFault).c_str());
        return 1;
    }
    printf("short read followed by EIO agrees\n");
#endif
    std::mt19937 rng(11);
    auto pick = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); };
    std::vector<std::string> lines;
    for (int i = 3; i < argc; ++i) {
        std::ifstream in(argv[i]);
        for (std::string l; std::getline(in, l);) lines.push_back(l);
    }
    const char* parts[] = {"movie", "Sample", "-sample", ".sample", "_SAMPLE", "sample", ".", ".rar", ".RAR", ".r00", ".s99", ".z01",
        ".001", ".7z", ".zip", ".gz", ".bz2", ".xz", ".par2", ".SFV", ".mkv", ".MP4", ".ts", ".iso", ".bin", ".cue", ".epub", ".jpg",
        ".nfo", ".srt", "/", "\\", "BDMV", "video_ts", "@eaDir", "__MACOSX", "._", ".DS_Store", "thumbs.db", "part01", "x", "1234",
        "\xe9", "\xc9", "IDE"};
    for (const char* loc : {"C", "C.UTF-8", "en_US.ISO8859-1"}) {
        if (!setlocale(LC_CTYPE, loc)) { printf("locale %s unavailable\n", loc); exit(1); }
        for (auto& l : lines) names(l);
        names({});
        // Explicit lengths, embedded NULs, and every byte under each C locale.
        for (const char* base : parts) {
            std::string s(base);
            for (size_t pos = 0; pos <= s.size(); ++pos) {
                for (int byte = 0; byte < 256; ++byte) {
                    auto t = s;
                    t.insert(pos, 1, static_cast<char>(byte));
                    names(t);
                    if (pos < s.size()) {
                        t = s;
                        t[pos] = static_cast<char>(byte);
                        names(t);
                    }
                }
            }
        }
        for (int i = 0; i < 300000; ++i) {
            std::string s;
            int n = pick(5) + 1;
            for (int k = 0; k < n; ++k) s += parts[pick(sizeof parts / sizeof *parts)];
            names(s);
        }
        printf("names in locale %s agree\n", loc);
    }
    // headers of real files, every prefix length up to 64 and some longer, and mutations
    std::vector<std::vector<uint8_t>> heads;
    for (auto& e : std::filesystem::directory_iterator(argv[1])) {
        std::ifstream in(e.path(), std::ios::binary);
        heads.emplace_back(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
        // the path overload on the same file
        if (OldFileTypes::SniffExtension(e.path()) != FileTypes::SniffExtension(e.path())) {
            printf("MISMATCH SniffExtension(path) %s\n", e.path().c_str());
            exit(1);
        }
    }
    for (auto& h : heads) {
        for (size_t k = 0; k <= h.size(); k += (k < 64 ? 1 : 37)) sniff(std::span<const uint8_t>(h.data(), k));
        for (int m = 0; m < 20; ++m) {
            auto g = h;
            if (g.empty()) break;
            g[pick(g.size())] = pick(256);
            sniff(g);
        }
    }
    static const std::vector<std::vector<uint8_t>> magics = {
        {'%','P','D','F','-'}, {0x1A,0x45,0xDF,0xA3}, {0,0,0,0,'f','t','y','p'}, {0,0,0,0,'m','o','o','v'}, {'R','I','F','F'},
        {0x89,'P','N','G',0x0D,0x0A,0x1A,0x0A}, {'G','I','F','8','9','a'}, {0xFF,0xD8,0xFF}, {'B','M'}, {0x47},
        {0x30,0x26,0xB2,0x75,0x8E,0x66,0xCF,0x11}, {'f','L','a','C'}, {'I','D','3'}, {0xFF,0xE2}, {'O','g','g','S'},
        {'P','K',3,4}, {'A','T','&','T','F','O','R','M'}, {'R','a','r','!',0x1A,0x07}, {'7','z',0xBC,0xAF,0x27,0x1C},
        {0x1F,0x8B,0x08}, {'B','Z','h'}, {0xFD,'7','z','X','Z',0}, {0x1F,0x9D}};
    for (int i = 0; i < 400000; ++i) {
        std::vector<uint8_t> h = magics[pick(magics.size())];
        size_t len = pick(4) ? pick(80) : pick(520);
        while (h.size() < len) h.push_back(pick(3) ? pick(256) : "webmM4V qt AVI WAVEWEBPBOOKMOBIDJVUustarapplication/epub+zip"[pick(60)]);
        if (pick(4) == 0 && h.size() > 400) { h[188] = 0x47; h[376] = 0x47; }
        sniff(h);
    }
    printf("%ld inputs agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-filetypes-") as temp:
    temp = Path(temp)
    (temp / "OldFileTypes.h").write_text(header)
    (temp / "OldFileTypes.cpp").write_text(old)
    (temp / "main.cpp").write_text(harness)
    env = dict(os.environ)
    if shutil.which("localedef") and Path("/usr/share/i18n/locales/en_US").exists():
        locdir = temp / "locales"
        locdir.mkdir()
        env["LOCPATH"] = str(locdir)
        subprocess.run(["localedef", "--no-archive", "-i", "en_US", "-f", "ISO-8859-1", str(locdir / "en_US.ISO8859-1")], check=True)
        for sysloc in ("/usr/lib/locale/C.utf8", "/usr/lib/locale/C.UTF-8"):
            if Path(sysloc).exists():
                os.symlink(sysloc, locdir / "C.UTF-8")
                break
    binary = temp / "filetypes"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-w", f"-I{temp}", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "OldFileTypes.cpp"),
                    "-o", str(binary), *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
    subprocess.run([str(binary), str(HEADERS), str(temp), *TEXTS], check=True, env=env)
