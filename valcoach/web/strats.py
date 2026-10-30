"""Strat book: boards on the minimap with agents, every ability, smokes, walls, arrows and text,
in steps (setup -> execute -> ...), saved per team and map. Everyone in the team can view and
edit boards; deleting is for the author and the team owner."""
from __future__ import annotations

import json
import re
import time

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from ..maps import AgentRegistry, MapRegistry
from ..stats import roles
from .abilityshapes import color_for, shape_for

SIDES = ("attack", "defense")
MAX_BOARD_BYTES = 400_000          # JSON of one board (items are tiny; this is plenty)
ITEM_NUMBERS = ("x", "y", "x2", "y2", "r", "len", "ang", "n", "size")
ITEM_STRINGS = {"t": 20, "id": 20, "a": 40, "s": 80, "label": 40, "c": 10}


def _number(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) < 1e6 else None          # no NaN / inf


def clean_board(data: dict) -> dict:
    """Board JSON as saved by any team member: keep only well-typed item fields, so another
    member's browser never gets text where the editor expects a number (it builds HTML from them)."""
    steps = []
    for st in data.get("steps") or []:
        if not isinstance(st, dict):
            continue
        items = []
        for it in st.get("items") or []:
            if not isinstance(it, dict):
                continue
            out = {}
            for k in ITEM_NUMBERS:
                if k in it and (x := _number(it[k])) is not None:
                    out[k] = x
            for k, n in ITEM_STRINGS.items():
                if isinstance(it.get(k), str):
                    out[k] = it[k][:n]
            if "dash" in it:
                out["dash"] = bool(it["dash"])
            if isinstance(it.get("pts"), list):
                pts = [[_number(p[0]), _number(p[1])] for p in it["pts"][:2000] if isinstance(p, list) and len(p) >= 2]
                out["pts"] = [p for p in pts if None not in p]
            if "t" in out:
                items.append(out)
        steps.append({"name": str(st.get("name") or "")[:40], "items": items})
    out = dict(data)
    out["steps"] = steps
    if "notes" in out:
        out["notes"] = str(out["notes"] or "")[:5000]
    return out
MAX_PNG_BYTES = 8_000_000
SLOT_ORDER = {"grenade": 0, "ability1": 1, "ability2": 2, "ultimate": 3}


