"""Practice › Aim insights: what the aim trainer's runs say about how you aim, and what to do about it.

Each run of the trainer (static/trainer.js) sends compact sums (stats/trainer.py clean_detail): flicks by direction
and size with overshoot (flying past) and stopping short, where missed shots land, tracking while the target moves
left or right (on it, ahead or behind, catching up after a direction change), and enemies peeking (reaction per side,
headshots, where the crosshair waited). This file adds up the last 30 days, finds what stands out (only with enough
samples), and turns it into findings with hand, grip and posture tips and scenarios to play, a skill profile, and the
data for the page's charts. Tips are general aim-training advice, not medical advice."""
from __future__ import annotations

import math
import time
from datetime import date, timedelta

from . import trainer as tr

DAYS = 30
SECTORS = ["right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right"]
LEFT, RIGHT, UP, DOWN = (3, 4, 5), (7, 0, 1), (1, 2, 3), (5, 6, 7)


def aggregate(runs: list[dict], days: int = DAYS, today: date | None = None) -> dict:
    """The sums of the runs of the last `days` days that have the detail."""
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    a = {"runs": 0, "d": [[0.0] * 5 for _ in range(8)], "s": [[0.0, 0.0] for _ in range(3)],
         "m": {"n": 0, "l": 0, "r": 0, "h": 0, "lo": 0, "g": {}},
         "t": {"L": [0.0, 0.0], "R": [0.0, 0.0], "lead": [0.0, 0.0], "re": [0.0, 0.0]},
         "p": {"L": [0.0, 0.0, 0.0], "R": [0.0, 0.0, 0.0], "place": [0.0, 0.0, 0.0], "body": 0},
         "acc": [0, 0], "track_on": [0.0, 0.0]}
    for r in runs:
        if r.get("d", "") < since:
            continue
        if "hits" in r and "shots" in r:
            a["acc"][0] += r["hits"]
            a["acc"][1] += r["shots"]
        if "on" in r and "sec" in r:
            a["track_on"][0] += r["on"] * r["sec"]
            a["track_on"][1] += r["sec"]
        x = r.get("x")
        if not x:
            continue
        a["runs"] += 1
        for i in range(8):
            for j in range(5):
                a["d"][i][j] += x["f"]["d"][i][j]
        for i in range(3):
            for j in range(2):
                a["s"][i][j] += x["f"]["s"][i][j]
        m = x["f"]["m"]
        for k in ("n", "l", "r", "h", "lo"):
            a["m"][k] += m.get(k, 0)
        for k, v in m.get("g", {}).items():
            a["m"]["g"][k] = a["m"]["g"].get(k, 0) + v
        for k in ("L", "R", "lead", "re"):
            for j in range(2):
                a["t"][k][j] += x["t"][k][j]
        for k in ("L", "R", "place"):
            for j in range(3):
                a["p"][k][j] += x["p"][k][j]
        a["p"]["body"] += x["p"].get("body", 0)
    return a


def _side(d: list, idx: tuple) -> dict:
    n = sum(d[i][0] for i in idx)
    measured = sum(d[i][4] for i in idx)
    return {"n": int(n), "ms": sum(d[i][1] for i in idx) / n if n else None,
            "over": sum(d[i][2] for i in idx) / measured if measured else None,
            "under": sum(d[i][3] for i in idx) / measured if measured else None, "measured": int(measured)}


def _cv(vals: list[float]) -> float | None:
    if len(vals) < 5:
        return None
    m = sum(vals) / len(vals)
    if not m:
        return None
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) / m


def _scale(v: float | None, worst: float, best: float) -> int | None:
    if v is None:
        return None
    return round(max(0.0, min(1.0, (v - worst) / (best - worst))) * 100)


