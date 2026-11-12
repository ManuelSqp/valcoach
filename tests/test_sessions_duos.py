"""4.17: when a player plays best, and which pairs of the team play well together."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from nexus.stats import duos, sessions


def _row(t: datetime, won: int, acs: int = 200):
    return {"started_at": t.astimezone(timezone.utc).isoformat(), "won": won, "acs": acs}


def test_sessions_and_tilt():
    base = datetime(2026, 10, 1, 19, 0).astimezone()
    rows = []
    for day in range(10):                      # 10 evenings, 5 games each: 3 wins, then 2 losses
        start = base + timedelta(days=day)
        for g in range(5):
            rows.append(_row(start + timedelta(minutes=45 * g), 1 if g < 3 else 0))
    ss = sessions.sessions(rows)
    assert len(ss) == 10 and all(len(s) == 5 for s in ss)
    a = sessions.analyse(rows)
    by = {b["key"]: b for b in a["by_game"]}
    assert by[1]["wr"] == 1.0 and by[4]["wr"] == 0.0 and by[5]["games"] == 10
    al = {b["key"]: b for b in a["after_losses"]}
    assert al[0]["games"] == 30 and al[1]["wr"] == 0.0
    assert any("From the 4th game" in h for h in a["hints"])
    assert {b["key"] for b in a["by_time"]} == {"evening", "night"} and len(a["by_day"]) == 7
    f = sessions.facts(rows)
    assert f["sessions"] == 10 and f["games_per_session"] == 5.0 and f["hints"]
    assert sessions.analyse(rows[:5]) is None


def _kill(t, killer, victim, locs=()):
    return NS(t_round_ms=t, killer=killer, victim=victim, victim_x=0.0, victim_y=0.0,
              player_locations=[NS(puuid=p, team=tm, x=x, y=0.0) for p, tm, x in locs])


def test_duo_pairs():
    team = {"a": "Red", "b": "Red", "c": "Red", "e": "Blue", "f": "Blue"}
    r1 = NS(kills=[_kill(1000, "e", "a", [("b", "Red", 500)]), _kill(3000, "b", "e")])     # b trades a, a not alone
    r2 = NS(kills=[_kill(1000, "f", "a", [("b", "Red", 9000)]), _kill(2000, "f", "b", [("a", "Red", 9000)])])
    m = NS(players=team, rounds=[r1, r2], team_of=lambda p: team.get(p, ""), team_rounds_won={"Red": 13, "Blue": 7},
           other_team=lambda s: "Blue" if s == "Red" else "Red")
    ps = {(p["a"], p["b"]): p for p in duos.pairs([(m, "Red"), (m, "Red")], {"a": "A", "b": "B", "c": "C"})}
    ab = ps[("A", "B")]
    assert ab["games"] == 2 and ab["wr"] == 1.0 and ab["trades"] == 2 and ab["both_alone"] == 2 and ab["rounds"] == 4
    assert ps[("A", "C")]["trades"] == 0 and ("B", "C") in ps
    s = duos.summary(list(ps.values()), 1.0)
    assert "best" not in s                                   # fewer than 4 games together
    assert duos.facts(list(ps.values())) == []
