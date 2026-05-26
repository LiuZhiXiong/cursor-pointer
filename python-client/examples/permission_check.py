"""Permission precheck: do macOS Accessibility + Screen Recording actually work?

What this demonstrates:
  Diagnostic-only. Takes one screenshot, runs anchors.is_permission_denied_frame
  on it (Screen Recording check), and probes AXIsProcessTrusted (Accessibility
  check). Prints a per-permission verdict and exits non-zero if anything is
  missing. Does NOT try to fix permissions — that's a user-facing System
  Settings flow.

When to read it:
  Run this as the first sanity check on a new machine. If both lines say "ok",
  the rest of cursor-pointer will work.

Prereqs:
  - macOS
  - CursorPointer daemon running on http://127.0.0.1:39213

Run:
  python examples/permission_check.py
  python examples/permission_check.py --dry-run
"""
from __future__ import annotations

import argparse
import sys

from cursor_pointer import CursorPointer
from cursor_pointer import anchors


def _check_accessibility() -> tuple[bool, str]:
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore
    except Exception as e:
        return False, f"pyobjc-framework-ApplicationServices not importable: {e}"
    return bool(AXIsProcessTrusted()), sys.executable


def _check_screen_recording(cp: CursorPointer) -> tuple[bool, str]:
    try:
        png = cp.screenshot()
    except Exception as e:
        return False, f"daemon screenshot failed: {e}"
    if anchors.is_permission_denied_frame(png):
        return False, f"frame is empty or all-black ({len(png)} bytes)"
    return True, f"captured {len(png)} bytes"


def _check_daemon(cp: CursorPointer) -> tuple[bool, str]:
    try:
        h = cp.health()
    except Exception as e:
        return False, f"unreachable: {e}"
    return bool(h.get("ok", True)), str(h)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the checks without performing them.")
    args = ap.parse_args()

    if args.dry_run:
        print("dry-run plan:")
        print("  1. CursorPointer().health()  → daemon reachable?")
        print("  2. AXIsProcessTrusted()      → Accessibility granted?")
        print("  3. cp.screenshot() + anchors.is_permission_denied_frame()")
        print("                               → Screen Recording granted?")
        print("  exit 0 if all ok, else 1")
        return 0

    cp = CursorPointer()
    results = [
        ("daemon",            _check_daemon(cp)),
        ("accessibility",     _check_accessibility()),
        ("screen_recording",  _check_screen_recording(cp)),
    ]

    all_ok = True
    for name, (ok, detail) in results:
        verdict = "ok" if ok else "FAIL"
        print(f"  {name:18s} {verdict:4s}  {detail}")
        all_ok = all_ok and ok

    if not all_ok:
        print(
            "\nFix in System Settings → Privacy & Security:\n"
            "  • Accessibility → add the Python interpreter that just printed FAIL\n"
            "  • Screen Recording → add the same interpreter\n"
            "Then re-launch your terminal and re-run this script."
        )
        return 1
    print("\nall permissions look good — cursor-pointer is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
