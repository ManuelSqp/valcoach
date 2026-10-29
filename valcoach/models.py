"""Normalised match model built from HenrikDev v4 match data.

Coordinates are Valorant world units (same space as the API). Times are ms.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerLoc:
    puuid: str
    team: str
    x: float
    y: float
    view: float = 0.0  # view_radians


@dataclass
class Kill:
    round: int
    t_round_ms: int
    t_match_ms: int
    killer: str            # puuid ("" for environment / spike)
    killer_team: str
    victim: str
    victim_team: str
    assistants: list[str]
    weapon: str
    weapon_type: str
    victim_x: float
    victim_y: float
    player_locations: list[PlayerLoc] = field(default_factory=list)

    def loc_of(self, puuid: str) -> PlayerLoc | None:
        for pl in self.player_locations:
            if pl.puuid == puuid:
                return pl
        return None


@dataclass
class SpikeEvent:
    kind: str              # "plant" | "defuse"
    t_round_ms: int
    site: str              # "A", "B", "C" ("" for defuse if unknown)
    player: str
    team: str
    x: float
    y: float
    player_locations: list[PlayerLoc] = field(default_factory=list)


@dataclass
class PlayerRound:
    puuid: str
    team: str
    kills: int
    score: int
    headshots: int
    bodyshots: int
    legshots: int
    loadout_value: int
    remaining: int
    weapon: str
    armor: str
    damage_dealt: int
    damage_to: dict[str, int]      # victim puuid -> damage
    ability_casts: dict[str, int]
    was_afk: bool = False
    stayed_in_spawn: bool = False


@dataclass
class Round:
    index: int                      # 0-based
    winning_team: str
    result: str                     # e.g. "Elimination", "Bomb detonated", "Bomb defused"
    ceremony: str
    attacking_team: str
    plant: SpikeEvent | None
    defuse: SpikeEvent | None
    stats: dict[str, PlayerRound]
    kills: list[Kill]
    start_match_ms: int | None = None   # derived from kills: t_match - t_round

    @property
    def number(self) -> int:
        return self.index + 1

    def defending_team(self, teams: list[str]) -> str:
        return next((t for t in teams if t != self.attacking_team), "")

    def side_of(self, team: str) -> str:
        return "attack" if team == self.attacking_team else "defense"


@dataclass
class Player:
    puuid: str
    name: str
    tag: str
    team: str
    agent: str
    party_id: str
    tier: str
    kills: int
    deaths: int
    assists: int
    score: int
    headshots: int
    bodyshots: int
    legshots: int
    damage_dealt: int
    damage_received: int
    ability_casts: dict[str, int]
    agent_id: str = ""

    @property
    def riot_id(self) -> str:
        return f"{self.name}#{self.tag}"


@dataclass
class Match:
    match_id: str
    map_name: str
    map_id: str
    started_at: str
    queue: str
    game_length_ms: int
    region: str
    players: dict[str, Player]
    teams: list[str]
    team_rounds_won: dict[str, int]
    rounds: list[Round]
    kills: list[Kill]
    raw_premier: dict | None = None
    # Riot's match data often has no ability casts (all null). Then utility can't be judged.
    has_utility: bool = True
    mode_type: str = ""             # "Standard", "Swiftplay", "Deathmatch", ...

    # ---- helpers -------------------------------------------------------
    def team_of(self, puuid: str) -> str:
        p = self.players.get(puuid)
        return p.team if p else ""

    def players_on(self, team: str) -> list[Player]:
        return [p for p in self.players.values() if p.team == team]

    def other_team(self, team: str) -> str:
        return next((t for t in self.teams if t != team), "")

    def find_player(self, name: str, tag: str | None = None) -> Player | None:
        name_l = name.lower()
        for p in self.players.values():
            if p.name.lower() == name_l and (tag is None or p.tag.lower() == tag.lower()):
                return p
        return None

    def label(self, puuid: str) -> str:
        """Human label: 'Name (Agent)'."""
        p = self.players.get(puuid)
        return f"{p.name} ({p.agent})" if p else "unknown"

    def score_before(self, round_index: int, team: str) -> tuple[int, int]:
        own = sum(1 for r in self.rounds[:round_index] if r.winning_team == team)
        opp = round_index - own
        return own, opp
