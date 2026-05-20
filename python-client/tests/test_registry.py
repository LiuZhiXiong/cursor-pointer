"""Meta tests for the verb registry."""
from __future__ import annotations


def test_registry_imports():
    from cursor_pointer.verbs import REGISTRY, dispatch, VerbContext  # noqa: F401
    from cursor_pointer.verbs.base import Verb, make_placeholder_intent  # noqa: F401


def test_registry_is_tuple():
    from cursor_pointer.verbs import REGISTRY
    assert isinstance(REGISTRY, tuple)


def test_no_duplicate_names():
    from cursor_pointer.verbs import REGISTRY
    names = [v.name for v in REGISTRY]
    assert len(names) == len(set(names))


def test_no_duplicate_aliases():
    from cursor_pointer.verbs import REGISTRY
    seen: set[str] = set()
    for v in REGISTRY:
        for n in (v.name, *v.aliases):
            assert n not in seen, f"duplicate verb name {n!r}"
            seen.add(n)


def test_build_grammar_section_returns_string():
    from cursor_pointer.verbs import build_grammar_section
    section = build_grammar_section()
    assert isinstance(section, str)
