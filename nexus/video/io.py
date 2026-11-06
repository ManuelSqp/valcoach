"""Video helpers: fast seeking, ROI cropping."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@dataclass
class VideoInfo:
    path: str
    fps: float
    frames: int
    width: int
    height: int
    content: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))   # game picture (x, y, w, h)

    @property
    def duration_s(self) -> float:
        return self.frames / self.fps if self.fps else 0.0


@contextmanager
def open_video(path: str | Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {path}")
    try:
        yield cap
    finally:
        cap.release()


def video_info(path: str | Path) -> VideoInfo:
    with open_video(path) as cap:
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        info = VideoInfo(
            path=str(path),
            fps=cap.get(cv2.CAP_PROP_FPS) or 60.0,
            frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            width=w,
            height=h,
        )
    p = Path(path)
    info.content = content_box(str(p), p.stat().st_mtime if p.exists() else 0.0) or (0, 0, w, h)
    return info


@lru_cache(maxsize=32)
def content_box(path: str, mtime: float = 0.0, samples: int = 12) -> tuple[int, int, int, int] | None:
    """Where the game picture is inside the frame, without black bars: (x, y, w, h).
    A 16:9 game recorded on an ultrawide screen (e.g. 3440x1440) has black bars left and right,
    so areas given as a fraction of the frame width miss the minimap. A column/row counts as
    picture if any sampled frame is lit there. None if no frame could be read."""
    lit_x = lit_y = None
    with open_video(path) as cap:
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (0.05 + 0.9 * i / max(1, samples - 1))))
            ok, frame = cap.read()
            if not ok:
                continue
            lit = frame.max(axis=2) > 24
            cols, rows = lit.any(axis=0), lit.any(axis=1)
            lit_x = cols if lit_x is None else lit_x | cols
            lit_y = rows if lit_y is None else lit_y | rows
    if lit_x is None or not lit_x.any():
        return None
    h, w = len(lit_y), len(lit_x)
    xs, ys = np.flatnonzero(lit_x), np.flatnonzero(lit_y)
    x0, x1, y0, y1 = int(xs[0]), int(xs[-1]) + 1, int(ys[0]), int(ys[-1]) + 1
    if x1 - x0 < w // 2 or y1 - y0 < h // 2:        # mostly dark video: trust the full frame
        return 0, 0, w, h
    return x0, y0, x1 - x0, y1 - y0


def roi_px(roi_frac: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = roi_frac
    return int(x * width), int(y * height), max(1, int(w * width)), max(1, int(h * height))


def video_roi(roi_frac: list[float], info: VideoInfo) -> tuple[int, int, int, int]:
    """An area given as fractions of the game picture (black bars left out) -> frame pixels."""
    cx, cy, cw, ch = info.content if info.content[2] else (0, 0, info.width, info.height)
    x, y, w, h = roi_px(roi_frac, cw, ch)
    return cx + x, cy + y, w, h


def crop(frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = roi
    return frame[y:y + h, x:x + w]


def iter_frames(cap: cv2.VideoCapture, fps: float, t_start: float, t_end: float, step_s: float):
    """Yield (t_seconds, frame) sampled every step_s.

    Uses sequential grab() for short steps (cheap, no decode of skipped frames
    beyond grab) and direct seeking for long steps.
    """
    t_start = max(0.0, t_start)
    idx_start = int(round(t_start * fps))
    idx_end = int(round(t_end * fps))
    stride = max(1, int(round(step_s * fps)))
    if stride <= 30:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx_start)
        idx = idx_start
        while idx <= idx_end:
            ok, frame = cap.read()
            if not ok:
                return
            yield idx / fps, frame
            for _ in range(stride - 1):
                if not cap.grab():
                    return
            idx += stride
    else:
        for idx in range(idx_start, idx_end + 1, stride):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                return
            yield idx / fps, frame


def frame_at(cap: cv2.VideoCapture, fps: float, t: float) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t * fps))))
    ok, frame = cap.read()
    return frame if ok else None
