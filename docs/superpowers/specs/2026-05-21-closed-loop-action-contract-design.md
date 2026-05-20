# Closed-Loop Action Contract — design

**Date:** 2026-05-21
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plan

## Problem

The agent loop is **open-loop control**: it picks an action ("click 5"), looks up element 5's pixel coordinates, fires `cp.mouse_click(x, y)`, and *believes* it worked. Mid-step verification doesn't exist; the only correctness check is `verify_done` at the very end of the task. By the time `verify_done` rejects, the agent has already walked five steps down a wrong path with no idea where it diverged.

Concrete failure modes that show up today:

- **Stale targeting.** Element 5's bbox is captured at perception time; between then and the click, the UI animates / scrolls / a dialog dismisses → the click lands on whatever moved into that spot. The agent never notices.
- **No structured action path.** Native macOS controls almost always expose `AXPressAction`, but the agent has no way to use it — every click is a pixel CGEvent, which is the most fragile transport.
- **Silent number-mismatch.** The VLM emits an element id; the parser is lenient (`run_agent.py:780-790`); if the annotation list and the AX tree disagree on numbering, the wrong element is clicked and nothing checks.
- **Pixel-only error propagation.** `execute()` returns `None` for success or a free-form string for failure (`run_agent.py:1451-1469`). The planner can't distinguish "click missed the target" from "click ran but UI didn't react" from "permission revoked." Everything degrades into `consec_action_fails += 1`.
- **Hardcoded escalation.** Three fixed strategies (`run_agent.py:256-321`) run in fixed order regardless of why the action failed.

The fix is to make every action a **closed loop**: each verb takes a *target intent* (what to act on, with multi-anchor evidence) and an *expected outcome* (what should be true after), then returns a *structured result* the planner can branch on. Internally the executor re-locates the target just-in-time, prefers structured action over pixel where possible, and verifies the expected outcome happened before declaring success.

## Goal

Introduce an `Intent → ActionExecutor → Outcome` contract in the Python client. Migrate the two highest-frequency verbs (`click`, `type`) to it. Add one new Rust endpoint (`POST /ax/press`) as the structured-action transport. Replace the planner's None/string return inspection with structured Outcome branching for these two verbs.

Success criteria (measurable, to be re-checked during plan execution):

1. On TextEdit integration test, `click File menu → New` and `type "hello world"` both verify automatically (no `verify_done` needed to catch mistakes).
2. Drift case: introduce a 200ms artificial delay between detect and act on a moving target — executor must detect the drift via relocate and return `mismatch_target`, not silently click the wrong place.
3. Structured-first path: clicking a button that has `AXPressAction` uses `/ax/press` (verified by tracing the request); falls back to pixel only when AX action unavailable.
4. Existing test suite passes (no regressions in `python-client/tests/`).

## Non-goals

- **Migrating verbs other than `click` and `type`** — the other 14 verbs (`scroll`, `key`, `clipboard_*`, `shell`, `browser`, `mouse_*`, `done`, etc.) keep their current implementations. They will be migrated in a follow-up PR once the contract has settled.
- **Verb registry refactor** (theme A from the audit) — out of scope; this spec only introduces the executor shell, not a declarative verb table.
- **Splitting `run_agent.py` monolith** (theme B) — out of scope.
- **Persistent cross-session learning** (theme D) — out of scope.
- **Changing the VLM protocol.** The VLM still emits `subgoal: ... / action: ...`; ExpectSig is derived from defaults per verb kind, not from VLM output. (Future PR may extend the protocol to let VLM emit explicit expects.)
- **Replacing the planner.** Planner remains as-is; it just consumes richer Outcome objects.
- **Tauri/Rust backend rewrite.** Only one small new endpoint is added.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Scope of first cut | `click` + `type` only; other verbs stay on legacy path. |
| Exception policy | Executor **never** raises across its boundary. All failures become structured `Outcome.status` values. |
| Target matching priority | `ax_path 完全等 > ocr_text 完全等 > pHash 距离 < 阈值 > bbox 完全重叠`. First hit wins. |
| Drift tolerance | Search re-located target within `bbox ± 50px`. Tuned during integration; fall back to a configurable constant. |
| pHash threshold | Hamming distance `< 8` on 16-byte pHash. Same caveat — empirical, will revisit with data. |
| Structured action transport | New Rust endpoint `POST /ax/press` with body `{ax_path: [...]}`. Returns `200` on success, `404` if action unsupported by element. |
| Verify timing | Synchronous re-screenshot + AX inspection immediately after action. Acceptable overhead (~200-500ms). |
| ExpectSig source | Per-verb default rules. `click` default: focus changes OR AX subtree changes OR ROI pixel delta ≥ 2%. `type` default: typed text appears in focused element's AXValue. |
| Verify on legacy verbs | No. Legacy verbs go through executor shell to get error structuring, but skip verify. |
| AXPressAction support discovery | Try-then-fallback per call. **No per-app caching in v1.** |
| Backward compat | All existing planner code paths that call `cp.click(...)` / `cp.type_text(...)` still work; they just now go through the executor. |

