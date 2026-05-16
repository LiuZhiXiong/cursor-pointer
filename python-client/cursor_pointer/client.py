"""HTTP client for the CursorPointer desktop daemon.

The Tauri app exposes a localhost JSON API; this module wraps it so AI
pipelines can drive the cursor without dealing with HTTP plumbing.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Iterable, Literal, Optional, Sequence

import requests

Button = Literal["left", "right", "middle"]


class CursorPointerError(RuntimeError):
    """Raised when the daemon returns an error response."""


@dataclass
class Monitor:
    index: int
    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool
    scale_factor: float


class CursorPointer:
    """Thin client over the CursorPointer HTTP API."""

    def __init__(self, base_url: str = "http://127.0.0.1:39213", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        # Opt-in HTTP trace — set CURSOR_POINTER_TRACE=1 to log every API call.
        import os
        self._trace = os.environ.get("CURSOR_POINTER_TRACE") == "1"

    # ----- low level -----

    def _log(self, method: str, path: str, payload: Optional[dict] = None) -> None:
        if not self._trace:
            return
        import json
        body = json.dumps(payload, ensure_ascii=False) if payload else ""
        print(f"  [cp] {method:4} {path}  {body}")

    def _post(self, path: str, payload: Optional[dict] = None) -> dict:
        self._log("POST", path, payload)
        r = self._session.post(
            f"{self.base_url}{path}", json=payload or {}, timeout=self.timeout
        )
        return self._unwrap(r)

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        self._log("GET", path, params)
        r = self._session.get(
            f"{self.base_url}{path}", params=params or {}, timeout=self.timeout
        )
        return self._unwrap(r)

    @staticmethod
    def _unwrap(r: requests.Response) -> dict:
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", r.text)
            except Exception:
                detail = r.text
            raise CursorPointerError(f"{r.status_code}: {detail}")
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return {"_raw": r.content}

    # ----- health / info -----

    def health(self) -> dict:
        return self._get("/health")

    def monitors(self) -> list[Monitor]:
        data = self._get("/screen/monitors")
        return [Monitor(**m) for m in data]  # type: ignore[arg-type]

    # ----- mouse -----

    def move(self, x: int, y: int) -> None:
        self._post("/mouse/move", {"x": int(x), "y": int(y)})

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: Button = "left",
        count: int = 1,
    ) -> None:
        body: dict = {"button": button, "count": int(count)}
        if x is not None and y is not None:
            body["x"], body["y"] = int(x), int(y)
        self._post("/mouse/click", body)

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        self.click(x, y, count=2)

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        self.click(x, y, button="right")

    def mouse_down(self, button: Button = "left") -> None:
        self._post("/mouse/down", {"button": button})

    def mouse_up(self, button: Button = "left") -> None:
        self._post("/mouse/up", {"button": button})

    def drag(
        self,
        from_xy: tuple[int, int],
        to_xy: tuple[int, int],
        button: Button = "left",
    ) -> None:
        self.move(*from_xy)
        self.mouse_down(button)
        self.move(*to_xy)
        self.mouse_up(button)

    def clipboard_get(self) -> str:
        return self._get("/clipboard/get")["text"]

    def clipboard_set(self, text: str) -> None:
        self._post("/clipboard/set", {"text": text})

    def scroll(
        self,
        dy: int = 0,
        dx: int = 0,
        x: Optional[int] = None,
        y: Optional[int] = None,
    ) -> None:
        body: dict = {"dx": int(dx), "dy": int(dy)}
        if x is not None and y is not None:
            body["x"], body["y"] = int(x), int(y)
        self._post("/mouse/scroll", body)

    def position(self) -> tuple[int, int]:
        data = self._get("/mouse/position")
        return int(data["x"]), int(data["y"])

    # ----- keyboard -----

    def type_text(self, text: str) -> None:
        self._post("/keyboard/type", {"text": text})

    def key(self, key: str, modifiers: Optional[Sequence[str]] = None) -> None:
        self._post("/keyboard/key", {"key": key, "modifiers": list(modifiers or [])})

    def hotkey(self, *keys: str) -> None:
        """Press a combo like hotkey("cmd", "shift", "4")."""
        if not keys:
            return
        *mods, target = keys
        self.key(target, modifiers=list(mods))

    def key_down(self, key: str) -> None:
        self._post("/keyboard/down", {"key": key})

    def key_up(self, key: str) -> None:
        self._post("/keyboard/up", {"key": key})

    # ----- screen -----

    def screenshot(self, monitor: int = 0, as_pil: bool = False, timeout: float = 30.0):
        """Return PNG bytes (default) or a PIL Image if as_pil=True."""
        r = self._session.get(
            f"{self.base_url}/screen/screenshot",
            params={"monitor": monitor, "format": "png"},
            timeout=timeout,
        )
        if r.status_code >= 400:
            raise CursorPointerError(f"{r.status_code}: {r.text}")
        png = r.content
        if not as_pil:
            return png
        from PIL import Image  # lazy import

        return Image.open(io.BytesIO(png))

    def screenshot_data_url(self, monitor: int = 0) -> str:
        data = self._get("/screen/screenshot", {"monitor": monitor})
        return data["image"]
