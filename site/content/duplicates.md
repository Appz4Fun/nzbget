+++
title = "Duplicate handling"
description = "How RustyGet recognizes copies of the same title with duplicate keys, picks one with duplicate scores and modes, and falls back to backups from history."
eyebrow = "Features"
lede = "The same title gets posted many times, by many posters, in many versions. Duplicate handling makes sure RustyGet downloads it once, picks the version you prefer, and falls back to another version when a download fails."
+++

> [!NOTE] Two layers
> This page covers the duplicate handling that RustyGet shares with NZBGet: keys, scores, modes, and backups. [Duplicate fleets](duplicate-fleets.md) covers what RustyGet adds on top: borrowing articles between copies, twins and alts, stream repair, and early failover.

## Why duplicates matter

Take one episode as an example. Within a few days, an indexer lists a WEB-DL, two HDTV releases, a subtitled release, and 720p and 1080p versions from several groups, between 1.2 GB and 9.4 GB. Filters can narrow that down, for example to 720p and 1080p only, but several versions still pass. Without duplicate handling, every one of them downloads.

Duplicate handling has two parts: **detection** decides which downloads are the same title, and **handling** decides which one to download and what to do with the rest.

## Detection

RustyGet treats two downloads as the same title when they share a duplicate key. Keys come from several places:

- **Newznab feeds** with extended attributes give the key automatically, from the IMDb ID for movies and from the TVRage, TVDB, or TVmaze ID with season and episode for shows.
- **Other feeds** get keys from your filter rules.
- **Clients** such as media managers and the Kodi add-on send a key with each download.
- **Everything else**, such as files added in the web interface or dropped into `NzbDir`, falls back to matching titles.
- **The same NZB file twice** is always caught, by comparing content.

You can also edit any download's key, score, and mode by hand.

> [!TIP] Turn on extended attributes
> Add `extended=1` to Newznab feed URLs, for example `https://indexer.example/api?apikey=KEY&t=search&q=dexter&extended=1`. Without it, feeds leave out the IDs that keys are built from.

## Duplicate keys

A duplicate key is a text string that's the same for every version of a title and different for every other title. Newznab feeds build it for you:

| Kind | Key format | Example |
|---|---|---|
| Movie | `imdb=<id>` | `imdb=175849` |
| Episode | `rageid=<id>-S<ss>-E<ee>` | `rageid=13434-S02-E10` |
| Episode, no TVRage ID | `tvdbid=<id>-S<ss>-E<ee>` or `tvmazeid=<id>-S<ss>-E<ee>` | `tvdbid=79349-S08-E10` |

For other feeds, set the key in a filter rule. Without one, RustyGet compares whole titles, which rarely match exactly between posters.

Match groups
: Each run of wildcard characters in a search term is a numbered group that you can use in an option. With `Accept(dupekey:dexter-${1}-${2}): dexter S##E##`, the title `Dexter.S08E10.720p` gets the key `dexter-08-10`. Every wildcard run counts, so in `*dexter*S##E##*` the season and episode are groups 3 and 4.

Season and episode variables
: `${season}` and `${episode}` hold the season and episode that RustyGet finds in the title, in either `S08E10` or `8x10` form, always formatted as `S08` and `E10`. For example, `Accept(dupekey:dexter-${season}-${episode}): dexter`.

The series option
: `Accept(series:dexter): dexter` is short for `dupekey:series=dexter-${season}-${episode}`, with one difference: when the title has no season or episode, such as a season pack, it sets no key at all. Prefer it for shows with seasons.

ID options
: When you mix Newznab and other feeds, make their keys match the Newznab form: `A(tvdbid:79349): dexter` sets the same key that a Newznab feed would.

| Title | `dupekey:dexter-${1}-${2}` with `S##E##` | `dupekey:dexter-${season}-${episode}` | `series:dexter` |
|---|---|---|---|
| `Dexter.S08E10.1080p` | `dexter-08-10` | `dexter-S08-E10` | `series=dexter-S08-E10` |
| `Dexter.8x10.1080p` | The term doesn't match | `dexter-S08-E10` | `series=dexter-S08-E10` |
| `Dexter.S08.Complete.720p` | The term doesn't match | Not useful: no episode | No key |

