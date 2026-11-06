"""Turn analysed facts into compact, factual round summaries for the LLM."""
from __future__ import annotations

from dataclasses import asdict

import yaml

from ..analysis.player import PlayerMatchStats, PlayerRoundFacts
from ..analysis.team import TeamMatchStats, TeamRoundFacts


def _clean(d):
    """Drop empty / None values to keep prompts short."""
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items() if v not in (None, "", [], {}, ())}
    if isinstance(d, list):
        return [_clean(v) for v in d]
    if isinstance(d, tuple):
        return list(d)
    return d


def team_round_block(f: TeamRoundFacts) -> dict:
    return _clean({
        "side": f.side,
        "result": ("WON" if f.won else "LOST") + (f" ({f.result})" if f.result else ""),
        "score_before": f"{f.score_before[0]}-{f.score_before[1]}",
        "economy": f"us {f.our_buy} (avg {f.our_loadout_avg}) vs them {f.opp_buy} (avg {f.opp_loadout_avg})",
        "first_kill": ("ours: " if f.first_kill_ours else "theirs: ") + f.first_kill_desc
                      + f" at {f.first_kill_time}" if f.first_kill_ours is not None else "none",
        "our_positions_at_first_contact": f.our_setup_at_first_contact,
        "their_positions_at_first_contact": f.opp_setup_at_first_contact,
        "plant": (f"{f.plant_site} at {f.plant_time}, alive {f.alive_at_plant[0]}v{f.alive_at_plant[1]}"
                  + (", defused" if f.defused else "")) if f.plant_site else None,
        "player_count_progression": f.progression,
        "our_deaths": f"{f.our_deaths_traded} traded, {f.our_deaths_untraded} untraded, "
                      f"{f.our_isolated_deaths} isolated",
        "trade_kills_by_us": f.trade_kills_ours,
        "fighting_mostly_at": f.activity_zone,
        "ults_used_by_us": f.ults_used_ours,
        "ults_used_by_them": f.ults_used_opp,
        "flags": f.notable,
    })


def player_round_block(f: PlayerRoundFacts) -> dict:
    death = None
    if not f.survived:
        death = (f"{f.death_time} at {f.death_area} by {f.killed_by} ({f.killed_with})"
                 f", {'traded' if f.death_traded else 'NOT traded'}"
                 + (f", isolated (nearest teammate {f.nearest_teammate_m} m)" if f.death_isolated else "")
                 + (f", team was {f.alive_when_died[0]}v{f.alive_when_died[1]}" if f.alive_when_died else ""))
        duel = []
        if f.death_distance_m is not None:
            duel.append(f"killer ~{f.death_distance_m:.0f} m away")
        if f.death_my_view:
            duel.append({"facing": "you were looking at your killer (lost the aim duel)",
                         "side": f"your killer was off to your side ({f.death_my_angle} deg from where you looked)",
                         "behind": "your killer was behind you / you looked the other way"}[f.death_my_view])
        if f.death_killer_view == "facing":
            duel.append("killer was aiming your way")
        if f.damage_to_killer is not None:
            duel.append(f"you did {f.damage_to_killer} damage to your killer")
        if duel:
            death += "; " + ", ".join(duel)
    util = {k: v for k, v in f.utility_casts.items() if v}
    return _clean({
        "agent": f.agent,
        "loadout": f"{f.weapon} + {f.armor} ({f.loadout_value})",
        "kills": f.kill_details or f.kills,
        "assists": f.assists,
        "damage": f.damage,
        "shots_hit": f"{f.headshots} head / {f.bodyshots} body / {f.legshots} leg",
        "first_kill": f.first_kill or None,
        "first_death": f.first_death or None,
        "trade_kills": f.trade_kills,
        "death": death if death else "survived",
        "clutch": f.clutch,
        "utility_casts": (util or "none") if f.utility_known else None,
        "ult_used": (f.ult_used or None) if f.utility_known else None,
        "positions_from_kill_snapshots": f.path,
    })


def round_summary(team_f: TeamRoundFacts | None, player_f: PlayerRoundFacts | None,
                  minimap: dict | None = None, own_note: str | None = None) -> str:
    rnd = (team_f or player_f).round
    doc: dict = {"round": rnd}
    if team_f:
        doc["team"] = team_round_block(team_f)
    if player_f:
        doc["you"] = player_round_block(player_f)
    if minimap:
        doc["minimap_tracking"] = minimap
    if own_note:
        doc["players_own_note"] = own_note
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)


def match_stats_block(team_stats: TeamMatchStats | None, player_stats: PlayerMatchStats | None) -> str:
    doc = {}
    if team_stats:
        d = asdict(team_stats)
        d["eco_buy_record"] = {k: f"{v[0]}/{v[1]}" for k, v in d["eco_buy_record"].items()}
        doc["team"] = d
    if player_stats:
        doc["you"] = asdict(player_stats)
    return yaml.safe_dump(_clean(doc), sort_keys=False, allow_unicode=True, width=120)