## Architecture

```
Planner (VLM)  ──"click 5" / "type hello"──▶
                                              IntentBuilder
                                                │ pulls element 5 from current
                                                │ annotation list; captures
                                                │ ax_path, ocr_text, pHash, bbox
                                                │ → Intent(target_sig, expect_sig)
                                                ▼
                                              ActionExecutor.execute(intent)
                                                ├─ 1. relocate
                                                │     fresh shot + AX walk
                                                │     find match within bbox±50
                                                │     mismatch → return early
                                                │
                                                ├─ 2. structured-first
                                                │     ax_path + AXPress avail?
                                                │     → POST /ax/press
                                                │     else fall through
                                                │
                                                ├─ 3. pixel fallback
                                                │     existing cp.mouse_click /
                                                │     cp.type_text path
                                                │
                                                └─ 4. verify
                                                      re-shot + focused AX
                                                      compare to expect_sig
                                                ▼
                                              Outcome ──▶ Planner branches
                                                          on .status
```

### New Python modules (live under `python-client/cursor_pointer/`)

- **`intent.py`** — frozen dataclasses: `TargetSig`, `ExpectSig`, `Intent`, `Outcome`. Pure data, no I/O.
- **`anchors.py`** — building and matching multi-anchor signatures: pHash, AX path walk, OCR-region extraction, drift search. Pure functions over inputs (screenshot bytes, AX tree, element list); easy to unit-test.
- **`executor.py`** — `ActionExecutor` class. Holds references to `CursorPointer` client + AX walker + screenshot source. One method: `execute(intent: Intent) -> Outcome`. Internally orchestrates relocate / structured / fallback / verify.

### Changes to existing files

- **`run_agent.py`** — the `click` and `type` branches in `execute()` are rewritten to build an `Intent` and delegate to `ActionExecutor` (full contract: relocate + structured + verify). The other 14 branches keep their existing bodies; each is wrapped at the return point by a thin adapter that maps the current return value (`None | str`) into a minimal `Outcome` with `status="executed_unverified"` (success) or `status="exec_error"` (failure string). The planner-side `consec_action_fails` logic switches to branching on `Outcome.status` instead of `result is None`. This keeps the legacy verbs functionally identical while making the planner uniform.
- **`client.py`** — adds `ax_press(path: list[str]) -> dict` method calling the new `/ax/press` endpoint. Existing methods unchanged.

### Rust side (small)

- **`src-tauri/src/ax.rs`** — new module. ~80 lines. Exposes `ax_press(ax_path: Vec<String>) -> Result<()>` using `objc2` / `objc2-application-services` bindings to `AXUIElementCopyAttributeValue` + `AXUIElementPerformAction(kAXPressAction)`. Walks the AX tree from system-wide root following the path; returns `404` semantics if element not found, `400` if `AXPressAction` unsupported.
- **`src-tauri/src/api.rs`** — new route `POST /ax/press` wired to `ax.rs`. Adds `AxPressRequest` and `AxPressResponse` structs. Follows existing handler pattern.
- **`src-tauri/Cargo.toml`** — add `objc2 = "0.5"` and `objc2-application-services = "0.2"` (current minor versions at time of writing; pin during plan execution). These are new dependencies — confirmed absent from current Cargo.toml.

## Data structures

