"""Team › Practice › Aim board (stats/aimweek.py): everyone's skill ratings side by side, who trained how much this
week, and a weekly challenge with a leaderboard. The owner picks the challenge (a built-in or a team sandbox scenario)
or leaves it to the rotation; it's posted to Discord with the weekly focus, or by hand."""
from __future__ import annotations

import threading

from flask import abort, flash, g, redirect, render_template, request, url_for

from ..discord import DiscordError, channel, post
from ..stats import aimweek as aw
from ..stats import trainer as tr
from .aim import _read, _write

_lock = threading.Lock()


def register(app, store, sr, get_team) -> None:
    def ext():
        return app.extensions["nexus"]

    def path(tid: int):
        return sr.team_dir(tid) / "aimboard.json"

    def team_sandbox(tid: int) -> dict:
        items = _read(sr.team_dir(tid) / "sandbox.json", {}).get("items", [])
        return {c["id"]: {"name": c["name"], "kind": c["kind"], "skill": c.get("skill", ""), "level": c.get("level", 2)}
                for c in items}

    def members_of(t) -> list[dict]:
        extra = team_sandbox(t.id)
        out = []
        for m in t.member_list:
            p = store.profile(m["pid"])
            if p:
                out.append({"name": p.name, "pid": p.id, "kind": m.get("kind"), "extra": extra,
                            "runs": _read(sr.games(p.id).path.parent / "trainer.json", {}).get("runs", [])})
        return out

    def current(t) -> tuple[dict, str, str, dict]:
        saved = _read(path(t.id), {})
        week = aw.week_label()
        extra = team_sandbox(t.id)
        ch = aw.challenge_of(saved.get("challenges", {}), week)
        if ch not in tr.SCENARIOS and ch not in extra:
            ch = aw.challenge_of({}, week)
        name = (tr.SCENARIOS.get(ch) or extra.get(ch) or {}).get("name", ch)
        return aw.board(members_of(t), ch), name, week, extra

    def post_board(t) -> None:
        url = channel(t.discord_info, "focus")
        if not url:
            raise DiscordError("No Discord channel set (Team settings › Discord).")
        b, name, _, _ = current(t)
        post(url, embeds=aw.discord_embeds(t.name, b, name))

    @app.route("/teams/<int:tid>/aimboard", methods=["GET", "POST"])
    def team_aimboard(tid: int):
        t = get_team(tid)
        if request.method == "POST":
            if not g.team_owner:
                abort(403)
            if request.form.get("post"):
                try:
                    post_board(t)
                    flash("Posted the aim board to Discord.", "ok")
                except DiscordError as e:
                    flash(str(e), "error")
                return redirect(url_for("team_aimboard", tid=tid))
            ch = request.form.get("challenge", "")
            if ch and ch not in tr.SCENARIOS and ch not in team_sandbox(tid):
                abort(400)
            with _lock:
                d = _read(path(tid), {})
                d.setdefault("challenges", {})[aw.week_label()] = ch
                if not ch:
                    d["challenges"].pop(aw.week_label(), None)
                _write(path(tid), d)
            flash("This week's challenge is set." if ch else "The challenge rotates again.", "ok")
            return redirect(url_for("team_aimboard", tid=tid))
        b, name, week, extra = current(t)
        mine = next((m["pid"] for m in t.member_list if m.get("user_id") == g.user.id), None)
        choices = [(k, v["name"]) for k, v in tr.SCENARIOS.items()] + [(k, v["name"] + " (sandbox)") for k, v in extra.items()]
        return render_template("team_aimboard.html", t=t, tab="aimboard", b=b, ch_name=name, week=week,
                               skills=tr.SKILLS, choices=choices, picked=_read(path(tid), {}).get("challenges", {}).get(week, ""),
                               mine=mine, discord=bool(channel(t.discord_info, "focus")), premier_status=None)

    # the weekly Discord post goes out with the weekly focus (same day and hour, Team settings › Discord)
    def wrap(job):
        def weekly(t):
            job(t)
            try:
                if any(_read(sr.games(m["pid"]).path.parent / "trainer.json", {}).get("runs") for m in t.member_list):
                    post_board(t)
            except Exception:
                pass
        return weekly
    if "weekly_job" in ext():
        ext()["weekly_job"] = wrap(ext()["weekly_job"])
