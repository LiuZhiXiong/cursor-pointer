"""Smoke-test every cursor-pointer HTTP endpoint and print a pass/fail
matrix with evidence.

Usage:  python scripts/smoke_test_api.py
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

import requests

API = "http://127.0.0.1:39213"

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m·\033[0m"

results: list[tuple[str, str, str, str]] = []  # (path, status, evidence, note)


def record(path: str, status: str, evidence: str, note: str = "") -> None:
    results.append((path, status, evidence, note))


def get(path: str, **kw) -> requests.Response:
    kw.setdefault("timeout", 5)
    return requests.get(f"{API}{path}", **kw)


def post(path: str, body: Any = None) -> requests.Response:
    return requests.post(f"{API}{path}", json=body or {}, timeout=5)


# --- health ---
def t_health() -> None:
    r = get("/health")
    ok = r.status_code == 200 and r.json().get("ok") is True
    record("/health", PASS if ok else FAIL, f"{r.status_code} {r.text[:60]}")


# --- mouse ---
def t_mouse_position() -> None:
    r = get("/mouse/position")
    j = r.json()
    ok = "x" in j and "y" in j
    record("/mouse/position", PASS if ok else FAIL, f"x={j.get('x')} y={j.get('y')}")


def t_mouse_move() -> None:
    pre = get("/mouse/position").json()
    target = (300, 300)
    r = post("/mouse/move", {"x": target[0], "y": target[1]})
    time.sleep(0.15)
    post_pos = get("/mouse/position").json()
    moved = abs(post_pos["x"] - target[0]) <= 2 and abs(post_pos["y"] - target[1]) <= 2
    record("/mouse/move", PASS if moved else FAIL,
           f"{pre} → {post_pos}", "cursor reached target ±2px" if moved else "did not move")


def t_mouse_click() -> None:
    # Click somewhere safe: tucked into top-left corner of menu bar (no-op'ish).
    # We only verify the endpoint responds 200 — clicking the menu bar is
    # safe (just highlights briefly).
    r = post("/mouse/click", {"x": 5, "y": 5, "button": "left"})
    ok = r.status_code == 200 and r.json().get("ok") is True
    record("/mouse/click", PASS if ok else FAIL, f"{r.status_code} {r.text[:30]}")


def t_mouse_down_up() -> None:
    # press + release: should not drag because we don't move between
    r1 = post("/mouse/down", {"button": "left"})
    r2 = post("/mouse/up", {"button": "left"})
    ok = r1.status_code == 200 and r2.status_code == 200
    record("/mouse/down+up", PASS if ok else FAIL,
           f"down={r1.status_code} up={r2.status_code}")


def t_mouse_scroll() -> None:
    r = post("/mouse/scroll", {"dy": -1})
    ok = r.status_code == 200 and r.json().get("ok") is True
    # Note: actual scrolling depends on cursor location & focused window —
    # not testable in isolation, only verify endpoint accepts request.
    record("/mouse/scroll", PASS if ok else FAIL,
           f"{r.status_code}",
           "endpoint OK; viewport movement depends on cursor anchor")


# --- keyboard ---
def t_keyboard_type() -> None:
    # Type into… nothing. The text goes to whatever has focus. We verify
    # only the endpoint contract here.
    r = post("/keyboard/type", {"text": ""})
    ok = r.status_code == 200 and r.json().get("ok") is True
    record("/keyboard/type", PASS if ok else FAIL,
           f"{r.status_code} (empty string)")


def t_keyboard_key() -> None:
    # Press a benign key — "F19" exists on most US keyboards but is unbound.
    # If F19 isn't recognized, parse_key will error → 400/500. We accept
    # either 200 or a documented error.
    r = post("/keyboard/key", {"key": "f19"})
    ok = r.status_code in (200, 400)
    detail = r.text[:50] if r.status_code != 200 else "ok"
    record("/keyboard/key", PASS if ok else FAIL,
           f"{r.status_code} {detail}")


def t_keyboard_down_up() -> None:
    r1 = post("/keyboard/down", {"key": "shift"})
    r2 = post("/keyboard/up", {"key": "shift"})
    ok = r1.status_code == 200 and r2.status_code == 200
    record("/keyboard/down+up", PASS if ok else FAIL,
           f"down={r1.status_code} up={r2.status_code}")


# --- screen ---
def t_screen_screenshot() -> None:
    r = get("/screen/screenshot?format=png")
    ok = r.status_code == 200 and r.headers.get("content-type") == "image/png" \
         and len(r.content) > 5000
    record("/screen/screenshot?format=png", PASS if ok else FAIL,
           f"{r.status_code} {len(r.content)} bytes",
           "macOS 26 xcap may only see own app + wallpaper")


def t_screen_screenshot_json() -> None:
    r = get("/screen/screenshot")
    j = r.json()
    ok = "image" in j and j["image"].startswith("data:image/png;base64,") \
         and j.get("width", 0) > 100
    record("/screen/screenshot (json)", PASS if ok else FAIL,
           f"{j.get('width')}x{j.get('height')}")


def t_screen_screenshot_native() -> None:
    r = get("/screen/screenshot_native")
    ok = r.status_code == 200
    record("/screen/screenshot_native", PASS if ok else FAIL,
           f"{r.status_code} ({len(r.content)} bytes)")


def t_screen_monitors() -> None:
    r = get("/screen/monitors")
    mons = r.json()
    ok = isinstance(mons, list) and len(mons) >= 1 and mons[0].get("width", 0) > 0
    record("/screen/monitors", PASS if ok else FAIL,
           f"{len(mons)} monitor(s), first={mons[0].get('width')}x{mons[0].get('height')}@{mons[0].get('scale_factor')}")


# --- fx ---
def t_fx_next() -> None:
    r = get("/_fx/next?since=0")
    j = r.json()
    ok = "events" in j and isinstance(j["events"], list)
    record("/_fx/next", PASS if ok else FAIL,
           f"{len(j.get('events', []))} events queued")


# --- window control (cursor-pointer's own floating window) ---
def t_window_compact_expand() -> None:
    r1 = post("/_window/compact")
    time.sleep(0.4)
    r2 = post("/_window/expand")
    time.sleep(0.4)
    ok = r1.status_code == 200 and r2.status_code == 200
    record("/_window/compact+expand", PASS if ok else FAIL,
           f"compact={r1.status_code} expand={r2.status_code}",
           "visual: control window should resize")


def t_window_minimize() -> None:
    r = post("/_window/minimize")
    time.sleep(0.3)
    # restore by expand
    post("/_window/expand")
    ok = r.status_code == 200
    record("/_window/minimize", PASS if ok else FAIL, f"{r.status_code}")


def t_window_quit() -> None:
    record("/_window/quit", SKIP, "destructive — skipped (would kill cursor-pointer)")


# --- ocr overlay ---
def t_ocr_get() -> None:
    r = get("/ocr/boxes")
    j = r.json()
    ok = "enabled" in j and "boxes" in j
    record("/ocr/boxes (GET)", PASS if ok else FAIL,
           f"enabled={j.get('enabled')} count={len(j.get('boxes', []))}")


def t_ocr_set_clear_toggle() -> None:
    # set 2 dummy boxes
    payload = {
        "boxes": [
            {"id": 1, "x": 100, "y": 100, "w": 80, "h": 30,
             "text": "smoke-test box 1", "tier": 3},
            {"id": 2, "x": 100, "y": 140, "w": 80, "h": 30,
             "text": "smoke-test box 2", "tier": 2},
        ],
        "enable": True,
    }
    r1 = post("/ocr/boxes", payload)
    g1 = get("/ocr/boxes").json()
    set_ok = r1.status_code == 200 and g1.get("enabled") is True \
             and len(g1.get("boxes", [])) == 2
    record("/ocr/boxes (POST)", PASS if set_ok else FAIL,
           f"set 2 boxes; got {len(g1.get('boxes', []))} back enabled={g1.get('enabled')}")

    # toggle
    r2 = post("/ocr/toggle")
    g2 = get("/ocr/boxes").json()
    toggled = r2.status_code == 200 and g2.get("enabled") is False
    record("/ocr/toggle", PASS if toggled else FAIL,
           f"enabled True → {g2.get('enabled')}")

    # clear
    r3 = post("/ocr/clear")
    g3 = get("/ocr/boxes").json()
    cleared = r3.status_code == 200 and g3.get("enabled") is False \
              and len(g3.get("boxes", [])) == 0
    record("/ocr/clear", PASS if cleared else FAIL,
           f"cleared; boxes={len(g3.get('boxes', []))} enabled={g3.get('enabled')}")


def t_ocr_run() -> None:
    r = post("/ocr/run")
    ok = r.status_code == 200 and r.json().get("started") is True
    record("/ocr/run", PASS if ok else FAIL,
           f"{r.status_code} {r.text[:50]}",
           "spawns python helper — best-effort")


# --- run all ---
def main() -> int:
    print(f"🔍 smoke-testing cursor-pointer @ {API}\n")
    try:
        get("/health", timeout=2)
    except Exception as e:
        print(f"{FAIL} cursor-pointer is not reachable: {e}")
        print("  Start it first: `npm run tauri dev` from project root")
        return 1

    tests = [
        t_health,
        t_mouse_position,
        t_mouse_move,
        t_mouse_click,
        t_mouse_down_up,
        t_mouse_scroll,
        t_keyboard_type,
        t_keyboard_key,
        t_keyboard_down_up,
        t_screen_screenshot,
        t_screen_screenshot_json,
        t_screen_screenshot_native,
        t_screen_monitors,
        t_fx_next,
        t_window_compact_expand,
        t_window_minimize,
        t_window_quit,
        t_ocr_get,
        t_ocr_set_clear_toggle,
        t_ocr_run,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            record(t.__name__, FAIL, f"crash: {type(e).__name__}: {e}")

    # report
    width = max(len(p) for p, *_ in results) + 2
    print(f"{'endpoint':{width}} {'':4} evidence")
    print("─" * (width + 6 + 60))
    pass_n = fail_n = skip_n = 0
    for p, st, ev, note in results:
        line = f"{p:{width}} {st:4} {ev}"
        if note:
            line += f"   ← {note}"
        print(line)
        if "✓" in st: pass_n += 1
        elif "✗" in st: fail_n += 1
        else: skip_n += 1
    print("─" * (width + 6 + 60))
    print(f"  {pass_n} pass · {fail_n} fail · {skip_n} skip")
    return 0 if fail_n == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
