#!/usr/bin/env python3
"""qa_demo_smoke.py — pre-recording validator for the 90s demo scenarios.

Drives the four scenarios from docs/marketing/demo-storyboard.md. Scenarios
that need a human action (focus a specific app, dismiss a dialog at the
right time, revoke a permission) pause and prompt; scenarios that don't
(SCENARIO 1) run fully automated.

    python scripts/qa_demo_smoke.py                     # SCENARIO 1 (default)
    python scripts/qa_demo_smoke.py --scenario 2        # Electron AXPress
    python scripts/qa_demo_smoke.py --scenario 3        # mismatch_target
    python scripts/qa_demo_smoke.py --scenario 4 \
        --confirm-permission-test                       # permission_denied (destructive)
    python scripts/qa_demo_smoke.py --scenario all      # 1, 2, 3, then prompt for 4
    python scripts/qa_demo_smoke.py --dry-run --scenario all  # print plan, do nothing
    python scripts/qa_demo_smoke.py --help

Per-scenario PASS criteria (must hold for that scenario to be green):

    SCENARIO 1  click=ok + type=ok + ✓ done verified banners.
    SCENARIO 2  at least one banner with status=ok AND path=ax_press.
    SCENARIO 3  at least one banner with status=mismatch_target.
    SCENARIO 4  !! permission denied banner AND agent exit code 2.

All scenarios share the same pre-flight: /health 200, /screen/screenshot
returns a non-trivial payload (Screen Recording grant proxy).

The per-step banner parser (parse_line) is imported from
scripts/demo_recorder.py — do not duplicate the regex here.

Exit codes
----------
    0  All requested scenarios passed.
    1  Pre-flight failed, OR at least one scenario failed.
    2  Misuse (e.g. --scenario 4 without --confirm-permission-test).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
AGENT_PATH = REPO_ROOT / "python-client" / "tools" / "run_agent.py"

# Re-use the banner parser from demo_recorder so the QA smoke and the
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
SCENARIO1_GOAL = "open a new TextEdit document and type closed loop"
# Scenario 2 goal: chosen to be a generic "click the focused button"
# instruction. The operator focuses the specific Electron button before
# pressing enter, so the goal phrasing stays app-agnostic.
SCENARIO2_GOAL_DEFAULT = "click the currently focused button"
# Scenario 3 goal: operator picks the app+dialog. We deliberately tell
# the agent the dialog exists so it commits to a target signature; the
# operator then dismisses it during the script's short sleep so the
# signature check fails as mismatch_target.
SCENARIO3_GOAL_DEFAULT = "in the open dialog, click the Cancel button"
SCENARIO3_DISMISS_HINT_S = 2.0
# Scenario 4 goal: any goal that runs long enough for the operator to
# revoke permission mid-run. Mail is reliable; TextEdit also works.
SCENARIO4_GOAL_DEFAULT = "open Mail and click the first unread message"
SCENARIO4_REVOKE_WINDOW_S = 5.0

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{GREEN}PASS{RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"{RED}FAIL{RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"{YELLOW}····{RESET}  {msg}")


def _banner(msg: str) -> None:
    print(f"\n{'='*70}\n{msg}\n{'='*70}")


def _prompt(msg: str) -> None:
    """Block until operator presses Enter. Returns None.

    We intentionally use input() (stdlib) — no readline tricks — so this
    works in any terminal including OBS-captured ones.
    """
    try:
        input(f"\n{BOLD}{YELLOW}[OPERATOR ACTION]{RESET} {msg}\n"
              f"{DIM}Press Enter when ready (Ctrl-C to abort)…{RESET} ")
    except (KeyboardInterrupt, EOFError):
        print(f"\n{YELLOW}aborted by operator{RESET}")
        raise SystemExit(130)


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


def preflight() -> bool:
    """Daemon + Screen Recording check shared by every scenario."""
    return check_daemon_up() and check_screen_permission()


# ---------------------------------------------------------------------------
# Agent run + banner collection
# ---------------------------------------------------------------------------


def run_agent_and_collect(
    goal: str,
    *,
    pre_step_hook: Optional[Callable[[int], None]] = None,
) -> tuple[int, list[dict], list[str]]:
    """Spawn run_agent.py, stream stdout, return (rc, parsed_events, raw_lines).

    pre_step_hook(step_count_so_far) is called every time a [STEP N] banner
    is parsed. Used by SCENARIO 3 to sleep / nudge the operator at the
    right moment, and by SCENARIO 4 to surface the revoke prompt only after
    the agent is clearly running.
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
    step_count = 0
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
                if ev.get("kind") == "step":
                    step_count += 1
                    if pre_step_hook is not None:
                        try:
                            pre_step_hook(step_count)
                        except Exception as hook_err:
                            _info(f"pre_step_hook raised "
                                  f"{hook_err.__class__.__name__}: {hook_err}")
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
    """click=ok + type=ok + ✓ done verified."""
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


