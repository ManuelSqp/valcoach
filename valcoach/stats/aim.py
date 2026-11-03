"""Aim routines: a small library (built-in in-game routines, your own, your team's), the routine that fits
what your matches show, a warm-up before matches, and whether warming up goes with a better headshot rate.

valcoach can't start or read Aimlabs or KovaaK's: a routine is an Aimlabs share link (opening it starts
Aimlabs and offers the playlist), a KovaaK's share code (pasted in KovaaK's), any other link, or plain steps
for the Range / Deathmatch. Scores are only what you type in yourself.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import habits as hb

FOCUS = {"warmup": "Warm-up", "crosshair": "Crosshair placement", "flicks": "Flicks", "micro": "Micro-adjusting",
         "tracking": "Tracking", "spray": "Spray control", "peeking": "Peeking & first shots",
         "switching": "Target switching", "reaction": "Reaction"}
KINDS = {"aimlabs": "Aimlabs playlist", "kovaaks": "KovaaK's playlist", "link": "Link", "steps": "In game",
         "kovaaksfile": "KovaaK's playlist from the coach"}
ADDABLE = ("aimlabs", "kovaaks", "link", "steps")      # kinds people can add (the coach's files are made for them)
CODE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{3,63}")
MAX_STEPS = 600
MIN_GAMES = 5                     # games on each side before "did it help" says anything

BUILTIN: list[dict] = [
    {"id": "b-range", "name": "Range warm-up", "kind": "steps", "minutes": 10, "focus": ["warmup", "crosshair", "flicks"],
     "steps": "Range, bots on medium then hard, strafing on. 2 min Sheriff (heads only), 3 min Vandal one-taps, "
              "3 min Vandal short bursts, 2 min moving between bots without shooting: keep the crosshair at head height."},
    {"id": "b-hsdm", "name": "Headshot-only deathmatch", "kind": "steps", "minutes": 10, "focus": ["warmup", "crosshair"],
     "steps": "One Deathmatch with a Vandal or Sheriff: only aim for the head, no spraying. Walk, stop, shoot. "
              "Count your kills, not your deaths."},
    {"id": "b-peek", "name": "Peek and first-shot drill", "kind": "steps", "minutes": 10, "focus": ["peeking", "flicks"],
     "steps": "Custom game or Range with a friend holding angles: wide swing, jiggle and shoulder peek the same angle "
              "10 times each. Shoot only when you've stopped. Swap who holds."},
    {"id": "b-micro", "name": "Micro-adjust at long range", "kind": "steps", "minutes": 8, "focus": ["micro", "crosshair"],
     "steps": "Range, bots at long distance, strafing slow. One-tap heads with the Vandal; after each kill move the "
              "crosshair only a little to the next head. Missed? Reset to head height, don't flick."},
    {"id": "b-spray", "name": "Spray control at the wall", "kind": "steps", "minutes": 5, "focus": ["spray"],
     "steps": "Range wall: 5-bullet bursts, then 10-bullet sprays with Vandal and Phantom, pulling down. "
              "Then the same on a strafing bot at close range."},
]


def new_id() -> str:
    return "r-" + secrets.token_hex(4)


def clean(form: dict) -> tuple[dict | None, str]:
    """A routine from a form, or (None, why not). Links must be http(s); codes are letters, numbers, - and _."""
    name = str(form.get("name") or "").strip()[:60]
    kind = form.get("kind") if form.get("kind") in ADDABLE else ""
    if not name:
        return None, "Give the routine a name."
    if not kind:
        return None, "Pick what it is (Aimlabs, KovaaK's, a link or steps)."
    try:
        minutes = max(1, min(90, int(form.get("minutes") or 10)))
    except (TypeError, ValueError):
        minutes = 10
    focus = [f for f in (form.get("focus") or []) if f in FOCUS][:4]
    r = {"id": new_id(), "name": name, "kind": kind, "minutes": minutes, "focus": focus or ["warmup"],
         "steps": str(form.get("steps") or "").strip()[:MAX_STEPS], "url": "", "code": ""}
    if kind in ("aimlabs", "link"):
        url = str(form.get("url") or "").strip()[:400]
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return None, "The link must start with https://"
        r["url"] = url
    elif kind == "kovaaks":
        code = str(form.get("code") or "").strip()
        if not CODE_RE.fullmatch(code):
            return None, "A KovaaK's share code is letters, numbers, - and _ (4 to 64 characters)."
        r["code"] = code
    elif not r["steps"]:
        return None, "Write down the steps."
    return r, ""


def is_aimlabs(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return "aimlab" in host


def needs(rows: list[dict]) -> list[dict]:
    """What your matches say your aim needs: [{focus: [...], why, weight}], most important first."""
    h = hb.track(rows)
    by = {x["key"]: x for x in h.get("habits", [])}
    out = []
    aim = by.get("aim")
    if aim and aim["now"] is not None and (aim["problem"] or aim["now"] < aim["bad_at"] + 0.03):
        out.append({"focus": ["crosshair", "micro"], "weight": 3 if aim["problem"] else 1, "key": "aim",
                    "why": f"Your headshot rate is {aim['now']:.0%} in your last games (it starts to cost duels under {aim['bad_at']:.0%})."})
    op = by.get("opening")
    if op and op["now"] is not None and (op["problem"] or op["now"] > op["bad_at"] - 0.05):
        out.append({"focus": ["peeking", "flicks", "reaction"], "weight": 3 if op["problem"] else 1, "key": "opening",
                    "why": f"You lose {op['now']:.0%} of the first duels you're in."})
    if not out:
        out.append({"focus": ["warmup"], "weight": 1, "key": "",
                    "why": "Nothing in your aim stands out: a short warm-up before you play is enough."
                    if h.get("games") else "No games with round data yet: start with a warm-up."})
    return sorted(out, key=lambda x: -x["weight"])


def pick(routines: list[dict], need: list[dict], n: int = 3) -> list[dict]:
    """The routines that fit best, each with the reason. Your own and the team's win ties over built-in ones."""
    scored = []
    for r in routines:
        s, why = 0, ""
        for x in need:
            hit = len(set(r.get("focus") or []) & set(x["focus"]))
            if hit:
                s += hit * x["weight"]
                why = why or x["why"]
        if s:
            scored.append((s, r.get("source") != "builtin", -int(r.get("minutes") or 10), r, why))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [dict(r, why=why) for _, _, _, r, why in scored[:n]]


