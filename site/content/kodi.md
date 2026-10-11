+++
title = "Streaming with Kodi"
description = "How the NeNeTeePee Stream Kodi add-on uses RustyGet as its download backbone: search through NZBHydra2, quality ranking, fleet deduplication, and appendfleet."
eyebrow = "Features"
lede = "The NeNeTeePee Stream add-on for Kodi can use RustyGet as its backbone. It finds every copy of the release you pick, removes the copies that are really the same posting, and hands the rest to RustyGet in one call. RustyGet checks which copies are alive on your servers and downloads the best one."
+++

## Who does what

The add-on and RustyGet split the work along what each can see.

| Step | Done by | Based on |
|---|---|---|
| Search every indexer | Add-on, through NZBHydra2 | Movie or episode IDs, then titles |
| Rank releases by quality | Add-on | Resolution, HDR format, remux, preferred release groups, audio format, size |
| Pick a release | You, or the add-on's automatic pick | The ranked list |
| Gather every copy of that release | Add-on | Parsed release names and NZBHydra2's results |
| Drop copies of the same posting | Add-on | Listing size and post time, then Message-ID overlap |
| Check which copies are alive | RustyGet | Article checks on your own news servers |
| Download the best copy, keep the rest as backups | RustyGet | Alive share, twin proof, score |
| Repair gaps and fail over | RustyGet | Twins, alts, par2 |
| Play the finished file | Add-on | SMB, NFS, or a local path |

The add-on decides *which release* you get. RustyGet decides *which copy* of that release downloads, because only your news servers can say which copies still exist.

## The add-on

[NeNeTeePee Stream](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi) is a Kodi 21 add-on (`plugin.video.nzbdav`) that plays movies and episodes from Usenet. TMDb Helper calls it as a player. It supports three backends:

- **nzbdav or InfiniDysk**, which stream over WebDAV while downloading.
- **NZBGet**, which downloads and unpacks the whole release, then plays the finished file. RustyGet is a drop-in for this backend.
- **StreamNZB**, which returns a direct HTTP stream.

Fleet submission with `appendfleet` came in add-on pull requests [514](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi/pull/514), [518](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi/pull/518), and [519](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi/pull/519). It ships in the add-on's beta channel, which publishes every pre-release tag: the first beta after 2.0.0-beta.2 includes it. Beta 2 sends backups one at a time with `append` instead.

## Step 1: search through NZBHydra2

The add-on searches NZBHydra2, Prowlarr, and direct Newznab indexers at the same time and merges the results. [NZBHydra2](nzbhydra2.md) is the recommended source: one URL and one API key cover all of your indexers, and each result names the indexer it came from.

- **Movies** search by IMDb ID (`t=movie&imdbid=`) when the indexer supports it, and by title and year otherwise.
- **Episodes** search by TVDB or IMDb ID with season and episode (`t=tvsearch`), adding the title where supported.
- An empty answer triggers one more search by title alone.

Results with the same download link are merged. The same release from two indexers stays as two rows, because those rows become backups later.

## Step 2: rank releases by quality

Indexers report little more than a title, a size, and a date, so the add-on parses each release name into resolution, codec, HDR format, audio format, channels, release group, edition, languages, and flags such as proper, repack, and 3D. Your filters remove what you don't want, and the rest sort in this order:

1. Resolution, highest first.
2. HDR format: Dolby Vision, then HDR10+, HDR10, HLG, other HDR, and SDR last.
3. Remux: hybrid remux, then remux, then everything else.
4. Preferred release groups, in three tiers that you can edit.
5. Audio: Atmos with TrueHD first, then Atmos, TrueHD, DTS:X, lossless DTS-HD MA and FLAC, and down to AAC.
6. Size, largest first.

You pick from the list, or turn on **Auto-select best match** to take the top row.

## Step 3: gather the fleet

A *fleet* is every copy of the release you picked. The add-on builds it from the ranked list and from everything NZBHydra2 returned:

1. **Same name.** Rows whose release name matches the pick exactly.
2. **Same release, different name.** Rows whose parsed names agree on everything that matters: title, year or season and episode, release group, resolution, codec, container, HDR set, audio, edition, languages, and flags. Size isn't used, so a repost with different packaging still counts.
3. **Other uploads.** Rows with the pick's exact title and a different link from NZBHydra2's first answer, including ones your filters hid.
4. **Extra copies.** If slots remain, the add-on downloads candidate NZB files and compares what they contain, such as the main video's name and the total size.

