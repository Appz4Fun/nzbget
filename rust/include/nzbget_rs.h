// C ABI of the Rust parts of nzbget (rust/src/ffi.rs)
#ifndef NZBGET_RS_H
#define NZBGET_RS_H

#include <stddef.h>
#include <stdint.h>

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

// Util's string helpers (rust/src/util.rs). Format results are Rust-owned;
// copy and release with nzbget_rs_free. Numeric formatting uses LC_NUMERIC.
// Panics abort and never unwind through C++.
NzbgetRsBuf nzbget_rs_format_size(long long size);
NzbgetRsBuf nzbget_rs_format_speed(long long bytesPerSecond);
// NULL is treated as an empty string.
int nzbget_rs_alpha_num(const char* str);
// buffer is NULL (hashed as empty) or readable for (unsigned int)bufSize bytes.
unsigned int nzbget_rs_hash_bj96(const char* buffer, int bufSize, unsigned int initValue);
// Caller-owned writable NUL-terminated str; from/to are NUL-terminated and
// may point into str. Any NULL argument is a no-op. Empty patterns and growing
// replacements are no-ops; equal-length replacements retain C++ truncation.
void nzbget_rs_reduce_str(char* str, const char* from, const char* to);
// case folding: glibc's tolower table (*__ctype_tolower_loc()) or NULL for
// the callbacks: caseFold(byte 0..255) as strcasecmp, maskFold as WildMask's.
// Callbacks must not unwind or mutate input storage. They may both be NULL
// with a table; without a table either NULL callback returns false.
// NULL strings are empty; non-NULL strings must be readable and NUL-terminated.
int nzbget_rs_match_file_ext(const char* filename, const char* extensionList, const char* listSeparator,
	const int* table, int charSigned, int (*caseFold)(int), int (*maskFold)(int));

// URL::ParseUrl (rust/src/url.rs): parts (protocol, user, password, host,
// resource) as {start, length} in the address, start -1 when not set; a valid
// URL without a resource has resource start -1 (meaning "/")
typedef struct
{
	int valid;
	int port;
	ptrdiff_t parts[5][2];
} NzbgetRsUrlParts;
void nzbget_rs_parse_url(const char* address, NzbgetRsUrlParts* out);

// FeedFilter (rust/src/feedfilter.rs): the feed item stays in C++ and is read
// and changed through these callbacks, in the C++ order. Fields: title,
// filename, category, url, size, age, imdbid, rageid, tvdbid, tvmazeid,
// description, season, episode, priority, dupekey, dupescore, dupestatus,
// attr- (0..17). Match status: 0 ignored, 1 accepted, 2 rejected.
// Callbacks must not throw/unwind or reenter/free the same filter. Callback
// strings are borrowed: returned strings stay valid until the next callback;
// strings passed to callbacks are valid only for that call and must be copied
// if retained. regexNew handles must stay valid for this filter's lifetime.
typedef struct NzbgetRsFeedOptions
{
	int hasPause, pause;
	int hasCategory; const char* category;
	int hasPriority, priority;
	int hasAddPriority, addPriority;
	int hasDupeScore, dupeScore;
	int hasAddDupeScore, addDupeScore;
	int hasBuildDupeKey; const char* ids[4]; // rageid, tvdbid, tvmazeid, series
	int hasDupeKey; const char* dupeKey;
	int hasAddDupeKey; const char* addDupeKey;
	int hasDupeMode, dupeMode;
} NzbgetRsFeedOptions;
typedef struct NzbgetRsFeedItem
{
	void* user;
	void (*field)(void* user, int field, const char* attr, const char** str, long long* num);
	const char* (*seasonEpisode)(void* user, int episode);
	size_t (*regexNew)(void* user, const char* pattern, int bufSize);
	int (*regexMatch)(void* user, size_t regex, const char* text, int (*groups)[2], int capacity);
	void (*apply)(void* user, const NzbgetRsFeedOptions* options);
	void (*setMatch)(void* user, int status, int rule);
	const int* lowerTable; // *__ctype_tolower_loc() or NULL for fold
	int charSigned;
	int (*fold)(int);
} NzbgetRsFeedItem;
typedef struct NzbgetRsFeedFilter NzbgetRsFeedFilter;
// Copies filter (NULL means empty). The opaque handle is owned by Rust and
// must only be released with feed_filter_free; free(NULL) is harmless.
NzbgetRsFeedFilter* nzbget_rs_feed_filter_new(const char* filter);
void nzbget_rs_feed_filter_free(NzbgetRsFeedFilter* filter);
// NULL filter/item or missing callbacks are a no-op. All callbacks are
// required except fold when lowerTable is supplied. lowerTable points to
// entry zero of a valid int table spanning indices -128..255.
// Matching requires exclusive access to the filter and its regex handles.
void nzbget_rs_feed_filter_match(NzbgetRsFeedFilter* filter, const NzbgetRsFeedItem* item);

