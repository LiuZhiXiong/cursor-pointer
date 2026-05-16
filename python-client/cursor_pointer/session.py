"""Session: an append-only event log + last-N annotations for the agent loop.

The Session is intentionally simple — a JSONL file on disk with every
screenshot/annotate/click/key/scroll/observe event in order. Any agent (yours
or a notebook script) can replay history, ground the model with prior steps,
or compute "what changed since action #N".

Layout under ``base_dir``::

    session-<id>/
      events.jsonl          one JSON object per line
      annotations/          *.png + *.json (one per annotate call)
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .annotate import Annotation, annotate, click_element
from .client import CursorPointer


@dataclass
class Event:
    seq: int
    timestamp: float
    kind: str                 # screenshot | annotate | click | move | scroll | key | type | observe | note
    data: dict[str, Any] = field(default_factory=dict)


class Session:
    """An agent's per-task scratchpad backed by a directory."""

    def __init__(
        self,
        client: CursorPointer,
        *,
        base_dir: Optional[Path] = None,
        session_id: Optional[str] = None,
    ):
        self.client = client
        sid = session_id or uuid.uuid4().hex[:10]
        self.id = sid
        base = Path(base_dir or "/tmp/cursor-pointer-sessions") / f"session-{sid}"
        base.mkdir(parents=True, exist_ok=True)
        (base / "annotations").mkdir(exist_ok=True)
        self.dir = base
        self.log_path = base / "events.jsonl"
        self._seq = 0
        self._annotations: dict[str, Annotation] = {}

    # ----- bookkeeping -----

    def _log(self, kind: str, data: dict[str, Any]) -> Event:
        self._seq += 1
        ev = Event(seq=self._seq, timestamp=time.time(), kind=kind, data=data)
        with self.log_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(ev), ensure_ascii=False) + "\n")
        return ev

    def note(self, text: str) -> Event:
        return self._log("note", {"text": text})

    def events(self) -> Iterable[Event]:
        if not self.log_path.exists():
            return
        for line in self.log_path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            yield Event(**d)

    def history_summary(self, last_n: int = 20) -> str:
        """Compact text summary of recent events — useful for LLM context."""
        lines = []
        evs = list(self.events())[-last_n:]
        for ev in evs:
            if ev.kind == "click":
                lines.append(f"#{ev.seq} click {ev.data.get('button','left')} @ {ev.data.get('x')},{ev.data.get('y')}  ({ev.data.get('label','')})")
            elif ev.kind == "type":
                lines.append(f"#{ev.seq} type {ev.data.get('text')!r}")
            elif ev.kind == "key":
                mods = "+".join(ev.data.get("modifiers", []))
                lines.append(f"#{ev.seq} key {mods}+{ev.data.get('key')}" if mods else f"#{ev.seq} key {ev.data.get('key')}")
            elif ev.kind == "scroll":
                lines.append(f"#{ev.seq} scroll dx={ev.data.get('dx',0)} dy={ev.data.get('dy',0)}")
            elif ev.kind == "annotate":
                lines.append(f"#{ev.seq} annotate {ev.data.get('annotation_id')} ({ev.data.get('count')} elements)")
            elif ev.kind == "note":
                lines.append(f"#{ev.seq} note: {ev.data.get('text')}")
            else:
                lines.append(f"#{ev.seq} {ev.kind} {ev.data}")
        return "\n".join(lines)

    # ----- high-level actions -----

    def screenshot(self) -> Path:
        png = self.client.screenshot()
        out = self.dir / f"shot-{self._seq+1:04d}.png"
        out.write_bytes(png)
        self._log("screenshot", {"path": str(out)})
        return out

    def annotate(self, *, monitor: int = 0, min_score: float = 0.45) -> Annotation:
        ann = annotate(
            self.client,
            monitor=monitor,
            min_score=min_score,
            save_dir=self.dir / "annotations",
        )
        self._annotations[ann.id] = ann
        self._log(
            "annotate",
            {
                "annotation_id": ann.id,
                "image": str(ann.image_path),
                "count": len(ann.elements),
                "elements": [e.to_dict() for e in ann.elements],
            },
        )
        return ann

    def get_annotation(self, annotation_id: str) -> Annotation:
        if annotation_id in self._annotations:
            return self._annotations[annotation_id]
        # Reload from disk
        for f in (self.dir / "annotations").glob(f"{annotation_id}.json"):
            d = json.loads(f.read_text())
            from .annotate import Annotation, Element
            from .client import Monitor
            ann = Annotation(
                id=d["id"],
                monitor=Monitor(**d["monitor"]),
                elements=[Element(**{**e, "bbox": tuple(e["bbox"]), "bbox_px": tuple(e["bbox_px"])}) for e in d["elements"]],
                image_path=Path(d["image_path"]),
                raw_path=Path(d["raw_path"]),
                timestamp=d["timestamp"],
            )
            self._annotations[annotation_id] = ann
            return ann
        raise KeyError(annotation_id)

    def click_element(
        self,
        annotation_id: str,
        element_id: int,
        *,
        button: str = "left",
        count: int = 1,
    ) -> tuple[int, int]:
        ann = self.get_annotation(annotation_id)
        el = ann.by_id(element_id)
        x, y = el.center
        self.client.click(x, y, button=button, count=count)
        self._log(
            "click",
            {
                "x": x, "y": y, "button": button, "count": count,
                "annotation_id": annotation_id, "element_id": element_id,
                "label": el.text,
            },
        )
        return x, y

    def click(self, x: int, y: int, *, button: str = "left", count: int = 1) -> None:
        self.client.click(x, y, button=button, count=count)
        self._log("click", {"x": x, "y": y, "button": button, "count": count})

    def type_text(self, text: str) -> None:
        self.client.type_text(text)
        self._log("type", {"text": text})

    def key(self, key: str, modifiers: Optional[list[str]] = None) -> None:
        self.client.key(key, modifiers=modifiers or [])
        self._log("key", {"key": key, "modifiers": modifiers or []})

    def scroll(self, dy: int = 0, dx: int = 0) -> None:
        self.client.scroll(dy=dy, dx=dx)
        self._log("scroll", {"dx": dx, "dy": dy})
