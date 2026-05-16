"""VLM-as-verifier — use a vision LLM to filter+refine the candidate list.

After running ``run_consensus.py`` we typically have 100-400 candidates of
mixed quality. This script crops each candidate from the screenshot, sends a
small grid (or individual crops) to a vision LLM, and asks:

    For each candidate, decide:
      • is_clickable: yes/no
      • semantic_role: button | link | text-field | image | decoration
      • visible_label: text on the element

The VLM acts as the final arbiter, dropping noise and adding real semantic
labels to icon-only buttons (where AX/OCR were blind).

The script is provider-agnostic. Implement ONE function::

    def call_vlm(image_path: Path, prompt: str) -> str:
        '''Send an image + prompt to your model of choice, return text.'''
        ...

Then wire it via the ``VLM_PROVIDER`` env var: ``openai`` / ``claude`` /
``qwen`` / ``ollama`` / ``stub``.

The default ``stub`` provider doesn't call any model — it just lets you
inspect what would be sent, useful for development.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Callable

import requests
from PIL import Image, ImageDraw, ImageFont

API = "http://127.0.0.1:39213"
PROVIDER = os.environ.get("VLM_PROVIDER", "stub")

VlmCall = Callable[[Path, str], str]


# ---------------------------------------------------------------------------
# Provider implementations — each takes (image_path, prompt) → string
# ---------------------------------------------------------------------------

def _stub_provider(image_path: Path, prompt: str) -> str:
    print(f"\n[stub VLM] image={image_path} prompt:\n{textwrap.indent(prompt, '  ')}\n")
    # Return an empty JSON list so the caller falls back to the raw candidates.
    return "[]"


def _openai_provider(image_path: Path, prompt: str) -> str:
    """OpenAI gpt-4o / gpt-4-vision via the chat completions API."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            "temperature": 0,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _anthropic_provider(image_path: Path, prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "max_tokens": 4096,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _minimax_provider(image_path: Path, prompt: str) -> str:
    """MiniMax VLM via the bundled `mmx` CLI (handles auth + base64 itself)."""
    import subprocess
    cmd = [
        "mmx", "vision", "describe",
        "--image", str(image_path),
        "--prompt", prompt,
        "--output", "json",
        "--quiet",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"mmx failed ({r.returncode}): {r.stderr.strip()}")
    # mmx --output json returns { reply: "..." } (or similar). Extract the text.
    try:
        data = json.loads(r.stdout)
        # try common keys
        for k in ("reply", "text", "content", "description", "answer", "response"):
            if k in data and isinstance(data[k], str):
                return data[k]
        # nested choices style
        if isinstance(data.get("choices"), list) and data["choices"]:
            msg = data["choices"][0].get("message", {})
            if isinstance(msg.get("content"), str):
                return msg["content"]
        return json.dumps(data)
    except json.JSONDecodeError:
        return r.stdout


