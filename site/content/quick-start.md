+++
title = "Quick start"
description = "Secure the web interface, add news servers, set paths and categories, and download your first NZB with RustyGet."
eyebrow = "Get started"
lede = "Five settings get RustyGet downloading. Three more turn on the duplicate fleet features that set it apart."
+++

Open the web interface at `http://<host>:6789` and go to **Settings**. Click **Save all changes** after each section, then reload when prompted.

## Set up the basics

<ol class="steps">
<li><p><strong>Secure the interface.</strong> In <strong>SECURITY</strong>, set <code>ControlUsername</code> and <code>ControlPassword</code>. Give other programs their own accounts: <code>RestrictedUsername</code> can use the interface but can't change settings, and <code>AddUsername</code> can only add downloads.</p></li>
<li><p><strong>Add your news servers.</strong> In <strong>NEWS-SERVERS</strong>, enter the host, port, user name, password, and connection count from your provider. Keep encryption on. Click <strong>Test connection</strong>. Add block accounts as fill servers at level 1. See <a href="automation.html#news-servers">News servers</a>.</p></li>
<li><p><strong>Choose your folders.</strong> In <strong>PATHS</strong>, set <code>MainDir</code>. The other paths default to folders inside it: <code>DestDir</code> for finished files, <code>InterDir</code> for downloads in progress, <code>NzbDir</code> for incoming NZB files, and <code>QueueDir</code> for the queue and history.</p></li>
<li><p><strong>Add categories.</strong> In <strong>CATEGORIES</strong>, add one per kind of download, such as Movies and TV, each with its own <code>DestDir</code>. Media managers and the Kodi add-on send a category with each download.</p></li>
<li><p><strong>Check unpacking.</strong> In <strong>UNPACK</strong>, make sure <code>UnrarCmd</code> and <code>SevenZipCmd</code> point to working programs.</p></li>
</ol>

## Add a download

You can add NZB files in several ways:

- **Web interface:** click **Add** and choose a file or paste a URL.
- **Watched folder:** drop the file into `NzbDir`. A subfolder's name becomes the download's category.
- **Media managers:** in Sonarr, Radarr, or Lidarr, add a download client of type NZBGet with your host, port, and an `AddUsername` account.
- **Kodi:** the NeNeTeePee Stream add-on sends a whole fleet of copies at once. See [Streaming with Kodi](kodi.md).
- **API:** call `append` or `appendfleet`. See [API and compatibility](api.md).

Watch the download in the **Downloads** tab. When it finishes, the **History** tab shows the result, the health, and each post-processing step.

## Turn on duplicate fleets

These settings live in **INCOMING NZBS** and **CHECK AND REPAIR**. Each defaults to NZBGet's behavior, so turn them on in this order and watch a few downloads after each step.

| Step | Setting | Effect |
|---|---|---|
| 1 | `DupeCheck=yes` | Groups copies of the same title by duplicate key and keeps backups in history. On by default. |
| 2 | `HealthCheck=dupe` | Fails over early to a better copy when a download can't complete. |
| 3 | `DupeArticleFallback=article` | Fetches articles that no server has from duplicate postings. Use `live` to also repair bytes while downloading. |
| 4 | `NzbCleanupDisk=no` | Keeps the NZB files of history items, so they can still serve as sources. |
| 5 | `DupeSearch=yes` | Searches NZBHydra2 for more copies of each new download. Start with `DupeSearchDryRun=yes`. |

[Duplicate fleets](duplicate-fleets.md) explains each step, and [Configuration options](options.md#incoming-nzbs) lists every setting.

> [!TIP] Article retries
> Keep `ArticleRetries` at 3 or more with `HealthCheck=dupe` or `DupeSearch`. RustyGet warns at startup when it's lower, because one network hiccup can otherwise look like a missing article.
