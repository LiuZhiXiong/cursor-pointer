# cursor-pointer HTTP API

Local-only HTTP service on `127.0.0.1:39213` (port set via `CURSOR_POINTER_PORT`).
Backed by [`api.rs`](../src-tauri/src/api.rs).

> **Status legend** — verified by `scripts/smoke_test_api.py` against a live
> cursor-pointer instance. Re-run that script to refresh.

| | |
|---|---|
| Pass | 20 |
| Fail | 1 (Screen Recording permission needed — see [Permissions](#permissions)) |
| Skipped (destructive) | 1 (`/_window/quit`) |

All endpoints respond with JSON unless noted. `Content-Type: application/json`
on requests. CORS allows `*` for cross-origin browser callers.

---

## Quick reference

| Method | Path | Purpose | Status |
|---|---|---|---|
| GET  | `/health`                    | health probe                        | ✓ |
| POST | `/mouse/move`                | absolute cursor move                | ✓ |
| POST | `/mouse/click`               | click (with optional move+count)    | ✓ |
| POST | `/mouse/down`                | press a mouse button (no release)   | ✓ |
| POST | `/mouse/up`                  | release a mouse button              | ✓ |
| POST | `/mouse/scroll`              | wheel scroll (cursor-anchored)      | ✓ |
| GET  | `/mouse/position`            | current cursor x,y                  | ✓ |
| POST | `/keyboard/type`             | type a Unicode string               | ✓ |
| POST | `/keyboard/key`              | press a named key (with modifiers)  | ✓ |
| POST | `/keyboard/down`             | hold a key down                     | ✓ |
| POST | `/keyboard/up`               | release a held key                  | ✓ |
| GET  | `/screen/screenshot`         | xcap screenshot (PNG / base64 JSON) | ⚠ wallpaper-only on macOS 26 |
| GET  | `/screen/screenshot_native`  | macOS `screencapture` CLI shell-out | ✗ permission-gated |
| GET  | `/screen/monitors`           | monitor list + scale factors        | ✓ |
| GET  | `/_fx/next?since=N`          | long-poll fx-event queue            | ✓ |
| POST | `/_window/minimize`          | minimize floating control window    | ✓ |
| POST | `/_window/compact`           | shrink control window to corner     | ✓ |
| POST | `/_window/expand`            | restore control window              | ✓ |
| POST | `/_window/quit`              | exit cursor-pointer (destructive)   | · skipped |
| GET  | `/ocr/boxes`                 | current overlay box state           | ✓ |
| POST | `/ocr/boxes`                 | set overlay boxes                   | ✓ |
| POST | `/ocr/clear`                 | clear overlay boxes                 | ✓ |
| POST | `/ocr/toggle`                | toggle overlay enabled bit          | ✓ |
| POST | `/ocr/run`                   | spawn bundled OCR python helper     | ✓ (best-effort) |

---

## Health

### `GET /health`
```json
{ "ok": true, "name": "cursor-pointer", "version": "0.1.0" }
```

---

## Mouse

### `POST /mouse/move`
Body: `{ "x": int, "y": int }` (logical screen px)
→ `{ "ok": true }`

### `POST /mouse/click`
Body: `{ "x"?: int, "y"?: int, "button"?: "left"|"right"|"middle", "count"?: int }`
- Omit x/y to click at current cursor position.
- `count` ≥ 2 = double/triple click. Default 1.
→ `{ "ok": true }`

The click moves the cursor to (x,y) first, spins briefly until
`NSEvent.mouseLocation()` reflects the target (max 50ms), then dispatches
the click — this avoids enigo's 1-frame stale-location bug.

### `POST /mouse/down`, `POST /mouse/up`
Body: `{ "button"?: "left"|"right"|"middle" }` (default left)
Press / release without the opposite event. Use for drag operations:
```
move → mouse_down → move → mouse_up
```

### `POST /mouse/scroll`
Body: `{ "dx"?: int, "dy"?: int, "x"?: int, "y"?: int }`
- `dy < 0` = scroll down, `dy > 0` = scroll up.
- Units are wheel ticks (~3 lines per tick on macOS).
- Optional x/y moves the cursor first (otherwise scrolls at current
  position). Wheel events are delivered to the window under the cursor —
  if you scroll without an anchor, events land on whatever window is
  topmost at the current cursor.

### `GET /mouse/position`
→ `{ "x": int, "y": int }`

---

## Keyboard

### `POST /keyboard/type`
Body: `{ "text": string }`
Types into whatever has focus.
→ `{ "ok": true }`

### `POST /keyboard/key`
Body: `{ "key": string, "modifiers"?: string[] }`
Examples:
```json
{ "key": "enter" }
{ "key": "a", "modifiers": ["cmd"] }                  // ⌘A
{ "key": "3", "modifiers": ["cmd", "shift"] }          // ⌘⇧3 = screenshot
{ "key": "escape" }
```
Key names: `enter`, `return`, `escape`, `space`, `tab`, `delete`, `backspace`,
arrow keys, `f1`-`f12`, single chars. Unknown keys return `400`:
```json
{ "error": "unknown key: f19" }
```

### `POST /keyboard/down`, `POST /keyboard/up`
Body: `{ "key": string }`
Hold / release for chorded gestures.

---

## Screen

### `GET /screen/screenshot`
Query: `?format=png` for raw bytes; otherwise JSON with base64.
- `format=png` → `Content-Type: image/png`, body = PNG bytes
- (default)    → `{ "width": int, "height": int, "image": "data:image/png;base64,…" }`

> **macOS 26 limitation**: xcap only captures windows owned by cursor-pointer
> plus the wallpaper. Third-party app windows (Chrome, iTerm, NeteaseMusic…)
> appear missing. The agent works around this by triggering `⌘⇧3` (system
> screenshot) — that goes through a different path that doesn't require
> Screen Recording permission.

### `GET /screen/screenshot_native`
Returns image bytes from `/usr/sbin/screencapture -x -C -t png`.

> **Permission-gated**: returns `500 { "error": "screencapture failed: could not create image from display" }`
> unless cursor-pointer (or the parent process spawned it) is granted Screen
> Recording in System Settings → Privacy & Security. Add the cursor-pointer
> `.app` bundle there, then restart cursor-pointer.

### `GET /screen/monitors`
→ `[ { "index": 0, "name": "...", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale_factor": 2.0 }, … ]`

---

## FX queue

### `GET /_fx/next?since=N`
Long-poll the visual-effects event ring (the overlay HTML uses this to
render click ripples / move halos / key labels).
→ `{ "events": [ { "id": int, "kind": "click"|"move"|"key", "x"?, "y"?, "button"?, "key"?, "modifiers"? }, … ] }`

`since` filters events with `id > N`. Buffer holds the last
`FX_BUFFER_MAX` events.

---

## Window control (cursor-pointer's own floating window)

| Endpoint | Effect |
|---|---|
| `POST /_window/minimize` | minimize the control window |
| `POST /_window/compact`  | shrink to 160×48 in bottom-right corner |
| `POST /_window/expand`   | restore to 320×220, unminimize, focus |
| `POST /_window/quit`     | shut down cursor-pointer (50ms delay) |

These do NOT affect other apps — only cursor-pointer's own floating widget.

---

## OCR overlay

The `/ocr/*` namespace controls the transparent always-on-top overlay that
paints numbered boxes on top of the real screen. The agent uses it to show
the user the SAME boxes the VLM is reasoning over.

### `GET /ocr/boxes`
→ `{ "enabled": bool, "boxes": [ {"id": int, "x", "y", "w", "h", "text", "score"?, "tier"?}, … ] }`

`tier` values control overlay styling:
- `1` (gold)   — all 3 sources agree (AX + OCR + visual)
- `2` (silver) — AX + OCR
- `3` (default) — AX only
- `4`          — OCR / visual only

### `POST /ocr/boxes`
Body: `{ "boxes": OcrBox[], "enable"?: bool }`
Replaces the entire box list. Overlay refreshes within ~400ms (it polls
`GET /ocr/boxes` on a 400ms tick).

### `POST /ocr/clear`
Clears boxes and sets `enabled=false`.

### `POST /ocr/toggle`
Flips `enabled` without clearing the boxes.
→ `{ "enabled": bool }`

### `POST /ocr/run`
Spawns the bundled `python-client/tools/run_ocr.py` helper, which screenshots
the screen, runs OCR, and POSTs results back to `/ocr/boxes` itself.
Hard-coded venv path: `/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/python`.
→ `{ "started": true }` (does not wait for completion)

---

## Permissions {#permissions}

cursor-pointer needs three macOS privacy grants:

| Grant | For | Where |
|---|---|---|
| **Accessibility** | reading AX tree from third-party apps (NeteaseMusic, Chrome, …) | System Settings → Privacy & Security → Accessibility |
| **Screen Recording** | `screencapture` shell-out + xcap visibility into other apps' windows | System Settings → Privacy & Security → Screen Recording |
| **Automation** (auto-prompted) | `osascript tell application … to activate` for re-focusing target apps | first time you trigger it |

If `screencapture_native` fails or `/screen/screenshot` shows only the wallpaper,
you're missing Screen Recording.

For the **agent** (`python-client/tools/run_agent.py`), the Python interpreter
itself must have Accessibility too — that's a separate grant for the binary
at `python-client/.venv/bin/python`.

---

## Common error shape

Any 4xx/5xx response:
```json
{ "error": "<message>" }
```

---

## Smoke testing

```bash
python3 scripts/smoke_test_api.py
```

Outputs a pass/fail/skip matrix with evidence (status code, response snippet,
expected behavior note). Re-runs the entire suite in ~3 seconds.
