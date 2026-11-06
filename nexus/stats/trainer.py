"""Practice › Aim trainer: Nexus's own aim trainer in the browser (static/trainer.js) and the mouse & monitor check
(static/gearcheck.js). This file is what the server knows about them: the scenarios, which ones today's warm-up
and training play (from what the matches show, stats/aim.py needs()), checking what a page sends, scores per
scenario, and the Valorant numbers (eDPI, cm per 360).

Stored per player in data/profiles/<pid>/stats/trainer.json:
  {"runs": [{s, score, t, d, hits, shots, ms, acc}], "setup": {sens, dpi, measured_dpi, ...}}"""
from __future__ import annotations

import math
import time
from datetime import date

from . import kovaaks as kv

VALORANT_YAW = 0.07                 # degrees per mouse count at sensitivity 1 (Valorant)
MAX_RUNS = 2000

# id -> what it is. "kind": click (score from hits, speed and accuracy) or track (time on target).
# The page (trainer.js) has the matching behaviour under the same id.
SCENARIOS: dict[str, dict] = {
    "grid": {"name": "Grid flicks", "kind": "click", "seconds": 60, "focus": ["flicks", "switching", "warmup"],
             "about": "Three targets on a wall: hit one, the next appears somewhere else. Fast, clean flicks."},
    "headline": {"name": "Head-line flicks", "kind": "click", "seconds": 45, "focus": ["crosshair", "flicks", "warmup"],
                 "about": "Small targets anywhere left or right, always at head height. Flick sideways, never up or down."},
    "micro": {"name": "Micro taps", "kind": "click", "seconds": 45, "focus": ["micro", "crosshair"],
              "about": "Tiny targets far away, each close to the last one. Small, calm corrections."},
    "peek": {"name": "Peek reaction", "kind": "click", "seconds": 45, "focus": ["peeking", "reaction", "flicks"],
             "about": "Enemies peek out from behind cover for a moment. Hit them before they're gone."},
    "track": {"name": "Strafe tracking", "kind": "track", "seconds": 45, "focus": ["tracking", "spray"],
              "about": "One target strafes left and right like a player. Hold the mouse button and stay on it."},
}
PLANS = {"warmup": "Warm-up", "training": "Training"}
WARMUP = [("grid", 30), ("headline", 30), ("micro", 30)]       # short and the same every day


def scenario_list() -> list[dict]:
    return [dict(v, id=k) for k, v in SCENARIOS.items()]


def plan(kind: str, need: list[dict], runs: list[dict]) -> dict:
    """Today's warm-up (always the same three, short) or training: the scenarios that fit what the matches show
    (stats/aim.py needs()), the one that's furthest below its best first, two rounds each.
    -> {kind, name, minutes, items: [{id, name, seconds, why}]}"""
    if kind == "warmup":
        items = [{"id": s, "name": SCENARIOS[s]["name"], "seconds": sec, "why": "warm-up"} for s, sec in WARMUP]
    else:
        weight: dict[str, float] = {}
        why: dict[str, str] = {}
        for x in need:
            for s, d in SCENARIOS.items():
                hit = len(set(d["focus"]) & set(x["focus"]))
                if hit:
                    weight[s] = weight.get(s, 0) + hit * x["weight"]
                    why.setdefault(s, x["why"])
        picked = sorted(weight, key=lambda s: -weight[s])[:3] or ["grid", "headline", "track"]
        for s in ("grid", "track", "headline"):                      # always three different ones
            if len(picked) >= 3:
                break
            if s not in picked:
                picked.append(s)
        gap = {x["name"]: (x["best"] - x["last"]) / x["best"] if x["best"] else 0 for x in kv.summary(runs)}
        picked.sort(key=lambda s: -gap.get(s, 0))
        items = [{"id": s, "name": SCENARIOS[s]["name"], "seconds": SCENARIOS[s]["seconds"],
                  "why": why.get(s, "a bit of everything")} for s in picked for _ in range(2)]
    return {"kind": kind, "name": PLANS[kind], "minutes": math.ceil(sum(i["seconds"] + 5 for i in items) / 60),
            "items": items}


def _num(v, lo: float, hi: float, digits: int = 2) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        return None
    return round(float(v), digits)


def clean_run(d: dict) -> dict | None:
    """One finished run as the page sends it -> what's stored, or None if it doesn't add up."""
    if not isinstance(d, dict) or d.get("scenario") not in SCENARIOS:
        return None
    sc = SCENARIOS[d["scenario"]]
    seconds = _num(d.get("seconds"), 10, 600, 1)
    score = _num(d.get("score"), 0, 100000, 0)
    if seconds is None or score is None:
        return None
    out = {"s": d["scenario"], "score": score, "sec": seconds, "t": time.time(), "d": date.today().isoformat()}
    if sc["kind"] == "click":
        hits = _num(d.get("hits"), 0, 2000, 0)
        shots = _num(d.get("shots"), 0, 5000, 0)
        if hits is None or shots is None or hits > shots:
            return None
        out.update(hits=int(hits), shots=int(shots), acc=round(hits / shots, 3) if shots else 0.0)
        ms = _num(d.get("ms"), 0, 5000, 0)
        if ms is not None and hits:
            out["ms"] = int(ms)
    else:
        on = _num(d.get("on_target"), 0, 1, 3)
        if on is None:
            return None
        out["on"] = on
    return out


