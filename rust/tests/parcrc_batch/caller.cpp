// Full fold caller: real Par2 packet access, LE extraction, FFI and comparison.
#include <zlib.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <mutex>
#include <random>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>
#include <cassert>
#include <par2/libpar2.h>
#include <par2/verificationpacket.h>
#include <par2/crc.h>
#include <par2/mainpacket.h>
#include <par2/par2repairersourcefile.h>
#include "nzbget_rs.h"
using uint32 = uint32_t;
struct Crc32 {
    static uint32 Combine(uint32 a, uint32 b, uint32 length) {
        return nzbget_rs_crc32_combine(a, b, length);
    }
};
static uint32 original(Par2::VerificationPacket* packet, Par2::u64 blocksize) {
#include "reference.inc"
}
static uint32 candidate(Par2::VerificationPacket* packet, Par2::u64 blocksize) {
#include "candidate.inc"
    return parCrc;
}
// Fair optimized C++: compute the fixed length operator once per fold, using
// zlib's public API, then apply the same CRC polynomial multiplication inline.
// No per-block Rust call; no prepared state is excluded from timing.
static uint32 multiply(uint32 a, uint32 b) {
    uint32 mask = 0x80000000, product = 0;
    for (;;) {
        if (a & mask) {
            product ^= b;
            if (!(a & (mask - 1))) break;
        }
        mask >>= 1;
        b = (b >> 1) ^ ((b & 1) ? 0xedb88320 : 0);
    }
    return product;
}
static uint32 optimized(Par2::VerificationPacket* packet, Par2::u64 blocksize) {
    const auto count = packet->BlockCount();
    if (!count) return 0;
    uint32 result = packet->VerificationEntry(0)->crc;
    uint32 length = (uint32)blocksize;
    if (!length || count == 1) return result;
    uint32 op = crc32_combine_gen(length);
    for (uint32 i = 1; i < count; ++i) {
        result = multiply(op, result) ^ (uint32)packet->VerificationEntry(i)->crc;
    }
    return result;
}
static uint32 independent(const std::vector<uint8_t>& data) {
    return crc32(0, data.data(), data.size());
}
static std::mt19937 rng(0xa21348);
static uint64_t checked = 0;
static void check(Par2::VerificationPacket& p, uint64_t size) {
    auto a = original(&p, size), b = candidate(&p, size), c = optimized(&p, size);
    if (a != b || a != c) { std::fprintf(stderr,"mismatch count=%u size=%llu %x %x %x\n",p.BlockCount(),(unsigned long long)size,a,b,c); std::exit(1); }
    // Include both true and false comparison outcomes.
    if (!(b == a) || (b == (a ^ 1))) std::abort();
    ++checked;
}
static void fixtures() {
    const uint64_t sizes[] = {0,1,2,4,17,512,716800,0x7fffffffULL,0x80000000ULL,
        0xffffffffULL,0x100000000ULL,0x100000001ULL,0xffffffffffffffffULL};
    Par2::MD5Hash hash{};
    for (uint32 n : {0u,1u,2u,3u,4u,8u,16u,1024u,32768u}) {
        Par2::VerificationPacket packet;
        packet.Create(n);
        for (uint32 i=0;i<n;i++) packet.SetBlockHashAndCRC(i,hash,rng());
        for (uint64_t size:sizes) check(packet,size);
    }
    // Exercise every length-bit transition through actual LE packet access,
    // descriptor construction and the unchanged u64-to-u32 caller cast.
    for (uint32 n : {3u,4u,8u}) {
        Par2::VerificationPacket packet;
        packet.Create(n);
        for (uint32 i=0;i<n;i++) packet.SetBlockHashAndCRC(i,hash,rng());
        for (unsigned bit=0;bit<32;bit++) {
            const uint64_t power = uint64_t(1) << bit;
            for (uint64_t length : {power-1,power,power+1}) {
                check(packet,length);
                check(packet,0x100000000ULL+length);
            }
        }
    }
    for (unsigned t=0;t<10000;t++) {
        Par2::VerificationPacket packet;
        const uint32 n = rng()%64;
        packet.Create(n);
        for (uint32 i=0;i<n;i++) packet.SetBlockHashAndCRC(i,hash,rng());
        check(packet, (uint64_t(rng())<<32)|rng());
    }
    for (uint32 size : {1u,4u,17u,512u,4096u}) {
        for (uint32 n : {1u,2u,7u}) {
            Par2::VerificationPacket packet;
            packet.Create(n);
            std::vector<uint8_t> whole;
            for(uint32 i=0;i<n;i++) {
                std::vector<uint8_t> block(size);
                for(auto& b:block) b=rng();
                if(i==n-1) std::fill(block.begin()+size/2,block.end(),0);
                packet.SetBlockHashAndCRC(i,hash,independent(block));
                whole.insert(whole.end(),block.begin(),block.end());
            }
            check(packet,size);
            if(candidate(&packet,size)!=independent(whole)) std::abort();
            // The real C++ zero-extension of a shortened last block.
            size_t tail = size-size/2;
            whole.resize(whole.size()-tail);
            auto padded = Par2::CRCUpdateBlock(independent(whole)^0xffffffffu,tail)^0xffffffffu;
            if(candidate(&packet,size)!=padded) std::abort();
        }
    }
    // Only CRC bytes are readable: the gap contains a protected page.
    const size_t page = sysconf(_SC_PAGESIZE);
    auto* guarded = static_cast<uint8_t*>(mmap(nullptr,page*3,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
    if(guarded==MAP_FAILED) std::abort();
    const uint8_t fixture[]={0x78,0x56,0x34,0x12};
    std::memcpy(guarded+page-5,fixture,4);
    std::memcpy(guarded+page*3-5,fixture,4);
    if(mprotect(guarded+page,page,PROT_NONE)) std::abort();
    uint32 guardedResult=0;
    if(!nzbget_rs_parcrc_batch(guarded+page-5,page*2+4,page*2,2,512,&guardedResult) ||
       guardedResult!=Crc32::Combine(0x12345678,0x12345678,512)) std::abort();
    munmap(guarded,page*3);
    // Deliberately unaligned LE bytes, independent of host uint32 layout.
    const uint8_t raw[] = {0xa5,0x78,0x56,0x34,0x12,0xef,0xcd,0xab,0x90};
    uint32 out=0;
    if(!nzbget_rs_parcrc_batch(raw+1,8,4,2,0,&out) || out!=0x12345678u) std::abort();
    if(!nzbget_rs_parcrc_batch(raw+1,8,4,2,17,&out) || out!=Crc32::Combine(0x12345678,0x90abcdef,17)) std::abort();
}
static void real_packet(const char* path) {
    std::ifstream file(path,std::ios::binary);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)),{});
    std::mutex lock;
    Par2::DiskFile disk(std::cout,std::cerr,lock);
    if(!disk.Open(path)) std::abort();
    struct Description { Par2::MD5Hash id; std::string name; uint64_t length; };
    std::vector<Description> descriptions;
    uint64_t blocksize=0;
    for(size_t offset=0;offset+sizeof(Par2::PACKET_HEADER)<=bytes.size();) {
        Par2::PACKET_HEADER header;
        std::memcpy(&header,bytes.data()+offset,sizeof header);
        uint64_t length=header.length;
        if(length<sizeof header || length>bytes.size()-offset) std::abort();
        if(std::memcmp(&header.type,"PAR 2.0\0Main\0\0\0\0",16)==0) {
            if(length<sizeof(Par2::MAINPACKET)) std::abort();
            Par2::MAINPACKET main;
            std::memcpy(&main,bytes.data()+offset,sizeof main);
            blocksize=main.blocksize;
        }
        if(std::memcmp(&header.type,"PAR 2.0\0FileDesc",16)==0) {
            if(length<sizeof(Par2::FILEDESCRIPTIONPACKET)) std::abort();
            Par2::FILEDESCRIPTIONPACKET desc;
            std::memcpy(&desc,bytes.data()+offset,sizeof desc);
            std::string name(reinterpret_cast<const char*>(bytes.data()+offset+sizeof desc),length-sizeof desc);
            while(!name.empty() && name.back()==0) name.pop_back();
            descriptions.push_back({desc.fileid,name,desc.length});
        }
        offset+=length;
    }
    if(!blocksize || descriptions.empty()) std::abort();
    size_t found=0;
    for(size_t offset=0;offset+sizeof(Par2::PACKET_HEADER)<=bytes.size();) {
        Par2::PACKET_HEADER header;
        std::memcpy(&header,bytes.data()+offset,sizeof header);
        uint64_t length=header.length;
        if(length<sizeof header || length>bytes.size()-offset) std::abort();
        if(std::memcmp(&header.type,"PAR 2.0\0IFSC\0\0\0\0",16)==0) {
            Par2::VerificationPacket packet;
            if(!packet.Load(&disk,offset,header)) std::abort();
            for(auto size:{0ULL,512ULL,716800ULL,0x100000001ULL}) check(packet,size);
            bool matched=false;
            for(const auto& desc:descriptions) if(packet.FileId()==desc.id) {
                std::ifstream dataFile(std::filesystem::path(path).parent_path()/desc.name,std::ios::binary);
                std::vector<uint8_t> data((std::istreambuf_iterator<char>(dataFile)),{});
                if(data.size()!=desc.length) std::abort();
                uint64_t paddedLength=blocksize*packet.BlockCount();
                if(paddedLength<data.size()) std::abort();
                uint32 expected=Par2::CRCUpdateBlock(independent(data)^0xffffffffu,paddedLength-data.size())^0xffffffffu;
                check(packet,blocksize);
                if(candidate(&packet,blocksize)!=expected) std::abort();
                matched=true;
            }
            if(!matched) std::abort();
            found++;
        }
        offset+=length;
    }
    if(!found) std::abort();
    std::printf("actual packet loads: %zu\n",found);
}
using Fold = uint32 (*)(Par2::VerificationPacket*,uint64_t);
static volatile uint32 sink=0;
static double measure(Fold fold,Par2::VerificationPacket& packet,uint64_t size,uint32 expected,unsigned calls) {
    const auto start=std::chrono::steady_clock::now();
    uint32 result=0;
    for(unsigned i=0;i<calls;i++) {
        // Function pointer prevents excluding extraction/descriptor/FFI work.
        result += fold(&packet,size)==expected;
        asm volatile("" : "+r"(result) : : "memory");
    }
    sink=result;
    return std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/calls;
}
static void benchmark() {
    std::puts("count,size,sample,order,old_ns,rust_ns,optimized_ns");
    Par2::MD5Hash hash{};
    for(uint32 n:{0u,1u,2u,16u,1024u,32768u}) {
        Par2::VerificationPacket packet;packet.Create(n);
        for(uint32 i=0;i<n;i++) packet.SetBlockHashAndCRC(i,hash,rng());
        for(uint64_t size:{512ULL,716800ULL}) {
            uint32 expected=original(&packet,size);
            unsigned calls=1;
            while(measure(original,packet,size,expected,calls)*calls<20000000 && calls<1u<<24) calls*=2;
            for(int sample=0;sample<31;sample++) {
                double times[3];Fold folds[]={original,candidate,optimized};
                for(int j=0;j<3;j++) {int index=sample%2 ? 2-j:j;times[index]=measure(folds[index],packet,size,expected,calls);}
                std::printf("%u,%llu,%d,%d,%.3f,%.3f,%.3f\n",n,(unsigned long long)size,sample,sample%2,times[0],times[1],times[2]);
            }
        }
    }
}
// Full release VerifySuccessDataFile bodies, including the existing padding,
// target filename copy/destruction and boolean comparison. PAR2 getter objects
// are real; these fixture subclasses prepare their metadata outside timing.
#define debug(...) do { } while (0)
class PreparedMain : public Par2::MainPacket {
public:
    explicit PreparedMain(uint64_t size) {
        AllocatePacket(sizeof(Par2::MAINPACKET));
        blocksize=size;
    }
};
class PreparedTarget : public Par2::DiskFile {
public:
    PreparedTarget(std::mutex& lock, uint64_t size)
        : DiskFile(std::cout,std::cerr,lock) {
        filename="/tmp/parcrc-offline/Complete.Offline.Fixture.7z.001";
        filesize=size;
    }
};
class FullCaller {
    struct RepairerView { Par2::MainPacket* mainpacket; } repairer;
public:
    explicit FullCaller(Par2::MainPacket* main) : repairer{main} {}
    RepairerView* GetRepairer() { return &repairer; }
    bool Old(Par2::DiskFile&, Par2::Par2RepairerSourceFile& sourceFile, uint32 downloadCrc) {
#include "reference-full.inc"
    }
    bool Candidate(Par2::DiskFile&, Par2::Par2RepairerSourceFile& sourceFile, uint32 downloadCrc) {
#include "candidate-full.inc"
    }
    bool Control(Par2::DiskFile&, Par2::Par2RepairerSourceFile& sourceFile, uint32 downloadCrc) {
#include "control-full.inc"
    }
};
#undef debug
using Verify = bool (FullCaller::*)(Par2::DiskFile&,Par2::Par2RepairerSourceFile&,uint32);
static double measure_full(FullCaller& caller, Verify verify, Par2::DiskFile& target,
                           Par2::Par2RepairerSourceFile& source, uint32 crc, unsigned calls) {
    auto start=std::chrono::steady_clock::now();
    uint32 result=0;
    for(unsigned i=0;i<calls;i++) {
        result+=(caller.*verify)(target,source,crc);
        asm volatile("" : "+r"(result) : : "memory");
    }
    sink=result;
    return std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/calls;
}
static void full_padding_checks() {
    std::mutex lock;
    Par2::MD5Hash hash{};
    size_t cases=0;
    for(uint32 count:{1u,2u,7u}) for(uint64_t size:{1ULL,4ULL,17ULL,512ULL,4096ULL}) {
        uint64_t length=size*count-(size+1)/2;
        std::vector<uint8_t> data(length);
        for(auto& byte:data) byte=rng();
        auto padded=data;padded.resize(size*count,0);
        auto* packet=new Par2::VerificationPacket;packet->Create(count);
        for(uint32 i=0;i<count;i++) packet->SetBlockHashAndCRC(i,hash,crc32(0,padded.data()+i*size,size));
        PreparedMain main(size);FullCaller caller(&main);
        PreparedTarget target(lock,length);
        Par2::Par2RepairerSourceFile source(nullptr,packet);source.SetTargetFile(&target);
        uint32 crc=independent(data);
        for(uint32 probe:{crc,crc^1}) {
            bool expected=probe==crc;
            if(caller.Old(target,source,probe)!=expected || caller.Candidate(target,source,probe)!=expected ||
               caller.Control(target,source,probe)!=expected) std::abort();
            cases++;
        }
    }
    std::printf("%zu full callers match independent shortened-file/padded CRCs\n",cases);
}
static void full_caller(bool timing) {
    if(timing) std::puts("count,size,sample,order,old_ns,rust_ns,optimized_ns");
    std::mutex lock;
    Par2::MD5Hash hash{};
    size_t cases=0;
    for(uint32 count:{0u,1u,2u,3u,4u,8u,16u,1024u,32768u}) {
        for(uint64_t size:{512ULL,716800ULL}) {
            // Real source object owns the verification packet.
            auto* packet=new Par2::VerificationPacket;
            packet->Create(count);
            for(uint32 i=0;i<count;i++) packet->SetBlockHashAndCRC(i,hash,rng());
            PreparedMain main(size);
            FullCaller caller(&main);
            PreparedTarget target(lock,size*count);
            Par2::Par2RepairerSourceFile source(nullptr,packet);
            source.SetTargetFile(&target);
            uint32 crc=original(packet,size);
            for(uint32 probe:{crc,crc^1}) {
                bool expected=probe==crc;
                if(caller.Old(target,source,probe)!=expected ||
                   caller.Candidate(target,source,probe)!=expected ||
                   caller.Control(target,source,probe)!=expected) std::abort();
                cases++;
            }
            // The exact prefix's zero-padding runs in every timed operation.
            // No padding is needed in this fixture, matching already-full blocks.
            if(!timing) continue;
            unsigned calls=1;
            while(measure_full(caller,&FullCaller::Old,target,source,crc,calls)*calls<20000000 && calls<1u<<24) calls*=2;
            Verify variants[]={&FullCaller::Old,&FullCaller::Candidate,&FullCaller::Control};
            for(int sample=0;sample<31;sample++) {
                double times[3];
                for(int j=0;j<3;j++) {int index=sample%2?2-j:j;times[index]=measure_full(caller,variants[index],target,source,crc,calls);}
                std::printf("%u,%llu,%d,%d,%.3f,%.3f,%.3f\n",count,(unsigned long long)size,sample,sample%2,times[0],times[1],times[2]);
            }
        }
    }
    if(!timing) std::printf("%zu full VerifySuccessDataFile boolean callers agree\n",cases);
}
int main(int argc,char** argv) {
    static_assert(sizeof(Par2::leu32)==4,"LE CRC size");
    if(argc>1 && !std::strcmp(argv[1],"bench")) {benchmark();return 0;}
    if(argc>1 && !std::strcmp(argv[1],"full-bench")) {full_caller(true);return 0;}
    full_caller(false);
    full_padding_checks();
    fixtures();
    if(argc>1) real_packet(argv[1]);
    std::printf("%llu ordered packet folds agree, including concatenation and padding\n",(unsigned long long)checked);
}
