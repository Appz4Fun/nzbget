+++
title = "Performance tuning"
description = "Tune RustyGet for small devices and fast links: connections, encryption, caching, direct write, par repair, and disk settings."
eyebrow = "Features"
lede = "RustyGet runs well on small NAS boxes, routers, and media players, and it scales up on fast machines. Three resources limit it: CPU, memory, and disk throughput. This page lists the settings that matter for each."
+++

> [!TIP] Change one setting at a time
> Measure a download before and after each change. A setting that helps a fast desktop can slow down a NAS, and the reverse.

## When the CPU is the limit

Encryption
: TLS costs more CPU than anything else in a download. If your device is slow, try another cipher with `ServerN.Cipher`; a fast cipher can raise throughput a lot. Keep encryption on unless you trust the network path.

Connections
: Each connection is a thread. For servers at level 0 (`ServerN.Level=0`), use the fewest connections that still fill your link. More connections make a small device less responsive. Give fill servers (level 1 and higher) the same count as your main servers when you can.

Article checksums
: `CrcCheck` verifies every article. With a reliable server you can turn it off to save CPU, but quick par verification then becomes less reliable and sometimes falls back to a full scan. RustyGet combines the per-article checksums into file checksums in Rust, about 135 times faster than NZBGet's C++ code, so the check costs less than it used to.

Par check and repair
: Keep `ParCheck=auto` so only damaged downloads get repaired, and keep `ParQuick=yes` for fast verification. Set `ParThreads` to your core count (`0` picks it for you) and raise `ParBuffer` if you have memory to spare. `ParTimeLimit` stops repairs that would run for hours; you can copy a badly damaged download to a faster computer and repair it there.

Pausing the queue
: `ParPauseQueue` and `UnpackPauseQueue` stop downloading while a repair or an unpack runs, so the two don't compete for the CPU and disk.

Speed limits
: Enforcing `DownloadRate` costs extra work. Leave it at `0` for the best speed.

Console mode
: The terminal interface (`-s`) redraws constantly. Run as a daemon (`-D`) on POSIX systems or as a service on Windows, and attach a remote console only when you need one.

## When memory is the limit

Article cache
: `ArticleCache` holds decoded articles in memory, which reduces disk writes and file fragmentation and speeds up unpacking, especially with ten or more connections. With `DirectWrite=yes`, about 200 MB is enough. Without direct write, the cache should fit a whole RAR volume, up to 1 GB.

Write buffer
: `WriteBuffer` sets a per-connection buffer in kilobytes. Use `1024` when memory is plentiful, or `32` and up on small devices, scaled to your connection count. It matters most when the article cache is off.

## When the disk is the limit

A fast drive behind a slow interface, such as a USB 2 port or a low-end NAS controller, is still a slow disk.

Direct write
: Without `DirectWrite`, articles wait in the cache or in temporary files until a file is complete, and then get written again. With it, each article goes straight to its place in the final file. Direct write needs a file system with sparse files, which NTFS, ext3, and ext4 have and HFS+ doesn't. On HFS+, use a large article cache instead.

Fragmentation
: With direct write, many threads write to one file at once. `WriteBuffer` reduces the resulting fragmentation, and `ArticleCache` nearly removes it.

Flushing the queue
: `FlushQueue` forces the queue and history to disk on every save, which protects them in a crash but can slow the whole system. Try turning it off; if that doesn't help, turn it back on.

Download progress
: `ContinuePartial` saves progress after each article so a restart resumes mid-file. Turning it off saves a little disk activity.

Logging
: Set `DetailTarget` and `DebugTarget` to `none`. Once your setup is stable, consider `WriteLog=none`, which stops writing the log file. NZBGet's older `CreateLog` option is obsolete and ignored.

Intermediate directory
: Put `InterDir` on another physical drive or an SSD to speed up unpacking. Even on one drive, keep it set, so active downloads and finished files stay apart.

## Duplicate fleets and performance

The fleet features add work, so size them for your hardware:

- Health checks of duplicates (`DupeHealthPercent`, `DupeHealthMin`, `DupeHealthMax`, `DupeBodyChecks`) use your news-server connections. Each check is bounded by `DupeHealthBudget`.
- Stream repair (`DupeArticleFallback=stream`) downloads and decodes parts of other postings. `DupeStreamTimeout` stops a repair that goes 60 seconds without progress, and also stops one that would take more than three times as long as downloading the release again.
- `DupeStreamDecompress` unpacks parts of compressed duplicates and needs CPU and an extractor.

See [Duplicate fleets](duplicate-fleets.md) for what each feature does.
