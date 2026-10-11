// C ABI of the Rust parts of nzbget (rust/src/ffi.rs)
#ifndef NZBGET_RS_H
#define NZBGET_RS_H

#include <stdbool.h>
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
// Twins and alts (rust/src/twin.rs). Lists are text lines: a file list is
// "length\tmd5\tname" per file. A download is given by its id and its
// identity "fingerprint#posting" (DupeFiles and the posting's message-id
// hash): a stored list is used only for the posting it was made for.
void nzbget_rs_twin_open(const char* path);
// returns "fingerprint\tcomplete" (complete: 1 or 0)
NzbgetRsBuf nzbget_rs_twin_put_par2(int id, const char* posting, const unsigned char* data, size_t len);
// 0: no list stored for this fingerprint, 1: a partial one, 2: a complete one
int nzbget_rs_twin_has(int id, const char* print);
// keeps the lists of the postings given as "id\tfingerprint" lines
void nzbget_rs_twin_prune(const char* lines);
NzbgetRsBuf nzbget_rs_twin_par2_sigs(const unsigned char* data, size_t len);
NzbgetRsBuf nzbget_rs_twin_fingerprint(const char* lines);
unsigned long long nzbget_rs_par2_block_size(const unsigned char* data, size_t len);
int nzbget_rs_par2_volume_blocks(const char* filename);
NzbgetRsBuf nzbget_rs_twin_kind(int primary, const char* primaryPrint, int dupe, const char* dupePrint);
NzbgetRsBuf nzbget_rs_twin_match(int own, const char* ownPrint, const char* target, const char* targetAlt,
	int donor, const char* donorPrint);
// "F\tsize\tpar2\tfilename\tsubject" per <file>, then "G\tgroup" and "S\tbytes\tmessage-id"
NzbgetRsBuf nzbget_rs_nzb_entries(const char* path);
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
// line is NULL (empty) or len initialized bytes. Tests stop at its first NUL;
// a locale-induced early match still reads the value at its fixed offset,
// bounded by len. Outputs may be NULL and must not alias the input.
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

// ExtensionLoader::V1 (rust/src/extload.rs): a pre-manifest script's header.
// parse returns a handle (free with ext_v1_free) or NULL when the file isn't
// an extension script. Strings are borrowed from the handle (not NUL-
// terminated). text: 0 about (untrimmed), 1 queue events, 2 task time,
// 3 description line i, 4 requirement i. count: 0 description lines,
// 1 requirements, 2 options, 3 commands. item_text (command 0 option, 1
// command): 0 section name, 1 section prefix, 2 name, 3 action, 4 description
// line j. item_count: 0 section multi, 1 description lines, 2 select values.
// select: option i's value (j == SIZE_MAX) or select value j: 1 a number in
// *num, 0 a text in *text, -1 none.
typedef struct NzbgetRsStr
{
	const char* data;
	size_t len;
} NzbgetRsStr;
typedef struct NzbgetRsExtV1 NzbgetRsExtV1;
// data is borrowed for this call; NULL is empty. The result owns its bytes.
// rightSpace classifies byte 0..255 as Util::TrimRight does in the caller's
// current C locale and char signedness. It must not throw. NULL returns NULL.
// All returned strings are length-delimited, may contain NUL, are immutable,
// and remain valid until free(h); never free them separately. Free accepts NULL.
// Invalid indexes/fields and NULL handles return empty/zero (select: -1).
// select outputs may be NULL: if the required output is NULL, returns -1;
// otherwise writes only that output. Outputs must not overlap the handle.
// Rust panics abort; no exception may unwind through these functions.
NzbgetRsExtV1* nzbget_rs_ext_v1_parse(const char* data, size_t len, int (*rightSpace)(int));
// next returns one std::getline line (without '\n'): 1 line, 0 EOF, -1 error.
// Its bytes remain readable until next is called again. On error parsing
// returns NULL. next must catch all C++ exceptions; rethrow after read returns.
// NULL callbacks return NULL. No callback is retained after this call.
typedef int (*NzbgetRsExtV1Next)(void* context, NzbgetRsStr* line);
NzbgetRsExtV1* nzbget_rs_ext_v1_read(NzbgetRsExtV1Next next, void* context, int (*rightSpace)(int));
void nzbget_rs_ext_v1_free(NzbgetRsExtV1* h);
int nzbget_rs_ext_v1_kind(const NzbgetRsExtV1* h);
NzbgetRsStr nzbget_rs_ext_v1_text(const NzbgetRsExtV1* h, int which, size_t i);
size_t nzbget_rs_ext_v1_count(const NzbgetRsExtV1* h, int which);
NzbgetRsStr nzbget_rs_ext_v1_item_text(const NzbgetRsExtV1* h, int command, size_t i, int field, size_t j);
size_t nzbget_rs_ext_v1_item_count(const NzbgetRsExtV1* h, int command, size_t i, int which);
int nzbget_rs_ext_v1_select(const NzbgetRsExtV1* h, size_t i, size_t j, double* num, NzbgetRsStr* text);

