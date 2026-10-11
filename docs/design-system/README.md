# NZBGet Design System tokens

`tokens.json` is the source of the web interface's design tokens: the colours of the dark and light themes, spacing, radii, shadows, sizes and font families. `webui/tokens.css` is generated from it:

```sh
python3 scripts/gen_webui_tokens.py          # regenerate webui/tokens.css
python3 scripts/gen_webui_tokens.py --check  # fail if webui/tokens.css is stale
```

Change a value here, regenerate, and commit both files. Text colours must keep 4.5:1 contrast on the grounds named in their `usage` note, in both themes.

The web UI uses the tokens through three stylesheets: `webui/tokens.css` (the custom properties), `webui/ds.css` (the `ng-*` component classes) and `webui/skin.css` (the restyle of the existing Bootstrap markup, loaded last).
