#include "PurgeJournalOps.h"
#include <cerrno>
#include <cstring>
#if defined(__unix__) || defined(__APPLE__)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace PurgeJournalOps {
namespace {
#if (defined(__unix__) || defined(__APPLE__)) && defined(O_NOFOLLOW) && defined(O_DIRECTORY)
std::ptrdiff_t Write(int fd, const void* p, std::size_t n) { return ::write(fd, p, n); }
int Sync(int fd) { return ::fsync(fd); }
int PublishLink(int dir, const char* from, const char* to) { return ::linkat(dir, from, dir, to, 0); }
int Remove(int dir, const char* name) { return ::unlinkat(dir, name, 0); }
const Calls systemCalls{Write, Sync, PublishLink, Remove};
struct Descriptor {
    int fd;
    ~Descriptor() { if (fd >= 0) ::close(fd); }
};
#else
const Calls systemCalls{nullptr, nullptr, nullptr, nullptr};
#endif
}
const Calls& SystemCalls() noexcept { return systemCalls; }

Identity Identify(int directory) noexcept {
    Identity result;
#if (defined(__unix__) || defined(__APPLE__)) && defined(O_NOFOLLOW) && defined(O_DIRECTORY)
    struct stat actual{};
    if constexpr (sizeof(actual.st_dev) > 8 || sizeof(actual.st_ino) > 8 || sizeof(actual.st_uid) > 8) {
        result.status = Status::Unsupported; return result;
    }
    if (::fstat(directory, &actual) != 0) { result.error = errno; return result; }
    if (!S_ISDIR(actual.st_mode) || actual.st_uid != ::geteuid() || (actual.st_mode & 0777) != 0700) {
        result.status = Status::Invalid; return result;
    }
    std::memcpy(result.bytes.data(), "NZBPJID1", 8);
    const std::uint64_t fields[] = {static_cast<std::uint64_t>(actual.st_dev),
        static_cast<std::uint64_t>(actual.st_ino), static_cast<std::uint64_t>(actual.st_uid)};
    for (unsigned field=0; field<3; ++field)
        for (unsigned byte=0; byte<8; ++byte)
            result.bytes[8+field*8+byte] = static_cast<std::uint8_t>(fields[field] >> (8*byte));
    result.status = Status::Ok;
#else
    (void)directory; result.status = Status::Unsupported;
#endif
    return result;
}

Result Publish(int directory, const char* sequenceName, const std::uint8_t* bytes,
    std::size_t length, const Calls& calls) noexcept {
    Result result;
#if (defined(__unix__) || defined(__APPLE__)) && defined(O_NOFOLLOW) && defined(O_DIRECTORY)
    try {
        if (!sequenceName || !bytes || length == 0 || length > 64U * 1024U * 1024U ||
            !calls.write || !calls.sync || !calls.publishNoReplace || !calls.removeTemporary) {
            result.status = Status::Invalid; return result;
        }
        std::size_t n = 0;
        for (; n <= 200 && sequenceName[n]; ++n) {
            unsigned char c = static_cast<unsigned char>(sequenceName[n]);
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) {
                result.status = Status::Invalid; return result;
            }
        }
        if (n == 0 || n > 200 || std::strcmp(sequenceName, ".") == 0 ||
            std::strcmp(sequenceName, "..") == 0 || std::strncmp(sequenceName, ".pending-", 9) == 0) {
            result.status = Status::Invalid; return result;
        }
        struct stat dir{};
        if (::fstat(directory, &dir) != 0) { result.error = errno; return result; }
        if (!S_ISDIR(dir.st_mode) || dir.st_uid != ::geteuid() || (dir.st_mode & 0777) != 0700) {
            result.status = Status::Invalid; return result;
        }
        char temporary[210] = ".pending-";
        std::memcpy(temporary + 9, sequenceName, n + 1);
        Descriptor file{::openat(directory, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600)};
        if (file.fd < 0) {
            result.error = errno;
            result.status = errno == EEXIST ? Status::Conflict : Status::IoError;
            return result;
        }
        if (::fchmod(file.fd, 0600) != 0) { result.error = errno; return result; }
        // Never delete a partial/failed publication here. Recovery inspects and
        // retains it under the same domain; a retry cannot overwrite evidence.
        std::size_t offset = 0;
        while (offset < length) {
            auto written = calls.write(file.fd, bytes + offset, length - offset);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0 || static_cast<std::size_t>(written) > length - offset) {
                result.error = written < 0 ? errno : EIO; return result;
            }
            offset += static_cast<std::size_t>(written);
        }
        if (calls.sync(file.fd) != 0) { result.error = errno; return result; }
        result.fileSynced = true;
        int closed = ::close(file.fd);
        file.fd = -1;
        if (closed != 0) { result.error = errno; return result; }
        // Atomic link publication has no replacement mode. Both names are
        // relative to the held private directory descriptor; no path is followed.
        if (calls.publishNoReplace(directory, temporary, sequenceName) != 0) {
            result.error = errno;
            result.status = errno == EEXIST ? Status::Conflict : Status::IoError;
            return result;
        }
        result.published = true;
        int cleanupError = calls.removeTemporary(directory, temporary) == 0 ? 0 : errno;
        if (calls.sync(directory) != 0) { result.error = errno; return result; }
        result.directorySynced = true;
        if (cleanupError) { result.error = cleanupError; return result; }
        result.status = Status::Ok;
    } catch (...) {
        result.status = Status::HostFailure;
    }
#else
    (void)directory; (void)sequenceName; (void)bytes; (void)length; (void)calls;
    result.status = Status::Unsupported;
#endif
    return result;
}
}
