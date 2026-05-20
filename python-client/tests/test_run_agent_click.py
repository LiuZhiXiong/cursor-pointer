"""Test that the click verb in run_agent.execute() delegates to ActionExecutor."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_click_delegates_to_executor_and_records_outcome():
    import run_agent

    fake_outcome = MagicMock(status="ok", used_path="ax_press",
                              relocate_drift_px=0, error=None,
                              elapsed_ms=10)
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    boxes = [{"id": 5, "x": 100, "y": 200, "w": 80, "h": 30,
              "role": "AXButton", "label": "Send", "ax_ref": object()}]

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute("click 5", boxes)

    assert result is None  # backward-compat: success still None
    fake_executor.execute.assert_called_once()
    intent = fake_executor.execute.call_args.args[0]
    assert intent.kind == "click"
    assert intent.target.element_id == 5


def test_click_returns_error_string_on_mismatch_target():
    import run_agent

    fake_outcome = MagicMock(status="mismatch_target", used_path="none",
                              relocate_drift_px=None,
                              error="target not found",
                              elapsed_ms=5)
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    boxes = [{"id": 5, "x": 100, "y": 200, "w": 80, "h": 30,
              "role": "AXButton", "label": "Send", "ax_ref": object()}]

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute("click 5", boxes)

    assert result is not None
    assert "mismatch_target" in result or "target not found" in result
