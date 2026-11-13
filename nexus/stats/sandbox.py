"""The aim trainer's sandbox (4.33): your own scenarios, made from the same builders as the built-in ones
(static/trainer.js). You pick a type and set its numbers; nothing else, so a shared scenario can't carry code.

A scenario: {id, type, name, about, seconds, skill, level, params, by, uid, at}. Kept per user in
data/sandbox/user-<uid>.json and per team in data/teams/<tid>/sandbox.json ({"items": [...]}). A share code is the
scenario itself (type, name, seconds, params) as compact JSON in base64url: pasting one checks it like a save."""
from __future__ import annotations

import base64
import json
import secrets
import time

# per type: label, kind, what it is, and its settings. A number: (label, min, max, step, default). A switch: (label,
# "bool", default). A choice: (label, "choice", [values], default). Pairs with _min/_max are kept in order.
N, BOOL, CHOICE = "num", "bool", "choice"
TYPES: dict[str, dict] = {
    "flicks": {"label": "Flicks", "kind": "click", "about": "One target at a time, somewhere away from the crosshair.", "params": {
        "amin": ("Angle from the crosshair, min (°)", 1, 170, 1, 15), "amax": ("Angle from the crosshair, max (°)", 2, 175, 1, 45),
        "dmin": ("Distance, min (m)", 3, 32, 0.5, 10), "dmax": ("Distance, max (m)", 3, 32, 0.5, 14),
        "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.28), "vert": ("Up and down (0 = only sideways)", 0, 1, 0.05, 0.35),
        "back": ("Also behind you", BOOL, False)}},
    "timed": {"label": "Targets that vanish", "kind": "click", "about": "Flicks, but each target is only there for a moment.", "params": {
        "amin": ("Angle from the crosshair, min (°)", 1, 90, 1, 10), "amax": ("Angle from the crosshair, max (°)", 2, 120, 1, 40),
        "dmin": ("Distance, min (m)", 3, 32, 0.5, 10), "dmax": ("Distance, max (m)", 3, 32, 0.5, 13),
        "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.3), "vert": ("Up and down (0 = only sideways)", 0, 1, 0.05, 0.35),
        "life": ("Time on screen at the start (s)", 0.3, 3, 0.05, 1.1), "min": ("Shortest time on screen (s)", 0.2, 2, 0.05, 0.5)}},
    "multi": {"label": "Several on a wall", "kind": "click", "about": "A few targets at once; each hit puts one back somewhere else.", "params": {
        "n": ("Targets at once", 1, 8, 1, 3), "w": ("Spread sideways (± °)", 3, 80, 1, 20),
        "pmin": ("Lowest (° from eye level)", -15, 20, 1, -3), "pmax": ("Highest (° from eye level)", -14, 25, 1, 10),
        "dmin": ("Distance, min (m)", 3, 32, 0.5, 12), "dmax": ("Distance, max (m)", 3, 32, 0.5, 12),
        "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.28), "sep": ("Space between them (°)", 1, 40, 0.5, 6),
        "hp": ("Hits per target", 1, 5, 1, 1), "head": ("All at head height", BOOL, False)}},
    "spider": {"label": "Spider", "kind": "click", "about": "A target in the middle, then one around it, back to the middle.", "params": {
        "amin": ("Out, min (°)", 1, 170, 1, 20), "amax": ("Out, max (°)", 2, 175, 1, 45),
        "dmin": ("Distance, min (m)", 3, 32, 0.5, 8), "dmax": ("Distance, max (m)", 3, 32, 0.5, 9),
        "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.3), "flat": ("Up and down (0 = flat)", 0.02, 1, 0.02, 0.55)}},
    "burst": {"label": "Bursts", "kind": "click", "about": "A small group of targets, then the next group further away.", "params": {
        "k": ("Targets per group", 2, 6, 1, 3), "spread": ("Group size (°)", 0.5, 10, 0.5, 3),
        "amin": ("Next group, min (°)", 5, 90, 1, 20), "amax": ("Next group, max (°)", 6, 120, 1, 50),
        "d": ("Distance (m)", 3, 32, 0.5, 12), "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.24)}},
    "bounce": {"label": "Moving targets", "kind": "click", "about": "Targets flying around a wall: click them while they move.", "params": {
        "n": ("Targets at once", 1, 8, 1, 3), "w": ("Spread sideways (± °)", 5, 75, 1, 28),
        "pmin": ("Lowest (° from eye level)", -15, 20, 1, -4), "pmax": ("Highest (° from eye level)", -14, 25, 1, 14),
        "d": ("Distance (m)", 4, 32, 0.5, 12), "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.3),
        "smin": ("Speed, min (m/s)", 0.2, 10, 0.1, 2), "smax": ("Speed, max (m/s)", 0.3, 12, 0.1, 4),
        "jink": ("Change direction suddenly", BOOL, False), "grav": ("Hop and fall", BOOL, False),
        "horiz": ("Only sideways", BOOL, False), "toward": ("Come at you", BOOL, False),
        "life": ("Shrink and vanish after (s, 0 = never)", 0, 6, 0.1, 0)}},
    "popups": {"label": "Pop-ups", "kind": "click", "about": "Targets pop up on their own and vanish; blue ones mustn't be shot.", "params": {
        "w": ("Spread sideways (± °)", 5, 85, 1, 35), "pmin": ("Lowest (° from eye level)", -15, 20, 1, -3),
        "pmax": ("Highest (° from eye level)", -14, 25, 1, 12), "dmin": ("Distance, min (m)", 3, 32, 0.5, 10),
        "dmax": ("Distance, max (m)", 3, 32, 0.5, 13), "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.3),
        "every_min": ("A new one every, min (s)", 0.15, 3, 0.05, 0.35), "every_max": ("A new one every, max (s)", 0.2, 4, 0.05, 0.7),
        "life": ("Time on screen (s)", 0.3, 4, 0.05, 1.1), "bad": ("Share of blue ones", 0, 0.7, 0.05, 0),
        "max": ("At most at once", 1, 8, 1, 4)}},
    "onetap": {"label": "One taps", "kind": "click", "about": "Heads at head height; only the first shot counts.", "params": {
        "n": ("Heads at once", 1, 5, 1, 1), "w": ("Spread sideways (± °)", 3, 85, 1, 30),
        "dmin": ("Distance, min (m)", 3, 32, 0.5, 10), "dmax": ("Distance, max (m)", 3, 32, 0.5, 14),
        "r": ("Head size (m)", 0.06, 0.4, 0.01, 0.15), "life": ("Gone after (s, 0 = never)", 0, 4, 0.05, 0)}},
    "tracker": {"label": "Strafe tracking", "kind": "track", "about": "One target strafing left and right: stay on it.", "params": {
        "d": ("Distance (m)", 3, 32, 0.5, 9), "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.38), "y": ("Height (m)", 0.5, 5, 0.05, 1.4),
        "vmin": ("Speed, min (m/s)", 0.3, 10, 0.1, 2.4), "vmax": ("Speed, max (m/s)", 0.4, 12, 0.1, 5.2),
        "fmin": ("Turns after, min (s)", 0.08, 4, 0.02, 0.25), "fmax": ("Turns after, max (s)", 0.1, 5, 0.02, 1.1),
        "bound": ("Room to the sides (m)", 1, 12, 0.5, 5), "stop": ("Stops now and then (share)", 0, 0.8, 0.05, 0),
        "jump": ("Jumps", BOOL, False), "duck": ("Crouches", BOOL, False)}},
    "glide": {"label": "Path tracking", "kind": "track", "about": "One target gliding over a wall along lines, curves, stars or circles.", "params": {
        "path": ("Path", CHOICE, ["line", "arc", "star", "circle"], "line"),
        "w": ("Spread sideways (± °)", 3, 60, 1, 25), "pmin": ("Lowest (° from eye level)", -15, 20, 1, -2),
        "pmax": ("Highest (° from eye level)", -14, 25, 1, 14), "d": ("Distance (m)", 3, 32, 0.5, 10),
        "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.32), "smin": ("Speed, min (m/s)", 0.3, 10, 0.1, 2.5),
        "smax": ("Speed, max (m/s)", 0.4, 12, 0.1, 4), "R": ("Circle size (m)", 0.3, 4, 0.1, 1.5),
        "blink": ("Jumps somewhere else now and then", BOOL, False)}},
    "orbit": {"label": "Around you", "kind": "track", "about": "A target circling around you at a distance.", "params": {
        "d": ("Distance (m)", 3, 25, 0.5, 7), "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.36), "y": ("Height (m)", 0.5, 5, 0.05, 1.4),
        "wmin": ("Speed, min (°/s)", 5, 150, 1, 25), "wmax": ("Speed, max (°/s)", 6, 180, 1, 60),
        "fmin": ("Changes after, min (s)", 0.2, 4, 0.05, 0.6), "fmax": ("Changes after, max (s)", 0.3, 5, 0.05, 1.6),
        "span": ("How far around (± °)", 20, 85, 1, 75), "jump": ("Hops", BOOL, False), "vy": ("Up and down speed (m/s)", 0, 4, 0.1, 0)}},
    "tswitch": {"label": "Switch tracking", "kind": "track", "about": "Several moving targets, each goes down after a moment of fire.", "params": {
        "n": ("Targets at once", 2, 6, 1, 3), "w": ("Spread sideways (± °)", 5, 75, 1, 25),
        "pmin": ("Lowest (° from eye level)", -15, 20, 1, -3), "pmax": ("Highest (° from eye level)", -14, 25, 1, 12),
        "d": ("Distance (m)", 3, 32, 0.5, 10), "r": ("Target size (m)", 0.06, 0.6, 0.01, 0.34),
        "hp": ("Seconds of fire to take one down", 0.1, 3, 0.05, 0.6), "smin": ("Speed, min (m/s)", 0.2, 10, 0.1, 1.5),
        "smax": ("Speed, max (m/s)", 0.3, 12, 0.1, 3), "fmin": ("Turns after, min (s)", 0.1, 4, 0.05, 0.6),
        "fmax": ("Turns after, max (s)", 0.2, 5, 0.05, 1.6), "vy": ("Up and down speed (m/s)", 0, 4, 0.1, 0),
        "evade": ("Dodges when you're on it", 0, 6, 0.5, 0)}},
    "peeks": {"label": "Peeks", "kind": "click", "about": "Targets peek out from behind three pieces of cover.", "params": {
        "z": ("Distance (m)", 5, 32, 0.5, 14), "spread": ("Space between covers (m)", 2, 10, 0.5, 4.5),
        "r": ("Target size (m)", 0.06, 0.5, 0.01, 0.26), "win": ("Out for, at the start (s)", 0.2, 2.5, 0.05, 0.9),
        "min": ("Out for, shortest (s)", 0.15, 2, 0.05, 0.38), "oneshot": ("One shot each", BOOL, False)}},
    "angle": {"label": "Hold the angle", "kind": "click", "about": "A doorway: an enemy model swings, jiggles or runs through.", "params": {
        "dmin": ("Distance, min (m)", 4, 32, 0.5, 10), "dmax": ("Distance, max (m)", 4, 32, 0.5, 17),
        "wmin": ("Door width, min (m)", 1.5, 6, 0.1, 2.6), "wmax": ("Door width, max (m)", 1.6, 7, 0.1, 4.2),
        "swing": ("Share of wide swings", 0, 1, 0.05, 0.5), "jiggle": ("Share of jiggles", 0, 1, 0.05, 0.25),
        "win": ("Stays in the door, at the start (s)", 0.2, 2.5, 0.05, 0.8), "min": ("Stays, shortest (s)", 0.15, 2, 0.05, 0.42),
        "fast": ("Speed", 0.5, 2, 0.05, 1), "oneshot": ("One shot each", BOOL, False)}},
}
SKILL_KEYS = ("", "tracking", "flicks", "onetap", "micro", "switching", "reaction", "peeks")
MAX_ITEMS = 60
CODE_MAX = 3000


def _pair(p: dict, a: str, b: str) -> None:
    if a in p and b in p and p[a] > p[b]:
        p[a], p[b] = p[b], p[a]


def clean(d: dict) -> tuple[dict | None, str]:
    """A scenario from the editor or a share code -> (scenario without id/author, "") or (None, what's wrong)."""
    if not isinstance(d, dict) or d.get("type") not in TYPES:
        return None, "Pick a type."
    t = TYPES[d["type"]]
    name = " ".join(str(d.get("name") or "").split())[:40]
    if not name:
        return None, "Give it a name."
    try:
        seconds = int(d.get("seconds") or 45)
    except (TypeError, ValueError):
        seconds = 45
    seconds = min(120, max(15, seconds))
    raw = d.get("params") if isinstance(d.get("params"), dict) else {}
    p: dict = {}
    for k, spec in t["params"].items():
        v = raw.get(k)
        if spec[1] == BOOL:
            p[k] = bool(v) if isinstance(v, bool) else spec[2]
        elif spec[1] == CHOICE:
            p[k] = v if v in spec[2] else spec[3]
        else:
            lo, hi, step, default = spec[1], spec[2], spec[3], spec[4]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                v = default
            v = min(hi, max(lo, float(v)))
            p[k] = int(round(v)) if step >= 1 else round(v, 3)
    for a, b in (("amin", "amax"), ("dmin", "dmax"), ("pmin", "pmax"), ("smin", "smax"), ("vmin", "vmax"),
                 ("fmin", "fmax"), ("wmin", "wmax"), ("every_min", "every_max"), ("min", "life"), ("min", "win")):
        _pair(p, a, b)
    if "pmin" in p and p["pmax"] - p["pmin"] < 1:
        p["pmax"] = p["pmin"] + 1
    skill = d.get("skill") if d.get("skill") in SKILL_KEYS else ""
    try:
        level = min(3, max(1, int(d.get("level") or 2)))
    except (TypeError, ValueError):
        level = 2
    return {"type": d["type"], "kind": t["kind"], "name": name, "about": " ".join(str(d.get("about") or "").split())[:200],
            "seconds": seconds, "skill": skill, "level": level, "params": p}, ""


def builder_options(sc: dict) -> dict:
    """What the page's builder gets: the settings, with the switches and pairs it expects."""
    p = dict(sc["params"])
    t = sc["type"]
    if t == "bounce":
        p["jink"] = [0.35, 0.9] if p.get("jink") else None
        if p.get("grav"):
            p["grav"], p["hop"] = 9, 7
        else:
            p.pop("grav", None)
        if p.get("toward"):
            p["near"] = 5
        if p.get("life"):
            p["shrink"] = 0.3
        else:
            p.pop("life", None)
        p = {k: v for k, v in p.items() if v is not None and v is not False}
    elif t == "popups":
        p["every"] = [p.pop("every_min"), p.pop("every_max")]
    elif t == "glide":
        p["bmin"], p["bmax"] = 90, 200
        p["blink"] = [1.1, 2.0] if p.get("blink") else None
        p = {k: v for k, v in p.items() if v is not None}
    elif t == "onetap" and not p.get("life"):
        p.pop("life", None)
    elif t == "tracker":
        p["acc"] = 26 if p["fmin"] > 0.2 else 60
    if t in ("tracker",) and (p.get("jump") or p.get("duck")):
        t = "strafer"
    for k in ("jump", "duck", "back", "head", "horiz", "toward", "oneshot"):
        if p.get(k) is False:
            p.pop(k)
    return {"builder": t, "o": p}


def to_page(sc: dict) -> dict:
    """A saved scenario as the trainer page needs it."""
    out = {k: sc[k] for k in ("id", "type", "kind", "name", "about", "seconds", "skill", "level", "params") if k in sc}
    out.update(builder_options(sc))
    for k in ("by", "uid", "scope", "tid"):
        if k in sc:
            out[k] = sc[k]
    return out


def add(data: dict, sc: dict, uid: int, by: str, sid: str = "") -> dict:
    items = data.setdefault("items", [])
    old = next((x for x in items if x["id"] == sid), None) if sid else None
    if old is not None:
        old.update(sc, at=time.time())
        return old
    new = dict(sc, id="c" + secrets.token_hex(4), uid=uid, by=by, at=time.time())
    items.append(new)
    del items[:-MAX_ITEMS]
    return new


def code(sc: dict) -> str:
    """A share code: the scenario (type, name, about, seconds, skill, level, settings) in base64url."""
    body = {k: sc[k] for k in ("type", "name", "about", "seconds", "skill", "level", "params") if k in sc}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    return "NX1-" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(s: str) -> tuple[dict | None, str]:
    s = "".join(str(s or "").split())
    if not s.startswith("NX1-") or len(s) > CODE_MAX:
        return None, "That isn't a Nexus scenario code (they start with NX1-)."
    try:
        raw = base64.urlsafe_b64decode(s[4:] + "=" * (-len(s[4:]) % 4))
        d = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError):
        return None, "That code is broken: copy it again, all of it."
    return clean(d)
