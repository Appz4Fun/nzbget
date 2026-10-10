// Standalone wrapper test, compiled by deobfuscation_differential.py.
// Stub the Rust ABI to observe release when C++ string allocation fails.
#include "nzbget.h"
#include "Deobfuscation.h"
#include "nzbget_rs.h"
#include <cstdlib>
#include <new>

static bool failAllocation = false;
static int releases = 0;
static char resultBytes[1025];

void* operator new(std::size_t size)
{
	if (failAllocation) throw std::bad_alloc();
	if (void* p = std::malloc(size ? size : 1)) return p;
	throw std::bad_alloc();
}

void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }

extern "C" NzbgetRsBuf nzbget_rs_deobfuscate(const char*, size_t)
{
	return {resultBytes, 1024, sizeof(resultBytes)};
}

extern "C" int nzbget_rs_is_excessively_obfuscated(const char*, size_t) { return 0; }

extern "C" void nzbget_rs_free(NzbgetRsBuf buf)
{
	if (buf.data != resultBytes || buf.len != 1024 || buf.cap != sizeof(resultBytes)) std::abort();
	++releases;
}

int main()
{
	failAllocation = true;
	try
	{
		Deobfuscation::Deobfuscate("subject");
		return 1;
	}
	catch (const std::bad_alloc&)
	{
		failAllocation = false;
		if (releases != 1) return 2;
	}
	auto result = Deobfuscation::Deobfuscate("subject");
	if (result.size() != 1024 || releases != 2) return 3;
	return 0;
}
