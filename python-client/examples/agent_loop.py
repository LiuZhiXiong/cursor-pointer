"""Generic agent loop on top of cursor-pointer + OCR Set-of-Mark.

The loop is provider-agnostic. You implement a ``decide(history, annotation)``
function that takes the screen state and returns one action. Wire it to your
LLM of choice (OpenAI, Claude, local LLaVA, …) — the host code stays the same.

Run:
    pip install -e ".[agent]"
    python examples/agent_loop.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Optional

from cursor_pointer import CursorPointer, Session
from cursor_pointer.annotate import Annotation


# ---- action types the policy can emit ----------------------------------------

@dataclass
class Click:
    element_id: int
    button: str = "left"
    count: int = 1


@dataclass
class Type:
    text: str


@dataclass
class Key:
    key: str
    modifiers: list[str] = None  # type: ignore[assignment]


@dataclass
class Scroll:
    dy: int = 0
    dx: int = 0


@dataclass
class Wait:
    seconds: float = 1.0


@dataclass
class Done:
    answer: str = ""


Action = Click | Type | Key | Scroll | Wait | Done

# ``decide`` callback signature
PolicyFn = Callable[[str, Annotation, str], Action]
"""Receives (goal, current annotation, history summary) → next action."""


# ---- agent driver ------------------------------------------------------------

def run_agent(
    goal: str,
    policy: PolicyFn,
    *,
    client: Optional[CursorPointer] = None,
    max_steps: int = 20,
    verbose: bool = True,
) -> Session:
    """Run the perceive→decide→act loop until policy emits Done."""
    cp = client or CursorPointer()
    cp.health()
    sess = Session(cp)
    sess.note(f"goal: {goal}")

    for step in range(1, max_steps + 1):
        ann = sess.annotate()
        if verbose:
            print(f"\n[step {step}] annotation {ann.id}  ({len(ann.elements)} elements)")
            print(f"  annotated image: {ann.image_path}")
            for e in ann.elements[:15]:
                print(f"    #{e.id:>3}  {e.text!r:30}  bbox={e.bbox}  score={e.score:.2f}")
            if len(ann.elements) > 15:
                print(f"    … {len(ann.elements) - 15} more")

        history = sess.history_summary(last_n=30)
        action = policy(goal, ann, history)
        if verbose:
            print(f"  → {action}")

        if isinstance(action, Click):
            sess.click_element(ann.id, action.element_id, button=action.button, count=action.count)
        elif isinstance(action, Type):
            sess.type_text(action.text)
        elif isinstance(action, Key):
            sess.key(action.key, modifiers=action.modifiers or [])
        elif isinstance(action, Scroll):
            sess.scroll(dy=action.dy, dx=action.dx)
        elif isinstance(action, Wait):
            import time
            time.sleep(action.seconds)
        elif isinstance(action, Done):
            sess.note(f"done: {action.answer}")
            if verbose:
                print(f"\nFinished after {step} step(s): {action.answer}")
            return sess
        else:
            raise TypeError(f"unknown action {action!r}")

    sess.note("aborted: max_steps reached")
    if verbose:
        print(f"\nGave up after {max_steps} steps")
    return sess


# ---- example policy: deterministic text matcher ------------------------------

def text_match_policy(target_text: str) -> PolicyFn:
    """Demo policy: find the element containing ``target_text``, click once, done.

    If not found, scroll a couple times then give up. Stateful across calls
    via closure so we don't re-click an already-clicked target.
    """
    already_clicked = {"v": False}

    def decide(goal: str, ann: Annotation, history: str) -> Action:
        if already_clicked["v"]:
            return Done(f"clicked {target_text!r}")
        el = ann.find(target_text)
        if el is None:
            if history.count("scroll") < 2:
                return Scroll(dy=6)
            return Done(f"could not find {target_text!r}")
        already_clicked["v"] = True
        return Click(element_id=el.id)

    return decide


# ---- example policy: pluggable LLM hook --------------------------------------

def llm_policy(call_model: Callable[[dict], str]) -> PolicyFn:
    """Wrap any chat-completion-style callable into a policy.

    ``call_model(payload) -> str`` should accept::

        {
          "goal": "...",
          "history": "...",
          "annotation_image": "/tmp/.../abcdef.png",
          "elements": [{"id":..,"text":..,"bbox":..}, ...]
        }

    …and return a one-line action string, one of::

        click <id>            # left click
        rclick <id>           # right click
        dclick <id>           # double click
        type "<text>"
        key <name> [+mod...]
        scroll <dy>
        done <answer>
    """
    import shlex

    def decide(goal: str, ann: Annotation, history: str) -> Action:
        payload = {
            "goal": goal,
            "history": history,
            "annotation_image": str(ann.image_path),
            "elements": [e.to_dict() for e in ann.elements],
        }
        raw = call_model(payload).strip()
        head, *rest = shlex.split(raw)
        head = head.lower()
        if head == "click":
            return Click(element_id=int(rest[0]))
        if head == "rclick":
            return Click(element_id=int(rest[0]), button="right")
        if head == "dclick":
            return Click(element_id=int(rest[0]), count=2)
        if head == "type":
            return Type(text=rest[0])
        if head == "key":
            parts = rest[0].split("+")
            return Key(key=parts[-1], modifiers=parts[:-1])
        if head == "scroll":
            return Scroll(dy=int(rest[0]))
        if head == "done":
            return Done(answer=" ".join(rest))
        raise ValueError(f"unparseable model action: {raw!r}")

    return decide


# ---- CLI demo ----------------------------------------------------------------

def _main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "find":
        print(
            "usage:\n"
            "  agent_loop.py find <text>          # text-match demo\n"
        )
        return 2
    target = sys.argv[2]
    run_agent(
        goal=f"click the element labelled {target!r}",
        policy=text_match_policy(target),
        max_steps=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
