"""Team › Practice › Scrims: the team's scrim log (stats/scrims.py). Everyone in the team adds scrims and reads them;
a scrim can be changed or removed by whoever wrote it and by the team owner."""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, url_for

from ..stats import scrims as sc

_lock = threading.Lock()


def register(app, store, sr, get_team, known_maps: list[str]) -> None:
    def path(tid: int) -> Path:
        return sr.team_dir(tid) / "scrims.json"

    def read(tid: int) -> dict:
        try:
            return json.loads(path(tid).read_text())
        except (OSError, ValueError):
            return {}

    def write(tid: int, d: dict) -> None:
        p = path(tid)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False))
        tmp.replace(p)

    def maps_of(t) -> list[str]:
        return list(t.map_list) + sorted(set(known_maps) - set(t.map_list))

    def form_dict() -> dict:
        f = request.form
        return {**{k: f.get(k, "") for k in f}, "good": f.getlist("good"), "bad": f.getlist("bad")}

    @app.route("/teams/<int:tid>/scrims", methods=["GET", "POST"])
    def team_scrims(tid: int):
        t = get_team(tid)
        maps = maps_of(t)
        if request.method == "POST":
            s, err = sc.clean(form_dict(), maps)
            if s is None:
                flash(err, "error")
                return redirect(url_for("team_scrims", tid=tid) + "#add")
            with _lock:
                d = read(tid)
                sid = request.form.get("id", "")
                old = next((x for x in d.get("scrims", []) if x["id"] == sid), None) if sid else None
                if sid and old is None:
                    abort(404)
                if old is not None:
                    if old["uid"] != g.user.id and not g.team_owner:
                        abort(403)
                    old.update(s)
                    d["scrims"].sort(key=lambda x: (x["date"], x["at"]))
                    flash("Scrim saved.", "ok")
                else:
                    sc.add(d, s, g.user.id, g.user.display_name or g.user.username)
                    flash(f"Scrim against {s['opponent']} added.", "ok")
                write(tid, d)
            return redirect(url_for("team_scrims", tid=tid))
        d = read(tid)
        scrims = d.get("scrims", [])
        mp = request.args.get("map", "")
        opp = request.args.get("opp", "")
        shown = [s for s in scrims if (not mp or s["map"] == mp) and (not opp or s["opponent"].lower() == opp.lower())]
        sm = sc.summary(shown)
        edit = next((s for s in scrims if s["id"] == request.args.get("edit")), None)
        if edit and edit["uid"] != g.user.id and not g.team_owner:
            edit = None
        return render_template("team_scrims.html", t=t, tab="scrims", scrims=list(reversed(shown)), n_all=len(scrims), sm=sm,
                               tend=sc.tendencies(sm), maps=maps, topics=sc.TOPICS, sides=sc.SIDES, f_map=mp, f_opp=opp,
                               edit=edit, result=sc.result, today=date.today().isoformat(), opponents=sorted({s["opponent"] for s in scrims}, key=str.lower))

    @app.post("/teams/<int:tid>/scrims/<sid>/delete")
    def team_scrim_delete(tid: int, sid: str):
        get_team(tid)
        with _lock:
            d = read(tid)
            s = next((x for x in d.get("scrims", []) if x["id"] == sid), None)
            if s is None:
                abort(404)
            if s["uid"] != g.user.id and not g.team_owner:
                abort(403)
            d["scrims"] = [x for x in d["scrims"] if x["id"] != sid]
            write(tid, d)
        flash("Scrim removed.", "ok")
        return redirect(url_for("team_scrims", tid=tid))
