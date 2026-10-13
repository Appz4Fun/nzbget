# Fallback validation, 2026-10-13

This integration merges upstream `develop` at
`f81d3f4de58fbfae9e0657a7eb3041ff6ab5adfd` into the fork's
`dupe-article-fallback` head `cbda2e4f3f50d7e70c5eeaa25b2b37d779ca026c`.
The historical upstream PR 850 is closed; updating its source branch does not
reopen it.

## Completion regression

Healthy live downloads reproduced a queue stall after direct rename paused
the remaining PAR volumes. The name notification could arrive while their
last article requests were still active. Those requests subsequently drained
without completing a file, leaving no event to start post-processing.

The completion check now runs on both the name notification and the last
downloader's removal. It requires successful direct rename, completed output,
no active download work, no deletion, and no existing post-processing job.
Raw and skipped writes remain excluded. The queue lock protects both callers.
Six unit cases cover completion, remaining data, active requests, unfinished
rename, health deletion, and request draining.

The broad harness also reproduced a healthy backup never being downloaded
after a primary ended `FAILURE/HEALTH` at 96% health without usable parity.
`IsDupeSuccess` compared that result with the estimated 85% download threshold,
whereas the reported status used the actual parity threshold. With
`HealthCheck=dupe`, the success decision now uses that same actual threshold.
A red/green unit test covers the mismatch and retains successful PAR repair,
explicit good marks, and complete downloads as controls. The same-posting
functional case now downloads the healthy backup successfully.

An isolated fleet test repeatedly abandoned both a slow URL and a healthy URL
immediately. An instrumented diagnostic traced this to a size watchdog reading
a huge bogus size for an output file that did not exist yet. The POSIX
`FileSize` helper ignored `stat`'s return value and read its output on failure.
It now returns `-1` when `stat` fails. A red/green regression covers nonexistent
paths, nonexistent parents, `ENOTDIR`, and a known-size regular file. The fleet
test now honors its time budget and queues the healthy member.

The restricted JSON-P configuration test now owns its Options instance rather
than reading a global cleared by an earlier test. Two parked-file retry
fixtures use one connection so the retained volume finishes before health
cancellation. A history-recheck fixture disables early health cancellation
so both failed files reach history; it still requires all five failed articles
to be sampled without state-file errors. Their integrity assertions are unchanged.
Search fixtures check exact logical query/page coverage and at most two
transport attempts per page, matching Newznab's existing single retry. They
still require one logical search and no new requests after a cached result.
The empty-search restart fixture now requires another search after restart:
discovery without a usable backup intentionally remains retryable. Completed
backup memo preservation continues to be checked by the memo scenarios.

## Verified live behavior

The isolated live matrix passed 12/12 cases. Healthy controls and every
positive repair compared complete output SHA-256 hashes with the healthy
reference downloads. The reference payloads were approximately 521 MB and
681 MB. The tests exercised:

- Complementary missing articles with a valid PAR index: article borrowing
  followed by successful PAR verification.
- Missing NZB segment entries and failed articles: stream repair restored
  28,672,000 bytes across 40 articles.
- Live stream repair: repair started before the primary download completed;
  both complete output files matched their controls.
- Local PAR recovery with `ParQuick=yes` and `ParQuick=no`.
- Duplicate PAR recovery: recovery blocks came from a twin posting, with no
  borrowed data articles, and the reconstructed payload matched its control.
- Disabled fallback, an unrelated donor, and insufficient parity: all
  retained failure status rather than reporting success with damaged output.

An additional decompression pair used genuine downloaded reference bytes in
a locally generated deflated ZIP donor served by the real nserv implementation.
The damaged primary still downloaded through the live NNTP proxy. With
`DupeStreamDecompress=yes`, 40 articles were recovered and the entire output
matched the reference. With decompression disabled, recovery remained zero
and the download failed. This is a hybrid test, not an independently found
compressed repost on the public provider.

The live fixtures came from NZBHydra NZBs. Selected message IDs or NZB entries
were deliberately removed, and donor segment-size metadata was adjusted where
needed to exercise byte-range rather than structural article matching.
These controls prove recovery against real provider data; they do not imply
that every historical release has a compatible available donor.

## Configuration and scope

The isolated instances enabled duplicate checking, retained source NZBs,
PAR repair, and duplicate PAR scanning. Fallback was varied explicitly between
off, article, stream, and live; decompression was varied explicitly too.
The production daemon, queue, and configuration were not replaced.

A retained large-release replay did try stream recovery and restored roughly
600 MB before its watchdog stopped the pass: repair throughput was below one
third of the original download average. Its remaining damage exceeded the
available parity, and it correctly ended in failure. A test timeout of zero
disabled that watchdog for controlled correctness experiments; this is not a
production performance recommendation. Article borrowing without a PAR index
remains deliberately rejected by the safety check.

The final runtime SHA-256 is
`2bf30ed5aac96f4129df79068a783c50a9eedec853a8d6c98dd6e7f650df9f1d`.
The build used Rust 1.99 and Linux amd64 containers under macOS arm64 emulation.
These are correctness results, not native performance qualification or a
production deployment claim. Private raw fixtures, provider configuration,
command receipts, logs, and output hashes were retained outside the repository.

## Offline regression results

The unit suite passed 586/586 cases and 23,124/23,124 assertions. PAR-first
validation passed 14/14 scenarios with quick verification enabled and 14/14
with it disabled. History retry preserved failure and bytes without redundant
requests. Four archive-stall cases verified unavailable/incomplete donor
rejection, cleanup, later healthy donors, and password retry.

All 354 broad functional scenarios were exercised on the final runtime. The
three concurrent shards initially passed 352/354. One failure was the old
empty-search restart assertion; the corrected fixture passed with exactly two
searches and two empty results. The other produced an inconclusive multi-server
probe under concurrent execution, then downloaded the healthy backup with
matching bytes. Its original assertions passed in an isolated run: four
definitive servers, two unreachable servers excluded, a dead-posting verdict,
and successful byte-identical backup output. These targeted results are
reported separately from the initial shard results.

Earlier raw failures and instrumented diagnostic runs are retained. Their
executables are distinguished from the final candidate above; none is
substituted for final verification. The final source reviews found no issues
in the success threshold, bounded transport-retry assertions, or failed-stat
handling. A claimed duplicate completion-script finding was rejected because
the queue-locked outer guard excludes existing post-processing jobs before
script enqueue.
