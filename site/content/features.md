+++
title = "Feature highlights"
description = "What makes RustyGet fast and reliable: efficient native code, fast deobfuscation, quick par verification, multicore repair, article retries, a complete API, RSS duplicate checks, and duplicate fleets."
eyebrow = "Features"
lede = "RustyGet keeps everything that made NZBGet fast and adds a new layer: it treats every copy of a release as one fleet, so a missing article on one posting no longer means a failed download."
+++

## Efficient by design

People new to Usenet often assume that download speed depends only on the connection, and that the program just writes data to disk. That holds for web and FTP downloads, but not for Usenet. Usenet was built to carry text messages, so sending files over it takes three extra steps:

- **Splitting.** Messages have a size limit, usually under 1 MB, so the poster cuts each file into thousands of small pieces called articles.
- **Encoding.** Messages can only carry plain text safely, so the poster encodes the binary data as text, most often with yEnc.
- **Recovery data.** Usenet doesn't guarantee delivery, so posters add par2 recovery files that can rebuild lost pieces.

A downloader reverses all three for every article: it decodes the text, checks each piece, joins the pieces into files, and repairs what's missing. That's real computation, and on a small device it decides how fast you can download.

RustyGet inherits NZBGet's answer: native code compiled for your CPU, efficient algorithms, no wasted work, and no loading whole files into memory. NZBGet runs on devices with 32 MB of RAM and a 200 MHz CPU, and RustyGet keeps that budget as a design goal. The rewrite moves the code to Rust one module at a time and measures each step. Some ports are much faster than the C++ they replace: combining article checksums runs about 135 times faster, and deobfuscation about 16 times faster.

The same design pays off on large machines. Extra memory becomes an article cache that cuts disk writes, and extra cores run more connections and faster par repair. See [Performance tuning](performance.md).

## Fast deobfuscation

Many postings hide their real filenames. A typical obfuscated posting has a 32-character hexadecimal base name and extensions such as `.01`, `.21`, and `.par2`. Archives can't be unpacked until their real names come back.

The par2 files of a posting record the original names. The usual fix is to run par2cmdline, as in `par2cmdline r <name>.par2`, which reads every downloaded file before it restores the names. How long that takes depends on the size and the disk: from several minutes to tens of minutes.

RustyGet's par-rename restores the names in seconds, even on slow devices, because it reads only the names that the par2 files store and needs no verification pass. NZBGet's own example: a 4 GB download with 75 renamed files, restored in two seconds on a slow Linux device. The download's log shows each step:

```text
INFO  Checking renamed files for Example.Release
INFO  Renaming 3f9c0e5a7d214b8c96e1f0a2b4c6d8e1.50 to Example.Release.r65
INFO  Renaming 3f9c0e5a7d214b8c96e1f0a2b4c6d8e1.47 to Example.Release.r25
INFO  Successfully renamed 75 file(s) for Example.Release
```

### RAR-rename

RAR-rename, added in NZBGet 18.0, restores the names of multi-volume RAR archives from the archive headers. It works when a posting has no par2 files at all, and when the files were obfuscated before the par2 files were created. In RustyGet the RAR header parser and the renaming of volume sets run in Rust.

## Quick par verification

Missing articles leave damaged files. Most postings include par2 recovery files that can repair them, in two steps:

1. **Verification** reads every file and checksums it to find the damaged ones.
2. **Repair** rebuilds the damaged parts from recovery blocks.

Both are slow. Verification takes minutes to tens of minutes; repair takes minutes to hours. Both depend on the damage and the CPU. For a large download with a little damage, verification can take longer than the repair. On a slow device, an hour of verification for five minutes of repair isn't unusual.

RustyGet doesn't call an external par2 tool. The par2 code is part of the program, and RustyGet knows exactly which files had download errors. It passes that list straight to the repair module, so it skips verifying the undamaged files and starts the repair at once.

## Multicore par repair

par2cmdline is older than multicore CPUs and uses one core. A multicore fork exists, but it depends on an Intel library and runs only on Intel-compatible CPUs. Most NAS boxes and media players have multicore ARM CPUs, so they can't use it and are stuck on one core.

RustyGet's par2 module has its own threading that works on every platform and CPU. On a four-core ARM device, it repairs two to three times faster than par2cmdline. MIPS, PowerPC, and x86 devices gain too.

## Retry failed articles

A failed download goes to history, where you can try again. Besides starting over, you can retry only the articles that failed. RustyGet keeps everything it already has and fetches just the gaps. This helps when:

- The first attempt hit a propagation delay, and the articles arrived on your servers later.
- An optional news server was unreachable during the first attempt.
- You turned on another news server.

## A complete API

Everything RustyGet does is available through its API, and RustyGet relies on that itself: the web interface uses nothing else. Any feature you see in the interface is open to scripts, media managers, and add-ons.

Many programs have one web server that renders pages and a separate API, and the two drift apart. RustyGet has no such split. The web interface is a static page with JavaScript; the built-in web server only serves its files. Once loaded, the page talks to RustyGet through the same JSON-RPC calls that any other program can use.

RustyGet adds methods of its own, such as `appendfleet`, which hands over a whole fleet of copies in one call. See [API and compatibility](api.md) for what changes as the rewrite goes on.

## RSS with duplicate checks

You don't need other automation software to follow shows: RustyGet reads RSS feeds itself, with filters that accept, reject, or require terms and set options per match.

```text
Reject: age:>10
Require: 720p
# shows to follow
Accept: game of thrones S03E##
Accept: dexter S08E##
```

Other programs often download the same title several times, because several posters upload it. RustyGet's duplicate handling downloads each title once, and if that download fails, it automatically falls back to another release of the same title. See [Duplicate handling](duplicates.md) and [Servers, RSS, and scheduling](automation.md#rss-feeds-and-filters).

## Duplicate fleets

This is where RustyGet goes beyond NZBGet. NZBGet uses duplicates one at a time: when a download fails, the next copy starts from scratch. RustyGet uses them together:

- **Article fallback.** RustyGet fetches an article that no server has from another posting of the same release.
- **Twins and alts.** A *twin* is a copy whose files are byte-identical, proven by par2 checksums; RustyGet can borrow its articles and par2 volumes. An *alt* is the same release in another encode; it's mainly a failover backup.
- **Stream repair.** RustyGet patches holes that article fallback can't fill with bytes from duplicates, even from a duplicate that's packed differently.
- **Early failover.** With `HealthCheck=dupe`, a download that can't complete switches to the best backup within seconds, and a probe catches copies that are dead before they start.
- **Donor search.** RustyGet can search NZBHydra2 for more copies of a new download, check them on your servers, and queue the live ones as backups.
- **Fleet submission.** Clients such as the Kodi add-on send every copy at once with `appendfleet`, and RustyGet picks the best one.

See [Duplicate fleets](duplicate-fleets.md) for how each one works.
