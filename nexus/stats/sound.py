"""Practice › Sound (4.29): hearing where a sound comes from. The page (static/sound.js) plays sounds in 3D with the
browser's HRTF panner (headphones), you click the direction on a radar around you. Direction: anywhere around you.
Distance: also near or far. Height: also above, level or below (Valorant's sounds from another floor).

The sounds are made in the browser (footsteps, a reload, a beep), not taken from Valorant: what's trained is hearing
the direction. This file checks what the page sends and keeps the player's results.

Stored per player in data/profiles/<pid>/stats/sound.json:
  {"runs": [{mode, n, err, fb, right, score, t, d}], "sec": [[sum err, n] x 8]}   (sec: by direction, 0 = in front,
  clockwise in 45° steps)"""
from __future__ import annotations

import math
import time
from datetime import date

MODES = {"dir": "Direction", "dist": "Distance", "height": "Height"}
SOUNDS = 15
MAX_RUNS = 600
SECTORS = ["in front", "front right", "right", "back right", "behind", "back left", "left", "front left"]


def wrap(a: float) -> float:
    return (a + 180) % 360 - 180


def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        return None
    return float(v)


def clean_run(d: dict) -> dict | None:
    """One finished round as the page sends it -> what's stored (with the sounds, for the sector sums), or None."""
    if not isinstance(d, dict) or d.get("mode") not in MODES:
        return None
    sounds = d.get("sounds")
    if not isinstance(sounds, list) or not 1 <= len(sounds) <= 40:
        return None
    rows = []
    for s in sounds:
        if not isinstance(s, dict):
            return None
        a, g = _num(s.get("a"), -180, 360), _num(s.get("guess"), -180, 360)
        if a is None or g is None:
            return None
        err = abs(wrap(g - a))
        fb = err > 90 and abs(wrap(g - (180 - a))) <= 30          # heard it on the wrong side of front/back
        extra = None
        if d["mode"] == "dist":
            extra = s.get("dist") in ("near", "far") and s.get("dist") == s.get("dist_guess")
        elif d["mode"] == "height":
            extra = s.get("h") in ("up", "level", "down") and s.get("h") == s.get("h_guess")
        rows.append({"a": a % 360, "err": err, "fb": fb, "extra": extra})
    n = len(rows)
    score = sum(max(0, 100 - 1.5 * r["err"]) + (50 if r["extra"] else 0) for r in rows)
    run = {"mode": d["mode"], "n": n, "err": round(sum(r["err"] for r in rows) / n, 1), "fb": sum(r["fb"] for r in rows),
           "score": int(round(score)), "t": time.time(), "d": date.today().isoformat(), "sounds": rows}
    if d["mode"] != "dir":
        run["right"] = sum(1 for r in rows if r["extra"])
    return run


def add_run(data: dict, run: dict) -> dict:
    """Into the player's data (the sounds feed the sector sums, they aren't kept) -> {best_before, is_best}."""
    sec = data.setdefault("sec", [[0.0, 0] for _ in SECTORS])
    for r in run.pop("sounds", []):
        k = int(((r["a"] + 22.5) % 360) // 45)
        sec[k][0] = round(sec[k][0] + r["err"], 1)
        sec[k][1] += 1
    runs = data.setdefault("runs", [])
    before = [r["score"] for r in runs if r["mode"] == run["mode"]]
    runs.append(run)
    del runs[:-MAX_RUNS]
    return {"best_before": max(before) if before else None, "is_best": not before or run["score"] > max(before)}


def summary(data: dict) -> dict:
    """Per mode: best, last, rounds, average error of the last five; by direction: average error; front/back mix-ups
    in the last five rounds."""
    runs = data.get("runs", [])
    modes = {}
    for k, name in MODES.items():
        xs = [r for r in runs if r["mode"] == k]
        last5 = xs[-5:]
        modes[k] = {"name": name, "rounds": len(xs), "best": max((r["score"] for r in xs), default=None),
                    "last": xs[-1]["score"] if xs else None,
                    "err": round(sum(r["err"] * r["n"] for r in last5) / max(1, sum(r["n"] for r in last5)), 1) if xs else None,
                    "right": (round(sum(r.get("right", 0) for r in last5) / max(1, sum(r["n"] for r in last5)), 2)
                              if xs and k != "dir" else None)}
    sec = data.get("sec") or [[0.0, 0] for _ in SECTORS]
    by = [{"name": SECTORS[i], "err": round(s / n, 1) if n else None, "n": n, "d": _wedge(i)} for i, (s, n) in enumerate(sec)]
    known = [x for x in by if x["n"] >= 3]
    last5 = runs[-5:]
    return {"modes": modes, "sectors": by, "worst": max(known, key=lambda x: x["err"])["name"] if known else None,
            "fb": sum(r["fb"] for r in last5), "fb_of": sum(r["n"] for r in last5), "rounds": len(runs)}


def _wedge(i: int, r: int = 100) -> str:
    """SVG path of sector i (0 = in front, at the top; clockwise) on a circle of radius r around 0,0."""
    a0, a1 = math.radians(i * 45 - 22.5 - 90), math.radians(i * 45 + 22.5 - 90)
    return (f"M0,0 L{r * math.cos(a0):.1f},{r * math.sin(a0):.1f} "
            f"A{r},{r} 0 0 1 {r * math.cos(a1):.1f},{r * math.sin(a1):.1f} Z")
