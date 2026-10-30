"""Minimap parsing: icon detection, automatic calibration, position tracking.

Requirements for your recording settings (Settings > General > Minimap):
  * Rotate: OFF (fixed orientation; "Always the same" or "Based on side" both work)
  * Keep Player Centered: OFF (whole map visible)
  * Fixed minimap size / zoom across recordings (calibration is cached per map)

Icon colours (default colour settings, no colour-blind mode):
  * you:     yellow ring
  * allies:  teal / cyan ring
  * enemies: red ring (only when spotted)
Tune COLOR_RANGES if you use a colour-blind mode or custom enemy highlight.

Calibration model: pixel = s * R_k * (u, v) + t, where (u, v) is the 0..1 map
UV from valorant-api.com, R_k a rotation by k*90 deg, s a scale and t a
translation. It is fitted automatically from moments where the API gives
exact player positions (every kill snapshot) and the VOD shows the allies.
With "Fixed orientation: Based on side" the map turns 180 deg around its centre
when your team swaps sides; then `flip_side` names the side (yours) on which the
UV is turned 180 deg before R_k. Both models are fitted and the better one kept.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from ..maps import MapInfo
from ..models import Match
from .io import crop, frame_at, iter_frames, open_video, video_info, video_roi
from .sync import SyncResult

# OpenCV HSV: H 0..180, S 0..255, V 0..255
COLOR_RANGES: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    # second range: under the translucent white circle around you the yellow ring is pale but very bright
    # (the yellowish site markers are as pale but much darker, V ~150)
    "self":  [((20, 120, 150), (35, 255, 255)), ((25, 60, 200), (38, 255, 255))],
    "ally":  [((80, 90, 130), (100, 255, 255))],
    "enemy": [((0, 130, 130), (8, 255, 255)), ((170, 130, 130), (180, 255, 255))],
}


@dataclass
class Blob:
    kind: str          # self | ally | enemy
    px: float          # pixel coords inside the minimap ROI
    py: float
    area: float
    count: int = 1     # estimated number of overlapping icons in this blob


@dataclass
class Calibration:
    map_uuid: str
    rot_k: int                 # number of 90 deg rotations applied to (u,v)
    scale: float
    tx: float
    ty: float
    rms_px: float
    n_points: int
    roi_frac: list[float] = field(default_factory=list)
    frame_size: list[int] = field(default_factory=list)
    flip_side: str = ""        # "attack" | "defense": your side on which the map is turned 180 deg ("" = never)

    def _k(self, side: str) -> int:
        return (self.rot_k + (2 if self.flip_side and side == self.flip_side else 0)) % 4

    def uv_to_px(self, u: float, v: float, side: str = "") -> tuple[float, float]:
        ru, rv = _rot(np.array([[u, v]]), self._k(side))[0]
        return self.scale * ru + self.tx, self.scale * rv + self.ty

    def px_to_uv(self, px: float, py: float, side: str = "") -> tuple[float, float]:
        ru, rv = (px - self.tx) / self.scale, (py - self.ty) / self.scale
        u, v = _rot(np.array([[ru, rv]]), (4 - self._k(side)) % 4)[0]
        return float(u), float(v)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        return cls(**json.loads(path.read_text()))


def _rot(uv: np.ndarray, k: int) -> np.ndarray:
    """Rotate points around the map centre (0.5, 0.5) by k*90 degrees."""
    c = uv - 0.5
    for _ in range(k % 4):
        c = np.stack([-c[:, 1], c[:, 0]], axis=1)
    return c + 0.5


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
def detect_blobs(minimap_bgr: np.ndarray, min_area: float | None = None,
                 max_area: float | None = None, icon_area: float | None = None,
                 merge_self: bool = True) -> list[Blob]:
    """merge_self=False keeps every yellow candidate (a teammate's yellowish agent portrait looks like
    you); track_round then picks yours from your exact positions at the kills."""
    h, w = minimap_bgr.shape[:2]
    scale_area = (w * h) / (400 * 400)            # tuned on a ~400 px minimap
    min_area = min_area if min_area is not None else 12 * scale_area
    max_area = max_area if max_area is not None else 2400 * scale_area   # allows ~5 stacked icons
    hsv = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2HSV)
    out: list[Blob] = []
    kernel = np.ones((3, 3), np.uint8)
    for kind, ranges in COLOR_RANGES.items():
        mask = np.zeros((h, w), np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        # rings -> fill holes so a ring becomes one component
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        kind_blobs = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            area = float(bw * bh)
            if area < min_area or area > max_area:
                continue
            aspect = bw / bh if bh else 0
            if not 0.33 <= aspect <= 3.0:
                continue
            kind_blobs.append(Blob(kind=kind, px=x + bw / 2, py=y + bh / 2, area=area))
        out.extend(kind_blobs)
    selfs = [b for b in out if b.kind == "self"]
    if merge_self and len(selfs) > 1:
        out = [b for b in out if b.kind != "self"] + [_merge_self(selfs)]
    _estimate_counts(out, icon_area)
    return out


def _merge_self(blobs: list[Blob]) -> Blob:
    """There is exactly one 'you' icon. Fragments of it (partly covered by other icons)
    are merged into an area-weighted centre; distant strays are dropped."""
    main = max(blobs, key=lambda b: b.area)
    radius = 2.0 * float(np.sqrt(main.area))
    near = [b for b in blobs if np.hypot(b.px - main.px, b.py - main.py) <= radius]
    tot = sum(b.area for b in near)
    return Blob(kind="self", px=sum(b.px * b.area for b in near) / tot,
                py=sum(b.py * b.area for b in near) / tot, area=main.area)


def _estimate_counts(blobs: list[Blob], icon_area: float | None) -> None:
    """Overlapping icons merge into one blob; estimate how many it contains from its
    bounding-box area relative to a single icon. Heavily stacked icons (same spot)
    are still undercounted - counts are approximate."""
    if not blobs:
        return
    unit = icon_area if icon_area else estimate_icon_area(blobs)
    for b in blobs:
        b.count = 1 if b.kind == "self" else max(1, min(5, round(b.area / (unit * 1.15))))


def estimate_icon_area(blobs: list[Blob]) -> float:
    """Bounding-box area of a single icon: the small end of the blob size distribution."""
    areas = sorted(b.area for b in blobs)
    return max(1.0, areas[len(areas) // 10])


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------
def _fit_similarity_fixed_rot(uv: np.ndarray, px: np.ndarray, k: int) -> tuple[float, float, float, float]:
    """Least squares for px = s*R_k(uv) + t with known rotation. Returns s, tx, ty, rms."""
    r = _rot(uv, k)
    mu_r, mu_p = r.mean(0), px.mean(0)
    rc, pc = r - mu_r, px - mu_p
    denom = float((rc ** 2).sum())
    s = float((rc * pc).sum() / denom) if denom > 1e-12 else 1.0
    t = mu_p - s * mu_r
    rms = float(np.sqrt(((s * r + t - px) ** 2).sum(1).mean()))
    return s, float(t[0]), float(t[1]), rms


def calibrate(samples: list[tuple], roi_size: tuple[int, int],
              map_uuid: str, iterations: int = 12) -> Calibration:
    """ICP-style fit.

    samples: list of (uv_points [N,2] from the API, px_points [M,2] detected allies+self[, your side])
    The side is optional; with it, a map that turns 180 deg when you swap sides is also tried.
    """
    sides = {smp[2] for smp in samples if len(smp) > 2 and smp[2]}
    best: Calibration | None = None
    for flip in [""] + (["attack"] if len(sides) == 2 else []):
        # turning the UV of one side by 180 deg turns the problem into a fixed-orientation fit
        fixed = [(1.0 - smp[0] if flip and len(smp) > 2 and smp[2] == flip else smp[0], smp[1]) for smp in samples]
        cand = _calibrate_fixed(fixed, roi_size, map_uuid, iterations)
        if cand is None:
            continue
        cand.flip_side = flip
        # the side model must clearly win: with one orientation it only fits noise
        if best is None or cand.rms_px < 0.8 * best.rms_px:
            best = cand
    if best is None:
        raise RuntimeError("Minimap calibration failed: not enough detections at kill moments")
    return best


def _calibrate_fixed(samples: list[tuple[np.ndarray, np.ndarray]], roi_size: tuple[int, int],
                     map_uuid: str, iterations: int) -> Calibration | None:
    w, h = roi_size
    best: Calibration | None = None
    for k in range(4):
        # initial guess: map fills the ROI (square, centred)
        s = float(min(w, h))
        tx, ty = (w - s) / 2, (h - s) / 2
        rms = float("inf")
        n_used = 0
        for _ in range(iterations):
            src, dst = [], []
            for uv, px in samples:
                if len(uv) == 0 or len(px) == 0:
                    continue
                proj = s * _rot(uv, k) + np.array([tx, ty])
                cost = np.linalg.norm(proj[:, None, :] - px[None, :, :], axis=2)
                ri, ci = linear_sum_assignment(cost)
                for a, b in zip(ri, ci):
                    src.append(uv[a])
                    dst.append(px[b])
            if len(src) < 4:
                break
            src_a, dst_a = np.array(src), np.array(dst)
            s_, tx_, ty_, _ = _fit_similarity_fixed_rot(src_a, dst_a, k)
            # trimmed refit: drop worst 25 % (mis-assignments, spectator icons, pings)
            resid = np.linalg.norm(s_ * _rot(src_a, k) + np.array([tx_, ty_]) - dst_a, axis=1)
            keep = resid <= np.percentile(resid, 75)
            if keep.sum() >= 4:
                s_, tx_, ty_, rms_ = _fit_similarity_fixed_rot(src_a[keep], dst_a[keep], k)
            else:
                rms_ = float(np.sqrt((resid ** 2).mean()))
            converged = abs(s_ - s) < 1e-3 * s and abs(tx_ - tx) < 0.05 and abs(ty_ - ty) < 0.05
            s, tx, ty, rms, n_used = s_, tx_, ty_, rms_, int(keep.sum())
            if converged:
                break
        if s <= 0:
            continue
        cand = Calibration(map_uuid=map_uuid, rot_k=k, scale=s, tx=tx, ty=ty, rms_px=rms, n_points=n_used)
        if best is None or cand.rms_px < best.rms_px:
            best = cand
    return best


def collect_calibration_samples(match: Match, map_info: MapInfo, video_path: str, sync: SyncResult,
                                roi_frac: list[float], focus_puuid: str,
                                max_samples: int = 80) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """At each kill, compare API positions of the focus player's team with detected ally/self icons.
    Each sample also carries the focus player's side in that round (for "Based on side" maps)."""
    info = video_info(video_path)
    roi = video_roi(roi_frac, info)
    team = match.team_of(focus_puuid)
    kills = [k for k in match.kills if k.player_locations]
    if len(kills) > max_samples:
        idx = np.linspace(0, len(kills) - 1, max_samples).astype(int)
        kills = [kills[i] for i in idx]
    samples = []
    with open_video(video_path) as cap:
        for k in kills:
            t = sync.vod_time(k.t_match_ms, k.round)
            if t < 0 or t > info.duration_s:
                continue
            frame = frame_at(cap, info.fps, t)
            if frame is None:
                continue
            blobs = [b for b in detect_blobs(crop(frame, roi)) if b.kind in ("ally", "self")]
            # the victim's icon disappears at the kill, so leave them out
            uv = np.array([map_info.to_uv(pl.x, pl.y) for pl in k.player_locations
                           if pl.team == team and pl.puuid != k.victim])
            px = np.array([[b.px, b.py] for b in blobs])
            if len(uv) >= 2 and len(px) >= 2:
                side = match.rounds[k.round].side_of(team) if 0 <= k.round < len(match.rounds) else ""
                samples.append((uv, px, side))
    return samples


