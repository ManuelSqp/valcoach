"""Does training help? The aim trainer's skill ratings next to the closest number from your matches, week by week.

Each trainer skill gets the match number it should move the most: one taps and micro-adjusting -> headshots, flicks,
peeks and reaction -> first duels won, target switching -> kills per round, tracking -> K/D. Week by week (Monday to
Sunday, the last WEEKS weeks) we have the skill's rating that week, how much of it you trained, and the match number.

Two checks, each only once there is enough data:
- trained weeks against weeks without that skill: the match number in weeks with at least TRAINED_RUNS runs of the
  skill against weeks with none (needs MIN_TRAINED and MIN_UNTRAINED weeks with games);
- whether rating and match number move together (Pearson correlation over MIN_TOGETHER weeks with both).

It is honest about what it can say: a few weeks of games are noisy, and moving together isn't proof that one causes
the other (a good week can lift both). Until a check has its weeks it says how many are still missing."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import progress as pg
from . import trainer as tr

WEEKS = 12
TRAINED_RUNS = 3             # a week counts as "trained" for a skill from this many runs of it
MIN_TRAINED = 3              # weeks trained and with games, for the comparison
MIN_UNTRAINED = 2            # weeks without that skill and with games
MIN_TOGETHER = 5             # weeks with a rating and the match number, for "move together"

# skill -> (match metric, why this one)
PAIRS = {
    "onetap": ("hs", "one clean shot to the head"),
    "micro": ("hs", "small corrections onto the head"),
    "flicks": ("first_duels", "the first fight of a round is usually a flick"),
    "peeks": ("first_duels", "holding and taking angles"),
    "reaction": ("first_duels", "who shoots first"),
    "switching": ("kpr", "more than one kill in a fight"),
    "tracking": ("kd", "moving targets, spraying while they strafe"),
}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _game_day(r: dict) -> date | None:
    try:
        d = datetime.fromisoformat(str(r.get("started_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone().date()


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def weeks(runs: list[dict], rows: list[dict], n: int = WEEKS, today: date | None = None) -> list[dict]:
    """The last n weeks, oldest first: {week, label, monday, games: [rows], runs: {skill: [values]}}."""
    today = today or date.today()
    first = _monday(today) - timedelta(weeks=n - 1)
    out = [{"week": _week_key(first + timedelta(weeks=i)), "label": (first + timedelta(weeks=i)).strftime("%d.%m"),
            "monday": first + timedelta(weeks=i), "games": [], "runs": defaultdict(list)} for i in range(n)]
    at = {w["week"]: w for w in out}
    for r in rows:
        d = _game_day(r)
        if d and d >= first and (w := at.get(_week_key(d))):
            w["games"].append(r)
    for r in runs:
        try:
            d = date.fromisoformat(r.get("d", ""))
        except ValueError:
            continue
        if d < first or not (w := at.get(_week_key(d))):
            continue
        v = tr._run_value(r)
        if v is None:
            continue
        for sk in tr.skill_of(r["s"]):
            w["runs"][sk].append(v)
    return out


def _fmt(key: str, v: float | None) -> str:
    return pg.fmt(key, v)


def _diff_text(key: str, d: float) -> str:
    f = pg.METRICS[key][2]
    if f == "pct":
        return f"{d * 100:+.0f} points"
    if f == "dec":
        return f"{d:+.2f}"
    return f"{d:+.0f}"


def _close(key: str, d: float, base: float | None) -> bool:
    """Too small a difference to mean anything for this metric."""
    f = pg.METRICS[key][2]
    if f == "pct":
        return abs(d) < 0.02
    return abs(d) < 0.05 * max(abs(base or 0), 1)


def check(runs: list[dict], rows: list[dict], today: date | None = None) -> dict:
    """-> {"skills": [...], "weeks": n, "game_weeks": n, "train_weeks": n, "ready": bool}.
    Per skill: name, metric label, why, per-week series, the comparison and the correlation (each with "missing"
    weeks until it can say something), and a verdict: "helps", "no_link", "worse" or None (not enough yet)."""
    ws = weeks(runs, rows, today=today)
    out = []
    for sk, (key, why) in PAIRS.items():
        label, _, _, higher, _, _ = pg.METRICS[key]
        series = []
        for w in ws:
            vals = w["runs"].get(sk, [])
            m = pg.value(w["games"], key) if w["games"] else None
            series.append({"week": w["week"], "label": w["label"], "runs": len(vals),
                           "rating": round(min(100, 100 * sum(vals) / len(vals))) if vals else None,
                           "value": m, "games": len(w["games"])})
        trained = [s for s in series if s["runs"] >= TRAINED_RUNS and s["value"] is not None]
        untrained = [s for s in series if s["runs"] == 0 and s["value"] is not None]
        # the comparison: pool the games of those weeks (not the mean of weekly values: busy weeks count more)
        by = {w["week"]: w for w in ws}
        cmp = {"trained_weeks": len(trained), "untrained_weeks": len(untrained),
               "missing": max(0, MIN_TRAINED - len(trained)) + max(0, MIN_UNTRAINED - len(untrained))}
        if not cmp["missing"]:
            a = pg.value([g for s in trained for g in by[s["week"]]["games"]], key)
            b = pg.value([g for s in untrained for g in by[s["week"]]["games"]], key)
            if a is not None and b is not None:
                cmp.update(trained=a, untrained=b, diff=a - b, trained_txt=_fmt(key, a), untrained_txt=_fmt(key, b),
                           diff_txt=_diff_text(key, a - b))
        both = [s for s in series if s["rating"] is not None and s["value"] is not None]
        tog = {"weeks": len(both), "missing": max(0, MIN_TOGETHER - len(both))}
        if not tog["missing"]:
            r = _corr([s["rating"] for s in both], [s["value"] for s in both])
            if r is not None:
                tog["r"] = round(r if higher else -r, 2)        # + always means "better rating, better number"
        if "r" in tog:
            r = tog["r"]
            tog["words"] = ("clearly together" if r >= 0.4 else "a little together" if r >= 0.2 else
                            "the opposite way" if r <= -0.2 else "not together")
        verdict = None
        if "diff" in cmp:
            better = cmp["diff"] if higher else -cmp["diff"]
            if _close(key, cmp["diff"], cmp["untrained"]):
                verdict = "no_link"
            else:
                verdict = "helps" if better > 0 else "worse"
            if "r" in tog and verdict == "helps" and tog["r"] < -0.3:
                verdict = "no_link"                              # the two checks disagree: don't claim anything
        elif "r" in tog:
            verdict = "helps" if tog["r"] >= 0.4 else ("worse" if tog["r"] <= -0.4 else "no_link")
        out.append({"id": sk, "name": tr.SKILLS[sk]["name"], "metric": key, "metric_label": label, "why": why,
                    "series": series, "compare": cmp, "together": tog, "verdict": verdict, "chart": chart(series, key),
                    "trained_runs": sum(s["runs"] for s in series)})
    out.sort(key=lambda s: (s["verdict"] is None, -s["trained_runs"]))
    return {"skills": out, "weeks": len(ws), "game_weeks": sum(1 for w in ws if w["games"]),
            "train_weeks": sum(1 for w in ws if any(w["runs"].values())),
            "ready": any(s["verdict"] for s in out)}


def chart(series: list[dict], key: str, w: int = 240, h: int = 64) -> dict:
    """A small chart: training per week as bars at the bottom, the skill rating and the match number as two lines
    (each scaled to its own range; a week without a value is skipped). -> {"bars", "rating", "value", "w", "h"}."""
    n = len(series)
    step = w / max(1, n)
    top = max([s["runs"] for s in series] + [1])
    bars = [(round(i * step + step * 0.2, 1), round(14 * s["runs"] / top, 1), round(step * 0.6, 1))
            for i, s in enumerate(series) if s["runs"]]

    def line(vals):
        xs = [v for v in vals if v is not None]
        if not xs:
            return []
        lo, hi = min(xs), max(xs)
        span = (hi - lo) or 1
        pts = []                                   # weeks without a value are skipped: the line joins its neighbours
        for i, v in enumerate(vals):
            if v is None:
                continue
            y = (h - 20) - (v - lo) * (h - 26) / span if hi != lo else (h - 20) / 2
            pts.append(f"{i * step + step / 2:.1f},{y:.1f}")
        return [" ".join(pts)]

    higher = pg.METRICS[key][3]
    vals = [s["value"] if s["value"] is None or higher else -s["value"] for s in series]
    return {"bars": bars, "rating": line([s["rating"] for s in series]), "value": line(vals), "w": w, "h": h,
            "first": series[0]["label"] if series else "", "last": series[-1]["label"] if series else ""}
