"""Hard verification: send API clicks at known coords, listen via CGEventTap.

We install a session-level event tap in listen-only mode, then issue clicks
through CursorPointer's HTTP API at a list of target points. For each click,
the tap reports the actual on-screen delivery coordinates as observed by the
OS event system. Requested vs caught = ground truth.

Run:
    python examples/click_delivery_test.py

Needs Accessibility permission for the Python interpreter running this
script (the *tap* requires it, separate from the cursor-pointer.app grant).
"""

from __future__ import annotations

import threading
import time

import Quartz
from CoreFoundation import (
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCFRunLoopCommonModes,
)

from cursor_pointer import CursorPointer

caught: list[tuple[float, float, int]] = []  # (x, y, type)


def tap_callback(proxy, etype, event, refcon):
    loc = Quartz.CGEventGetLocation(event)
    caught.append((loc.x, loc.y, etype))
    return event


def run_tap(stop_event: threading.Event):
    mask = (
        Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown)
    )
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        tap_callback,
        None,
    )
    if not tap:
        print("!! Failed to create event tap.")
        print("   Grant Accessibility permission to the python binary running")
        print("   this script, then re-run.")
        stop_event.set()
        return

    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    stop_event.run_loop = CFRunLoopGetCurrent()
    CFRunLoopRun()


def main() -> int:
    cp = CursorPointer()
    cp.health()
    mon = cp.monitors()[0]
    print(f"monitor {mon.width}x{mon.height} scale={mon.scale_factor}\n")

    stop = threading.Event()
    t = threading.Thread(target=run_tap, args=(stop,), daemon=True)
    t.start()
    time.sleep(0.8)
    if stop.is_set():
        return 1
    # Drop any clicks that landed before the test loop started.
    caught.clear()

    targets = [
        (100, 100, "left"),
        (1820, 100, "left"),
        (960, 540, "left"),
        (100, 980, "right"),
        (1820, 980, "right"),
        (517, 423, "left"),
        (888, 333, "left"),
        (1234, 567, "left"),
        (50, 50, "left"),
        (1870, 1030, "left"),
    ]

    print(f"{'idx':>3}  {'requested':>14}  {'caught':>14}  {'dx':>5} {'dy':>5}")
    results: list[tuple[int, int, float, float]] = []
    for i, (x, y, btn) in enumerate(targets):
        before = len(caught)
        cp.click(x, y, button=btn)
        # wait for *this* click to arrive
        deadline = time.time() + 1.5
        while len(caught) <= before and time.time() < deadline:
            time.sleep(0.02)
        if len(caught) <= before:
            print(f"{i:>3}  ({x:>5},{y:>5})  *** NOT CAUGHT ***")
            continue
        cx, cy, _ = caught[before]  # the first NEW event, not [-1]
        dx, dy = cx - x, cy - y
        print(f"{i:>3}  ({x:>5},{y:>5})  ({cx:6.1f},{cy:6.1f})  {dx:+5.1f} {dy:+5.1f}")
        results.append((x, y, cx, cy))
        # let any followup taps drain
        time.sleep(0.05)

    # stop runloop
    rl = getattr(stop, "run_loop", None)
    if rl:
        CFRunLoopStop(rl)

    if not results:
        return 2

    dxs = [c[2] - c[0] for c in results]
    dys = [c[3] - c[1] for c in results]
    mean = lambda v: sum(v) / len(v)
    print(
        f"\nsummary over {len(results)} clicks:"
        f"\n  mean dx = {mean(dxs):+.3f}   max |dx| = {max(map(abs, dxs)):.3f}"
        f"\n  mean dy = {mean(dys):+.3f}   max |dy| = {max(map(abs, dys)):.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
