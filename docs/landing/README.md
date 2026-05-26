# cursor-pointer landing page

A two-file static landing — `index.html` + `style.css` — generated from the
marketing copy we already maintain (`README.md`, `docs/marketing/`). No build
step, no dependencies, no JS.

## Regenerate

```bash
python scripts/build_landing.py
```

Re-reads:
- `README.md` (hero hook + Python example)
- `docs/marketing/release-notes-v0.2.0.md` (feature cards)

Re-writes `docs/landing/index.html` and `docs/landing/style.css` in place.
Commit the result.

## Preview locally

```bash
python scripts/build_landing.py --serve         # http://127.0.0.1:8000
python scripts/build_landing.py --serve --port 8080
```

Or rebuild on every source change:

```bash
python scripts/build_landing.py --watch         # polling, ~1s
python scripts/build_landing.py --watch --serve # both at once
```

## Deploy to GitHub Pages

1. Push the `docs/landing/` directory to `main`.
2. GitHub repo → **Settings → Pages**.
3. **Source:** Deploy from a branch.
4. **Branch:** `main` — **Folder:** `/docs/landing`.
5. Save. GitHub serves it at `https://<user>.github.io/<repo>/` within a minute.

No build action is needed — GitHub Pages serves the two files as-is.

## TODO placeholders to fill in

Edit these in `scripts/build_landing.py` and re-run the build:

- `VIDEO_EMBED_URL` — set to the YouTube `embed/<id>` URL once the 90-second
  demo is published. Currently empty → renders a placeholder card.
- `SIGNUP_URL` — currently points at a pre-filled GitHub Issue title
  ("Notify me when the signed dmg is available"). Swap for a real
  ConvertKit / Gumroad / Beehiiv URL when one exists.

After editing, run `python scripts/build_landing.py` and commit the
regenerated `index.html`.

## Conventions

- **No fabricated metrics.** Every claim on the page traces back to a line
  in `README.md` or `docs/marketing/release-notes-v0.2.0.md`. Do not edit
  `index.html` by hand to add stats — change the source markdown and
  regenerate.
- **stdlib only.** The generator has no third-party dependencies. Keep it
  that way — GitHub Pages is the deploy target, but the builder must run
  on a vanilla Python 3.10+ on a contributor's laptop without `pip install`.
- **Two files.** `index.html` + `style.css`. No JS, no images, no
  webfonts. If a future change needs more, justify it first.