def warmup_for(routines: list[dict], chosen: str | None, team_choice: str | None = None) -> dict | None:
    """Your warm-up: the one you picked, else the team's, else the shortest warm-up routine."""
    by = {r["id"]: r for r in routines}
    for rid in (chosen, team_choice):
        if rid and rid in by:
            return by[rid]
    ws = [r for r in routines if "warmup" in (r.get("focus") or [])]
    return min(ws, key=lambda r: (r.get("source") == "builtin", int(r.get("minutes") or 10))) if ws else None


def _local_day(started_at: str) -> str:
    try:
        d = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError:
        return str(started_at)[:10]
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone().date().isoformat()


def effect(rows: list[dict], log: list[dict], extra_days: set[str] | None = None) -> dict:
    """Headshot rate in games on days you warmed up against the other days since your first warm-up.
    extra_days: days with an aim trainer run (KovaaK's scores) count as warm-up days too."""
    days = {x["date"] for x in log if x.get("date")} | set(extra_days or ())
    out: dict = {"days": len(days), "with": {"games": 0, "hs": None}, "without": {"games": 0, "hs": None}, "ready": False}
    if not days:
        return out
    first = min(days)
    acc = {"with": [0, 0, 0], "without": [0, 0, 0]}
    for r in rows:
        if r.get("source") != "full" or not r.get("shots"):
            continue
        day = _local_day(r.get("started_at") or "")
        if day < first:
            continue
        h, b, lg = (r["shots"] + [0, 0, 0])[:3]
        k = "with" if day in days else "without"
        acc[k][0] += h
        acc[k][1] += h + b + lg
        acc[k][2] += 1
    for k, (h, tot, g) in acc.items():
        out[k] = {"games": g, "hs": h / tot if tot else None}
    out["ready"] = all(out[k]["games"] >= MIN_GAMES and out[k]["hs"] is not None for k in ("with", "without"))
    if out["ready"]:
        out["diff"] = out["with"]["hs"] - out["without"]["hs"]
    return out


def scores(log: list[dict], rid: str, n: int = 12) -> list[dict]:
    """The scores you typed in for one routine, oldest first."""
    xs = [x for x in log if x.get("routine") == rid and x.get("score") is not None]
    return sorted(xs, key=lambda x: x.get("t", 0))[-n:]
