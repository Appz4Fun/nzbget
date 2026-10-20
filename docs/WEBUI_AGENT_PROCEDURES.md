## WebUI changes and Settings guides

Use this section for WebUI and documentation work. Keep UI-only validation and deployment separate from backend build, benchmark, and rollout permissions.

### Isolated UI validation

- Run destructive editor exercises against an isolated loopback NZBGet service serving the exact candidate WebUI. The fixture should include one news server and example list entries, including an empty Scheduler case. Use the Playwright and Chrome runtime already available to the job.
- The committed Settings checks reject non-loopback targets. Preserve that guard. Intercept saveconfig for editor tests so assertions inspect the payload without changing daemon configuration. Simulate health notices through read-only RPC fixture responses.
- Exercise light and dark themes at desktop and phone widths. Cover native keyboard activation, Edit/Close, unsaved summaries, adding, deleting, reordering, renumbering, retained save values, search, and health navigation. Feed URLs and scheduler parameters must stay out of compact summaries.
- Test programmatic section changes separately from focused keyboard links. Native focus can scroll a menu automatically and conceal a search-navigation defect. Keep the active link visible by scrolling only the bounded phone menu, preserving the document position, and focus.
- After an action, refresh the cheapest relevant actual state. Use direct
  locators for current selected/expanded attributes and the geometry of the
  intended link. If a batched snapshot disagrees with visible headings, inspect
  fresh accessibility state before treating the mismatch as a product defect
  or repeating the action.
- After replacing a localized heading with manual text, clear its cached translation value before returning to a translated static page. Test repeated returns in several locales; one successful initial heading is insufficient.
- Preserve failed regression output, fix the cause, and run the affected check again. Report fixture/setup failures separately from product failures; a skipped interaction is not a pass. Record the exact source, check list, and log hashes. Repeat a full UI suite when new source changes invalidate the previous run.

Run the committed Settings checks using the isolated service URL described in tests/webui/README.md:

```sh
node tests/webui/settings-density.js http://127.0.0.1:17689/
node tests/webui/settings-lists.js http://127.0.0.1:17689/
node tests/webui/settings-list-health.js http://127.0.0.1:17689/
node tests/webui/settings-phone-navigation.js http://127.0.0.1:17689/
node tests/webui/settings-titles.js http://127.0.0.1:17689/
node tests/webui/settings-locales.js http://127.0.0.1:17689/
```

### Screenshot capture

- Capture actual browser screenshots as JPEGs from a sanitized demonstration service. Use example domains, blank credentials, variable-based or relative folder examples, and sanitized optional-extension definitions. Never publish production configuration, provider account details, or host folder locations.
- Wait for the selected section and all asynchronous content to load. Inspect the complete page, including the last option or table row, before declaring a capture complete. Full-page capture does not expand an internally scrolling pane; increase the viewport or capture its complete content.
- Verify the active tab's actual viewport dimensions before capturing. A browser-wide viewport change can affect the selected tab rather than another bound tab. Use the visible controls and accessibility state to resolve conflicts with an edited field's initial DOM snapshot value.
- Capture every visible Settings section and each list editor separately. Include phone navigation, option help, and dark mode. Keep controls legible and inspect every picture for clipping, overflow, connection errors, and private data.
- When pictures change, update JPEG dimensions and SHA-256 hashes in site/assets/settings/captures.json and the guide image attributes. Freshness metadata covers every tracked WebUI asset and `nzbget.conf`. Use --check-source when refreshing; the ordinary CI integrity check intentionally does not require future UI commits to recapture unchanged pictures.
- Keep previews short on screen, with accessible full-size links, useful alt text, captions, explicit dimensions, and lazy loading. Override preview clipping for print; check print media as well as phone and desktop layouts.

### Documentation checks

Use the locked dependencies in site/requirements.lock, verify prose with the configured Vale styles, and build the exact reviewed source. Keep demonstrations distinct from tuning recommendations and production status. Verify behavioral claims against source and built-in option help; UnpackIgnoreExt affects nonstandard RAR handling and is not a general extraction exclusion.

```sh
python3 site/tools/check-settings-captures.py
python3 site/tools/check-settings-captures.py --check-source
vale --minAlertLevel=warning --output=line README.md site/content site/tools/README.md
python3 site/build.py --out build/site
python3 site/check.py build/site
```

Inspect every changed guide at desktop and phone widths, in both themes when relevant. Confirm accessible full-size links and complete print captures. The Pages workflow publishes only the canonical default branch. Verify the actual deployed page, image bytes and build revision after a merge; a successful local build is not publication evidence.

### Review and live UI delivery

Preserve the currently assigned default integrator, shared scheduling, authorization and release holds. The PR owner owns deployment and live verification under the shared PR delivery policy in AGENTS.md. Obtain exact-head independent and GitHub reviews, resolve actionable threads, and refresh default ancestry before integration. Retain the original registered signed squash commit and canonical xbmc4lyfe author and committer identities; confirm GitHub verification after publishing.

For an authorized UI-only rollout, the PR owner stages the exact merged WebUI assets, preserves the current daemon binary, process, configuration and providers, installs atomically with a recovery copy, and checks served asset hashes and warm service health. The same PR owner then checks all main tabs and Settings sections at desktop and phone widths without saving, reloading, shutting down, testing providers, or changing live values. Report merged, published, installed, verified, and any separate backend hold distinctly.