```python
# intent.py

@dataclass(frozen=True)
class TargetSig:
    element_id: int                       # original annotation id (best-effort)
    bbox: tuple[int, int, int, int]       # x, y, w, h — logical px
    ax_path: tuple[str, ...] | None       # e.g. ("AXApplication:Mail",
                                          #       "AXWindow:Inbox",
                                          #       "AXButton:Send")
    role: str | None                      # AX role of the leaf, if known
    ocr_text: str | None                  # text inside bbox, if OCR run
    visual_hash: str                      # pHash of ROI, hex

@dataclass(frozen=True)
class ExpectSig:
    # any-of semantics: action is verified if ANY enabled condition matches
    focus_changes: bool = True
    ax_subtree_changes: bool = False
    roi_pixel_delta_min: float = 0.02     # mean abs pixel diff in ROI
    typed_text_in_focus: str | None = None  # for type: focused AXValue must
                                            # end-with or contain this string

@dataclass(frozen=True)
class Intent:
    kind: Literal["click", "type"]
    target: TargetSig | None              # None only for type-without-target
    payload: dict                         # e.g. {"text": "hello"} for type
    expect: ExpectSig
    raw_action: str                       # original VLM-emitted string, for logs

@dataclass(frozen=True)
class Outcome:
    status: Literal["ok", "mismatch_target", "executed_unverified",
                    "verify_failed", "exec_error"]
    intent: Intent
    elapsed_ms: int
    relocate_drift_px: int | None         # how far the target moved between
                                          # detect-time and act-time
    used_path: Literal["ax_press", "pixel", "dom_click", "none"]
    before_hash: str | None               # pHash of ROI before action
    after_hash: str | None
    error: str | None                     # human-readable, structured by status
```

## Data flow — click

1. Planner emits `subgoal: open compose / action: click 5`.
2. `IntentBuilder.build_click(action_str, elements, screenshot, ax_tree)`:
   - Pull element with `id == 5` from `elements`.
   - Compute `pHash` over screenshot ROI defined by element bbox.
   - Walk `ax_tree` to find the AX node enclosing bbox center → store ax_path + role.
   - Pull OCR text for that bbox if `ocr_results` available.
   - Assemble `TargetSig` + default `ExpectSig` for click → assemble `Intent`.
3. `ActionExecutor.execute(intent)`:
   - **relocate (≤ 100ms)**: take a fresh screenshot, walk AX tree, search candidates within `bbox±50px`. Match priority: `ax_path` exact → `ocr_text` exact → pHash distance < 8 → bbox overlap. Compute `relocate_drift_px = euclidean(old_center, new_center)`. If no candidate → `status=mismatch_target, used_path=none`, return.
   - **structured-first**: if `ax_path` still valid → `POST /ax/press {path}`. On 200 → set `used_path=ax_press`, skip pixel. On 4xx → fall through.
   - **pixel fallback**: `cp.mouse_click(new_center_x, new_center_y)`. Set `used_path=pixel`.
   - **verify**: 50ms later, re-screenshot + read AX focused element. Compute `after_hash` for ROI. Compare against `ExpectSig`. Any condition met → `status=ok`. None met → `status=verify_failed`.
4. Return Outcome.

## Data flow — type

Two sub-cases:

- **`type` with no target** (just type into whatever's focused): no TargetSig, no relocate. Skip directly to `cp.type_text(payload.text)`. Verify by reading focused element's AXValue immediately after and checking it contains `payload.text` (suffix match, since editors may auto-complete).
- **`type` with target** (`type 5 "hello"` — focus element 5 first, then type): build TargetSig like click, run the same relocate + structured-first + pixel-fallback pipeline to focus the target (verify step is **skipped** for this internal focus click — its only job is to put focus on the element), then `cp.type_text(payload.text)`. Then run the type verify (AXValue suffix match) over the final state. The Outcome's `used_path` reports the path used for the focus click.

ExpectSig for type defaults: `typed_text_in_focus = payload.text`, other flags off.

## Error handling — Outcome → Planner

Replaces the current `result is None → success, else failure` check. New mapping:

| Outcome.status | Planner reaction |
|---|---|
| `ok` | Increment success counters, proceed. |
| `mismatch_target` | **Force re-perception**: discard current annotation list, take fresh screenshot, re-annotate, re-prompt VLM. Do NOT increment `consec_action_fails` (this isn't a model failure; the world moved). |
| `executed_unverified` | Treat as "maybe worked." Take a screenshot before next action; if next action is a `done`, run `verify_done` as usual but with extra caution. |
| `verify_failed` | Increment `consec_action_fails`. On next step, escalate: if used_path was `pixel`, prefer `ax_press` next time (or vice versa); try scroll-into-view; surface to planner via prompt hint "last action did not produce the expected effect." |
| `exec_error` | Sub-classify on `error` field. `permission_denied` → halt loop, surface to user. `network_timeout` → retry once, then `verify_failed` semantics. `unknown` → `verify_failed` semantics. |

This table is the replacement for the blunt `consec_action_fails += 1` counter at the call site.

## Permission revocation surfacing

Adjacent fix that falls out of the executor's verify step almost for free: when verify reads a screenshot that is "all black" or has zero dimensions, treat that as `exec_error` with `error="permission_denied: screen_recording"` and halt the loop. (Today the agent loops on black screenshots indefinitely — see audit finding #11.) Detection heuristic, applied to the **full screenshot** (not just the target ROI, because ROI of a black frame is trivially black): mean pixel value `< 2` AND stddev `< 1` AND width × height > 0. Cheap to compute. Same check runs once at executor construction to surface the failure at agent startup rather than mid-task.

## Testing

### Unit tests (new file `python-client/tests/test_executor.py`)

- `test_intent_builder_click_with_ax_path` — element with AX path produces full TargetSig.
- `test_intent_builder_click_no_ax_path` — AX walk fails → ax_path is None, pHash still computed.
- `test_executor_relocate_exact_hit` — same screenshot, target found at same place, drift = 0.
- `test_executor_relocate_drifted_within_threshold` — target moved 30px → recovered, drift recorded.
- `test_executor_relocate_mismatch` — target gone → `status=mismatch_target`, no click issued.
- `test_executor_structured_first_used` — ax_path present + mock /ax/press returns 200 → `used_path=ax_press`, pixel client never called.
- `test_executor_structured_falls_back_on_404` — mock /ax/press returns 404 → `used_path=pixel`.
- `test_executor_verify_focus_changed` — before/after focused AX differs → `status=ok`.
- `test_executor_verify_roi_changed` — focus same but ROI pHash differs ≥ threshold → `status=ok`.
- `test_executor_verify_failed` — neither focus nor ROI changed → `status=verify_failed`.
- `test_executor_type_verify_text_appears` — AXValue ends with typed text → ok.
- `test_executor_permission_denied_detection` — verify screenshot is black → `status=exec_error, error=permission_denied:screen_recording`.

### Integration test (new file `python-client/tests/test_integration_textedit.py`, gated by env var `RUN_INTEGRATION=1`)

- Spawn TextEdit via AppleScript.
- Drive the agent through: click File menu → click New → type "hello world" → click File → click Close → click Don't Save.
- Assert each step's Outcome.status == "ok" and `used_path == "ax_press"` for menu clicks.
- Teardown: kill TextEdit.

### Drift test (new file `python-client/tests/test_drift.py`)

- Synthetic: mock the screenshot source to return a shifted image on the second call.
- Assert `relocate_drift_px` is recorded and `status=ok` (within threshold) or `mismatch_target` (beyond threshold).

### Regression

- All existing tests in `python-client/tests/` must pass unchanged.
- `scripts/smoke_test_api.py` must pass — new `/ax/press` endpoint added to the smoke matrix.

## Open questions (resolve during plan execution, not now)

1. **pHash and drift thresholds.** Starting values: pHash distance < 8, drift radius 50px. Tune against integration test results.
2. **AXPressAction support discovery.** v1 strategy: try, fall back on 4xx. **Defer per-app caching** until we have telemetry on miss rate.
3. **AX path equality.** Should we match on the full path or only the leaf role + label? Start with full path; if it's too strict in practice, weaken to leaf-only with a flag.
4. **OCR text presence.** OCR is not always run before each action (cost). If `ocr_text` is None on the TargetSig, drop that match criterion silently.

## Risks

- **AX path stability across app updates.** If macOS changes how an app exposes its AX hierarchy mid-task, ax_path matching fails and we fall back to pHash/bbox. Acceptable.
- **Verify overhead.** ~200-500ms per action × 5-10 actions per task ≈ 1-5s added latency. The accuracy gain offsets this; if it doesn't, an opt-out flag per Intent can be added later.
- **Rust `objc2-application-services` integration complexity.** Implementation risk on the Rust side. Mitigation: if the bindings are painful, drop in a small `swift` shim called via FFI. The interface (`/ax/press` endpoint) is unchanged from Python's perspective.
- **Existing tests assume `execute()` returns `None | str`.** They'll need targeted updates where they assert on the return shape of click/type. Listed as part of the migration work.

## What this unlocks (out of scope here, but worth noting)

- Per-app learning (theme D): with structured Outcomes carrying `used_path`, success rate per (app, verb, used_path) becomes trivially recordable.
- Verb registry (theme A): the executor shell is essentially the registry's runtime; converting verbs to declarative entries is a mechanical follow-up.
- Better stuck detection: replace string-equality on `last_action` with semantic equality on `Intent.target.ax_path + Intent.kind`.
