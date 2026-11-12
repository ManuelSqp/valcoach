"""Practice › Aim trainer: Nexus's own aim trainer in the browser (static/trainer.js) and the mouse & monitor check
(static/gearcheck.js). This file is what the server knows about them: the scenarios, which ones today's warm-up
and training play (from what the matches show, stats/aim.py needs()), checking what a page sends, scores per
scenario, and the Valorant numbers (eDPI, cm per 360).

Stored per player in data/profiles/<pid>/stats/trainer.json:
  {"runs": [{s, score, t, d, hits, shots, ms, acc}], "setup": {sens, dpi, measured_dpi, ...}}"""
from __future__ import annotations

import math
import re
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
    "flick_close": {"name": "Close flicks", "kind": "click", "seconds": 45, "group": "flicks",
                    "focus": ["flicks", "reaction", "switching"],
                    "about": "Big targets close to you, far to the side. Like an enemy right next to you: turn fast, hit, stop."},
    "flick_far": {"name": "Far flicks", "kind": "click", "seconds": 45, "group": "flicks",
                  "focus": ["micro", "crosshair", "flicks"],
                  "about": "Small targets far away, a short flick each. Like a long angle: small, exact movements."},
    "holdangle": {"name": "Hold the angle", "kind": "click", "seconds": 60, "group": "duels",
                  "focus": ["peeking", "crosshair", "reaction"],
                  "about": "Hold a doorway: an enemy swings wide, jiggles or runs through, from the left or the right. "
                           "Only a headshot kills."},
    "track": {"name": "Strafe tracking", "kind": "track", "seconds": 45, "focus": ["tracking", "spray"],
              "about": "One target strafes left and right like a player. Hold the mouse button and stay on it."},
}
PLANS = {"warmup": "Warm-up", "training": "Training"}
# the rest of the tracking scenarios (after "track" so the page keeps its order: flicks, duels, tracking)
SCENARIOS.update({
    "track_close": {"name": "Close tracking", "kind": "track", "seconds": 45, "group": "tracking",
                    "focus": ["tracking", "spray"],
                    "about": "An enemy 4–5 m away strafing fast: big, quick movements to stay on them."},
    "track_far": {"name": "Far tracking", "kind": "track", "seconds": 45, "group": "tracking",
                  "focus": ["tracking", "micro"],
                  "about": "A small target far away, moving slowly: small, smooth corrections."},
    "track_react": {"name": "Reactive tracking", "kind": "track", "seconds": 45, "group": "tracking",
                    "focus": ["tracking", "peeking", "reaction"],
                    "about": "Short left-right strafes and sudden stops, like a player dodging. React to each change."},
})

# 4.23: the library. level: 1 easy, 2 medium, 3 hard. Same ids in static/trainer.js.
def _sc(name, kind, group, level, focus, about, seconds=45):
    return {"name": name, "kind": kind, "seconds": seconds, "group": group, "level": level, "focus": focus, "about": about}