def add_run(data: dict, run: dict) -> dict:
    """Into the player's trainer data -> {best_before, is_best}."""
    runs = data.setdefault("runs", [])
    before = [r["score"] for r in runs if r["s"] == run["s"]]
    runs.append(run)
    del runs[:-MAX_RUNS]
    return {"best_before": max(before) if before else None, "is_best": not before or run["score"] > max(before)}


def summary(runs: list[dict]) -> list[dict]:
    """Per scenario (in the scenarios' order): runs, best, last, recent scores, trend, steady at best."""
    by = {x["name"]: x for x in kv.summary(runs)}
    out = []
    for sid, sc in SCENARIOS.items():
        x = by.get(sid)
        acc = [r["acc"] for r in runs if r["s"] == sid and "acc" in r][-10:]
        out.append({"id": sid, "name": sc["name"], "focus": sc["focus"], "runs": x["runs"] if x else 0,
                    "best": x["best"] if x else None, "last": x["last"] if x else None,
                    "spark": x["spark"] if x else [], "trend": x["trend"] if x else None,
                    "steady": bool(x and x["mastered"]), "last_day": x["last_day"] if x else None,
                    "acc": sum(acc) / len(acc) if acc else None})
    return out


SETUP_KEYS = {"sens": (0.01, 20, 3), "dpi": (50, 64000, 0), "measured_dpi": (20, 100000, 0),
              "polling_hz": (10, 16000, 0), "refresh_hz": (20, 1000, 0), "scale": (0.25, 4, 3)}


def clean_setup(d: dict) -> dict:
    """The settings the pages save (Valorant sensitivity and mouse DPI) and what the check measured."""
    out: dict = {}
    if not isinstance(d, dict):
        return out
    for k, (lo, hi, digits) in SETUP_KEYS.items():
        if k in d:
            v = _num(d[k], lo, hi, digits)
            if v is not None:
                out[k] = int(v) if digits == 0 else v
    if "raw" in d and isinstance(d["raw"], bool):
        out["raw"] = d["raw"]
    return out


def numbers(setup: dict) -> dict:
    """eDPI and how many cm one full turn takes in Valorant, with the DPI you set and the DPI measured."""
    sens, dpi, real = setup.get("sens"), setup.get("dpi"), setup.get("measured_dpi")
    out: dict = {}
    if sens and dpi:
        out["edpi"] = round(sens * dpi)
        out["cm360"] = round(360 / (VALORANT_YAW * sens) / dpi * 2.54, 1)
    if sens and real:
        out["cm360_real"] = round(360 / (VALORANT_YAW * sens) / real * 2.54, 1)
    if dpi and real:
        out["dpi_off"] = round((real - dpi) / dpi, 3)
    return out


# ---------------------------------------------------------------------- sens finder
# The page plays a 20-second mixed test (flicks, micro corrections, tracking) at several sensitivities, blind and in
# random order: round 1 from 70% to 130% of the current sens, round 2 close around round 1's best. Each test sends
# its click score (points × accuracy), time on the moving target, and how the flicks went (overshoot: past the
# target; undershoot: stopped short and needed another correction). Sessions are kept; the recommendation uses all
# of the last 90 days, each session scaled to its own best so a good or bad day doesn't count more.
SENS_KEEP_DAYS = 90
MAX_SESSIONS = 60


def clean_sens_session(d: dict) -> dict | None:
    if not isinstance(d, dict):
        return None
    base = _num(d.get("base"), 0.01, 20, 4)
    tests = d.get("tests")
    if base is None or not isinstance(tests, list) or not 4 <= len(tests) <= 20:
        return None
    out = []
    for x in tests:
        if not isinstance(x, dict):
            return None
        s = _num(x.get("sens"), 0.01, 20, 4)
        click = _num(x.get("click"), 0, 100000, 1)
        track = _num(x.get("track"), 0, 1, 3)
        if s is None or click is None or track is None:
            return None
        t = {"sens": s, "click": click, "track": track}
        for k, hi in (("over", 5), ("under", 5), ("acc", 1), ("ms", 5000)):
            v = _num(x.get(k), 0, hi, 3)
            if v is not None:
                t[k] = v
        out.append(t)
    return {"base": base, "tests": out, "t": time.time(), "d": date.today().isoformat()}


