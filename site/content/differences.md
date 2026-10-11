+++
title = "Differences from NZBGet"
description = "Everything RustyGet does differently from NZBGet: duplicate fleets, new options, API changes, security fixes, bug fixes, and the move to Rust."
eyebrow = "Overview"
lede = "RustyGet started from NZBGet 27.0 and the work of pull request 850. This page lists what differs, area by area. The sections after the table cover the details."
+++

## At a glance

| Area | NZBGet | RustyGet |
|---|---|---|
| Language | C++ | C++ moving to Rust module by module, with 30 modules in Rust as of October 2026 |
| An article missing on every server | Lost; par2 repair or failure | Fetched from a matching file in another copy of the release, then verified against par2 |
| Duplicates | Spare downloads, tried one after another | One fleet: copies lend each other articles, bytes, and par2 volumes |
| Proving two copies hold the same files | Not done | Par2 checksums prove twins; alts are told apart |
| Not enough par2 blocks | Repair fails | Repairs with a twin's recovery volumes |
| Holes after the download | Left to par2 | Patched with verified bytes from duplicates, across RAR, ZIP, 7-Zip, splits, and encryption |
| A download that can't complete | Runs to the end, then fails over | `HealthCheck=dupe` fails over within seconds, and a probe catches dead copies before they start |
| Finding more copies | Only what feeds and clients send | `DupeSearch` queries NZBHydra2, checks each copy on your servers, and queues the live ones |
| Clients sending many copies | One `append` per copy | One `appendfleet` call; RustyGet checks every copy and picks the best |
| Health of a backup | Unknown until it downloads | Measured, shown with its score, and used to skip dead copies |
| Configuration | 155 options | 16 more options and a new `HealthCheck` value, all off by default |
| API | NZBGet API | NZBGet API plus `appendfleet` and new fields; unsafe methods need POST; may diverge later |
| Queue files | NZBGet formats | NZBGet formats, with RustyGet's data in a trailer that NZBGet ignores |
| Bug fixes | | More than 100 fixes to inherited bugs, most reported upstream |
| Build and test workflows | Builds for every platform on each push | Turned off while the tests are rebuilt; only the documentation deploys |

## Duplicate fleets

| Feature | Setting | Summary |
|---|---|---|
| Article fallback | `DupeArticleFallback=article` | Missing articles come from matching files in other copies, matched by par2 content, name, or structure, and checked against the download's par2 block checksums. |
| Cutover and lead rotation | Part of article fallback | After three recoveries in a file, RustyGet asks the lead duplicate first; after three misses in a row, the next duplicate leads. |
| Twins and alts | Automatic with Rust | par2 file lists prove which copies are byte-identical (twins) and which are other encodes (alts). |
| par2 from a twin | Automatic | When recovery blocks run short, RustyGet fetches and uses the fewest twin recovery volumes that cover the damage. |
| Stream repair | `DupeArticleFallback=stream` | Byte-level repair from duplicates after the download, with same-byte, whole-file, cross-packaging, and cross-encryption methods. |
| Live repair | `DupeArticleFallback=live` | Stream repair during the download. |
| Compressed donors | `DupeStreamDecompress=yes` | Extracts a compressed duplicate to repair from its contents. |
| Repair time limit | `DupeStreamTimeout` | Stops a stream repair that stalls, or that would take longer than downloading again. |
| Early failover | `HealthCheck=dupe` | Fails over as soon as a download can't complete, by failure counts, projected health, or par2 block damage. |
| Dead-copy probe | `HealthCheck=dupe` | Ten articles checked on every server before a download starts, when a backup waits. |
| Failed-article recheck | Article fallback or `HealthCheck=dupe` | After a failure, RustyGet asks for a sample of the failed articles again and retries them once if most now exist. |
| Donor search | `DupeSearch=yes` | Finds, checks, and queues more copies through NZBHydra2. |
| Fleet submission | `appendfleet` | A client sends up to 50 copies in one call. |

See [Duplicate fleets](duplicate-fleets.md) and [Donor search](dupesearch.md).

## Changes to inherited duplicate handling

- Failover skips a backup whose NZB file is gone, a backup found dead, and a copy of a posting that already failed.
- Among backups with equal scores, the most complete one goes first.
- A title already on disk isn't downloaded again, and once one copy is on disk, the other copies stop.
- With `HealthCheck=dupe`, a forced download fails over to its backups like a scored one.
- When no backup qualifies, the log gives the reason for each one.
- The duplicate mode of a download survives a restart.