// WebDownloader's HTTP decisions (rust/src/webdownload.rs). check_response:
// result 0 running, 1 running a redirect, 2 connect error, 3 not found,
// 4 failed; setStatus/httpStatus the status code read; warn 0 none,
// 1 connection closed, 2 failed with the whole line, 3 failed with the text at
// statusOffset. http_header: 0 nothing, 1 Content-Length (*value), 2 gzip,
// 3 Content-Disposition, 4 Location (at line + *value). http_redirect: the
// address a Location leads to (free with nzbget_rs_free).
typedef struct NzbgetRsHttpResponse
{
	int result;
	int setStatus;
	int httpStatus;
	int warn;
	size_t statusOffset;
} NzbgetRsHttpResponse;
void nzbget_rs_http_check_response(const char* response, NzbgetRsHttpResponse* out);
int nzbget_rs_http_header(const char* line, int redirecting, int* value);
NzbgetRsBuf nzbget_rs_http_redirect(const char* oldUrl, const char* location);

// NntpConnection's protocol (rust/src/nntp.rs), driving the C++ connection
// through NzbgetRsNntpIo. Each callback returns 0, or -1 when it threw: the
// exchange stops and the call returns -1 (rethrow then). readLine sets *line
// to the connection's line buffer or NULL; the exchange may cut it at its last
// CR. The login state (authError, authRejected) is read and written back.
// Only one exchange may use a connection at a time; callbacks must not reenter
// it or unwind. A non-NULL line is writable and NUL-terminated, and remains
// valid until the next readLine (including after return to the caller). Only
// readLine may overwrite it. Callback string arguments are borrowed for that
// callback only. Configuration strings remain immutable during the exchange;
// NULL configuration strings mean empty. req/group may alias the line buffer
// and must remain NUL-terminated across reads. Nothing is retained or freed.
// Non-NULL outputs must be writable, mutually disjoint, and not overlap io or
// strings. NULL required arguments or a missing required callback return -1;
// result outputs are written only on success. debug may be NULL.
// request: *answer is the buffer or NULL. handshake (after the socket
// connected): *result 0 connected, 1 the greeting failed (disconnect), 2 the
// login failed. join_group (not in the group yet): *answer, *joined.
typedef struct NzbgetRsNntpIo
{
	void* ctx;
	int (*writeLine)(void* ctx, const char* line);
	int (*readLine)(void* ctx, char** line);
	int (*reportError)(void* ctx, const char* prefix, const char* arg);
	int (*debug)(void* ctx, const char* msg);
	int (*cancelled)(void* ctx, int* cancelled);
	const char* user;
	const char* password;
	const char* name;
	const char* host;
	const char* connHost;
} NzbgetRsNntpIo;
int nzbget_rs_nntp_request(const NzbgetRsNntpIo* io, const char* req, int* authError, int* authRejected, char** answer);
int nzbget_rs_nntp_handshake(const NzbgetRsNntpIo* io, int* authError, int* authRejected, int* result);
int nzbget_rs_nntp_join_group(const NzbgetRsNntpIo* io, const char* group, int* authError, int* authRejected,
	char** answer, int* joined);

// CommandLineParser (rust/src/cmdline.rs): its constructor, over the argv array
// getopt permutes. The fields are set through the sink (field numbers in
// rust/src/cmdline.rs: field, edit); steal moves argv[index] into a field
// (std::move, the entry becomes null). Callbacks return 0, or -1 when they
// threw (parsing stops, the call returns -1: rethrow then). No callback may
// unwind. String arguments are borrowed for the callback; copy them if retained.
// steal keeps a moved allocation alive until its destination is overwritten
// or parsing finishes. The argv array
// initially contains argc non-NULL strings followed by a NULL sentinel.
// NULL inputs/entries or missing
// callbacks return -1. getopt globals must not be used concurrently.
typedef struct NzbgetRsCmdlineSink
{
	// The platform's getopt_long with the C++ option table; optional only
	// when useLong == 0. Returns libc's option code (or -1 at end).
	int (*getoptLong)(int argc, char** argv);
	void* ctx;
	int (*setInt)(void* ctx, int field, int value);
	int (*setStr)(void* ctx, int field, const char* value);
	int (*steal)(void* ctx, int field, int index);
	int (*pushOption)(void* ctx, const char* value);
	int (*pushId)(void* ctx, int id);
	int (*pushName)(void* ctx, const char* value);
	int (*error)(void* ctx, const char* msg);
} NzbgetRsCmdlineSink;
int nzbget_rs_cmdline_parse(int argc, char** argv, int useLong, const NzbgetRsCmdlineSink* sink);

