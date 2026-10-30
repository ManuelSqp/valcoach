"""Roster drafts: per map, five player slots with an agent (and a backup agent) each, dragged in
from the agent list. Everyone in the team can make and edit drafts; deleting is for the author
and the team owner. The editor shows each player's real numbers on the agent and map."""
from __future__ import annotations

import json
import time

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..stats import roles
from ..stats.aggregate import filter_rows, local_meta
from ..stats.comp import Pool, parse_meta, rate, top_comps

SLOTS = 5
STATUSES = ("idea", "try", "main")         # idea -> trying it in games -> our comp
MAX_DRAFT_BYTES = 50_000


def empty_data() -> dict:
    return {"slots": [{"pid": None, "agent": "", "alt": "", "note": ""} for _ in range(SLOTS)],
            "status": "idea", "notes": ""}


def clean_draft(data: dict, pids: set[int], agents: set[str]) -> dict:
    """Draft JSON as saved by any team member: keep only well-typed fields. Players must be team
    members and agents real agents, so another member's browser only ever gets known values."""
    out = empty_data()
    slots = data.get("slots") if isinstance(data.get("slots"), list) else []
    for i, s in enumerate(slots[:SLOTS]):
        if not isinstance(s, dict):
            continue
        pid = s.get("pid")
        if isinstance(pid, str) and pid.isdigit():
            pid = int(pid)
        out["slots"][i] = {
            "pid": pid if isinstance(pid, int) and not isinstance(pid, bool) and pid in pids else None,
            "agent": s["agent"] if s.get("agent") in agents else "",
            "alt": s["alt"] if s.get("alt") in agents else "",
            "note": str(s.get("note") or "")[:60],
        }
    out["status"] = data.get("status") if data.get("status") in STATUSES else "idea"
    out["notes"] = str(data.get("notes") or "")[:3000]
    return out


