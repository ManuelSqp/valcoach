"""4.15: weighting, buy state, lobby strength, confidence, goals and check-ins."""
from datetime import datetime, timedelta, timezone

from nexus.stats import checkins as ck
from nexus.stats import evidence as ev
from nexus.stats import goals as gl
from nexus.stats.comp import Pool
from nexus.stats.games import patch_of

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def row(days=0, won=1.0, agent="Jett", patch="", opp=None, own=None, **kw):
    return {"started_at": (NOW - timedelta(days=days)).isoformat(), "won": won, "agent": agent, "map": "Ascent",
            "acs": 220, "kills": 15, "deaths": 14, "patch": patch, "opp_tier": opp, "own_tier": own,
            "source": "full", "rounds": 22, **kw}


def test_patch_of():
    assert patch_of("release-09.10-shipping-12-2843215") == "9.10"
    assert patch_of("release-11.06-shipping") == "11.06" and patch_of("") == "" and patch_of("test") == ""


def test_weight_recency_patch_and_lobby():
    assert abs(ev.weight(row(0), NOW) - 1.0) < 1e-9
    assert abs(ev.weight(row(45), NOW) - 0.5) < 1e-6                   # one half-life
    assert abs(ev.weight(row(0, patch="9.09"), NOW, "9.10") - ev.PATCH_OLD) < 1e-9
    assert ev.weight(row(0, patch="10.01"), NOW, "9.10") == 1.0        # 10.01 is newer than 9.10
    assert ev.weight(row(0, opp=12, own=10), NOW) > 1 > ev.weight(row(0, opp=8, own=10), NOW)
    assert ev.weight(row(0, opp=27, own=3), NOW) == ev.OPP_MAX
    assert ev.current_patch([row(patch="9.09"), row(patch="9.10"), row(patch="")]) == "9.10"


def test_pool_weights_recent_games():
    old_losses = [row(200, won=0.0, agent="Jett") for _ in range(6)]
    new_wins = [row(1, won=1.0, agent="Jett") for _ in range(4)]
    p = Pool.from_rows("x", old_losses + new_wins)
    plain = Pool.from_rows("x", old_losses + new_wins, weighted=False)
    assert p.n["Jett"] == plain.n["Jett"] == 10                          # real game counts stay
    assert plain.w["Jett"] / plain.n["Jett"] == 0.4
    assert p.w["Jett"] / p.n["Jett"] > 0.85                              # the recent wins weigh more
    # nothing to weigh (no dates, patches, ranks): exactly as before
    bare = [{"agent": "Sova", "map": "Bind", "won": w, "acs": 200} for w in (1, 0, 1)]
    a, b = Pool.from_rows("y", bare), Pool.from_rows("y", bare, weighted=False)
    assert a.w == b.w and a.acs == b.acs


def test_buy_split_and_note():
    econ = ([[i, "attack", 1, 4500, 4500, 1000, 3, 0] for i in range(15)] +       # anti-eco: 3 kills, alive
            [[i, "attack", 0, 4500, 4500, 4500, 0, 1] for i in range(35)] +       # full buys: lost, died
            [[i, "defense", 0, 1000, 1200, 4500, 0, 1] for i in range(5)])        # own eco
    rows = [row(econ=econ)]
    sp = {x["key"]: x for x in ev.buy_split(rows)}
    assert sp["anti_eco"]["rounds"] == 15 and sp["anti_eco"]["wr"] == 1.0 and sp["anti_eco"]["kd"] == 45
    assert sp["full"]["rounds"] == 35 and sp["full"]["kd"] == 0 and sp["full"]["confidence"] == ev.EARLY
    assert sp["own_eco"]["rounds"] == 5
    assert "full-buy rounds" in ev.buy_note(ev.buy_split(rows))
    # old rows (6 values): round win rates, no K/D
    old = ev.buy_split([row(econ=[[1, "attack", 1, 4500, 4500, 4500]])])
    assert old[0]["kd"] is None and old[0]["rounds"] == 1


