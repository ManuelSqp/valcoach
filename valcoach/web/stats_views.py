"""Stats, pick helper and team (Premier) pages."""
from __future__ import annotations

import json
import time

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from ..maps import AgentRegistry
from ..stats import roles
from ..stats.aggregate import by_agent, by_map, by_role, filter_rows, local_meta, map_detail, summary
from ..stats.comp import META_EXAMPLE, Pool, parse_meta, pick_helper, team_plan
from .statsjobs import StatsRunner, slug

def week_map_of(app, t) -> str | None:
    """This Premier week's map for a team (None if not a Premier team or not known)."""
    fn = app.extensions["valcoach"].get("week_map")
    try:
        return fn(t) if fn and t.premier_info.get("tag") else None
    except Exception:
        return None


QUEUE_TABS = [("all", "All ranked"), ("competitive", "Competitive"), ("premier", "Premier")]
# fallback when nobody has games yet; maps with games are added automatically
KNOWN_MAPS = ["Abyss", "Ascent", "Bind", "Breeze", "Corrode", "Fracture", "Haven", "Icebox", "Lotus",
              "Pearl", "Split", "Summit", "Sunset"]


def register(app, store, sr: StatsRunner, get_profile) -> None:
    cache_dir = store.data_dir / "cache"
    agents_reg = AgentRegistry(cache_dir)

    def queue_arg(default: str = "all") -> str:
        q = request.args.get("queue", default)
        return q if q in dict(QUEUE_TABS) else default

    def owner_rows(uid: int) -> list[dict]:
        out = []
        for p in store.profiles(uid):
            out.extend(sr.games(p.id).rows())
        return out

    def get_team(tid: int, manage: bool = False):
        """Owner: everything. Teammates you added: view, notes, link themselves. Others: 404."""
        t = store.team(tid)
        if t is None:
            abort(404)
        owner = t.owner_id == g.user.id
        if not owner and not store.has_team_access(tid, g.user.id):
            abort(404)
        if manage and not owner:
            abort(403)
        g.team_owner = owner
        return t

    def view_profile(pid: int):
        """Your own players, or a player in a team you were added to (read-only). -> (profile, can_edit)"""
        p = store.profile(pid)
        if p is None:
            abort(404)
        if p.owner_id == g.user.id:
            return p, True
        for t in store.teams_for_user(g.user.id):
            if t.owner_id == p.owner_id and any(m["pid"] == pid for m in t.member_list):
                return p, False
        abort(404)

    @app.template_filter("pct")
    def pct(v) -> str:
        return "–" if v is None else f"{v * 100:.0f}%"

    @app.template_filter("num")
    def num(v, digits: int = 0) -> str:
        return "–" if v is None else f"{v:.{digits}f}"

    icon_misses: dict[str, float] = {}

    @app.get("/agent-icon/<path:name>")
    def agent_icon(name: str):
        # offline or unknown agent: don't retry the download on every page view
        if time.time() - icon_misses.get(name, 0) < 600:
            abort(404)
        try:
            a = agents_reg.find(name=name)
            f = agents_reg.icon_file(a) if a else None
        except Exception:
            f = None
        if not f or not f.exists():
            icon_misses[name] = time.time()
            abort(404)
        return send_file(f, mimetype="image/png", max_age=86400)

    # ------------------------------------------------------------------ stats
    @app.get("/profiles/<int:pid>/stats")
    def stats(pid: int):
        p, can_edit = view_profile(pid)
        roles.load(cache_dir)
        queue = queue_arg()
        data = sr.games(pid).load()
        rows = filter_rows(sorted(data["games"].values(), key=lambda r: r.get("started_at", ""), reverse=True), queue)
        maps = by_map(rows)
        sel = request.args.get("map") or (maps[0]["map"] if maps else None)
        if sel and not any(m["map"] == sel for m in maps):
            sel = maps[0]["map"] if maps else None
        everyone = owner_rows(p.owner_id)
        meta_all = local_meta(filter_rows(everyone, queue))
        pick = None
        pick_map = request.args.get("pick_map", "")
        locked = [a for a in request.args.getlist("locked") if a][:4]
        if pick_map:
            pick = pick_helper(Pool.from_rows(p.name, rows), pick_map, locked, meta_all.get(pick_map))
        return render_template(
            "stats.html", p=p, active_pid=pid, queue=queue, queues=QUEUE_TABS, rows=rows, data=data,
            total=summary(rows), maps=maps, agents=by_agent(rows), roles_t=by_role(rows), sel=sel,
            detail=map_detail(rows, sel) if sel else None, meta=meta_all.get(sel) if sel else None,
            tips=sr.read_tips(pid, sel, queue) if sel else None,
            import_status=sr.status(f"import:{pid}"),
            tips_status=sr.status(f"tips:{pid}:{slug(sel)}:{queue}") if sel else None,
            tips_key=f"tips:{pid}:{slug(sel)}:{queue}" if sel else "",
            all_agents=roles.all_agents(), map_names=sorted({m["map"] for m in maps} | set(KNOWN_MAPS)), tab="stats",
            can_edit=can_edit,
            pick=pick, pick_map=pick_map, locked=locked + [""] * (4 - len(locked)),
            recent=rows[:12])

    def pro_context(p, queue: str, pro: str | None = None) -> dict:
        from ..stats.style import load_pros, match_pros, profile, video_queries
        roles.load(cache_dir)
        rows = filter_rows(sr.games(p.id).rows(), queue)
        prof = profile(rows)
        pros_error = None
        try:
            pros = load_pros(store.get("pros_yaml"))
        except Exception as e:
            pros, pros_error = load_pros(""), str(e)
        matches = match_pros(prof, pros)
        chosen = next((m for m in matches if m["name"] == pro), matches[0] if matches else None)
        queries = video_queries(rows, prof, matches, pro=chosen["name"] if chosen else None) if rows else []
        return {"rows": rows, "prof": prof, "matches": matches, "queries": queries, "pros_error": pros_error,
                "n_pros": len(pros), "chosen": chosen}

    @app.get("/profiles/<int:pid>/pros")
    def pros(pid: int):
        p, can_edit = view_profile(pid)
        queue = queue_arg()
        c = pro_context(p, queue, request.args.get("pro"))
        by_pro = sr.read_watch(pid, queue)["by_pro"]
        closest = c["matches"][0]["name"] if c["matches"] else ""
        chosen = c["chosen"]["name"] if c["chosen"] else ""
        saved = by_pro.get(chosen) or (by_pro.get("") if chosen == closest else None)
        # attach saved videos / notes to the current searches (matched by search text)
        guide, errors, created = None, [], None
        if saved:
            by_query = {q["query"]: q for q in saved.get("queries", [])}
            guide, errors, created = saved.get("guide"), saved.get("errors", []), saved.get("_created")
            notes = {i["id"]: i["watch_for"] for i in (guide or {}).get("items", [])}
            for q in c["queries"]:
                old = by_query.get(q["query"])
                if old:
                    q["videos"] = old.get("videos", [])
                    q["watch_for"] = notes.get(old["id"])
        ready = {m["name"] for m in c["matches"] if (by_pro.get(m["name"]) or (by_pro.get("") if m["name"] == closest else None) or {}).get("guide")}
        return render_template("pros.html", p=p, active_pid=pid, queue=queue, queues=QUEUE_TABS, tab="pros", can_edit=can_edit,
                               guide=guide, errors=errors, created=created, yt=bool(store.get("youtube_api_key")), ready=ready,
                               status=sr.status(f"watch:{pid}:{queue}"), status_key=f"watch:{pid}:{queue}", **c)

    @app.post("/profiles/<int:pid>/pros/build")
    def pros_build(pid: int):
        from ..stats.style import video_queries
        p = get_profile(pid)
        queue = request.form.get("queue", "all")
        queue = queue if queue in dict(QUEUE_TABS) else "all"
        pro = request.form.get("pro") or None
        c = pro_context(p, queue, pro)
        if c["queries"] and c["chosen"]:
            names = [m["name"] for m in c["matches"]] if request.form.get("all") else [c["chosen"]["name"]]
            jobs = [{"pro": n, "queries": c["queries"] if n == c["chosen"]["name"] else video_queries(c["rows"], c["prof"], c["matches"], pro=n)}
                    for n in names]
            sr.submit_watch(pid, queue, c["prof"], c["matches"], jobs)
        return redirect(url_for("pros", pid=pid, queue=queue, pro=c["chosen"]["name"] if c["chosen"] else None) + "#pros")

    @app.post("/profiles/<int:pid>/stats/import")
    def stats_import(pid: int):
        get_profile(pid)
        if not store.get("henrik_api_key"):
            flash("No HenrikDev API key is set yet.", "error")
        else:
            sr.submit_import(pid)
        return redirect(url_for("stats", pid=pid, queue=request.form.get("queue", "all"), map=request.form.get("map") or None))

    @app.post("/profiles/<int:pid>/stats/tips")
    def stats_tips(pid: int):
        get_profile(pid)
        m = request.form.get("map", "")
        queue = request.form.get("queue", "all")
        if m:
            sr.submit_tips(pid, m, queue if queue in dict(QUEUE_TABS) else "all",
                           filter_rows(owner_rows(g.user.id), queue))
        return redirect(url_for("stats", pid=pid, queue=queue, map=m or None) + "#tips")

    @app.get("/api/stats/status")
    def stats_status():
        key = request.args.get("key", "")
        parts = key.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            return jsonify(error="bad key"), 400
        if parts[0] in ("premier", "plans", "focus", "post", "scout", "review", "schedule"):
            get_team(int(parts[1]))
        else:
            view_profile(int(parts[1]))
        return jsonify(sr.status(key) or {"status": "none"})

    # ------------------------------------------------------------------ teams
    @app.route("/teams", methods=["GET", "POST"])
    def teams():
        if request.method == "POST":
            f = request.form
            if f.get("premier_name", "").strip():
                pname = f["premier_name"].strip()
                ptag = f.get("premier_tag", "").strip().lstrip("#")
                if "#" in pname and not ptag:
                    pname, _, ptag = pname.partition("#")
                region = f.get("premier_region", "eu")
                if not ptag or region not in ("eu", "na", "ap", "kr", "latam", "br"):
                    flash("Enter the Premier team as Name#TAG and pick its region.", "error")
                    return redirect(url_for("teams"))
                if not store.get("henrik_api_key"):
                    flash("No HenrikDev API key is set yet.", "error")
                    return redirect(url_for("teams"))
                tid = store.create_team(g.user.id, pname[:60])
                store.update_team(tid, premier={"name": pname, "tag": ptag, "region": region})
                sr.submit_premier(tid, g.user.id, pname, ptag, region)
                return redirect(url_for("team", tid=tid))
            name = f.get("name", "").strip()
            if not name:
                flash("Give the team a name.", "error")
                return redirect(url_for("teams"))
            tid = store.create_team(g.user.id, name[:60])
            return redirect(url_for("team_settings", tid=tid))
        return render_template("teams.html", teams=store.teams_for_user(g.user.id),
                               profiles={p.id: p for p in store.profiles(g.user.id)})

    def team_context(t) -> dict:
        own = store.profiles(t.owner_id)
        own_ids = {p.id for p in own}
        members = [m for m in t.member_list if m["pid"] in own_ids]
        byid = {p.id: p for p in own}
        rows_by = {m["pid"]: filter_rows(sr.games(m["pid"]).rows(), t.queue) for m in members}
        return {"own": own, "members": members, "byid": byid, "rows_by": rows_by,
                "seen_maps": sorted({r["map"] for rs in rows_by.values() for r in rs})}

    @app.get("/teams/<int:tid>")
    def team(tid: int):
        t = get_team(tid)
        roles.load(cache_dir)
        c = team_context(t)
        members, byid, rows_by = c["members"], c["byid"], c["rows_by"]
        starters = [Pool.from_rows(byid[m["pid"]].name, rows_by[m["pid"]]) for m in members if m["kind"] == "starter"]
        subs = [Pool.from_rows(byid[m["pid"]].name, rows_by[m["pid"]]) for m in members if m["kind"] == "sub"]
        maps = t.map_list or [m["map"] for m in by_map([r for rs in rows_by.values() for r in rs])][:7]
        try:
            meta = parse_meta(t.meta)
            meta_error = None
        except Exception as e:
            meta, meta_error = {}, str(e)
        plan = None
        if len(starters) == 5 and maps:
            plan = team_plan(starters, subs, maps, local_meta(filter_rows(owner_rows(t.owner_id), t.queue)), meta)
        sel = request.args.get("map") or week_map_of(app, t)
        if plan and sel not in [m["map"] for m in plan]:
            sel = plan[0]["map"]
        alts = []
        if plan and sel:
            from ..stats.comp import top_comps
            alts = top_comps(starters, sel, local_meta(filter_rows(owner_rows(t.owner_id), t.queue)).get(sel),
                             meta.get(sel.lower()))[1:]
        users = {u.id: u for u in store.users()}
        member_info = [{"p": byid[m["pid"]], "kind": m["kind"], "games": len(rows_by[m["pid"]]),
                        "full": sum(r.get("source") == "full" for r in rows_by[m["pid"]]),
                        "status": sr.status(f"import:{m['pid']}"),
                        "user": users.get(m.get("user_id")), "me": m.get("user_id") == g.user.id} for m in members]
        return render_template(
            "team.html", t=t, premier_status=sr.status(f"premier:{tid}"), member_info=member_info, n_starters=len(starters), n_subs=len(subs),
            starters=[s.label for s in starters], plan=plan, maps=maps, sel=sel,
            detail=next((m for m in plan if m["map"] == sel), None) if plan else None,
            meta_error=meta_error, queues=QUEUE_TABS, tab="comps", alts=alts,
            linked=any(m.get("user_id") == g.user.id for m in members))

    @app.route("/teams/<int:tid>/settings", methods=["GET", "POST"])
    def team_settings(tid: int):
        t = get_team(tid, manage=True)
        c = team_context(t)
        own = c["own"]
        if request.method == "POST":
            f = request.form
            members = []
            prev = {m["pid"]: m for m in t.member_list}
            for p in own:
                kind = f.get(f"kind_{p.id}", "")
                if kind in ("starter", "sub"):
                    members.append({**prev.get(p.id, {}), "pid": p.id, "kind": kind})
            if sum(m["kind"] == "starter" for m in members) > 5:
                flash("A team has at most 5 starters; make the others substitutes.", "error")
                return redirect(url_for("team_settings", tid=tid))
            meta_text = f.get("meta", "")
            try:
                parse_meta(meta_text)
            except Exception as e:
                flash(f"Map meta: {e}", "error")
                return redirect(url_for("team_settings", tid=tid))
            queue = f.get("queue", "all")
            store.update_team(tid, name=(f.get("name") or t.name).strip()[:60], members=members,
                              maps=[m for m in f.getlist("maps") if m][:12], meta=meta_text,
                              queue=queue if queue in dict(QUEUE_TABS) else "all")
            flash("Team saved.", "ok")
            return redirect(url_for("team", tid=tid))
        access = store.team_access(tid)
        others = [u for u in store.users() if u.id != t.owner_id and u.id not in {a.id for a in access} and not u.disabled]
        return render_template(
            "team_settings.html", t=t, premier_status=sr.status(f"premier:{tid}"), own=own, kinds={m["pid"]: m["kind"] for m in c["members"]},
            access=access, others=others, discord=t.discord_info,
            games={pid: len(rs) for pid, rs in c["rows_by"].items()},
            map_choices=sorted(set(KNOWN_MAPS) | set(c["seen_maps"])), meta_example=META_EXAMPLE,
            queues=QUEUE_TABS, tab="settings")

    @app.route("/teams/<int:tid>/roles", methods=["GET", "POST"])
    def team_roles_page(tid: int):
        from ..stats.teamroles import DESCRIPTION, TEAM_ROLES, team_roles
        t = get_team(tid)
        roles.load(cache_dir)
        c = team_context(t)
        if request.method == "POST":
            if not g.team_owner:
                abort(403)
            members = []
            for m in t.member_list:
                if m["pid"] in c["byid"]:
                    picked = [r for r in request.form.getlist(f"roles_{m['pid']}") if r in TEAM_ROLES][:3]
                    m = {**m, "roles": picked}
                members.append(m)
            store.update_team(tid, members=members)
            flash("Roles saved.", "ok")
            return redirect(url_for("team_roles_page", tid=tid))
        members = [{"label": c["byid"][m["pid"]].name, "pid": m["pid"], "kind": m["kind"],
                    "rows": c["rows_by"][m["pid"]], "assigned": m.get("roles", [])} for m in c["members"]]
        maps = t.map_list or [m["map"] for m in by_map([r for rs in c["rows_by"].values() for r in rs])][:7]
        res = team_roles(members, local_meta(filter_rows(owner_rows(t.owner_id), t.queue)), maps) if members else None
        return render_template("team_roles.html", t=t, tab="roles", res=res, team_roles=TEAM_ROLES, is_owner=g.team_owner,
                               desc=DESCRIPTION, queues=QUEUE_TABS, premier_status=sr.status(f"premier:{tid}"))

    team_cache: dict[tuple, object] = {}

    def team_data(t) -> dict:
        """Starters' puuids/names and the matches they played together (cached per set of matches)."""
        from ..stats.teamdata import team_matches
        c = team_context(t)
        rows_by_pu, names = {}, {}
        for m in c["members"]:
            data = sr.games(m["pid"]).load()
            pu = data.get("puuid") or m.get("puuid")
            if pu and m["kind"] == "starter":
                rows_by_pu[pu] = list(data["games"].values())
            if pu:
                names[pu] = c["byid"][m["pid"]].name
        key = (t.id, tuple(sorted((pu, len(r)) for pu, r in rows_by_pu.items())))
        if key not in team_cache:
            team_cache.clear() if len(team_cache) > 20 else None
            team_cache[key] = team_matches(cache_dir, rows_by_pu)
        return {**c, "matches": team_cache[key], "names": names}

    @app.route("/teams/<int:tid>/notes", methods=["GET", "POST"])
    def team_notes(tid: int):
        from ..stats.teamdata import teammate_tips
        t = get_team(tid)
        if request.method == "POST":
            text = request.form.get("text", "").strip()
            about = request.form.get("about", "")
            if text:
                store.add_team_note(tid, g.user.id, text, int(about) if about.isdigit() else None,
                                    request.form.get("map", "")[:30])
                flash("Note added. Everyone in the team sees it.", "ok")
            return redirect(url_for("team_notes", tid=tid))
        d = team_data(t)
        tips = teammate_tips(d["matches"], cache_dir, d["names"])
        maps = sorted({m.map_name for m, _ in d["matches"]} | set(t.map_list))
        return render_template("team_notes.html", t=t, tab="notes", notes=store.team_notes(tid), tips=tips,
                               n_matches=len(d["matches"]), players=d["byid"], members=d["members"], maps=maps,
                               premier_status=sr.status(f"premier:{tid}"))

    @app.post("/teams/<int:tid>/notes/<int:nid>/delete")
    def team_note_delete(tid: int, nid: int):
        t = get_team(tid)
        n = store.team_note(nid)
        if n is None or n["team_id"] != tid or (n["author_id"] != g.user.id and not g.team_owner):
            abort(404)
        store.delete_team_note(nid)
        return redirect(url_for("team_notes", tid=tid))

    @app.post("/teams/<int:tid>/access")
    def team_access_edit(tid: int):
        t = get_team(tid, manage=True)
        f = request.form
        if f.get("add"):
            u = store.user(int(f["add"])) if f["add"].isdigit() else None
            if u is None or u.id == t.owner_id:
                abort(400)
            store.add_team_access(tid, u.id)
            # an account whose in-game name matches a team player is linked to it right away
            members = t.member_list
            for m in members:
                p = store.profile(m["pid"])
                if p and u.display_name and u.display_name.lower() == f"{p.name}#{p.tag}".lower() and not m.get("user_id"):
                    m["user_id"] = u.id
            store.update_team(tid, members=members)
            flash(f"{u.label} can now open this team.", "ok")
        elif f.get("remove"):
            uid = int(f["remove"])
            store.remove_team_access(tid, uid)
            store.update_team(tid, members=[{k: v for k, v in m.items() if not (k == "user_id" and v == uid)}
                                            for m in t.member_list])
            flash("Removed.", "ok")
        return redirect(url_for("team_settings", tid=tid) + "#access")

    @app.post("/teams/<int:tid>/me")
    def team_me(tid: int):
        t = get_team(tid)
        pid = request.form.get("pid", "")
        members = []
        for m in t.member_list:
            m = {k: v for k, v in m.items() if not (k == "user_id" and v == g.user.id)}
            if pid.isdigit() and m["pid"] == int(pid) and not m.get("user_id"):
                m["user_id"] = g.user.id
            members.append(m)
        store.update_team(tid, members=members)
        flash("Saved: that's you in this team." if pid else "Unlinked.", "ok")
        return redirect(request.form.get("next") or url_for("team", tid=tid))

    register_team_extras(app, store, sr, {"get_team": get_team, "team_context": team_context,
                                          "team_data": team_data, "owner_rows": owner_rows})
    from .strats import register as register_strats
    register_strats(app, store, sr, get_team, KNOWN_MAPS)
    from .player_views import register as register_player
    register_player(app, store, sr, {"view_profile": view_profile, "team_context": team_context, "owner_rows": owner_rows,
                                     "queue_arg": queue_arg, "queues": QUEUE_TABS})
    from .lineups import register as register_lineups
    register_lineups(app, store, get_team, KNOWN_MAPS)
    from .drafts import register as register_drafts
    register_drafts(app, store, get_team, {"team_context": team_context, "owner_rows": owner_rows}, KNOWN_MAPS)

    def import_members(t) -> int:
        own_ids = {p.id for p in store.profiles(t.owner_id)}
        n = 0
        for m in t.member_list:
            if m["pid"] in own_ids:
                sr.submit_import(m["pid"])
                n += 1
        return n

    def nightly_job(t) -> None:
        """The same as pressing both buttons: Premier roster (which then imports everyone), else the stats."""
        pi = t.premier_info
        if pi.get("tag"):
            sr.submit_premier(t.id, t.owner_id, pi["name"], pi["tag"], pi.get("region", "eu"))
            pj = app.extensions["valcoach"].get("premier")
            if pj:                             # queued after the roster (one worker): schedule, reviews, the division
                pj.submit_schedule(t.id)
                pj.submit_reviews(t.id, post=True)
                pj.submit_scout(t.id, {"division": True})
        else:
            import_members(t)

    app.extensions["valcoach"]["nightly_job"] = nightly_job

    @app.post("/teams/<int:tid>/premier-sync")
    def team_premier_sync(tid: int):
        t = get_team(tid, manage=True)
        pi = t.premier_info
        if not pi.get("tag"):
            abort(404)
        sr.submit_premier(tid, g.user.id, pi["name"], pi["tag"], pi.get("region", "eu"))
        flash("Updating the roster from Premier in the background.", "ok")
        return redirect(url_for("team", tid=tid))

    @app.post("/teams/<int:tid>/import")
    def team_import(tid: int):
        t = get_team(tid, manage=True)
        n = import_members(t)
        flash(f"Updating stats for {n} players in the background. Reload in a minute.", "ok")
        return redirect(url_for("team", tid=tid))

    @app.post("/teams/<int:tid>/sync-settings")
    def team_sync_settings(tid: int):
        t = get_team(tid, manage=True)
        info = t.sync_info
        info["nightly"] = bool(request.form.get("nightly"))
        try:
            info["hour"] = max(0, min(23, int(request.form.get("hour", 2))))
        except ValueError:
            pass
        store.update_team(tid, sync=info)
        flash(f"Nightly sync {'on at %02d:00' % info['hour'] if info['nightly'] else 'off'}.", "ok")
        return redirect(url_for("team_settings", tid=tid) + "#sync")

    @app.post("/teams/<int:tid>/delete")
    def team_delete(tid: int):
        get_team(tid, manage=True)
        store.delete_team(tid)
        flash("Team deleted.", "ok")
        return redirect(url_for("teams"))


