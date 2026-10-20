#ifndef NZBGET_TLS_CIPHER_BACKEND_H
#define NZBGET_TLS_CIPHER_BACKEND_H
#include <string>
#ifdef NZBGET_USE_RUST
#include "nzbget_rs.h"
#endif
namespace TlsCipherBackend
{
	bool Available();
	std::string Start();
	std::string Status(const char* id);
	std::string Cancel(const char* id);
	void Shutdown();
#ifdef NZBGET_USE_RUST
	// Owned callback table; caller transfers it to Rust or invokes destroy once.
	NzbgetTlsBackend Create();
#endif
}
#endif
