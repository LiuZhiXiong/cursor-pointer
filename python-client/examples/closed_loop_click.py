"""Closed-loop click: detect → act → verify → report.

What this demonstrates:
  Opens TextEdit, finds its "File" menu via Accessibility detection, clicks it
  through the ActionExecutor (which picks AXPress when available, pixel
  fallback otherwise) and prints the structured Outcome — status, used_path,
  drift, elapsed_ms. This is the closed-loop contract in ~80 lines.

When to read it:
  Read this first if you want to see how cursor-pointer's perceive→act→verify
  cycle composes. The same pattern scales to any AX-driven app.

Prereqs:
  - macOS with Accessibility + Screen Recording granted to your Python interpreter
  - CursorPointer daemon running on http://127.0.0.1:39213
  - pip install -e ".[ocr]"

Run:
  python examples/closed_loop_click.py            # for real
  python examples/closed_loop_click.py --dry-run  # prints the plan only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Allow run_agent.py imports for ax_press_element + detect_elements.
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
TARGET_MENU_LABEL = "File"


def _activate_app(bundle_id: str) -> int:
    """Open the app and return its PID."""
    subprocess.run(
        ["open", "-b", bundle_id],
        check=True,
        capture_output=True,
    )
    time.sleep(1.0)
    out = subprocess.run(
        ["pgrep", "-f", bundle_id.split(".")[-1]],
        capture_output=True, text=True,
    )
    pid = int(out.stdout.strip().splitlines()[0])
    return pid


def _quit_app(bundle_id: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'tell application id "{bundle_id}" to quit'],
        capture_output=True,
    )


def _find_menu_item(elements: list[dict], label: str) -> dict | None:
    for e in elements:
        if e.get("role") == "MenuBarItem" and e.get("label") == label:
            return e
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan without acting.")
    args = ap.parse_args()

    if args.dry_run:
        print("dry-run plan:")
        print(f"  1. open {TARGET_BUNDLE}")
        print(f"  2. detect_elements → find role=MenuBarItem label={TARGET_MENU_LABEL!r}")
        print( "  3. build Intent(kind=click, target=TargetSig(...))")
        print( "  4. ActionExecutor.execute(intent)")
        print( "  5. print Outcome(status, used_path, drift, elapsed_ms)")
        print(f"  6. quit {TARGET_BUNDLE}")
        return 0

    # Lazy import — these need accessibility frameworks.
    from run_agent import (  # type: ignore
        ax_press_element,
        detect_elements,
        _focused_ax_dict,
    )

    cp = CursorPointer()
    cp.health()
    print(f"daemon up: {cp.health()}")

    pid = _activate_app(TARGET_BUNDLE)
    print(f"activated {TARGET_BUNDLE} pid={pid}")

    try:
        elements = detect_elements(pid)
        print(f"detected {len(elements)} clickable elements")

        target_el = _find_menu_item(elements, TARGET_MENU_LABEL)
        if target_el is None:
            print(f"could not find MenuBarItem {TARGET_MENU_LABEL!r}")
            return 1

        bbox = (target_el["x"], target_el["y"], target_el["w"], target_el["h"])
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
            raw_action=f"click File menu ({target_el['id']})",
        )

        executor = ActionExecutor(
            cp=cp,
            screenshot_fn=lambda: cp.screenshot(),
            ax_press_fn=ax_press_element,
            focused_ax_fn=_focused_ax_dict,
            detect_elements_fn=lambda: detect_elements(pid),
        )

        outcome = executor.execute(intent)

        drift = "n/a" if outcome.relocate_drift_px is None else f"{outcome.relocate_drift_px}px"
        print(
            f"status={outcome.status} path={outcome.used_path} "
            f"drift={drift} elapsed={outcome.elapsed_ms}ms"
        )
        if outcome.error:
            print(f"error: {outcome.error}")

        # Dismiss the open menu so the app isn't left in a weird state.
        cp.key("escape")
        return 0 if outcome.status == "ok" else 1
    finally:
        _quit_app(TARGET_BUNDLE)


if __name__ == "__main__":
    raise SystemExit(main())