# ---------------------------------------------------------------------------
# game plans, weekly focus, Discord (registered from register_team_extras)
# ---------------------------------------------------------------------------
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def register_team_extras(app, store, sr: StatsRunner, helpers: dict) -> None:
    from ..discord import DiscordError, post as dpost, valid_url
    from ..maps import MapRegistry
    from ..stats.comp import top_comps
    from ..stats.teamdata import map_facts, teammate_tips
    from ..stats.teamroles import team_roles
    from ..stats.weekly import player_facts, week_id

    get_team, team_context, team_data, owner_rows = (helpers["get_team"], helpers["team_context"],
                                                     helpers["team_data"], helpers["owner_rows"])
    cache_dir = store.data_dir / "cache"

    def language(t) -> str:
        ps = store.profiles(t.owner_id)
        return ps[0].language if ps else "English"

    def build(t) -> dict:
        """Everything the team pages / jobs need: comps per map, roles, data, tips."""
        roles.load(cache_dir)
        d = team_data(t)
        members, byid, rows_by = d["members"], d["byid"], d["rows_by"]
        starters = [m for m in members if m["kind"] == "starter"]
        pools = [Pool.from_rows(byid[m["pid"]].name, rows_by[m["pid"]]) for m in starters]
        maps = t.map_list or [m["map"] for m in by_map([r for rs in rows_by.values() for r in rs])][:7]
        try:
            meta = parse_meta(t.meta)
        except Exception:
            meta = {}
        local = local_meta(filter_rows(owner_rows(t.owner_id), t.queue))
        comps = {mp: top_comps(pools, mp, local.get(mp), meta.get(mp.lower())) for mp in maps} if len(pools) == 5 else {}
        rr = team_roles([{"label": byid[m["pid"]].name, "pid": m["pid"], "kind": m["kind"], "rows": rows_by[m["pid"]],
                          "assigned": m.get("roles", [])} for m in members], local, maps) if members else {"players": [], "lineup": {}}
        role_of = {}
        for p in rr["players"]:
            role_of[p["label"]] = p["assigned"] or ([rr["lineup"].get("primary", {}).get(p["label"])] if rr["lineup"].get("primary", {}).get(p["label"]) else p["best"][:1])
        tips = teammate_tips(d["matches"], cache_dir, d["names"])
        return {**d, "maps": maps, "comps": comps, "roles": rr, "role_of": role_of, "tips": tips, "starters": starters}

    def plan_items(t, b, maps: list[str]) -> list[dict]:
        reg = MapRegistry(cache_dir)
        notes = store.team_notes(t.id)
        items = []
        for mp in maps:
            comp = (b["comps"].get(mp) or [{}])[0]
            if not comp.get("ok"):
                continue
            lineup = [{"player": p["player"], "agent": p["agent"], "agent_role": p["role"], "team_roles": b["role_of"].get(p["player"], [])}
                      for p in comp["picks"]]
            try:
                mi = reg.get("", mp)
            except Exception:
                mi = None
            callouts = sorted({c.label for c in mi.callouts if c.region.lower() != "spawn"}) if mi else []
            map_notes = [n["text"] for n in notes if not n["map"] or n["map"].lower() == mp.lower()]
            map_tips = [x["text"] for x in b["tips"] if not x["map"] or x["map"].lower() == mp.lower()]
            items.append({"map": mp, "facts": map_facts(b["matches"], cache_dir, mp), "lineup": lineup,
                          "callouts": callouts, "notes": map_notes, "tips": map_tips})
        return items

    def focus_items(t, b) -> list[dict]:
        notes = store.team_notes(t.id)
        scores = {p["label"]: p["scores"] for p in b["roles"]["players"]}
        items = []
        for m in b["members"]:
            name = b["byid"][m["pid"]].name
            tips = [x["text"] for x in b["tips"] if x.get("about") == name]
            about = [n["text"] for n in notes if n["about_pid"] == m["pid"]]
            items.append({"pid": m["pid"], "name": name, "roles": b["role_of"].get(name, []),
                          "facts": player_facts(name, b["rows_by"][m["pid"]], b["role_of"].get(name, []),
                                                scores.get(name) or {}, tips, about)})
        return items

    def prep_post(b, maps: list[str]) -> dict:
        return {"maps": [{"map": mp, "comps": [c for c in b["comps"].get(mp, []) if c.get("ok")]} for mp in maps]}

    # ------------------------------------------------------------------ game plans
    @app.get("/teams/<int:tid>/plans")
    def team_plans(tid: int):
        t = get_team(tid)
        b = build(t)
        wm = week_map_of(app, t)
        sel = request.args.get("map") or (wm if wm in b["maps"] else (b["maps"][0] if b["maps"] else None))
        facts = map_facts(b["matches"], cache_dir, sel) if sel else None
        return render_template("team_plans.html", t=t, tab="plans", maps=b["maps"], sel=sel, plans=sr.read_plans(tid, sel) if sel else None,
                               facts=facts, comps=b["comps"].get(sel, []), n_matches=len(b["matches"]),
                               status=sr.status(f"plans:{tid}"), post_status=sr.status(f"post:{tid}"),
                               discord=t.discord_info, ready=len(b["starters"]) == 5, premier_status=sr.status(f"premier:{tid}"))

    @app.post("/teams/<int:tid>/plans/build")
    def team_plans_build(tid: int):
        t = get_team(tid)
        b = build(t)
        which = request.form.get("map", "")
        maps = b["maps"] if which == "__all" else [which]
        items = plan_items(t, b, [m for m in maps if m in b["maps"]])
        if not items:
            flash("Pick 5 starters and update everyone's stats first.", "error")
            return redirect(url_for("team_plans", tid=tid))
        post = prep_post(b, [i["map"] for i in items]) if request.form.get("post") and g.team_owner else None
        sr.submit_plans(tid, items, language(t), post)
        return redirect(url_for("team_plans", tid=tid, map=None if which == "__all" else which))

    @app.post("/teams/<int:tid>/discord/prep")
    def team_post_prep(tid: int):
        t = get_team(tid, manage=True)
        b = build(t)
        maps = [m for m in request.form.getlist("maps") if m in b["maps"]] or b["maps"]
        if not (t.discord_info.get("prep_url") or t.discord_info.get("focus_url")):
            flash("Add a Discord webhook under Members, maps & Discord first.", "error")
        else:
            sr.submit_post_prep(tid, prep_post(b, maps))
            flash(f"Posting comps{' and game plans' if any(sr.read_plans(tid, m) for m in maps) else ''} for {', '.join(maps)} to Discord.", "ok")
        return redirect(request.form.get("next") or url_for("team_plans", tid=tid))

    # ------------------------------------------------------------------ weekly focus
    @app.get("/teams/<int:tid>/focus")
    def team_focus(tid: int):
        t = get_team(tid)
        f = sr.read_focus(tid)
        c = team_context(t)
        order = [str(m["pid"]) for m in c["members"]]
        players = []
        if f:
            players = [dict(f["players"][pid], pid=int(pid)) for pid in order if pid in f["players"]]
        # how the focus before this one went (its number, in the games since)
        from ..stats.progress import fmt as pfmt, focus_check
        d = sr.team_dir(tid) / "focus"
        files = sorted(d.glob("*.json"), reverse=True) if d.exists() else []
        prev = None
        for fp in files:
            if f and fp.stem == f.get("week"):
                continue
            try:
                prev = json.loads(fp.read_text())
            except ValueError:
                prev = None
            break
        for pl in players:
            pf = ((prev or {}).get("players") or {}).get(str(pl["pid"]))
            ck = focus_check(c["rows_by"].get(pl["pid"], []), prev.get("week", ""), pf) if pf and pf.get("focus") else None
            if ck:
                ck.update({f"{k}_s": pfmt(ck["metric"], ck[k]) for k in ("before", "now", "goal")})
                ck["focus"] = pf["focus"]
                ck["week"] = prev.get("week")
            pl["last"] = ck
        mine = next((m["pid"] for m in t.member_list if m.get("user_id") == g.user.id), None)
        return render_template("team_focus.html", t=t, tab="focus", focus=f, players=players, mine=mine,
                               this_week=week_id(), status=sr.status(f"focus:{tid}"), discord=t.discord_info,
                               days=DAYS, premier_status=sr.status(f"premier:{tid}"))

    @app.post("/teams/<int:tid>/focus/build")
    def team_focus_build(tid: int):
        t = get_team(tid, manage=True)
        b = build(t)
        items = focus_items(t, b)
        if not items:
            flash("The team has no players yet.", "error")
        else:
            sr.submit_focus(tid, week_id(), items, language(t), post=bool(request.form.get("post")))
        return redirect(url_for("team_focus", tid=tid))

    @app.post("/teams/<int:tid>/focus/post")
    def team_focus_post(tid: int):
        get_team(tid, manage=True)
        try:
            sr.post_focus(tid)
            flash("Posted this week's focus to Discord.", "ok")
        except Exception as e:
            flash(f"Discord: {e}", "error")
        return redirect(url_for("team_focus", tid=tid))

    # ------------------------------------------------------------------ Discord settings
    @app.post("/teams/<int:tid>/discord")
    def team_discord(tid: int):
        t = get_team(tid, manage=True)
        f = request.form
        info = dict(t.discord_info)
        for k in ("prep_url", "focus_url"):
            v = f.get(k, "").strip()
            if v and not valid_url(v):
                flash(f"That doesn't look like a Discord webhook URL: {v[:60]}…", "error")
                return redirect(url_for("team_settings", tid=tid) + "#discord")
            if v or f.get(f"clear_{k}"):
                info[k] = v
        info["weekly"] = bool(f.get("weekly"))
        try:
            info["weekly_day"] = max(0, min(6, int(f.get("weekly_day", 0))))
            info["weekly_hour"] = max(0, min(23, int(f.get("weekly_hour", 18))))
        except ValueError:
            pass
        store.update_team(tid, discord=info)
        if f.get("test"):
            url = info.get("prep_url") or info.get("focus_url")
            try:
                dpost(url, f"✅ valcoach is connected to **{t.name}**. Comps, game plans and the weekly focus will show up here.")
                flash("Test message sent.", "ok")
            except (DiscordError, Exception) as e:
                flash(f"Discord: {e}", "error")
        else:
            flash("Discord settings saved.", "ok")
        return redirect(url_for("team_settings", tid=tid) + "#discord")

    def weekly_job(t) -> None:
        b = build(t)
        items = focus_items(t, b)
        if items:
            sr.submit_focus(t.id, week_id(), items, language(t), post=True)

    app.extensions["valcoach"]["weekly_job"] = weekly_job

    from .premier_views import register as register_premier
    register_premier(app, store, sr, {"get_team": get_team, "team_data": team_data, "build": build, "known_maps": KNOWN_MAPS,
                                      "team_context": team_context})
