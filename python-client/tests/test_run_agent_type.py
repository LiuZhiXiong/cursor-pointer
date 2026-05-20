"""Test that the type verb in run_agent.execute() delegates to ActionExecutor."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_type_no_target_delegates_to_executor():
    import run_agent
    fake_outcome = MagicMock(status="ok", used_path="none",
                              relocate_drift_px=None, error=None,
                              elapsed_ms=10,
                              intent=MagicMock(raw_action='type "hello"'))
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute('type "hello"', boxes=[])

    assert result is None
    intent = fake_executor.execute.call_args.args[0]
    assert intent.kind == "type"
    assert intent.target is None
    assert intent.payload["text"] == "hello"


def test_type_verify_failed_returns_structured_error():
    import run_agent
    fake_outcome = MagicMock(status="verify_failed", used_path="none",
                              relocate_drift_px=None,
                              error="value not present",
                              elapsed_ms=5,
                              intent=MagicMock(raw_action='type "hello"'))
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute('type "hello"', boxes=[])

    assert result is not None
    assert "verify_failed" in result
