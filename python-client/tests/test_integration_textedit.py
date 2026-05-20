"""Live integration test: real cursor-pointer daemon + real TextEdit.app.

Gated by env var. Run with:

    cd python-client
    RUN_INTEGRATION=1 python -m pytest tests/test_integration_textedit.py -v -s

Prereqs:
  * cursor-pointer daemon running on default port (npm run dev)
  * Accessibility + Screen Recording permissions granted
  * TextEdit available at /System/Applications/TextEdit.app
"""
from __future__ import annotations

import os
import subprocess
import time

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live TextEdit integration test",
)


def _osascript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


@pytest.fixture
def textedit():
    _osascript('tell application "TextEdit" to activate')
    _osascript('tell application "TextEdit" to make new document')
    time.sleep(1.5)
    yield
    _osascript(
        'tell application "TextEdit" to close every document saving no'
    )
    _osascript('tell application "TextEdit" to quit')


def test_type_into_textedit_verifies_via_axvalue(textedit):
    from cursor_pointer import CursorPointer
    from cursor_pointer.executor import ActionExecutor, build_type_intent
    import run_agent

    cp = CursorPointer()
    ex = ActionExecutor(
        cp=cp,
        screenshot_fn=run_agent._current_screenshot,
        ax_press_fn=run_agent.ax_press_element,
        focused_ax_fn=run_agent._focused_ax_dict,
    )
    intent = build_type_intent(
        action_str='type "closed loop"',
        text="closed loop",
        element_id=None,
        elements=[],
        screenshot_png=run_agent._current_screenshot(),
    )
    outcome = ex.execute(intent)
    assert outcome.status == "ok", (
        f"type verify failed: {outcome.error} "
        f"(used_path={outcome.used_path})"
    )
