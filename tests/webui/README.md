The WebUI density regression check uses Playwright and Chrome against an isolated,
loopback NZBGet instance serving the current WebUI. The fixture should start with
one configured news server. Never use a production instance: the check changes
the browser's unsaved configuration, and intercepts `saveconfig` before it reaches
the daemon.

```sh
node tests/webui/settings-density.js http://127.0.0.1:17689/
node tests/webui/settings-lists.js http://127.0.0.1:17689/
node tests/webui/settings-list-health.js http://127.0.0.1:17689/
node tests/webui/settings-locales.js http://127.0.0.1:17689/
```

Checks cover both themes at desktop and phone widths, compact option height,
keyboard help disclosure, server Edit/Close, unsaved summary updates, adding,
reordering, deleting and renumbering servers, search navigation, and the raw save
payload after closing an editor.

The locale check verifies the server health label exists in all 20 translated
catalogs and renders translated summaries and help names in German, Spanish and
Turkish.

The list check exercises Categories, RSS Feeds and Scheduler tasks, including an
empty scheduler, scoped editor controls, keyboard Edit/Close, adding, moving,
deleting, renumbering, search, escaping and retained save values. Feed URLs and
scheduler command parameters are excluded from summaries.

The health check simulates option warnings and errors in read-only RPC responses
and verifies their counts remain visible on all three collapsed list types.
