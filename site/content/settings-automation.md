+++
title = "Feeds and schedules"
description = "Create, edit, preview, and schedule RSS feeds and timed tasks from compact Settings lists."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## RSS feeds

1. Click **Add Feed** or **Edit** beside an existing feed.
2. Give it a name and enter the RSS URL from your indexer.
3. Set the filter, category, priority, and whether new NZBs start paused.
4. Use **Preview feed** to inspect the filter's result before relying on it.
5. Save your changes and observe the next fetch in Downloads and Messages.

`Interval` is in minutes. Zero disables automatic fetching. With `Backlog=yes`, the first fetch marks existing items as backlog and ignores them; later fetches process new items. Changing the URL or filter can cause another first-fetch backlog pass.

RSS URLs can contain account credentials or API keys. The compact summary shows the feed's name, category, and interval. Open the editor to review its URL and rules.

Key options: [`FeedN.URL`](options.md#feedn-url), [`FeedN.Filter`](options.md#feedn-filter), [`FeedN.Interval`](options.md#feedn-interval), [`FeedN.Backlog`](options.md#feedn-backlog), [`FeedN.PauseNzb`](options.md#feedn-pausenzb), [`FeedN.CategorySource`](options.md#feedn-categorysource).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/rss-feeds.jpg" aria-label="Open full-size picture: Compact RSS feed list with category, interval, and Edit"><img src="assets/settings/rss-feeds.jpg" width="1280" height="938" loading="lazy" alt="Compact RSS feed list with category, interval, and Edit"></a>
<figcaption>Feed URLs stay inside the editor. Open the picture to inspect the full section.</figcaption>
</figure>

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/feed-edit.jpg" aria-label="Open full-size picture: RSS feed editor with a placeholder URL and filter controls"><img src="assets/settings/feed-edit.jpg" width="1280" height="938" loading="lazy" alt="RSS feed editor with a placeholder URL and filter controls"></a>
<figcaption>The example URL does not connect to an indexer. Open the picture to inspect the full section.</figcaption>
</figure>

For rule syntax and examples, see the [RSS guide](https://github.com/Appz4Fun/nzbget/blob/HEAD/docs/usage/RSS.md) and the option's built-in help.

## Scheduler

Create one task per timed action. Each row summarizes its time, weekdays, and command. **Edit** reveals `Time`, `WeekDays`, `Command`, and `Param`.

- Enter times as `HH:MM`. A comma-separated list runs the task at several times.
- Use `*:00` for every hour, or `*` for program startup.
- Weekdays use numbers 1 through 7, with Monday as 1. `1-5` means weekdays.
- Choose the command, then supply `Param` only when that command needs it.

The example pauses downloads at 08:00 and resumes at 20:00 on weekdays. It is demonstration data, not an active schedule. Review `TimeCorrection` when the daemon's clock differs from the intended schedule.

Commands that select servers or feeds can use names or numbered entries. Recheck numbered references after you move or delete entries. `Process` runs an external program; `Script` runs scheduler extensions. Command parameters remain inside the editor.

Key options: [`TaskN.Time`](options.md#taskn-time), [`TaskN.WeekDays`](options.md#taskn-weekdays), [`TaskN.Command`](options.md#taskn-command), [`TaskN.Param`](options.md#taskn-param), [`TimeCorrection`](options.md#timecorrection).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/scheduler.jpg" aria-label="Open full-size picture: Scheduler list with weekday pause and resume examples"><img src="assets/settings/scheduler.jpg" width="1280" height="938" loading="lazy" alt="Scheduler list with weekday pause and resume examples"></a>
<figcaption>Each timed action has its own Edit control. Open the picture to inspect the full section.</figcaption>
</figure>

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/task-edit.jpg" aria-label="Open full-size picture: Expanded scheduler editor with time, weekdays, command, and parameter"><img src="assets/settings/task-edit.jpg" width="1280" height="938" loading="lazy" alt="Expanded scheduler editor with time, weekdays, command, and parameter"></a>
<figcaption>Read the command help before supplying a parameter. Open the picture to inspect the full section.</figcaption>
</figure>
