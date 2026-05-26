# Community intro messages

Two short, low-pressure messages for breaking into specific developer communities. Both lead with the problem, mention cursor-pointer once, and ask a real question. Do NOT post both on the same day — space them out, and read the recent channel context before posting so you can hook into an existing thread if one fits.

---

## (a) Anthropic Claude developer Discord — #general

> Hey — I've been building computer-use tooling with Claude on macOS and keep hitting one specific failure mode: synthetic clicks on Electron apps (Slack, Discord, etc.) get silently swallowed, so the agent thinks it clicked and walks five more steps in the wrong direction. My current workaround is to try the accessibility AXPress path first and fall back to pixel clicks, then verify each action by re-perceiving — I open-sourced it as cursor-pointer (github.com/LiuZhiXiong/cursor-pointer) if it's useful to anyone. Genuinely curious: how are others handling click-verification with Claude computer-use today? Are you re-screenshotting after every action, or trusting the click?

(~615 chars — trim "Genuinely curious:" if over the channel's limit.)

---

## (b) r/LocalLLaMA

> Question for folks running local models against computer-use tasks on macOS: how are you handling silent click failures? I've found Electron apps (Slack, Discord, NeteaseMusic, anything Chromium-based) frequently ignore synthetic mouse events, which means the model gets no signal that its action failed and keeps planning forward. I ended up writing cursor-pointer (MIT, github.com/LiuZhiXiong/cursor-pointer) to try AXPress first and verify each action, but I'd love to know what local-model setups are doing here. Is anyone getting reliable computer-use out of Llama / Qwen on a Mac, and if so what's your click-verification loop look like?

(~660 chars — Reddit doesn't enforce a strict cap but this fits in a comfortable single screen on mobile.)

---

## Posting checklist

- [ ] Read the last ~20 messages in the target channel/sub before posting. If there's a live thread asking exactly this question, reply there instead of starting a new one.
- [ ] Do not edit-bomb to add the link if you forgot it — post once, accept the result.
- [ ] If someone engages, respond within an hour. If you can't, don't post.
- [ ] Track which message went where so you don't repeat in the same community.
