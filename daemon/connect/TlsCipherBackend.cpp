#include "nzbget.h"
#include "TlsCipherBackend.h"
#if defined(NZBGET_USE_RUST) && !defined(DISABLE_TLS) && (defined(__APPLE__) || defined(__linux__))
#include "nzbget_rs.h"
#include "ScriptConfig.h"
#include "TlsSocket.h"
#include "NntpConnection.h"
#include "OpenSSL.h"
#include <openssl/rand.h>
#include <array>
#include <limits>

namespace
{
constexpr int RecordSize = 16384;
struct Context { std::string snapshot; };
struct Crypto
{
	const EVP_CIPHER* cipher = nullptr;
	OpenSSL::EVPCipherCtxPtr encrypt{EVP_CIPHER_CTX_new(), &EVP_CIPHER_CTX_free};
	OpenSSL::EVPCipherCtxPtr decrypt{EVP_CIPHER_CTX_new(), &EVP_CIPHER_CTX_free};
	std::array<unsigned char, 64> key{};
	std::array<unsigned char, 4> prefix{};
	std::array<unsigned char, RecordSize> plaintext{};
	std::array<unsigned char, RecordSize + EVP_MAX_BLOCK_LENGTH> output{};
	std::vector<std::array<unsigned char, RecordSize + EVP_MAX_BLOCK_LENGTH>> ciphertext;
	std::vector<std::array<unsigned char, 16>> tags;
	std::vector<std::array<unsigned char, 12>> nonces;
	uint64_t first = 0;
	int tagSize = 16;
	bool ccm = false;
	bool encryptKeyed = false, decryptKeyed = false;
	~Crypto() { OPENSSL_cleanse(key.data(), key.size()); }
	bool Init(std::string name)
	{
		if (name.ends_with("@8")) { tagSize = 8; name.resize(name.size() - 2); }
		cipher = EVP_get_cipherbyname(name.c_str());
		if (!cipher || !encrypt || !decrypt) return false;
		int mode = EVP_CIPHER_mode(cipher), keySize = EVP_CIPHER_key_length(cipher);
		ccm = mode == EVP_CIPH_CCM_MODE;
		if (mode != EVP_CIPH_GCM_MODE && !ccm && EVP_CIPHER_nid(cipher) != NID_chacha20_poly1305) return false;
		if (keySize <= 0 || keySize > static_cast<int>(key.size()) || RAND_bytes(key.data(), keySize) != 1 || RAND_bytes(prefix.data(), prefix.size()) != 1) return false;
		for (int i = 0; i < RecordSize; ++i) plaintext[i] = static_cast<unsigned char>((i * 31 + i / 251) & 255);
		return EVP_EncryptInit_ex(encrypt.get(), cipher, nullptr, nullptr, nullptr) == 1 &&
			EVP_DecryptInit_ex(decrypt.get(), cipher, nullptr, nullptr, nullptr) == 1 &&
			EVP_CIPHER_CTX_ctrl(encrypt.get(), EVP_CTRL_AEAD_SET_IVLEN, 12, nullptr) == 1 &&
			EVP_CIPHER_CTX_ctrl(decrypt.get(), EVP_CTRL_AEAD_SET_IVLEN, 12, nullptr) == 1;
	}
	bool Prepare(uint64_t sequence, uint32_t count)
	{
		if (count == 0 || count > 64 || sequence > std::numeric_limits<uint64_t>::max() - count) return false;
		first = sequence; ciphertext.resize(count); tags.resize(count); nonces.resize(count);
		for (uint32_t i = 0; i < count; ++i)
		{
			auto& nonce = nonces[i]; std::copy(prefix.begin(), prefix.end(), nonce.begin());
			for (unsigned j = 0; j < 8; ++j) nonce[11 - j] = static_cast<unsigned char>((sequence + i) >> (j * 8));
			int size = 0, tail = 0;
			unsigned char aad[5]{23, 3, 3, 0x40, static_cast<unsigned char>(tagSize)};
			if (ccm && EVP_CIPHER_CTX_ctrl(encrypt.get(), EVP_CTRL_AEAD_SET_TAG, tagSize, nullptr) != 1) return false;
			if (EVP_EncryptInit_ex(encrypt.get(), nullptr, nullptr, encryptKeyed ? nullptr : key.data(), nonce.data()) != 1) return false;
			encryptKeyed = true;
			if (ccm && EVP_EncryptUpdate(encrypt.get(), nullptr, &size, nullptr, RecordSize) != 1) return false;
			if (EVP_EncryptUpdate(encrypt.get(), nullptr, &size, aad, sizeof(aad)) != 1 ||
				EVP_EncryptUpdate(encrypt.get(), ciphertext[i].data(), &size, plaintext.data(), RecordSize) != 1 || size != RecordSize ||
				EVP_EncryptFinal_ex(encrypt.get(), ciphertext[i].data() + size, &tail) != 1 || tail != 0 ||
				EVP_CIPHER_CTX_ctrl(encrypt.get(), EVP_CTRL_AEAD_GET_TAG, tagSize, tags[i].data()) != 1) return false;
		}
		// Require authentication failure to reject a corrupted tag, then prove the
		// reusable context still decrypts the restored record before timing it.
		if (Record(sequence) != RecordSize) return false;
		tags[0][0] ^= 1;
		bool rejected = Record(sequence) == -1;
		tags[0][0] ^= 1;
		ERR_clear_error();
		return rejected && Record(sequence) == RecordSize;
	}
	int Record(uint64_t sequence)
	{
		if (sequence < first || sequence - first >= ciphertext.size()) return -1;
		size_t i = static_cast<size_t>(sequence - first);
		unsigned char aad[5]{23, 3, 3, 0x40, static_cast<unsigned char>(tagSize)};
		int size = 0, tail = 0;
		if (ccm && EVP_CIPHER_CTX_ctrl(decrypt.get(), EVP_CTRL_AEAD_SET_TAG, tagSize, tags[i].data()) != 1) return -1;
		if (EVP_DecryptInit_ex(decrypt.get(), nullptr, nullptr, decryptKeyed ? nullptr : key.data(), nonces[i].data()) != 1) return -1;
		decryptKeyed = true;
		if (ccm && EVP_DecryptUpdate(decrypt.get(), nullptr, &size, nullptr, RecordSize) != 1) return -1;
		if (EVP_DecryptUpdate(decrypt.get(), nullptr, &size, aad, sizeof(aad)) != 1 ||
			EVP_DecryptUpdate(decrypt.get(), output.data(), &size, ciphertext[i].data(), RecordSize) != 1 || size != RecordSize) return -1;
		if (!ccm && (EVP_CIPHER_CTX_ctrl(decrypt.get(), EVP_CTRL_AEAD_SET_TAG, tagSize, tags[i].data()) != 1 ||
			EVP_DecryptFinal_ex(decrypt.get(), output.data() + size, &tail) != 1 || tail != 0)) return -1;
		return memcmp(output.data(), plaintext.data(), RecordSize) == 0 ? RecordSize : -1;
	}
};

int Snapshot(void* context, const unsigned char** data, size_t* length) noexcept
{
	try
	{
		auto& value = static_cast<Context*>(context)->snapshot;
		if (!g_ScriptConfig->ReadCipherSnapshot(value)) return 0;
		*data = reinterpret_cast<const unsigned char*>(value.data()); *length = value.size(); return 1;
	}
	catch (...) { return 0; }
}
int Suites(void*, NzbgetTlsEmitSuite emit, void* context) noexcept
{
	try
	{
		OpenSSL::SSLCtxPtr tls(SSL_CTX_new(TLS_method()), &SSL_CTX_free);
		if (!tls) return 0;
		int minimum = SSL_CTX_get_min_proto_version(tls.get()), maximum = SSL_CTX_get_max_proto_version(tls.get());
		const auto* suites = SSL_CTX_get_ciphers(tls.get());
		for (int i = 0; i < sk_SSL_CIPHER_num(suites); ++i)
		{
			const auto* suite = sk_SSL_CIPHER_value(suites, i);
			bool tls13 = !strcmp(SSL_CIPHER_get_version(suite), "TLSv1.3");
			int version = tls13 ? TLS1_3_VERSION : TLS1_2_VERSION;
			if ((minimum && version < minimum) || (maximum && version > maximum)) continue;
			int auth = SSL_CIPHER_get_auth_nid(suite), kx = SSL_CIPHER_get_kx_nid(suite);
			bool certificate = tls13 || auth == NID_auth_rsa || auth == NID_auth_ecdsa;
			bool ephemeral = tls13 || kx == NID_kx_ecdhe || kx == NID_kx_dhe;
			unsigned flags = (SSL_CIPHER_is_aead(suite) ? 1 : 0) | (certificate ? 2 : 0) | (ephemeral ? 4 : 0);
			const EVP_CIPHER* bulk = EVP_get_cipherbynid(SSL_CIPHER_get_cipher_nid(suite));
			std::string name = bulk ? EVP_CIPHER_name(bulk) : "unavailable";
			if (strstr(SSL_CIPHER_get_name(suite), "CCM8")) name += "@8";
			// CCM8 has a 64-bit authentication tag despite a 128/256-bit AES key.
			unsigned bits = strstr(SSL_CIPHER_get_name(suite), "CCM8") ? 64 : SSL_CIPHER_get_bits(suite, nullptr);
			if (!emit(context, SSL_CIPHER_get_name(suite), name.c_str(), tls13 ? 13 : 12, bits, flags)) return 0;
		}
		return 1;
	}
	catch (...) { return 0; }
}
void* Prepare(void*, const char* algorithm) noexcept
{
	try { auto crypto = std::make_unique<Crypto>(); return crypto->Init(algorithm) ? crypto.release() : nullptr; }
	catch (...) { return nullptr; }
}
int PrepareBatch(void* context, uint64_t first, uint32_t count) noexcept
{
	try { return static_cast<Crypto*>(context)->Prepare(first, count) ? 1 : 0; } catch (...) { return 0; }
}
int Record(void* context, uint64_t sequence) noexcept
{
	try { return static_cast<Crypto*>(context)->Record(sequence); } catch (...) { return -1; }
}
void FreeCrypto(void* context) noexcept { delete static_cast<Crypto*>(context); ERR_clear_error(); }

class ProbeConnection final : public NntpConnection
{
public:
	explicit ProbeConnection(NewsServer* server) : NntpConnection(server) {}
protected:
	void PrintError(const char*) override {} // Never return provider text/credentials.
};
int Probe(void*, const NzbgetTlsServer* server, const char* cipher, int protocol, const char* numeric,
	uint64_t milliseconds, NzbgetTlsCancelled cancel, void* cancelContext) noexcept
{
	try
	{
		if (cancel(cancelContext)) return -6;
		if (milliseconds == 0) return -3;
		if (milliseconds > 10000) return -1;
		if (server->verification && !TlsSocket::HasCertificateStore()) return -4;
		auto deadline = std::make_shared<SocketDeadline>();
		deadline->end = std::chrono::steady_clock::now() + std::chrono::milliseconds(milliseconds);
		deadline->cancelled = [=] { return cancel(cancelContext) != 0; };
		NewsServer value(server->id, true, "TLS cipher probe", server->host, server->port, server->ip_version,
			server->username, server->password, false, true, cipher, 1, 0, 0, 0, false, server->verification);
		ProbeConnection connection(&value);
		std::vector<std::string> addresses;
		std::string remaining(numeric);
		for (size_t pos = 0; pos < remaining.size();)
		{
			size_t end = remaining.find('\n', pos);
			addresses.push_back(remaining.substr(pos, end == std::string::npos ? end : end - pos));
			if (end == std::string::npos) break; pos = end + 1;
		}
		if (addresses.empty() || addresses.size() > 16) return -2;
		connection.SetResolvedAddresses(addresses); connection.SetDeadline(deadline);
		connection.SetSuppressErrors(true); connection.SetTimeout(10);
		bool connected = connection.Connect();
		int result = connected && !strcmp(connection.GetNegotiatedCipher(), cipher) &&
			connection.GetNegotiatedVersion() == (protocol == 13 ? TLS1_3_VERSION : TLS1_2_VERSION) ? 1 :
			connection.GetAuthError() ? -5 : connection.GetTlsProbeFailure();
		if (cancel(cancelContext)) result = -6;
		else if (std::chrono::steady_clock::now() >= deadline->end) result = -3;
		connection.SetBroken(); connection.Disconnect();
		return result;
	}
	catch (...) { ERR_clear_error(); return -1; }
}
int Commit(void*, const unsigned char* original, size_t originalLength, const unsigned char* replacement, size_t replacementLength,
	NzbgetTlsCancelled cancel, void* cancelContext) noexcept
{
	try
	{
		auto result = g_ScriptConfig->CommitCipherPatch(
			std::string_view(reinterpret_cast<const char*>(original), originalLength),
			std::string_view(reinterpret_cast<const char*>(replacement), replacementLength), [=] { return cancel(cancelContext) != 0; });
		switch (result)
		{
			case ScriptConfig::CipherCommit::Saved: return 1;
			case ScriptConfig::CipherCommit::Unchanged: return 0;
			case ScriptConfig::CipherCommit::Conflict: return -2;
			case ScriptConfig::CipherCommit::Cancelled: return -3;
			default: return -1;
		}
	}
	catch (...) { return -1; }
}
void Destroy(void* context) noexcept { delete static_cast<Context*>(context); }
std::string Response(NzbgetRsBuf value)
{
	struct Release { NzbgetRsBuf value; ~Release() { nzbget_rs_free(value); } } release{value};
	return std::string(value.data, value.len);
}
}
bool TlsCipherBackend::Available() { return true; }
std::string TlsCipherBackend::Start()
{
	NzbgetTlsBackend io = Create();
	return Response(nzbget_rs_tls_cipher_start(&io));
}
NzbgetTlsBackend TlsCipherBackend::Create()
{
	return {new Context(), Snapshot, Suites, Prepare, PrepareBatch, Record, FreeCrypto, Probe, Commit, Destroy};
}
std::string TlsCipherBackend::Status(const char* id) { return Response(nzbget_rs_tls_cipher_status(id)); }
std::string TlsCipherBackend::Cancel(const char* id) { return Response(nzbget_rs_tls_cipher_cancel(id)); }
void TlsCipherBackend::Shutdown() { nzbget_rs_tls_cipher_shutdown(); }
#else
bool TlsCipherBackend::Available() { return false; }
std::string TlsCipherBackend::Status(const char*) { return R"({"Available":false,"State":"unavailable","Message":"TLS cipher optimization requires a TLS-enabled Rust backend and a supported atomic configuration adapter."})"; }
std::string TlsCipherBackend::Start() { return Status(nullptr); }
std::string TlsCipherBackend::Cancel(const char*) { return Status(nullptr); }
void TlsCipherBackend::Shutdown() {}
#ifdef NZBGET_USE_RUST
NzbgetTlsBackend TlsCipherBackend::Create() { return {}; }
#endif
#endif
