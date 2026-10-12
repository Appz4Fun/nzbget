+++
title = "Extensions"
description = "Manage extension hooks and installation, with illustrated examples of four optional extension Settings pages."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## Extension scripts

Choose the global `Extensions` list and review `ScriptOrder`. Extensions can run at different hooks; the available hooks depend on the installed extension. A category can choose its own post-processing extension list.

`ScriptPauseQueue` controls queue behavior during script work. `ShellOverride` selects interpreters for scripts that need them. Read the extension's requirements before changing those controls.

Key options: [`Extensions`](options.md#extensions), [`ScriptOrder`](options.md#scriptorder), [`ScriptPauseQueue`](options.md#scriptpausequeue), [`ShellOverride`](options.md#shelloverride), [`EventInterval`](options.md#eventinterval).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/extension-scripts.jpg" aria-label="Open full-size picture: Global extension list, script ordering, and execution controls"><img src="assets/settings/extension-scripts.jpg" width="1280" height="938" loading="lazy" alt="Global extension list, script ordering, and execution controls"></a>
<figcaption>Global hook selection and per-extension settings have different roles. Open the picture to inspect the full section.</figcaption>
</figure>

## Extension manager

Use the built-in manager to inspect installed extensions and the available catalog. Read an extension's description, requirements, and project link before installing it. Review its settings after installation, and check Messages when an extension fails.

Installing an extension does not mean every workflow uses it. Check the global or category extension selection for the hook you intend to use. See [Post-processing](post-processing.md) for the processing pipeline.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/extension-manager.jpg" aria-label="Open full-size picture: Extension manager displaying example installed extensions"><img src="assets/settings/extension-manager.jpg" width="1280" height="900" loading="lazy" alt="Extension manager displaying example installed extensions"></a>
<figcaption>The demonstration includes four optional extensions; they are not bundled defaults. Open the picture to inspect the full section.</figcaption>
</figure>

## DupeDonors

This optional extension adds health-checked duplicate postings as backup NZBs. Its controls include an indexer URL and API key, donor limits, health sampling, concurrency, and `DryRun`.

Read the installed version's help, configure its indexer credentials locally, and use its dry-run mode while checking the intended behavior. Keep its workflow distinct from the built-in duplicate-search controls described in [Indexer search](dupesearch.md). Numeric values in the picture are sanitized examples, not tuning recommendations.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/dupe-donors.jpg" aria-label="Open full-size picture: DupeDonors example options with blank indexer credentials"><img src="assets/settings/dupe-donors.jpg" width="1280" height="1067" loading="lazy" alt="DupeDonors example options with blank indexer credentials"></a>
<figcaption>Extension options and requirements can change between versions. Open the picture to inspect the full section.</figcaption>
</figure>

## Extended Unpacker

This optional extension handles nested ZIP and RAR archives. Configure its extraction tools and arguments, then review its wait and leftover-file controls. Confirm the result on a representative download before choosing cleanup behavior.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/extended-unpacker.jpg" aria-label="Open full-size picture: Extended Unpacker example extraction-tool and cleanup controls"><img src="assets/settings/extended-unpacker.jpg" width="1280" height="938" loading="lazy" alt="Extended Unpacker example extraction-tool and cleanup controls"></a>
<figcaption>The installed extension's help explains each argument and cleanup option. Open the picture to inspect the full section.</figcaption>
</figure>

## Extended Unrar

This optional extension handles nested RAR files. It has separate tool, wait, and leftover-file controls. Choose the extension that matches your archive workflow and review its relationship with global unpacking.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/extended-unrar.jpg" aria-label="Open full-size picture: Extended Unrar example tool and cleanup settings"><img src="assets/settings/extended-unrar.jpg" width="1280" height="938" loading="lazy" alt="Extended Unrar example tool and cleanup settings"></a>
<figcaption>This extension supplements the daemon's unpacking workflow. Open the picture to inspect the full section.</figcaption>
</figure>

## Permission Fix

This optional extension normalizes completed-download permissions to `UMask`. The pictured version has no editable options. Its page provides information about the installed extension.

On POSIX services, review `DaemonUsername`, `UMask`, and folder ownership for the account that runs the daemon. An extension does not replace the deployment's permission setup.

Key options: [`DaemonUsername`](options.md#daemonusername), [`UMask`](options.md#umask).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/permission-fix.jpg" aria-label="Open full-size picture: Permission Fix information page with no editable options"><img src="assets/settings/permission-fix.jpg" width="1280" height="938" loading="lazy" alt="Permission Fix information page with no editable options"></a>
<figcaption>An extension can have an information page without configurable fields. Open the picture to inspect the full section.</figcaption>
</figure>
