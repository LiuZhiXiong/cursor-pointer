# cursor-pointer

**The bridge that lets your AI agent actually use your Mac.**

Computer-use SDKs treat the desktop as a black box. When your agent's click
silently fails — wrong pixel, stale modal, Electron app ignoring the synthetic
event — you spend hours debugging. cursor-pointer gives every action a
**structured outcome** so the agent (and you) know whether it actually worked.

- **Closed-loop click verification** — each click reports `ok` /
  `mismatch_target` / `verify_failed` / `exec_error`, with the path it took
  (`ax_press` or `pixel`) and pixel drift between perception and action.
- **AXPress on Electron apps** that ignore synthetic mouse events
  (Slack, Discord, NeteaseMusic, …).
- **Permission revocation surfaces immediately** instead of looping on
  black screenshots.
- **Declarative verb registry** — adding a new action is one file.
- 173 tests, MIT-licensed, free to try.

## What you need

| | |
| --- | --- |
| **OS** | macOS 12+ (Apple Silicon or Intel) |
| **Toolchain** | Rust (stable), Node ≥ 18, Python ≥ 3.10, Xcode Command Line Tools |
| **Permissions** | Accessibility + Screen Recording (granted on first run) |
| **Disk / time** | ~2 GB for the Rust build cache; 10–15 min cold build |

## Two ways to see it work

### 1. Watch path — 90 seconds, no install

Don't want to build? Watch the closed-loop agent open TextEdit, type, and
verify every step on a real Mac:

