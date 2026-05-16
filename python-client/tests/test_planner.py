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
