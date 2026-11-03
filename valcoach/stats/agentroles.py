"""Agents & roles for one player: every agent's numbers, the agent class you prefer, and the
team role your habits fit, with agents to try if the two don't match.

- Preferred: what you pick (share of games per agent class: Duelist, Initiator, Controller,
  Sentinel) and, if a team owner set it, your team role.
- Fit: the 0-100 team-role scores from stats/teamroles.py (first into fights, trades, fights
  far from the team, holding a site, assists, Operator, several classes, traits for calling).
- Performs best: the agent class where your win rate and combat score are highest compared
  with your own average (only classes with enough games).
- The verdict compares the three and names agents to try in the class that suits the fit.
"""
from __future__ import annotations

from . import roles as agent_roles
from .aggregate import MIN_GAMES_AGENT, by_agent, by_map, smooth, summary
from .teamroles import DESCRIPTION, FALLBACK_AGENTS, MIN_GAMES, PRIMARY, ROLE_AGENTS, metrics, scores

CLASSES = ["Duelist", "Initiator", "Controller", "Sentinel"]
CLASS_TEXT = {
    "Duelist": "takes space and the first fights",
    "Initiator": "gathers info and sets up fights for the team",
    "Controller": "smokes and controls the pace",
    "Sentinel": "holds sites and watches flanks",
}
MIN_CLASS_GAMES = 5


def _per_agent(rows: list[dict]) -> list[dict]:
    out = []
    for a in by_agent(rows):
        on = [r for r in rows if r.get("agent") == a["agent"]]
        maps = [m for m in by_map(on) if m["games"] >= 2]
        best = max(maps, key=lambda m: (m["wr_s"], m["games"])) if maps else None
        worst = min(maps, key=lambda m: (m["wr_s"], -m["games"])) if len(maps) >= 2 else None
        a.update(
            enough=a["games"] >= MIN_GAMES_AGENT,
            best_map=best["map"] if best else None, best_map_wr=best["wr"] if best else None,
            worst_map=worst["map"] if worst and worst is not best else None,
            worst_map_wr=worst["wr"] if worst and worst is not best else None,
            maps=[{"map": m["map"], "games": m["games"], "wr": m["wr"], "acs": m["acs"], "kd": m["kd"]} for m in by_map(on)],
            last=max((r.get("started_at") or "" for r in on), default=""),
        )
        out.append(a)
    return out


def _classes(rows: list[dict], total: dict) -> list[dict]:
    n = len(rows) or 1
    out = []
    for c in CLASSES:
        rs = [r for r in rows if agent_roles.role_of(r["agent"]) == c]
        s = summary(rs) if rs else {"games": 0}
        s.update(role=c, share=len(rs) / n, text=CLASS_TEXT[c])
        if rs and total.get("acs"):
            # how you do on this class compared with your own average: win rate (smoothed) and ACS
            s["edge"] = (smooth(s["wins"], s["games"]) - total["wr_s"]) + 0.5 * (s["acs"] / total["acs"] - 1)
        out.append(s)
    return out


