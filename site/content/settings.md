+++
title = "Settings at a glance"
description = "An illustrated guide to every Settings section, compact list editors, search, help, and saving configuration."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## Find the section you need

| Settings section | Guide | What to configure |
|---|---|---|
| Web-interface, Paths, News-servers, Security, Categories | [Basic setup](settings-basics.md) | Browser preferences, folders, providers, accounts, and download categories |
| Incoming NZBs, Download queue, Connection, Logging | [Downloads and diagnostics](settings-downloads.md) | Intake, duplicate recovery, queue storage, retries, and logs |
| RSS Feeds, Scheduler | [Feeds and schedules](settings-automation.md) | Feed rules and timed tasks |
| Check and repair, Unpack | [Repair and unpacking](settings-processing.md) | Article checks, par2, and archive extraction |
| Extension scripts, Extension manager, optional extension pages | [Extensions](settings-extensions.md) | Script hooks, ordering, installation, and extension settings |
| Info, Status, System, Licenses | [Maintenance](settings-maintenance.md) | Help, service health, backups, reloads, and attribution |

The [configuration reference](options.md) describes every core option, its default, and its accepted values. Numbered entries appear there as `ServerN`, `CategoryN`, `FeedN`, and `TaskN`.

## Edit one entry at a time

News servers, categories, feeds, and scheduler tasks start as compact lists. Click **Edit** beside an entry to show its fields and action buttons. Click **Close** to return to its summary. Closing an editor keeps unsaved changes; it does not save them.

**Add** opens a new entry. **Up**, **Down**, and **Delete** appear inside its editor. Reordering changes entry numbers. Review scheduler commands that refer to server or feed numbers after you reorder those lists.

Health-notice counts remain visible on closed rows. Open the affected entry to read the notices.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/categories.jpg" aria-label="Open full-size picture: Compact category list with an Edit button for each entry"><img src="assets/settings/categories.jpg" width="1280" height="938" loading="lazy" alt="Compact category list with an Edit button for each entry"></a>
<figcaption>Category summaries keep the individual fields out of the list until you open an editor. Open the picture to inspect the full section.</figcaption>
</figure>

## Search and open help

Use **Search in settings** to find an option name or description. Select an option in the results to open its section and editor. Clear the search to return to the section menu.

Option help starts collapsed. The question-mark button beside a row opens that option's help. The **View** menu can show help for all rows. With a keyboard, use Tab to reach a button and Enter or Space to activate it.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/option-help.jpg" aria-label="Open full-size picture: option help"><img src="assets/settings/option-help.jpg" width="1280" height="1100" loading="lazy" alt="Expanded help for one browser preference"></a>
<figcaption>Help opens beside the option you are editing. Open the picture to inspect the full section.</figcaption>
</figure>

## Save and reload

1. Finish your edits across the sections you need.
2. Click **Save all changes** once.
3. Read the confirmation. Reload the service if it prompts you to apply server configuration.
4. Check **Status** and the **Messages** tab after the reload.

Web-interface preferences belong to this browser. Server and extension settings belong to the daemon's configuration. See [Maintenance](settings-maintenance.md#system) before backing up or restoring that file.

## Use the available desktop width

On desktop, the section menu stays at the left edge while the open section fills the remaining width. Wider windows give lists, editors, and Status panels more room. Statistics also uses the available width.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/desktop-wide.jpg" aria-label="Open full-size picture: Wide desktop Settings with a left section menu and compact categories"><img src="assets/settings/desktop-wide.jpg" width="1920" height="1080" loading="lazy" alt="Wide desktop Settings with a left section menu and compact categories"></a>
<figcaption>The dark desktop view uses the space beside the section menu. Open the picture to inspect the full section.</figcaption>
</figure>

## Use Settings on a phone

The section menu scrolls within a short area, leaving room for the open section. Scroll that menu to reach another section, or use search to jump to an option. Use the keyboard or tap the controls to open editors and help.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/categories-phone.jpg" aria-label="Open full-size picture: Phone Settings view with a short section menu and compact categories"><img src="assets/settings/categories-phone.jpg" width="390" height="945" loading="lazy" alt="Phone Settings view with a short section menu and compact categories"></a>
<figcaption>The shorter phone menu brings the category list into the first screen. Open the picture to inspect the full section.</figcaption>
</figure>

## Choose a theme

The header settings menu offers light and dark themes. Theme and language choices belong to the browser. The pictures in the section guides use the light theme.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/categories-dark.jpg" aria-label="Open full-size picture: dark theme"><img src="assets/settings/categories-dark.jpg" width="1280" height="1000" loading="lazy" alt="Compact category list in the dark theme"></a>
<figcaption>The same list editors work in both themes. Open the picture to inspect the full section.</figcaption>
</figure>