## Options

All new options are in **INCOMING NZBS**, after `DupeCheck`, and default to NZBGet's behavior: `DupeArticleFallback`, `DupeStreamDecompress`, `DupeStreamTimeout`, `DupeSearch`, `DupeSearchUrl`, `DupeSearchApiKey`, `DupeSearchDelay`, `DupeSearchDryRun`, `DupeSearchMaxDonors`, `DupeHealthPercent`, `DupeHealthMin`, `DupeHealthMax`, `DupeBodyChecks`, `DupeHealthBudget`, `DupeMinAlive`, and `DupeFastDonors`. `HealthCheck` gains the value `dupe`. No existing default changed.

Option parsing also changed: a `ScriptDir` with several folders creates each folder correctly, and a scheduler task with an unknown command is reported and skipped instead of running as `PauseDownload`.

New startup warnings point out risky combinations, such as donor search without `DupeCheck` or with fewer than three article retries.

See [Configuration options](options.md) for every option.

## API

- New method `appendfleet`, and new fields `DupeRecoveredArticles`, `DupeRecoveredBytesLo`, `DupeRecoveredBytesHi`, `DupeRecoveredHoles`, and `LiveRepairing`.
- New stage `STREAM_REPAIRING`.
- New NZB parameters, including `DupeKind`, `DupeFiles`, `DupeAlive`, and `DupeFleet`.
- Methods that change the system or reach out to the network need POST on the JSON-RPC and XML-RPC paths. JSON-P still runs them, as in NZBGet.
- `system.multicall` respects the caller's access level.
- Out-of-range numbers are rejected, `saveconfig` refuses malformed input, and several decoding and output bugs are fixed.

See [API and compatibility](api.md).

## Web interface

- Fleet tags such as `PRIMARY-3fa9c2`, `TWIN-3fa9c2`, and `ALT-81d0e4` on downloads and history items. Copies with the same fingerprint hold the same files.
- A score badge with each backup's measured health.
- A **Repair** badge during live repair, and a **dupe repair** post-processing status.
- **Recovered from duplicates** in the statistics dialog.
- History shows `twin` or `alt` instead of `dupe` where known.
- Escaping of names, categories, messages, and extension text that NZBGet printed as HTML, and `http` or `https` links only.
- Fixes to keyboard shortcuts, the filter box, upload errors, and size totals.

## Security and robustness

- Extension downloads use generated filenames, closing a path traversal, and a failed update keeps the old version.
- File cleanup never follows symbolic links.
- NZB parsing refuses XML entity declarations.
- The control port limits concurrent connections and keeps running when a thread or a connection fails.
- State files accept lines of any length. In NZBGet, a line over 1,024 characters can crash the program.
- The lock file is deleted only by the process that owns it.
- Scripts get close-on-exec pipes, full-length output lines, and a correct exit code when a signal kills them.

## Bug fixes

RustyGet fixes more than 100 inherited bugs, most of them reported to the NZBGet project along the way. Highlights:

- **Downloads:** 451 errors count as missing, 502 login refusals move on, malformed headers move to the next server, a connection that times out in the middle of an article is closed instead of reused, yEnc data can't overrun its range, and uuencoded parts no longer pass through the article cache.
- **Post-processing:** `ParScan=extended` and `ParScan=dupe` find extra blocks again, split files join correctly, a failed direct unpack no longer deletes the download folder, `ParTimeLimit` counts from the right moment, RAR-rename works per folder, and archives with encrypted headers parse.
- **Queue and history:** concurrent appends, names with newlines or slashes, long names, merges, splits, and edits of missing items all behave.
- **Files:** moves across file systems and copies that fail leave no partial file behind.
- **Feeds and URLs:** fixes to dates in RFC 822 format, redirects, protocol-relative URLs, and the retry loop.
- **Clock changes:** the scheduler, quotas, and maintenance handle a clock that moves backward.

## Build

- `rust/rust-toolchain.toml` pins Rust 1.99.0. CMake finds Cargo and builds the crate into the binary; without Rust, the C++ fallbacks build instead.
- The par2 parsing for twins uses the `rust-par2` crate.
- The inherited GitHub workflows for builds, packages, and tests are turned off while the tests are rebuilt. Only the documentation workflow runs.
