"""When you play well (4.17): sessions, time of day, weekday and losing streaks.

Ideas from stats tools of other games (e.g. Mobalytics' consistency / tilt and daily activity): the same player
wins at different rates depending on when and how long they play. From the games Nexus already has:

- **game in the session**: a session is a run of games with less than SESSION_GAP_MIN minutes between the end
  of one and the start of the next; win rate and ACS of the 1st, 2nd, 3rd ... game;
- **after losses**: win rate of the next game after 0 / 1 / 2+ losses in a row in the same session (tilt);
- **time of day** and **weekday** (the server's local time);
- **a stop hint** when the numbers show a clear drop with enough games behind it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .evidence import confidence

SESSION_GAP_MIN = 75
MATCH_MIN = 40                   # a game counts as ~40 minutes when the row has no length
MIN_BUCKET = 8                   # games a bucket needs before it's compared
DROP = 0.10                      # a win-rate drop this big (10 points) is worth a hint
DAY_PARTS = (("morning", "Morning", 5, 12), ("afternoon", "Afternoon", 12, 18),
             ("evening", "Evening", 18, 22), ("night", "Late", 22, 29))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _local(r: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(r.get("started_at") or "").replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _bucket(rs: list[dict]) -> dict:
    n = len(rs)
    return {"games": n, "wr": sum(r.get("won", 0) for r in rs) / n if n else None,
            "acs": sum(r.get("acs", 0) for r in rs) / n if n else None, "confidence": confidence(n, 20)}


def sessions(rows: list[dict]) -> list[list[dict]]:
    """Games grouped into sessions, oldest first."""
    timed = sorted(((d, r) for r in rows if (d := _local(r)) is not None), key=lambda x: x[0])
    out: list[list[dict]] = []
    end = None
    for d, r in timed:
        if end is None or d - end > timedelta(minutes=SESSION_GAP_MIN):
            out.append([])
        out[-1].append(r)
        mins = (r.get("length_s") or 0) / 60 or MATCH_MIN
        end = d + timedelta(minutes=mins)
    return out


def analyse(rows: list[dict]) -> dict | None:
    """{by_game: [...], after_losses: [...], by_time: [...], by_day: [...], sessions, avg_len, hints: [...]}."""
    rows = [r for r in rows if r.get("won") is not None]
    if len(rows) < 10:
        return None
    ss = sessions(rows)
    by_game: dict[int, list[dict]] = {}
    after: dict[int, list[dict]] = {0: [], 1: [], 2: []}
    for s in ss:
        streak = 0
        for i, r in enumerate(s):
            by_game.setdefault(min(i + 1, 5), []).append(r)
            if i:
                after[min(streak, 2)].append(r)
            streak = streak + 1 if not r.get("won") else 0
    by_time: dict[str, list[dict]] = {k: [] for k, *_ in DAY_PARTS}
    by_day: dict[int, list[dict]] = {i: [] for i in range(7)}
    for r in rows:
        d = _local(r)
        if d is None:
            continue
        h = d.hour if d.hour >= 5 else d.hour + 24
        for k, _, a, b in DAY_PARTS:
            if a <= h < b:
                by_time[k].append(r)
        by_day[(d - timedelta(hours=5)).weekday()].append(r)        # a game at 01:00 belongs to the evening before
    out = {
        "by_game": [{"key": n, "label": f"{n}{'+' if n == 5 else ''}. game", **_bucket(by_game[n])} for n in sorted(by_game)],
        "after_losses": [{"key": k, "label": ("after a win / first game" if k == 0 else
                                              "after 1 loss" if k == 1 else "after 2+ losses in a row"), **_bucket(after[k])}
                         for k in (0, 1, 2) if after[k]],
        "by_time": [{"key": k, "label": lab, **_bucket(by_time[k])} for k, lab, *_ in DAY_PARTS if by_time[k]],
        "by_day": [{"key": i, "label": WEEKDAYS[i], **_bucket(by_day[i])} for i in range(7) if by_day[i]],
        "sessions": len(ss), "avg_len": round(sum(len(s) for s in ss) / len(ss), 1) if ss else 0,
        "overall": _bucket(rows),
    }
    out["hints"] = hints(out)
    return out


def hints(a: dict) -> list[str]:
    """Plain lines where the numbers show a clear difference (enough games on both sides)."""
    out = []
    g = {b["key"]: b for b in a["by_game"]}
    early = [b for k, b in g.items() if k <= 3]
    late = [b for k, b in g.items() if k >= 4]
    ne, nl = sum(b["games"] for b in early), sum(b["games"] for b in late)
    if ne >= MIN_BUCKET and nl >= MIN_BUCKET:
        we = sum(b["wr"] * b["games"] for b in early) / ne
        wl = sum(b["wr"] * b["games"] for b in late) / nl
        if we - wl >= DROP:
            out.append(f"From the 4th game of a session the win rate drops from {we:.0%} to {wl:.0%} "
                       f"({nl} games): stopping after 3 games is worth trying")
    al = {b["key"]: b for b in a["after_losses"]}
    if 0 in al and 2 in al and al[2]["games"] >= MIN_BUCKET and al[0]["games"] >= MIN_BUCKET:
        if al[0]["wr"] - al[2]["wr"] >= DROP:
            out.append(f"After 2 losses in a row only {al[2]['wr']:.0%} of the next games are won "
                       f"({al[2]['games']} games, otherwise {al[0]['wr']:.0%}): a break after two losses is worth trying")
    t = [b for b in a["by_time"] if b["games"] >= MIN_BUCKET]
    if len(t) >= 2:
        best, worst = max(t, key=lambda b: b["wr"]), min(t, key=lambda b: b["wr"])
        if best["wr"] - worst["wr"] >= DROP + 0.05:
            out.append(f"Best time: {best['label'].lower()} ({best['wr']:.0%} of {best['games']} games won), "
                       f"weakest: {worst['label'].lower()} ({worst['wr']:.0%} of {worst['games']})")
    return out


def facts(rows: list[dict]) -> dict | None:
    """Compact block for the coach."""
    a = analyse(rows)
    if not a:
        return None
    pct = lambda v: None if v is None else f"{v:.0%}"     # noqa: E731
    return {"sessions": a["sessions"], "games_per_session": a["avg_len"],
            "win_rate_by_game_in_session": {b["label"]: f"{pct(b['wr'])} of {b['games']}" for b in a["by_game"]},
            "win_rate_after_losses": {b["label"]: f"{pct(b['wr'])} of {b['games']}" for b in a["after_losses"]},
            "win_rate_by_time_of_day": {b["label"]: f"{pct(b['wr'])} of {b['games']}" for b in a["by_time"]},
            "hints": a["hints"]}
