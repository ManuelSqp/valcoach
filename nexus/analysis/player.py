"""Individual-player analysis: per-round facts and match aggregates."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..maps import MapInfo
from ..models import Match, Round
from .core import UNITS_PER_METER, area, death_infos, fmt_ms
from .view import ViewModel, duel_view, facing_label, range_bucket


@dataclass
class PlayerRoundFacts:
    round: int
    side: str
    won: bool
    agent: str
    weapon: str
    armor: str
    loadout_value: int
    kills: int
    assists: int
    damage: int
    headshots: int
    bodyshots: int
    legshots: int
    survived: bool
    kast: bool
    first_kill: bool
    first_death: bool
    trade_kills: int                  # kills that avenged a teammate within 5 s
    death_time: str | None
    death_area: str | None
    killed_by: str | None
    killed_with: str | None
    death_traded: bool | None
    death_isolated: bool | None
    nearest_teammate_m: float | None
    alive_when_died: tuple[int, int] | None   # (own team alive, enemies alive) before death
    clutch: str | None                 # e.g. "1v3 won"
    utility_casts: dict[str, int]
    ult_used: bool
    path: list[str] = field(default_factory=list)   # "0:21 A Main" positions sampled from kill snapshots
    kill_details: list[str] = field(default_factory=list)
    # ---- duels (from positions + view directions) ----
    kill_duels: list[dict] = field(default_factory=list)
    death_distance_m: float | None = None
    death_my_view: str | None = None          # was I looking at my killer? facing / side / behind
    death_my_angle: int | None = None
    death_killer_view: str | None = None      # was my killer looking at me?
    damage_to_killer: int | None = None       # damage I did to the player who killed me (this round)
    utility_known: bool = True                # False: the match data has no ability casts


def analyse_player_round(match: Match, rnd: Round, puuid: str, map_info: MapInfo | None,
                         vm: ViewModel | None = None) -> PlayerRoundFacts:
    me = match.players[puuid]
    team = me.team
    s = rnd.stats.get(puuid)
    deaths = death_infos(match, rnd, map_info)
    vm = vm or ViewModel()

    my_death = next((d for d in deaths if d.kill.victim == puuid), None)
    my_kills = [k for k in rnd.kills if k.killer == puuid]
    assists = sum(1 for k in rnd.kills if puuid in k.assistants)
    trade_kills = sum(1 for d in deaths if d.traded_by == puuid)
    fk = rnd.kills[0] if rnd.kills else None

    # KAST: kill, assist, survived, or traded
    survived = my_death is None
    kast = bool(my_kills) or assists > 0 or survived or bool(my_death and my_death.traded)

    # positions over time from every kill snapshot while alive
    path: list[str] = []
    last_area = None
    for k in rnd.kills:
        if my_death and k.t_round_ms > my_death.kill.t_round_ms:
            break
        loc = k.loc_of(puuid)
        if loc is None and k.victim == puuid:
            ax, ay = k.victim_x, k.victim_y
        elif loc is not None:
            ax, ay = loc.x, loc.y
        else:
            continue
        a = area(map_info, ax, ay)
        if a != last_area:
            path.append(f"{fmt_ms(k.t_round_ms)} {a}")
            last_area = a
    if rnd.plant and not (my_death and my_death.kill.t_round_ms < rnd.plant.t_round_ms):
        for pl in rnd.plant.player_locations:
            if pl.puuid == puuid:
                path.append(f"{fmt_ms(rnd.plant.t_round_ms)} {area(map_info, pl.x, pl.y)} (at plant)")

    # ---- my kills as duels ----
    kill_details, kill_duels = [], []
    for k in my_kills:
        dv = duel_view(vm, k, puuid, k.victim)
        their = facing_label(dv.other_angle_to_me)
        kill_duels.append({
            "t": fmt_ms(k.t_round_ms), "victim": match.label(k.victim), "weapon": k.weapon or "ability",
            "distance_m": dv.distance_m, "range": range_bucket(dv.distance_m),
            "victim_view": their, "victim_angle": dv.other_angle_to_me,
        })
        note = {"facing": "they were looking at you (won the duel)",
                "side": "you caught them off-angle",
                "behind": "they were looking away"}.get(their or "", "")
        kill_details.append(
            f"{fmt_ms(k.t_round_ms)} killed {match.label(k.victim)} at {area(map_info, k.victim_x, k.victim_y)}"
            f" with {k.weapon or 'ability'}" + (f" from ~{dv.distance_m:.0f} m" if dv.distance_m is not None else "")
            + (f", {note}" if note else "")
        )

    # ---- my death as a duel ----
    death_distance = death_my_view = death_killer_view = None
    death_my_angle = damage_to_killer = None
    if my_death and my_death.kill.killer:
        k = my_death.kill
        dv = duel_view(vm, k, puuid, k.killer)
        death_distance = dv.distance_m
        death_my_angle = dv.my_angle_to_other
        death_my_view = facing_label(dv.my_angle_to_other)
        death_killer_view = facing_label(dv.other_angle_to_me)
        if s is not None:
            damage_to_killer = s.damage_to.get(k.killer, 0)

    # clutch: first moment I'm the last one alive on my team
    clutch = None
    alive_team = {t: len(match.players_on(t)) or 5 for t in match.teams}
    dead: set[str] = set()
    for k in rnd.kills:
        dead.add(k.victim)
        alive_team[k.victim_team] = alive_team.get(k.victim_team, 5) - 1
        if k.victim_team == team and alive_team[team] == 1 and puuid not in dead:
            enemies = alive_team.get(match.other_team(team), 0)
            if enemies >= 1:
                clutch = f"1v{enemies} " + ("won" if rnd.winning_team == team else "lost")
            break

    casts = (s.ability_casts if s else {}) if match.has_utility else {}
    return PlayerRoundFacts(
        round=rnd.number,
        side=rnd.side_of(team),
        won=rnd.winning_team == team,
        agent=me.agent,
        weapon=(s.weapon if s else "") or "?",
        armor=(s.armor if s else "") or "none",
        loadout_value=s.loadout_value if s else 0,
        kills=len(my_kills),
        assists=assists,
        damage=s.damage_dealt if s else 0,
        headshots=s.headshots if s else 0,
        bodyshots=s.bodyshots if s else 0,
        legshots=s.legshots if s else 0,
        survived=survived,
        kast=kast,
        first_kill=bool(fk and fk.killer == puuid),
        first_death=bool(fk and fk.victim == puuid),
        trade_kills=trade_kills,
        death_time=fmt_ms(my_death.kill.t_round_ms) if my_death else None,
        death_area=area(map_info, my_death.kill.victim_x, my_death.kill.victim_y) if my_death else None,
        killed_by=match.label(my_death.kill.killer) if my_death else None,
        killed_with=(my_death.kill.weapon or "ability") if my_death else None,
        death_traded=my_death.traded if my_death else None,
        death_isolated=my_death.isolated if my_death else None,
        nearest_teammate_m=(round(my_death.nearest_teammate_units / UNITS_PER_METER, 1)
                            if my_death and my_death.nearest_teammate_units is not None else None),
        alive_when_died=my_death.alive_before if my_death else None,
        clutch=clutch,
        utility_casts=casts,
        ult_used=casts.get("ultimate", 0) > 0,
        path=path,
        kill_details=kill_details,
        kill_duels=kill_duels,
        death_distance_m=death_distance,
        death_my_view=death_my_view,
        death_my_angle=death_my_angle,
        death_killer_view=death_killer_view,
        damage_to_killer=damage_to_killer,
        utility_known=match.has_utility,
    )


@dataclass
class PlayerMatchStats:
    riot_id: str
    agent: str
    rounds: int
    kills: int
    deaths: int
    assists: int
    acs: float
    adr: float
    kd: float
    hs_pct: float
    kast_pct: float
    first_kills: int
    first_deaths: int
    trade_kills: int
    traded_death_pct: float
    isolated_deaths: int
    clutches: str
    multikills: dict[str, int]
    avg_death_time_s: float | None
    top_death_areas: list[tuple[str, int]]
    kills_by_weapon: list[tuple[str, int]]
    utility_per_round: float | None
    attack_adr: float
    defense_adr: float
    # ---- duels ----
    view_analysis: bool = False
    deaths_by_my_view: dict[str, int] = field(default_factory=dict)     # facing / side / behind
    kills_by_victim_view: dict[str, int] = field(default_factory=dict)
    avg_damage_to_killer: float | None = None
    deaths_without_damage: int = 0
    duels_by_range: dict[str, dict[str, int]] = field(default_factory=dict)   # range -> {kills, deaths}
    shots_by_weapon: dict[str, dict] = field(default_factory=dict)            # main weapon of the round
    ults_used: int | None = None


def player_match_stats(match: Match, puuid: str, facts: list[PlayerRoundFacts],
                       vm: ViewModel | None = None) -> PlayerMatchStats:
    me = match.players[puuid]
    n = len(facts) or 1
    deaths = [f for f in facts if not f.survived]
    shots = me.headshots + me.bodyshots + me.legshots
    clutch_att = [f for f in facts if f.clutch]
    clutch_won = [f for f in clutch_att if f.clutch.endswith("won")]
    mk = Counter(f.kills for f in facts if f.kills >= 2)
    death_secs = []
    for f in deaths:
        if f.death_time and ":" in f.death_time:
            m, s = f.death_time.split(":")
            death_secs.append(int(m) * 60 + int(s))
    weapons = Counter(d["weapon"] for f in facts for d in f.kill_duels)
    att = [f for f in facts if f.side == "attack"]
    dfn = [f for f in facts if f.side == "defense"]
    util = ults = None
    if match.has_utility:
        util = sum(sum(v for k, v in f.utility_casts.items() if k != "ultimate") for f in facts)
        ults = sum(f.utility_casts.get("ultimate", 0) for f in facts)
    elif any(me.ability_casts.values()):
        # no per-round casts (live API): the match totals are still real numbers
        util = sum(v for k, v in me.ability_casts.items() if k != "ultimate")
        ults = me.ability_casts.get("ultimate", 0)

    by_range: dict[str, dict[str, int]] = {}
    for f in facts:
        for d in f.kill_duels:
            if d["range"]:
                by_range.setdefault(d["range"], {"kills": 0, "deaths": 0})["kills"] += 1
        if f.death_distance_m is not None:
            by_range.setdefault(range_bucket(f.death_distance_m), {"kills": 0, "deaths": 0})["deaths"] += 1

    shots_w: dict[str, dict] = {}
    for f in facts:
        if f.weapon and f.weapon != "?":
            w = shots_w.setdefault(f.weapon, {"head": 0, "body": 0, "leg": 0, "rounds": 0})
            w["head"] += f.headshots
            w["body"] += f.bodyshots
            w["leg"] += f.legshots
            w["rounds"] += 1
    for w in shots_w.values():
        tot = w["head"] + w["body"] + w["leg"]
        w["hs_pct"] = round(100 * w["head"] / tot, 1) if tot else 0.0
        w["leg_pct"] = round(100 * w["leg"] / tot, 1) if tot else 0.0

    dmg_k = [f.damage_to_killer for f in deaths if f.damage_to_killer is not None]

    def pct(a: float, b: float) -> float:
        return round(100 * a / b, 1) if b else 0.0

    return PlayerMatchStats(
        riot_id=me.riot_id,
        agent=me.agent,
        rounds=len(facts),
        kills=me.kills, deaths=me.deaths, assists=me.assists,
        acs=round(me.score / n, 1),
        adr=round(sum(f.damage for f in facts) / n, 1),
        kd=round(me.kills / me.deaths, 2) if me.deaths else float(me.kills),
        hs_pct=pct(me.headshots, shots),
        kast_pct=pct(sum(f.kast for f in facts), len(facts)),
        first_kills=sum(f.first_kill for f in facts),
        first_deaths=sum(f.first_death for f in facts),
        trade_kills=sum(f.trade_kills for f in facts),
        traded_death_pct=pct(sum(bool(f.death_traded) for f in deaths), len(deaths)),
        isolated_deaths=sum(bool(f.death_isolated) for f in deaths),
        clutches=f"{len(clutch_won)}/{len(clutch_att)}",
        multikills={f"{k}k": v for k, v in sorted(mk.items())},
        avg_death_time_s=round(sum(death_secs) / len(death_secs), 1) if death_secs else None,
        top_death_areas=Counter(f.death_area for f in deaths if f.death_area).most_common(3),
        kills_by_weapon=weapons.most_common(5),
        utility_per_round=round(util / n, 2) if util is not None else None,
        ults_used=ults,
        attack_adr=round(sum(f.damage for f in att) / len(att), 1) if att else 0.0,
        defense_adr=round(sum(f.damage for f in dfn) / len(dfn), 1) if dfn else 0.0,
        view_analysis=bool(vm and vm.ok),
        deaths_by_my_view=dict(Counter(f.death_my_view for f in deaths if f.death_my_view)),
        kills_by_victim_view=dict(Counter(d["victim_view"] for f in facts for d in f.kill_duels if d["victim_view"])),
        avg_damage_to_killer=round(sum(dmg_k) / len(dmg_k), 1) if dmg_k else None,
        deaths_without_damage=sum(1 for x in dmg_k if x == 0),
        duels_by_range=by_range,
        shots_by_weapon=shots_w,
    )
