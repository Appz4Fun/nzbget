// Included after the exact reference methods by streampatchparts_differential.py.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <random>
#include <string>
#include "nzbget_rs.h"

// Fair algorithm-equivalent C++ control. All allocations and materialization
// occur within the measured call, just as in the actual daemon and old caller.
static std::vector<int> Control(const StreamRangeList& donors, const StreamRangeList& holes, int margin)
{
    std::vector<int> out;
    if (donors.empty() || holes.empty() || margin < 0) return out;
    out.reserve(donors.size());
    size_t logarithm = 0;
    for (size_t n = donors.size(); n; n >>= 1) ++logarithm;
    bool ordered = donors.size() > 32 && holes.size() <= (donors.size() - 1) / (2 * logarithm);
    for (size_t i=1; ordered && i<donors.size(); ++i)
        ordered = donors[i-1].Offset <= donors[i].Offset && donors[i-1].End() <= donors[i].End();
    if (ordered) {
        std::vector<std::pair<size_t,size_t>> spans;
        spans.reserve(holes.size());
        for (auto h : holes) {
            size_t from = std::upper_bound(donors.begin(), donors.end(), h.Offset,
                [](int64 offset, auto d) { return offset < d.End(); }) - donors.begin();
            size_t to = std::lower_bound(donors.begin(), donors.end(), h.End(),
                [](auto d, int64 end) { return d.Offset < end; }) - donors.begin();
            if (from < to) spans.emplace_back(from > (size_t)margin ? from - margin : 0,
                std::min(to - 1 + margin, donors.size() - 1));
        }
        if (!std::is_sorted(spans.begin(), spans.end(), [](auto a, auto b) {return a.first < b.first;}))
            std::sort(spans.begin(), spans.end(), [](auto a, auto b) {return a.first < b.first;});
        size_t nextIndex = 0;
        for (auto span : spans) {
            for (size_t j = std::max(span.first, nextIndex); j <= span.second; ++j) out.push_back((int)j);
            nextIndex = std::max(nextIndex, span.second + 1);
        }
        return out;
    }
    std::vector<std::pair<int64, int64>> ends;
    bool indexed = holes.size() > 8 && donors.size() > 32;
    if (indexed) {
        ends.reserve(holes.size());
        for (auto h : holes) ends.emplace_back(h.Offset, h.End());
        if (!std::is_sorted(ends.begin(), ends.end(), [](auto a, auto b) { return a.first < b.first; }))
            std::sort(ends.begin(), ends.end(), [](auto a, auto b) { return a.first < b.first; });
        int64 maximum = std::numeric_limits<int64>::min();
        for (auto& h : ends) h.second = maximum = std::max(maximum, h.second);
    }
    size_t cursor = 0, nextIndex = 0;
    int64 previousEnd = std::numeric_limits<int64>::min();
    for (size_t i = 0; i < donors.size(); ++i) {
        bool hit;
        int64 end = donors[i].End();
        if (indexed) {
            if (end >= previousEnd) while (cursor < ends.size() && ends[cursor].first < end) ++cursor;
            else cursor = std::lower_bound(ends.begin(), ends.end(), end,
                [](auto h, int64 e) { return h.first < e; }) - ends.begin();
            previousEnd = end;
            hit = cursor && ends[cursor - 1].second > donors[i].Offset;
        } else hit = Old::IntersectsAny(donors[i], holes);
        if (hit) {
            size_t from = std::max(i > (size_t)margin ? i - margin : 0, nextIndex);
            size_t to = std::min(i + margin, donors.size() - 1);
            for (size_t j = from; j <= to; ++j) out.push_back((int)j);
            nextIndex = to + 1;
        }
    }
    return out;
}

static std::vector<int> Direct(const StreamRangeList& donors, const StreamRangeList& holes, int margin)
{
    std::vector<int> out(donors.size());
    out.resize(nzbget_rs_stream_patch_parts(donors.data(), donors.size(), holes.data(), holes.size(), margin, out.data()));
    return out;
}

static void Check(const StreamRangeList& donors, const StreamRangeList& holes, int margin)
{
    auto want = Old::SelectPatchParts(donors, holes, margin);
    auto actual = DupeStreamRepair::SelectPatchParts(donors, holes, margin);
    auto control = Control(donors, holes, margin);
    std::vector<int> direct(donors.size());
    direct.resize(nzbget_rs_stream_patch_parts(donors.data(), donors.size(), holes.data(), holes.size(), margin, direct.data()));
    if (want != actual || want != direct || want != control) {
        std::fprintf(stderr, "parity mismatch donors=%zu holes=%zu margin=%d sizes=%zu/%zu/%zu/%zu\n",
            donors.size(), holes.size(), margin, want.size(), actual.size(), direct.size(), control.size());
        std::exit(1);
    }
}

