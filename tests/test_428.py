"""4.28: map angles, the aim trainer's duel on a real map layout."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_427 import payload  # noqa: E402
from test_web import add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.maps import _parse_maps  # noqa: E402
from nexus.stats import mapangles as ma  # noqa: E402
from nexus.stats import trainer as tr  # noqa: E402

JS = (Path(__file__).parent.parent / "nexus" / "web" / "static" / "trainer.js").read_text()


def test_positions_have_real_directions():
    mi = next(m for m in _parse_maps(payload()) if m.name == "Ascent")
    ps = {p["id"]: p for p in ma.positions(mi)}
    hold = ps["B-hold"]
    assert hold["stand"] == "B Site" and hold["face"] == "B Main"
    by = {s["label"]: s for s in hold["spots"]}
    # B Site looks east to B Main (straight ahead); A Main is north-east (left), Mid Window south-east (right)
    assert by["B Main"]["yaw"] == 0 and by["A Main"]["yaw"] < 0 < by["Mid Window"]["yaw"]
    assert all(ma.NEAR <= s["d"] <= ma.FAR and abs(s["yaw"]) <= ma.CONE for s in hold["spots"])
    assert "A-hold" not in ps                                                  # fewer than 3 spots in front
    assert ma.positions(None) == []


def test_runs_keep_where():
    run = tr.clean_run({"scenario": "map_angles", "score": 900, "seconds": 60, "hits": 9, "shots": 11, "body": 1,
                        "escaped": 3, "where": "Ascent ·  Hold B Site, facing B Main"})
    assert run["w"] == "Ascent · Hold B Site, facing B Main" and run["escaped"] == 3
    assert "w" not in tr.clean_run({"scenario": "grid", "score": 1, "seconds": 30, "hits": 1, "shots": 1, "where": "x"})
    assert "map_angles: B.mapspots(" in JS and "body.where = st.where" in JS


def test_trainer_page_has_the_card(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    (store.data_dir / "cache" / "valorant_api_maps.json").write_text(json.dumps(payload()))
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert 'id="tr-angles"' in page and 'id="tr-ang-map"' in page
    boot = json.loads(re.search(r"window.NEXUS_TRAINER = (\{.*?\});\s*</script>", page, re.S).group(1))
    assert [p["id"] for p in boot["angles"]["Ascent"]] == ["B-hold", "B-take"]
