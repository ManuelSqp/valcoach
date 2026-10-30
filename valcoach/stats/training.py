"""Individual training: aim fundamentals from your fights, a warm-up routine built from them,
teammates to learn from, and a learning path for the agents worth learning.

Numbers come from game rows of full matches (stats/games.py, rows v3+: shots, duel ranges)."""
from __future__ import annotations

from collections import Counter
from urllib.parse import quote_plus

from . import roles as agent_roles

CLOSE_M, LONG_M = 10, 25            # duel ranges: close < 10 m <= mid < 25 m <= long
YT = "https://www.youtube.com/results?search_query="


def _full(rows):
    return [r for r in rows if r.get("source") == "full"]


def aim_profile(rows: list[dict]) -> dict:
    """Headshots, fights by range (how many, how many won), first duels, trades, deaths alone."""
    full = _full(rows)
    h = b = l = 0
    rng = {"close": [0, 0], "mid": [0, 0], "long": [0, 0]}         # [duels, won]
    for r in full:
        s = r.get("shots") or [0, 0, 0]
        h, b, l = h + s[0], b + s[1], l + s[2]
        for d in r.get("duels") or []:
            m, won = d[0], d[1]
            k = "close" if m < CLOSE_M else ("mid" if m < LONG_M else "long")
            rng[k][0] += 1
            rng[k][1] += won
    fk, fd = sum(r.get("fk", 0) for r in full), sum(r.get("fd", 0) for r in full)
    deaths = sum(r.get("deaths", 0) for r in full) or 0
    alone = sum((r.get("iso") or {}).get(s, [0, 0, 0, 0])[3] for r in full for s in ("attack", "defense"))
    rounds = sum(r.get("rounds", 0) for r in full) or 0
    duels = sum(v[0] for v in rng.values())
    return {
        "games": len(full), "shots": h + b + l,
        "hs": h / (h + b + l) if h + b + l >= 100 else None,
        "legs": l / (h + b + l) if h + b + l >= 100 else None,
        "ranges": {k: {"duels": v[0], "won": v[1] / v[0] if v[0] >= 8 else None,
                       "share": v[0] / duels if duels else None} for k, v in rng.items()},
        "first_duels": {"taken": (fk + fd) / rounds if rounds else None, "won": fk / (fk + fd) if fk + fd >= 8 else None},
        "trades": sum(r.get("trade_kills", 0) for r in full),
        "traded_deaths": sum(r.get("traded_deaths", 0) for r in full) / deaths if deaths >= 10 else None,
        "alone_deaths": alone / deaths if deaths >= 10 else None,
        "duels": duels,
    }


# drill text: what, how long, why (Valorant's own Range and modes: no extra software needed)
DRILLS = {
    "crosshair": ("Crosshair placement walk", "5 min",
                  "Custom game on your next map: walk every entry and hold your crosshair at head height on the door line and corner edges, never on the floor."),
    "hs_range": ("Range: head-level bots", "5 min",
                 "The Range, shooting test, medium bots, strafing off: only first bullets, reset your aim to head height between bots."),
    "strafe": ("Counter-strafe taps", "5 min",
               "The Range, strafing bots: A–D strafe, stop, tap 1–2 bullets, move again. Only shoot when you've stopped."),
    "close_dm": ("Deathmatch: Sheriff or Ghost only", "1 game",
                 "Forces clean first shots at close and mid range; no spraying."),
    "long_taps": ("Long-range taps", "5 min",
                  "The Range, long bots: Vandal 1–2 bullet taps with full reset between; then the same with Guardian."),
    "jiggle": ("Jiggle and wide peeks", "5 min",
               "Custom game with a friend or the bots: jiggle a long angle for info, then swing wide on a close one. Learn which peek fits which angle."),
    "flick": ("Range: flicks", "3 min", "The Range, small bots: flick to head and back to centre. Accuracy first, then speed."),
    "util_entry": ("Peek with utility", "in games", "Before a first duel, use your flash/dart/smoke or wait for a teammate's: never dry-peek a held angle twice."),
    "trade_spacing": ("Trade spacing", "in games", "Stay 1 entry behind your entry fragger: close enough to trade within 2 seconds, not in the same crosshair."),
    "dm_warm": ("Deathmatch warm-up", "1 game", "Head level, first bullet, stop before you shoot. Don't chase the score."),
}


