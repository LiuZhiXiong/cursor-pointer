"""Generate the full CursorPointer icon set.

Renders the master icon at 1024² using Pillow, then exports the macOS iconset
sizes (16/32/128/256/512 plus @2x) and the Tauri config sizes (32, 128, 256).
The .icns file is produced via the macOS-only `iconutil` CLI.

Run from project root:
    python scripts/make_icon.py
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src-tauri" / "icons"


def squircle_mask(size: int, radius_ratio: float = 0.225) -> Image.Image:
    """Apple-style superellipse approximation via a high-radius rounded rect."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_ratio)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    return mask


def vertical_gradient(size: int, top: tuple[int, int, int], bot: tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGB", (size, size), top)
    px = base.load()
    for y in range(size):
        t = y / (size - 1)
        # ease-in-out for nicer falloff
        t = t * t * (3 - 2 * t)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return base


def draw_pointer(size: int) -> Image.Image:
    """A classic mouse-pointer arrow centred on a transparent canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Pointer is sized as ~46% of the icon, shifted up-left of centre so the
    # tail lands near the geometric midpoint.
    s = size
    cx, cy = int(s * 0.41), int(s * 0.34)
    L = int(s * 0.48)  # spine length

    spine_w = max(2, int(s * 0.012))
    outline_w = max(3, int(s * 0.022))

    # Cursor polygon (classic 7-point arrow).
    p = [
        (cx, cy),
        (cx, cy + L),
        (cx + int(L * 0.31), cy + int(L * 0.69)),
        (cx + int(L * 0.45), cy + L),
        (cx + int(L * 0.56), cy + int(L * 0.95)),
        (cx + int(L * 0.42), cy + int(L * 0.64)),
        (cx + int(L * 0.71), cy + int(L * 0.62)),
    ]

    # Outer black outline for depth
    d.polygon(p, fill=(0, 0, 0, 220), outline=(0, 0, 0, 255))
    # Inner shrink for white fill — emulate by drawing a slightly smaller poly
    shrink = outline_w
    cx2 = cx + 1
    cy2 = cy + 1
    p2 = [
        (cx2, cy2 + shrink // 2),
        (cx2, cy2 + L - shrink),
        (cx2 + int(L * 0.30), cy2 + int(L * 0.66)),
        (cx2 + int(L * 0.42), cy2 + L - shrink + 1),
        (cx2 + int(L * 0.52), cy2 + int(L * 0.91)),
        (cx2 + int(L * 0.38), cy2 + int(L * 0.60)),
        (cx2 + int(L * 0.66), cy2 + int(L * 0.58)),
    ]
    d.polygon(p2, fill=(255, 255, 255, 255))
    return img


def draw_crosshair(size: int) -> Image.Image:
    """A faint targeting ring + ticks behind the cursor."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    R = int(size * 0.32)
    w = max(2, int(size * 0.012))
    col = (255, 255, 255, 60)

    # Outer ring
    d.ellipse((cx - R, cy - R, cx + R, cy + R), outline=col, width=w)
    # Inner small ring
    r2 = int(R * 0.4)
    d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), outline=col, width=w)
    # Crosshair ticks
    tick = int(R * 0.22)
    d.line((cx, cy - R - tick, cx, cy - R + tick), fill=col, width=w)
    d.line((cx, cy + R - tick, cx, cy + R + tick), fill=col, width=w)
    d.line((cx - R - tick, cy, cx - R + tick, cy), fill=col, width=w)
    d.line((cx + R - tick, cy, cx + R + tick, cy), fill=col, width=w)
    return img


def make_master(size: int = 1024) -> Image.Image:
    # Background gradient (deep indigo → vivid blue)
    grad = vertical_gradient(size, (88, 80, 220), (50, 130, 240))

    # Compose onto squircle
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = squircle_mask(size)
    canvas.paste(grad, (0, 0), mask)

    # Soft top highlight
    hl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    hd.ellipse(
        (-int(size * 0.2), -int(size * 0.7), int(size * 1.2), int(size * 0.3)),
        fill=(255, 255, 255, 38),
    )
    hl = hl.filter(ImageFilter.GaussianBlur(size // 60))
    hl_masked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hl_masked.paste(hl, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, hl_masked)

    # Crosshair behind pointer
    canvas = Image.alpha_composite(canvas, draw_crosshair(size))

    # Pointer with subtle drop-shadow
    pointer = draw_pointer(size)
    shadow = pointer.split()[3].point(lambda a: int(a * 0.55))
    shadow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_layer.putalpha(shadow)
    # Blur and offset shadow
    sh = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sh.paste((0, 0, 0, 200), (0, 0), shadow_layer.split()[3])
    sh = sh.filter(ImageFilter.GaussianBlur(size // 80))
    offset = (int(size * 0.012), int(size * 0.02))
    canvas.paste(sh, offset, sh)

    canvas = Image.alpha_composite(canvas, pointer)
    return canvas


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    master = make_master(1024)

    # Tauri config expects these
    pairs = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 1024,
    }
    for name, size in pairs.items():
        master.resize((size, size), Image.LANCZOS).save(OUT / name, "PNG")

    # macOS .iconset for icns
    iconset = OUT / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()
    icns_sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, size in icns_sizes:
        master.resize((size, size), Image.LANCZOS).save(iconset / name, "PNG")

    icns_out = OUT / "icon.icns"
    rc = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_out)],
        check=False,
    )
    if rc.returncode != 0:
        print("iconutil failed — skipping .icns (build will still work with PNGs).", file=sys.stderr)
        return rc.returncode
    shutil.rmtree(iconset)

    for p in sorted(OUT.iterdir()):
        st = p.stat()
        print(f"  {p.name:<22} {st.st_size:>8} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
