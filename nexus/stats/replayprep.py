"""Opponent prep from replay files (4.18): how a team sets up, where its utility goes and where it plants.

A replay file has every player twice a second and every smoke, wall, molly and recon with its spot and time
(nexus/replayfile.py). Per stored match one small extract is worked out once for both teams and kept next to
the replay as <match id>.prep.json:

  rounds: [{n, team, side, won, plant: site or "", at: {"10": [[agent, zone, area, u, v], ...], "20": ...},
            util: [[type, agent, slot, t0 s, zone, area, u, v], ...]}]   (one entry per team and round)

analyse() then sums those extracts for one roster (any team: an opponent you faced, or your own team) per
map and side: the usual setup (how many players in which zone, e.g. "A 2 · Mid 1 · B 2"), the spots taken
most at that moment, the utility thrown most (type, place, median time) and where they plant.

  opponents(...)   the enemy rosters in the stored replays of a team, grouped by shared players
  analyse(...)     the tendencies of one roster
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from .. import replayfile
from ..maps import MapRegistry
from ..parse import parse_match

VERSION = 1
TIMES = (10, 20, 30, 45)           # seconds into the round at which positions are kept
UTIL_UNTIL_S = 100                 # utility after this (late post-plant / retake) is left out
SHOWN_TYPES = ("smoke", "wall", "slow", "damage", "trap", "recon", "orb", "flash")
log_ = logging.getLogger(__name__)


def prep_file(replays_dir: Path, match_id: str) -> Path:
    return replayfile._inside(Path(replays_dir), match_id, ".prep.json")


def _uv(mi, x: float, y: float) -> list[float]:
    u, v = mi.to_uv(x, y)
    return [round(u * 1000), round(v * 1000)]


def extract(match, data: dict, mi, agent_names: dict[str, str] | None = None) -> dict:
    """The extract of one match (both teams). data = the replay file's compact data."""
    offsets, q = replayfile.align(data, match)
    if not offsets or (q["kills"] and q["share"] < replayfile.MIN_MATCHED_SHARE):
        return {"v": VERSION, "ok": False}
    paths = replayfile.round_paths(data, match, offsets)
    effects = replayfile.round_effects(data, match, offsets, agent_names)
    agent = {p.puuid: p.agent for p in match.players.values()}
    out = []
    for r in match.rounds:
        ps = paths.get(r.index) or {}
        if not ps:
            continue
        for team in sorted({p.team for p in match.players.values() if p.team}):
            side = r.side_of(team)
            e = {"n": r.number, "team": team, "side": side, "won": int(r.winning_team == team),
                 "plant": (r.plant.site or "?") if r.plant and r.plant.team == team else "", "at": {}, "util": []}
            plant_s = r.plant.t_round_ms / 1000 if r.plant else None
            for t in TIMES:
                if plant_s is not None and plant_s <= t:
                    continue                      # after the plant it isn't a setup any more
                pts = []
                for pu, seq in ps.items():
                    if match.team_of(pu) != team:
                        continue
                    pt = replayfile._at(seq, t)
                    if pt is None:
                        continue
                    try:
                        zone, area = mi.zone(*pt), mi.area(*pt)
                    except Exception:
                        continue
                    pts.append([agent.get(pu, "?"), zone, area, *_uv(mi, *pt)])
                if pts:
                    e["at"][str(t)] = pts
            for f in effects.get(r.index) or []:
                if not f.get("owner") or match.team_of(f["owner"]) != team:
                    continue
                t0 = f["t0"] / 1000
                if t0 > UTIL_UNTIL_S or f["type"] not in SHOWN_TYPES:
                    continue
                try:
                    zone, area = mi.zone(f["x"], f["y"]), mi.area(f["x"], f["y"])
                except Exception:
                    continue
                e["util"].append([f["type"], f.get("agent") or "", f.get("slot") or "", round(max(0.0, t0), 1),
                                  zone, area, *_uv(mi, f["x"], f["y"])])
            out.append(e)
    roster = {p.puuid: {"name": p.name, "team": p.team, "agent": p.agent} for p in match.players.values()}
    return {"v": VERSION, "ok": True, "map": match.map_name, "started_at": match.started_at, "roster": roster,
            "rounds": out}


