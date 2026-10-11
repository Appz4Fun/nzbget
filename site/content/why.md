+++
title = "Why RustyGet"
description = "Where RustyGet comes from: NZBGet, pull request 850, leaving the fork network, the rewrite in Rust, and what that means for compatibility."
eyebrow = "Overview"
lede = "RustyGet began as a pull request to NZBGet. When that pull request closed without being merged, the work became its own project: a rewrite of NZBGet in Rust, built around duplicate fleets."
+++

## Where it comes from

[NZBGet](https://github.com/nzbgetcom/nzbget) is a Usenet downloader written in C++, known for running fast on small devices. Its original author maintained it for many years, and the NZBGet team carries it on today. RustyGet starts from NZBGet 27.0 and owes it the download engine, the par2 repair, the web interface, and the API.

## Pull request 850

In July 2026, [NZBGet pull request 850](https://github.com/nzbgetcom/nzbget/pull/850) proposed `DupeArticleFallback`: fetching an article that no news server has from a duplicate posting of the same release. NZBGet already kept duplicates as whole backups and could share par2 blocks between them, but nothing in between. A release with a few missing articles failed, even when another posting of it had every one.

Over three months the pull request grew to cover the whole duplicate fleet:

- **July:** article fallback with cutover and lead rotation, then byte-level stream repair across packaging and encryption, live repair during the download, and a functional test harness with dozens of scenarios.
- **September:** par2 first, so a download's own recovery data is always tried before any donor, and a fix for repairs that stalled on unavailable duplicates.
- **October:** `HealthCheck=dupe` with early failover and a dead-copy probe, `DupeStreamTimeout`, donor search through NZBHydra2, whole-file rebuilds from proven twins, `appendfleet`, a queue format that NZBGet can still read, and more than 100 fixes to bugs found along the way, most of them reported upstream.

By October it held 385 commits and about 45,000 added lines, much of it tests, and it had run in daily use since July.

On 2026-10-09 the NZBGet maintainers closed the pull request without merging it, together with the related bug reports. No code review took place, and no reason was given. Earlier, a maintainer had asked to wait for a stable build before testing, and on another pull request a maintainer had said that changes made with AI are hard to review. A change this size is a lot to ask of a volunteer team, and the work went on without them.

## Leaving the fork network

The repository has left GitHub's fork network. It's a standalone project, not a fork of NZBGet:

- It no longer tracks NZBGet's development or sends changes back as pull requests.
- It's a rewrite, not a patch set: the code moves to Rust, and the design follows duplicate fleets rather than NZBGet's roadmap.
- It has its own name, documentation, issue tracker, and release plan.

NZBGet's code is licensed under the GNU GPL, and so is RustyGet. Copyright notices stay in place, and credit for the original work stays with its authors.

## Why Rust

The rewrite moves the program to Rust one module at a time, for four reasons:

- **Memory safety.** Duplicate fleets juggle many postings, threads, and partial files at once. Use-after-free crashes and overlapping buffer copies turned up in this work, including one in the original article decoder that the Rust port avoids. Rust rules out that class of bug.
- **Speed where it counts.** Ports so far include CRC combination at 135 times the speed of the C++ code, and deobfuscation at 16 times.
- **Proof that nothing changed.** Every port is checked against the old C++ code with differential tests, so behavior stays the same while the code underneath changes.
- **A healthier codebase.** Cargo, a strong type system, and modern libraries make the code easier to test and to change.

See [Rust port status](rust-port.md) for progress.

## What this means for you

- **Today,** RustyGet reads NZBGet's configuration, queue, and history, answers NZBGet's API, and runs NZBGet extensions. Media managers and the Kodi add-on connect to it as NZBGet.
- **Over time,** the API may change where NZBGet's behavior is unsafe or in the way. RustyGet may also add a SABnzbd-compatible API, so clients that only speak SABnzbd can use it. [API and compatibility](api.md) tracks both.
- **Packages** return once the build workflows are rebuilt for the rewrite. Until then, [build from source](install.md).

## The name

RustyGet keeps the "Get" of its roots and adds the language it's moving to. During the move, the binary and the configuration file keep NZBGet's names, `nzbget` and `nzbget.conf`, so existing setups and clients keep working.
