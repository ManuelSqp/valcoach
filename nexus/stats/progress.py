"""Progress over time: the numbers that matter, week by week, and whether a weekly focus worked.

Works on a player's game rows (stats/games.py). Round-level numbers (KAST, first duels, trades,
clutches, headshots, duel ranges) need rows from full matches; the rest also use the archive."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _full(rows):
    return [r for r in rows if r.get("source") == "full"]


def _sum(rows, k):
    return sum(r.get(k) or 0 for r in rows)


def _ratio(a, b):
    return a / b if b else None


def _shots(rows):
    h = b = l = 0
    for r in _full(rows):
        s = r.get("shots") or [0, 0, 0]
        h, b, l = h + s[0], b + s[1], l + s[2]
    return h, b, l


def _clutch(rows):
    att = won = 0
    for r in _full(rows):
        for x, (a, w) in (r.get("clutch") or {}).items():
            att += a
            won += w
    return att, won


def _pair(rows, k):
    n = w = 0
    for r in _full(rows):
        v = r.get(k) or [0, 0]
        n, w = n + v[0], w + v[1]
    return n, w


# key: (label, value(rows), format, higher is better, needs full rows, min sample)
METRICS = {
    "win_rate": ("Win rate", lambda rs: _ratio(sum(r["won"] for r in rs), len(rs)), "pct", True, False, 3),
    "acs": ("ACS", lambda rs: _ratio(sum(r["acs"] for r in rs), len(rs)), "int", True, False, 3),
    "kd": ("K/D", lambda rs: _ratio(_sum(rs, "kills"), _sum(rs, "deaths")), "dec", True, False, 3),
    "adr": ("ADR", lambda rs: _ratio(sum(r.get("adr") or 0 for r in rs), len(rs)), "int", True, False, 3),
    "kast": ("KAST", lambda rs: _ratio(_sum(_full(rs), "kast"), _sum(_full(rs), "rounds")), "pct", True, True, 2),
    "first_duels": ("First duels won", lambda rs: _ratio(_sum(_full(rs), "fk"), _sum(_full(rs), "fk") + _sum(_full(rs), "fd")), "pct", True, True, 2),
    "traded": ("Deaths traded", lambda rs: _ratio(_sum(_full(rs), "traded_deaths"), _sum(_full(rs), "deaths")), "pct", True, True, 2),
    "alone": ("Deaths far from the team", lambda rs: _ratio(sum((r.get("iso") or {}).get(s, [0, 0, 0, 0])[3] for r in _full(rs) for s in ("attack", "defense")),
                                                              _sum(_full(rs), "deaths")), "pct", False, True, 2),
    "survival": ("Rounds survived", lambda rs: _ratio(sum(sum((r.get("survived") or {}).values()) for r in _full(rs)), _sum(_full(rs), "rounds")), "pct", True, True, 2),
    "hs": ("Headshots", lambda rs: (lambda h, b, l: _ratio(h, h + b + l))(*_shots(rs)), "pct", True, True, 2),
    "clutch": ("Clutches won", lambda rs: (lambda a, w: _ratio(w, a) if a >= 2 else None)(*_clutch(rs)), "pct", True, True, 2),
    "retake": ("Retakes won", lambda rs: (lambda n, w: _ratio(w, n) if n >= 3 else None)(*_pair(rs, "retake")), "pct", True, True, 2),
}
ORDER = ["win_rate", "acs", "kd", "kast", "first_duels", "traded", "alone", "survival", "hs", "clutch", "retake", "adr"]

# words in a weekly focus' "number to watch" -> metric
ALIASES = [
    (r"kast", "kast"), (r"first (duel|blood|kill|fight)|opening|entry", "first_duels"), (r"trad", "traded"),
    (r"alone|isolat|far from|without (a )?team", "alone"), (r"surviv|stay alive|death", "survival"),
    (r"head ?shot|hs%|\bhs\b|crosshair", "hs"), (r"clutch", "clutch"), (r"retake", "retake"),
    (r"\bacs\b|combat score", "acs"), (r"\badr\b|damage", "adr"), (r"k/?d|kill.?death", "kd"), (r"win", "win_rate"),
]


def metric_for(text: str) -> str | None:
    t = (text or "").lower()
    for pat, key in ALIASES:
        if re.search(pat, t):
            return key
    return None


def value(rows: list[dict], key: str):
    label, fn, fmt, hib, full, min_n = METRICS[key]
    rs = _full(rows) if full else rows
    if len(rs) < min_n:
        return None
    try:
        return fn(rows)
    except (TypeError, ZeroDivisionError):
        return None


def fmt(key: str, v) -> str:
    if v is None:
        return "–"
    f = METRICS[key][2]
    return f"{v:.0%}" if f == "pct" else (f"{v:.2f}" if f == "dec" else f"{v:.0f}")


def _week_start(d: datetime) -> datetime:
    d = d.astimezone(timezone.utc)
    return (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _when(r) -> datetime | None:
    try:
        return datetime.fromisoformat(str(r.get("started_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def weekly(rows: list[dict], weeks: int = 10, now: datetime | None = None) -> list[dict]:
    """The last `weeks` weeks, oldest first: {week, label, games, values: {metric: value}}."""
    now = now or datetime.now(timezone.utc)
    start0 = _week_start(now) - timedelta(weeks=weeks - 1)
    buckets: dict[datetime, list] = defaultdict(list)
    for r in rows:
        d = _when(r)
        if d and d >= start0:
            buckets[_week_start(d)].append(r)
    out = []
    for i in range(weeks):
        ws = start0 + timedelta(weeks=i)
        rs = buckets.get(ws, [])
        y, w, _ = ws.isocalendar()
        out.append({"week": f"{y}-W{w:02d}", "label": ws.strftime("%d.%m"), "games": len(rs),
                    "full": len(_full(rs)), "values": {k: value(rs, k) for k in ORDER}})
    return out


def trend(rows: list[dict], key: str, now: datetime | None = None) -> dict:
    """Last 2 weeks vs the 6 weeks before."""
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(days=14)
    old_cut = now - timedelta(days=56)
    recent = [r for r in rows if (_when(r) or now) >= cut]
    before = [r for r in rows if old_cut <= (_when(r) or now) < cut]
    a, b = value(recent, key), value(before, key)
    d = None if a is None or b is None else a - b
    better = None
    if d is not None and abs(d) > (0.02 if METRICS[key][2] == "pct" else 0.05 * max(abs(b), 1)):
        better = (d > 0) == METRICS[key][3]
    return {"now": a, "before": b, "delta": d, "better": better}


def _num(text: str) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(text or ""))
    if not m:
        return None
    v = float(m.group(0).replace(",", "."))
    return v / 100 if "%" in str(text) else v


def focus_check(rows: list[dict], week: str, focus: dict) -> dict | None:
    """Did the number of a weekly focus move? Compares the games after the focus week started
    with the 'now' value written in the focus (or the games before it)."""
    n = (focus or {}).get("number_to_watch") or {}
    key = metric_for(n.get("metric", "")) or metric_for(focus.get("focus", ""))
    if not key:
        return None
    try:
        y, w = week.split("-W")
        start = datetime.fromisocalendar(int(y), int(w), 1).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    after = [r for r in rows if (_when(r) or start) >= start]
    before = [r for r in rows if start - timedelta(days=21) <= (_when(r) or start) < start]
    now_v = value(after, key)
    base = _num(n.get("now"))
    if base is None or (METRICS[key][2] == "pct" and base > 1):
        base = value(before, key)
    goal = _num(n.get("goal"))
    if goal is not None and METRICS[key][2] == "pct" and goal > 1:
        goal = goal / 100
    res = {"metric": key, "label": METRICS[key][0], "before": base, "now": now_v, "goal": goal,
           "games": len(after), "text": n.get("metric") or METRICS[key][0]}
    if now_v is None or base is None:
        res["verdict"] = "too few games yet"
        return res
    up = (now_v - base) if METRICS[key][3] else (base - now_v)
    if goal is not None and ((now_v >= goal) if METRICS[key][3] else (now_v <= goal)):
        res["verdict"], res["ok"] = "goal reached", True
    elif up > 0.01:
        res["verdict"], res["ok"] = "better", True
    elif up < -0.01:
        res["verdict"], res["ok"] = "worse", False
    else:
        res["verdict"], res["ok"] = "no change", None
    return res
