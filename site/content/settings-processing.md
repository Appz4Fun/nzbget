+++
title = "Repair and unpacking"
description = "Configure article integrity checks, par2 repair, and archive extraction with illustrated Settings controls."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## Check and repair

Keep `CrcCheck` enabled for article checksum validation. Choose a `ParCheck` mode for par2 verification and use `ParRepair` to control repair. `ParQuick`, `ParScan`, and the rename controls affect how the daemon finds and verifies files.

`HealthCheck` determines how the daemon handles a download that cannot complete from its current articles. The `dupe` mode can fail over to another copy; see [Duplicate fleets](duplicate-fleets.md) before enabling it.

Review `ParBuffer` and `ParThreads` against available memory and CPU capacity. `ParPauseQueue` and `ParTimeLimit` control how repair work interacts with downloads. A successful check or repair appears in the download's History details.

Key options: [`CrcCheck`](options.md#crccheck), [`ParCheck`](options.md#parcheck), [`ParRepair`](options.md#parrepair), [`ParQuick`](options.md#parquick), [`HealthCheck`](options.md#healthcheck), [`ParBuffer`](options.md#parbuffer), [`ParThreads`](options.md#parthreads).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/check-repair.jpg" aria-label="Open full-size picture: Checksum, par2, rename, and health-check settings"><img src="assets/settings/check-repair.jpg" width="1280" height="975" loading="lazy" alt="Checksum, par2, rename, and health-check settings"></a>
<figcaption>Verification, repair, and duplicate failover are separate controls. Open the picture to inspect the full section.</figcaption>
</figure>

## Unpack

Turn `Unpack` on when you want archive extraction. Check that `UnrarCmd` and `SevenZipCmd` select tools available to the daemon. `DirectUnpack` can extract supported archives while articles arrive; `UseTempUnpackDir` controls temporary extraction folders.

`UnpackCleanupDisk` removes archive files after successful extraction. Choose it according to what you want the completed folder to retain. `UnpackIgnoreExt` lists nonstandard RAR extensions, such as `.cbr`, that should keep their names during RAR renaming. It also suppresses the failure for finding only nonstandard RAR archives with those extensions. Recognized `.rar` and `.7z` archives still follow normal extraction. `UnpackPassFile` supplies a password-list file when needed.

A category can override the global unpack setting. For nested archives, see the optional extension examples in [Extensions](settings-extensions.md).

Key options: [`Unpack`](options.md#unpack), [`DirectUnpack`](options.md#directunpack), [`UseTempUnpackDir`](options.md#usetempunpackdir), [`UnrarCmd`](options.md#unrarcmd), [`SevenZipCmd`](options.md#sevenzipcmd), [`UnpackCleanupDisk`](options.md#unpackcleanupdisk), [`UnpackIgnoreExt`](options.md#unpackignoreext).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/unpack.jpg" aria-label="Open full-size picture: Archive extraction and cleanup settings"><img src="assets/settings/unpack.jpg" width="1280" height="938" loading="lazy" alt="Archive extraction and cleanup settings"></a>
<figcaption>These controls choose tools, extraction behavior, and retained files. Open the picture to inspect the full section.</figcaption>
</figure>