// FileSystem's file operations (rust/src/fsops.rs, POSIX). error_message:
// writes at most 1022 bytes plus NUL (the original BString capacity argument)
// to a 1024-byte buffer; NULL is a no-op. Buffers returned by these functions
// are Rust-owned and must be freed with nzbget_rs_free, never free/delete.
// Panics abort; they do not unwind across the ABI.
// stat: borrowed for the call, takes a borrowed NUL-terminated path and returns
// -errno on failure, 1 for a regular file, 2 for a directory, 0 otherwise.
// It follows symlinks, uses the caller's stat ABI, and must not throw/unwind.
typedef int (*NzbgetRsFsStat)(const char* path);
void nzbget_rs_error_message(int errnum, char* buf);
// NULL paths or callbacks return 0.
int nzbget_rs_file_exists(const char* path, NzbgetRsFsStat stat);
int nzbget_rs_directory_exists(const char* path, NzbgetRsFsStat stat);
// 1 on success, 0 on failure; every non-NULL errmsg is initialized (empty on
// success or invalid NULL arguments). errmsg must not overlap the input.
int nzbget_rs_force_directories(const char* path, NzbgetRsBuf* errmsg, NzbgetRsFsStat stat);
// NULL dir/basename mean empty strings; a NULL stat reports no collisions.
NzbgetRsBuf nzbget_rs_make_unique_filename(const char* dir, const char* basename, NzbgetRsFsStat stat);
// NULL filename means empty; NULL home leaves the filename unchanged.
NzbgetRsBuf nzbget_rs_expand_home_path(const char* filename, const char* home);

// ParParser's name checks (rust/src/parparser.rs).
// Names are borrowed and read only through the first NUL or 1023 bytes.
// fold takes a byte (0..255), applies the caller's tolower(char), and must not
// unwind. NULL names/fold return 0. Outputs are optional, writable C ints;
// they may alias each other (blocks is written last), and change only on success.
// No ownership transfer or allocation crosses the ABI; panics abort.
// table: glibc's tolower table (*__ctype_tolower_loc()) read for a char of
// the given signedness instead of calling fold per byte; NULL calls fold.
int nzbget_rs_parse_par_filename(const char* name, int confirmed, int* baseLen, int* blocks,
	const int* table, int charSigned, int (*fold)(int));
int nzbget_rs_same_par_collection(const char* name1, const char* name2, int confirmed,
	const int* table, int charSigned, int (*fold)(int));

// RarVolume's header parsing (rust/src/rarreader.rs). rar_read parses the
// content source into *state (read and written back) and calls addFile for each
// file read, in order, also when the parse fails; 1 when the volume was read
// to its end. size/read are the ContentSource; rar3Prepare, rar5Prepare, init
// (iv NULL: rar3's derived IV), decrypt (one 16-byte block) and free are the
// header cipher. addFile commits a completed header before the trailing seek;
// setDataOffset updates the last file to position minus its packed size after
// that seek succeeds. File/name pointers are borrowed only for addFile: copy
// their contents there; never retain or free them. read/decrypt buffers are
// borrowed writable storage of len/16 bytes. Callbacks must not throw; int
// callbacks return nonzero for success; a rejected addFile stops parsing. NULL io/state
// fails without callbacks; NULL callbacks are allowed (missing addFile drops
// files and suppresses setDataOffset). ctx is opaque and may be NULL if the
// callbacks support it. io must remain immutable and state exclusively borrowed
// until rar_read returns, including during callbacks.
typedef struct NzbgetRsRarFile
{
	const char* filename;
	size_t filenameLen;
	uint32_t time;
	uint32_t attr;
	int64_t size;
	int splitBefore;
	int splitAfter;
	uint32_t method;
	int stored;
	int64_t packedSize;
	int64_t dataOffset;
	int encryptedData;
	int hasSalt;
	uint8_t salt[8];
	int hasCrypt;
	uint64_t cryptVersion;
	uint64_t cryptFlags;
	uint8_t cryptKdfCount;
	uint8_t cryptSalt[16];
	uint8_t cryptIv[16];
	uint8_t cryptCheckValue[12];
	int cryptHasCheck;
} NzbgetRsRarFile;
typedef struct NzbgetRsRarIo
{
	void* ctx;
	int64_t (*size)(void* ctx);
	int (*read)(void* ctx, int64_t offset, uint8_t* buffer, int64_t len);
	int (*rar3Prepare)(void* ctx, const uint8_t* salt);
	int (*rar5Prepare)(void* ctx, uint8_t kdfCount, const uint8_t* salt);
	int (*init)(void* ctx, int keyBits, const uint8_t* iv);
	int (*decrypt)(void* ctx, const uint8_t* in, uint8_t* out);
	void (*free)(void* ctx);
	int (*addFile)(void* ctx, const NzbgetRsRarFile* file);
	void (*setDataOffset)(void* ctx, int64_t position);
} NzbgetRsRarIo;
typedef struct NzbgetRsRarVolume
{
	int version;
	uint32_t volumeNo;
	int newNaming;
	int hasNextVolume;
	int multiVolume;
	int encrypted;
	int hasPassword;
	uint8_t decryptBuf[16];
	uint8_t decryptPos;
} NzbgetRsRarVolume;
int nzbget_rs_rar_read(const NzbgetRsRarIo* io, NzbgetRsRarVolume* state);

