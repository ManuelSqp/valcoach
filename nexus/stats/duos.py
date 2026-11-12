"""Who plays well together (4.17): every pair of team members in the matches they played on the same team.

Like the "teammates" lists of stats tools for other games, but per pair inside your team:
- games together and how many of them were won;
- how often they **traded each other** (one died, the other killed that enemy within TRADE_S seconds), as a
  share of the pair's deaths in those games;
- how often **both died alone** in the same round (no teammate near either death), the pair that splits up.
"""
from __future__ import annotations

from itertools import combinations

from .evidence import confidence

TRADE_S = 5.0
ALONE_M = 20.0          # matches stats/games.py's "alone": no living teammate within 20 m at the death
MIN_GAMES = 4


def _alone(match, k, team: str) -> bool:
    """No living teammate of the victim within ALONE_M at the moment of the kill (kill positions)."""
    import math
    if not k.player_locations:
        return False
    for loc in k.player_locations:
        if loc.puuid == k.victim or match.team_of(loc.puuid) != team:
            continue
        if math.hypot(loc.x - k.victim_x, loc.y - k.victim_y) / 100 <= ALONE_M:
            return False
    return True


def pairs(matches: list, names: dict[str, str]) -> list[dict]:
    """matches: [(Match, side)] of the team; names: puuid -> member name. One entry per pair with games together."""
    acc: dict[tuple, dict] = {}
    for m, side in matches:
        mine = [p for p in names if p in m.players and m.team_of(p) == side]
        if len(mine) < 2:
            continue
        won = m.team_rounds_won.get(side, 0) > m.team_rounds_won.get(m.other_team(side), 0)
        for a, b in combinations(sorted(mine), 2):
            e = acc.setdefault((a, b), {"games": 0, "won": 0, "deaths": 0, "trades": 0, "rounds": 0, "both_alone": 0})
            e["games"] += 1
            e["won"] += int(won)
        for r in m.rounds:
            kills = sorted(r.kills, key=lambda k: k.t_round_ms)
            alone_died = set()
            for i, k in enumerate(kills):
                if k.victim not in names or m.team_of(k.victim) != side:
                    continue
                if _alone(m, k, side):
                    alone_died.add(k.victim)
                for later in kills[i + 1:]:
                    if (later.t_round_ms - k.t_round_ms) / 1000 > TRADE_S:
                        break
                    if later.victim == k.killer and later.killer in names and later.killer != k.victim:
                        key = tuple(sorted((k.victim, later.killer)))
                        if key in acc:
                            acc[key]["trades"] += 1
                        break
                for other in mine:
                    if other != k.victim:
                        key = tuple(sorted((k.victim, other)))
                        if key in acc:
                            acc[key]["deaths"] += 1
            for a, b in combinations(sorted(alone_died), 2):
                if (a, b) in acc:
                    acc[(a, b)]["both_alone"] += 1
            for a, b in combinations(sorted(mine), 2):
                acc[(a, b)]["rounds"] += 1
    out = []
    for (a, b), e in acc.items():
        out.append({"a": names[a], "b": names[b], **e, "wr": e["won"] / e["games"],
                    "trade_share": e["trades"] / e["deaths"] if e["deaths"] else None,
                    "alone_share": e["both_alone"] / e["rounds"] if e["rounds"] else None,
                    "confidence": confidence(e["games"], 12)})
    return sorted(out, key=lambda x: (-x["games"], x["a"], x["b"]))


def summary(ps: list[dict], team_wr: float | None) -> dict:
    """The pairs worth a look: best and worst win rate, best and worst at trading each other (MIN_GAMES+)."""
    ok = [p for p in ps if p["games"] >= MIN_GAMES]
    out: dict = {}
    if ok:
        out["best"] = max(ok, key=lambda p: (p["wr"], p["games"]))
        out["worst"] = min(ok, key=lambda p: (p["wr"], -p["games"]))
        tr = [p for p in ok if p["trade_share"] is not None and p["deaths"] >= 10]
        if tr:
            out["traders"] = max(tr, key=lambda p: p["trade_share"])
            out["apart"] = max(ok, key=lambda p: p["alone_share"] or 0)
    out["team_wr"] = team_wr
    return out


def facts(ps: list[dict]) -> list[dict]:
    """For the coach (team plans): pairs with enough games."""
    return [{"pair": f"{p['a']} + {p['b']}", "games": p["games"], "win_rate": f"{p['wr']:.0%}",
             "traded_each_other": None if p["trade_share"] is None else f"{p['trade_share']:.0%} of {p['deaths']} deaths",
             "rounds_both_died_alone": None if p["alone_share"] is None else f"{p['alone_share']:.0%}",
             "confidence": p["confidence"]} for p in ps if p["games"] >= MIN_GAMES][:15]
