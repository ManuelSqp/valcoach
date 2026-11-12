"""4.23: the aim trainer's scenario library."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import trainer as tr  # noqa: E402

JS = (Path(__file__).parent.parent / "nexus" / "web" / "static" / "trainer.js").read_text()
FOCUS = {"flicks", "switching", "warmup", "crosshair", "micro", "peeking", "reaction", "tracking", "spray"}


def test_every_scenario_has_both_halves():
    body = JS[JS.index("const SC = {"):JS.index("const PART = {")]
    in_js = set(re.findall(r"^    (\w+): ", body, re.M)) - {"kind"}
    assert in_js == set(tr.SCENARIOS), (in_js ^ set(tr.SCENARIOS))
    assert len(tr.SCENARIOS) >= 40
    for sid, sc in tr.SCENARIOS.items():
        assert sc["group"] in tr.GROUPS and sc["level"] in tr.LEVELS, sid
        assert sc["kind"] in ("click", "track") and 10 <= sc["seconds"] <= 120, sid
        assert set(sc["focus"]) <= FOCUS and sc["focus"], sid
        assert len(sc["about"]) > 20 and sc["name"], sid
    names = [sc["name"] for sc in tr.SCENARIOS.values()]
    assert len(names) == len(set(names))
    for g in tr.GROUPS:
        assert any(sc["group"] == g for sc in tr.SCENARIOS.values()), g
    # the old ids are still there (saved runs keep their scenario)
    assert {"grid", "headline", "micro", "peek", "holdangle", "track", "track_react"} <= set(tr.SCENARIOS)


def test_new_scenarios_save_runs_and_join_training():
    run = tr.clean_run({"scenario": "double_tap", "score": 2100, "seconds": 45, "hits": 40, "shots": 44, "ms": 380})
    assert run and run["s"] == "double_tap" and run["acc"] == round(40 / 44, 3)
    assert tr.clean_run({"scenario": "orbit_air", "score": 620, "seconds": 45, "on_target": 0.62})["on"] == 0.62
    assert tr.clean_run({"scenario": "angle_runners", "score": 900, "seconds": 45, "hits": 9, "shots": 12, "body": 2,
                         "escaped": 5})["escaped"] == 5
    assert tr.clean_run({"scenario": "nope", "score": 1, "seconds": 45}) is None
    p = tr.plan("training", [{"focus": ["tracking", "micro"], "weight": 3, "key": "aim", "why": "aim"}], [])
    assert p["items"] and all(i["id"] in tr.SCENARIOS for i in p["items"])
    s = {x["id"]: x for x in tr.summary([run])}
    assert s["double_tap"]["runs"] == 1 and s["six_shot"]["runs"] == 0 and len(s) == len(tr.SCENARIOS)


def test_library_page(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert "Scenario library" in page and 'id="tr-search"' in page and 'data-f="level"' in page
    assert page.count('class="tr-card"') == len(tr.SCENARIOS)
    for g, name in tr.GROUPS.items():
        assert f'data-v="{g}">{name} <span>' in page
    assert 'data-play="orbit_vert"' in page and "Hard</span>" in page
