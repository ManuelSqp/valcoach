"""Measurable goals and whether they were met (4.15).

A goal is one number from the progress metrics (stats/progress.py, e.g. "Deaths traded" or "First duels
won"), a target, and the games it has to happen in (default GOAL_GAMES). It is checked automatically against
the games played after it was set: reached as soon as the number over those games meets the target (with at
least MIN_GAMES), missed when the window is over without it.

Goals come from the weekly focus (its "number to watch"), from a habit ("Make this a goal") or are set by
hand on the Habits page. The coach sees every open goal and the ones closed in the last LOOKBACK_DAYS with
their result, so it doesn't repeat advice that didn't move the number and builds on what worked.

Kept per player in profiles/<id>/stats/goals.json.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .progress import METRICS, fmt, value

GOAL_GAMES = 10
MIN_GAMES = 3
MAX_OPEN = 6
LOOKBACK_DAYS = 60


def _when(r: dict) -> str:
    return str(r.get("started_at") or "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GoalStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[dict]:
        try:
            d = json.loads(self.path.read_text())
            return [g for g in d.get("goals", []) if isinstance(g, dict) and g.get("metric") in METRICS]
        except (OSError, ValueError, AttributeError):
            return []

    def save(self, goals: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"goals": goals[-80:]}, ensure_ascii=False))
        tmp.replace(self.path)

    def add(self, metric: str, target: float, rows: list[dict], text: str = "", source: str = "you",
            games: int = GOAL_GAMES, start: str | None = None) -> dict | None:
        """A new open goal; an open goal on the same metric is replaced. None if the metric is unknown."""
        if metric not in METRICS:
            return None
        start = start or _now_iso()
        before = [r for r in rows if _when(r) < start]
        goals = [g for g in self.load() if not (g["metric"] == metric and g.get("state", "open") == "open")]
        g = {"id": uuid.uuid4().hex[:10], "metric": metric, "target": float(target),
             "baseline": value(before[-20:] if before else [], metric), "start": start,
             "games": max(3, min(30, int(games))), "text": (text or "").strip()[:200], "source": source,
             "state": "open", "created": time.time()}
        open_ = [x for x in goals if x.get("state", "open") == "open"]
        if len(open_) >= MAX_OPEN:                     # the oldest open goal makes room
            oldest = min(open_, key=lambda x: x.get("created", 0))
            oldest["state"], oldest["closed"] = "dropped", _now_iso()
        goals.append(g)
        self.save(goals)
        return g

    def drop(self, gid: str) -> bool:
        goals = self.load()
        for g in goals:
            if g["id"] == gid and g.get("state", "open") == "open":
                g["state"], g["closed"] = "dropped", _now_iso()
                self.save(goals)
                return True
        return False

    def refresh(self, rows: list[dict]) -> list[dict]:
        """Checks every open goal against the games since it was set, closes the finished ones (saved), and
        returns all goals with their check, newest first."""
        goals = self.load()
        changed = False
        out = []
        for g in goals:
            ck = check(g, rows)
            if g.get("state", "open") == "open" and ck["state"] != "open":
                g["state"], g["closed"], g["final"] = ck["state"], _now_iso(), ck["now"]
                changed = True
            out.append({**g, **ck, "state": g.get("state", "open")})
        if changed:
            self.save(goals)
        return sorted(out, key=lambda g: (g["state"] != "open", -(g.get("created") or 0)))


def higher_is_better(metric: str) -> bool:
    return METRICS[metric][3]


def met(metric: str, v: float | None, target: float) -> bool:
    if v is None:
        return False
    return v >= target if higher_is_better(metric) else v <= target


def check(g: dict, rows: list[dict]) -> dict:
    """{label, now, played, left, progress 0..1, state (open / reached / missed), verdict}."""
    metric, target = g["metric"], float(g["target"])
    full = METRICS[metric][4]
    after = sorted((r for r in rows if _when(r) >= g.get("start", "") and (not full or r.get("source") == "full")),
                   key=_when)[: g.get("games", GOAL_GAMES)]
    now = value(after, metric) if len(after) >= MIN_GAMES else None
    played, window = len(after), g.get("games", GOAL_GAMES)
    state = g.get("state", "open")
    if state == "open":
        if now is not None and met(metric, now, target):
            state = "reached"
        elif played >= window:
            state = "missed"
    base = g.get("baseline")
    if base is not None and now is not None and base != target:
        prog = max(0.0, min(1.0, (now - base) / (target - base)))
    else:
        prog = 1.0 if state == "reached" else 0.0
    verdict = {"reached": "reached", "missed": "missed", "dropped": "dropped"}.get(state)
    if verdict is None:
        verdict = f"{played} of {window} games" if played else "no games yet"
    return {"label": METRICS[metric][0], "now": now if state != "dropped" else g.get("final"), "played": played,
            "left": max(0, window - played), "progress": prog, "state": state, "verdict": verdict,
            "now_text": fmt(metric, now), "target_text": fmt(metric, target), "baseline_text": fmt(metric, base)}


def facts(goals: list[dict], now: datetime | None = None) -> list[dict]:
    """Open goals and the ones closed recently, for the coach."""
    cut = ((now or datetime.now(timezone.utc)) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out = []
    for g in goals:
        if g.get("state") != "open" and (g.get("closed") or "") < cut:
            continue
        out.append({"goal": g.get("text") or g["label"], "metric": g["label"], "before": g["baseline_text"],
                    "target": g["target_text"], "now": g["now_text"], "games": f"{g['played']} of {g['games']}",
                    "result": g["state"] if g["state"] != "open" else "in progress", "from": g.get("source", "")})
    return out[:10]


def parse_target(metric: str, text) -> float | None:
    """"45 %" / "0.45" / "1.1" -> the metric's unit (percent metrics as 0..1)."""
    import re
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(text or ""))
    if not m:
        return None
    v = float(m.group(0).replace(",", "."))
    if METRICS[metric][2] == "pct" and (v > 1 or "%" in str(text)):
        v /= 100
    return v
