"""Practice › Sound (per player): hearing where a sound comes from. The page plays and scores the sounds in the
browser (static/sound.js); the server keeps the results (stats/sound.py)."""
from __future__ import annotations

from pathlib import Path

from flask import abort, g, jsonify, render_template, request

from ..stats import sound as so
from .aim import _lock, _read, _write


def register(app, store, sr, view_profile) -> None:
    def path(pid: int) -> Path:
        return sr.games(pid).path.parent / "sound.json"

    def can_save(p, can_edit: bool) -> bool:
        if can_edit:
            return True
        return any(m["pid"] == p.id and m.get("user_id") == g.user.id
                   for t in store.teams_for_user(g.user.id) for m in t.member_list)

    @app.get("/profiles/<int:pid>/sound")
    def sound_trainer(pid: int):
        p, can_edit = view_profile(pid)
        d = _read(path(pid), {})
        boot = {"sounds": so.SOUNDS, "can_save": can_save(p, can_edit), "save": f"/profiles/{pid}/sound/runs"}
        return render_template("sound.html", p=p, active_pid=pid, boot=boot, s=so.summary(d), modes=so.MODES)

    @app.post("/profiles/<int:pid>/sound/runs")
    def sound_run(pid: int):
        p, can_edit = view_profile(pid)
        if not can_save(p, can_edit):
            abort(403)
        run = so.clean_run(request.get_json(silent=True) or {})
        if run is None:
            return jsonify(error="That round doesn't add up."), 400
        with _lock:
            d = _read(path(pid), {})
            res = so.add_run(d, run)
            _write(path(pid), d)
        s = so.summary(d)
        return jsonify(ok=True, **res, err=run["err"], fb=run["fb"], worst=s["worst"])