For daily shows, build the key from the date with a regular expression, for example `A(dupekey:tv=show-${1}): show $([0-9]+\.[0-9]+\.[0-9]+)`.

In the feed preview, hover over a status to see the key, category, and priority that an item would get.

## Duplicate scores

With good keys, RustyGet downloads only the first version of a title that arrives. With a feed that you poll often, that's usually the oldest posting, which might be the 720p version, while the 1080p version arrives days later and gets set aside.

Scores fix that. Every download carries a score next to its key, and the highest score wins:

```text
Require: ( 720p | 1080p )
Options(dupescore:1000): 720p
Options(dupescore:2000): 1080p
Accept: dexter
Accept: breaking bad
```

- All versions with the same key are added, but only the highest-scored one downloads. The others go to history as backups.
- If the download fails, the highest-scored backup starts.
- After a success, a new version downloads only if its score is higher. Lower ones go straight to history.

To stop waiting for a better version, mark the successful download as good in history.

### Duplicate status in filters

The `dupestatus` field lists the states of all downloads with the same key or title, separated by commas: `QUEUED`, `DOWNLOADING`, `SUCCESS`, `WARNING`, or `FAILURE`. Use it in rules, for example to lower the score of titles you already have:

```text
O(dupescore+:-10000): dupestatus:success | dupestatus:downloading
```

## Duplicate modes

| Mode | Behavior |
|---|---|
| `score` | Default. After a success, only a higher score downloads. |
| `all` | Every version downloads, whatever the score. Use it to compare versions and keep one by hand. |
| `force` | Downloads without any duplicate check. The **Add** dialog uses it when you turn off the duplicate check. |

`score` and `all` both stop when a successful version is marked good. Set modes with `dupemode` in filter rules, such as `Options(dupemode:all): *`.

> [!NOTE] Force mode in RustyGet
> In NZBGet a forced download never fails over. In RustyGet a forced download fails over to its backups like a scored one, so a client that re-sends a pick in force mode still gets a backup.

## Backups and history

Duplicate handling needs a long memory, because a title can show up in a feed weeks after you downloaded it. `KeepHistory` removes old items after 30 days by default, but items used for duplicate checks aren't deleted. They shrink from about 2 KB to about 200 bytes, keeping only the title, key, score, and status. The **Hidden** button in history shows them.

> [!CAUTION] Back up the queue directory
> A damaged history breaks duplicate checks. Back up `QueueDir`, which holds the history, with RustyGet stopped.

### Statuses

| Status | Meaning |
|---|---|
| `SUCCESS` | Downloaded. A later version downloads only with a higher score, or in force mode. |
| `FAILURE` | Failed. A backup has already moved to the queue; if there's none, feeds keep watching for the title. |
| `DUPE` | Set aside because another version was in the queue. It starts if that version fails. |
| `COPY` | An exact copy of an NZB file already in the queue or history. |
| `GOOD` | Marked good. New versions are ignored. |
| `BAD` | Marked bad. Handled like a failure. |

### Mark as good or bad

Mark as good
: Later versions from any source are ignored, and the waiting backups move to the old history.

Mark as bad
: Use it on a successful download that turned out wrong, such as one in the wrong language. The backups move back to the queue: one starts, and the rest wait paused. If there are none, feeds keep watching for the title.

## Failover and health

When a download can't complete, `HealthCheck` decides whether a backup takes over:

- `delete` deletes the failing download, and the best backup starts.
- `park` keeps the failing download's files in history and starts the best backup.
- `pause` pauses the download; you start a backup by hand.
- `dupe` <span class="tag tag-new">new</span> fails over early, as soon as it's clear that the download can't complete, and also catches copies that are dead before they start. See [Duplicate fleets](duplicate-fleets.md#early-failover).

RustyGet also changes some details of failover:

- A backup whose NZB file is gone, or that a check found dead, is skipped.
- Between backups with the same score, the one with more articles alive wins.
- A re-sent copy of the same NZB file counts as a backup, unless it's a copy of the download that just failed.
- When no backup qualifies, the message in the download's log says why each one was skipped.
- A title that's already on disk isn't downloaded again, and once one copy is on disk, the other copies of the key stop.
