"""Habit tracker: habits that cost rounds, measured game by game, and whether they're going away.

Each habit is one number per game (games with round data only), with a line where it starts to
cost you. For every habit we compare your recent games (the last RECENT) with the games before
(up to BEFORE more) and say: gone, getting better, still there, getting worse, or fine.

Things the coach named in reports (match reviews, Premier reviews) are matched to a habit by
their words ("died alone", "not traded", "lost the first duel", "aim", a callout you keep dying
at). For those we compare the games before the report with the games after it, so you see
whether the tip worked. What can't be matched is listed as a note with how often it came up.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

RECENT = 10          # "now": your last 10 games with round data
BEFORE = 20          # "before": up to 20 games before those
MIN_GAMES = 4        # per side of the comparison

# key -> (title, what it means, direction, threshold, unit, drills)
#   direction "high" = a high number is the problem
HABITS: dict[str, dict] = {
    "alone": {"title": "Dying far from the team", "what": "share of your deaths where no teammate was within 20 m",
              "dir": "high", "bad": 0.35, "fmt": "pct",
              "drill": "Play within trading range: in customs, entry + trader pairs (2v2); in games, call your position before you peek.",
              "words": r"alone|isolat|by yourself|far from (the|your) team|no one (near|close)|without (a )?teammate|lurk"},
    "untraded": {"title": "Deaths nobody trades", "what": "share of your deaths no teammate paid back within a few seconds",
                 "dir": "high", "bad": 0.70, "fmt": "pct",
                 "drill": "Before you take a fight, check that someone can trade it; as the trader, stay 1 to 2 seconds behind the entry.",
                 "words": r"untraded|not traded|trade|refrag|nobody (could )?(help|follow)"},
    "opening": {"title": "Losing the first duel", "what": "share of the round's first duels you were in that you lost",
                "dir": "high", "bad": 0.55, "fmt": "pct",
                "drill": "Deathmatch with only first-shot kills; in games, take the first duel only with utility or a teammate ready.",
                "words": r"first (death|duel|fight)|opening|dry peek|peek(ed|ing)? (wide|without)|entry duel|died first"},
    "kast": {"title": "Rounds without impact", "what": "rounds without a kill, an assist, surviving or being traded (1 − KAST)",
             "dir": "high", "bad": 0.35, "fmt": "pct",
             "drill": "Each round, do one useful thing: utility for a teammate, a trade, or stay alive for the retake / post-plant.",
             "words": r"\bkast\b|impact|no (kills|damage)|0[- ]damage|zero damage"},
    "aim": {"title": "Low headshot rate", "what": "share of your hits that are headshots",
            "dir": "low", "bad": 0.17, "fmt": "pct",
            "drill": "10 min crosshair placement at head height (Range, bots on hard), then deathmatch aiming only at the head.",
            "words": r"crosshair|headshot|aim|spray|leg ?shot|head height"},
    "no_util": {"title": "Dying with utility unused", "what": "share of your deaths in rounds where you used no ability",
                "dir": "high", "bad": 0.45, "fmt": "pct",
                "drill": "Plan one ability per round before you peek: a flash, a smoke, a scan or a wall, then the fight.",
                "words": r"utility|abilit|didn.t use|unused|save(d)? (your )?(util|abilit)"},
    "spot": {"title": "Dying at the same spot", "what": "share of your deaths at your most common death spot",
             "dir": "high", "bad": 0.30, "fmt": "pct",
             "drill": "Change how you play your death spot: a different angle, utility first, or play it with a teammate.",
             "words": None},
}
STATUS_TEXT = {"gone": "Gone", "better": "Getting better", "same": "Still there", "worse": "Getting worse",
               "fine": "Fine", "new": "New", "few": "Too few games"}


def _full(rows: list[dict]) -> list[dict]:
    full = [r for r in rows if r.get("source") == "full" and r.get("rounds")]
    return sorted(full, key=lambda r: r.get("started_at") or "")


def _sum(rows: list[dict], key: str) -> tuple[float, float] | None:
    """(numerator, denominator) for one habit over several games."""
    num = den = 0.0
    for r in rows:
        if key == "alone":
            num += sum(r["iso"][s][3] for s in ("attack", "defense"))
            den += sum(r["iso"][s][2] for s in ("attack", "defense"))
        elif key == "untraded":
            num += r["deaths"] - r.get("traded_deaths", 0)
            den += r["deaths"]
        elif key == "opening":
            num += r.get("fd", 0)
            den += r.get("fk", 0) + r.get("fd", 0)
        elif key == "kast":
            num += r["rounds"] - r.get("kast", 0)
            den += r["rounds"]
        elif key == "no_util":
            nu = r.get("no_util")
            if nu:
                num += nu[0]
                den += nu[1]
        elif key == "aim":
            h, b, lg = (r.get("shots") or [0, 0, 0])[:3]
            num += h
            den += h + b + lg
    return (num, den) if den else None


def _value(rows: list[dict], key: str, spot: str | None = None) -> float | None:
    if key == "spot":
        deaths = [d for r in rows for d in r.get("deaths_at", []) if d[1] and d[1] != "?"]
        if len(deaths) < 4 or not spot:
            return None
        return sum(1 for d in deaths if d[1] == spot) / len(deaths)
    s = _sum(rows, key)
    if not s:
        return None
    num, den = s
    return num / den if den >= 3 else None


def _bad(key: str, v: float | None) -> bool:
    if v is None:
        return False
    h = HABITS[key]
    return v > h["bad"] if h["dir"] == "high" else v < h["bad"]


def _status(key: str, before: float | None, now: float | None, n_before: int, n_now: int) -> str:
    if now is None or n_now < MIN_GAMES:
        return "few"
    h = HABITS[key]
    better = (lambda a, b: a < b) if h["dir"] == "high" else (lambda a, b: a > b)
    if before is None or n_before < MIN_GAMES:
        return "new" if _bad(key, now) else "fine"
    step = 0.04
    if _bad(key, before) and not _bad(key, now):
        return "gone"
    if not _bad(key, before) and not _bad(key, now):
        return "fine"
    if better(now, before) and abs(now - before) >= step:
        return "better"
    if better(before, now) and abs(now - before) >= step:
        return "worse"
    return "same"


def _trend(rows: list[dict], key: str, spot: str | None, n: int = 20) -> list[float | None]:
    """One value per game, oldest first (for the little chart), smoothed over 3 games."""
    last = rows[-n:]
    out = []
    for i in range(len(last)):
        out.append(_value(last[max(0, i - 2): i + 1], key, spot))
    return out


def top_spot(rows: list[dict]) -> tuple[str | None, str | None]:
    c = Counter((d[0], d[1]) for r in rows for d in r.get("deaths_at", []) if d[1] and d[1] != "?")
    if not c:
        return None, None
    (side, area), _ = c.most_common(1)[0]
    return area, side


def track(rows: list[dict], coach: list[dict] | None = None) -> dict:
    """rows: one player's game rows. coach: [{text, fix, date, source, url}] from reports (newest first is fine)."""
    full = _full(rows)
    now_rows, before_rows = full[-RECENT:], full[-(RECENT + BEFORE):-RECENT]
    spot, spot_side = top_spot(full[-(RECENT + BEFORE):])
    out: dict = {"games": len(full), "recent": len(now_rows), "before": len(before_rows), "habits": [], "notes": [],
                 "spot": spot, "spot_side": spot_side}
    if not full:
        return out
    for key, h in HABITS.items():
        b, n = _value(before_rows, key, spot), _value(now_rows, key, spot)
        st = _status(key, b, n, len(before_rows), len(now_rows))
        title = h["title"] if key != "spot" or not spot else f"Dying at {spot}{' on ' + spot_side if spot_side else ''}"
        out["habits"].append({"key": key, "title": title, "what": h["what"], "dir": h["dir"], "bad_at": h["bad"],
                              "before": b, "now": n, "status": st, "status_text": STATUS_TEXT[st],
                              "problem": st in ("same", "worse", "new", "better"), "drill": h["drill"],
                              "trend": _trend(full, key, spot), "coach": []})
    by_key = {x["key"]: x for x in out["habits"]}
    # what the coach said, matched to a habit, and whether it changed since
    for c in coach or []:
        key = _match(c.get("text", ""), spot) or _match(c.get("fix", ""), spot)
        if key:
            when = c.get("date") or ""
            after = [r for r in full if (r.get("started_at") or "") > when]
            before = [r for r in full if (r.get("started_at") or "") <= when][-BEFORE:]
            item = dict(c, before=_value(before, key, spot), after=_value(after, key, spot), n_after=len(after))
            if item["after"] is not None and item["before"] is not None and len(after) >= 3:
                d = item["after"] - item["before"]
                good = d < -0.03 if HABITS[key]["dir"] == "high" else d > 0.03
                bad = d > 0.03 if HABITS[key]["dir"] == "high" else d < -0.03
                item["verdict"] = "better since" if good else ("worse since" if bad else "no change since")
            else:
                item["verdict"] = "too few games since"
            by_key[key]["coach"].append(item)
        else:
            out["notes"].append(c)
    # notes that come up again and again
    seen: Counter = Counter(_norm(n.get("text", "")) for n in out["notes"])
    uniq, done = [], set()
    for n in out["notes"]:
        k = _norm(n.get("text", ""))
        if k in done:
            continue
        done.add(k)
        uniq.append(dict(n, times=seen[k]))
    out["notes"] = sorted(uniq, key=lambda n: -n["times"])[:12]
    order = {"worse": 0, "same": 1, "new": 2, "better": 3, "gone": 4, "fine": 5, "few": 6}
    out["habits"].sort(key=lambda x: (order[x["status"]], -len(x["coach"])))
    out["problems"] = [x for x in out["habits"] if x["status"] in ("worse", "same", "new")]
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower())[:60]


