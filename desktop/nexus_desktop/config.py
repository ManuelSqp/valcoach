"""Settings and what was done already, in %APPDATA%\\Nexus\\config.json. The device key is kept in
Windows' Credential Manager (keyring), never in the file.

Up to 4.4 the app was "valcoach companion": its folder (%APPDATA%\\valcoach-companion) is copied over once and its
key in the Credential Manager is still found."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "Nexus"
OLD_APP = "valcoach-companion"                  # the name up to 4.4 (folder and Credential Manager entry)
_save_lock = threading.Lock()


def folder() -> Path:
    base = Path(os.environ.get("APPDATA") or str(Path.home() / ".config"))
    p = base / APP
    old = base / OLD_APP
    if not p.exists() and old.is_dir():
        try:
            shutil.copytree(old, p)                  # settings, what was done, a key file: once, the old folder stays
        except OSError:
            pass
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Settings:
    server: str = ""
    user: str = ""
    player_id: int = 0
    player_name: str = ""
    medal_dir: str = ""
    kovaaks_dir: str = ""
    put_playlists: bool = True
    send_scores: bool = True
    upload_matches: bool = True
    only_coachable: bool = True
    demos_dir: str = ""                  # VALORANT's replay files (4.9): %LOCALAPPDATA%\VALORANT\Saved\Demos
    send_replays: bool = True
    autostart: bool = False
    check_updates: bool = True
    last_update_check: float = 0.0
    every_min: int = 5
    since: float = field(default_factory=lambda: time.time() - 86400)   # older recordings and scores are left alone
    # what was done: recording name -> {"state": "done"|"waiting"|"skipped", "why": ..., "matches": [...]}
    recordings: dict = field(default_factory=dict)
    stats_sent: list = field(default_factory=list)                       # stats file names sent already
    # replay files: demos.key(file) -> {"state": "done"|"skipped", "match_id": ..., "why": ...}
    replays: dict = field(default_factory=dict)
    last_playlists: str = ""                                              # the day playlists were last written


def load() -> Settings:
    p = folder() / "config.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
    return Settings(**known)


def save(s: Settings) -> None:
    """Write the settings (the window and the sync both save: one at a time, never a half-written file)."""
    with _save_lock:
        s.stats_sent = s.stats_sent[-5000:]
        if len(s.recordings) > 500:
            for k in sorted(s.recordings)[:-500]:
                s.recordings.pop(k)
        if len(s.replays) > 500:
            for k in list(s.replays)[:-500]:
                s.replays.pop(k)
        p = folder() / "config.json"
        tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(asdict(s), indent=1), encoding="utf-8")
        tmp.replace(p)


def _token_file(server: str) -> Path:
    import hashlib
    return folder() / f"key-{hashlib.sha256(server.encode()).hexdigest()[:12]}.txt"


def get_token(server: str) -> str:
    """The device key: from the Credential Manager, else (no keyring on this system) from a file next to the
    settings that only this user can read."""
    try:
        import keyring
        for service in (APP, OLD_APP):
            t = keyring.get_password(service, server)
            if t:
                return t
    except Exception:
        pass
    try:
        return _token_file(server).read_text().strip()
    except OSError:
        return ""


def set_token(server: str, token: str) -> None:
    try:
        import keyring
        if token:
            keyring.set_password(APP, server, token)
            _token_file(server).unlink(missing_ok=True)
            try:
                keyring.delete_password(OLD_APP, server)
            except Exception:
                pass
            return
        for service in (APP, OLD_APP):
            try:
                keyring.delete_password(service, server)
            except Exception:
                pass
    except Exception:
        if token:                                  # no Credential Manager / keyring here: a private file
            f = _token_file(server)
            f.write_text(token)
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
            return
    _token_file(server).unlink(missing_ok=True)
