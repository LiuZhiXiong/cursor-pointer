# cursor-pointer · 从零到跑通 (新 Mac)

整套有三层：`CursorPointer.app`（macOS Tauri 服务端）+ Python agent + WebClaw Chrome 扩展。下面分层装。预计 30–45 分钟。

## 0. 前置工具

```bash
xcode-select --install        # Xcode CLT (Rust 链接器 + macOS SDKs)
brew install rustup-init && rustup-init -y       # Rust toolchain
brew install node             # Node 20+
# Python 3.11 — 用你顺手的方式
# Chrome / Chromium
# mmx CLI: 你 MiniMax 提供的二进制（cursor-pointer 的 agent 通过它调 VLM）
```

权限提前心理准备：每次重 build `CursorPointer.app`，macOS TCC 都会失效（cdhash 绑定）— 这是 macOS 26 的固有行为。

## 1. cursor-pointer 服务端

```bash
git clone git@github.com:LiuZhiXiong/cursor-pointer.git
cd cursor-pointer
npm install
npm run build                 # 产 src-tauri/target/release/bundle/macos/CursorPointer.app
cp -R src-tauri/target/release/bundle/macos/CursorPointer.app /Applications/
open /Applications/CursorPointer.app
curl -s http://127.0.0.1:39213/health      # 应回 {"ok":true,...}
```

### 1a. 三个 TCC 权限（关键）

第一次跑会立刻在权限不足时报错。打开 System Settings → Privacy & Security：

| 面板 | 加什么 | 用途 |
|---|---|---|
| Accessibility | `/Applications/CursorPointer.app` | 读 AX 树（其它 app 的元素） |
| Input Monitoring | 同上 | 合成鼠标 / 键盘事件（含 ⌘⇧3 截图）|
| Screen Recording | 同上 | `/screen/screenshot` + `/screen/screenshot_native` 看到其它窗口 |

三个都打开。如果将来重 build .app 后某些功能失效，多半是 cdhash 变了，跑：

```bash
tccutil reset Accessibility com.cursorpointer.app
tccutil reset PostEvent      com.cursorpointer.app
tccutil reset ScreenCapture  com.cursorpointer.app
# 重启 .app，从面板里移除旧条目，再把新 .app 加进去
```

### 1b. 自启（可选）

让 CursorPointer 开机自启：

```bash
bash scripts/launchd/install.sh
```

下次登录就自动起。卸载：`bash scripts/launchd/uninstall.sh`。

## 2. Python agent

```bash
cd cursor-pointer/python-client
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[agent]"        # 装 cursor_pointer 包 + agent extras
```

### 2a. Python 自己也要 Accessibility

agent 直接 PyObjC 读 AX 树，所以 venv 的 Python 解释器也要在 Accessibility 列表里：

```
/Users/<you>/path/to/cursor-pointer/python-client/.venv/bin/python
```

把这个路径加进 Accessibility 面板。

### 2b. 配 MiniMax key

cursor-pointer 的 agent 通过 `mmx` CLI 调 MiniMax。在 mmx 自己的配置里把 API key 放好（具体看 mmx 文档），或者设环境变量 `MINIMAX_API_KEY`。

### 2c. 跑一次最小验证

```bash
cd cursor-pointer/python-client
.venv/bin/pytest tests/           # 62 passed
```

跑 agent 干个简单任务：

```bash
osascript -e 'tell application "NeteaseMusic" to activate' && sleep 1
env -u CURSOR_POINTER_NO_OVERLAY .venv/bin/python tools/run_agent.py \
   "在网易云左侧切换到「漫游」tab"
```

应该看到 subgoal、AXPress、verify_done 等日志。

## 3. WebClaw Chrome 扩展（浏览器桥）

```bash
git clone git@github.com:LiuZhiXiong/web-claw.git
cd web-claw
npm install
npm run build         # 产 ./web-claw/ 目录（Vite 输出）
```

### 3a. 加载到 Chrome

1. Chrome 地址栏 → `chrome://extensions/`
2. 右上角开 **Developer mode**
3. 点 **Load unpacked**，选 `web-claw/web-claw/` 目录（Vite 输出的那个，不是源码）

### 3b. 配 LLM provider

WebClaw 内部也要 LLM。打开 WebClaw 选项页（Chrome 右上角拼图 → WebClaw → 选项）：

- 选预设模型（推荐 MiniMax）
- 填 API key（和 mmx 那个可以同一把）
- Save

### 3c. 开 Remote Control（连 cursor-pointer 桥）

1. 点 Chrome 工具栏 WebClaw 图标 → 打开侧栏
2. 侧栏**最顶上**有一个蓝边折叠区「Remote Control (cursor-pointer)」
3. 点开：
   - ☑ Enable polling
   - URL 默认 `http://127.0.0.1:39213` 保持
   - **Save**
4. 状态行变成 `✓ enabled, polling`

## 4. 验证端到端

```bash
bash cursor-pointer/scripts/test_bridge_e2e.sh
```

期望 ~20 秒内返回 `{"status":"done","ok":true,"output":"<title from active Chrome tab>"}`。

如果 `expired` 一直不变：

- WebClaw 侧栏 status 看下，确认 `✓ enabled, polling`
- chrome://extensions 上 WebClaw 没被禁用、Service worker `Active` 状态正常
- Chrome DevTools 打开 WebClaw service-worker context，看 console 有没有 `[remote-control] tick error`

## 5. 跑一个跨 app 任务（dogfood）

```bash
osascript -e 'tell application "Google Chrome" to activate' && sleep 1 && \
osascript -e 'tell application "Google Chrome" to set URL of active tab of front window to "about:blank"' && sleep 1
cd cursor-pointer/python-client
env -u CURSOR_POINTER_NO_OVERLAY .venv/bin/python tools/run_agent.py \
   "用百度搜索「上海好玩的展览」并把首条标题告诉我" --max-steps 4
```

VLM 看到「搜索」关键词应该自动出 `browser "..."` verb，bridge 委托 WebClaw 跑，结果回到 history。verify_done 跑一遍做最终确认。

## 6. 故障排查清单

| 现象 | 检查 |
|---|---|
| `/health` 不通 | `.app` 没起，`open /Applications/CursorPointer.app` |
| AX 走不到（preflight 报 Accessibility） | Python 解释器路径加 Accessibility |
| ⌘⇧3 截图没文件出现 | Input Monitoring 不够 / 刚 rebuild .app 失效 → reset+重加 |
| `/screen/screenshot` 只看到自己窗口 | Screen Recording 同上 |
| `browser` verb 报 `expired` | WebClaw 没在 polling，重开 Remote Control |
| Agent 选了错按钮反复点 | AX-invisible 操作的已知坑，看 docs/superpowers/specs/ 里的 backlog |

## 7. 文档索引

- `docs/API.md` — cursor-pointer HTTP API 全表
- `docs/BRIDGE_E2E.md` — bridge 调试细节
- `docs/superpowers/specs/` — 每个 cycle 的设计 spec
- `docs/superpowers/plans/` — 每个 cycle 的实现 plan
- `docs/superpowers/evidence/` — E2E run logs
