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

// RPC request decoders (rust/src/decode.rs), as WebUtil's:
// All buffers remain caller-owned; these functions allocate no result buffers.
// Base64: NULL input returns 0. Otherwise input is readable for length bytes,
// or, when length <= 0, through the NUL (strlen is truncated to uint32 as in
// C++). Output has room for len / 4 * 3 bytes, and is input or disjoint from it.
// Returns bytes written, without a terminator.
unsigned int nzbget_rs_decode_base64(const char* input, int length, char* output);
// raw is NULL (no-op) or a writable NUL-terminated string, decoded in place.
void nzbget_rs_json_decode(char* raw);
// text is NULL or NUL-terminated; valueLength is NULL or a writable int.
// Returns a pointer into text, or NULL on failure (including either NULL
// argument). Leaves valueLength unchanged on failure.
const char* nzbget_rs_json_next_value(const char* text, int* valueLength);

// CRC-32 of A followed by B from CRC(A), CRC(B) and B's length
// (rust/src/crc.rs); a length of 0 returns crc1
unsigned int nzbget_rs_crc32_combine(unsigned int crc1, unsigned int crc2, unsigned int len2);

// WebUtil's text helpers (rust/src/text.rs): the in-place ones take NULL (no-op)
// or a caller-owned writable NUL-terminated string. Panics abort.
// lower receives an ASCII hex letter and returns the caller's tolower result.
// It must not unwind or access raw. NULL lower is a no-op.
void nzbget_rs_xml_decode(char* raw, int (*lower)(int));
void nzbget_rs_xml_strip_tags(char* raw);
// isAlpha receives a byte in 0..255 and classifies it using the caller's locale
// and char signedness. It must not unwind or access raw. NULL isAlpha is a no-op.
void nzbget_rs_xml_remove_entities(char* raw, int (*isAlpha)(int));
void nzbget_rs_http_unquote(char* raw);
void nzbget_rs_url_decode(char* raw);
// NULL input means empty. Results are Rust-owned NUL-terminated buffers:
// copy before freeing with nzbget_rs_free, never with the C allocator.
NzbgetRsBuf nzbget_rs_url_encode(const char* raw);
NzbgetRsBuf nzbget_rs_latin1_to_utf8(const char* raw);

// WebUtil's finders (rust/src/webutil.rs): a pointer into the text and the
// value length, or NULL with valueLength untouched
const char* nzbget_rs_xml_find_tag(const char* xml, const char* tag, int* valueLength);
const char* nzbget_rs_json_find_field(const char* text, const char* field, int* valueLength);
// WebUtil::ParseContentDispositionFilename: data is NULL for no file name.
// Case folding as strncasecmp: glibc's tolower table (*__ctype_tolower_loc(),
// entries -128..255) indexed by unsigned byte, or fold(byte 0..255) when NULL.
NzbgetRsBuf nzbget_rs_content_disposition_filename(const char* contentDisposition,
	const int* table, int (*fold)(int));

#ifdef __cplusplus
}
#endif

#endif
