+++
title = "Duplicate fleets"
description = "How RustyGet uses every copy of a release together: article fallback, twins and alts, par2 from a twin, stream repair, early failover, and fleet submission."
eyebrow = "Features"
lede = "NZBGet keeps duplicates as spare downloads: when one fails, the next starts from scratch. RustyGet treats all copies of a release as one fleet. A gap in one copy is filled from another, a dying copy hands over within seconds, and every borrowed article is checked before it counts."
+++

## Vocabulary

Fleet
: Every download that shares a duplicate key: the one downloading now plus the backups waiting in history. See [Duplicate handling](duplicates.md) for how keys are set.

Primary
: The copy that's downloading. The web interface tags it <span class="tag tag-primary">PRIMARY</span>.

Twin
: A backup whose files are byte-identical to the primary's, proven by the checksums in the two postings' par2 files: the full MD5, the MD5 of the first 16 KB, and the length of every file. A twin's articles and par2 volumes can be used freely. Tagged <span class="tag tag-twin">TWIN</span>, or `TWIN N/M` when more than half of the files match.

Alt
: The same release from another encode, so the bytes differ. An alt is only a failover backup; nothing is borrowed from it. Tagged <span class="tag tag-alt">ALT</span>.

Same posting
: Two NZB files that point to the same Usenet articles, such as one posting listed by two indexers. They can't back each other up, because they share every missing article. RustyGet recognizes them by their Message-IDs and keeps one.

Donor
: Any duplicate that supplies articles or bytes to the primary.

## The layers

Each layer handles what the one before it couldn't. Turn them on in this order.

| Layer | Setting | What it does |
|---|---|---|
| Duplicate check | `DupeCheck=yes` | Groups copies by key and keeps backups. Inherited from NZBGet. |
| Article fallback | `DupeArticleFallback=article` | Fetches articles that no server has from matching files in other postings. |
| par2 from a twin | Automatic | Repairs with a twin's recovery volumes when the download's own par2 falls short. |
| Stream repair | `DupeArticleFallback=stream` | Patches holes with verified bytes from duplicates after the download, even across different packaging. |
| Live repair | `DupeArticleFallback=live` | Runs stream repair while the download is still running. |
| Early failover | `HealthCheck=dupe` | Switches to a better backup as soon as the primary can't complete. |
| Donor search | `DupeSearch=yes` | Finds more copies through NZBHydra2 and queues the live ones as backups. |
| Fleet submission | `appendfleet` | Lets a client send every copy at once and have RustyGet pick the best. |

Every new setting defaults to NZBGet's behavior, so an existing setup changes nothing until you opt in.

## Article fallback

When an article fails on every server, RustyGet asks the fleet for it. It looks for the same file in the other copies, in the queue and in history, highest score first, and fetches the matching article by its Message-ID.

### Finding the matching file

RustyGet tries three ways to match a file in the primary to a file in a donor, in order:

1. **By content.** The par2 files of both postings list each file's MD5 and length. Equal values prove the files are byte-identical, whatever their names.
2. **By name.** A file with the same name, matched without case, if exactly one donor file has it.
3. **By structure.** The same article count, a total size within 1/64, each article within 1/16, and the same part count in the subject line. Ties go to the file whose article sizes step the same way.

### Making sure the bytes are right

RustyGet checks a borrowed article before it counts:

- Its yEnc header must place it exactly where the missing article belongs, next to the articles around it. If the size, start, or end disagree, it's rejected before anything is written.
- It's written to a staging file, never straight into the output, and the finished file must tile with no gaps or overlaps.
- Its yEnc checksum must match, even with `CrcCheck=no`.
- When the primary's par2 set describes the file, the article's data must match that set's block checksums. If the set doesn't list the file, or lists no usable checksums for it, this check can't run, and only the other checks apply. RustyGet blocks a donor that fails for the rest of the download.

That's why article fallback needs par2: RustyGet doesn't borrow articles for a download that has no par2 files, and it never borrows par2 files themselves. It also stays off for downloads in force mode and with `RawArticle=yes`.

### Cutover and lead rotation

After three articles of a file have been recovered from duplicates, RustyGet asks the lead duplicate first for the rest of the file and tries the primary last. That saves a failed request per article when a whole stretch is missing. If the lead donor misses three articles in a row, the next donor takes over.

> [!IMPORTANT] Keep the NZB files of backups
> History items can only donate while their NZB file is still in `NzbDir`. Set `NzbCleanupDisk=no`.

## Repair with a twin's par2 files

par2 repair needs as many recovery blocks as there are damaged blocks. When a download is short, RustyGet checks the fleet for a twin. If one exists, it fetches the twin's par2 index file, works out which of the twin's recovery volumes cover the missing blocks, downloads only those, and repairs with the twin's par2 set.

The twin's set is separate from the download's own set, so its volumes can't simply be added to the repair; RustyGet runs the repair with the twin's set, and only when the filenames in both sets match.

To find twins, RustyGet fetches the smallest par2 file of each posting, at most 16 MB, and stores a fingerprint of its file list. For postings without par2, it compares six articles at the same positions in both postings instead.

## Stream repair

Article fallback needs a donor with the same articles. Stream repair works with bytes instead, so it can repair from postings that are split, packed, or even encrypted differently. It runs after the download and before par check, and it tries the cheapest method first:

