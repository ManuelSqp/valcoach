"""4.33: the aim trainer's sandbox, scenarios people make from the trainer's builders."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import sandbox as sbx  # noqa: E402
from nexus.stats import trainer as tr  # noqa: E402

JS = (Path(__file__).parent.parent / "nexus" / "web" / "static" / "trainer.js").read_text()


def test_every_type_has_a_builder_and_clamps():
    for t in sbx.TYPES:
        sc, err = sbx.clean({"type": t, "name": "x", "params": {}})
        assert sc, (t, err)
        b = sbx.builder_options(sc)["builder"]
        names = JS[JS.index("const BUILD = {") + 15:JS.index("};", JS.index("const BUILD = {"))].split(", ")
        assert b in names, (t, b)
    sc, _ = sbx.clean({"type": "bounce", "name": "  My   bouncers ", "seconds": 999, "level": 7, "skill": "nope",
                       "params": {"n": 99, "r": "big", "smin": 6, "smax": 2, "jink": True, "grav": "yes", "evil": "<script>"}})
    assert sc["name"] == "My bouncers" and sc["seconds"] == 120 and sc["level"] == 3 and sc["skill"] == ""
    p = sc["params"]
    assert p["n"] == 8 and p["r"] == 0.3 and (p["smin"], p["smax"]) == (2, 6) and p["jink"] is True and p["grav"] is False
    assert "evil" not in p
    o = sbx.builder_options(sc)["o"]
    assert o["jink"] == [0.35, 0.9] and "grav" not in o and "life" not in o
    assert sbx.builder_options(sbx.clean({"type": "tracker", "name": "j", "params": {"jump": True}})[0])["builder"] == "strafer"
    assert sbx.builder_options(sbx.clean({"type": "popups", "name": "p", "params": {}})[0])["o"]["every"] == [0.35, 0.7]
    assert sbx.clean({"type": "laser", "name": "x"})[0] is None and sbx.clean({"type": "flicks", "name": " "})[0] is None


def test_codes_round_trip():
    sc, _ = sbx.clean({"type": "onetap", "name": "Heads on B", "skill": "onetap", "level": 3, "params": {"n": 2, "r": 0.12}})
    code = sbx.code(sc)
    back, err = sbx.decode(code)
    assert back == sc and code.startswith("NX1-")
    assert sbx.decode("NX1-%%%")[0] is None and sbx.decode("KovaaKsSomething")[0] is None
    assert sbx.decode("NX1-" + "A" * 4000)[0] is None


def test_save_play_share_and_skills(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    url = f"/profiles/{pid}/trainer/sandbox"
    dry = c.post(url, json={"type": "glide", "name": "Try", "params": {"path": "star"}, "dry": True}).get_json()
    assert dry["item"]["id"] == "c_try" and dry["item"]["builder"] == "glide" and dry["item"]["o"]["path"] == "star"
    assert not (store.data_dir / "sandbox").exists()                         # trying saves nothing
    r = c.post(url, json={"type": "onetap", "name": "My heads", "skill": "onetap", "level": 1, "params": {"n": 2}}).get_json()
    sid = r["item"]["id"]
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    boot = json.loads(re.search(r"window.NEXUS_TRAINER = (\{.*?\});\s*</script>", page, re.S).group(1))
    item = next(x for x in boot["sandbox"]["items"] if x["id"] == sid)
    assert item["builder"] == "onetap" and item["code"].startswith("NX1-") and item["mine"]
    assert sid in [x["id"] for x in boot["plans"]["skill_onetap_30"]["items"]]      # joins the skill's sessions
    # its runs count
    assert c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": sid, "score": 800, "seconds": 45, "hits": 20,
                                                          "shots": 25, "escaped": 5}).status_code == 200
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert "Best</span> 800" in page
    # share it with a team; a teammate sees and plays it but can't change it; the code works for anyone
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}])
    c.post(url, json={"id": sid, "from": "me", "scope": f"team:{tid}", "type": "onetap", "name": "My heads", "params": {"n": 2}})
    assert json.loads((store.data_dir / "teams" / str(tid) / "sandbox.json").read_text())["items"][0]["id"] == sid
    assert json.loads((store.data_dir / "sandbox" / f"user-{owner}.json").read_text())["items"] == []
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    mp = mate.get(f"/profiles/{pid}/trainer").data.decode()
    mboot = json.loads(re.search(r"window.NEXUS_TRAINER = (\{.*?\});\s*</script>", mp, re.S).group(1))
    mi = next(x for x in mboot["sandbox"]["items"] if x["id"] == sid)
    assert not mi["can_edit"] and mi["team"] == "Squad"
    assert mate.post(f"{url}/{sid}/delete", json={"scope": f"team:{tid}"}).status_code == 404
    assert mate.post(url, json={"code": mi["code"]}).get_json()["item"]["name"] == "My heads"   # a copy of her own
    assert mate.post(url, json={"type": "flicks", "name": "x", "scope": "team:999"}).status_code == 403
    assert c.post(f"{url}/{sid}/delete", json={"scope": f"team:{tid}"}).get_json()["ok"]
    assert tr.SCENARIOS and sid not in tr.SCENARIOS
