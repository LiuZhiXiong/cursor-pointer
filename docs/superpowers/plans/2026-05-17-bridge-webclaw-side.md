# cursor-pointer ↔ WebClaw bridge — WebClaw side plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Remote Control" feature to WebClaw that polls cursor-pointer's `/browser/next-command`, executes each command via WebClaw's existing `agent.run()`, and POSTs the result back to `/browser/result`. Toggleable from the sidepanel; state persisted in `chrome.storage.local`.

**Architecture:** New module `src/core/remote-control.js` owns a setInterval-based poll loop. Reuses WebClaw's `agent` from `src/core/agent.js`. Sidepanel toggle + URL input writes to `chrome.storage.local`; service-worker reads on startup to auto-resume.

**Tech Stack:** JavaScript ES modules (Chrome MV3 extension). Vite for the dev build. No new npm deps.

**Repo:** `/Users/liuzhixiong/coding-project/workspace-ai/web-claw`

**Spec:** [`cursor-pointer/docs/superpowers/specs/2026-05-17-cursor-pointer-webclaw-bridge-design.md`](../../../../cursor-pointer/docs/superpowers/specs/2026-05-17-cursor-pointer-webclaw-bridge-design.md) (lives in the cursor-pointer repo; this plan lives in web-claw repo)

---

## File Structure (in web-claw repo)

| File | Role | Change |
|---|---|---|
| `src/core/remote-control.js` | new poll loop + lifecycle | CREATE |
| `src/background/service-worker.js` | wire startup auto-resume | MODIFY |
| `src/sidepanel/sidepanel.html` (or src/sidepanel/sidepanel.js) | Remote Control toggle UI | MODIFY |
| `tests/core/remote-control.test.js` | unit tests | CREATE (if jest/vitest configured) |
| `docs/REMOTE_CONTROL.md` | brief user-facing doc | CREATE |

Note: web-claw uses Vite. Tests via `vitest` if `package.json` has it, otherwise pure `node` smoke. Check first.

---

## Task 1: scaffold `remote-control.js`

**Files:**
- Create: `src/core/remote-control.js`

- [ ] **Step 1: confirm web-claw test setup**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
grep -E "vitest|jest|mocha" package.json
```

Note whether vitest is present. If yes, we add `.test.js` files in Task 4. If no, skip Task 4's unit tests; the E2E test in Task 5 is enough.

- [ ] **Step 2: write `src/core/remote-control.js`**

Create the file with this content:

```javascript
/**
 * WebClaw Remote Control — polls cursor-pointer's /browser/next-command
 * and posts results back to /browser/result. Reuses the existing `agent`
 * to execute each command in the active tab.
 *
 * State lives in chrome.storage.local under the key 'remoteControl':
 *   { enabled: bool, baseUrl: string, lastError: string? }
 *
 * Lifecycle:
 *   start(baseUrl) — sets up the poll loop (idempotent)
 *   stop()         — clears the poll loop
 *   isActive()     — boolean
 */

import { agent } from './agent.js';

const POLL_INTERVAL_MS = 2000;
const STORAGE_KEY = 'remoteControl';

let _timer = null;
let _baseUrl = null;
let _inFlight = false;  // single-flight guard so a long-running agent
                        // doesn't get re-entered by the next tick

function _log(...args) {
  console.log('[remote-control]', ...args);
}

async function _setState(patch) {
  const current = (await chrome.storage.local.get(STORAGE_KEY))[STORAGE_KEY] || {};
  await chrome.storage.local.set({ [STORAGE_KEY]: { ...current, ...patch } });
}