// RarRenamer::RenameFiles (rust/src/rarrenamer.rs): the volumes read from dir
// gathered into sets; the sets not properly named are renamed through rename
// (index into volumes, the new path). fileExists is FileSystem::FileExists;
// matchPart the RegEx ".*.part([0-9]+)\\.rar$" (group 1's start and length).
// All input buffers are borrowed for the call. Callback strings are borrowed
// only until the callback returns; callbacks must copy them to retain them and
// must not free them or throw. No allocation crosses the ownership boundary.
// NULL dir/env or NULL volumes with nonzero count makes the call a no-op.
// NULL names and file arrays are treated as empty. Rust panics abort, never
// unwind through C++.
typedef struct NzbgetRsRarRenFile
{
	const char* name;
	size_t nameLen;
	int64_t size;
	int splitBefore;
	int splitAfter;
} NzbgetRsRarRenFile;
typedef struct NzbgetRsRarRenVolume
{
	const char* filename;
	size_t filenameLen;
	int version;
	uint32_t volumeNo;
	int multiVolume;
	int hasNextVolume;
	int newNaming;
	const NzbgetRsRarRenFile* files;
	size_t fileCount;
} NzbgetRsRarRenVolume;
typedef struct NzbgetRsRarRenEnv
{
	void* ctx;
	int (*fileExists)(void* ctx, const char* path);
	int (*matchPart)(void* ctx, const char* name, size_t* start, size_t* len);
	void (*rename)(void* ctx, size_t index, const char* dest);
} NzbgetRsRarRenEnv;
void nzbget_rs_rar_rename_files(const char* dir, const NzbgetRsRarRenVolume* volumes, size_t count, const NzbgetRsRarRenEnv* env);

// DirectRenamer's RenameContentAnalyzer (rust/src/renameanalyzer.rs): the PAR2
// packet header and MD5 of a file's first 16 KiB, fed article by article.
// append returns 1 when it recognized a PAR2 header (setId: 32 hex digits and
// a NUL); finish writes the printed MD5 (32 hex digits and a NUL).
// The caller owns these 33-byte output buffers; no buffer is retained or freed.
// Output buffers must not overlap the input or analyzer. NULL outputs discard
// the set id; NULL hash makes finish a no-op. NULL analyzers are accepted as
// no-ops, as are negative lengths and NULL input with positive length. NULL
// input with zero length is an ordinary empty piece (it may recognize a header).
// Use only new/free for analyzer ownership, with exclusive access on each call.
typedef struct NzbgetRsRenameAnalyzer NzbgetRsRenameAnalyzer;
NzbgetRsRenameAnalyzer* nzbget_rs_rename_analyzer_new(void);
void nzbget_rs_rename_analyzer_free(NzbgetRsRenameAnalyzer* a);
void nzbget_rs_rename_analyzer_reset(NzbgetRsRenameAnalyzer* a);
int nzbget_rs_rename_analyzer_append(NzbgetRsRenameAnalyzer* a, const char* buf, int len, char* setId);
void nzbget_rs_rename_analyzer_finish(NzbgetRsRenameAnalyzer* a, char* hash);

// DirectRenamer's new names (rust/src/directrenamer.rs), comparing in the
// current locale. Strings are borrowed for the call; NULL strings are empty.
// direct_regular_name: the index of the par2 hash whose filename the file
// gets, or -1 to keep its name; at writes index's filename and hash (borrowed
// until the call returns) for every index below count; NULL at returns -1.
// direct_par_name: the par2 file's new name (free with nzbget_rs_free), *vol
// counted up for every name tried (NULL vol: from 1); exists gets the full
// path (NULL: nothing exists). format is NULL for classic formatting, or
// writes a borrowed candidate buffer and length (valid until the next
// callback), returning 1 on success, 0 to stop the search. Callbacks must
// not access *vol. direct_need_rename_pars: 1 when the par2 files
// need new names; a NULL filename needs one; NULL pars/fold return 0. fold is
// ParParser::FilenameFold. Callbacks must not throw; panics abort.
typedef void (*NzbgetRsParHashAt)(void* ctx, size_t index, const char** filename, const char** hash);
ptrdiff_t nzbget_rs_direct_regular_name(const char* oldName, const char* hash16k, size_t count,
	NzbgetRsParHashAt at, void* ctx);
