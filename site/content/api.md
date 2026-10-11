+++
title = "API and compatibility"
description = "RustyGet's JSON-RPC and XML-RPC API: what stays compatible with NZBGet, the new appendfleet method and fields, security changes, and the plan for SABnzbd compatibility."
eyebrow = "Reference"
lede = "RustyGet speaks NZBGet's API today, so media managers, the Kodi add-on, and extensions work unchanged. As the rewrite moves on, the API may change, and RustyGet may add a SABnzbd-compatible API next to it."
+++

## Compatibility

> [!IMPORTANT] Compatibility isn't guaranteed
> RustyGet is a rewrite, not a fork that tracks NZBGet. Today it answers every NZBGet API method, but future versions may change or drop parts of the NZBGet API, and may add a SABnzbd-compatible API. Release notes list every change that breaks a client.

| Interface | Today | Plan |
|---|---|---|
| NZBGet JSON-RPC, XML-RPC, and JSON-P | Every method, with the changes on this page | Kept while clients depend on it. Methods may change where the old behavior is unsafe or in the way of the rewrite. |
| `appendfleet` | Available | Kept and extended |
| Extension scripts (`NZBPP_`, `NZBPO_`, `NZBNA_` variables, exit codes) | Unchanged, plus new `NZBPR_` parameters | Kept for now |
| SABnzbd API | Not available | Under consideration, so that clients that only speak SABnzbd can use RustyGet |
| `nzbget.conf` | NZBGet's format, plus new options | Kept for now |
| Queue and history files | NZBGet's formats, plus a trailer that NZBGet ignores | Kept for now |

## Connecting

The API listens on the web interface's port, 6789 by default, at three paths:

| Protocol | Path |
|---|---|
| JSON-RPC | `/jsonrpc` |
| XML-RPC | `/xmlrpc` |
| JSON-P | `/jsonprpc` |

Send credentials with HTTP basic authentication, or in the path, as in `http://user:pass@host:6789/jsonrpc`. Three accounts set what a client may do:

| Account | Options | Access |
|---|---|---|
| Control | `ControlUsername`, `ControlPassword` | Everything |
| Restricted | `RestrictedUsername`, `RestrictedPassword` | The web interface, but no changes to settings and no passwords |
| Add | `AddUsername`, `AddPassword` | `append`, `appendfleet`, and `version` only |

> [!WARNING] Use HTTPS on untrusted networks
> Basic authentication only encodes the password; it doesn't encrypt it. Turn on the HTTPS port in **SECURITY** if clients connect over a network you don't control.

JSON-RPC takes positional parameters only: names are ignored, and every parameter must be present, in order. Integers wider than 32 bits are split into `Lo` and `Hi` fields, such as `FileSizeLo` and `FileSizeHi`.

## Methods

These methods are inherited from NZBGet. The repository's [API reference](https://github.com/Appz4Fun/nzbget/blob/dupe-article-fallback/docs/api/API.md) documents each one's parameters and results.

| Area | Methods |
|---|---|
| Program | `version`, `shutdown`, `reload` |
| Queue | `listgroups`, `listfiles`, `append`, `appendfleet`, `editqueue`, `scan` |
| History | `history` |
| Status and logs | `status`, `sysinfo`, `systemhealth`, `log`, `writelog`, `loadlog`, `logscript`, `logupdate`, `servervolumes`, `resetservervolume` |
| Pause and speed | `rate`, `pausedownload`, `resumedownload`, `pausepost`, `resumepost`, `pausescan`, `resumescan`, `scheduleresume` |
| Configuration | `config`, `loadconfig`, `saveconfig`, `configtemplates` |
| Extensions | `loadextensions`, `downloadextension`, `updateextension`, `deleteextension`, `testextension` |
| Tests | `testserver`, `testserverspeed`, `testdiskspeed`, `testnetworkspeed` |

## appendfleet