1. **Same bytes.** The donor file must have the same size, and two probe reads from it must match bytes the primary already has, exactly, before any hole is patched. Each probe compares up to 16 KB, and runs of a single repeated byte don't count as a match.
2. **Whole files.** A file that received nothing at all is rebuilt from a donor, but only after the donor proved identical on the release's other, intact files.
3. **Different packaging.** RustyGet maps the media inside both postings, across bare files, raw `.001` splits, store-mode RAR (versions 3 and 5), stored ZIP including ZIP64, and 7-Zip in copy mode. A donor in one form can fill holes in another.
4. **Different encryption.** For store-mode RAR with the password in the NZB, donor bytes are encrypted with the primary's key and compared and patched in encrypted form. This also works when the two postings use different passwords.
5. **Compressed donors.** With `DupeStreamDecompress=yes`, RustyGet downloads a compressed donor archive, extracts it with `UnrarCmd` or `SevenZipCmd` into a temporary folder, and uses the extracted file. RustyGet rejects archives with symbolic links and caps the size at 16 GiB.

Stream repair only writes inside holes, and only after a donor is verified against this file. par2 still has the final say: after any donor write, RustyGet runs a full par check, not the quick one, because download-time checksums don't cover donor data. A file whose holes are all filled counts as complete again, so a release without par2 can still finish with `SUCCESS`.

### Your own par2 files first

When the download's own par2 can repair the damage, stream repair stays out of the way: par repair runs first, and stream repair only takes on what par2 can't fix. If par2 clearly can't cover the damage, RustyGet tries the fleet first and skips a par check that's bound to fail.

### Time limits

`DupeStreamTimeout` (default 60 seconds) stops a repair that goes that long without recovering anything. Waiting for a free connection doesn't count. It also stops a repair that would take more than three times as long as downloading the release again, and any repair after five times the timeout.

### Live repair

With `DupeArticleFallback=live`, stream repair also runs while the rest of the release downloads, once per file. It doesn't decompress donors and doesn't change health; the repair after the download still decides.

## Early failover

`HealthCheck=dupe` acts like `none` until a backup is worth switching to. A backup qualifies when its score is at least the primary's score times its health. When the primary can't complete, it's parked with its files kept, and the best backup takes over at once.

RustyGet decides that a primary can't complete in several ways:

Dead before it starts
: When a download starts and a backup waits in history, RustyGet probes ten articles spread across the posting on every server. If fewer than two exist and every reachable server gave a definite answer, RustyGet parks the download before it uses any bandwidth.

Dead while downloading
: 64 failed articles beyond the first of each file, with fewer than 1 in 100 of its own articles arriving. Or 40 failures in a row in a part that par2 can't repair.

Projected to fail
: After 200 tried articles, health projected below critical health, with a backup that's clearly more complete.

Too damaged for par2
: Health counts articles, but par2 repairs whole blocks. RustyGet counts the par2 blocks that failed articles actually spoil and compares them with the recovery blocks available. When the damage is certain to exceed the recovery data, the download fails over.

With article fallback on, failover waits until the fleet was asked for 32 missing articles and supplied less than half, so a gap that borrowing can fill doesn't cost a failover. Without any backup, RustyGet parks a hopeless download anyway: at least a tenth of it tried with fewer than 10% of those articles present.

Failover chooses backups with care. It skips a backup whose NZB file is gone, one that a check found dead, and a copy of the posting that just failed, and among equal scores the most complete one wins. If nothing qualifies, the download's log says why each backup was skipped.

### Retry after a failure

With article fallback or `HealthCheck=dupe` on, when a download fails with missing articles, RustyGet asks every server for up to ten of the failed articles again, within 60 seconds. If at least half now exist, the articles were only late to arrive, and RustyGet retries the failed articles once.

## Donor search

With `DupeSearch=yes`, RustyGet looks for more copies of each new download on its own. It searches through NZBHydra2 or another Newznab endpoint. It checks how much of each copy is alive on your servers and adds the live ones as backups. See [Donor search](dupesearch.md).

## Fleet submission

Clients that already know every copy, such as the [Kodi add-on](kodi.md), send them in one `appendfleet` call. RustyGet then:

1. Reads each NZB file, and marks members that are the same posting as another member, or as something RustyGet already has, as `SAME_POSTING`.
2. Holds downloads for a moment, so the check gets connections, and checks a sample of each posting on all servers at once, within the call's time limit.
3. Ranks the members: checked and alive first, then unknown, then dead. Within a group, the most complete copy wins, then the copy whose size is closest to the fleet's median size, which is usually the release's own packaging, then the order the client sent.
4. Adds every usable member under the key, with scores that follow the rank. The duplicate check queues the top one and keeps the rest as backups. If a download of the key is already running, the members become its backups instead.
5. Replies with the chosen download, a reason, and a status for every member.

If the release is already on disk, RustyGet adds nothing and the reply says `ALREADY_DOWNLOADED`. See [API and compatibility](api.md#appendfleet) for the full call.

## What you see

- Tags in the download and history lists show each copy's role and a short fingerprint, such as `PRIMARY-3fa9c2` and `TWIN-3fa9c2`. Copies with the same fingerprint hold the same files.
- A score badge shows each backup's score and measured health.
- A **Repair** badge appears while live repair runs, and the post-processing status reads **dupe repair** during stream repair.
- The statistics dialog of a download shows **Recovered from duplicates**: articles, and megabytes once bytes were recovered.
- Each download's log names every donor, every failover, and why.

## Recommended settings

| Option | Value | Why |
|---|---|---|
| `DupeCheck` | `yes` | Fleets are built on duplicate keys. |
| `HealthCheck` | `dupe` | Fails over early instead of downloading a copy that can't complete. |
| `DupeArticleFallback` | `live` | Uses every layer. Start with `article` on slow devices. |
| `DupeStreamDecompress` | `no` | Turn it on only with working extractors and spare CPU. |
| `NzbCleanupDisk` | `no` | Keeps backups' NZB files so they can donate. |
| `ArticleRetries` | `3` or more | Keeps one network error from looking like a missing article. |
| `ParScan` | `extended` or `dupe` | `dupe` also borrows par2 blocks from duplicates in history. |
