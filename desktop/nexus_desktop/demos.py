"""VALORANT's replay files (4.9): after you download a replay in the game (match history), it is saved as a
.vrf file in %LOCALAPPDATA%\\VALORANT\\Saved\\Demos. The app sends new ones to Nexus, where they give the coach
every player's position for the whole match. The server reads the match id from inside the file."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SETTLE_S = 60                     # a file changed in the last minute may still be downloading
MAX_BYTES = 512 * 1024 ** 2


def default_dir() -> str:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return ""
    p = Path(base) / "VALORANT" / "Saved" / "Demos"
    return str(p) if p.is_dir() else ""


def find(root: Path, since: float, now: float | None = None) -> list[Path]:
    """Replay files in the folder that are new since `since` and finished downloading, oldest first."""
    now = now or time.time()
    out = []
    try:
        files = list(Path(root).glob("*.vrf"))
    except OSError:
        return []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        if st.st_mtime < since or now - st.st_mtime < SETTLE_S or not 0 < st.st_size <= MAX_BYTES:
            continue
        out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime)


def key(f: Path) -> str:
    """Name + size + time: the same replay downloaded again (a new file) is sent again only if it changed."""
    st = f.stat()
    return f"{f.name}:{st.st_size}:{int(st.st_mtime)}"


def match_id(f: Path) -> str:
    m = UUID_RE.search(f.name)
    return m.group(0).lower() if m else ""
