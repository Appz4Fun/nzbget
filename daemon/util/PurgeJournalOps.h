#ifndef NZBGET_PURGE_JOURNAL_OPS_H
#define NZBGET_PURGE_JOURNAL_OPS_H
#include <array>
#include <cstddef>
#include <cstdint>

// Mechanical immutable-frame publication only. The caller owns a serialized,
// exclusive journal domain and a live descriptor to its private directory.
// Rust owns frame bytes, sequence allocation, leases and recovery decisions.
namespace PurgeJournalOps {
enum class Status { Ok, Invalid, Unsupported, Conflict, IoError, HostFailure };
struct Identity {
    Status status = Status::IoError;
    int error = 0;
    std::array<std::uint8_t,32> bytes{};
};
// Actual held private directory identity: NZBPJID1 then device/inode/owner
// converted to uint64 and encoded little-endian. No caller label or digest.
Identity Identify(int directory) noexcept;
struct Result {
    Status status = Status::IoError;
    int error = 0;
    bool fileSynced = false;
    bool published = false;
    bool directorySynced = false;
};
// Explicit syscall boundary permits deterministic error drivers without a
// second publication policy. Production callers use SystemCalls(). Foreign
// adapters must not throw; Publish catches exceptions before any ABI return.
struct Calls {
    std::ptrdiff_t (*write)(int, const void*, std::size_t);
    int (*sync)(int);
    int (*publishNoReplace)(int, const char*, const char*);
    int (*removeTemporary)(int, const char*);
};
const Calls& SystemCalls() noexcept;
Result Publish(int directory, const char* sequenceName, const std::uint8_t* bytes,
    std::size_t length, const Calls& calls = SystemCalls()) noexcept;
}
#endif