def assert_scenario2(events: list[dict]) -> tuple[bool, list[str]]:
    """At least one banner with status=ok AND path=ax_press."""
    ax_press = [e for e in events
                if e.get("kind") == "step"
                and e.get("status") == "ok"
                and e.get("path") == "ax_press"]
    if ax_press:
        return True, []
    return False, [
        "expected at least one  [STEP] ... status=ok path=ax_press  banner; "
        "none found. Either the target button wasn't AX-accessible, or the "
        "daemon picked a different path (cgevent/pixel). See "
        "docs/qa/demo-runbooks.md SCENARIO 2 fallback list."
    ]


def assert_scenario3(events: list[dict]) -> tuple[bool, list[str]]:
    """At least one step with status=mismatch_target."""
    mismatch = [e for e in events
                if e.get("kind") == "step"
                and e.get("status") == "mismatch_target"]
    if mismatch:
        return True, []
    return False, [
        "expected at least one  [STEP] ... status=mismatch_target  banner; "
        "none found. Most common cause: dialog dismissed too late (the click "
        "fired before the signature check). Retry with the dialog closing "
        "earlier in the perceive→execute window."
    ]


def assert_scenario4(events: list[dict], rc: int) -> tuple[bool, list[str]]:
    """!! permission denied banner AND agent exit code 2."""
    failures: list[str] = []
    halt = [e for e in events if e.get("kind") == "halt"]
    if not halt:
        failures.append(
            "expected a  !! permission denied  banner; none found. Either "
            "permission was never revoked, or the daemon swallowed the error."
        )
    if rc != 2:
        failures.append(
            f"expected agent exit code 2 (permission_denied halt); got rc={rc}."
        )
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
# Per-scenario drivers
# ---------------------------------------------------------------------------


def _print_event_summary(events: list[dict], rc: int) -> None:
    print(f"\n{'-'*70}\nResults\n{'-'*70}")
    print(f"agent exit code: {rc}")
    print(f"events parsed:   {len(events)}")
    step_events = [e for e in events if e.get("kind") == "step"]
    print(f"  step banners:  {len(step_events)}")
    print(f"  done banners:  {sum(1 for e in events if e.get('kind') == 'done')}")
    print(f"  halt banners:  {sum(1 for e in events if e.get('kind') == 'halt')}")


def _show_tail(raw: list[str], n: int = 20) -> None:
    print(f"\n{DIM}--- last {n} raw agent lines ---{RESET}")
    for line in raw[-n:]:
        sys.stdout.write(line)