typedef int (*NzbgetRsFormatParName)(void* ctx, int vol, const char** data, size_t* len);
NzbgetRsBuf nzbget_rs_direct_par_name(const char* oldName, const char* destDir, const char* setId,
	char separator, int* vol, int (*exists)(void* ctx, const char* path), NzbgetRsFormatParName format, void* ctx);
typedef struct NzbgetRsParName
{
	const char* filename;
	const char* setId;
} NzbgetRsParName;
int nzbget_rs_direct_need_rename_pars(const NzbgetRsParName* pars, size_t count, int (*fold)(int));

// ManifestFile::Load (rust/src/manifest.rs, rust/src/json.rs: Boost.JSON's
// parse with the default options) on the manifest text the C++ read: 1 when
// loaded, after loaded got the manifest; 0 refused (a required key missing
// or of another kind); -1 a syntax error; -2 not a JSON object; -3 an
// option, command or section that isn't an object. On 0 and -3, loaded gets
// the partial writes preceding failure. Texts/options/commands are appended; sections apply
// to both existing and appended entries. The manifest and every
// string in it are borrowed for the loaded call only; strings are not
// NUL-terminated. fields are author, main, homepage, about, version, name,
// displayName, kind, license, taskTime, queueEvents, nzbgetMinVersion; has[i]
// says whether fields[i] was assigned before validation stopped. NULL text is empty; NULL loaded
// is not called. loaded must not throw; panics abort.
typedef struct NzbgetRsManifestSection
{
	int multi;
	NzbgetRsStr name;
	NzbgetRsStr prefix;
} NzbgetRsManifestSection;
typedef struct NzbgetRsManifestSelect
{
	int isString;
	double number;
	NzbgetRsStr string;
} NzbgetRsManifestSelect;
typedef struct NzbgetRsManifestOption
{
	NzbgetRsManifestSection section;
	NzbgetRsStr name;
	NzbgetRsStr displayName;
	const NzbgetRsStr* description;
	size_t descriptionCount;
	NzbgetRsManifestSelect value;
	const NzbgetRsManifestSelect* select;
	size_t selectCount;
} NzbgetRsManifestOption;
typedef struct NzbgetRsManifestCommand
{
	NzbgetRsManifestSection section;
	NzbgetRsStr name;
	NzbgetRsStr displayName;
	NzbgetRsStr action;
	const NzbgetRsStr* description;
	size_t descriptionCount;
} NzbgetRsManifestCommand;
typedef struct NzbgetRsManifest
{
	NzbgetRsStr fields[12];
	int has[12];
	const NzbgetRsStr* description;
	size_t descriptionCount;
	const NzbgetRsStr* requirements;
	size_t requirementsCount;
	const NzbgetRsManifestOption* options;
	size_t optionCount;
	const NzbgetRsManifestCommand* commands;
	size_t commandCount;
	const NzbgetRsManifestSection* sections;
	size_t sectionCount;
} NzbgetRsManifest;
// Limits from this build of Boost.JSON, in decoded bytes / input elements.
typedef struct NzbgetRsJsonLimits
{
	size_t stringSize;
	size_t arraySize;
	size_t objectSize;
} NzbgetRsJsonLimits;
int nzbget_rs_manifest_load(const char* text, size_t len, NzbgetRsJsonLimits limits, void* ctx,
	void (*loaded)(void* ctx, const NzbgetRsManifest* manifest));

// TestServerXmlCommand's JSON body (rust/src/rpcparams.rs with the parser
// above): 1 when parsed, after parsed got the parameters (strings borrowed
// for the call only, whole - NULs included - and not NUL-terminated); 0 not
// JSON ("Invalid JSON"); -1 "Invalid parameters". NULL request is empty;
// NULL parsed is not called. parsed must not throw; panics abort.
typedef struct NzbgetRsTestServerParams
{
	NzbgetRsStr host;
	NzbgetRsStr username;
	NzbgetRsStr password;
	NzbgetRsStr cipher;
	int port;
	int timeout;
	int certVerifLevel;
	int encryption;
} NzbgetRsTestServerParams;
int nzbget_rs_test_server_params(const char* request, NzbgetRsJsonLimits limits, void* ctx,
	void (*parsed)(void* ctx, const NzbgetRsTestServerParams* params));

