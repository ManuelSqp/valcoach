"""Data for the round replay on the minimap (drawn by the report's JavaScript).

Coordinates are 0..1 on the map image (valorant-api.com displayIcon).

Known positions come from the API at every kill, plant and defuse (all alive
players, incl. where they looked), plus, with a VOD, your own path and your
teammates' paths from the minimap, and enemies whenever they were spotted.
Everyone starts in their spawn. Between two known positions a player's movement
is estimated as the shortest walkable route on the map image (see nav.py), at
running speed: they leave spawn right away, and between two later positions
they hold the first one and move just in time to reach the next. Those points
are marked as estimates so the replay can draw them faded.
"""
from __future__ import annotations

import base64
import math

from ..analysis.core import fmt_ms
from ..analysis.view import ViewModel
from ..maps import AgentRegistry, MapInfo, MapRegistry
from ..models import Match, PlayerLoc, Round
from .nav import NavGrid, path_length

CONE_UNITS = 400          # world units used to turn a view direction into a map angle
END_PAD_MS = 4000         # show a few seconds after the last event
RUN_UNITS_S = 540         # running with a rifle, world units (cm) per second
KNOWN, ESTIMATE, SPAWN = 1, 0, 2


def _uv(mi: MapInfo, x: float, y: float) -> list[float]:
    u, v = mi.to_uv(x, y)
    return [round(u, 4), round(v, 4)]


def _angle(mi: MapInfo, vm: ViewModel, pl: PlayerLoc) -> float | None:
    """Look direction as an angle on the map image (radians, atan2 in image coords)."""
    if not vm.ok:
        return None
    dx, dy = vm.world_dir(pl.view)
    u0, v0 = mi.to_uv(pl.x, pl.y)
    u1, v1 = mi.to_uv(pl.x + dx * CONE_UNITS, pl.y + dy * CONE_UNITS)
    return round(math.atan2(v1 - v0, u1 - u0), 3)


def spawns(mi: MapInfo) -> dict[str, list[float]]:
    out = {}
    for c in mi.callouts:
        if c.region.lower() == "spawn":
            if "attack" in c.super_region.lower():
                out["attack"] = _uv(mi, c.x, c.y)
            elif "defend" in c.super_region.lower():
                out["defense"] = _uv(mi, c.x, c.y)
    return out


def map_meta(mi: MapInfo | None, registry: MapRegistry | None = None, embed_image: bool = True) -> dict | None:
    if mi is None:
        return None
    seen, callouts = set(), []
    for c in mi.callouts:
        if c.label in seen:
            continue
        seen.add(c.label)
        callouts.append({"label": c.label, "p": _uv(mi, c.x, c.y)})
    image = ""
    if embed_image and registry is not None:
        try:
            p = registry.minimap_image(mi)
            if p and p.exists():
                image = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
        except Exception:
            image = ""          # offline: the replay draws callout labels on a plain background
    if not image and mi.display_icon:
        image = mi.display_icon  # fall back to loading it from valorant-api.com in the browser
    return {"name": mi.name, "image": image, "callouts": callouts}


def nav_grid(mi: MapInfo | None, registry: MapRegistry | None) -> NavGrid | None:
    """Walkable grid for this map, or None (then movement is drawn as straight lines)."""
    if mi is None or registry is None:
        return None
    try:
        return NavGrid.from_image(registry.minimap_image(mi))
    except Exception:          # no map image, offline, or OpenCV not usable: straight lines
        return None


def agent_icons(match: Match, registry: AgentRegistry | None) -> dict[str, str]:
    """Agent name -> icon (embedded PNG, or the valorant-api.com URL if it can't be downloaded).
    Agents without an icon are left out; the replay draws a plain dot for them."""
    out: dict[str, str] = {}
    if registry is None:
        return out
    try:
        registry.load()
    except Exception:
        return out                      # offline and nothing cached: plain dots
    for p in match.players.values():
        if p.agent in out:
            continue
        a = registry.find(p.agent_id, p.agent)
        if a is None:
            continue
        try:
            f = registry.icon_file(a)
            if f and f.exists():
                out[p.agent] = "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()
                continue
        except Exception:
            pass
        if a.get("icon"):
            out[p.agent] = a["icon"]
    return out


