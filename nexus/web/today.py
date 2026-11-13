"""Practice › Today (4.38): what to do today on one page, for one player: the warm-up, a skill session, map prep
when the team plays this week, the quiz, this week's focus, and the way to every practice tool."""
from __future__ import annotations

from flask import g, render_template, url_for

from ..stats import aimweek as aw
from .aim import _read


def register(app, store, sr, view_profile) -> None:
    @app.get("/profiles/<int:pid>/today")
    def today(pid: int):
        p, can_edit = view_profile(pid)
        ext = app.extensions["nexus"]
        runs = _read(sr.games(pid).path.parent / "trainer.json", {}).get("runs", [])
        week = aw.report(runs)
        warm = ext["aim_today"](pid, g.user.id) if "aim_today" in ext else {"warm": None, "done": False}
        prep = []                                       # this week's map of every team this player is in
        for t in store.teams_for_user(g.user.id):
            if not any(m["pid"] == pid for m in t.member_list):
                continue
            m = ext["week_map"](t) if "week_map" in ext and t.premier_info.get("tag") else None
            week = bool(m)
            m = m or (list(t.map_list)[0] if t.map_list else None)
            if m and m not in [x["map"] for x in prep]:
                prep.append({"map": m, "team": t.name, "week": week,
                             "url": url_for("trainer", pid=pid, plan="prep", map=m) + "#tr-prep"})
        try:
            q = sr.read_quiz(pid)
            played = {r.get("created") for r in q.get("results") or []}
            quiz_n = len(q.get("questions") or []) if q.get("questions") and q.get("created") not in played else 0
        except Exception:
            quiz_n = 0
        own = sr.read_own_focus(pid)
        tools = [("trainer", "Aim trainer", "100+ scenarios, skill sessions, your own"), ("callouts", "Callouts", "every map's callouts"),
                 ("maps3d", "3D maps", "walk the maps"), ("sound_trainer", "Sound", "where a sound comes from"),
                 ("habits", "Habits", "what your matches keep showing"), ("ask_coach", "Ask the coach", "anything about your games")]
        return render_template("today.html", p=p, active_pid=pid, week=week, warm=warm, prep=prep, quiz_n=quiz_n, own=own,
                               tools=tools, can_edit=can_edit)
