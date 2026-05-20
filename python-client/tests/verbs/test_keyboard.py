from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.keyboard import KEY_VERB, TYPE_VERB


def _ctx(executor=None):
    return VerbContext(
        cp=MagicMock(), boxes=[],
        executor=executor or MagicMock(), history=[], log=lambda _m: None,
    )


def test_type_parse_quoted():
    assert TYPE_VERB.parse('type "hello world"') == {"text": "hello world"}


def test_type_parse_unquoted():
    assert TYPE_VERB.parse("type hello") == {"text": "hello"}


def test_type_parse_rejects_empty():
    assert TYPE_VERB.parse("type") is None


def test_type_handle_delegates_to_executor():
    exec_mock = MagicMock()
    fake_outcome = MagicMock(status="ok", used_path="none",
                              relocate_drift_px=None, error=None,
                              elapsed_ms=5,
                              intent=MagicMock(raw_action='type "hi"'))
    exec_mock.execute.return_value = fake_outcome
    ctx = _ctx(executor=exec_mock)
    out = TYPE_VERB.handle({"text": "hi"}, ctx)
    exec_mock.execute.assert_called_once()
    intent_arg = exec_mock.execute.call_args.args[0]
    assert intent_arg.kind == "type"
    assert intent_arg.payload["text"] == "hi"
    assert out is fake_outcome


def test_key_parse_simple():
    assert KEY_VERB.parse("key enter") == {"key": "enter", "modifiers": []}


def test_key_parse_combo():
    assert KEY_VERB.parse("key cmd+a") == \
        {"key": "a", "modifiers": ["cmd"]}


def test_key_parse_default_enter():
    assert KEY_VERB.parse("key") == {"key": "enter", "modifiers": []}


def test_key_handle_calls_cp_key():
    ctx = _ctx()
    out = KEY_VERB.handle({"key": "a", "modifiers": ["cmd"]}, ctx)
    ctx.cp.key.assert_called_once_with("a", modifiers=["cmd"])
    assert out.status == "executed_unverified"
