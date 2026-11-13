"""Team › Practice › Scrims (4.30): a log of scrims. Per scrim: date, opponent, map, score (and the first half if
you have it), which side you started on, what went well and what didn't (in words and as topics), who wrote it.
Over all scrims: the record per map and per opponent, recent form, and which topics keep coming up as good or bad.

Stored per team in data/teams/<tid>/scrims.json: {"scrims": [...]} (newest last)."""
from __future__ import annotations

import re
import secrets
import time
from datetime import date

TOPICS = {"pistols": "Pistol rounds", "ecos": "Eco and anti-eco rounds", "executes": "Executes", "defaults": "Defaults",
          "retakes": "Retakes", "postplant": "Post-plant", "holds": "Site holds", "rotations": "Rotations",
          "trades": "Trades", "utility": "Utility", "clutches": "Clutches", "comms": "Comms", "mid": "Mid control",
          "economy": "Economy calls"}
SIDES = {"attack": "Attack", "defense": "Defense"}
MAX_SCRIMS = 400
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _int(v, lo: int, hi: int) -> int | None:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def clean(form: dict, maps: list[str]) -> tuple[dict | None, str]:
    """A scrim from the form -> (scrim, "") or (None, what's wrong). form: a dict of str or lists (topics)."""
    opp = " ".join(str(form.get("opponent", "")).split())[:40]
    if not opp:
        return None, "Who did you play? Write the opponent's name."
    mp = str(form.get("map", "")).strip()
    if mp not in maps:
        return None, "Pick the map."
    us, them = _int(form.get("us"), 0, 30), _int(form.get("them"), 0, 30)
    if us is None or them is None:
        return None, "Write the score: rounds you won and rounds they won."
    d = str(form.get("date", "")).strip() or date.today().isoformat()
    if not DATE_RE.match(d):
        return None, "That date isn't one (YYYY-MM-DD)."
    h_us, h_them = _int(form.get("h_us"), 0, 15), _int(form.get("h_them"), 0, 15)
    half = [h_us, h_them] if h_us is not None and h_them is not None and h_us <= us and h_them <= them else None
    side = form.get("side") if form.get("side") in SIDES else ""
    good = [x for x in _list(form.get("good")) if x in TOPICS][:6]
    bad = [x for x in _list(form.get("bad")) if x in TOPICS and x not in good][:6]
    return {"date": d, "opponent": opp, "map": mp, "us": us, "them": them, "half": half, "side": side,
            "good": good, "bad": bad, "worked": str(form.get("worked", "")).strip()[:1200],
            "didnt": str(form.get("didnt", "")).strip()[:1200]}, ""


def _list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return [v] if isinstance(v, str) and v else []


def add(data: dict, s: dict, uid: int, by: str) -> dict:
    s = dict(s, id=secrets.token_hex(4), by=by, uid=uid, at=time.time())
    lst = data.setdefault("scrims", [])
    lst.append(s)
    lst.sort(key=lambda x: (x["date"], x["at"]))
    del lst[:-MAX_SCRIMS]
    return s


def result(s: dict) -> str:
    return "win" if s["us"] > s["them"] else ("loss" if s["us"] < s["them"] else "draw")


def summary(scrims: list[dict]) -> dict:
    """Record overall, per map and per opponent; the last ten results; topics that keep coming up (good, bad);
    rounds won per side (from the first half and the side you started on, where you wrote them)."""
    def rec(xs):
        w = sum(1 for s in xs if result(s) == "win")
        lo = sum(1 for s in xs if result(s) == "loss")
        rw, rl = sum(s["us"] for s in xs), sum(s["them"] for s in xs)
        return {"n": len(xs), "w": w, "l": lo, "d": len(xs) - w - lo, "rounds": [rw, rl],
                "rate": round(w / len(xs), 2) if xs else None, "rshare": round(rw / (rw + rl), 2) if rw + rl else None}
    by_map: dict[str, list] = {}
    by_opp: dict[str, list] = {}
    for s in scrims:
        by_map.setdefault(s["map"], []).append(s)
        by_opp.setdefault(s["opponent"].lower(), []).append(s)
    topics = []
    for k, name in TOPICS.items():
        g = sum(1 for s in scrims if k in s.get("good", []))
        b = sum(1 for s in scrims if k in s.get("bad", []))
        recent = scrims[-5:]
        if g or b:
            topics.append({"id": k, "name": name, "good": g, "bad": b,
                           "recent_bad": sum(1 for s in recent if k in s.get("bad", [])),
                           "recent_good": sum(1 for s in recent if k in s.get("good", []))})
    topics.sort(key=lambda x: (-(x["bad"] - x["good"]), -x["bad"]))
    side = {"attack": [0, 0], "defense": [0, 0]}           # rounds won, rounds played per side
    for s in scrims:
        if not s.get("half") or not s.get("side"):
            continue
        first, second = s["side"], "defense" if s["side"] == "attack" else "attack"
        hu, ht = s["half"]
        side[first][0] += hu
        side[first][1] += hu + ht
        side[second][0] += s["us"] - hu
        side[second][1] += (s["us"] - hu) + (s["them"] - ht)
    return {"all": rec(scrims),
            "maps": sorted(({"map": m, **rec(xs)} for m, xs in by_map.items()), key=lambda x: (-x["n"], x["map"])),
            "opps": sorted(({"name": xs[-1]["opponent"], **rec(xs), "last": xs[-1]["date"]} for xs in by_opp.values()),
                           key=lambda x: (-x["n"], x["name"].lower())),
            "form": [result(s) for s in scrims[-10:]],
            "topics": topics,
            "sides": {k: {"won": w, "played": n, "rate": round(w / n, 2) if n else None} for k, (w, n) in side.items()}}


def tendencies(sm: dict) -> list[dict]:
    """What the scrims keep showing, as lines for the page: [{kind, label, items}] (items: topic or map names, shown
    one by one so they translate), kinds bad, good, maps, side."""
    out = []
    bad = [t for t in sm["topics"] if t["bad"] >= 2 and t["bad"] > t["good"]]
    if bad:
        out.append({"kind": "bad", "label": "Keeps coming up as a problem", "items": [t["name"] for t in bad[:3]]})
    good = [t for t in sorted(sm["topics"], key=lambda x: -(x["good"] - x["bad"])) if t["good"] >= 2 and t["good"] > t["bad"]]
    if good:
        out.append({"kind": "good", "label": "Keeps working", "items": [t["name"] for t in good[:3]]})
    maps = [m for m in sm["maps"] if m["n"] >= 2]
    if len(maps) >= 2:
        best = max(maps, key=lambda m: (m["rshare"] or 0))
        worst = min(maps, key=lambda m: (m["rshare"] or 0))
        if best["map"] != worst["map"]:
            out.append({"kind": "maps", "label": "Best and worst map (rounds won)",
                        "items": [f"{best['map']} {round(100 * best['rshare'])}%", f"{worst['map']} {round(100 * worst['rshare'])}%"]})
    sd = sm["sides"]
    if sd["attack"]["played"] >= 24 and sd["defense"]["played"] >= 24:
        a, d = sd["attack"]["rate"], sd["defense"]["rate"]
        if abs(a - d) >= 0.08:
            out.append({"kind": "side", "label": "Weaker side", "items": ["Attack" if a < d else "Defense",
                                                                           f"{round(100 * min(a, d))}% / {round(100 * max(a, d))}%"]})
    return out