def _ollama_provider(image_path: Path, prompt: str) -> str:
    """Local Qwen2-VL or LLaVA via Ollama."""
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    r = requests.post(
        os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat"),
        json={
            "model": os.environ.get("OLLAMA_MODEL", "qwen2.5vl:7b"),
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            "stream": False,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


PROVIDERS: dict[str, VlmCall] = {
    "stub": _stub_provider,
    "openai": _openai_provider,
    "anthropic": _anthropic_provider,
    "claude": _anthropic_provider,
    "ollama": _ollama_provider,
    "minimax": _minimax_provider,
}


# ---------------------------------------------------------------------------
# Annotation rendering — draw numbered boxes on the screenshot for the VLM
# ---------------------------------------------------------------------------

def annotate_screenshot(png_path: Path, boxes: list[dict], scale: float, max_width: int = 1600) -> Path:
    img = Image.open(png_path).convert("RGB")
    # Resize to keep prompt fast (4K screenshots can take minutes for VLMs)
    w0, h0 = img.size
    if w0 > max_width:
        ratio = max_width / w0
        img = img.resize((int(w0 * ratio), int(h0 * ratio)), Image.LANCZOS)
        scale = scale * ratio
    draw = ImageDraw.Draw(img, "RGBA")
    font = None
    for cand in ("/System/Library/Fonts/SFNS.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(cand):
            try:
                font = ImageFont.truetype(cand, max(11, int(14)))
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    for b in boxes:
        x = int(b["x"] * scale); y = int(b["y"] * scale)
        w = int(b["w"] * scale); h = int(b["h"] * scale)
        draw.rectangle([x, y, x + w, y + h], outline=(236, 72, 153, 255), width=2)
        tag = str(b["id"])
        tw = max(18, 8 * len(tag) + 4)
        draw.rectangle([x, max(0, y - 16), x + tw, y], fill=(236, 72, 153, 235))
        draw.text((x + 2, max(0, y - 16)), tag, fill="white", font=font)

    out = png_path.with_suffix(".annotated.png")
    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------------------
# Main loop — fetch candidates, build prompt, parse VLM response, push back
# ---------------------------------------------------------------------------

PROMPT = textwrap.dedent("""\
    The image is a desktop screenshot annotated with numbered rectangles. Each
    rectangle is a candidate interactive UI element our detector found.

    For each candidate, decide one of:
      • keep  — it is genuinely interactive (button, link, text input, slider,
        toggle, tab, menu item, …)
      • drop  — it is decoration / a static label / overlaps something else

    Also assign a semantic role (button | link | text_input | toggle | tab |
    menu | other) and a short human label of what the element does.

    Output strictly as a JSON array, no prose, no markdown fences:

    [
      {"id": 1, "keep": true,  "role": "button", "label": "Play"},
      {"id": 2, "keep": false},
      ...
    ]
""")


def main() -> int:
    # Pull current candidates from API
    boxes = requests.get(f"{API}/ocr/boxes", timeout=5).json()["boxes"]
    if not boxes:
        print("no candidates posted to /ocr/boxes yet — run run_consensus.py first")
        return 1

    # Cap the number of candidates per VLM call. 229 in one shot times out;
    # smaller batches fit in the model's attention window and finish in ~10-30s.
    max_per_call = int(os.environ.get("VLM_BATCH", "40"))
    # Sort by tier so we keep the most-likely actionable items first.
    boxes_sorted = sorted(boxes, key=lambda b: (b.get("tier", 4), b["id"]))
    boxes_to_verify = boxes_sorted[:max_per_call]
    print(
        f"verifying {len(boxes_to_verify)}/{len(boxes)} candidates "
        f"(top {max_per_call} by tier) with provider={PROVIDER}"
    )
    boxes = boxes_to_verify

    mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = float(mons[0]["scale_factor"] or 2.0)

    # Use the most recent screenshot on Desktop (taken by run_consensus or trigger_system_screenshot)
    desk = Path.home() / "Desktop"
    candidates = sorted(
        list(desk.glob("截屏*.png")) + list(desk.glob("Screen Shot*.png")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        print("no recent screenshot — run consensus first to capture one")
        return 2
    png_path = candidates[0]
    print(f"using {png_path}")

    annotated = annotate_screenshot(png_path, boxes, scale=scale)
    print(f"annotated → {annotated}")

    if PROVIDER not in PROVIDERS:
        print(f"unknown VLM_PROVIDER {PROVIDER!r}. Valid: {list(PROVIDERS)}")
        return 3

    call = PROVIDERS[PROVIDER]
    t0 = time.time()
    raw = call(annotated, PROMPT)
    print(f"VLM round-trip {time.time()-t0:.2f}s, response length {len(raw)}")

    # Parse JSON (tolerate ```json fences)
    txt = raw.strip()
    if txt.startswith("```"):
        txt = "\n".join(txt.split("\n")[1:-1] if txt.endswith("```") else txt.split("\n")[1:])
    try:
        verdicts = json.loads(txt)
    except json.JSONDecodeError:
        print("Failed to parse VLM JSON. Raw response:\n", raw[:1000])
        return 4

    by_id = {v["id"]: v for v in verdicts if isinstance(v, dict) and "id" in v}
    kept = []
    for b in boxes:
        v = by_id.get(b["id"])
        if v and v.get("keep"):
            b["text"] = f"VLM/{v.get('role','?')}: {v.get('label','')[:40]} | " + b["text"]
            b["tier"] = 1  # VLM-verified = gold
            kept.append(b)

    print(f"VLM kept {len(kept)} of {len(boxes)} candidates")
    # Re-id
    for i, b in enumerate(kept, start=1):
        b["id"] = i

    requests.post(f"{API}/ocr/boxes", json={"boxes": kept, "enable": True}, timeout=5)
    print("posted VLM-verified set → overlay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
