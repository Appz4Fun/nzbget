// Full production C++ caller, exact old source, and an optimized C++ geometry control.
#include "nzbget.h"
#include "DupeStreamRepair.h"
#include "nzbget_rs.h"
#include <chrono>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <random>
#include <limits>
#include "streamcompare_reference.inc"

static bool counting = false;
static size_t allocations = 0, allocatedBytes = 0;
extern "C" void* __real_malloc(size_t);
extern "C" void* __real_calloc(size_t, size_t);
extern "C" void* __real_realloc(void*, size_t);
extern "C" void __real_free(void*);
static void record(size_t n) { if (counting) { ++allocations; allocatedBytes += n; } }
extern "C" void* __wrap_malloc(size_t n) { record(n); return __real_malloc(n); }
extern "C" void* __wrap_calloc(size_t n, size_t s) { record(n*s); return __real_calloc(n,s); }
extern "C" void* __wrap_realloc(void* p, size_t n) { record(n); return __real_realloc(p,n); }
extern "C" void __wrap_free(void* p) { __real_free(p); }
void* operator new(size_t n) { record(n); if (auto p=__real_malloc(n)) return p; throw std::bad_alloc(); }
void* operator new[](size_t n) { return ::operator new(n); }
void operator delete(void* p) noexcept { __real_free(p); }
void operator delete[](void* p) noexcept { __real_free(p); }
void operator delete(void* p, size_t) noexcept { __real_free(p); }
void operator delete[](void* p, size_t) noexcept { __real_free(p); }

using Fn = int64(*)(int64, const StreamRangeList&, const StreamRangeList&, const std::vector<int>&);
__attribute__((noinline)) static int64 Original(int64 d, const StreamRangeList& h, const StreamRangeList& r, const std::vector<int>& p)
{ return Reference::RequiredCompareFloor(d,h,r,p); }
__attribute__((noinline)) static int64 Rust(int64 d, const StreamRangeList& h, const StreamRangeList& r, const std::vector<int>& p)
{ return DupeStreamRepair::RequiredCompareFloor(d,h,r,p); }

static int64 WrappedEnd(const StreamRange& range) {
    return std::bit_cast<int64>((uint64_t)range.Offset + (uint64_t)range.Size);
}

// Same fast-path geometry and early no-probe return as Rust. No deliberately
// weak reference: borrowed sorted inputs, lower_bound, one union allocation only
// for unordered/overlapping positive holes, and original reversed-range parity.
__attribute__((noinline)) static int64 Control(int64 decoded, const StreamRangeList& holes,
    const StreamRangeList& donors, const std::vector<int>& probes)
{
    if (probes.empty()) return Reference::BaseCompareFloor(decoded-Reference::TotalSize(holes));
    if (holes.empty()) {
        int64 total=0;
        for(int i:probes) { if((unsigned)i>=donors.size())std::abort(); total+=donors[i].Size; }
        auto base=Reference::BaseCompareFloor(decoded);
        return total>=64 ? std::min(base,total) : base;
    }
    int64 sum=0, previous=std::numeric_limits<int64>::min();
    bool ordered=true, positive=true;
    for (const auto& h: holes) {
        sum+=h.Size;
        int64 end=WrappedEnd(h);
        positive &= h.Size>=0;
        positive &= end>=h.Offset;
        ordered &= h.Offset>=previous;
        previous=end;
    }
    int64 base=Reference::BaseCompareFloor(decoded-sum);
    for (int i: probes) {
        if (i<0 || (size_t)i>=donors.size())std::abort();
        positive &= donors[i].Size>=0;
        positive &= WrappedEnd(donors[i])>=donors[i].Offset;
    }
    if (!positive) {
        int64 total=0;
        for(int i:probes) {
            StreamRangeList present={donors[i]}, remaining;
            for(const auto& hole:holes) {
                remaining.clear();
                for(const auto& range:present) {
                    if (!Reference::RangesIntersect(range,hole)) remaining.push_back(range);
                    else {
                        if(range.Offset<hole.Offset)remaining.push_back({range.Offset,hole.Offset-range.Offset});
                        if(hole.End()<range.End())remaining.push_back({hole.End(),range.End()-hole.End()});
                    }
                }
                present.swap(remaining);
            }
            total+=Reference::TotalSize(present);
        }
        return total>=64 ? std::min(base,total) : base;
    }
    StreamRangeList merged;
    const StreamRangeList* ranges=&holes;
    if (!ordered) {
        merged=holes;
        std::sort(merged.begin(),merged.end(),[](auto& a,auto& b){return a.Offset<b.Offset;});
        size_t count=0;
        for (size_t i=0;i<merged.size();++i) {
            auto h=merged[i];
            if (count && h.Offset<=merged[count-1].End()) {
                auto& last=merged[count-1]; last.Size=std::max(last.End(),h.End())-last.Offset;
            } else merged[count++]=h;
        }
        merged.resize(count); ranges=&merged;
    }
    int64 total=0;
    for (int i: probes) {
        const auto& d=donors[i]; int64 bytes=d.Size;
        auto start=ranges->size()<=8 ? ranges->begin() : std::lower_bound(ranges->begin(),ranges->end(),d.Offset,
            [](const auto& h,int64 off){return h.End()<=off;});
        for (auto h=start;h!=ranges->end() && h->Offset<d.End();++h) {
            if(h->End()<=d.Offset)continue;
            bytes-=std::max<int64>(0,std::min(d.End(),h->End())-std::max(d.Offset,h->Offset));
        }
        total+=bytes;
    }
    return total>=64 ? std::min(base,total) : base;
}

