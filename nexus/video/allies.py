"""Teammate paths from the VOD minimap.

Your minimap shows every living teammate the whole round (also while you spectate
after your death), so their movement can be measured instead of estimated. The
hard part is identity: the detector only sees "a teal icon here". It is solved
with the exact API positions at every kill:

  1. At each kill snapshot (anchor) the API says where each teammate stood; the
     icons in that frame are matched to them (Hungarian assignment, gated).
  2. From each anchor the identities are carried frame by frame (nearest icon
     within running distance), forwards to the next anchor and backwards to the
     previous one / the round start.
  3. Where the forward and backward pass disagree (two icons crossed or merged
     and the identity is unclear), the points are dropped; the replay estimates
     that stretch instead of showing a possibly swapped path.

Stacked icons (blob count > 1) may be assigned to several players. After your
own death the yellow icon follows the teammate you spectate, so it is treated
as a normal teammate icon from then on.

Enemy icons are only on the minimap while someone sees them; they are returned
as anonymous sightings (no identity).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..models import Match
from .minimap import RoundTrack

RUN_UNITS_S = 700.0          # a bit above max run speed (675 u/s with the knife), world units per second
SLACK_UNITS = 350.0          # detection noise + icon size
ANCHOR_UNITS = 650.0         # max distance icon <-> API position at a kill
ANCHOR_WINDOW_S = 0.6        # frame must be this close to the kill time
AGREE_UNITS = 300.0          # forward and backward pass agree within this
OUT_HZ = 2.0                 # output points per second


def _frames(track: RoundTrack, focus_death_s: float | None) -> list[tuple[float, np.ndarray]]:
    """[(t, detections [N,2])] with stacked blobs repeated by their count."""
    by_t: dict[float, list] = {}
    for p in track.points:
        kind = p.kind
        if kind == "self" and focus_death_s is not None and p.t_round_s > focus_death_s + 0.5:
            kind = "ally"                              # spectated teammate
        by_t.setdefault(p.t_round_s, [])
        if kind == "ally":
            by_t[p.t_round_s].extend([(p.x, p.y)] * max(1, p.count))
    return [(t, np.array(v, float).reshape(-1, 2)) for t, v in sorted(by_t.items())]


def _assign(state: dict[str, np.ndarray], det: np.ndarray, gate: float) -> dict[str, np.ndarray]:
    if not state or len(det) == 0:
        return {}
    ids = list(state)
    S = np.array([state[i] for i in ids])
    cost = np.linalg.norm(S[:, None, :] - det[None, :, :], axis=2)
    big = gate * 10 + 1e6
    ri, ci = linear_sum_assignment(np.where(cost <= gate, cost, big))
    return {ids[r]: det[c] for r, c in zip(ri, ci) if cost[r, c] <= gate}


def _run(frames, start_idx: int, stop_idx: int, init: dict[str, np.ndarray],
         alive, step: int) -> dict[str, dict[int, np.ndarray]]:
    """Carry identities from frame start_idx (exclusive) towards stop_idx (inclusive)."""
    out: dict[str, dict[int, np.ndarray]] = {p: {} for p in init}
    state = {p: (v.copy(), frames[start_idx][0]) for p, v in init.items()}
    i = start_idx + step
    while (step > 0 and i <= stop_idx) or (step < 0 and i >= stop_idx):
        t, det = frames[i]
        live = {p: s for p, s in state.items() if alive(p, t)}
        # one assignment per frame; each player's gate grows with the time since they were last seen
        if live:
            ids = list(live)
            S = np.array([live[p][0] for p in ids])
            gates = np.array([SLACK_UNITS + RUN_UNITS_S * abs(t - live[p][1]) for p in ids])
            if len(det):
                cost = np.linalg.norm(S[:, None, :] - det[None, :, :], axis=2)
                ok = cost <= gates[:, None]
                ri, ci = linear_sum_assignment(np.where(ok, cost, 1e9))
                for r, c in zip(ri, ci):
                    if ok[r, c]:
                        p = ids[r]
                        state[p] = (det[c].copy(), t)
                        out[p][i] = det[c]
        i += step
    return out


def ally_paths(match: Match, round_index: int, track: RoundTrack, focus: str) -> dict[str, list[tuple[float, float, float]]]:
    """Teammate puuid -> [(t_round_s, x, y)] measured from the minimap (about 2 per second)."""
    rnd = match.rounds[round_index]
    team = match.team_of(focus)
    mates = [p.puuid for p in match.players.values() if p.team == team and p.puuid != focus]
    deaths: dict[str, float] = {}
    for k in rnd.kills:
        deaths.setdefault(k.victim, k.t_round_ms / 1000)
    frames = _frames(track, deaths.get(focus))
    if not frames or not mates:
        return {}
    times = np.array([t for t, _ in frames])

    def alive(p: str, t: float) -> bool:
        return p not in deaths or t < deaths[p] - 0.2

    # anchors: frame index -> {puuid: API position}
    anchors: list[tuple[int, dict[str, np.ndarray]]] = []
    for k in rnd.kills:
        if not k.player_locations:
            continue
        t = k.t_round_ms / 1000
        i = int(np.argmin(np.abs(times - t)))
        if abs(times[i] - t) > ANCHOR_WINDOW_S:
            continue
        api = {pl.puuid: np.array([pl.x, pl.y], float) for pl in k.player_locations
               if pl.puuid in mates and pl.puuid != k.victim and alive(pl.puuid, times[i])}
        got = _assign(api, frames[i][1], ANCHOR_UNITS)
        if got:
            anchors.append((i, got))
    if not anchors:
        return {}

    # per player: frame index -> position, only where the passes agree
    final: dict[str, dict[int, np.ndarray]] = {p: {} for p in mates}
    bounds = [a for a, _ in anchors]
    for j, (ai, got) in enumerate(anchors):
        for p, v in got.items():
            final[p][ai] = v
        prev_i = bounds[j - 1] if j > 0 else 0
        next_i = bounds[j + 1] if j + 1 < len(bounds) else len(frames) - 1
        fwd = _run(frames, ai, next_i, got, alive, +1)
        if j + 1 < len(anchors):
            bwd = _run(frames, next_i, ai, anchors[j + 1][1], alive, -1)
            for p in mates:
                f, b = fwd.get(p, {}), bwd.get(p, {})
                for i in range(ai + 1, next_i):
                    if i in f and i in b:
                        if np.linalg.norm(f[i] - b[i]) <= AGREE_UNITS:
                            final[p][i] = (f[i] + b[i]) / 2
                    elif i in f and p not in anchors[j + 1][1] and alive(p, frames[i][0]):
                        final[p][i] = f[i]          # not anchored at the next kill: forward only
                    elif i in b and p not in got:
                        final[p][i] = b[i]
        else:
            for p, pts in fwd.items():             # after the last kill: forward only
                for i, v in pts.items():
                    if i > ai:
                        final[p][i] = v
        if j == 0 and ai > 0:                      # before the first kill: backward only
            for p, pts in _run(frames, ai, prev_i, got, alive, -1).items():
                for i, v in pts.items():
                    final[p][i] = v

    out: dict[str, list[tuple[float, float, float]]] = {}
    for p, pts in final.items():
        seq, last_b = [], None
        for i in sorted(pts):
            t = float(frames[i][0])
            b = int(t * OUT_HZ)
            if b == last_b:
                continue
            last_b = b
            seq.append((round(t, 2), float(pts[i][0]), float(pts[i][1])))
        if seq:
            out[p] = seq
    return out


def enemy_sightings(track: RoundTrack) -> list[tuple[float, float, float]]:
    """[(t_round_s, x, y)] of enemy icons (spotted), thinned to about 2 per second per spot."""
    out, seen = [], set()
    for p in sorted((p for p in track.points if p.kind == "enemy"), key=lambda p: p.t_round_s):
        key = (int(p.t_round_s * OUT_HZ), int(p.x // 400), int(p.y // 400))
        if key in seen:
            continue
        seen.add(key)
        out.append((p.t_round_s, p.x, p.y))
    return out


def coverage(paths: dict[str, list], match: Match, round_index: int, focus: str) -> float:
    """Share of teammate-alive time with a measured point within 1.5 s (for the log)."""
    rnd = match.rounds[round_index]
    team = match.team_of(focus)
    end = max([k.t_round_ms for k in rnd.kills] + [0]) / 1000
    deaths = {}
    for k in rnd.kills:
        deaths.setdefault(k.victim, k.t_round_ms / 1000)
    tot = hit = 0
    for p in (q.puuid for q in match.players.values() if q.team == team and q.puuid != focus):
        ts = np.array([t for t, _, _ in paths.get(p, [])])
        t = 1.0
        while t < min(end, deaths.get(p, math.inf)):
            tot += 1
            if len(ts) and np.min(np.abs(ts - t)) <= 1.5:
                hit += 1
            t += 1.0
    return hit / tot if tot else 0.0
