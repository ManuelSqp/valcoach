"""Team tab "Premier": this week's map and the pre-match brief, reviews of your Premier matches,
your division (scouted in advance), one team's scouting page with the map veto for playoffs."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..stats import roles
from ..stats.scouting import general_lines, map_lines, map_record, side_rates, veto
from ..stats.premier_schedule import current
from ..stats.weekly import week_id
from .premierjobs import PremierJobs

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TEAM_RE = re.compile(r"^\s*(.{1,40}?)\s*#\s*([^#\s]{1,10})\s*$")


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def season_week_map(seasons, now: datetime | None = None) -> str | None:
    """The fixed map of the current Premier week from the seasons data, if it can be read.
    The structure isn't documented, so: any object with a start/end around now and exactly one map."""
    now = now or datetime.now(timezone.utc)
    found: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            st, en = _ts(x.get("starts_at") or x.get("start_time")), _ts(x.get("ends_at") or x.get("end_time"))
            maps = (x.get("map_selection") or {}).get("maps") if isinstance(x.get("map_selection"), dict) else None
            if st and en and st <= now <= en and isinstance(maps, list) and len(maps) == 1:
                m = maps[0]
                name = m.get("name") if isinstance(m, dict) else m
                if isinstance(name, str):
                    found.append(name)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(seasons)
    return found[0] if found else None


