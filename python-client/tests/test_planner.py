"""Tests for the multi-step planner additions to run_agent.py."""
from __future__ import annotations

from run_agent import parse_action_with_subgoal


def test_parse_action_with_subgoal_two_lines():
    raw = "subgoal: 切换到漫游 tab\naction: click 13"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "切换到漫游 tab"
    assert act == "click 13"


def test_parse_action_with_subgoal_missing_subgoal():
    raw = "click 5"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "(unspecified)"
    assert act == "click 5"


def test_parse_action_with_subgoal_missing_action_falls_back_to_first_nonblank():
    """If `action:` prefix is absent, take the first non-blank, non-subgoal line."""
    raw = "subgoal: open settings\nclick 5"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "open settings"
    assert act == "click 5"


def test_parse_action_with_subgoal_case_insensitive():
    raw = "SUBGOAL: do stuff\nAction: click 7"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "do stuff"
    assert act == "click 7"


def test_parse_action_with_subgoal_extra_lines_tolerated():
    raw = (
        "Some commentary I shouldn't have written.\n"
        "subgoal: switch tab\n"
        "more noise\n"
        "action: click 3\n"
        "(reasoning trailing the action — drop me)"
    )
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "switch tab"
    assert act == "click 3"


# ---------------------------------------------------------------------------
# subgoal failure-counter accounting
# ---------------------------------------------------------------------------

from run_agent import update_subgoal_failure_counter


def test_failure_counter_increments_on_fail():
    new_count = update_subgoal_failure_counter(
        prev_count=2,
        prev_subgoal="X",
        new_subgoal="X",
        step_failed=True,
    )
    assert new_count == 3


def test_failure_counter_resets_on_success():
    new_count = update_subgoal_failure_counter(
        prev_count=2,
        prev_subgoal="X",
        new_subgoal="X",
        step_failed=False,
    )
    assert new_count == 0


def test_failure_counter_resets_when_subgoal_changes():
    """Switching sub-goals wipes the counter, whether or not the step failed."""
    assert update_subgoal_failure_counter(
        prev_count=2, prev_subgoal="X", new_subgoal="Y", step_failed=True,
    ) == 0
    assert update_subgoal_failure_counter(
        prev_count=2, prev_subgoal="X", new_subgoal="Y", step_failed=False,
    ) == 0


def test_failure_counter_initial_state():
    """Empty prev_subgoal (first step) behaves like a sub-goal change."""
    assert update_subgoal_failure_counter(
        prev_count=0, prev_subgoal="", new_subgoal="X", step_failed=True,
    ) == 1


# ---------------------------------------------------------------------------
# stuck-warning prompt augmentation
# ---------------------------------------------------------------------------

from run_agent import build_stuck_warning


def test_stuck_warning_empty_under_threshold():
    assert build_stuck_warning(subgoal="X", consec_fails=0) == ""
    assert build_stuck_warning(subgoal="X", consec_fails=2) == ""


def test_stuck_warning_at_threshold():
    out = build_stuck_warning(subgoal="切换 tab", consec_fails=3)
    assert "切换 tab" in out
    assert "3" in out
    assert "sub-goal" in out.lower() or "subgoal" in out.lower()


def test_stuck_warning_above_threshold():
    out = build_stuck_warning(subgoal="X", consec_fails=5)
    assert "5" in out
