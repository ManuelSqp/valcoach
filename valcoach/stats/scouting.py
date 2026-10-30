"""Scouting other Premier teams, and the map veto.

Premier weekly matches are played on the week's map against a team from your own division and
zone, found only when you queue. So we scout every team in the division in advance (their
recent Premier matches), and when you get matched their page is ready. Playoffs have a real
pick/ban: `veto()` compares your map record with theirs.

Everything here is computed from match data; nothing calls a model.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from ..models import Match
from . import roles
from .teamdata import map_facts

PRIOR = 3          # games of 50 % added to every map record before comparing (small samples)


def side_in_match(raw: dict, team_id: str = "", name: str = "", tag: str = "", members: set[str] | None = None) -> str | None:
    """Which side ('Red'/'Blue') a Premier team played in a raw v4 match payload."""
    d = raw.get("data", raw) if isinstance(raw, dict) else {}
    for t in d.get("teams") or []:
        pr = t.get("premier_roster") or {}
        if pr and ((team_id and str(pr.get("id")) == str(team_id))
                   or (tag and name and (pr.get("tag") or "").lower() == tag.lower() and (pr.get("name") or "").lower() == name.lower())):
            return t.get("team_id")
    if members:
        sides = Counter(pl.get("team_id") for pl in d.get("players") or [] if pl.get("puuid") in members)
        if sides:
            side, n = sides.most_common(1)[0]
            if n >= 3:
                return side
    return None


def _won(m: Match, team: str) -> bool:
    other = m.other_team(team)
    return m.team_rounds_won.get(team, 0) > m.team_rounds_won.get(other, 0)


def map_record(items: list[tuple[Match, str]]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"games": 0, "wins": 0, "rounds": 0, "rounds_won": 0})
    for m, team in items:
        r = out[m.map_name]
        r["games"] += 1
        r["wins"] += _won(m, team)
        r["rounds"] += len(m.rounds)
        r["rounds_won"] += m.team_rounds_won.get(team, 0)
    return dict(out)


def summarize(items: list[tuple[Match, str]], cache_dir: Path) -> dict:
    """What a team does: record, maps (comps, sites, timings), players (agents, who entries), pistols."""
    roles.load(cache_dir)
    rec = map_record(items)
    wins = sum(r["wins"] for r in rec.values())
    out: dict = {"matches": len(items), "wins": wins, "losses": len(items) - wins, "maps": {}, "players": [],
                 "pistols": {"played": 0, "won": 0}, "comps": []}
    by_map: dict[str, list] = defaultdict(list)
    comps_all: Counter = Counter()
    pl: dict[str, dict] = {}
    for m, team in items:
        by_map[m.map_name].append((m, team))
        agents = tuple(sorted(p.agent for p in m.players_on(team)))
        comps_all[agents] += 1
        for i in (0, 12):
            if len(m.rounds) > i:
                out["pistols"]["played"] += 1
                out["pistols"]["won"] += m.rounds[i].winning_team == team
        n = len(m.rounds) or 1
        for p in m.players_on(team):
            e = pl.setdefault(p.puuid, {"name": p.name, "tag": p.tag, "games": 0, "agents": Counter(), "rounds": 0, "kills": 0,
                                        "deaths": 0, "score": 0, "first_kills": 0, "first_deaths": 0})
            e["games"] += 1
            e["agents"][p.agent] += 1
            e["rounds"] += n
            e["kills"] += p.kills
            e["deaths"] += p.deaths
            e["score"] += p.score
        for rnd in m.rounds:
            if rnd.kills:
                k0 = rnd.kills[0]
                if k0.killer in pl and k0.killer_team == team:
                    pl[k0.killer]["first_kills"] += 1
                if k0.victim in pl and k0.victim_team == team:
                    pl[k0.victim]["first_deaths"] += 1
    total_first = sum(e["first_kills"] + e["first_deaths"] for e in pl.values()) or 1
    for pu, e in sorted(pl.items(), key=lambda kv: -kv[1]["games"]):
        if e["games"] < 2 and len(pl) > 5:
            continue                       # one-off fill-ins
        fd = e["first_kills"] + e["first_deaths"]
        main = e["agents"].most_common(1)[0][0]
        out["players"].append({
            "puuid": pu, "name": e["name"], "tag": e["tag"], "games": e["games"],
            "agents": [{"agent": a, "games": c} for a, c in e["agents"].most_common(3)], "role": roles.role_of(main),
            "kpr": round(e["kills"] / max(1, e["rounds"]), 2), "acs": round(e["score"] / max(1, e["rounds"])),
            "kd": round(e["kills"] / max(1, e["deaths"]), 2),
            "first_duel_share": round(fd / total_first, 2), "first_duels_won": round(e["first_kills"] / fd, 2) if fd else None,
        })
    out["players"] = out["players"][:7]
    out["comps"] = [{"agents": list(a), "games": c} for a, c in comps_all.most_common(3)]
    for mp, ms in sorted(by_map.items(), key=lambda kv: -len(kv[1])):
        r = rec[mp]
        comps = Counter(tuple(sorted(p.agent for p in m.players_on(t))) for m, t in ms)
        f = map_facts(ms, cache_dir, mp)
        out["maps"][mp] = {"games": r["games"], "wins": r["wins"], "rounds": r["rounds"], "rounds_won": r["rounds_won"],
                           "comps": [{"agents": list(a), "games": c} for a, c in comps.most_common(2)],
                           "attack": f.get("attack", {}), "defense": f.get("defense", {}), "sides": side_rates(ms, mp)}
    return out


def _pct(s) -> float | None:
    try:
        return float(str(s).rstrip("%")) / 100
    except (TypeError, ValueError):
        return None


def how_to_play(s: dict, map_name: str | None = None) -> list[str]:
    """Short, concrete lines about a scouted team (all from their numbers): the general ones, plus
    the lines for one map (map_name) or for every map (None)."""
    if not s.get("matches"):
        return ["No Premier matches of this team found yet."]
    lines = general_lines(s)
    for mp in s.get("maps", {}):
        if map_name is None or mp.lower() == map_name.lower():
            lines += map_lines(s, mp)
    return lines or ["Nothing stands out yet: too few matches."]


def general_lines(s: dict) -> list[str]:
    lines: list[str] = []
    maps = s.get("maps", {})
    strong = [f"{m} ({v['wins']}–{v['games'] - v['wins']})" for m, v in maps.items() if v["games"] >= 2 and v["wins"] / v["games"] >= .6]
    weak = [f"{m} ({v['wins']}–{v['games'] - v['wins']})" for m, v in maps.items() if v["games"] >= 2 and v["wins"] / v["games"] <= .4]
    if strong:
        lines.append(f"Strong on {', '.join(strong)}.")
    if weak:
        lines.append(f"Weak on {', '.join(weak)}.")
    entry = max(s.get("players", []), key=lambda p: p["first_duel_share"], default=None)
    if entry and entry["first_duel_share"] >= .25:
        won = f", wins {entry['first_duels_won']:.0%} of them" if entry.get("first_duels_won") is not None else ""
        lines.append(f"{entry['name']} ({entry['agents'][0]['agent']}) takes {entry['first_duel_share']:.0%} of their first duels{won}: "
                     f"expect them first, trade them fast or use utility on the entry.")
    p = s.get("pistols", {})
    if p.get("played", 0) >= 4:
        r = p["won"] / p["played"]
        if r >= .65 or r <= .35:
            lines.append(f"Pistols: they won {p['won']} of {p['played']}" + (": prepare your pistol plan." if r >= .65 else "."))
    return lines


def map_lines(s: dict, mp: str) -> list[str]:
    lines: list[str] = []
    v = (s.get("maps") or {}).get(mp)
    if v:
        att, dfn = v.get("attack") or {}, v.get("defense") or {}
        sites = att.get("sites_hit") or {}
        total = sum(x["plants"] for x in sites.values())
        if total >= 3:
            site, x = max(sites.items(), key=lambda kv: kv[1]["plants"])
            share = x["plants"] / total
            if share >= .55:
                lines.append(f"{mp} attack: they plant {site} {share:.0%} of the time" +
                             (f" (and win {x['rounds_won']} of those rounds)" if x.get("rounds_won") else "") + ": stack or rotate early.")
        pt = att.get("plant_median_s")
        if pt:
            if pt <= 40:
                lines.append(f"{mp}: fast executes (plant around {pt}s): keep utility for the first 30 seconds.")
            elif pt >= 70:
                lines.append(f"{mp}: slow, late hits (plant around {pt}s): play for info, don't over-rotate early.")
        retakes = dfn.get("enemy_plants") or {}
        for site, x in retakes.items():
            w = _pct(x.get("retakes_won"))
            if x["plants"] >= 3 and w is not None and w <= .35:
                lines.append(f"{mp} defense: they lose most retakes on {site} ({x['retakes_won']}): plant {site} and play post-plant.")
    return lines


def _smooth(w: int, g: int) -> float:
    return (w + PRIOR * .5) / (g + PRIOR)


def veto(ours: dict[str, dict], theirs: dict[str, dict], pool: list[str],
         our_sides: dict[str, dict] | None = None, their_sides: dict[str, dict] | None = None) -> dict:
    """Rank the map pool for a pick/ban against one team.
    ours/theirs: map -> {"games", "wins"}; *_sides: map -> {"attack": 0.55, "defense": 0.48} round win rates."""
    rows = []
    for mp in pool:
        o, t = ours.get(mp, {}), theirs.get(mp, {})
        og, ow, tg, tw = o.get("games", 0), o.get("wins", 0), t.get("games", 0), t.get("wins", 0)
        edge = _smooth(ow, og) - _smooth(tw, tg)
        side = None
        os_, ts = (our_sides or {}).get(mp) or {}, (their_sides or {}).get(mp) or {}
        if os_.get("attack") is not None and os_.get("defense") is not None:
            # start where we're relatively better: our attack vs their defense, our defense vs their attack
            a = os_["attack"] - (ts.get("defense") if ts.get("defense") is not None else .5)
            d = os_["defense"] - (ts.get("attack") if ts.get("attack") is not None else .5)
            side = "attack" if a > d else "defense"
        rows.append({"map": mp, "ours": {"games": og, "wins": ow}, "theirs": {"games": tg, "wins": tw},
                     "edge": round(edge, 3), "side": side, "sure": og + tg >= 6})
    rows.sort(key=lambda r: -r["edge"])
    n_bans = 2 if len(rows) >= 4 else (1 if len(rows) >= 2 else 0)
    bans = [r["map"] for r in rows[len(rows) - n_bans:]][::-1]          # worst for us first
    for i, r in enumerate(rows):
        r["call"] = "pick" if i == 0 else ("ban" if r["map"] in bans else "")
    return {"rows": rows, "pick": rows[0]["map"] if rows else None, "bans": bans}


def side_rates(items: list[tuple[Match, str]], map_name: str) -> dict:
    """Round win rate on attack and defense on one map."""
    a = [0, 0]
    d = [0, 0]
    for m, team in items:
        if m.map_name.lower() != map_name.lower():
            continue
        for rnd in m.rounds:
            x = a if rnd.side_of(team) == "attack" else d
            x[0] += 1
            x[1] += rnd.winning_team == team
    return {"attack": a[1] / a[0] if a[0] >= 6 else None, "defense": d[1] / d[0] if d[0] >= 6 else None}


def timing(items: list[tuple[Match, str]]) -> dict:
    """Median first-fight and plant time over all their attack rounds (seconds)."""
    first, plant = [], []
    for m, team in items:
        for rnd in m.rounds:
            if rnd.side_of(team) != "attack":
                continue
            if rnd.kills:
                first.append(rnd.kills[0].t_round_ms / 1000)
            if rnd.plant:
                plant.append(rnd.plant.t_round_ms / 1000)
    return {"first_fight_s": round(median(first)) if first else None, "plant_s": round(median(plant)) if plant else None}