# ---------------------------------------------------------------------------
# tracking
# ---------------------------------------------------------------------------
@dataclass
class TrackPoint:
    t_round_s: float
    kind: str
    x: float           # world coords
    y: float
    area: str
    zone: str
    count: int = 1


@dataclass
class RoundTrack:
    round_index: int
    points: list[TrackPoint] = field(default_factory=list)

    def zone_counts(self, kind: str, t0: float, t1: float) -> dict[str, float]:
        """Average number of `kind` icons per zone between t0 and t1 (round seconds)."""
        pts = [p for p in self.points if p.kind == kind and t0 <= p.t_round_s < t1]
        times = sorted({p.t_round_s for p in pts})
        if not times:
            return {}
        acc: dict[str, int] = {}
        for p in pts:
            acc[p.zone] = acc.get(p.zone, 0) + p.count
        avg = {z: round(c / len(times), 1) for z, c in sorted(acc.items(), key=lambda kv: -kv[1])}
        return {z: n for z, n in avg.items() if n > 0}


def track_round(match: Match, round_index: int, map_info: MapInfo, cal: Calibration,
                video_path: str, sync: SyncResult, roi_frac: list[float],
                sample_fps: float = 4.0, round_len_s: float | None = None, side: str = "",
                focus: str = "", floor=None) -> RoundTrack:
    """side: the focus player's side this round (needed when the minimap turns by side).
    focus: the focus player; then the icon counts per frame are capped at the players still alive
    (stack estimates and icon fragments over-counted), and after your death the yellow icon is the
    teammate you spectate, so it becomes an ally point. floor(u, v) -> bool drops detections off the map
    (HUD marks, teleporter lines)."""
    rnd = match.rounds[round_index]
    info = video_info(video_path)
    roi = video_roi(roi_frac, info)
    if rnd.start_match_ms is None:
        return RoundTrack(round_index)
    start_vod = sync.vod_time(rnd.start_match_ms, round_index)
    if round_len_s is None:
        last_evt = max([k.t_round_ms for k in rnd.kills] +
                       [rnd.plant.t_round_ms if rnd.plant else 0, rnd.defuse.t_round_ms if rnd.defuse else 0])
        round_len_s = last_evt / 1000 + 2.0
    track = RoundTrack(round_index)
    frames: list[tuple[float, list[Blob]]] = []
    with open_video(video_path) as cap:
        for t, frame in iter_frames(cap, info.fps, start_vod, start_vod + round_len_s, 1.0 / sample_fps):
            frames.append((t, detect_blobs(crop(frame, roi), merge_self=not focus)))
    # single-icon size from the whole round (one frame may only contain merged blobs)
    all_blobs = [b for _, bs in frames for b in bs if b.kind != "self"]
    unit = estimate_icon_area(all_blobs) if all_blobs else None
    alive = _alive_counts(match, rnd, focus) if focus else None
    per_frame = []
    for t, blobs in frames:
        if unit:
            _estimate_counts(blobs, unit)
        kept = []
        for b in blobs:
            u, v = cal.px_to_uv(b.px, b.py, side)
            if not (-0.05 <= u <= 1.05 and -0.05 <= v <= 1.05):
                continue
            if floor is not None and not floor(u, v):
                continue
            kept.append((b, u, v, *map_info.from_uv(u, v)))
        per_frame.append((t - start_vod, kept))
    if focus:
        _pick_self(per_frame, rnd, focus, alive)
    for t, kept in per_frame:
        if alive:
            _, n_mates, n_enemies = alive(t)
            _cap_counts([k[0] for k in kept], n_mates, n_enemies)
        for b, u, v, x, y in kept:
            track.points.append(TrackPoint(
                t_round_s=round(t, 2), kind=b.kind, x=x, y=y,
                area=map_info.area(x, y), zone=map_info.zone(x, y), count=b.count,
            ))
    return track


