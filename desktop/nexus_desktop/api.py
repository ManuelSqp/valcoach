"""Talking to a Nexus server with this PC's device key (the website gives it to the app, see app.py): the
/api/companion/... calls."""
from __future__ import annotations

import os
from pathlib import Path

import requests

from . import __version__

TIMEOUT = 30
UA = f"nexus/{__version__}"


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _err(r: requests.Response) -> ApiError:
    try:
        msg = r.json().get("error") or ""
    except ValueError:
        msg = ""
    if r.status_code == 401 and not msg:
        msg = "Not logged in"
    return ApiError(msg or f"The server answered HTTP {r.status_code}", r.status_code)


class Api:
    def __init__(self, server: str, token: str = "", session: requests.Session | None = None):
        self.server = server.rstrip("/")
        self.token = token
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = UA

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.s.request(method, self.server + path, headers=self._h(), timeout=kw.pop("timeout", TIMEOUT), **kw)
        except requests.RequestException as e:
            raise ApiError(f"The server isn't reachable ({e.__class__.__name__})") from None
        if not r.ok:
            raise _err(r)
        try:
            return r.json()
        except ValueError:
            raise ApiError("The server didn't answer like Nexus (check the address)") from None

    # ---------------------------------------------------------------- account
    def logout(self) -> None:
        try:
            self._call("POST", "/api/companion/logout")
        except ApiError:
            pass
        self.token = ""

    def me(self) -> dict:
        return self._call("GET", "/api/companion/me")

    # ---------------------------------------------------------------- KovaaK's
    def playlists(self, pid: int) -> list[dict]:
        return self._call("GET", f"/api/companion/players/{int(pid)}/playlists")["playlists"]

    def send_stats(self, pid: int, files: list[Path]) -> dict:
        parts = [("files", (f.name, f.read_bytes(), "text/csv")) for f in files]
        return self._call("POST", f"/api/companion/players/{int(pid)}/kovaaks", files=parts, timeout=120)

    # ---------------------------------------------------------------- recordings
    def matches(self, pid: int) -> list[dict]:
        return self._call("GET", f"/api/companion/players/{int(pid)}/matches", timeout=90)["matches"]

    def upload_clip(self, pid: int, match_id: str, path: Path, source: str, progress=lambda done, total: None) -> dict:
        """Send the file in pieces (the server takes no big requests), then attach it to the match."""
        size = os.path.getsize(path)
        up = self._call("POST", "/api/companion/uploads", json={"name": f"{match_id}.mp4", "size": size})
        chunk, done = int(up["chunk"]), 0
        with open(path, "rb") as f:
            while done < size:
                f.seek(done)
                data = f.read(chunk)
                try:
                    r = self.s.put(f"{self.server}/api/companion/uploads/{up['id']}", params={"offset": done}, data=data,
                                   headers=self._h(), timeout=300)
                except requests.RequestException as e:
                    raise ApiError(f"The upload stopped ({e.__class__.__name__})") from None
                if r.status_code == 409:                  # the server has a different position: go on from there
                    received = (r.json() or {}).get("received")
                    if received is None:
                        raise _err(r)
                    done = int(received)
                    continue
                if not r.ok:
                    raise _err(r)
                done = int(r.json()["received"])
                progress(done, size)
        return self._call("POST", f"/api/companion/players/{int(pid)}/clips",
                          json={"match_id": match_id, "upload_id": up["id"], "source": source})
