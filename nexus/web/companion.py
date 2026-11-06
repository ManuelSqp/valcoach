"""The companion app's side of Nexus (4.3): a small app on each player's Windows PC that
- puts the coach's KovaaK's playlists into KovaaK's Playlists folder (if the player turns that on),
- sends new KovaaK's scores from the stats folder,
- cuts the matches out of Medal session recordings and uploads them, so the VOD is ready on the match's
  report page ("Recording (VOD)": the clip from the companion app is picked already).

The app logs in once with username and password and gets a key for this one device (Account › Devices lists
and removes them; changing the password logs every device out). Every call sends that key as
"Authorization: Bearer vc_..."; it only works for /api/companion/..., never for the web pages.

Clips are kept in data/companion/<user>/ until a report used them (then they're deleted like any uploaded VOD)
or for `companion_keep_days` days (Settings; default 14).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from flask import abort, g, jsonify, render_template, request

from .. import __version__, pipeline
from ..henrik import HenrikError
from .uploads import CHUNK_BYTES, UploadError

DEVICE_NAME_MAX = 60
APP_DOWNLOAD = "https://github.com/ManuelSqp/valcoach/releases/latest"
MAX_KOVAAKS_FILES = 200
MAX_KOVAAKS_BYTES = 8 * 1024 ** 2
_lock = threading.Lock()
log = logging.getLogger(__name__)


def clips_dir(store, uid: int) -> Path:
    return store.data_dir / "companion" / str(int(uid))


def _index_path(store, uid: int) -> Path:
    return clips_dir(store, uid) / "index.json"


def read_index(store, uid: int) -> dict:
    try:
        d = json.loads(_index_path(store, uid).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(store, uid: int, d: dict) -> None:
    p = _index_path(store, uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(p)


def prune(store, uid: int) -> int:
    """Forget clips whose file is gone (a report used it) and delete ones older than companion_keep_days."""
    keep_s = max(1, int(store.get("companion_keep_days") or 14)) * 86400
    removed = 0
    with _lock:
        d = read_index(store, uid)
        for mid, c in list(d.items()):
            f = clips_dir(store, uid) / c.get("file", "")
            if not f.is_file():
                d.pop(mid)
            elif time.time() - float(c.get("at", 0)) > keep_s:
                f.unlink(missing_ok=True)
                d.pop(mid)
                removed += 1
        _write_index(store, uid, d)
    return removed


def clip_for(store, uid: int, match_id: str) -> dict | None:
    """The companion app's clip of this match for this user: {path, name, size, at} or None."""
    c = read_index(store, uid).get(match_id)
    if not c:
        return None
    f = clips_dir(store, uid) / c.get("file", "")
    return dict(c, path=str(f)) if f.is_file() else None


