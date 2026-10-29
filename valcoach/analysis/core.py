"""Shared round mechanics: alive tracking, trades, economy classification."""
from __future__ import annotations

from dataclasses import dataclass

from ..maps import MapInfo, dist
from ..models import Kill, Match, Round

TRADE_WINDOW_MS = 5000      # death is "traded" if its killer dies within this window
ISOLATION_UNITS = 1800      # ~18 m to nearest alive teammate = isolated
UNITS_PER_METER = 100


def is_pistol(match: Match, rnd: Round) -> bool:
    from ..parse import half_length_for_queue
    half = half_length_for_queue(match.queue)
    return rnd.index in (0, half)


def buy_type(avg_loadout: float, pistol: bool = False) -> str:
    if pistol:
        return "pistol"
    if avg_loadout < 1200:
        return "eco"
    if avg_loadout < 2600:
        return "force/half buy"
    if avg_loadout < 3800:
        return "light buy"
    return "full buy"


def team_loadout(rnd: Round, team: str) -> tuple[int, float]:
    vals = [s.loadout_value for s in rnd.stats.values() if s.team == team]
    if not vals:
        return 0, 0.0
    return sum(vals), sum(vals) / len(vals)


@dataclass
class DeathInfo:
    kill: Kill
    traded: bool
    traded_by: str | None
    trade_time_ms: int | None
    nearest_teammate_units: float | None
    isolated: bool
    first_death: bool
    alive_before: tuple[int, int]   # (victim team alive, killer team alive) just before the kill


def alive_progression(match: Match, rnd: Round, team: str) -> list[tuple[int, int, int]]:
    """List of (t_round_ms, team_alive, opp_alive) after each kill, starting 5v5."""
    opp = match.other_team(team)
    n_team = len(match.players_on(team)) or 5
    n_opp = len(match.players_on(opp)) or 5
    out = [(0, n_team, n_opp)]
    for k in rnd.kills:
        if k.victim_team == team:
            n_team -= 1
        elif k.victim_team == opp:
            n_opp -= 1
        out.append((k.t_round_ms, max(n_team, 0), max(n_opp, 0)))
    return out


def alive_at(match: Match, rnd: Round, team: str, t_ms: int) -> tuple[int, int]:
    prog = alive_progression(match, rnd, team)
    cur = prog[0]
    for p in prog:
        if p[0] <= t_ms:
            cur = p
        else:
            break
    return cur[1], cur[2]


def death_infos(match: Match, rnd: Round, map_info: MapInfo | None = None) -> list[DeathInfo]:
    out: list[DeathInfo] = []
    dead: set[str] = set()
    team_alive = {t: len(match.players_on(t)) or 5 for t in match.teams}
    for i, k in enumerate(rnd.kills):
        # trade: killer dies to victim's team within window
        traded_by = None
        trade_t = None
        if k.killer:
            for k2 in rnd.kills[i + 1:]:
                if k2.t_round_ms - k.t_round_ms > TRADE_WINDOW_MS:
                    break
                if k2.victim == k.killer and k2.killer_team == k.victim_team:
                    traded_by, trade_t = k2.killer, k2.t_round_ms - k.t_round_ms
                    break
        # isolation: nearest alive teammate in player_locations
        nearest = None
        for pl in k.player_locations:
            if pl.team == k.victim_team and pl.puuid != k.victim and pl.puuid not in dead:
                d = dist(pl.x, pl.y, k.victim_x, k.victim_y)
                nearest = d if nearest is None else min(nearest, d)
        alive_before = (team_alive.get(k.victim_team, 5), team_alive.get(k.killer_team, 5))
        out.append(DeathInfo(
            kill=k,
            traded=traded_by is not None,
            traded_by=traded_by,
            trade_time_ms=trade_t,
            nearest_teammate_units=nearest,
            isolated=(nearest is None and alive_before[0] > 1) or (nearest is not None and nearest > ISOLATION_UNITS),
            first_death=(i == 0),
            alive_before=alive_before,
        ))
        dead.add(k.victim)
        if k.victim_team in team_alive:
            team_alive[k.victim_team] -= 1
    return out


def zone_distribution(match: Match, kill: Kill, team: str, map_info: MapInfo | None) -> dict[str, int]:
    """Where `team` players were at the moment of `kill` (coarse zones)."""
    if map_info is None:
        return {}
    counts: dict[str, int] = {}
    seen = set()
    for pl in kill.player_locations:
        if pl.team == team:
            z = map_info.zone(pl.x, pl.y)
            counts[z] = counts.get(z, 0) + 1
            seen.add(pl.puuid)
    if kill.victim_team == team and kill.victim not in seen:
        z = map_info.zone(kill.victim_x, kill.victim_y)
        counts[z] = counts.get(z, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def area(map_info: MapInfo | None, x: float, y: float) -> str:
    return map_info.area(x, y) if map_info else f"({int(x)},{int(y)})"


def fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "?"
    s = ms / 1000
    return f"{int(s // 60)}:{int(s % 60):02d}"