// ParRenamer::Execute (rust/src/parrenamer.rs). The callbacks get borrowed
// NUL-terminated strings, valid for the call only, and return -1 (read: -1)
// for a C++ exception, which ends the run (execute then returns 0; the state
// holds what was done until then). stopped: 1 stopped. progress: the label
// and stage set, then UpdateProgress. message kinds: 0 info, 1 warning,
// 2 error. listDir / findMainPars call add for each name (DirBrowser's
// snapshot / ParParser::FindMainPars). dirExists / fileExists /
// ignoredExt (Util::MatchFileExt with ParIgnoreExt): 1 yes. fileSize writes
// FileSystem::FileSize. read: the bytes DiskFile read from the start of the
// file into buf (at most len), -2 when it could not be opened, -3 when the
// read failed. loadPar: 1 loaded (writes the source map size), 0 when the
// packets could not be loaded or the file is empty. parEntry translates the
// next source map entry and calls add once (damaged or local name/hash).
// closePar releases the loaded repairer; the caller must also release it on
// an aborted run. stateChanged publishes members before callbacks, cannot
// fail or unwind, and must not retain the borrowed state pointer. It writes
// back detectMissing, which callbacks can change through the C++ setter.
// previousDirs / rememberDir retain the directory list across runs.
// destination calls add once with the current destination after initial progress;
// a NULL callback uses execute's destDir argument instead. All input strings
// are copied before callbacks may replace the caller's storage. All sink
// and add pointers are borrowed, non-NULL, and valid only during the callback.
// No buffers or objects transfer ownership across the ABI. rename: RenameFile
// without the count, 1 when moved. fold is ParParser::FilenameFold. NULL
// callbacks mean: not stopped, nothing printed, empty lists, no files, reads
// that can't open, nothing loaded, no renames, identity fold.
typedef struct NzbgetRsParRenamerState
{
	int fileCount;
	int curFile;
	int renamedCount;
	int hasMissedFiles;
	int hasDamagedParFiles;
	int detectMissing;
} NzbgetRsParRenamerState;
typedef struct NzbgetRsParRenamerEnv
{
	void* ctx;
	int (*stopped)(void* ctx);
	int (*progress)(void* ctx, const char* label, int stage);
	int (*message)(void* ctx, int kind, const char* text);
	int (*debug)(void* ctx, const char* text);
	int (*listDir)(void* ctx, const char* dir, void* sink, void (*add)(void* sink, const char* name));
	int (*dirExists)(void* ctx, const char* path);
	int (*fileExists)(void* ctx, const char* path);
	int (*fileSize)(void* ctx, const char* path, int64_t* size);
	int64_t (*read)(void* ctx, const char* path, uint8_t* buf, size_t len);
	int (*loadPar)(void* ctx, const char* path, size_t* count);
	int (*parEntry)(void* ctx, void* sink,
		void (*add)(void* sink, int damaged, const char* name, const char* hash));
	void (*closePar)(void* ctx);
	int (*findMainPars)(void* ctx, const char* dir, void* sink, void (*add)(void* sink, const char* name));
	int (*registerParred)(void* ctx, const char* name);
	int (*rename)(void* ctx, const char* src, const char* dst);
	int (*ignoredExt)(void* ctx, const char* name);
	int (*fold)(int byte);
	void (*stateChanged)(void* ctx, NzbgetRsParRenamerState* state);
	int (*previousDirs)(void* ctx, const char* unused, void* sink, void (*add)(void* sink, const char* name));
	int (*rememberDir)(void* ctx, const char* dir);
	int (*destination)(void* ctx, const char* unused, void* sink, void (*add)(void* sink, const char* dir));
} NzbgetRsParRenamerEnv;
int nzbget_rs_par_renamer_execute(const NzbgetRsParRenamerEnv* env, NzbgetRsParRenamerState* state,
	const char* infoName, const char* destDir, char separator);