def test_opponent_split_and_facts():
    rows = [row(opp=14, own=10, won=0.0), row(opp=10, own=10), row(opp=6, own=10), row()]
    sp = {x["key"]: x for x in ev.opponent_split(rows)}
    assert sp["stronger"]["games"] == 1 and sp["stronger"]["wr"] == 0 and sp["weaker"]["games"] == 1
    f = ev.facts(rows, NOW)
    assert f["weighted"]["effective_games"] > 0 and f["by_opponent"]
    assert ev.tag(9, 40) == "early sign, 9 rounds" and ev.tag(84, 40) == "solid, 84 rounds"


def test_situations_say_how_sure():
    from nexus.stats.archetypes import situations
    econ = [[i, "attack", int(i % 2), 4500, 4500, 4500, 1, 0] for i in range(70)]
    sit = {s["key"]: s for s in situations([row(econ=econ, fk=10, fd=4)])}
    assert sit["buy_full"]["n"] == 70 and sit["buy_full"]["confidence"] == ev.SOLID
    assert sit["opening"]["confidence"] == ev.EARLY


def test_goals_reached_missed_and_dropped(tmp_path):
    st = gl.GoalStore(tmp_path / "goals.json")
    before = [row(10, kills=10, deaths=20, traded_deaths=4, started_at="2026-10-01T10:00:00+00:00")]
    g = st.add("traded", 0.4, before, text="trade more", start="2026-10-05T00:00:00+00:00")
    assert g["baseline"] is None or 0 <= g["baseline"] <= 1
    after = [dict(row(), started_at=f"2026-10-0{6 + i}T10:00:00+00:00", deaths=10, traded_deaths=5) for i in range(3)]
    out = st.refresh(before + after)
    assert out[0]["state"] == "reached" and out[0]["now"] == 0.5
    assert st.load()[0]["state"] == "reached"                       # closed and saved
    # missed: the window is over without the target
    g2 = st.add("kd", 2.0, before, start="2026-10-05T00:00:00+00:00", games=3)
    out = {x["id"]: x for x in st.refresh(before + after)}
    assert out[g2["id"]]["state"] == "missed"
    # open, then dropped
    g3 = st.add("hs", 0.3, before, start="2026-11-01T00:00:00+00:00")
    assert {x["id"]: x for x in st.refresh(before + after)}[g3["id"]]["state"] == "open"
    assert st.drop(g3["id"]) and not st.drop(g3["id"])
    facts = gl.facts(st.refresh(before + after), NOW)
    assert {f["result"] for f in facts} >= {"reached", "missed", "dropped"}
    assert gl.parse_target("traded", "45 %") == 0.45 and gl.parse_target("kd", "1,2") == 1.2
    assert st.add("nonsense", 1, []) is None


def test_checkins(tmp_path):
    members = {1, 2, 3, 4, 5}
    for pid, caller, comms in ((1, 2, 4), (2, 2, 3), (3, 2, 5), (4, 9, 2)):
        ck.record(tmp_path, "m1", pid, caller, comms, 4, "fell back late" if pid == 1 else "", members)
    data = ck.load(tmp_path)
    s = ck.summary(data["m1"])
    assert s["n"] == 4 and s["caller"] == 2 and s["comms"] == 3.5 and s["votes"] == {2: 3}
    assert data["m1"]["4"]["caller"] == 0                     # not a team member: no vote
    names = {1: "a", 2: "b", 3: "c", 4: "d", 5: "e"}
    assert ck.igl(data, names) == {"label": "b", "votes": 3, "total": 3}
    assert ck.match_facts(data["m1"], names)["caller"] == "b"
    assert ck.player_facts(ck.of_player(data, 1))["their_notes"] == ["fell back late"]
    ck.record(tmp_path, "m1", 1, 3, 9, 0, "", members)        # replaced; out-of-range scores dropped
    a = ck.load(tmp_path)["m1"]["1"]
    assert a["caller"] == 3 and a["comms"] is None and a["mood"] is None
    assert ck.igl({"m": {"1": {"caller": 2}}}, names) is None  # too few votes
