"""4.24: 57 more aim trainer scenarios (100 in all), the drill types of the big aim trainers in our own versions."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import trainer as tr  # noqa: E402

ROOT = Path(__file__).parent.parent
JS = (ROOT / "nexus" / "web" / "static" / "trainer.js").read_text()
DE = json.loads((ROOT / "nexus" / "i18n" / "de.json").read_text(encoding="utf-8"))
NEW = ["bounce_shot", "jink", "hops", "horde", "shrinking", "flick_180", "spider_180", "burst", "friend_foe",
       "side_vision", "popups", "line_trace", "arc_track", "star_track", "circle_track", "blink_track", "tswitch",
       "tswitch_evasive", "track_zigzag", "triple_tap"]


def test_hundred_scenarios_both_halves():
    body = JS[JS.index("const SC = {"):JS.index("const PART = {")]
    in_js = set(re.findall(r"^    (\w+): ", body, re.M)) - {"kind"}
    assert in_js == set(tr.SCENARIOS) and len(tr.SCENARIOS) == 100
    assert set(NEW) <= set(tr.SCENARIOS)
    for b in ("bounce", "burst", "popups", "glide", "tswitch"):
        assert f"function {b}(o)" in JS, b
    assert {"moving", "trackswitch"} <= set(tr.GROUPS)
    assert all(tr.SCENARIOS[s]["group"] == "trackswitch" for s in tr.SCENARIOS if s.startswith("tswitch"))
    for g in tr.GROUPS:
        assert sum(sc["group"] == g for sc in tr.SCENARIOS.values()) >= 4, g
    for lvl in tr.LEVELS:
        assert sum(sc["level"] == lvl for sc in tr.SCENARIOS.values()) >= 15, lvl


def test_german_for_every_scenario():
    for sid, sc in tr.SCENARIOS.items():
        assert sc["name"] in DE and sc["about"] in DE, sid
    for label in list(tr.GROUPS.values()) + ["Blue ones hit", "Targets down"]:
        assert label in DE, label
    assert not any("ß" in v for v in DE.values())


def test_new_runs_are_stored():
    run = tr.clean_run({"scenario": "friend_foe", "score": 3100, "seconds": 45, "hits": 30, "shots": 36, "ms": 420})
    assert run and run["acc"] == round(30 / 36, 3)
    assert tr.clean_run({"scenario": "tswitch_evasive", "score": 540, "seconds": 45, "on_target": 0.54})["on"] == 0.54
    assert tr.clean_run({"scenario": "line_trace", "score": 10, "seconds": 45}) is None      # tracking needs on_target
    p = tr.plan("training", [{"focus": ["switching", "tracking"], "weight": 3, "key": "aim", "why": "aim"}], [])
    assert len(p["items"]) == 6 and all(i["id"] in tr.SCENARIOS for i in p["items"])


def test_library_page_shows_all(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert page.count('class="tr-card"') == 100
    assert 'data-v="moving">Moving targets <span>' in page and 'data-v="trackswitch">Switch tracking <span>' in page
    assert 'data-play="friend_foe"' in page and 'data-play="tswitch_float"' in page
