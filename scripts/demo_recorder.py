#!/usr/bin/env python3
"""Demo recorder — wraps `tools/run_agent.py` and emits a JSONL event stream
suitable for OBS / screen-recording overlays.

Why it exists
-------------
The agent already prints a `[STEP N] action → status path=... drift=... (Nms)`
banner per step (run_agent.py). For a clean demo video you want that data:

  1. as a structured JSON stream (so an overlay tool can render it nicely),
  2. timestamped (so the overlay can pace with the agent),
  3. tee'd to both stdout (overlay) and a .jsonl file (post-edit reference).

This script does that. It does NOT change agent behavior — it parses the
agent's existing stdout. If the agent's banner format changes, update the
PARSE regexes here.

Usage
-----
    python scripts/demo_recorder.py "open TextEdit and type hello"

    # write the JSONL to a file you can later load into your editor
    python scripts/demo_recorder.py --jsonl /tmp/demo.jsonl "open Mail"

    # also forward the raw agent log so you can inspect later
    python scripts/demo_recorder.py --raw-log /tmp/demo.txt "..."
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


# Banner produced by run_agent.py at the end of every step. We parse it
# because adding a SECOND emission point would mean keeping two formats in
# sync.
#
#   [STEP 3] click 5                                → status=ok path=ax_press drift=0px (12ms)
#   [STEP 4] type "hello"                          → status=verify_failed path=none  — value not present
_STEP_RE = re.compile(
    r"^\[STEP (?P<step>\d+)\]\s+(?P<action>.+?)\s+→\s+status=(?P<status>\S+)"
    r"(?:\s+path=(?P<path>\S+))?"
    r"(?:\s+drift=(?P<drift>\d+)px)?"
    r"(?:\s+\((?P<ms>\d+)ms\))?"
    r"(?:\s+—\s+(?P<error>.+))?$"
)

# Subgoal lines the planner prints — e.g. "  → 5. subgoal: open compose"
_SUBGOAL_RE = re.compile(r"subgoal:\s*(?P<subgoal>.+)$", re.IGNORECASE)

# "done" / "stuck" / "permission" markers worth surfacing separately.
_DONE_RE = re.compile(r"^\s*✓\s+done\s+verified")
_HALT_RE = re.compile(r"^\s*!!\s+permission denied")


def parse_line(raw: str) -> Optional[dict]:
    """Convert one stdout line into a structured event dict, or None to skip."""
    line = raw.rstrip("\n").rstrip()

    m = _STEP_RE.match(line)
    if m:
        return {
            "kind": "step",
            "step": int(m["step"]),
            "action": m["action"].strip(),
            "status": m["status"],
            "path": m["path"],
            "drift_px": int(m["drift"]) if m["drift"] else None,
            "elapsed_ms": int(m["ms"]) if m["ms"] else None,
            "error": m["error"].strip() if m["error"] else None,
        }

    m = _SUBGOAL_RE.search(line)
    if m:
        return {"kind": "subgoal", "subgoal": m["subgoal"].strip()}

    if _DONE_RE.search(line):
        return {"kind": "done", "raw": line.strip()}

    if _HALT_RE.search(line):
        return {"kind": "halt", "raw": line.strip()}

    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("goal", help="Goal string to pass to run_agent.py")
    p.add_argument("--jsonl", type=Path, default=None,
                   help="Write parsed events as JSONL to this path")
    p.add_argument("--raw-log", type=Path, default=None,
                   help="Tee the raw agent stdout to this path")
    p.add_argument("--agent",
                   default=str(Path(__file__).parent.parent / "python-client"
                               / "tools" / "run_agent.py"),
                   help="Path to run_agent.py")
    p.add_argument("--max-steps", type=int, default=None,
                   help="Forward --max-steps N to the agent")
    args = p.parse_args()

    cmd = [sys.executable, args.agent, args.goal]
    if args.max_steps is not None:
        cmd += ["--max-steps", str(args.max_steps)]

    print(f"# demo_recorder: launching {' '.join(shlex.quote(c) for c in cmd)}",
          file=sys.stderr)

    jsonl_fp = args.jsonl.open("w") if args.jsonl else None
    raw_fp = args.raw_log.open("w") if args.raw_log else None
    started_at = time.time()

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1, text=True,
        )
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            # Echo agent output so the user (and OBS scene capturing the
            # terminal) still sees the live banner.
            sys.stdout.write(raw_line)
            sys.stdout.flush()

            if raw_fp:
                raw_fp.write(raw_line)
                raw_fp.flush()

            event = parse_line(raw_line)
            if event is None:
                continue
            event["t"] = round(time.time() - started_at, 3)
            line = json.dumps(event, ensure_ascii=False)

            # Always emit JSONL on stderr so overlay tools can `tail -f` the
            # process without having to drop the user-visible stdout.
            print(line, file=sys.stderr, flush=True)
            if jsonl_fp:
                jsonl_fp.write(line + "\n")
                jsonl_fp.flush()

        return proc.wait()
    finally:
        if jsonl_fp:
            jsonl_fp.close()
        if raw_fp:
            raw_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())
