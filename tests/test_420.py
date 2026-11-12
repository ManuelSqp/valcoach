"""4.20: lineup suggestions from replay files, notes / strat board / Discord picture on the report's playback."""
import io
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_replayfile import data, fake_replay, map_info, match  # noqa: E402,F401
from test_web import _run_with_model, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus import replayfile  # noqa: E402
from nexus.stats import replayprep  # noqa: E402
from nexus.web import pins  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _util(owner, to=(500, 500), frm=(300, 300), typ="smoke", agent="Omen", slot="E", t=22.0):
    return [typ, agent, slot, t, "B", "B Main", *to, *frm, "B Lobby", owner]


def test_lineup_suggestions():
    def ex(mid, items, side="attack"):
        return {"ok": True, "map": "Bind", "m": 7.0, "started_at": mid,
                "roster": {"me": {"name": "adv1ce", "team": "Red", "agent": "Omen"}, "them": {"name": "x", "team": "Blue", "agent": "Omen"}},
                "rounds": [{"n": i + 1, "team": "Red", "side": side, "won": 1, "plant": "", "at": {}, "util": [u]} for i, u in enumerate(items)]}
    exs = {"m1": ex("m1", [_util("me"), _util("me", to=(510, 495)), _util("me", frm=(305, 290))]),
           "m2": ex("m2", [_util("me", to=(512, 508), t=24.0), _util("me", to=(800, 800)), _util("them"), _util("them"), _util("them")])}
    out = replayprep.lineups(exs, {"me"})["Bind"]
    assert len(out) == 1
    x = out[0]
    assert x["n"] == 4 and x["matches"] == 2 and x["agent"] == "Omen" and x["slot"] == "E" and x["type"] == "smoke"
    assert x["area"] == "B Main" and x["from_area"] == "B Lobby" and x["who"] == "adv1ce" and x["side"] == "attack"
    assert 500 <= x["to"][0] <= 512 and x["from"][0] in range(300, 306) and x["t"] in (22.0, 24.0)
    assert replayprep.lineups(exs, {"nobody"}) == {}
    # old extracts (v1: 8 fields) are skipped, not an error
    assert replayprep.lineups({"m": ex("m", [["smoke", "Omen", "E", 1.0, "B", "B Main", 1, 2]] * 4)}, {"me"}) == {}


def test_extract_knows_where_utility_was_thrown(tmp_path, data, match, map_info):  # noqa: F811 (fixtures)
    rdir = tmp_path / "replays"
    rep = fake_replay(match)
    offsets, _ = replayfile.align(rep, match)
    p = next(iter(match.players.values()))
    rep["effects"] = [[offsets[1] + 25000, offsets[1] + 40000, "Codename", "E", "smoke", "zone", 0, 0]]
    rep["casts"] = [[offsets[1] + 24000, p.puuid, 2]]
    replayfile._write(replayfile.data_file(rdir, match.match_id), rep)
    cache = tmp_path / "cache"
    shutil.copytree(data["cache"], cache)
    (cache / "matches").mkdir(exist_ok=True)
    shutil.copy(data["match"], cache / "matches" / f"{match.match_id}.json")
    ex = replayprep.for_match(rdir, cache, match.match_id, agent_names={"Codename": p.agent})
    assert ex["v"] == replayprep.VERSION == 2 and ex["m"] > 0
    u = next(x for e in ex["rounds"] for x in e["util"])
    assert len(u) == 12 and u[11] == p.puuid and u[8] is not None and u[10]
    # where he stood at the cast (24 s), from his path
    seq = replayfile.round_paths(rep, match, offsets)[1][p.puuid]
    pt = replayfile._at(seq, 24.0)
    uu, vv = map_info.to_uv(*pt)
    assert [u[8], u[9]] == [round(uu * 1000), round(vv * 1000)]


def test_pins_cleaner():
    store = {}
    assert pins.apply(store, {"t": 5000, "text": " hi ", "strokes": [[[1, 2], [3, 4]], [[5, 5]]]}, "pin", 2, "a", 1, False) is None
    p = store["2"][0]
    assert p["text"] == "hi" and p["strokes"] == [[[1, 2], [3, 4]]] and p["by_id"] == 1
    assert pins.apply(store, {"t": 1, "text": "", "strokes": []}, "pin", 2, "a", 1, False) == "write something or draw on the map"
    assert pins.apply(store, {"id": p["id"]}, "unpin", 2, "b", 2, False) == "not yours"
    assert pins.apply(store, {"id": p["id"]}, "unpin", 2, "b", 2, True) is None and store == {}
    assert pins.apply(store, {"id": "x"}, "unpin", 3, "a", 1, True) == "unknown note" and store == {}


