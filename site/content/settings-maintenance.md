+++
title = "Maintenance"
description = "Read service status, back up or restore settings, reload configuration, and find license information."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## Info

Start here for the difference between browser preferences and server configuration. The page links to the first-time setup, extension manager, backups, and community resources.

Use [Basic setup](settings-basics.md) when configuring a new installation. Use [Settings at a glance](settings.md) for search, help, and the compact list editors.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/info.jpg" aria-label="Open full-size picture: Settings information and community resources"><img src="assets/settings/info.jpg" width="1280" height="900" loading="lazy" alt="Settings information and community resources"></a>
<figcaption>The Info page explains where settings are stored. Open the picture to inspect the full section.</figcaption>
</figure>

## Status

Review system health notices and service information before changing performance settings. Health notices can link you to affected options. Check the Messages tab for the surrounding error or warning, and inspect History for download-specific outcomes.

The built-in disk and server tests perform work. Run them when you can spare the relevant disk or network capacity. A result describes that installation and test, not a provider's advertised speed.

Key options: [`SystemHealthCheck`](options.md#systemhealthcheck), [`WriteBuffer`](options.md#writebuffer), [`ArticleCache`](options.md#articlecache).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/status.jpg" aria-label="Open full-size picture: Status page with demonstration health and system information"><img src="assets/settings/status.jpg" width="1280" height="1300" loading="lazy" alt="Status page with demonstration health and system information"></a>
<figcaption>These example status values are not a production health report. Open the picture to inspect the full section.</figcaption>
</figure>

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/status-wide.jpg" aria-label="Open full-size picture: Wide dark Status panels beside the Settings menu"><img src="assets/settings/status-wide.jpg" width="1920" height="1080" loading="lazy" alt="Wide dark Status panels beside the Settings menu"></a>
<figcaption>Status panels expand with the desktop window. Open the picture to inspect the full section.</figcaption>
</figure>

## System

Back up configuration before a substantial change:

1. Open **System** and choose the configuration backup control.
2. Keep the downloaded backup private; it can contain provider credentials.
3. Use the restore control when you intend to replace settings from a backup.
4. Save and reload when prompted, then review Status and Messages.

A configuration backup is not a backup of downloaded files, the queue, or history. Preserve those separately for a deployment recovery plan. Reload applies saved server configuration. Shutdown stops the daemon; an external service manager can start it again according to your deployment.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/system.jpg" aria-label="Open full-size picture: System controls for configuration backup, restore, reload, and shutdown"><img src="assets/settings/system.jpg" width="1280" height="900" loading="lazy" alt="System controls for configuration backup, restore, reload, and shutdown"></a>
<figcaption>Review saved changes before reloading the service. Open the picture to inspect the full section.</figcaption>
</figure>

## Licenses

This page lists the app's license and third-party credits. Follow the linked license texts when reviewing redistribution requirements. The repository includes the app's license in `COPYING`.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/licenses.jpg" aria-label="Open full-size picture: App license information and third-party credits"><img src="assets/settings/licenses.jpg" width="1280" height="900" loading="lazy" alt="App license information and third-party credits"></a>
<figcaption>License information is separate from configuration. Open the picture to inspect the full section.</figcaption>
</figure>
