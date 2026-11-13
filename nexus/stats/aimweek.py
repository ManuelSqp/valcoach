"""The aim trainer's week (4.37): a player's weekly report (Aim page) and the team's aim board with a weekly challenge
(Team › Practice › Aim board, and a Discord post with the weekly focus).

Everything comes from the trainer runs (data/profiles/<pid>/stats/trainer.json). A week runs Monday to Sunday.
Skill ratings are trainer.skill_ratings(): from the last 12 runs of a skill, so "a week ago" is the rating from the
runs before this week."""
from __future__ import annotations

from datetime import date, timedelta

from . import trainer as tr

# scenarios the weekly challenge rotates through when the team owner hasn't picked one: one of each kind
CHALLENGES = ["grid", "onetap_heads", "track", "six_shot", "reflex", "spider", "tswitch", "flick_mid", "angle_wide",
              "bounce_shot", "micro", "strafe_shot", "popups", "track_react"]


def week_start(today: date | None = None) -> date:
    t = today or date.today()
    return t - timedelta(days=t.weekday())


def week_label(today: date | None = None) -> str:
    y, w, _ = (today or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def this_week(runs: list[dict], today: date | None = None) -> list[dict]:
    start = week_start(today).isoformat()
    return [r for r in runs if (r.get("d") or "") >= start]


def report(runs: list[dict], extra: dict | None = None, today: date | None = None) -> dict:
    """A player's week: runs and minutes, every skill now and a week ago, new bests, what to train next."""
    start = week_start(today).isoformat()
    week = [r for r in runs if (r.get("d") or "") >= start]
    before = [r for r in runs if (r.get("d") or "") < start]
    now_r, then_r = tr.skill_ratings(runs, extra), tr.skill_ratings(before, extra)
    skills = []
    for k, v in now_r.items():
        was = then_r[k]["rating"]
        played = sum(1 for r in week if r["s"] in tr.SKILLS[k]["ladder"])
        skills.append({"id": k, "name": v["name"], "now": v["rating"], "was": was, "played": played,
                       "change": v["rating"] - was if v["rating"] is not None and was is not None else None})
    bests = []
    names = {k: x["name"] for k, x in tr.SCENARIOS.items()}
    names.update({k: x["name"] for k, x in (extra or {}).items()})
    for sid in sorted({r["s"] for r in week}):
        old = [r["score"] for r in before if r["s"] == sid and not r.get("k")]
        new = [r["score"] for r in week if r["s"] == sid and not r.get("k")]
        if new and (not old or max(new) > max(old)) and sid in names:
            bests.append({"id": sid, "name": names[sid], "best": max(new), "before": max(old) if old else None})
    rated = [s for s in skills if s["now"] is not None]
    nxt = None
    dropped = [s for s in rated if s["change"] is not None and s["change"] <= -5]
    if dropped:
        s = min(dropped, key=lambda x: x["change"])
        nxt = {"id": s["id"], "name": s["name"], "why": "dropped"}
    elif len(rated) >= 2:
        s = min(rated, key=lambda x: x["now"])
        nxt = {"id": s["id"], "name": s["name"], "why": "weakest"}
    untried = [s for s in skills if s["now"] is None]
    if not nxt and untried:
        nxt = {"id": untried[0]["id"], "name": untried[0]["name"], "why": "untried"}
    return {"week": week_label(today), "runs": len(week), "minutes": round(sum(r.get("sec", 0) for r in week) / 60),
            "days": len({r["d"] for r in week}), "skills": skills, "bests": sorted(bests, key=lambda b: b["name"])[:8],
            "next": nxt}


def challenge_of(saved: dict, week: str) -> str:
    """This week's challenge: the one the owner picked, else one from CHALLENGES by the week number."""
    if saved.get(week):
        return saved[week]
    try:
        n = int(week.split("W")[1]) + int(week[:4])
    except (IndexError, ValueError):
        n = 0
    return CHALLENGES[n % len(CHALLENGES)]


def board(members: list[dict], challenge: str, today: date | None = None) -> dict:
    """members: [{name, pid, runs}] -> per member: ratings, this week's minutes and runs, challenge best;
    and the challenge's leaderboard (best score this week, normal rounds only)."""
    rows, lb = [], []
    start = week_start(today).isoformat()
    for m in members:
        runs = m["runs"]
        rep = report(runs, m.get("extra"), today)
        ch = [r["score"] for r in runs if r["s"] == challenge and (r.get("d") or "") >= start and not r.get("k")]
        rows.append({"name": m["name"], "pid": m["pid"], "skills": {s["id"]: s for s in rep["skills"]},
                     "minutes": rep["minutes"], "runs": rep["runs"], "days": rep["days"]})
        if ch:
            lb.append({"name": m["name"], "pid": m["pid"], "best": max(ch), "tries": len(ch)})
    lb.sort(key=lambda x: -x["best"])
    return {"rows": rows, "leaderboard": lb, "challenge": challenge, "week": week_label(today)}


def discord_embeds(team_name: str, b: dict, challenge_name: str, url: str = "") -> list[dict]:
    """The aim board as one Discord embed: the challenge's top five, then who trained how much and what moved."""
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    lines = [f"{medals[i]} **{x['name']}** {int(x['best'])} ({x['tries']}×)" for i, x in enumerate(b["leaderboard"][:5])]
    desc = f"**Challenge: {challenge_name}**\n" + ("\n".join(lines) if lines else "Nobody has played it yet this week.")
    rows = []
    for r in sorted(b["rows"], key=lambda x: -x["minutes"]):
        moved = [(s["name"], s["change"]) for s in r["skills"].values() if s["change"]]
        moved.sort(key=lambda x: -abs(x[1]))
        tail = ", ".join(f"{n} {c:+d}" for n, c in moved[:2])
        rows.append(f"**{r['name']}** {r['minutes']} min" + (f" · {tail}" if tail else ""))
    if rows:
        desc += "\n\n**Trained this week**\n" + "\n".join(rows)
    e = {"title": f"Aim board · {b['week']}", "description": desc[:4000], "color": 0x2DD4BF,
         "footer": {"text": f"{team_name} · Nexus"}}
    if url:
        e["url"] = url
    return [e]
