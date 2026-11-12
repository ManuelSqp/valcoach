"""Team economy review (4.21): how your buys go as a team, against the teams in the same lobbies.

From the team's matches together (3+ starters on one side, full round data). Per round and team the buy is
the team's average loadout at the start (stats/rounds.py: pistol / eco / force / full). The other team in
the same matches is the yardstick ("your rank's lobbies"): same maps, same patch, same ranks.

  kinds        round win rate per buy, yours and theirs
  matchups     anti-eco, force into a full buy, ... yours and theirs
  bonus        the round after a won pistol
  broke        a lost force that left the team unable to full buy the next round (lost twice for one gamble)
  split        rounds with 2+ on rifles and 2+ saving at the same time (half the team bought)
  players      per player: bought while the team saved, saved while the team bought, and how those rounds went
  lost_to_buys rounds per match lost in a broken force or a split buy

  analyse(matches, names) -> dict or None (fewer than MIN_ROUNDS rounds)
"""
from __future__ import annotations

from collections import defaultdict

from .aggregate import smooth
from .rounds import ECO, FULL, KIND_TEXT, KINDS, MATCHUPS, kind

MIN_ROUNDS = 60
GAP = 0.08                 # a difference to the lobbies counts from 8 points


def _rate(w: int, n: int) -> dict:
    return {"rounds": n, "won": w, "wr": w / n if n else None, "wr_s": smooth(w, n) if n else None}


def _team_round(rnd, team: str) -> tuple[float, list, list]:
    st = [s for s in rnd.stats.values() if s.team == team]
    loads = [s.loadout_value for s in st]
    return (sum(loads) / len(loads) if loads else 0.0), st, loads


def _side_counts() -> dict:
    return {"kinds": defaultdict(lambda: [0, 0]), "mu": defaultdict(lambda: [0, 0]), "bonus": [0, 0],
            "forces": [0, 0], "broke": 0, "split": [0, 0], "rounds": 0}


def _count(acc: dict, m, team: str, players: dict | None, names: dict) -> int:
    """Adds one team's rounds of one match. Returns the rounds lost to a broken force or a split buy."""
    other = m.other_team(team)
    rounds = sorted(m.rounds, key=lambda r: r.number)
    kinds = []
    for r in rounds:
        avg, _, _ = _team_round(r, team)
        oavg, _, _ = _team_round(r, other)
        kinds.append((kind(r.number, int(avg)), kind(r.number, int(oavg))))
    lost_buys = 0
    for i, r in enumerate(rounds):
        won = int(r.winning_team == team)
        kk, ok = kinds[i]
        acc["rounds"] += 1
        acc["kinds"][kk][0] += won
        acc["kinds"][kk][1] += 1
        if kk != "pistol" and ok != "pistol":
            acc["mu"][(kk, ok)][0] += won
            acc["mu"][(kk, ok)][1] += 1
        if r.number in (2, 14) and i > 0 and rounds[i - 1].number == r.number - 1 and rounds[i - 1].winning_team == team:
            acc["bonus"][0] += won
            acc["bonus"][1] += 1
        bad = False
        if kk == "force":
            acc["forces"][0] += won
            acc["forces"][1] += 1
            # lost, and the next round (same half) couldn't be a full buy: the force cost two rounds
            nxt = rounds[i + 1] if i + 1 < len(rounds) else None
            if not won and nxt and nxt.number not in (13,) and nxt.number <= 24 and kinds[i + 1][0] in ("eco", "force"):
                acc["broke"] += 1
                bad = True
        _, st, loads = _team_round(r, team)
        rifles = sum(1 for v in loads if v >= FULL)
        saving = sum(1 for v in loads if v < ECO)
        if kk != "pistol" and rifles >= 2 and saving >= 2:
            acc["split"][0] += won
            acc["split"][1] += 1
            bad = bad or not won
        if bad:
            lost_buys += 1
        if players is not None and kk != "pistol":
            for s in st:
                if s.puuid not in names:
                    continue
                p = players.setdefault(s.puuid, {"name": names[s.puuid], "rounds": 0, "alone_buy": [0, 0], "alone_save": [0, 0]})
                p["rounds"] += 1
                if kk == "eco" and s.loadout_value >= FULL - 900:          # rifle money while the team saves
                    p["alone_buy"][0] += won
                    p["alone_buy"][1] += 1
                elif kk == "full" and s.loadout_value < ECO:              # the team bought, he didn't
                    p["alone_save"][0] += won
                    p["alone_save"][1] += 1
    return lost_buys