SELF_RUN_UNITS_S = 700.0      # a bit above max run speed, world units per second
SELF_SLACK_UNITS = 350.0      # detection noise + icon size
SELF_ANCHOR_S = 0.3           # a frame this close to a kill is anchored to your API position


def _pick_self(per_frame: list[tuple[float, list]], rnd, focus: str, alive) -> None:
    """Keep one 'self' detection per frame: the one reachable from your last known position.
    Your exact position is known at every kill (API snapshot); from there the icon is followed
    frame by frame, forwards and (before the first kill) backwards. Other yellow candidates (a
    teammate's yellowish portrait) are dropped. After your death the yellow icon is the teammate
    you spectate: it becomes one ally point."""
    anchors = sorted((k.t_round_ms / 1000, (pl.x, pl.y)) for k in rnd.kills
                     for pl in [k.loc_of(focus)] if pl and k.victim != focus)
    times = [t for t, _ in per_frame]
    pick: dict[int, tuple] = {}

    def follow(order):
        state = None                                   # (x, y, t)
        for i in order:
            t, kept = per_frame[i]
            near = [a for a in anchors if abs(a[0] - t) <= SELF_ANCHOR_S]
            if near:
                ax, ay = near[0][1]
                state = (ax, ay, near[0][0])
            if state is None:
                continue
            gate = SELF_SLACK_UNITS + SELF_RUN_UNITS_S * abs(t - state[2])
            cands = [k for k in kept if k[0].kind == "self"
                     and math.hypot(k[3] - state[0], k[4] - state[1]) <= gate]
            if cands:
                best = min(cands, key=lambda k: math.hypot(k[3] - state[0], k[4] - state[1]))
                pick.setdefault(i, best)
                state = (best[3], best[4], t)

    if anchors:
        follow(range(len(per_frame)))                  # forwards from each kill
        first = min(range(len(times)), key=lambda i: abs(times[i] - anchors[0][0]))
        follow(range(first, -1, -1))                   # before the first kill: backwards
    for i, (t, kept) in enumerate(per_frame):
        selfs = [k for k in kept if k[0].kind == "self"]
        if not selfs:
            continue
        rest = [k for k in kept if k[0].kind != "self"]
        if alive and not alive(t)[0]:
            b = max(selfs, key=lambda k: k[0].area)    # spectated teammate
            b[0].kind = "ally"
            rest.append(b)
        elif i in pick:
            rest.append(pick[i])
        elif not anchors:
            rest.append(max(selfs, key=lambda k: k[0].area))   # no API positions: biggest yellow blob
        kept[:] = rest


