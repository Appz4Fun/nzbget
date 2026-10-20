#ifndef NZBGET_TLS_CIPHER_ABI_H
#define NZBGET_TLS_CIPHER_ABI_H

// Included by nzbget_rs.h after NzbgetRsBuf. Every callback is nonthrowing.
// Callback strings are NUL-terminated and borrowed only during that callback.
// The backend context transfers to Rust at start, even on a rejected start;
// destroy is called once after its owned worker has finished using it.
typedef int (*NzbgetTlsCancelled)(void*);
typedef int (*NzbgetTlsEmitSuite)(void*, const char*, const char*, int, unsigned int, unsigned int);
typedef struct
{
    uint32_t id;
    const char* host;
    uint16_t port;
    uint8_t ip_version;
    uint8_t verification;
    const char* username;
    const char* password;
} NzbgetTlsServer;

typedef struct
{
    void* context;
    int (*snapshot)(void*, const unsigned char**, size_t*);
    int (*suites)(void*, NzbgetTlsEmitSuite, void*);
    void* (*prepare)(void*, const char*);
    int (*prepare_batch)(void*, uint64_t, uint32_t);
    int (*record)(void*, uint64_t);
    void (*free_decryptor)(void*);
    // probe: 1 supported, 0 unsupported; negative DNS(-2), deadline(-3),
    // certificate(-4), authentication(-5), cancellation(-6), other(-1).
    int (*probe)(void*, const NzbgetTlsServer*, const char*, int, const char*,
        uint64_t, NzbgetTlsCancelled, void*);
    // commit: 1 saved, 0 unchanged, -2 conflict, -3 cancelled, -1 failed.
    int (*commit)(void*, const unsigned char*, size_t, const unsigned char*, size_t,
        NzbgetTlsCancelled, void*);
    void (*destroy)(void*);
} NzbgetTlsBackend;

NzbgetRsBuf nzbget_rs_tls_cipher_start(const NzbgetTlsBackend* backend);
// Returns12/13 for an eligible exact pin, 0 otherwise; flags as in suite emitter.
int nzbget_rs_tls_cipher_pin(int protocol, unsigned int bits, unsigned int flags);
NzbgetRsBuf nzbget_rs_tls_cipher_status(const char* id);
NzbgetRsBuf nzbget_rs_tls_cipher_cancel(const char* id);
void nzbget_rs_tls_cipher_shutdown(void);
int nzbget_rs_tls_cipher_resolver(int argc, const char* const* argv);
#endif