def for_match(replays_dir: Path, cache_dir: Path, match_id: str, registry: MapRegistry | None = None,
              agent_names: dict[str, str] | None = None) -> dict | None:
    """The extract of one stored match (worked out once), or None."""
    try:
        f = prep_file(replays_dir, match_id)
    except replayfile.ReplayError:
        return None
    if f.exists():
        try:
            d = json.loads(f.read_text())
            if d.get("v") == VERSION:
                return d
        except (OSError, ValueError):
            pass
    cached = Path(cache_dir) / "matches" / f"{match_id}.json"
    if not cached.exists() or not replayfile.has_replay(Path(replays_dir), match_id):
        return None
    try:
        match = parse_match(json.loads(cached.read_text()))
        data = replayfile.load(Path(replays_dir), match_id)
        if not data:
            return None
        reg = registry or MapRegistry(cache_dir)
        mi = reg.get(match.map_id, match.map_name)
        if mi is None:
            return None
        out = extract(match, data, mi, agent_names)
    except Exception as e:                 # one odd replay must not break the page
        log_.warning("replay prep for %s: %s", match_id, e)
        return None
    try:
        f.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def _key(puuids) -> str:
    """A short, stable id for a roster in the page's URL (not a secret)."""
    return hashlib.sha256(",".join(sorted(puuids)).encode()).hexdigest()[:12]


