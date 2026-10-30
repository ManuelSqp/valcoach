"""Lineups library (part of the strat book): one entry per smoke / molly / dart lineup with a clip link,
per team and map. Everyone in the team can add; the author and the team owner can delete."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from flask import abort, flash, g, redirect, render_template, request, url_for

from ..maps import AgentRegistry
from ..stats import roles

SIDES = ("", "attack", "defense")
SITES = ("", "A", "B", "C", "Mid")


def clip_info(url: str) -> dict | None:
    """Only http(s) links; YouTube gets a thumbnail (the ID is checked, nothing else from the URL is used)."""
    try:
        u = urlsplit((url or "").strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    host = u.netloc.lower().split(":")[0]
    vid = None
    if host in ("youtu.be",):
        vid = u.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [""])[0]
        elif u.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = u.path.split("/")[2] if len(u.path.split("/")) > 2 else None
    if vid and not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid):
        vid = None
    return {"url": u.geturl(), "host": host.removeprefix("www."),
            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else None}


def register(app, store, get_team, known_maps: list[str]) -> None:
    cache_dir = store.data_dir / "cache"
    agents_reg = AgentRegistry(cache_dir)

    def abilities() -> dict[str, list[str]]:
        try:
            ags = agents_reg.load()
        except Exception:
            ags = []
        out = {a["name"]: [ab["name"] for ab in a.get("abilities", [])] for a in ags if a.get("name")}
        for n in roles.all_agents():
            out.setdefault(n, [])
        return dict(sorted(out.items()))

    def maps_for(t) -> list[str]:
        return list(t.map_list) or sorted(known_maps)

    @app.route("/teams/<int:tid>/lineups", methods=["GET", "POST"])
    def team_lineups(tid: int):
        t = get_team(tid)
        maps = maps_for(t)
        ab = abilities()
        if request.method == "POST":
            f = request.form
            m, agent = f.get("map", ""), f.get("agent", "")
            title = (f.get("title") or "").strip()[:80]
            if m not in maps and m not in known_maps:
                abort(400)
            if agent not in ab or not title:
                flash("Pick an agent and give the lineup a name.", "error")
                return redirect(url_for("team_lineups", tid=tid, map=m))
            url = (f.get("url") or "").strip()
            clip = clip_info(url) if url else None
            if url and not clip:
                flash("The clip link must start with https:// (YouTube, Medal, Outplayed, a Discord link …).", "error")
                return redirect(url_for("team_lineups", tid=tid, map=m))
            ability = f.get("ability", "")
            store.add_lineup(tid, g.user.id, map=m, agent=agent, ability=ability if ability in ab[agent] else "",
                             side=f.get("side") if f.get("side") in SIDES else "", site=f.get("site") if f.get("site") in SITES else "",
                             title=title, url=clip["url"][:500] if clip else "", notes=(f.get("notes") or "").strip()[:500])
            flash(f"Added {title}.", "ok")
            return redirect(url_for("team_lineups", tid=tid, map=m, agent=agent))
        sel = request.args.get("map") or ""
        if sel not in maps:
            fn = app.extensions["valcoach"].get("week_map")
            wm = fn(t) if fn and t.premier_info.get("tag") else None
            sel = wm if wm in maps else (maps[0] if maps else "")
        rows = store.lineups(tid, sel) if sel else []
        counts = {}
        for r in store.lineups(tid):
            counts[r["map"]] = counts.get(r["map"], 0) + 1
        agent = request.args.get("agent", "")
        side = request.args.get("side", "")
        shown = [r for r in rows if (not agent or r["agent"] == agent) and (not side or r["side"] == side)]
        for r in shown:
            r["clip"] = clip_info(r["url"]) if r["url"] else None
            r["can_delete"] = bool(g.team_owner or r["author_id"] == g.user.id)
        groups: dict[str, list] = {}
        for r in shown:
            groups.setdefault(r["agent"], []).append(r)
        return render_template("team_lineups.html", t=t, tab="strats", maps=maps, sel=sel, counts=counts, groups=groups,
                               agents_with=sorted({r["agent"] for r in rows}), agent=agent, side=side, abilities=ab,
                               sides=SIDES, sites=SITES, premier_status=None)

    @app.post("/teams/<int:tid>/lineups/<int:lid>/delete")
    def lineup_delete(tid: int, lid: int):
        get_team(tid)
        r = store.lineup(lid)
        if r is None or r["team_id"] != tid:
            abort(404)
        if not (g.team_owner or r["author_id"] == g.user.id):
            abort(403)
        store.delete_lineup(lid)
        flash(f"Deleted {r['title']}.", "ok")
        return redirect(url_for("team_lineups", tid=tid, map=r["map"]))
