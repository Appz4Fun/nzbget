+++
title = "Servers, categories, RSS, and scheduling"
nav_title = "Servers, RSS, scheduling"
description = "Configure news servers and fill servers, sort downloads with categories, filter RSS feeds, and schedule pauses, speed limits, and quotas."
eyebrow = "Features"
lede = "Most of RustyGet's day-to-day behavior comes from four settings areas: the news servers it downloads from, the categories it sorts into, the RSS feeds it watches, and the schedule it follows."
+++

## News servers

Add each Usenet provider as a server in the **NEWS-SERVERS** section. Servers have a level, which works as a priority:

| Role | `ServerN.Level` | When it's used |
|---|---|---|
| Main server | `0` | First, for every article. At least one active server must be at level 0. |
| Fill server | `1` | Only for articles that the main servers don't have. |
| More fill servers | `2` and up | In order, for articles that the lower levels don't have. |

A fill server is usually a block account, which sells a fixed volume of data rather than a monthly plan. Fill servers carry little traffic, because they only see articles that every lower level missed. Mark a server as `ServerN.Optional=yes` when it's unreliable, so a failure there doesn't count against the download.

Use encryption (`ServerN.Encryption=yes`, usually on port 563 or 443) and keep `ServerN.CertVerification=strict`. Set `ServerN.Connections` to what your plan allows; see [Performance tuning](performance.md) for picking a number.

> [!TIP] Missing articles on every server
> When no server has an article, RustyGet can still fetch it from a duplicate posting of the same release. See [Duplicate fleets](duplicate-fleets.md).

## Categories

Categories sort downloads into folders and decide how each kind is processed. Each `CategoryN` sets:

- `CategoryN.Name` and `CategoryN.Aliases`: the category and other names that map to it, such as the names that indexers use.
- `CategoryN.DestDir`: where finished downloads go.
- `CategoryN.Unpack`: whether to unpack archives.
- `CategoryN.Extensions`: which post-processing extensions run.

Media managers such as Sonarr and Radarr set the category when they send a download. A file dropped into a subdirectory of `NzbDir` gets the category with that directory's name.

## RSS feeds and filters

RustyGet can watch RSS feeds on its own, with no other automation software. Each `FeedN` has a URL, a polling interval, and a filter.

### Search terms

A filter line is a list of search terms, and every term must match. A plain word matches a whole word of the title, so `gam` doesn't match the word game. Wildcards extend a word: `?` matches one character, `*` matches any run of characters, and `#` matches one digit.

The full form of a term is `[+|-][field:][command]value`:

- `-` turns the term around: the item is skipped if the term matches.
- `field` defaults to `title`. Other text fields are `filename`, `category`, `link`, `genre`, and `dupekey`. Number fields include `size`, `age`, `rating`, `imdbid`, `tvdbid`, `tvmazeid`, `season`, `episode`, `priority`, and `dupescore`.
- `command` is `@` for a word search (the default), `$` for a regular expression, or a comparison such as `<`, `>=`, or `=`.

Sizes take `K`, `M`, or `G` units, and ages take `m`, `h`, or `d`. Group terms with spaced parentheses and `|` for "or":

```text
dexter ( 720p | 1080p ) size:>1GB size:<5GB -category:sd
```

### Rules

A multi-line filter is a list of rules, checked from the top. The first rule that decides wins:

| Rule | Short form | Effect |
|---|---|---|
| `Accept:` | `A:` | If the line matches, download the item and stop. A line without a prefix is an accept rule. |
| `Reject:` | `R:` | If the line matches, skip the item and stop. |
| `Require:` | `Q:` | If the line doesn't match, skip the item and stop. |
| `Options:` | `O:` | If the line matches, set options and keep checking. |
| `#` | | A comment. |

An item that no rule accepts or rejects is ignored. Rules can carry options in parentheses: `category`, `pause`, `priority`, `dupekey`, `dupescore`, and `dupemode`, each with a short form. For example:

```text
Reject: age:>10
Require: ( 720p | 1080p )
Options(dupescore:1000): 720p
Options(dupescore:2000): 1080p
Accept(series:dexter): dexter season:=8 episode:>0
```

The duplicate options in these rules feed RustyGet's duplicate handling, which [Duplicate handling](duplicates.md) explains in full.

### Feed scripts

When filters aren't enough, `FeedN.Extensions` runs a feed extension. RustyGet saves the feed to a file, the extension changes it, and RustyGet reads it back.

## Scheduler

Scheduled tasks run commands at set times. Each `TaskN` has a time (`TaskN.Time`, with `*` for every hour), week days (`TaskN.WeekDays`, such as `1-5`), a command, and a parameter. The commands are:

- `PauseDownload`, `UnpauseDownload`, `PausePostProcess`, `UnpausePostProcess`, `PauseScan`, and `UnpauseScan`.
- `DownloadRate`, with a limit in KB/s.
- `ActivateServer` and `DeactivateServer`, with server IDs.
- `FetchFeed`, with feed IDs.
- `Script` runs a scheduler extension, and `Process` runs a program.

RustyGet reports a task with an unknown command as a configuration error and skips that task. NZBGet runs such a task as `PauseDownload` instead.

## Speed limits and quotas

- `DownloadRate` sets a speed limit at start, and the web interface or the API changes it at run time.
- `MonthlyQuota` and `DailyQuota` pause downloading when a volume in megabytes is used up. `QuotaStartDay` sets the day the monthly quota resets.
- `DiskSpace` pauses downloading when free space drops below a size in megabytes.
