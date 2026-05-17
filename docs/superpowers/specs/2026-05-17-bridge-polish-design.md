# Bridge polish — design

**Date:** 2026-05-17
**Status:** approved → ready for implementation plan

## Problems

Two follow-ups discovered during the Cycle C dogfood:

1. **`expired` false-positive in `/browser/result/<id>`**
   After WebClaw drains a command (it leaves `pending`) but before WebClaw
   posts a result, our status endpoint returns `expired`. Scripts and
   agents that bail on `expired` give up too early; the command was
   actually being executed and would have completed in seconds.

2. **VLM doesn't pick `browser` verb naturally**
   The verb is in `SYSTEM_PROMPT` but the VLM doesn't reliably prefer it
   for tasks that obviously call for a browser (URLs, search-engine
   keywords, "open the website ..."). The verb gets ignored in favor of
   click/scroll attempts on whatever's on-screen.

## Goals

- Add an `in_progress` queue state, returned for IDs that have been
  drained but not yet resulted.
- Update SYSTEM_PROMPT to steer the worker VLM toward `browser` for
  web-flavored tasks.

## Non-goals

- Persistent queue (in-memory is still fine; SW restarts are rare).
- Per-tab targeting for the `browser` verb (defer).
- Auto-detecting URLs in the goal string (the VLM should decide).

## Design

### Rust: `in_progress` state

In `src-tauri/src/api.rs`, `BrowserQueue` gets a third map:

```rust
pub struct BrowserQueue {
    pub pending:     Mutex<VecDeque<BrowserCommand>>,
    pub in_progress: Mutex<HashMap<String, BrowserCommand>>,  // NEW
    pub results:     Mutex<HashMap<String, BrowserResult>>,
}
```

`next()` moves the popped command into `in_progress` (keyed by id)
instead of dropping it on the floor. `store_result()` removes the id
from `in_progress` when posting the result. `status()` returns:

| Case | Status |
|---|---|
| id in `results` | `done` |
| id in `pending` (not expired) | `pending` |
| id in `in_progress` (not expired) | `in_progress` |
| id in `pending` or `in_progress` but expired | `expired` |
| id never seen | `expired` (current behavior) |

TTL eviction: same 60-second TTL on `in_progress` as on `pending` and
`results`. A WebClaw client that crashes mid-execution causes an
`expired` after 60s, not 0s.

### Python: agent verb handles `in_progress`

In `python-client/tools/run_agent.py`, the `browser` verb loop already
polls forever as long as status is `pending`. Add `in_progress` to the
"keep polling" branch (it's the same semantic: not done yet).

### SYSTEM_PROMPT addition

After the existing verb listing, add a sentence in the rules section:

> 任务里出现 URL、域名、"搜索"、"网页"、"浏览器"、"打开 https://" 这类信号时，
> **必须**用 `browser "<task>"` 把整个任务委托给浏览器代理，不要自己尝试 click 浏览器界面。

### Smoke test script

`scripts/test_bridge_e2e.sh` currently exits on `expired`. Change to:
- exit on `done`
- treat `expired` as `still trying` UNTIL the timeout deadline
- exit on `expired` only if it persists past the deadline

## Testing

| Test | Asserts |
|---|---|
| (Rust) `BrowserQueue::next` moves item to in_progress | manually unit-checkable by reading state |
| (Rust) `status()` returns `in_progress` for drained-but-unresulted | new state visible via curl |
| (Rust) `status()` still returns `expired` for unknown ids | regression |
| (Python) `browser` verb keeps polling on `in_progress` | mock returns `in_progress` then `done`, agent stays in loop |
| (Smoke) /browser/* round-trip with intermediate `in_progress` observable | post enqueue → next → status now `in_progress`; then result → status `done` |

## Scope

| Layer | LOC |
|---|---|
| Rust queue + status | ~50 |
| Python verb poll loop | ~3 |
| SYSTEM_PROMPT | ~3 |
| smoke script fix | ~10 |
| tests | ~60 |
| **Total** | **~125** |

No new deps. Same `.app` rebuild caveat (TCC re-grant likely needed).

## Roll-back

Revert two commits (Rust, prompt). Smoke script either reverts or stays — it works with both queue shapes.
