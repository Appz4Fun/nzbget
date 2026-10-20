#include "nzbget.h"
#include <boost/test/unit_test.hpp>
#include "TlsCipherBackend.h"

#if defined(NZBGET_USE_RUST) && !defined(DISABLE_TLS) && (defined(__APPLE__) || defined(__linux__))
#include <openssl/rand.h>
#include <set>
#include <thread>
#include <atomic>
#include <poll.h>
#include <stdexcept>
#include <csignal>
#include "OpenSSL.h"
#endif

BOOST_AUTO_TEST_SUITE(ConnectTest)

#if defined(NZBGET_USE_RUST) && !defined(DISABLE_TLS) && (defined(__APPLE__) || defined(__linux__))

namespace
{
struct OwnedBackend
{
	// The daemon installs this same disposition during startup. The unit harness
	// does not; restore its handler once this case's fixture has joined.
	using Handler = void (*)(int);
	Handler previous = std::signal(SIGPIPE, SIG_IGN);
	NzbgetTlsBackend io = TlsCipherBackend::Create();
	~OwnedBackend() { if (io.destroy) io.destroy(io.context); if (previous != SIG_ERR) std::signal(SIGPIPE, previous); }
};
struct OwnedCrypto
{
	NzbgetTlsBackend& io; void* context;
	~OwnedCrypto() { if (context) io.free_decryptor(context); }
};

// One owned loopback server, no daemon/global configuration or public providers.
class LoopbackTls
{
public:
	enum Mode { Normal, BadLogin, StallGreeting };
	OpenSSL::SSLCtxPtr context{SSL_CTX_new(TLS_server_method()), &SSL_CTX_free};
	std::atomic<int> negotiated{0};
	std::atomic<int> authCommands{0};
	std::atomic<int> articleCommands{0};
	uint16_t port = 0;
	LoopbackTls(int minimum, int maximum, const char* legacy, const char* modern, Mode mode = Normal) : mode(mode)
	{
		if (!context || !SSL_CTX_set_min_proto_version(context.get(), minimum) || !SSL_CTX_set_max_proto_version(context.get(), maximum) ||
			!SSL_CTX_set_cipher_list(context.get(), legacy) || !SSL_CTX_set_ciphersuites(context.get(), modern)) throw std::runtime_error("TLS fixture context");
		std::unique_ptr<EVP_PKEY_CTX, decltype(&EVP_PKEY_CTX_free)> generator(EVP_PKEY_CTX_new_id(EVP_PKEY_RSA, nullptr), &EVP_PKEY_CTX_free);
		EVP_PKEY* rawKey = nullptr;
		if (!generator || EVP_PKEY_keygen_init(generator.get()) <= 0 || EVP_PKEY_CTX_set_rsa_keygen_bits(generator.get(), 2048) <= 0 || EVP_PKEY_keygen(generator.get(), &rawKey) <= 0)
			throw std::runtime_error("TLS fixture key");
		std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> key(rawKey, &EVP_PKEY_free);
		OpenSSL::X509Ptr cert(X509_new(), &X509_free);
		if (!cert || !X509_set_version(cert.get(), 2) || !ASN1_INTEGER_set(X509_get_serialNumber(cert.get()), 1) ||
			!X509_gmtime_adj(X509_getm_notBefore(cert.get()), -60) || !X509_gmtime_adj(X509_getm_notAfter(cert.get()), 3600) || !X509_set_pubkey(cert.get(), key.get()))
			throw std::runtime_error("TLS fixture certificate");
		X509_NAME* name = X509_get_subject_name(cert.get());
		if (!X509_NAME_add_entry_by_txt(name, "CN", MBSTRING_ASC, reinterpret_cast<const unsigned char*>("localhost"), -1, -1, 0) ||
			!X509_set_issuer_name(cert.get(), name) || !X509_sign(cert.get(), key.get(), EVP_sha256()) ||
			!SSL_CTX_use_certificate(context.get(), cert.get()) || !SSL_CTX_use_PrivateKey(context.get(), key.get())) throw std::runtime_error("TLS fixture signing");
		listener = socket(AF_INET, SOCK_STREAM, 0);
		if (listener < 0) throw std::runtime_error("TLS fixture socket");
		sockaddr_in address{}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		if (bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) || listen(listener, 1))
		{
			close(listener); listener = -1; throw std::runtime_error("TLS fixture bind");
		}
		socklen_t length = sizeof(address);
		if (getsockname(listener, reinterpret_cast<sockaddr*>(&address), &length))
		{
			close(listener); listener = -1; throw std::runtime_error("TLS fixture address");
		}
		port = ntohs(address.sin_port);
		try { worker = std::thread([this] { Serve(); }); }
		catch (...) { close(listener); listener = -1; throw; }
	}
	~LoopbackTls()
	{
		stop.store(true); if (listener >= 0) shutdown(listener, SHUT_RDWR);
		if (worker.joinable()) worker.join(); if (listener >= 0) close(listener);
	}
private:
	int listener = -1; Mode mode; std::atomic<bool> stop{false}; std::thread worker;
	void Serve()
	{
		pollfd ready{listener, POLLIN, 0};
		while (!stop.load())
		{
			if (poll(&ready, 1, 50) <= 0) continue;
			int socket = accept(listener, nullptr, nullptr); if (socket < 0) break;
			timeval timeout{1, 0}; setsockopt(socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
			setsockopt(socket, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
			OpenSSL::SSLSessionPtr session(SSL_new(context.get()), &SSL_free);
			if (session && SSL_set_fd(session.get(), socket) && SSL_accept(session.get()) == 1)
			{
				negotiated.store(SSL_version(session.get()));
				if (mode == StallGreeting) { while (!stop.load()) std::this_thread::sleep_for(std::chrono::milliseconds(10)); }
				else
				{
					const char* greeting = "200 example fixture ready\r\n";
					SSL_write(session.get(), greeting, strlen(greeting));
					std::string line;
					while (!stop.load())
					{
						char byte;
						if (SSL_read(session.get(), &byte, 1) != 1) break;
						line.push_back(byte); if (line.size() > 4096) break;
						if (byte != '\n') continue;
						std::string reply;
						if (line.starts_with("AUTHINFO USER")) { ++authCommands; reply = "381 password required\r\n"; }
						else if (line.starts_with("AUTHINFO PASS")) { ++authCommands; reply = mode == BadLogin ? "502 rejected\r\n" : "281 accepted\r\n"; }
						else { ++articleCommands; reply = "500 no article commands permitted\r\n"; }
						SSL_write(session.get(), reply.data(), reply.size()); line.clear();
					}
				}
			}
			shutdown(socket, SHUT_RDWR); close(socket); ERR_clear_error(); break;
		}
	}
};

int ProbeFixture(OwnedBackend& backend, LoopbackTls& server, const char* suite, int protocol, uint64_t milliseconds = 1000,
	uint8_t verification = 0, NzbgetTlsCancelled cancel = [](void*) { return 0; }, void* cancelContext = nullptr,
	const char* addresses = "127.0.0.1")
{
	NzbgetTlsServer input{1, "localhost", server.port, 4, verification, "example", "example"};
	return backend.io.probe(backend.io.context, &input, suite, protocol, addresses, milliseconds, cancel, cancelContext);
}
}

BOOST_AUTO_TEST_CASE(TlsCryptoAuthenticatesEveryAdvertisedEligibleAlgorithm)
{
	OwnedBackend backend; BOOST_REQUIRE(TlsCipherBackend::Available());
	std::set<std::string> algorithms;
	BOOST_REQUIRE(backend.io.suites(backend.io.context,
		[](void* context, const char*, const char* algorithm, int protocol, unsigned bits, unsigned flags) {
			if (nzbget_rs_tls_cipher_pin(protocol, bits, flags)) static_cast<std::set<std::string>*>(context)->insert(algorithm);
			return 1;
		}, &algorithms) == 1);
	BOOST_REQUIRE(!algorithms.empty());
	for (const auto& algorithm : algorithms)
	{
		OwnedCrypto crypto{backend.io, backend.io.prepare(backend.io.context, algorithm.c_str())};
		BOOST_REQUIRE_MESSAGE(crypto.context, "Unmeasured advertised algorithm: " + algorithm);
		BOOST_CHECK(backend.io.record(crypto.context, 0) < 0);
		BOOST_REQUIRE(backend.io.prepare_batch(crypto.context, 0, 2) == 1);
		BOOST_CHECK_EQUAL(backend.io.record(crypto.context, 0), 16384);
		BOOST_CHECK_EQUAL(backend.io.record(crypto.context, 1), 16384);
		BOOST_CHECK(backend.io.record(crypto.context, 2) < 0);
		BOOST_CHECK(backend.io.prepare_batch(crypto.context, 0, 65) == 0);
		BOOST_CHECK(backend.io.prepare_batch(crypto.context, UINT64_MAX, 1) == 0);
		BOOST_REQUIRE(backend.io.prepare_batch(crypto.context, 2, 2) == 1);
		BOOST_CHECK_EQUAL(backend.io.record(crypto.context, 2), 16384);
	}
}

BOOST_AUTO_TEST_CASE(Tls12PinCannotNegotiateTls13Defaults)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_2_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_256_GCM_SHA384");
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "ECDHE-RSA-AES128-GCM-SHA256", 12), 1);
	BOOST_CHECK_EQUAL(fixture.negotiated.load(), TLS1_2_VERSION);
	BOOST_CHECK_EQUAL(fixture.authCommands.load(), 2);
	BOOST_CHECK_EQUAL(fixture.articleCommands.load(), 0);
}

