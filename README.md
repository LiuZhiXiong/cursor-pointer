# CursorPointer

A macOS desktop control surface for AI agents.

A small floating Tauri app runs in the corner of your screen and exposes a
localhost HTTP API. Python (or anything that speaks HTTP) can call it to move
the cursor, click, scroll, type, press keys, and grab screenshots. Pair it
with OCR / a vision model on the Python side and you have a complete
agentic computer-use loop.

```
┌───────────────────────────┐         ┌────────────────────────────┐
│ Python / AI agent         │         │  CursorPointer.app         │
│  • OCR / vision           │ HTTP    │  • floating overlay panel  │
│  • element-tree builder   │ ──────▶ │  • axum API @ :39213       │
│  • plans actions          │         │  • enigo → CGEvent (input) │
│                           │ ◀────── │  • xcap (screenshot)       │
└───────────────────────────┘  JSON   └────────────────────────────┘
```

## Layout

```
cursor-pointer/
├── src-tauri/          Rust backend + Tauri shell
│   ├── src/
│   │   ├── input.rs    mouse / keyboard / scroll via enigo
│   │   ├── screen.rs   monitor info + PNG screenshots via xcap
│   │   ├── api.rs      axum HTTP server
│   │   ├── lib.rs      Tauri entry + commands
│   │   └── main.rs
│   ├── capabilities/   Tauri 2 capability declarations
│   ├── icons/          placeholder icons (replace with your own)
│   ├── Cargo.toml
│   └── tauri.conf.json
├── src/                Floating control panel (vanilla HTML/CSS/JS)
├── python-client/      Python SDK + OCR demo
└── package.json        Tauri CLI scripts
```

## Develop

Prereqs: Rust toolchain, Node ≥ 18, Xcode Command Line Tools.

```bash
npm install
npm run dev          # tauri dev — opens the floating control panel
```

The first run will prompt for **Accessibility** and **Screen Recording**
permissions. Grant both in *System Settings → Privacy & Security*, then
restart the app.

Default API port is `39213`. Override with `CURSOR_POINTER_PORT=...`.

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

## Python SDK

See [`python-client/`](python-client/).

```python
from cursor_pointer import CursorPointer

cp = CursorPointer()
cp.click(640, 480)
cp.type_text("hello")
cp.hotkey("cmd", "a")
png = cp.screenshot()
```

End-to-end OCR demo:

```bash
cd python-client
pip install -e ".[ocr]"
python examples/ocr_click.py "Submit"
```

## Permissions checklist (macOS)

1. **Accessibility** — for input simulation (enigo / CGEvent).
2. **Screen Recording** — for `/screen/screenshot` (xcap).

Both prompt on first use. If the app is already running when you toggle
permissions, **quit and relaunch**.

## License

MIT
