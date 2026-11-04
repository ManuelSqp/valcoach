"""The home page: what's up today, for you and your teams, in one place.

Per team: the next match day and who's playing (and whether you answered), this week's map and the
brief, your focus. For you: today's warm-up, a quiz waiting, rank change, the newest report. Jobs that
run or failed. What changed since your last visit (strats, drafts, notes, Premier reviews by others)."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _done_today(store, pid: int) -> tuple[bool, int]:
    try:
        done = set(json.loads((store.profile_dir(pid) / "stats" / "training.json").read_text()).get("done", []))
    except (OSError, ValueError):
        done = set()
    today = date.today()
    d = today if today.isoformat() in done else today - timedelta(days=1)
    n = 0
    while d.isoformat() in done:
        n += 1
        d -= timedelta(days=1)
    return today.isoformat() in done, n


def today(app, store, sr, user, since: float) -> dict:
    ext = app.extensions["valcoach"]
    out: dict = {"teams": [], "me": None, "jobs": [], "new": []}
    my_profiles = store.profiles(user.id)
    my_pids = {p.id for p in my_profiles}
    teams = store.teams_for_user(user.id)
    # ---- teams
    for t in teams:
        mine = next((m for m in t.member_list if m.get("user_id") == user.id), None)
        if mine is None and t.owner_id == user.id and user.display_name:
            p = next((p for p in my_profiles if p.riot_id.lower() == user.display_name.lower()), None)
            mine = next((m for m in t.member_list if p and m["pid"] == p.id), None)
        x = {"t": t, "mine": mine, "map": None, "avail": None, "my_answer": None, "focus": None, "own": None, "live": False}
        try:
            x["live"] = bool(ext["match_window"](t)) if "match_window" in ext else False
        except Exception:
            pass
        try:
            x["map"] = ext["week_map"](t) if "week_map" in ext else None
        except Exception:
            x["map"] = None
        try:
            a = ext["next_avail"](t) if "next_avail" in ext else None
        except Exception:
            a = None
        if a:
            x["avail"] = a
            if mine:
                x["my_answer"] = a["state"].get(mine["pid"])
        if mine:
            x["own"] = sr.read_own_focus(mine["pid"])
        x["focus"] = sr.my_focus(t, user.id)
        x["warm"] = None
        if x["live"] and "aim" in ext:          # match day: your warm-up, until it's ticked off
            try:
                w = ext["aim"]["card"](t, user.id)
                x["warm"] = w if w and not w["done"] else None
            except Exception:
                x["warm"] = None
        out["teams"].append(x)
        # what's new since the last visit (by others)
        for s in store.strats(t.id):
            if _ts(s["updated_at"]) > since and s.get("author") and s["author"] not in (user.username, user.display_name):
                out["new"].append({"t": _ts(s["updated_at"]), "kind": "strat", "text": f"{s['author']} changed the strat “{s['name']}” ({s['map']})",
                                   "url": ("strat_edit", {"tid": t.id, "sid": s["id"]}), "team": t.name})
        for d in store.drafts(t.id):
            if _ts(d["updated_at"]) > since and d.get("updated_by") not in (None, user.id):
                out["new"].append({"t": _ts(d["updated_at"]), "kind": "draft", "text": f"{d.get('editor') or 'Someone'} changed the draft “{d['name']}” ({d['map']})",
                                   "url": ("team_drafts", {"tid": t.id, "map": d["map"], "d": d["id"]}), "team": t.name})
        for n in store.team_notes(t.id)[:20]:
            if _ts(n["created_at"]) > since and n.get("author_id") != user.id:
                out["new"].append({"t": _ts(n["created_at"]), "kind": "note", "text": f"{n.get('author') or 'Someone'}: {n['text'][:90]}",
                                   "url": ("team_notes", {"tid": t.id}), "team": t.name})
        pj = ext.get("premier")
        if pj is not None:
            for r in pj.reviews(t.id)[:10]:
                if float(r.get("created") or 0) > since:
                    out["new"].append({"t": float(r["created"]), "kind": "review",
                                       "text": f"Review: {'won' if r.get('won') else 'lost'} {r.get('score')} on {r.get('map')} vs {r.get('opponent')}",
                                       "url": ("team_review_page", {"tid": t.id, "match_id": r["match_id"]}), "team": t.name})
    out["new"].sort(key=lambda x: -x["t"])
    out["new"] = out["new"][:12]
    # ---- me: your own player (the one named like your in-game name, else the first)
    me = next((p for p in my_profiles if user.display_name and p.riot_id.lower() == user.display_name.lower()), my_profiles[0] if my_profiles else None)
    if me is not None:
        from ..stats import rank as rk
        done, streak = _done_today(store, me.id)
        q = sr.read_quiz(me.id)
        played = {r.get("created") for r in q.get("results") or []}
        pts, src = rk.series(rk.RankStore(sr.rank_path(me.id)).load(), sr.games(me.id).rows())
        jobs = [j for j in store.jobs(me.id, 5) if j.status == "done"]
        out["me"] = {"p": me, "warmup_done": done, "streak": streak, "rank": rk.summary(pts), "rank_src": src,
                     "quiz": len(q.get("questions") or []) if q.get("questions") and q.get("created") not in played else 0,
                     "has_quiz": bool(q.get("questions")), "report": jobs[0] if jobs else None,
                     "games": len(sr.games(me.id).load()["games"])}
    # ---- jobs: running now, or failed in the last day
    names = {"import": "history import", "tips": "playstyle tips", "premier": "Premier roster", "plans": "game plans",
             "focus": "weekly focus", "post": "Discord post", "scout": "scouting", "review": "match reviews",
             "schedule": "season schedule", "watch": "what to watch", "quiz": "quiz"}
    team_kinds = {"premier", "plans", "focus", "post", "scout", "review", "schedule"}
    tids = {t.id for t in teams}
    pname = {p.id: p.name for p in my_profiles}
    now = time.time()
    for key, st in sr.states().items():
        kind, _, rest = key.partition(":")
        ident = rest.split(":")[0]
        if not ident.isdigit():
            continue
        ident = int(ident)
        if (kind in team_kinds and ident not in tids) or (kind not in team_kinds and ident not in my_pids):
            continue
        if st["status"] in ("queued", "running") or (st["status"] == "error" and now - st["t"] < 86400):
            who = next((t.name for t in teams if t.id == ident), "") if kind in team_kinds else pname.get(ident, "")
            out["jobs"].append({"what": names.get(kind, kind), "who": who, "status": st["status"], "error": st.get("error", ""),
                                "age": int(now - st["t"])})
    for j in store.jobs_for_owner(user.id, 10):
        if j.status in ("queued", "running") or (j.status == "error" and now - _ts(j.created_at) < 86400):
            out["jobs"].append({"what": f"coaching {j.map or 'a match'}", "who": pname.get(j.profile_id, ""), "status": j.status,
                                "error": (j.error or "")[:140], "age": int(now - _ts(j.created_at)), "jid": j.id})
    return out