def run_scenario1(args: argparse.Namespace) -> bool:
    _banner("SCENARIO 1 — TextEdit happy path (fully automated)")
    if args.dry_run:
        print(f"{DIM}[dry-run] would run: {SCENARIO1_GOAL!r}{RESET}")
        print(f"{DIM}[dry-run] PASS criteria: click=ok + type=ok + done{RESET}")
        return True

    try:
        rc, events, raw = run_agent_and_collect(args.goal or SCENARIO1_GOAL)
    finally:
        if not args.no_cleanup:
            cleanup_textedit()

    _print_event_summary(events, rc)
    if rc not in (0, 2):
        _fail(f"agent exited with rc={rc} (expected 0)")

    ok, failures = assert_scenario1(events)
    if ok:
        _ok("SCENARIO 1 verified: click=ok + type=ok + done banners present")
        return True
    print()
    for f in failures:
        _fail(f)
    _show_tail(raw)
    return False


def run_scenario2(args: argparse.Namespace) -> bool:
    _banner("SCENARIO 2 — Electron AXPress beat (human-in-the-loop)")
    if args.dry_run:
        print(f"{DIM}[dry-run] would prompt operator to focus an Electron "
              f"button, then run: {SCENARIO2_GOAL_DEFAULT!r}{RESET}")
        print(f"{DIM}[dry-run] PASS criteria: status=ok AND path=ax_press"
              f"{RESET}")
        return True

    _prompt(
        "Open Slack / Discord / NeteaseMusic / VS Code, focus a sidebar "
        "button (e.g. Slack's 'New message' pencil, VS Code's Source "
        "Control icon, NeteaseMusic play/pause). Make the button clearly "
        "visible — not behind another window."
    )

    goal = args.goal or SCENARIO2_GOAL_DEFAULT
    rc, events, raw = run_agent_and_collect(goal)
    _print_event_summary(events, rc)

    ok, failures = assert_scenario2(events)
    if ok:
        _ok("SCENARIO 2 verified: status=ok path=ax_press banner present")
        return True
    print()
    for f in failures:
        _fail(f)
    _show_tail(raw)
    return False


def run_scenario3(args: argparse.Namespace) -> bool:
    _banner("SCENARIO 3 — mismatch_target on stale UI (human-in-the-loop)")
    if args.dry_run:
        print(f"{DIM}[dry-run] would prompt operator to open a dialog, run "
              f"{SCENARIO3_GOAL_DEFAULT!r}, and instruct them to dismiss "
              f"the dialog within ~{SCENARIO3_DISMISS_HINT_S}s of the first "
              f"step banner.{RESET}")
        print(f"{DIM}[dry-run] PASS criteria: any step with "
              f"status=mismatch_target{RESET}")
        return True

    _prompt(
        "Open a dialog in any app (TextEdit: File → Open…, or a System "
        "Settings sheet). Leave it OPEN and on top. The agent will start "
        f"shortly. As soon as you see the FIRST [STEP N] banner scroll past, "
        f"press Esc (or click outside the dialog) within "
        f"~{SCENARIO3_DISMISS_HINT_S}s to dismiss it."
    )

    hint_fired = {"value": False}

    def hint_on_first_step(step_count: int) -> None:
        if step_count == 1 and not hint_fired["value"]:
            hint_fired["value"] = True
            print(f"\n{BOLD}{YELLOW}>>> DISMISS THE DIALOG NOW "
                  f"(within ~{SCENARIO3_DISMISS_HINT_S}s) <<<{RESET}\n")

    goal = args.goal or SCENARIO3_GOAL_DEFAULT
    rc, events, raw = run_agent_and_collect(
        goal, pre_step_hook=hint_on_first_step
    )
    _print_event_summary(events, rc)

    ok, failures = assert_scenario3(events)
    if ok:
        _ok("SCENARIO 3 verified: mismatch_target banner present")
        return True
    print()
    for f in failures:
        _fail(f)
    _show_tail(raw)
    return False


