from __future__ import annotations

from unittest.mock import MagicMock, patch

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.system import SHELL_VERB, SHELL_WHITELIST


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_shell_parse_simple():
    assert SHELL_VERB.parse("shell ls -la") == {"cmd": "ls -la"}


def test_shell_parse_rejects_empty():
    assert SHELL_VERB.parse("shell") is None


def test_shell_parse_rejects_other():
    assert SHELL_VERB.parse("click 5") is None


def test_shell_handle_whitelisted_command():
    with patch("cursor_pointer.verbs.system.subprocess.run") as run:
        run.return_value = MagicMock(stdout="hi", stderr="")
        ctx = _ctx()
        out = SHELL_VERB.handle({"cmd": "echo hi"}, ctx)
    assert out.status == "executed_unverified"
    assert any("shell" in h for h in ctx.history)


def test_shell_handle_rejects_non_whitelisted():
    out = SHELL_VERB.handle({"cmd": "rm -rf /"}, _ctx())
    assert out.status == "exec_error"
    assert "whitelist" in (out.error or "")


def test_shell_whitelist_contains_safe_readonly_commands():
    assert "ls" in SHELL_WHITELIST
    assert "echo" in SHELL_WHITELIST
