"""4.36: the warm-up follows the weakest skill; map prep before a match."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_427 import payload  # noqa: E402
from test_web import add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import trainer as tr  # noqa: E402


def run(sid, **kw):
    r = {"s": sid, "score": 1000, "sec": 40, "t": 1, "d": "2026-11-01"}
    if tr.SCENARIOS[sid]["kind"] == "track":
        r["on"] = kw.pop("on", 0.5)
    else:
        r.update(hits=40, shots=50, acc=0.8, ms=450)
    r.update(kw)
    return r


def test_warmup_from_the_weakest_skill():
    assert [i["id"] for i in tr.warmup_items([])] == ["grid", "headline", "micro"]          # no ratings yet
    one = [run("track", on=0.2)] * 4
    assert [i["id"] for i in tr.warmup_items(one)] == ["grid", "headline", "micro"]         # one skill isn't enough
    runs = one + [run("flick_speed")] * 4
    assert tr.weakest_skill(runs) == "tracking"
    w = tr.plan("warmup", [], runs)
    assert [i["id"] for i in w["items"]] == ["grid", "track_smooth", "line_trace"] and w["weak"] == "Tracking"
    assert all(i["seconds"] == 30 for i in w["items"])


def test_prep_plan():
    pos = [{"id": f"p{i}", "name": f"Spot {i}"} for i in range(6)]
    p = tr.plan_prep("Ascent", pos, [run("track", on=0.2)] * 4 + [run("flick_speed")] * 4)
    ids = [i["id"] for i in p["items"]]
    assert ids[0] == "onetap_heads" and ids[1:5] == ["map_angles"] * 4 and ids[5] in tr.SKILLS["tracking"]["ladder"]
    assert p["items"][1]["angle"] == {"map": "Ascent", "id": "p0"} and p["map"] == "Ascent" and p["minutes"] <= 10


def test_trainer_page_prep(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    (store.data_dir / "cache" / "valorant_api_maps.json").write_text(json.dumps(payload()))
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/trainer?plan=prep&map=Ascent").data.decode()
    boot = json.loads(re.search(r"window.NEXUS_TRAINER = (\{.*?\});\s*</script>", page, re.S).group(1))
    assert boot["start"] == "prep_Ascent" and boot["plans"]["prep_Ascent"]["items"][1]["angle"]["id"] == "B-hold"
    assert 'id="tr-prep"' in page and boot["urls"]["callouts"].endswith("/callouts")
