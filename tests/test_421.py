"""4.21: team economy review, the Premier opponent's replay habits on match day."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent))
from test_replayfile import fake_replay  # noqa: E402
from test_web import _premier_team, _wait_stats, app, setup_admin, synthetic  # noqa: E402,F401

from nexus import replayfile  # noqa: E402
from nexus.stats import teamecon  # noqa: E402


class FakeMatch:
    """Just what teamecon reads: rounds with numbers, winners and everyone's loadout."""

    def __init__(self, rounds):
        self.rounds = rounds

    @staticmethod
    def other_team(t):
        return "Blue" if t == "Red" else "Red"


def _round(no, winner, red, blue):
    stats = {f"r{i}": NS(puuid=f"r{i}", team="Red", loadout_value=v) for i, v in enumerate(red)}
    stats.update({f"b{i}": NS(puuid=f"b{i}", team="Blue", loadout_value=v) for i, v in enumerate(blue)})
    return NS(number=no, winning_team=winner, stats=stats)


def test_team_economy_against_the_lobbies():
    full, force, eco = [4500] * 5, [2800] * 5, [500] * 5
    split = [4500, 4500, 4500, 500, 500]
    alone = [3500, 500, 500, 500, 500]                        # r0 buys while the team saves
    ms = []
    for k in range(12):
        rs = [_round(1, "Red", [800] * 5, [800] * 5),               # pistol won
              _round(2, "Blue", full, eco),                         # bonus round lost (anti-eco lost)
              _round(3, "Red", force, full),                        # force won
              _round(4, "Blue", force, full),                       # force lost ...
              _round(5, "Blue", eco, full),                         # ... and broke: eco next
              _round(6, "Blue", split, full),                       # split buy lost
              _round(7, "Red", alone, full),                        # r0 alone on rifles, won
              _round(8, "Blue", full, full)]
        ms.append((FakeMatch(rs), "Red"))
    names = {f"r{i}": f"red-{i}" for i in range(5)}
    o = teamecon.analyse(ms, names)
    assert o["games"] == 12 and o["rounds"] == 96
    k = {x["kind"]: x for x in o["kinds"]}
    assert k["pistol"]["us"]["wr"] == 1 and k["pistol"]["them"]["wr"] == 0 and k["pistol"]["v"] == "good"
    assert k["force"]["us"]["rounds"] == 36 and k["force"]["us"]["won"] == 12           # rounds 3, 4, 6 (split avg 2,900 = force)
    assert o["broke"]["us"] == 24 and o["broke"]["forces"] == 36          # rounds 4 and 6 (eco after both)
    assert o["split"]["us"]["rounds"] == 12 and o["split"]["us"]["won"] == 0
    assert o["bonus"]["us"]["rounds"] == 12 and o["bonus"]["us"]["wr"] == 0
    assert o["lost_to_buys"] == 2.0                                                     # round 4 + round 6
    r0 = next(p for p in o["players"] if p["name"] == "red-0")
    assert r0["alone_buy"]["rounds"] == 12 and r0["alone_buy"]["wr"] == 1
    texts = " | ".join(n["text"] for n in o["notes"])
    assert "Pistol rounds: 100% won" in texts and "forces were lost and left you broke" in texts
    assert "Half the team bought, half saved" in texts and "rounds per match are lost" in texts
    assert o["notes"][0]["bad"]
    f = teamecon.facts(o)
    assert f["rounds_per_match_lost_to_buys"] == 2.0 and "Pistol rounds" in f["win_rate_by_buy_vs_lobbies"]
    assert teamecon.analyse(ms[:5], names) is None and teamecon.facts(None) is None      # too few rounds


def test_economy_page_and_replays_on_match_day(app, monkeypatch):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    tid = _premier_team(app, c, monkeypatch)
    for m in store.team(tid).member_list:
        _wait_stats(app, f"import:{m['pid']}")
    page = c.get(f"/teams/{tid}/economy").data.decode()
    assert 'id="econ"' in page and "How your buys go" in page and "Lobbies" in page and "Buying with the team" in page
    assert f'href="/teams/{tid}/economy"' in c.get(f"/teams/{tid}/plans").data.decode()   # a tab of Plans & strats (4.38)

    # scout the division, then replay files of matches against the scouted team (Blue)
    c.post(f"/teams/{tid}/premier/scout", data={"division": "1"})
    assert _wait_stats(app, f"scout:{tid}")["status"] == "done"
    page = c.get(f"/teams/{tid}/premier/team/team-2").data.decode()
    assert "From your replay files" not in page                                         # none yet
    from nexus.parse import parse_match
    rdir = store.data_dir / "replays"
    maps = set()
    for f in sorted((store.data_dir / "cache" / "matches").glob("*.json"))[:6]:
        m = parse_match(json.loads(f.read_text()))
        if m.rounds:
            replayfile._write(replayfile.data_file(rdir, m.match_id), fake_replay(m))
            maps.add(m.map_name)
    mp = sorted(maps & set(store.team(tid).map_list or maps))[0]
    page = c.get(f"/teams/{tid}/premier/team/team-2").data.decode()
    assert "From your replay files" in page and "Setups, spots and utility on the map" in page
    page = c.get(f"/teams/{tid}/match?map={mp}&opp=team-2").data.decode()
    assert "From your replay files" in page and f"Write counter-plans for {mp}" in page and "usually" in page
    page = c.get(f"/teams/{tid}/premier/brief?map={mp}").data.decode()
    assert "Teams you have replay files of" in page and "replay scouting" in page
    # the Discord brief names them too
    pv = app.extensions["nexus"]
    sent = []
    import nexus.discord as dc
    monkeypatch.setattr(dc, "post", lambda url, content, embeds=None, **k: sent.append(embeds))
    store.update_team(tid, discord=json.dumps({"prep_url": "https://discord.example/prep"}))
    c.post(f"/teams/{tid}/premier/settings", data={"week_map": mp})
    r = c.post(f"/teams/{tid}/premier/brief/post", follow_redirects=True)
    assert sent, r.data.decode()[-300:]
    assert sent and "Replays of " in sent[-1][0]["description"], sent
    assert pv["replays_of"](store.team(tid), {"nobody", "x"}, mp) is None