// Deobfuscation (rust/src/deobfuscation.rs): text as pointer and length.
// NULL means empty regardless of len; otherwise len bytes must be readable.
// Embedded NULs are preserved. Free the owned result with nzbget_rs_free.
int nzbget_rs_is_excessively_obfuscated(const char* str, size_t len);
NzbgetRsBuf nzbget_rs_deobfuscate(const char* str, size_t len);

// FileTypes (rust/src/filetypes.rs): name checks by number, in FileTypes.h's
// order (IsSevenZipExt 0 ... IsSampleFile 24); a sniffed extension is static
// ("" for none), its length in outLen. Inputs are borrowed byte spans; NULL
// means empty regardless of len. outLen may be NULL. Returned strings have
// static lifetime and must not be freed. Panics abort at the ABI boundary.
int nzbget_rs_file_type(int which, const char* str, size_t len);
const char* nzbget_rs_sniff_extension(const unsigned char* header, size_t len, size_t* outLen);

// FileSystem's path texts (rust/src/paths.rs): op 0 MakeValidFilename (flag:
// allow slashes), 1 SanitizePathSegment, 2 SanitizeRelativePath,
// 3 EscapePathForShell. Positions: op 0 BaseFileName's start, 1 the last
// '/' or '\\' (SIZE_MAX for none), 2 ExtractFilePathFromCmd's length.
// str is NULL (empty regardless of len) or readable for len bytes in one
// allocation, with len <= PTRDIFF_MAX. No input terminator is required.
// Text results own their storage; release exactly once with nzbget_rs_free.
// Panics/allocation failures abort; Rust never unwinds across this ABI.
NzbgetRsBuf nzbget_rs_path_text(int op, const char* str, size_t len, int flag);
size_t nzbget_rs_path_position(int op, const char* str, size_t len);
int nzbget_rs_reserved_char(char c);
// path is NULL (no-op) or a writable NUL-terminated string, owned by the caller.
void nzbget_rs_normalize_path_separators(char* path);

// CollectionAnalyzer (rust/src/collection.rs): files as text and length;
// an analysis by index (-1: none), index arrays with room for every file;
// a plan through callbacks (exists, ignored by the ignoreExt list, each
// rename), the effective base name returned (free with nzbget_rs_free).
// NULL files/text means empty, regardless of length. NULL analysis output is
// ignored; NULL index arrays report counts only. Non-NULL arrays hold count
// indices and must not overlap the output struct. NULL plan table/flags
// returns an empty buffer and clears non-NULL flags. NULL exists/ignored
// returns false; NULL action discards actions. Callback strings are borrowed
// only during each call; callbacks must not throw or invalidate table/flags.
// Panics abort; input storage remains caller-owned.
typedef struct
{
	const char* path; size_t pathLen;
	// UTF-8 parent_path() / "x", with the final "x" removed.
	const char* renamePrefix; size_t renamePrefixLen;
	const char* filename; size_t filenameLen;
	const char* stem; size_t stemLen;
	const char* ext; size_t extLen;
	unsigned long long size;
} NzbgetRsFileEntry;
typedef struct
{
	ptrdiff_t mainVideo, sampleVideo, mainBook;
	size_t* subtitles; size_t subtitleCount;
	size_t* nfos; size_t nfoCount;
	size_t* otherFiles; size_t otherCount;
	int ambiguous, discStructure, hasAudio;
} NzbgetRsAnalysis;
typedef struct
{
	void* user;
	int (*exists)(void* user, const char* path, size_t len);
	int (*ignored)(void* user, const char* path, size_t len);
	void (*action)(void* user, size_t file, const char* dstPath, size_t dstLen, const char* newName, size_t newLen);
	// the stem of a path as fs::path has it, into out (room for cap); returns
	// its length (more than cap: called again with that room); NULL: as is
	size_t (*stem)(void* user, const char* path, size_t len, char* out, size_t cap);
} NzbgetRsPlanCallbacks;
typedef struct
{
	int ambiguous, discStructure, canRename, targetNameObfuscated;
} NzbgetRsPlanFlags;
void nzbget_rs_collection_analyze(const NzbgetRsFileEntry* files, size_t count, NzbgetRsAnalysis* out);
NzbgetRsBuf nzbget_rs_collection_plan(const NzbgetRsFileEntry* files, size_t count, int discDir,
	const char* target, size_t targetLen, const NzbgetRsPlanCallbacks* callbacks, NzbgetRsPlanFlags* flags);
