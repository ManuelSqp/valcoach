"""Convert raw HenrikDev v4 match JSON into valcoach.models objects."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .models import Kill, Match, Player, PlayerLoc, PlayerRound, Round, SpikeEvent


def _g(d: Any, *keys, default=None):
    """Safe nested get."""
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
    return default if cur is None else cur


def _locs(raw: list | None) -> list[PlayerLoc]:
    out = []
    for pl in raw or []:
        out.append(PlayerLoc(
            puuid=_g(pl, "player", "puuid", default=""),
            team=_g(pl, "player", "team", default=""),
            x=float(_g(pl, "location", "x", default=0)),
            y=float(_g(pl, "location", "y", default=0)),
            view=float(_g(pl, "view_radians", default=0.0)),
        ))
    return out


def _spike(kind: str, raw: dict | None) -> SpikeEvent | None:
    if not raw:
        return None
    return SpikeEvent(
        kind=kind,
        t_round_ms=int(_g(raw, "round_time_in_ms", default=0)),
        site=str(_g(raw, "site", default="")),
        player=_g(raw, "player", "puuid", default=""),
        team=_g(raw, "player", "team", default=""),
        x=float(_g(raw, "location", "x", default=0)),
        y=float(_g(raw, "location", "y", default=0)),
        player_locations=_locs(raw.get("player_locations")),
    )


def half_length_for_queue(queue_id: str) -> int:
    q = (queue_id or "").lower()
    if "swift" in q:
        return 4
    if "spike" in q:
        return 3
    return 12


def rule_attackers(idx: int, half: int, first_attacker: str, second: str) -> str:
    """Side rule: first half `first_attacker` attacks, then swap; OT alternates."""
    regulation = 2 * half
    if idx < half:
        return first_attacker
    if idx < regulation:
        return second
    # overtime: sides swap every round, starting with original sides
    return first_attacker if (idx - regulation) % 2 == 0 else second


def infer_attackers(rounds_raw: list[dict], teams: list[str], half: int) -> list[str]:
    """Attacking team per round.

    Riot convention is that Red starts on attack. We verify this against
    plants (the planter is always an attacker) and flip if the evidence
    disagrees, so the parser is robust if the convention ever changes.
    """
    if len(teams) < 2:
        return [teams[0] if teams else ""] * len(rounds_raw)
    first = "Red" if "Red" in teams else teams[0]
    second = next(t for t in teams if t != first)
    agree = disagree = 0
    for i, r in enumerate(rounds_raw):
        planter_team = _g(r, "plant", "player", "team")
        if planter_team:
            if planter_team == rule_attackers(i, half, first, second):
                agree += 1
            else:
                disagree += 1
    if disagree > agree:
        first, second = second, first
    return [rule_attackers(i, half, first, second) for i in range(len(rounds_raw))]


def parse_match(raw: dict) -> Match:
    """Parse a v4 match payload (either {"status","data"} or the data dict)."""
    data = raw.get("data", raw) if isinstance(raw, dict) else raw
    meta = data.get("metadata", {})

    players: dict[str, Player] = {}
    for p in data.get("players", []):
        st = p.get("stats", {}) or {}
        ac = p.get("ability_casts", {}) or {}
        players[p["puuid"]] = Player(
            puuid=p["puuid"],
            name=p.get("name", ""),
            tag=p.get("tag", ""),
            team=p.get("team_id", ""),
            agent=_g(p, "agent", "name", default="?"),
            agent_id=_g(p, "agent", "id", default="") or "",
            party_id=p.get("party_id", ""),
            tier=str(_g(p, "tier", "name", default="")),
            kills=int(st.get("kills", 0)),
            deaths=int(st.get("deaths", 0)),
            assists=int(st.get("assists", 0)),
            score=int(st.get("score", 0)),
            headshots=int(st.get("headshots", 0)),
            bodyshots=int(st.get("bodyshots", 0)),
            legshots=int(st.get("legshots", 0)),
            damage_dealt=int(_g(st, "damage", "dealt", default=0)),
            damage_received=int(_g(st, "damage", "received", default=0)),
            ability_casts={k: int(v or 0) for k, v in ac.items()},
        )

    teams_raw = data.get("teams", [])
    teams = [t["team_id"] for t in teams_raw] or sorted({p.team for p in players.values()})
    team_rounds_won = {t["team_id"]: int(_g(t, "rounds", "won", default=0)) for t in teams_raw}

    queue_id = _g(meta, "queue", "id", default="")
    rounds_raw = data.get("rounds", [])
    attackers = infer_attackers(rounds_raw, teams, half_length_for_queue(queue_id))

    kills: list[Kill] = []
    for k in data.get("kills", []):
        kills.append(Kill(
            round=int(k.get("round", 0)),
            t_round_ms=int(k.get("time_in_round_in_ms", 0)),
            t_match_ms=int(k.get("time_in_match_in_ms", 0)),
            killer=_g(k, "killer", "puuid", default=""),
            killer_team=_g(k, "killer", "team", default=""),
            victim=_g(k, "victim", "puuid", default=""),
            victim_team=_g(k, "victim", "team", default=""),
            assistants=[a.get("puuid", "") for a in k.get("assistants", []) or []],
            weapon=_g(k, "weapon", "name", default="") or "",
            weapon_type=_g(k, "weapon", "type", default="") or "",
            victim_x=float(_g(k, "location", "x", default=0)),
            victim_y=float(_g(k, "location", "y", default=0)),
            player_locations=_locs(k.get("player_locations")),
        ))
    kills.sort(key=lambda k: (k.round, k.t_round_ms))

    rounds: list[Round] = []
    for i, r in enumerate(rounds_raw):
        idx = int(r.get("id", i))
        stats: dict[str, PlayerRound] = {}
        for s in r.get("stats", []) or []:
            pu = _g(s, "player", "puuid", default="")
            dmg_to: dict[str, int] = {}
            for de in s.get("damage_events", []) or []:
                vid = _g(de, "player", "puuid", default="")
                dmg_to[vid] = dmg_to.get(vid, 0) + int(de.get("damage", 0))
            ac = s.get("ability_casts", {}) or {}
            stats[pu] = PlayerRound(
                puuid=pu,
                team=_g(s, "player", "team", default=""),
                kills=int(_g(s, "stats", "kills", default=0)),
                score=int(_g(s, "stats", "score", default=0)),
                headshots=int(_g(s, "stats", "headshots", default=0)),
                bodyshots=int(_g(s, "stats", "bodyshots", default=0)),
                legshots=int(_g(s, "stats", "legshots", default=0)),
                loadout_value=int(_g(s, "economy", "loadout_value", default=0)),
                remaining=int(_g(s, "economy", "remaining", default=0)),
                weapon=_g(s, "economy", "weapon", "name", default="") or "",
                armor=_g(s, "economy", "armor", "name", default="") or "",
                damage_dealt=sum(dmg_to.values()),
                damage_to=dmg_to,
                ability_casts={k: int(v or 0) for k, v in ac.items()},
                was_afk=bool(s.get("was_afk", False)),
                stayed_in_spawn=bool(s.get("stayed_in_spawn", False)),
            )
        rkills = [k for k in kills if k.round == idx]
        start = None
        if rkills:
            # median is robust against odd timing entries
            offs = sorted(k.t_match_ms - k.t_round_ms for k in rkills)
            start = offs[len(offs) // 2]
        rounds.append(Round(
            index=idx,
            winning_team=r.get("winning_team", ""),
            result=r.get("result", ""),
            ceremony=r.get("ceremony", ""),
            attacking_team=attackers[i] if i < len(attackers) else "",
            plant=_spike("plant", r.get("plant")),
            defuse=_spike("defuse", r.get("defuse")),
            stats=stats,
            kills=rkills,
            start_match_ms=start,
        ))

    # derive any missing round start from neighbours (rounds with zero kills)
    _fill_round_starts(rounds)

    if not team_rounds_won:
        c = Counter(r.winning_team for r in rounds)
        team_rounds_won = {t: c.get(t, 0) for t in teams}

    return Match(
        match_id=meta.get("match_id", ""),
        map_name=_g(meta, "map", "name", default="?"),
        map_id=_g(meta, "map", "id", default=""),
        started_at=meta.get("started_at", ""),
        queue=queue_id,
        game_length_ms=int(meta.get("game_length_in_ms", 0)),
        region=meta.get("region") or "",
        players=players,
        teams=teams,
        team_rounds_won=team_rounds_won,
        rounds=rounds,
        kills=kills,
        raw_premier=meta.get("premier"),
        has_utility=_utility_present(data),
        mode_type=_g(meta, "queue", "mode_type", default="") or "",
    )


def _utility_present(data: dict) -> bool:
    """True if any player has any per-round ability cast > 0.
    All null/0 means the data is missing (not that nobody used utility). Only the rounds count:
    the live API fills the match totals (players[].ability_casts) but sends null for every round,
    and the round prompts are built from the per-round casts."""
    for r in data.get("rounds", []) or []:
        for s in r.get("stats", []) or []:
            if any((v or 0) > 0 for v in (s.get("ability_casts") or {}).values()):
                return True
    return False


def _fill_round_starts(rounds: list[Round]) -> None:
    known = [(i, r.start_match_ms) for i, r in enumerate(rounds) if r.start_match_ms is not None]
    if not known:
        return
    if len(known) >= 2:
        # average round length from known rounds
        spans = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(known, known[1:]) if b[0] > a[0]]
        avg = sorted(spans)[len(spans) // 2] if spans else 100_000
    else:
        avg = 100_000
    for i, r in enumerate(rounds):
        if r.start_match_ms is None:
            prev = [(j, s) for j, s in known if j < i]
            nxt = [(j, s) for j, s in known if j > i]
            if prev and nxt:
                (j0, s0), (j1, s1) = prev[-1], nxt[0]
                r.start_match_ms = int(s0 + (s1 - s0) * (i - j0) / (j1 - j0))
            elif prev:
                j0, s0 = prev[-1]
                r.start_match_ms = int(s0 + avg * (i - j0))
            else:
                j1, s1 = nxt[0]
                r.start_match_ms = int(max(0, s1 - avg * (j1 - i)))