// FileSystem's deletes and RenameBak (rust/src/fsdelete.rs). The callbacks
// get borrowed NUL-terminated paths and return -1 for a C++ exception (the
// call then returns -1). pathType: GetPathTypeNoFollow, 0 error, 1 file,
// 2 directory, 3 link, 4 directory link. removeDir / deleteFile / deleteLink
// (type 3 or 4) / fileExists / dirExists / moveFile: 1 done or yes. list
// calls add for each name of DirBrowser's snapshot; lastError calls set with
// GetLastErrorMessage for the call that failed last. NULL callbacks mean
// errors, empty lists, nothing done. errmsg / newName (NULL: not written)
// get a buffer to free with nzbget_rs_free; an empty errmsg was cleared.
// A NULL ops table returns 0 and writes empty output buffers. Output slots
// must not hold an allocation needing release. Callbacks must not unwind;
// sink and add/set are valid only during their list/lastError call. Strings
// passed to add/set are copied before that function returns.
typedef struct NzbgetRsFsOps
{
	void* ctx;
	int (*pathType)(void* ctx, const char* path);
	int (*removeDir)(void* ctx, const char* path);
	int (*deleteFile)(void* ctx, const char* path);
	int (*deleteLink)(void* ctx, const char* path, int type);
	int (*list)(void* ctx, const char* dir, void* sink, void (*add)(void* sink, const char* name));
	int (*fileExists)(void* ctx, const char* path);
	int (*dirExists)(void* ctx, const char* path);
	int (*moveFile)(void* ctx, const char* from, const char* to);
	int (*lastError)(void* ctx, void* sink, void (*set)(void* sink, const char* text));
	// sets errno to ENAMETOOLONG: delete roots (without trailing separators or
	// "." components) and paths below them longer than 1023 bytes are refused
	int (*tooLong)(void* ctx);
} NzbgetRsFsOps;
int nzbget_rs_delete_directory(const NzbgetRsFsOps* ops, const char* dir, char separator);
int nzbget_rs_delete_directory_with_content(const NzbgetRsFsOps* ops, const char* dir, char separator, NzbgetRsBuf* errmsg);
int nzbget_rs_rename_bak(const NzbgetRsFsOps* ops, const char* filename, const char* bakPart, int removeOldExtension,
	NzbgetRsBuf* newName);
// FileSystem::GetFileExtension: the offset of the last '.', or -1.
ptrdiff_t nzbget_rs_file_extension(const char* name, size_t len);

// The binary remote protocol's frame (rust/src/binrpc.rs). base is the
// request base as received (SNzbRequestBase, 76 bytes, network byte order).
// check: 1 when the credentials match (strcmp as BinRpcProcessor compared
// them; an empty control user isn't compared), *type the request type.
// name: a static string for the log. size_ok: 1, or 0 with *expected and
// *received set for a known type whose struct size differs from sizes[type].
// bool_response: the bytes SendBoolResponse sends (free with nzbget_rs_free).
// trailing_ok: 1 when 0 <= len <= max. NULL outputs aren't written; a NULL
// or short base fails, as does a missing sizes entry for a known type,
// leaving outputs untouched. NULL control strings/text mean empty strings.
// Non-NULL inputs must be readable for their lengths (strings through NUL);
// non-NULL uint32_t pointers must be aligned and outputs writable. Outputs
// may overlap inputs; inputs are read first. Panics abort.
int nzbget_rs_binrpc_check(const unsigned char* base, size_t len, const char* controlUser, const char* controlPassword,
	uint32_t* type);
const char* nzbget_rs_binrpc_name(uint32_t type);
int nzbget_rs_binrpc_size_ok(const unsigned char* base, size_t len, const uint32_t* sizes, size_t count,
	uint32_t* expected, uint32_t* received);
NzbgetRsBuf nzbget_rs_binrpc_bool_response(int success, const char* text);
int nzbget_rs_binrpc_trailing_ok(int64_t len, int64_t max);
// The trailing data of a list response (List, Log, PostQueue, History).
// entry appends ints (host order) written big-endian, puts each string's
// length with its NUL into the field fields[i] names, then the strings with
// their NULs, padded with zeros to 4 bytes counted in field padField. Fields
// not given values are 0. take returns the bytes (free with nzbget_rs_free)
// and frees the buffer; free frees an untaken one. NULL buffers do nothing.
typedef struct NzbgetRsBinBuf NzbgetRsBinBuf;
NzbgetRsBinBuf* nzbget_rs_binrpc_buf_new(void);
void nzbget_rs_binrpc_buf_free(NzbgetRsBinBuf* buf);
size_t nzbget_rs_binrpc_buf_len(const NzbgetRsBinBuf* buf);
NzbgetRsBuf nzbget_rs_binrpc_buf_take(NzbgetRsBinBuf* buf);
void nzbget_rs_binrpc_entry(NzbgetRsBinBuf* buf, const uint32_t* ints, size_t nints, const char* const* strings,
	const size_t* fields, size_t nstrings, size_t padField);
// EditQueue's trailing data (text, ids, names). edit_sizes: 1 when the
// client's counts and lengths are non-negative, nrIds <= 10000000, nrNames <=
// namesLen and nrIds*4 + textLen + namesLen == dataLen. edit_split: 1 when
// the nrIds big-endian ids after the text and the nrNames names after them
// fit in len, each name ending within it, with the ids written into ids
// (host order); 0 (ids untouched) otherwise. Nothing is allocated. data is
// readable for len bytes; ids is writable for nrIds (NULL for 0).
// is_url: 1 when content starts with "http:/" or "https:/" in any case (NULL
// is empty).
int nzbget_rs_binrpc_edit_sizes(int32_t nrIds, int32_t nrNames, int32_t namesLen, int32_t textLen, uint32_t dataLen);
int nzbget_rs_binrpc_edit_split(const char* data, size_t len, size_t textLen, size_t nrIds, size_t nrNames,
	uint32_t* ids);
