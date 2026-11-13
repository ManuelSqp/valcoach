"""Map angles (4.28): the aim trainer's duel on a real map layout. You stand at a callout of a site, facing another
one (hold the site looking at its main, or come out of main looking at the site); enemies show up at the other
callouts in front of you, at their real direction and distance on the map.

Where the callouts are comes from valorant-api.com (maps.py): points on the minimap, no walls and no heights. So the
directions and distances are the real ones in a straight line, every enemy is at your height, and each spot gets a
piece of cover to peek from. The page (static/trainer.js, scenario "map_angles") builds the room from this."""
from __future__ import annotations

import math

CONE = 75            # degrees left and right of where you look
NEAR, FAR = 3.0, 34.0
MIN_SPOTS = 3


def _ang(du: float, dv: float) -> float:
    """Direction on the minimap in degrees: 0 = up, clockwise positive (to the right)."""
    return math.degrees(math.atan2(du, -dv))


def _wrap(a: float) -> float:
    return (a + 180) % 360 - 180


def spots_from(mi, stand, face) -> list[dict]:
    """The callouts in front of you from `stand` facing `face`: [{label, yaw (deg, right positive), d (m)}]."""
    per_m = abs(mi.x_mult) * 100 or 0.007           # minimap units per meter (world units are cm)
    su, sv = mi.to_uv(stand.x, stand.y)
    fu, fv = mi.to_uv(face.x, face.y)
    look = _ang(fu - su, fv - sv)
    out, seen = [], {stand.label}
    for c in mi.callouts:
        if c.region.lower() == "spawn" or c.label in seen:
            continue
        seen.add(c.label)
        u, v = mi.to_uv(c.x, c.y)
        d = math.hypot(u - su, v - sv) / per_m
        yaw = _wrap(_ang(u - su, v - sv) - look)
        if NEAR <= d <= FAR and abs(yaw) <= CONE:
            out.append({"label": c.label, "yaw": round(yaw, 1), "d": round(d, 1)})
    return sorted(out, key=lambda s: s["yaw"])


def positions(mi) -> list[dict]:
    """Where you can stand on a map: per site, holding the site (facing its main) and taking it from main (facing
    the site). [{id, name, stand, face, spots}] with at least MIN_SPOTS spots."""
    if not mi or not mi.callouts:
        return []
    by = {}
    for c in mi.callouts:
        by.setdefault((c.super_region, c.region.lower()), c)
    out = []
    for site in ("A", "B", "C"):
        s = by.get((site, "site"))
        m = by.get((site, "main")) or by.get((site, "lobby")) or by.get((site, "link"))
        if not s or not m:
            continue
        for stand, face, name, key in ((s, m, f"Hold {site} Site, facing {m.label}", f"{site}-hold"),
                                       (m, s, f"Take {site} from {m.label}", f"{site}-take")):
            sp = spots_from(mi, stand, face)
            if len(sp) >= MIN_SPOTS:
                out.append({"id": key, "name": name, "stand": stand.label, "face": face.label, "spots": sp})
    return out


def for_maps(reg, names: list[str]) -> dict[str, list[dict]]:
    """Map name -> positions, for the maps that have any (in the order given)."""
    out = {}
    for n in names:
        try:
            mi = reg.get(name=n)
        except Exception:
            mi = None
        ps = positions(mi)
        if ps:
            out[n] = ps
    return out
