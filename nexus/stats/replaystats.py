"""What the replay files show about each player (4.15): positions of all ten players, not just kill moments.

The match data only has everyone's position at the moment of a kill. A replay file (nexus/replayfile.py) has
every player twice a second for the whole round, so these numbers become measurable:

- **untradeable deaths**: when you died, no living teammate was within TRADE_M metres, and none got there in
  the next TRADE_S seconds. Nobody could have traded you, whatever they did.
- **retake arrival**: in defense rounds where the enemy planted while you were alive, how many seconds until
  you were within RETAKE_M metres of the spike (or "didn't get there").
- **setups**: where you stood SETUP_S seconds into the round (zone and callout), per map and side, and how
  many of those rounds your team won. The default you play, and which spot loses.

Each match is worked out once for all ten players and kept next to the replay as <match id>.metrics.json.
Utility timing isn't in the replay data Nexus reads; "died without using utility" comes from the match data
(stats/games.py, "no_util").
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from pathlib import Path

from .. import replayfile
from ..maps import MapRegistry
from ..parse import parse_match

VERSION = 1
UNITS_PER_M = 100.0
TRADE_M = 15.0
TRADE_S = 3.0
RETAKE_M = 12.0
SETUP_S = 20.0
log_ = logging.getLogger(__name__)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) / UNITS_PER_M


def _at(seq: list, t: float):
    return replayfile._at(seq, t)


def match_metrics(match, paths: dict[int, dict[str, list]], mi) -> dict[str, dict]:
    """puuid -> {deaths, untradeable, retakes: [[seconds or None]], setups: [[side, zone, area, won]]}."""
    out: dict[str, dict] = {p: {"deaths": 0, "untradeable": 0, "retakes": [], "setups": []} for p in match.players}
    for r in match.rounds:
        ps = paths.get(r.index)
        if not ps:
            continue
        for k in r.kills:
            me = k.victim
            if me not in ps or me not in out:
                continue
            t = k.t_round_ms / 1000
            team = match.team_of(me)
            spot = (k.victim_x, k.victim_y)
            mates = [p for p in ps if p != me and match.team_of(p) == team]
            near = False
            for dt in (0.0, 1.0, 2.0, TRADE_S):
                for m in mates:
                    pt = _at(ps[m], t + dt)
                    if pt is not None and _dist(pt, spot) <= TRADE_M:
                        near = True
                        break
                if near:
                    break
            out[me]["deaths"] += 1
            out[me]["untradeable"] += int(not near)
        # setups: where everyone stood SETUP_S into the round (before a plant)
        if mi is not None and (r.plant is None or r.plant.t_round_ms / 1000 > SETUP_S):
            for p, seq in ps.items():
                if p not in out:
                    continue
                pt = _at(seq, SETUP_S)
                if pt is None:
                    continue
                team = match.team_of(p)
                try:
                    zone, area = mi.zone(*pt), mi.area(*pt)
                except Exception:
                    continue
                out[p]["setups"].append([r.side_of(team), zone, area, int(r.winning_team == team)])
        # retakes: defenders alive at the plant, seconds until they reached the spike
        if r.plant is not None:
            tp = r.plant.t_round_ms / 1000
            spike = (r.plant.x, r.plant.y)
            for p, seq in ps.items():
                if p not in out or match.team_of(p) == r.plant.team or match.team_of(p) == "":
                    continue
                if not seq or seq[-1][0] < tp:          # dead before the plant
                    continue
                got = None
                for ts, x, y in seq:
                    if ts >= tp and _dist((x, y), spike) <= RETAKE_M:
                        got = round(ts - tp, 1)
                        break
                out[p]["retakes"].append(got)
    return out


def metrics_file(replays_dir: Path, match_id: str) -> Path:
    return replayfile._inside(Path(replays_dir), match_id, ".metrics.json")


def for_match(replays_dir: Path, cache_dir: Path, match_id: str, registry: MapRegistry | None = None) -> dict | None:
    """The metrics of one match (computed once, then read from <match id>.metrics.json), or None if the match
    has no replay file, isn't cached, or the replay doesn't line up."""
    try:
        f = metrics_file(replays_dir, match_id)
    except replayfile.ReplayError:
        return None
    if f.exists():
        try:
            d = json.loads(f.read_text())
            if d.get("v") == VERSION:
                return d
        except (OSError, ValueError):
            pass
    if not replayfile.has_replay(Path(replays_dir), match_id):
        return None
    cached = Path(cache_dir) / "matches" / f"{match_id}.json"
    if not cached.exists():
        return None
    try:
        match = parse_match(json.loads(cached.read_text()))
        data = replayfile.load(Path(replays_dir), match_id)
        if not data:
            return None
        offsets, q = replayfile.align(data, match)
        if not offsets or (q["kills"] and q["share"] < replayfile.MIN_MATCHED_SHARE):
            out = {"v": VERSION, "ok": False, "players": {}}
        else:
            reg = registry or MapRegistry(cache_dir)
            try:
                mi = reg.get(match.map_id, match.map_name)
            except Exception:
                mi = None
            paths = replayfile.round_paths(data, match, offsets)
            out = {"v": VERSION, "ok": True, "map": match.map_name, "players": match_metrics(match, paths, mi)}
    except Exception as e:                      # one odd replay must not break a stats page
        log_.warning("replay metrics for %s: %s", match_id, e)
        return None
    try:
        f.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def player(replays_dir: Path, cache_dir: Path, rows: list[dict], puuid: str) -> dict | None:
    """One player's numbers over all his games that have a replay file. None if none has."""
    if not puuid or not Path(replays_dir).exists():
        return None
    reg = None
    deaths = untr = 0
    retakes: list = []
    setups: dict[tuple, list] = defaultdict(lambda: [0, 0])
    areas: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    games = 0
    for r in rows:
        mid = str(r.get("match_id") or "").lower()
        if r.get("source") != "full" or not replayfile.has_replay(Path(replays_dir), mid):
            continue
        if reg is None:
            reg = MapRegistry(cache_dir)
        m = for_match(replays_dir, cache_dir, mid, reg)
        if not m or not m.get("ok"):
            continue
        me = (m.get("players") or {}).get(puuid)
        if not me:
            continue
        games += 1
        deaths += me["deaths"]
        untr += me["untradeable"]
        retakes += me["retakes"]
        for side, zone, area, won in me["setups"]:
            key = (r.get("map") or m.get("map") or "?", side, zone)
            setups[key][0] += 1
            setups[key][1] += won
            areas[key][area] += 1
    if not games:
        return None
    arrived = [x for x in retakes if x is not None]
    sets = []
    for (mp, side, zone), (n, won) in setups.items():
        top_area = max(areas[(mp, side, zone)].items(), key=lambda kv: kv[1])[0]
        sets.append({"map": mp, "side": side, "zone": zone, "area": top_area, "rounds": n, "won": won, "wr": won / n})
    sets.sort(key=lambda s: (s["map"], s["side"], -s["rounds"]))
    return {"games": games, "deaths": deaths, "untradeable": untr,
            "untradeable_share": untr / deaths if deaths else None,
            "retakes": len(retakes), "retake_arrived": len(arrived),
            "retake_s": round(sum(arrived) / len(arrived), 1) if arrived else None,
            "setups": sets}


