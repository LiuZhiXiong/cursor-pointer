#!/usr/bin/env python3
"""qa_demo_smoke.py — Automated SCENARIO 1 validator for the 90s demo recording.

Scenario under test
-------------------
SCENARIO 1 from docs/marketing/demo-storyboard.md:

    TextEdit happy path
      $ python tools/run_agent.py "open a new TextEdit document and type closed loop"
      EXPECT in stdout:
        [STEP N]   click <id>   → status=ok path=ax_press ...
        [STEP N+1] type "closed loop" → status=ok path=none ...
        ✓ done verified

This script is the QA gate that runs BEFORE the human hits record on OBS.
A green run here is a necessary (not sufficient) precondition; the human
still validates scenarios 2, 3, 4 by hand using docs/qa/demo-runbooks.md.

What the script verifies
------------------------
  1. Daemon /health is reachable      (FAIL fast if `npm run dev` is down)
  2. /screen/screenshot returns 200   (proxy for Screen Recording perm)
  3. run_agent.py is launched on the fixed goal string
  4. Per-step banner is parsed using the EXACT same regex as
     scripts/demo_recorder.py (imported, not re-implemented — so when the
     banner format changes there is only one place to update)
  5. Collected banners contain:
        - at least one  click  with status=ok
        - at least one  type   with status=ok
        - a  ✓ done verified  line
     If any of those three are missing the script exits 1 with an
     explanation of which assertion failed.

Cleanup
-------
TextEdit is closed via osascript on exit, success OR failure, so the
human can re-run without manually wrangling stale windows. Cleanup is
best-effort — if osascript itself fails the script still exits with the
test's pass/fail code.

Usage
-----
    python scripts/qa_demo_smoke.py             # run the full smoke
    python scripts/qa_demo_smoke.py --help      # show options
    python scripts/qa_demo_smoke.py --dry-run   # health + perm checks only

Exit codes
----------
    0  All assertions passed; safe to proceed to the human-driven runbook.
    1  Any assertion failed (daemon down, perm denied, or banner mismatch).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
AGENT_PATH = REPO_ROOT / "python-client" / "tools" / "run_agent.py"

# Re-use the banner parser from demo_recorder.py so the QA smoke and the
# OBS overlay agree on what counts as a "step". If demo_recorder's regex
# moves, this import is the canary.
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from demo_recorder import parse_line  # type: ignore
except Exception as e:  # pragma: no cover - import-time check
    print(f"FAIL: could not import demo_recorder.parse_line: {e}",
          file=sys.stderr)
    sys.exit(1)

API = "http://127.0.0.1:39213"
DAEMON_TIMEOUT_S = 3.0
AGENT_TIMEOUT_S = 180  # generous; TextEdit launch + 2 actions usually < 30s
FIXED_GOAL = "open a new TextEdit document and type closed loop"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{GREEN}PASS{RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"{RED}FAIL{RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"{YELLOW}····{RESET}  {msg}")


# ---------------------------------------------------------------------------
# Pre-flight checks (daemon + permissions)
# ---------------------------------------------------------------------------


def check_daemon_up() -> bool:
    """GET /health and confirm {ok: true}. Returns True on success."""
    try:
        import requests  # local import so --help works without requests
    except ImportError:
        _fail("`requests` not installed in the active Python. "
              "`pip install requests` then re-run.")
        return False

    try:
        r = requests.get(f"{API}/health", timeout=DAEMON_TIMEOUT_S)
    except Exception as e:
        _fail(f"daemon not reachable at {API}/health — is `npm run dev` "
              f"running? ({e.__class__.__name__}: {e})")
        return False

    if r.status_code != 200:
        _fail(f"/health returned {r.status_code}, expected 200")
        return False
    try:
        body = r.json()
    except Exception:
        _fail(f"/health body was not JSON: {r.text[:80]!r}")
        return False
    if body.get("ok") is not True:
        _fail(f"/health returned {body!r}, expected ok=true")
        return False

    _ok(f"/health 200 ok=true")
    return True


def check_screen_permission() -> bool:
    """Hit /screen/screenshot — if Screen Recording is denied, the daemon
    returns an error/empty image. We treat any non-2xx OR a permission_denied
    body as FAIL.
    """
    try:
        import requests
    except ImportError:
        _fail("`requests` not installed")
        return False

    try:
        r = requests.get(f"{API}/screen/screenshot?format=png",
                         timeout=DAEMON_TIMEOUT_S)
    except Exception as e:
        _fail(f"/screen/screenshot request crashed: {e}")
        return False

    if r.status_code != 200:
        _fail(f"/screen/screenshot returned {r.status_code} — Screen "
              f"Recording permission likely missing. System Settings → "
              f"Privacy & Security → Screen Recording → enable for the "
              f"daemon binary.")
        return False
    # An empty body OR a body containing 'permission_denied' is also bad.
    body_preview = r.text[:200] if r.headers.get("content-type", "").startswith(
        "application/json") else f"<{len(r.content)} bytes>"
    if "permission_denied" in r.text[:500]:
        _fail(f"/screen/screenshot returned permission_denied: {body_preview}")
        return False
    if len(r.content) < 100:
        _fail(f"/screen/screenshot returned suspiciously small payload "
              f"({len(r.content)} bytes) — likely a perm issue")
        return False

    _ok(f"/screen/screenshot 200 ({len(r.content)} bytes)")
    return True


# ---------------------------------------------------------------------------
# Agent run + banner collection
# ---------------------------------------------------------------------------


def run_agent_and_collect(goal: str) -> tuple[int, list[dict], list[str]]:
    """Spawn run_agent.py, stream stdout, return (rc, parsed_events, raw_lines).

    raw_lines is captured so error messages can show the user the literal
    output, not just the parsed events.
    """
    cmd = [sys.executable, str(AGENT_PATH), goal]
    _info(f"launching: {' '.join(cmd)}")

    events: list[dict] = []
    raw_lines: list[str] = []
    start = time.time()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )
    except FileNotFoundError as e:
        _fail(f"could not launch agent: {e}")
        return 127, [], []

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            sys.stdout.write(f"{DIM}{line}{RESET}" if line.strip() else line)
            sys.stdout.flush()
            raw_lines.append(line)

            if time.time() - start > AGENT_TIMEOUT_S:
                _fail(f"agent exceeded {AGENT_TIMEOUT_S}s timeout — killing")
                proc.kill()
                break

            ev = parse_line(line)
            if ev is not None:
                events.append(ev)
        rc = proc.wait(timeout=10)
    except Exception as e:
        _fail(f"agent stream crashed: {e}")
        try:
            proc.kill()
        except Exception:
            pass
        rc = -1

    return rc, events, raw_lines


# ---------------------------------------------------------------------------
# Assertions on the collected banner stream
# ---------------------------------------------------------------------------


def assert_scenario1(events: list[dict]) -> tuple[bool, list[str]]:
    """Return (ok, failure_messages). Scenario 1 requires:
        - at least one  click  with status=ok
        - at least one  type   with status=ok
        - a  ✓ done verified  line  (parsed as kind=done)
    """
    failures: list[str] = []

    click_ok = [e for e in events
                if e.get("kind") == "step"
                and e.get("status") == "ok"
                and e.get("action", "").startswith("click")]
    type_ok = [e for e in events
               if e.get("kind") == "step"
               and e.get("status") == "ok"
               and e.get("action", "").startswith("type")]
    done = [e for e in events if e.get("kind") == "done"]

    if not click_ok:
        failures.append("expected at least one  [STEP] click ... status=ok  "
                        "banner; none found")
    if not type_ok:
        failures.append('expected at least one  [STEP] type "..." status=ok  '
                        "banner; none found")
    if not done:
        failures.append("expected a  ✓ done verified  line; none found "
                        "(agent did not self-confirm goal completion)")

    return (len(failures) == 0), failures


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_textedit() -> None:
    """Best-effort: close all TextEdit windows without saving, then quit."""
    script = (
        'tell application "TextEdit" to close every document saving no\n'
        'tell application "TextEdit" to quit'
    )
    try:
        subprocess.run(["osascript", "-e", script], timeout=5,
                       check=False, capture_output=True)
        _info("TextEdit closed (osascript cleanup)")
    except Exception as e:
        _info(f"TextEdit cleanup skipped ({e})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "QA smoke for SCENARIO 1 of the 90s demo storyboard. "
            "Verifies daemon health, screen-recording permission, and "
            "that running the agent on the fixed goal produces the "
            "click=ok + type=ok + done banners required by the storyboard."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Exit 0 = scenario 1 verified, OK to record. "
                "Exit 1 = something is wrong; fix before recording.\n"
                "Run `python scripts/qa_demo_smoke.py --dry-run` to just "
                "check daemon + perms without launching the agent."),
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Skip the agent run; only check daemon + perms")
    p.add_argument("--goal", default=FIXED_GOAL,
                   help=f"Override the goal string "
                        f"(default: {FIXED_GOAL!r})")
    p.add_argument("--no-cleanup", action="store_true",
                   help="Skip osascript TextEdit cleanup at end")
    args = p.parse_args()

    print(f"\n{'='*70}\nqa_demo_smoke — SCENARIO 1 validator\n{'='*70}")

    # --- Pre-flight ---
    if not check_daemon_up():
        return 1
    if not check_screen_permission():
        return 1

    if args.dry_run:
        print(f"\n{GREEN}dry-run OK — daemon + perms green, agent not "
              f"launched.{RESET}")
        return 0

    # --- Agent run ---
    try:
        rc, events, raw = run_agent_and_collect(args.goal)
    finally:
        if not args.no_cleanup:
            cleanup_textedit()

    # --- Assert ---
    print(f"\n{'-'*70}\nResults\n{'-'*70}")
    print(f"agent exit code: {rc}")
    print(f"events parsed:   {len(events)}")
    step_events = [e for e in events if e.get("kind") == "step"]
    print(f"  step banners:  {len(step_events)}")
    print(f"  done banners:  {sum(1 for e in events if e.get('kind') == 'done')}")
    print(f"  halt banners:  {sum(1 for e in events if e.get('kind') == 'halt')}")

    if rc not in (0, 2):
        # rc=2 is the "permission denied halt" path — still a real exit, not
        # a crash. Scenario 1 should be rc=0 though.
        _fail(f"agent exited with rc={rc} (expected 0)")

    ok, failures = assert_scenario1(events)
    if ok:
        _ok("SCENARIO 1 verified: click=ok + type=ok + done banners present")
        return 0

    print()
    for f in failures:
        _fail(f)

    # Show the last 20 raw lines so the human can see what actually happened
    # without having to scroll back through the dim block above.
    print(f"\n{DIM}--- last 20 raw agent lines ---{RESET}")
    for line in raw[-20:]:
        sys.stdout.write(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
