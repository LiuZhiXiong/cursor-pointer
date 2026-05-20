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
    # Closed-loop action contract
    "ActionExecutor",
    "ExpectSig",
    "Intent",
    "Outcome",
    "TargetSig",
    # Verb registry
    "REGISTRY",
    "dispatch",
    "build_grammar_section",
    "Verb",
    "VerbContext",
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
    if name == "ActionExecutor":
        from .executor import ActionExecutor
        return ActionExecutor
    if name in {"ExpectSig", "Intent", "Outcome", "TargetSig"}:
        from . import intent as _i
        return getattr(_i, name)
    if name in {"REGISTRY", "dispatch", "build_grammar_section",
                "Verb", "VerbContext"}:
        from . import verbs as _v
        return getattr(_v, name)
    raise AttributeError(name)
