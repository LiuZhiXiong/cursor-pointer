#!/usr/bin/env python3
"""Build a static landing page for cursor-pointer.

Reads marketing files under docs/marketing/ and README.md, then writes
docs/landing/index.html + docs/landing/style.css. Stdlib only — no
jinja, no markdown library, no JS frameworks.

Usage:
    python scripts/build_landing.py            # build once
    python scripts/build_landing.py --serve    # build + serve at :8000
    python scripts/build_landing.py --watch    # rebuild on file change
"""
from __future__ import annotations

import argparse
import html
import http.server
import os
import re
import socketserver
import sys
import time
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
RELEASE_NOTES = REPO_ROOT / "docs" / "marketing" / "release-notes-v0.2.0.md"
STORYBOARD = REPO_ROOT / "docs" / "marketing" / "demo-storyboard.md"
OUT_DIR = REPO_ROOT / "docs" / "landing"
OUT_HTML = OUT_DIR / "index.html"
OUT_CSS = OUT_DIR / "style.css"

GITHUB_URL = "https://github.com/LiuZhiXiong/cursor-pointer"
SIGNUP_URL = (
    "https://github.com/LiuZhiXiong/cursor-pointer/issues/new"
    "?title=Notify+me+when+the+signed+dmg+is+available"
)
# TODO(landing): replace with the real YouTube embed URL once the demo is published.
VIDEO_EMBED_URL = ""  # e.g. "https://www.youtube.com/embed/XXXXXXXXXXX"


# ---------------------------------------------------------------------------
# Source extraction
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_bold(s: str) -> str:
    """Remove surrounding **...** if the whole string is bolded."""
    s = s.strip()
    if s.startswith("**") and s.endswith("**") and len(s) > 4:
        return s[2:-2].strip()
    return s


def extract_hero(readme: str) -> dict:
    """Pull H1 brand, the bold lede paragraph as hook, and the first bullet list.

    The README is structured as:
        # cursor-pointer          <- brand / eyebrow
        **The bridge ...**         <- hero hook (use as H1)
        Computer-use SDKs ...      <- supporting paragraph
        - bullets ...
    """
    lines = readme.splitlines()
    brand = ""
    hook = ""
    body = ""
    bullets: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not brand and line.startswith("# "):
            brand = line[2:].strip()
            i += 1
            continue
        if brand and not hook and line.strip() and not line.startswith("#"):
            # first non-empty paragraph after H1 = hook (often bold)
            buf = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("#"):
                buf.append(lines[i].strip())
                i += 1
            hook = _strip_bold(" ".join(buf))
            continue
        if brand and hook and not body and line.strip() and not line.startswith(("#", "- ")):
            buf = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "- ")):
                buf.append(lines[i].strip())
                i += 1
            body = " ".join(buf)
            continue
        if brand and hook and line.startswith("- "):
            while i < len(lines):
                cur = lines[i]
                if cur.startswith("- "):
                    bullets.append(cur[2:].strip())
                    i += 1
                elif cur.startswith("  ") and bullets:
                    bullets[-1] += " " + cur.strip()
                    i += 1
                else:
                    break
            break
        i += 1
    return {"brand": brand, "h1": hook, "lede": body, "bullets": bullets}


