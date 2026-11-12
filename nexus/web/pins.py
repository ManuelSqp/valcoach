"""Notes on the round playback (4.18 review evening, 4.20 also personal reports): a moment, a line of text and
lines drawn on the map (0..1000 board units). One cleaner for every place that stores them."""
from __future__ import annotations

import secrets
import time

MAX_TEXT = 300
MAX_PER_ROUND = 40
MAX_STROKES = 12
MAX_STROKE_PTS = 300


def clean(b: dict, by: str, by_id: int) -> tuple[dict | None, str | None]:
    """{t (ms), text, strokes} as sent by the page -> (a note to store, None) or (None, error)."""
    try:
        t_ms = max(0, min(300_000, int(b.get("t"))))
    except (TypeError, ValueError):
        return None, "unknown time"
    text = str(b.get("text") or "").strip()[:MAX_TEXT]
    strokes = []
    for st in (b.get("strokes") or [])[:MAX_STROKES]:
        if not isinstance(st, list):
            continue
        pts = []
        for p in st[:MAX_STROKE_PTS]:
            try:
                pts.append([max(0, min(1000, int(p[0]))), max(0, min(1000, int(p[1])))])
            except (TypeError, ValueError, IndexError):
                continue
        if len(pts) >= 2:
            strokes.append(pts)
    if not text and not strokes:
        return None, "write something or draw on the map"
    return {"id": secrets.token_hex(4), "t": t_ms, "text": text, "strokes": strokes, "by": by, "by_id": by_id,
            "created": time.time()}, None


def apply(pins: dict, b: dict, act: str, n: int, by: str, by_id: int, may_delete_all: bool) -> str | None:
    """Add ("pin") or remove ("unpin") a note in round n of pins ({round: [note, ...]}). Returns an error or None."""
    key = str(n)
    lst = pins.setdefault(key, [])
    if act == "unpin":
        pid = str(b.get("id") or "")
        p = next((x for x in lst if x["id"] == pid), None)
        if p is None:
            err = "unknown note"
        elif not (may_delete_all or p.get("by_id") == by_id):
            err = "not yours"
        else:
            lst.remove(p)
            err = None
    else:
        note, err = clean(b, by, by_id)
        if note is not None:
            if len(lst) >= MAX_PER_ROUND:
                err = "too many notes in this round"
            else:
                lst.append(note)
                lst.sort(key=lambda x: x["t"])
    if not lst:
        pins.pop(key, None)
    return err