def run_scenario4(args: argparse.Namespace) -> bool:
    _banner("SCENARIO 4 — permission_denied (DESTRUCTIVE)")

    # Dry-run prints the plan unconditionally — that's the point of dry-run.
    # The destructive-action gate only applies to real runs.
    if args.dry_run:
        print(f"{DIM}[dry-run] would require --confirm-permission-test "
              f"(currently {'set' if args.confirm_permission_test else 'NOT set'}).{RESET}")
        print(f"{DIM}[dry-run] would prompt operator to revoke Screen "
              f"Recording within ~{SCENARIO4_REVOKE_WINDOW_S}s of agent "
              f"start, running goal: {SCENARIO4_GOAL_DEFAULT!r}{RESET}")
        print(f"{DIM}[dry-run] PASS criteria: !! permission denied banner "
              f"AND rc==2{RESET}")
        return True

    if not args.confirm_permission_test:
        print(
            f"{RED}{BOLD}REFUSING TO RUN SCENARIO 4 without "
            f"--confirm-permission-test.{RESET}\n\n"
            f"This scenario requires you to REVOKE Screen Recording for the\n"
            f"daemon mid-run. After it finishes, the daemon will have no\n"
            f"Screen Recording permission and every subsequent agent run\n"
            f"will fail until you re-grant via System Settings → Privacy &\n"
            f"Security → Screen Recording → toggle daemon back on AND\n"
            f"restart `npm run dev`.\n\n"
            f"Re-run with:\n"
            f"  python scripts/qa_demo_smoke.py --scenario 4 "
            f"--confirm-permission-test\n"
        )
        return False

    print(f"\n{RED}{BOLD}"
          f"┌────────────────────────────────────────────────────────────┐\n"
          f"│  WARNING: this scenario will BREAK Screen Recording perm.  │\n"
          f"│  You will have to re-grant it before any further runs.     │\n"
          f"│  See docs/qa/demo-runbooks.md → Re-grant checklist.        │\n"
          f"└────────────────────────────────────────────────────────────┘"
          f"{RESET}")

    _prompt(
        "Pre-open System Settings → Privacy & Security → Screen Recording, "
        "with the daemon row visible and the toggle one click away. "
        f"After you press Enter, the agent will start. Within ~"
        f"{SCENARIO4_REVOKE_WINDOW_S}s (or after 2-3 step banners), toggle "
        "Screen Recording OFF for the daemon."
    )

    goal = args.goal or SCENARIO4_GOAL_DEFAULT
    rc, events, raw = run_agent_and_collect(goal)
    _print_event_summary(events, rc)

    ok, failures = assert_scenario4(events, rc)

    # Always remind the operator, pass or fail — permission is broken either way.
    print(f"\n{YELLOW}{BOLD}*** RE-GRANT REMINDER ***{RESET}")
    print(f"{YELLOW}Screen Recording is now revoked for the daemon.{RESET}")
    print(f"{YELLOW}  1. System Settings → Privacy & Security → "
          f"Screen Recording → toggle daemon ON.{RESET}")
    print(f"{YELLOW}  2. Stop `npm run dev` (Ctrl-C) and restart it — "
          f"macOS caches the previous decision until daemon relaunch.{RESET}")
    print(f"{YELLOW}  3. Run `python scripts/qa_demo_smoke.py --dry-run` "
          f"to confirm.{RESET}")

    if ok:
        _ok("SCENARIO 4 verified: permission_denied halt + rc=2")
        return True
    print()
    for f in failures:
        _fail(f)
    _show_tail(raw)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


