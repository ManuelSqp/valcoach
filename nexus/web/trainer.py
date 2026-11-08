"""Practice › Aim trainer and Practice › Mouse & monitor (per player). The pages do the work in the browser
(static/trainer.js, static/gearcheck.js); the server keeps the scores and the settings (stats/trainer.py) and
ticks off the warm-up or training on the Aim page when a whole one was played."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from flask import abort, g, jsonify, render_template, request

from ..stats import aim as am
from ..stats import aim_insights as ai
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


def register(app, store, sr, view_profile, filter_rows) -> None:
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
        return render_template("trainer.html", p=p, active_pid=pid, can_save=can_save(p, can_edit),
                               groups=tr.GROUPS, part_names=tr.PARTS, rec=rec, step=tr.sens_step(setup.get("sens"), rec["sens"]) if rec else None,
                               chart=sens_chart(rec) if rec else None,
                               scenarios=tr.scenario_list(), summary=tr.summary(runs), plans=pl,
                               start=start if start in pl else "", play=play if play in tr.SCENARIOS else "", setup=setup, numbers=tr.numbers(setup),
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
        run = tr.clean_run(b)
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
        row = next(x for x in tr.summary(d["runs"]) if x["id"] == run["s"])
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
