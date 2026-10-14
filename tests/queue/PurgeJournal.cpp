/* Private offline journal tests. The production helper only publishes bytes;
 * Rust owns framing, sequencing, reservations and recovery decisions. */
#ifdef PURGE_JOURNAL_STANDALONE
#include <cstdio>
#include <stdexcept>
#include "../../rust/include/nzbget_rs.h"
namespace JournalTests {
using Test = void(*)();
Test tests[32]; const char* names[32]; unsigned count = 0, failures = 0;
void Check(bool ok, const char* expression, int line) {
    if (!ok) { ++failures; std::fprintf(stderr, "ASSERT line %d: %s\n", line, expression); }
}
struct Register { Register(Test t, const char* n) { tests[count]=t; names[count++]=n; } };
}
#define BOOST_AUTO_TEST_SUITE(name)
#define BOOST_AUTO_TEST_SUITE_END()
#define BOOST_AUTO_TEST_CASE(name) static void name(); static JournalTests::Register register_##name(name,#name); static void name()
#define BOOST_CHECK(expr) JournalTests::Check(!!(expr), #expr, __LINE__)
#define BOOST_REQUIRE(expr) do {if (!(expr)) { JournalTests::Check(false, #expr, __LINE__); throw std::runtime_error(#expr); }} while(0)
#define BOOST_CHECK_EQUAL(a,b) BOOST_CHECK((a)==(b))
int main() {
    unsigned failed=0;
    for (unsigned i=0;i<JournalTests::count;++i) {
        unsigned before=JournalTests::failures;
        bool exception=false;
        try {JournalTests::tests[i]();}
        catch (const std::exception& e) {exception=true;std::fprintf(stderr,"EXCEPTION %s: %s\n",JournalTests::names[i],e.what());}
        catch (...) {exception=true;std::fprintf(stderr,"EXCEPTION %s: nonstandard\n",JournalTests::names[i]);}
        if (exception || JournalTests::failures!=before) {++failed;std::fprintf(stderr,"FAIL %s\n",JournalTests::names[i]);}
        else std::printf("PASS %s\n",JournalTests::names[i]);
    }
    std::printf("CASES %u FAILED %u ASSERTIONS_FAILED %u\n",JournalTests::count,failed,JournalTests::failures);
    return failed ? 1 : 0;
}
#else
#include "nzbget.h"
#include <boost/test/unit_test.hpp>
#endif
#include "PurgeJournalOps.h"
#include <cstring>
#include <cerrno>
#include <fstream>
#include <string>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