SCENARIOS.update({
    "flick_mid": _sc("Mid-range flicks", "click", "flicks", 1, ["flicks", "warmup"],
                     "Medium targets 12–16 m away, 15–45° from the crosshair. The everyday flick: fast, then stop on it."),
    "flick_wide": _sc("Wide flicks", "click", "flicks", 2, ["flicks", "reaction"],
                      "Targets 50–70° to the side, close. Someone you didn't check: one big, controlled turn."),
    "flick_vert": _sc("Vertical flicks", "click", "flicks", 2, ["flicks", "crosshair"],
                      "Up and down as much as sideways: high ledges, boxes, stairs. Your vertical flicks are usually the weak ones."),
    "flick_tiny": _sc("Tiny flicks", "click", "flicks", 3, ["flicks", "micro"],
                      "Small targets 14–18 m away. Speed only counts if you hit: slow down at the end of the flick."),
    "spider": _sc("Spider flicks", "click", "flicks", 1, ["flicks", "warmup", "crosshair"],
                  "A target in the middle, then one around it, back to the middle. Flick out, come back to your crosshair spot."),
    "spider_far": _sc("Far spider", "click", "precision", 3, ["micro", "crosshair", "flicks"],
                      "The spider far away with small targets: short, exact flicks out and back."),
    "six_shot": _sc("Six shot", "click", "switching", 1, ["switching", "warmup", "flicks"],
                    "Six targets on a wall at once: clear them in a smooth order, the shortest way from one to the next."),
    "head_switch": _sc("Head-line switching", "click", "switching", 2, ["switching", "crosshair"],
                       "Four targets, all at head height, spread wide. Move along the line, never up or down."),
    "close_switch": _sc("Close switching", "click", "switching", 2, ["switching", "flicks", "reaction"],
                        "Three big targets around you, up to 65° apart: a site full of enemies at close range."),
    "tiny_switch": _sc("Tiny switching", "click", "switching", 3, ["switching", "micro"],
                       "Five small targets far away, close together: short, exact switches without overshooting."),
    "double_tap": _sc("Double tap", "click", "switching", 2, ["switching", "spray", "crosshair"],
                      "Each target needs two hits (it shrinks after the first). Stay on it for the second shot, then switch."),
    "reflex": _sc("Reflex flicks", "click", "reflex", 1, ["reaction", "flicks"],
                  "A target shows up for about a second, then it's gone. Each hit makes the next one shorter."),
    "reflex_small": _sc("Reflex: small", "click", "reflex", 3, ["reaction", "micro"],
                        "Small, far targets that vanish fast: react and hit, no second try."),
    "reflex_wide": _sc("Reflex: wide", "click", "reflex", 2, ["reaction", "flicks", "peeking"],
                       "Close targets far to the side, there for a moment: like an enemy appearing beside you."),
    "pinpoint": _sc("Pinpoint", "click", "precision", 3, ["micro", "crosshair"],
                    "One tiny target 24–28 m away, the next close to it. Calm, exact taps: accuracy over speed."),
    "headline_far": _sc("Far head-line", "click", "precision", 2, ["crosshair", "micro", "flicks"],
                        "Small heads far away, always at head height. Long-range crosshair placement."),
    "micro_spider": _sc("Micro spider", "click", "precision", 3, ["micro", "crosshair"],
                        "Tiny steps out of the middle and back: the small corrections after a flick."),
    "peek_far": _sc("Far peeks", "click", "duels", 2, ["peeking", "reaction", "micro"],
                    "Enemies peek out from cover 28 m away: small and quick, like a long corridor."),
    "peek_fast": _sc("Fast peeks", "click", "duels", 3, ["peeking", "reaction"],
                     "Shorter peeks that get faster with every hit. Pure reaction from a held crosshair."),
    "angle_close": _sc("Close angle", "click", "duels", 2, ["peeking", "reaction", "flicks"],
                       "Hold a doorway 5–8 m away: they come out fast and big. Head only."),
    "angle_long": _sc("Long angle", "click", "duels", 3, ["peeking", "micro", "crosshair"],
                      "Hold a narrow gap 24–32 m away: a small head for a short moment. Head only."),
    "angle_jiggle": _sc("Jiggle peeks", "click", "duels", 3, ["peeking", "reaction"],
                        "Mostly jiggles: a shoulder and the head, straight back. Wait for the real swing or hit the head in time."),
    "angle_wide": _sc("Wide swings", "click", "duels", 1, ["peeking", "crosshair"],
                      "Only wide swings that stop in the opening: the easiest duel, perfect your crosshair placement. Head only."),
    "angle_runners": _sc("Runners", "click", "duels", 3, ["peeking", "reaction", "tracking"],
                         "Every enemy runs through the doorway without stopping: shoot the head as they cross."),
    "track_smooth": _sc("Smooth tracking", "track", "tracking", 1, ["tracking", "warmup"],
                        "A big target moving slowly and evenly: stay on it with smooth movement, no jerks."),
    "track_fast": _sc("Fast strafes", "track", "tracking", 3, ["tracking", "reaction"],
                      "Fast, short strafes 7 m away: react to every change of direction."),
    "track_tiny": _sc("Small target tracking", "track", "tracking", 2, ["tracking", "micro"],
                      "A small target 14 m away: small, precise corrections to stay on it."),
    "track_jump": _sc("Jumping strafes", "track", "tracking", 2, ["tracking", "spray"],
                      "A strafing target that jumps now and then: follow it up and down too."),
    "track_crouch": _sc("Crouch spam", "track", "tracking", 2, ["tracking", "spray", "crosshair"],
                        "A strafing target that crouches suddenly: drop your crosshair with it."),
    "orbit": _sc("Around you", "track", "tracking", 2, ["tracking", "flicks"],
                 "A target running in a circle around you, up to 75° to each side: big, smooth turns."),
    "orbit_air": _sc("Air tracking", "track", "tracking", 3, ["tracking", "reaction"],
                     "Running around you and jumping: follow it in the air and when it lands."),
    "orbit_vert": _sc("Up and down", "track", "tracking", 3, ["tracking", "crosshair"],
                      "Moves sideways and up and down at the same time: tracking in two directions."),
})
GROUPS = {"flicks": "Flicks", "switching": "Switching", "reflex": "Reflex", "precision": "Precision", "duels": "Duels",
          "tracking": "Tracking"}