SCENARIO_RUNNERS = {
    "1": run_scenario1,
    "2": run_scenario2,
    "3": run_scenario3,
    "4": run_scenario4,
}


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"\n{BOLD}{YELLOW}{prompt}{RESET} [y/N] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    return ans in ("y", "yes")


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "QA smoke for the 90s demo storyboard scenarios. "
            "Verifies daemon health, Screen Recording permission, and "
            "the per-scenario success banners required by the storyboard."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Scenarios:\n"
            "  1     TextEdit happy path (fully automated)\n"
            "  2     Electron AXPress beat (operator focuses a button)\n"
            "  3     mismatch_target on stale UI (operator dismisses dialog)\n"
            "  4     permission_denied mid-run (DESTRUCTIVE — needs "
            "--confirm-permission-test)\n"
            "  all   1, then 2, then 3, then confirm before 4\n"
            "\n"
            "Default is scenario 1 for back-compat with the original script."
        ),
    )
    p.add_argument("--scenario",
                   choices=["1", "2", "3", "4", "all"],
                   default="1",
                   help="Which scenario(s) to run (default: 1)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what each scenario would do; do not launch the "
                        "agent and do not prompt for operator action")
    p.add_argument("--goal", default=None,
                   help="Override the goal string for the chosen scenario "
                        "(ignored when --scenario all). For SCENARIO 1 the "
                        f"default is {SCENARIO1_GOAL!r}.")
    p.add_argument("--no-cleanup", action="store_true",
                   help="Skip osascript TextEdit cleanup after SCENARIO 1")
    p.add_argument("--confirm-permission-test", action="store_true",
                   help="Required to actually run SCENARIO 4. Without it, "
                        "scenario 4 refuses to start and explains why.")
    args = p.parse_args()

    _banner(f"qa_demo_smoke — scenario={args.scenario}"
            f"{'  [dry-run]' if args.dry_run else ''}")

    # --- Early destructive-action gate ---
    # If the operator asked for scenario 4 (alone, not in --scenario all)
    # without the safety flag, refuse BEFORE the pre-flight network check.
    # Otherwise a dead daemon would mask the more important "you didn't
    # confirm the destructive action" message.
    if (args.scenario == "4"
            and not args.confirm_permission_test
            and not args.dry_run):
        run_scenario4(args)
        return 1

    # --- Pre-flight (skipped in dry-run so the plan still prints when the
    # daemon is down). For real runs we always check /health + /screen so
    # the operator catches a dead daemon BEFORE they go set up an Electron
    # app or a dialog. In dry-run the whole point is "tell me what you'd
    # do" — failing here would defeat that.
    if args.dry_run:
        _info("dry-run: skipping daemon/permission pre-flight")
    elif not preflight():
        return 1

    # --- Scenario selection ---
    if args.scenario == "all":
        results: dict[str, bool] = {}

        # 1: auto
        results["1"] = run_scenario1(args)

        # 2: prompt before kicking off (gives operator time to set up)
        if not args.dry_run:
            _prompt("Ready for SCENARIO 2 (Electron AXPress)?")
        results["2"] = run_scenario2(args)

        # 3: prompt
        if not args.dry_run:
            _prompt("Ready for SCENARIO 3 (mismatch_target)?")
        results["3"] = run_scenario3(args)

        # 4: extra confirmation because it breaks permissions
        if args.dry_run:
            results["4"] = run_scenario4(args)
        else:
            if not _confirm(
                "Are you sure you want to run SCENARIO 4? This will REVOKE "
                "Screen Recording for the daemon and you will have to "
                "re-grant + restart `npm run dev` before any further runs."
            ):
                _info("SCENARIO 4 skipped by operator (no destructive action)")
                results["4"] = None  # type: ignore[assignment]
            else:
                results["4"] = run_scenario4(args)

        # Final summary
        _banner("FINAL SUMMARY (--scenario all)")
        any_failed = False
        for sid in ("1", "2", "3", "4"):
            res = results.get(sid)
            if res is None:
                print(f"  SCENARIO {sid}: {DIM}skipped{RESET}")
            elif res:
                print(f"  SCENARIO {sid}: {GREEN}PASS{RESET}")
            else:
                print(f"  SCENARIO {sid}: {RED}FAIL{RESET}")
                any_failed = True
        return 1 if any_failed else 0

    runner = SCENARIO_RUNNERS[args.scenario]
    ok = runner(args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
