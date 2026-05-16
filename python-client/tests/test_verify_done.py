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
