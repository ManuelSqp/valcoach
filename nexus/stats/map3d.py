"""3D maps (4.35): a walkable map rebuilt from replay files, not from the game's files.

Every replay holds every player's position, height included, ten times a second (replayfile.py). Every spot
someone stood on is floor at that height; where nobody ever stood is a wall, a box or outside the map. Nexus puts
all positions of a map from all replays on the server on a grid (half a metre per cell), keeps one or more floor
heights per cell (Heaven above Market, a ramp, a box you can stand on), fills the gaps between paths that are close
together, and the page (static/map3d.js) builds floors and walls from that. Callouts (valorant-api.com) name the
areas; their colours come from a palette per map.

The more replays of a map, the more complete it is: one match covers the paths people take, not every corner.
Everything is in metres in the minimap's frame: x to the right and z down on the minimap, y up.

Stored per map in data/maps3d/<map>.json, rebuilt when the set of replays changes."""
from __future__ import annotations

import gzip
import json
import math
import statistics
from pathlib import Path

CELL = 0.5                 # metres per grid cell
FOOT_CM = 0.0              # replay z minus this = the floor (tuned on real replays; the capsule's centre may need ~90)
LEVEL_GAP = 1.6            # two floors in one cell need this much height between them (Heaven over Market)
STEP_FILL = 0.6            # gap filling only between cells this close in height
PATH_GAP = 3.0             # consecutive samples further apart than this (m) aren't joined into a path
SPREAD = 1                 # cells added around every path (a player is about 0.6 m wide)
FILL = 4                   # cells: a gap this narrow between two walkable cells of the same height is filled
VERSION = 1

PALETTES = {               # per map: base, then site / mid / attacker / defender tints (r, g, b 0..1)
    "Ascent": [(0.72, 0.64, 0.52), (0.80, 0.62, 0.42), (0.66, 0.70, 0.60), (0.75, 0.58, 0.50), (0.62, 0.62, 0.70)],
    "Bind": [(0.74, 0.62, 0.46), (0.82, 0.58, 0.38), (0.70, 0.66, 0.52), (0.78, 0.56, 0.44), (0.60, 0.64, 0.62)],
    "Haven": [(0.66, 0.62, 0.56), (0.74, 0.56, 0.44), (0.60, 0.66, 0.58), (0.70, 0.56, 0.50), (0.58, 0.62, 0.66)],
    "Split": [(0.60, 0.62, 0.66), (0.70, 0.54, 0.50), (0.56, 0.64, 0.60), (0.66, 0.56, 0.58), (0.54, 0.60, 0.70)],
    "Icebox": [(0.80, 0.84, 0.88), (0.62, 0.74, 0.86), (0.74, 0.80, 0.82), (0.84, 0.72, 0.66), (0.60, 0.70, 0.84)],
    "Breeze": [(0.82, 0.76, 0.60), (0.64, 0.80, 0.74), (0.78, 0.74, 0.58), (0.84, 0.66, 0.52), (0.58, 0.74, 0.78)],
    "Fracture": [(0.62, 0.58, 0.54), (0.72, 0.52, 0.42), (0.56, 0.62, 0.60), (0.70, 0.50, 0.48), (0.52, 0.58, 0.66)],
    "Pearl": [(0.58, 0.64, 0.70), (0.52, 0.70, 0.74), (0.62, 0.64, 0.62), (0.70, 0.60, 0.56), (0.50, 0.60, 0.74)],
    "Lotus": [(0.62, 0.70, 0.56), (0.70, 0.62, 0.46), (0.56, 0.70, 0.62), (0.72, 0.58, 0.50), (0.52, 0.64, 0.66)],
    "Sunset": [(0.80, 0.66, 0.54), (0.86, 0.60, 0.44), (0.74, 0.68, 0.60), (0.84, 0.58, 0.52), (0.62, 0.62, 0.70)],
    "Abyss": [(0.54, 0.58, 0.64), (0.60, 0.52, 0.66), (0.52, 0.60, 0.62), (0.64, 0.52, 0.54), (0.48, 0.56, 0.68)],
}
DEFAULT_PALETTE = [(0.66, 0.66, 0.66), (0.74, 0.60, 0.48), (0.62, 0.68, 0.62), (0.72, 0.58, 0.54), (0.58, 0.62, 0.70)]


