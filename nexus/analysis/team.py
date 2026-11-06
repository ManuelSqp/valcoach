"""Team / IGL-level analysis: per-round macro facts and match aggregates."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..maps import MapInfo
from ..models import Match, Round
from .view import ViewModel, duel_view, facing_label
from .core import (
    DeathInfo, alive_at, alive_progression, area, buy_type, death_infos, fmt_ms,
    is_pistol, team_loadout, zone_distribution,
)


@dataclass
class TeamRoundFacts:
    round: int                    # 1-based number
    side: str                     # attack | defense
    won: bool
    result: str
    score_before: tuple[int, int]
    our_buy: str
    our_loadout_avg: int
    opp_buy: str
    opp_loadout_avg: int
    first_kill_ours: bool | None
    first_kill_desc: str
    first_kill_time: str
    our_setup_at_first_contact: dict[str, int]
    opp_setup_at_first_contact: dict[str, int]
    plant_site: str | None
    plant_time: str | None
    alive_at_plant: tuple[int, int] | None    # (ours, theirs)
    defused: bool
    progression: str                          # e.g. "5v5 > 5v4 > 4v4 > ..."
    max_advantage: int                        # best (ours - theirs)
    max_disadvantage: int                     # worst (ours - theirs), negative
    threw_advantage: bool
    won_from_disadvantage: bool
    our_deaths_traded: int
    our_deaths_untraded: int
    our_isolated_deaths: int
    trade_kills_ours: int
    ults_used_ours: list[str] = field(default_factory=list)
    ults_used_opp: list[str] = field(default_factory=list)
    activity_zone: str = ""                   # where most of the fighting happened
    our_deaths_caught_off_angle: int = 0      # our player wasn't looking at the killer
    notable: list[str] = field(default_factory=list)


def analyse_team_round(match: Match, rnd: Round, team: str, map_info: MapInfo | None,
                       vm: ViewModel | None = None) -> TeamRoundFacts:
    opp = match.other_team(team)
    side = rnd.side_of(team)
    pistol = is_pistol(match, rnd)
    _, our_avg = team_loadout(rnd, team)
    _, opp_avg = team_loadout(rnd, opp)

    deaths = death_infos(match, rnd, map_info)
    fk = rnd.kills[0] if rnd.kills else None
    if fk:
        fk_ours = fk.killer_team == team
        fk_desc = (f"{match.label(fk.killer)} killed {match.label(fk.victim)} "
                   f"at {area(map_info, fk.victim_x, fk.victim_y)} ({fk.weapon or 'ability'})")
        our_setup = zone_distribution(match, fk, team, map_info)
        opp_setup = zone_distribution(match, fk, opp, map_info)
    else:
        fk_ours, fk_desc, our_setup, opp_setup = None, "no kills", {}, {}

    prog = alive_progression(match, rnd, team)
    diffs = [a - b for _, a, b in prog]
    max_adv, max_dis = max(diffs), min(diffs)
    won = rnd.winning_team == team
    progression = " > ".join(f"{a}v{b}" for _, a, b in prog)
    # the API has no "time ran out" result: no plant, attackers still alive, defenders won
    attackers_left = prog[-1][1] if side == "attack" else prog[-1][2]
    timed_out = (not rnd.plant and attackers_left > 0 and bool(rnd.winning_team)
                 and rnd.winning_team != rnd.attacking_team)

    plant_site = plant_time = None
    alive_plant = None
    if rnd.plant:
        plant_site = rnd.plant.site or (map_info.zone(rnd.plant.x, rnd.plant.y) if map_info else "?")
        plant_time = fmt_ms(rnd.plant.t_round_ms)
        alive_plant = alive_at(match, rnd, team, rnd.plant.t_round_ms)

    our_deaths = [d for d in deaths if d.kill.victim_team == team]
    trade_kills = sum(1 for d in deaths if d.kill.victim_team == opp and _is_trade_kill(d, deaths))

    ults_ours = ults_opp = []
    if match.has_utility:
        ults_ours = [match.label(p) for p, s in rnd.stats.items() if s.team == team and s.ability_casts.get("ultimate", 0) > 0]
        ults_opp = [match.label(p) for p, s in rnd.stats.items() if s.team == opp and s.ability_casts.get("ultimate", 0) > 0]

    zone_counts: dict[str, int] = {}
    if map_info:
        for k in rnd.kills:
            z = map_info.zone(k.victim_x, k.victim_y)
            zone_counts[z] = zone_counts.get(z, 0) + 1
    activity = max(zone_counts, key=zone_counts.get) if zone_counts else ""

    notable: list[str] = []
    if max_adv >= 2 and not won:
        notable.append(f"lost the round after being up {max_adv} players")
    if max_dis <= -2 and won:
        notable.append(f"won the round from {abs(max_dis)} players down")
    if fk and not fk_ours and side == "attack":
        notable.append("gave up first death on attack")
    if rnd.plant and side == "attack" and not won:
        if rnd.defuse:
            notable.append("post-plant lost to a defuse")
        else:
            notable.append("planted but lost post-plant (eliminated)")
    if rnd.plant and side == "defense" and won and rnd.defuse:
        notable.append("successful retake + defuse")
    if timed_out and side == "attack":
        notable.append("failed to plant before time ran out")
    if timed_out and side == "defense":
        notable.append("held until time ran out (no plant)")
    if our_avg and opp_avg and our_avg < 1500 and opp_avg > 3500 and won:
        notable.append("won an eco/force vs full buy")
    if our_avg > 3500 and opp_avg and opp_avg < 1500 and not won:
        notable.append("lost a full buy vs eco")
    untraded = [d for d in our_deaths if not d.traded]
    off_angle = 0
    if vm is not None and vm.ok:
        for d in our_deaths:
            if d.kill.killer:
                lab = facing_label(duel_view(vm, d.kill, d.kill.victim, d.kill.killer).my_angle_to_other)
                if lab in ("side", "behind"):
                    off_angle += 1
    if off_angle >= 2:
        notable.append(f"{off_angle} of our players died without looking at their killer (crossfire/flank)")
    if len(untraded) >= 3:
        notable.append(f"{len(untraded)} untraded deaths")

    return TeamRoundFacts(
        round=rnd.number,
        side=side,
        won=won,
        result=rnd.result or ("Time expired" if timed_out else ""),
        score_before=match.score_before(rnd.index, team),
        our_buy=buy_type(our_avg, pistol),
        our_loadout_avg=int(our_avg),
        opp_buy=buy_type(opp_avg, pistol),
        opp_loadout_avg=int(opp_avg),
        first_kill_ours=fk_ours,
        first_kill_desc=fk_desc,
        first_kill_time=fmt_ms(fk.t_round_ms) if fk else "?",
        our_setup_at_first_contact=our_setup,
        opp_setup_at_first_contact=opp_setup,
        plant_site=plant_site,
        plant_time=plant_time,
        alive_at_plant=alive_plant,
        defused=rnd.defuse is not None,
        progression=progression,
        max_advantage=max_adv,
        max_disadvantage=max_dis,
        threw_advantage=max_adv >= 2 and not won,
        won_from_disadvantage=max_dis <= -2 and won,
        our_deaths_traded=sum(1 for d in our_deaths if d.traded),
        our_deaths_untraded=len(untraded),
        our_isolated_deaths=sum(1 for d in our_deaths if d.isolated),
        trade_kills_ours=trade_kills,
        ults_used_ours=ults_ours,
        ults_used_opp=ults_opp,
        activity_zone=activity,
        our_deaths_caught_off_angle=off_angle,
        notable=notable,
    )


def _is_trade_kill(enemy_death: DeathInfo, deaths: list[DeathInfo]) -> bool:
    """True if this enemy death was itself a trade for one of our deaths."""
    k = enemy_death.kill
    for d in deaths:
        if d.traded_by == k.killer and d.kill.killer == k.victim:
            return True
    return False


@dataclass
class TeamMatchStats:
    team: str
    rounds_won: int
    rounds_lost: int
    attack_won: int
    attack_played: int
    defense_won: int
    defense_played: int
    pistols_won: int
    pistols_played: int
    first_kill_rate: float
    first_kill_conversion: float     # rounds won when we got first kill
    first_death_conversion: float    # rounds won when we gave first death
    trade_rate: float                # our deaths that were traded
    isolated_death_rate: float
    advantages_thrown: int
    comebacks: int
    plants: int
    post_plant_win_rate: float
    retakes_won: int
    retakes_attempted: int
    site_hits: dict[str, int]
    site_hit_wins: dict[str, int]
    eco_buy_record: dict[str, list[int]]   # buy type -> [won, played]
    deaths_caught_off_angle_pct: float = 0.0


def team_match_stats(match: Match, team: str, facts: list[TeamRoundFacts]) -> TeamMatchStats:
    att = [f for f in facts if f.side == "attack"]
    dfn = [f for f in facts if f.side == "defense"]
    pist = [f for f in facts if f.our_buy == "pistol"]
    fk = [f for f in facts if f.first_kill_ours is True]
    fd = [f for f in facts if f.first_kill_ours is False]
    deaths_traded = sum(f.our_deaths_traded for f in facts)
    deaths_total = deaths_traded + sum(f.our_deaths_untraded for f in facts)
    iso = sum(f.our_isolated_deaths for f in facts)
    plants = [f for f in att if f.plant_site]
    retakes = [f for f in dfn if f.plant_site]
    site_hits: dict[str, int] = {}
    site_wins: dict[str, int] = {}
    for f in att:
        s = f.plant_site or (f.activity_zone if f.activity_zone in ("A", "B", "C") else None)
        if s:
            site_hits[s] = site_hits.get(s, 0) + 1
            if f.won:
                site_wins[s] = site_wins.get(s, 0) + 1
    buys: dict[str, list[int]] = {}
    for f in facts:
        b = buys.setdefault(f.our_buy, [0, 0])
        b[1] += 1
        if f.won:
            b[0] += 1

    def rate(a: int, b: int) -> float:
        return round(a / b, 3) if b else 0.0

    return TeamMatchStats(
        team=team,
        rounds_won=sum(f.won for f in facts),
        rounds_lost=sum(not f.won for f in facts),
        attack_won=sum(f.won for f in att), attack_played=len(att),
        defense_won=sum(f.won for f in dfn), defense_played=len(dfn),
        pistols_won=sum(f.won for f in pist), pistols_played=len(pist),
        first_kill_rate=rate(len(fk), len(fk) + len(fd)),
        first_kill_conversion=rate(sum(f.won for f in fk), len(fk)),
        first_death_conversion=rate(sum(f.won for f in fd), len(fd)),
        trade_rate=rate(deaths_traded, deaths_total),
        isolated_death_rate=rate(iso, deaths_total),
        advantages_thrown=sum(f.threw_advantage for f in facts),
        comebacks=sum(f.won_from_disadvantage for f in facts),
        plants=len(plants),
        post_plant_win_rate=rate(sum(f.won for f in plants), len(plants)),
        retakes_won=sum(f.won for f in retakes), retakes_attempted=len(retakes),
        site_hits=site_hits, site_hit_wins=site_wins,
        eco_buy_record=buys,
        deaths_caught_off_angle_pct=rate(sum(f.our_deaths_caught_off_angle for f in facts), deaths_total),
    )