NzbgetRsBuf nzbget_rs_collection_name(int op, const char* a, size_t aLen, const char* b, size_t bLen,
	const char* c, size_t cLen);

// WebProcessor's request decisions (rust/src/webserver.rs). Header kinds:
// 0 other, 1 Content-Length (number), 2 credentials (value), 3 credentials
// too long, 4 Accept-Encoding (number: gzip), 5 Origin, 6 Auth-Token cookie,
// 7 X-Forwarded-For, 8 If-None-Match, 9 keep-alive, 10 end of headers
int nzbget_rs_web_header(const char* line, size_t len, int authInfoEmpty,
	size_t* valueStart, size_t* valueLen, int* number);
// NULL URL means empty; embedded NUL ends the URL. Outputs may be NULL.
// Free both returned buffers with nzbget_rs_free (including on exceptions).
NzbgetRsBuf nzbget_rs_web_parse_url(const char* url, size_t len, int* redirect, NzbgetRsBuf* auth);
typedef struct
{
	const char* users[6]; // control, restricted, add: username, password
	const char* authorizedIp;
	const char* remoteAddr;
	const char* authInfo;
	const char* authToken;
	const char* serverTokens[3];
	const int* lowerTable; // as for WildMask
	int charSigned;
	int (*fold)(int);
} NzbgetRsWebCredentials;
typedef struct
{
	int authorized;
	int access; // EUserAccess, -1 to leave it
	ptrdiff_t authCut; // where m_authInfo is cut, -1 for none
	int warn;
} NzbgetRsWebCheck;
// NULL input denies access; NULL out is a no-op. Output must not alias inputs.
void nzbget_rs_web_check_credentials(const NzbgetRsWebCredentials* input, NzbgetRsWebCheck* out);
int nzbget_rs_web_authorized_ip(const char* option, const char* remote, const int* table, int charSigned, int (*fold)(int));

// Decoder (rust/src/decoder.rs), with rapidyenc's incremental decoder (its
// state as an int) and CRC. Get: 0 format, 1 begin, 2 end, 3 size,
// 4 expected CRC, 5 calculated CRC, 6 EOF. Set: 0 CRC check, 1 raw mode.
// Handles are Rust-owned, freed once with decoder_free, never used concurrently.
// NULL callbacks make new return NULL; NULL handles/inputs are accepted as no-ops
// (check returns UnknownError, getters return zero/an empty borrowed string).
// decode: buffer is caller-owned and disjoint from the decoder. It must fit the
// input AND output (up to input length + 63 for a buffered UU line; Connection
// reserves 128). In line mode len==0 means strlen(buffer), as in StringBuilder.
// Negative lengths are ignored. Callbacks must not unwind; Rust panics abort.
// filename is borrowed until the decoder changes; do not free it.
typedef struct NzbgetRsDecoder NzbgetRsDecoder;
typedef int (*NzbgetRsYencDecode)(const void** src, void** dst, size_t len, int* state);
typedef unsigned int (*NzbgetRsCrc)(const void* src, size_t len, unsigned int init);
NzbgetRsDecoder* nzbget_rs_decoder_new(NzbgetRsYencDecode decode, NzbgetRsCrc crc);
void nzbget_rs_decoder_free(NzbgetRsDecoder* decoder);
void nzbget_rs_decoder_clear(NzbgetRsDecoder* decoder);
int nzbget_rs_decoder_decode(NzbgetRsDecoder* decoder, char* buffer, int len);
int nzbget_rs_decoder_check(NzbgetRsDecoder* decoder);
void nzbget_rs_decoder_set(NzbgetRsDecoder* decoder, int which, int value);
long long nzbget_rs_decoder_get(NzbgetRsDecoder* decoder, int which);
const char* nzbget_rs_decoder_filename(NzbgetRsDecoder* decoder);

