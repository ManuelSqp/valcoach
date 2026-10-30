"""Background work for Premier: scouting the teams of your division (or one team by name),
reviewing your new Premier matches, and the pre-match brief.

Uses the StatsRunner's single worker and status keys (`scout:<tid>`, `review:<tid>`); results
are JSON files under data/teams/<tid>/ (scout/, reviews/)."""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from ..parse import parse_match
from ..stats.scouting import side_in_match, summarize
from .statsjobs import StatsRunner, slug

SCOUT_MATCHES = 8          # recent Premier matches read per scouted team (cached forever after)
REVIEW_MAX = 3             # new matches reviewed per run


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except ValueError:
        return default


class PremierJobs:
    def __init__(self, sr: StatsRunner):
        self.sr = sr
        self.store = sr.store
        self.cache_dir = self.store.data_dir / "cache"

    # ---- files --------------------------------------------------------------------------
    def scout_dir(self, tid: int) -> Path:
        return self.sr.team_dir(tid) / "scout"

    def scout_index(self, tid: int) -> dict:
        return _read(self.scout_dir(tid) / "index.json", {}) or {}

    def scouted(self, tid: int, team_id: str) -> dict | None:
        return _read(self.scout_dir(tid) / f"{slug(team_id)}.json")

    def reviews(self, tid: int) -> list[dict]:
        d = self.sr.team_dir(tid) / "reviews"
        out = [x for x in (_read(p) for p in d.glob("*.json")) if x] if d.exists() else []
        return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)

    def review(self, tid: int, match_id: str) -> dict | None:
        return _read(self.sr.team_dir(tid) / "reviews" / f"{slug(match_id)}.json")

    # ---- scouting -----------------------------------------------------------------------
    def submit_scout(self, tid: int, target: dict) -> str:
        """target: {"division": True} | {"name", "tag"} | {"id", "name", "tag"}"""
        key = f"scout:{tid}"
        if not self.sr.busy(key):
            self.sr._set(key, status="queued", log=[], error="", t=time.time())
            self.sr.ex.submit(self._scout, key, tid, target)
        return key

    def _scout_team(self, key: str, client, region: str, tid: int, t: dict) -> dict:
        from ..henrik import premier_history_by_id, premier_team_by_id
        hist = premier_history_by_id(client, t["id"])[:SCOUT_MATCHES]
        members: set[str] = set()
        items = []
        for h in hist:
            try:
                raw = client.match(region, h["id"])
            except Exception as e:
                self.sr._log(key, f"  ! {t['name']}: match {str(h['id'])[:8]}: {e}")
                continue
            side = side_in_match(raw, t["id"], t["name"], t.get("tag", ""), members)
            if side is None and not members:                   # no roster in the match data: ask for the members once
                try:
                    members = {m.get("puuid") for m in premier_team_by_id(client, t["id"]).get("member") or [] if m.get("puuid")}
                except Exception:
                    members = {"-"}
                side = side_in_match(raw, t["id"], t["name"], t.get("tag", ""), members)
            if side is None:
                continue
            try:
                m = parse_match(raw if "data" in raw else {"data": raw})
            except Exception:
                continue
            if m.mode_type and m.mode_type.lower() not in ("standard", ""):
                continue
            items.append((m, side))
        s = summarize(items, self.cache_dir)
        s.update({k: t.get(k) for k in ("id", "name", "tag", "wins", "losses", "points", "place")})
        s["scouted_at"] = time.time()
        _write(self.scout_dir(tid) / f"{slug(t['id'])}.json", s)
        return s

    def _scout(self, key: str, tid: int, target: dict) -> None:
        from ..henrik import premier_leaderboard, premier_team
        self.sr._set(key, status="running")
        try:
            team = self.store.team(tid)
            if team is None:
                raise RuntimeError("Team was deleted")
            pi = team.premier_info
            region = pi.get("region") or "eu"
            client = self.sr._client()
            client.on_wait = lambda m: self.sr._log(key, m)
            idx = self.scout_index(tid)
            idx.setdefault("teams", {})
            if target.get("division"):
                pl = pi.get("placement") or {}
                conf, div = pl.get("conference"), pl.get("division")
                if not (conf and div):
                    raise RuntimeError("Your team's conference/division isn't known yet: press Sync Premier roster first.")
                self.sr._log(key, f"· Reading division {div} ({conf}) ...")
                teams = premier_leaderboard(client, region, conf, div)
                ours = {str(pi.get("id") or ""), f"{pi.get('name', '').lower()}#{pi.get('tag', '').lower()}"}
                idx["division"] = {"conference": conf, "division": div, "fetched_at": time.time(),
                                   "teams": teams, "ours": pi.get("id") or ""}
                try:                                        # for this week's map (structure read tolerantly)
                    from ..henrik import premier_seasons
                    idx["seasons"] = premier_seasons(client, region)
                except Exception as e:
                    self.sr._log(key, f"  ! season schedule: {e}")
                todo = [t for t in teams if t["id"] not in ours and f"{t['name'].lower()}#{t['tag'].lower()}" not in ours]
                self.sr._log(key, f"· {len(todo)} other teams in your division")
            else:
                t = dict(target)
                if not t.get("id"):
                    self.sr._log(key, f"· Looking up {t.get('name')}#{t.get('tag')} ...")
                    d = premier_team(client, t["name"], t["tag"], region)
                    if not d.get("id"):
                        raise RuntimeError(f"No Premier team {t.get('name')}#{t.get('tag')} found")
                    st = d.get("stats") or {}
                    t = {"id": str(d["id"]), "name": d.get("name") or t["name"], "tag": d.get("tag") or t["tag"],
                         "wins": st.get("wins"), "losses": st.get("losses"),
                         "points": (d.get("placement") or {}).get("points"), "place": (d.get("placement") or {}).get("place")}
                todo = [t]
            for i, t in enumerate(todo, 1):
                self.sr._log(key, f"· ({i}/{len(todo)}) {t['name']}#{t.get('tag', '')} ...")
                try:
                    s = self._scout_team(key, client, region, tid, t)
                    idx["teams"][t["id"]] = {k: t.get(k) for k in ("id", "name", "tag", "wins", "losses", "points", "place")}
                    idx["teams"][t["id"]].update(scouted_at=s["scouted_at"], matches=s["matches"],
                                                 maps={m: [v["wins"], v["games"]] for m, v in s["maps"].items()})
                    _write(self.scout_dir(tid) / "index.json", idx)
                except Exception as e:
                    self.sr._log(key, f"  ! {t['name']}: {e}")
            _write(self.scout_dir(tid) / "index.json", idx)
            self.sr._log(key, f"✓ scouted {len(todo)} team{'s' if len(todo) != 1 else ''}")
            self.sr._set(key, status="done", result=todo[0]["id"] if len(todo) == 1 else None)
        except Exception as e:
            self.sr._log(key, "✗ " + str(e))
            self.sr._log(key, traceback.format_exc(limit=2))
            self.sr._set(key, status="error", error=str(e) or e.__class__.__name__)

    # ---- reviews of your own new Premier matches ------------------------------------------
    def submit_reviews(self, tid: int, post: bool = True, force: str | None = None) -> str:
        """Review Premier matches that have no review yet (or `force` = one match id again)."""
        key = f"review:{tid}"
        if not self.sr.busy(key):
            self.sr._set(key, status="queued", log=[], error="", t=time.time())
            self.sr.ex.submit(self._reviews, key, tid, post, force)
        return key

    def _reviews(self, key: str, tid: int, post: bool, force: str | None) -> None:
        from ..henrik import premier_history
        self.sr._set(key, status="running")
        try:
            team = self.store.team(tid)
            if team is None:
                raise RuntimeError("Team was deleted")
            pi = team.premier_info
            if not pi.get("tag"):
                raise RuntimeError("This team isn't linked to a Premier team")
            region = pi.get("region") or "eu"
            client = self.sr._client()
            client.on_wait = lambda m: self.sr._log(key, m)
            prev = self.reviews(tid)
            done = {r["match_id"] for r in prev}
            newest = max((r.get("started_at") or "" for r in prev), default="")
            hist = premier_history(client, pi["name"], pi["tag"], region)
            # only matches after the newest review (the first run takes the latest few): never backfill old ones
            todo = [h for h in hist if h.get("id") and (h["id"] == force or (
                not force and h["id"] not in done and (not newest or (h.get("started_at") or "") > newest or
                                                       (h.get("tournament") and not h.get("started_at")))))]
            todo = todo[:1] if force else todo[:REVIEW_MAX]
            if not todo:
                self.sr._log(key, "· no new Premier matches")
                self.sr._set(key, status="done")
                return
            starters = set()
            for m in team.member_list:
                pu = m.get("puuid") or (self.sr.games(m["pid"]).load() or {}).get("puuid")
                if pu and m.get("kind") == "starter":
                    starters.add(pu)
            llm = None
            prof = self.store.profile(team.member_list[0]["pid"]) if team.member_list else None
            if prof:
                try:
                    llm, cfg = self.sr._llm(prof)
                    self.sr._log(key, f"· reviews written by {cfg.ollama.model}")
                except Exception as e:
                    self.sr._log(key, f"  ! no model ({e}): numbers only")
            for h in reversed(todo):                       # oldest first, so Discord reads in order
                self.sr._log(key, f"· match {h['id'][:8]} ...")
                try:
                    r = self._review_one(client, region, team, h, starters, llm, prof.language if prof else "English")
                except Exception as e:
                    self.sr._log(key, f"  ! {e}")
                    continue
                if r is None:
                    continue
                _write(self.sr.team_dir(tid) / "reviews" / f"{slug(r['match_id'])}.json", r)
                self.sr._log(key, f"  ✓ {r['map']} {r['score']} vs {r['opponent']}")
                if post:
                    url = team.discord_info.get("prep_url") or team.discord_info.get("focus_url")
                    if url:
                        from ..discord import post as dpost
                        try:
                            dpost(url, "", embeds=[review_embed(r)])
                        except Exception as e:
                            self.sr._log(key, f"  ! Discord: {e}")
            self.sr._set(key, status="done")
        except Exception as e:
            self.sr._log(key, "✗ " + str(e))
            self.sr._set(key, status="error", error=str(e) or e.__class__.__name__)

    def _review_one(self, client, region: str, team, h: dict, starters: set[str], llm, language: str) -> dict | None:
        from ..coach.teamreview import review
        from ..maps import MapRegistry
        pi = team.premier_info
        raw = client.match(region, h["id"])
        side = side_in_match(raw, pi.get("id", ""), pi.get("name", ""), pi.get("tag", ""), starters)
        if side is None:
            self.sr._log(key_of(team), "  ! couldn't tell which side was your team")
            return None
        m = parse_match(raw)
        try:
            mi = MapRegistry(self.cache_dir).get(m.map_id, m.map_name)
        except Exception:
            mi = None
        roles_by = {}
        for mm in team.member_list:
            p = self.store.profile(mm["pid"])
            if p and mm.get("roles"):
                roles_by[f"{p.name}#{p.tag}".lower()] = mm["roles"]
        rv = review(m, side, mi, llm, language, roles_by)
        other = m.other_team(side)
        d = raw.get("data", raw)
        opp = next(((t.get("premier_roster") or {}) for t in d.get("teams") or [] if t.get("team_id") == other), {}) or {}
        if not opp.get("name"):                  # no Premier roster in the data: recognise them from the scouting
            theirs_pu = {p.puuid for p in m.players_on(other)}
            for tid_, s in ((k, self.scouted(team.id, k)) for k in (self.scout_index(team.id).get("teams") or {})):
                if s and len(theirs_pu & {p["puuid"] for p in s.get("players", [])}) >= 3:
                    opp = {"name": s.get("name"), "tag": s.get("tag"), "id": tid_}
                    break
        ours, theirs = m.team_rounds_won.get(side, 0), m.team_rounds_won.get(other, 0)
        return {"match_id": m.match_id, "started_at": m.started_at, "map": m.map_name, "won": ours > theirs,
                "score": f"{ours}–{theirs}", "opponent": (f"{opp.get('name')}#{opp.get('tag')}" if opp.get("name") else "their team"),
                "opponent_id": str(opp.get("id") or ""), "tournament": bool(h.get("tournament")),
                "key_rounds": key_rounds(m, side), "players": rv["players"], "trade_pairs": rv["trade_pairs"],
                "model": getattr(llm, "model", "") if llm else "", "created": time.time()}