def setup_notes(p: dict, min_rounds: int = 6) -> list[str]:
    """Plain lines for the coach: per map and side, the spot played most and spots that lose a lot."""
    out = []
    by: dict[tuple, list] = defaultdict(list)
    for s in p.get("setups") or []:
        by[(s["map"], s["side"])].append(s)
    for (mp, side), ss in sorted(by.items()):
        total = sum(s["rounds"] for s in ss)
        if total < min_rounds:
            continue
        main = max(ss, key=lambda s: s["rounds"])
        line = (f"{mp} {side}: at {int(SETUP_S)} s mostly {main['zone']} ({main['area']}) in {main['rounds']} of "
                f"{total} rounds, {main['wr']:.0%} won")
        bad = [s for s in ss if s["rounds"] >= min_rounds and s["wr"] <= 0.35 and s is not main]
        if bad:
            line += "; losing spot: " + ", ".join(f"{s['zone']} ({s['area']}) {s['won']}/{s['rounds']}" for s in bad)
        out.append(line)
    return out


def facts(p: dict | None) -> dict | None:
    """Compact block for the coach."""
    if not p:
        return None
    from .evidence import confidence
    out = {"games_with_replay": p["games"],
           "note": "from the game's replay files: positions of all ten players through the whole round"}
    if p["deaths"]:
        out["untradeable_deaths"] = (f"{p['untradeable_share']:.0%} of {p['deaths']} deaths: no teammate within "
                                     f"{int(TRADE_M)} m then or in the next {int(TRADE_S)} s "
                                     f"({confidence(p['deaths'], 60)})")
    if p["retakes"]:
        out["retake_arrival"] = (f"reached the spike in {p['retake_arrived']} of {p['retakes']} retake rounds"
                                 + (f", after {p['retake_s']} s on average" if p["retake_s"] is not None else "")
                                 + f" ({confidence(p['retakes'], 20)})")
    notes = setup_notes(p)
    if notes:
        out["setups"] = notes[:8]
    return out