// Scheduler::CheckTasks' timing (rust/src/scheduler.rs): which tasks are due
// between *lastCheck and current. Local times use separate offset readings:
// current + currentOffset and *lastCheck + lastCheckOffset, as in C++. Updates the
// tasks' lastExecuted and *lastCheck, writes the due task indexes in execution
// order to due (room for dueCapacity) and returns how many; *reset tells whether
// the clock jumped (> 90 minutes or back) and a week was rechecked.
// If the return value exceeds dueCapacity, no outputs change; retry with that
// many entries. count * 9 is a usual capacity, not a bound for every libc TZif.
// All buffers are disjoint and caller-owned. NULL lastCheck/reset, or NULL
// tasks with nonzero count, or NULL due with nonzero dueCapacity, returns 0
// without changing outputs. With zero count/capacity, tasks/due may be NULL.
// Unrepresentable buffer sizes are also rejected.
typedef struct NzbgetRsSchedTask
{
	int hours; // -1: startup task
	int minutes;
	int weekDays; // bit n: weekday n + 1 (1 Monday .. 7 Sunday); 0: all
	long long lastExecuted;
} NzbgetRsSchedTask;
// Calendar conversion stays in libc: leap-aware TZif files affect gmtime_r.
// year is the full year; mon is 0..11 and wday is 0 (Sunday)..6.
typedef struct NzbgetRsSchedTm
{
	long long year, mon, mday, hour, min, sec, wday;
} NzbgetRsSchedTm;
// gmtime must fill all fields and must not throw. NULL is rejected atomically.
size_t nzbget_rs_scheduler_check(NzbgetRsSchedTask* tasks, size_t count, long long* lastCheck, long long current, long long currentOffset, long long lastCheckOffset, size_t* due, size_t dueCapacity, int* reset, void (*gmtime)(long long, NzbgetRsSchedTm*));

// XmlCommand's request parameters (rust/src/rpcparams.rs), parsed in place in
// the writable NUL-terminated request. skip_to_params: PrepareParams for a JSON
// POST (the position after "params", or the request emptied). next_param: what
// 0 int, 1 bool (0/1 in *intValue), 2 string (*strValue points into the
// request); get: a GET query string, else json: JSON-RPC, else XML-RPC. Moves
// *request past the parameter; returns 1 with a value, else 0.
// NULL request, *request or the required value output, and unknown what, are
// rejected without mutation. Outputs and pointer slots must be disjoint from
// each other and the request buffer. Storage stays caller-owned; string results
// borrow the request and must not be freed. Panics cannot unwind across the ABI.
char* nzbget_rs_rpc_skip_to_params(char* request);
int nzbget_rs_rpc_next_param(char** request, int get, int json, int what, int* intValue, char** strValue);

// XmlRpcProcessor's routing (rust/src/rpcroute.rs). protocol: the
// ERpcProtocol of an RPC URL (rpUndefined if none). route: Dispatch's method
// name (into a 100-byte buffer), where the parameters start (*params, into url
// for GET, else request) and the JSON-RPC id (*id, *idLen; null if none or its
// legacy C-int length exceeds 4096). Inputs may be NULL (empty), otherwise
// they are NUL-terminated. All output pointers must be non-NULL, writable,
// and disjoint; methodName has at least 100 bytes. params/id borrow the
// caller's input storage; do not free them or retain them beyond its lifetime.
// envelope: BuildResponse's text before (head) and after (tail) the response;
// each result owns its buffer, independently of the inputs. Free both exactly
// once with nzbget_rs_free. Panics abort; unwinding never crosses the ABI.
int nzbget_rs_rpc_protocol(const char* url);
void nzbget_rs_rpc_route(const char* url, const char* request, int get, int protocol, char* methodName, const char** params, const char** id, int* idLen);
void nzbget_rs_rpc_envelope(int protocol, int fault, const char* callback, const char* id, NzbgetRsBuf* head, NzbgetRsBuf* tail);