def key_of(team) -> str:
    return f"review:{team.id}"


def key_rounds(m, team: str) -> list[dict]:
    """Rounds that decided the match: lost with a man advantage, lost after the first kill, pistols."""
    out = []
    for rnd in m.rounds:
        won = rnd.winning_team == team
        alive = {t: len(m.players_on(t)) or 5 for t in m.teams}
        other = m.other_team(team)
        best_lead = 0
        for k in rnd.kills:
            if k.victim_team in alive:
                alive[k.victim_team] -= 1
            best_lead = max(best_lead, alive.get(team, 0) - alive.get(other, 0))
        why = None
        if not won and best_lead >= 2:
            why = f"lost a {best_lead}-player advantage"
        elif not won and rnd.kills and rnd.kills[0].killer_team == team and len(m.rounds) > 0:
            why = "lost after taking the first kill"
        elif rnd.index in (0, 12):
            why = "pistol round " + ("won" if won else "lost")
        if why:
            out.append({"round": rnd.number, "side": rnd.side_of(team), "won": won, "why": why})
    # the big ones first: advantages thrown, then first-kill losses, then pistols; keep it short
    order = {"lost a": 0, "lost after": 1, "pistol": 2}
    out.sort(key=lambda r: (next(v for k, v in order.items() if r["why"].startswith(k)), r["round"]))
    return out[:6]


