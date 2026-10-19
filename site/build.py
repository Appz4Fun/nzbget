#!/usr/bin/env python3
"""Build the documentation site.

Reads Markdown pages from site/content, renders them with the Jinja templates
in site/templates, and writes a static site that GitHub Pages can serve.
The configuration reference is generated from the repository's nzbget.conf,
and the Rust port status from rust/PORTING.md.

    python3 site/build.py --out build/site
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent

ALERTS = {
    "NOTE": "note",
    "TIP": "help",
    "IMPORTANT": "important",
    "WARNING": "warning",
    "CAUTION": "caution",
}


@dataclass
class Page:
    slug: str
    source: str
    meta: dict
    body: str = ""
    toc: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{self.slug}.html"

    @property
    def title(self) -> str:
        return self.meta["title"]


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[`'\"’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "section"


def split_front_matter(text: str, name: str) -> tuple[dict, str]:
    if not text.startswith("+++\n"):
        raise SystemExit(f"{name}: missing +++ front matter")
    end = text.index("\n+++\n", 4)
    return tomllib.loads(text[4:end]), text[end + 5 :]


def markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "typographer": False})
    md.enable(["table", "strikethrough"])
    md.use(deflist_plugin)
    md.use(tasklists_plugin)

    def fence(renderer, tokens, idx, options, env):
        token = tokens[idx]
        lang = token.info.strip().split(" ")[0]
        label = html.escape(lang or "text")
        code = html.escape(token.content)
        return (
            f'<div class="code"><div class="code-head"><span>{label}</span>'
            f'<button class="copy" type="button" hidden>Copy</button></div>'
            f'<pre><code class="language-{label}">{code}</code></pre></div>\n'
        )

    md.add_render_rule("fence", fence)
    md.add_render_rule("table_open", lambda *a: '<div class="table-wrap"><table>\n')
    md.add_render_rule("table_close", lambda *a: "</table></div>\n")
    return md


def rewrite_links(tokens: list[Token]) -> None:
    for token in tokens:
        if token.children:
            rewrite_links(token.children)
        if token.type == "link_open":
            href = token.attrGet("href") or ""
            if not re.match(r"^[a-z]+:", href):
                href = re.sub(r"\.md(#|$)", r".html\1", href)
                token.attrSet("href", href)
            else:
                token.attrSet("class", "ext")


def convert_alerts(tokens: list[Token]) -> list[Token]:
    """Turn GitHub alert blockquotes into compiler-style diagnostics."""
    out: list[Token] = []
    closers: dict[int, str] = {}
    for i, token in enumerate(tokens):
        if token.type == "blockquote_open" and i + 2 < len(tokens):
            inline = tokens[i + 2]
            first = inline.children[0] if inline.children else None
            match = first and re.match(r"^\[!(\w+)\]\s*(.*)$", first.content)
            if match and match.group(1) in ALERTS:
                level = ALERTS[match.group(1)]
                title = match.group(2)
                first.content = ""
                if len(inline.children) > 1 and inline.children[1].type == "softbreak":
                    inline.children[1].type = "text"
                    inline.children[1].content = ""
                token.tag = "aside"
                token.attrSet("class", f"diag diag-{level}")
                closers[token.level] = "aside"
                head = Token("html_block", "", 0)
                head.content = (
                    f'<p class="diag-head"><span class="diag-level">{level}</span>'
                    + (f'<span class="diag-title">: {html.escape(title)}</span>' if title else "")
                    + '</p><div class="diag-body">\n'
                )
                out.append(token)
                out.append(head)
                continue
        if token.type == "blockquote_close" and closers.get(token.level):
            del closers[token.level]
            tail = Token("html_block", "", 0)
            tail.content = "</div>\n"
            token.tag = "aside"
            out.append(tail)
        out.append(token)
    # Drop paragraphs that only held the alert marker.
    cleaned: list[Token] = []
    i = 0
    while i < len(out):
        if (
            out[i].type == "paragraph_open"
            and i + 2 < len(out)
            and out[i + 1].type == "inline"
            and not "".join(c.content for c in out[i + 1].children or []).strip()
            and out[i + 2].type == "paragraph_close"
        ):
            i += 3
            continue
        cleaned.append(out[i])
        i += 1
    return cleaned


def render(md: MarkdownIt, page: Page) -> None:
    env: dict = {}
    tokens = md.parse(page.source, env)
    tokens = convert_alerts(tokens)
    rewrite_links(tokens)
    seen: dict[str, int] = {}
    for i, token in enumerate(tokens):
        if token.type == "heading_open":
            text = tokens[i + 1].content
            slug = slugify(text)
            if slug in seen:
                seen[slug] += 1
                slug = f"{slug}-{seen[slug]}"
            else:
                seen[slug] = 0
            token.attrSet("id", slug)
            plain = re.sub(r"[`*_]", "", text)
            if token.tag in ("h2", "h3"):
                page.toc.append({"level": int(token.tag[1]), "id": slug, "text": plain})
    page.body = md.renderer.render(tokens, md.options, env)
    page.sections = search_sections(page)


def search_sections(page: Page) -> list[dict]:
    """Split the rendered page at h2 headings for the search index."""
    parts = re.split(r'(<h2 id="[^"]+">.*?</h2>)', page.body)
    sections = [{"s": "", "u": page.url, "x": parts[0]}]
    for i in range(1, len(parts), 2):
        hid = re.search(r'id="([^"]+)"', parts[i]).group(1)
        heading = re.sub(r"<[^>]+>", "", parts[i])
        sections.append({"s": html.unescape(heading), "u": f"{page.url}#{hid}", "x": parts[i + 1]})
    for section in sections:
        text = re.sub(r"<[^>]+>", " ", section["x"])
        section["x"] = re.sub(r"\s+", " ", html.unescape(text)).strip()
        section["t"] = page.title
    return [s for s in sections if s["x"] or s["s"]]


# ---------------------------------------------------------------------------
# Generated pages


def section_title(header: str) -> str:
    """"NEWS-SERVERS" -> "News servers", "RSS FEEDS" -> "RSS feeds"."""
    words = header.replace("-", " ").lower().split()
    fixed = {"rss": "RSS", "nzbs": "NZBs"}
    words = [fixed.get(w, w) for w in words]
    words[0] = words[0][0].upper() + words[0][1:]
    return " ".join(words)


def parse_conf(path: Path, upstream: dict[str, str]) -> list[dict]:
    """Parse nzbget.conf into sections of documented options.

    A comment block directly above an option line documents that option.
    Its first line is the summary, which may end with the allowed values in
    parentheses. Numbered options such as Server1.Host are listed once, as
    ServerN.Host.
    """
    sections: list[dict] = []
    comment: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        header = re.match(r"^### (.+?)\s+###$", line)
        if header:
            sections.append({"title": section_title(header.group(1)), "options": []})
            comment = []
        elif line.startswith("####") or not line.strip():
            comment = []
        elif option := re.match(r"^#?([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?)=(.*)$", line):
            name, value = option.groups()
            generic = re.sub(r"(\D)\d+\.", r"\1N.", name)
            if sections and comment and generic not in seen:
                seen.add(generic)
                blank = comment.index("") if "" in comment else len(comment)
                summary = " ".join(c.strip() for c in comment[:blank])
                values = re.search(r"\(([^()]*)\)\.?$", summary)
                sections[-1]["options"].append(
                    {
                        "name": generic,
                        "id": slugify(generic),
                        "default": value,
                        "summary": summary,
                        "values": values.group(1) if values else "",
                        "details": "\n".join(comment[blank + 1 :]).strip(),
                        "new": generic not in upstream,
                        "changed": generic in upstream and upstream[generic] != summary,
                    }
                )
            comment = []
        elif line.startswith("#"):
            text = line[1:]
            comment.append(text[1:] if text.startswith(" ") else text)
        else:
            comment = []
    return [s for s in sections if s["options"]]


def conf_details_html(text: str, known: set[str]) -> str:
    """Render an option's comment block as paragraphs and preformatted lists."""
    blocks = re.split(r"\n\s*\n", text.strip())
    out = []
    for block in blocks:
        lines = [l for l in block.splitlines()]
        if not "".join(lines).strip():
            continue
        body = html.escape("\n".join(lines))

        def link(m: re.Match) -> str:
            name = m.group(1)
            generic = re.sub(r"(\D)\d+\.", r"\1N.", name)
            if generic in known:
                return f'<a href="#{slugify(generic)}"><code>{name}</code></a>'
            return f"<code>{name}</code>"

        body = re.sub(r"&lt;([A-Za-z][A-Za-z0-9.]*)&gt;", link, body)
        if any(l.startswith((" ", "\t")) for l in lines[1:]) or re.search(r"^\s+\w+\s+-", "\n".join(lines), re.M):
            out.append(f'<pre class="conf-pre">{body}</pre>')
        else:
            out.append(f"<p>{' '.join(body.splitlines())}</p>")
    return "\n".join(out)


