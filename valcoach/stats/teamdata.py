"""Matches your team played together, and what they show.

A "team match" is a match with full round data in which at least 3 of the starters played on
the same side. From those:
  * teammate tips (who keeps dying outnumbered where, who trades whom), and
  * map facts for game plans: which site you hit and how that goes, when the first fight
    happens, where you get flanked from, mid control, retakes, what opponents at your level do.
Matches come from the local cache (data/cache/matches), so this costs no API requests.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from ..coach.teamreview import facts as review_facts
from ..maps import MapInfo, MapRegistry
from ..models import Match
from ..parse import parse_match

MIN_TOGETHER = 3
BEHIND_UNITS = 600          # killer at least this much closer to our spawn than the victim = from behind


def team_matches(cache_dir: Path, rows_by_puuid: dict[str, list[dict]], limit: int = 40) -> list[tuple[Match, str]]:
    """[(match, our team id)] newest first. rows_by_puuid: starter puuid -> their game rows."""
    count: Counter = Counter()
    when: dict[str, str] = {}
    for pu, rows in rows_by_puuid.items():
        for r in rows:
            if r.get("source") == "full":
                count[r["match_id"]] += 1
                when[r["match_id"]] = r.get("started_at", "")
    ids = sorted((m for m, n in count.items() if n >= MIN_TOGETHER), key=lambda m: when[m], reverse=True)[:limit]
    out = []
    for mid in ids:
        f = Path(cache_dir) / "matches" / f"{mid}.json"
        if not f.exists():
            continue
        try:
            m = parse_match(json.loads(f.read_text()))
        except Exception:
            continue
        sides = Counter(m.team_of(pu) for pu in rows_by_puuid if pu in m.players)
        if sides:
            team, n = sides.most_common(1)[0]
            if n >= MIN_TOGETHER:
                out.append((m, team))
    return out


def _map_info(reg: MapRegistry, m: Match, cache: dict) -> MapInfo | None:
    if m.map_id not in cache:
        try:
            cache[m.map_id] = reg.get(m.map_id, m.map_name)
        except Exception:
            cache[m.map_id] = None
    return cache[m.map_id]


# ---------------------------------------------------------------------------
# teammate tips
# ---------------------------------------------------------------------------
def teammate_tips(matches: list[tuple[Match, str]], cache_dir: Path, names: dict[str, str]) -> list[dict]:
    """Deterministic tips about how teammates can help each other. names: puuid -> display name."""
    reg, mcache = MapRegistry(cache_dir), {}
    outnum = defaultdict(Counter)           # puuid -> (map, side, area) -> deaths with 2+ enemies close
    alone = defaultdict(Counter)            # puuid -> (map, side, area) -> untraded deaths far from team
    deaths = Counter()
    pairs = Counter()
    for m, team in matches:
        f = review_facts(m, team, _map_info(reg, m, mcache))
        for pu, d in f["players"].items():
            if pu not in names:
                continue
            for x in d["deaths_list"]:
                deaths[pu] += 1
                key = (m.map_name, x["side"], x["where"])
                if x["enemies_close"] >= 2:
                    outnum[pu][key] += 1
                if x["alone"] and not x["traded"]:
                    alone[pu][key] += 1
        for t in f["trade_pairs"]:
            pairs[(t["traded_by"], t["died"])] += t["times"]
    tips = []
    for pu, c in outnum.items():
        for (mp, side, area), n in c.most_common(2):
            if n >= 3 and area != "?":
                tips.append({"about": names[pu], "puuid": pu, "map": mp, "kind": "outnumbered", "count": n,
                             "text": f"{names[pu]} died outnumbered (2+ enemies close) {n}× at {area} on {mp} {side}. "
                                     f"Whoever plays nearest should play that spot with him, or fall back together."})
    for pu, c in alone.items():
        for (mp, side, area), n in c.most_common(1):
            if n >= 3 and area != "?":
                tips.append({"about": names[pu], "puuid": pu, "map": mp, "kind": "alone", "count": n,
                             "text": f"{names[pu]} died alone and untraded {n}× at {area} on {mp} {side}. "
                                     f"Either someone stays in trade distance there, or he plays it for info and falls back early."})
    for (a, b), n in pairs.most_common(3):
        if n >= 3:
            tips.append({"about": b, "puuid": None, "map": "", "kind": "duo", "count": n,
                         "text": f"{a} traded {b} {n}× in your recent matches: a duo that works, keep them together on hits."})
    tips.sort(key=lambda t: -t["count"])
    return tips[:8]


# ---------------------------------------------------------------------------
# map facts for game plans
# ---------------------------------------------------------------------------
def _spawn(mi: MapInfo | None, side: str) -> tuple[float, float] | None:
    if mi is None:
        return None
    for c in mi.callouts:
        if c.region.lower() == "spawn" and side in c.super_region.lower():
            return c.x, c.y
    return None


def _d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def window(xs: list[float]) -> list[int] | None:
    """The middle half of the times (25th-75th percentile), in seconds since the round started."""
    if len(xs) < 3:
        return None
    s = sorted(xs)
    q = lambda f: s[min(len(s) - 1, max(0, round(f * (len(s) - 1))))]   # noqa: E731
    return [round(q(0.25)), round(q(0.75))]


def map_facts(matches: list[tuple[Match, str]], cache_dir: Path, map_name: str) -> dict:
    """Numbers about how your team plays one map (only matches on that map)."""
    reg, mcache = MapRegistry(cache_dir), {}
    ms = [(m, t) for m, t in matches if m.map_name.lower() == map_name.lower()]
    out: dict = {"map": map_name, "team_matches": len(ms)}
    if not ms:
        return out
    att = {"rounds": 0, "won": 0, "plants": Counter(), "plant_won": Counter(), "no_plant": 0, "no_plant_won": 0,
           "first_t": [], "first_area": Counter(), "first_area_won": Counter(), "flanks": Counter(), "flank_t": [],
           "plant_t": []}
    dfn = {"rounds": 0, "won": 0, "enemy_plants": Counter(), "retake_won": Counter(), "first_t": [],
           "first_death_area": Counter(), "enemy_plant_t": [], "contact_t": defaultdict(list)}
    mid = {"ours": 0, "ours_won": 0, "theirs": 0, "theirs_won": 0}
    for m, team in ms:
        mi = _map_info(reg, m, mcache)
        att_spawn = _spawn(mi, "attack")
        for rnd in m.rounds:
            side = rnd.side_of(team)
            won = rnd.winning_team == team
            k0 = rnd.kills[0] if rnd.kills else None
            if side == "attack":
                att["rounds"] += 1
                att["won"] += won
                if rnd.plant and rnd.plant.site:
                    att["plants"][rnd.plant.site] += 1
                    att["plant_won"][rnd.plant.site] += won
                    att["plant_t"].append(rnd.plant.t_round_ms / 1000)
                else:
                    att["no_plant"] += 1
                    att["no_plant_won"] += won
                if k0:
                    att["first_t"].append(k0.t_round_ms / 1000)
                    if mi:
                        a = mi.area(k0.victim_x, k0.victim_y)
                        att["first_area"][a] += 1
                        att["first_area_won"][a] += k0.killer_team == team
                # flanks: our attackers killed by someone between them and our spawn
                if att_spawn:
                    for k in rnd.kills:
                        if k.victim_team != team:
                            continue
                        kl = k.loc_of(k.killer) if k.killer else None
                        if kl and _d((kl.x, kl.y), att_spawn) + BEHIND_UNITS < _d((k.victim_x, k.victim_y), att_spawn):
                            att["flanks"][mi.area(kl.x, kl.y) if mi else "?"] += 1
                            att["flank_t"].append(k.t_round_ms / 1000)
            else:
                dfn["rounds"] += 1
                dfn["won"] += won
                if rnd.plant and rnd.plant.site:
                    dfn["enemy_plants"][rnd.plant.site] += 1
                    dfn["retake_won"][rnd.plant.site] += won
                    dfn["enemy_plant_t"].append(rnd.plant.t_round_ms / 1000)
                if k0:
                    dfn["first_t"].append(k0.t_round_ms / 1000)
                    if k0.victim_team == team and mi:
                        dfn["first_death_area"][mi.area(k0.victim_x, k0.victim_y)] += 1
                    if mi:                       # where and when the attackers make first contact
                        try:
                            z = mi.zone(k0.victim_x, k0.victim_y)
                        except Exception:
                            z = "?"
                        dfn["contact_t"][z].append(k0.t_round_ms / 1000)
            if k0 and mi and k0.t_round_ms <= 45000 and mi.zone(k0.victim_x, k0.victim_y).lower() == "mid":
                if k0.killer_team == team:
                    mid["ours"] += 1
                    mid["ours_won"] += won
                else:
                    mid["theirs"] += 1
                    mid["theirs_won"] += won
    pct = lambda a, b: None if not b else f"{a / b:.0%}"      # noqa: E731
    sec = lambda xs: None if not xs else round(median(xs))     # noqa: E731
    win = window
    out["attack"] = {
        "rounds": att["rounds"], "won": pct(att["won"], att["rounds"]),
        "sites_hit": {s: {"plants": n, "rounds_won": pct(att["plant_won"][s], n)} for s, n in att["plants"].most_common()},
        "no_plant_rounds": {"count": att["no_plant"], "won": pct(att["no_plant_won"], att["no_plant"])},
        "first_fight_median_s": sec(att["first_t"]), "plant_median_s": sec(att["plant_t"]),
        "first_fight_areas": [{"area": a, "fights": n, "you_won": pct(att["first_area_won"][a], n)}
                              for a, n in att["first_area"].most_common(4)],
        "killed_from_behind": {"count": sum(att["flanks"].values()), "from": [{"area": a, "count": n} for a, n in att["flanks"].most_common(3)],
                               "median_time_s": sec(att["flank_t"]), "window_s": win(att["flank_t"])},
        "first_fight_window_s": win(att["first_t"]), "plant_window_s": win(att["plant_t"]),
    }
    out["defense"] = {
        "rounds": dfn["rounds"], "won": pct(dfn["won"], dfn["rounds"]),
        "enemy_plants": {s: {"plants": n, "retakes_won": pct(dfn["retake_won"][s], n)} for s, n in dfn["enemy_plants"].most_common()},
        "enemy_plant_median_s": sec(dfn["enemy_plant_t"]), "first_fight_median_s": sec(dfn["first_t"]),
        "your_first_deaths": [{"area": a, "count": n} for a, n in dfn["first_death_area"].most_common(3)],
        "enemy_plant_window_s": win(dfn["enemy_plant_t"]),
        "first_contact": [{"where": z, "rounds": len(ts), "window_s": win(ts)}
                          for z, ts in sorted(dfn["contact_t"].items(), key=lambda kv: -len(kv[1])) if z != "?" and window(ts)][:4],
    }
    out["mid_control"] = {"early_mid_kill_yours": {"rounds": mid["ours"], "won": pct(mid["ours_won"], mid["ours"])},
                          "early_mid_kill_theirs": {"rounds": mid["theirs"], "won": pct(mid["theirs_won"], mid["theirs"])}}
    return out