BOOST_AUTO_TEST_CASE(Tls13PinCannotFallBackToTls12)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_2_VERSION, TLS1_2_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256");
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13), 0);
	BOOST_CHECK_EQUAL(fixture.authCommands.load(), 0);
}

BOOST_AUTO_TEST_CASE(TlsAuthenticationFailureIsUnknownNotUnsupported)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_3_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256", LoopbackTls::BadLogin);
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13), -5);
}

BOOST_AUTO_TEST_CASE(TlsGreetingDeadlineBoundsTheCompleteProbe)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_3_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256", LoopbackTls::StallGreeting);
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13, 100), -3);
}

BOOST_AUTO_TEST_CASE(TlsUntrustedCertificateIsUnknown)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_3_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256");
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13, 1000, 2), -4);
	BOOST_CHECK_EQUAL(fixture.authCommands.load(), 0);
}

BOOST_AUTO_TEST_CASE(TlsCancellationInterruptsGreeting)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_3_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256", LoopbackTls::StallGreeting);
	// Cancellation becomes true once the owned fixture completed its handshake.
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13, 1000, 0,
		[](void* context) { return static_cast<LoopbackTls*>(context)->negotiated.load() != 0 ? 1 : 0; }, &fixture), -6);
	BOOST_CHECK_EQUAL(fixture.authCommands.load(), 0);
}

BOOST_AUTO_TEST_CASE(TlsProbeTriesSecondResolvedAddressOfSameFamily)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_3_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256");
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13, 1000, 0,
		[](void*) { return 0; }, nullptr, "127.0.0.2\n127.0.0.1"), 1);
	BOOST_CHECK_EQUAL(fixture.negotiated.load(), TLS1_3_VERSION);
}

BOOST_AUTO_TEST_CASE(TlsEmptyResolvedAddressesCannotFallBackToBlockingDns)
{
	OwnedBackend backend;
	LoopbackTls fixture(TLS1_3_VERSION, TLS1_3_VERSION, "ECDHE-RSA-AES128-GCM-SHA256", "TLS_AES_128_GCM_SHA256");
	BOOST_CHECK_EQUAL(ProbeFixture(backend, fixture, "TLS_AES_128_GCM_SHA256", 13, 1000, 0,
		[](void*) { return 0; }, nullptr, ""), -2);
	BOOST_CHECK_EQUAL(fixture.negotiated.load(), 0);
}
#endif

BOOST_AUTO_TEST_SUITE_END()