BOOST_AUTO_TEST_SUITE(QueueTest)
#ifndef _WIN32
namespace {
struct PrivateJournal {
    char path[64] = "/tmp/nzbget-journal-test-XXXXXX";
    int fd = -1;
    PrivateJournal() {
        BOOST_REQUIRE(mkdtemp(path) != nullptr);
        fd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
        BOOST_REQUIRE(fd >= 0);
    }
    ~PrivateJournal() {
        // Test-owned names only; never recursively sweep an unexpected object.
        unlinkat(fd, "frame", 0); unlinkat(fd, "other", 0);
        unlinkat(fd, ".pending-frame", 0); unlinkat(fd, ".pending-other", 0);
        close(fd); rmdir(path);
    }
    std::string read(const char* name) {
        std::ifstream f(std::string(path) + "/" + name, std::ios::binary);
        return std::string(std::istreambuf_iterator<char>(f), {});
    }
};
}
BOOST_AUTO_TEST_CASE(PurgeJournalCheckedPublication) {
    // Catches truncated byte emission and unacknowledged file/directory sync.
    PrivateJournal j;
    const unsigned char bytes[] = {'a', 0, 255, 'z'};
    auto r = PurgeJournalOps::Publish(j.fd, "frame", bytes, sizeof(bytes));
    BOOST_CHECK(r.status == PurgeJournalOps::Status::Ok);
    BOOST_CHECK(r.fileSynced && r.published && r.directorySynced);
    BOOST_CHECK(j.read("frame") == std::string(reinterpret_cast<const char*>(bytes), 4));
    struct stat s{};
    BOOST_REQUIRE(fstatat(j.fd, "frame", &s, AT_SYMLINK_NOFOLLOW) == 0);
    BOOST_CHECK_EQUAL(s.st_mode & 0777, 0600);
}
BOOST_AUTO_TEST_CASE(PurgeJournalNeverReplacesSequenceFrame) {
    // Exact replay is verified above this primitive. EEXIST must preserve bytes.
    PrivateJournal j;
    const unsigned char a[] = {'a'}, b[] = {'b'};
    BOOST_REQUIRE(PurgeJournalOps::Publish(j.fd, "frame", a, 1).status == PurgeJournalOps::Status::Ok);
    auto r = PurgeJournalOps::Publish(j.fd, "frame", b, 1);
    BOOST_CHECK(r.status == PurgeJournalOps::Status::Conflict);
    BOOST_CHECK(!r.published);
    BOOST_CHECK(j.read("frame") == "a");
}
BOOST_AUTO_TEST_CASE(PurgeJournalRejectsSymlinkAndTraversal) {
    PrivateJournal j;
    const unsigned char b[] = {'b'};
    BOOST_REQUIRE(symlinkat("other", j.fd, "frame") == 0);
    BOOST_CHECK(PurgeJournalOps::Publish(j.fd, "frame", b, 1).status == PurgeJournalOps::Status::Conflict);
    BOOST_CHECK(PurgeJournalOps::Publish(j.fd, "../other", b, 1).status == PurgeJournalOps::Status::Invalid);
    BOOST_CHECK(PurgeJournalOps::Publish(j.fd, "nested/other", b, 1).status == PurgeJournalOps::Status::Invalid);
    struct stat s{};
    BOOST_REQUIRE(fstatat(j.fd, "frame", &s, AT_SYMLINK_NOFOLLOW) == 0);
    BOOST_CHECK(S_ISLNK(s.st_mode));
    BOOST_CHECK(fstatat(j.fd, "other", &s, AT_SYMLINK_NOFOLLOW) != 0);
}
namespace {
int failureStage = 0;
int syncCalls = 0;
std::ptrdiff_t FaultWrite(int fd, const void* p, std::size_t n) {
    if (failureStage == 1) { errno = ENOSPC; return -1; }
    if (failureStage == 6) throw std::runtime_error("host exception");
    // Exercise the real writer's partial-write loop even without a fault.
    return PurgeJournalOps::SystemCalls().write(fd, p, n > 1 ? 1 : n);
}
int FaultSync(int fd) {
    ++syncCalls;
    if ((failureStage == 2 && syncCalls == 1) || (failureStage == 4 && syncCalls == 2)) { errno = EIO; return -1; }
    return PurgeJournalOps::SystemCalls().sync(fd);
}
int FaultPublish(int dir, const char* a, const char* b) {
    if (failureStage == 3) { errno = EIO; return -1; }
    return PurgeJournalOps::SystemCalls().publishNoReplace(dir,a,b);
}
int FaultRemove(int dir, const char* a) {
    if (failureStage == 5) { errno = EIO; return -1; }
    return PurgeJournalOps::SystemCalls().removeTemporary(dir,a);
}
}
BOOST_AUTO_TEST_CASE(PurgeJournalFailureAcknowledgmentsRetainEvidence) {
    const unsigned char bytes[] = {'a',0,'b'};
    const PurgeJournalOps::Calls calls{FaultWrite,FaultSync,FaultPublish,FaultRemove};
    for (int stage=1;stage<=6;++stage) {
        PrivateJournal j; failureStage=stage; syncCalls=0;
        auto r=PurgeJournalOps::Publish(j.fd,"frame",bytes,sizeof(bytes),calls);
        BOOST_CHECK(r.status != PurgeJournalOps::Status::Ok);
        BOOST_CHECK(r.fileSynced == (stage>=3 && stage<=5));
        BOOST_CHECK(r.published == (stage==4 || stage==5));
        BOOST_CHECK(r.directorySynced == (stage==5));
        struct stat retained{};
        const char* name=(stage==4) ? "frame" : ".pending-frame";
        BOOST_CHECK(fstatat(j.fd,name,&retained,AT_SYMLINK_NOFOLLOW)==0);
        if (r.published) BOOST_CHECK(j.read("frame")==std::string("a\0b",3));
    }
    failureStage=0;syncCalls=0;PrivateJournal j;
    auto r=PurgeJournalOps::Publish(j.fd,"frame",bytes,sizeof(bytes),calls);
    BOOST_CHECK(r.status == PurgeJournalOps::Status::Ok);
    BOOST_CHECK(j.read("frame")==std::string("a\0b",3));
}
BOOST_AUTO_TEST_CASE(PurgeJournalInvalidDescriptorAndNonprivateDirectory) {
    PrivateJournal j;
    const unsigned char b[] = {'b'};
    BOOST_CHECK(PurgeJournalOps::Publish(-1, "frame", b, 1).status != PurgeJournalOps::Status::Ok);
    BOOST_REQUIRE(fchmod(j.fd, 0755) == 0);
    BOOST_CHECK(PurgeJournalOps::Publish(j.fd, "frame", b, 1).status == PurgeJournalOps::Status::Invalid);
    struct stat s{};
    BOOST_CHECK(fstatat(j.fd, "frame", &s, AT_SYMLINK_NOFOLLOW) != 0);
}
BOOST_AUTO_TEST_CASE(PurgeJournalActualHeldDescriptorIdentity) {
    PrivateJournal j, other;
    auto id = PurgeJournalOps::Identify(j.fd);
    BOOST_REQUIRE(id.status == PurgeJournalOps::Status::Ok);
    BOOST_CHECK(std::memcmp(id.bytes.data(), "NZBPJID1", 8) == 0);
    struct stat actual{};
    BOOST_REQUIRE(fstat(j.fd, &actual) == 0);
    const std::uint64_t values[] = {static_cast<std::uint64_t>(actual.st_dev),
        static_cast<std::uint64_t>(actual.st_ino), static_cast<std::uint64_t>(actual.st_uid)};
    for (unsigned field=0; field<3; ++field)
        for (unsigned byte=0; byte<8; ++byte)
            BOOST_CHECK_EQUAL(id.bytes[8+field*8+byte], (values[field] >> (8*byte)) & 255);
    int duplicate = dup(j.fd);
    BOOST_REQUIRE(duplicate >= 0);
    auto same = PurgeJournalOps::Identify(duplicate);
    BOOST_CHECK(same.status == PurgeJournalOps::Status::Ok && same.bytes == id.bytes);
    BOOST_REQUIRE(close(duplicate) == 0);
    auto different = PurgeJournalOps::Identify(other.fd);
    BOOST_CHECK(different.status == PurgeJournalOps::Status::Ok && different.bytes != id.bytes);
    BOOST_CHECK(PurgeJournalOps::Identify(-1).status != PurgeJournalOps::Status::Ok);
    BOOST_REQUIRE(fchmod(j.fd, 0755) == 0);
    BOOST_CHECK(PurgeJournalOps::Identify(j.fd).status == PurgeJournalOps::Status::Invalid);
    BOOST_CHECK(fstatat(j.fd, "frame", &actual, AT_SYMLINK_NOFOLLOW) != 0);
}
#ifdef PURGE_JOURNAL_RUST_LINKED
namespace {
struct NativeJournalHost {
    PrivateJournal journal;
    int held = journal.fd;
    unsigned calls = 0;
    std::uint64_t published = 0;
    ~NativeJournalHost() {
        for (std::uint64_t i=1;i<=published;++i) {
            char name[64], pending[80];
            std::snprintf(name,sizeof(name),"journal-%llu",static_cast<unsigned long long>(i));
            std::snprintf(pending,sizeof(pending),".pending-%s",name);
            unlinkat(journal.fd,name,0); unlinkat(journal.fd,pending,0);
        }
    }
};
int NativeIdentity(void* context, std::uint8_t out[32]) noexcept {
    auto& h=*static_cast<NativeJournalHost*>(context);
    auto identity=PurgeJournalOps::Identify(h.held);
    if (identity.status!=PurgeJournalOps::Status::Ok) return 9;
    std::memcpy(out,identity.bytes.data(),32); return 0;
}
int NativePublish(void* context, std::uint64_t sequence, NzbgetRsPurgeBytesV1 bytes,
    NzbgetRsPurgePublicationAckV1* ack) noexcept {
    auto& h=*static_cast<NativeJournalHost*>(context);
    char name[64];
    std::snprintf(name,sizeof(name),"journal-%llu",static_cast<unsigned long long>(sequence));
    h.published=sequence;
    auto result=PurgeJournalOps::Publish(h.held,name,bytes.data,bytes.len);
    if (result.status!=PurgeJournalOps::Status::Ok) return 8;
    *ack={1,sizeof(*ack),sequence,bytes,1,1,1}; return 0;
}
int NativeExecute(void* context,const NzbgetRsPurgeCallV1*,NzbgetRsPurgeAckV1*) noexcept {
    ++static_cast<NativeJournalHost*>(context)->calls; return 9;
}
}
BOOST_AUTO_TEST_CASE(PurgeJournalNativeRustRegistryAndInventoryBoundary) {
    NativeJournalHost h;
    NzbgetRsPurgeHostOpsV1 ops{};
    ops.version=1;ops.struct_size=sizeof(ops);ops.context=&h;ops.capabilities=1;
    ops.journal_identity=NativeIdentity;ops.publish=NativePublish;ops.execute=NativeExecute;
    const std::uint8_t domain[16]={8};
    NzbgetRsPurgeRegistryV1* initial=nullptr;
    BOOST_REQUIRE(nzbget_rs_purge_registry_create(domain,&ops,&ops.registry)==0);
    initial=ops.registry;
    BOOST_REQUIRE(initial!=nullptr);
    ops.registry=initial;
    const auto stored=h.journal.read("journal-1");
    BOOST_REQUIRE(stored.size()>36);
    const NzbgetRsPurgeBytesV1 frame{reinterpret_cast<const std::uint8_t*>(stored.data()),static_cast<std::uint32_t>(stored.size())};
    NzbgetRsPurgeRegistryV1* recovered=nullptr;
    BOOST_CHECK(nzbget_rs_purge_registry_recover(domain,&frame,1,0,&ops,&recovered)==1);
    BOOST_CHECK(recovered==nullptr);
    BOOST_REQUIRE(nzbget_rs_purge_registry_recover(domain,&frame,1,1,&ops,&ops.registry)==0);
    recovered=ops.registry;
    nzbget_rs_purge_registry_destroy(initial);
    NzbgetRsPurgeBindingV1 binding{};
    const std::uint8_t source[]={'n','a','t','i','v','e'};
    binding.collection_id=1;binding.incarnation=1;binding.posting_source={source,sizeof(source)};
    NzbgetRsPurgeOutputDeltaV1 delta{};
    delta.version=1;delta.struct_size=sizeof(delta);delta.producer_ticket=1;
    delta.sequence=1;delta.prior_inventory_revision=7;delta.final_for_producer=1;
    int error=-1;
    PrivateJournal substituted;
    h.held=substituted.fd;
    BOOST_CHECK(nzbget_rs_purge_inventory_store(&binding,&delta,&ops,&error)==4);
    BOOST_CHECK(error==4 && h.published==1 && h.calls==0);
    h.held=h.journal.fd;
    BOOST_CHECK(nzbget_rs_purge_inventory_store(&binding,&delta,&ops,&error)==0);
    BOOST_CHECK(error==0 && h.published==3 && h.calls==0);
    const auto inventory=h.journal.read("journal-3");
    BOOST_REQUIRE(inventory.size()>36);
    BOOST_CHECK(static_cast<unsigned char>(inventory[12])==3);
    BOOST_CHECK(nzbget_rs_purge_inventory_store(&binding,&delta,&ops,&error)==0);
    BOOST_CHECK(h.published==3);
    nzbget_rs_purge_registry_destroy(recovered);
}
#endif
#else
BOOST_AUTO_TEST_CASE(PurgeJournalUnsupportedBeforeMutation) {
    const unsigned char b[] = {'b'};
    auto r = PurgeJournalOps::Publish(-1, "frame", b, 1);
    BOOST_CHECK(r.status == PurgeJournalOps::Status::Unsupported);
    BOOST_CHECK(!r.fileSynced && !r.published && !r.directorySynced);
}
#endif
BOOST_AUTO_TEST_SUITE_END()
