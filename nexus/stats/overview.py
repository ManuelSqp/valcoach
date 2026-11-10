"""Player overview of a team (4.11): who plays what, how and in which role, at a glance.

Everything is calculated from the stored games, nothing is written by the model:
  agents      every agent a player has played (games, win rate, ACS), the 5 most played in the short view
  agent roles share of games as Duelist / Initiator / Controller / Sentinel
  team role   the role you assigned on the Roles page, else the suggested lineup's (marked as a suggestion),
              plus the hats (IGL, Operator) and the fit score from the data
  playstyle   labels like Aggressive or Clutch player with the numbers behind them (archetypes.py), the four
              style numbers (opening duels, kills, assists, survival) and the closest pro
  situations  where a player thrives and struggles: opening duels, clutches, retakes, post-plants, duel
              range, attack / defense, alone / with the team, trades (archetypes.py)
  maps        the maps a player does best on (3+ games), all maps in the full view
and for the team: which agent roles each player covers, roles nobody covers, mains that collide.
"""
from __future__ import annotations

from . import roles
from .aggregate import by_agent, by_map, summary
from .archetypes import analyse
from .style import match_pros, profile
from .teamroles import HATS, PRIMARY

TOP = 5
REGULAR_SHARE = 0.25      # a player "covers" an agent role when it's at least a quarter of his games ...
REGULAR_GAMES = 5         # ... and at least this many games
BEST_MAP_GAMES = 3


def _trait(t: str) -> str:
    return t[4:] if t.startswith("you ") else t


def player(p: dict, lineup: dict, pros: list[dict]) -> dict:
    """p: one player from teamroles.team_roles (label, pid, kind, rows, assigned, scores, best)."""
    rows = p["rows"]
    out: dict = {"label": p["label"], "pid": p["pid"], "kind": p["kind"], "games": len(rows)}
    if not rows:
        return out
    s = summary(rows)
    out.update(wr=s["wr"], acs=s["acs"], kd=s["kd"])
    agents = by_agent(rows)
    for a in agents:
        a["share"] = a["games"] / len(rows)
    out["agents"] = agents
    out["top"] = agents[:TOP]
    prof = profile(rows)
    out["role_split"] = [{"role": r, "share": prof["roles"].get(r, 0.0)} for r in roles.ROLES]
    out["main_role"] = prof.get("main_role")
    arch = analyse(rows, prof)
    out["style"] = {"dims": prof.get("dims") or {}, "traits": [_trait(t) for t in prof.get("traits") or []],
                    "opening_wr": prof.get("opening_wr"), "reference": prof.get("reference", ""),
                    "no_openings": prof.get("no_openings", False), "labels": arch["labels"],
                    "full_games": arch["full_games"]}
    out["thrives"], out["struggles"] = arch["thrives"], arch["struggles"]
    pro = match_pros(prof, pros, top=1) if pros else []
    out["pro"] = pro[0]["name"] if pro else None
    # team role: yours first, else the suggestion
    assigned = p.get("assigned") or []
    role = next((r for r in assigned if r in PRIMARY or r == "Flex"), None)
    suggested = False
    if role is None:
        role = (lineup.get("primary") or {}).get(p["label"]) if p["kind"] == "starter" else \
            (p["best"][0] if p.get("best") else None)
        suggested = role is not None
    hats = [{"hat": h, "suggested": False} for h in assigned if h in HATS]
    for h, who in (lineup.get("hats") or {}).items():
        if who == p["label"] and h not in [x["hat"] for x in hats]:
            hats.append({"hat": h, "suggested": True,
                         "votes": lineup.get("igl_votes") if h == "IGL" else None})   # 4.15: from check-ins
    sc = p.get("scores") or {}
    out["team_role"] = {"role": role, "suggested": suggested, "hats": hats,
                        "score": sc.get(role, {}).get("score") if role else None}
    maps = by_map(rows)
    out["maps"] = maps
    good = [m for m in maps if m["games"] >= BEST_MAP_GAMES]
    out["best_maps"] = sorted(good, key=lambda m: -m["wr_s"])[:2]
    return out


def team(members_roles: dict, pros: list[dict]) -> dict:
    """members_roles: the result of teamroles.team_roles(...). -> {players, starters, subs, cover, notes, agents}"""
    lineup = members_roles.get("lineup") or {}
    players = [player(p, lineup, pros) for p in members_roles.get("players") or []]
    starters = [p for p in players if p["kind"] == "starter"]
    lineup_players = starters or players
    cover = {}
    for r in roles.ROLES:
        cover[r] = [p["label"] for p in lineup_players if p["games"] >= REGULAR_GAMES and
                    any(x["role"] == r and x["share"] >= REGULAR_SHARE for x in p.get("role_split", []))]
    notes = []
    uncovered = [r for r in roles.ROLES if not cover[r]]
    if uncovered and any(p["games"] for p in lineup_players):
        notes.append(f"Nobody {'in the lineup ' if starters else ''}plays {' or '.join(r.lower() for r in uncovered)} regularly")
    mains: dict[str, list[str]] = {}
    for p in lineup_players:
        if p.get("top"):
            mains.setdefault(p["top"][0]["agent"], []).append(p["label"])
    for agent, who in mains.items():
        if len(who) > 1:
            notes.append(f"{' and '.join(who)} both play {agent} most")
    # every agent anyone played, most played first: the rows of the full view
    total: dict[str, int] = {}
    for p in players:
        for a in p.get("agents", []):
            total[a["agent"]] = total.get(a["agent"], 0) + a["games"]
    all_agents = [{"agent": a, "role": roles.role_of(a), "games": n}
                  for a, n in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))]
    cells = {p["label"]: {a["agent"]: a for a in p.get("agents", [])} for p in players}
    map_total: dict[str, int] = {}
    for p in players:
        for m in p.get("maps", []):
            map_total[m["map"]] = map_total.get(m["map"], 0) + m["games"]
    all_maps = [m for m, _ in sorted(map_total.items(), key=lambda kv: (-kv[1], kv[0]))]
    map_cells = {p["label"]: {m["map"]: m for m in p.get("maps", [])} for p in players}
    return {"players": players, "starters": starters, "subs": [p for p in players if p["kind"] != "starter"],
            "cover": cover, "notes": notes, "all_agents": all_agents, "cells": cells,
            "all_maps": all_maps, "map_cells": map_cells}