def area_kind(super_region: str) -> int:
    """Palette slot of a callout's area: 1 site, 2 mid, 3 attacker side, 4 defender side, 0 anything else."""
    s = (super_region or "").lower()
    if s in ("a", "b", "c"):
        return 1
    if s == "mid":
        return 2
    if "attacker" in s:
        return 3
    if "defender" in s:
        return 4
    return 0


class Frame:
    """World (cm, as in replays and callouts) -> metres in the minimap's frame."""
    def __init__(self, mi):
        self.mi = mi
        self.per_m = abs(mi.x_mult) * 100 or 0.007     # minimap units per metre

    def to_m(self, x: float, y: float) -> tuple[float, float]:
        u, v = self.mi.to_uv(x, y)
        return u / self.per_m, v / self.per_m


def rebuild(mi, replays: list[dict], name: str = "") -> dict:
    """The walkable grid of a map from replays (compact replay data, replayfile.py) and its callouts."""
    fr = Frame(mi)
    heights: dict[tuple[int, int], list[float]] = {}
    n = 0
    # the hot loop (millions of samples): Frame.to_m and the cell lookup inlined, same arithmetic
    xm, xa, ym, ya, per_m = mi.x_mult, mi.x_add, mi.y_mult, mi.y_add, fr.per_m
    floor, hypot, get = math.floor, math.hypot, heights.get
    step_m = CELL * 0.7

    def put(mx: float, mz: float, h: float) -> None:
        key = (floor(mx / CELL), floor(mz / CELL))
        lst = get(key)
        if lst is None:
            heights[key] = [h]
        else:
            lst.append(h)

    for rep in replays:
        for pts in (rep.get("pos") or {}).values():
            pt = px = pz = ph = None
            for p in pts:
                t, x, y = p[0], p[1], p[2]
                z = p[3] if len(p) > 3 else 0.0
                mx, mz = (y * xm + xa) / per_m, (x * ym + ya) / per_m
                h = ((z or 0.0) - FOOT_CM) / 100
                key = (floor(mx / CELL), floor(mz / CELL))
                lst = get(key)
                if lst is None:
                    heights[key] = [h]
                else:
                    lst.append(h)
                n += 1
                if pt is not None:                       # the path between two samples
                    d = hypot(mx - px, mz - pz)
                    if 0 < d <= PATH_GAP and t - pt <= 400 and abs(h - ph) < 1.0:
                        steps = int(d / step_m)
                        for k in range(1, steps):
                            f = k / steps
                            put(px + (mx - px) * f, pz + (mz - pz) * f, ph + (h - ph) * f)
                pt, px, pz, ph = t, mx, mz, h
    levels = {c: _levels(hs) for c, hs in heights.items()}
    _spread(levels)
    _fill(levels)
    # callouts at their floor
    callouts = []
    seen = set()
    for c in mi.callouts:
        if c.label in seen:
            continue
        seen.add(c.label)
        mx, mz = fr.to_m(c.x, c.y)
        lv = levels.get((math.floor(mx / CELL), math.floor(mz / CELL)))
        callouts.append({"label": c.label, "x": round(mx, 2), "z": round(mz, 2), "y": round(min(lv), 2) if lv else None,
                         "kind": area_kind(c.super_region)})
    # every floor cell gets the area of its nearest callout
    named = [(c["x"], c["z"], c["kind"]) for c in callouts]
    cells = []
    for (i, j), lv in sorted(levels.items()):
        cx, cz = (i + 0.5) * CELL, (j + 0.5) * CELL
        kind = min(named, key=lambda a: (a[0] - cx) ** 2 + (a[1] - cz) ** 2)[2] if named else 0
        for h in lv:
            cells.append([i, j, round(h, 2), kind])
    start = _start(levels, callouts)
    return {"version": VERSION, "map": name or mi.name, "cell": CELL, "cells": cells, "callouts": callouts,
            "palette": PALETTES.get(name or mi.name, DEFAULT_PALETTE), "start": start, "samples": n,
            "matches": len(replays), "per_m": fr.per_m}


