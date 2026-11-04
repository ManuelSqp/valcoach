"""Player tabs "Progress" (rank over time, week by week, did the weekly focus work, clutches and
retakes), "Quiz" (decisions from your own rounds) and
"Training" (aim fundamentals, a warm-up routine with a streak, teammates to learn from,
agents to learn with a learning path)."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

from flask import abort, g, jsonify, redirect, render_template, request, url_for

from ..stats import progress as prog
from ..stats import roles
from ..stats import training as tr
from ..stats.aggregate import by_map, filter_rows, local_meta


def register(app, store, sr, helpers: dict) -> None:
    view_profile, team_context, owner_rows = helpers["view_profile"], helpers["team_context"], helpers["owner_rows"]
    queue_arg, queues = helpers["queue_arg"], helpers["queues"]
    cache_dir = store.data_dir / "cache"

    def teams_of(pid: int) -> list:
        return [t for t in store.teams_for_user(g.user.id) if any(m["pid"] == pid for m in t.member_list)]

    def all_rows(pid: int) -> list[dict]:
        return sorted(sr.games(pid).rows(), key=lambda r: r.get("started_at", ""), reverse=True)

    # ------------------------------------------------------------------ progress
    @app.get("/profiles/<int:pid>/progress")
    def progress(pid: int):
        p, can_edit = view_profile(pid)
        roles.load(cache_dir)
        queue = queue_arg()
        rows = filter_rows(all_rows(pid), queue)
        weeks = prog.weekly(rows, 10)
        cards = []
        for k in prog.ORDER:
            vals = [w["values"][k] for w in weeks]
            present = [v for v in vals if v is not None]
            if not present:
                continue
            top = max(present) or 1
            lo = 0 if prog.METRICS[k][2] == "pct" else min(present) * 0.8
            bars = [{"h": None if v is None else max(0.04, (v - lo) / ((top - lo) or 1)), "v": prog.fmt(k, v),
                     "label": w["label"], "games": w["games"]} for v, w in zip(vals, weeks)]
            cards.append({"key": k, "label": prog.METRICS[k][0], "trend": prog.trend(rows, k), "bars": bars,
                          "fmt": lambda v, k=k: prog.fmt(k, v), "higher": prog.METRICS[k][3]})
        # did the weekly focus work? (every team this player is in, last 6 weeks)
        checks = []
        for t in teams_of(pid):
            d = sr.team_dir(t.id) / "focus"
            for f in sorted(d.glob("*.json"), reverse=True)[:6] if d.exists() else []:
                try:
                    data = json.loads(f.read_text())
                except ValueError:
                    continue
                fp = (data.get("players") or {}).get(str(pid))
                if not fp or not fp.get("focus"):
                    continue
                ck = prog.focus_check(rows, data.get("week") or f.stem, fp)
                if ck:
                    ck.update({f"{k}_s": prog.fmt(ck["metric"], ck[k]) for k in ("before", "now", "goal")})
                checks.append({"team": t.name, "week": data.get("week") or f.stem, "focus": fp["focus"], "check": ck})
        # clutches, retakes, post-plants
        full = [r for r in rows if r.get("source") == "full"]
        cl = {str(x): [0, 0] for x in range(1, 6)}
        rt, pp = [0, 0], [0, 0]
        for r in full:
            for x, (a, w) in (r.get("clutch") or {}).items():
                if x in cl:
                    cl[x][0] += a
                    cl[x][1] += w
            for key, acc in (("retake", rt), ("postplant", pp)):
                v = r.get(key) or [0, 0]
                acc[0] += v[0]
                acc[1] += v[1]
        v3 = sum(1 for r in full if "clutch" in r)
        # rank over time (competitive only, whatever queue tab is open)
        from ..stats import rank as rk
        pts, rank_src = rk.series(rk.RankStore(sr.rank_path(pid)).load(), all_rows(pid))
        return render_template("progress.html", p=p, active_pid=pid, queue=queue, queues=queues, tab="progress",
                               can_edit=can_edit, weeks=weeks, cards=cards, checks=checks, clutch=cl, retake=rt,
                               postplant=pp, n_full=len(full), n_v3=v3, n=len(rows),
                               rank=rk.summary(pts), rank_chart=rk.chart(pts), rank_src=rank_src,
                               reports={j.match_id: j.id for j in reversed(store.jobs(pid, 500)) if j.status == "done"} if can_edit else {})

    # ------------------------------------------------------------------ quiz
    @app.route("/profiles/<int:pid>/quiz", methods=["GET", "POST"])
    def quiz(pid: int):
        from ..stats.quiz import KINDS, by_kind
        p, can_edit = view_profile(pid)
        if request.method == "POST":
            if not can_edit:
                abort(403)
            from .models import picked
            sr.submit_quiz(pid, picked(store))
            return redirect(url_for("quiz", pid=pid))
        q = sr.read_quiz(pid)
        res = q.get("results") or []
        kinds = [{"kind": k, "label": KINDS.get(k, k), "right": v[0], "total": v[1]} for k, v in by_kind(res).items()]
        kinds.sort(key=lambda x: x["right"] / max(1, x["total"]))
        return render_template("quiz.html", p=p, active_pid=pid, tab="quiz", can_edit=can_edit, q=q,
                               status=sr.status(f"quiz:{pid}"), results=res[-10:], kinds=kinds,
                               best=max((r["score"] / r["of"] for r in res if r.get("of")), default=None),
                               result_url=url_for("quiz_result", pid=pid), rate_url=url_for("quiz_rate", pid=pid),
                               focus_url=url_for("own_focus", pid=pid), own=sr.read_own_focus(pid))

    @app.post("/api/profiles/<int:pid>/quiz/result")
    def quiz_result(pid: int):
        p, can_edit = view_profile(pid)
        if not can_edit:
            abort(403)
        body = request.get_json(silent=True)
        q = sr.read_quiz(pid)
        if not isinstance(body, dict) or not q.get("questions"):
            return jsonify(error="no quiz"), 400
        answers = body.get("answers")
        if not isinstance(answers, list) or len(answers) != len(q["questions"]):
            return jsonify(error="answers don't match the quiz"), 400
        per = [{"kind": qq.get("kind", "?"), "ok": isinstance(a, int) and not isinstance(a, bool) and a == qq["best"]}
               for a, qq in zip(answers, q["questions"])]
        score = sum(x["ok"] for x in per)
        q.setdefault("results", []).append({"t": time.time(), "created": q.get("created"), "score": score,
                                            "of": len(q["questions"]), "answers": per})
        q["results"] = q["results"][-60:]
        sr.save_quiz(pid, q)
        return jsonify(ok=True, score=score, of=len(q["questions"]))

    @app.post("/api/profiles/<int:pid>/quiz/rate")
    def quiz_rate(pid: int):
        """good / unrealistic / obvious: shapes the next quiz."""
        from ..stats.quiz import RATINGS
        p, can_edit = view_profile(pid)
        if not can_edit:
            abort(403)
        body = request.get_json(silent=True) or {}
        q = sr.read_quiz(pid)
        qq = next((x for x in q.get("questions") or [] if x.get("id") == body.get("id")), None)
        if qq is None or body.get("rating") not in RATINGS:
            return jsonify(error="unknown question or rating"), 400
        qq["rating"] = body["rating"]
        bank = [b for b in q.get("bank") or [] if not (b.get("created") == q.get("created") and b.get("id") == qq["id"])]
        bank.append({"created": q.get("created"), "id": qq["id"], "kind": qq.get("kind"), "rating": body["rating"],
                     "question": qq["question"], "best_text": qq["options"][qq["best"]]})
        q["bank"] = bank[-40:]
        sr.save_quiz(pid, q)
        return jsonify(ok=True)

    @app.route("/api/profiles/<int:pid>/own-focus", methods=["POST", "DELETE"])
    def own_focus(pid: int):
        """Your own focus for this week, picked from a quiz question or a report line."""
        p, can_edit = view_profile(pid)
        if not can_edit:
            abort(403)
        if request.method == "DELETE":
            sr.set_own_focus(pid, None)
            return jsonify(ok=True)
        body = request.get_json(silent=True) or {}
        focus = str(body.get("focus") or "").strip()[:160]
        if not focus:
            return jsonify(error="focus is empty"), 400
        src = body.get("source") if body.get("source") in ("quiz", "report") else "own"
        sr.set_own_focus(pid, {"focus": focus, "why": str(body.get("why") or "").strip()[:400], "source": src,
                               "ref": str(body.get("ref") or "")[:80]})
        return jsonify(ok=True)

    # ------------------------------------------------------------------ training
    def streak_file(pid: int):
        return store.profile_dir(pid) / "stats" / "training.json"

    def streak(pid: int) -> dict:
        try:
            done = set(json.loads(streak_file(pid).read_text()).get("done", []))
        except (OSError, ValueError):
            done = set()
        today = date.today()
        d = today if today.isoformat() in done else today - timedelta(days=1)
        n = 0
        while d.isoformat() in done:
            n += 1
            d -= timedelta(days=1)
        last14 = [{"day": (today - timedelta(days=i)).isoformat(), "done": (today - timedelta(days=i)).isoformat() in done,
                   "label": (today - timedelta(days=i)).strftime("%a %d.%m")} for i in range(13, -1, -1)]
        return {"streak": n, "today": today.isoformat() in done, "last14": last14, "total": len(done)}

    @app.post("/profiles/<int:pid>/training/done")
    def training_done(pid: int):
        p, can_edit = view_profile(pid)
        if not can_edit:
            abort(403)
        f = streak_file(pid)
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            data = {"done": []}
        today = date.today().isoformat()
        done = set(data.get("done", []))
        done.symmetric_difference_update({today})
        data["done"] = sorted(done)[-400:]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data))
        return redirect(url_for("training", pid=pid) + "#routine")

    def team_learning(t, pid: int, rows: list[dict]) -> dict | None:
        """This player's agents to learn in one team (from the roles), each with its learning path."""
        from ..stats.style import load_pros
        from ..stats.teamroles import team_roles
        c = team_context(t)
        members = [{"label": c["byid"][m["pid"]].name, "pid": m["pid"], "kind": m["kind"],
                    "rows": c["rows_by"][m["pid"]], "assigned": m.get("roles", [])} for m in c["members"]]
        if not members:
            return None
        maps = t.map_list or [m["map"] for m in by_map([r for rs in c["rows_by"].values() for r in rs])][:7]
        res = team_roles(members, local_meta(filter_rows(owner_rows(t.owner_id), t.queue)), maps)
        me = next((x for x in res["players"] if x["pid"] == pid), None)
        if not me:
            return None
        try:
            pros = load_pros(store.get("pros_yaml"))
        except Exception:
            pros = load_pros("")
        paths = [{**tr.learn_path(a["agent"], rows, maps, pros), "why": a["why"]} for a in me.get("learn_list") or []]
        profiles = {c["byid"][m["pid"]].name: tr.aim_profile(c["rows_by"][m["pid"]]) for m in c["members"]}
        return {"team": t, "role": me.get("role_for_agent"), "paths": paths,
                "refs": tr.team_refs(c["byid"][pid].name if pid in c["byid"] else "", profiles)}

    @app.get("/profiles/<int:pid>/training")
    def training(pid: int):
        p, can_edit = view_profile(pid)
        roles.load(cache_dir)
        rows = all_rows(pid)
        from ..stats.quiz import KINDS, by_kind
        a = tr.aim_profile(rows)
        diag = tr.diagnose(a) + tr.quiz_diag(by_kind(sr.read_quiz(pid).get("results") or []), KINDS)
        teams = [x for x in (team_learning(t, pid, rows) for t in teams_of(pid)) if x]
        return render_template("training.html", p=p, active_pid=pid, queue="all", queues=queues, tab="training",
                               can_edit=can_edit, a=a, diag=diag, routine=tr.routine(diag), st=streak(pid), teams=teams,
                               close_m=tr.CLOSE_M, long_m=tr.LONG_M, own=sr.read_own_focus(pid),
                               focus_url=url_for("own_focus", pid=pid))
