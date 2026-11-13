"""4.35: 3D maps rebuilt from replay positions."""
import gzip
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from test_web import MATCH_ID, add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.maps import _parse_maps  # noqa: E402
from nexus.stats import map3d as m3  # noqa: E402

UUID = "0e1d2c3b-4a59-4687-9a1b-2c3d4e5f6a7b"


def corridor_replay(players=6, seed=1):
    """A 4 m wide corridor (60 m long) at floor height 0, a ramp up 3 m and a platform: positions as a replay has
    them (world units, cm). On the synthetic map 100 world units are one metre."""
    random.seed(seed)
    pos = {}
    for p in range(players):
        off, pts, t = random.uniform(-180, 180), [], 0
        for y in range(-3000, 3000, 60):
            pts.append([t, off, y, 0.0, 0.0]); t += 100
        for y in range(3000, 3500, 60):
            pts.append([t, off, y, (y - 3000) / 500 * 300, 0.0]); t += 100
        for y in range(3500, 4500, 60):
            pts.append([t, off, y, 300.0, 0.0]); t += 100
        pos[f"p{p}"] = pts
    return {"format": 1, "pos": pos}


def test_rebuild_floors_ramps_and_levels():
    mi = next(m for m in _parse_maps(synth.maps_payload()) if m.name == "Testmap")
    r = m3.rebuild(mi, [corridor_replay()], "Testmap")
    cells = r["cells"]
    low = [c for c in cells if c[2] < 0.3]
    high = [c for c in cells if c[2] > 2.7]
    ramp = [c for c in cells if 0.6 < c[2] < 2.4]
    assert low and high and ramp
    widths = {}
    for c in low:
        widths.setdefault(c[0], set()).add(c[1])
    w = sorted(len(v) for v in widths.values())[len(widths) // 2] * m3.CELL
    assert 3.0 <= w <= 5.5, w                               # the corridor is about 4 m wide (paths spread and filled)
    assert r["matches"] == 1 and r["samples"] > 500 and len(r["callouts"]) == 8
    # two floors in one cell when one is high enough above the other
    assert m3._levels([0.0, 0.1, 0.05, 3.2, 3.3]) == [0.0, 3.2]
    assert m3._levels([0.0, 0.1, 0.2, 0.3, 1.0]) == [0.1]   # a jump doesn't make a second floor
    assert m3.area_kind("A") == 1 and m3.area_kind("Attacker Side") == 3 and m3.area_kind("Mid") == 2


def test_page_and_data(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/maps3d").data.decode()
    assert "No replay files on the server yet" in page and "map3d.js" in page
    shutil.copy(store.data_dir / "cache" / "matches" / f"{MATCH_ID}.json", store.data_dir / "cache" / "matches" / f"{UUID}.json")
    (store.data_dir / "replays").mkdir(parents=True, exist_ok=True)
    with gzip.open(store.data_dir / "replays" / f"{UUID}.json.gz", "wt", encoding="utf-8") as f:
        json.dump(corridor_replay(), f)
    page = c.get(f"/profiles/{pid}/maps3d").data.decode()
    assert 'data-map="Testmap"' in page and "No replay files" not in page
    d = c.get("/api/maps3d/Testmap").get_json()
    assert d["matches"] == 1 and d["cells"] and d["ids"] == [UUID]
    assert (store.data_dir / "maps3d" / "testmap.json").is_file()          # cached until the replays change
    assert c.get("/api/maps3d/Ascent").status_code == 404
    assert c.get("/api/maps3d/..%2Fx").status_code == 404