def options_search(sections: list, url: str, title: str) -> list[dict]:
    entries = []
    for section in sections:
        entries.append({
            "t": title,
            "s": section["title"],
            "u": f"{url}#{section['id']}",
            "x": "Options: " + ", ".join(o["name"] for o in section["options"]),
        })
        for o in section["options"]:
            text = " ".join([o["summary"], o["values"], o["details"]])
            entries.append({
                "t": title,
                "s": o["name"],
                "u": f"{url}#{o['id']}",
                "x": re.sub(r"\s+", " ", text).strip(),
            })
    return entries


def options_page(conf: Path, upstream_file: Path) -> tuple[str, list, list]:
    upstream = {}
    if upstream_file.exists():
        upstream = dict(l.split("\t", 1) for l in upstream_file.read_text(encoding="utf-8").splitlines() if "\t" in l)
    sections = parse_conf(conf, upstream)
    known = {o["name"] for s in sections for o in s["options"]}
    parts = []
    toc = []
    total = sum(len(s["options"]) for s in sections)
    new = sum(o["new"] for s in sections for o in s["options"])
    changed = sum(o["changed"] for s in sections for o in s["options"])
    parts.append(
        f'<p class="lede-sm">{total} options in {len(sections)} sections. '
        f'<span class="tag tag-new">new</span> marks the {new} options that NZBGet doesn\'t have, and '
        f'<span class="tag tag-ref">changed</span> marks the {changed} option{"s" if changed != 1 else ""} whose values or meaning differ from NZBGet. '
        "This page is generated from <code>nzbget.conf</code> on every build, "
        "so it always matches the code.</p>"
    )
    parts.append(
        '<div class="filter"><label for="opt-filter">Filter options</label>'
        '<input id="opt-filter" type="search" placeholder="Type an option name, like Dupe" autocomplete="off">'
        '<label class="check"><input id="opt-new" type="checkbox"> Only new and changed options</label></div>'
    )
    for section in sections:
        sid = slugify(section["title"])
        if sid in {o["id"] for s2 in sections for o in s2["options"]}:
            sid += "-options"
        section["id"] = sid
        toc.append({"level": 2, "id": sid, "text": section["title"]})
        parts.append(f'<section class="conf-section" data-section><h2 id="{sid}">{html.escape(section["title"])}</h2>')
        for o in section["options"]:
            tag = '<span class="tag tag-new">new</span>' if o["new"] else ""
            if o["changed"]:
                tag = '<span class="tag tag-ref" title="NZBGet has this option with other values or another meaning">changed</span>'
            default = html.escape(o["default"]) if o["default"] else "<em>empty</em>"
            values = f'<span class="conf-values">{html.escape(o["values"])}</span>' if o["values"] else ""
            parts.append(
                f'<article class="conf-option" id="{o["id"]}" data-name="{html.escape(o["name"].lower())}" data-new="{int(o["new"] or o["changed"])}">'
                f'<header><h3><a href="#{o["id"]}">{html.escape(o["name"])}</a></h3>{tag}{values}</header>'
                f'<p class="conf-summary">{html.escape(o["summary"])}</p>'
                f'<p class="conf-default">default <code>{default}</code></p>'
                f'{conf_details_html(o["details"], known)}</article>'
            )
        parts.append("</section>")
    return "\n".join(parts), toc, sections