def _alive_counts(match: Match, rnd, focus: str):
    """t_round_s -> (you alive, teammates alive, enemies alive)."""
    team = match.team_of(focus)
    mates = [p.puuid for p in match.players_on(team) if p.puuid != focus]
    enemies = [p.puuid for p in match.players_on(match.other_team(team))]
    died = {k.victim: k.t_round_ms / 1000 for k in rnd.kills}

    def at(t: float) -> tuple[bool, int, int]:
        def n_alive(ps):
            return sum(1 for pu in ps if died.get(pu, float("inf")) > t)
        return died.get(focus, float("inf")) > t, n_alive(mates), n_alive(enemies)
    return at


def _cap_counts(blobs: list[Blob], n_mates: int, n_enemies: int) -> None:
    """Counts add up to at most the living players; the biggest blobs keep theirs. Extra blobs stay
    (count 0) because a teammate often shows as several fragments and the path tracking needs them."""
    for kind, left in (("ally", n_mates), ("enemy", n_enemies)):
        for b in sorted((b for b in blobs if b.kind == kind), key=lambda b: -b.area):
            b.count = min(b.count, left)
            left -= b.count


def describe_track(track: RoundTrack, bucket_s: float = 10.0) -> dict:
    """Compact, LLM-friendly description of movement during a round."""
    if not track.points:
        return {}
    end = max(p.t_round_s for p in track.points)
    timeline = []
    prev = None
    t = 0.0
    while t <= end:
        allies = track.zone_counts("ally", t, t + bucket_s)
        selfz = track.zone_counts("self", t, t + bucket_s)
        enemies = track.zone_counts("enemy", t, t + bucket_s)
        entry = {"t": f"{int(t)}-{int(t + bucket_s)}s"}
        if allies:
            entry["allies"] = allies
        if selfz:
            entry["you"] = max(selfz, key=selfz.get)
        if enemies:
            entry["enemies_seen"] = enemies
        if len(entry) > 1:
            timeline.append(entry)
        t += bucket_s

    # rotations: a zone losing >=1.5 allies while another gains >=1.5 between buckets
    rotations = []
    for a, b in zip(timeline, timeline[1:]):
        za, zb = a.get("allies", {}), b.get("allies", {})
        lost = {z: za[z] - zb.get(z, 0) for z in za if za[z] - zb.get(z, 0) >= 1.5}
        gained = {z: zb[z] - za.get(z, 0) for z in zb if zb[z] - za.get(z, 0) >= 1.5}
        for zl in lost:
            for zg in gained:
                if zl != zg:
                    rotations.append(f"{b['t']}: ~{round(min(lost[zl], gained[zg]))} allies {zl} -> {zg}")

    self_path = []
    last = None
    for p in sorted((p for p in track.points if p.kind == "self"), key=lambda p: p.t_round_s):
        if p.area != last:
            self_path.append(f"{int(p.t_round_s)}s {p.area}")
            last = p.area
    return {"note": "counts are averages per window and approximate (stacked icons merge)",
            "timeline": timeline, "rotations": rotations, "your_path": self_path[:25]}
