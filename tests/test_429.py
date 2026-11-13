"""4.29: Practice › Sound, hearing where a sound comes from."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import sound as so  # noqa: E402


def test_scoring_front_back_and_sectors():
    run = so.clean_run({"mode": "height", "sounds": [
        {"a": 10, "guess": 20, "h": "up", "h_guess": "up"},            # 10° off, height right
        {"a": 20, "guess": 160, "h": "down", "h_guess": "level"},      # heard behind instead of in front
        {"a": 270, "guess": 250, "h": "level", "h_guess": "level"}]})
    assert run["n"] == 3 and run["fb"] == 1 and run["right"] == 2
    assert run["err"] == round((10 + 140 + 20) / 3, 1)
    assert run["score"] == round((100 - 15 + 50) + 0 + (100 - 30 + 50))
    assert so.clean_run({"mode": "dir", "sounds": [{"a": "x", "guess": 1}]}) is None
    assert so.clean_run({"mode": "loud", "sounds": [{"a": 1, "guess": 1}]}) is None
    data = {}
    assert so.add_run(data, run)["is_best"] and "sounds" not in data["runs"][0]
    assert data["sec"][0] == [150.0, 2] and data["sec"][6] == [20.0, 1]   # in front: 10 + 140 (a=10, a=20); left: 20
    s = so.summary(data)
    assert s["modes"]["height"]["rounds"] == 1 and s["modes"]["height"]["right"] == round(2 / 3, 2)
    assert s["fb"] == 1 and s["sectors"][0]["err"] == 75.0 and s["sectors"][0]["d"].startswith("M0,0")


def test_page_and_saving(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/sound").data.decode()
    assert "NEXUS_SOUND" in page and "Your hearing" in page and "sound.js" in page
    r = c.post(f"/profiles/{pid}/sound/runs", json={"mode": "dir", "sounds": [{"a": a, "guess": a + 5} for a in range(0, 360, 30)]})
    assert r.status_code == 200 and r.get_json()["err"] == 5.0
    assert c.post(f"/profiles/{pid}/sound/runs", json={"mode": "dir", "sounds": []}).status_code == 400
    assert json.loads((store.data_dir / "profiles" / str(pid) / "stats" / "sound.json").read_text())["runs"][0]["n"] == 12
    assert "Direction" in c.get(f"/profiles/{pid}/sound").data.decode()
    other = make_user(app, c, "other")
    assert other.post(f"/profiles/{pid}/sound/runs", json={"mode": "dir", "sounds": []}).status_code in (403, 404)
