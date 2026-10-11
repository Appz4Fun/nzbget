+++
title = "Check, repair, and unpack"
nav_title = "Check, repair, unpack"
description = "How RustyGet verifies downloads with par2, repairs them on every core, restores obfuscated names, unpacks archives, and runs extension scripts."
eyebrow = "Features"
lede = "After the last article arrives, RustyGet checks the files, repairs damage with par2 recovery data, restores obfuscated names, unpacks archives, and cleans up. Everything except unpacking runs inside the program, with no external par2 tool."
+++

## The pipeline

<ol class="steps">
<li><strong>Health check during download.</strong> If so many articles are missing that repair can't succeed, <code>HealthCheck</code> acts before you waste more bandwidth.</li>
<li><strong>Rename.</strong> Par-rename and RAR-rename restore the real filenames of obfuscated postings.</li>
<li><strong>Verify.</strong> Quick verification checks only the files that had download errors.</li>
<li><strong>Repair.</strong> Multithreaded par2 repair rebuilds damaged files.</li>
<li><strong>Unpack.</strong> RAR and 7-Zip archives are extracted. Passwords come from the NZB file or from a password file.</li>
<li><strong>Clean up and run extensions.</strong> Archives and par2 files are deleted, and post-processing extensions run in the order you set.</li>
</ol>

`PostStrategy` controls how many downloads can be in these steps at once: `sequential`, `balanced` (the default), `aggressive`, or `rocket`.

## Health check

Health is the share of a download's articles that the news servers actually delivered. Critical health is the lowest health that the download's par2 recovery data can still repair; RustyGet computes it from the number and size of the par2 files.

When health drops below critical health, `HealthCheck` decides what happens:

| Value | Effect |
|---|---|
| `park` | Default. Moves the download to history with its files kept, so you can add more par2 files or retry later. |
| `delete` | Deletes the download and moves it to history. With duplicate checks on, the best backup of the title starts. |
| `pause` | Pauses the download. You start a backup yourself. |
| `none` | Keeps downloading. Use it when you plan to repair by hand. |
| `dupe` <span class="tag tag-new">new</span> | Waits for a duplicate first. If a better copy of the same title waits in history, the download fails over to it; if article fallback can borrow the missing articles, the download keeps going. See [Duplicate fleets](duplicate-fleets.md). |

## Renaming obfuscated files

Many postings hide their real names, for example a 32-character hexadecimal base name with extensions such as `.01`, `.21`, and `.par2`. Archives with names like these can't be unpacked until the real names come back.

Par-rename
: The par2 set stores the original filenames. RustyGet reads them and renames the files in seconds, with no verification pass. The classic approach, running par2cmdline over every file, can take tens of minutes on a large download. Set by `ParRename`.

RAR-rename
: Restores the names of multi-volume RAR archives from the archive headers. It works when a posting has no par2 files, and when the files were obfuscated before the par2 files were made. Set by `RarRename`. RustyGet parses RAR headers and renames volume sets in Rust.

Direct rename
: Renames files while they download, as soon as the first article of each par2 file arrives. Set by `DirectRename`.

## Quick verification

Par2 verification reads and checksums every file, which takes minutes to tens of minutes. On a slow device with a large, lightly damaged download, verification can take longer than the repair itself.

RustyGet doesn't need that pass. It records which files had download errors and hands exactly those to the repair module, so repair starts right away. `ParQuick` controls this, and `ParScan` sets which files take part:

| `ParScan` | Files scanned |
|---|---|
| `limited` | Only files that belong to the par2 set. |
| `extended` | Default. Files of the set first, then other files, until enough recovery blocks are found. |
| `full` | Every file in the download directory. |
| `dupe` | Like `extended`, and also borrows par2 blocks from duplicate downloads of the same title in history. |

## Multicore repair

par2cmdline predates multicore CPUs and uses one core. A popular multicore fork depends on an Intel library and runs only on Intel-compatible CPUs, which leaves out the ARM chips in most NAS boxes and media players.

The repair module has its own threading that works on every platform and CPU. On a four-core ARM device it repairs two to three times faster than par2cmdline. Set the thread count with `ParThreads` and the memory with `ParBuffer`.

> [!NOTE] Repair from a twin
> When a download is short of recovery blocks, RustyGet can use the par2 volumes of a twin: a duplicate posting whose files are byte-identical, proven by par2 checksums. See [Duplicate fleets](duplicate-fleets.md#repair-with-a-twins-par2-files).

## Unpack

`Unpack` extracts RAR archives with `UnrarCmd` and 7-Zip archives with `SevenZipCmd`. `DirectUnpack` starts extracting while the download is still running, which saves time when the download needs no repair.

- `UseTempUnpackDir` extracts into a temporary `_unpack` directory and moves the files when done.
- `UnpackPassFile` points to a file of passwords to try.
- `UnpackCleanupDisk` deletes archives after a successful unpack, and `ExtCleanupDisk` deletes other leftovers, such as `.par2` and `.sfv` files.
- `UnpackIgnoreExt` leaves some archives alone, for example `.cbr` comic books.

## Retry failed articles

A failed download goes to history, where you can download it again. Besides starting over, you can retry only the articles that failed. That keeps everything already downloaded and fetches just the gaps. It helps when:

- A posting hadn't finished propagating to your servers.
- An optional news server was unreachable during the first attempt.
- You added or turned on another news server.

## Post-processing extensions

Extensions are scripts that run at set points, such as after a download finishes. Par check, repair, and unpack are built in; extensions handle everything else, such as deleting samples, sending notifications, or moving files for media managers.

- Install extensions from the Extension Manager in the web interface, or put them in `ScriptDir`.
- Each extension has a `manifest.json` and an executable. Its options are saved in `nzbget.conf` and passed as `NZBPO_` environment variables.
- Post-processing extensions read the download's state from `NZBPP_` variables such as `NZBPP_DIRECTORY`, `NZBPP_TOTALSTATUS`, and `NZBPP_STATUS`.
- Exit with `93` for success, `94` for failure, or `95` to skip. Any other exit code, including `0`, marks the script as failed. Exit `92` to ask for a par check after an extension unpacked the files itself.
- Print `[NZB] DIRECTORY=<path>` to tell later scripts that the files moved, or `[NZB] FINALDIR=<path>` when you move them into a directory that holds other files.

The extension interface is inherited from NZBGet, and NZBGet extensions work unchanged today. The [compatibility](api.md#compatibility) policy explains what may change.
