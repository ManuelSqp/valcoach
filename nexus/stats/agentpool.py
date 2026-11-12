"""Agent pool advisor (4.22): which agent each player should add next.

What the team needs: per map of the team, the agents of the ideal composition (comp sheet: typed or from the
web) and the agents your lobbies pick most there (local meta, a third of the teams or more). An agent is
missing when nobody has it in their pool (comp sheet order: played or added, not marked "won't play").

Who should learn it, per player and missing agent:
  role fit    how much of his play is in that agent's role (share of his games)
  how well    his ACS on agents of that role against what players of his rank do on the same agents (the
              other players in his own matches, games.lobby_agents)
  room        a player whose pool has few agents gets a small plus, one already covering a role nobody else
              covers gets a small minus (he's needed there)
Each missing agent goes to the best fitting player, at most two suggestions per player.

  advise(players, maps, ideal, meta) -> {"missing": [...], "players": [...], "roles": {...}}
"""
from __future__ import annotations

from collections import defaultdict

from . import roles

META_SHARE = 0.33          # an agent picked by a third of the teams in your lobbies on a map counts as wanted
MIN_GAMES_ROLE = 5         # games in a role before his numbers there count
PER_PLAYER = 2


def _role_numbers(rows: list[dict]) -> dict[str, dict]:
    """role -> {games, acs (his, per game average), lobby (players of his rank on the same agents)}."""
    games: dict[str, list] = defaultdict(list)
    lobby: dict[str, list] = defaultdict(list)          # (agent) -> ACS of lobby players on it
    for r in rows:
        if r.get("agent"):
            games[roles.role_of(r["agent"])].append(r)
        for la in r.get("lobby_agents") or []:
            if la and la[0] and la[1] is not None:
                lobby[la[0]].append(la[1])
    out = {}
    for role, rs in games.items():
        acs = sum(r.get("acs", 0) for r in rs) / len(rs)
        mine = {r["agent"] for r in rs}
        ref = [v for a in mine for v in lobby.get(a, [])]
        out[role] = {"games": len(rs), "acs": acs, "lobby": sum(ref) / len(ref) if len(ref) >= 10 else None}
    return out


def advise(players: list[dict], maps: list[str], ideal: dict[str, list[str]], meta: dict[str, dict]) -> dict | None:
    """players: [{label, pid, rows, pool: [agents], no: [agents]}]; ideal: map -> 5 agents; meta: local_meta()."""
    if not players or not maps:
        return None
    pools = {p["label"]: set(p["pool"]) for p in players}
    wanted: dict[str, dict] = {}
    for mp in maps:
        for a in ideal.get(mp) or []:
            w = wanted.setdefault(a, {"maps": [], "why": set()})
            w["maps"].append(mp)
            w["why"].add("ideal")
        for x in (meta.get(mp) or {}).get("agents", []):
            if x["share"] >= META_SHARE and (meta[mp].get("games") or 0) >= 5:
                w = wanted.setdefault(x["agent"], {"maps": [], "why": set()})
                if mp not in w["maps"]:
                    w["maps"].append(mp)
                w["why"].add("meta")
                w.setdefault("share", {})[mp] = x["share"]
    covered_by = {a: sorted(n for n, pl in pools.items() if a in pl) for a in wanted}
    missing = [{"agent": a, "role": roles.role_of(a), "maps": w["maps"], "ideal": "ideal" in w["why"],
                "share": max((w.get("share") or {}).values(), default=None)}
               for a, w in wanted.items() if not covered_by[a]]
    missing.sort(key=lambda m: (-len(m["maps"]), not m["ideal"], m["agent"]))
    # how deep each role is: who has an agent of it in his pool
    depth: dict[str, list[str]] = {r: sorted(n for n, pl in pools.items() if any(roles.role_of(a) == r for a in pl))
                                   for r in roles.ROLES}
    nums = {p["label"]: _role_numbers(p["rows"]) for p in players}
    total = {p["label"]: max(1, sum(1 for r in p["rows"] if r.get("agent"))) for p in players}
    cands = []
    for m in missing:
        role = m["role"]
        for p in players:
            if m["agent"] in (p.get("no") or []):
                continue
            n = nums[p["label"]].get(role)
            share = (n["games"] / total[p["label"]]) if n else 0.0
            perf = None
            if n and n["games"] >= MIN_GAMES_ROLE and n["lobby"]:
                perf = n["acs"] / n["lobby"]
            score = 1.5 * share + (min(1.3, max(0.7, perf)) - 1.0 if perf else 0.0) * 2
            score += 0.15 if len(pools[p["label"]]) <= 4 else 0.0
            sole = [r for r, who in depth.items() if who == [p["label"]] and r != role]
            score -= 0.2 * len(sole)
            why = []
            if share >= 0.2:
                why.append(f"{share:.0%} of their games are on {role}s")
            elif share == 0:
                why.append(f"a new role for them ({role})")
            if perf:
                why.append(f"ACS {n['acs']:.0f} on {role}s, players of their rank {n['lobby']:.0f} on the same agents")
            if sole:
                why.append(f"they are the only {' and '.join(sole)} in the pools")
            cands.append((score, p["label"], m, why))
    cands.sort(key=lambda c: -c[0])
    given: dict[str, list] = defaultdict(list)
    done: set[str] = set()
    for score, label, m, why in cands:
        if m["agent"] in done or len(given[label]) >= PER_PLAYER:
            continue
        reason = [f"needed on {', '.join(m['maps'])}" + (" (ideal comp)" if m["ideal"] else "")
                  + (f", picked by {m['share']:.0%} of teams in your lobbies" if m.get("share") else "")]
        given[label].append({"agent": m["agent"], "role": m["role"], "maps": m["maps"], "why": reason + why,
                             "score": round(score, 2)})
        done.add(m["agent"])
    out_players = []
    for p in players:
        out_players.append({"label": p["label"], "pid": p["pid"], "pool": p["pool"][:6], "suggest": given.get(p["label"], [])})
    return {"missing": missing, "players": out_players, "roles": depth,
            "thin": [r for r, who in depth.items() if len(who) <= 1]}


def facts(a: dict | None) -> dict | None:
    if not a:
        return None
    return {"agents_nobody_plays_on_your_maps": [f"{m['agent']} ({m['role']}: {', '.join(m['maps'])})" for m in a["missing"]][:8],
            "suggested": {p["label"]: [s["agent"] for s in p["suggest"]] for p in a["players"] if p["suggest"]},
            "roles_with_one_player_or_none": a["thin"]}
