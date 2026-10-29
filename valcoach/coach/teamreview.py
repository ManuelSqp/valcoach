"""Whole-team review of one match: every player of your team gets their own short review,
plus how you played together (who traded whom, who was left alone, who keeps fighting
outnumbered) and what teammates can do to help each other.

Facts are computed here from the match data; the model only writes the words.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import yaml

from ..analysis.core import death_infos
from ..maps import MapInfo
from ..models import Match
from .prompts import field_guide

CLOSE_UNITS = 1500         # enemies within ~15 m count as "in the fight"
ALONE_UNITS = 2000


def _area(mi: MapInfo | None, x: float, y: float) -> str:
    try:
        return mi.area(x, y) if mi else "?"
    except Exception:
        return "?"


def facts(match: Match, team: str, mi: MapInfo | None) -> dict:
    """Per player of `team`: numbers + notable rounds; plus pairwise trades."""
    players = {p.puuid: p for p in match.players_on(team)}
    n = len(match.rounds) or 1
    per = {pu: {"name": p.name, "agent": p.agent, "kills": p.kills, "deaths": p.deaths, "assists": p.assists,
                "acs": round(p.score / n), "first_kills": 0, "first_deaths": 0, "deaths_list": [], "trades": 0,
                "kast_rounds": 0, "multi_kills": []} for pu, p in players.items()}
    traded_by: Counter = Counter()          # (dead, avenger) -> count
    for rnd in match.rounds:
        side = rnd.side_of(team)
        died, contributed = set(), set()
        if rnd.kills:
            k0 = rnd.kills[0]
            if k0.killer in per:
                per[k0.killer]["first_kills"] += 1
            if k0.victim in per:
                per[k0.victim]["first_deaths"] += 1
        kills_by = Counter(k.killer for k in rnd.kills if k.killer in per)
        for pu, c in kills_by.items():
            if c >= 3:
                per[pu]["multi_kills"].append({"round": rnd.number, "kills": c})
        for k in rnd.kills:
            if k.killer in per:
                contributed.add(k.killer)
            for a in k.assistants:
                if a in per:
                    contributed.add(a)
        for di in death_infos(match, rnd, mi):
            k = di.kill
            if k.victim not in per:
                continue
            died.add(k.victim)
            if di.traded:
                contributed.add(k.victim)
                if di.traded_by in per:
                    traded_by[(k.victim, di.traded_by)] += 1
            enemies_close = sum(1 for pl in k.player_locations if pl.team != team and pl.puuid != k.killer
                                and ((pl.x - k.victim_x) ** 2 + (pl.y - k.victim_y) ** 2) ** 0.5 <= CLOSE_UNITS) + 1
            per[k.victim]["deaths_list"].append({
                "round": rnd.number, "side": side, "time_s": round(k.t_round_ms / 1000), "where": _area(mi, k.victim_x, k.victim_y),
                "first_death": di.first_death, "traded": di.traded,
                "alone": di.nearest_teammate_units is None or di.nearest_teammate_units > ALONE_UNITS,
                "enemies_close": enemies_close, "team_alive_before": di.alive_before[0],
            })
        for pu in per:
            if pu in contributed or pu not in died:
                per[pu]["kast_rounds"] += 1
    for (dead, avenger), c in traded_by.items():     # same trade window as "deaths traded"
        per[avenger]["trades"] += c
    for pu, d in per.items():
        dl = d["deaths_list"]
        d["kast"] = round(d["kast_rounds"] / n, 2)
        d["untraded_deaths"] = sum(1 for x in dl if not x["traded"])
        d["alone_deaths"] = sum(1 for x in dl if x["alone"] and not x["traded"])
        d["outnumbered_deaths"] = sum(1 for x in dl if x["enemies_close"] >= 2)
        spots = Counter((x["side"], x["where"]) for x in dl)
        d["repeat_death_spots"] = [{"side": s, "where": w, "deaths": c} for (s, w), c in spots.most_common(3) if c >= 2]
    names = {pu: p.name for pu, p in players.items()}
    pairs = [{"died": names[a], "traded_by": names[b], "times": c} for (a, b), c in traded_by.most_common()]
    return {"players": per, "trade_pairs": pairs, "rounds": n}


SYSTEM = """You are the coach of a Valorant team, reviewing one player of the team after a match.
Use ONLY the facts given; refer to round numbers. Be direct and specific, no generic advice.
Missing data means unknown. No aim data here: judge positioning, timing, trading and roles.
{roles}Also say what TEAMMATES can do to help this player (e.g. play closer to him on a site
where he keeps dying outnumbered), because the whole team reads this. Write in {language}."""


def schema() -> dict:
    item = {"type": "object", "properties": {"point": {"type": "string"}, "rounds": {"type": "array", "items": {"type": "integer"}}},
            "required": ["point", "rounds"]}
    return {"type": "object", "properties": {
        "summary": {"type": "string", "description": "1-2 sentences on this player's match."},
        "went_well": {"type": "array", "items": item, "maxItems": 3},
        "fix": {"type": "array", "items": {"type": "object", "properties": {
            "issue": {"type": "string"}, "rounds": {"type": "array", "items": {"type": "integer"}},
            "try": {"type": "string", "description": "what to do instead next time"}}, "required": ["issue", "rounds", "try"]},
            "maxItems": 3},
        "teammates_can_help": {"type": "string"},
    }, "required": ["summary", "went_well", "fix", "teammates_can_help"]}


def review(match: Match, team: str, mi: MapInfo | None, llm=None, language: str = "English",
           roles: dict[str, list[str]] | None = None, parallel: int = 4, progress=None) -> dict:
    """roles: lower-case 'name#tag' -> assigned team roles (from the team page)."""
    f = facts(match, team, mi)
    roles = roles or {}
    out = {"players": [], "trade_pairs": f["trade_pairs"]}
    order = sorted(f["players"].items(), key=lambda kv: -kv[1]["acs"])

    def one(item):
        pu, d = item
        p = match.players[pu]
        r = roles.get(f"{p.name}#{p.tag}".lower(), [])
        entry = {"puuid": pu, "name": d["name"], "agent": d["agent"], "agent_id": p.agent_id, "roles": r,
                 "stats": {k: d[k] for k in ("kills", "deaths", "assists", "acs", "kast", "first_kills", "first_deaths",
                                             "trades", "untraded_deaths", "alone_deaths", "outnumbered_deaths")},
                 "repeat_death_spots": d["repeat_death_spots"], "multi_kills": d["multi_kills"], "feedback": None}
        if llm is not None:
            team_view = [{"name": x["name"], "agent": x["agent"], "kd": f"{x['kills']}/{x['deaths']}"} for _, x in order]
            payload = {"player": {k: v for k, v in d.items() if k not in ("kast_rounds",)}, "team_roles": r,
                       "teammates": team_view, "who_traded_whom": f["trade_pairs"], "map": match.map_name}
            role_line = (f"This player's team role(s): {', '.join(r)}. Judge them against what that role needs.\n"
                         if r else "")
            try:
                entry["feedback"] = llm.chat_json(SYSTEM.format(roles=role_line, language=language) + field_guide(schema()),
                                                  "Facts (YAML):\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                                                  schema())
            except Exception as e:
                entry["error"] = str(e)
        return entry

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        for i, e in enumerate(ex.map(one, order), 1):
            out["players"].append(e)
            if progress:
                progress(i, len(order))
    return out
