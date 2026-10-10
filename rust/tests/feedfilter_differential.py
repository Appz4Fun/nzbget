#!/usr/bin/env python3
"""Compare FeedFilter (rust/src/feedfilter.rs) with the pre-port C++ on random
filters and feed items: match status and rule, and every option a rule sets
(category, priority, pause, dupe key, score and mode).

The pre-port FeedFilter is compiled as OldFeedFilter and linked with a built
libnzbget (the Rust one), so both share FeedItemInfo, WildMask and RegEx.

Usage: feedfilter_differential.py [BUILD_DIR]  (default: build; configure and
build it first). Run at idle priority.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "75817c42"
BUILD = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build").resolve()


def old(path):
    text = subprocess.check_output(["git", "show", f"{REFERENCE}:{path}"], cwd=ROOT, text=True)
    text = re.sub(r"\bFeedFilter\b", "OldFeedFilter", text)
    return text.replace("FEEDFILTER_H", "OLDFEEDFILTER_H").replace('"FeedFilter.h"', '"OldFeedFilter.h"')


flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
cxx_flags = re.search(r"^CXX_FLAGS = (.*)$", flags, re.M).group(1)
defines = re.search(r"^CXX_DEFINES = (.*)$", flags, re.M).group(1)
includes = re.search(r"^CXX_INCLUDES = (.*)$", flags, re.M).group(1)
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = [a for a in link[link.index("liblibnzbget.a"):]]

harness = r'''
#include "nzbget.h"
#include "FeedFilter.h"
#include "OldFeedFilter.h"
#include <chrono>
#include <random>
#include <string>
#include <vector>

static std::mt19937 rng(20261010);
static int pick(int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); }
template <class T, size_t N> static const T& any(const T (&a)[N]) { return a[pick(N)]; }

static const char* words[] = {"game", "Game", "of", "clowns", "S02E06", "s02e*", "1080p", "720p", "HDTV", "WEB-DL",
    "x264", "*am*", "gam*", "game.of?clowns", "S##E##", "*", "?", "#", "-group", "kings", "\xc3\xa9t\xc3\xa9", "\xe9t\xe9", "IDE"};
static const char* fields[] = {"", "title:", "filename:", "category:", "url:", "link:", "size:", "age:", "rageid:",
    "tvdbid:", "imdbid:", "season:", "episode:", "priority:", "dupekey:", "dupescore:", "dupestatus:", "description:",
    "attr-genre:", "attr-missing:", "TITLE:", "bogus:", ":"};
static const char* comps[] = {"", "", "", "@", "$", "=", "<", "<=", ">", ">=", "=1.5", "<4GB", ">600MB", "<10", ">=1h", "<2d", "<x"};
static const char* regexes[] = {"game.*\\.s02e[0-9]*\\..*", ".+S([0-9]{1,2})E([0-9]{1,2})", "(cl)(own)s", "[", "^Game", "x26([45])"};
static const char* options[] = {"category:my series", "c:TV-${1}", "pause:yes", "p:n", "p:maybe", "priority:100", "r:-5",
    "r:abc", "pr+:10", "s:1000", "ds+:-50", "k:1080p", "k:series=GOT-${1}-${2}", "dk+:-x${season}E${episode}", "m:force",
    "dm:all", "dupemode:bogus", "rageid:123", "tvdbid:77", "tvmazeid:9", "series:Show", "paused", "unpaused", "100",
    "my category", "cat : spaced", ":x", "k:${}", "k:${3", "c:${season}"};
static const char* commands[] = {"", "", "A:", "Accept:", "R:", "Reject:", "Q:", "Require:", "#", "a:", "O:"};

static std::string term() {
    std::string t;
    int k = pick(10);
    static const char* ops[] = {"(", ")", "|"};
    if (k == 0) return any(ops);
    if (k == 1) t += "-";
    if (k == 2) t += "+";
    std::string f = any(fields);
    t += f;
    std::string c = any(comps);
    if (c == "$" || (k == 3 && f.empty())) return t + "$" + any(regexes);
    t += c;
    if (c.size() <= 2) t += pick(3) ? any(words) : std::to_string(pick(3000) - 100);
    return t;
}

static std::string rule() {
    std::string cmd = any(commands);
    std::string r = cmd;
    if ((cmd == "" || cmd == "A:" || cmd == "Accept:") && pick(2)) {
        r = pick(2) ? "A(" : (pick(2) ? "Options(" : "O(");
        int n = pick(4) + 1;
        for (int i = 0; i < n; ++i) r += std::string(i ? (pick(2) ? "," : ", ") : "") + any(options);
        r += pick(5) ? "):" : ")";
    }
    int n = pick(5);
    for (int i = 0; i < n; ++i) r += std::string(pick(4) ? " " : "  ") + term();
    if (pick(8) == 0) r = "  " + r + " ";
    return r;
}

// what FeedCoordinator gives the items: title/episode regexes and a dupe status
struct Helper : FeedFilterHelper {
    std::unique_ptr<RegEx> regExes[2];
    std::unique_ptr<RegEx>& GetRegEx(int id) override { return regExes[id]; }
    void CalcDupeStatus(const char* title, const char* dupeKey, char* buf, int len) override {
        snprintf(buf, len, "%s", title && strstr(title, "Kings") ? "SUCCESS" : (dupeKey && *dupeKey ? "QUEUED" : ""));
    }
};
static Helper helperA, helperB;

static void setup(FeedItemInfo& item, int seed) {
    std::mt19937 r(seed);
    auto p = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(r); };
    const char* titles[] = {"Game.of.Clowns.S02E06.REAL.1080p.HDTV.X264-Group.WEB-DL", "Kings.S01E01.720p.x265",
        "\xc3\xa9t\xc3\xa9 2020", "", "Show Name - 1x02 - Title [1080p]"};
    if (p(6)) item.SetTitle(titles[p(5)]);
    if (p(2)) item.SetFilename(titles[p(5)]);
    if (p(2)) item.SetCategory(p(2) ? "TV > HD" : "Movies");
    item.SetSize((int64)p(4000) * 1024 * 1024);
    // ages away from whole seconds of the thresholds
    item.SetTime(Util::CurrentTime() - p(90) * 3600 - 1800);
    item.SetRageId(p(3) ? 123456 : 0);
    item.SetTvdbId(p(1000));
    if (p(2)) { item.SetSeason("02"); item.SetEpisode("06"); }
    if (p(2)) item.SetDupeKey("old-key");
    item.SetDupeScore(p(200) - 100);
    item.SetPriority(p(5) - 2);
    if (p(2)) item.GetAttributes()->emplace_back("genre", p(2) ? "Drama" : "Comedy");
}

static std::string state(FeedItemInfo& i) {
    struct { std::string operator()(const char* v) const { return v ? std::string("[") + v + "]" : std::string("(null)"); }
             std::string operator()(const std::string& v) const { return "[" + v + "]"; } } s;
    return std::to_string(i.GetMatchStatus()) + " rule " + std::to_string(i.GetMatchRule()) + " cat " + s(i.GetAddCategory()) +
        " pr " + std::to_string(i.GetPriority()) + " pause " + std::to_string(i.GetPauseNzb()) + " dk " + s(i.GetDupeKey()) +
        " ds " + std::to_string(i.GetDupeScore()) + " dm " + std::to_string(i.GetDupeMode());
}

int main(int argc, char** argv) {
    long cases = 0;
    int filters = argc > 1 ? atoi(argv[1]) : 20000;
    for (int f = 0; f < filters; ++f) {
        std::string filter;
        int n = pick(4) + 1;
        for (int i = 0; i < n; ++i) filter += std::string(i ? "%" : "") + rule();
        OldFeedFilter oldFilter(filter.c_str());
        FeedFilter newFilter(filter.c_str());
        // the same filters on several items: state carries over between matches
        for (int k = 0; k < 8; ++k) {
            int seed = pick(1 << 30);
            FeedItemInfo a, b;
            setup(a, seed);
            setup(b, seed);
            a.SetFeedFilterHelper(&helperA);
            b.SetFeedFilterHelper(&helperB);
            oldFilter.Match(a);
            newFilter.Match(b);
            if (state(a) != state(b)) {
                printf("MISMATCH filter [%s] item %d\n  C++:  %s\n  Rust: %s\n", filter.c_str(), seed, state(a).c_str(), state(b).c_str());
                return 1;
            }
            ++cases;
        }
    }
    printf("%ld matches agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
    // timing: the same filters and items through each
    std::vector<std::string> fs;
    for (int f = 0; f < 3000; ++f) fs.push_back(rule() + "%" + rule());
    for (int side = 0; side < 2; ++side) {
        auto t = std::chrono::steady_clock::now();
        for (auto& f : fs) {
            if (side == 0) { OldFeedFilter x(f.c_str()); for (int k = 0; k < 20; ++k) { FeedItemInfo i; setup(i, k); i.SetFeedFilterHelper(&helperA); x.Match(i); } }
            else { FeedFilter x(f.c_str()); for (int k = 0; k < 20; ++k) { FeedItemInfo i; setup(i, k); i.SetFeedFilterHelper(&helperB); x.Match(i); } }
        }
        printf("%s: %.0f ms\n", side ? "Rust" : "C++ ", std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count());
    }
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-feedfilter-") as temp:
    temp = Path(temp)
    (temp / "OldFeedFilter.h").write_text(old("daemon/feed/FeedFilter.h"))
    (temp / "OldFeedFilter.cpp").write_text(old("daemon/feed/FeedFilter.cpp"))
    (temp / "main.cpp").write_text(harness)
    binary = temp / "feedfilter"
    cmd = [*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(cxx_flags), *shlex.split(defines), "-w",
           f"-I{temp}", *shlex.split(includes), str(temp / "main.cpp"), str(temp / "OldFeedFilter.cpp"),
           "-o", str(binary), *[str(BUILD / l) if not l.startswith("-") and not l.startswith("/") else l for l in libs]]
    subprocess.run(cmd, check=True, cwd=BUILD)
    run = ["gdb", "-batch", "-ex", "run", "-ex", "bt 15", "--args"] if os.environ.get("GDB") else []
    subprocess.run([*run, str(binary), *sys.argv[2:]], check=True)
