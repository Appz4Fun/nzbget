The WebUI density regression check uses Playwright and Chrome against an isolated,
loopback NZBGet instance serving the current WebUI. The fixture should start with
one configured news server. Never use a production instance: the check changes
the browser's unsaved configuration, and intercepts `saveconfig` before it reaches
the daemon.

```sh
node tests/webui/workspaces.js http://127.0.0.1:17689/
node tests/webui/workspace-interactions.js http://127.0.0.1:17689/
node tests/webui/full-width-layout.js http://127.0.0.1:17689/
node tests/webui/settings-density.js http://127.0.0.1:17689/
node tests/webui/settings-lists.js http://127.0.0.1:17689/
node tests/webui/settings-list-health.js http://127.0.0.1:17689/
node tests/webui/settings-phone-navigation.js http://127.0.0.1:17689/
node tests/webui/settings-titles.js http://127.0.0.1:17689/
node tests/webui/settings-locales.js http://127.0.0.1:17689/
node tests/webui/settings-compact-tiles.js http://127.0.0.1:17689/
node tests/webui/settings-health-startup.js http://127.0.0.1:17689/
node tests/webui/tls-cipher.js http://127.0.0.1:17689/
node tests/webui/tls-cipher-settings.js http://127.0.0.1:17689/
```

The TLS cipher dialog check fulfills candidate assets and intercepts every RPC.
It runs at 1280, 390 and 320 pixels in both themes, covering duplicate starts,
active-job reopening, progress, escaped provider text, compatibility details,
saved/reload results, cancellation, unsaved-server guards, unavailable backends,
keyboard close and the final table column. Optional sanitized JPEGs use
`NZBGET_UI_CAPTURE_DIR`. This dialog check uses a Config stub; actual editor
reconciliation and native behavior require the isolated daemon fixture described
in `tests/functional/tlscipher/README.md` and separate Settings checks.
The `tls-cipher-settings.js` check uses the real Settings model and intercepts
optimizer and save RPCs. It checks unsaved-server rejection, unrelated unsaved
field retention, confirmed cipher baselines, changed-browser rejection and the
actual subsequent save payload at desktop/phone widths in both themes.
Add `--offline` to run that same model/editor workflow with committed templates
and synthetic read replies, without a daemon. Automatic application startup is
omitted in this mode; actual Config, Options, controls, RPC transport and save
serialization remain active.

Checks cover both themes at desktop and phone widths, compact option height,
keyboard help disclosure, server Edit/Close, unsaved summary updates, adding,
reordering, deleting and renumbering servers, search navigation, and the raw save
payload after closing an editor.

The dialog layout regression needs no daemon. It uses the same loopback-only
target guard, fulfills committed assets locally, and omits automatic startup.
Actual modal templates, styles, Bootstrap and the merge renderer/caller remain
active; the merge RPC is intercepted. It checks full-width explanations and
merge lists, the final entry, matching speed/unit edges, and retained field
columns at 1280/768/390/320 pixels in both themes. Optional JPEGs use the same
existing `NZBGET_UI_CAPTURE_DIR` convention.

```sh
node tests/webui/dialog-layout.js http://127.0.0.1:17689/
```

The locale check verifies the server health label exists in all 20 translated
catalogs and renders translated summaries and help names in German, Spanish and
Turkish.

The list check exercises Categories, RSS Feeds and Scheduler tasks, including an
empty scheduler, scoped editor controls, keyboard Edit/Close, adding, moving,
deleting, renumbering, search, escaping and retained save values. Feed URLs and
scheduler command parameters are excluded from summaries.

The health check simulates option warnings and errors in read-only RPC responses
and verifies their counts remain visible on all three collapsed list types.

The phone-navigation check bounds the section menu, reaches every section by
keyboard, keeps the focused link in view, and checks that categories appear in
the first phone screen. Desktop retains the full menu in both themes.

The title check returns repeatedly from Paths to all five static Settings pages
and verifies their localized headings in English, German, and Turkish.

The full-width check compares navigation and content bounds as the desktop window
grows, verifies Status and Statistics use the available width in both themes,
and retains the compact category view on a phone.

The compact-tiles check exercises both themes at 1920, 1280, 1024, 390, and 320 pixels.
It verifies three/two/one column placement, labels above controls, source-order
tabbing, full-width main tabs, keyboard help, retained unsaved values, the discard
guard, and escaped extension summaries.
It also checks the desktop Save button's primary background and readable label
in normal, hover, and focus states, neutral disabled styling, and the View control.
Set `NZBGET_UI_CAPTURE_DIR` to an existing directory to capture sanitized desktop
JPEGs from the fixture; never use production values for those pictures.

The health-startup check holds the actual read-only health RPC reply until
Settings loads, then releases it and verifies the report arrives without errors.

The workspace checks cover Downloads, History, Statistics and Messages in both
themes at 1920, 1280, 768, 390 and 320 pixels. They verify accessible headings,
bounded table scrolling and final-column access, nonoverlapping provider charts,
and Add dialog geometry and payloads. The interaction check exercises native
keyboard activation, paging, row menus, download/history edits and their RPC
payloads, filters, status/volume navigation and empty views at desktop and phone
and tablet widths, including resizing across the phone breakpoint. Delayed
intercepted download and history saves exercise the real pending indicator timer
and verify disabled buttons remain readable without spinner overlap. Offline sanitized replies retain the real renderers; tested mutations
are intercepted. Both checks reject non-loopback targets. Optional JPEG captures
use an existing `NZBGET_UI_CAPTURE_DIR`; use a fresh directory for each attempt.