def numbers(a: dict, runs: list[dict]) -> dict:
    """The measured numbers the findings and the page use."""
    d = a["d"]
    allf = _side(d, tuple(range(8)))
    t = a["t"]
    on = {k: (t[k][1] / t[k][0] if t[k][0] else None) for k in ("L", "R")}
    p = a["p"]
    kills = p["L"][0] + p["R"][0]
    by_s: dict[str, list[float]] = {}
    for r in runs[-300:]:
        by_s.setdefault(r["s"], []).append(r["score"])
    cvs = {s: c for s, v in by_s.items() if (c := _cv(v[-8:])) is not None}
    return {
        "runs": a["runs"],
        "flick": {"all": allf, "left": _side(d, LEFT), "right": _side(d, RIGHT), "up": _side(d, UP), "down": _side(d, DOWN),
                  "sizes": [{"n": int(s[0]), "ms": s[1] / s[0] if s[0] else None} for s in a["s"]],
                  "dirs": [{"n": int(x[0]), "ms": x[1] / x[0] if x[0] else None,
                            "over": x[2] / x[4] if x[4] else None, "under": x[3] / x[4] if x[4] else None} for x in d]},
        "miss": a["m"],
        "acc": a["acc"][0] / a["acc"][1] if a["acc"][1] else None,
        "track": {"on": on, "secs": {k: t[k][0] for k in ("L", "R")},
                  "all": (t["L"][1] + t["R"][1]) / (t["L"][0] + t["R"][0]) if t["L"][0] + t["R"][0] else
                         (a["track_on"][0] / a["track_on"][1] if a["track_on"][1] else None),
                  "lead": t["lead"][0] / t["lead"][1] if t["lead"][1] else None, "lead_secs": t["lead"][1],
                  "re": t["re"][0] / t["re"][1] if t["re"][1] else None, "re_n": int(t["re"][1])},
        "peek": {"kills": int(kills), "ms": (p["L"][1] + p["R"][1]) / kills if kills else None,
                 "L": {"n": int(p["L"][0]), "ms": p["L"][1] / p["L"][0] if p["L"][0] else None},
                 "R": {"n": int(p["R"][0]), "ms": p["R"][1] / p["R"][0] if p["R"][0] else None},
                 "place_n": int(p["place"][2]), "place_dy": p["place"][0] / p["place"][2] if p["place"][2] else None,
                 "place_dx": p["place"][1] / p["place"][2] if p["place"][2] else None,
                 "body": int(p["body"]), "body_share": p["body"] / (kills + p["body"]) if kills + p["body"] else None},
        "cv": cvs,
    }


def _find(kind, title, text, weight, tips, play, area, data=None) -> dict:
    return {"id": kind, "title": title, "text": text, "weight": round(weight, 3), "tips": tips, "play": play,
            "area": area, "data": data or {}}