def review_embed(r: dict) -> dict:
    lines = []
    ps = sorted(r.get("players", []), key=lambda p: -(p.get("stats") or {}).get("acs", 0))
    if ps:
        mvp = ps[0]
        st = mvp.get("stats") or {}
        lines.append(f"**MVP:** {mvp['name']} ({mvp['agent']}) {st.get('kills')}/{st.get('deaths')}/{st.get('assists')}, ACS {st.get('acs')}")
    kr = r.get("key_rounds") or []
    if kr:
        lines.append("**Rounds that decided it:** " + "; ".join(f"R{k['round']} {k['why']}" for k in kr[:4]))
    for p in ps:
        fb = p.get("feedback") or {}
        fix = (fb.get("fix") or [{}])[0]
        line = f"• **{p['name']}**: " + (fix.get("try") or fb.get("summary") or
                                         f"{(p.get('stats') or {}).get('untraded_deaths', 0)} deaths not traded")
        lines.append(line[:300])
    return {"title": f"{'WIN' if r['won'] else 'LOSS'} {r['score']} on {r['map']} vs {r['opponent']}"[:250],
            "description": "\n".join(lines)[:3800], "color": 0x35D0A0 if r["won"] else 0xFF4655,
            "footer": {"text": "valcoach · Premier review" + (" · tournament" if r.get("tournament") else "")}}
