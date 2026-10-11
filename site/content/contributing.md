+++
title = "Contributing"
description = "How to report problems, propose changes, port code to Rust, and edit this documentation."
eyebrow = "Project"
lede = "RustyGet is rewriting a mature program while people use it every day. The rules below keep that safe: behavior stays the same while code moves, and every change is checked before it ships."
+++

## Report a problem

Open an issue in the [repository](https://github.com/Appz4Fun/nzbget/issues). Include:

- The commit you built, from `nzbget -v` or the footer of the web interface.
- The settings involved, especially `DupeArticleFallback`, `HealthCheck`, and `DupeSearch`.
- The download's log from the **History** tab. Remove server names, user names, and NZB names that you don't want to share.

Report problems in stock NZBGet to the [NZBGet project](https://github.com/nzbgetcom/nzbget) instead.

## Propose a change

1. Fork the repository and branch from the default branch.
2. Keep one change per pull request. A port to Rust and a behavior change go in separate commits.
3. Write new code in Rust. Use C++ only as glue that Rust can't replace yet.
4. Add tests that fail without your change.
5. Open a pull request. An automated reviewer comments on each one; answer every comment with a fix or a reason.

Pull requests are squash-merged into a single signed commit.

## Port code to Rust

The port follows the rules in [Rust port status](rust-port.md#rules):

- A port matches the C++ output byte for byte, quirks included. If the C++ has a bug, the port keeps it, and the fix lands as its own commit.
- Before the switch, a differential test runs the old C++ and the new Rust side by side on the same inputs, including random ones.
- The C++ version stays behind `NZBGET_USE_RUST` as a fallback for builds without Rust, until those builds go away.
- Measure before and after. Ports of hot paths report their speed-up.

Prefer porting a whole module over a single small function.

## Tests

The inherited build and test workflows are disabled in the repository's Actions tab while the test suite is rebuilt for the rewrite. Until then, run the tests locally:

```bash
cmake -B build -DENABLE_TESTS=ON
cmake --build build -j 8
(cd build && ctest)
```

The duplicate-fleet features have a functional harness in `tests/functional/dupefallback/`, which runs real downloads against a local test news server. Point it at a copy of the binary, so a rebuild during the run can't change it:

```bash
cp build/nzbget /tmp/nzbget-under-test
python3 tests/functional/dupefallback/harness.py --nzbget /tmp/nzbget-under-test --scenario all
```

Check the pass count, not just the exit code: a build without `-DENABLE_TESTS=ON` runs no unit tests and still exits with `0`.

## Edit the documentation

This site lives in `site/` in the repository. Pages are Markdown files in `site/content/`, and `site/site.toml` sets the navigation.

1. Edit or add a page. Callouts use GitHub's alert syntax, such as `> [!NOTE]`.
2. Check the prose with [Vale](https://vale.sh) and the Google developer documentation style:

   ```bash
   vale README.md site/content
   ```

3. Build the site and check its links:

   ```bash
   python3 -m pip install --require-hashes -r site/requirements.lock
   python3 site/build.py --out build/site
   python3 site/check.py build/site
   ```

4. Preview it with `python3 -m http.server -d build/site`.

The site deploys to GitHub Pages on every push to the default branch. The build fails on any Vale warning or error and on any broken link. [Configuration options](options.md) and part of [Rust port status](rust-port.md) are generated from `nzbget.conf` and `rust/PORTING.md`, so edit those files, not the pages.

See [Design system](design-system.md) for the colors, components, and voice.

## AI-assisted work

Much of RustyGet is written with AI coding tools. That's welcome, on three conditions:

- Say in the pull request which tools you used and for what.
- Understand every line you submit, and be able to explain it without the tool.
- Run the tests yourself. A tool's claim that something works isn't a test result.

## License

RustyGet is free software under the GNU General Public License, version 2 or later, like the NZBGet code it started from. Keep existing copyright notices when you change a file.
