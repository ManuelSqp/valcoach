"""VOD uploads in chunks.

Waitress reads a whole request body into a temp file before the app sees it, so a limit inside a
view can't stop a big upload, and an unlimited body would let anyone fill the disk without logging
in. So no request may be big: the browser first asks to start (size, quota and free disk are checked
before a single byte is sent), then sends the file in small pieces, each one from a logged-in user.

Parts live in data/tmp and are only tracked in memory: a restart clears them.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from werkzeug.utils import secure_filename

CHUNK_BYTES = 16 * 1024 ** 2
MAX_REQUEST_BYTES = CHUNK_BYTES + 1024 ** 2      # body limit of every request
MIN_FREE_DISK = 1024 ** 3                        # keep this much disk free after an upload
MAX_OPEN_PER_USER = 2
STALE_S = 6 * 3600                               # abandoned uploads (tab closed) are removed


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400, received: int | None = None):
        super().__init__(message)
        self.status = status
        self.received = received


@dataclass
class Upload:
    id: str
    owner: int
    name: str
    size: int
    path: Path
    received: int = 0
    touched: float = 0.0
    busy: bool = False


class Uploads:
    def __init__(self, tmp_dir: Path):
        self.dir = Path(tmp_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        for left in self.dir.glob("*"):
            left.unlink(missing_ok=True)       # parts of uploads cut off by a crash or restart (can be GBs)
        self._open: dict[str, Upload] = {}
        self._lock = threading.Lock()

    def _drop(self, u: Upload) -> None:
        self._open.pop(u.id, None)
        u.path.unlink(missing_ok=True)

    def _get(self, owner: int, upload_id: str) -> Upload:
        u = self._open.get(upload_id)
        if u is None or u.owner != owner:
            raise UploadError("This upload doesn't exist anymore. Start it again.", 404)
        return u

    def begin(self, owner: int, name: str, size: int) -> Upload:
        now = time.time()
        with self._lock:
            for u in [u for u in self._open.values() if not u.busy and now - u.touched > STALE_S]:
                self._drop(u)
            mine = sorted((u for u in self._open.values() if u.owner == owner and not u.busy), key=lambda u: u.touched)
            for u in mine[:max(0, len(mine) - MAX_OPEN_PER_USER + 1)]:
                self._drop(u)                  # e.g. the page was reloaded mid-upload
            reserved = sum(u.size - u.received for u in self._open.values())
            if shutil.disk_usage(self.dir).free - reserved - size < MIN_FREE_DISK:
                raise UploadError("Not enough free disk space on the server for this upload.", 507)
            uid = uuid.uuid4().hex
            u = Upload(uid, owner, name, size, self.dir / f"{uid}.part", touched=now)
            u.path.touch()
            self._open[uid] = u
            return u

    def write(self, owner: int, upload_id: str, offset: int, stream, length: int | None) -> int:
        """Store one piece and return the bytes received so far. A client that lost an answer gets
        409 with the real position and goes on from there."""
        with self._lock:
            u = self._get(owner, upload_id)
            if u.busy or offset != u.received:
                raise UploadError("Wrong position in the upload.", 409, u.received)
            if not length or length > CHUNK_BYTES or offset + length > u.size:
                raise UploadError("Bad chunk size.", 400)
            u.busy = True
        received = offset
        try:
            with u.path.open("r+b") as f:
                f.seek(offset)
                left = length
                while left:
                    data = stream.read(min(left, 1024 ** 2))
                    if not data:
                        break
                    f.write(data)
                    left -= len(data)
                if left:                       # connection lost: forget the partial piece
                    f.truncate(offset)
                    raise UploadError("The chunk arrived incomplete.", 400)
            received = offset + length
        except OSError as e:
            os.truncate(u.path, offset)
            raise UploadError(f"The server could not store the upload: {e.strerror}", 507) from e
        finally:
            with self._lock:
                u.busy = False
                u.received = received
                u.touched = time.time()
        return received

    def finish(self, owner: int, upload_id: str, dest_dir: Path) -> tuple[Path, str]:
        """Move a complete upload into dest_dir (same disk: instant) -> (new path, original file name)."""
        with self._lock:
            u = self._get(owner, upload_id)
            if u.busy or u.received != u.size:
                raise UploadError("The upload isn't complete.", 409, u.received)
            dest = dest_dir / f"{uuid.uuid4().hex[:8]}_{secure_filename(u.name)}"
            os.replace(u.path, dest)
            del self._open[upload_id]
            return dest, u.name
