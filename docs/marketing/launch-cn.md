# cursor-pointer 中文社区发布文案

四份独立文案，按各自渠道直接复制粘贴即可发。事实全部来自 README 与 launch-show-hn.md，不外加。

---

## 1. 少数派 / V2EX 长文

**标题：**

> 写了个 macOS 上给 AI agent 用的"闭环点击"工具，每次点击都告诉你到底点没点上

**正文（约 850 字）：**

调过 computer-use agent 的应该都遇到过这种情况：模型说"点 Submit"，pyautogui 把鼠标事件发出去了，看着像点上了，结果 Slack / Discord / 网易云这种 Electron 应用根本没理你那个合成事件。Agent 不知道，继续往下走五步，最后你拿着一堆截图回头找哪一步开始跑偏，一下午就没了。

我写 cursor-pointer 就是为了不再过这种下午。它是一个 macOS 的 Tauri/Rust 守护进程加一个 Python SDK，每次 click / type 之后给你一个结构化的结果——不是"事件已发送"，而是"针对当前焦点元素点击已验证，走的是 ax_press 路径，漂移 0px，耗时 12ms"。

和自己拿 pyautogui + 截图循环糊一套相比，主要不一样的是三点：

1. **先 AXPress 再 pixel fallback。** 很多 Electron 应用会吞掉合成 CGEvent，但它们认 accessibility action。cursor-pointer 先试 AX，AX 不可用再退回到像素点击。结果里会写清楚这一步走的是哪条路径，不用你自己猜。
2. **每个动作单独 verify。** 点完 / 输完之后会重新感知一次，对比预期变化是否发生。失败模式是有限枚举的：`ok` / `mismatch_target` / `verify_failed` / `exec_error` / `permission_denied`。Agent 收到 `verify_failed` 自己就知道要重规划，而不是接着往下错。
3. **权限被收回会立刻冒出来。** 跑到一半你把屏幕录制权限关了，进程直接 exit code 2 退出，不会在一堆黑色截图上死循环。

最小用法长这样：

```python
from cursor_pointer import CursorPointer
from cursor_pointer.executor import ActionExecutor, build_click_intent

cp = CursorPointer()
ex = ActionExecutor(cp=cp, screenshot_fn=lambda: cp.screenshot(),
                    ax_press_fn=..., focused_ax_fn=...)

intent = build_click_intent("click 5", element_id=5,
                            elements=detect(), screenshot_png=cp.screenshot())
outcome = ex.execute(intent)
print(outcome.status, outcome.used_path)
# → ok ax_press
# → mismatch_target none
```

或者直接跑自带的 agent：

```bash
python tools/run_agent.py "open a new TextEdit document and type closed loop"
```

目前只支持 macOS（依赖 CGEvent + xcap + accessibility API），173 个测试，MIT 协议。Rust 冷编译大概 10–15 分钟，之后第一次启动会让你授权 Accessibility 和 Screen Recording，授完重启一下就行。

Repo：https://github.com/LiuZhiXiong/cursor-pointer

主要想问一下也在搞 computer-use agent 的朋友：

- 你们现在点完之后是怎么确认点上了的？每步都重截图？还是直接信任 click？
- 我现在那套 outcome 分类（ok / mismatch_target / verify_failed / exec_error / permission_denied）能覆盖你们实际踩过的坑吗，有什么是我没列进去的失败模式？
- 还有 verb registry 的扩展形状，欢迎拍砖。

有用过类似工具或者踩过同样坑的，希望能给点反馈。

---

## 2. Twitter 中文版（≤ 280 字符）

> 写了个 macOS 上给 AI agent 用的工具：cursor-pointer。
>
> 解决一个具体问题——Electron 应用（Slack / Discord / 网易云）会吞掉 agent 的合成点击，agent 不知道，继续往下错五步。
>
> 每次点击都返回结构化结果：走的是 AXPress 还是像素点击、有没有 verify 通过、漂移多少。点没点上不用猜。
>
> Rust + Python，MIT，173 个测试。
>
> github.com/LiuZhiXiong/cursor-pointer

（约 210 字符，留出引用 / 加图的余地。）

---

## 3. 知乎专栏

**标题候选：**

> 我是怎么让 AI agent 在 macOS 上点击不再"看起来点上了"的

**开头钩子段落（直接发布版，约 280 字）：**

去年底开始用 Claude 做 macOS 上的 computer-use，前两周每天都在同一个坑里栽：让模型点一个按钮，pyautogui 把合成事件发出去了，截图看着也像点上了，结果下游什么反应都没有——Slack 那种 Electron 应用根本不认合成 CGEvent。Agent 不知道，继续往下走五步、十步，最后我拿着一长串截图回溯哪一步开始错的，调一下午很正常。

