"""Settings and what was done already, in %APPDATA%\\valcoach-companion\\config.json. The device key is kept in
Windows' Credential Manager (keyring), never in the file."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "valcoach-companion"


def folder() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / APP
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
    autostart: bool = False
    every_min: int = 5
    since: float = field(default_factory=lambda: time.time() - 86400)   # older recordings and scores are left alone
    # what was done: recording name -> {"state": "done"|"waiting"|"skipped", "why": ..., "matches": [...]}
    recordings: dict = field(default_factory=dict)
    stats_sent: list = field(default_factory=list)                       # stats file names sent already
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
    s.stats_sent = s.stats_sent[-5000:]
    if len(s.recordings) > 500:
        for k in sorted(s.recordings)[:-500]:
            s.recordings.pop(k)
    p = folder() / "config.json"
    tmp = p.with_suffix(".tmp")
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
        t = keyring.get_password(APP, server)
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
            return
        try:
            keyring.delete_password(APP, server)
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
