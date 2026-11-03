"""Team › Practice › Practice plan: this week's practice sessions, made from the team's habits,
the week's map, its strats and lineups, and the newest review. Anyone in the team can tick items off
and add their own; the owner sets days and time, makes it again and posts it to Discord."""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..stats import habits as hb
from ..stats import practice as pr
from ..stats.weekly import week_id


def register(app, store, sr, get_team) -> None:
    def cfg_of(t) -> dict:
        c = dict(pr.DEFAULT)
        c.update((t.sync_info.get("practice") or {}))
        return c

    def path(tid: int, week: str):
        return sr.team_dir(tid) / "practice" / f"{week}.json"

    def read(tid: int, week: str) -> dict | None:
        try:
            return json.loads(path(tid, week).read_text())
        except (OSError, ValueError):
            return None

    def write(tid: int, plan: dict) -> None:
        p = path(tid, plan["week"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan, ensure_ascii=False))
        tmp.replace(p)

    def context(t) -> dict:
        ext = app.extensions["valcoach"]
        m = ext["week_map"](t) if "week_map" in ext and t.premier_info.get("tag") else None
        m = m or (list(t.map_list)[0] if t.map_list else None)
        strats = {"attack": [], "defense": []}
        for s in store.strats(t.id):
            if s["map"] == m and s["side"] in strats:
                strats[s["side"]].append(s["name"])
        lineups: dict[str, int] = {}
        for r in (store.lineups(t.id, m) if m else []):
            lineups[r["agent"]] = lineups.get(r["agent"], 0) + 1
        members, personal = {}, {}
        for mm in t.member_list:
            if mm.get("kind") != "starter":
                continue
            p = store.profile(mm["pid"])
            if not p:
                continue
            h = hb.track(sr.games(p.id).rows())
            members[p.name] = h
            personal[p.name] = [{"title": x["title"], "drill": x["drill"], "status": x["status_text"]} for x in h.get("problems", [])[:2]]
        review = None
        pj = ext.get("premier")
        if pj:
            rv = pj.reviews(t.id)
            if rv:
                r = rv[0]
                review = {"title": f"the {r.get('map', '')} review vs {r.get('opponent', '')}".replace("  ", " "),
                          "url": url_for("team_review_page", tid=t.id, match_id=r.get("match_id", ""))}
        f = sr.read_focus(t.id) or {}
        focus = any(v.get("focus") for v in (f.get("players") or {}).values())
        from .availability import DEFAULT_DAYS
        brief = t.sync_info.get("brief") or {}
        return {"map": m, "strats": strats, "lineups": lineups, "habits": pr.team_habits(members), "personal": personal,
                "review": review, "match_days": brief.get("days") or DEFAULT_DAYS, "focus": focus}

    def make(t, week: str) -> dict:
        plan = pr.build(week, pr.monday(), cfg_of(t), context(t))
        write(t.id, plan)
        return plan

    def links(t, plan: dict) -> dict:
        m = plan.get("map")
        return {"brief": url_for("team_match", tid=t.id) if m else "", "habits": "",
                "strats": url_for("team_strats", tid=t.id) + (f"#map-{m}" if m else ""),
                "lineups": url_for("team_lineups", tid=t.id, map=m) if m else url_for("team_lineups", tid=t.id)}

    @app.get("/teams/<int:tid>/practice")
    def team_practice(tid: int):
        t = get_team(tid)
        week = week_id()
        plan = read(tid, week) or make(t, week)
        done, total = pr.progress(plan)
        pids = {store.profile(m["pid"]).name: m["pid"] for m in t.member_list if store.profile(m["pid"])}
        return render_template("team_practice.html", t=t, tab="practice", premier_status=None, plan=plan, cfg=cfg_of(t),
                               weekday=pr.WEEKDAY, done=done, total=total, links=links(t, plan), pids=pids, today_iso=date.today().isoformat(),
                               discord=bool(t.discord_info.get("focus_url") or t.discord_info.get("prep_url")))

    @app.post("/api/teams/<int:tid>/practice")
    def team_practice_api(tid: int):
        """Tick an item, add one, remove one (removing: the owner or whoever added it)."""
        t = get_team(tid)
        b = request.get_json(silent=True) or {}
        week = week_id()
        plan = read(tid, week) or make(t, week)
        day = next((d for d in plan["days"] if d["date"] == b.get("day")), None)
        if day is None:
            return jsonify(error="unknown day"), 400
        act = b.get("action")
        if act == "tick":
            it = next((x for x in day["items"] if x["id"] == b.get("id")), None)
            if it is None:
                return jsonify(error="unknown item"), 400
            it["done"] = bool(b.get("done"))
            it["by"] = g.user.display_name or g.user.username
        elif act == "add":
            title = str(b.get("title") or "").strip()[:100]
            if not title:
                return jsonify(error="the item needs a name"), 400
            try:
                minutes = max(0, min(240, int(b.get("minutes") or 15)))
            except ValueError:
                minutes = 15
            day["items"].append({"id": pr._id(), "kind": "own", "title": title, "detail": str(b.get("detail") or "").strip()[:300],
                                 "minutes": minutes, "who": "team", "link": "", "done": False,
                                 "added_by": g.user.id, "by": g.user.display_name or g.user.username})
        elif act == "remove":
            it = next((x for x in day["items"] if x["id"] == b.get("id")), None)
            if it is None:
                return jsonify(error="unknown item"), 400
            if not (g.team_owner or it.get("added_by") == g.user.id):
                return jsonify(error="only the team owner can remove planned items"), 403
            day["items"].remove(it)
        else:
            return jsonify(error="unknown action"), 400
        write(tid, plan)
        done, total = pr.progress(plan)
        return jsonify(ok=True, done=done, total=total)

    @app.post("/teams/<int:tid>/practice")
    def team_practice_settings(tid: int):
        t = get_team(tid, manage=True)
        f = request.form
        if f.get("action") == "remake":
            make(t, week_id())
            flash("Practice plan made again from the team's current numbers.", "ok")
        elif f.get("action") == "post":
            from ..discord import channel, post as dpost
            url = channel(t.discord_info, "focus")
            plan = read(tid, week_id()) or make(t, week_id())
            try:
                if not url:
                    raise RuntimeError("Add a Discord webhook under Team settings first.")
                dpost(url, pr.discord_text(plan, t.name))
                flash("Posted the practice plan to Discord.", "ok")
            except Exception as e:
                flash(f"Not posted: {e}", "error")
        else:
            days = sorted({int(d) for d in f.getlist("days") if str(d).isdigit() and 0 <= int(d) <= 6})
            time = f.get("time", "19:00")
            if not re.fullmatch(r"\d{1,2}:\d{2}", time):
                time = "19:00"
            try:
                minutes = max(30, min(240, int(f.get("minutes") or 90)))
            except ValueError:
                minutes = 90
            info = t.sync_info
            info["practice"] = {"days": days or pr.DEFAULT_DAYS, "time": time, "minutes": minutes, "post": f.get("post") == "1"}
            store.update_team(tid, sync=info)
            make(store.team(tid), week_id())
            flash("Practice days saved; this week's plan was made again.", "ok")
        return redirect(url_for("team_practice", tid=tid))

    def tick() -> list[int]:
        """On practice days, 60 min before: a reminder to Discord (if on) and to everyone's devices."""
        from . import push
        now = datetime.now()
        done = []
        for t in store.all_teams():
            c = cfg_of(t)
            if now.weekday() not in (c.get("days") or []):
                continue
            try:
                hh, mm = (int(x) for x in str(c.get("time") or "19:00").split(":"))
            except ValueError:
                continue
            mins = (now.replace(hour=hh, minute=mm, second=0, microsecond=0) - now).total_seconds() / 60
            today = date.today().isoformat()
            if not (0 <= mins <= 60) or (t.sync_info.get("practice_sent") == today):
                continue
            info = t.sync_info
            info["practice_sent"] = today
            store.update_team(t.id, sync=info)
            plan = read(t.id, week_id())
            day = next((d for d in (plan or {}).get("days", []) if d["date"] == today), None)
            what = ", ".join(it["title"] for it in (day or {}).get("items", [])[:4]) or "practice"
            if c.get("post"):
                from ..discord import channel, post as dpost
                url = channel(t.discord_info, "focus")
                if url:
                    try:
                        dpost(url, f"**Practice today at {c['time']}** ({t.name}): {what}")
                    except Exception:
                        pass
            for u in store.users():
                if any(x.id == t.id for x in store.teams_for_user(u.id)):
                    push.send(store, u.id, f"Practice today at {c['time']}", what, url=f"/teams/{t.id}/practice",
                              tag=f"practice-{t.id}", kind="practice")
            done.append(t.id)
        return done

    app.extensions["valcoach"].setdefault("ticks", []).append(tick)
