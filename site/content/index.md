+++
title = "RustyGet"
nav_title = "Overview"
template = "home"
toc = false
description = "RustyGet is a Usenet downloader rewritten from NZBGet in Rust. It treats every copy of a release as one fleet, so missing articles come from other copies instead of failing the download."
eyebrow = "Usenet downloader · rewrite in progress"
headline = "Every copy of a release,"
headline_accent = "working as one download."
lede = "RustyGet is a rewrite of NZBGet in Rust. It keeps NZBGet's speed and API, and adds duplicate fleets: when an article is missing on every server, it comes from another copy of the release, verified by par2, instead of failing the download."
facts = ["NZBGet API today", "Rust, one module at a time", "Every borrowed byte verified", "GPL v2 or later"]
+++

## Start here

<div class="cards">
<a class="card" href="install.html"><p class="eyebrow">Get started</p><h3>Install and build</h3><p>Build from source with CMake and the pinned Rust toolchain, then run it as a service.</p></a>
<a class="card" href="quick-start.html"><p class="eyebrow">Get started</p><h3>Quick start</h3><p>Five settings to start downloading, and five more to turn on duplicate fleets.</p></a>
<a class="card" href="duplicate-fleets.html"><p class="eyebrow">Features</p><h3>Duplicate fleets</h3><p>Article fallback, twins and alts, par2 from a twin, stream repair, and early failover.</p></a>
<a class="card" href="kodi.html"><p class="eyebrow">Features</p><h3>Streaming with Kodi</h3><p>How the NeNeTeePee Stream add-on finds every copy through NZBHydra2 and hands the fleet to RustyGet.</p></a>
<a class="card" href="differences.html"><p class="eyebrow">Overview</p><h3>Differences from NZBGet</h3><p>Every change, area by area, from new options to more than 100 bug fixes.</p></a>
<a class="card" href="why.html"><p class="eyebrow">Overview</p><h3>Why RustyGet</h3><p>From pull request 850 to a standalone rewrite, and what it means for compatibility.</p></a>
</div>

## What it does

RustyGet downloads files from Usenet using NZB files, the way NZBGet does: it fetches articles from your news servers, decodes them, checks and repairs the result with par2, unpacks archives, and runs your extensions. It runs on anything from a small NAS to a large server, and media managers such as Sonarr and Radarr talk to it as NZBGet.

What's new is how it treats duplicates. The same release usually exists as several postings: reposts, listings on other indexers, and other encodes. NZBGet keeps them as spares and starts the next one from scratch when a download fails. RustyGet uses them together:

- An article missing on every server is fetched from a matching file in another copy, then checked against the download's own par2 data.
- Copies with byte-identical files, called **twins**, are proven by par2 checksums and can lend articles and recovery volumes. Other encodes, called **alts**, serve only as backups.
- Holes that articles can't fill are patched with verified bytes, even from copies that are split, packed, or encrypted differently.
- A copy that can't complete hands over to the best backup within seconds.
- RustyGet can search NZBHydra2 for more copies and check each one on your servers before it counts on it.

See [Feature highlights](features.md) for the full list.

## Status

RustyGet is in active development and runs in daily use. The C++ code inherited from NZBGet moves to Rust one module at a time, each port proven against the old code. There are no release packages yet, and the API may change as the rewrite goes on. Follow progress in the [Rust port status](rust-port.md) and the [repository](https://github.com/Appz4Fun/nzbget).
