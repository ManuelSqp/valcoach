"""Agents & roles: preferred class, role fit and the verdict, from hand-made game rows."""
from nexus.stats import agentroles, roles


def _row(agent, won=True, **kw):
    r = {"agent": agent, "won": won, "kills": 18, "deaths": 14, "assists": 4, "rounds": 22, "acs": 220, "adr": 140,
         "map": kw.pop("map", "Ascent"), "queue": "competitive", "source": "full", "v": 2, "kast": 16, "fk": 3, "fd": 2,
         "sides": {"attack": [11, 6], "defense": [11, 5]}, "openings": [["attack", 1]] * 3, "first_in": {"attack": 4, "defense": 2},
         "trade_kills": 2, "iso": {"attack": [10, 7, 2, 1], "defense": [8, 3, 1, 0]}, "def_zones": ["B"] * 6 + ["A"],
         "survived": {"attack": 2, "defense": 6}, "op_rounds": 0, "op_kills": 0, "started_at": "2026-10-01T20:00:00Z"}
    r.update(kw)
    return r


def test_lurker_on_sentinels_matches_and_names_agents():
    roles.load(None)
    rows = [_row("Cypher", won=i % 3 != 0, map="Bind" if i % 2 else "Ascent") for i in range(12)] + [_row("Jett", won=False)]
    o = agentroles.overview(rows, [{"team": "T", "tid": 1, "roles": ["Anchor"]}], {"Killjoy": 0.4})
    assert o["preferred"] == "Sentinel" and o["main_agent"] == "Cypher"
    assert [a["agent"] for a in o["agents"]] == ["Cypher", "Jett"] and o["agents"][1]["enough"] is False
    assert o["suggested"] == "Lurker" and o["match"] and o["strength"] in ("clear", "leaning")
    assert o["try_class"] == "Sentinel" and o["to_try"][0]["agent"] == "Killjoy"          # most picked at your level first
    assert "Cypher" not in [a["agent"] for a in o["to_try"]]                                 # already played
    assert "team has you as Anchor" in o["verdict"]
    assert "Jett" not in o["not_played"]["Duelist"] and "Reyna" in o["not_played"]["Duelist"]


def test_too_little_round_data_has_no_fit():
    roles.load(None)
    o = agentroles.overview([_row("Sova", source="archive") for _ in range(8)])
    assert o["preferred"] == "Initiator" and "fit" not in o and o["full_games"] == 0
    assert agentroles.overview([])["agents"] == []
