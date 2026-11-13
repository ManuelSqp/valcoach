"""VOD review (4.31): a match recording (the one a coaching report was made with, e.g. cut from Medal by the Nexus app)
watched together: pause, draw on the frame, leave a comment at that moment. The team sees the comments and the
drawings at their time in the video; round markers come from the report (round starts in the recording).

Stored per report in data/vodreview/<job id>.json: {"notes": [{id, t, round, text, strokes, by, uid, at}]}
strokes: [{c: colour, k: "pen" | "arrow" | "circle", p: [[x, y], ...]}], x and y 0..1 of the frame."""
from __future__ import annotations

import secrets
import time

COLORS = ("#ffd166", "#ef476f", "#06d6a0", "#4cc9f0", "#ffffff")
KINDS = ("pen", "arrow", "circle")
MAX_NOTES = 500
MAX_STROKES = 40
MAX_POINTS = 300


def _xy(p) -> list[float] | None:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        return None
    x, y = p
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (x, y)):
        return None
    if not (-0.05 <= x <= 1.05 and -0.05 <= y <= 1.05):
        return None
    return [round(float(x), 4), round(float(y), 4)]


def clean_note(d: dict) -> tuple[dict | None, str]:
    """A comment from the page -> ({t, text, strokes}, "") or (None, what's wrong)."""
    if not isinstance(d, dict):
        return None, "That isn't a comment."
    t = d.get("t")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 6 * 3600:
        return None, "The time in the video is missing."
    text = " ".join(str(d.get("text") or "").split())[:600]
    strokes = []
    for s in (d.get("strokes") or [])[:MAX_STROKES]:
        if not isinstance(s, dict) or s.get("c") not in COLORS or s.get("k", "pen") not in KINDS:
            continue
        pts = [q for q in (_xy(p) for p in (s.get("p") or [])[:MAX_POINTS]) if q]
        if len(pts) >= 2:
            strokes.append({"c": s["c"], "k": s.get("k", "pen"), "p": pts})
    if not text and not strokes:
        return None, "Write something or draw on the frame first."
    return {"t": round(float(t), 2), "text": text, "strokes": strokes}, ""


def round_at(t: float, rounds: list[dict]) -> int | None:
    """The round a moment of the recording belongs to (the last round that started before it)."""
    cur = None
    for r in rounds:
        if r.get("t") is not None and r["t"] <= t + 0.5:
            cur = r["n"]
    return cur


def add_note(data: dict, note: dict, uid: int, by: str, rounds: list[dict]) -> dict:
    n = dict(note, id=secrets.token_hex(4), uid=uid, by=by, at=time.time(), round=round_at(note["t"], rounds))
    lst = data.setdefault("notes", [])
    lst.append(n)
    lst.sort(key=lambda x: x["t"])
    del lst[MAX_NOTES:]
    return n


def rounds_of(report: dict | None) -> list[dict]:
    """Round starts in the recording from a coaching report: [{n, t, won}] (rounds without a time left out)."""
    out = []
    for r in (report or {}).get("rounds") or []:
        t = (r.get("vod") or {}).get("start")
        if isinstance(t, (int, float)) and t >= 0:
            out.append({"n": r.get("number"), "t": round(float(t), 2), "won": bool((r.get("team_facts") or {}).get("won"))})
    return sorted(out, key=lambda x: x["t"])
