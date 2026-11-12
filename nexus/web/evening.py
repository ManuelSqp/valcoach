"""Team › Practice › Review evening: go through one match round by round together.

Whoever starts the evening hosts it: the host moves from round to round and everyone who follows the host
jumps along (the page asks the server every few seconds). Everyone marks his own rounds; the summary at the
end goes to the practice plan and, if the owner wants, to Discord.

Files: data/teams/<tid>/evenings/<id>.json (facts, marks, state) and <id>.replay.json (the minimap replay,
made the first time someone opens it)."""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from .. import pipeline
from ..parse import parse_match
from ..discord import channel as _channel
from ..stats import evening as ev_stats

SID_RE = re.compile(r"[0-9a-f]{10}")
PRESENT_S = 20                   # someone counts as "here" this long after his last refresh
MAX_NOTE = 200
REPLAY_V = 2                     # 4.18: the replay file's positions and utility when there is one
MAX_EVENINGS = 60
_lock = threading.RLock()
_present: dict[tuple[int, str], dict[str, float]] = {}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def register(app, store, sr, get_team) -> None:
    cache = store.data_dir / "cache"

    def edir(tid: int) -> Path:
        return sr.team_dir(tid) / "evenings"

    def load(tid: int, sid: str) -> dict:
        if not SID_RE.fullmatch(sid or ""):
            abort(404)
        ev = _read(edir(tid) / f"{sid}.json")
        if not ev:
            abort(404)
        return ev

    def save(tid: int, ev: dict) -> None:
        ev["updated"] = time.time()
        _write(edir(tid) / f"{ev['id']}.json", ev)

    def evenings(tid: int) -> list[dict]:
        d = edir(tid)
        out = [x for x in (_read(p) for p in d.glob("*.json") if not p.name.endswith(".replay.json")) if x] if d.exists() else []
        return sorted(out, key=lambda e: e.get("created", 0), reverse=True)

    def member_puuids(t) -> dict[str, int]:
        """puuid -> pid of every team member (starters and subs)."""
        out = {}
        for m in t.member_list:
            pu = m.get("puuid") or (sr.games(m["pid"]).load() or {}).get("puuid")
            if pu:
                out[pu] = m["pid"]
        return out

    def candidates(t, limit: int = 20) -> list[dict]:
        """Matches two or more of you played together (newest first), from everyone's games, plus Premier reviews."""
        seen: dict[str, dict] = {}
        for m in t.member_list:
            p = store.profile(m["pid"])
            if not p:
                continue
            for r in sr.games(m["pid"]).rows()[:80]:
                mid = r.get("match_id")
                if not mid or not pipeline.valid_match_id(mid):
                    continue
                e = seen.setdefault(mid, {"match_id": mid, "map": r.get("map"), "started_at": r.get("started_at") or "",
                                          "won": bool(r.get("won")), "score": (r.get("score") or "").replace("-", "–"),
                                          "queue": r.get("queue") or "", "who": []})
                e["who"].append(p.name)
        pj = app.extensions["nexus"].get("premier")
        reviewed = {r["match_id"]: r for r in pj.reviews(t.id)} if pj else {}
        for mid, r in reviewed.items():
            e = seen.setdefault(mid, {"match_id": mid, "map": r.get("map"), "started_at": r.get("started_at") or "",
                                      "won": bool(r.get("won")), "score": r.get("score") or "", "queue": "premier", "who": []})
            e["review"] = True
            e["opponent"] = r.get("opponent")
        out = [e for e in seen.values() if (len(e["who"]) >= 2 or e.get("review")) and (cache / "matches" / f"{e['match_id']}.json").exists()]
        out.sort(key=lambda e: e["started_at"], reverse=True)
        return out[:limit]

    def my_player(t, ev: dict) -> str:
        """The player in the match this user most likely is (his team member's puuid, else his Riot ID)."""
        names = {p["puuid"]: p["name"] for p in ev["players"]}
        for m in t.member_list:
            if m.get("user_id") == g.user.id and m.get("puuid") in names:
                return names[m["puuid"]]
        dn = (g.user.display_name or "").split("#")[0].lower()
        return next((p["name"] for p in ev["players"] if p["name"].lower() == dn), "")

    def can_host(t, ev: dict) -> bool:
        return bool(g.team_owner or ev.get("host_id") == g.user.id)

    def here(tid: int, sid: str) -> list[str]:
        now = time.time()
        k = (tid, sid)
        with _lock:
            d = _present.setdefault(k, {})
            d[g.user.display_name or g.user.username] = now
            for name in [n for n, ts in d.items() if now - ts > PRESENT_S]:
                d.pop(name, None)
            return sorted(d)

    def pin_action(ev: dict, b: dict, act: str, host: bool) -> str | None:
        """Add or remove a note on the playback (pins.py): {round, t (ms), text, strokes} / {round, id}."""
        from . import pins as pn
        try:
            n = int(b.get("round"))
        except (TypeError, ValueError):
            return "unknown round"
        if not 1 <= n <= len(ev["rounds"]):
            return "unknown round"
        return pn.apply(ev.setdefault("pins", {}), b, act, n, g.user.display_name or g.user.username, g.user.id, host)

    def state(t, ev: dict) -> dict:
        return {"current": ev.get("current", 1), "host": ev.get("host"), "finished": bool(ev.get("finished")),
                "marks": ev.get("marks") or {}, "here": here(t.id, ev["id"]), "updated": ev.get("updated", 0),
                "planned": ev.get("planned") or "", "pins": ev.get("pins") or {}}

    # ------------------------------------------------------------------ pages
    @app.route("/teams/<int:tid>/review-evening", methods=["GET", "POST"])
    def team_evening(tid: int):
        t = get_team(tid)
        if request.method == "POST":
            mid = request.form.get("match_id", "")
            if not pipeline.valid_match_id(mid):
                abort(400)
            raw = _read(cache / "matches" / f"{mid}.json")
            if not raw:
                flash("That match isn't loaded yet: update everyone's stats first.", "error")
                return redirect(url_for("team_evening", tid=tid))
            m = parse_match(raw)
            side = ev_stats.our_side(m, set(member_puuids(t)))
            if side is None:
                flash("Fewer than two of your team played in that match.", "error")
                return redirect(url_for("team_evening", tid=tid))
            other = m.other_team(side)
            rv = None
            pj = app.extensions["nexus"].get("premier")
            if pj:
                rv = pj.review(tid, mid)
            ours, theirs = m.team_rounds_won.get(side, 0), m.team_rounds_won.get(other, 0)
            ev = {"id": secrets.token_hex(5), "match_id": m.match_id or mid, "map": m.map_name, "started_at": m.started_at,
                  "queue": m.queue, "won": ours > theirs, "score": f"{ours}–{theirs}", "side_team": side,
                  "opponent": (rv or {}).get("opponent") or "their team",
                  "players": [{"name": p.name, "agent": p.agent, "puuid": p.puuid} for p in m.players_on(side)],
                  "rounds": ev_stats.round_facts(m, side), "marks": {}, "current": 1,
                  "host_id": g.user.id, "host": g.user.display_name or g.user.username, "created": time.time(),
                  "finished": False}
            ev["key"] = ev_stats.key_rounds(ev["rounds"])
            ev["current"] = 1
            save(tid, ev)
            old = evenings(tid)[MAX_EVENINGS:]           # keep the newest ones
            for x in old:
                for suffix in (".json", ".replay.json"):
                    (edir(tid) / f"{x['id']}{suffix}").unlink(missing_ok=True)
            return redirect(url_for("team_evening_session", tid=tid, sid=ev["id"]))
        pre = request.args.get("match", "")
        return render_template("team_evening.html", t=t, tab="evening", premier_status=None, evenings=evenings(tid)[:12],
                               matches=candidates(t), pre=pre if pipeline.valid_match_id(pre) else "")

    @app.get("/teams/<int:tid>/review-evening/<sid>")
    def team_evening_session(tid: int, sid: str):
        t = get_team(tid)
        ev = load(tid, sid)
        summary = ev_stats.summarize(ev)
        return render_template("team_evening_session.html", t=t, tab="evening", premier_status=None, ev=ev,
                               me=my_player(t, ev), host=can_host(t, ev), summary=summary, marks=ev_stats.MARKS,
                               boot=json.dumps({"state": state(t, ev), "rounds": ev["rounds"], "key": ev.get("key") or [],
                                                "players": ev["players"], "me": my_player(t, ev), "host": can_host(t, ev),
                                                "api": url_for("team_evening_api", tid=tid, sid=sid),
                                                "replay": url_for("team_evening_replay", tid=tid, sid=sid),
                                                "uid": g.user.id, "map": ev.get("map") or "",
                                                "to_strat": url_for("strat_from_replay", tid=tid),
                                                "moment": url_for("team_evening_moment", tid=tid, sid=sid)
                                                if _channel(t.discord_info, "review") else "",
                                                "opponent": ev.get("opponent") or "",
                                                "replay_js": url_for("replay_js"),
                                                "summary": url_for("team_evening_summary", tid=tid, sid=sid), "marks": ev_stats.MARKS,
                                                "agent_icon": url_for("agent_icon", name="__A__")}).replace("</", "<\\/"),
                               discord=bool(_channel(t.discord_info, "review")))

    @app.get("/teams/<int:tid>/review-evening/<sid>/summary")
    def team_evening_summary(tid: int, sid: str):
        """Just the summary block, so it stays current while people mark."""
        t = get_team(tid)
        ev = load(tid, sid)
        return render_template("_evening_summary.html", t=t, ev=ev, host=can_host(t, ev), summary=ev_stats.summarize(ev),
                               discord=bool(_channel(t.discord_info, "review")))

    @app.get("/api/teams/<int:tid>/review-evening/<sid>")
    def team_evening_state(tid: int, sid: str):
        t = get_team(tid)
        return jsonify(state(t, load(tid, sid)))

    @app.post("/api/teams/<int:tid>/review-evening/<sid>")
    def team_evening_api(tid: int, sid: str):
        t = get_team(tid)
        b = request.get_json(silent=True) or {}
        act = b.get("action")
        with _lock:
            ev = load(tid, sid)
            n_max = len(ev["rounds"])
            if act == "mark":
                try:
                    n = int(b.get("round"))
                except (TypeError, ValueError):
                    return jsonify(error="unknown round"), 400
                player = str(b.get("player") or "")
                if not 1 <= n <= n_max or player not in {p["name"] for p in ev["players"]}:
                    return jsonify(error="unknown round or player"), 400
                mark = b.get("mark")
                by = ev.setdefault("marks", {}).setdefault(str(n), {})
                if mark in (None, "", "none"):
                    by.pop(player, None)
                    if not by:
                        ev["marks"].pop(str(n), None)
                elif mark in ev_stats.MARKS:
                    by[player] = {"m": mark, "note": str(b.get("note") or "").strip()[:MAX_NOTE],
                                  "by": g.user.display_name or g.user.username}
                else:
                    return jsonify(error="unknown mark"), 400
            elif act in ("pin", "unpin"):
                err = pin_action(ev, b, act, can_host(t, ev))
                if err:
                    return jsonify(error=err), 400 if err != "not yours" else 403
            elif act == "goto":
                if not can_host(t, ev):
                    return jsonify(error="only the host moves everyone"), 403
                try:
                    ev["current"] = max(1, min(n_max, int(b.get("round"))))
                except (TypeError, ValueError):
                    return jsonify(error="unknown round"), 400
            elif act in ("finish", "reopen"):
                if not can_host(t, ev):
                    return jsonify(error="only the host ends the evening"), 403
                ev["finished"] = act == "finish"
            elif act == "host":                       # take over as host (the owner, or when the host left)
                if not (g.team_owner or (ev.get("host") not in here(tid, sid))):
                    return jsonify(error="the host is still here"), 403
                ev["host_id"], ev["host"] = g.user.id, g.user.display_name or g.user.username
            else:
                return jsonify(error="unknown action"), 400
            save(tid, ev)
        return jsonify(state(t, ev))

    @app.post("/api/teams/<int:tid>/review-evening/<sid>/moment")
    def team_evening_moment(tid: int, sid: str):
        """4.20: a moment of the playback (the picture the page made) to the team's Discord."""
        from .report_tools import post_moment
        t = get_team(tid)
        ev = load(tid, sid)
        url = _channel(t.discord_info, "review")
        if not url:
            return jsonify(error="no Discord webhook for reviews set for this team"), 400
        return post_moment(url, f"{ev.get('map') or ''} {ev.get('score') or ''} vs {ev.get('opponent') or 'them'}".strip())

    @app.post("/teams/<int:tid>/review-evening/<sid>/plan")
    def team_evening_plan(tid: int, sid: str):
        """The summary's practice items into this week's practice plan (next practice day)."""
        t = get_team(tid)
        with _lock:
            ev = load(tid, sid)
            if not can_host(t, ev):
                abort(403)
            items = ev_stats.summarize(ev)["plan"]
            if not items:
                flash("Nothing to add yet: mark a few rounds first.", "error")
                return redirect(url_for("team_evening_session", tid=tid, sid=sid) + "#summary")
            ev["plan_items"] = items
            from ..stats.weekly import week_id
            ev["planned"] = week_id()
            ev["planned_at"] = time.time()
            save(tid, ev)
        add = app.extensions["nexus"].get("practice_add")
        n = add(t, ev) if add else 0
        flash(f"Added {n} item{'s' if n != 1 else ''} to this week's practice plan." if n else
              "Saved: the items go into the next practice plan (no practice day left this week).", "ok")
        return redirect(url_for("team_practice", tid=tid))

    @app.post("/teams/<int:tid>/review-evening/<sid>/post")
    def team_evening_post(tid: int, sid: str):
        t = get_team(tid, manage=True)
        ev = load(tid, sid)
        from ..discord import channel, post as dpost
        url = channel(t.discord_info, "review") or channel(t.discord_info, "focus")
        try:
            if not url:
                raise RuntimeError("Add a Discord webhook under Team settings first.")
            dpost(url, ev_stats.discord_text(ev, ev_stats.summarize(ev), t.name))
            flash("Posted the summary to Discord.", "ok")
        except Exception as e:
            flash(f"Not posted: {e}", "error")
        return redirect(url_for("team_evening_session", tid=tid, sid=sid) + "#summary")

    @app.post("/teams/<int:tid>/review-evening/<sid>/delete")
    def team_evening_delete(tid: int, sid: str):
        t = get_team(tid)
        ev = load(tid, sid)
        if not can_host(t, ev):
            abort(403)
        for suffix in (".json", ".replay.json"):
            (edir(tid) / f"{sid}{suffix}").unlink(missing_ok=True)
        flash("Review evening deleted.", "ok")
        return redirect(url_for("team_evening", tid=tid))

    @app.get("/teams/<int:tid>/review-evening/<sid>/replay.json")
    def team_evening_replay(tid: int, sid: str):
        """The minimap replay of every round (made once, then read from the file)."""
        get_team(tid)
        ev = load(tid, sid)
        p = edir(tid) / f"{sid}.replay.json"
        data = _read(p)
        if data is None or data.get("v") != REPLAY_V:
            data = build_replay_data(ev)
            _write(p, data)
        resp = jsonify(data)
        resp.headers["Cache-Control"] = "private, max-age=3600"
        return resp

    def build_replay_data(ev: dict) -> dict:
        from ..analysis.view import calibrate
        from ..coach.replay import build_replay, map_meta, nav_grid
        from ..maps import MapRegistry
        raw = _read(cache / "matches" / f"{ev['match_id']}.json")
        if not raw:
            return {"map": None, "rounds": {}}
        m = parse_match(raw)
        reg = MapRegistry(cache)
        try:
            mi = reg.get(m.map_id, m.map_name)
        except Exception:
            mi = None
        if mi is None:
            return {"map": None, "rounds": {}}
        meta = map_meta(mi, reg, embed_image=False) or {}
        meta["image"] = url_for("map_image", name=mi.name)
        vm = calibrate(m)
        nav = nav_grid(mi, reg)
        focus = next((p.puuid for p in m.players_on(ev["side_team"])), "")
        rep = replay_file(m, focus, mi)              # 4.18: everyone's positions and utility from the replay file
        rounds = {}
        for r in m.rounds:
            try:
                rp = build_replay(m, r, focus, mi, vm, (rep or {}).get("self_paths", {}).get(r.index), nav,
                                  (rep or {}).get("others", {}).get(r.index))
            except Exception:
                rp = None
            if rp:
                for x in rp["roster"].values():
                    x["you"] = False          # every viewer marks himself in the browser
                rounds[r.number] = rp
        agents = {p.agent: url_for("agent_icon", name=p.agent) for p in m.players.values()}
        from ..coach.replay import ABILITY_SLOT
        for o in (rep or {}).get("others", {}).values():
            for e in o.get("effects") or []:
                if e.get("agent") and e.get("slot") in ABILITY_SLOT:
                    agents[f"{e['agent']}|{e['slot']}"] = url_for("ability_icon", agent=e["agent"], slot=ABILITY_SLOT[e["slot"]])
        return {"v": REPLAY_V, "map": meta, "agents": agents, "better": {}, "rounds": rounds,
                "source": "replay file" if rep else ""}

    def replay_file(m, focus: str, mi) -> dict | None:
        """The match's replay file (positions of all ten, casts, placed utility), or None."""
        from .. import replayfile
        from ..maps import AgentRegistry
        replays = store.data_dir / "replays"
        if not focus or not replayfile.has_replay(replays, m.match_id):
            return None
        try:
            names = {a["dev"]: a["name"] for a in AgentRegistry(cache).load() if a.get("dev")}
        except Exception:
            names = {}
        try:
            return replayfile.for_match(replays, cache / "vrf_work", replayfile.vrfkit_path(store.get("vrfkit_path") or ""), m, focus, mi,
                                        agent_names=names)
        except Exception:
            return None

    @app.get("/replay.js")
    def replay_js():
        return send_file(Path(__file__).resolve().parent.parent / "replay.js", mimetype="text/javascript", max_age=3600)

    app.extensions["nexus"]["evenings"] = evenings