def findings(n: dict, setup: dict) -> tuple[list[dict], list[str]]:
    """(what to work on, most important first; what's already good). Only with enough samples."""
    hand = setup.get("hand", "right")
    grip = setup.get("grip", "unsure")
    out: list[dict] = []
    good: list[str] = []
    f = n["flick"]
    # ---------------------------------------------------------------- flicks left vs right
    L, R = f["left"], f["right"]
    if L["n"] >= 15 and R["n"] >= 15 and L["ms"] and R["ms"]:
        slow, fast, sname = (L, R, "left") if L["ms"] > R["ms"] else (R, L, "right")
        diff = slow["ms"] / fast["ms"] - 1
        if diff >= 0.12:
            toward_thumb = (sname == "left") == (hand == "right")
            tips = ([f"With your {hand} hand the wrist bends less toward the thumb side, so long flicks to the {sname} need "
                     "the forearm. Let the forearm move for big flicks instead of pivoting on the wrist."]
                    if toward_thumb else
                    [f"Flicks to the {sname} move your hand away from the body: check there's mousepad room on that side "
                     "and that the keyboard isn't in the way, and let the elbow move with it."])
            tips.append(f"Start each flick to the {sname} with the arm, finish with the wrist and fingers.")
            out.append(_find("flick-side", f"Flicks to the {sname} are slower",
                             f"{diff:.0%} slower to the {sname}: {slow['ms']:.0f} ms against {fast['ms']:.0f} ms.",
                             min(1.0, diff * 2.5), tips, ["flick_close", "grid"], "flicks",
                             {"slow": sname, "ms": [round(L["ms"]), round(R["ms"])]}))
        else:
            good.append(f"Your flicks are even left and right ({L['ms']:.0f} and {R['ms']:.0f} ms).")
    # ---------------------------------------------------------------- flicks up vs down
    U, D = f["up"], f["down"]
    if U["n"] >= 12 and D["n"] >= 12 and U["ms"] and D["ms"]:
        slow_name = "up" if U["ms"] > D["ms"] else "down"
        diff = max(U["ms"], D["ms"]) / min(U["ms"], D["ms"]) - 1
        if diff >= 0.2:
            out.append(_find("flick-vertical", f"Flicks {slow_name} are slower",
                             f"{diff:.0%} slower {slow_name}ward ({U['ms']:.0f} ms up, {D['ms']:.0f} ms down).",
                             min(0.7, diff * 1.5),
                             [("Vertical movement comes mostly from the fingers and wrist: a relaxed hand moves up and down "
                               "more freely than one pressed onto the mouse."),
                              "In Valorant most fights are at head height: keeping the crosshair there saves vertical flicks."],
                             ["headline", "flick_close"], "flicks"))
    # ---------------------------------------------------------------- overshoot / stopping short
    a = f["all"]
    if a["measured"] >= 15 and a["over"] is not None:
        over, under = a["over"], a["under"]
        if over >= 0.08 and over >= under:
            tips = [("Flying past and pulling back usually means the hand doesn't brake in time. Focus on the stop, not the speed: "
                     "a flick that lands is faster than one that has to come back."),
                    "If it happens on almost every flick, your sens may be a little high: the sens finder shows it."]
            if grip == "fingertip":
                tips.insert(1, "With a fingertip grip only the fingers brake: a little palm contact at the back of the mouse "
                               "makes stopping easier.")
            elif grip == "claw":
                tips.insert(1, "With a claw grip, press the mouse a bit more with the palm's heel when you stop.")
            else:
                tips.insert(1, "Grip the mouse a little firmer at the moment you stop, then relax again.")
            out.append(_find("overshoot", "You fly past targets", f"On average you go {over:.0%} of the flick past the target "
                             "before coming back.", min(1.0, over * 5), tips, ["flick_far", "micro", "grid"], "precision",
                             {"over": round(over, 3), "under": round(under, 3)}))
        elif under >= 0.12 and under > over:
            tips = ["You stop short and need a second correction: commit to the flick. Look at the target, then move in one go.",
                    "Stopping short on most flicks can mean a sens that's a little low for you: the sens finder shows it."]
            if grip == "palm":
                tips.insert(1, "Palm grips are steady but slow to start: lead big flicks with the wrist and arm, "
                               "not the whole hand pushed forward.")
            else:
                tips.insert(1, "Keep the hand loose before the flick: a tense hand starts late and stops early.")
            out.append(_find("undershoot", "You stop short of targets", f"Your first stop is on average {under:.0%} of the way "
                             "short of the target.", min(1.0, under * 3.5), tips, ["flick_close", "grid"], "precision",
                             {"over": round(over, 3), "under": round(under, 3)}))
        else:
            good.append("Your flicks stop where the target is: hardly flying past or stopping short.")
    # ---------------------------------------------------------------- big and small flicks
    small, mid, big = f["sizes"]
    if big["n"] >= 10 and big["ms"] and big["ms"] > 620:
        out.append(_find("big-flicks", "Big flicks take long", f"Flicks over 30° take {big['ms']:.0f} ms on average.",
                         min(1.0, (big["ms"] - 620) / 300 + 0.3),
                         [("Big turns come from the arm, not the wrist: sit so the forearm can slide (elbow not hanging off "
                           "the desk edge, the mousepad big enough)."),
                          "Low sens needs more arm: if big flicks run out of room, a slightly higher sens helps."],
                         ["flick_close", "grid"], "flicks"))
    if small["n"] >= 15 and small["ms"] and small["ms"] > 420:
        out.append(_find("small-flicks", "Small corrections are slow", f"Flicks under 10° take {small['ms']:.0f} ms.",
                         min(0.9, (small["ms"] - 420) / 250 + 0.3),
                         [("Small corrections come from the fingers: keep the fingertips on the mouse and the hand relaxed "
                           "so they can move it a few millimetres."),
                          "Don't re-grip between small corrections: one steady grip, small finger movements."],
                         ["micro", "flick_far"], "precision"))
    # ---------------------------------------------------------------- where misses land
    m = n["miss"]
    if m["n"] >= 20:
        hx = (m["r"] - m["l"]) / m["n"]
        vy = (m["h"] - m["lo"]) / m["n"]
        if abs(vy) >= 0.25:
            where = "above" if vy > 0 else "below"
            out.append(_find("miss-vertical", f"Missed shots land {where} the target",
                             f"{max(m['h'], m['lo'])} of your {m['n']} near misses were {where} the target, "
                             f"{min(m['h'], m['lo'])} {'below' if vy > 0 else 'above'}.",
                             min(0.9, abs(vy) * 1.6),
                             (["Shots that land low often come from the click itself pulling the mouse down: click with "
                               "less force, only the finger moving, the hand still."]
                              if vy < 0 else
                              ["Shots that land high: you may still be moving up when you click. Let the crosshair settle "
                               "for a moment on small targets."]) +
                             ["Keep the crosshair at head height: then most corrections are only sideways."],
                             ["headline", "micro"], "precision", {"dir": where}))
        if abs(hx) >= 0.25:
            where = "right" if hx > 0 else "left"
            out.append(_find("miss-horizontal", f"Missed shots land {where} of the target",
                             f"{max(m['l'], m['r'])} of your {m['n']} near misses were {where} of the target, "
                             f"{min(m['l'], m['r'])} {'left' if hx > 0 else 'right'}.",
                             min(0.8, abs(hx) * 1.4),
                             ["Misses on one side usually mean flying past in that direction or clicking while still moving: "
                              "stop, then click."], ["flick_far", "grid"], "precision", {"dir": where}))
    # ---------------------------------------------------------------- tracking
    t = n["track"]
    if t["secs"]["L"] >= 20 and t["secs"]["R"] >= 20 and t["on"]["L"] is not None:
        diff = t["on"]["L"] - t["on"]["R"]
        if abs(diff) >= 0.08:
            worse = "left" if diff < 0 else "right"
            out.append(_find("track-side", f"Tracking targets moving {worse} is harder",
                             f"On the target {t['on']['L']:.0%} of the time when it moves left, "
                             f"{t['on']['R']:.0%} when it moves right.", min(1.0, abs(diff) * 4),
                             [f"Following to the {worse} uses a different set of muscles: slow, smooth practice that way helps. "
                              "Keep the arm free to move along.",
                              "Hold the mouse loosely while tracking; a tight grip makes the movement jerky."],
                             ["track", "track_close"], "tracking"))
        elif t["all"] and t["all"] > 0.55:
            good.append(f"Your tracking is even both ways ({t['on']['L']:.0%} and {t['on']['R']:.0%} on target).")
    if t["lead_secs"] >= 15 and t["lead"] is not None:
        if t["lead"] <= -0.6:
            out.append(_find("track-behind", "You trail moving targets",
                             f"While tracking, your crosshair is on average {abs(t['lead']):.1f}° behind the target.",
                             min(1.0, abs(t["lead"]) / 1.5),
                             ["Trailing means reacting late: watch the target's body, not the crosshair, and move with it.",
                              "Smooth, constant speed beats catching up in jumps: a relaxed arm and hand help.",
                              "If you trail on every target, a slightly higher sens can make tracking easier."],
                             ["track_react", "track_close"], "tracking", {"lead": round(t["lead"], 2)}))
        elif t["lead"] >= 0.6:
            out.append(_find("track-ahead", "You run ahead of moving targets",
                             f"While tracking, your crosshair is on average {t['lead']:.1f}° ahead of the target.",
                             min(0.9, t["lead"] / 1.5),
                             ["Ahead of the target means overcorrecting: slow down and match its speed instead of guessing.",
                              "Small, calm movements from the fingers for far targets."],
                             ["track_far", "track"], "tracking", {"lead": round(t["lead"], 2)}))
    if t["re_n"] >= 10 and t["re"] and t["re"] > 320:
        out.append(_find("track-turn", "Direction changes throw you off",
                         f"After the target changes direction you need {t['re']:.0f} ms to be back on it.",
                         min(1.0, (t["re"] - 320) / 300 + 0.3),
                         ["Don't keep moving when the target stops: watch its feet/body for the change and stop with it.",
                          "Reactive tracking trains exactly this: short strafes with sudden stops."],
                         ["track_react"], "tracking"))
    # ---------------------------------------------------------------- peeks
    p = n["peek"]
    if p["kills"] >= 10 and p["ms"]:
        if p["L"]["n"] >= 5 and p["R"]["n"] >= 5 and p["L"]["ms"] and p["R"]["ms"]:
            diff = max(p["L"]["ms"], p["R"]["ms"]) / min(p["L"]["ms"], p["R"]["ms"]) - 1
            if diff >= 0.15:
                worse = "left" if p["L"]["ms"] > p["R"]["ms"] else "right"
                out.append(_find("peek-side", f"Enemies from the {worse} take you longer",
                                 f"{diff:.0%} slower against peeks from the {worse} ({p['L']['ms']:.0f} vs {p['R']['ms']:.0f} ms).",
                                 min(0.9, diff * 2),
                                 [f"Hold the crosshair a little toward the {worse} edge of the angle: the side you react "
                                  "slower to should need the shortest move."], ["holdangle", "peek"], "duels"))
        if p["ms"] > 430:
            out.append(_find("reaction", "Slow on peeking enemies", f"{p['ms']:.0f} ms on average to hit an enemy who peeks.",
                             min(1.0, (p["ms"] - 430) / 300 + 0.3),
                             ["Pre-aim the edge the enemy comes from: the less you have to move, the faster the shot.",
                              "Warm up before playing: reaction is a few dozen ms slower cold.",
                              "Watch the edge, not the middle of the doorway."], ["holdangle", "peek"], "duels"))
        elif p["ms"] < 330:
            good.append(f"Fast against peeks: {p['ms']:.0f} ms on average.")
    if p["place_n"] >= 10 and p["place_dy"] is not None:
        if p["place_dy"] <= -0.6:
            out.append(_find("placement-low", "Your crosshair waits below head height",
                             f"When an enemy showed up, your crosshair was on average {abs(p['place_dy']):.1f}° below the head.",
                             min(1.0, abs(p["place_dy"]) / 1.5),
                             [("Keep the crosshair where heads appear: in Valorant that's a fixed height on flat ground. "
                               "Then the shot is a sideways move only."),
                              "After every movement, put the crosshair back at head height before the next angle."],
                             ["holdangle", "headline"], "duels", {"dy": round(p["place_dy"], 2)}))
        elif p["place_dy"] >= 0.8:
            out.append(_find("placement-high", "Your crosshair waits above head height",
                             f"When an enemy showed up, your crosshair was on average {p['place_dy']:.1f}° above the head.",
                             min(0.8, p["place_dy"] / 1.5),
                             ["Bring the crosshair down to head height: aiming too high costs a downward flick each fight."],
                             ["holdangle", "headline"], "duels", {"dy": round(p["place_dy"], 2)}))
        else:
            good.append("Your crosshair waits at head height.")
    if p["body_share"] is not None and p["kills"] + p["body"] >= 12 and p["body_share"] >= 0.3:
        out.append(_find("body-shots", "Many body shots", f"{p['body_share']:.0%} of your hits on peeking enemies were body shots.",
                         min(0.9, p["body_share"] * 1.6),
                         ["Body shots usually mean the crosshair waited too low or you shot while still moving up.",
                          "In Valorant one headshot often kills, body shots need several: aim for the head first."],
                         ["holdangle", "headline"], "duels"))
    # ---------------------------------------------------------------- consistency
    if n["cv"]:
        sid, cv = max(n["cv"].items(), key=lambda kv: kv[1])
        if cv >= 0.15:
            out.append(_find("consistency", "Your scores jump around",
                             f"In {tr.SCENARIOS.get(sid, {}).get('name', sid)} your last runs vary by about ±{cv:.0%}.",
                             min(0.8, cv * 2.5),
                             ["Same setup every time: chair height, arm position, mousepad position, mouse grip.",
                              "Warm up the same way before you play, and stop when you get tired: tired runs teach bad habits."],
                             ["grid", "headline"], "consistency"))
        elif len(n["cv"]) >= 2:
            good.append("Your scores are steady from run to run.")
    out.sort(key=lambda x: -x["weight"])
    return out, good