def extract_features(notes: str) -> list[dict]:
    """Return list of {title, body} from the '## What's new' section."""
    lines = notes.splitlines()
    features: list[dict] = []
    in_section = False
    cur_title = None
    cur_body: list[str] = []

    def flush():
        if cur_title:
            features.append({
                "title": cur_title,
                "body": "\n".join(cur_body).strip(),
            })

    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            if in_section:
                flush()
                cur_title = None
                cur_body = []
                in_section = False
            if heading.startswith("what's new") or heading.startswith("whats new"):
                in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("### "):
            flush()
            cur_title = line[4:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if in_section:
        flush()
    return features


def extract_python_example(readme: str) -> str:
    """Pull the first ```python ... ``` fenced block that contains 'outcome'."""
    pattern = re.compile(r"```python\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(readme):
        body = match.group(1)
        if "outcome" in body or "Outcome" in body:
            return body.rstrip()
    # fall back: first python block
    match = pattern.search(readme)
    return match.group(1).rstrip() if match else ""


# ---------------------------------------------------------------------------
# Markdown -> HTML (tiny subset, hand-rolled)
# ---------------------------------------------------------------------------

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def md_inline(text: str) -> str:
    """Inline markdown -> HTML, escape-safe."""
    # Escape first, then walk replacements using HTML-encoded markers
    out = html.escape(text)
    out = _LINK_RE.sub(
        lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>',
        out,
    )
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _INLINE_CODE_RE.sub(r"<code>\1</code>", out)
    return out


def md_block(body: str) -> str:
    """Convert a small markdown block into HTML paragraphs and bullet lists.

    Handles: paragraphs, '- ' bullet lists, and fenced ```code``` blocks.
    Inline markdown is processed via md_inline.
    """
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            out.append(
                "<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>"
            )
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append("<li>" + md_inline(lines[i][2:].strip()) + "</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if not line.strip():
            i += 1
            continue
        # paragraph: collect until blank
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("- ", "```")):
            buf.append(lines[i])
            i += 1
        out.append("<p>" + md_inline(" ".join(s.strip() for s in buf)) + "</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Cheap Python syntax highlighter (regex-based, no Pygments)
# ---------------------------------------------------------------------------

_PY_KEYWORDS = {
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or",
    "pass", "raise", "return", "try", "while", "with", "yield", "True",
    "False", "None",
}


def highlight_python(code: str) -> str:
    """Wrap tokens in <span class="..."> using simple lexing rules."""
    out: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        # comment to end of line
        if ch == "#":
            j = code.find("\n", i)
            j = n if j == -1 else j
            out.append(f'<span class="c">{html.escape(code[i:j])}</span>')
            i = j
            continue
        # triple or single string
        if ch in ("'", '"'):
            quote = ch
            triple = code[i:i + 3] == quote * 3
            if triple:
                end = code.find(quote * 3, i + 3)
                end = n if end == -1 else end + 3
            else:
                # walk forward respecting backslash escapes
                j = i + 1
                while j < n and code[j] != quote:
                    if code[j] == "\\" and j + 1 < n:
                        j += 2
                    else:
                        j += 1
                end = min(j + 1, n)
            out.append(f'<span class="s">{html.escape(code[i:end])}</span>')
            i = end
            continue
        # identifier / keyword
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (code[j].isalnum() or code[j] == "_"):
                j += 1
            word = code[i:j]
            if word in _PY_KEYWORDS:
                out.append(f'<span class="k">{html.escape(word)}</span>')
            elif j < n and code[j] == "(":
                out.append(f'<span class="fn">{html.escape(word)}</span>')
            else:
                out.append(html.escape(word))
            i = j
            continue
        # number
        if ch.isdigit():
            j = i
            while j < n and (code[j].isdigit() or code[j] == "."):
                j += 1
            out.append(f'<span class="n">{html.escape(code[i:j])}</span>')
            i = j
            continue
        out.append(html.escape(ch))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

def _li(items: Iterable[str]) -> str:
    return "\n".join(f"  <li>{md_inline(x)}</li>" for x in items)


def _feature_title_html(title: str) -> str:
    """Render a feature heading: support `inline code` (`x`) inside the title."""
    return md_inline(title)


def render_html(hero: dict, features: list[dict], py_example: str) -> str:
    feature_cards = "\n".join(
        f'''  <article class="card">
    <h3>{_feature_title_html(f["title"])}</h3>
    {md_block(f["body"])}
  </article>'''
        for f in features
    )

    if VIDEO_EMBED_URL:
        video_html = (
            f'<div class="video-wrap"><iframe src="{html.escape(VIDEO_EMBED_URL)}" '
            'title="cursor-pointer 90-second demo" '
            'allow="accelerator; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture" allowfullscreen></iframe></div>'
        )
    else:
        video_html = (
            '<div class="video-placeholder">'
            '<p><strong>90-second demo video</strong></p>'
            '<p class="muted">TODO: paste the YouTube embed URL into '
            '<code>VIDEO_EMBED_URL</code> in <code>scripts/build_landing.py</code> '
            'once the recording is published.</p>'
            "</div>"
        )

    highlighted = highlight_python(py_example) if py_example else ""
    example_section = ""
    if highlighted:
        example_section = f'''  <section class="section" id="example">
    <div class="container">
      <h2>30-second example</h2>
      <p class="muted">The closed-loop click &mdash; straight from the README.</p>
      <details>
        <summary>Show the Python code</summary>
        <pre class="code-py"><code>{highlighted}</code></pre>
      </details>
    </div>
  </section>'''

    plain_desc = re.sub(r"\*\*|`|\[|\]\([^)]+\)", "", hero["lede"])[:160]
    brand = hero.get("brand") or "cursor-pointer"
    page_title = f"{brand} — {hero['h1']}"
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(page_title)}</title>
  <meta name="description" content="{html.escape(plain_desc)}">
  <link rel="stylesheet" href="style.css">
</head>
<body>
<header class="hero">
  <div class="container">
    <p class="eyebrow">{html.escape(brand)}</p>
    <h1>{md_inline(hero["h1"])}</h1>
    <p class="lede">{md_inline(hero["lede"])}</p>
    <ul class="hero-bullets">
{_li(hero["bullets"])}
    </ul>
    <p class="cta-row">
      <a class="btn btn-primary" href="{html.escape(SIGNUP_URL)}">Notify me about the $49 signed .dmg</a>
      <a class="btn btn-ghost" href="{html.escape(GITHUB_URL)}">View on GitHub</a>
    </p>
  </div>
</header>

<main>
  <section class="section" id="demo">
    <div class="container">
      <h2>See it work</h2>
      <p class="muted">90 seconds. The agent opens TextEdit, types, and verifies every step.</p>
      {video_html}
    </div>
  </section>

  <section class="section section-alt" id="features">
    <div class="container">
      <h2>What&rsquo;s new in v0.2.0</h2>
      <div class="cards">
{feature_cards}
      </div>
    </div>
  </section>

{example_section}

  <section class="section section-alt" id="get-started">
    <div class="container">
      <h2>Get it</h2>
      <p>Two paths today, and a third on the way:</p>
      <div class="cards">
        <article class="card">
          <h3>Build from source</h3>
          <p>macOS 12+, Rust, Node 18, Python 3.10. 10&ndash;15 minutes cold.</p>
          <pre><code>git clone {html.escape(GITHUB_URL)}.git
cd cursor-pointer
npm install &amp;&amp; npm run dev</code></pre>
        </article>
        <article class="card">
          <h3>Signed <code>.dmg</code> &mdash; $49</h3>
          <p>Skip the toolchain. Drag-to-Applications, signed, notarized.</p>
          <p><a class="btn btn-primary" href="{html.escape(SIGNUP_URL)}">Get notified when it ships</a></p>
        </article>
        <article class="card">
          <h3>Read the source</h3>
          <p>MIT-licensed. 173 tests. Single author. macOS only.</p>
          <p><a class="btn btn-ghost" href="{html.escape(GITHUB_URL)}">github.com/LiuZhiXiong/cursor-pointer</a></p>
        </article>
      </div>
    </div>
  </section>
</main>

<footer>
  <div class="container">
    <p>MIT-licensed. Built with Tauri, axum, enigo, and xcap. <a href="{html.escape(GITHUB_URL)}">Source on GitHub</a>.</p>
  </div>
</footer>
</body>
</html>
'''


CSS = """\
/* cursor-pointer landing — dark dev-tool aesthetic, single file */
:root {
  --bg: #0b0d12;
  --bg-alt: #11141b;
  --surface: #161a23;
  --border: #232836;
  --text: #e6e8ee;
  --muted: #8a93a6;
  --accent: #7cf0a4;
  --accent-soft: rgba(124, 240, 164, 0.12);
  --code-bg: #0f1219;
  --link: #88b8ff;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
          "Helvetica Neue", Arial, sans-serif;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

.container {
  max-width: 920px;
  margin: 0 auto;
  padding: 0 24px;
}

a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

code {
  font-family: var(--mono);
  background: var(--code-bg);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.92em;
  color: #f5e7a5;
}

pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px 18px;
  overflow-x: auto;
  font-size: 0.88rem;
}

pre code {
  background: transparent;
  padding: 0;
  color: var(--text);
}

/* Hero */
.hero {
  padding: 72px 0 56px;
  background:
    radial-gradient(circle at 12% 0%, var(--accent-soft), transparent 55%),
    linear-gradient(180deg, #0d1018 0%, var(--bg) 100%);
  border-bottom: 1px solid var(--border);
}

.hero .eyebrow {
  font-family: var(--mono);
  color: var(--accent);
  letter-spacing: 0.04em;
  text-transform: lowercase;
  margin: 0 0 18px;
  font-size: 0.95rem;
}

.hero h1 {
  font-size: clamp(2rem, 4.4vw, 3.2rem);
  line-height: 1.12;
  margin: 0 0 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.hero .lede {
  font-size: 1.15rem;
  color: var(--muted);
  margin: 0 0 26px;
  max-width: 60ch;
}

.hero-bullets {
  list-style: none;
  padding: 0;
  margin: 0 0 32px;
  display: grid;
  gap: 10px;
}

.hero-bullets li {
  position: relative;
  padding-left: 24px;
  color: #cfd5e3;
}

.hero-bullets li::before {
  content: "›";
  position: absolute;
  left: 4px;
  top: 0;
  color: var(--accent);
  font-weight: 700;
}

.cta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0;
}

.btn {
  display: inline-block;
  padding: 11px 18px;
  border-radius: 7px;
  font-weight: 600;
  font-size: 0.95rem;
  border: 1px solid transparent;
  cursor: pointer;
  transition: transform 0.05s ease, background 0.15s ease;
}

.btn-primary {
  background: var(--accent);
  color: #062611;
}

.btn-primary:hover {
  background: #9ef5bd;
  text-decoration: none;
}

.btn-ghost {
  background: transparent;
  border-color: var(--border);
  color: var(--text);
}

.btn-ghost:hover {
  background: var(--surface);
  text-decoration: none;
}

/* Sections */
.section {
  padding: 56px 0;
}

.section-alt {
  background: var(--bg-alt);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.section h2 {
  font-size: 1.7rem;
  margin: 0 0 12px;
  letter-spacing: -0.005em;
}

.muted { color: var(--muted); }

/* Cards */
.cards {
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  margin-top: 24px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 22px 22px 18px;
}

.card h3 {
  margin: 0 0 10px;
  font-size: 1.1rem;
  color: var(--accent);
}

.card p, .card ul { margin: 0 0 10px; }
.card ul { padding-left: 18px; }
.card pre { font-size: 0.8rem; }

/* Video */
.video-wrap {
  position: relative;
  padding-bottom: 56.25%;
  height: 0;
  border-radius: 10px;
  overflow: hidden;
  background: #000;
  border: 1px solid var(--border);
  margin-top: 22px;
}

.video-wrap iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
}

.video-placeholder {
  border: 1px dashed var(--border);
  border-radius: 10px;
  padding: 36px 24px;
  text-align: center;
  background: var(--surface);
  margin-top: 22px;
}

/* Example details */
details {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 18px;
  margin-top: 14px;
}

details summary {
  cursor: pointer;
  color: var(--accent);
  font-weight: 600;
  list-style: none;
}

details summary::-webkit-details-marker { display: none; }
details summary::before {
  content: "▸ ";
  display: inline-block;
  width: 1em;
  transition: transform 0.15s;
}

details[open] summary::before {
  content: "▾ ";
}

details pre { margin-top: 14px; }

/* Python syntax highlighting */
.code-py .k  { color: #d18cff; }   /* keyword */
.code-py .s  { color: #b5e890; }   /* string */
.code-py .c  { color: #6e7894; font-style: italic; } /* comment */
.code-py .n  { color: #ffb673; }   /* number */
.code-py .fn { color: #88b8ff; }   /* function */

/* Footer */
footer {
  border-top: 1px solid var(--border);
  padding: 28px 0;
  color: var(--muted);
  font-size: 0.9rem;
}

/* Narrow viewport */
@media (max-width: 640px) {
  .hero { padding: 56px 0 40px; }
  .section { padding: 40px 0; }
  .cta-row { flex-direction: column; align-items: stretch; }
  .btn { text-align: center; }
}
"""


def build_once() -> None:
    readme = _read(README)
    notes = _read(RELEASE_NOTES)
    hero = extract_hero(readme)
    features = extract_features(notes)
    py_example = extract_python_example(readme)
    if not hero["h1"]:
        raise SystemExit("Could not extract H1 from README.md")
    if not features:
        raise SystemExit("Could not extract any features from release notes")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_doc = render_html(hero, features, py_example)
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    OUT_CSS.write_text(CSS, encoding="utf-8")
    print(f"wrote {OUT_HTML.relative_to(REPO_ROOT)} ({len(html_doc)} bytes)")
    print(f"wrote {OUT_CSS.relative_to(REPO_ROOT)} ({len(CSS)} bytes)")
    print(f"  features: {len(features)}  hero bullets: {len(hero['bullets'])}")


# ---------------------------------------------------------------------------
# --watch (polling) and --serve
# ---------------------------------------------------------------------------

def _watched_paths() -> list[Path]:
    paths = [README, RELEASE_NOTES, STORYBOARD, Path(__file__)]
    return [p for p in paths if p.exists()]


def watch_loop(interval: float = 1.0) -> None:
    print(f"watching {len(_watched_paths())} files; Ctrl-C to stop")
    last = {p: p.stat().st_mtime for p in _watched_paths()}
    while True:
        try:
            time.sleep(interval)
            changed = False
            for p in _watched_paths():
                mt = p.stat().st_mtime
                if last.get(p) != mt:
                    last[p] = mt
                    changed = True
            if changed:
                print("change detected — rebuilding")
                try:
                    build_once()
                except Exception as exc:  # noqa: BLE001
                    print(f"  build failed: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nstopped")
            return


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    os.chdir(OUT_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer((host, port), handler) as httpd:
        url = f"http://{host}:{port}/"
        print(f"serving {OUT_DIR.relative_to(REPO_ROOT)} at {url}")
        print("Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true",
                        help="start a local preview server on :8000")
    parser.add_argument("--watch", action="store_true",
                        help="rebuild whenever marketing sources change")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    build_once()

    if args.watch and args.serve:
        # background-thread watcher, foreground server
        import threading
        t = threading.Thread(target=watch_loop, daemon=True)
        t.start()
        serve(port=args.port)
    elif args.watch:
        watch_loop()
    elif args.serve:
        serve(port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