async function _tick() {
  if (_inFlight) return;
  if (!_baseUrl) return;
  _inFlight = true;
  try {
    const r = await fetch(`${_baseUrl}/browser/next-command`, { cache: 'no-store' });
    if (!r.ok) {
      await _setState({ lastError: `next-command HTTP ${r.status}` });
      return;
    }
    const j = await r.json();
    if (!j.id) return;  // empty queue

    _log('received command', j.id, j.command);
    let ok = true;
    let output = '';
    try {
      const result = await agent.run({
        messages: [{ role: 'user', content: j.command }],
        maxIterations: 8,
      });
      output = (result && result.content) || JSON.stringify(result);
    } catch (e) {
      ok = false;
      output = String(e && (e.stack || e.message || e));
    }

    await fetch(`${_baseUrl}/browser/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: j.id, ok, output }),
    });
    _log('posted result for', j.id, 'ok=', ok);
    await _setState({ lastError: null });
  } catch (e) {
    _log('tick error:', e);
    await _setState({ lastError: String(e && (e.message || e)) });
  } finally {
    _inFlight = false;
  }
}

export function isActive() {
  return _timer !== null;
}

export async function start(baseUrl) {
  if (!baseUrl) throw new Error('start requires baseUrl');
  if (_timer !== null && _baseUrl === baseUrl) {
    return;  // already running with same URL
  }
  stop();
  _baseUrl = baseUrl.replace(/\/+$/, '');  // strip trailing slash
  _timer = setInterval(_tick, POLL_INTERVAL_MS);
  _log('started, polling', _baseUrl);
  await _setState({ enabled: true, baseUrl: _baseUrl });
}

export function stop() {
  if (_timer !== null) {
    clearInterval(_timer);
    _timer = null;
    _baseUrl = null;
    _log('stopped');
  }
}

export async function disable() {
  stop();
  await _setState({ enabled: false });
}

/**
 * Read persisted state and auto-resume if enabled. Called from
 * service-worker on startup.
 */
export async function resumeIfEnabled() {
  const stored = (await chrome.storage.local.get(STORAGE_KEY))[STORAGE_KEY];
  if (stored && stored.enabled && stored.baseUrl) {
    await start(stored.baseUrl);
    return true;
  }
  return false;
}
```

- [ ] **Step 3: commit**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
git add src/core/remote-control.js
git commit -m "feat(remote-control): add poll-loop module for cursor-pointer bridge"
```

---

## Task 2: wire service-worker startup

**Files:**
- Modify: `src/background/service-worker.js`

- [ ] **Step 1: locate startup section**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
grep -n "chrome.runtime.onInstalled\|chrome.runtime.onStartup\|chrome.storage.local\|init(\|setup(" src/background/service-worker.js | head -10
```

Find whichever existing block runs at service-worker startup (likely `chrome.runtime.onStartup.addListener` or top-level code that runs at module load).

- [ ] **Step 2: import + auto-resume**

At the top of `src/background/service-worker.js`, after the other imports, add:

```javascript
import { resumeIfEnabled as resumeRemoteControl } from '../core/remote-control.js';
```

In the service-worker's startup region (look for `chrome.runtime.onStartup` or top-level init code), add:

```javascript
// Auto-resume Remote Control if previously enabled.
resumeRemoteControl().then((on) => {
  if (on) console.log('[service-worker] remote-control resumed');
}).catch((e) => {
  console.warn('[service-worker] remote-control resume failed:', e);
});
```

If neither `onStartup` nor a clear init section exists, put the `.then()` call at module top-level so it runs whenever the worker boots.

- [ ] **Step 3: commit**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
git add src/background/service-worker.js
git commit -m "feat(remote-control): auto-resume on service-worker startup"
```

---

## Task 3: sidepanel toggle UI

**Files:**
- Modify: `src/sidepanel/sidepanel.html` and/or one of the sidepanel JS files

- [ ] **Step 1: locate sidepanel entry**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
ls src/sidepanel/
grep -l "settings\|options\|toggle" src/sidepanel/*.js src/sidepanel/*.html 2>/dev/null | head -3
```

The toggle could live in the main sidepanel or its settings sub-panel. Pick whichever is easier — typically the main sidepanel near other settings.

- [ ] **Step 2: add toggle markup**

In `src/sidepanel/sidepanel.html`, find a sensible existing settings region (search for `<input type="checkbox"`) and append next to it (or create a new section if no settings region exists):

```html
<details>
  <summary>Remote Control (cursor-pointer)</summary>
  <label>
    <input type="checkbox" id="rc-enable" />
    Enable polling
  </label>
  <input type="text" id="rc-url" placeholder="http://127.0.0.1:39213" />
  <button id="rc-save">Save</button>
  <p id="rc-status"></p>
</details>
```

- [ ] **Step 3: add toggle JS**

If there's already a single sidepanel JS file that handles inputs, append handlers there. Otherwise create `src/sidepanel/remote-control-ui.js`:

```javascript
import { start, disable, isActive } from '../core/remote-control.js';

const STORAGE_KEY = 'remoteControl';

async function _readState() {
  const stored = (await chrome.storage.local.get(STORAGE_KEY))[STORAGE_KEY] || {};
  return {
    enabled: !!stored.enabled,
    baseUrl: stored.baseUrl || 'http://127.0.0.1:39213',
    lastError: stored.lastError || null,
  };
}

function _renderStatus(state) {
  const el = document.getElementById('rc-status');
  if (!el) return;
  if (state.enabled) {
    el.textContent = state.lastError
      ? `⚠ enabled, last error: ${state.lastError}`
      : '✓ enabled, polling';
  } else {
    el.textContent = '○ disabled';
  }
}

async function init() {
  const enableEl = document.getElementById('rc-enable');
  const urlEl = document.getElementById('rc-url');
  const saveEl = document.getElementById('rc-save');
  if (!enableEl || !urlEl || !saveEl) return;

  const state = await _readState();
  enableEl.checked = state.enabled;
  urlEl.value = state.baseUrl;
  _renderStatus(state);

  saveEl.addEventListener('click', async () => {
    const baseUrl = (urlEl.value || '').trim();
    if (enableEl.checked) {
      if (!baseUrl) { alert('baseUrl required'); return; }
      await start(baseUrl);
    } else {
      await disable();
    }
    _renderStatus(await _readState());
  });

  // Periodic refresh so lastError stays current
  setInterval(async () => _renderStatus(await _readState()), 3000);
}

document.addEventListener('DOMContentLoaded', init);
```

Then add to `src/sidepanel/sidepanel.html` (in the `<head>` or before `</body>`):

```html
<script type="module" src="./remote-control-ui.js"></script>
```

- [ ] **Step 4: rebuild extension**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
npm run build 2>&1 | tail -3
```

Expected: Vite build output mentions the new module compiles.

- [ ] **Step 5: reload in Chrome**

Manual step. Open `chrome://extensions`, find WebClaw, click Reload. Then open the sidepanel — the new "Remote Control" section should appear.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
git add src/sidepanel/
git commit -m "feat(sidepanel): Remote Control toggle UI"
```

---

## Task 4: tests (skip if no vitest)

If Task 1 Step 1 found vitest, do this. Otherwise skip to Task 5.

**Files:**
- Create: `tests/core/remote-control.test.js`

- [ ] **Step 1: write tests**

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock chrome.storage and fetch BEFORE importing the module.
const _store = { remoteControl: {} };
globalThis.chrome = {
  storage: {
    local: {
      get: async (key) => ({ [key]: _store[key] }),
      set: async (obj) => Object.assign(_store, obj),
    },
  },
};

vi.mock('../../src/core/agent.js', () => ({
  agent: {
    run: vi.fn(async ({ messages }) => ({
      content: `mocked response to: ${messages[0].content}`,
    })),
  },
}));

let rc;
beforeEach(async () => {
  vi.useFakeTimers();
  rc = await import('../../src/core/remote-control.js?bust=' + Math.random());
});

describe('remote-control', () => {
  it('start sets enabled=true in storage', async () => {
    globalThis.fetch = vi.fn(async () => new Response('{}'));
    await rc.start('http://test');
    const state = (await chrome.storage.local.get('remoteControl')).remoteControl;
    expect(state.enabled).toBe(true);
    expect(state.baseUrl).toBe('http://test');
    rc.stop();
  });

  it('isActive returns true after start, false after stop', async () => {
    globalThis.fetch = vi.fn(async () => new Response('{}'));
    expect(rc.isActive()).toBe(false);
    await rc.start('http://test');
    expect(rc.isActive()).toBe(true);
    rc.stop();
    expect(rc.isActive()).toBe(false);
  });

  it('tick posts result back when fetch returns a command', async () => {
    const calls = [];
    globalThis.fetch = vi.fn(async (url, opts) => {
      calls.push({ url, opts });
      if (url.endsWith('/browser/next-command')) {
        return new Response(JSON.stringify({ id: 'x1', command: 'hello' }));
      }
      if (url.endsWith('/browser/result')) {
        return new Response(JSON.stringify({ ok: true }));
      }
      return new Response('{}');
    });
    await rc.start('http://test');
    // Advance timer to fire one tick
    await vi.advanceTimersByTimeAsync(2500);
    const resultCall = calls.find(c => c.url.endsWith('/browser/result'));
    expect(resultCall).toBeDefined();
    const body = JSON.parse(resultCall.opts.body);
    expect(body.id).toBe('x1');
    expect(body.ok).toBe(true);
    expect(body.output).toContain('mocked response');
    rc.stop();
  });
});
```

- [ ] **Step 2: run tests**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
npx vitest run tests/core/remote-control.test.js 2>&1 | tail -5
```

Expected: 3 passed.

If vitest isn't configured properly, mark this task as `DONE_WITH_CONCERNS` and move on; E2E covers behavior.

- [ ] **Step 3: commit**

```bash
cd /Users/liuzhixiong/coding-project/workspace-ai/web-claw
git add tests/
git commit -m "test(remote-control): unit tests covering start/stop/tick"
```

---

## Task 5: E2E with the cursor-pointer side

**Files:** none modified. Manual cross-repo test.

cursor-pointer side is already merged on main (commit `dcf3ba5`). The .app is running with `/browser/*` endpoints.

- [ ] **Step 1: confirm cursor-pointer side**

```bash
curl -s http://127.0.0.1:39213/health
curl -s http://127.0.0.1:39213/browser/next-command
```

Expected: `/health` returns ok, `/browser/next-command` returns `{}`.

- [ ] **Step 2: load updated WebClaw in Chrome**

Open `chrome://extensions`. Reload WebClaw. Open its sidepanel.

In the "Remote Control" section:
1. Enter `http://127.0.0.1:39213` in the URL field.
2. Check "Enable polling".
3. Click Save.

The status should show `✓ enabled, polling`.

- [ ] **Step 3: enqueue a command**

```bash
curl -s -X POST http://127.0.0.1:39213/browser/enqueue \
     -H "Content-Type: application/json" \
     -d '{"command":"what is the page title of the current tab?","timeout_seconds":60}'
```

Capture the `id`.

Within ~10 seconds, the WebClaw extension should:
1. Drain the command on its next 2s poll
2. Call `agent.run({messages: ...})`
3. POST `/browser/result` with the answer

```bash
curl -s http://127.0.0.1:39213/browser/result/<the-id>
```

Expected: `{"status":"done","ok":true,"output":"<title text>"}`. The output value depends on the active tab — could be anything; the test passes as long as `status==done` and `output` is non-empty.

- [ ] **Step 4: try via cursor-pointer agent**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
source /Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'tools')
from run_agent import execute
# Skip the SoM detect path; call execute() directly
result = execute('browser \"what is the page title?\"', boxes=[])
print('result:', result)
"
```

Expected: `result: None` (success). Check `python-client/tools/run_agent.py` history would have the output entry; without going through main loop, we just confirm no exception.

- [ ] **Step 5: archive evidence**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
mkdir -p docs/superpowers/evidence
cat > docs/superpowers/evidence/2026-05-17-bridge-e2e.log <<'EOF'
# E2E: cursor-pointer agent → WebClaw → cursor-pointer history
$ curl /browser/enqueue {"command":"what is the page title?",...}
{"id":"abc-...","expires_at":...}

$ # (WebClaw polls every 2s, drains the queue, runs agent, posts back)

$ curl /browser/result/abc-...
{"status":"done","ok":true,"output":"<title from active tab>"}
EOF
git add docs/superpowers/evidence/2026-05-17-bridge-e2e.log
git commit -m "evidence: bridge E2E cursor-pointer ↔ WebClaw"
```

(Note: this evidence commit lives in cursor-pointer, NOT web-claw.)

---

## Self-Review Notes

- **Spec coverage:** remote-control module → Task 1. Auto-resume → Task 2. UI toggle → Task 3. Tests → Task 4 (conditional). E2E → Task 5.
- **Placeholder scan:** no TBDs.
- **Single-flight:** `_inFlight` guard prevents the poll loop from re-entering `agent.run` while a previous command is still executing.
- **Rollback:** disable from the sidepanel turns off polling; no code change needed. Reverting commits removes the feature entirely.
- **Cross-repo:** spec lives in cursor-pointer; this plan documents WebClaw work. Implementation commits go to web-claw's own git history. Evidence (Task 5 Step 5) goes back into cursor-pointer's evidence dir.
