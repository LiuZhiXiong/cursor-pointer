"""Verb registry — shared base types.

Each verb is a frozen Verb dataclass: name + parse + handle + grammar hint.
Handlers receive a VerbContext giving them access to the cursor-pointer
client, the current element list, the ActionExecutor, the shared history
list, and a log function.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..intent import ExpectSig, Intent, Outcome


@dataclass(frozen=True)
class Verb:
    name: str
    parse: Callable[[str], Optional[dict]]
    handle: Callable[[dict, "VerbContext"], Outcome]
    aliases: tuple[str, ...] = ()
    grammar_hint: str = ""


@dataclass
class VerbContext:
    cp: object                          # CursorPointer — loose-typed to avoid cycle
    boxes: list[dict]
    executor: object                    # ActionExecutor — same reason
    history: list[str]
    log: Callable[[str], None]


def make_placeholder_intent(action_str: str) -> Intent:
    """Used by legacy-bodied verbs that don't build a real Intent."""
    return Intent(
        kind="click",                   # placeholder kind; legacy verbs ignore
        target=None,
        payload={},
        expect=ExpectSig(),
        raw_action=action_str,
    )
