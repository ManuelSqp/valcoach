"""Align a VOD to the match timeline.

Strategy
--------
1. Detect kill-feed *onsets* in the VOD: moments where new coloured content
   appears in the kill-feed region (rising edges only, so entries fading out
   don't create false events).
2. Every (onset - kill_time) pair votes for an offset; the histogram peak is
   the global offset (vod_seconds = match_seconds + offset). This works even
   when the recording starts mid-match.
3. Refine per round within +-3 s, so tech pauses / dropped frames don't drift.

A manual anchor (one known kill timestamp in the VOD) can replace step 1-2.
"""
from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..models import Match
from .io import crop, iter_frames, open_video, roi_px, video_info


@dataclass
class SyncResult:
    global_offset_s: float
    per_round_offset_s: dict[int, float] = field(default_factory=dict)   # round index -> offset
    matched_kills: int = 0
    total_kills: int = 0
    method: str = "auto"
    vod_duration_s: float = 0.0

    def offset_for(self, round_index: int) -> float:
        return self.per_round_offset_s.get(round_index, self.global_offset_s)

    def vod_time(self, t_match_ms: int, round_index: int) -> float:
        return t_match_ms / 1000.0 + self.offset_for(round_index)

    @property
    def confidence(self) -> float:
        return self.matched_kills / self.total_kills if self.total_kills else 0.0

    def save(self, path: Path) -> None:
        d = asdict(self)
        d["per_round_offset_s"] = {str(k): v for k, v in self.per_round_offset_s.items()}
        path.write_text(json.dumps(d, indent=2))

    @classmethod
    def load(cls, path: Path) -> "SyncResult":
        d = json.loads(path.read_text())
        d["per_round_offset_s"] = {int(k): v for k, v in d.get("per_round_offset_s", {}).items()}
        return cls(**d)


# ---------------------------------------------------------------------------
# 1. kill-feed onset detection
# ---------------------------------------------------------------------------
def feed_mask(roi_bgr: np.ndarray) -> np.ndarray:
    """Pixels that look like kill-feed entries: saturated team colours or bright white text/bars."""
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    sat = (hsv[..., 1] > 110) & (hsv[..., 2] > 120)
    bright = (hsv[..., 2] > 225) & (hsv[..., 1] < 40)
    return (sat | bright).astype(np.uint8)


def detect_killfeed_onsets(video_path: str, roi_frac: list[float], step_s: float = 0.1,
                           t_start: float = 0.0, t_end: float | None = None,
                           min_rise: float | None = None, progress=None) -> list[float]:
    info = video_info(video_path)
    roi = roi_px(roi_frac, info.width, info.height)
    t_end = info.duration_s if t_end is None else min(t_end, info.duration_s)
    counts: list[tuple[float, int]] = []
    with open_video(video_path) as cap:
        prev_mask = None
        for t, frame in iter_frames(cap, info.fps, t_start, t_end, step_s):
            m = feed_mask(crop(frame, roi))
            # count *newly lit* pixels vs previous sample (rising edge of content)
            new = int(np.count_nonzero(m & (1 - prev_mask))) if prev_mask is not None else 0
            counts.append((t, new))
            prev_mask = m
            if progress and len(counts) % 600 == 0:
                progress(t, t_end)
    if not counts:
        return []
    vals = np.array([c for _, c in counts], dtype=float)
    area = roi[2] * roi[3]
    if min_rise is None:
        # an entry is ~ a row of the ROI; require ~0.6 % of ROI newly lit and well above noise
        noise = np.median(vals) + 3 * (np.median(np.abs(vals - np.median(vals))) + 1)
        min_rise = max(0.006 * area, noise)
    onsets: list[float] = []
    last = -1e9
    for i, (t, c) in enumerate(counts):
        if c >= min_rise:
            # local peak & debounce 0.4 s (entries animate in over a few frames)
            nxt = counts[i + 1][1] if i + 1 < len(counts) else 0
            if c >= nxt and t - last > 0.4:
                onsets.append(t)
                last = t
    return onsets


