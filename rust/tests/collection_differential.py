#!/usr/bin/env python3
"""Compare CollectionAnalyzer (rust/src/collection.rs) with the pre-port C++
on random download directories built on disk: AnalyzeDirectory (every field)
and BuildPlan (every action and flag) for random release names and ignore
lists, with existing files to collide with, and the name resolvers.

The pre-port code is compiled as OldCollectionAnalyzer, with independent
C++ FileTypes and Deobfuscation helpers (including the original regexes),
and linked with a built libnzbget.

Usage: collection_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "c46b4523"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "3000"

old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/CollectionAnalyzer.cpp"], cwd=ROOT, text=True)
old = old.replace('#include "CollectionAnalyzer.h"', '#include "OldCollectionAnalyzer.h"').replace(
    "namespace CollectionAnalyzer", "namespace OldCollectionAnalyzer")
header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/CollectionAnalyzer.h"], cwd=ROOT, text=True)
header = header.replace("namespace CollectionAnalyzer", "namespace OldCollectionAnalyzer").replace(
    "COLLECTION_ANALYZER_H", "OLD_COLLECTION_ANALYZER_H")

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = shlex.split((BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text())
libs = link[link.index("liblibnzbget.a"):]

harness = r'''
#include "nzbget.h"
#include "CollectionAnalyzer.h"
#include "OldCollectionAnalyzer.h"
#include <fstream>
#include <random>
#include <sstream>
#include <clocale>

namespace N = CollectionAnalyzer;
namespace O = OldCollectionAnalyzer;

template <class E> static std::string entry(const E& e) {
    return e.path.string() + "|" + e.filename + "|" + e.stem + "|" + e.ext + "|" + std::to_string(e.size);
}
template <class R> static std::string analysis(const R& r) {
    std::ostringstream s;
    s << entry(r.mainVideo) << "\n" << entry(r.sampleVideo) << "\n" << entry(r.mainBook) << "\n";
    for (auto& e : r.subtitles) s << "sub " << entry(e) << "\n";
    for (auto& e : r.nfos) s << "nfo " << entry(e) << "\n";
    for (auto& e : r.otherFiles) s << "other " << entry(e) << "\n";
    s << r.isAmbiguousCollection << r.isDiscStructure << r.hasAudio << r.CanRename();
    return s.str();
}
template <class P> static std::string plan(const P& p) {
    std::ostringstream s;
    for (auto& a : p.actions) s << a.srcPath.string() << " -> " << a.dstPath.string() << " (" << a.oldFilename << " -> " << a.newFilename << ")\n";
    s << p.isAmbiguousCollection << p.isDiscStructure << p.canRename << p.targetNameObfuscated << " [" << p.effectiveBaseName << "]";
    return s.str();
}

int main(int argc, char** argv) {
    std::setlocale(LC_CTYPE, "");
    std::mt19937 rng(17);
    auto pick = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); };
    const char* stems[] = {"Movie.2014.1080p", "a8f7s6d5f4g3h2j1k0l9", "5KzdcWdGVGUG83Q9jv8KXht4O2k57w", "sample", "movie-sample",
        "x.sample", "Show.S01E01", "Show.S01E02", "track01", "track02", "book", "abc", "nzb", "IDE", "e1", "VIDEO_TS"};
    const char* exts[] = {".mkv", ".MKV", ".mp4", ".avi", ".srt", ".en.srt", ".eng.sub", ".nfo", ".mp3", ".flac", ".epub",
        ".pdf", ".rar", ".par2", ".vob", ".ifo", ".cue", ".iso", ".jpg", ".txt", "", ".bin", ".mkv.1", ".duplicate1.mkv"};
    const char* targets[] = {"Movie.2014.1080p", "Show.S01E01.720p", "nzb", "", "abc", "a8f7s6d5f4g3h2j1k0l9", "Bad/Name:..",
        "Movie.2014.1080p.mkv", "  spaced  ", "Re.Release", "CON", ".hidden", "Movie\nTitle", "Movie.\xff", "abc\n", "abc\r", "Backup_12345S01-02", "ABCDEFGHIJK123", "abcdefghijkl123"};
    const char* ignores[] = {nullptr, ".nfo", ".srt,.sub", "*.mkv"};
    fs::path base = fs::temp_directory_path() / ("nzbget-collection-" + std::to_string(getpid()));
    long cases = 0;
    int rounds = atoi(argv[1]);
    for (int round = 0; round < rounds; ++round) {
        // Analyze accepts entries independent of the filesystem: include
        // empty fields, ties, zero sizes and unsigned overflow.
        std::vector<N::FileEntry> nf;
        std::vector<O::FileEntry> of;
        for (int k = pick(12); k > 0; --k) {
            const std::string stem = stems[pick(sizeof stems / sizeof *stems)];
            const std::string ext = exts[pick(sizeof exts / sizeof *exts)];
            const std::string name = pick(5) ? stem + ext : "";
            const uintmax_t sizes[] = {0, 1, 3, 4, UINT64_MAX, UINT64_MAX / 3, UINT64_MAX / 3 + 1};
            const uintmax_t size = sizes[pick(7)];
            nf.push_back({name, name, stem, ext, size});
            of.push_back({name, name, stem, ext, size});
        }
        if (analysis(N::Analyze(nf)) != analysis(O::Analyze(of))) {
            printf("MISMATCH Analyze round %d\n", round); return 1;
        }
        std::string raw;
        for (int k = pick(40); k > 0; --k) raw += char(pick(256));
        std::string tag = raw + ".";
        for (int k = pick(6); k > 0; --k) tag += char(pick(256));
        if (N::ResolveSubtitleName(raw, tag, ".srt") != O::ResolveSubtitleName(raw, tag, ".srt") ||
            N::ResolveTargetName(raw, tag) != O::ResolveTargetName(raw, tag) ||
            N::ResolveSampleName(raw, tag) != O::ResolveSampleName(raw, tag)) {
            printf("MISMATCH raw name resolver round %d\n", round); return 1;
        }
        cases += 4;
        fs::remove_all(base);
        fs::create_directories(base);
        int n = pick(7);
        for (int k = 0; k < n; ++k) {
            fs::path dir = base;
            if (pick(5) == 0) dir /= any_of_dirs(pick);
            fs::create_directories(dir);
            std::string name = std::string(stems[pick(sizeof stems / sizeof *stems)]) + exts[pick(sizeof exts / sizeof *exts)];
            if (name.empty()) continue;
            std::ofstream(dir / name) << std::string(pick(3) ? pick(20) * 100 : pick(3), 'x');
        }
        if (pick(4) == 0) std::ofstream(base / "Movie.2014.1080p.mkv") << "x";
        const fs::path walked = round % 2 ? fs::path(base.string() + "///") : base;
        std::string a = analysis(O::AnalyzeDirectory(walked)), b = analysis(N::AnalyzeDirectory(walked));
        if (a != b) { printf("MISMATCH AnalyzeDirectory round %d\n--- C++\n%s\n--- Rust\n%s\n", round, a.c_str(), b.c_str()); return 1; }
        for (int t = 0; t < 3; ++t) {
            const char* target = targets[pick(sizeof targets / sizeof *targets)];
            const char* ignore = ignores[pick(4)];
            std::string p = plan(O::BuildPlan(walked, target, ignore)), q = plan(N::BuildPlan(walked, target, ignore));
            if (p != q) { printf("MISMATCH BuildPlan round %d target [%s]\n--- C++\n%s\n--- Rust\n%s\n", round, target, p.c_str(), q.c_str()); return 1; }
            ++cases;
        }
        std::string s1 = stems[pick(sizeof stems / sizeof *stems)], s2 = std::string(stems[pick(sizeof stems / sizeof *stems)]) + exts[pick(24)];
        if (O::ResolveTargetName(s1, s2) != N::ResolveTargetName(s1, s2)) { printf("MISMATCH ResolveTargetName\n"); return 1; }
        if (O::ResolveSubtitleName(s1, s2, ".srt") != N::ResolveSubtitleName(s1, s2, ".srt")) { printf("MISMATCH ResolveSubtitleName [%s]\n", s2.c_str()); return 1; }
        if (O::ResolveSampleName(s1, ".mkv") != N::ResolveSampleName(s1, ".mkv")) { printf("MISMATCH ResolveSampleName\n"); return 1; }
        ++cases;
    }
    fs::remove_all(base);
    printf("%ld cases agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
harness = harness.replace("dir /= any_of_dirs(pick);", 'dir /= std::string[]{"sub", "BDMV", "@eaDir", "CD1", "Sample", ".AppleDouble"}[pick(6)];')
harness = harness.replace('std::string[]{"sub", "BDMV", "@eaDir", "CD1", "Sample", ".AppleDouble"}[pick(6)]',
                          'std::vector<std::string>{"sub", "BDMV", "@eaDir", "CD1", "Sample", ".AppleDouble"}[pick(6)]')
with tempfile.TemporaryDirectory(prefix="nzbget-collection-") as temp:
    temp = Path(temp)
    (temp / "OldCollectionAnalyzer.h").write_text(header)
    # Do not let the reference call the same Rust classification/regex
    # helpers as the implementation under test.
    legacy = "#undef NZBGET_USE_RUST\n#define FileTypes OldFileTypes\n#define Deobfuscation OldDeobfuscation\n"
    (temp / "OldCollectionAnalyzer.cpp").write_text(legacy + old)
    helper_sources = []
    for relative in ("daemon/util/FileTypes.cpp", "daemon/queue/Deobfuscation.cpp"):
        source = temp / Path(relative).name
        source.write_text(legacy + (ROOT / relative).read_text())
        helper_sources.append(str(source))
    (temp / "main.cpp").write_text(harness)
    binary = temp / "collection"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-w", f"-I{temp}", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "OldCollectionAnalyzer.cpp"), *helper_sources,
                    "-o", str(binary), *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
    subprocess.run([str(binary), ROUNDS], check=True)
