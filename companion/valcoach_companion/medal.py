"""Medal session recordings: when they started, how long they are, which matches are in them, and cutting one out.

Medal names a recording after the moment it started, in local time, to the millisecond:
MedalTVValorant20260701203418498.mp4 -> 01.07.2026 20:34:18.498. A full-session recording starts when the game
starts (menu time included) and ends when it's closed, so it can hold several matches. Riot's match data has each
match's start (UTC) and length, so a match sits at (match start - recording start) seconds into the file.
Clips Medal saves separately get a suffix (...498-1774815019.mp4) and are ignored.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

NAME_RE = re.compile(r"^MedalTVValorant(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{3})\.mp4$", re.I)
DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
PRE_ROLL_S = 90          # the cut starts this much before the match (Riot's start and the file's clock differ a bit)
POST_ROLL_S = 60
MAX_CLOCK_GAP_S = 180    # start + length and the file's end time may differ this much; more = Medal paused
SETTLE_S = 120           # a recording counts as finished when it hasn't changed for this long
MIN_SIZE = 200 * 1024 ** 2


@dataclass
class Recording:
    path: Path
    start: float                 # unix time
    end: float                   # unix time (the file's last change = when the recording stopped)
    size: int

    @property
    def name(self) -> str:
        return self.path.name


def start_of(name: str) -> float | None:
    """Unix time a Medal recording started, from its name (local time of this PC), or None."""
    m = NAME_RE.match(name)
    if not m:
        return None
    y, mo, d, h, mi, s, ms = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s, ms * 1000).timestamp()      # naive = this PC's time zone (and DST)
    except ValueError:
        return None


def find(root: Path, since: float, now: float) -> list[Recording]:
    """Finished session recordings below root (up to 3 folders deep) that started after `since`."""
    out = []
    if not root or not Path(root).is_dir():
        return out
    for depth in ("", "*/", "*/*/", "*/*/*/"):
        for f in Path(root).glob(depth + "MedalTVValorant*.mp4"):
            start = start_of(f.name)
            if start is None or start < since:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if now - st.st_mtime < SETTLE_S or st.st_size < MIN_SIZE:
                continue                          # still recording, or too short to hold a match
            out.append(Recording(f, start, st.st_mtime, st.st_size))
    return sorted(out, key=lambda r: r.start)


def matches_in(rec: Recording, matches: list[dict]) -> list[dict]:
    """The matches (start: unix time, length_s) that lie inside this recording, each with where to cut:
    {match..., cut_from, cut_length}."""
    out = []
    for m in matches:
        start, length = float(m.get("start") or 0), float(m.get("length_s") or 0)
        if not start or not length:
            continue
        if start >= rec.start - 5 and start + length <= rec.end + POST_ROLL_S:
            cut_from = max(0.0, start - rec.start - PRE_ROLL_S)
            cut_to = min(rec.end - rec.start, start - rec.start + length + POST_ROLL_S)
            out.append(dict(m, cut_from=round(cut_from, 2), cut_length=round(cut_to - cut_from, 2)))
    return out


def clock_fits(rec: Recording, duration_s: float) -> bool:
    """Start + video length should land where the file stopped; if not, Medal paused or the clock is off."""
    return abs(rec.start + duration_s - rec.end) <= MAX_CLOCK_GAP_S


def _hide() -> dict:
    """No console window popping up for ffmpeg on Windows."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}       # CREATE_NO_WINDOW
    return {}


def duration(ffmpeg: str, path: Path) -> float | None:
    """The video's length in seconds (ffmpeg prints it; no ffprobe needed)."""
    p = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       errors="replace", timeout=60, **_hide())
    m = DURATION_RE.search(p.stderr or "")
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def cut(ffmpeg: str, src: Path, dest: Path, start_s: float, length_s: float) -> None:
    """Copy one part of the recording without re-encoding (fast, same quality; starts at the keyframe before)."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start_s:.2f}", "-i", str(src), "-t", f"{length_s:.2f}",
           "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", "-y", str(dest)]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=1800, **_hide())
    if p.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError("ffmpeg couldn't cut the match: " + (p.stderr or "").strip()[-300:])
