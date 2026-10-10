#!/usr/bin/env python3
"""Compare FeedFilter (rust/src/feedfilter.rs) with the pre-port C++ on random
filters and feed items: match status and rule, and every option a rule sets
(category, priority, pause, dupe key, score and mode).

The pre-port FeedFilter is compiled as OldFeedFilter and linked with a built
libnzbget (the Rust one), so both share FeedItemInfo, WildMask and RegEx.

Usage: feedfilter_differential.py [BUILD_DIR]  (default: build; configure and
build it first). Run at idle priority. Uses the environment's locale by
default; FEEDFILTER_COMPILE_LOCALE and FEEDFILTER_MATCH_LOCALE can override
the locale at construction and matching independently (with LOCPATH for
privately generated locales). Also compares helper callback order.
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
#include <clocale>
#include <limits>
#include <random>
#include <string>
#include <vector>

// Debug's legacy matcher pulls in Log.cpp. The application normally owns
// these globals; a null logger makes its debug calls harmless in this harness.
class Log;
class Options;
Log* g_Log = nullptr;
Options* g_Options = nullptr;

static std::mt19937 rng(20261010);
static int pick(int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); }
template <class T, size_t N> static const T& any(const T (&a)[N]) { return a[pick(N)]; }

static const char* words[] = {"game", "Game", "of", "clowns", "S02E06", "s02e*", "1080p", "720p", "HDTV", "WEB-DL",
    "x264", "*am*", "gam*", "game.of?clowns", "S##E##", "*", "?", "#", "-group", "kings", "\xc3\xa9t\xc3\xa9", "\xe9t\xe9", "IDE",
    "", "\t", "\r", "0", "-0", ".", "--1", "1.5", "9223372036854775808", "99999999999999999999999999999999999999999"};
static const char* fields[] = {"", "title:", "filename:", "category:", "url:", "link:", "size:", "age:", "rageid:",
    "tvdbid:", "imdbid:", "season:", "episode:", "priority:", "dupekey:", "dupescore:", "dupestatus:", "description:",
    "attr-genre:", "attr-missing:", "TITLE:", "bogus:", ":", "tvmazeid:", "SIZE:", "PRIORITY:", "attr-:"};
static const char* comps[] = {"", "", "", "@", "$", "=", "<", "<=", ">", ">=", "=1.5", "<4GB", ">600MB", "<10", ">=1h", "<2d", "<x"};
static const char* regexes[] = {"game.*\\.s02e[0-9]*\\..*", ".+S([0-9]{1,2})E([0-9]{1,2})", "(cl)(own)s", "[", "^Game", "x26([45])"};
static const char* options[] = {"category:my series", "c:TV-${1}", "pause:yes", "p:n", "p:maybe", "priority:100", "r:-5",
    "r:abc", "pr+:10", "s:1000", "ds+:-50", "k:1080p", "k:series=GOT-${1}-${2}", "dk+:-x${season}E${episode}", "m:force",
    "dm:all", "dupemode:bogus", "rageid:123", "tvdbid:77", "tvmazeid:9", "series:Show", "paused", "unpaused", "100",
    "my category", "cat : spaced", ":x", "k:${}", "k:${3", "c:${season}", "c:${episode}", "c:", "k:",
    "c:${1}${2}${3}", "c:${100}", "c:${0}", "c:${1x}", "c:${episode}-${season}", "priority:", "ds:", "r:+5junk",
    "c:${EPISODE}", "c:${SEASON}", "PRIORITY:6", "RAGEID:7", "TVDBID:8", "SERIES:Upper", "PAUSE:YES"};
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
    // Valid terms with longer, possibly malformed boolean expressions. Uniform
    // random fields/operators otherwise invalidate most rules at compile time.
    if (pick(5) == 0) {
        static const char* terms[] = {"**", "missing", "-missing", "|", "(", ")", "-(", "+)",
            "priority:>=0", "season:>=0", "episode:>=0", "dupestatus:**", "attr-genre:**"};
        std::string r = any(commands);
        for (int n = pick(30) + 1; n; --n) r += std::string(" ") + any(terms);
        return r;
    }
    // Exercise valid option rules frequently; arbitrary terms otherwise make
    // most randomly generated option/reference rules invalid or nonmatching.
    if (pick(4) == 0) {
        std::string r = pick(2) ? "A(" : "O(";
        int n = pick(6) + 1;
        for (int i = 0; i < n; ++i) r += std::string(i ? "," : "") + any(options);
        static const char* patterns[] = {"**", "*.*", "$^(.*)$", "$(.*)(.*)", "S##E##", "** | dupestatus:**", "-missing | **"};
        return r + "): " + any(patterns);
    }
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

// Perturb otherwise structured filters, including control and non-UTF-8
// bytes. This reaches parser boundaries the token lists cannot generate.
static void mutate(std::string& filter) {
    static const unsigned char bytes[] = " :%(),|+-@$<>=*?#{}012.Ii\t\r\n\v\f\x80\xdd\xfd\xff";
    for (int n = pick(4) + 1; n; --n) {
        size_t at = pick(filter.size() + 1);
        if (at < filter.size() && pick(3) == 0) filter.erase(at, 1);
        else filter.insert(at, 1, bytes[pick(sizeof(bytes) - 1)]);
    }
}

// what FeedCoordinator gives the items: title/episode regexes and a dupe status
struct Helper : FeedFilterHelper {
    std::unique_ptr<RegEx> regExes[2];
    std::vector<std::string> calls;
    std::unique_ptr<RegEx>& GetRegEx(int id) override {
        calls.push_back("regex " + std::to_string(id));
        return regExes[id];
    }
    void CalcDupeStatus(const char* title, const char* dupeKey, char* buf, int len) override {
        calls.push_back(std::string("status ") + title + " key " + dupeKey);
        snprintf(buf, len, "%s", title && strstr(title, "Kings") ? "SUCCESS" : (dupeKey && *dupeKey ? "QUEUED" : ""));
    }
};
static Helper helperA, helperB;

static void setup(FeedItemInfo& item, int seed) {
    std::mt19937 r(seed);
    auto p = [&](int n) { return std::uniform_int_distribution<int>(0, n - 1)(r); };
    const char* titles[] = {"Game.of.Clowns.S02E06.REAL.1080p.HDTV.X264-Group.WEB-DL", "Kings.S01E01.720p.x265",
        "\xc3\xa9t\xc3\xa9 2020", "", "Show Name - 1x02 - Title [1080p]", "\tgame\r", "1.5", "nan", "inf", "-inf", "\xdd" "DE \xfd" "de IDE",
        "${1}", "${season}", "${episode}", "${2}${1}", "1,5", "-9223372036854775808", "9223372036854775808", "\xff\xfe\x80"};
    if (p(6)) item.SetTitle(titles[p(sizeof(titles) / sizeof(*titles))]);
    // Cross the short-string and capture-count boundaries independently of
    // regex's fixed capture buffer. Wildcard captures have no 100-entry cap.
    if (p(16) == 0) {
        std::string title;
        for (int n = p(150) + 90; n; --n) title += "a.";
        item.SetTitle(title.c_str());
    }
    if (p(2)) item.SetFilename(titles[p(sizeof(titles) / sizeof(*titles))]);
    if (p(2)) item.SetCategory(p(2) ? "TV > HD" : "Movies");
    item.SetSize((int64)p(4000) * 1024 * 1024);
    // ages away from whole seconds of the thresholds
    item.SetTime(Util::CurrentTime() - p(90) * 3600 - 1800);
    if (p(16) == 0) item.SetTime(std::numeric_limits<time_t>::min());
    item.SetRageId(p(3) ? 123456 : 0);
    item.SetTvdbId(p(1000));
    item.SetTvmazeId(p(1000));
    item.SetImdbId(p(1000));
    item.SetUrl(p(2) ? "https://example.test/file.nzb" : "");
    item.SetDescription(p(2) ? "Some description" : "1.5");
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
    const char* compileLocale = getenv("FEEDFILTER_COMPILE_LOCALE");
    const char* matchLocale = getenv("FEEDFILTER_MATCH_LOCALE");
    auto locale = [](const char* name) {
        if (!setlocale(LC_ALL, name ? name : "")) {
            fprintf(stderr, "Unavailable locale: %s\n", name ? name : "environment");
            exit(2);
        }
    };
    std::vector<std::string> regressions = {
        "", "%", "%%A:**%", "A(c:${1}): $(a*)", "A(c:${1}): $^(.*)$",
        "A(c:${1},legacy): **", "A(c:${1},c:literal): **", "A(c:${season},k:${episode},dk+:${1}): **",
        "O(r:4,pr+:3,ds:6,s+:2,k:x,dk+:y,m:all): **%A: priority:=7 dupescore:=8 dupekey:x-y",
        "O(k:new): **%Q: dupestatus:QUEUED%A: **",
        "A(r:2147483647,r+:1,ds:-2147483648,ds+:-1): **",
        "TITLE:**", "-TITLE:**", "PRIORITY:=0", "SIZE:>=0", "title:**",
        "A(c:${1}-${2}-${3}): $(a*)(.*)", "A(c:${1}-${2}): $(x)?(.*)",
        "A(c:${1}-${2}): ** | $^(.*)$", "A(c:${1},k:${2},dk+:${3}): -missing ** ** **",
        "A(c:${1}): $", "A(c:${1}): @", "A(c:${1}): *?*?*",
        "A(c:${season},k:${episode}): season:>=0 episode:>=0 dupestatus:**",
        "A(c:${1},legacy:${episode}): **", "A(, \t ,c: x\t\r\n,): **",
        "A(c:${-2147483648}): **", "A(c:${4294967297}): **", "A(c:${+1}): **",
        "A(c:${1}): title:=9223372036854775808", "A: title:=-9223372036854775808",
        "A: title:=1.5", "A: title:=", "A: size:>=.5KB", "A: age:>=.001h",
        "A: ** \t **", "A: **\t**", "A: ** \r\n **", "A: ( ** | missing ) **",
        "A(c:${1}-${2}): *.*", "A(c:${1}): @\t", "A(c:${1}): @\v", "age:<0", "age:>=0",
        "O(c:first,k:old): **%O(c:${1},dk+:${1}): **%Q: dupestatus:**%A: **"
    };
    // BString<100>'s variable truncation, RegEx's 100-entry capture buffer,
    // and the 100-substitution limit are independent boundaries.
    for (int n : {98, 99, 100, 101, 120}) {
        regressions.push_back("A(c:${1" + std::string(n, 'x') + "}): **");
        std::string regex = "A(c:${1}-${98}-${99}-${100}): $";
        std::string substitutions = "A(c:";
        for (int j = 0; j < n; ++j) { regex += "()"; substitutions += "${season}"; }
        regressions.push_back(regex);
        regressions.push_back(substitutions + "): **");
        std::string wild = "A(c:${1}-${98}-${99}-${100}-${101}-${120}): *";
        for (int j = 0; j < n; ++j) wild += ".*";
        regressions.push_back(wild);
    }
    long cases = 0;
    // Cover every non-NUL byte pair, including locale-specific case pairs,
    // control characters, separators and invalid multibyte text. The random
    // vocabulary above only samples a handful of these. Reuse each filter
    // across all titles to check captures are refreshed between matches.
    for (int pattern = 1; pattern < 256; ++pattern) {
        for (bool substring : {false, true}) {
            std::string filter = "A(c:${1},k:${2}): @";
            if (substring) filter += '*';
            filter += char(pattern);
            if (substring) filter += '*';
            locale(compileLocale);
            OldFeedFilter oldFilter(filter.c_str());
            FeedFilter newFilter(filter.c_str());
            locale(matchLocale ? matchLocale : compileLocale);
            for (int title = 1; title < 256; ++title) {
                std::string text(1, char(title));
                FeedItemInfo a, b;
                a.SetTitle(text.c_str());
                b.SetTitle(text.c_str());
                oldFilter.Match(a);
                newFilter.Match(b);
                if (state(a) != state(b)) {
                    printf("MISMATCH byte pattern %02x title %02x substring %d\n  C++: %s\n  Rust: %s\n",
                        pattern, title, substring, state(a).c_str(), state(b).c_str());
                    return 1;
                }
                ++cases;
            }
        }
    }
    int filters = argc > 1 ? atoi(argv[1]) : 20000;
    for (int f = -int(regressions.size()); f < filters; ++f) {
        std::string filter;
        if (f < 0) filter = regressions[-f - 1];
        else {
            int n = pick(4) + 1;
            for (int i = 0; i < n; ++i) filter += std::string(i ? "%" : "") + rule();
            if (pick(4) == 0) mutate(filter);
        }
        locale(compileLocale);
        OldFeedFilter oldFilter(filter.c_str());
        FeedFilter newFilter(filter.c_str());
        locale(matchLocale ? matchLocale : compileLocale);
        // the same filters on several items: state carries over between matches
        for (int k = 0; k < 8; ++k) {
            int seed = pick(1 << 30);
            FeedItemInfo a, b;
            setup(a, seed);
            setup(b, seed);
            a.SetFeedFilterHelper(&helperA);
            b.SetFeedFilterHelper(&helperB);
            helperA.calls.clear();
            helperB.calls.clear();
            oldFilter.Match(a);
            newFilter.Match(b);
            if (state(a) != state(b) || helperA.calls != helperB.calls) {
                printf("MISMATCH filter [%s] item %d\n  C++:  %s\n  Rust: %s\n", filter.c_str(), seed, state(a).c_str(), state(b).c_str());
                for (auto& c : helperA.calls) printf("  C++ callback: %s\n", c.c_str());
                for (auto& c : helperB.calls) printf("  Rust callback: %s\n", c.c_str());
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