def diagnose(a: dict) -> list[dict]:
    """What to work on, from the numbers (most important first)."""
    out = []
    if a["hs"] is not None and a["hs"] < 0.17:
        out.append({"key": "hs", "title": "Crosshair at head height",
                    "why": f"{a['hs']:.0%} of your hits are headshots (good players at most ranks sit around 20–25%)",
                    "drills": ["crosshair", "hs_range"]})
    rc, rl = a["ranges"]["close"], a["ranges"]["long"]
    if rc["won"] is not None and rc["won"] < 0.45:
        out.append({"key": "close", "title": "Close fights",
                    "why": f"you win {rc['won']:.0%} of fights under {CLOSE_M} m ({rc['duels']} fights)",
                    "drills": ["strafe", "close_dm"]})
    if rl["won"] is not None and rl["won"] < 0.45:
        out.append({"key": "long", "title": "Long angles",
                    "why": f"you win {rl['won']:.0%} of fights over {LONG_M} m ({rl['duels']} fights): take fewer, or with utility",
                    "drills": ["long_taps", "jiggle"]})
    fdw = a["first_duels"]["won"]
    if fdw is not None and fdw < 0.45 and (a["first_duels"]["taken"] or 0) >= 0.18:
        out.append({"key": "entry", "title": "First duels",
                    "why": f"you're in a lot of first duels and win {fdw:.0%}: peek them with utility or a teammate",
                    "drills": ["util_entry", "jiggle"]})
    if a["alone_deaths"] is not None and a["alone_deaths"] >= 0.35:
        out.append({"key": "alone", "title": "Don't fight alone",
                    "why": f"{a['alone_deaths']:.0%} of your deaths are far from your team",
                    "drills": ["trade_spacing"]})
    return out


def routine(diag: list[dict]) -> list[dict]:
    """A warm-up of about 20 minutes: the drills for your weak spots first, a deathmatch last."""
    keys: list[str] = []
    for d in diag:
        for k in d["drills"]:
            if k not in keys:
                keys.append(k)
    base = [k for k in ("crosshair", "strafe", "flick") if k not in keys]
    keys = keys + base[: max(0, 3 - len([k for k in keys if DRILLS[k][1] != "in games"]))]
    keys.append("dm_warm")
    return [{"key": k, "name": DRILLS[k][0], "time": DRILLS[k][1], "how": DRILLS[k][2]} for k in keys]


def team_refs(me: str, profiles: dict[str, dict]) -> list[dict]:
    """Teammates who are best at what you're weakest at. profiles: name -> aim_profile."""
    out = []
    mine = profiles.get(me)
    if not mine:
        return out
    tests = [("hs", "headshots", lambda a: a["hs"]),
             ("close", f"close fights (<{CLOSE_M} m)", lambda a: a["ranges"]["close"]["won"]),
             ("long", f"long fights (>{LONG_M} m)", lambda a: a["ranges"]["long"]["won"]),
             ("entry", "first duels won", lambda a: a["first_duels"]["won"])]
    for key, label, fn in tests:
        v = fn(mine)
        if v is None:
            continue
        best = max(((n, fn(a)) for n, a in profiles.items() if n != me and fn(a) is not None), key=lambda x: x[1], default=None)
        if best and best[1] - v >= 0.05:
            out.append({"what": label, "who": best[0], "theirs": best[1], "yours": v})
    return out