**[Demo video → YouTube](https://youtube.com/TODO-replace-with-real-url)** *(TODO: link once the demo recording is published)*

### 2. Build path — 10–15 minutes to your first verified click

This is a Tauri + Rust app with a Python SDK. Cold build is honest work:

```bash
git clone https://github.com/LiuZhiXiong/cursor-pointer.git
cd cursor-pointer
npm install           # ~1 min
npm run dev           # first run: 5–10 min Rust compile, then opens the panel
```

On first launch macOS will prompt for **Accessibility** and **Screen
Recording** (*System Settings → Privacy & Security*). Grant both, quit, relaunch.
Default API port is `39213` — override with `CURSOR_POINTER_PORT=...`.

Then install the Python SDK and run a click that reports its own outcome:

```bash
cd python-client
pip install -e ".[ocr]"
```

```python
from cursor_pointer import CursorPointer
from cursor_pointer.executor import ActionExecutor, build_click_intent

cp = CursorPointer()
ex = ActionExecutor(cp=cp, screenshot_fn=lambda: cp.screenshot(),
                    ax_press_fn=..., focused_ax_fn=...)

intent = build_click_intent("click 5", element_id=5,
                            elements=detect(), screenshot_png=cp.screenshot())
outcome = ex.execute(intent)

print(outcome.status, outcome.used_path)
# → ok ax_press         (button responded to accessibility action)
# → verify_failed pixel (click executed but nothing on screen changed)
# → mismatch_target none (button moved between detect and act)
```

The agent stops guessing.

### 3. Skip the build — signed `.dmg`, $49 *(coming soon)*

If your time is worth more than 15 minutes of `cargo build`, a signed,
notarized `.dmg` is on the way for **$49 one-time**. Same binary, no Rust
toolchain, no Gatekeeper warnings, drag-to-Applications and go.
**[Get notified when it ships →](https://github.com/LiuZhiXiong/cursor-pointer/issues/new?title=Notify+me+when+the+signed+dmg+is+available)** *(TODO: replace with real signup URL when landing page is live)*

## More Python SDK examples

Raw input (no verification, no agent loop) — useful for scripted automation
where you already trust the coordinates:

```python
from cursor_pointer import CursorPointer

cp = CursorPointer()
cp.click(640, 480)
cp.type_text("hello")
cp.hotkey("cmd", "a")
png = cp.screenshot()
```

End-to-end closed-loop agent (perception + intent + verify):

```bash
python tools/run_agent.py "open TextEdit and type hello"
```

The agent emits a structured outcome per step. See
[`docs/superpowers/specs/`](docs/superpowers/specs/) for the action contract
design.

---

## Architecture

```
┌───────────────────────────┐         ┌────────────────────────────┐
│ Python / AI agent         │         │  CursorPointer.app         │
│  • OCR / vision           │ HTTP    │  • floating overlay panel  │
│  • IntentBuilder          │ ──────▶ │  • axum API @ :39213       │
│  • ActionExecutor (verify)│         │  • enigo → CGEvent (input) │
│                           │ ◀────── │  • xcap (screenshot)       │
└───────────────────────────┘  JSON   └────────────────────────────┘
```

```
cursor-pointer/
├── src-tauri/          Rust backend + Tauri shell
│   └── src/
│       ├── input.rs    mouse / keyboard / scroll via enigo
│       ├── screen.rs   monitor info + PNG screenshots via xcap
│       ├── api.rs      axum HTTP server
│       └── lib.rs      Tauri entry + commands
├── src/                Floating control panel (vanilla HTML/CSS/JS)
├── python-client/      Python SDK + agent + closed-loop executor + verb registry
└── package.json        Tauri CLI scripts
```

## HTTP API (cheat sheet)

All endpoints accept/return JSON unless noted. Default base URL
`http://127.0.0.1:39213`.

| Method | Path                     | Body / Query                                                                 | Notes                              |
| ------ | ------------------------ | ---------------------------------------------------------------------------- | ---------------------------------- |
| GET    | `/health`                | —                                                                            | `{ok, version, name}`              |
| POST   | `/mouse/move`            | `{x, y}`                                                                     | Absolute coordinates (logical px)  |
| POST   | `/mouse/click`           | `{x?, y?, button?: "left"\|"right"\|"middle", count?: 1}`                   | Move-then-click if x,y given       |
| POST   | `/mouse/down` / `/up`    | `{button?}`                                                                  | Hold / release                     |
| POST   | `/mouse/scroll`          | `{dx?, dy?, x?, y?}`                                                         | Ticks; +y = down                   |
| GET    | `/mouse/position`        | —                                                                            | `{x, y}`                           |
| POST   | `/keyboard/type`         | `{text}`                                                                     | Unicode text input                 |
| POST   | `/keyboard/key`          | `{key, modifiers?: ["cmd","shift",...]}`                                     | Tap with optional combo            |
| POST   | `/keyboard/down`/`/up`   | `{key}`                                                                      | Hold / release                     |
| GET    | `/screen/monitors`       | —                                                                            | List of `{index,x,y,width,height,scale_factor,is_primary,name}` |
| GET    | `/screen/screenshot`     | `?monitor=0&format=png`                                                      | `format=png` → raw PNG; default → `{image: data-url, width, height}` |

### Keys

`enter`, `tab`, `space`, `backspace`, `delete`, `escape`, `up`, `down`,
`left`, `right`, `home`, `end`, `pageup`, `pagedown`, `shift`, `ctrl`,
`alt` / `option`, `cmd` / `meta`, `f1`…`f12`, and any single character
(`a`, `1`, `/`, …).

## Build a `.dmg`

```bash
# Apple Silicon only (fastest)
npm run build

# Universal (Intel + Apple Silicon)
rustup target add x86_64-apple-darwin                       # one-time
npx tauri build --target universal-apple-darwin
```

Artifacts land under `src-tauri/target/<triple>/release/bundle/`:

| Path | What |
| ---- | ---- |
| `…/macos/CursorPointer.app` | runnable app bundle |
| `…/dmg/CursorPointer_<version>_<arch>.dmg` | shippable disk image |

### Custom icons

The repo ships placeholder icons. To regenerate them from the included Pillow
script (or after replacing the master design):

```bash
python-client/.venv/bin/pip install pillow
python scripts/make_icon.py
```

This writes a fresh `src-tauri/icons/{32x32,128x128,128x128@2x,icon}.png` +
`icon.icns`. If you have a 1024×1024 source PNG, prefer `npx tauri icon
path/to/source.png` — it covers iOS/Android too.

### Unsigned dmg — open on another Mac

The dmg above is **not** code-signed or notarized. End-users on macOS will see
*"App can't be opened because Apple cannot check it for malicious software"*.
Three ways to bypass:

1. **Right-click → Open** in Finder, then confirm in the dialog. (One-time
   per user.)
2. CLI strip the quarantine flag:
   ```bash
   xattr -dr com.apple.quarantine /Applications/CursorPointer.app
   ```
3. Proper fix: get an Apple Developer ID, then set
   `bundle.macOS.signingIdentity` in `tauri.conf.json` plus `notarize` env
   vars (`APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`) before running
   `tauri build`.

## Permissions checklist (macOS)

1. **Accessibility** — for input simulation (enigo / CGEvent).
2. **Screen Recording** — for `/screen/screenshot` (xcap).

Both prompt on first use. If the app is already running when you toggle
permissions, **quit and relaunch**.

## License

MIT