def register(app, store, sr, helpers: dict) -> PremierJobs:
    get_team, team_data, build, known_maps = helpers["get_team"], helpers["team_data"], helpers["build"], helpers["known_maps"]
    pj = PremierJobs(sr)
    cache_dir = store.data_dir / "cache"

    def brief_cfg(t) -> dict:
        b = dict(t.sync_info.get("brief") or {})
        b.setdefault("on", False)
        b.setdefault("days", [])
        b.setdefault("time", "20:00")
        b.setdefault("before", 60)
        return b

    def pool(t) -> list[str]:
        return list(t.map_list) or sorted(known_maps)

    def week_map(t) -> tuple[str | None, str]:
        """(map, where it comes from) for this Premier week."""
        b = brief_cfg(t)
        if b.get("map") and b.get("map_week") == week_id():
            return b["map"], "set by hand"
        if t.premier_info.get("tag"):
            sched = pj.schedule_for(t)
            cur = current(sched)
            if cur["week"]:
                when = "coming week" if cur["upcoming"] else "this week"
                return cur["week"]["map"], f"Premier week {cur['week']['week']} ({when})" + (
                    "" if sched.get("source") == "Premier API" else ", built-in schedule")
        wk = week_id()
        for r in pj.reviews(t.id):
            d = _ts(r.get("started_at"))
            if d and week_id(d.astimezone().replace(tzinfo=None)) == wk and not r.get("tournament"):
                return r["map"], "your match this week"
        return None, ""

    from .availability import register as register_availability, summary_line
    _, next_avail = register_availability(app, store, get_team, {
        "brief_cfg": brief_cfg, "schedule_for": pj.schedule_for, "team_context": helpers["team_context"], "build": build})

    def our_records(t) -> tuple[dict, list]:
        d = team_data(t)
        return map_record(d["matches"]), d["matches"]

    # ------------------------------------------------------------------ brief
    def brief(t, map_name: str | None) -> dict:
        out: dict = {"map": map_name, "week": week_id()}
        try:
            out["avail"] = next_avail(t)
        except Exception:
            out["avail"] = None
        if not map_name:
            return out
        drafts = [d for d in store.drafts(t.id, map_name) if (d["data"] or {}).get("status") == "main"]
        names = {}
        for m in t.member_list:
            p = store.profile(m["pid"])
            if p:
                names[m["pid"]] = p.name
        if drafts:
            d = drafts[0]
            out["comp"] = {"source": f"draft “{d['name']}”",
                           "picks": [{"player": names.get(s.get("pid"), "?"), "agent": s.get("agent") or "?", "alt": s.get("alt") or "",
                                      "note": s.get("note") or ""} for s in d["data"].get("slots", []) if s.get("agent") or s.get("pid")]}
        else:
            b = build(t)
            c = next((c for c in (b["comps"].get(map_name) or []) if c.get("ok")), None)
            if c:
                out["comp"] = {"source": "suggested comp", "picks": [{"player": pk["player"], "agent": pk["agent"], "alt": "", "note": ""}
                                                                     for pk in c["picks"]]}
        plans = sr.read_plans(t.id, map_name) or {}
        out["plans"] = [{"title": p.get("title"), "side": p.get("side"), "idea": p.get("idea")} for p in plans.get("plans", [])[:3]]
        f = sr.read_focus(t.id) or {}
        out["focus"] = []
        for m in t.member_list:
            if m.get("kind") != "starter":
                continue
            fp = (f.get("players") or {}).get(str(m["pid"])) or {}
            if fp.get("focus"):
                out["focus"].append({"player": names.get(m["pid"], "?"), "focus": fp["focus"],
                                     "first": (fp.get("in_game") or [""])[0]})
        rec, matches = our_records(t)
        r = rec.get(map_name)
        sides = side_rates(matches, map_name)
        out["ours"] = {"games": r["games"] if r else 0, "wins": r["wins"] if r else 0,
                       "attack": sides["attack"], "defense": sides["defense"]}
        idx = pj.scout_index(t.id)
        threats = []
        for tm in (idx.get("teams") or {}).values():
            w, gms = (tm.get("maps") or {}).get(map_name, [0, 0])
            if gms:
                threats.append({"id": tm["id"], "name": tm["name"], "tag": tm.get("tag", ""), "wins": w, "games": gms})
        threats.sort(key=lambda x: (-(x["wins"] + 1) / (x["games"] + 2), -x["games"]))
        out["threats"] = threats[:4]
        out["scouted"] = len(idx.get("teams") or {})
        return out

    def brief_embed(t, b: dict) -> dict:
        lines = []
        a = b.get("avail")
        if a and a.get("today"):
            lines.append("**Who's playing:** " + summary_line(a))
        if b.get("comp"):
            lines.append("**Comp** (" + b["comp"]["source"] + "): " + " · ".join(
                f"**{p['agent']}** {p['player']}" + (f" (or {p['alt']})" if p.get("alt") else "") for p in b["comp"]["picks"]))
        o = b.get("ours") or {}
        if o.get("games"):
            sides = ""
            if o.get("attack") is not None:
                sides = f", rounds won: attack {o['attack']:.0%}, defense {o['defense']:.0%}"
            lines.append(f"**Our record on {b['map']}:** {o['wins']}–{o['games'] - o['wins']}{sides}")
        for p in b.get("plans", []):
            lines.append(f"{'⚔' if p.get('side') == 'attack' else '🛡'} **{p['title']}**: {p.get('idea') or ''}")
        if b.get("focus"):
            lines.append("**Focus today:** " + "; ".join(f"{f['player']}: {f['focus']}" for f in b["focus"]))
        if b.get("threats"):
            lines.append("**Strongest on this map in our division:** " + ", ".join(
                f"{x['name']} {x['wins']}–{x['games'] - x['wins']}" for x in b["threats"][:3]))
        lines.append("When you get matched: open the opponent under Premier › Division in valcoach.")
        return {"title": f"Match day: {b['map']}"[:250], "description": "\n".join(lines)[:3900], "color": 0xFF4655,
                "footer": {"text": f"{t.name} · valcoach brief"}}

    def post_brief(t) -> str:
        from ..discord import post as dpost
        url = t.discord_info.get("prep_url") or t.discord_info.get("focus_url")
        if not url:
            raise RuntimeError("Add a Discord webhook under Members, maps & Discord first.")
        m, _ = week_map(t)
        if not m:
            raise RuntimeError("This week's map isn't known yet: set it on the Premier tab.")
        dpost(url, "", embeds=[brief_embed(t, brief(t, m))])
        return m

    def tick_brief(now: datetime | None = None) -> list[int]:
        """Post the brief `before` minutes before the match time on match days (server time)."""
        now = now or datetime.now()
        done = []
        for t in store.all_teams():
            b = brief_cfg(t)
            if not b["on"] or now.weekday() not in b["days"]:
                continue
            try:
                hh, mm = (int(x) for x in str(b["time"]).split(":"))
            except ValueError:
                continue
            start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            mins = (start - now).total_seconds() / 60
            today = now.strftime("%Y-%m-%d")
            if not (0 <= mins <= int(b["before"])) or b.get("last_day") == today:
                continue
            info = t.sync_info
            info.setdefault("brief", {})
            info["brief"]["last_day"] = today
            store.update_team(t.id, sync=info)
            try:
                post_brief(t)
                done.append(t.id)
            except Exception:
                pass
        return done

    app.extensions["valcoach"].setdefault("ticks", []).append(tick_brief)
    app.extensions["valcoach"]["premier"] = pj
    app.extensions["valcoach"]["week_map"] = lambda t: week_map(t)[0]

    # ------------------------------------------------------------------ pages
    def ctx(t, tab2: str, **kw) -> dict:
        return dict(t=t, tab="premier", tab2=tab2, premier_status=None, pi=t.premier_info, **kw)

    @app.get("/teams/<int:tid>/premier")
    def team_premier(tid: int):
        t = get_team(tid)
        if t.premier_info.get("tag"):
            _, fetched = pj.read_seasons(t.premier_info.get("region") or "eu")
            if time.time() - fetched > 86400:           # refresh the schedule in the background once a day
                pj.submit_schedule(tid)
            if pj.apply_pool(t):
                t = get_team(tid)
        sched = pj.schedule_for(t) if t.premier_info.get("tag") else None
        cur = current(sched) if sched else None
        results: dict[str, list] = {}
        for r in pj.reviews(tid):
            if sched and not r.get("tournament"):
                day = (r.get("started_at") or "")[:10]
                w = next((w for w in sched["weeks"] if w["starts"] <= day <= w["ends"]), None)
                if w:
                    results.setdefault(str(w["week"]), []).append(r)
        m, src = week_map(t)
        b = brief(t, m)
        return render_template("premier.html", **ctx(t, "overview", week_map=m, week_src=src, b=b, cfg=brief_cfg(t),
                                                      sched=sched, cur=cur, results=results, today=datetime.now().date().isoformat(),
                                                      reviews=pj.reviews(tid)[:8], pool=pool(t), days=DAYS,
                                                      rstatus=sr.status(f"review:{tid}"), discord=t.discord_info))

    @app.get("/teams/<int:tid>/premier/seasons.json")
    def team_seasons_raw(tid: int):
        """What HenrikDev returned for the season schedule (for checking the format)."""
        t = get_team(tid, manage=True)
        data, fetched = pj.read_seasons(t.premier_info.get("region") or "eu")
        return jsonify(fetched_at=fetched, data=data)

    @app.get("/teams/<int:tid>/premier/division")
    def team_division(tid: int):
        t = get_team(tid)
        idx = pj.scout_index(tid)
        div = idx.get("division") or {}
        scouted = idx.get("teams") or {}
        rows = []
        for tm in div.get("teams") or []:
            s = scouted.get(tm["id"]) or {}
            rows.append({**tm, "scouted_at": s.get("scouted_at"), "matches": s.get("matches"), "maps": s.get("maps") or {},
                         "ours": tm["id"] == div.get("ours")})
        others = [s for k, s in scouted.items() if k not in {r["id"] for r in rows}]
        return render_template("premier_division.html", **ctx(t, "division", div=div, rows=rows, others=others,
                                                               status=sr.status(f"scout:{tid}"), wm=week_map(t)[0]))

    @app.post("/teams/<int:tid>/premier/scout")
    def team_scout(tid: int):
        t = get_team(tid)
        if not t.premier_info.get("tag"):
            flash("Link the team to Premier first (Teams › new team from Premier, or Sync Premier roster).", "error")
            return redirect(url_for("team_premier", tid=tid))
        q = (request.form.get("q") or "").strip()
        if request.form.get("division"):
            pj.submit_scout(tid, {"division": True})
            flash("Scouting your division in the background: the first time takes a few minutes (HenrikDev rate limit).", "ok")
        elif q:
            m = TEAM_RE.match(q)
            if not m:
                flash("Write the team as Name#TAG.", "error")
                return redirect(url_for("team_division", tid=tid))
            pj.submit_scout(tid, {"name": m.group(1), "tag": m.group(2)})
            flash(f"Scouting {m.group(1)}#{m.group(2)} …", "ok")
        elif request.form.get("id"):
            tm = (pj.scout_index(tid).get("teams") or {}).get(request.form["id"]) or next(
                (x for x in (pj.scout_index(tid).get("division") or {}).get("teams") or [] if x["id"] == request.form["id"]), None)
            if not tm:
                abort(404)
            pj.submit_scout(tid, {k: tm.get(k) for k in ("id", "name", "tag", "wins", "losses", "points", "place")})
            flash(f"Scouting {tm['name']} again …", "ok")
            return redirect(url_for("team_scouted", tid=tid, team_id=tm["id"]))
        return redirect(url_for("team_division", tid=tid))

    @app.get("/teams/<int:tid>/premier/team/<team_id>")
    def team_scouted(tid: int, team_id: str):
        t = get_team(tid)
        s = pj.scouted(tid, team_id)
        if s is None:
            abort(404)
        rec, matches = our_records(t)
        mp = pool(t)
        our_sides = {m: side_rates(matches, m) for m in mp}
        their_sides = {m: (v.get("sides") or {}) for m, v in s.get("maps", {}).items()}
        v = veto(rec, {m: {"games": x["games"], "wins": x["wins"]} for m, x in s.get("maps", {}).items()}, mp, our_sides, their_sides)
        wm = week_map(t)[0]
        roles.load(cache_dir)
        mlines = {m: map_lines(s, m) for m in s.get("maps", {})}
        return render_template("premier_team.html", **ctx(t, "division", s=s, v=v, lines=general_lines(s), mlines=mlines, wm=wm,
                                                           status=sr.status(f"scout:{tid}")))

    @app.get("/teams/<int:tid>/premier/review/<match_id>")
    def team_review_page(tid: int, match_id: str):
        t = get_team(tid)
        r = pj.review(tid, match_id)
        if r is None:
            abort(404)
        return render_template("premier_review.html", **ctx(t, "overview", r=r))

    @app.post("/teams/<int:tid>/premier/reviews")
    def team_reviews_run(tid: int):
        t = get_team(tid, manage=True)
        if not t.premier_info.get("tag"):
            abort(400)
        force = request.form.get("force") or None
        if force and not re.fullmatch(r"[A-Za-z0-9-]{8,64}", force):
            abort(400)
        pj.submit_reviews(tid, post=bool(request.form.get("post")), force=force)
        flash("Reviewing your Premier matches in the background.", "ok")
        return redirect(url_for("team_premier", tid=tid))

    @app.get("/teams/<int:tid>/premier/brief")
    def team_brief(tid: int):
        t = get_team(tid)
        m = request.args.get("map") or week_map(t)[0]
        if m and m not in pool(t) and m not in known_maps:
            abort(404)
        return render_template("premier_brief.html", **ctx(t, "overview", b=brief(t, m) if m else {"map": None},
                                                           pool=pool(t), discord=t.discord_info))

    @app.post("/teams/<int:tid>/premier/brief/post")
    def team_brief_post(tid: int):
        t = get_team(tid, manage=True)
        try:
            m = post_brief(t)
            flash(f"Posted the {m} brief to Discord.", "ok")
        except Exception as e:
            flash(str(e), "error")
        return redirect(url_for("team_premier", tid=tid))

    @app.post("/teams/<int:tid>/premier/settings")
    def team_premier_settings(tid: int):
        t = get_team(tid, manage=True)
        f = request.form
        info = t.sync_info
        b = dict(info.get("brief") or {})
        if "follow_pool" in f:                                # team maps follow the stage's map pool
            pi = dict(t.premier_info)
            pi["follow_pool"] = f.get("follow_pool") == "1"
            store.update_team(tid, premier=pi)
            if pi["follow_pool"]:
                pj.apply_pool(get_team(tid))
            flash("Map pool: " + ("follows the Premier stage." if pi["follow_pool"] else "your own list (Members, maps & Discord)."), "ok")
            return redirect(url_for("team_premier", tid=tid) + "#schedule")
        if "week_map" in f:                                   # the week's map, by hand (only for this week)
            m = f.get("week_map", "")
            if m and m not in pool(t) and m not in known_maps:
                abort(400)
            b.update(map=m, map_week=week_id() if m else "")
        else:
            b["on"] = bool(f.get("on"))
            b["days"] = sorted({int(d) for d in f.getlist("days") if d.isdigit() and 0 <= int(d) <= 6})
            tm = f.get("time", "20:00")
            b["time"] = tm if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", tm) else "20:00"
            try:
                b["before"] = max(10, min(240, int(f.get("before", 60))))
            except ValueError:
                b["before"] = 60
        info["brief"] = b
        store.update_team(tid, sync=info)
        flash("Saved.", "ok")
        return redirect(url_for("team_premier", tid=tid))

    return pj
