"""Shared test fixtures.

`tools/` is a sibling of `tests/` — adopt the same path-insert pattern
the production code uses so test files can `from tools.run_agent import …`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `tools/` importable as a package root.
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
