# cursor-pointer-client

Python SDK for the [CursorPointer](../) desktop daemon.

```bash
pip install -e .          # core
pip install -e ".[ocr]"   # with OCR demo deps (RapidOCR + Pillow)
```

```python
from cursor_pointer import CursorPointer

cp = CursorPointer()           # http://127.0.0.1:39213 by default
assert cp.health()["ok"]
cp.move(400, 300)
cp.click()                     # left click at current position
cp.click(500, 400, button="right")
cp.double_click(120, 80)
cp.scroll(dy=-5)               # 5 ticks down
cp.type_text("hello, world")
cp.hotkey("cmd", "a")          # ⌘A
png = cp.screenshot()          # PNG bytes
```

See `examples/ocr_click.py` for a full OCR-driven click demo.

## Set-of-Mark agent layer

When you want an LLM to drive cursor-pointer, use the `Session` + annotate
helpers — the standard Set-of-Mark (SoM) pattern.

```python
from cursor_pointer import CursorPointer, Session

cp = CursorPointer()
sess = Session(cp)

ann = sess.annotate()
# ann.image_path → annotated PNG (numbered boxes), feed to your VLM
# ann.elements   → [{id, bbox, text, score}, ...]

# After the model says "click element 12":
sess.click_element(ann.id, element_id=12)

# Everything is recorded under sess.dir/events.jsonl
print(sess.history_summary())
```

### Full agent loop

`examples/agent_loop.py` provides a generic perceive→decide→act driver.
You supply a `policy(goal, annotation, history) → Action`. Two built-ins:

- `text_match_policy("Submit")` — deterministic, no LLM.
- `llm_policy(call_model)` — wrap any chat-completion callable.

```python
from cursor_pointer import CursorPointer
from examples.agent_loop import run_agent, llm_policy

def call_model(payload):
    # payload = {goal, history, annotation_image, elements}
    # Send to OpenAI / Claude / local LLaVA — return a string like
    #   click 5     |   type "hello"   |   key cmd+a   |   done
    ...

run_agent(
    goal="play the first audio sample on the page",
    policy=llm_policy(call_model),
    client=CursorPointer(),
)
```

### Coordinates

OCR runs on the raw 3840×2160 (Retina) screenshot; `Element.bbox` is converted
to **logical** screen pixels and that is what `CursorPointer.click(...)` takes.
End-to-end click precision is 0 pixels (verified by CGEventTap, see
`examples/click_delivery_test.py`).