// Util text helpers (rust/src/util.rs). split_command_line: the words, each
// NUL-terminated, back to back (len covers all). trim_line: TrimRight(char*)
// (rightOnly) or Trim(char*) in place, returning the start. trim_string:
// TrimLeft/TrimRight/Trim of a std::string, or SanitizeLine (which blanks
// control characters in place): the kept range [*start, result). ends_with:
// EndsWith on byte ranges. parse_rfc822_date_time: WebUtil's, 0 if invalid.
// NULL inputs are empty; trim_line(NULL) returns NULL. trim_string accepts a
// NULL start output; rightSpace classifies unsigned bytes as the caller's char
// in its current C locale (NULL means no right whitespace). The callback must
// not throw or access the buffer. All input buffers remain caller-owned.
// Rust panics abort and never unwind across the ABI.
// Free returned buffers with nzbget_rs_free.
NzbgetRsBuf nzbget_rs_split_command_line(const char* s);
char* nzbget_rs_trim_line(char* s, int rightOnly);
size_t nzbget_rs_trim_string(char* data, size_t len, int left, int right, int sanitize, size_t* start, int (*rightSpace)(int));
int nzbget_rs_ends_with(const char* s, size_t len, const char* suffix, size_t suffixLen, int caseSensitive);
NzbgetRsBuf nzbget_rs_format_buffer(const char* buf, int len);
long long nzbget_rs_parse_rfc822_date_time(const char* s);

// ServerVolume's slots (rust/src/statmeter.rs). calc_slots: CalcSlots for a
// local time (cut to an int as before), updating *firstDay; day is -1 outside
// the 20 years from 2013, inRange tells whether the day arrays may grow.
// volume_add: AddStats' clearing of the second/minute/hour slots passed since
// locDataTime, then adding bytes at the slots; slots outside an array (a time
// before 1970 or after 2038-01-19 as an int) are skipped.
// Arrays stay caller-owned, must be disjoint and writable for their lengths
// (in int64_t elements). NULL arrays are ignored; NULL slots makes add a no-op.
// The slots descriptor is copied before accessing arrays and may overlap one.
// calc_slots is a no-op if either output pointer is NULL.
typedef struct NzbgetRsVolumeSlots
{
	int sec, min, hour, day, inRange;
} NzbgetRsVolumeSlots;
void nzbget_rs_volume_calc_slots(long long locCurTime, int* firstDay, NzbgetRsVolumeSlots* slots);
void nzbget_rs_volume_add(int64_t* seconds, size_t secondsLen, int64_t* minutes, size_t minutesLen,
	int64_t* hours, size_t hoursLen, const NzbgetRsVolumeSlots* slots, int lastMinSlot, int lastHourSlot,
	long long locCurTime, long long locDataTime, int64_t bytes);

// Options' value parsers (rust/src/options.rs). parse_time/parse_week_days
// write their outputs as the C++ did, also on failure. validate_option_name:
// 0 invalid, 1 valid, 2 obsolete (warn), 3 obsolete script option (error with
// a value), 4 obsolete log option; predefined(ctx, name) is GetOption's answer.
// convert_old_option: the current name and value (free with nzbget_rs_free).
// NULL inputs mean empty strings; NULL outputs discard the corresponding result.
// Identical output pointers retain only the new value. Previous output buffers
// are not freed. Non-NULL outputs must be writable and disjoint from inputs;
// they must be either identical or disjoint from each other.
// parse_time: NULL arguments return 0 without writes; outputs may alias each other.
// parse_week_days: NULL input means empty; NULL output returns 0.
// validate_option_name: NULL name is invalid; NULL callback means not predefined.
// The callback must not unwind or modify/invalidate name; ctx is caller-owned.
// has_script: NULL inputs mean empty. parse_category_source: NULL means NZBFile.
// parse_category_source: FeedInfo::CategorySource (0 Auto, 1 NZBFile, 2 FeedFile).
int nzbget_rs_parse_time(const char* time, int* hours, int* minutes);
int nzbget_rs_parse_week_days(const char* weekDays, int* bits);
int nzbget_rs_validate_option_name(const char* name, int (*predefined)(void* ctx, const char* name), void* ctx);
void nzbget_rs_convert_old_option(const char* option, const char* value, NzbgetRsBuf* newOption, NzbgetRsBuf* newValue);
int nzbget_rs_has_script(const char* list, const char* name);
int nzbget_rs_parse_category_source(const char* value);

#ifdef __cplusplus
}
#endif

#endif