# ---------------------------------------------------------------------------
# 2./3. offset estimation
# ---------------------------------------------------------------------------
def _match_count(kill_s: np.ndarray, onsets: np.ndarray, offset: float, tol: float) -> tuple[int, list[float]]:
    res = []
    for k in kill_s:
        t = k + offset
        j = bisect_left(onsets, t)
        best = None
        for jj in (j - 1, j):
            if 0 <= jj < len(onsets):
                d = onsets[jj] - t
                if abs(d) <= tol and (best is None or abs(d) < abs(best)):
                    best = d
        if best is not None:
            res.append(best)
    return len(res), res


def estimate_offset(kill_times_s: list[float], onsets: list[float], bin_s: float = 0.2,
                    tol: float = 0.5) -> tuple[float, int]:
    if not kill_times_s or not onsets:
        raise ValueError("Need kills and kill-feed onsets to estimate an offset")
    k = np.asarray(sorted(kill_times_s))
    o = np.asarray(sorted(onsets))
    diffs = (o[None, :] - k[:, None]).ravel()
    lo, hi = diffs.min(), diffs.max()
    nbins = max(1, int((hi - lo) / bin_s) + 1)
    hist, edges = np.histogram(diffs, bins=nbins, range=(lo, lo + nbins * bin_s))
    # smooth with 3-bin window so a peak split across bins still wins
    smooth = np.convolve(hist, np.ones(3), mode="same")
    peak = int(np.argmax(smooth))
    coarse = (edges[peak] + edges[peak + 1]) / 2
    n, res = _match_count(k, o, coarse, tol)
    fine = coarse + (float(np.median(res)) if res else 0.0)
    n2, _ = _match_count(k, o, fine, tol)
    return (fine, n2) if n2 >= n else (coarse, n)


def sync_vod(match: Match, video_path: str, roi_frac: list[float], step_s: float = 0.1,
             progress=None) -> SyncResult:
    onsets = detect_killfeed_onsets(video_path, roi_frac, step_s=step_s, progress=progress)
    info = video_info(video_path)
    kill_s = [k.t_match_ms / 1000 for k in match.kills]
    offset, n = estimate_offset(kill_s, onsets)
    res = SyncResult(global_offset_s=round(offset, 3), matched_kills=n, total_kills=len(kill_s),
                     method="auto", vod_duration_s=info.duration_s)
    refine_per_round(res, match, onsets)
    return res


def sync_from_anchor(match: Match, video_path: str, round_number: int, kill_number: int,
                     vod_time_s: float, roi_frac: list[float] | None = None) -> SyncResult:
    """Manual anchor: 'kill #k of round #r happens at vod_time_s'. Optional refinement."""
    rnd = match.rounds[round_number - 1]
    if not rnd.kills or kill_number < 1 or kill_number > len(rnd.kills):
        raise ValueError(f"Round {round_number} has {len(rnd.kills)} kills")
    k = rnd.kills[kill_number - 1]
    offset = vod_time_s - k.t_match_ms / 1000
    info = video_info(video_path)
    res = SyncResult(global_offset_s=round(offset, 3), method="anchor",
                     total_kills=len(match.kills), vod_duration_s=info.duration_s)
    if roi_frac:
        onsets = detect_killfeed_onsets(video_path, roi_frac)
        o = np.asarray(sorted(onsets))
        res.matched_kills, _ = _match_count(np.array([kk.t_match_ms / 1000 for kk in match.kills]), o, offset, 0.5)
        refine_per_round(res, match, onsets)
    return res


def refine_per_round(res: SyncResult, match: Match, onsets: list[float],
                     window_s: float = 3.0, tol: float = 0.4) -> None:
    o = np.asarray(sorted(onsets))
    for rnd in match.rounds:
        ks = np.array([k.t_match_ms / 1000 for k in rnd.kills])
        if len(ks) < 2:
            continue
        best_off, best_n, best_res = res.global_offset_s, -1, []
        for d in np.arange(-window_s, window_s + 1e-9, 0.1):
            off = res.global_offset_s + d
            n, r = _match_count(ks, o, off, tol)
            if n > best_n or (n == best_n and abs(d) < abs(best_off - res.global_offset_s)):
                best_off, best_n, best_res = off, n, r
        if best_n >= max(2, int(0.5 * len(ks))):
            res.per_round_offset_s[rnd.index] = round(best_off + (float(np.median(best_res)) if best_res else 0), 3)
