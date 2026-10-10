// C ABI of the Rust parts of nzbget (rust/src/ffi.rs)
#ifndef NZBGET_RS_H
#define NZBGET_RS_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
	char* data; // Rust-owned, NUL-terminated; never pass to free()/realloc()
	size_t len;
	size_t cap;
} NzbgetRsBuf;

// raw may be NULL (treated as empty); otherwise it must point to a readable
// NUL-terminated string for the duration of the call. Results own their storage.
// Allocation failure or a Rust panic aborts; unwinding never crosses this ABI.
NzbgetRsBuf nzbget_rs_json_encode(const char* raw);
NzbgetRsBuf nzbget_rs_xml_encode(const char* raw);
// Release each result exactly once, with all fields unchanged. A zero buffer
// is also accepted. Copy the bytes before freeing if they must outlive the result.
void nzbget_rs_free(NzbgetRsBuf buf);

typedef struct
{
	int matched;
	size_t count;
} NzbgetRsWildResult;

// NULL pattern/text mean empty strings; otherwise they must be NUL-terminated.
// table: glibc's tolower table of the calling thread (*__ctype_tolower_loc(),
// valid for indexes -128..255; char_signed: CHAR_MIN < 0 of the caller), or NULL to use fold(byte 0..255), which returns
// tolower of that byte as the caller's char in the current locale.
// fold may be NULL when table is supplied. If both are NULL, returns {0, 0}
// without writing positions.
// positions is caller-owned writable storage for capacity pairs, disjoint from
// the inputs. NULL disables positions. Both result fields are valid on failure.
// count is the TOTAL capture count, even if only capacity pairs could be written;
// retry with count pairs if needed. Panics abort; no unwinding crosses the ABI.
NzbgetRsWildResult nzbget_rs_wild_match(const char* pattern, const char* text,
	int (*positions)[2], size_t capacity, const int* table, int char_signed, int (*fold)(int));

#ifdef __cplusplus
}
#endif

#endif
