"""Playstyle labels and situations (4.12)."""
from nexus.stats import archetypes


def row(**kw):
    """One game with round data; defaults are an unremarkable player."""
    base = {"source": "full", "rounds": 22, "kills": 15, "deaths": 15, "assists": 4, "acs": 200, "agent": "Jett",
            "map": "Ascent", "won": 1, "fk": 2, "fd": 2, "kast": 15, "trade_kills": 3,
            "sides": {"attack": [11, 5], "defense": [11, 6]}, "first_in": {"attack": 3, "defense": 3},
            "survived": {"attack": 3, "defense": 4},
            "iso": {"attack": [8, 2, 8, 2], "defense": [7, 2, 7, 2]},
            "duels": [[5, 1], [5, 0], [15, 1], [15, 0], [30, 1], [30, 0]],
            "clutch": {}, "retake": [3, 1], "postplant": [3, 2], "op_rounds": 0, "op_kills": 0, "lobby": []}
    base.update(kw)
    return base


def test_typical_player_has_no_strong_situations():
    sit = archetypes.situations([row() for _ in range(15)])
    keys = {s["key"] for s in sit}
    assert {"opening", "close", "mid", "long", "attack", "defense", "alone", "together", "trades"} <= keys
    good, bad = archetypes.thrives(sit)
    assert good == [] and bad == []


def test_clutch_player_and_aggressive_entry():
    rows = [row(clutch={"1": [2, 2], "2": [1, 1]}, fk=6, fd=3, first_in={"attack": 6, "defense": 2}) for _ in range(8)]
    res = archetypes.analyse(rows)
    names = [x["label"] for x in res["labels"]]
    assert "Clutch player" in names and "Aggressive" in names
    clutch = next(s for s in res["situations"] if s["key"] == "clutch")
    assert "won 24 of 24 clutches" in clutch["text"] and clutch["diff"] > 0.3
    assert res["thrives"][0]["key"] == "clutch"
    assert any(s["key"] == "opening" for s in res["thrives"])


def test_small_samples_dont_count():
    sit = archetypes.situations([row(clutch={"1": [2, 2]}, retake=[3, 3])])
    assert not any(s["key"] in ("clutch", "retake") for s in sit)      # 2 clutches, 3 retakes: too few


def test_range_struggles_and_brawler():
    rows = [row(duels=[[5, 1]] * 4 + [[5, 0]] + [[30, 0]] * 3 + [[30, 1]]) for _ in range(10)]
    res = archetypes.analyse(rows)
    assert "Brawler" in [x["label"] for x in res["labels"]]
    assert res["struggles"] and res["struggles"][0]["key"] == "long"


def test_lone_wolf_and_trader():
    lone = [row(iso={"attack": [10, 8, 6, 5], "defense": [8, 5, 6, 4]}) for _ in range(6)]
    assert "Lone wolf" in [x["label"] for x in archetypes.analyse(lone)["labels"]]
    trader = [row(trade_kills=6) for _ in range(6)]
    assert "Trader" in [x["label"] for x in archetypes.analyse(trader)["labels"]]


def test_without_round_data():
    res = archetypes.analyse([dict(row(), source="stored")] * 5)
    assert res == {"labels": [], "thrives": [], "struggles": [], "situations": [], "full_games": 0}


def test_few_trades_are_never_a_weakness():
    sit = archetypes.situations([row(trade_kills=0) for _ in range(10)])
    good, bad = archetypes.thrives(sit)
    assert not any(s["key"] == "trades" for s in bad)