更阴间的是另一种情况：感知和动作之间过了 80ms，一个 modal 弹出来或者消失，点击落到了底下不该点的东西上，agent 还以为自己点的是原来的目标。这类问题不是"偶尔不稳定"，是 computer-use 本身把桌面当黑盒在用，缺一个反馈回路。

后来我把这套反馈回路单独抽出来做了个工具，叫 cursor-pointer，已经开源。下面把这个问题和我的解法展开讲一下。

**正文大纲（约 800–1200 字展开）：**

### 一、问题：computer-use SDK 把桌面当黑盒

- 现在主流 computer-use 框架（Anthropic 的 reference impl、各种 pyautogui 套壳）都是"发事件 → 截图 → 让模型自己判断有没有点上"。
- 模型判断不可靠的三个真实场景：
  1. Electron 应用吞合成 CGEvent（Slack / Discord / 网易云全中招）。
  2. 感知和动作之间界面变了（modal 弹出 / 消失，列表刷新，焦点切走）。
  3. 权限中途被收回（用户手贱关掉屏幕录制权限），agent 在一堆黑截图上死循环。
- 这些都不是模型能力问题，是底层动作通道没给反馈。
- *【此处插示意图：感知-决策-动作 三段式 vs. 感知-决策-动作-验证 闭环】*

### 二、解法：每个动作返回一个结构化 outcome

- 核心想法：动作不是 fire-and-forget，动作是一个有返回值的契约。
- outcome 至少包含：状态（ok / mismatch_target / verify_failed / exec_error / permission_denied）、走的路径（ax_press / pixel）、感知坐标和实际动作坐标的漂移、耗时。
- 模型拿到 `verify_failed` 自己知道该重规划，而不是闭着眼往下走。
- *【此处插代码示例：README 里 ActionExecutor.execute(intent) 的最小例子】*

### 三、AXPress：为什么 Electron 应用要单独处理

- macOS 的 accessibility API 提供了 `AXPress` 动作，可以直接告诉控件"你被按了"，不走鼠标事件通道。
- Electron 应用响应 AXPress，但不一定响应合成 CGEvent。
- cursor-pointer 的策略：先试 AXPress，目标控件没暴露这个 action 再退回到像素点击。outcome 里写清楚走的哪条。
- *【此处插一段对比代码：纯像素点击 Slack 发送按钮 vs. AXPress 点同一个按钮】*

### 四、Verify：感知-动作-再感知

- 每个 verb（click / type / hotkey）在 verb registry 里注册自己的 verify 函数。
- click 的 verify：检查焦点元素是否变了 / 按钮状态是否变了 / 期望的副作用是否出现。
- type 的 verify：检查目标文本框的 value 是否包含输入字符串。
- *【此处插示意图：verb registry 的结构 + 添加一个新 verb 需要写哪些东西】*

### 五、权限：能 fail-fast 就不要悄悄烂掉

- macOS 上 Accessibility 和 Screen Recording 两个权限随时可能被用户关掉。
- 关掉之后继续 screenshot 会返回黑帧，继续合成事件会被静默丢弃。
- cursor-pointer 探测到这种情况直接 exit code 2，不让 agent 在错误状态下继续跑。

### 六、目前状态和坑

- macOS only（CGEvent + xcap + accessibility 都是 macOS 专属）。
- Rust 冷编译 10–15 分钟，心理准备一下。
- 173 个测试，MIT 协议。
- 还在打磨的部分：跨屏 / 多 monitor 场景；非英文输入法的 type verify。

### 七、链接和邀请

- 开源仓库：https://github.com/LiuZhiXiong/cursor-pointer
- 也在搞 computer-use 的同行欢迎提 issue 或者直接拍砖 outcome 分类。
- 如果你的 agent 也经常"看起来点上了实际没点上"，可以拿去试试。

---

## 4. AI 圈微信群破冰短消息（≤ 200 字）

> 大家好，潜水好久第一次冒泡。最近在拿 Claude 做点 macOS 上的 computer-use，被一个问题搞烦了——agent 让点 Slack 的发送按钮，合成点击被 Electron 吞了，agent 不知道继续往下错好几步，每次调一下午。
>
> 顺手写了个小工具叫 cursor-pointer，每次点击返回个结构化结果，至少知道点没点上。已经开源（github.com/LiuZhiXiong/cursor-pointer）。
>
> 想问下群里在搞 agent 的朋友：你们现在点完一个按钮，是怎么确认真的点上了的？每步都重截图给模型自己判断吗？
