#ifndef NZBGET_RS_DUPESEARCH_NZB_H
#define NZBGET_RS_DUPESEARCH_NZB_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Terminal yEnc range after the C++ first-quote fast path.
 * Borrowed range inside the input. No allocation crosses the ABI. */
typedef struct { size_t start; size_t len; } NzbgetRsSubjectRange;
/* Inputs must provide len readable bytes; NULL is allowed only when len is zero. */
NzbgetRsSubjectRange nzbget_rs_dupesearch_unquoted_subject(const uint8_t* data, size_t len);
int32_t nzbget_rs_dupesearch_par_name(const uint8_t* data, size_t len);
#ifdef __cplusplus
}
#endif
#endif
