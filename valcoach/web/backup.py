"""Nightly backups of everything people typed into valcoach (Settings › Backups).

One .tar.gz per night with the database (a consistent copy made with SQLite's backup API, safe
while valcoach runs), players, teams, notes, strats and reports. Left out because they can be
rebuilt or are huge: the match cache, uploaded VODs, clips and unfinished uploads. The newest
`keep` backups stay; older ones are deleted. Point the folder at your NAS so a dead disk can't
take the backups with it.

Restore: stop valcoach, unpack the archive into the data folder (it contains valcoach.db,
profiles/, teams/, reports/ ...), start valcoach again."""
from __future__ import annotations

import errno
import json
import os
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {"cache", "backups", "tmp", "uploads", "clips", "__pycache__"}
SKIP_SUFFIX = {".mp4", ".mkv", ".mov", ".webm", ".part", ".tmp"}
PREFIX = "valcoach-backup-"


def backup_dir(store) -> Path:
    d = (store.get("backup_dir") or "").strip()
    return Path(d).expanduser() if d else store.data_dir / "backups"


def _keep(store) -> int:
    try:
        return max(1, min(365, int(store.get("backup_keep") or 14)))
    except ValueError:
        return 14


def explain(e: BaseException, folder: Path | str) -> str:
    """A failed write in words: a read-only folder is almost always the service's sandbox, not the disk."""
    if isinstance(e, OSError) and e.errno in (errno.EROFS, errno.EACCES, errno.EPERM):
        why = "is read-only for valcoach" if e.errno == errno.EROFS else "isn't writable for the user valcoach runs as"
        return (f"The backup folder {folder} {why}. If valcoach runs as a systemd service, it may only write to its data "
                f"folder: add the line ReadWritePaths={folder} to the [Service] part of valcoach.service, then "
                "sudo systemctl daemon-reload and sudo systemctl restart valcoach. Otherwise check the folder's owner "
                "(sudo chown) or leave the folder empty to keep backups in the data folder.")
    return str(e)[:300]


def check_folder(folder: Path | str) -> str:
    """'' when valcoach can write backups to this folder, else why not (for Settings)."""
    d = Path(folder).expanduser()
    if not d.is_dir():
        return f"Backup folder not found on this server: {folder}"
    probe = d / f".valcoach-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        return explain(e, folder)
    return ""


def list_backups(store) -> list[dict]:
    d = backup_dir(store)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob(f"{PREFIX}*.tar.gz"), reverse=True):
        try:
            out.append({"name": f.name, "size": f.stat().st_size, "time": f.stat().st_mtime})
        except OSError:
            continue
    return out


def make_backup(store) -> Path:
    data = store.data_dir
    dest = backup_dir(store)
    dest.mkdir(parents=True, exist_ok=True)
    name = f"{PREFIX}{datetime.now().strftime('%Y-%m-%d_%H%M')}.tar.gz"
    out = dest / name
    tmp = dest / (name + ".part")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "valcoach.db"
        src = sqlite3.connect(store.db_path)
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)                     # consistent copy while the app keeps writing
        finally:
            dst.close()
            src.close()
        with tarfile.open(tmp, "w:gz") as tar:
            tar.add(snap, arcname="valcoach.db")
            for p in sorted(data.iterdir()):
                if p.name in SKIP_DIRS or p.name.startswith("valcoach.db") or p.resolve() == dest.resolve():
                    continue
                if p.is_file():
                    if p.suffix not in SKIP_SUFFIX:
                        tar.add(p, arcname=p.name)
                    continue

                def keep(ti: tarfile.TarInfo):
                    parts = set(Path(ti.name).parts)
                    if parts & SKIP_DIRS or Path(ti.name).suffix in SKIP_SUFFIX:
                        return None
                    return ti
                tar.add(p, arcname=p.name, filter=keep)
    tmp.replace(out)
    for old in list_backups(store)[_keep(store):]:   # newest first: drop the rest
        (dest / old["name"]).unlink(missing_ok=True)
    return out


def run(store) -> dict:
    """Make a backup now; remember the result for Settings and the server overview."""
    t0 = time.time()
    try:
        f = make_backup(store)
        res = {"ok": True, "at": time.time(), "file": f.name, "size": f.stat().st_size, "secs": round(time.time() - t0, 1)}
    except Exception as e:
        res = {"ok": False, "at": time.time(), "error": explain(e, backup_dir(store))[:600]}
    store.set("backup_last", json.dumps(res))
    return res


def last(store) -> dict:
    try:
        return json.loads(store.get("backup_last") or "{}")
    except ValueError:
        return {}


def tick(store, now: datetime | None = None) -> bool:
    """Once a night from 04:00 (after the nightly sync); catches up later if the server was off."""
    if store.get("backup_on") != "1":
        return False
    now = now or datetime.now()
    l = last(store)
    done_today = l.get("at") and datetime.fromtimestamp(l["at"]).date() == now.date() and l.get("ok")
    tried_recently = l.get("at") and time.time() - l["at"] < 3600
    if now.hour >= 4 and not done_today and not tried_recently:
        run(store)
        return True
    return False
