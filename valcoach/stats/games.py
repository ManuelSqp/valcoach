"""Match history -> one row per game for one player, stored in profiles/<id>/stats/games.json.

Two sources:
  * full matches (v4 history, 10 per request, cached forever): everything, incl. opening
    duels, where you died / got kills, trades, KAST and which agents both teams played.
  * HenrikDev's stored archive (v1, 20 summaries per request): map, agent, result, K/D/A and
    score only, but it goes much further back. Used where no full match is available.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..analysis.core import death_infos
from ..maps import MapInfo, MapRegistry
from ..models import Match
from ..parse import parse_match
from . import roles

QUEUES = ("competitive", "premier")
ROW_VERSION = 3            # bump when rows from full matches gain fields; old rows are rebuilt from the cache
ISOLATED_UNITS = 2000      # ~20 m to the nearest living teammate
TRADE_MS = 3000
Log = Callable[[str], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
def _area(mi: MapInfo | None, x: float, y: float) -> str:
    if mi is None:
        return "?"
    try:
        return mi.area(x, y)
    except Exception:
        return "?"


def row_from_match(match: Match, puuid: str, mi: MapInfo | None) -> dict | None:
    me = match.players.get(puuid)
    if me is None or not match.rounds:
        return None
    team, opp = me.team, match.other_team(me.team)
    own_r, opp_r = match.team_rounds_won.get(team, 0), match.team_rounds_won.get(opp, 0)
    n = len(match.rounds)
    row = {
        "match_id": match.match_id, "started_at": match.started_at, "queue": (match.queue or "").lower(),
        "map": match.map_name, "agent": me.agent, "role": roles.role_of(me.agent),
        "won": 1.0 if own_r > opp_r else (0.0 if own_r < opp_r else 0.5), "score": f"{own_r}-{opp_r}",
        "rounds": n, "kills": me.kills, "deaths": me.deaths, "assists": me.assists,
        "acs": round(me.score / n, 1), "source": "full",
        "fk": 0, "fd": 0, "kast": 0, "adr": 0.0, "traded_deaths": 0,
        "sides": {"attack": [0, 0], "defense": [0, 0]},    # [rounds played, rounds won]
        "openings": [],      # [side, area, 1 = you got the first kill / 0 = you died first]
        "deaths_at": [],     # [side, area, traded 0/1, first death 0/1]
        "kills_at": [],      # [side, area]
        "v": ROW_VERSION,
        "trade_kills": 0,     # kills on someone who had just killed a teammate
        "op_rounds": 0, "op_kills": 0,
        "first_in": {"attack": 0, "defense": 0},     # rounds where your team's first fight involved you
        "survived": {"attack": 0, "defense": 0},
        "iso": {"attack": [0, 0, 0, 0], "defense": [0, 0, 0, 0]},   # [kills, far from team, deaths, far from team]
        "def_zones": [],      # where you were at your defense fights (A / B / C / Mid ...)
        "own_agents": sorted(p.agent for p in match.players_on(team)),
        "opp_agents": sorted(p.agent for p in match.players_on(opp)),
        # v3: aim and late-round numbers
        "shots": [me.headshots, me.bodyshots, me.legshots],
        "duels": [],          # [distance in m, 1 = you won the fight / 0 = you died]
        "clutch": {},         # "X" (1vX) -> [attempts, won]
        "retake": [0, 0],     # defense rounds they planted while you were alive: [rounds, won]
        "postplant": [0, 0],  # attack rounds your team planted while you were alive: [rounds, won]
    }
    dmg = 0
    for rnd in match.rounds:
        side = rnd.side_of(team)
        row["sides"][side][0] += 1
        if rnd.winning_team == team:
            row["sides"][side][1] += 1
        st = rnd.stats.get(puuid)
        if st:
            dmg += st.damage_dealt
        got_kill = assisted = died = traded = False
        if st and (st.weapon or "").lower() == "operator":
            row["op_rounds"] += 1
        # first engagement of your team in this round: were you in it?
        first_team = next((k for k in rnd.kills if team in (k.killer_team, k.victim_team)), None)
        if first_team and puuid in (first_team.killer, first_team.victim):
            row["first_in"][side] += 1
        if rnd.kills:
            k0 = rnd.kills[0]
            if k0.killer == puuid:
                loc = k0.loc_of(puuid)
                row["fk"] += 1
                row["openings"].append([side, _area(mi, loc.x, loc.y) if loc else "?", 1])
            elif k0.victim == puuid:
                row["fd"] += 1
                row["openings"].append([side, _area(mi, k0.victim_x, k0.victim_y), 0])
        dead: set[str] = set()
        for i, k in enumerate(rnd.kills):
            if k.killer == puuid:
                got_kill = True
                loc = k.loc_of(puuid)
                row["kills_at"].append([side, _area(mi, loc.x, loc.y) if loc else "?"])
                if (k.weapon or "").lower() == "operator":
                    row["op_kills"] += 1
                # trade: the victim had killed one of your teammates just before
                if any(p.killer == k.victim and p.victim_team == team and p.victim != puuid
                       and 0 <= k.t_round_ms - p.t_round_ms <= TRADE_MS for p in rnd.kills[:i]):
                    row["trade_kills"] += 1
                if loc:
                    near = _nearest_mate(k, puuid, team, dead, loc.x, loc.y)
                    row["iso"][side][0] += 1
                    if near is None or near > ISOLATED_UNITS:
                        row["iso"][side][1] += 1
                    if side == "defense" and mi is not None:
                        row["def_zones"].append(_zone(mi, loc.x, loc.y))
            if k.victim == puuid:
                near = _nearest_mate(k, puuid, team, dead, k.victim_x, k.victim_y)
                row["iso"][side][2] += 1
                if near is None or near > ISOLATED_UNITS:
                    row["iso"][side][3] += 1
                if side == "defense" and mi is not None:
                    row["def_zones"].append(_zone(mi, k.victim_x, k.victim_y))
            if puuid in k.assistants:
                assisted = True
            dead.add(k.victim)
        _late_round(row, match, rnd, puuid, team, opp, side)
        for di in death_infos(match, rnd, mi):
            if di.kill.victim == puuid:
                died = True
                traded = di.traded
                row["deaths_at"].append([side, _area(mi, di.kill.victim_x, di.kill.victim_y),
                                         int(di.traded), int(di.first_death)])
                row["traded_deaths"] += int(di.traded)
                break
        if got_kill or assisted or not died or traded:
            row["kast"] += 1
        if not died:
            row["survived"][side] += 1
    row["adr"] = round(dmg / n, 1)
    row["lobby"] = lobby_metrics(match)
    return row


def _late_round(row: dict, match: Match, rnd, puuid: str, team: str, opp: str, side: str) -> None:
    """Duel ranges, 1vX clutches, retakes and post-plants for one round."""
    won = rnd.winning_team == team
    for k in rnd.kills:
        if k.killer == puuid and k.victim:
            loc = k.loc_of(puuid)
            if loc:
                row["duels"].append([round(((loc.x - k.victim_x) ** 2 + (loc.y - k.victim_y) ** 2) ** 0.5 / 100), 1])
        elif k.victim == puuid and k.killer:
            loc = k.loc_of(k.killer)
            if loc:
                row["duels"].append([round(((loc.x - k.victim_x) ** 2 + (loc.y - k.victim_y) ** 2) ** 0.5 / 100), 0])
    alive = {team: {p.puuid for p in match.players_on(team)}, opp: {p.puuid for p in match.players_on(opp)}}
    my_death = None
    clutch = None
    for k in sorted(rnd.kills, key=lambda k: k.t_round_ms):
        for t in alive.values():
            t.discard(k.victim)
        if k.victim == puuid:
            my_death = k.t_round_ms
            break
        if clutch is None and alive[team] == {puuid} and alive[opp]:
            clutch = len(alive[opp])
    if clutch:
        c = row["clutch"].setdefault(str(clutch), [0, 0])
        c[0] += 1
        c[1] += int(won)
    if rnd.plant:
        alive_at_plant = my_death is None or my_death > rnd.plant.t_round_ms
        if alive_at_plant:
            key = "retake" if side == "defense" else "postplant"
            row[key][0] += 1
            row[key][1] += int(won)


def _zone(mi: MapInfo, x: float, y: float) -> str:
    try:
        return mi.zone(x, y)
    except Exception:
        return "?"


def _nearest_mate(k, puuid: str, team: str, dead: set[str], x: float, y: float) -> float | None:
    best = None
    for pl in k.player_locations:
        if pl.team == team and pl.puuid != puuid and pl.puuid not in dead and pl.puuid != k.victim:
            d = ((pl.x - x) ** 2 + (pl.y - y) ** 2) ** 0.5
            best = d if best is None else min(best, d)
    return best


def lobby_metrics(match: Match) -> list[list[float]]:
    """Per player of this match (all 10): [kills, assists, deaths, opening duels] per round.
    Lets your style be compared with the players at your level, not with fixed numbers."""
    n = len(match.rounds) or 1
    openings: dict[str, int] = {}
    for rnd in match.rounds:
        if rnd.kills:
            k0 = rnd.kills[0]
            for pu in (k0.killer, k0.victim):
                if pu:
                    openings[pu] = openings.get(pu, 0) + 1
    return [[round(p.kills / n, 3), round(p.assists / n, 3), round(p.deaths / n, 3),
             round(openings.get(p.puuid, 0) / n, 3)] for p in match.players.values()]


def row_from_stored(item: dict) -> dict | None:
    meta, st, teams = item.get("meta", {}) or {}, item.get("stats", {}) or {}, item.get("teams", {}) or {}
    team = (st.get("team") or "").lower()
    own, opp = teams.get(team), teams.get("blue" if team == "red" else "red")
    if not meta.get("id") or not isinstance(own, int) or not isinstance(opp, int) or own + opp == 0:
        return None
    agent = (st.get("character") or {}).get("name", "?")
    n = own + opp
    return {
        "match_id": meta["id"], "started_at": meta.get("started_at", ""), "queue": (meta.get("mode") or "").lower(),
        "map": (meta.get("map") or {}).get("name", "?"), "agent": agent, "role": roles.role_of(agent),
        "won": 1.0 if own > opp else (0.0 if own < opp else 0.5), "score": f"{own}-{opp}", "rounds": n,
        "kills": int(st.get("kills", 0) or 0), "deaths": int(st.get("deaths", 0) or 0),
        "assists": int(st.get("assists", 0) or 0), "acs": round(int(st.get("score", 0) or 0) / n, 1),
        "adr": round(int((st.get("damage") or {}).get("made", 0) or 0) / n, 1), "source": "stored",
        "puuid": st.get("puuid", ""),
    }


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
class GameStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except ValueError:
                pass
        return {"version": 1, "games": {}, "updated": "", "puuid": ""}

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)

    def rows(self) -> list[dict]:
        return sorted(self.load()["games"].values(), key=lambda r: r.get("started_at", ""), reverse=True)


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------
def import_games(client, region: str, platform: str, name: str, tag: str, store: GameStore,
                 cache_dir: Path, log: Log = lambda m: None, full_limit: int = 60,
                 stored_limit: int = 300, queues: tuple[str, ...] = QUEUES) -> dict:
    """Fetch history for one player. Incremental: stops paging once a page has nothing new.
    Returns counts {"full": n_new_full, "stored": n_new_stored, "total": n_rows}."""
    data = store.load()
    games: dict = data["games"]
    reg = MapRegistry(cache_dir)
    roles.load(cache_dir)
    map_cache: dict[str, MapInfo | None] = {}
    puuid = data.get("puuid", "")
    new_full = new_stored = 0

    def map_info(m: Match) -> MapInfo | None:
        if m.map_id not in map_cache:
            try:
                map_cache[m.map_id] = reg.get(m.map_id, m.map_name)
            except Exception:
                map_cache[m.map_id] = None
        return map_cache[m.map_id]

    # rows from an older version lack newer numbers: rebuild them from the cached match (no API call)
    cached = Path(cache_dir) / "matches"
    for mid, r in list(games.items()):
        if r.get("source") == "full" and r.get("v", 1) < ROW_VERSION and (cached / f"{mid}.json").exists():
            try:
                m = parse_match(json.loads((cached / f"{mid}.json").read_text()))
                me = m.find_player(name, tag) or (m.players.get(puuid) if puuid else None)
                if me is not None:
                    games[mid] = row_from_match(m, me.puuid, map_info(m)) or r
            except Exception:
                pass

    for q in queues:
        start = 0
        while start < full_limit:
            log(f"· {q}: loading recent matches {start + 1}–{start + 10} ...")
            page = client.match_history(region, platform, name, tag, mode=q, size=10, start=start)
            if not page:
                break
            fresh = 0
            for raw in page:
                mid = (raw.get("metadata") or {}).get("match_id")
                if not mid or (games.get(mid) or {}).get("source") == "full":
                    continue
                try:
                    m = parse_match({"data": raw})
                    me = m.find_player(name, tag) or (m.players.get(puuid) if puuid else None)
                    if me is None:
                        continue
                    puuid = me.puuid
                    row = row_from_match(m, me.puuid, map_info(m))
                except Exception as e:          # one odd match must not stop the import
                    log(f"  ! skipped {mid}: {e}")
                    continue
                if row:
                    games[mid] = row
                    fresh += 1
            new_full += fresh
            log(f"· {q}: {start + len(page)} recent matches checked, {new_full} new with full data")
            start += len(page)
            if len(page) < 10 or fresh == 0:
                break
        page_no = 1
        while (page_no - 1) * 20 < stored_limit:
            try:
                items, results = client.stored_matches(region, name, tag, mode=q, page=page_no, size=20)
            except Exception as e:
                log(f"  ! stored archive: {e}")
                break
            if not items:
                break
            fresh = 0
            seen_before = 0          # archive rows from an earlier import: we've reached old ground
            for it in items:
                row = row_from_stored(it)
                if row is None:
                    continue
                if row["match_id"] in games:
                    seen_before += games[row["match_id"]].get("source") == "stored"
                    continue
                if not puuid and row.get("puuid"):
                    puuid = row["puuid"]
                games[row["match_id"]] = row
                fresh += 1
            new_stored += fresh
            total = int(results.get("total") or 0)
            log(f"· {q}: archive page {page_no}, {new_stored} older matches added")
            if (fresh == 0 and seen_before) or (total and page_no * 20 >= total) or len(items) < 20:
                break
            page_no += 1
        data.update(games=games, puuid=puuid, updated=_now())
        store.save(data)
    return {"full": new_full, "stored": new_stored, "total": len(games)}
