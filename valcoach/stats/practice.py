"""Practice planner: a week of team practice built from what the team needs right now.

Every practice day gets a session of about `minutes`:
  warm-up          10 min, always
  habit drill      the habit most of the team still has (from the habit tracker), with who it's for
  map work         this week's Premier map: attack strats on one day, defense on the next, the lineups
  review           the newest Premier review (or the newest report) together
  play             the rest: Premier / Unrated with this week's focus
The last practice before a match day becomes match prep (brief + match screen).
No model is needed: the plan is made instantly and anyone in the team can tick items off or add their own.
"""
from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta

WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_DAYS = [1, 3]                 # Tue, Thu
DEFAULT = {"days": DEFAULT_DAYS, "time": "19:00", "minutes": 90, "post": False}

TEAM_DRILLS = {
    "alone": ("Trade drill", "2v2 and 3v3 in a custom game: entry + trader pairs, the trader 1 to 2 seconds behind. "
                             "Swap roles every 3 rounds."),
    "untraded": ("Trade drill", "2v2 and 3v3 in a custom game: entry + trader pairs, the trader 1 to 2 seconds behind. "
                                "Swap roles every 3 rounds."),
    "opening": ("First-duel drill", "1v1 peeks in a custom game, first with utility (flash, recon, smoke) before the duel, "
                                    "then dry peeks only when a teammate can trade."),
    "kast": ("Post-plant & retake customs", "Plant and retake on both sites; every player says his job before the round."),
    "aim": ("Aim block", "15 min Range bots on hard (heads only), then a deathmatch aiming only at the head."),
    "spot": ("Death-spot customs", "Everyone plays his worst death spot with a different angle or with utility first; "
                                   "the others attack it."),
}


def week_days(week_start: date, days: list[int]) -> list[date]:
    return [week_start + timedelta(days=d) for d in sorted(set(days)) if 0 <= d <= 6]


def monday(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def _id() -> str:
    return secrets.token_hex(4)


def team_habits(members: dict[str, dict]) -> list[dict]:
    """members: name -> habit tracker result. -> [{key, title, who: [names]}] most common first."""
    who: dict[str, list[str]] = defaultdict(list)
    titles = {}
    for name, h in members.items():
        for x in h.get("problems", []):
            who[x["key"]].append(name)
            titles.setdefault(x["key"], x["title"] if x["key"] != "spot" else "Dying at the same spot")
    out = [{"key": k, "title": titles[k], "who": sorted(v)} for k, v in who.items()]
    return sorted(out, key=lambda x: -len(x["who"]))


def build(week: str, start: date, cfg: dict, ctx: dict) -> dict:
    """ctx: map, strats {attack: [names], defense: [names]}, lineups {agent: n}, comp_agents, habits [team_habits],
    personal {name: [habit titles]}, review {title, url}, match_days [weekday ints], focus (str),
    evening [{title, detail, minutes, who, url, evening}] (from the last review evening)."""
    days = week_days(start, cfg.get("days") or DEFAULT_DAYS)
    total = int(cfg.get("minutes") or 90)
    habits = ctx.get("habits") or []
    m = ctx.get("map")
    match_days = set(ctx.get("match_days") or [])
    out = {"week": week, "start": start.isoformat(), "days": [], "created": datetime.now().timestamp(), "map": m}
    for i, d in enumerate(days):
        items: list[dict] = []
        left = total

        def add(kind, title, detail, minutes, who="team", link=""):
            nonlocal left
            items.append({"id": _id(), "kind": kind, "title": title, "detail": detail, "minutes": minutes,
                          "who": who, "link": link, "done": False})
            left -= minutes

        add("warmup", "Warm-up", "Range: 5 min bots on hard, then a deathmatch. Everyone on time, voice on.", 10)
        before_match = any(((d.weekday() + k) % 7) in match_days for k in (0, 1)) and m
        if before_match:
            add("prep", f"Match prep: {m}", "Go through the match-day brief together, then open the match screen: "
                "comp, who plays what, the plans per side, the strats.", 20, link="brief")
        # the team's most common habit, a different one each day where possible
        if habits:
            h = habits[i % len(habits)] if len(habits) > 1 else habits[0]
            title, detail = TEAM_DRILLS.get(h["key"], ("Habit drill", ""))
            who = h["who"] if len(h["who"]) < 5 else "team"
            add("habit", f"{title}: {h['title'].lower()}", detail + (f" Mostly for {', '.join(h['who'])}." if who != "team" else ""),
                20, who=who, link="habits")
        if m:
            side = "attack" if i % 2 == 0 else "defense"
            names = (ctx.get("strats") or {}).get(side) or []
            if names:
                detail = f"Walk through {', '.join(names[:3])} in a custom game, then run each one 3 times at full speed."
            else:
                detail = f"No {side} strat for {m} yet: draw one together in the Strat book, then walk it."
            add("map", f"{m}: {side} strats", detail, 25, link="strats")
            lu = ctx.get("lineups") or {}
            if lu and not before_match:
                agents = ", ".join(f"{a} ({n})" for a, n in sorted(lu.items(), key=lambda kv: -kv[1])[:3])
                add("lineups", f"{m} lineups", f"Each player practises his saved lineups: {agents}.", 10, link="lineups")
        if i == 0:                          # what the last review evening found
            for x in (ctx.get("evening") or [])[:3]:
                items.append({"id": _id(), "kind": "evening", "title": x["title"][:100], "detail": x.get("detail", "")[:400],
                              "minutes": int(x.get("minutes") or 15), "who": x.get("who") or "team", "link": x.get("url", ""),
                              "evening": x.get("evening", ""), "done": False})
                left -= int(x.get("minutes") or 15)
        if ctx.get("review") and i == 0 and not ctx.get("evening"):
            add("review", "Review together", f"Open {ctx['review']['title']} and go through the rounds that decided it.",
                15, link=ctx["review"]["url"])
        if left >= 15:
            focus = ctx.get("focus")
            add("play", "Play together", "Premier or Unrated as a five" + (", everyone on his weekly focus." if focus else "."), left)
        out["days"].append({"date": d.isoformat(), "label": f"{WEEKDAY[d.weekday()]} {d.day:02d}.{d.month:02d}.",
                            "time": cfg.get("time") or "19:00", "items": items})
    out["personal"] = ctx.get("personal") or {}
    return out


def progress(plan: dict) -> tuple[int, int]:
    items = [it for d in plan.get("days", []) for it in d["items"]]
    return sum(1 for it in items if it.get("done")), len(items)


def discord_text(plan: dict, team: str) -> str:
    lines = [f"**Practice this week ({team})**" + (f", map: {plan['map']}" if plan.get("map") else "")]
    for d in plan.get("days", []):
        lines.append(f"\n**{d['label']} {d['time']}**")
        for it in d["items"]:
            who = "" if it["who"] == "team" else f" ({', '.join(it['who'])})"
            lines.append(f"• {it['title']}, {it['minutes']} min{who}")
    return "\n".join(lines)

