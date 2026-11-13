"""Practice › Aim (per player): aim routines (built in, your own, your team's), the ones that fit what your
matches show, your warm-up before matches (also on the match screen, in the practice plan and as a push
30 minutes before the match), ticking it off with an optional score, and whether warming up shows in your
headshot rate.

Files: data/aim/user-<uid>.json (your routines), data/teams/<tid>/aim.json (the team's routines and its
warm-up), data/profiles/<pid>/stats/aim.json (that player's warm-up and log)."""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from urllib.parse import urlparse

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..coach import websearch as ws
from ..stats import aim as am
from ..stats import kovaaks as kv
from .urls import local_path

MAX_ROUTINES = 60
MAX_SCENARIOS = 300                  # people's own scenarios, per user and per team
MAX_UPLOAD_FILES = 2000
MAX_LOG = 400
_lock = threading.RLock()
_find_ex = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kfind")
_finds: dict[tuple[int, int], dict] = {}          # (user, player) -> the last search for share codes
_find_lock = threading.Lock()
log = logging.getLogger(__name__)


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


def player_runs(sr, pid: int) -> list[dict]:
    """A player's imported KovaaK's runs."""
    return _read(sr.games(pid).path.parent / "aim.json", {}).get("kovaaks", [])


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

    def coach_files(pid: int) -> list[dict]:
        """The two KovaaK's playlists the coach writes, as routines (downloaded from the Aim page)."""
        how = ("Download it, save it in FPSAimTrainer › Saved › SaveGames › Playlists (the date is in its name, "
               "older ones can stay), then open KovaaK's › Playlists › Local Playlists.")
        return [{"id": "k-warmup", "name": "KovaaK's warm-up from the coach", "kind": "kovaaksfile", "minutes": 10,
                 "focus": ["warmup", "flicks", "micro"], "steps": how, "code": "",
                 "url": f"/profiles/{int(pid)}/aim/kovaaks/warmup.json"},
                {"id": "k-training", "name": "KovaaK's training from the coach", "kind": "kovaaksfile", "minutes": 25,
                 "focus": ["flicks", "micro", "reaction", "switching"], "steps": how, "code": "",
                 "url": f"/profiles/{int(pid)}/aim/kovaaks/training.json"}]

    def trainer_plans(pid: int) -> list[dict]:
        """Today's warm-up and training in Nexus's own aim trainer (Practice › Aim trainer), as routines."""
        return [{"id": "t-warmup", "name": "Nexus trainer warm-up", "kind": "trainer", "minutes": 2,
                 "focus": ["warmup", "flicks", "crosshair", "micro"], "code": "",
                 "steps": "Three short scenarios in the browser: grid flicks, head-line flicks, micro taps. "
                          "Ticked off by itself when you finish it.",
                 "url": f"/profiles/{int(pid)}/trainer?plan=warmup"},
                {"id": "t-training", "name": "Nexus trainer training", "kind": "trainer", "minutes": 6,
                 "focus": ["flicks", "micro", "tracking", "peeking", "reaction", "crosshair", "switching"], "code": "",
                 "steps": "The trainer's scenarios that fit what your matches show, two rounds each. "
                          "Ticked off by itself when you finish it.",
                 "url": f"/profiles/{int(pid)}/trainer?plan=training"}]

    def library(pid: int, uid: int) -> list[dict]:
        out = [dict(r, source="builtin", source_name="Nexus") for r in am.BUILTIN + coach_files(pid) + trainer_plans(pid)]
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
        pdata = _read(player_path(pid), {})
        tw = next((team_warmup(t) for t in teams_of(pid, uid) if team_warmup(t)), None)
        # someone who plays KovaaK's (scores imported) gets the coach's KovaaK's warm-up by default
        played = "k-warmup" if pdata.get("kovaaks") else ("t-warmup" if trainer_played(pid) else None)
        return am.warmup_for(lib, pdata.get("warmup"), tw or played)

    def trainer_played(pid: int) -> bool:
        return bool(_read(player_path(pid).with_name("trainer.json"), {}).get("runs"))

    def scenarios(pid: int, uid: int) -> list[dict]:
        """Every scenario the coach may use for this player: built in, the teams', this user's own."""
        out = {s["name"]: s for s in kv.builtin()}
        for t in teams_of(pid, uid):
            for s in _read(team_path(t.id), {}).get("scenarios", []):
                out.setdefault(s["name"], dict(s, source="team", tid=t.id, source_name=t.name))
        for s in _read(user_path(uid), {}).get("scenarios", []):
            out.setdefault(s["name"], dict(s, source="mine", source_name="yours"))
        return list(out.values())

    def plan(pid: int, uid: int, kind: str, rows=None) -> dict:
        if rows is None:
            rows = filter_rows(sr.games(pid).rows(), "everything")
        need, cat = am.needs(rows), scenarios(pid, uid)
        runs, week = _read(player_path(pid), {}).get("kovaaks", []), kv.week_id()
        skip: set[str] = set()
        if kind == "training":                  # training plays different scenarios from the warm-up
            skip = {x["name"] for x in kv.build("warmup", need, cat, runs, week=week)["items"]}
        return kv.build(kind, need, cat, runs, week=week, exclude=skip)

    def import_runs(pid: int, uid: int, files: list[tuple[str, bytes]]) -> tuple[list, int, int, int]:
        """KovaaK's stats files (csv or zip) into the player's scores. -> (runs read, new runs, scenarios learned,
        files that couldn't be read). Scenarios the coach doesn't know yet go into this user's own list."""
        runs, bad = [], 0
        for name, data in files:
            if not name.lower().endswith((".csv", ".zip")):
                bad += 1
                continue
            r, b = kv.read_upload(name, data)
            runs += r
            bad += b
        d = _read(player_path(pid), {})
        d["kovaaks"], new = kv.merge_runs(d.get("kovaaks", []), runs)
        _write(player_path(pid), d)
        known = {s["name"] for s in scenarios(pid, uid)}
        unknown = sorted({r["s"] for r in runs} - known)
        learned = add_scenarios(user_path(uid), [{"name": n, "focus": kv.guess(n)[0], "level": kv.guess(n)[1]}
                                                 for n in unknown], uid) if unknown else 0
        return runs, new, learned, bad

    def playlist_files(pid: int, uid: int, player_name: str) -> list[dict]:
        """Both KovaaK's playlists the coach writes for this player, as files: [{kind, file_name, data}]."""
        return [{"kind": k, "file_name": kv.file_name(k), "data": kv.playlist_file(plan(pid, uid, k), player_name)}
                for k in kv.KINDS]

    def done_today(pid: int, rid: str) -> bool:
        today = date.today().isoformat()
        return any(x.get("date") == today and x.get("routine") == rid for x in _read(player_path(pid), {}).get("log", []))

    # ------------------------------------------------------------------ page
    @app.route("/profiles/<int:pid>/aim", methods=["GET", "POST"])
    def aim(pid: int):
        return aim_page(pid, "main")

    # 4.25: KovaaK's on its own page (Aim › KovaaK's), so the Aim page is about the warm-up and the routines
    @app.route("/profiles/<int:pid>/aim/kovaaks", methods=["GET", "POST"])
    def aim_kovaaks_page(pid: int):
        return aim_page(pid, "kovaaks")

    def aim_page(pid: int, page: str):
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
        runs = pdata.get("kovaaks", [])
        scen = scenarios(pid, uid)
        have = {(r.get("code") or "").lower() for r in lib if r.get("code")}
        shared_all: dict[str, list] = {}
        for x in kv.shared():
            shared_all.setdefault(x["group"], []).append(dict(x, added=x["code"].lower() in have))
        by_focus: dict[str, list] = {}
        for s in sorted(scen, key=lambda s: (s["level"], s["name"].lower())):
            by_focus.setdefault(s["focus"][0] if s.get("focus") else "flicks", []).append(s)
        # the coach's KovaaK's playlists only show among the routines for someone who plays KovaaK's (or has one as
        # warm-up); everyone else finds them on the KovaaK's page
        shown = [r for r in lib if r["kind"] != "kovaaksfile" or runs or (warm and warm["id"] == r["id"])]
        return render_template("aim.html", page=page, p=p, active_pid=pid, tab="aim", can_edit=can_edit, can_log=can_log(p, can_edit, uid),
                               lib=shown, need=need, picks=am.pick(shown, need), warm=warm, mine_warm=pdata.get("warmup"),
                               done=done, effect=am.effect(rows, log, kv.run_days(runs)), recent=recent, names=names, teams=teams, team_warm=team_warm,
                               plans=[plan(pid, uid, k, rows) for k in kv.KINDS], kstats=kv.summary(runs)[:16], kruns=len(runs),
                               scen_by_focus=by_focus, n_scen=len(scen), addable=am.ADDABLE,
                               owned={t.id for t in teams if t.owner_id == uid}, focus=am.FOCUS, kinds=am.KINDS,
                               scores={r["id"]: am.scores(log, r["id"]) for r in lib}, is_aimlabs=am.is_aimlabs,
                               min_games=am.MIN_GAMES, shared_pick=kv.suggest(need, runs, 4, have), shared_all=shared_all,
                               shared_groups=kv.SHARED_GROUPS, n_shared=len(kv.SHARED), search_on=bool(ws.provider(store)))

    def back(pid: int):
        target = (request.form.get("next") or "").replace("\\", "")
        if local_path(target) and not urlparse(target).netloc and not urlparse(target).scheme:
            return redirect(target)
        return redirect(url_for("aim", pid=pid))

    def aim_post(p, can_edit: bool, uid: int):
        f = request.form
        act = f.get("action")
        rid = f.get("rid", "")
        teams = {t.id: t for t in teams_of(p.id, uid)}
        if act and act.startswith("k_"):
            return kovaaks_post(p, can_edit, uid, act, teams)
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

    # ------------------------------------------------------------------ KovaaK's
    def scope_path(scope: str, uid: int, teams: dict):
        if scope.startswith("team:") and scope[5:].isdigit() and int(scope[5:]) in teams:
            t = teams[int(scope[5:])]
            return team_path(t.id), t.name
        return user_path(uid), "your scenarios"

    def add_scenarios(path: Path, items: list[dict], uid: int) -> int:
        """Scenarios into a library (skips names it already has, built-in ones included)."""
        d = _read(path, {})
        have = {s["name"] for s in d.get("scenarios", [])} | {n for n, _, _ in kv.BUILTIN}
        added = 0
        for it in items:
            if it["name"] in have or len(d.get("scenarios", [])) >= MAX_SCENARIOS:
                continue
            d.setdefault("scenarios", []).append({"name": it["name"], "focus": it["focus"], "level": it["level"],
                                                  "added_by": uid, "by": g.user.display_name or g.user.username})
            have.add(it["name"])
            added += 1
        if added:
            _write(path, d)
        return added

    def files_of(field: str) -> list:
        fs = [f for f in request.files.getlist(field) if f and f.filename][:MAX_UPLOAD_FILES]
        if not fs:
            flash("Choose one or more files first.", "error")
        return fs

    def kovaaks_post(p, can_edit: bool, uid: int, act: str, teams: dict):
        f = request.form
        back_to = redirect(url_for("aim_kovaaks_page", pid=p.id) + "#kovaaks")
        with _lock:
            if act == "k_add_scenario":
                name = kv.clean_name(f.get("name"))
                if not name:
                    flash("Write the scenario's name exactly as KovaaK's shows it.", "error")
                    return back_to
                focus = [x for x in f.getlist("focus") if x in am.FOCUS][:3] or kv.guess(name)[0]
                try:
                    level = max(1, min(3, int(f.get("level") or 2)))
                except ValueError:
                    level = 2
                path, where = scope_path(f.get("scope", "me"), uid, teams)
                n = add_scenarios(path, [{"name": name, "focus": focus, "level": level}], uid)
                flash(f"Added {name} to {where}." if n else f"{name} is already in the list.", "ok" if n else "error")
                return back_to
            if act == "k_remove_scenario":
                name = f.get("name", "")
                path, _ = scope_path(f.get("scope", "me"), uid, teams)
                d = _read(path, {})
                s = next((x for x in d.get("scenarios", []) if x["name"] == name), None)
                if s is None:
                    abort(404)
                t = teams.get(int(f["scope"][5:])) if f.get("scope", "").startswith("team:") else None
                if t is not None and not (t.owner_id == uid or s.get("added_by") == uid):
                    abort(403)
                d["scenarios"] = [x for x in d["scenarios"] if x["name"] != name]
                _write(path, d)
                flash(f"Removed {name}.", "ok")
                return back_to
            if act == "k_import_playlist":
                fs = files_of("files")
                if not fs:
                    return back_to
                path, where = scope_path(f.get("scope", "me"), uid, teams)
                added = routines = bad = 0
                for fh in fs:
                    pl = kv.read_playlist(fh.read(200_000))
                    if pl is None:
                        bad += 1
                        continue
                    added += add_scenarios(path, [{"name": n, "focus": kv.guess(n)[0], "level": kv.guess(n)[1]}
                                                  for n, _ in pl["scenarios"]], uid)
                    if f.get("as_routine") and pl["code"]:
                        d = _read(path, {})
                        if not any(r.get("code") == pl["code"] for r in d.get("routines", [])) and len(d.get("routines", [])) < MAX_ROUTINES:
                            tags = []
                            for n, _ in pl["scenarios"]:
                                tags += [t for t in kv.guess(n)[0] if t not in tags]
                            d.setdefault("routines", []).append({
                                "id": am.new_id(), "name": pl["name"], "kind": "kovaaks", "code": pl["code"], "url": "",
                                "minutes": max(1, round(sum(r for _, r in pl["scenarios"]) * kv.SECONDS_PER_RUN / 60)),
                                "focus": tags[:4] or ["flicks"], "added_by": uid, "by": g.user.display_name or g.user.username,
                                "steps": "Scenarios: " + ", ".join(f"{n.strip()} ×{r}" for n, r in pl["scenarios"])[:550]})
                            _write(path, d)
                            routines += 1
                msg = [f"New scenarios for the coach: {added}."]
                if routines:
                    msg.append(f"Playlists added as routines: {routines}.")
                if bad:
                    msg.append(f"Files that weren't KovaaK's playlists: {bad}.")
                flash(" ".join(msg), "ok" if added or routines else "error")
                return back_to
            if act == "k_add_shared":                # a community playlist (built-in list or found online) as a routine
                code = (f.get("code") or "").strip()
                known = {x["code"].lower(): x for x in kv.shared()}
                if not am.CODE_RE.fullmatch(code) or not code.lower().startswith("kovaaks"):
                    flash("That isn't a KovaaK's share code.", "error")
                    return redirect(url_for("aim_kovaaks_page", pid=p.id) + "#kshared")
                base = known.get(code.lower())
                name = (base["name"] if base else " ".join((f.get("name") or "").split())[:60]) or code
                focus = base["focus"] if base else (kv.guess(name)[0] or ["flicks"])
                path, where = scope_path(f.get("scope", "me"), uid, teams)
                d = _read(path, {})
                if any((r.get("code") or "").lower() == code.lower() for r in d.get("routines", [])):
                    flash(f"{name} is already in {where}.", "error")
                    return redirect(url_for("aim_kovaaks_page", pid=p.id) + "#kshared")
                if len(d.get("routines", [])) >= MAX_ROUTINES:
                    flash(f"{where} already has {MAX_ROUTINES} routines: remove one first.", "error")
                    return redirect(url_for("aim_kovaaks_page", pid=p.id) + "#kshared")
                src = f.get("url", "").strip()
                steps = (f"By {base['author']}. " if base else "") + "In KovaaK's: Sandbox › Online Playlists › Enter Share Code; it downloads every scenario."
                if not base and src.startswith(("https://", "http://")):
                    steps += f" Found on {src[:200]}"
                d.setdefault("routines", []).append({
                    "id": am.new_id(), "name": name, "kind": "kovaaks", "code": code, "url": "",
                    "minutes": 20, "focus": [x for x in focus if x in am.FOCUS][:4] or ["flicks"], "steps": steps[:am.MAX_STEPS],
                    "added_by": uid, "by": g.user.display_name or g.user.username})
                _write(path, d)
                flash(f"Added {name} to {where.replace('scenarios', 'routines')}.", "ok")
                return redirect(url_for("aim_kovaaks_page", pid=p.id) + "#kshared")
            if not can_log(p, can_edit, uid):
                abort(403)
            if act == "k_import_stats":
                fs = files_of("files")
                if not fs:
                    return back_to
                runs, new, learned, bad = import_runs(p.id, uid, [(fh.filename or "", fh.read()) for fh in fs])
                msg = [f"New runs imported: {new} ({len(runs) - new} were already there)."]
                if learned:
                    msg.append(f"New scenarios the coach can use now: {learned}.")
                if bad:
                    msg.append(f"Files that couldn't be read: {bad}.")
                flash(" ".join(msg), "ok" if runs else "error")
                return back_to
            if act == "k_clear_stats":
                d = _read(player_path(p.id), {})
                d.pop("kovaaks", None)
                _write(player_path(p.id), d)
                flash("KovaaK's scores removed.", "ok")
                return back_to
        abort(400)

    @app.get("/profiles/<int:pid>/aim/kovaaks/<kind>.json")
    def aim_kovaaks(pid: int, kind: str):
        """The playlist file for KovaaK's, dated (DD-MM-YYYY) in its name and file name, so older ones can stay."""
        p, _ = view_profile(pid)
        if kind not in kv.KINDS:
            abort(404)
        data = kv.playlist_file(plan(pid, g.user.id, kind), p.name)
        resp = app.response_class(json.dumps(data, indent=2, ensure_ascii=False), mimetype="application/json")
        resp.headers["Content-Disposition"] = f'attachment; filename="{kv.file_name(kind)}"'
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/api/profiles/<int:pid>/aim/find-playlists")
    def aim_find_playlists(pid: int):
        """Start looking for KovaaK's share codes on the web for what this player's aim needs (Settings › Web
        search). It runs in the background (several searches and pages can take a minute); the page polls the
        GET below."""
        view_profile(pid)
        search = ws.searcher(store)
        if search is None:
            return jsonify(error="Web search isn't set up (Settings › Web search)."), 400
        key = (g.user.id, pid)
        with _find_lock:
            if _finds.get(key, {}).get("pending"):
                return jsonify(pending=True)
            _finds[key] = {"pending": True, "t": time.time()}
        rows = filter_rows(sr.games(pid).rows(), "everything")
        focus = []
        for x in am.needs(rows):
            focus += [f for f in x["focus"] if f not in focus and f != "warmup"]
        words = {"crosshair": "crosshair placement", "micro": "micro flicks", "flicks": "flicking", "peeking": "peeking",
                 "reaction": "reactivity", "switching": "target switching", "tracking": "tracking"}
        queries = ["KovaaK's playlist share code Valorant"] + [f"KovaaK's share code {words[f]} playlist" for f in focus[:2] if f in words]
        have = {(r.get("code") or "").lower() for r in library(pid, g.user.id) if r.get("code")} | {x["code"].lower() for x in kv.shared()}

        def work():
            try:
                found, errors = ws.find_share_codes(search, queries, have)
                for x in found:
                    x["focus"] = [am.FOCUS.get(f, f) for f in kv.guess(x["name"])[0]]
                res = {"found": found, "searched": queries, "errors": errors[:2]}
            except Exception:                        # details only in the log
                log.exception("finding KovaaK's playlists")
                res = {"found": [], "searched": queries, "errors": ["the search failed"]}
            with _find_lock:
                _finds[key] = dict(res, pending=False, t=time.time())
        _find_ex.submit(work)
        return jsonify(pending=True)

    @app.get("/api/profiles/<int:pid>/aim/find-playlists")
    def aim_find_playlists_state(pid: int):
        view_profile(pid)
        with _find_lock:
            for k in [k for k, v in _finds.items() if time.time() - v.get("t", 0) > 1800]:
                _finds.pop(k, None)                 # forget old results
            st = dict(_finds.get((g.user.id, pid)) or {"pending": False, "found": None})
        return jsonify(st)

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
        lib = {r["id"]: r for r in am.BUILTIN + coach_files(0)}
        lib.update({r["id"]: r for r in _read(team_path(t.id), {}).get("routines", [])})
        return lib.get(rid)

    def tick() -> list[int]:
        """About 30 minutes before the match: everyone's warm-up to his devices (once per team and day)."""
        from . import push
        ext = app.extensions["nexus"]
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

    ext = app.extensions["nexus"]
    ext["aim"] = {"card": card, "team_routine": team_routine, "is_aimlabs": am.is_aimlabs, "tick": tick,
                  "import_runs": import_runs, "playlist_files": playlist_files}
    ext.setdefault("ticks", []).append(tick)
