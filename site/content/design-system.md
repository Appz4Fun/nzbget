+++
title = "Design system"
description = "Oxide, the RustyGet design system: color tokens, type, components, and voice for the docs, the README, and future interfaces."
eyebrow = "Reference"
lede = "Oxide is the visual language of RustyGet. It borrows from metal and the oxides that form on it: iron oxide for action, copper patina for health, steel for reference, and cast iron for text."
+++

## Principles

- **Functional first.** Every element helps a reader find, read, or act. Decoration that doesn't do one of those jobs stays out.
- **Quiet surfaces, one accent.** Warm paper and cast-iron ink carry the page. The `--rust` accent marks the single most important action or state in view.
- **Color carries meaning.** Each accent has one job, and it keeps that job everywhere it appears: on this site, in the README badges, and in any interface that adopts the tokens.
- **Readable in both themes.** Every text color passes WCAG AA contrast (4.5:1) on every surface it appears on. That holds in both the light and the dark theme.
- **Feels like the toolchain.** Callouts read like compiler diagnostics, paths read like Rust module paths, and code is first-class.

## Color tokens

The swatches below use the live tokens, so they change when you switch themes with the button in the header.

<div class="swatches">
<div class="swatch"><i style="background:var(--paper)"></i><b><code>--paper</code></b><span>#f7f4ef · #12100e</span></div>
<div class="swatch"><i style="background:var(--surface)"></i><b><code>--surface</code></b><span>#ffffff · #1b1714</span></div>
<div class="swatch"><i style="background:var(--sunken)"></i><b><code>--sunken</code></b><span>#f0eae2 · #1e1915</span></div>
<div class="swatch"><i style="background:var(--ink)"></i><b><code>--ink</code></b><span>#1c1916 · #f1eae2</span></div>
<div class="swatch"><i style="background:var(--muted)"></i><b><code>--muted</code></b><span>#5c534b · #b3a79b</span></div>
<div class="swatch"><i style="background:var(--line)"></i><b><code>--line</code></b><span>#e4dcd2 · #352e28</span></div>
<div class="swatch"><i style="background:var(--rust)"></i><b><code>--rust</code></b><span>#a8400f · #f08c5a</span></div>
<div class="swatch"><i style="background:var(--patina)"></i><b><code>--patina</code></b><span>#1d6f60 · #6cc9b4</span></div>
<div class="swatch"><i style="background:var(--steel)"></i><b><code>--steel</code></b><span>#3d5a73 · #9ab8d1</span></div>
<div class="swatch"><i style="background:var(--amber)"></i><b><code>--amber</code></b><span>#8a5a00 · #e3b45a</span></div>
<div class="swatch"><i style="background:var(--ember)"></i><b><code>--ember</code></b><span>#b02a1f · #f2867a</span></div>
</div>

Each accent also has a `-soft` variant for backgrounds, such as `--rust-soft`. Text in an accent color sits on paper, surface, or its own soft variant.

| Token | Meaning | Used for |
|---|---|---|
| `--rust` | Action and emphasis | Links, the primary button, the current page, `new` tags, the primary copy of a fleet |
| `--patina` | Healthy and verified | Success states, twins proven by checksums, completed steps, `help:` callouts |
| `--steel` | Reference and neutral | `note:` callouts, alts, `changed` tags, cross-references |
| `--amber` | Needs attention | `warning:` callouts, degraded health, settings that send network traffic |
| `--ember` | Failure and danger | `caution:` callouts, failed downloads, settings that delete data |
| `--ink`, `--muted` | Text | Body text and secondary text |
| `--paper`, `--surface`, `--sunken` | Surfaces | The page background, raised cards, and inset areas such as code |
| `--line`, `--line-strong` | Structure | Borders, rules, table grid lines |

### Contrast

Measured as WCAG 2 contrast ratios against `--paper`:

| Token | Light theme | Dark theme |
|---|---|---|
| `--ink` | 15.9:1 | 15.9:1 |
| `--muted` | 6.9:1 | 8.1:1 |
| `--rust` | 5.6:1 | 7.8:1 |
| `--patina` | 5.5:1 | 9.6:1 |
| `--steel` | 6.6:1 | 9.2:1 |
| `--amber` | 5.4:1 | 9.9:1 |
| `--ember` | 6.0:1 | 7.7:1 |

The lowest pairing anywhere in the system is `--amber` on `--rust-soft` at 4.9:1.

## Type

- **Text:** the platform's system font stack (`system-ui`). It loads instantly and matches the reader's operating system.
- **Code and labels:** a monospace stack that starts with `ui-monospace`. Navigation labels, eyebrows, tags, and diagnostics use it too, which gives the interface its toolchain feel.
- **Scale:** body text is 16 px with a 1.65 line height. Page titles scale from 32 px to 44 px. Headings use a slight negative letter spacing; labels use uppercase with wide spacing.
- **Line length:** paragraphs stop at about 76 characters.

## Shape and space

- Corner radius is 10 px for panels and cards, and 6 px for controls.
- Borders are 1 px in `--line`. Shadows appear only on hover and on floating panels such as search results.
- The layout is a sidebar, a content column of up to 800 px, and an outline on wide screens. On phones the sidebar folds into a menu and the page keeps a 16 px gutter.

## Components

### Diagnostics

Callouts borrow the shape of compiler output: a level, a colon, an optional title, and a gutter down the left. Write them in Markdown with GitHub's alert syntax, so they read the same on GitHub.

```markdown
> [!WARNING] DupeSearch sends traffic to your indexers
> Start with DupeSearchDryRun=yes and read the log first.
```

> [!NOTE] note
> Background a reader can skip.

> [!TIP] help
> A suggestion that saves time.

> [!IMPORTANT] important
> Something a reader must know to succeed.

> [!WARNING] warning
> A setting or action with side effects.

> [!CAUTION] caution
> Risk of lost data or a broken setup.

### Tags

Tags label states in short monospace text: <span class="tag tag-new">new</span> <span class="tag tag-ref">changed</span> <span class="tag tag-primary">PRIMARY</span> <span class="tag tag-twin">TWIN</span> <span class="tag tag-alt">ALT</span> <span class="tag tag-ok">SUCCESS</span> <span class="tag tag-warn">WARNING</span> <span class="tag tag-bad">FAILURE</span>

In the docs, the fleet tags use `--rust` for the primary copy, `--patina` for a twin, and `--steel` for an alt. In the web interface, a fleet tag takes its color from the copy's file fingerprint instead, so copies that hold the same files share a color.

### Module paths

Each page shows its location as a Rust-style path, such as `rustyget::docs::design_system`. The path doubles as a breadcrumb.

### Code blocks

Code blocks name their language in a header bar and offer a copy button when the browser allows clipboard access.

## The mark

The mark is a hex nut with a download arrow: hardware for a tool that builds files out of parts. It's drawn from simple paths so it works as a favicon, in the masthead, and in the README wordmark. The README uses separate light and dark wordmarks so it reads well in both GitHub themes.

## Voice

- Follow the [Google developer documentation style guide](https://developers.google.com/style). Vale checks every page and the README on each build.
- Use second person and present tense. Describe what the software does now, not plans for later.
- Use sentence case for headings.
- Use the project's words consistently: **fleet** for all postings of one title, **primary** for the copy being downloaded, **twin** for a byte-identical copy proven by par2 checksums, and **alt** for the same release in another encode.
- Never claim a feature that the code doesn't have. Mark planned work as planned.

## Use in other surfaces

The tokens live in `site/assets/site.css`. Other surfaces, such as a future web interface, should copy the token block rather than invent new colors, and keep the accent meanings from the token table.
