"""KovaaK's folders: where the game is installed, writing the coach's playlists, finding new stats files."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

GAME = Path("steamapps") / "common" / "FPSAimTrainer" / "FPSAimTrainer"


def steam_libraries() -> list[Path]:
    """Steam's library folders on this PC (from libraryfolders.vdf), the default one first."""
    roots = []
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / "Steam")
    libs: list[Path] = []
    for steam in roots:
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if steam.is_dir():
            libs.append(steam)
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p not in libs:
                libs.append(p)
    return libs


def find_game() -> Path | None:
    """KovaaK's game folder (the one with Saved and stats in it), or None."""
    for lib in steam_libraries():
        p = lib / GAME
        if p.is_dir():
            return p
    return None


def playlists_dir(game: Path) -> Path:
    return Path(game) / "Saved" / "SaveGames" / "Playlists"


def stats_dir(game: Path) -> Path:
    return Path(game) / "stats"


def write_playlists(folder: Path, files: list[dict]) -> list[str]:
    """Write the coach's playlists ({file_name, data}) into KovaaK's Playlists folder. Files with the same
    content are left alone; older dated ones stay. -> names written."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"KovaaK's Playlists folder not found: {folder}")
    written = []
    for f in files:
        name = os.path.basename(str(f.get("file_name") or ""))
        if not re.fullmatch(r"(?:nexus|valcoach)_[a-z]+_\d{2}-\d{2}-\d{4}\.json", name):
            continue                              # only the coach's own file names, never anything else
        text = json.dumps(f["data"], indent=2, ensure_ascii=False)
        p = folder / name
        try:
            if p.read_text(encoding="utf-8") == text:
                continue
        except OSError:
            pass
        tmp = p.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        written.append(name)
    return written


def new_stats(folder: Path, sent: set[str], since: float) -> list[Path]:
    """Stats files (*.csv) KovaaK's wrote after `since` that weren't sent yet, oldest first."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for f in folder.glob("*.csv"):
        try:
            if f.name not in sent and f.stat().st_mtime >= since:
                out.append(f)
        except OSError:
            continue
    return sorted(out, key=lambda f: f.stat().st_mtime)
