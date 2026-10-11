+++
title = "Donor search"
description = "How DupeSearch finds more copies of a new download through NZBHydra2, checks them on your news servers, and queues the live ones as backups."
eyebrow = "Features"
lede = "A fleet is only as strong as its backups. With DupeSearch, RustyGet looks for other postings of each new download itself, checks how much of each still exists on your servers, and keeps the live ones ready as backups and donors."
+++

> [!WARNING] DupeSearch sends traffic to your indexers
> Each search makes several API calls and downloads several NZB files. Start with `DupeSearchDryRun=yes`, set limits in NZBHydra2, and read the log before you turn it on for real.

## When a search runs

RustyGet searches for a download after it's added and `DupeSearchDelay` (20 seconds by default) has passed. The delay lets a client's own backups arrive first, so the search doesn't duplicate them. RustyGet searches for a download only when:

- `DupeCheck` is on, and the download is in `score` mode.
- It's the top-scored item of its duplicate key, and it's still downloading.
- It isn't itself a copy that DupeSearch added.
- Its key wasn't searched in the last six hours, unless a higher-scored download arrived since.

At startup, RustyGet also searches for queued downloads and for downloads that failed in the last hour. A download without a key gets one from its normalized name, such as `dupes:show-name-s02e14-1080p`, and RustyGet raises its score to 1,000,000 so that every copy found ranks below it.

## How it searches

DupeSearch talks to one Newznab endpoint, which is why [NZBHydra2](nzbhydra2.md) is recommended: it puts every indexer behind that endpoint. RustyGet sends up to five queries:

1. The full normalized title, with `t=search`.
2. A short form, such as `lucifer s02e14 1080p`.
3. The short form plus the release group.
4. `t=movie` with the IMDb ID, if the NZB file carries one.
5. `t=tvsearch` with the TVDB ID, season, and episode, if the NZB file carries an ID and the name has a season and episode.

Each query reads up to five pages of 100 results, four queries at a time. The API key is always sent last and hidden in logs.

## Which results count

A result counts as the same release only if its parsed name agrees with the download's on the title, release group, season and episodes, repack and proper flags, and HDR format. Other details, such as resolution, source, codec, and audio, must not conflict. Size is never a reason to accept a result.

Then RustyGet removes copies it doesn't need:

- **Repeated listings.** Results with the same size, posted within 120 seconds of each other, are one posting.
- **Same posting.** After it downloads the NZB files, RustyGet compares a fingerprint of each one's Message-IDs. NZB files that share more than 1% of their articles are the same posting, so only one stays.
- **Known dead postings.** RustyGet skips postings found dead in the last three days.

NZB files download one at a time per indexer, with one retry. When an indexer answers an NZB download with HTTP 403 or 429, it gets a 30-minute break. RustyGet tells indexers apart by the names that NZBHydra2 reports, so the break applies only through NZBHydra2.

## Checking health

A listing says nothing about whether a posting still exists on your servers, so RustyGet checks each candidate before using it:

- **Sample.** It checks `DupeHealthPercent` of the posting's articles (5% by default), at least `DupeHealthMin` and at most `DupeHealthMax`.
- **Existence.** It asks every server about each sampled article with pipelined `STAT` commands.
- **Content.** Up to `DupeBodyChecks` articles download in full and must pass their yEnc checksum, because a server can claim an article whose body is gone.
- **Limits.** The check uses at most half of each server's connections and ends after `DupeHealthBudget` seconds. An article counts as missing when every server answered and none of them has it. If the time runs out first, an article that at least half of the servers reported missing counts as missing too.

A first pass checks about ten articles of each candidate. RustyGet queues the best `DupeFastDonors` candidates that pass it right away, before the full check finishes.

## Scoring and queueing

RustyGet adds each measured candidate that's at least `DupeMinAlive` percent alive as a backup under the download's key, with a score below the download's. A candidate that the check couldn't measure, for example because too few servers answered in time, is added too, as an unchecked backup that scores as if it were whole.

- The base is the download's score minus 1,000.
- On top of the base, a live copy gets 9 plus up to 80 for its alive share, at most 90 in all. A copy that matches the download's file count and total size gets one more point, which breaks ties in its favor.
- The search also checks the backups the key already holds, including a client's own, and records each one's health as `DupeHealth`. It reorders them with the new copies, but never raises the score of a copy that isn't whole. A backup that turns out dead drops to the lowest score and gets `DupeAlive=0`, so failover never picks it.

Because the score is lower, the duplicate check files each copy in history as a backup. From there it can donate articles and bytes, and take over through failover. `DupeSearchMaxDonors` caps how many copies one download gets.

## Resume and dry run

RustyGet saves search progress in the queue directory, so a restart picks up where it stopped without downloading the NZB files again. With `DupeSearchDryRun=yes`, RustyGet logs every query, every candidate, and what it would queue and score, but changes nothing and leaves no saved state.

## Settings

| Option | Default | Meaning |
|---|---|---|
| `DupeSearch` | `no` | Turns the search on. Turns itself off with a warning if `DupeSearchUrl` is empty. |
| `DupeSearchUrl` | empty | The Newznab endpoint, such as `http://127.0.0.1:5076/api`. A URL without a path gets `/api`. |
| `DupeSearchApiKey` | empty | The endpoint's API key. |
| `DupeSearchDelay` | `20` | Seconds to wait after a download is added. |
| `DupeSearchDryRun` | `no` | Log only. |
| `DupeSearchMaxDonors` | `0` | Most copies to queue per download. `0` means no limit. |
| `DupeHealthPercent` | `5` | Share of a posting's articles to check. |
| `DupeHealthMin` | `50` | Fewest articles to check per posting. |
| `DupeHealthMax` | `1000` | Most articles to check per posting. |
| `DupeBodyChecks` | `20` | Articles per posting to download and verify in full. |
| `DupeHealthBudget` | `120` | Seconds allowed for checking one posting. |
| `DupeMinAlive` | `50` | Percent of a posting that must be alive to queue it. |
| `DupeFastDonors` | `5` | Copies to queue right after the first quick check. |

RustyGet warns at startup when DupeSearch is on and `DupeCheck` is off, `HealthCheck` isn't `dupe`, `ArticleRetries` is below 3, or a server has fewer than four connections.
