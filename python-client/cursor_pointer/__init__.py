"""CursorPointer Python client SDK."""
from .client import CursorPointer, CursorPointerError, Monitor

__all__ = [
    "CursorPointer",
    "CursorPointerError",
    "Monitor",
    # Agent helpers (require the `[ocr]` extra)
    "Annotation",
    "Element",
    "Session",
    "annotate",
    "click_element",
]
__version__ = "0.1.0"


def __getattr__(name):
    # Lazy import — agent helpers depend on Pillow + RapidOCR, optional.
    if name in {"Annotation", "Element", "annotate", "click_element"}:
        from . import annotate as _a
        return getattr(_a, name)
    if name == "Session":
        from .session import Session
        return Session
    raise AttributeError(name)
