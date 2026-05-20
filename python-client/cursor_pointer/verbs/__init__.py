"""Verb registry — declarative dispatch.

REGISTRY is the source of truth for which verbs the agent understands.
dispatch(action_str, ctx) iterates it; first non-None parse() wins.
build_grammar_section() renders the verb-list block for SYSTEM_PROMPT.
"""
from __future__ import annotations

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# Verbs are added here one at a time as the migration progresses.
# Order matters: longer-prefix / more-specific verbs go FIRST so the
# first-match-wins dispatch can't be tricked by a shorter prefix.
from .done import DONE_VERB, WAIT_VERB
from .scroll import SCROLL_TO_VERB, SCROLL_VERB
from .mouse import DRAG_VERB
from .system import APP_VERB, CLIPBOARD_VERB, SHELL_VERB
from .browser import BROWSER_VERB
from .keyboard import KEY_VERB, TYPE_VERB
from .click import CLICK_VERB, DCLICK_VERB, RCLICK_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB,
    WAIT_VERB,
    SCROLL_TO_VERB,
    SCROLL_VERB,
    DRAG_VERB,
    APP_VERB,
    CLIPBOARD_VERB,
    SHELL_VERB,
    BROWSER_VERB,
    TYPE_VERB,
    KEY_VERB,
    DCLICK_VERB,
    RCLICK_VERB,
    CLICK_VERB,
)


def dispatch(action_str: str, ctx: VerbContext) -> Outcome:
    for verb in REGISTRY:
        args = verb.parse(action_str)
        if args is not None:
            return verb.handle(args, ctx)
    return Outcome(
        status="exec_error",
        intent=make_placeholder_intent(action_str),
        error=f"unknown action: {action_str!r}",
    )


def build_grammar_section() -> str:
    """Render the verb-grammar block for SYSTEM_PROMPT. One line per verb."""
    return "\n".join(
        f"    {v.grammar_hint}" for v in REGISTRY if v.grammar_hint
    )
