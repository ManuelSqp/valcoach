"""Stats, pick helper and team (Premier) pages."""
from __future__ import annotations

import json
import time

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from ..maps import AgentRegistry
from ..stats import roles
from ..stats.aggregate import by_agent, by_map, by_role, filter_rows, local_meta, map_detail, summary
from ..stats.comp import META_EXAMPLE, Pool, parse_meta, pick_helper
from ..stats.compmodes import METHODS as COMP_METHODS, method_of, plan as comp_plan, top as comp_top
from .models import picked
from .statsjobs import StatsRunner, slug

def week_map_of(app, t) -> str | None:
    """This Premier week's map for a team (None if not a Premier team or not known)."""
    fn = app.extensions["nexus"].get("week_map")
    try:
        return fn(t) if fn and t.premier_info.get("tag") else None
    except Exception:
        return None


QUEUE_TABS = [("all", "All ranked"), ("competitive", "Competitive"), ("premier", "Premier"), ("unrated", "Unrated"), ("everything", "Everything")]
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
    def heat_map(rows: list[dict], map_name: str) -> dict | None:
        """Deaths and kills per callout, placed on the minimap (attack / defense)."""
        from collections import Counter
        from ..maps import MapRegistry
        full = [r for r in rows if r.get("map") == map_name and r.get("source") == "full"]
        if not full:
            return None
        try:
            mi = MapRegistry(cache_dir).get(name=map_name)
        except Exception:
            mi = None
        if mi is None:
            return None
        cnt = {k: Counter() for k in ("d_attack", "d_defense", "k_attack", "k_defense")}
        for r in full:
            for x in r.get("deaths_at") or []:
                cnt[f"d_{x[0]}"][x[1]] += 1
            for x in r.get("kills_at") or []:
                cnt[f"k_{x[0]}"][x[1]] += 1
        pts, seen = [], set()
        for c in mi.callouts:
            if c.label in seen:
                continue
            seen.add(c.label)
            vals = {k: v.get(c.label, 0) for k, v in cnt.items()}
            if any(vals.values()):
                u, v = mi.to_uv(c.x, c.y)
                pts.append({"label": c.label, "x": round(u * 1000), "y": round(v * 1000), **vals})
        if not pts:
            return None
        top = max(max(p[k] for k in cnt) for p in pts) or 1
        return {"img": url_for("map_image", name=map_name), "points": pts, "top": top, "games": len(full)}

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
            heat=heat_map(rows, sel) if sel else None,
            tips=sr.read_tips(pid, sel, queue) if sel else None,
            import_status=sr.status(f"import:{pid}"),
            tips_status=sr.status(f"tips:{pid}:{slug(sel)}:{queue}") if sel else None,
            tips_key=f"tips:{pid}:{slug(sel)}:{queue}" if sel else "",
            all_agents=roles.all_agents(), map_names=sorted({m["map"] for m in maps} | set(KNOWN_MAPS)), tab="stats",
            can_edit=can_edit,
            pick=pick, pick_map=pick_map, locked=locked + [""] * (4 - len(locked)),
            recent=rows[:12], ctx=stats_context(rows),
            peers=__import__("nexus.stats.peers", fromlist=["analyse"]).analyse(rows),
            goal_edit=own_player(pid, can_edit),
            open_goals={x["metric"] for x in sr.goals(pid).load() if x.get("state", "open") == "open"})

    def stats_context(rows: list[dict]) -> dict:
        """4.15: weighted numbers, rounds by buy state and games by lobby strength."""
        from ..stats import evidence as ev
        buy = ev.buy_split(rows)
        return {"w": ev.weighted_summary(rows), "buy": buy, "note": ev.buy_note(buy), "opp": ev.opponent_split(rows),
                "half_life": int(ev.HALF_LIFE_DAYS), "patch_old": ev.PATCH_OLD}

    @app.get("/profiles/<int:pid>/agents")
    def agents_roles(pid: int):
        """Every agent's numbers, the class you prefer, and the role your habits fit."""
        from ..stats.agentroles import overview
        p, can_edit = view_profile(pid)
        roles.load(cache_dir)
        queue = queue_arg()
        rows = filter_rows(sr.games(pid).rows(), queue)
        # what teams at your level pick (all maps together), from the matches of everyone in this workspace
        meta = local_meta(filter_rows(owner_rows(p.owner_id), queue))
        picks, teams = {}, 0
        for m in meta.values():
            teams += 2 * m["games"]
            for a in m["agents"]:
                picks[a["agent"]] = picks.get(a["agent"], 0) + a["picks"]
        meta_share = {a: n / teams for a, n in picks.items()} if teams else {}
        # roles a team owner set for this player
        team_set = []
        for t in store.teams_for_user(g.user.id):
            for m in t.member_list:
                if m.get("pid") == pid and m.get("roles"):
                    team_set.append({"team": t.name, "tid": t.id, "roles": m["roles"]})
        o = overview(rows, team_set, meta_share)
        from ..stats.agentroles import agent_detail, grid
        sel = request.args.get("agent") or ""
        detail = None
        if sel and any(a["agent"] == sel for a in o["agents"]):
            names = {}
            try:
                a = agents_reg.find(name=sel)
                slot_map = {"Grenade": "grenade", "Ability1": "ability1", "Ability2": "ability2", "Ultimate": "ultimate"}
                names = {slot_map[ab["slot"]]: ab["name"] for ab in (a or {}).get("abilities", []) if ab.get("slot") in slot_map}
            except Exception:
                pass
            detail = agent_detail(rows, sel, names)
        old = sum(1 for r in rows if r.get("source") == "full" and r.get("v", 1) < 5)
        return render_template("agents_roles.html", p=p, active_pid=pid, queue=queue, queues=QUEUE_TABS, tab="agents",
                               can_edit=can_edit, o=o, import_status=sr.status(f"import:{pid}"), grid=grid(rows),
                               sel=sel, detail=detail, old_rows=old)

    @app.get("/profiles/<int:pid>/rounds")
    def rounds_page(pid: int):
        """Round types & economy: pistols, ecos, forces, full buys and how the buys line up."""
        from ..stats.rounds import economy
        p, can_edit = view_profile(pid)
        queue = queue_arg()
        rows = filter_rows(sr.games(pid).rows(), queue)
        old = sum(1 for r in rows if r.get("source") == "full" and r.get("v", 1) < 5)
        return render_template("rounds.html", p=p, active_pid=pid, queue=queue, queues=QUEUE_TABS, tab="rounds",
                               can_edit=can_edit, e=economy(rows), old_rows=old)

    @app.get("/profiles/<int:pid>/teammates")
    def teammates_page(pid: int):
        """Who you win with."""
        from ..stats.rounds import teammates
        p, can_edit = view_profile(pid)
        queue = queue_arg("everything")
        rows = filter_rows(sr.games(pid).rows(), queue)
        old = sum(1 for r in rows if r.get("source") == "full" and r.get("v", 1) < 5)
        return render_template("teammates.html", p=p, active_pid=pid, queue=queue, queues=QUEUE_TABS, tab="teammates",
                               can_edit=can_edit, d=teammates(rows), old_rows=old)

    def coach_said(p) -> list[dict]:
        """What reports and Premier reviews told this player to fix (for the habit tracker)."""
        from ..stats.habits import coach_lines, review_lines
        out = []
        for j in store.jobs(p.id, 60):
            path = store.resolve(j.json_path) if j.status == "done" and j.json_path else None
            if path is None or not path.exists():
                continue
            try:
                rep = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            date = (rep.get("meta") or {}).get("started_at") or j.started_at_match or j.created_at
            out += coach_lines(rep, p.name, date, f"Report {j.map} {j.score}".strip(), url_for("job_report", jid=j.id))
        pj = app.extensions["nexus"].get("premier")
        if pj:
            for t in store.teams_for_user(g.user.id):
                if not any(m.get("pid") == p.id for m in t.member_list):
                    continue
                for r in pj.reviews(t.id)[:30]:
                    out += review_lines(r, p.name, url_for("team_review_page", tid=t.id, match_id=r.get("match_id", "")))
        return sorted(out, key=lambda c: c.get("date") or "", reverse=True)

    @app.get("/profiles/<int:pid>/habits")
    def habits(pid: int):
        """Habits that cost rounds, game by game, and whether they're going away."""
        from ..stats.habits import fmt_date, track
        p, can_edit = view_profile(pid)
        queue = queue_arg("everything")
        rows = filter_rows(sr.games(pid).rows(), queue)
        h = track(rows, coach_said(p))
        from ..stats import goals as gl, replaystats
        from ..stats.progress import METRICS, ORDER
        all_rows = sr.games(pid).rows()
        goals = sr.goals(pid).refresh(all_rows)
        replay = replaystats.player(store.data_dir / "replays", cache_dir, all_rows, sr.games(pid).load().get("puuid", ""))
        return render_template("habits.html", p=p, active_pid=pid, queue=queue, queues=QUEUE_TABS, tab="habits",
                               can_edit=can_edit, h=h, fmt_date=fmt_date, own=sr.read_own_focus(pid),
                               goals=goals, goal_edit=own_player(pid, can_edit), metrics=[(k, METRICS[k][0], METRICS[k][2]) for k in ORDER],
                               habit_goal=HABIT_GOAL, goal_games=gl.GOAL_GAMES, replay=replay,
                               setup_s=int(replaystats.SETUP_S), trade_m=int(replaystats.TRADE_M), trade_s=int(replaystats.TRADE_S),
                               retake_m=int(replaystats.RETAKE_M))

    # habit -> (progress metric, target): "Make it a goal" aims for the habit's line
    HABIT_GOAL = {"alone": ("alone", None), "untraded": ("traded", "inv"), "opening": ("first_duels", "inv"),
                  "kast": ("kast", "inv"), "aim": ("hs", None), "no_util": ("no_util", None)}

    def own_player(pid: int, can_edit: bool) -> bool:
        """You can set goals for your own players and for the team player linked to your account."""
        if can_edit:
            return True
        return any(m.get("pid") == pid and m.get("user_id") == g.user.id
                   for t in store.teams_for_user(g.user.id) for m in t.member_list)

    @app.post("/profiles/<int:pid>/goals")
    def goal_add(pid: int):
        """A measurable goal (4.15): a metric, a target and the games it has to happen in."""
        from ..stats import goals as gl
        from ..stats.habits import HABITS
        from ..stats.progress import METRICS
        p, can_edit = view_profile(pid)
        if not own_player(pid, can_edit):
            abort(403)
        f = request.form
        metric, target, text = f.get("metric", ""), None, f.get("text", "")
        if f.get("habit") in HABIT_GOAL:
            metric, how = HABIT_GOAL[f["habit"]]
            line = HABITS[f["habit"]]["bad"]
            target = round(1 - line, 2) if how == "inv" else line
            text = text or HABITS[f["habit"]]["title"]
        elif metric in METRICS:
            target = gl.parse_target(metric, f.get("target"))
        if metric not in METRICS or target is None:
            flash("Pick a number and a target.", "error")
            return redirect(url_for("habits", pid=pid) + "#goals")
        games = f.get("games", type=int) or gl.GOAL_GAMES
        source = "your rank" if f.get("from") == "peers" else "you"
        sr.goals(pid).add(metric, target, sr.games(pid).rows(), text=text, source=source, games=games)
        flash(f"Goal set: {METRICS[metric][0]} in the next {max(3, min(30, games))} games.", "ok")
        if f.get("from") == "peers":                 # 4.19: from "You vs your rank": back there
            return redirect(url_for("stats", pid=pid, queue=f.get("queue") or None) + "#peers")
        return redirect(url_for("habits", pid=pid) + "#goals")

    @app.post("/profiles/<int:pid>/goals/<gid>/drop")
    def goal_drop(pid: int, gid: str):
        p, can_edit = view_profile(pid)
        if not own_player(pid, can_edit):
            abort(403)
        sr.goals(pid).drop(gid)
        return redirect(url_for("habits", pid=pid) + "#goals")

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
            sr.submit_watch(pid, queue, c["prof"], c["matches"], jobs, picked(store))
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
                           filter_rows(owner_rows(g.user.id), queue), picked(store))
        return redirect(url_for("stats", pid=pid, queue=queue, map=m or None) + "#tips")

    @app.get("/api/stats/status")
    def stats_status():
        key = request.args.get("key", "")
        parts = key.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            return jsonify(error="bad key"), 400
        if parts[0] in ("premier", "plans", "focus", "post", "scout", "review", "schedule", "webcomps"):
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

    def comp_pools(t, entries) -> list:
        """[(name, pid, rows)] -> comp Pools. With "Follow our agent pools" on (Comp sheet, 4.14) each one carries
        the player's own agent pool, so every comp mode leaves out agents he won't play and prefers his top ones."""
        from ..stats import compsheet
        sheet = compsheet.load(sr.team_dir(t.id))
        out = []
        for name, pid, rows in entries:
            p = Pool.from_rows(name, rows)
            if sheet["follow"]:
                p.pref = compsheet.prefs(rows, sheet["pools"].get(str(pid)))
            out.append(p)
        return out

    def pools_followed(t) -> bool:
        from ..stats import compsheet
        return compsheet.load(sr.team_dir(t.id))["follow"]

    def set_follow(tid: int, on: bool) -> None:
        from ..stats import compsheet
        data = compsheet.load(sr.team_dir(tid))
        if data["follow"] != on:
            data["follow"] = on
            compsheet.save(sr.team_dir(tid), data)

    def web_search_on() -> bool:
        """A web search is set up (Settings › Web search, DuckDuckGo by default). 4.13: before, a setting that
        doesn't exist was checked, so "From the web" always looked switched off."""
        from ..coach.websearch import searcher
        return searcher(store) is not None

    @app.post("/teams/<int:tid>/sheet/follow")
    def team_sheet_follow(tid: int):
        """The "Follow our agent pools" switch on the comp sheet (4.14); the same one as on the comps page."""
        get_team(tid, manage=True)
        on = request.form.get("follow_pools") == "1"
        set_follow(tid, on)
        flash("The comps now follow your agent pools." if on else "The comps no longer follow your agent pools.", "ok")
        return redirect(url_for("team_sheet", tid=tid) + "#pool")

    @app.post("/teams/<int:tid>/comps/method")
    def team_comp_method(tid: int):
        """The comp mode picker on the comps page (4.10.1): same setting as team settings › Comp suggestions."""
        t = get_team(tid, manage=True)
        method = request.form.get("comp_method", "")
        if method not in COMP_METHODS:
            abort(400)
        sel = request.form.get("map", "")
        store.update_team(tid, comp_method=method)
        set_follow(tid, request.form.get("follow_pools") == "1")
        if method == "web" and sel and web_search_on() and sel.lower() not in sr.read_webcomps(tid) \
                and sel in (t.map_list or [sel]):
            owner = store.profiles(t.owner_id)
            sr.submit_webcomps(tid, [sel], owner[0].language if owner else "English", picked(store))
        flash(f"Comps are now made with: {COMP_METHODS[method]}", "ok")
        if pools_followed(t):
            flash("Following your agent pools from the comp sheet.", "ok")
        return redirect(url_for("team", tid=tid, map=sel or None) + "#detail")

    @app.post("/teams/<int:tid>/webcomps")
    def team_webcomps(tid: int):
        """From the web (4.10): search comps for this map or all the team's maps, in the background."""
        t = get_team(tid)
        sheet = request.form.get("back") == "sheet"         # the comp sheet's ideal compositions (4.13)
        if method_of(t) != "web" and not sheet:
            abort(400)
        if not web_search_on():
            flash("Web search is off: an admin turns it on under Settings › Web search.", "error")
            return redirect(url_for("team_sheet", tid=tid) if sheet else url_for("team", tid=tid))
        c = team_context(t)
        maps = t.map_list or [m["map"] for m in by_map([r for rs in c["rows_by"].values() for r in rs])][:7]
        which = request.form.get("map", "")
        todo = maps if which == "__all" else [m for m in maps if m == which]
        if not todo:
            abort(400)
        owner = store.profiles(t.owner_id)
        sr.submit_webcomps(tid, todo, owner[0].language if owner else "English", picked(store))
        if sheet:
            return redirect(url_for("team_sheet", tid=tid) + "#ideal")
        return redirect(url_for("team", tid=tid, map=None if which == "__all" else which))

    # ---- comp sheet (4.13): agent pools + ideal composition per map -----------------------------
    def sheet_can_edit(t, pid: int) -> bool:
        """The team owner edits every pool, a player his own (linked by in-game name, see link_me)."""
        return g.team_owner or any(m["pid"] == pid and m.get("user_id") == g.user.id for m in t.member_list)

    @app.get("/teams/<int:tid>/sheet")
    def team_sheet(tid: int):
        from ..stats import compsheet
        t = link_me(get_team(tid))
        roles.load(cache_dir)
        c = team_context(t)
        saved = compsheet.load(sr.team_dir(tid))
        players = []
        for m in sorted(c["members"], key=lambda m: m["kind"] != "starter"):
            p = c["byid"][m["pid"]]
            players.append({"pid": p.id, "label": p.name, "kind": m["kind"], "can_edit": sheet_can_edit(t, p.id),
                            **compsheet.pool(c["rows_by"][p.id], saved["pools"].get(str(p.id)))})
        pools = {pl["label"]: pl for pl in players}
        maps = t.map_list or [m["map"] for m in by_map([r for rs in c["rows_by"].values() for r in rs])][:7]
        web = sr.read_webcomps(tid)
        ideals = []
        for mp in maps:
            idl = compsheet.ideal(mp, saved["ideal"].get(mp.lower()), web.get(mp.lower()))
            agents = [{"agent": a, "role": roles.role_of(a), "who": compsheet.who_plays(a, pools)}
                      for a in (idl or {}).get("agents", [])]
            ideals.append({"map": mp, "ideal": idl, "agents": agents, "searched": mp.lower() in web})
        advice = agent_advice(t, c, players, maps, ideals)
        return render_template("team_sheet.html", t=t, tab="sheet", players=players, ideals=ideals, advice=advice,
                               hue=compsheet.hue, all_agents=sorted(roles.all_agents()), is_owner=g.team_owner,
                               edit=request.args.get("edit", type=int), web_search_on=web_search_on(),
                               web_status=sr.status(f"webcomps:{tid}"), queues=QUEUE_TABS, follow_pools=saved["follow"],
                               premier_status=sr.status(f"premier:{tid}"))

    def agent_advice(t, c, players: list[dict], maps: list[str], ideals: list[dict]) -> dict | None:
        """4.22: which agent each player should add next (stats/agentpool.py)."""
        from ..stats import agentpool
        try:
            meta = local_meta(filter_rows(owner_rows(t.owner_id), t.queue))
            return agentpool.advise(
                [{"label": pl["label"], "pid": pl["pid"], "rows": c["rows_by"][pl["pid"]], "pool": [a["agent"] for a in pl["agents"]],
                  "no": pl["no"]} for pl in players],
                maps, {x["map"]: (x["ideal"] or {}).get("agents") or [] for x in ideals}, meta)
        except Exception:
            return None

    @app.post("/teams/<int:tid>/sheet/pool/<int:pid>/add")
    def team_sheet_pool_add(tid: int, pid: int):
        """4.22: "＋ Add to pool" from the advisor: the agent goes to the end of the player's pool."""
        from ..stats import compsheet
        t = get_team(tid)
        if pid not in [m["pid"] for m in t.member_list]:
            abort(404)
        if not sheet_can_edit(t, pid):
            abort(403)
        agent = (compsheet.clean_agents([request.form.get("agent", "")]) or [None])[0]
        if agent is None:
            abort(400)
        data = compsheet.load(sr.team_dir(tid))
        saved = data["pools"].get(str(pid))
        cur = compsheet.pool(filter_rows(sr.games(pid).rows(), t.queue), saved)
        order = [a["agent"] for a in cur["agents"]]
        if agent not in order:
            order.append(agent)
        data["pools"][str(pid)] = {"order": order, "no": [a for a in cur["no"] if a != agent]}
        compsheet.save(sr.team_dir(tid), data)
        p = store.profile(pid)
        flash(f"{agent} added to the pool of {p.name if p else 'the player'}.", "ok")
        return redirect(url_for("team_sheet", tid=tid) + "#advisor")

    @app.post("/teams/<int:tid>/sheet/pool/<int:pid>")
    def team_sheet_pool(tid: int, pid: int):
        from ..stats import compsheet
        t = get_team(tid)
        if pid not in [m["pid"] for m in t.member_list]:
            abort(404)
        if not sheet_can_edit(t, pid):
            abort(403)
        data = compsheet.load(sr.team_dir(tid))
        if request.form.get("reset"):
            data["pools"].pop(str(pid), None)
            flash("Agent pool back to the stats.", "ok")
        else:
            no = compsheet.clean_agents(request.form.get("no", "").split(","))
            order = [a for a in compsheet.clean_agents(request.form.get("order", "").split(",")) if a not in no]
            data["pools"][str(pid)] = {"order": order, "no": no}
            flash("Agent pool saved.", "ok")
        compsheet.save(sr.team_dir(tid), data)
        return redirect(url_for("team_sheet", tid=tid) + "#pool")

    @app.post("/teams/<int:tid>/sheet/ideal")
    def team_sheet_ideal(tid: int):
        from ..stats import compsheet
        t = get_team(tid, manage=True)
        mp = request.form.get("map", "")
        maps = t.map_list or [mp]
        if mp not in maps:
            abort(400)
        data = compsheet.load(sr.team_dir(tid))
        if request.form.get("reset"):
            data["ideal"].pop(mp.lower(), None)
            flash(f"{mp}: back to the comp from the web.", "ok")
        else:
            agents = compsheet.clean_agents(request.form.getlist("agent"))
            if len(agents) != 5:
                flash("An ideal composition needs 5 different agents.", "error")
                return redirect(url_for("team_sheet", tid=tid) + "#ideal")
            data["ideal"][mp.lower()] = agents
            flash(f"{mp}: ideal composition saved.", "ok")
        compsheet.save(sr.team_dir(tid), data)
        return redirect(url_for("team_sheet", tid=tid) + "#ideal")

    def link_me(t):
        """You are the team player whose Riot ID (Name#TAG) is your in-game name (Account). Replaces the
        "You are" pick on the comps page (4.10); links set before stay."""
        u = g.user
        if not u.display_name or any(m.get("user_id") == u.id for m in t.member_list):
            return t
        members, hit = t.member_list, False
        for m in members:
            p = store.profile(m["pid"])
            if p and not m.get("user_id") and f"{p.name}#{p.tag}".lower() == u.display_name.strip().lower():
                m["user_id"], hit = u.id, True
                break
        if hit:
            store.update_team(t.id, members=members)
            return store.team(t.id)
        return t

    @app.get("/teams/<int:tid>")
    def team(tid: int):
        t = link_me(get_team(tid))
        roles.load(cache_dir)
        c = team_context(t)
        members, byid, rows_by = c["members"], c["byid"], c["rows_by"]
        starters = comp_pools(t, [(byid[m["pid"]].name, m["pid"], rows_by[m["pid"]]) for m in members if m["kind"] == "starter"])
        subs = comp_pools(t, [(byid[m["pid"]].name, m["pid"], rows_by[m["pid"]]) for m in members if m["kind"] == "sub"])
        maps = t.map_list or [m["map"] for m in by_map([r for rs in rows_by.values() for r in rs])][:7]
        try:
            meta = parse_meta(t.meta)
            meta_error = None
        except Exception as e:
            meta, meta_error = {}, str(e)
        plan = None
        method = method_of(t)
        web = sr.read_webcomps(tid) if method == "web" else None
        rules_text = store.get("comp_rules_yaml")
        local = local_meta(filter_rows(owner_rows(t.owner_id), t.queue))
        if len(starters) == 5 and maps:
            plan = comp_plan(method, starters, subs, maps, local, meta, rules_text, web)
        sel = request.args.get("map") or week_map_of(app, t)
        if plan and sel not in [m["map"] for m in plan]:
            sel = plan[0]["map"]
        alts = []
        if plan and sel:
            alts = comp_top(method, starters, sel, local.get(sel), meta.get(sel.lower()), rules_text, web)[1:]
        users = {u.id: u for u in store.users()}
        member_info = [{"p": byid[m["pid"]], "kind": m["kind"], "games": len(rows_by[m["pid"]]),
                        "full": sum(r.get("source") == "full" for r in rows_by[m["pid"]]),
                        "status": sr.status(f"import:{m['pid']}"),
                        "user": users.get(m.get("user_id")), "me": m.get("user_id") == g.user.id} for m in members]
        return render_template(
            "team.html", t=t, premier_status=sr.status(f"premier:{tid}"), member_info=member_info, n_starters=len(starters), n_subs=len(subs),
            starters=[s.label for s in starters], plan=plan, maps=maps, sel=sel,
            detail=next((m for m in plan if m["map"] == sel), None) if plan else None,
            meta_error=meta_error, queues=QUEUE_TABS, tab="comps", alts=alts, comp_method=method,
            comp_label=COMP_METHODS[method], comp_methods=COMP_METHODS, is_owner=g.team_owner,
            web_status=sr.status(f"webcomps:{tid}") if method == "web" else None,
            web_data=web, web_search_on=bool(web_search_on()), follow_pools=pools_followed(t),
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
            method = f.get("comp_method", t.comp_method)
            store.update_team(tid, name=(f.get("name") or t.name).strip()[:60], members=members,
                              maps=[m for m in f.getlist("maps") if m][:12], meta=meta_text,
                              queue=queue if queue in dict(QUEUE_TABS) else "all",
                              comp_method=method if method in COMP_METHODS else "rules")
            set_follow(tid, f.get("follow_pools") == "1")
            flash("Team saved.", "ok")
            return redirect(url_for("team", tid=tid))
        access = store.team_access(tid)
        plays_as = {m.get("user_id"): m["pid"] for m in t.member_list if m.get("user_id")}
        others = [u for u in store.users() if u.id != t.owner_id and u.id not in {a.id for a in access} and not u.disabled]
        return render_template(
            "team_settings.html", t=t, premier_status=sr.status(f"premier:{tid}"), own=own, kinds={m["pid"]: m["kind"] for m in c["members"]},
            access=access, others=others, discord=t.discord_info, plays_as=plays_as,
            games={pid: len(rs) for pid, rs in c["rows_by"].items()},
            map_choices=sorted(set(KNOWN_MAPS) | set(c["seen_maps"])), meta_example=META_EXAMPLE,
            comp_methods=COMP_METHODS, follow_pools=pools_followed(t),
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
        res = checkin_igl(t, team_roles(members, local_meta(filter_rows(owner_rows(t.owner_id), t.queue)), maps)) if members else None
        return render_template("team_roles.html", t=t, tab="roles", res=res, team_roles=TEAM_ROLES, is_owner=g.team_owner,
                               desc=DESCRIPTION, queues=QUEUE_TABS, premier_status=sr.status(f"premier:{tid}"))

    @app.get("/teams/<int:tid>/overview")
    def team_overview(tid: int):
        """Player overview (4.11): agents, agent roles, team role, playstyle and maps per player.
        ?view=all shows every agent and map instead of the top 5."""
        from ..stats.overview import team as overview_team
        from ..stats.style import load_pros
        from ..stats.teamroles import team_roles
        t = get_team(tid)
        roles.load(cache_dir)
        c = team_context(t)
        view = "all" if request.args.get("view") == "all" else "top"
        members = [{"label": c["byid"][m["pid"]].name, "pid": m["pid"], "kind": m["kind"],
                    "rows": c["rows_by"][m["pid"]], "assigned": m.get("roles", [])} for m in c["members"]]
        maps = t.map_list or [m["map"] for m in by_map([r for rs in c["rows_by"].values() for r in rs])][:7]
        try:
            pros = load_pros(store.get("pros_yaml"))
        except Exception:
            pros = load_pros()
        ov = overview_team(checkin_igl(t, team_roles(members, local_meta(filter_rows(owner_rows(t.owner_id), t.queue)), maps)),
                           pros) if members else None
        return render_template("team_overview.html", t=t, tab="overview", ov=ov, view=view, queues=QUEUE_TABS,
                               premier_status=sr.status(f"premier:{tid}"), duos=team_duos(t))

    def team_duos(t) -> dict | None:
        """4.17: every pair of members in the matches they played together."""
        from ..stats import duos as du
        try:
            d = team_data(t)
        except Exception:
            return None
        ms = d["matches"]
        ps = du.pairs(ms, d["names"]) if ms else []
        if not ps:
            return None
        won = sum(1 for m, side in ms if m.team_rounds_won.get(side, 0) > m.team_rounds_won.get(m.other_team(side), 0))
        return {"pairs": ps, "matches": len(ms), "sum": du.summary(ps, won / len(ms) if ms else None)}

    def team_econ(t) -> dict | None:
        """4.21: the team's buys against the teams in the same lobbies."""
        from ..stats import teamecon
        try:
            d = team_data(t)
        except Exception:
            return None
        return teamecon.analyse(d["matches"], d["names"]) if d["matches"] else None

    @app.get("/teams/<int:tid>/economy")
    def team_economy(tid: int):
        t = get_team(tid)
        return render_template("team_economy.html", t=t, tab="economy", e=team_econ(t), premier_status=sr.status(f"premier:{tid}"))

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

    # ------------------------------------------------------------------ post-match check-in (4.15)
    def checkin_igl(t, res: dict | None) -> dict | None:
        """The team's check-ins name the caller: that replaces the IGL guess from the stats (not an assigned IGL)."""
        from ..stats import checkins as ck
        if not res:
            return res
        lu = res.setdefault("lineup", {})
        if any("IGL" in (p.get("assigned") or []) for p in res.get("players") or []):
            return res
        names = {}
        for m in t.member_list:
            pr = store.profile(m["pid"])
            if pr:
                names[m["pid"]] = pr.name
        c = ck.igl(ck.load(sr.team_dir(t.id)), names)
        if c and any(p.get("label") == c["label"] for p in res.get("players") or []):
            lu.setdefault("hats", {})["IGL"] = c["label"]
            lu["igl_votes"] = c
        return res

    def my_pid(t) -> int | None:
        return next((m["pid"] for m in t.member_list if m.get("user_id") == g.user.id), None)

    def checkin_matches(t, d) -> list[dict]:
        """The team's matches together, plus reviewed Premier matches not imported yet (4.16: the Discord
        reminder links to a match right after its review), newest first."""
        out = {}
        for m, side in d["matches"]:
            own, opp = m.team_rounds_won.get(side, 0), m.team_rounds_won.get(m.other_team(side), 0)
            out[m.match_id] = {"id": m.match_id, "map": m.map_name, "when": m.started_at, "score": f"{own}–{opp}",
                               "won": own > opp, "queue": m.queue}
        pj = app.extensions["nexus"].get("premier")
        for r in (pj.reviews(t.id)[:12] if pj else []):
            if r.get("match_id") and r["match_id"] not in out:
                out[r["match_id"]] = {"id": r["match_id"], "map": r.get("map", "?"), "when": r.get("started_at", ""),
                                      "score": r.get("score", ""), "won": bool(r.get("won")), "queue": "premier"}
        return sorted(out.values(), key=lambda x: x["when"] or "", reverse=True)

    @app.get("/teams/<int:tid>/checkin")
    def team_checkin(tid: int):
        """After a match the team played together: who called, comms and mood (1-5), one line. 20 seconds."""
        from ..stats import checkins as ck
        t = link_me(get_team(tid))
        d = team_data(t)
        names = {m["pid"]: d["byid"][m["pid"]].name for m in d["members"]}
        data = ck.load(sr.team_dir(tid))
        me = my_pid(t)
        as_pid = request.args.get("as", type=int) if g.team_owner else None
        if as_pid not in names:
            as_pid = None
        who = as_pid or me
        matches = []
        for mm in checkin_matches(t, d)[:12]:
            ans = data.get(mm["id"]) or {}
            matches.append({**mm, "mine": ans.get(str(who)) if who else None, "sum": ck.summary(ans) if ans else None})
        igl = ck.igl(data, names)
        return render_template("team_checkin.html", t=t, tab="checkin", matches=matches, names=names, me=me, who=who,
                               as_pid=as_pid, igl=igl, min_votes=ck.MIN_VOTES, scale=ck.SCALE, queues=QUEUE_TABS,
                               open_id=request.args.get("m", ""), premier_status=sr.status(f"premier:{tid}"))

    @app.post("/teams/<int:tid>/checkin")
    def team_checkin_save(tid: int):
        from ..stats import checkins as ck
        t = link_me(get_team(tid))
        f = request.form
        members = {m["pid"] for m in t.member_list}
        who = f.get("as", type=int) if g.team_owner and f.get("as", type=int) in members else my_pid(t)
        if who is None:
            flash("Set your in-game name under Account first, so Nexus knows which player you are.", "error")
            return redirect(url_for("team_checkin", tid=tid))
        mid = f.get("match_id", "")
        if not any(m["id"] == mid for m in checkin_matches(t, team_data(t))):
            abort(404)
        ck.record(sr.team_dir(tid), mid, who, f.get("caller", type=int), f.get("comms"), f.get("mood"), f.get("note", ""),
                  members)
        flash("Check-in saved. Thanks!", "ok")
        return redirect(url_for("team_checkin", tid=tid, **({"as": who} if who != my_pid(t) else {})))

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
        get_team(tid)                       # 404 unless the user is in this team
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
        elif f.get("link"):                         # 4.34: the owner says which player a teammate is
            uid = int(f["link"]) if f["link"].isdigit() else 0
            if not store.has_team_access(tid, uid):
                abort(400)
            pid = f.get("pid", "")
            members = []
            for m in t.member_list:
                m = {k: v for k, v in m.items() if not (k == "user_id" and v == uid)}
                if str(m["pid"]) == pid:
                    m["user_id"] = uid
                members.append(m)
            store.update_team(tid, members=members)
            flash("Linked." if pid else "Not linked to a player any more.", "ok")
        elif f.get("remove"):
            uid = int(f["remove"])
            store.remove_team_access(tid, uid)
            store.update_team(tid, members=[{k: v for k, v in m.items() if not (k == "user_id" and v == uid)}
                                            for m in t.member_list])
            flash("Removed.", "ok")
        return redirect(url_for("team_settings", tid=tid) + "#access")

    register_team_extras(app, store, sr, {"get_team": get_team, "team_context": team_context, "team_econ": team_econ,
                                          "team_data": team_data, "owner_rows": owner_rows, "comp_pools": comp_pools})
    from .strats import register as register_strats
    register_strats(app, store, sr, get_team, KNOWN_MAPS)
    from .player_views import register as register_player
    register_player(app, store, sr, {"view_profile": view_profile, "team_context": team_context, "owner_rows": owner_rows,
                                     "queue_arg": queue_arg, "queues": QUEUE_TABS})
    from .lineups import register as register_lineups
    register_lineups(app, store, get_team, KNOWN_MAPS)
    from .practice import register as register_practice
    register_practice(app, store, sr, get_team)
    from .scrims import register as register_scrims
    register_scrims(app, store, sr, get_team, KNOWN_MAPS)
    from .vodreview import register as register_vodreview
    register_vodreview(app, store, sr, get_team)
    from .evening import register as register_evening
    register_evening(app, store, sr, get_team)
    from .prep_views import register as register_prep
    register_prep(app, store, sr, get_team)
    from .aim import register as register_aim
    register_aim(app, store, sr, view_profile, filter_rows)
    from .trainer import register as register_trainer
    register_trainer(app, store, sr, view_profile, filter_rows, KNOWN_MAPS)
    from .callouts import register as register_callouts
    register_callouts(app, store, sr, view_profile, filter_rows, KNOWN_MAPS)
    from .sound import register as register_sound
    register_sound(app, store, sr, view_profile)
    from .maps3d import register as register_maps3d
    register_maps3d(app, store, sr, view_profile, KNOWN_MAPS)
    from .askcoach import register as register_ask
    register_ask(app, store, sr, view_profile, filter_rows)
    from .drafts import register as register_drafts
    register_drafts(app, store, get_team, {"team_context": team_context, "owner_rows": owner_rows,
                                           "web_of": lambda t: sr.read_webcomps(t.id), "comp_pools": comp_pools}, KNOWN_MAPS)

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
            pj = app.extensions["nexus"].get("premier")
            if pj:                             # queued after the roster (one worker): schedule, reviews, the division
                pj.submit_schedule(t.id)
                pj.submit_reviews(t.id, post=True)
                pj.submit_scout(t.id, {"division": True})
        else:
            import_members(t)

    app.extensions["nexus"]["nightly_job"] = nightly_job

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
    from ..stats.teamdata import map_facts, teammate_tips
    from ..stats.teamroles import team_roles
    from ..stats.weekly import player_facts, week_id

    get_team, team_context, team_data, owner_rows = (helpers["get_team"], helpers["team_context"],
                                                     helpers["team_data"], helpers["owner_rows"])
    comp_pools = helpers["comp_pools"]
    team_econ = helpers["team_econ"]
    cache_dir = store.data_dir / "cache"

    def language(t) -> str:
        ps = store.profiles(t.owner_id)
        return ps[0].language if ps else "English"

    build_cache: dict = {}

    def sheet_sig(t) -> str:
        """The comp sheet (agent pools, "follow" switch, 4.14): the comps change with it."""
        try:
            return (sr.team_dir(t.id) / "compsheet.json").read_text()
        except OSError:
            return ""

    def build(t) -> dict:
        """Everything the team pages / jobs need: comps per map, roles, data, tips. Cached until the team or
        anyone's games change (a team page used to recompute all of it on every visit)."""
        web_sig = (tuple(sorted((k, v.get("at")) for k, v in sr.read_webcomps(t.id).items()))
                   if method_of(t) == "web" else ())
        sig = (t.id, t.members, t.maps, t.meta, t.queue, t.comp_method, store.get("comp_rules_yaml"), web_sig,
               tuple(sorted((p.id, sr.games(p.id).signature()) for p in store.profiles(t.owner_id))), sheet_sig(t))
        hit = build_cache.get(t.id)
        if hit and hit[0] == sig:
            return hit[1]
        out = _build(t)
        if len(build_cache) > 50:
            build_cache.clear()
        build_cache[t.id] = (sig, out)
        return out

    def _build(t) -> dict:
        roles.load(cache_dir)
        d = team_data(t)
        members, byid, rows_by = d["members"], d["byid"], d["rows_by"]
        starters = [m for m in members if m["kind"] == "starter"]
        pools = comp_pools(t, [(byid[m["pid"]].name, m["pid"], rows_by[m["pid"]]) for m in starters])
        maps = t.map_list or [m["map"] for m in by_map([r for rs in rows_by.values() for r in rs])][:7]
        try:
            meta = parse_meta(t.meta)
        except Exception:
            meta = {}
        local = local_meta(filter_rows(owner_rows(t.owner_id), t.queue))
        method = method_of(t)
        web = sr.read_webcomps(t.id) if method == "web" else None
        comps = {mp: comp_top(method, pools, mp, local.get(mp), meta.get(mp.lower()), store.get("comp_rules_yaml"), web)
                 for mp in maps} if len(pools) == 5 else {}
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
        from ..stats import checkins as ck
        notes = store.team_notes(t.id)
        team_ci = ck.team_facts(ck.load(sr.team_dir(t.id)), {m["pid"]: b["byid"][m["pid"]].name for m in b["members"]})
        try:
            from ..stats import duos as du
            td = team_data(t)
            duo_facts = du.facts(du.pairs(td["matches"], td["names"])) if td["matches"] else []
        except Exception:
            duo_facts = []
        try:
            from ..stats import teamecon
            econ = teamecon.facts(team_econ(t))
        except Exception:
            econ = None
        scores = {p["label"]: p["scores"] for p in b["roles"]["players"]}
        items = []
        for m in b["members"]:
            name = b["byid"][m["pid"]].name
            tips = [x["text"] for x in b["tips"] if x.get("about") == name]
            about = [n["text"] for n in notes if n["about_pid"] == m["pid"]]
            facts = player_facts(name, b["rows_by"][m["pid"]], b["role_of"].get(name, []), scores.get(name) or {}, tips, about)
            facts.update(sr.coach_extras(m["pid"], b["rows_by"][m["pid"]], cache_dir))      # 4.15
            if team_ci:
                facts["team_check_ins"] = team_ci
            mine = [x for x in duo_facts if name in x["pair"].split(" + ")]
            if mine:
                facts["duos_with_teammates"] = mine          # 4.17
            if econ:
                facts["team_economy"] = econ                 # 4.21
            items.append({"pid": m["pid"], "name": name, "roles": b["role_of"].get(name, []), "facts": facts})
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
        sr.submit_plans(tid, items, language(t), post, picked(store))
        return redirect(url_for("team_plans", tid=tid, map=None if which == "__all" else which))

    @app.post("/teams/<int:tid>/replay-scouting/counter")
    def team_replay_counter(tid: int):
        """4.19: game plans for one map against a team from replay scouting (its habits go to the model)."""
        from ..stats import replayprep as rp
        t = get_team(tid)
        who, mp = request.form.get("who", ""), request.form.get("map", "")
        sc = app.extensions["nexus"]["replay_scouting"](t, who)
        if sc["sel"] is None or sc["who"] != who or mp not in sc["a"]:
            flash("Pick a team you played and a map with replays first.", "error")
            return redirect(url_for("team_replay_prep", tid=tid, who=who, map=mp))
        b = build(t)                                  # cached: only read
        if mp not in b["maps"]:
            flash(f"{mp} isn't one of the team's maps (team settings).", "error")
            return redirect(url_for("team_replay_prep", tid=tid, who=who, map=mp))
        items = plan_items(t, b, [mp])
        if not items:
            flash("Pick 5 starters and update everyone's stats first (the plans need a comp for this map).", "error")
            return redirect(url_for("team_replay_prep", tid=tid, who=who, map=mp))
        name = sc["sel"]["label"]
        items[0]["opponent"] = {"name": name, "habits": rp.facts(sc["a"][mp], name)}
        sr.submit_plans(tid, items, language(t), None, picked(store))
        flash(f"Writing counter-plans for {mp} against {name}.", "ok")
        return redirect(url_for("team_plans", tid=tid, map=mp))

    @app.post("/teams/<int:tid>/discord/prep")
    def team_post_prep(tid: int):
        t = get_team(tid, manage=True)
        b = build(t)
        maps = [m for m in request.form.getlist("maps") if m in b["maps"]] or b["maps"]
        if not (t.discord_info.get("prep_url") or t.discord_info.get("focus_url")):
            flash("Add a Discord webhook under the team's ⚙ Settings first.", "error")
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
            pl["own"] = sr.read_own_focus(pl["pid"])
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
            sr.submit_focus(tid, week_id(), items, language(t), post=bool(request.form.get("post")), llm_choice=picked(store))
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
        for k in ("prep_url", "focus_url", "review_url", "clips_url"):
            v = f.get(k, "").strip()
            if v and not valid_url(v):
                flash(f"That doesn't look like a Discord webhook URL: {v[:60]}…", "error")
                return redirect(url_for("team_settings", tid=tid) + "#discord")
            if v or f.get(f"clear_{k}"):
                info[k] = v
        from ..i18n import LANGS
        if f.get("lang") in LANGS:
            info["lang"] = f.get("lang")
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
                dpost(url, f"✅ Nexus is connected to **{t.name}**. Comps, game plans and the weekly focus will show up here.")
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
            sr.submit_focus(t.id, week_id(), items, language(t), post=True, llm_choice=sr.AUTO)

    app.extensions["nexus"]["weekly_job"] = weekly_job

    from .premier_views import register as register_premier
    register_premier(app, store, sr, {"get_team": get_team, "team_data": team_data, "build": build, "known_maps": KNOWN_MAPS,
                                      "team_context": team_context})