def _levels(hs: list[float]) -> list[float]:
    """The floor heights in one cell: samples grouped by LEVEL_GAP, each group's lower quarter (jumps sit above)."""
    hs = sorted(hs)
    groups, cur = [], [hs[0]]
    for h in hs[1:]:
        if h - cur[-1] > LEVEL_GAP:
            groups.append(cur)
            cur = [h]
        else:
            cur.append(h)
    groups.append(cur)
    return [g[len(g) // 4] if len(g) >= 4 else g[0] for g in groups]


def _near(lv: list[float], h: float) -> float | None:
    best = min(lv, key=lambda x: abs(x - h)) if lv else None
    return best if best is not None and abs(best - h) <= STEP_FILL else None


def _spread(levels: dict) -> None:
    """Widen every path by SPREAD cells (same height): a player is wider than the line through his centre."""
    add: dict = {}
    for (i, j), lv in levels.items():
        for di in range(-SPREAD, SPREAD + 1):
            for dj in range(-SPREAD, SPREAD + 1):
                c = (i + di, j + dj)
                if c in levels:
                    continue
                for h in lv:
                    add.setdefault(c, []).append(h)
    for c, hs in add.items():
        levels[c] = _levels(hs)


def _fill(levels: dict) -> None:
    """Fill gaps up to FILL cells wide between two walkable cells of about the same height on opposite sides
    (both sides of a corridor walked at different places)."""
    dirs = [(1, 0), (0, 1), (1, 1), (1, -1)]
    add: dict = {}
    keys = list(levels)
    lo_i, hi_i = min(k[0] for k in keys), max(k[0] for k in keys)
    lo_j, hi_j = min(k[1] for k in keys), max(k[1] for k in keys)
    for i in range(lo_i, hi_i + 1):
        for j in range(lo_j, hi_j + 1):
            if (i, j) in levels:
                continue
            for di, dj in dirs:
                a = b = None
                for k in range(1, FILL + 1):
                    if a is None and (i + di * k, j + dj * k) in levels:
                        a = levels[(i + di * k, j + dj * k)]
                    if b is None and (i - di * k, j - dj * k) in levels:
                        b = levels[(i - di * k, j - dj * k)]
                if a and b:
                    for h in a:
                        m = _near(b, h)
                        if m is not None:
                            add.setdefault((i, j), []).append((h + m) / 2)
                    if (i, j) in add:
                        break
    for c, hs in add.items():
        levels[c] = _levels(hs)


def _start(levels: dict, callouts: list[dict]) -> list[float]:
    """Where you start: at the attacker spawn if the map has one, else the most central floor cell."""
    spawn = next((c for c in callouts if c["kind"] == 3 and "spawn" in c["label"].lower()), None)
    if spawn and spawn["y"] is not None:
        return [spawn["x"], spawn["y"], spawn["z"]]
    if not levels:
        return [0.0, 0.0, 0.0]
    xs = statistics.median(i for i, _ in levels)
    zs = statistics.median(j for _, j in levels)
    c = min(levels, key=lambda k: (k[0] - xs) ** 2 + (k[1] - zs) ** 2)
    return [round((c[0] + 0.5) * CELL, 2), round(min(levels[c]), 2), round((c[1] + 0.5) * CELL, 2)]


def replays_by_map(replays_dir: Path, map_of) -> dict[str, list[str]]:
    """Map name -> match ids with replay data on the server. map_of(match id) -> map name or None."""
    from ..replayfile import stored
    out: dict[str, list[str]] = {}
    for mid in stored(replays_dir):
        m = map_of(mid)
        if m:
            out.setdefault(m, []).append(mid)
    return out


def load_replays(replays_dir: Path, ids: list[str]) -> list[dict]:
    out = []
    for mid in ids:
        p = Path(replays_dir) / f"{mid}.json.gz"
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    return out