# ---------------------------------------------------------------------------
def _track(known: list[tuple[int, list[float], int]], nav: NavGrid | None,
           uv_per_ms: float | None = None) -> list[list]:
    """known: [(t_ms, [u, v], kind)] sorted -> [[t, u, v, kind], ...] with estimated route points between.

    With uv_per_ms (running speed on the map image) a gap that is longer than the
    walk is filled realistically: from spawn the player moves first and then waits;
    otherwise they hold the earlier position and move just in time. Without it the
    movement is spread evenly over the gap."""
    out: list[list] = []
    for i, (t, p, kind) in enumerate(known):
        if i > 0:
            t0, p0, k0 = known[i - 1]
            dt = t - t0
            far = math.hypot(p[0] - p0[0], p[1] - p0[1]) > 0.02
            if far and dt > 600:
                route = nav.route((p0[0], p0[1]), (p[0], p[1])) if nav is not None else None
                if not route or len(route) < 2:
                    route = [(p0[0], p0[1]), (p[0], p[1])]
                total = path_length(route)
                walk = total / uv_per_ms if uv_per_ms and total > 0 else dt
                walk = min(dt, walk)
                if k0 == SPAWN:
                    m0 = t0                         # leave spawn at once, then wait
                else:
                    m0 = t - walk                   # hold, then move just in time
                    if m0 - t0 > 300:
                        out.append([round(m0), round(p0[0], 3), round(p0[1], 3), ESTIMATE])
                if total > 0:
                    acc = 0.0
                    for a, b in zip(route[:-1], route[1:]):
                        acc += math.hypot(b[0] - a[0], b[1] - a[1])
                        if b is route[-1]:
                            break
                        out.append([round(m0 + walk * acc / total), round(b[0], 3), round(b[1], 3), ESTIMATE])
                if k0 == SPAWN and t - (m0 + walk) > 300:
                    out.append([round(m0 + walk), round(p[0], 3), round(p[1], 3), ESTIMATE])
        out.append([int(t), round(p[0], 3), round(p[1], 3), kind])
    return out


