"""Test the outcome adapter that wraps legacy execute() returns."""
from __future__ import annotations


def test_adapter_none_becomes_executed_unverified():
    from run_agent import _wrap_legacy_return
    out = _wrap_legacy_return(None, action_str="scroll down")
    assert out.status == "executed_unverified"
    assert out.error is None
    assert out.intent.raw_action == "scroll down"


def test_adapter_done_sentinel_becomes_ok():
    from run_agent import _wrap_legacy_return
    out = _wrap_legacy_return("DONE", action_str="done complete")
    assert out.status == "ok"


def test_adapter_error_string_becomes_exec_error():
    from run_agent import _wrap_legacy_return
    out = _wrap_legacy_return("could not parse action: 'wat'",
                              action_str="wat")
    assert out.status == "exec_error"
    assert "could not parse" in (out.error or "")