int nzbget_rs_binrpc_is_url(const char* content);
// The remote client's side (RemoteClient.cpp). read_entry: one list-response
// entry at *at: 1 with nints big-endian ints in ints (host order), the start
// of each of nfields strings in starts (string k's length in ints[fields[k]],
// each ending with a NUL within the data) and *at past the entry (the header
// and those lengths); 0 (outputs untouched) when the entry or a string
// doesn't fit in len. log_line: "[INFO] text" and so on for Message::EKind,
// 0 for an unknown kind. post_queue_line: "[id] name, stage, n%".
// history_line: "[id] name (...)" for an NZB, URL or hidden entry, 0 for
// other kinds; unknown stages and statuses have no text. Lines are freed
// with nzbget_rs_free; NULL outputs aren't written, NULL strings are empty.
// read_entry requires at and nonempty arrays; ints and starts are writable
// arrays and may be uninitialized. NULL arrays are allowed for zero counts.
int nzbget_rs_binrpc_read_entry(const char* data, size_t len, size_t* at, uint32_t* ints, size_t nints,
	const size_t* fields, size_t* starts, size_t nfields);
int nzbget_rs_binrpc_log_line(uint32_t kind, const char* text, NzbgetRsBuf* line);
NzbgetRsBuf nzbget_rs_binrpc_post_queue_line(uint32_t id, uint32_t stage, uint32_t progress, const char* infoName);
int nzbget_rs_binrpc_history_line(uint32_t id, uint32_t kind, const char* nicename, uint32_t fileCount, uint32_t sizeHi,
	uint32_t sizeLo, uint32_t parStatus, uint32_t scriptStatus, uint32_t urlStatus, NzbgetRsBuf* line);

// UrlCoordinator (rust/src/urlcoord.rs). dnzb_header: UrlDownloader's
// X-DNZB headers; 1 with *first X-DNZB-Category's trimmed value, 2 with
// *first "*DNZB:" and the header's name (cut to 99 bytes) and *value its
// value after the colon's spaces, right-trimmed, Latin-1 to UTF-8; 0 for
// another line (outputs untouched). Free outputs with nzbget_rs_free; NULL
// outputs aren't written, a NULL line is empty. completed: the URL and
// delete statuses UrlCompleted leaves for the downloader's status
// (WebDownloader::EStatus) and whether the fetch is retried; NULL pointers
// read as 0 and aren't written.
int nzbget_rs_url_dnzb_header(const char* line, NzbgetRsBuf* first, NzbgetRsBuf* value);
void nzbget_rs_url_completed(int downloaderStatus, int deleting, int* urlStatus, int* deleteStatus, int* retry);

// ---- dupesearch (daemon/dupesearch/) ----
// DonorScore (rust/src/donorscore.rs): Base, Target (twin 0/1) and Rerank;
// rerank writes n scores parallel to entries into out (both NULL for n 0).
typedef struct NzbgetRsDonorEntry
{
	int score;
	double alive;
	int twin;
	int64_t bytes;
	int grabs;
} NzbgetRsDonorEntry;
int nzbget_rs_donorscore_base(int pickScore);
int nzbget_rs_donorscore_target(double alive, int twin);
void nzbget_rs_donorscore_rerank(const NzbgetRsDonorEntry* entries, size_t n, int64_t pickBytes, int* out);

// ReleaseName (rust/src/releasename.rs): Clean, Normalize, ShortQuery, Readable,
// SameRelease; Parse returns the attributes encoded: per set (resolution,
// quality, codec, bitDepth, audio, channels, network, edition, hdr) a u32
// count and its strings, each a u32 length and bytes; then title, group, the
// seasons and episodes (u32 count, i32 each), year (i32), repack and proper
// (one byte each); all little-endian. Names may be NULL (empty).
NzbgetRsBuf nzbget_rs_releasename_clean(const char* name, size_t len);
NzbgetRsBuf nzbget_rs_releasename_normalize(const char* name, size_t len);
NzbgetRsBuf nzbget_rs_releasename_short_query(const char* title, size_t len);
NzbgetRsBuf nzbget_rs_releasename_parse(const char* name, size_t len);
int nzbget_rs_releasename_readable(const char* name, size_t len);
int nzbget_rs_releasename_same_release(const char* a, size_t alen, const char* b, size_t blen);

#ifdef __cplusplus
}
#endif

#endif