def rust_modules(src: Path) -> str:
    """A table of the crate's modules, from each file's leading //! comment."""
    rows = []
    for path in sorted(src.glob("*.rs")):
        if path.stem == "lib":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        doc = []
        for line in lines:
            if not line.startswith("//!"):
                break
            text = line[3:].strip()
            if not text and doc:
                break
            doc.append(text)
        summary = " ".join(doc)
        first = re.match(r"(.+?\.)(\s|$)", summary)
        summary = first.group(1) if first else summary
        if len(summary) > 200:
            summary = summary[:200].rsplit(" ", 1)[0].rstrip(",;:-(") + "…"
        summary = summary.replace("|", "\\|")
        rows.append(f"| `{path.stem}` | {summary} | {len(lines):,} |")
    head = "| Module | What it does | Lines |\n|---|---|---|\n"
    return head + "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------


MARKER = ".rustyget-site"


def prepare_output(out: Path) -> None:
    """Empty the output directory, refusing anything that isn't ours to delete.

    Only a directory that an earlier build marked as its output, or an empty
    one, is cleared. The repository, its parents and the site sources never are.
    """
    if out == ROOT or out in ROOT.parents or out == SITE or SITE in out.parents or out in SITE.parents:
        raise SystemExit(f"refusing to write the site into {out}: choose a separate directory, such as build/site")
    if out.exists():
        if not out.is_dir():
            raise SystemExit(f"{out} exists and isn't a directory")
        if (out / MARKER).exists():
            shutil.rmtree(out)
        elif any(out.iterdir()):
            raise SystemExit(f"{out} isn't empty and wasn't made by this script; remove it or choose another directory")
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Output of site/build.py. The next build deletes this directory.\n")


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build(out: Path) -> None:
    config = tomllib.loads((SITE / "site.toml").read_text(encoding="utf-8"))
    md = markdown()
    pages: dict[str, Page] = {}
    nav = []
    for group in config["nav"]:
        items = []
        for slug in group["pages"]:
            source = SITE / "content" / f"{slug}.md"
            meta, body = split_front_matter(source.read_text(encoding="utf-8"), source.name)
            page = Page(slug=slug, source=body, meta=meta)
            pages[slug] = page
            items.append(page)
        nav.append({"title": group["title"], "pages": items})

    for page in pages.values():
        if page.meta.get("generated") == "options":
            body, toc, conf_sections = options_page(ROOT / "nzbget.conf", SITE / "data" / "upstream-options.txt")
            render(md, page)
            page.sections = search_sections(page) + options_search(conf_sections, page.url, page.title)
            page.body = page.body + body
            page.toc = page.toc + toc
        elif page.meta.get("generated") == "porting":
            porting = (ROOT / "rust" / "PORTING.md").read_text(encoding="utf-8")
            porting = re.sub(r"^# .*\n", "", porting, count=1)
            porting = re.sub(r"^## ", "### ", porting, flags=re.M)
            page.source = page.source.replace("<!-- modules -->", rust_modules(ROOT / "rust" / "src"))
            page.source = page.source.replace("<!-- porting -->", porting)
            render(md, page)
        else:
            render(md, page)

    order = [p for group in nav for p in group["pages"]]
    # links to the source follow the branch this build came from (GitHub
    # Actions sets GITHUB_REF_NAME), so a deploy from main links to main
    site_config = dict(config["site"])
    site_config["branch"] = os.environ.get("GITHUB_REF_NAME") or site_config["branch"]
    sha = git("rev-parse", "--short=8", "HEAD")
    built = git("log", "-1", "--format=%cs")

    jenv = Environment(
        loader=FileSystemLoader(SITE / "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    prepare_output(out)
    shutil.copytree(SITE / "assets", out / "assets")
    (out / ".nojekyll").write_text("")

    index = []
    for i, page in enumerate(order):
        template = jenv.get_template(page.meta.get("template", "page") + ".html")
        rendered = template.render(
            site=site_config,
            nav=nav,
            page=page,
            prev=order[i - 1] if i > 0 else None,
            next=order[i + 1] if i + 1 < len(order) else None,
            sha=sha,
            built=built,
            root="",
        )
        (out / page.url).write_text(rendered, encoding="utf-8")
        for section in page.sections:
            index.append(section)

    # GitHub Pages serves 404.html at whatever path was missing, so its links
    # start at the site's base path instead of being relative
    base_path = urlsplit(config["site"]["base_url"]).path or "/"
    not_found = Page(slug="404", source="", meta={"title": "Page not found", "description": "The page does not exist."})
    not_found.body = (
        '<p class="lede-sm">This page does not exist. It may have moved when the documentation was reorganized.</p>'
        f'<p><a class="button primary" href="{base_path}index.html">Go to the overview</a></p>'
    )
    (out / "404.html").write_text(
        jenv.get_template("page.html").render(
            site=site_config, nav=nav, page=not_found, prev=None, next=None, sha=sha, built=built,
            root=base_path,
        ),
        encoding="utf-8",
    )
    (out / "search.json").write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    base = config["site"]["base_url"].rstrip("/") + "/"
    urls = "".join(f"<url><loc>{base}{p.url}</loc></url>" for p in order)
    (out / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
    )
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}sitemap.xml\n")
    print(f"built {len(order)} pages into {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "site", help="output directory")
    args = parser.parse_args()
    build(args.out.resolve())


if __name__ == "__main__":
    main()
