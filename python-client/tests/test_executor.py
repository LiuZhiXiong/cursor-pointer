"""Unit tests for ActionExecutor — skeleton + construction.

Uses mocks for CursorPointer + screenshot source + AX press so tests can
run without the desktop daemon or pyobjc.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image

from cursor_pointer.executor import ActionExecutor


def _png(w: int = 200, h: int = 200, color=(180, 180, 180)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_executor_constructs_with_dependencies():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)

    ex = ActionExecutor(
        cp=cp,
        screenshot_fn=screenshot_fn,
        ax_press_fn=ax_press,
        focused_ax_fn=focused_ax,
    )
    assert ex is not None
