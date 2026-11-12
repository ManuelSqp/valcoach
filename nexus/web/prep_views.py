"""Team › Match day › Replay scouting (4.18): what the replay files on the server show about a team's habits.

Pick an opponent you played (from the stored replays of matches where 2+ of your team played; the same
roster met again, or scrims, is grouped) or your own team ("how readable are we"), a map and a moment in
the round: the usual setup, the spots taken, the utility thrown and where they plant (stats/replayprep.py)."""
from __future__ import annotations

from flask import render_template, request, url_for

from .. import replayfile
from ..maps import AgentRegistry, MapRegistry
from ..stats import replayprep as rp

TYPE_COL = {"smoke": "#aab3c2", "wall": "#7dd3fc", "slow": "#7fc4ff", "damage": "#ff8a3d", "trap": "#f2b84b",
            "recon": "#c58cff", "orb": "#c58cff", "flash": "#ffffff"}
TYPE_NAME = {"smoke": "Smoke", "wall": "Wall", "slow": "Slow", "damage": "Molly / damage", "trap": "Trap",
             "recon": "Recon", "orb": "Orb", "flash": "Flash"}


def register(app, store, sr, get_team) -> None:
    cache = store.data_dir / "cache"
    replays = store.data_dir / "replays"

    def our_puuids(t) -> set[str]:
        out = set()
        for m in t.member_list:
            pu = m.get("puuid") or (sr.games(m["pid"]).load() or {}).get("puuid")
            if pu:
                out.add(pu)
        return out

    def agent_names() -> dict[str, str]:
        try:
            return {a["dev"]: a["name"] for a in AgentRegistry(cache).load() if a.get("dev")}
        except Exception:
            return {}

    def team_extracts(t, ours: set[str]) -> dict[str, dict]:
        """Extracts of every stored replay in which 2+ of the team played (the members' matches and every
        file on the server)."""
        out: dict[str, dict] = {}
        reg, names = None, None
        mids = set(replayfile.stored(replays))
        for m in t.member_list:
            for r in sr.games(m["pid"]).rows():
                mid = str(r.get("match_id") or "").lower()
                if mid and mid not in mids and r.get("source") == "full" and replayfile.has_replay(replays, mid):
                    mids.add(mid)
        for mid in sorted(mids):
            if reg is None:
                reg, names = MapRegistry(cache), agent_names()
            ex = rp.for_match(replays, cache, mid, reg, names)
            if not ex or not ex.get("ok"):
                continue
            if len(set(ex.get("roster") or {}) & ours) >= 2:
                out[mid] = ex
        return out

    def scouting(t, who: str, at: int = 20) -> dict:
        """{opps, sel, who, analysis, n} for a team and the picked roster ("us" = the team itself)."""
        ours = our_puuids(t)
        ex = team_extracts(t, ours) if ours else {}
        labels = {}
        pj = app.extensions["nexus"].get("premier")
        if pj:
            labels = {r["match_id"]: r.get("opponent") for r in pj.reviews(t.id) if r.get("opponent")}
        opps = rp.opponents(ex, ours, labels)
        sel = next((o for o in opps if o["key"] == who), None)
        if sel is None and who != "us":
            sel = opps[0] if opps else None
            who = sel["key"] if sel else "us"
        roster = set(sel["puuids"]) if sel else ours
        return {"opps": opps, "sel": sel, "who": who, "a": rp.analyse(ex, roster, at) if ex else {}, "n": len(ex)}

    app.extensions["nexus"]["replay_scouting"] = scouting
    app.extensions["nexus"]["team_replays"] = lambda t: (team_extracts(t, our_puuids(t)), our_puuids(t))     # 4.20

    def replays_of(t, puuids, map_name: str | None = None, sc: dict | None = None) -> dict | None:
        """4.21: what the replay files show of a known team (3+ of its players in a roster you played), for the
        match-day screen, the brief and the scouting page. {key, label, matches, maps, map, hints, url} or None."""
        puuids = {p for p in puuids or () if p}
        if len(puuids) < 3:
            return None
        sc = sc or scouting(t, "us")
        o = next((o for o in sc["opps"] if len(set(o["puuids"]) & puuids) >= 3), None)
        if o is None:
            return None
        a = rp.analyse({mid: ex for mid, ex in team_extracts(t, our_puuids(t)).items() if mid in o["matches"]}, set(o["puuids"]))
        mp = map_name if map_name in a else None
        return {"key": o["key"], "label": o["label"], "matches": len(o["matches"]), "maps": o["maps"], "map": mp,
                "hints": rp.hints({mp: a[mp]} if mp else a, min_rounds=3)[:6],
                "url": url_for("team_replay_prep", tid=t.id, who=o["key"], map=mp or "")}

    app.extensions["nexus"]["replays_of"] = replays_of
    app.extensions["nexus"]["replay_scouting_all"] = lambda t: scouting(t, "us")

    @app.get("/teams/<int:tid>/replay-scouting")
    def team_replay_prep(tid: int):
        t = get_team(tid)
        try:
            at = int(request.args.get("at", 20))
        except ValueError:
            at = 20
        at = at if at in rp.TIMES else 20
        sc = scouting(t, request.args.get("who", ""), at)
        a = sc["a"]
        maps = sorted(a, key=lambda m: -a[m]["matches"])
        mp = request.args.get("map", "")
        mp = mp if mp in a else (maps[0] if maps else "")
        return render_template("team_replay_prep.html", t=t, tab="replay_prep", premier_status=None, opps=sc["opps"],
                               who=sc["who"], sel=sc["sel"], a=a, maps=maps, mp=mp, d=a.get(mp) or {}, at=at, times=rp.TIMES,
                               hints=[h for h in rp.hints({mp: a[mp]}) if h] if mp else [], n_replays=sc["n"],
                               type_col=TYPE_COL, type_name=TYPE_NAME,
                               map_img=url_for("map_image", name=mp) if mp else "",
                               plans_status=app.extensions["nexus"]["stats"].status(f"plans:{tid}"))
