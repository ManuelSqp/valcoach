"""Practice › Callouts (per player): the minimap quiz. The page does the quiz in the browser (static/callouts.js);
the server gives it the maps and callouts and keeps the results (stats/callouts.py)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from flask import abort, g, jsonify, render_template, request

from ..maps import MapRegistry
from ..stats import callouts as co
from .aim import _lock, _read, _write


def register(app, store, sr, view_profile, filter_rows, known_maps: list[str]) -> None:
    reg = MapRegistry(store.data_dir / "cache")

    def path(pid: int) -> Path:
        return sr.games(pid).path.parent / "callouts.json"

    def can_save(p, can_edit: bool) -> bool:
        if can_edit:
            return True
        return any(m["pid"] == p.id and m.get("user_id") == g.user.id
                   for t in store.teams_for_user(g.user.id) for m in t.member_list)

    def maps_for(pid: int) -> tuple[dict, list[str]]:
        """The quiz maps, the ones this player plays most first."""
        played = Counter(r.get("map") for r in filter_rows(sr.games(pid).rows(), "everything"))
        order = sorted(set(known_maps) | {m for m in played if m}, key=lambda m: (-played.get(m, 0), m))
        return co.quiz_maps(reg, order), [m for m in order if played.get(m)]

    @app.get("/profiles/<int:pid>/callouts")
    def callouts(pid: int):
        p, can_edit = view_profile(pid)
        maps, played = maps_for(pid)
        d = _read(path(pid), {})
        pick = request.args.get("map")
        cur = pick if pick in maps else next(iter(maps), "")
        boot = {"maps": {m: {"points": pts, "weights": co.weights(d, m, pts), "weak": co.weak(d, m)} for m, pts in maps.items()},
                "map": cur, "questions": co.QUESTIONS, "can_save": can_save(p, can_edit),
                "save": f"/profiles/{pid}/callouts/runs", "image": "/map-image/"}
        return render_template("callouts.html", p=p, active_pid=pid, boot=boot, maps=list(maps), cur=cur, played=set(played),
                               summary=co.summary(d, maps), modes=co.MODES, n_runs=len(d.get("runs", [])))

    @app.post("/profiles/<int:pid>/callouts/runs")
    def callouts_run(pid: int):
        p, can_edit = view_profile(pid)
        if not can_save(p, can_edit):
            abort(403)
        maps, _ = maps_for(pid)
        run = co.clean_run(request.get_json(silent=True) or {}, maps)
        if run is None:
            return jsonify(error="That round doesn't add up."), 400
        with _lock:
            d = _read(path(pid), {})
            res = co.add_run(d, run)
            _write(path(pid), d)
        m = run["map"]
        row = next(x for x in co.summary(d, maps) if x["map"] == m)
        return jsonify(ok=True, **res, known=row["known"], n=row["n"], weights=co.weights(d, m, maps[m]), weak=co.weak(d, m))
