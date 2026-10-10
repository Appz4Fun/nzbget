// C ABI of the Rust parts of nzbget (rust/src/ffi.rs)
#ifndef NZBGET_RS_H
#define NZBGET_RS_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
	char* data; // NUL-terminated
	size_t len;
	size_t cap;
} NzbgetRsBuf;

NzbgetRsBuf nzbget_rs_json_encode(const char* raw);
NzbgetRsBuf nzbget_rs_xml_encode(const char* raw);
void nzbget_rs_free(NzbgetRsBuf buf);

#ifdef __cplusplus
}
#endif

#endif
