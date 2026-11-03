"""Practice › Aim (per player): aim routines (built in, your own, your team's), the ones that fit what your
matches show, your warm-up before matches (also on the match screen, in the practice plan and as a push
30 minutes before the match), ticking it off with an optional score, and whether warming up shows in your
headshot rate.

Files: data/aim/user-<uid>.json (your routines), data/teams/<tid>/aim.json (the team's routines and its
warm-up), data/profiles/<pid>/stats/aim.json (that player's warm-up and log)."""
from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, url_for

from ..stats import aim as am

MAX_ROUTINES = 60
MAX_LOG = 400
_lock = threading.RLock()


def _read(path: Path, default):
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else default
    except (OSError, ValueError):
        return default


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def register(app, store, sr, view_profile, filter_rows) -> None:
    def user_path(uid: int) -> Path:
        return store.data_dir / "aim" / f"user-{int(uid)}.json"

    def team_path(tid: int) -> Path:
        return sr.team_dir(tid) / "aim.json"

    def player_path(pid: int) -> Path:
        return sr.games(pid).path.parent / "aim.json"

    def teams_of(pid: int, uid: int) -> list:
        """The teams this player is in that this user can see."""
        return [t for t in store.teams_for_user(uid) if any(m["pid"] == pid for m in t.member_list)]

    def library(pid: int, uid: int) -> list[dict]:
        out = [dict(r, source="builtin", source_name="valcoach") for r in am.BUILTIN]
        for t in teams_of(pid, uid):
            out += [dict(r, source="team", tid=t.id, source_name=t.name) for r in _read(team_path(t.id), {}).get("routines", [])]
        out += [dict(r, source="mine", source_name="your routines") for r in _read(user_path(uid), {}).get("routines", [])]
        return out

    def can_log(p, can_edit: bool, uid: int) -> bool:
        return can_edit or any(m["pid"] == p.id and m.get("user_id") == uid for t in teams_of(p.id, uid) for m in t.member_list)

    def team_warmup(t) -> str | None:
        return _read(team_path(t.id), {}).get("warmup")

    def warmup_of(pid: int, uid: int) -> dict | None:
        lib = library(pid, uid)
        mine = _read(player_path(pid), {}).get("warmup")
        tw = next((team_warmup(t) for t in teams_of(pid, uid) if team_warmup(t)), None)
        return am.warmup_for(lib, mine, tw)

    def done_today(pid: int, rid: str) -> bool:
        today = date.today().isoformat()
        return any(x.get("date") == today and x.get("routine") == rid for x in _read(player_path(pid), {}).get("log", []))

    # ------------------------------------------------------------------ page
    @app.route("/profiles/<int:pid>/aim", methods=["GET", "POST"])
    def aim(pid: int):
        p, can_edit = view_profile(pid)
        uid = g.user.id
        if request.method == "POST":
            return aim_post(p, can_edit, uid)
        rows = filter_rows(sr.games(pid).rows(), "everything")
        lib = library(pid, uid)
        pdata = _read(player_path(pid), {})
        log = pdata.get("log", [])
        need = am.needs(rows)
        warm = warmup_of(pid, uid)
        today = date.today().isoformat()
        done = {x["routine"] for x in log if x.get("date") == today}
        teams = teams_of(pid, uid)
        team_warm = {t.id: team_warmup(t) for t in teams}
        recent = sorted(log, key=lambda x: x.get("t", 0), reverse=True)[:10]
        names = {r["id"]: r["name"] for r in lib}
        return render_template("aim.html", p=p, active_pid=pid, tab="aim", can_edit=can_edit, can_log=can_log(p, can_edit, uid),
                               lib=lib, need=need, picks=am.pick(lib, need), warm=warm, mine_warm=pdata.get("warmup"),
                               done=done, effect=am.effect(rows, log), recent=recent, names=names, teams=teams, team_warm=team_warm,
                               owned={t.id for t in teams if t.owner_id == uid}, focus=am.FOCUS, kinds=am.KINDS,
                               scores={r["id"]: am.scores(log, r["id"]) for r in lib}, is_aimlabs=am.is_aimlabs,
                               min_games=am.MIN_GAMES)

    def back(pid: int):
        nxt = request.form.get("next") or ""
        if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
            return redirect(nxt)
        return redirect(url_for("aim", pid=pid))

    def aim_post(p, can_edit: bool, uid: int):
        f = request.form
        act = f.get("action")
        rid = f.get("rid", "")
        teams = {t.id: t for t in teams_of(p.id, uid)}
        with _lock:
            if act == "add":
                r, err = am.clean({**f, "focus": f.getlist("focus")})
                if r is None:
                    flash(err, "error")
                    return redirect(url_for("aim", pid=p.id) + "#add")
                r["by"] = g.user.display_name or g.user.username
                r["added_by"] = uid
                scope = f.get("scope", "me")
                if scope.startswith("team:") and scope[5:].isdigit() and int(scope[5:]) in teams:
                    path, where = team_path(int(scope[5:])), teams[int(scope[5:])].name
                else:
                    path, where = user_path(uid), "your routines"
                d = _read(path, {})
                d.setdefault("routines", [])
                if len(d["routines"]) >= MAX_ROUTINES:
                    flash(f"{where} already has {MAX_ROUTINES} routines: remove one first.", "error")
                    return redirect(url_for("aim", pid=p.id) + "#library")
                d["routines"].append(r)
                _write(path, d)
                flash(f"Added {r['name']} to {where}.", "ok")
                return redirect(url_for("aim", pid=p.id) + "#library")
            if act == "remove":
                scope = f.get("scope", "")
                if scope.startswith("team:") and scope[5:].isdigit() and int(scope[5:]) in teams:
                    t = teams[int(scope[5:])]
                    path = team_path(t.id)
                    d = _read(path, {})
                    r = next((x for x in d.get("routines", []) if x["id"] == rid), None)
                    if r is None:
                        abort(404)
                    if not (t.owner_id == uid or r.get("added_by") == uid):
                        abort(403)
                else:
                    path = user_path(uid)
                    d = _read(path, {})
                d["routines"] = [x for x in d.get("routines", []) if x["id"] != rid]
                _write(path, d)
                flash("Routine removed.", "ok")
                return redirect(url_for("aim", pid=p.id) + "#library")
            lib = {r["id"]: r for r in library(p.id, uid)}
            if act == "team_warmup":
                tid = int(f.get("tid", "0")) if f.get("tid", "").isdigit() else 0
                t = teams.get(tid)
                if t is None or t.owner_id != uid or (rid and (rid not in lib or lib[rid]["source"] == "mine")):
                    abort(403)
                d = _read(team_path(tid), {})
                d["warmup"] = rid or None
                _write(team_path(tid), d)
                flash(f"{lib[rid]['name']} is now {t.name}'s warm-up." if rid else f"{t.name} has no team warm-up now.", "ok")
                return back(p.id)
            if not can_log(p, can_edit, uid):
                abort(403)
            if rid not in lib:
                abort(400)
            d = _read(player_path(p.id), {})
            log = d.setdefault("log", [])
            today = date.today().isoformat()
            if act == "warmup":
                d["warmup"] = rid
                flash(f"{lib[rid]['name']} is your warm-up now.", "ok")
            elif act == "done":
                score = None
                raw = (f.get("score") or "").strip().replace(",", ".")
                if raw:
                    try:
                        score = round(float(raw), 2)
                    except ValueError:
                        flash("The score must be a number.", "error")
                        return back(p.id)
                    if not -1e7 < score < 1e7:
                        score = None
                log[:] = [x for x in log if not (x.get("date") == today and x.get("routine") == rid)]
                log.append({"date": today, "routine": rid, "name": lib[rid]["name"], "score": score, "t": time.time()})
                del log[:-MAX_LOG]
                flash(f"{lib[rid]['name']}: done for today" + (f", score {score:g}." if score is not None else "."), "ok")
            elif act == "undo":
                log[:] = [x for x in log if not (x.get("date") == today and x.get("routine") == rid)]
            else:
                abort(400)
            _write(player_path(p.id), d)
        return back(p.id)

    # ------------------------------------------------------------------ for other pages
    def member_pid(t, uid: int) -> int | None:
        """The team member linked to this user (or named like his in-game name)."""
        for m in t.member_list:
            if m.get("user_id") == uid:
                return m["pid"]
        u = store.user(uid)
        dn = (getattr(u, "display_name", "") or "").lower()
        for m in t.member_list:
            pr = store.profile(m["pid"])
            if pr and dn and pr.riot_id.lower() == dn:
                return m["pid"]
        return None

    def card(t, uid: int) -> dict | None:
        """Your warm-up for the match screen: {pid, routine, done}."""
        pid = member_pid(t, uid)
        if pid is None:
            return None
        r = warmup_of(pid, uid)
        return {"pid": pid, "routine": r, "done": bool(r and done_today(pid, r["id"]))} if r else None

    def team_routine(t) -> dict | None:
        rid = team_warmup(t)
        if not rid:
            return None
        lib = {r["id"]: r for r in am.BUILTIN}
        lib.update({r["id"]: r for r in _read(team_path(t.id), {}).get("routines", [])})
        return lib.get(rid)

    def tick() -> list[int]:
        """About 30 minutes before the match: everyone's warm-up to his devices (once per team and day)."""
        from . import push
        ext = app.extensions["valcoach"]
        mins_of = ext.get("minutes_to_match")
        if mins_of is None:
            return []
        today = date.today().isoformat()
        sent = []
        for t in store.all_teams():
            m = mins_of(t)
            if m is None or not 20 <= m <= 36:
                continue
            info = t.sync_info
            if (info.get("push") or {}).get("warmup") == today:
                continue
            info.setdefault("push", {})["warmup"] = today
            store.update_team(t.id, sync=info)
            for u in store.users():
                if not any(x.id == t.id for x in store.teams_for_user(u.id)):
                    continue
                pid = member_pid(t, u.id)
                r = warmup_of(pid, u.id) if pid else None
                if r is None:
                    continue
                push.send(store, u.id, f"Warm up: {r['name']}", f"{r['minutes']} min before your match ({t.name}).",
                          url=f"/profiles/{pid}/aim#warmup", tag=f"warmup-{t.id}", kind="warmup")
            sent.append(t.id)
        return sent

    ext = app.extensions["valcoach"]
    ext["aim"] = {"card": card, "team_routine": team_routine, "is_aimlabs": am.is_aimlabs, "tick": tick}
    ext.setdefault("ticks", []).append(tick)