`nzbget_max_backups` caps the fleet. The default, `-1`, sends every copy up to the limit of 50.

## Step 4: drop copies of the same posting

Two indexers often list the same Usenet posting. Sending both wastes a check, and one can't back up the other: when one is missing an article, so is the other. The add-on removes them twice.

Before downloading NZB files
: Rows with the same size, posted within 120 seconds of each other, are one posting. Only the best-ranked row downloads; the others are tried only if its indexer fails.

After downloading NZB files
: The add-on reads every article's Message-ID and compares fingerprints. NZB files that share more than 1% of their Message-IDs describe the same posting, and only the first stays. A re-upload that shares no Message-IDs stays in, and it's the most valuable backup there is: it has its own copy of every article.

## Step 5: send the fleet with appendfleet

The add-on sends all members in one `appendfleet` call:

```json
{
  "method": "appendfleet",
  "params": [
    "imdb=1234567|movie-title-2024-2160p-uhd-bluray-remux-group",
    "Movies", 0, 45,
    "Movie.Title.2024.2160p.UHD.BluRay.REMUX-GROUP [NZBDAV copy 01].nzb", "<base64 NZB>",
    "Movie.Title.2024.2160p.UHD.BluRay.REMUX-GROUP [NZBDAV copy 02].nzb", "<base64 NZB>"
  ]
}
```

The parameters are the duplicate key, the category, the priority, a time limit in seconds, and then name and content pairs. The duplicate key joins a content ID, such as `imdb=` or `tvdbid=` with season and episode, to the release name, so every copy lands under one key.

## Step 6: RustyGet checks and chooses

For each member, RustyGet:

1. Reads the NZB file and spots copies of the same posting that the add-on couldn't see.
2. Checks a sample of articles on all of your news servers, and downloads and verifies a few in full.
3. Drops members that are mostly gone (below `DupeMinAlive`).
4. Queues the most complete member, and parks the others in history as scored backups.
5. Answers with the chosen download, a reason, and a status for every member.

If the release is already on disk, nothing downloads. If another fleet for the same key is still being checked, the call returns `KEY_BUSY` and the add-on retries. The add-on then shows how many good copies RustyGet found and the health of the one it chose.

## Step 7: download, repair, and fail over

From here the fleet features take over:

- An article that no server has is borrowed from a matching file in a backup. Matching by content comes first, so a **twin**, a backup whose files are byte-identical as proven by par2 checksums, is the first choice.
- A copy that's dying fails over early to the best backup with `HealthCheck=dupe`.
- An **alt**, the same release in another encode, serves as a failover backup only. Nothing is borrowed from it.

The add-on follows the duplicate key: if RustyGet fails over, the add-on tracks the promoted backup. When a copy completes with `SUCCESS`, the add-on plays it from your completed folder.

See [Duplicate fleets](duplicate-fleets.md) for how twins, alts, and failover work.

## Stock NZBGet

The add-on also works with stock NZBGet. When `appendfleet` is missing, it falls back to one `append` per copy, with the pick at the highest duplicate score and the backups below it. NZBGet's duplicate handling then fails over between copies, but no copy is checked before downloading and nothing is borrowed between them.

## Settings

In the add-on:

| Setting | Value |
|---|---|
| Playback backend | NZBGet |
| NZBGet URL, user name, password | Your RustyGet address and an account. An `AddUsername` account can call `appendfleet`, but the add-on also reads the queue and history, so use a full or restricted account. |
| NZBGet category | A category that RustyGet knows |
| Completed folder | The SMB share or local path where that category's `DestDir` appears to Kodi |
| Maximum duplicate backups | `-1` for all, `0` for none, or a cap |
| Enable fallback streams | On. This also turns the NZBGet fleet on. |
| Enable NZBHydra2, NZBHydra2 URL, API key | Your NZBHydra2 instance |

In RustyGet:

| Option | Value | Why |
|---|---|---|
| `DupeCheck` | `yes` | Keeps backups in history under the fleet's key |
| `HealthCheck` | `dupe` | Fails over to a backup instead of pausing. The add-on warns if this is `pause`. |
| `DupeArticleFallback` | `article` or `live` | Borrows missing articles from twins |
| `NzbCleanupDisk` | `no` | Keeps backups' NZB files so they can serve as sources |
| `DupeMinAlive` | `50` | The share of a copy that must be alive to take part |
