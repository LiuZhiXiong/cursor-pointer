"""Closed-loop click-precision test.

For each target point we:
  1. Move the cursor to a far corner (5, 5)
  2. Take a baseline screenshot
  3. Move the cursor to the target (logical px)
  4. Read back /mouse/position
  5. Take a second screenshot
  6. Diff the two — the largest changed cluster is the cursor sprite
  7. Convert measured pixel back to logical coords (÷ monitor.scale_factor)
  8. Report:  requested  →  readback  →  measured

This isolates three failure modes:
  - enigo move accuracy   (requested vs readback)
  - coordinate translation (readback vs measured logical)
  - retina scaling        (any monotonic offset across targets)
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass

from PIL import Image, ImageChops

from cursor_pointer import CursorPointer


@dataclass
class Sample:
    requested: tuple[int, int]
    readback: tuple[int, int]
    measured: tuple[float, float] | None
    delta_request_readback: tuple[int, int]
    delta_readback_measured: tuple[float, float] | None

    def fmt(self) -> str:
        rq = self.requested
        rb = self.readback
        d1 = self.delta_request_readback
        if self.measured is None:
            return f"  req={rq}  read={rb}  d(rq→rd)={d1}  measured=??"
        mx, my = self.measured
        d2 = self.delta_readback_measured
        return (
            f"  req={rq}  read={rb}  measured=({mx:6.1f},{my:6.1f})  "
            f"d(rq→rd)={d1}  d(rd→ms)=({d2[0]:+.1f},{d2[1]:+.1f})"
        )


def open_png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def cursor_pixel(baseline: Image.Image, current: Image.Image, threshold: int = 25):
    """Return (cx, cy, w, h) of the most-changed cluster in physical pixels."""
    diff = ImageChops.difference(baseline, current).convert("L")
    bbox = diff.point(lambda v: 255 if v > threshold else 0).getbbox()
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0)


def main() -> int:
    cp = CursorPointer()
    cp.health()

    monitor = cp.monitors()[0]
    scale = monitor.scale_factor or 1.0
    print(f"monitor: {monitor.width}x{monitor.height}  scale={scale}")
    print()

    # Targets across the screen, away from edges
    W, H = monitor.width, monitor.height
    targets = [
        (W // 4, H // 4),
        (W // 2, H // 2),
        (3 * W // 4, H // 4),
        (W // 4, 3 * H // 4),
        (3 * W // 4, 3 * H // 4),
        (100, 100),
        (W - 100, 100),
        (100, H - 100),
        (W - 100, H - 100),
        (500, 500),
        (517, 423),  # deliberately odd
        (888, 333),
    ]

    cp.move(5, 5)
    time.sleep(0.15)
    baseline = open_png(cp.screenshot(monitor=monitor.index))

    samples: list[Sample] = []
    for tx, ty in targets:
        cp.move(tx, ty)
        time.sleep(0.10)
        rb = cp.position()
        shot = open_png(cp.screenshot(monitor=monitor.index))
        pix = cursor_pixel(baseline, shot)
        if pix is None:
            samples.append(
                Sample(
                    requested=(tx, ty),
                    readback=rb,
                    measured=None,
                    delta_request_readback=(rb[0] - tx, rb[1] - ty),
                    delta_readback_measured=None,
                )
            )
            continue

        # The macOS arrow cursor's hotspot sits at the top-left tip of the
        # sprite. The bbox we measured covers the whole arrow shape, so the
        # *hotspot* is roughly (x0, y0) ≈ (cx - w/2, cy - h/2).
        px, py, w, h = pix
        hotspot_x = px - w / 2
        hotspot_y = py - h / 2
        ms_logical = (hotspot_x / scale, hotspot_y / scale)
        samples.append(
            Sample(
                requested=(tx, ty),
                readback=rb,
                measured=ms_logical,
                delta_request_readback=(rb[0] - tx, rb[1] - ty),
                delta_readback_measured=(
                    ms_logical[0] - rb[0],
                    ms_logical[1] - rb[1],
                ),
            )
        )

    for s in samples:
        print(s.fmt())

    # Summary
    print()
    dx_rb = [s.delta_request_readback[0] for s in samples]
    dy_rb = [s.delta_request_readback[1] for s in samples]
    print(f"requested → readback:   max |dx|={max(map(abs, dx_rb))}  max |dy|={max(map(abs, dy_rb))}")

    measured = [s for s in samples if s.measured is not None]
    if measured:
        dx_ms = [s.delta_readback_measured[0] for s in measured]
        dy_ms = [s.delta_readback_measured[1] for s in measured]
        mean = lambda xs: sum(xs) / len(xs)
        print(
            f"readback  → measured:   "
            f"mean dx={mean(dx_ms):+.2f}  mean dy={mean(dy_ms):+.2f}  "
            f"max |dx|={max(map(abs, dx_ms)):.1f}  max |dy|={max(map(abs, dy_ms)):.1f}"
        )
    print(f"\n{len(samples)} samples, {len(measured)} located in screenshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