def register(app, store, sr, get_team, known_maps: list[str]) -> None:
    cache_dir = store.data_dir / "cache"
    agents_reg = AgentRegistry(cache_dir)
    maps_reg = MapRegistry(cache_dir)
    misses: dict[str, float] = {}

    def missing(key: str) -> bool:
        return time.time() - misses.get(key, 0) < 600

    # ------------------------------------------------------------------ assets
    @app.get("/map-image/<path:name>")
    def map_image(name: str):
        if missing("map:" + name):
            abort(404)
        try:
            mi = maps_reg.get(name=name)
            f = maps_reg.minimap_image(mi) if mi else None
        except Exception:
            f = None
        if not f or not f.exists():
            misses["map:" + name] = time.time()
            abort(404)
        return send_file(f, mimetype="image/png", max_age=86400)

    @app.get("/ability-icon/<path:agent>/<slot>")
    def ability_icon(agent: str, slot: str):
        key = f"ab:{agent}:{slot}"
        if missing(key):
            abort(404)
        try:
            a = agents_reg.find(name=agent)
            f = agents_reg.ability_icon_file(a, slot) if a else None
        except Exception:
            f = None
        if not f or not f.exists():
            misses[key] = time.time()
            abort(404)
        return send_file(f, mimetype="image/png", max_age=86400)

    def assets(map_name: str) -> dict:
        roles.load(cache_dir)
        try:
            agents = agents_reg.load()
        except Exception:
            agents = []
        names = {a["name"] for a in agents}
        out_agents = []
        for a in agents:
            if not a.get("name"):
                continue
            role = a.get("role") or roles.role_of(a["name"])
            abl = [{"slot": ab["slot"], "name": ab["name"], "shape": shape_for(ab["name"])} for ab in a.get("abilities", [])]
            out_agents.append({"name": a["name"], "role": role, "color": color_for(a["name"], role),
                               "abilities": sorted(abl, key=lambda x: SLOT_ORDER.get(x["slot"].lower(), 9))})
        for n in roles.all_agents():            # offline / not in the cached list: still placeable as a portrait
            if n not in names:
                out_agents.append({"name": n, "role": roles.role_of(n), "color": color_for(n, roles.role_of(n)), "abilities": []})
        out_agents.sort(key=lambda a: (roles.ROLES.index(a["role"]) if a["role"] in roles.ROLES else 9, a["name"]))
        mp = {"name": map_name, "callouts": [], "m": 7.0}      # m = board units (of 1000) per meter
        try:
            mi = maps_reg.get(name=map_name)
        except Exception:
            mi = None
        if mi:
            seen = set()
            for c in mi.callouts:
                if c.region.lower() == "spawn" or c.label in seen:
                    continue
                seen.add(c.label)
                u, v = mi.to_uv(c.x, c.y)
                mp["callouts"].append({"label": c.label, "u": round(u, 4), "v": round(v, 4)})
            mp["m"] = round(abs(mi.x_mult) * 100 * 1000, 3) or 7.0
        return {"agents": out_agents, "map": mp}

    # ------------------------------------------------------------------ helpers
    def get_strat(tid: int, sid: int):
        t = get_team(tid)
        s = store.strat(sid)
        if s is None or s["team_id"] != tid:
            abort(404)
        return t, s

    def maps_for(t) -> list[str]:
        return sorted(set(t.map_list) | set(known_maps))

    # ------------------------------------------------------------------ pages
    @app.route("/teams/<int:tid>/strats", methods=["GET", "POST"])
    def team_strats(tid: int):
        t = get_team(tid)
        if request.method == "POST":
            f = request.form
            m = f.get("map", "")
            side = f.get("side", "attack")
            if m not in maps_for(t) or side not in SIDES:
                abort(400)
            name = (f.get("name") or "").strip() or f"{m} {side}"
            data = {"steps": [{"name": "Setup", "items": []}], "notes": ""}
            plan_ref = f.get("from_plan", "")
            if plan_ref:                              # "Draw it" from a game plan: its steps become the notes
                plans = sr.read_plans(tid, m) or {}
                try:
                    p = plans.get("plans", [])[int(plan_ref)]
                except (ValueError, IndexError):
                    p = None
                if p:
                    name = p.get("title") or name
                    side = p.get("side") if p.get("side") in SIDES else side
                    lines = [p.get("idea", "")] + [f"{s['player']}: {s['what']}" for s in p.get("steps", []) if s.get("what")]
                    if p.get("timing"):
                        lines.append(f"Timing: {p['timing']}")
                    lines += [f"If: {x}" for x in p.get("if_then", [])]
                    data["notes"] = "\n".join(x for x in lines if x)
                    data["steps"] = [{"name": "Setup", "items": []}, {"name": "Execute", "items": []}]
            sid = store.create_strat(tid, g.user.id, m, side, name, data)
            return redirect(url_for("strat_edit", tid=tid, sid=sid))
        strats = store.strats(tid)
        by_map: dict[str, list] = {}
        for s in strats:
            by_map.setdefault(s["map"], []).append(s)
        return render_template("team_strats.html", t=t, tab="strats", by_map=by_map, maps=maps_for(t),
                               sel=request.args.get("map", ""), premier_status=sr.status(f"premier:{tid}"))

    @app.get("/teams/<int:tid>/strats/<int:sid>")
    def strat_edit(tid: int, sid: int):
        t, s = get_strat(tid, sid)
        lineup = []
        for m in t.member_list:
            p = store.profile(m["pid"])
            if p and m.get("kind") == "starter":
                lineup.append(p.name)
        boot = {"strat": {k: s[k] for k in ("id", "name", "map", "side", "data", "updated_at")},
                "assets": assets(s["map"]), "lineup": lineup,
                "save_url": url_for("strat_save", tid=tid, sid=sid),
                "discord_url": url_for("strat_discord", tid=tid, sid=sid)
                if (t.discord_info.get("prep_url") or t.discord_info.get("focus_url")) else None,
                "map_image": url_for("map_image", name=s["map"]),
                "lineups": [{"agent": x["agent"], "ability": x["ability"], "title": x["title"], "url": x["url"], "side": x["side"]}
                            for x in store.lineups(tid, s["map"])],
                "lineups_url": url_for("team_lineups", tid=tid, map=s["map"]),
                "agent_icon": url_for("agent_icon", name="__A__"), "ability_icon": url_for("ability_icon", agent="__A__", slot="__S__")}
        can_delete = g.team_owner or s["author_id"] == g.user.id
        return render_template("strat_edit.html", t=t, s=s, tab="strats", can_delete=can_delete,
                               boot=json.dumps(boot).replace("</", "<\\/"), premier_status=None)

    @app.post("/api/teams/<int:tid>/strats/<int:sid>")
    def strat_save(tid: int, sid: int):
        get_strat(tid, sid)
        body = request.get_json(silent=True)                 # JSON only: a cross-site form can't send this
        if not isinstance(body, dict):
            return jsonify(error="expected JSON"), 400
        fields = {}
        if "name" in body:
            fields["name"] = str(body["name"]).strip()[:80] or "Untitled"
        if body.get("side") in SIDES:
            fields["side"] = body["side"]
        if "data" in body:
            data = body["data"]
            if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
                return jsonify(error="data.steps must be a non-empty list"), 400
            data = clean_board(data)
            if not data["steps"]:
                return jsonify(error="data.steps must be a non-empty list"), 400
            raw = json.dumps(data)
            if len(raw) > MAX_BOARD_BYTES:
                return jsonify(error="board too big"), 413
            fields["data"] = raw
        store.update_strat(sid, g.user.id, **fields)
        return jsonify(ok=True, saved_at=time.strftime("%H:%M:%S"))

    @app.post("/teams/<int:tid>/strats/<int:sid>/delete")
    def strat_delete(tid: int, sid: int):
        t, s = get_strat(tid, sid)
        if not (g.team_owner or s["author_id"] == g.user.id):
            abort(403)
        store.delete_strat(sid)
        flash(f"Deleted {s['name']}.", "ok")
        return redirect(url_for("team_strats", tid=tid, map=s["map"]))

    @app.post("/teams/<int:tid>/strats/<int:sid>/copy")
    def strat_copy(tid: int, sid: int):
        t, s = get_strat(tid, sid)
        nid = store.create_strat(tid, g.user.id, s["map"], s["side"], f"{s['name']} (copy)", s["data"])
        return redirect(url_for("strat_edit", tid=tid, sid=nid))

    @app.post("/api/teams/<int:tid>/strats/<int:sid>/discord")
    def strat_discord(tid: int, sid: int):
        from ..discord import post_file
        t, s = get_strat(tid, sid)
        url = t.discord_info.get("prep_url") or t.discord_info.get("focus_url")
        f = request.files.get("png")
        if not url:
            return jsonify(error="no Discord webhook set for this team"), 400
        if f is None:
            return jsonify(error="no image"), 400
        data = f.read(MAX_PNG_BYTES + 1)
        if len(data) > MAX_PNG_BYTES or not data.startswith(b"\x89PNG"):
            return jsonify(error="not a PNG or too big"), 400
        step = re.sub(r"[^\w .-]", "", request.form.get("step", ""))[:40]
        notes = (s["data"].get("notes") or "").strip()
        text = f"**{s['name']}** · {s['map']} {s['side']}{' · ' + step if step else ''}"
        if notes:
            text += "\n" + notes[:1500]
        try:
            post_file(url, text, f"{re.sub(r'[^A-Za-z0-9]+', '-', s['name'])[:40] or 'strat'}.png", data)
        except Exception as e:
            return jsonify(error=str(e)), 502
        return jsonify(ok=True)
