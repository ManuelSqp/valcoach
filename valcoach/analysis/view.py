"""Where players were looking at each kill (from the API's `view_radians`).

The API doesn't document how `view_radians` maps onto the map's x/y axes, so the
convention is calibrated per match: at a kill, the killer is almost always looking
at the victim. We try the 8 possible conventions (4 rotations x 2 directions) and
keep the one that makes killers face their victims best. If even the best one
doesn't fit (median error > 35 deg), view analysis is switched off for that match
instead of producing wrong conclusions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import Kill, Match, PlayerLoc

FACING_DEG = 30      # within this angle = looking at the target (crosshair roughly there)
SIDE_DEG = 90        # 30..90 = target was off to the side; > 90 = behind


@dataclass
class ViewModel:
    sign: int = 1
    offset: float = 0.0          # radians
    median_error_deg: float = 180.0
    samples: int = 0

    @property
    def ok(self) -> bool:
        return self.samples >= 5 and self.median_error_deg <= 35

    def world_dir(self, view_radians: float) -> tuple[float, float]:
        a = self.sign * view_radians + self.offset
        return math.cos(a), math.sin(a)

    def angle_to(self, pl: PlayerLoc, tx: float, ty: float) -> float | None:
        """Degrees between where `pl` looks and the direction to (tx, ty), 0..180."""
        dx, dy = tx - pl.x, ty - pl.y
        if dx == 0 and dy == 0:
            return None
        vx, vy = self.world_dir(pl.view)
        target = math.atan2(dy, dx)
        look = math.atan2(vy, vx)
        d = abs((target - look + math.pi) % (2 * math.pi) - math.pi)
        return math.degrees(d)


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def calibrate(match: Match) -> ViewModel:
    pairs: list[tuple[PlayerLoc, float, float]] = []
    for k in match.kills:
        if not k.killer or k.killer == k.victim:
            continue
        loc = k.loc_of(k.killer)
        if loc is not None and (loc.x, loc.y) != (k.victim_x, k.victim_y):
            pairs.append((loc, k.victim_x, k.victim_y))
    best = ViewModel(samples=len(pairs))
    if len(pairs) < 5:
        return best
    for sign in (1, -1):
        for q in range(4):
            vm = ViewModel(sign=sign, offset=q * math.pi / 2, samples=len(pairs))
            errs = [e for loc, tx, ty in pairs if (e := vm.angle_to(loc, tx, ty)) is not None]
            if errs:
                vm.median_error_deg = round(_median(errs), 1)
                if vm.median_error_deg < best.median_error_deg:
                    best = vm
    return best


def facing_label(deg: float | None) -> str | None:
    if deg is None:
        return None
    if deg <= FACING_DEG:
        return "facing"
    if deg <= SIDE_DEG:
        return "side"
    return "behind"


@dataclass
class DuelView:
    """View facts for one kill, from one player's perspective."""
    my_angle_to_other: float | None      # where I looked vs. the other player
    other_angle_to_me: float | None      # where they looked vs. me
    distance_m: float | None


def duel_view(vm: ViewModel, k: Kill, me: str, other: str) -> DuelView:
    my_loc, other_loc = k.loc_of(me), k.loc_of(other)
    # the victim is not always in player_locations: use the kill location for their position
    mx, my = (my_loc.x, my_loc.y) if my_loc else ((k.victim_x, k.victim_y) if me == k.victim else (None, None))
    ox, oy = (other_loc.x, other_loc.y) if other_loc else (
        (k.victim_x, k.victim_y) if other == k.victim else (None, None))
    dist = None
    if mx is not None and ox is not None:
        dist = round(math.hypot(mx - ox, my - oy) / 100, 1)
    mine = theirs = None
    if vm.ok:
        if my_loc is not None and ox is not None:
            mine = vm.angle_to(my_loc, ox, oy)
        if other_loc is not None and mx is not None:
            theirs = vm.angle_to(other_loc, mx, my)
    return DuelView(
        my_angle_to_other=round(mine) if mine is not None else None,
        other_angle_to_me=round(theirs) if theirs is not None else None,
        distance_m=dist,
    )


def range_bucket(dist_m: float | None) -> str | None:
    if dist_m is None:
        return None
    if dist_m < 10:
        return "close (<10 m)"
    if dist_m < 25:
        return "mid (10-25 m)"
    return "long (>25 m)"