# ------------------------------------------------------------------ agents to learn
def agents_to_learn(role: str | None, pool: dict[str, int], team_cover: dict[str, int], meta_share: dict[str, float],
                    n: int = 5, role_agents: dict | None = None, fallback: dict | None = None) -> list[dict]:
    """Up to n agents worth learning: agent roles that suit the team role, the team's thin roles first,
    then what teams at your level pick on your maps."""
    if not role or not role_agents:
        return []
    targets = sorted(role_agents.get(role, []), key=lambda r: (team_cover.get(r, 0), role_agents[role].index(r)))
    known = {a for a, c in pool.items() if c >= 5}
    out: list[dict] = []
    for t_i, target in enumerate(targets):
        cands = [a for a in agent_roles.all_agents() if agent_roles.role_of(a) == target and a not in known]
        fb = (fallback or {}).get(target, [])
        cands.sort(key=lambda a: (-meta_share.get(a, 0.0), fb.index(a) if a in fb else 99, a))
        for a in cands[:3 if t_i == 0 else 2]:
            why = [f"{'an' if target[0] in 'AEIOU' else 'a'} {target} fits the {role} role"]
            if team_cover.get(target, 0) <= 1:
                why.append(f"only {team_cover.get(target, 0)} of your starters play a {target} regularly")
            if meta_share.get(a):
                why.append(f"picked by {meta_share[a]:.0%} of teams on your maps at your level")
            if pool.get(a):
                why.append(f"you've played it {pool[a]}× already")
            out.append({"agent": a, "agent_role": target, "why": why})
    return out[:n]


def learn_path(agent: str, rows: list[dict], maps: list[str], pros: list[dict]) -> dict:
    """Steps from first game to Premier, with where you are now (from your games on the agent)."""
    on = [r for r in rows if r.get("agent") == agent]
    full = _full(on)
    games = len(on)
    ranked = sum(1 for r in on if (r.get("queue") or "") in ("competitive", "premier"))
    wr = sum(r["won"] for r in on) / games if games else None
    kast = (sum(r.get("kast", 0) for r in full) / sum(r.get("rounds", 0) for r in full)) if full and sum(r.get("rounds", 0) for r in full) else None
    on_maps = Counter(r["map"] for r in on if r["map"] in maps)
    pro = next((p for p in pros if agent in (p.get("agents") or [])[:2]), None) or next((p for p in pros if agent in (p.get("agents") or [])), None)
    steps = [
        {"title": f"Learn the kit", "done": games >= 1,
         "what": f"Watch a short {agent} guide, then try every ability in the Range.",
         "link": YT + quote_plus(f"{agent} guide valorant")},
        {"title": "5 games in unrated or Swiftplay", "done": games >= 5, "what": f"{games} of 5 played.",
         "link": None},
        {"title": "Lineups for your maps", "done": sum(on_maps.values()) >= 3 and len(on_maps) >= 2,
         "what": "Learn 2–3 setups per map for " + (", ".join(maps[:3]) if maps else "your maps") +
                 (f" (played on {', '.join(f'{m} {c}×' for m, c in on_maps.most_common(3))})" if on_maps else "") + ".",
         "link": YT + quote_plus(f"{agent} {maps[0] if maps else ''} lineups valorant")},
        {"title": "Ranked", "done": ranked >= 10,
         "what": (f"{ranked} of 10 ranked games." + (f" KAST {kast:.0%}" if kast is not None else "") +
                  (" Ready: your KAST on it is fine." if kast is not None and kast >= 0.68 and ranked < 10 else "")),
         "link": None},
        {"title": "Premier-ready", "done": games >= 15 and (wr or 0) >= 0.5,
         "what": f"{games} of 15 games" + (f", {wr:.0%} won" if wr is not None else "") + " (needs 50%+).",
         "link": None},
    ]
    if pro:
        steps.insert(1, {"title": f"Watch {pro['name']} play {agent}", "done": False,
                         "what": pro.get("known_for", ""), "link": YT + quote_plus(f"{pro['name']} {agent} POV valorant"), "optional": True})
    reached = sum(1 for s in steps if s["done"] and not s.get("optional"))
    return {"agent": agent, "role": agent_roles.role_of(agent), "games": games, "ranked": ranked, "win_rate": wr,
            "kast": kast, "steps": steps, "reached": reached, "total": sum(1 for s in steps if not s.get("optional"))}