def profile(n: dict) -> list[dict]:
    """Skill profile 0–100 per area (rough scale from what's typical in aim trainers), only with data."""
    f, t, p = n["flick"], n["track"], n["peek"]
    axes = [
        ("Flick speed", _scale(f["all"]["ms"], 800, 300) if f["all"]["n"] >= 15 else None),
        ("Accuracy", _scale(n["acc"], 0.55, 0.95) if n["acc"] is not None else None),
        ("Small fixes", _scale(f["sizes"][0]["ms"], 600, 220) if f["sizes"][0]["n"] >= 10 else None),
        ("Tracking", _scale(t["all"], 0.3, 0.8) if t["all"] is not None else None),
        ("Reaction", _scale(p["ms"], 650, 260) if p["kills"] >= 5 else None),
        ("Placement", _scale(abs(p["place_dy"]) + (p["place_dx"] or 0) / 3, 3, 0) if p["place_n"] >= 5 else None),
        ("Consistency", _scale(sum(n["cv"].values()) / len(n["cv"]), 0.3, 0.05) if n["cv"] else None),
    ]
    return [{"name": k, "v": v} for k, v in axes if v is not None]


def focus_plan(found: list[dict]) -> dict | None:
    """Training from the top findings: their scenarios, two rounds each (three scenarios at most)."""
    ids: list[str] = []
    why: dict[str, str] = {}
    for x in found:
        for s in x["play"]:
            if s in tr.SCENARIOS and s not in ids:
                ids.append(s)
                why[s] = x["title"]
                break
        if len(ids) == 3:
            break
    if not ids:
        return None
    items = [{"id": s, "name": tr.SCENARIOS[s]["name"], "seconds": tr.SCENARIOS[s]["seconds"], "why": why[s]}
             for s in ids for _ in range(2)]
    return {"kind": "focus", "name": "Focus", "minutes": math.ceil(sum(i["seconds"] + 5 for i in items) / 60), "items": items}


