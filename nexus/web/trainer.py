"""Practice › Aim trainer and Practice › Mouse & monitor (per player). The pages do the work in the browser
(static/trainer.js, static/gearcheck.js); the server keeps the scores and the settings (stats/trainer.py) and
ticks off the warm-up or training on the Aim page when a whole one was played."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from flask import abort, g, jsonify, render_template, request, url_for

from ..stats import aim as am
from ..stats import aim_insights as ai
from ..stats import mapangles as ma
from ..stats import sandbox as sbx
from ..stats import trainer as tr
from .aim import MAX_LOG, _lock, _read, _write


def trainer_data(sr, pid: int) -> dict:
    return _read(sr.games(pid).path.parent / "trainer.json", {})


def sens_chart(rec: dict, w: int = 560, h: int = 200) -> dict:
    """The sens finder's chart as SVG coordinates: every test as a dot, the fitted curve, the recommendation."""
    xs = [p["sens"] for p in rec["points"]] + [c[0] for c in rec["curve"]]
    ys = [p["y"] for p in rec["points"]] + [c[1] for c in rec["curve"]]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    x1 = x1 if x1 > x0 else x0 + 0.01
    y1 = y1 if y1 > y0 else y0 + 0.01
    pad = 28

    def X(v):
        return round(pad + (v - x0) / (x1 - x0) * (w - 2 * pad), 1)

    def Y(v):
        return round(h - pad - (v - y0) / (y1 - y0) * (h - 2 * pad), 1)
    ticks = sorted({round(x0, 2), round((x0 + x1) / 2, 2), round(x1, 2)})
    return {"w": w, "h": h, "dots": [{"x": X(p["sens"]), "y": Y(p["y"]), "sens": p["sens"], "q": p["y"], "d": p.get("d", ""),
                                      "mode": tr.MODES.get(p.get("mode"), "")} for p in rec["points"]],
            "curve": " ".join(f"{X(a)},{Y(b)}" for a, b in rec["curve"]),
            "rec": X(rec["sens"]), "band": (X(rec["low"]), X(rec["high"])), "ticks": [(X(v), v) for v in ticks],
            "base": h - pad}


