"""4.18: you vs your rank, opponent tendencies from replay files, notes on the playback, a moment as a strat board."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_replayfile import data, fake_replay, map_info, match  # noqa: E402,F401
from test_web import app, synthetic  # noqa: E402,F401

from nexus import replayfile  # noqa: E402
from nexus.stats import games, peers, replayprep  # noqa: E402


# ---------------------------------------------------------------------------- you vs your rank
def _row(tier="Gold 2", peers_=None, **kw):
    r = {"source": "full", "tier": tier, "rounds": 20, "acs": 250.0, "kills": 18, "deaths": 12, "assists": 4,
         "adr": 160.0, "shots": [30, 60, 10], "kast": 15, "fk": 4, "fd": 2, "agent": "Jett"}
    r.update(kw)
    r["peers"] = peers_ if peers_ is not None else (
        [[13, 200.0, 0.7, 0.72, 0.25, 135.0, 0.2, 0.7, 2, 2]] * 8 + [[16, 240.0, 0.82, 0.66, 0.3, 155.0, 0.25, 0.74, 3, 2]] * 2)
    return r


def test_you_vs_your_rank():
    rows = [_row() for _ in range(6)]
    a = peers.analyse(rows)
    assert a["rank"] == "Gold 2" and a["games"] == 6 and a["same"] == 48 and a["next"] == 0     # 12 a rank higher: too few
    m = {x["key"]: x for x in a["metrics"]}
    assert m["acs"]["you"] == "250" and m["acs"]["same"] == "200" and m["acs"]["v_same"] == "good"
    assert m["dpr"]["v_same"] == "good"                        # 0.60 deaths per round vs 0.72: fewer is better
    assert m["opr"]["v_same"] == ""                            # opening duels: depends on the role
    assert m["hs"]["you"] == "30%" and m["hs"]["same"] == "20%"
    assert m["kast"]["you"] == "75%" and m["kast"]["v_same"] == "good"   # 75 vs 70 %: 5 points
    assert a["hints"][0].startswith("Better than your rank in ")
    # a rank higher once there are enough of them
    rows = [_row(peers_=[[13, 200.0, 0.7, 0.72, 0.25, 135.0, 0.2, 0.7, 2, 2]] * 5 + [[15, 300.0, 1.0, 0.6, 0.3, 190.0, 0.3, 0.8, 3, 1]] * 5)
            for _ in range(6)]
    a = peers.analyse(rows)
    assert a["next"] == 30 and any(h.startswith("The biggest step to the next rank is ") for h in a["hints"])
    f = peers.facts(rows)
    assert f["rank"] == "Gold 2" and "ACS" in f["you_vs_your_rank"] and "a rank higher" in f["you_vs_your_rank"]["ACS"]
    # too little: nothing
    assert peers.analyse(rows[:3]) is None
    assert peers.analyse([_row(peers_=[[13, 200.0, 0.7, 0.72, 0.25, 135.0, 0.2, 0.7, 2, 2]]) for _ in range(6)]) is None
    assert peers.analyse([_row(tier="") for _ in range(6)]) is None


def test_peer_numbers_from_a_match(match):                 # noqa: F811 (fixtures)
    me = match.find_player("adv1ce", "LFT").puuid
    ps = games.peer_metrics(match, me)
    assert len(ps) == len(match.players) - 1
    for p in ps:
        assert p[0] == 15 and len(p) == 10 and 0 <= p[7] <= 1 and p[8] >= 0 and p[9] >= 0
    assert sum(p[8] for p in ps) + sum(1 for r in match.rounds if r.kills and r.kills[0].killer == me) == \
        sum(1 for r in match.rounds if r.kills and r.kills[0].killer)
    row = games.row_from_match(match, me, None)
    assert row["v"] == games.ROW_VERSION >= 7 and row["peers"] == ps


# ---------------------------------------------------------------------------- replay scouting
def _stored(tmp_path, data, match, with_effects=True):                 # noqa: F811 (fixtures)
    rdir = tmp_path / "replays"
    rep = fake_replay(match)
    if with_effects:
        offsets, _ = replayfile.align(rep, match)
        p = next(iter(match.players.values()))
        rep["effects"] = [[offsets[i] + 25000, offsets[i] + 40000, "Codename", "E", "smoke", "zone", 0, 0]
                          for i in range(len(match.rounds))]
        rep["casts"] = []
        names = {"Codename": p.agent}
    else:
        names = {}
    replayfile._write(replayfile.data_file(rdir, match.match_id), rep)
    cache = tmp_path / "cache"
    shutil.copytree(data["cache"], cache)
    (cache / "matches").mkdir(exist_ok=True)
    shutil.copy(data["match"], cache / "matches" / f"{match.match_id}.json")
    return rdir, cache, names


def test_replay_scouting_tendencies(tmp_path, data, match):                 # noqa: F811 (fixtures)
    rdir, cache, names = _stored(tmp_path, data, match)
    ex = replayprep.for_match(rdir, cache, match.match_id, agent_names=names)
    assert ex["ok"] and ex["map"] == match.map_name and replayprep.prep_file(rdir, match.match_id).exists()
    assert len(ex["rounds"]) == 2 * len(match.rounds)
    assert all("20" in e["at"] or e["plant"] for e in ex["rounds"])
    # cached: read again without the replay
    assert replayprep.for_match(rdir, cache, match.match_id) == json.loads(replayprep.prep_file(rdir, match.match_id).read_text())
    me = match.find_player("adv1ce", "LFT")
    ours = {p.puuid for p in match.players_on(me.team)}
    opps = replayprep.opponents({match.match_id: ex}, ours, {match.match_id: "Their Team"})
    assert len(opps) == 1 and opps[0]["label"] == "Their Team" and opps[0]["matches"] == [match.match_id]
    them = set(opps[0]["puuids"])
    assert them == {p.puuid for p in match.players.values() if p.team != me.team}
    a = replayprep.analyse({match.match_id: ex}, them, 20)
    d = a[match.map_name]
    assert d["matches"] == 1
    sides = [s for s in ("attack", "defense") if s in d]
    assert sides and sum(d[s]["rounds"] for s in sides) == len(match.rounds)
    for s in sides:
        x = d[s]
        assert x["setups"] and x["spots"] and x["points"] and all(len(p) == 3 for p in x["points"])
        assert sum(c for _, c in x["setups"]) == x["with_pos"]
    # the smoke belongs to the team of the agent "Codename" maps to
    owner_team = next(iter(match.players.values())).team
    smoke_side = [s for s in sides if any(u["type"] == "smoke" for u in d[s]["util"])]
    assert bool(smoke_side) == (owner_team != me.team)
    if "attack" in d:
        assert sum(c for _, c in d["attack"]["plants"]) == d["attack"]["rounds"]
    assert isinstance(replayprep.hints(a, min_rounds=1), list) and replayprep.hints(a, min_rounds=1)
    # your own team the same way; a roster with fewer than 2 players in a match: nothing
    assert replayprep.analyse({match.match_id: ex}, ours, 10)[match.map_name]["matches"] == 1
    assert replayprep.analyse({match.match_id: ex}, {me.puuid}, 20) == {}
    # no replay / not cached: None
    assert replayprep.for_match(tmp_path / "none", cache, match.match_id) is None


def test_replay_scouting_groups_the_same_team():
    def ex(mid, ours, them, started):
        roster = {p: {"name": p, "team": "Blue", "agent": "Jett"} for p in ours}
        roster.update({p: {"name": p, "team": "Red", "agent": "Sova"} for p in them})
        return {"ok": True, "map": "Bind", "started_at": started, "roster": roster, "rounds": []}
    ours = ["u1", "u2", "u3"]
    exs = {"m1": ex("m1", ours, ["a", "b", "c", "d", "e"], "1"), "m2": ex("m2", ours, ["a", "b", "c", "x", "y"], "2"),
           "m3": ex("m3", ours, ["p", "q", "r", "s", "t"], "3"), "m4": ex("m4", ["u1", "z"], ["a", "b", "c", "d", "e"], "4")}
    opps = replayprep.opponents(exs, set(ours))
    assert [len(o["matches"]) for o in opps] == [2, 1]
    assert set(opps[0]["puuids"]) == {"a", "b", "c", "d", "e", "x", "y"} and opps[0]["label"].endswith("…")


# ---------------------------------------------------------------------------- web
def test_web_rank_scouting_notes_and_strat(app):                 # noqa: F811 (fixtures)
    import test_web as tw
    c = tw.setup_admin(app)
    store = app.extensions["nexus"]["store"]
    raw = json.loads((store.data_dir / "cache" / "matches" / f"{tw.MATCH_ID}.json").read_text())
    players = raw.get("data", raw)["players"]
    side = players[0]["team_id"]
    ours = [p for p in players if p["team_id"] == side][:2]
    pids = [tw.add_profile(c, name=p["name"], tag="#" + p["tag"]) for p in ours]
    uid = store.user_by_name("manuel").id
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "puuid": p["puuid"], **({"user_id": uid} if i == 0 else {})}
                                    for i, (pid, p) in enumerate(zip(pids, ours))], maps=["Testmap"])
    sr = app.extensions["nexus"]["stats"]
    for pid, p in zip(pids, ours):                # the members' games know the match (the synthetic id isn't a UUID)
        gs = sr.games(pid)
        d = gs.load()
        d["games"][tw.MATCH_ID] = {"match_id": tw.MATCH_ID, "source": "full", "map": "Testmap", "started_at": "2026-10-20"}
        gs.save(d)
    # replay scouting: nothing stored yet, then one replay file
    page = c.get(f"/teams/{tid}/replay-scouting").data.decode()
    assert "No replay files yet" in page and "Replay scouting" in page
    from nexus.parse import parse_match
    m = parse_match(raw)
    rdir = store.data_dir / "replays"
    replayfile._write(replayfile.data_file(rdir, m.match_id), fake_replay(m))
    page = c.get(f"/teams/{tid}/replay-scouting").data.decode()
    assert 'id="defense"' in page and 'id="attack"' in page and "Setup at 20 s" in page and "Spots taken most" in page
    assert "your team" in page
    page = c.get(f"/teams/{tid}/replay-scouting?who=us&at=45&map=nope").data.decode()
    assert "45 s into the round" in page
    # review evening: the playback uses the replay file, notes, a moment as a strat board
    r = c.post(f"/teams/{tid}/review-evening", data={"match_id": tw.MATCH_ID})
    sid = r.headers["Location"].rstrip("/").split("/")[-1]
    page = c.get(f"/teams/{tid}/review-evening/{sid}").data.decode()
    boot = json.loads(page.split('id="ev-boot">')[1].split("</script>")[0])
    assert boot["uid"] == uid and boot["to_strat"].endswith("/strats/from-replay") and boot["state"]["pins"] == {}
    rp = c.get(f"/teams/{tid}/review-evening/{sid}/replay.json").get_json()
    assert rp["v"] == 2 and rp["source"] == "replay file"
    api = f"/api/teams/{tid}/review-evening/{sid}"
    st = c.post(api, json={"action": "pin", "round": 2, "t": 15400, "text": " watch <b>mid</b> ",
                           "strokes": [[[100, 100], [200, 220], ["x", 1]], [[5, 5]], "bad"]}).get_json()
    pin = st["pins"]["2"][0]
    assert pin["text"] == "watch <b>mid</b>" and pin["t"] == 15400 and pin["strokes"] == [[[100, 100], [200, 220]]]
    assert c.post(api, json={"action": "pin", "round": 2, "t": 1000, "text": "", "strokes": []}).status_code == 400
    assert c.post(api, json={"action": "pin", "round": 99, "t": 1000, "text": "x"}).status_code == 400
    mate = tw.make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    st = mate.post(api, json={"action": "pin", "round": 2, "t": 9000, "text": "mine", "strokes": []}).get_json()
    assert [p["text"] for p in st["pins"]["2"]] == ["mine", "watch <b>mid</b>"]          # by time
    assert mate.post(api, json={"action": "unpin", "round": 2, "id": pin["id"]}).status_code == 403
    mine = st["pins"]["2"][0]["id"]
    assert mate.post(api, json={"action": "unpin", "round": 2, "id": mine}).status_code == 200
    st = c.post(api, json={"action": "unpin", "round": 2, "id": pin["id"]}).get_json()          # the host may
    assert st["pins"] == {}
    # strat board from a moment
    body = {"map": "Testmap", "side": "attack", "name": "Testmap R2 0:15", "notes": "From the review",
            "items": [{"t": "agent", "a": "Jett", "x": 100, "y": 200, "c": "us", "label": "adv1ce"},
                      {"t": "ab", "a": "Omen", "s": "Ability2", "x": 300, "y": 300, "c": "them"},
                      {"t": "pen", "pts": [[1, 2], [3, 4]], "c": "us"}, {"t": "evil", "x": 1}, "junk"]}
    r = c.post(f"/api/teams/{tid}/strats/from-replay", json=body)
    url = r.get_json()["url"]
    sid2 = int(url.rstrip("/").split("/")[-1])
    s = store.strat(sid2)
    assert s["map"] == "Testmap" and s["side"] == "attack" and s["data"]["notes"] == "From the review"
    assert [i["t"] for i in s["data"]["steps"][0]["items"]] == ["agent", "ab", "pen"]
    assert c.post(f"/api/teams/{tid}/strats/from-replay", json={**body, "map": "Nowhere"}).status_code == 400
    assert c.post(f"/api/teams/{tid}/strats/from-replay", data="x").status_code == 400
    stranger = tw.make_user(app, c, "stranger")
    assert stranger.post(f"/api/teams/{tid}/strats/from-replay", json=body).status_code == 404
    assert stranger.get(f"/teams/{tid}/replay-scouting").status_code == 404
