"""Block until OCR sees a play-like element on screen, then click it once.

Usage:
    python examples/watch_and_play.py [pattern]

Default pattern matches: ▶, "play" (word), "播放", "audio", etc.
Polls every 2s, gives up after 60s. Prints what it finds along the way.
"""

from __future__ import annotations

import re
import sys
import time

from cursor_pointer import CursorPointer, Session

DEFAULT_PATTERNS = [
    r"^[▶►▷⏵]",
    r"\bplay\b",
    r"播放",
    r"audio|sample|listen|music",
]


def main() -> int:
    pats = sys.argv[1:] or DEFAULT_PATTERNS
    rxs = [re.compile(p, re.I) for p in pats]

    cp = CursorPointer()
    cp.health()
    sess = Session(cp)
    sess.note(f"watch_and_play patterns: {pats}")

    deadline = time.time() + 60
    while time.time() < deadline:
        ann = sess.annotate()
        for rx in rxs:
            for el in ann.elements:
                if rx.search(el.text):
                    print(f"\n✓ matched {rx.pattern!r} → #{el.id} {el.text!r} bbox={el.bbox}")
                    x, y = sess.click_element(ann.id, el.id)
                    print(f"  clicked logical ({x}, {y})")
                    print(f"\nsession: {sess.dir}")
                    return 0
        print(f"  {len(ann.elements)} elements, no play match — retrying in 2s")
        time.sleep(2)
    print("gave up after 60s")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
