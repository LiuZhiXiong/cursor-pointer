"""Tests for verify_done helper logic in run_agent.py."""
from __future__ import annotations

from run_agent import parse_verdict


def test_parse_verdict_ok():
    raw = """verdict: ok
why: 网易云左侧栏「漫游」已高亮"""
    verdict, why = parse_verdict(raw)
    assert verdict == "ok"
    assert "漫游" in why


def test_parse_verdict_reject():
    raw = """verdict: reject
why: 当前仍在推荐页，左栏「漫游」未高亮"""
    verdict, why = parse_verdict(raw)
    assert verdict == "reject"
    assert "推荐" in why


def test_parse_verdict_garbage_defaults_reject():
    """If the reviewer output is unparseable, default to reject (fail-safe)."""
    for raw in ["", "???", "ok cool", "yes"]:
        verdict, _ = parse_verdict(raw)
        assert verdict == "reject", f"garbage {raw!r} should be reject"


def test_parse_verdict_case_insensitive():
    raw = """VERDICT: OK
WHY: looks good"""
    verdict, _ = parse_verdict(raw)
    assert verdict == "ok"


def test_parse_verdict_extra_whitespace():
    raw = "  verdict:   ok  \n  why:   yep  "
    verdict, why = parse_verdict(raw)
    assert verdict == "ok"
    assert why == "yep"


# -----------------------------------------------------------------------
# verify_done — orchestration tests (all I/O stubbed)
# -----------------------------------------------------------------------

from pathlib import Path
from unittest.mock import patch


def _stub_pipeline():
    """Patch the four I/O dependencies of verify_done.

    Returns the patchers (already started). Caller must stop them.
    """
    p_shot = patch("run_agent.trigger_system_screenshot",
                   return_value=Path("/tmp/fake_shot.png"))
    p_detect = patch("run_agent.detect_elements", return_value=[
        {"id": 1, "x": 100, "y": 200, "w": 30, "h": 20,
         "role": "StaticText", "label": "漫游",
         "parent_label": "", "parent_bbox": None,
         "ax_ref": None, "parent_ax_ref": None},
    ])
    p_monitors = patch("run_agent.requests.get")
    p_annotate = patch("run_agent.annotate",
                       return_value=Path("/tmp/fake_shot.review.png"))
    p_shot.start()
    p_detect.start()
    m_monitors = p_monitors.start()
    p_annotate.start()
    m_monitors.return_value.json.return_value = [{"scale_factor": 2.0}]
    return [p_shot, p_detect, p_monitors, p_annotate]


def _stop_patchers(patchers):
    for p in patchers:
        p.stop()


def test_verify_done_ok():
    from run_agent import verify_done
    patchers = _stub_pipeline()
    try:
        def fake_minimax(_img, _prompt):
            return "verdict: ok\nwhy: 漫游 tab 已激活"
        verdict, why = verify_done(
            goal="切到漫游 tab",
            done_reason="已经切到漫游",
            target_pid=1234,
            ask_minimax=fake_minimax,
        )
        assert verdict == "ok"
        assert "漫游" in why
    finally:
        _stop_patchers(patchers)


def test_verify_done_reject_when_reviewer_says_no():
    from run_agent import verify_done
    patchers = _stub_pipeline()
    try:
        def fake_minimax(_img, _prompt):
            return "verdict: reject\nwhy: 仍在推荐页"
        verdict, why = verify_done(
            goal="切到漫游 tab",
            done_reason="看到漫游",
            target_pid=1234,
            ask_minimax=fake_minimax,
        )
        assert verdict == "reject"
        assert "推荐" in why
    finally:
        _stop_patchers(patchers)


def test_verify_done_reject_on_minimax_exception():
    """If ask_minimax raises, treat as reject (fail-safe)."""
    from run_agent import verify_done
    patchers = _stub_pipeline()
    try:
        def boom(_img, _prompt):
            raise RuntimeError("mmx exploded")
        verdict, why = verify_done(
            goal="x",
            done_reason="x",
            target_pid=1234,
            ask_minimax=boom,
        )
        assert verdict == "reject"
        assert "mmx" in why or "exception" in why.lower()
    finally:
        _stop_patchers(patchers)


def test_verify_done_prompt_includes_goal_and_reason():
    """Verify the goal and done_reason are interpolated into the prompt
    the reviewer sees — that's the whole grounding mechanism."""
    from run_agent import verify_done
    patchers = _stub_pipeline()
    captured = {}
    try:
        def capture(_img, prompt):
            captured["prompt"] = prompt
            return "verdict: ok\nwhy: ok"
        verify_done(
            goal="切到「漫游」tab",
            done_reason="左栏漫游已高亮",
            target_pid=1234,
            ask_minimax=capture,
        )
        assert "切到「漫游」tab" in captured["prompt"]
        assert "左栏漫游已高亮" in captured["prompt"]
    finally:
        _stop_patchers(patchers)