def overview(rows: list[dict], team_roles: list[dict] | None = None, meta_share: dict[str, float] | None = None) -> dict:
    """team_roles: [{team, roles}] set by team owners for this player. meta_share: agent -> pick share at your level."""
    total = summary(rows)
    out: dict = {"total": total, "agents": [], "classes": [], "team_roles": team_roles or []}
    if not rows:
        return out
    out["agents"] = _per_agent(rows)
    played = {a["agent"] for a in out["agents"]}
    out["not_played"] = {c: [a for a in agent_roles.all_agents() if agent_roles.role_of(a) == c and a not in played] for c in CLASSES}
    classes = _classes(rows, total)
    out["classes"] = classes
    preferred = max(classes, key=lambda c: c["games"])
    out["preferred"] = preferred["role"]
    out["preferred_share"] = preferred["share"]
    out["main_agent"] = out["agents"][0]["agent"]
    ranked = [c for c in classes if c["games"] >= MIN_CLASS_GAMES and "edge" in c]
    out["best_class"] = max(ranked, key=lambda c: c["edge"])["role"] if len(ranked) >= 2 else None

    # what your habits fit
    m = metrics(rows)
    fit = scores(m)
    out["full_games"] = m.get("full", 0)
    out["min_full"] = MIN_GAMES
    if fit:
        order = sorted(fit.items(), key=lambda kv: -kv[1]["score"])
        out["fit"] = [{"role": k, "description": DESCRIPTION.get(k, ""), **v} for k, v in order]
        primary = [x for x in out["fit"] if x["role"] in PRIMARY]
        sug = primary[0]
        out["suggested"] = sug["role"]
        out["suggested_score"] = sug["score"]
        out["runner_up"] = primary[1]["role"] if len(primary) > 1 and primary[1]["score"] >= sug["score"] - 8 else None
        out["hats"] = [x for x in out["fit"] if x["role"] in ("IGL", "Operator") and x["score"] >= 60]
        out["suggested_classes"] = ROLE_AGENTS.get(sug["role"], [])
        out["strength"] = "clear" if sug["score"] >= 55 else ("leaning" if sug["score"] >= 35 else "open")
        out["match"] = out["preferred"] in out["suggested_classes"]
        pool = {a["agent"]: a["games"] for a in out["agents"]}
        target = out["preferred"] if out["match"] else (out["suggested_classes"] or [out["preferred"]])[0]
        out["try_class"] = target
        out["to_try"] = _to_try(target, sug["role"], pool, meta_share or {}, widen=out["match"])
        out["verdict"] = _verdict(out)
    return out


def _to_try(cls: str, role: str, pool: dict[str, int], meta_share: dict[str, float], widen: bool, n: int = 3) -> list[dict]:
    """Agents of one class you haven't really played yet (fewer than 5 games), most picked at your level first."""
    fb = FALLBACK_AGENTS.get(cls, [])
    cands = [a for a in agent_roles.all_agents() if agent_roles.role_of(a) == cls and pool.get(a, 0) < 5]
    cands.sort(key=lambda a: (-meta_share.get(a, 0.0), fb.index(a) if a in fb else 99, a))
    out = []
    for a in cands[:n]:
        why = [f"a second {cls} for your pool" if widen else f"{'an' if cls[0] in 'AEIOU' else 'a'} {cls} suits the {role} role"]
        if meta_share.get(a):
            why.append(f"picked by {meta_share[a]:.0%} of teams at your level")
        if pool.get(a):
            why.append(f"you've played it {pool[a]}×")
        out.append({"agent": a, "agent_role": cls, "why": why})
    return out


def _verdict(o: dict) -> str:
    pref, sug, cls = o["preferred"], o["suggested"], o["suggested_classes"]
    first = cls[0] if cls else "?"
    best = o.get("best_class")
    if o["strength"] == "open":
        s = (f"No role stands out yet: your habits lean towards {sug}, but not by much. "
             f"You mostly play {pref}.")
    elif o["match"]:
        s = f"What you pick fits how you play: you mostly play {pref}, and your habits fit the {sug} role, which {pref}s suit."
    else:
        s = (f"You mostly play {pref}, but your habits fit the {sug} role better, and that role suits "
             f"{' or '.join(cls[:2]) or first} agents more.")
    set_by_team = sorted({r for t in o.get("team_roles", []) for r in t["roles"] if r in PRIMARY})
    if set_by_team and o["strength"] != "open" and sug not in set_by_team:
        s += f" Your team has you as {' / '.join(set_by_team)}; your habits point to {sug}: worth a talk."
    elif set_by_team and sug in set_by_team:
        s += f" That's also the role your team gave you."
    if best and best != pref:
        s += f" You also win more and score higher on {best} than on {pref}."
    elif best and best == pref:
        s += f" Your numbers are best on {pref} too."
    return s