def test_report_notes_strat_and_discord_picture(app, monkeypatch):  # noqa: F811 (fixtures)
    from nexus import discord as dc
    from nexus.web import report_tools as rt
    fb = {"summary": "Fight at A", "importance": 2, "player": {"went_well": [], "mistakes": ["Peeked alone"], "better_option": "Wait"}}
    c = setup_admin(app)
    job, _ = _run_with_model(app, c, monkeypatch, lambda n: fb)
    store = app.extensions["nexus"]["store"]
    html = c.get(f"/jobs/{job.id}/report").data.decode()
    boot = json.loads(re.search(r"window.VALCOACH_FB = (\{.*?\});</script>", html).group(1))
    assert boot["pins_url"] == f"/api/jobs/{job.id}/pins" and boot["replay_js"].startswith("/replay.js?v=")
    assert boot["strat"] is None and boot["moment_url"] == ""                  # no team yet
    api = boot["pins_url"]
    assert c.get(api).get_json() == {"pins": {}}
    d = c.post(api, json={"action": "pin", "round": 2, "t": 3000, "text": "too early", "strokes": [[[1, 1], [9, 9]]]}).get_json()
    pid = d["pins"]["2"][0]["id"]
    assert c.get(api).get_json()["pins"]["2"][0]["text"] == "too early"
    assert c.post(api, json={"action": "pin", "round": 99, "t": 1, "text": "x"}).status_code == 400
    assert c.post(api, json={"action": "nope", "round": 2}).status_code == 400
    other = make_user(app, c, "burn")
    assert other.get(api).status_code == 404 and other.post(api, json={"action": "pin", "round": 2, "t": 1, "text": "x"}).status_code == 404
    assert c.post(api, json={"action": "unpin", "round": 2, "id": pid}).get_json()["pins"] == {}
    # with a team (and its webhook): strat board and the Discord picture
    uid = store.user_by_name("manuel").id
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, members=[{"pid": job.profile_id, "kind": "starter"}], maps=["Testmap"],
                      discord=json.dumps({"clips_url": "https://discord.example/clip"}))
    html = c.get(f"/jobs/{job.id}/report").data.decode()
    boot = json.loads(re.search(r"window.VALCOACH_FB = (\{.*?\});</script>", html).group(1))
    assert boot["strat"]["team"] == "Squad" and boot["moment_url"] == f"/jobs/{job.id}/moment/discord"
    sent = []
    monkeypatch.setattr(dc, "post_file", lambda url, text, name, blob, **k: sent.append((url, text, name, blob)))
    r = c.post(boot["moment_url"], data={"png": (io.BytesIO(PNG), "m.png"), "text": "round 2 · 0:03\ntoo early"},
               content_type="multipart/form-data")
    assert r.status_code == 200 and sent[-1][0] == "https://discord.example/clip" and sent[-1][3] == PNG
    assert "too early" in sent[-1][1] and sent[-1][2] == "moment.png"
    r = c.post(boot["moment_url"], data={"png": (io.BytesIO(b"GIF89a"), "m.png")}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert c.post(boot["moment_url"], data={}, content_type="multipart/form-data").status_code == 400
    assert rt.MAX_PNG_BYTES > len(PNG)


def test_lineups_page_suggests_from_replays(app):  # noqa: F811 (fixtures)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    uid = store.user_by_name("manuel").id
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, maps=["Bind"])
    ex = {"m1": {"ok": True, "map": "Bind", "m": 7.0, "started_at": "1",
                 "roster": {"me": {"name": "adv1ce", "team": "Red", "agent": "Omen"}},
                 "rounds": [{"n": i, "team": "Red", "side": "attack", "won": 1, "plant": "", "at": {}, "util": [_util("me")]}
                            for i in range(1, 5)]}}
    app.extensions["nexus"]["team_replays"] = lambda t: (ex, {"me"})
    page = c.get(f"/teams/{tid}/lineups?map=Bind").data.decode()
    assert 'id="suggested"' in page and "Smoke B Main from B Lobby" in page and "Thrown 4× in your replay files" in page
    form = page.split('id="suggested"')[1].split("</form>")[0]
    fields = dict(re.findall(r'name="(\w+)" value="([^"]*)"', form))
    assert fields["agent"] == "Omen" and fields["side"] == "attack" and fields["site"] == "B"
    r = c.post(f"/teams/{tid}/lineups", data=fields)
    assert r.status_code == 302 and [x["title"] for x in store.lineups(tid, "Bind")] == ["Smoke B Main from B Lobby"]
    assert 'id="suggested"' not in c.get(f"/teams/{tid}/lineups?map=Bind").data.decode()      # in the library now
    app.extensions["nexus"]["team_replays"] = lambda t: (_ for _ in ()).throw(RuntimeError("x"))
    assert c.get(f"/teams/{tid}/lineups?map=Bind").status_code == 200                           # never breaks the page


def test_number_scan_matches_the_old_regex_and_stays_linear():
    import random
    import time
    from nexus.i18n import find_nums, mask_nums
    old = re.compile(r"(?<![\w#])[-+]?\d+(?:[.,'’]\d+)*(?![\w])")
    rnd = random.Random(7)
    for _ in range(20000):
        s = "".join(rnd.choice("0123456789.,'’+-#_ aZé%:/") for _ in range(rnd.randint(0, 12)))
        assert find_nums(s) == old.findall(s) and mask_nums(s, "\x00") == old.sub("\x00", s), s
    assert find_nums("1'000 Spiele, 3.5 KD, -2 RR, R2, #3") == ["1'000", "3.5", "-2"]
    t = time.time()
    find_nums("9" * 100000 + "x" + "9." * 50000)
    assert time.time() - t < 1


def test_discord_error_stays_in_the_log(app, monkeypatch):  # noqa: F811 (fixtures)
    from nexus import discord as dc
    from nexus.web.report_tools import post_moment

    def boom(*a, **k):
        raise RuntimeError("secret https://discord.com/api/webhooks/123/token")
    monkeypatch.setattr(dc, "post_file", boom)
    with app.test_request_context("/", method="POST", data={"png": (io.BytesIO(PNG), "m.png")}, content_type="multipart/form-data"):
        r, code = post_moment("https://x", "Bind")
    assert code == 502 and "secret" not in r.get_data(as_text=True) and "token" not in r.get_data(as_text=True)