static void Parity()
{
    std::mt19937_64 rng(0x73656c656374);
    Check({}, {}, 2);
    Check({{0, 1}}, {}, 2);
    Check({{0,10},{10,10},{20,0},{20,10}}, {{19,2}}, 0);
    Check({{10,-2}}, {{7,4}}, 0);
    Check({{10,2}}, {{11,-2}}, 0);
    Check({{INT64_MIN,1},{INT64_MAX-2,2}}, {{INT64_MAX-1,1}}, 0);
    for (int round = 0; round < 100000; ++round) {
        StreamRangeList donors, holes;
        size_t n = rng() % 130, m = rng() % 100;
        for (size_t i = 0; i < n; ++i) donors.push_back({(int64)(rng()%1000)-500, (int64)(rng()%150)-50});
        for (size_t i = 0; i < m; ++i) holes.push_back({(int64)(rng()%1000)-500, (int64)(rng()%150)-50});
        if (round%5 == 0) std::sort(donors.begin(), donors.end(), [](auto a, auto b) {return a.Offset < b.Offset;});
        if (round%7 == 0) std::sort(holes.begin(), holes.end(), [](auto a, auto b) {return a.Offset < b.Offset;});
        Check(donors, holes, (int)(rng()%12)-3);
    }
    for (int step : {1, 10, 1000}) {
        StreamRangeList donors, holes;
        for (int i = 0; i < 20000; ++i) donors.push_back({(int64)i*700000, 700000});
        for (int i = 0; i < 20000; i += step) holes.push_back({(int64)i*700000+100, 20});
        Check(donors, holes, 2);
    }
    std::puts("PASS 100009 old/actual Rust/direct ABI/fair-control comparisons");
}

static volatile uint64_t sink = 0;
using Call = std::vector<int>(*)(const StreamRangeList&, const StreamRangeList&, int);
static double Time(Call call, const StreamRangeList& donors, const StreamRangeList& holes, int margin, int repeats)
{
    auto begin = std::chrono::steady_clock::now();
    for (int i = 0; i < repeats; ++i) {
        auto result = call(donors, holes, margin);
        uint64_t sum = result.size();
        for (int part : result) sum += part;
        sink = sink + sum;
    }
    return std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now()-begin).count()/repeats;
}

static void Bench()
{
    bool confirm = std::getenv("STREAMPATCH_CONFIRM") != nullptr;
    std::puts("fixture,sample,order,old_ns,rust_ns,control_ns,direct_ns,old_repeats,rust_repeats,control_repeats,direct_repeats");
    struct Fixture { const char* name; int n, step, mode, repeats; };
    for (auto f : {
        Fixture{"empty",0,1,0,100000}, {"tiny",8,4,0,30000}, {"small31",31,4,0,15000}, {"small32",32,4,0,15000}, {"small33",33,4,0,15000},
        {"small33-few-holes",33,16,0,15000}, {"small64",64,4,0,15000}, {"small64-few-holes",64,16,0,15000}, {"small128",128,4,0,10000}, {"small256",256,4,0,3000},
        {"one-hole",20000,20000,0,300}, {"sparse",20000,1000,0,150},
        {"dense",20000,10,0,3}, {"all",20000,1,0,1},
        {"shuffled",20000,1000,1,150}, {"no-holes",20000,1,2,300},
        {"no-hit",20000,1000,3,150}, {"negative-margin",20000,1000,4,150}
    }) {
        std::string name(f.name);
        if (confirm && name != "tiny" && name != "small33-few-holes" && name != "all") continue;
        StreamRangeList donors, holes;
        for (int i=0; i<f.n; ++i) donors.push_back({(int64)i*700000,700000});
        if (f.mode != 2) for (int i=0; i<f.n; i+=f.step) holes.push_back({(int64)i*700000+100,20});
        if (f.mode == 1) { std::mt19937 rng(42); std::shuffle(donors.begin(),donors.end(),rng); std::shuffle(holes.begin(),holes.end(),rng); }
        if (f.mode == 3) for (auto& h : holes) h.Offset += 1000000000000LL;
        int margin = f.mode == 4 ? -1 : 2;
        Check(donors, holes, margin);
        Call calls[] = {Old::SelectPatchParts, DupeStreamRepair::SelectPatchParts, Control, Direct};
        int repeats[4];
        for (int k=0; k<4; ++k) repeats[k] = confirm ? (name == "all" ? (k ? 1000 : 1) : f.repeats * 10) : f.repeats;
        for (int warm=0; warm<3; ++warm) for (int k=0; k<4; ++k) Time(calls[k],donors,holes,margin,repeats[k]);
        for (int sample=0; sample<(confirm ? 40 : 31); ++sample) {
            double times[4];
            for (int j=0; j<4; ++j) { int k = sample%2 ? 3-j : j; times[k]=Time(calls[k],donors,holes,margin,repeats[k]); }
            std::printf("%s,%d,%s,%.3f,%.3f,%.3f,%.3f,%d,%d,%d,%d\n", f.name,sample,sample%2?"DCRO":"ORCD",times[0],times[1],times[2],times[3],repeats[0],repeats[1],repeats[2],repeats[3]);
            std::fflush(stdout);
        }
    }
}
int main(int argc, char** argv) { if (argc>1 && std::string(argv[1])=="bench") Bench(); else Parity(); }
