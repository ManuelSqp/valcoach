"""4.27: Practice › Callouts, the minimap quiz."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.maps import _parse_maps  # noqa: E402
from nexus.stats import callouts as co  # noqa: E402

NAMES = [("A", "Site"), ("A", "Main"), ("A", "Lobby"), ("A", "Heaven"), ("B", "Site"), ("B", "Main"), ("B", "Back"),
         ("Mid", "Top"), ("Mid", "Bottom"), ("Mid", "Window"), ("Mid", "Catwalk"), ("Defender Side", "Market"),
         ("Attacker Side", "Spawn"), ("Defender Side", "Spawn")]


def payload(name="Ascent"):
    pay = synth.maps_payload()
    m = pay["data"][1]
    m["displayName"] = name
    # spread them over the minimap: world (x, y) from uv through the synthetic transform
    pts = []
    for i, (s, r) in enumerate(NAMES):
        u, v = 0.3 + 0.4 * (i % 4) / 3, 0.3 + 0.4 * (i // 4) / 3
        pts.append({"regionName": r, "superRegionName": s,
                    "location": {"x": (v - synth.Y_ADD) / synth.Y_MULT, "y": (u - synth.X_ADD) / synth.X_MULT}})
    m["callouts"] = pts
    return pay


class Reg:
    def __init__(self, maps):
        self.maps = {m.name: m for m in maps}

    def get(self, map_id="", name=""):
        return self.maps.get(name)


def test_points_runs_and_weights():
    reg = Reg(_parse_maps(payload()))
    maps = co.quiz_maps(reg, ["Ascent", "Nowhere"])
    assert list(maps) == ["Ascent"]
    pts = maps["Ascent"]
    assert len(pts) == 12 and not any("Spawn" in p["label"] for p in pts)        # spawns are left out
    assert all(0 <= p["u"] <= 1 and 0 <= p["v"] <= 1 for p in pts)
    asked = [{"label": p["label"], "ok": i != 0, "ms": 1200} for i, p in enumerate(pts[:6])]
    run = co.clean_run({"map": "Ascent", "mode": "find", "asked": asked}, maps)
    assert run["right"] == 5 and run["total"] == 6 and run["score"] == 5 * (100 + 38)
    assert co.clean_run({"map": "Ascent", "mode": "find", "asked": [{"label": "Nope", "ok": True}]}, maps) is None
    assert co.clean_run({"map": "Ascent", "mode": "guess", "asked": asked}, maps) is None
    data = {}
    assert co.add_run(data, run)["is_best"]
    run2 = co.clean_run({"map": "Ascent", "mode": "find", "asked": asked}, maps)
    co.add_run(data, run2)
    first = pts[0]["label"]
    assert data["miss"]["Ascent"][first] == [2, 2] and "asked" not in data["runs"][0]
    assert co.weak(data, "Ascent") == [first]
    w = co.weights(data, "Ascent", pts)
    assert w[first] > w[pts[1]["label"]]                 # the one you get wrong comes up more often
    s = co.summary(data, maps)[0]
    assert s["known"] == 5 and s["weak"][0]["label"] == first and s["modes"]["find"]["best"] == run["score"]


def test_page_and_saving(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    (store.data_dir / "cache" / "valorant_api_maps.json").write_text(json.dumps(payload()))
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/callouts").data.decode()
    assert 'href="/profiles/%d/callouts"' % pid in page or "Callouts</span>" in page          # in the menu
    boot = json.loads(re.search(r"NEXUS_CALLOUTS = (\{.*?\});</script>", page, re.S).group(1))
    assert boot["map"] == "Ascent" and len(boot["maps"]["Ascent"]["points"]) == 12
    pts = boot["maps"]["Ascent"]["points"]
    r = c.post(f"/profiles/{pid}/callouts/runs", json={"map": "Ascent", "mode": "name",
                                                       "asked": [{"label": p["label"], "ok": True, "ms": 900} for p in pts[:4]]})
    assert r.status_code == 200 and r.get_json()["is_best"] and r.get_json()["n"] == 12
    assert c.post(f"/profiles/{pid}/callouts/runs", json={"map": "Ascent", "mode": "name", "asked": []}).status_code == 400
    stored = json.loads((store.data_dir / "profiles" / str(pid) / "stats" / "callouts.json").read_text())
    assert stored["runs"][0]["right"] == 4
    page = c.get(f"/profiles/{pid}/callouts?map=Ascent").data.decode()
    assert "Your maps" in page and "Name it: best" in page
    # someone else can't save into this player's results
    other = make_user(app, c, "other")
    assert other.post(f"/profiles/{pid}/callouts/runs", json={"map": "Ascent", "mode": "name", "asked": []}).status_code in (403, 404)


def test_no_map_data(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/callouts").data.decode()
    assert "No map data yet" in page or "NEXUS_CALLOUTS" in page
