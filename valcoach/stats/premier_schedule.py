"""The Premier season schedule: which map is played in which week, and when the playoffs are.

Read from HenrikDev's /valorant/v1/premier/seasons/{region} (undocumented shape: a season has
`events`, each LEAGUE event is one week with its dates, per conference in `conference_schedules`,
and `map_selection.maps`; the TOURNAMENT event is the playoffs). If the API gives no maps, the
stage below is used (from Riot's announcement, Oct–Dec 2026). Queue windows differ by zone; the
dates here are the week, not your queue window.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Premier stage V26A6 (Riot's schedule graphic, Oct–Dec 2026)
BUILTIN = {
    "id": "V26A6", "source": "built-in (Riot's stage V26A6 announcement)",
    "weeks": [
        {"week": 1, "map": "Bind", "starts": "2026-10-21", "ends": "2026-10-25"},
        {"week": 2, "map": "Corrode", "starts": "2026-10-28", "ends": "2026-11-01"},
        {"week": 3, "map": "Sunset", "starts": "2026-11-04", "ends": "2026-11-08"},
        {"week": 4, "map": "Haven", "starts": "2026-11-11", "ends": "2026-11-15"},
        {"week": 5, "map": "Summit", "starts": "2026-11-18", "ends": "2026-11-22"},
        {"week": 6, "map": "Abyss", "starts": "2026-11-25", "ends": "2026-11-29"},
        {"week": 7, "map": "Lotus", "starts": "2026-12-02", "ends": "2026-12-05"},
    ],
    "playoffs": {"starts": "2026-12-06", "ends": "2026-12-06", "maps": []},
}


def _ts(s) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _map_names(ev: dict) -> list[str]:
    ms = (ev.get("map_selection") or {}).get("maps") if isinstance(ev.get("map_selection"), dict) else None
    out = []
    for m in ms or []:
        n = m.get("name") if isinstance(m, dict) else m
        if isinstance(n, str) and n:
            out.append(n)
    return out


def from_api(seasons, conference: str | None = None, now: datetime | None = None) -> dict | None:
    """Schedule of the current (or next) season from the API data, or None if it has no weekly maps."""
    now = now or datetime.now(timezone.utc)
    if isinstance(seasons, dict):
        seasons = seasons.get("data", [seasons])
    if not isinstance(seasons, list):
        return None
    best = None
    for s in seasons:
        if not isinstance(s, dict):
            continue
        evs = [e for e in s.get("events") or [] if isinstance(e, dict)]
        weeks, playoffs = [], None
        for e in evs:
            st, en = _ts(e.get("starts_at")), _ts(e.get("ends_at"))
            for cs in e.get("conference_schedules") or []:      # your conference's own window, if listed
                if conference and isinstance(cs, dict) and str(cs.get("conference", "")).upper() == str(conference).upper():
                    st, en = _ts(cs.get("starts_at")) or st, _ts(cs.get("ends_at")) or en
            maps = _map_names(e)
            kind = str(e.get("type", "")).upper()
            if kind == "TOURNAMENT" or (len(maps) > 1 and kind != "LEAGUE"):
                playoffs = {"starts": st.date().isoformat() if st else "", "ends": en.date().isoformat() if en else "", "maps": maps}
            elif len(maps) == 1 and st:
                weeks.append({"map": maps[0], "starts": st.date().isoformat(), "ends": (en or st).date().isoformat()})
        if not weeks:
            continue
        weeks.sort(key=lambda w: w["starts"])
        for i, w in enumerate(weeks, 1):
            w["week"] = i
        sched = {"id": str(s.get("id") or ""), "source": "Premier API", "weeks": weeks, "playoffs": playoffs}
        end = _ts(weeks[-1]["ends"]) or now
        start = _ts(weeks[0]["starts"]) or now
        # the season we're in, else the next one, else the latest
        rank = 0 if start <= now <= end.replace(hour=23, minute=59) else (1 if start > now else 2)
        key = (rank, abs((start - now).total_seconds()))
        if best is None or key < best[0]:
            best = (key, sched)
    return best[1] if best else None


def schedule(seasons=None, conference: str | None = None, now: datetime | None = None) -> dict:
    """The API's schedule when it has one, else the built-in stage."""
    return from_api(seasons, conference, now) or BUILTIN


def current(sched: dict, now: datetime | None = None) -> dict:
    """{"week": the week we're in (or None), "next": the next week, "pool": maps in week order}."""
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    weeks = sched.get("weeks") or []
    cur = next((w for w in weeks if w["starts"] <= today <= w["ends"]), None)
    nxt = next((w for w in weeks if w["starts"] > today), None)
    upcoming = False
    if cur is None and nxt is not None:
        # between two weeks (e.g. Monday/Tuesday): prepare for the coming week's map
        days = (datetime.fromisoformat(nxt["starts"]).date() - datetime.fromisoformat(today).date()).days
        if days <= 3:
            cur, upcoming = nxt, True
    pool = []
    for w in weeks:
        if w["map"] not in pool:
            pool.append(w["map"])
    po = sched.get("playoffs") or {}
    in_playoffs = bool(po.get("starts")) and po["starts"] <= today <= (po.get("ends") or po["starts"])
    return {"week": cur, "upcoming": upcoming, "next": nxt if nxt is not cur else next((w for w in weeks if w["starts"] > cur["starts"]), None) if cur else nxt,
            "pool": pool, "playoffs": po, "in_playoffs": in_playoffs}