def register(app, store, sr, view_profile, filter_rows, known_maps: list[str] = ()) -> None:
    from collections import Counter

    from ..maps import MapRegistry
    reg = MapRegistry(store.data_dir / "cache")

    def angle_maps(pid: int) -> dict:
        """Map angles: the maps with positions, the ones this player plays most first."""
        played = Counter(r.get("map") for r in filter_rows(sr.games(pid).rows(), "everything"))
        order = sorted(set(known_maps) | {m for m in played if m}, key=lambda m: (-played.get(m, 0), m))
        return ma.for_maps(reg, order)

    def path(pid: int) -> Path:
        return sr.games(pid).path.parent / "trainer.json"

    def aim_path(pid: int) -> Path:
        return sr.games(pid).path.parent / "aim.json"

    def can_save(p, can_edit: bool) -> bool:
        """The owner of the player, or the person the player is (a teammate who linked themselves)."""
        if can_edit:
            return True
        return any(m["pid"] == p.id and m.get("user_id") == g.user.id
                   for t in store.teams_for_user(g.user.id) for m in t.member_list)

    # ---- 4.33: the sandbox. Your scenarios and your teams' (data/sandbox/user-<uid>.json, teams/<tid>/sandbox.json)
    def sb_path(scope: str) -> Path:
        if scope.startswith("team:"):
            return store.data_dir / "teams" / scope[5:] / "sandbox.json"
        return store.data_dir / "sandbox" / f"user-{int(g.user.id)}.json"

    def my_teams() -> dict:
        return {t.id: t for t in store.teams_for_user(g.user.id)}

    def customs() -> list[dict]:
        """Every sandbox scenario this user can play: their own, then their teams'."""
        out = [dict(x, scope="me") for x in _read(sb_path("me"), {}).get("items", [])]
        for tid, t in my_teams().items():
            out += [dict(x, scope=f"team:{tid}", tid=tid, team=t.name) for x in _read(sb_path(f"team:{tid}"), {}).get("items", [])]
        return out

    def extra_of(cs: list[dict]) -> dict:
        return {c["id"]: {"name": c["name"], "kind": c["kind"], "skill": c.get("skill", ""), "level": c.get("level", 2),
                          "focus": [], "group": "sandbox"} for c in cs}

    def plans(pid: int, runs: list[dict], setup: dict) -> dict:
        need = am.needs(filter_rows(sr.games(pid).rows(), "everything"))
        out = {k: tr.plan(k, need, runs) for k in tr.PLANS}
        focus = ai.focus_plan(ai.build(runs, setup)["findings"])
        if focus:
            out["focus"] = focus
        return out

    @app.get("/profiles/<int:pid>/trainer")
    def trainer(pid: int):
        p, can_edit = view_profile(pid)
        d = _read(path(pid), {})
        runs = d.get("runs", [])
        setup = d.get("setup", {})
        start = request.args.get("plan")
        play = request.args.get("play")
        rec = tr.recommend(d.get("sensfind", []))
        pl = plans(pid, runs, setup)
        amaps = angle_maps(pid)
        prep_plans = {f"prep_{m}": tr.plan_prep(m, ps, runs) for m, ps in amaps.items()}
        prep_map = request.args.get("map", "")
        if start == "prep" and f"prep_{prep_map}" in prep_plans:
            start = f"prep_{prep_map}"
        cs = customs()
        extra = extra_of(cs)
        skill_plans = {f"skill_{k}_{m}": tr.plan_skill(k, m, runs, extra) for k in tr.SKILLS for m in tr.SESSION_MINUTES}
        csum = {x["id"]: x for x in tr.summary(runs, extra) if x["id"] in extra}
        sandbox = {"types": {k: {"label": v["label"], "kind": v["kind"], "about": v["about"],      # lists: the page keeps the order
                                 "params": [[pk, *pv] for pk, pv in v["params"].items()]} for k, v in sbx.TYPES.items()},
                   "order": list(sbx.TYPES),
                   "items": [dict(sbx.to_page(c), code=sbx.code(c), mine=c["uid"] == g.user.id,
                                  can_edit=c["uid"] == g.user.id or (c.get("tid") and my_teams()[c["tid"]].owner_id == g.user.id),
                                  team=c.get("team", ""), best=(csum.get(c["id"]) or {}).get("best"),
                                  runs=(csum.get(c["id"]) or {}).get("runs", 0)) for c in cs],
                   "teams": [{"id": t.id, "name": t.name} for t in my_teams().values()],
                   "save": url_for("trainer_sandbox_save", pid=pid), "skills": [[k, v["name"]] for k, v in tr.SKILLS.items()],
                   "skill_names": {k: v["name"] for k, v in tr.SKILLS.items()}}
        return render_template("trainer.html", p=p, active_pid=pid, can_save=can_save(p, can_edit), angles=amaps,
                               prep_plans=prep_plans, all_plans={**pl, **skill_plans, **prep_plans}, prep_map=prep_map if f"prep_{prep_map}" in prep_plans else next(iter(amaps), ""),
                               skills=tr.skill_ratings(runs, extra), skill_plans=skill_plans, minutes=tr.SESSION_MINUTES,
                               sandbox=sandbox,
                               groups=tr.GROUPS, part_names=tr.PARTS, rec=rec, step=tr.sens_step(setup.get("sens"), rec["sens"]) if rec else None,
                               chart=sens_chart(rec) if rec else None,
                               scenarios=tr.scenario_list(), summary=tr.summary(runs), plans=pl, levels=tr.LEVELS,
                               start=start if start in pl or start in skill_plans or start in prep_plans else "",
                               play=play if play in tr.SCENARIOS or play in extra else "", setup=setup, numbers=tr.numbers(setup),
                               n_runs=len(runs), today=sum(1 for r in runs if r.get("d") == date.today().isoformat()))

    @app.get("/profiles/<int:pid>/trainer/insights")
    def aim_insights(pid: int):
        p, can_edit = view_profile(pid)
        d = _read(path(pid), {})
        runs = d.get("runs", [])
        setup = d.get("setup", {})
        res = ai.build(runs, setup)
        names = {k: v["name"] for k, v in tr.SCENARIOS.items()}
        trends = [s for s in tr.summary(runs) if s["runs"] >= 2]
        return render_template("aim_insights.html", p=p, active_pid=pid, can_save=can_save(p, can_edit), setup=setup,
                               ins=res, names=names, trends=trends, grips=tr.GRIPS, days=ai.DAYS, n_runs=len(runs))

    @app.get("/profiles/<int:pid>/gear")
    def gear_check(pid: int):
        p, can_edit = view_profile(pid)
        setup = _read(path(pid), {}).get("setup", {})
        return render_template("gear.html", p=p, active_pid=pid, can_save=can_save(p, can_edit), setup=setup,
                               numbers=tr.numbers(setup), yaw=tr.VALORANT_YAW)

    @app.post("/profiles/<int:pid>/trainer/runs")
    def trainer_run(pid: int):
        p, can_edit = view_profile(pid)
        if not can_save(p, can_edit):
            abort(403)
        b = request.get_json(silent=True) or {}
        extra = extra_of(customs())
        run = tr.clean_run(b, extra)
        if run is None:
            return jsonify(error="That run doesn't add up."), 400
        with _lock:
            d = _read(path(pid), {})
            res = tr.add_run(d, run)
            _write(path(pid), d)
            kind = b.get("plan_done")
            if kind in tr.PLANS or kind == "focus":                 # a whole warm-up or training: ticked off on the Aim page
                total = tr._num(b.get("plan_score"), 0, 10**6, 0)
                rid = f"t-{kind}"
                a = _read(aim_path(pid), {})
                log = a.setdefault("log", [])
                today = date.today().isoformat()
                log[:] = [x for x in log if not (x.get("date") == today and x.get("routine") == rid)]
                log.append({"date": today, "routine": rid, "name": f"Nexus trainer {tr.PLANS.get(kind, 'Focus').lower()}",
                            "score": total, "t": time.time()})
                del log[:-MAX_LOG]
                _write(aim_path(pid), a)
        row = next(x for x in tr.summary(d["runs"], extra) if x["id"] == run["s"])
        return jsonify(ok=True, **res, best=row["best"], runs=row["runs"])

    @app.post("/profiles/<int:pid>/trainer/sens")
    def trainer_sens(pid: int):
        p, can_edit = view_profile(pid)
        if not can_save(p, can_edit):
            abort(403)
        session = tr.clean_sens_session(request.get_json(silent=True) or {})
        if session is None:
            return jsonify(error="That sens test doesn't add up."), 400
        with _lock:
            d = _read(path(pid), {})
            ss = d.setdefault("sensfind", [])
            ss.append(session)
            del ss[:-tr.MAX_SESSIONS]
            _write(path(pid), d)
        rec = tr.recommend(ss)
        this = tr.recommend([session])
        return jsonify(ok=True, this=this["sens"] if this else None, sens=rec["sens"], low=rec["low"], high=rec["high"],
                       edge=rec["edge"], sessions=rec["sessions"], sure=rec["sure"], parts=this["parts"] if this else {})

    @app.post("/profiles/<int:pid>/trainer/setup")
    def trainer_setup(pid: int):
        p, can_edit = view_profile(pid)
        if not can_save(p, can_edit):
            abort(403)
        new = tr.clean_setup(request.get_json(silent=True) or {})
        if not new:
            return jsonify(error="Nothing to save."), 400
        with _lock:
            d = _read(path(pid), {})
            setup = d.setdefault("setup", {})
            setup.update(new)
            setup["t"] = time.time()
            _write(path(pid), d)
        return jsonify(ok=True, setup=setup, numbers=tr.numbers(setup))


    # ---- 4.33: sandbox saves and removals (from the trainer page; the scenario belongs to the user or a team)
    def sb_scope(scope: str) -> str:
        if scope.startswith("team:") and scope[5:].isdigit() and int(scope[5:]) in my_teams():
            return scope
        if scope not in ("", "me"):
            abort(403)
        return "me"

    def sb_can_change(item: dict, scope: str) -> bool:
        if item["uid"] == g.user.id:
            return True
        return scope.startswith("team:") and my_teams()[int(scope[5:])].owner_id == g.user.id

    @app.post("/profiles/<int:pid>/trainer/sandbox")
    def trainer_sandbox_save(pid: int):
        view_profile(pid)
        b = request.get_json(silent=True) or {}
        if b.get("code"):
            sc, err = sbx.decode(b["code"])
        else:
            sc, err = sbx.clean(b)
        if sc is None:
            return jsonify(error=err), 400
        scope = sb_scope(str(b.get("scope") or "me"))
        if b.get("dry"):                                   # "Try it": checked and built, not saved
            item = dict(sc, id="c_try", uid=g.user.id, by="")
            return jsonify(ok=True, item=dict(sbx.to_page(item), code=sbx.code(item), scope=scope))
        sid = str(b.get("id") or "")
        old_scope = sb_scope(str(b.get("from") or scope)) if sid else scope
        with _lock:
            if sid and old_scope != scope:            # moved (e.g. shared with a team): out of the old place
                od = _read(sb_path(old_scope), {})
                it = next((x for x in od.get("items", []) if x["id"] == sid), None)
                if it is None or not sb_can_change(it, old_scope):
                    abort(404)
                od["items"] = [x for x in od["items"] if x["id"] != sid]
                _write(sb_path(old_scope), od)
                sid_keep, sid = sid, ""
            else:
                sid_keep = ""
            d = _read(sb_path(scope), {})
            if sid:
                it = next((x for x in d.get("items", []) if x["id"] == sid), None)
                if it is None or not sb_can_change(it, scope):
                    abort(404)
            elif len(d.get("items", [])) >= sbx.MAX_ITEMS:
                return jsonify(error=f"That list already has {sbx.MAX_ITEMS} scenarios: remove one first."), 400
            item = sbx.add(d, sc, g.user.id, g.user.display_name or g.user.username, sid)
            if sid_keep:                                 # keep its id, so its runs stay with it
                item["id"] = sid_keep
            _write(sb_path(scope), d)
        return jsonify(ok=True, item=dict(sbx.to_page(item), code=sbx.code(item), scope=scope))

    @app.post("/profiles/<int:pid>/trainer/sandbox/<sid>/delete")
    def trainer_sandbox_delete(pid: int, sid: str):
        view_profile(pid)
        scope = sb_scope(str((request.get_json(silent=True) or {}).get("scope") or "me"))
        with _lock:
            d = _read(sb_path(scope), {})
            it = next((x for x in d.get("items", []) if x["id"] == sid), None)
            if it is None or not sb_can_change(it, scope):
                abort(404)
            d["items"] = [x for x in d["items"] if x["id"] != sid]
            _write(sb_path(scope), d)
        return jsonify(ok=True)