def build_replay(match: Match, rnd: Round, focus: str, mi: MapInfo | None, vm: ViewModel,
                 self_path: list | None = None, nav: NavGrid | None = None,
                 others: dict | None = None) -> dict | None:
    if mi is None:
        return None
    team = match.team_of(focus)
    ids: dict[str, str] = {}

    def pid(puuid: str) -> str:
        if puuid not in ids:
            ids[puuid] = f"p{len(ids)}"
        return ids[puuid]

    for p in sorted(match.players.values(), key=lambda p: (p.team != team, p.puuid != focus, p.name.lower())):
        pid(p.puuid)                                  # stable ids: you, your team, then enemies

    known: dict[str, list] = {pu: [] for pu in ids}
    deaths: dict[str, int] = {}

    def players(locs: list[PlayerLoc], t: int, extra: tuple[str, float, float] | None = None) -> list[dict]:
        out, seen = [], set()
        for pl in locs:
            if pl.puuid not in ids:
                continue
            seen.add(pl.puuid)
            p = _uv(mi, pl.x, pl.y)
            known[pl.puuid].append((t, p, KNOWN))
            out.append({"id": pid(pl.puuid), "p": p, "a": _angle(mi, vm, pl)})
        if extra and extra[0] in ids and extra[0] not in seen:   # victim not listed: kill spot
            p = _uv(mi, extra[1], extra[2])
            known[extra[0]].append((t, p, KNOWN))
            out.append({"id": pid(extra[0]), "p": p, "a": None})
        return out

    events = []
    for i, k in enumerate(rnd.kills):
        killer_loc = k.loc_of(k.killer) if k.killer else None
        events.append({
            "kind": "kill", "t": k.t_round_ms, "time": fmt_ms(k.t_round_ms),
            "killer": pid(k.killer) if k.killer in ids else None, "victim": pid(k.victim),
            "from": _uv(mi, killer_loc.x, killer_loc.y) if killer_loc else None,
            "to": _uv(mi, k.victim_x, k.victim_y),
            "ours": k.killer_team == team, "weapon": k.weapon or "ability", "first": i == 0,
            "players": players(k.player_locations, k.t_round_ms, (k.victim, k.victim_x, k.victim_y)),
        })
        if k.victim in ids and k.victim not in deaths:
            deaths[k.victim] = k.t_round_ms
    for ev in (rnd.plant, rnd.defuse):
        if ev is None:
            continue
        if ev.player in ids:
            known[ev.player].append((ev.t_round_ms, _uv(mi, ev.x, ev.y), KNOWN))
        events.append({
            "kind": ev.kind, "t": ev.t_round_ms, "time": fmt_ms(ev.t_round_ms),
            "by": pid(ev.player) if ev.player in ids else None, "site": ev.site,
            "spot": _uv(mi, ev.x, ev.y),
            "players": players(ev.player_locations, ev.t_round_ms) if ev.player_locations else None,
        })
    events.sort(key=lambda e: e["t"])
    last = []
    for e in events:            # a plant/defuse without its own snapshot shows the step before
        if e["players"] is None:
            e["players"] = last
        last = e["players"]

    # your own path from the VOD is measured, so it counts as known
    path = []
    for t, x, y in (self_path or []):
        u = _uv(mi, x, y)
        path.append([round(t, 1), *u])
        if focus in known and (focus not in deaths or t * 1000 <= deaths[focus]):
            known[focus].append((int(t * 1000), u, KNOWN))

    # teammates measured on your minimap (VOD); identities checked against the kill snapshots
    others = others or {}
    measured = []
    for puuid, pts in (others.get("allies") or {}).items():
        if puuid not in known:
            continue
        measured.append(pid(puuid))
        for t, x, y in pts:
            if puuid not in deaths or t * 1000 <= deaths[puuid]:
                known[puuid].append((int(t * 1000), _uv(mi, x, y), KNOWN))
    seen = [[int(t * 1000), *_uv(mi, x, y)] for t, x, y in (others.get("enemies") or [])]

    sp = spawns(mi)
    uv_per_ms = abs(mi.x_mult) * RUN_UNITS_S / 1000 if mi.x_mult else None
    end = max([e["t"] for e in events] + [int(p[0] * 1000) for p in path] + [0]) + END_PAD_MS
    tracks = {}
    for puuid, short in ids.items():
        pts = sorted(known[puuid], key=lambda x: x[0])
        if puuid in deaths:
            pts = [p for p in pts if p[0] <= deaths[puuid]]
        dedup = []
        for p in pts:
            if dedup and p[0] - dedup[-1][0] < 50:
                continue
            dedup.append(p)
        side = rnd.side_of(match.team_of(puuid))
        if side in sp and (not dedup or dedup[0][0] > 0):
            dedup.insert(0, (0, sp[side], SPAWN))
        if not dedup:
            continue
        tracks[short] = {"pts": _track(dedup, nav, uv_per_ms), "death": deaths.get(puuid)}

    roster = {}
    for puuid, short in ids.items():
        p = match.players.get(puuid)
        roster[short] = {
            "name": p.name if p else "?", "agent": p.agent if p else "?",
            "us": (p.team == team) if p else False, "you": puuid == focus,
        }
    return {"events": events, "roster": roster, "tracks": tracks, "path": path, "end": end,
            "attack": rnd.side_of(team) == "attack", "view": vm.ok, "routes": nav is not None,
            "measured": sorted(measured), "seen": seen}