def analyse(matches: list, names: dict[str, str]) -> dict | None:
    """matches: [(Match, our team id)] (stats.teamdata.team_matches); names: puuid -> member name."""
    us, them = _side_counts(), _side_counts()
    players: dict[str, dict] = {}
    lost = 0
    games = 0
    for m, team in matches:
        if not m.rounds or not any(r.stats for r in m.rounds):
            continue
        games += 1
        lost += _count(us, m, team, players, names)
        _count(them, m, m.other_team(team), None, names)
    if us["rounds"] < MIN_ROUNDS:
        return None

    def cmp(a: dict, b: dict, higher_better: bool = True) -> str:
        if a["wr"] is None or b["wr"] is None or a["rounds"] < 10 or b["rounds"] < 10:
            return ""
        d = a["wr"] - b["wr"]
        return "" if abs(d) < GAP else ("good" if (d > 0) == higher_better else "bad")

    out: dict = {"games": games, "rounds": us["rounds"]}
    out["kinds"] = []
    for k in KINDS:
        a, b = _rate(*us["kinds"][k]), _rate(*them["kinds"][k])
        out["kinds"].append({"kind": k, "text": KIND_TEXT[k], "share": a["rounds"] / us["rounds"],
                             "share_them": b["rounds"] / (them["rounds"] or 1), "us": a, "them": b, "v": cmp(a, b)})
    out["matchups"] = []
    for x, y, title, text in MATCHUPS:
        a, b = _rate(*us["mu"][(x, y)]), _rate(*them["mu"][(x, y)])
        out["matchups"].append({"title": title, "text": text, "us": a, "them": b, "v": cmp(a, b)})
    out["bonus"] = {"us": _rate(*us["bonus"]), "them": _rate(*them["bonus"])}
    out["bonus"]["v"] = cmp(out["bonus"]["us"], out["bonus"]["them"])
    fu, ft = us["forces"][1] or 1, them["forces"][1] or 1
    out["broke"] = {"us": us["broke"], "forces": us["forces"][1], "share": us["broke"] / fu,
                    "them": them["broke"], "forces_them": them["forces"][1], "share_them": them["broke"] / ft}
    out["split"] = {"us": _rate(*us["split"]), "them": _rate(*them["split"]),
                    "share": us["split"][1] / us["rounds"], "share_them": them["split"][1] / (them["rounds"] or 1)}
    out["lost_to_buys"] = round(lost / games, 1) if games else 0
    out["players"] = sorted(({"name": p["name"], "rounds": p["rounds"], "alone_buy": _rate(*p["alone_buy"]),
                              "alone_save": _rate(*p["alone_save"])} for p in players.values()),
                            key=lambda p: -(p["alone_buy"]["rounds"] + p["alone_save"]["rounds"]))
    out["notes"] = notes(out)
    return out


def notes(o: dict) -> list[dict]:
    """Plain findings, only with enough rounds; bad ones first."""
    out = []
    k = {x["kind"]: x for x in o["kinds"]}
    m = {x["title"]: x for x in o["matchups"]}
    pct = lambda r: f"{r['wr']:.0%}"           # noqa: E731
    for key, label in (("pistol", "Pistol rounds"), ("force", "Force buys"), ("full", "Full buys")):
        x = k[key]
        if x["v"]:
            out.append({"bad": x["v"] == "bad", "text": f"{label}: {pct(x['us'])} won, the teams in your lobbies {pct(x['them'])}"})
    ae = m["Anti-eco"]
    if ae["us"]["rounds"] >= 8 and ae["v"] == "bad":
        out.append({"bad": True, "text": f"Anti-eco: you lose {1 - ae['us']['wr']:.0%} of the rounds where you full buy into a "
                    f"saving team (lobbies {1 - ae['them']['wr']:.0%}): no wide peeks into shotguns, keep distance, trade"})
    b = o["broke"]
    if b["forces"] >= 8 and b["share"] >= b["share_them"] + GAP:
        out.append({"bad": True, "text": f"{b['us']} of your {b['forces']} forces were lost and left you broke the next round "
                    f"({b['share']:.0%}, lobbies {b['share_them']:.0%}): force only when the next round is a full buy anyway"})
    s = o["split"]
    if s["us"]["rounds"] >= 6 and (s["share"] >= s["share_them"] + 0.03 or (s["us"]["wr"] or 0) < 0.3):
        out.append({"bad": True, "text": f"Half the team bought, half saved in {s['us']['rounds']} rounds ({s['share']:.0%} of rounds, "
                    f"lobbies {s['share_them']:.0%}); {pct(s['us'])} of them won. Call the buy before the round"})
    bo = o["bonus"]
    if bo["us"]["rounds"] >= 5 and bo["v"]:
        out.append({"bad": bo["v"] == "bad", "text": f"The round after a won pistol: {pct(bo['us'])} won, lobbies {pct(bo['them'])}"})
    for p in o["players"]:
        if p["alone_buy"]["rounds"] >= 4:
            out.append({"bad": (p["alone_buy"]["wr"] or 0) < 0.3, "text": f"{p['name']} bought {p['alone_buy']['rounds']}× while the "
                        f"team saved ({pct(p['alone_buy'])} of those rounds won)"})
    if o["lost_to_buys"] >= 1:
        out.append({"bad": True, "text": f"About {o['lost_to_buys']} rounds per match are lost in a broken force or a split buy"})
    out.sort(key=lambda x: not x["bad"])
    return out


def facts(o: dict | None) -> dict | None:
    """Compact for the coach."""
    if not o:
        return None
    return {"rounds": o["rounds"], "games": o["games"],
            "win_rate_by_buy_vs_lobbies": {x["text"]: f"{x['us']['wr']:.0%} vs {x['them']['wr']:.0%}" for x in o["kinds"]
                                           if x["us"]["rounds"] and x["them"]["rounds"]},
            "lost_forces_that_broke_the_next_round": f"{o['broke']['us']} of {o['broke']['forces']}",
            "split_buy_rounds": o["split"]["us"]["rounds"], "rounds_per_match_lost_to_buys": o["lost_to_buys"],
            "notes": [n["text"] for n in o["notes"]]}
