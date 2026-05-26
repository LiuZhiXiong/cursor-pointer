"""Drift recovery: what happens when the target moves between detect and click.

What this demonstrates:
  Detects TextEdit's "File" menu, captures a TargetSig, then *simulates*
  a 200ms delay + window shift before the click lands. The ActionExecutor
  re-locates the target inside its drift_radius_px window. The printed
  Outcome reveals one of two paths: drift > 0 with status=ok (recovery
  worked) OR status=mismatch_target (drift too large, executor refused
  to act on a moved target). Either outcome is the *correct* closed-loop
  behavior — silent miss is the bug we don't ship.

When to read it:
  Read this after closed_loop_click.py. It answers "what if the screen
  changes mid-action?" — the failure mode that breaks every open-loop
  agent.

Prereqs:
  - macOS with Accessibility + Screen Recording granted to your Python interpreter
  - CursorPointer daemon running on http://127.0.0.1:39213
  - pip install -e ".[ocr]"

Run:
  python examples/drift_recovery.py
  python examples/drift_recovery.py --dry-run
  python examples/drift_recovery.py --shift 400   # induce a bigger shift
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from cursor_pointer import (  # noqa: E402
    ActionExecutor,
    CursorPointer,
    ExpectSig,
    Intent,
    TargetSig,
)
from cursor_pointer import anchors  # noqa: E402


TARGET_BUNDLE = "com.apple.TextEdit"


def _activate_textedit_with_doc() -> int:
    # Activate + open a fresh document so there's a window we can shift.
    subprocess.run(
        ["osascript", "-e",
         'tell application "TextEdit" to activate',
         "-e", 'tell application "TextEdit" to make new document'],
        capture_output=True,
    )
    time.sleep(1.0)
    out = subprocess.run(
        ["pgrep", "-f", "TextEdit"], capture_output=True, text=True,
    )
    return int(out.stdout.strip().splitlines()[0])


def _quit_textedit() -> None:
    subprocess.run(
        ["osascript", "-e",
         'tell application "TextEdit" to close every document saving no',
         "-e", 'tell application "TextEdit" to quit'],
        capture_output=True,
    )


def _shift_window(dx: int) -> None:
    """Move the front TextEdit window horizontally by dx points."""
    script = f'''
    tell application "System Events"
        tell process "TextEdit"
            try
                set p to position of front window
                set position of front window to {{(item 1 of p) + {dx}, item 2 of p}}
            end try
        end tell
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _find_menu_item(elements: list[dict], label: str) -> dict | None:
    for e in elements:
        if e.get("role") == "MenuBarItem" and e.get("label") == label:
            return e
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan without acting.")
    ap.add_argument("--shift", type=int, default=80,
                    help="Pixels to shift the TextEdit window before clicking "
                         "(default 80; try 400 to force mismatch_target).")
    ap.add_argument("--delay-ms", type=int, default=200,
                    help="Sleep between detect and execute (default 200ms).")
    args = ap.parse_args()

    if args.dry_run:
        print("dry-run plan:")
        print(f"  1. open {TARGET_BUNDLE} + new document")
        print( "  2. detect_elements → capture TargetSig for MenuBarItem 'File'")
        print(f"  3. sleep {args.delay_ms}ms (simulate planner latency)")
        print(f"  4. shift TextEdit window by {args.shift}px (simulate drift)")
        print( "  5. executor.execute(intent) — relocate within drift radius")
        print( "  6. report Outcome: expect status=ok with drift>0, OR mismatch_target")
        print(f"  7. quit {TARGET_BUNDLE}")
        return 0

    from run_agent import (  # type: ignore
        ax_press_element,
        detect_elements,
        _focused_ax_dict,
    )

    cp = CursorPointer()
    cp.health()

    pid = _activate_textedit_with_doc()
    print(f"activated TextEdit pid={pid}")

    try:
        elements = detect_elements(pid)
        target_el = _find_menu_item(elements, "File")
        if target_el is None:
            print("could not find File menu")
            return 1

        bbox = (target_el["x"], target_el["y"], target_el["w"], target_el["h"])
        original_center = (bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2)
        screenshot = cp.screenshot()
        target = TargetSig(
            element_id=target_el["id"],
            bbox=bbox,
            role=target_el["role"],
            ocr_text=target_el["label"],
            visual_hash=anchors.average_hash_hex(screenshot, bbox=bbox),
        )
        intent = Intent(
            kind="click",
            target=target,
            expect=ExpectSig(focus_changes=True, roi_pixel_delta_min=0.02),
            raw_action="click File menu (drift test)",
        )
        print(
            f"captured target at bbox={bbox} center={original_center}; "
            f"now waiting {args.delay_ms}ms then shifting window by {args.shift}px"
        )

        # Simulate the drift window: latency + UI motion.
        time.sleep(args.delay_ms / 1000.0)
        _shift_window(args.shift)
        time.sleep(0.15)  # let AppKit commit the new geometry

        executor = ActionExecutor(
            cp=cp,
            screenshot_fn=lambda: cp.screenshot(),
            ax_press_fn=ax_press_element,
            focused_ax_fn=_focused_ax_dict,
            detect_elements_fn=lambda: detect_elements(pid),
            drift_radius_px=50,
        )

        outcome = executor.execute(intent)

        drift = "n/a" if outcome.relocate_drift_px is None else f"{outcome.relocate_drift_px}px"
        print(
            f"status={outcome.status} path={outcome.used_path} "
            f"drift={drift} elapsed={outcome.elapsed_ms}ms"
        )
        if outcome.status == "ok":
            print(f"  → drift recovery worked: target re-located within "
                  f"radius (drift={drift})")
        elif outcome.status == "mismatch_target":
            print( "  → target moved beyond drift radius — executor refused "
                   "to act on a possibly-wrong element (correct behavior)")
        if outcome.error:
            print(f"error: {outcome.error}")

        # Restore window position roughly + dismiss any open menu.
        _shift_window(-args.shift)
        cp.key("escape")
        return 0
    finally:
        _quit_textedit()


if __name__ == "__main__":
    raise SystemExit(main())