struct Fixture { const char* name; int64 decoded; StreamRangeList holes, donors; std::vector<int> probes; };
static void Check(const Fixture& f) {
    auto old=Original(f.decoded,f.holes,f.donors,f.probes);
    auto rs=Rust(f.decoded,f.holes,f.donors,f.probes);
    auto cpp=Control(f.decoded,f.holes,f.donors,f.probes);
    if (old!=rs || old!=cpp) {
        std::fprintf(stderr,"Mismatch %s old=%lld rust=%lld cpp=%lld decoded=%lld\n",f.name,(long long)old,(long long)rs,(long long)cpp,(long long)f.decoded);
        for(auto h:f.holes) std::fprintf(stderr,"hole %lld %lld\n",(long long)h.Offset,(long long)h.Size);
        for(auto d:f.donors) std::fprintf(stderr,"donor %lld %lld\n",(long long)d.Offset,(long long)d.Size);
        std::abort();
    }
}
static std::vector<Fixture> Fixtures() {
    std::vector<Fixture> fs={
        {"empty",100000,{}, {},{}},
        {"no_probes",100000,{{0,100},{200,100}},{{0,1000}},{}},
        {"small_clear",100000,{},{{0,800000},{800000,800000}},{0,1}},
        {"small_sparse",100000,{{100,20},{400,30}},{{0,800000},{800000,800000}},{0,1}},
        {"small_dense",100000,{{0,200},{210,100},{400,600}},{{0,500},{500,500}},{0,1}},
        {"small_unordered",100000,{{400,600},{210,100},{0,200}},{{0,500},{500,500}},{0,1}},
        {"reversed",100000,{{200,-100},{250,0}},{{0,300},{100,-20}},{0,1,0}},
    };
    for (bool dense: {false,true}) {
        Fixture f{dense?"large_dense":"large_sparse", 1600000000,{}, {}, {100,1900}};
        for (int i=0;i<2000;++i) f.donors.push_back({i*800000LL,800000});
        for (int i=0;i<4096;++i) f.holes.push_back({i*390625LL,dense?390000LL:1000LL});
        fs.push_back(f);
        if (!dense) { std::reverse(f.holes.begin(),f.holes.end()); f.name="large_unordered";fs.push_back(f); }
    }
    return fs;
}
static volatile int64 sink=0;
static double Time(Fn fn,const Fixture& f,size_t iterations) {
    auto start=std::chrono::steady_clock::now(); int64 x=0;
    for(size_t i=0;i<iterations;++i) x^=fn(f.decoded,f.holes,f.donors,f.probes);
    sink=x;
    return std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/iterations;
}
int main(int argc,char** argv) {
    auto fs=Fixtures();for(const auto& f:fs)Check(f);
    if(argc>1 && std::string(argv[1])=="bench") {
        std::puts("fixture,sample,position,implementation,iterations,ns,allocations,allocated_bytes");
        Fn funcs[]={Reference::RequiredCompareFloor,Control,DupeStreamRepair::RequiredCompareFloor};const char* names[]={"original","control","rust"};
        for(const auto& f:fs) {
            size_t counts[3]={1,1,1};
            for(int i=0;i<3;++i)
                while(Time(funcs[i],f,counts[i])*counts[i]<5000000 && counts[i]<(1u<<26))counts[i]*=2;
            for(int sample=0;sample<31;++sample) {
                for(int pos=0;pos<3;++pos) {
                    int index=sample%2==0 ? (pos+sample/2)%3 : (2-pos+sample/2)%3;
                    double ns=Time(funcs[index],f,counts[index]);
                    allocations=allocatedBytes=0;counting=true;
                    sink=funcs[index](f.decoded,f.holes,f.donors,f.probes);counting=false;
                    std::printf("%s,%d,%d,%s,%zu,%.6f,%zu,%zu\n",f.name,sample,pos,names[index],counts[index],ns,allocations,allocatedBytes);
                }
            }
        }
    } else {
        size_t rounds=argc>1?std::strtoull(argv[1],nullptr,10):100000;
        for(int64 bytes: {0,63,64,65,16384,16385}) Check({"threshold",100000,{},{{0,bytes}},{0}});
        Check({"max",std::numeric_limits<int64>::max(),{{std::numeric_limits<int64>::max()-20,20}},{{std::numeric_limits<int64>::max()-100,100}},{0}});
        Check({"min",100000,{{std::numeric_limits<int64>::min(),20}},{{std::numeric_limits<int64>::min(),100}},{0}});
        // An unused overflowing endpoint is defined in C++: no subtraction occurs.
        Check({"unused_endpoint",100000,{{std::numeric_limits<int64>::max(),1}},{},{}});
        Check({"raw_overlap_base",100,{{0,30},{0,30}},{},{}});
        StreamRangeList unused={{0,200}};
        for(int i=0;i<8;++i)unused.push_back({std::numeric_limits<int64>::max(),1});
        Check({"unused_after_cover",100000,unused,{{0,100}},{0}});
        Check({"unused_negative_after_cover",100000,{{0,200},{std::numeric_limits<int64>::min(),-1}},{{0,100}},{0}});
        Check({"unused_donor_end",100000,{{0,1}},{{std::numeric_limits<int64>::max(),100}},{0}});
        Check({"unused_negative_donor_end",100000,{{std::numeric_limits<int64>::min(),0}},{{std::numeric_limits<int64>::min(),-100}},{0}});
        size_t exhaustive=0;
        for(int offset=-2;offset<=4;++offset)
        for(int size=-2;size<=6;++size)
        for(int holeOffset=-2;holeOffset<=4;++holeOffset)
        for(int holeSize=-2;holeSize<=6;++holeSize) {
            // Scale by 64 so the identity threshold does not hide geometry errors.
            Fixture f{"exhaustive",100000,{{holeOffset*64,holeSize*64}},{{offset*64,size*64}}, {0,0}};
            Check(f); ++exhaustive;
        }
        std::mt19937_64 random(0xCA1B20261011ULL);
        for(size_t k=0;k<rounds;++k) {
            Fixture f{"fuzz",k%2 ? 100000 : (int64)(random()%100000)-5000,{},{},{}};
            int nd=1+random()%12,nh=random()%24,np=random()%10;
            for(int i=0;i<nd;++i)f.donors.push_back({(int64)(random()%4000)-1000,(int64)(random()%2000)-(k%4==0?200:0)});
            for(int i=0;i<nh;++i)f.holes.push_back({(int64)(random()%6000)-2000,(int64)(random()%2000)-(k%4==0?100:0)});
            if(k%4==1)std::sort(f.holes.begin(),f.holes.end(),[](auto& a,auto& b){return a.Offset<b.Offset;});
            for(int i=0;i<np;++i)f.probes.push_back(random()%nd);
            Check(f);
        }
        std::printf("Parity: %zu deterministic random cases, %zu exhaustive cases, %zu fixtures, threshold and int64 boundary cases\n",rounds,exhaustive,fs.size());
    }
}