`appendfleet` adds every copy of one release in a single call. RustyGet checks each copy on your news servers, queues the best, and keeps the rest as backups. [Duplicate fleets](duplicate-fleets.md#fleet-submission) explains how it ranks them.

```text
appendfleet(DupeKey, Category, Priority, Timeout, Name1, Content1, Name2, Content2, ...)
```

| Parameter | Type | Meaning |
|---|---|---|
| `DupeKey` | string | The key shared by every copy. Empty means RustyGet derives one from the first name. |
| `Category` | string | The category for every member. |
| `Priority` | int | The priority for every member. |
| `Timeout` | int | Seconds allowed for checking, from 5 to 120. The default is 45. |
| `NameN` | string | The member's filename, such as `Release.Name.nzb`. |
| `ContentN` | string | The NZB file in base64, or an `http://` or `https://` URL to fetch it from. |

Up to 50 members. JSON-RPC only; XML-RPC callers get an error.

The result:

```json
{
  "Chosen": 4182,
  "Complete": true,
  "Reason": "",
  "Members": [
    { "NZBID": 4182, "Name": "Release.Name [copy 01].nzb", "Rank": 1, "Alive": 99, "Status": "QUEUED", "SameAs": 0, "SameAsRank": 0, "Reason": "" },
    { "NZBID": 4183, "Name": "Release.Name [copy 02].nzb", "Rank": 2, "Alive": 97, "Status": "BACKUP", "SameAs": 0, "SameAsRank": 0, "Reason": "" },
    { "NZBID": 0, "Name": "Release.Name [copy 03].nzb", "Rank": 3, "Alive": 99, "Status": "SAME_POSTING", "SameAs": 4182, "SameAsRank": 1, "Reason": "" }
  ]
}
```

| Field | Meaning |
|---|---|
| `Chosen` | The ID of the download that runs: a new member, or a download of the key that was already running. `0` if none. |
| `Complete` | `false` when the time limit cut the check short, so some members are less well measured. |
| `Reason` | Why nothing new is downloading, when that's the case: `ALREADY_QUEUED`, `ALREADY_DOWNLOADED`, `ALL_DEAD`, `INCOMPLETE`, `NO_USABLE_MEMBERS`, `NO_MEMBERS`, `NOT_QUEUED`, `KEY_BUSY`, or `SHUTDOWN`. Retry after `KEY_BUSY` and `SHUTDOWN`. |
| `Members` | One entry per member, in rank order. |
| `Members[].Status` | `QUEUED` (downloading), `BACKUP` (kept in history), `SAME_POSTING` (a copy of another member or of an existing item), `COPY` (the same NZB file as an existing item), `DEAD`, `SKIPPED`, or `ERROR`. |
| `Members[].Alive` | Percent of the sampled articles found, or `-1` if unknown. |
| `Members[].SameAs`, `SameAsRank` | For `SAME_POSTING`: the ID of the item it duplicates, and that member's rank. |

## New fields and parameters

`listgroups` and `history` items have these extra fields:

| Field | Meaning |
|---|---|
| `DupeRecoveredArticles` | Articles recovered from duplicates. |
| `DupeRecoveredBytesLo`, `DupeRecoveredBytesHi` | Bytes recovered by stream repair. |
| `DupeRecoveredHoles` | Holes filled from decompressed donors. |
| `LiveRepairing` | `true` while live repair runs. |

The `listgroups` status and the `postqueue` stage can be `STREAM_REPAIRING`.

RustyGet also stores its findings as NZB parameters, which the API returns in `Parameters` and extensions see as `NZBPR_` variables:

| Parameter | Meaning |
|---|---|
| `DupeFiles` | The fingerprint of the posting's par2 file list, or `none` or `lost`. |
| `DupeKind` | `twin`, `twin:N/M`, or `alt`. |
| `DupeSampled`, `DupeSampledOf` | A twin or alt verdict from sampled articles, for postings without par2, and the primary it refers to. |
| `DupeAlive` | Percent of the posting found alive. `0` means dead, and failover skips it. |
| `DupeHealth` | The measured health of a backup. |
| `DupeSearch` | `yes` on copies that donor search added. |
| `DupeFleet` | The member's rank in its `appendfleet` call. |

## Changes to existing methods

RustyGet fixes several problems in NZBGet's API. Clients that rely on the old behavior may need changes:

- **POST only.** `downloadextension`, `updateextension`, `deleteextension`, `testextension`, `readurl`, `testserverspeed`, `testdiskspeed`, and `testnetworkspeed` no longer answer GET or JSON-P requests, so a link on another web page can't trigger them.
- **Access checks in multicalls.** The XML-RPC `system.multicall` method runs each call with the caller's access level. In NZBGet, a restricted account could read passwords through it.
- **Range checks.** Integers outside the 32-bit range are rejected instead of wrapping around. `editqueue` checks scores, priorities, parameters, and duplicate modes.
- **Safe configuration saves.** `saveconfig` refuses an empty or malformed option list instead of truncating the file.
- **Decoding.** `append` decodes post-processing parameters, so passwords with quotes work. Numeric escapes decode to UTF-8, and characters outside the Basic Multilingual Plane come out as valid JSON.
- **Correct output.** Request IDs are echoed in full, `servervolumes` returns valid JSON, and `resetservervolume` persists the reset.
