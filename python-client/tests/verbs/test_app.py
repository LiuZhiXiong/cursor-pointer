from __future__ import annotations

from unittest.mock import MagicMock, patch

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.system import APP_VERB


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_app_parse_simple_name():
    assert APP_VERB.parse("app Finder") == {"name": "Finder"}


def test_app_parse_quoted_name():
    assert APP_VERB.parse('app "Google Chrome"') == {"name": "Google Chrome"}


def test_app_parse_bundle_id():
    assert APP_VERB.parse("app com.apple.finder") == {"name": "com.apple.finder"}


def test_app_parse_rejects_other():
    assert APP_VERB.parse("click 5") is None


def test_app_parse_bare_returns_empty_name():
    # Parser is lenient — bare "app" matches; handler reports the error.
    assert APP_VERB.parse("app") == {"name": ""}


def test_app_handle_empty_name_returns_error():
    out = APP_VERB.handle({"name": ""}, _ctx())
    assert out.status == "exec_error"
    assert "name" in (out.error or "").lower()


def test_app_handle_osascript_success():
    with patch("cursor_pointer.verbs.system.subprocess.run") as run:
        run.return_value = MagicMock(stdout=b"", stderr=b"")
        out = APP_VERB.handle({"name": "Finder"}, _ctx())
    assert out.status == "executed_unverified"


def test_app_handle_osascript_fail_open_fallback_success():
    import subprocess
    err = subprocess.CalledProcessError(1, "osascript")
    err.stderr = b"some error"
    with patch("cursor_pointer.verbs.system.subprocess.run") as run:
        run.side_effect = [err, MagicMock(stdout=b"", stderr=b"")]
        out = APP_VERB.handle({"name": "Foo"}, _ctx())
    assert out.status == "executed_unverified"