def _points(session: dict) -> list[tuple[float, float, dict]]:
    """(sens, 0..1 how well it went, the test) for one session: click score and tracking each scaled to the
    session's best, then averaged."""
    ts = session["tests"]
    cmax = max((t["click"] for t in ts), default=0) or 1
    tmax = max((t["track"] for t in ts), default=0) or 1
    return [(t["sens"], (t["click"] / cmax + t["track"] / tmax) / 2, t) for t in ts]


def _fit(points: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Least squares y = a·x² + b·x + c over x = ln(sens). None if it can't be solved."""
    if len({round(x, 4) for x, _ in points}) < 3:
        return None
    s = [sum(x ** k for x, _ in points) for k in range(5)]
    t = [sum(y * x ** k for x, y in points) for k in range(3)]
    m = [[s[4], s[3], s[2], t[2]], [s[3], s[2], s[1], t[1]], [s[2], s[1], s[0], t[0]]]
    for i in range(3):                                   # Gauss elimination with pivoting
        p = max(range(i, 3), key=lambda r: abs(m[r][i]))
        if abs(m[p][i]) < 1e-12:
            return None
        m[i], m[p] = m[p], m[i]
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [a - f * b for a, b in zip(m[r], m[i])]
    return m[0][3] / m[0][0], m[1][3] / m[1][1], m[2][3] / m[2][2]


def recommend(sessions: list[dict], now: float | None = None) -> dict | None:
    """What the sessions of the last 90 days say: {sens, low, high, edge, sessions, sure, curve, points, over_trend,
    per_session}. "edge": the best was at the end of what was tested ("higher"/"lower")."""
    now = now or time.time()
    recent = [s for s in sessions if now - s.get("t", 0) <= SENS_KEEP_DAYS * 86400]
    if not recent:
        return None
    pts = [p for s in recent for p in _points(s)]
    xs = [math.log(s) for s, _, _ in pts]
    lo, hi = min(xs), max(xs)
    fit = _fit([(math.log(s), y) for s, y, _ in pts])
    best_measured = max(pts, key=lambda p: p[1])[0]
    if fit and fit[0] < 0:
        x = min(max(-fit[1] / (2 * fit[0]), lo), hi)
    else:
        x = math.log(best_measured)
    sens = math.exp(x)
    edge = "higher" if x >= hi - 1e-6 and sens > 0 else "lower" if x <= lo + 1e-6 else ""
    # the range where the curve is within 3% of its top: "anything in here is fine"
    if fit and fit[0] < 0:
        top = fit[0] * x * x + fit[1] * x + fit[2]
        span = math.sqrt(0.03 * abs(top) / -fit[0]) if top else 0.05
        low, high = math.exp(max(lo, x - span)), math.exp(min(hi, x + span))
    else:
        low = high = sens
    per = []
    for s in recent:
        f = _fit([(math.log(a), y) for a, y, _ in _points(s)])
        if f and f[0] < 0:
            per.append(math.exp(-f[1] / (2 * f[0])))
        else:
            per.append(max(_points(s), key=lambda p: p[1])[0])
    spread = (max(per) - min(per)) / sens if len(per) > 1 else None
    sure = "low" if len(recent) == 1 else "high" if len(recent) >= 3 and spread is not None and spread < 0.15 else "medium"
    over = [(math.log(s), t["over"]) for s, _, t in pts if "over" in t]
    trend = None
    if len(over) >= 4:                                   # does overshooting grow with the sens?
        mx = sum(a for a, _ in over) / len(over)
        my = sum(b for _, b in over) / len(over)
        cov = sum((a - mx) * (b - my) for a, b in over)
        trend = "up" if cov > 0 else "down"
    curve = []
    if fit:
        for i in range(25):
            cx = lo + (hi - lo) * i / 24
            curve.append((round(math.exp(cx), 4), round(fit[0] * cx * cx + fit[1] * cx + fit[2], 4)))
    return {"sens": round(sens, 3), "low": round(low, 3), "high": round(high, 3), "edge": edge,
            "sessions": len(recent), "sure": sure, "curve": curve, "over_trend": trend,
            "per_session": [round(p, 3) for p in per],
            "points": [{"sens": s, "y": round(y, 3), "over": t.get("over"), "under": t.get("under")} for s, y, t in pts]}


def round2(round1: list[dict]) -> list[float]:
    """Round 2's sensitivities: close around round 1's best (by the same measure the recommendation uses)."""
    best = max(_points({"tests": round1}), key=lambda p: p[1])[0]
    return [round(best * f, 4) for f in (0.9, 0.95, 1.0, 1.05, 1.1)]


def sens_step(current: float | None, rec: float) -> dict:
    """How to get there: big changes in steps of about 10% a week, so muscle memory keeps up."""
    if not current:
        return {"steps": [rec]}
    change = rec / current - 1
    if abs(change) <= 0.12:
        return {"change": round(change, 3), "steps": [rec]}
    n = math.ceil(abs(math.log(rec / current)) / math.log(1.1))
    return {"change": round(change, 3), "steps": [round(current * (rec / current) ** (i / n), 3) for i in range(1, n + 1)]}
