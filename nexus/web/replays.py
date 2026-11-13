"""Replay files (.vrf) on the server (4.9): upload on the coach page, on the Replay files page (4.40, any match,
several at once) or from the Nexus app.

A replay is uploaded in pieces like a VOD (uploads.py), then vrfkit reads it once: the compact data and the
file are kept as data/replays/<match id>.json.gz and .vrf (see nexus/replayfile.py). One file serves every
player of that match, so it is stored per match, not per user; a coaching run of that match uses it when
Settings › Replay files › Positions is "Replay file".
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from flask import abort, g, jsonify, render_template, request

from .. import pipeline, replayfile
from .uploads import CHUNK_BYTES, UploadError

_ingest_lock = threading.Lock()      # vrfkit is quick, but one at a time keeps memory use predictable


def replays_dir(store) -> Path:
    return store.data_dir / "replays"


def begin_upload(store, uploads, uid: int, data) -> dict:
    """Checks for starting a .vrf upload; returns {id, chunk}."""
    if not isinstance(data, dict) or type(data.get("size")) is not int or data["size"] <= 0:
        raise UploadError("expected {\"name\": file name, \"size\": bytes}")
    name = os.path.basename(str(data.get("name") or ""))
    if Path(name).suffix.lower() != ".vrf":
        raise UploadError("That isn't a replay file (.vrf).")
    if data["size"] > replayfile.MAX_VRF_BYTES:
        raise UploadError("That file is too big for a replay file.", 413)
    return {"id": uploads.begin(uid, name, data["size"]).id, "chunk": CHUNK_BYTES}


def ingest_upload(store, uploads, uid: int, upload_id: str) -> dict:
    """A finished .vrf upload -> stored replay data. Returns replayfile.summary(); raises UploadError."""
    work = store.data_dir / "cache" / "vrf_work"
    work.mkdir(parents=True, exist_ok=True)
    dest, _ = uploads.finish(uid, upload_id, work)
    try:
        with _ingest_lock:
            return replayfile.ingest(dest, replays_dir(store), work,
                                     replayfile.vrfkit_path(store.get("vrfkit_path")))
    except replayfile.ReplayError as e:
        raise UploadError(str(e), 422)
    finally:
        Path(dest).unlink(missing_ok=True)       # moved into data/replays on success


def register(app, store, uploads, get_profile) -> None:
    @app.post("/api/replays")
    def replay_upload_begin():
        """Start a replay upload (JSON only, like /api/uploads); the pieces go to PUT /api/uploads/<id>."""
        return jsonify(**begin_upload(store, uploads, g.user.id, request.get_json(silent=True)))

    @app.post("/profiles/<int:pid>/coach/<match_id>/replay")
    def replay_attach(pid: int, match_id: str):
        """The finished upload is this match's replay file."""
        get_profile(pid)
        if not pipeline.valid_match_id(match_id):
            abort(404)
        b = request.get_json(silent=True) or {}
        info = ingest_upload(store, uploads, g.user.id, str(b.get("upload_id") or ""))
        if info["match_id"] != match_id.lower():
            # stored anyway (it's a real replay of another match), but say so
            return jsonify(ok=False, match_id=info["match_id"],
                           error="This replay file is from another match. It was kept for that match."), 409
        return jsonify(ok=True, **info)

    # ------------------------------------------------------------------ 4.40: Replay files page, upload any replay
    @app.post("/api/replays/<upload_id>/store")
    def replay_store(upload_id: str):
        """A finished upload is a replay of whichever match it is: no coaching run needed. -> the summary, the map
        if the match is known, and whether it's one of this player's matches (?pid=)."""
        info = ingest_upload(store, uploads, g.user.id, upload_id)
        mine = None
        pid = request.args.get("pid", type=int)
        if pid:
            app.extensions["nexus"]["view_profile"](pid)
            rows = {r.get("match_id", "").lower(): r for r in _rows(app, pid)}
            r = rows.get(info["match_id"])
            mine = bool(r)
            if r:
                info["map"] = r.get("map") or ""
                info["started_at"] = r.get("started_at") or ""
        return jsonify(ok=True, mine=mine, **info)

    @app.get("/profiles/<int:pid>/replays")
    def replay_files(pid: int):
        """Upload replay files (several at once, any match) and see which of your matches have one."""
        p, can_edit = app.extensions["nexus"]["view_profile"](pid)     # yours, or a teammate's: a replay is the match's
        d = replays_dir(store)
        have = set(replayfile.stored(d))
        rows = sorted(_rows(app, pid), key=lambda r: r.get("started_at") or "", reverse=True)
        with_replay = [r for r in rows if (r.get("match_id") or "").lower() in have]
        recent_missing = [r for r in rows[:RECENT] if (r.get("match_id") or "").lower() not in have]
        problem = replayfile.check_vrfkit(replayfile.vrfkit_path(store.get("vrfkit_path") or ""))
        return render_template("replay_files.html", p=p, active_pid=pid, can_edit=can_edit, with_replay=with_replay,
                               missing=recent_missing, total=len(have), others=len(have) - len(with_replay),
                               problem=problem, max_mb=replayfile.MAX_VRF_BYTES // 1024 ** 2, recent=RECENT)


RECENT = 15                         # the Replay files page lists your last this-many matches without a replay


def _rows(app, pid: int) -> list[dict]:
    try:
        return list(app.extensions["nexus"]["stats"].games(pid).rows())
    except Exception:                                    # no stats yet
        return []