def register(app, store, get_team, helpers: dict, known_maps: list[str]) -> None:
    team_context, owner_rows = helpers["team_context"], helpers["owner_rows"]
    cache_dir = store.data_dir / "cache"

    def maps_for(t) -> list[str]:
        return list(t.map_list) or sorted(known_maps)

    def agent_list() -> list[dict]:
        roles.load(cache_dir)
        out = [{"name": a, "role": roles.role_of(a)} for a in roles.all_agents()]
        out.sort(key=lambda a: (roles.ROLES.index(a["role"]) if a["role"] in roles.ROLES else 9, a["name"]))
        return out

    def get_draft(tid: int, did: int):
        t = get_team(tid)
        d = store.draft(did)
        if d is None or d["team_id"] != tid:
            abort(404)
        return t, d

    def roster(t) -> tuple[list[dict], dict]:
        """Members (starters first) and their game rows."""
        c = team_context(t)
        members = sorted(c["members"], key=lambda m: m["kind"] != "starter")
        players = [{"pid": m["pid"], "name": c["byid"][m["pid"]].name, "kind": m["kind"],
                    "roles": m.get("roles", [])} for m in members]
        return players, c["rows_by"]

    def player_stats(players: list[dict], rows_by: dict, map_name: str, local: dict | None, meta: dict | None) -> dict:
        """{pid: {agent: {n_all, wr_all, n_map, wr_map, acs_map, score}}} for agents they've played."""
        out = {}
        for p in players:
            pool = Pool.from_rows(p["name"], rows_by.get(p["pid"], []))
            per = {}
            for a in pool.n:
                r = rate(pool, a, map_name, local, meta)
                per[a] = {k: (round(v, 3) if isinstance(v, float) else v)
                          for k, v in r.items() if k in ("n_all", "wr_all", "n_map", "wr_map", "acs_map", "score")}
            out[str(p["pid"])] = per
        return out

    def suggestions(t, players: list[dict], rows_by: dict, map_name: str, local, meta) -> list[dict]:
        starters = [p for p in players if p["kind"] == "starter"]
        if len(starters) != SLOTS:
            return []
        pools = [Pool.from_rows(p["name"], rows_by.get(p["pid"], [])) for p in starters]
        pid_of = {p["name"]: p["pid"] for p in starters}
        out = []
        for c in top_comps(pools, map_name, local, meta):
            if c.get("ok"):
                out.append({"pattern": c.get("pattern", ""),
                            "picks": [{"pid": pid_of.get(pk["player"]), "player": pk["player"], "agent": pk["agent"]}
                                      for pk in c["picks"]]})
        return out

    def context(t, map_name: str) -> dict:
        players, rows_by = roster(t)
        try:
            meta = parse_meta(t.meta).get(map_name.lower())
        except Exception:
            meta = None
        local = local_meta(filter_rows(owner_rows(t.owner_id), t.queue)).get(map_name)
        return {"players": players, "stats": player_stats(players, rows_by, map_name, local, meta),
                "suggestions": suggestions(t, players, rows_by, map_name, local, meta)}

    # ------------------------------------------------------------------ pages
    @app.route("/teams/<int:tid>/drafts", methods=["GET", "POST"])
    def team_drafts(tid: int):
        t = get_team(tid)
        maps = maps_for(t)
        if request.method == "POST":
            f = request.form
            m = f.get("map", "")
            if m not in maps:
                abort(400)
            data, name = empty_data(), (f.get("name") or "").strip()
            src = f.get("from", "")
            players, _ = roster(t)
            if src.startswith("comp:"):                       # one of the suggested comps
                ctx = context(t, m)
                try:
                    sug = ctx["suggestions"][int(src[5:])]
                except (ValueError, IndexError):
                    sug = None
                if sug:
                    for i, pk in enumerate(sug["picks"][:SLOTS]):
                        data["slots"][i].update(pid=pk["pid"], agent=pk["agent"])
                    name = name or f"Suggestion {int(src[5:]) + 1}: " + ", ".join(pk["agent"] for pk in sug["picks"])
            elif src.startswith("copy:") and src[5:].isdigit():
                old = store.draft(int(src[5:]))
                if old and old["team_id"] == tid:
                    data = old["data"]
                    name = name or f"{old['name']} (copy)"
            else:                                             # empty: the starters in order, no agents
                for i, p in enumerate([p for p in players if p["kind"] == "starter"][:SLOTS]):
                    data["slots"][i]["pid"] = p["pid"]
            data = clean_draft(data, {p["pid"] for p in players}, {a["name"] for a in agent_list()})
            did = store.create_draft(tid, g.user.id, m, (name or f"{m} draft")[:80], data)
            return redirect(url_for("team_drafts", tid=tid, map=m, d=did))

        sel = request.args.get("map") or ""
        counts: dict[str, int] = {}
        for d in store.drafts(tid):
            counts[d["map"]] = counts.get(d["map"], 0) + 1
        if sel not in maps:
            fn = app.extensions["valcoach"].get("week_map")
            wm = fn(t) if fn and t.premier_info.get("tag") else None
            sel = wm if wm in maps else next((m for m in maps if counts.get(m)), maps[0] if maps else "")
        drafts = store.drafts(tid, sel) if sel else []
        cur = None
        if request.args.get("d", "").isdigit():
            cur = next((d for d in drafts if d["id"] == int(request.args["d"])), None)
        cur = cur or (drafts[0] if drafts else None)
        ctx = context(t, sel) if sel else {"players": [], "stats": {}, "suggestions": []}
        can_delete = {d["id"]: bool(g.team_owner or d["author_id"] == g.user.id) for d in drafts}
        boot = {"map": sel, "draft": {k: cur[k] for k in ("id", "name", "data", "updated_at")} if cur else None,
                "players": ctx["players"], "stats": ctx["stats"], "agents": agent_list(),
                "save_url": url_for("draft_save", tid=tid, did=cur["id"]) if cur else None,
                "agent_icon": url_for("agent_icon", name="__A__")}
        return render_template("team_drafts.html", t=t, tab="drafts", maps=maps, sel=sel, counts=counts, drafts=drafts,
                               cur=cur, suggestions=ctx["suggestions"], players=ctx["players"], can_delete=can_delete,
                               discord=t.discord_info, boot=json.dumps(boot).replace("</", "<\\/"), premier_status=None)

    @app.post("/api/teams/<int:tid>/drafts/<int:did>")
    def draft_save(tid: int, did: int):
        t, d = get_draft(tid, did)
        body = request.get_json(silent=True)                 # JSON only: a cross-site form can't send this
        if not isinstance(body, dict):
            return jsonify(error="expected JSON"), 400
        fields = {}
        if "name" in body:
            fields["name"] = str(body["name"]).strip()[:80] or "Untitled"
        if "data" in body:
            if not isinstance(body["data"], dict):
                return jsonify(error="data must be an object"), 400
            if len(json.dumps(body["data"])) > MAX_DRAFT_BYTES:
                return jsonify(error="draft too big"), 413
            players, _ = roster(t)
            fields["data"] = clean_draft(body["data"], {p["pid"] for p in players}, {a["name"] for a in agent_list()})
        store.update_draft(did, g.user.id, **fields)
        return jsonify(ok=True, saved_at=time.strftime("%H:%M:%S"))

    @app.post("/teams/<int:tid>/drafts/<int:did>/delete")
    def draft_delete(tid: int, did: int):
        t, d = get_draft(tid, did)
        if not (g.team_owner or d["author_id"] == g.user.id):
            abort(403)
        store.delete_draft(did)
        flash(f"Deleted {d['name']}.", "ok")
        return redirect(url_for("team_drafts", tid=tid, map=d["map"]))

    @app.post("/teams/<int:tid>/drafts/<int:did>/discord")
    def draft_discord(tid: int, did: int):
        from ..discord import post
        t, d = get_draft(tid, did)
        url = t.discord_info.get("prep_url") or t.discord_info.get("focus_url")
        if not url:
            flash("Add a Discord webhook under Members, maps & Discord first.", "error")
            return redirect(url_for("team_drafts", tid=tid, map=d["map"], d=did))
        players = {p["pid"]: p["name"] for p in roster(t)[0]}
        lines = []
        for s in d["data"].get("slots", []):
            if not (s.get("agent") or s.get("pid")):
                continue
            who = players.get(s.get("pid"), "open slot")
            line = f"**{s.get('agent') or '?'}** · {who}"
            if s.get("alt"):
                line += f" (or {s['alt']})"
            if s.get("note"):
                line += f" · {s['note']}"
            lines.append(line)
        status = {"idea": "idea", "try": "trying it", "main": "our comp"}.get(d["data"].get("status"), "idea")
        notes = (d["data"].get("notes") or "").strip()
        embed = {"title": f"{d['map']} draft: {d['name']}"[:250], "description": "\n".join(lines)[:3500] or "(empty)",
                 "color": 0xFF4655, "footer": {"text": f"valcoach · {status}"}}
        if notes:
            embed["fields"] = [{"name": "Notes", "value": notes[:1000]}]
        try:
            post(url, "", embeds=[embed])
            flash("Posted the draft to Discord.", "ok")
        except Exception as e:
            flash(f"Discord: {e}", "error")
        return redirect(url_for("team_drafts", tid=tid, map=d["map"], d=did))
