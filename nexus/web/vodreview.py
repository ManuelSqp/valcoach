"""VOD review (stats/vodreview.py): watch a report's match recording together, pause, draw, comment at the moment.
The owner of the report and everyone in a team the player is in can watch and comment; a comment can be removed by
whoever wrote it and by the owner of the report. Team › Practice › Recordings lists the team's recordings."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import abort, g, jsonify, render_template, request, send_file, url_for

from ..stats import vodreview as vr

_lock = threading.Lock()


def register(app, store, sr, get_team) -> None:
    def path(jid: str) -> Path:
        return store.data_dir / "vodreview" / f"{jid}.json"

    def read(jid: str) -> dict:
        try:
            return json.loads(path(jid).read_text())
        except (OSError, ValueError):
            return {}

    def write(jid: str, d: dict) -> None:
        p = path(jid)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False))
        tmp.replace(p)

    def access(jid: str):
        """-> (job, is the report's owner). 404 for a report you can't see or one without a recording."""
        if not jid.replace("-", "").isalnum():
            abort(404)
        j = store.job(jid)
        if j is None or not j.vod_path:
            abort(404)
        owner = store.job_owner(jid) == g.user.id
        if not owner and not any(any(m["pid"] == j.profile_id for m in t.member_list)
                                 for t in store.teams_for_user(g.user.id)):
            abort(404)
        return j, owner

    def report_rounds(j) -> list[dict]:
        jp = store.resolve(j.json_path) if j.status == "done" and j.json_path else None
        if not jp:
            return []
        try:
            return vr.rounds_of(json.loads(Path(jp).read_text()))
        except (OSError, ValueError):
            return []

    @app.get("/jobs/<jid>/review")
    def vod_review(jid: str):
        j, owner = access(jid)
        p = store.profile(j.profile_id)
        boot = {"video": url_for("vod_review_video", jid=jid), "api": url_for("vod_review_notes", jid=jid),
                "rounds": report_rounds(j), "notes": read(jid).get("notes", []), "colors": vr.COLORS, "uid": g.user.id,
                "owner": owner}
        return render_template("vod_review.html", j=j, p=p, owner=owner, boot=json.dumps(boot).replace("</", "<\\/"))

    @app.get("/jobs/<jid>/review/video")
    def vod_review_video(jid: str):
        j, _ = access(jid)
        f = store.resolve(j.vod_path)
        if f is None:
            abort(404)
        return send_file(f, conditional=True)            # Range requests: seeking works

    @app.route("/api/jobs/<jid>/review/notes", methods=["GET", "POST"])
    def vod_review_notes(jid: str):
        j, _ = access(jid)
        if request.method == "GET":
            return jsonify(notes=read(jid).get("notes", []))
        note, err = vr.clean_note(request.get_json(silent=True) or {})
        if note is None:
            return jsonify(error=err), 400
        with _lock:
            d = read(jid)
            n = vr.add_note(d, note, g.user.id, g.user.display_name or g.user.username, report_rounds(j))
            write(jid, d)
        return jsonify(ok=True, note=n, notes=d["notes"])

    @app.post("/api/jobs/<jid>/review/notes/<nid>/delete")
    def vod_review_note_delete(jid: str, nid: str):
        _, owner = access(jid)
        with _lock:
            d = read(jid)
            n = next((x for x in d.get("notes", []) if x["id"] == nid), None)
            if n is None:
                abort(404)
            if n["uid"] != g.user.id and not owner:
                abort(403)
            d["notes"] = [x for x in d["notes"] if x["id"] != nid]
            write(jid, d)
        return jsonify(ok=True, notes=d["notes"])

    @app.get("/teams/<int:tid>/recordings")
    def team_recordings(tid: int):
        t = get_team(tid)
        rows = []
        for m in t.member_list:
            p = store.profile(m["pid"])
            if not p:
                continue
            for j in store.jobs(p.id, 60):
                if j.vod_path and store.resolve(j.vod_path):
                    notes = read(j.id).get("notes", [])
                    rows.append({"j": j, "player": p.name, "notes": len(notes),
                                 "last": max((n["at"] for n in notes), default=None)})
        rows.sort(key=lambda r: r["j"].created_at, reverse=True)
        return render_template("team_recordings.html", t=t, tab="recordings", rows=rows[:60], premier_status=None)
