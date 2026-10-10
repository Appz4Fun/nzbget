// Linked by paths_differential.py with --wrap=nzbget_rs_free on Linux.
#include "nzbget.h"
#include "FileSystem.h"
#include "nzbget_rs.h"
#include <new>

static bool failNextNew = false;
static int released = 0;

void* operator new(std::size_t size)
{
	if (failNextNew)
	{
		failNextNew = false;
		throw std::bad_alloc();
	}
	if (void* p = std::malloc(size ? size : 1)) return p;
	throw std::bad_alloc();
}

void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }

extern "C" void __real_nzbget_rs_free(NzbgetRsBuf);
extern "C" void __wrap_nzbget_rs_free(NzbgetRsBuf buf)
{
	++released;
	__real_nzbget_rs_free(buf);
}

int main()
{
	// Longer than small-string storage, so each result copy must allocate.
	const std::string input(200, 'x');
	for (int op = 0; op < 3; ++op)
	{
		const int before = released;
		bool threw = false;
		failNextNew = true;
		try
		{
			switch (op)
			{
				case 0: FileSystem::SanitizePathSegment(input); break;
				case 1: FileSystem::SanitizeRelativePath(input); break;
				case 2: FileSystem::EscapePathForShell(input); break;
			}
		}
		catch (const std::bad_alloc&) { threw = true; }
		failNextNew = false;
		if (!threw || released != before + 1)
		{
			std::fprintf(stderr, "Rust path buffer leaked on allocation failure (op %d)\n", op);
			return 1;
		}
	}
	std::puts("Rust path buffers released on allocation failure");
}