def register(app, store, uploads, check_login) -> None:
    def own_player(pid: int):
        p = store.profile(pid)
        if p is None or p.owner_id != g.user.id:
            abort(404)
        return p

    @app.post("/api/companion/login")
    def companion_login():
        b = request.get_json(silent=True) or {}
        user, err, code = check_login(str(b.get("username") or "").strip(), str(b.get("password") or ""))
        if user is None:
            return jsonify(error=err), code
        name = " ".join(str(b.get("device") or "Nexus app").split())[:DEVICE_NAME_MAX]
        return jsonify(token=store.add_device(user.id, name), user=user.display_name or user.username)

    # ---- the Nexus app for Windows (4.5): it shows these pages in its own window ----------------------------
    @app.post("/account/devices/pair")
    def device_pair():
        """The Nexus app on this PC asks for its device key with the session it is logged in with (same-site
        POST, so the CSRF check applies). The page passes the key straight to the app."""
        b = request.get_json(silent=True) or {}
        name = " ".join(str(b.get("device") or "Nexus app").split())[:DEVICE_NAME_MAX] or "Nexus app"
        return jsonify(token=store.add_device(g.user.id, name), user=g.user.username)

    @app.get("/this-pc")
    def this_pc():
        """Folders, switches and activity of the Nexus app on this PC. The page fills itself from the app (it
        only works inside the app; in a browser it says where to get the app)."""
        players = [{"id": p.id, "riot_id": f"{p.name}#{p.tag}"} for p in store.profiles(g.user.id)]
        return render_template("this_pc.html", players=players, download=APP_DOWNLOAD)

    @app.post("/api/companion/logout")
    def companion_logout():
        store.delete_device(g.user.id, g.device_id)
        return jsonify(ok=True)

    @app.get("/api/companion/me")
    def companion_me():
        players = [{"id": p.id, "name": p.name, "tag": p.tag, "riot_id": f"{p.name}#{p.tag}"}
                   for p in store.profiles(g.user.id)]
        return jsonify(user=g.user.display_name or g.user.username, version=__version__, players=players,
                       chunk=CHUNK_BYTES, max_upload_gb=float(store.get("max_upload_gb") or 20))

    @app.get("/api/companion/players/<int:pid>/playlists")
    def companion_playlists(pid: int):
        """The coach's warm-up and training playlist for KovaaK's, dated in name and file name."""
        p = own_player(pid)
        aim = app.extensions["nexus"]["aim"]
        return jsonify(playlists=aim["playlist_files"](pid, g.user.id, p.name))

    @app.post("/api/companion/players/<int:pid>/kovaaks")
    def companion_kovaaks(pid: int):
        """New stats files from KovaaK's stats folder (multipart, field "files")."""
        own_player(pid)
        fs = request.files.getlist("files")[:MAX_KOVAAKS_FILES]
        files, total = [], 0
        for fh in fs:
            data = fh.read(MAX_KOVAAKS_BYTES + 1)
            total += len(data)
            if len(data) > MAX_KOVAAKS_BYTES or total > 4 * MAX_KOVAAKS_BYTES:
                return jsonify(error="Too much at once: send fewer files."), 413
            files.append((os.path.basename(fh.filename or ""), data))
        runs, new, learned, bad = app.extensions["nexus"]["aim"]["import_runs"](pid, g.user.id, files)
        return jsonify(read=len(runs), new=new, scenarios_learned=learned, unreadable=bad)

    @app.get("/api/companion/players/<int:pid>/matches")
    def companion_matches(pid: int):
        """The player's recent matches with start (UTC) and length, so the app can find them in a recording.
        has_clip: a clip of it was uploaded already."""
        p = own_player(pid)
        try:
            rows = pipeline.history(store.build_config(p), size=10)
        except (HenrikError, ValueError, requests.RequestException) as e:
            log.warning("companion: match list for player %s: %s", pid, e)
            return jsonify(error="Couldn't load the matches from HenrikDev right now. Try again later."), 502
        have = read_index(store, g.user.id)
        out = []
        for r in rows:
            try:
                start = datetime.fromisoformat(str(r["started_at"]).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            out.append({"match_id": r["match_id"], "start": start, "length_s": r.get("length_s") or 0,
                        "map": r["map"], "queue": r["queue"], "score": r["score"], "agent": r["agent"],
                        "coachable": r["coachable"], "has_clip": r["match_id"] in have})
        return jsonify(matches=out)

    # chunked upload like the web page's, then attach the finished file to a match
    @app.post("/api/companion/uploads")
    def companion_upload_begin():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get("size")) is not int or data["size"] <= 0:
            raise UploadError("expected {\"name\": file name, \"size\": bytes}")
        name = os.path.basename(str(data.get("name") or "match.mp4"))
        if Path(name).suffix.lower() != ".mp4":
            raise UploadError("The Nexus app uploads mp4 files.")
        if data["size"] > float(store.get("max_upload_gb") or 20) * 1024 ** 3:
            raise UploadError(f"The clip is too big (limit {store.get('max_upload_gb')} GB, set by the admin).", 413)
        return jsonify(id=uploads.begin(g.user.id, name, data["size"]).id, chunk=CHUNK_BYTES)

    @app.put("/api/companion/uploads/<upload_id>")
    def companion_upload_chunk(upload_id: str):
        offset = request.args.get("offset", "")
        if not offset.isdigit():
            raise UploadError("offset missing")
        return jsonify(received=uploads.write(g.user.id, upload_id, int(offset), request.stream, request.content_length))

    @app.post("/api/companion/players/<int:pid>/clips")
    def companion_clip(pid: int):
        """A finished upload is the recording of this match."""
        own_player(pid)
        b = request.get_json(silent=True) or {}
        mid = str(b.get("match_id") or "")
        if not pipeline.valid_match_id(mid):
            return jsonify(error="That isn't a match ID."), 400
        d = clips_dir(store, g.user.id)
        d.mkdir(parents=True, exist_ok=True)
        dest, _ = uploads.finish(g.user.id, str(b.get("upload_id") or ""), d)
        final = d / f"{mid}.mp4"
        os.replace(dest, final)
        with _lock:
            idx = read_index(store, g.user.id)
            idx[mid] = {"file": final.name, "pid": pid, "size": final.stat().st_size, "at": time.time(),
                        "name": str(b.get("source") or "")[:120]}
            _write_index(store, g.user.id, idx)
        prune(store, g.user.id)
        return jsonify(ok=True, url=f"/profiles/{pid}/coach/{mid}")