# ---------------------------------------------------------------------- charts (SVG coordinates for the page)
def _wedge(cx: float, cy: float, r0: float, r1: float, a0: float, a1: float) -> str:
    """An SVG path for a ring segment; angles in degrees, 0 = right, counter-clockwise (screen y down)."""
    def pt(r, a):
        return f"{cx + r * math.cos(math.radians(a)):.1f},{cy - r * math.sin(math.radians(a)):.1f}"
    return (f"M{pt(r0, a0)} L{pt(r1, a0)} A{r1:.1f},{r1:.1f} 0 0 0 {pt(r1, a1)} L{pt(r0, a1)} "
            f"A{r0:.1f},{r0:.1f} 0 0 1 {pt(r0, a0)} Z")


def charts(n: dict) -> dict:
    out: dict = {}
    # flick wheel: one wedge per direction, longer = faster; colour: flying past / stopping short / fine
    dirs = n["flick"]["dirs"]
    speeds = [1000 / d["ms"] if d["n"] >= 3 and d["ms"] else None for d in dirs]
    top = max((s for s in speeds if s), default=None)
    if top and sum(1 for s in speeds if s) >= 4:
        wedges = []
        for i, (d, s) in enumerate(zip(dirs, speeds)):
            a0, a1 = i * 45 - 20, i * 45 + 20
            if not s:
                wedges.append({"d": _wedge(110, 110, 22, 40, a0, a1), "cls": "none", "label": SECTORS[i], "ms": None, "n": d["n"]})
                continue
            r = 22 + 70 * (s / top) ** 2
            cls = ("over" if d["over"] is not None and d["over"] >= 0.08 and d["over"] >= (d["under"] or 0)
                   else "under" if d["under"] is not None and d["under"] >= 0.12 else "ok")
            wedges.append({"d": _wedge(110, 110, 22, r, a0, a1), "cls": cls, "label": SECTORS[i], "ms": round(d["ms"]), "n": d["n"],
                           "over": d["over"], "under": d["under"]})
        out["wheel"] = wedges
    # misses: 13 × 13 cells of 0.5° around the target centre (x right, y up)
    g = n["miss"]["g"]
    if n["miss"]["n"] >= 10 and g:
        mx = max(g.values())
        out["misses"] = [{"x": 8 + (int(k.split(",")[0]) + 6) * 14, "y": 8 + (6 - int(k.split(",")[1])) * 14,
                          "o": round(0.15 + 0.85 * v / mx, 2), "n": v} for k, v in g.items()]
    # profile radar
    prof = profile(n)
    if len(prof) >= 3:
        pts, axes = [], []
        for i, a in enumerate(prof):
            ang = -math.pi / 2 + 2 * math.pi * i / len(prof)
            r = 90 * a["v"] / 100
            pts.append(f"{120 + r * math.cos(ang):.1f},{120 + r * math.sin(ang):.1f}")
            lx, ly = 120 + 108 * math.cos(ang), 120 + 108 * math.sin(ang)
            axes.append({"x2": round(120 + 90 * math.cos(ang), 1), "y2": round(120 + 90 * math.sin(ang), 1),
                         "lx": round(lx, 1), "ly": round(ly, 1), "name": a["name"], "v": a["v"],
                         "anchor": "middle" if abs(math.cos(ang)) < 0.3 else ("start" if math.cos(ang) > 0 else "end")})
        out["radar"] = {"pts": " ".join(pts), "axes": axes,
                        "rings": [" ".join(f"{120 + 90 * k * math.cos(-math.pi / 2 + 2 * math.pi * i / len(prof)):.1f},"
                                           f"{120 + 90 * k * math.sin(-math.pi / 2 + 2 * math.pi * i / len(prof)):.1f}"
                                           for i in range(len(prof))) for k in (0.25, 0.5, 0.75, 1.0)]}
    return out


def build(runs: list[dict], setup: dict) -> dict:
    """Everything the page needs."""
    a = aggregate(runs)
    n = numbers(a, runs)
    found, good = findings(n, setup)
    return {"numbers": n, "findings": found, "good": good, "profile": profile(n), "charts": charts(n),
            "focus": focus_plan(found), "detail_runs": a["runs"], "t": time.time()}
