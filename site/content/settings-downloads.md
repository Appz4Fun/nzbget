+++
title = "Downloads and diagnostics"
description = "Guide to incoming NZBs, duplicate recovery, queue storage, connection limits, and diagnostic logging."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## Incoming NZBs

Set the scan interval and file age for the watched NZB folder. `AppendCategoryDir` controls category subfolders. Review archive scanning options if another program submits packed NZBs.

Duplicate handling belongs here too. `DupeCheck` groups backups by duplicate key. `DupeArticleFallback` enables article or live byte recovery from other copies. `DupeSearch` asks your configured indexer for more copies; start with `DupeSearchDryRun` while checking its behavior.

Keep the indexer URL and API key private. Follow [Duplicate fleets](duplicate-fleets.md) and [Indexer search](dupesearch.md) for the complete setup.

Key options: [`NzbDirInterval`](options.md#nzbdirinterval), [`NzbDirFileAge`](options.md#nzbdirfileage), [`DupeCheck`](options.md#dupecheck), [`DupeArticleFallback`](options.md#dupearticlefallback), [`DupeSearch`](options.md#dupesearch), [`DupeSearchDryRun`](options.md#dupesearchdryrun).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/incoming-nzbs.jpg" aria-label="Open full-size picture: Incoming NZB and duplicate-recovery controls with blank indexer credentials"><img src="assets/settings/incoming-nzbs.jpg" width="1280" height="1191" loading="lazy" alt="Incoming NZB and duplicate-recovery controls with blank indexer credentials"></a>
<figcaption>Use option help for the recovery and health-check controls. Open the picture to inspect the full section.</figcaption>
</figure>

## Download queue

Review queue persistence and partial-download continuation before changing cache or disk behavior. `ArticleCache` and `WriteBuffer` affect memory and write buffering. `DiskSpace` controls the free-space pause threshold.

`KeepHistory` sets history retention. `NzbCleanupDisk` controls whether the original NZB remains on disk. Duplicate fleets can need those original NZBs as sources, so follow the fleet guide when choosing cleanup behavior.

Use [Performance](performance.md) for measured tuning guidance. Keep `SkipWrite` and `RawArticle` for their documented diagnostic uses.

Key options: [`ContinuePartial`](options.md#continuepartial), [`ArticleCache`](options.md#articlecache), [`WriteBuffer`](options.md#writebuffer), [`DiskSpace`](options.md#diskspace), [`KeepHistory`](options.md#keephistory), [`NzbCleanupDisk`](options.md#nzbcleanupdisk).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/download-queue.jpg" aria-label="Open full-size picture: Download queue persistence, memory, disk, and cleanup settings"><img src="assets/settings/download-queue.jpg" width="1280" height="1059" loading="lazy" alt="Download queue persistence, memory, disk, and cleanup settings"></a>
<figcaption>Cache and cleanup values depend on the workload and available storage. Open the picture to inspect the full section.</figcaption>
</figure>

## Connection

Set timeouts and retries for your network. `ArticleRetries` and `ArticleInterval` govern article retries; URL downloads have separate retry controls. `DownloadRate` sets a rate limit, and zero removes that limit.

Monthly and daily quotas count download volume. Review quota units and the billing-period start day in option help. After changing retries or timeouts, check Messages for recurring failures rather than changing several controls at once.

Key options: [`ArticleRetries`](options.md#articleretries), [`ArticleTimeout`](options.md#articletimeout), [`UrlRetries`](options.md#urlretries), [`UrlTimeout`](options.md#urltimeout), [`DownloadRate`](options.md#downloadrate), [`MonthlyQuota`](options.md#monthlyquota), [`DailyQuota`](options.md#dailyquota).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/connection.jpg" aria-label="Open full-size picture: Article and URL connection controls, rate limit, and quotas"><img src="assets/settings/connection.jpg" width="1280" height="938" loading="lazy" alt="Article and URL connection controls, rate limit, and quotas"></a>
<figcaption>Article and URL downloads have separate controls. Open the picture to inspect the full section.</figcaption>
</figure>

## Logging

Enable `SystemHealthCheck` to expose configuration notices. `WriteLog`, `RotateLog`, and the log targets control file and screen output. `LogBuffer` controls the in-memory message buffer; `NzbLog` controls per-download logs.

Use debug output when investigating a specific issue, then return to the level you normally use. Before sharing logs, remove credentials, private URLs, and identifying download details. The Messages tab and a download's History details provide context for failures.

Key options: [`SystemHealthCheck`](options.md#systemhealthcheck), [`WriteLog`](options.md#writelog), [`RotateLog`](options.md#rotatelog), [`LogBuffer`](options.md#logbuffer), [`NzbLog`](options.md#nzblog), [`TimeCorrection`](options.md#timecorrection).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/logging.jpg" aria-label="Open full-size picture: System health, log targets, rotation, and message-buffer settings"><img src="assets/settings/logging.jpg" width="1280" height="938" loading="lazy" alt="System health, log targets, rotation, and message-buffer settings"></a>
<figcaption>Health checks and logging serve different diagnostic purposes. Open the picture to inspect the full section.</figcaption>
</figure>
