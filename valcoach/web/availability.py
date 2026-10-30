"""Who can play on which match day (Premier tab › Availability), and who could sub in.

Match days are the days set under "Brief before each match" on the Premier tab. Each player
marks yes / maybe / no for the next two weeks (the team owner can set it for anyone). For every
day, the planned five come from the "main" draft for that day's map, else the suggested comp;
if one of them can't play, the available players are ranked by how much they play that agent
(and that role)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import abort, g, jsonify, render_template, request

from ..stats import roles
from ..stats.premier_schedule import current

STATES = ("yes", "maybe", "no")
DAYS_AHEAD = 14
DEFAULT_DAYS = [5, 6]          # Sat, Sun until match days are set
WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def map_on(sched: dict | None, day: str) -> tuple[str | None, bool]:
    """(the map played that day, is it the playoffs)."""
    if not sched:
        return None, False
    for w in sched.get("weeks") or []:
        if w["starts"] <= day <= w["ends"]:
            return w["map"], False
    po = sched.get("playoffs") or {}
    if po.get("starts") and po["starts"] <= day <= (po.get("ends") or po["starts"]):
        return None, True
    return None, False


def match_days(weekdays: list[int], sched: dict | None, today: date | None = None, ahead: int = DAYS_AHEAD) -> list[dict]:
    today = today or datetime.now().date()
    wd = weekdays or DEFAULT_DAYS
    out = []
    for i in range(ahead):
        d = today + timedelta(days=i)
        if d.weekday() not in wd:
            continue
        iso = d.isoformat()
        m, po = map_on(sched, iso)
        out.append({"day": iso, "label": f"{WEEKDAY[d.weekday()]} {d.day:02d}.{d.month:02d}.", "map": m, "playoffs": po,
                    "today": i == 0})
    return out


def agent_games(rows: list[dict], agent: str) -> tuple[int, float | None]:
    rs = [r for r in rows if r.get("agent") == agent]
    return len(rs), (sum(r.get("won", 0) for r in rs) / len(rs) if rs else None)


def role_games(rows: list[dict], role: str) -> int:
    return sum(1 for r in rows if roles.role_of(r.get("agent", "")) == role)


def sub_options(agent: str | None, candidates: list[dict], rows_by: dict[int, list[dict]]) -> list[dict]:
    """Rank available players for an open slot: games on that agent first, then on its role."""
    role = roles.role_of(agent) if agent else None
    out = []
    for c in candidates:
        rows = rows_by.get(c["pid"], [])
        n, wr = agent_games(rows, agent) if agent else (0, None)
        rn = role_games(rows, role) if role else 0
        if agent and n:
            why = f"plays {agent} ({n} games{f', {wr:.0%} won' if wr is not None else ''})"
        elif role and rn:
            why = f"plays {role}s ({rn} games), not {agent}"
        elif agent:
            why = f"hasn't played {agent} or {role}s"
        else:
            why = f"{len(rows)} games"
        out.append({**c, "agent_games": n, "role_games": rn, "why": why,
                    "score": n * 3 + rn + (0.5 if c["state"] == "yes" else 0)})
    out.sort(key=lambda x: -x["score"])
    return out


def day_summary(day: dict, members: list[dict], marks: dict, plan: list[dict], rows_by: dict[int, list[dict]]) -> dict:
    """members: [{pid, name, kind}] · plan: [{pid, agent}] (the five planned for that map)."""
    state = {m["pid"]: (marks.get((m["pid"], day["day"])) or {}).get("state") for m in members}
    yes = [m for m in members if state[m["pid"]] == "yes"]
    maybe = [m for m in members if state[m["pid"]] == "maybe"]
    unknown = [m for m in members if state[m["pid"]] is None]
    byid = {m["pid"]: m for m in members}
    planned = {p["pid"] for p in plan}
    out_slots = []
    for p in plan:
        st = state.get(p["pid"])
        if st == "no":
            cands = [{**m, "state": state[m["pid"]]} for m in members
                     if m["pid"] not in planned and state[m["pid"]] in ("yes", "maybe")]
            out_slots.append({"pid": p["pid"], "name": byid.get(p["pid"], {}).get("name", "?"), "agent": p.get("agent"),
                              "subs": sub_options(p.get("agent"), cands, rows_by)[:3]})
    n_yes = len(yes)
    level = "ok" if n_yes >= 5 else ("maybe" if n_yes + len(maybe) >= 5 else "short")
    return {**day, "yes": yes, "maybe": maybe, "unknown": unknown, "no": [m for m in members if state[m["pid"]] == "no"],
            "level": level, "missing": out_slots, "state": state}


def summary_line(s: dict) -> str:
    """One line for the brief / Discord."""
    parts = [f"{len(s['yes'])}/5 confirmed"]
    if s["maybe"]:
        parts.append("maybe: " + ", ".join(m["name"] for m in s["maybe"]))
    for slot in s["missing"]:
        sub = slot["subs"][0] if slot["subs"] else None
        parts.append(f"{slot['name']} can't play" + (f" ({slot['agent']})" if slot.get("agent") else "") +
                     (f" → {sub['name']} {sub['why']}" if sub else " → nobody free"))
    if s["unknown"]:
        parts.append("no answer: " + ", ".join(m["name"] for m in s["unknown"]))
    return " · ".join(parts)


def register(app, store, get_team, h: dict):
    """h: brief_cfg(t), schedule_for(t), team_context(t), build(t). Returns summary_for(t, day) -> dict | None."""

    def members_of(t) -> tuple[list[dict], dict]:
        c = h["team_context"](t)
        ms = [{"pid": m["pid"], "name": c["byid"][m["pid"]].name, "kind": m.get("kind", "sub"), "user_id": m.get("user_id")}
              for m in c["members"] if m.get("kind") in ("starter", "sub")]
        ms.sort(key=lambda m: (m["kind"] != "starter", m["name"].lower()))
        return ms, c["rows_by"]

    def plan_for(t, map_name: str | None, members: list[dict]) -> tuple[list[dict], str]:
        names = {m["name"]: m["pid"] for m in members}
        pids = {m["pid"] for m in members}
        if map_name:
            main = [d for d in store.drafts(t.id, map_name) if (d["data"] or {}).get("status") == "main"]
            if main:
                slots = [s for s in main[0]["data"].get("slots", []) if s.get("pid") in pids]
                if slots:
                    return [{"pid": s["pid"], "agent": s.get("agent") or None} for s in slots], f"draft “{main[0]['name']}”"
            try:
                comp = next((c for c in (h["build"](t)["comps"].get(map_name) or []) if c.get("ok")), None)
            except Exception:
                comp = None
            if comp:
                return [{"pid": names[pk["player"]], "agent": pk["agent"]} for pk in comp["picks"] if pk["player"] in names], "suggested comp"
        return [{"pid": m["pid"], "agent": None} for m in members if m["kind"] == "starter"], "starters"

    def schedule(t):
        try:
            return h["schedule_for"](t)
        except Exception:
            return None

    def summaries(t, days: list[dict]) -> tuple[list[dict], list[dict], dict]:
        members, rows_by = members_of(t)
        marks = store.availability(t.id, [d["day"] for d in days])
        plans: dict = {}
        out = []
        for d in days:
            if d["map"] not in plans:
                plans[d["map"]] = plan_for(t, d["map"], members)
            plan, src = plans[d["map"]]
            s = day_summary(d, members, marks, plan, rows_by)
            s["plan_source"] = src
            s["plan"] = [{"name": next((m["name"] for m in members if m["pid"] == p["pid"]), "?"), "agent": p["agent"]} for p in plan]
            out.append(s)
        return out, members, marks

    def summary_for(t, day: date | None = None) -> dict | None:
        """The summary for one day (today by default), if it's a match day."""
        day = day or datetime.now().date()
        cfg = h["brief_cfg"](t)
        if day.weekday() not in (cfg.get("days") or DEFAULT_DAYS):
            return None
        m, po = map_on(schedule(t), day.isoformat())
        d = {"day": day.isoformat(), "label": f"{WEEKDAY[day.weekday()]} {day.day:02d}.{day.month:02d}.", "map": m, "playoffs": po, "today": True}
        return summaries(t, [d])[0][0]

    def next_summary(t) -> dict | None:
        days = match_days(h["brief_cfg"](t).get("days") or [], schedule(t))
        return summaries(t, days[:1])[0][0] if days else None

    def can_edit(t, pid: int, members: list[dict]) -> bool:
        if g.team_owner:
            return True
        return any(m["pid"] == pid and m.get("user_id") == g.user.id for m in members)

    @app.get("/teams/<int:tid>/premier/availability")
    def team_availability(tid: int):
        t = get_team(tid)
        cfg = h["brief_cfg"](t)
        days = match_days(cfg.get("days") or [], schedule(t))
        sums, members, marks = summaries(t, days)
        editable = {m["pid"]: can_edit(t, m["pid"], members) for m in members}
        notes = {f"{pid}|{day}": v["note"] for (pid, day), v in marks.items() if v.get("note")}
        return render_template("premier_availability.html", t=t, tab="premier", tab2="availability", premier_status=None,
                               pi=t.premier_info, days=days, sums=sums, members=members, editable=editable, notes=notes,
                               days_set=bool(cfg.get("days")), weekday=WEEKDAY,
                               save_url=f"/api/teams/{tid}/availability")

    @app.post("/api/teams/<int:tid>/availability")
    def team_availability_save(tid: int):
        t = get_team(tid)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="expected JSON"), 400
        try:
            pid = int(body.get("pid"))
            day = date.fromisoformat(str(body.get("day"))).isoformat()
        except (TypeError, ValueError):
            return jsonify(error="bad player or day"), 400
        members, _ = members_of(t)
        if not any(m["pid"] == pid for m in members):
            abort(404)
        if not can_edit(t, pid, members):
            return jsonify(error="you can only set your own days (link yourself to your player first)"), 403
        state = body.get("state")
        note = str(body.get("note") or "").strip()[:80]
        store.set_availability(tid, pid, day, state if state in STATES else "", note, g.user.id)
        store.prune_availability((datetime.now().date() - timedelta(days=30)).isoformat())
        return jsonify(ok=True)

    return summary_for, next_summary
