<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="site/assets/wordmark-dark.svg">
    <img src="site/assets/wordmark-light.svg" alt="RustyGet" width="520">
  </picture>
</p>

<p align="center">
  <a href="https://appz4fun.github.io/nzbget/"><img alt="Documentation" src="https://img.shields.io/badge/docs-appz4fun.github.io%2Fnzbget-a8400f"></a>
  <a href="https://github.com/Appz4Fun/nzbget/actions/workflows/pages.yml"><img alt="Docs build" src="https://github.com/Appz4Fun/nzbget/actions/workflows/pages.yml/badge.svg"></a>
  <img alt="Rust 1.99.0" src="https://img.shields.io/badge/rust-1.99.0-1d6f60">
  <img alt="Status: rewrite in progress" src="https://img.shields.io/badge/status-rewrite%20in%20progress-8a5a00">
  <a href="COPYING"><img alt="License: GPL v2 or later" src="https://img.shields.io/badge/license-GPL--2.0--or--later-3d5a73"></a>
</p>

RustyGet is a Usenet downloader that started as a fork of [NZBGet](https://github.com/nzbgetcom/nzbget) and is being rewritten in Rust. It carries every improvement from NZBGet [pull request 850](https://github.com/nzbgetcom/nzbget/pull/850), which NZBGet never merged, and builds on them: RustyGet treats every copy of a release as one **fleet**, so an article that's missing on every news server comes from another copy instead of failing the download.

**[Read the documentation](https://appz4fun.github.io/nzbget/)**

> [!IMPORTANT]
> RustyGet is no longer a fork. The repository has left GitHub's fork network and is a standalone rewrite. It still speaks NZBGet's API today, but future versions may break NZBGet API compatibility, and may add a SABnzbd-compatible API. See [API and compatibility](https://appz4fun.github.io/nzbget/api.html).

## Contents

- [What's different from NZBGet](#whats-different-from-nzbget)
- [How deduplication works](#how-deduplication-works)
- [Pull request 850](#pull-request-850)
- [A rewrite, not a fork](#a-rewrite-not-a-fork)
- [Build and run](#build-and-run)
- [Documentation](#documentation)
- [Contribute](#contribute)
- [License and credits](#license-and-credits)

## What's different from NZBGet

| Area | NZBGet | RustyGet |
|---|---|---|
| Language | C++ | C++ moving to Rust module by module, each port proven identical by differential tests |
| An article missing on every server | Lost, and left to par2 repair or failure | Fetched from a matching file in another copy of the release. A borrowed article must fit its place in the file, and, where they're available, it's checked against its yEnc checksum (with the default `CrcCheck=yes`) and the download's par2 block checksums |
| Duplicates of a release | Spare downloads, tried one after another from scratch | One fleet: copies lend each other articles, bytes, and par2 recovery volumes |
| Byte-identical copies | Not detected | **Twins** proven by par2 checksums (MD5, 16 KB hash, and length of every file); other encodes are **alts**, used only as backups |
| Not enough par2 blocks | Repair fails | Repairs with the fewest recovery volumes of a twin that cover the damage |
| Holes after the download | Left to par2 | Stream repair patches verified bytes from duplicates, even across RAR, ZIP, 7-Zip, raw splits, and encrypted RAR |
| A download that can't complete | Runs to the end, then fails over | `HealthCheck=dupe` fails over within seconds, and a probe parks dead copies before they download |
| Finding more copies | Only what feeds and clients send | `DupeSearch` queries NZBHydra2, checks each copy on your servers, and queues the live ones as backups |
| Clients with many copies | One `append` per copy | One `appendfleet` call: RustyGet checks every copy and downloads the most complete one |
| Configuration | 155 options | 16 new options and a new `HealthCheck` value, all off by default |
| API | NZBGet API | NZBGet API, plus `appendfleet`, new fields, POST for risky methods on the JSON-RPC and XML-RPC paths, and access checks in multicalls |
| Queue and history files | NZBGet formats | NZBGet formats, with RustyGet's data in a trailer that NZBGet ignores |
| Inherited bugs | | More than 100 fixed: downloads, post-processing, queue edits, state files, scripts, feeds, and the web interface |
| CI workflows | Builds and tests for every platform | Turned off while the tests are rebuilt; only the documentation deploys |

The new options are `DupeArticleFallback`, `DupeStreamDecompress`, `DupeStreamTimeout`, `DupeSearch`, `DupeSearchUrl`, `DupeSearchApiKey`, `DupeSearchDelay`, `DupeSearchDryRun`, `DupeSearchMaxDonors`, `DupeHealthPercent`, `DupeHealthMin`, `DupeHealthMax`, `DupeBodyChecks`, `DupeHealthBudget`, `DupeMinAlive`, and `DupeFastDonors`. The full list of changes is in [Differences from NZBGet](https://appz4fun.github.io/nzbget/differences.html).

## How deduplication works

The same release usually exists as many postings: reposts, listings on several indexers, and other encodes. NZBGet keeps them as spares. RustyGet uses them together, and it pairs with the beta version of the [NeNeTeePee Stream](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi) add-on for Kodi, which can use RustyGet as its download backbone.

### The add-on finds and deduplicates the fleet

1. **Search.** The add-on searches through [NZBHydra2](https://github.com/theotherp/nzbhydra2), the recommended Newznab front end, which puts all of your indexers behind one API. It searches by IMDb or TVDB ID first and by title as a fallback, alongside Prowlarr and direct indexers if you use them.
2. **Rank by quality.** It parses each release name and ranks by resolution, HDR format, remux, preferred release-group tiers, audio format, and size. You pick a release, or let the add-on pick the top one.
3. **Gather every copy.** It collects every row that's the same release as the pick: the same name, or a parsed name that agrees on title, year or episode, group, resolution, codec, HDR, audio, edition, and language. It also adds other uploads with the same title from NZBHydra2's answer, including ones your filters hid.
4. **Drop the same posting twice.** Rows with the same size, posted within 120 seconds of each other, are one listing seen through several indexers. After it downloads the NZB files, the add-on compares fingerprints of every article's Message-ID; NZB files that share more than 1% of their articles are the same posting, and only one stays. A re-upload that shares none is kept, because it's the strongest backup there is.
5. **Send the fleet.** It sends up to 50 copies in one [`appendfleet`](https://appz4fun.github.io/nzbget/api.html#appendfleet) call under a duplicate key built from the content ID and the release name.

### RustyGet picks the copy and keeps the rest working

1. **Check every copy on your servers.** RustyGet checks a sample of each posting's articles on all of your news servers at once, and downloads a few in full to verify their checksums. It marks copies of the same posting that the add-on couldn't see.
2. **Rank.** Copies that are alive come first, then unknown, then dead. Within a group, the most complete copy wins, then the one whose size is closest to the fleet's median, which is usually the release's own packaging.
3. **Queue the best, keep the rest.** The top copy downloads, and the others wait in history as scored backups, with their measured health.
4. **Borrow, repair, fail over.** During the download, a missing article comes from a matching file in another copy. It must fit its place in the file, and, where they're available, it's checked against its yEnc checksum (with the default `CrcCheck=yes`) and the download's par2 block checksums. [Duplicate fleets](https://appz4fun.github.io/nzbget/duplicate-fleets.html#making-sure-the-bytes-are-right) lists when a check can't run. Holes are patched from verified bytes. If the copy can't complete, the best backup takes over within seconds, and the add-on follows the duplicate key to the new download.

RustyGet can also search on its own: with `DupeSearch=yes`, it queries NZBHydra2 for more copies of each new download, checks them the same way, and adds the live ones as backups.

The add-on decides *which release* you get. RustyGet decides *which copy* of it downloads, because only your news servers know which copies still exist. Fleet submission with `appendfleet` came in add-on pull requests [514](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi/pull/514), [518](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi/pull/518), and [519](https://github.com/Appz4Fun/NeNeTeePee-Stream-Kodi/pull/519) and ships in the add-on's beta channel. With stock NZBGet, the add-on falls back to one `append` per copy.

For more detail, see [Duplicate fleets](https://appz4fun.github.io/nzbget/duplicate-fleets.html), [Streaming with Kodi](https://appz4fun.github.io/nzbget/kodi.html), [Donor search](https://appz4fun.github.io/nzbget/dupesearch.html), and [NZBHydra2](https://appz4fun.github.io/nzbget/nzbhydra2.html).

## Pull request 850

NZBGet pull request [850](https://github.com/nzbgetcom/nzbget/pull/850), "Add DupeArticleFallback: recover missing articles from duplicate releases," opened in July 2026. Over three months it grew from article fallback to the whole fleet: stream repair across packaging and encryption, live repair, early failover with `HealthCheck=dupe`, donor search through NZBHydra2, `appendfleet`, a queue format that NZBGet can still read, more than 100 fixes to inherited bugs, and a functional test harness with more than 100 scenarios. It reached 385 commits and about 45,000 added lines, much of it tests.

What the pull request's comments documented, in order:

- **July 8–12: article fallback.** An article that fails on every server is fetched from a duplicate posting of the same release, then checked by its yEnc header before anything is written. A per-file "Recovered N of M" log line and the `DupeRecoveredArticles` counter in the API and web interface. Cutover after three recoveries in a file, lead rotation after three misses in a row, and a fix for a use-after-free crash with many duplicates.
- **July 9–12: stream repair.** `DupeArticleFallback` became `no`, `article`, `stream`, or `live`. Byte-level repair from same-byte reposts, across packaging (store-mode RAR, ZIP, 7-Zip, raw splits), and across RAR encryption with the NZB password. `DupeStreamDecompress` repairs from compressed duplicates, live mode repairs during the download, and a fully repaired release without par2 completes with `SUCCESS`.
- **September 10: par2 first.** In the `stream` and `live` modes, when a download's own par2 files can repair the damage, they repair it first; in `article` mode, articles are borrowed right away. par2 files are never borrowed. The first article of each file is the exception: RustyGet borrows it at once, because it needs that article to identify and rename the file. Later work added another: when par2 clearly can't cover the damage, duplicates go first.
- **September 12: no more stalls.** A repair that waited hours on an unavailable duplicate moves on to the next one; requests for one release dropped from 258 to 9.
- **October 2: renamed and obfuscated duplicates.** Up to 8 probe articles per file, up to 32 same-size files of an obfuscated posting checked, a full par check instead of the quick one when par check runs after a donor write, and the repair after the download fetching with a quarter of the main servers' connections, but between 4 and 16 of them; live repair fetches one article at a time.
- **October 5: failover and search.** `HealthCheck=dupe` with a dead-copy probe, `DupeStreamTimeout`, `DupeSearch` through Newznab or NZBHydra2 with a dry run, whole files rebuilt from a byte-identical duplicate, server answer 451 treated as missing when downloading and probing, and the yEnc checksum of articles fetched for stream repair checked whenever the article carries one, even with `CrcCheck=no`.
- **October 5: compatibility and pairing.** Queue files written in NZBGet's own format again, with this work's data in a trailer NZBGet ignores; pairing by the part counts that subjects declare; a dead download fails over once 64 articles beyond the first of each file have failed, instead of after up to 1,000.

After the last comment, the branch added `appendfleet`, twins and alts from par2 file lists, repair with a twin's par2 volumes, more than 100 fixes to inherited bugs, and the start of the Rust port.

On 2026-10-09 the NZBGet maintainers closed it without merging, along with the related bug reports. No formal review was submitted, and no reason was given. That work is the starting point of RustyGet.

## A rewrite, not a fork

- **Left the fork network.** This repository is standalone on GitHub. It no longer tracks NZBGet's development or sends changes back as pull requests.
- **Rewriting in Rust.** The C++ moves to Rust one module at a time. Each port matches the C++ output byte for byte, proven by differential tests against the old code under sanitizers, and the C++ stays as a fallback for builds without Rust. Some ports are much faster, such as CRC combination at 135 times the speed. See [Rust port status](https://appz4fun.github.io/nzbget/rust-port.html).
- **API compatibility may change.** Today RustyGet answers NZBGet's API, so Sonarr, Radarr, the Kodi add-on, and NZBGet extensions work unchanged. Future versions may break NZBGet API compatibility where the old behavior is unsafe or in the way, and may add a SABnzbd-compatible API.
- **New name.** The project is RustyGet. During the move, the binary and the configuration file keep NZBGet's names, `nzbget` and `nzbget.conf`, so existing setups keep working.

## Build and run

RustyGet has no release packages yet. Build it from source with CMake, a C++20 compiler, and Rust. The repository pins Rust 1.99.0, and rustup installs it on the first build.

```bash
git clone https://github.com/Appz4Fun/nzbget.git rustyget
cd rustyget
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 8
sudo cmake --install build
[ -e ~/.nzbget ] || install -m 600 /usr/local/share/nzbget/nzbget.conf ~/.nzbget
nzbget -D
```

`~/.nzbget` is the first place RustyGet looks for its configuration, and the web interface saves your settings there. The test keeps an existing copy when you run these steps again to upgrade. Then open `http://<host>:6789`. The default login is `nzbget` with the password `tegbzn6789`. Change it first. See [Install and build](https://appz4fun.github.io/nzbget/install.html) for the libraries each platform needs, and [Quick start](https://appz4fun.github.io/nzbget/quick-start.html) for the first settings.

To move from NZBGet, stop it, back up the queue directory and `nzbget.conf`, and start RustyGet with the same configuration file.

## Documentation

The **[documentation site](https://appz4fun.github.io/nzbget/)** covers:

- [Feature highlights](https://appz4fun.github.io/nzbget/features.html) and [Differences from NZBGet](https://appz4fun.github.io/nzbget/differences.html)
- [Duplicate handling](https://appz4fun.github.io/nzbget/duplicates.html) and [Duplicate fleets](https://appz4fun.github.io/nzbget/duplicate-fleets.html)
- [Check, repair, and unpack](https://appz4fun.github.io/nzbget/post-processing.html), [Servers, RSS, and scheduling](https://appz4fun.github.io/nzbget/automation.html), and [Performance tuning](https://appz4fun.github.io/nzbget/performance.html)
- [Configuration options](https://appz4fun.github.io/nzbget/options.html), generated from `nzbget.conf`
- [API and compatibility](https://appz4fun.github.io/nzbget/api.html) and the [Design system](https://appz4fun.github.io/nzbget/design-system.html)

The site's source is in [`site/`](site). It deploys on every push to the default branch, after Vale checks the prose against the Google developer documentation style.

## Contribute

Issues and pull requests are welcome in this repository. Write new code in Rust, keep ports byte-identical with the code they replace, and add tests that fail without your change. AI-assisted work is welcome if you say which tools you used and understand every line. See [Contributing](https://appz4fun.github.io/nzbget/contributing.html).

## License and credits

RustyGet is free software under the [GNU General Public License](COPYING), version 2 or, at your option, any later version. It's built on NZBGet, created by its original author and continued by the NZBGet team; their copyright notices stay in the source.