LEVELS = {1: "Easy", 2: "Medium", 3: "Hard"}
_OLD = {"grid": ("switching", 1), "headline": ("flicks", 1), "micro": ("precision", 2), "peek": ("duels", 1),
        "flick_close": ("flicks", 2), "flick_far": ("precision", 2), "holdangle": ("duels", 2), "track": ("tracking", 1),
        "track_close": ("tracking", 2), "track_far": ("tracking", 2), "track_react": ("tracking", 3)}
for _k, _v in SCENARIOS.items():
    if _k in _OLD:
        _v["group"], _v["level"] = _OLD[_k]
    _v.setdefault("group", "tracking")
    _v.setdefault("level", 2)

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
        for k in ("body", "escaped"):                    # hold the angle: body shots, enemies that got away
            v = _num(d.get(k), 0, 5000, 0)
            if v is not None and k in d:
                out[k] = int(v)
    else:
        on = _num(d.get("on_target"), 0, 1, 3)
        if on is None:
            return None
        out["on"] = on
    x = clean_detail(d.get("detail"))                   # what Aim insights needs (see trainer.js ixNew)
    if x:
        out["x"] = x
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
        out.append({"id": sid, "name": sc["name"], "focus": sc["focus"], "group": sc["group"], "runs": x["runs"] if x else 0,
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
    if d.get("grip") in GRIPS:
        out["grip"] = d["grip"]
    if d.get("hand") in ("right", "left"):
        out["hand"] = d["hand"]
    x = clean_crosshair(d.get("crosshair"))
    if x:
        out["crosshair"] = x
    return out


# the trainer's crosshair (like Valorant's primary crosshair; see trainer.js): number keys with their range, switches
CROSSHAIR_NUM = {"ot": (1, 6), "oo": (0, 1), "dt": (1, 6), "da": (0, 1), "it": (0, 10), "il": (0, 20), "iv": (0, 20),
                 "io": (0, 20), "ia": (0, 1), "ot2": (0, 10), "ol": (0, 20), "ov": (0, 20), "oo2": (0, 40), "oa": (0, 1)}
CROSSHAIR_BOOL = ("outline", "dot", "inner", "ig", "outer", "og")


GRIPS = {"palm": "Palm", "claw": "Claw", "fingertip": "Fingertip", "unsure": "Not sure"}


def clean_detail(x) -> dict | None:
    """The per-run sums for Aim insights (trainer.js ixNew): only the expected shape, only sane numbers."""
    if not isinstance(x, dict):
        return None

    def nums(v, n, hi):
        if not isinstance(v, list) or len(v) != n:
            return None
        out = [_num(a, -hi, hi, 3) for a in v]
        return None if any(a is None for a in out) else out
    try:
        f, tk, p = x.get("f") or {}, x.get("t") or {}, x.get("p") or {}
        d = [nums(a, 5, 10 ** 6) for a in f.get("d", [])]
        s = [nums(a, 2, 10 ** 6) for a in f.get("s", [])]
        m = f.get("m") or {}
        if len(d) != 8 or len(s) != 3 or any(a is None for a in d + s):
            return None
        grid = {}
        for k, v in (m.get("g") or {}).items():
            parts = str(k).split(",")
            if len(parts) == 2 and all(q.lstrip("-").isdigit() and abs(int(q)) <= 6 for q in parts):
                n = _num(v, 0, 10000, 0)
                if n:
                    grid[f"{int(parts[0])},{int(parts[1])}"] = int(n)
        miss = {k: int(_num(m.get(k), 0, 10000, 0) or 0) for k in ("n", "l", "r", "h", "lo")}
        track = {k: nums(tk.get(k, [0, 0]), 2, 10 ** 6) for k in ("L", "R", "lead", "re")}
        peek = {k: nums(p.get(k, [0, 0, 0]), 3, 10 ** 6) for k in ("L", "R", "place")}
        if any(v is None for v in list(track.values()) + list(peek.values())):
            return None
        peek["body"] = int(_num(p.get("body"), 0, 10000, 0) or 0)
        return {"f": {"d": d, "s": s, "m": dict(miss, g=grid)}, "t": track, "p": peek}
    except (AttributeError, TypeError):
        return None


def clean_crosshair(x) -> dict | None:
    if not isinstance(x, dict) or not isinstance(x.get("color"), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", x["color"]):
        return None
    out: dict = {"color": x["color"].lower()}
    for k, (lo, hi) in CROSSHAIR_NUM.items():
        v = _num(x.get(k), lo, hi, 3)
        if v is None:
            return None
        out[k] = v
    for k in CROSSHAIR_BOOL:
        out[k] = x.get(k) is True
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
# Two modes: quick (1 warm-up, 5 + 5 rounds of 20 s, about 5 minutes) and thorough (2 warm-ups, your sens counted at
# the start and the end, 7 wide + 6 close played twice, 25 s each, about 11 minutes). The thorough one measures how
# much you tired between its first and last round at your own sens and corrects the rounds in between for it, and it
# counts twice in the recommendation.
MODE_WEIGHT = {"quick": 1, "thorough": 2, "standard": 2, "full": 3}     # thorough: 4.6's 11-minute mode
MODES = {"quick": "5 min", "standard": "15 min", "full": "30 min", "thorough": "11 min"}
PARTS = {"fc": "Close flicks", "ff": "Far flicks", "tc": "Close tracking", "tf": "Far tracking", "tr": "Reactive tracking"}
SENS_KEEP_DAYS = 90
MAX_SESSIONS = 60


def clean_sens_session(d: dict) -> dict | None:
    if not isinstance(d, dict):
        return None
    base = _num(d.get("base"), 0.01, 20, 4)
    tests = d.get("tests")
    mode = d.get("mode") if d.get("mode") in MODE_WEIGHT else "quick"
    if base is None or not isinstance(tests, list) or not 4 <= len(tests) <= 40:
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
        parts = x.get("parts")
        if isinstance(parts, dict):                      # per part of the round (15 and 30 minutes)
            pt = {}
            for k, v in parts.items():
                if k in PARTS:
                    n = _num(v, 0, 1, 3) if k.startswith("t") else _num(v, 0, 100000, 1)
                    if n is not None:
                        pt[k] = n
            if pt:
                t["parts"] = pt
        order = x.get("i")
        if isinstance(order, int) and not isinstance(order, bool) and 0 <= order < 100:
            t["i"] = order
        for k, hi in (("over", 5), ("under", 5), ("acc", 1), ("ms", 5000)):
            v = _num(x.get(k), 0, hi, 3)
            if v is not None:
                t[k] = v
        out.append(t)
    return {"base": base, "mode": mode, "tests": out, "t": time.time(), "d": date.today().isoformat()}


def _tiring(session: dict) -> float:
    """How much worse you got per round, from the rounds at your own sens (start, end, and the middle in the
    30-minute mode): a straight line through them, as a share per round (0.01 = 1% worse each round). 0 when
    there's nothing to compare or it got better."""
    ts = [t for t in session["tests"] if "i" in t]
    own = sorted((t for t in ts if abs(t["sens"] - session["base"]) < 1e-3), key=lambda t: t["i"])
    if session.get("mode") == "quick" or len(own) < 2 or own[-1]["i"] == own[0]["i"]:
        return 0.0
    cmax = max(t["click"] for t in own) or 1e-9
    tmax = max(t["track"] for t in own) or 1e-9
    q = [(t["i"], (t["click"] / cmax + t["track"] / tmax) / 2) for t in own]
    mx = sum(i for i, _ in q) / len(q)
    my = sum(v for _, v in q) / len(q)
    slope = sum((i - mx) * (v - my) for i, v in q) / sum((i - mx) ** 2 for i, _ in q)
    per = -slope / my if my else 0.0
    return min(max(per, 0.0), 0.02)                      # at most 2% a round: more is a bad round, not tiring


def _points(session: dict) -> list[tuple[float, float, dict]]:
    """(sens, 0..1 how well it went, the test) for one session: click score and tracking each scaled to the
    session's best, then averaged."""
    ts = session["tests"]
    per = _tiring(session)
    fix = [1 + per * t.get("i", 0) for t in ts]           # a later round gets back what tiring took
    cmax = max((t["click"] * k for t, k in zip(ts, fix)), default=0) or 1
    tmax = max((t["track"] * k for t, k in zip(ts, fix)), default=0) or 1
    return [(t["sens"], (t["click"] * k / cmax + t["track"] * k / tmax) / 2, t) for t, k in zip(ts, fix)]


def _fit(points: list[tuple]) -> tuple[float, float, float] | None:
    """Least squares y = a·x² + b·x + c over x = ln(sens); points (x, y) or (x, y, weight). None if it can't be
    solved."""
    pts = [(p[0], p[1], p[2] if len(p) > 2 else 1.0) for p in points]
    if len({round(x, 4) for x, _, _ in pts}) < 3:
        return None
    s = [sum(w * x ** k for x, _, w in pts) for k in range(5)]
    t = [sum(w * y * x ** k for x, y, w in pts) for k in range(3)]
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
    meta = [(s.get("d", ""), s.get("mode", "quick")) for s in recent for _ in s["tests"]]     # which test each point is from
    wts = [MODE_WEIGHT.get(s.get("mode"), 1) for s in recent for _ in s["tests"]]
    xs = [math.log(s) for s, _, _ in pts]
    lo, hi = min(xs), max(xs)
    fit = _fit([(math.log(s), y, w) for (s, y, _), w in zip(pts, wts)])
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
    weight = sum(MODE_WEIGHT.get(s.get("mode"), 1) for s in recent)        # a thorough test counts as two quick ones
    sure = ("low" if weight == 1 else
            "high" if weight >= 3 and len({s.get("d") for s in recent}) >= 2 and spread is not None and spread < 0.15
            else "medium")
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
            "sessions": len(recent), "long": sum(1 for s in recent if MODE_WEIGHT.get(s.get("mode"), 1) > 1),
            "tiring": round(_tiring(recent[-1]), 4), "sure": sure, "curve": curve, "over_trend": trend,
            "parts": _part_best(recent),
            "per_session": [round(p, 3) for p in per],
            "points": [{"sens": s, "y": round(y, 3), "over": t.get("over"), "under": t.get("under"), "d": d, "mode": mode}
                       for (s, y, t), (d, mode) in zip(pts, meta)]}


def _part_best(sessions: list[dict]) -> dict:
    """Which sens each part of the test likes on its own (close and far flicks, close, far and reactive tracking),
    from the sessions that have parts: each part scaled to its session's best, a curve through it, its top."""
    out = {}
    for k in PARTS:
        pts = []
        for s in sessions:
            per = _tiring(s)                             # later rounds get back what tiring took, as in _points
            vals = [(t["sens"], t["parts"][k] * (1 + per * t.get("i", 0))) for t in s["tests"] if k in t.get("parts", {})]
            top = max((v for _, v in vals), default=0)
            if top > 0:
                w = MODE_WEIGHT.get(s.get("mode"), 1)
                pts += [(math.log(a), v / top, w) for a, v in vals]
        if len({round(x, 4) for x, _, _ in pts}) < 3:
            continue
        lo, hi = min(x for x, _, _ in pts), max(x for x, _, _ in pts)
        fit = _fit(pts)
        x = min(max(-fit[1] / (2 * fit[0]), lo), hi) if fit and fit[0] < 0 else max(pts, key=lambda p: p[1])[0]
        out[k] = round(math.exp(x), 3)
    return out


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
