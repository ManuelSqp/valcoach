"""Video helpers: fast seeking, ROI cropping."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
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
        return VideoInfo(
            path=str(path),
            fps=cap.get(cv2.CAP_PROP_FPS) or 60.0,
            frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )


def roi_px(roi_frac: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = roi_frac
    return int(x * width), int(y * height), max(1, int(w * width)), max(1, int(h * height))


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
