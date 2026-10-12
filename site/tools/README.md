# Settings pictures

The Settings guides use real WebUI captures from an isolated demonstration service. The pictures contain example values, blank credentials, and sanitized optional-extension defaults. Each picture documents the captured controls. Choose tuning values for the target installation.

The capture manifest records all 23 visible Settings sections, four list editors, phone navigation, option help, and dark mode. Each JPEG has dimensions and a SHA-256 hash. UI source hashes identify the captured version.

Check image integrity and guide coverage:

```sh
python3 site/tools/check-settings-captures.py
```

When refreshing pictures, also check the current UI source:

```sh
python3 site/tools/check-settings-captures.py --check-source
```

Use an isolated fixture serving the current WebUI. Include example server, category, feed, and scheduler entries. Optional extension pictures should use sanitized metadata from the installed version. Capture each section after its content loads. Resize the viewport to include every visible option row, and capture the four list editors separately. Keep the existing image names so guide links continue to work.

Review every picture for readable text, complete controls, connection errors, credentials, account URLs, and machine-specific folder values. Use variable-based folder examples and placeholder domains. Update the manifest and HTML image dimensions when replacing a picture. Build the site, check its links, run Vale, and review the guides at desktop and phone widths before publication.
