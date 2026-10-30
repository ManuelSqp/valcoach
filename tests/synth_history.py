"""Synthetic match history for the stats features: many matches on several maps with
per-player agent pools, plus a fake HenrikDev client serving them as v4 history pages
and v1 stored-archive summaries."""
from __future__ import annotations

import copy
import random
from datetime import datetime, timedelta, timezone

import synth

MAPS = ["Ascent", "Bind", "Haven", "Lotus"]
# our team (Red). red-1 is the focus player adv1ce#LFT; red-4 is "subby" in some matches
POOLS = {
    "red-0": ["Omen", "Viper"],
    "red-1": ["Jett", "Raze", "Sova"],
    "red-2": ["Sova", "Fade", "Skye"],
    "red-3": ["Killjoy", "Cypher"],
    "red-4": ["Skye", "Breach", "Omen"],
}
ENEMY = ["Reyna", "Sova", "Omen", "Killjoy", "Breach"]
SUB_EVERY = 4


def build_history(n: int = 40, seed: int = 3) -> list[dict]:
    """Newest first. Each item is the v4 `data` dict of one match."""
    rng = random.Random(seed)
    base = synth.build_match(n_rounds=8, seed=seed)["data"]
    t0 = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        d = copy.deepcopy(base)
        m = MAPS[i % len(MAPS)]
        queue = "premier" if i % 3 == 0 else "competitive"
        d["metadata"].update(match_id=f"hist-{i:03d}", started_at=(t0 - timedelta(hours=6 * i)).isoformat().replace("+00:00", "Z"),
                             queue={"id": queue, "name": queue.title(), "mode_type": "Standard"},
                             map={"id": synth.MAP_UUID, "name": m})
        used = set()
        agents = {}
        for pu in synth.RED:
            pool = POOLS[pu]
            # adv1ce: Jett on Ascent, otherwise mixed
            if pu == "red-1":
                choice = "Jett" if m == "Ascent" and i % 5 != 0 else pool[(i // 4) % len(pool)]
            else:
                choice = pool[(i + rng.randint(0, 2)) % len(pool)]
            if choice in used:
                choice = next(a for a in pool + ["Brimstone", "Sage", "Chamber"] if a not in used)
            used.add(choice)
            agents[pu] = choice
        for j, pu in enumerate(synth.BLUE):
            agents[pu] = ENEMY[j]
        for p in d["players"]:
            p["agent"] = {"id": synth.agent_uuid(agents[p["puuid"]]), "name": agents[p["puuid"]]}
            if p["puuid"] == "red-4" and i % SUB_EVERY == 0:
                p["name"], p["tag"] = "subby", "T"
        # results: adv1ce on Jett wins most, Raze loses most, the rest is a coin flip
        a = agents["red-1"]
        p_win = 0.8 if a == "Jett" else (0.3 if a == "Raze" else 0.5)
        win = rng.random() < p_win
        own, opp = (13, rng.randint(5, 11)) if win else (rng.randint(5, 11), 13)
        d["teams"] = [{"team_id": "Red", "rounds": {"won": own, "lost": opp}, "won": win, "premier_roster": None},
                      {"team_id": "Blue", "rounds": {"won": opp, "lost": own}, "won": not win, "premier_roster": None}]
        out.append(d)
    return out


def stored_item(d: dict, name: str, tag: str) -> dict | None:
    me = next((p for p in d["players"] if p["name"].lower() == name.lower() and p["tag"].lower() == tag.lower()), None)
    if me is None:
        return None
    won = {t["team_id"].lower(): t["rounds"]["won"] for t in d["teams"]}
    return {"meta": {"id": d["metadata"]["match_id"], "map": d["metadata"]["map"], "mode": d["metadata"]["queue"]["name"],
                     "started_at": d["metadata"]["started_at"]},
            "stats": {"puuid": me["puuid"], "team": me["team_id"], "character": me["agent"],
                      "score": me["stats"]["score"] + 2000, "kills": me["stats"]["kills"], "deaths": me["stats"]["deaths"],
                      "assists": me["stats"]["assists"], "damage": {"made": 2400, "received": 2000}},
            "teams": won}


class FakeHenrik:
    """Serves the history like HenrikDev: full matches only for the newest `full_depth` per queue."""

    def __init__(self, history: list[dict], full_depth: int = 8):
        self.history = history
        self.full_depth = full_depth
        self.calls = {"history": 0, "stored": 0}

    def _mine(self, name, tag, mode):
        out = []
        for d in self.history:
            if mode and d["metadata"]["queue"]["id"] != mode:
                continue
            if any(p["name"].lower() == name.lower() and p["tag"].lower() == tag.lower() for p in d["players"]):
                out.append(d)
        return out

    def _get(self, path, params=None):
        if "/stored-mmr-history/" in path:                 # rank history: Gold 3 climbing 9 RR per win
            name, tag = path.rstrip("/").split("/")[-2:]
            mine = sorted(self._mine(name, tag, "competitive"), key=lambda d: d["metadata"]["started_at"])
            out, pts = [], 1050
            for d in mine:
                won = any(t["won"] for t in d["teams"] if any(p["team_id"] == t["team_id"] and p["name"].lower() == name.lower()
                                                             for p in d["players"]))
                ch = 18 if won else -15
                pts += ch
                out.append({"match_id": d["metadata"]["match_id"], "tier": {"id": 3 + pts // 100, "name": ""},
                            "ranking_in_tier": pts % 100, "last_mmr_change": ch, "elo": pts,
                            "map": {"name": d["metadata"]["map"]["name"]}, "date": d["metadata"]["started_at"]})
            return {"status": 200, "data": list(reversed(out))}
        raise AssertionError(path)

    def match_history(self, region, platform, name, tag, mode=None, size=10, start=0):
        self.calls["history"] += 1
        mine = self._mine(name, tag, mode)[: self.full_depth]
        return copy.deepcopy(mine[start:start + size])

    def stored_matches(self, region, name, tag, mode=None, page=1, size=20):
        self.calls["stored"] += 1
        mine = self._mine(name, tag, mode)
        items = [stored_item(d, name, tag) for d in mine[(page - 1) * size: page * size]]
        return [x for x in items if x], {"total": len(mine)}


class FakeHenrikPremier(FakeHenrik):
    """Adds the Premier endpoints: team 'Red Squad#RED' = the five red players + subby.
    members: 'named' (like the docs' example), 'nonames' (name/tag null, as seen live) or 'none'."""

    def __init__(self, history, full_depth=8, members="named", roster_in_match=False):
        super().__init__(history, full_depth)
        self.members_mode = members
        self.roster_in_match = roster_in_match

    def _get(self, path, params=None):
        if "/by-puuid/account/" in path:
            pu = path.rsplit("/", 1)[1]
            known = {"red-1": ("adv1ce", "LFT"), "sub-x": ("subby", "T")}
            n, t = known.get(pu, (pu, "T"))
            return {"status": 200, "data": {"puuid": pu, "name": n, "tag": t, "region": "eu"}}
        if "/premier/leaderboard/" in path:                 # division 12: us, a scouted rival, a team without matches
            return {"status": 200, "data": [
                {"id": "team-1", "name": "Red Squad", "tag": "RED", "wins": 6, "losses": 3, "score": 300, "ranking": 3},
                {"id": "team-2", "name": "Blue Bandits", "tag": "BLU", "wins": 7, "losses": 2, "score": 350, "ranking": 1},
                {"id": "team-3", "name": "Green Goats", "tag": "GG", "wins": 1, "losses": 8, "score": 75, "ranking": 9}]}
        if "/premier/seasons/" in path:
            return {"status": 200, "data": [{"id": "s1", "events": [
                {"id": "e1", "type": "LEAGUE", "starts_at": "2020-01-01T00:00:00Z", "ends_at": "2020-01-08T00:00:00Z",
                 "map_selection": {"type": "RANDOM", "maps": [{"name": "Ascent"}]}},
                {"id": "e2", "type": "LEAGUE", "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2099-01-01T00:00:00Z",
                 "map_selection": {"type": "RANDOM", "maps": [{"name": "Bind"}]}}]}]}
        if path.endswith("/premier/team-3/history"):
            return {"status": 200, "data": {"league_matches": [], "tournament_matches": []}}
        if path.endswith("/premier/team-2"):
            return {"status": 200, "data": {"id": "team-2", "name": "Blue Bandits", "tag": "BLU",
                                            "member": [{"puuid": pu, "name": None, "tag": None} for pu in synth.BLUE]}}
        if path.endswith("/history"):
            prem = [d for d in self.history if d["metadata"]["queue"]["id"] == "premier"]
            if self.members_mode == "none-1match":
                prem = prem[:1]                           # new season: one match so far
            return {"status": 200, "data": {"league_matches": [
                {"id": d["metadata"]["match_id"], "started_at": d["metadata"]["started_at"], "points_before": 0, "points_after": 25}
                for d in prem], "tournament_matches": []}}
        if "/premier/" in path:
            # like the real API: names may be missing (null) for some members
            members = [{"puuid": "red-1", "name": None, "tag": None}] + [
                {"puuid": f"red-{i}", "name": f"red-{i}", "tag": "T"} for i in (0, 2, 3)] + [
                {"puuid": "red-4", "name": None, "tag": None}, {"puuid": "sub-x", "name": None, "tag": None}]
            if self.members_mode in ("none", "none-1match"):
                members = []
            elif self.members_mode == "nonames":
                members = [{"puuid": m["puuid"], "name": None, "tag": None} for m in members]
            return {"status": 200, "data": {"id": "team-1", "name": "Red Squad", "tag": "RED", "enrolled": True,
                                            "placement": {"points": 300, "division": 12, "place": 3, "conference": "EU_CENTRAL"},
                                            "stats": {"wins": 6, "matches": 9, "losses": 3, "rounds_won": 0, "rounds_lost": 0},
                                            "member": members}}
        if "/by-puuid/account/" in path:
            pu = path.rsplit("/", 1)[1]
            names = {"sub-x": ("subby", "T")}
            if pu not in names:
                return {"status": 404, "data": {}}
            return {"status": 200, "data": {"puuid": pu, "name": names[pu][0], "tag": names[pu][1], "region": "eu"}}
        return FakeHenrik._get(self, path, params)

    def match(self, region, match_id, use_cache=True):
        d = copy.deepcopy(next(x for x in self.history if x["metadata"]["match_id"] == match_id))
        if self.roster_in_match:
            for t in d["teams"]:
                if t["team_id"] == "Red":
                    t["premier_roster"] = {"id": "team-1", "name": "Red Squad", "tag": "RED",
                                           "members": ["red-0", "red-1", "red-2", "red-3", "red-4", "sub-x"]}
        return {"status": 200, "data": d}