def opponents(extracts: dict[str, dict], ours: set[str], labels: dict[str, str] | None = None) -> list[dict]:
    """Enemy rosters in matches where 2+ of ours played, grouped when they share 3+ players (the same team
    met again, or scrims). -> [{key, label, puuids, matches: [match ids], maps}], most matches first.
    labels: match id -> a known opponent name (Premier reviews)."""
    groups: list[dict] = []
    for mid, ex in sorted(extracts.items(), key=lambda kv: kv[1].get("started_at") or ""):
        roster = ex.get("roster") or {}
        teams: dict[str, set] = defaultdict(set)
        for pu, p in roster.items():
            teams[p["team"]].add(pu)
        mine = [t for t, ps in teams.items() if len(ps & ours) >= 2]
        if len(mine) != 1:
            continue
        them = next((ps for t, ps in teams.items() if t != mine[0]), set())
        if not them:
            continue
        g = next((x for x in groups if len(x["puuids"] & them) >= 3), None)
        if g is None:
            g = {"puuids": set(), "matches": [], "maps": Counter(), "names": {}, "label": ""}
            groups.append(g)
        g["puuids"] |= them
        g["matches"].append(mid)
        g["maps"][ex.get("map") or "?"] += 1
        for pu in them:
            g["names"][pu] = roster[pu]["name"]
        if labels and labels.get(mid):
            g["label"] = labels[mid]
    out = []
    for g in groups:
        names = sorted(g["names"].values(), key=str.lower)
        out.append({"key": _key(g["puuids"]), "label": g["label"] or ", ".join(names[:3]) + ("…" if len(names) > 3 else ""),
                    "puuids": sorted(g["puuids"]), "names": names, "matches": g["matches"], "maps": dict(g["maps"])})
    out.sort(key=lambda g: (-len(g["matches"]), g["label"].lower()))
    return out


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[len(s) // 2]


def analyse(extracts: dict[str, dict], puuids: set[str], at: int = 20) -> dict:
    """Tendencies of the roster puuids (2+ of them in a team) per map and side:
    {map: {side: {rounds, won, setups: [[pattern, n]], spots: [...], util: [...], plants: [[site, n]],
    points: [[agent, u, v]], util_points: [[type, agent, slot, u, v, t]]}}}"""
    key = str(at if at in TIMES else 20)
    out: dict = {}
    for mid, ex in extracts.items():
        roster = ex.get("roster") or {}
        teams: dict[str, set] = defaultdict(set)
        for pu, p in roster.items():
            teams[p["team"]].add(pu)
        team = next((t for t, ps in teams.items() if len(ps & puuids) >= 2), None)
        if team is None:
            continue
        mp = out.setdefault(ex.get("map") or "?", {"matches": 0})
        mp["matches"] += 1
        for e in ex.get("rounds") or []:
            if e["team"] != team:
                continue
            s = mp.setdefault(e["side"], {"rounds": 0, "won": 0, "patterns": Counter(), "spots": defaultdict(lambda: [0, 0, Counter(), 0]),
                                          "util": defaultdict(lambda: [0, [], Counter()]), "plants": Counter(), "points": [],
                                          "util_points": [], "with_pos": 0})
            s["rounds"] += 1
            s["won"] += e["won"]
            if e["side"] == "attack":
                s["plants"][e["plant"] or "no plant"] += 1
            pts = (e.get("at") or {}).get(key) or []
            if pts:
                s["with_pos"] += 1
                zones = Counter(p[1] for p in pts)
                s["patterns"][" · ".join(f"{z} {n}" for z, n in sorted(zones.items()))] += 1
                here: Counter = Counter()
                for ag, zone, area, u, v in pts:
                    here[(zone, area)] += 1
                    s["spots"][(zone, area)][2][ag] += 1
                    s["points"].append([ag, u, v])
                for k, c in here.items():          # rounds with someone there (and how many players in all)
                    sp = s["spots"][k]
                    sp[0] += 1
                    sp[1] += e["won"]
                    sp[3] += c
            for typ, ag, slot, t0, zone, area, u, v in e.get("util") or []:
                k = s["util"][(typ, zone, area)]
                k[0] += 1
                k[1].append(t0)
                k[2][ag] += 1
                s["util_points"].append([typ, ag, slot, u, v, t0])
    for mp in out.values():
        for side in ("attack", "defense"):
            s = mp.get(side)
            if not s:
                continue
            n = s["with_pos"] or 1
            s["setups"] = [[p, c] for p, c in s.pop("patterns").most_common(4)]
            s["spots"] = sorted(({"zone": z, "area": a, "n": v[0], "share": v[0] / n, "won": v[1],
                                  "players": round(v[3] / v[0], 1) if v[0] else 0,
                                  "agents": [x for x, _ in v[2].most_common(2)]} for (z, a), v in s["spots"].items()),
                                key=lambda x: -x["n"])[:8]
            s["util"] = sorted(({"type": t, "zone": z, "area": a, "n": v[0], "share": v[0] / (s["rounds"] or 1),
                                 "t": _median(v[1]), "agents": [x for x, _ in v[2].most_common(2)]}
                                for (t, z, a), v in s["util"].items()), key=lambda x: -x["n"])[:10]
            s["plants"] = [[k, c] for k, c in s["plants"].most_common()]
    return out


def facts(d: dict, name: str = "") -> dict:
    """One map of analyse() as a compact block for the model (4.19 counter-plans)."""
    out: dict = {"team": name, "matches_with_replay": d.get("matches", 0),
                 "note": "from replay files: positions twice a second, every smoke / wall / molly / recon with spot and time"}
    for side in ("attack", "defense"):
        s = d.get(side)
        if not s or not s["rounds"]:
            continue
        out[f"when_they_{side}"] = {
            "rounds": s["rounds"], "won": s["won"],
            "setup_20s": [f"{p} in {c} of {s['with_pos']} rounds" for p, c in s["setups"][:3]],
            "spots_taken": [f"{x['area']} ({x['zone']}) in {x['share']:.0%} of rounds" + (f" by {', '.join(x['agents'])}" if x["agents"] else "")
                            for x in s["spots"][:6]],
            "utility": [f"{x['type']} at {x['area']} in {x['n']} of {s['rounds']} rounds, around {int(x['t'] or 0)} s"
                        + (f" ({', '.join(x['agents'])})" if x["agents"] else "") for x in s["util"][:8]],
            **({"plants": [f"{site}: {c}" for site, c in s["plants"]]} if side == "attack" else {}),
        }
    return out


def hints(a: dict, min_rounds: int = 5) -> list[str]:
    """Plain lines per map and side (enough rounds only)."""
    out = []
    for mp, d in sorted(a.items()):
        for side in ("defense", "attack"):
            s = d.get(side)
            if not s or s["rounds"] < min_rounds:
                continue
            if s["setups"]:
                p, c = s["setups"][0]
                out.append(f"{mp} {side}: usually {p} ({c} of {s['with_pos']} rounds)")
            u = next((x for x in s["util"] if x["type"] == "smoke" and x["n"] >= 3), None)
            if u:
                out.append(f"{mp} {side}: smoke at {u['area']} in {u['n']} of {s['rounds']} rounds, around {int(u['t'] or 0)} s in")
            if side == "attack" and s["plants"]:
                site, c = s["plants"][0]
                if site != "no plant":
                    out.append(f"{mp} attack: planted {site} in {c} of {s['rounds']} rounds")
    return out
