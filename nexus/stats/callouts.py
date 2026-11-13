"""Practice › Callouts: a quiz on the minimap (static/callouts.js). Find it: a callout's name is shown, click where it
is. Name it: a spot lights up, pick its name. Learn: every callout on the map, to look at first.

The callouts and where they are come from valorant-api.com's maps (maps.py, the same as the strat board). This file
is what the server knows: which maps have enough callouts, the points per map, checking what the page sends and the
player's results.

Stored per player in data/profiles/<pid>/stats/callouts.json:
  {"runs": [{map, mode, right, total, score, ms, t, d}], "miss": {map: {label: [wrong, asked]}}}"""
from __future__ import annotations

import time
from datetime import date

MODES = {"find": "Find it", "name": "Name it"}
QUESTIONS = 12
MIN_CALLOUTS = 8
MAX_RUNS = 600


def points(mi) -> list[dict]:
    """A map's callouts as minimap points: [{label, u, v, area}] (no spawns, every name once)."""
    out, seen = [], set()
    for c in mi.callouts if mi else []:
        if c.region.lower() == "spawn" or c.label in seen:
            continue
        seen.add(c.label)
        u, v = mi.to_uv(c.x, c.y)
        if not (-0.05 <= u <= 1.05 and -0.05 <= v <= 1.05):
            continue
        out.append({"label": c.label, "u": round(u, 4), "v": round(v, 4), "area": c.super_region})
    return out


def quiz_maps(reg, names: list[str]) -> dict[str, list[dict]]:
    """Map name -> points, for the maps with enough callouts for a quiz (in the order given)."""
    out: dict[str, list[dict]] = {}
    for n in names:
        try:
            mi = reg.get(name=n)
        except Exception:
            mi = None
        pts = points(mi)
        if len(pts) >= MIN_CALLOUTS:
            out[n] = pts
    return out


def clean_run(d: dict, maps: dict[str, list[dict]]) -> dict | None:
    """One finished round as the page sends it -> what's stored, or None if it doesn't add up."""
    if not isinstance(d, dict) or d.get("map") not in maps or d.get("mode") not in MODES:
        return None
    labels = {p["label"] for p in maps[d["map"]]}
    asked = d.get("asked")
    if not isinstance(asked, list) or not 1 <= len(asked) <= 40:
        return None
    rows = []
    for a in asked:
        if not isinstance(a, dict) or a.get("label") not in labels or not isinstance(a.get("ok"), bool):
            return None
        ms = a.get("ms")
        ms = int(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) and 0 <= ms <= 120000 else None
        rows.append({"label": a["label"], "ok": a["ok"], "ms": ms})
    right = sum(r["ok"] for r in rows)
    score = sum(100 + max(0, 50 - (r["ms"] or 5000) // 100) for r in rows if r["ok"])
    times = [r["ms"] for r in rows if r["ok"] and r["ms"] is not None]
    return {"map": d["map"], "mode": d["mode"], "right": right, "total": len(rows), "score": int(score),
            "ms": int(sum(times) / len(times)) if times else None, "t": time.time(), "d": date.today().isoformat(),
            "asked": rows}


def add_run(data: dict, run: dict) -> dict:
    """Into the player's data (the asked list feeds the miss counts, it isn't kept) -> {best_before, is_best}."""
    asked = run.pop("asked", [])
    miss = data.setdefault("miss", {}).setdefault(run["map"], {})
    for a in asked:
        w = miss.setdefault(a["label"], [0, 0])
        w[1] += 1
        if not a["ok"]:
            w[0] += 1
    runs = data.setdefault("runs", [])
    before = [r["score"] for r in runs if r["map"] == run["map"] and r["mode"] == run["mode"]]
    runs.append(run)
    del runs[:-MAX_RUNS]
    return {"best_before": max(before) if before else None, "is_best": not before or run["score"] > max(before)}


def summary(data: dict, maps: dict[str, list[dict]]) -> list[dict]:
    """Per map: best and last per mode, rounds played, how many callouts you know (asked at least twice, wrong at
    most a quarter of the time) and the weakest ones."""
    runs = data.get("runs", [])
    out = []
    for m, pts in maps.items():
        mr = [r for r in runs if r["map"] == m]
        modes = {}
        for k in MODES:
            xs = [r for r in mr if r["mode"] == k]
            modes[k] = {"best": max((r["score"] for r in xs), default=None), "last": xs[-1]["score"] if xs else None,
                        "acc": round(sum(r["right"] for r in xs[-5:]) / max(1, sum(r["total"] for r in xs[-5:])), 2) if xs else None}
        miss = data.get("miss", {}).get(m, {})
        labels = {p["label"] for p in pts}
        known = sum(1 for lb, (w, n) in miss.items() if lb in labels and n >= 2 and w / n <= 0.25)
        weak = sorted(((lb, w, n) for lb, (w, n) in miss.items() if lb in labels and w), key=lambda x: (-x[1] / x[2], -x[1]))
        out.append({"map": m, "n": len(pts), "rounds": len(mr), "known": known, "modes": modes,
                    "weak": [{"label": lb, "wrong": w, "asked": n} for lb, w, n in weak[:5]]})
    return out


def weights(data: dict, map_name: str, pts: list[dict]) -> dict[str, float]:
    """How likely each callout is asked: more often the ones you get wrong or haven't seen yet."""
    miss = data.get("miss", {}).get(map_name, {})
    out = {}
    for p in pts:
        w, n = miss.get(p["label"], (0, 0))
        out[p["label"]] = round(1.0 + 2.5 * (w + 1) / (n + 2) + (0.8 if n == 0 else 0), 3)
    return out


def weak(data: dict, map_name: str) -> list[str]:
    """The callouts you get wrong at least a third of the time (asked at least twice)."""
    return sorted(lb for lb, (w, n) in data.get("miss", {}).get(map_name, {}).items() if n >= 2 and w / n >= 1 / 3)