def _match(text: str, spot: str | None) -> str | None:
    t = text.lower()
    if spot and spot.lower() in t:
        return "spot"
    for key, h in HABITS.items():
        if h["words"] and re.search(h["words"], t):
            return key
    return None


def coach_lines(report: dict, player: str, date: str, source: str, url: str) -> list[dict]:
    """Issues from one report JSON (match review + the team review entry for this player)."""
    out = []
    mr = report.get("match_review") or {}
    for i in mr.get("player_issues") or []:
        if isinstance(i, dict) and i.get("issue"):
            out.append({"text": i["issue"], "fix": i.get("fix", ""), "date": date, "source": source, "url": url})
    tr = report.get("team_review") or {}
    for p in tr.get("players") or []:
        if (p.get("name") or "").split("#")[0].lower() != player.lower():
            continue
        for f in ((p.get("feedback") or {}).get("fix") or []):
            if isinstance(f, dict) and f.get("issue"):
                out.append({"text": f["issue"], "fix": f.get("try", ""), "date": date, "source": source, "url": url})
    return out


def review_lines(review: dict, player: str, url: str) -> list[dict]:
    """Issues for one player from a Premier match review (teams/<tid>/reviews/*.json)."""
    out = []
    for p in review.get("players") or []:
        if (p.get("name") or "").lower() != player.lower():
            continue
        for f in ((p.get("feedback") or {}).get("fix") or []):
            if isinstance(f, dict) and f.get("issue"):
                out.append({"text": f["issue"], "fix": f.get("try", ""), "date": review.get("started_at") or "",
                            "source": f"Premier review {review.get('map', '')} vs {review.get('opponent', '')}".strip(), "url": url})
    return out


def fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.")
    except ValueError:
        return ""
