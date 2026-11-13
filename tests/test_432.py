"""4.32: train one skill (sessions up a ladder, adaptive rounds, ratings) and one-tap scenarios."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import trainer as tr  # noqa: E402

JS = (Path(__file__).parent.parent / "nexus" / "web" / "static" / "trainer.js").read_text()


def run(sid, d="2026-11-01", **kw):
    r = {"s": sid, "score": 1000, "sec": 40, "t": 1, "d": d}
    if tr.SCENARIOS[sid]["kind"] == "track":
        r["on"] = kw.pop("on", 0.5)
    else:
        r.update(hits=kw.pop("hits", 40), shots=kw.pop("shots", 50), ms=kw.pop("ms", 450))
        r["acc"] = round(r["hits"] / r["shots"], 3)
    r.update(kw)
    return r


def test_one_taps_and_ladders():
    one = [s for s, x in tr.SCENARIOS.items() if x["group"] == "onetap"]
    assert len(one) == 7 and all(f"    {s}: " in JS for s in one)
    assert "miss(st)" in JS and "if (H().miss) H().miss(st)" in JS
    for k, sk in tr.SKILLS.items():
        assert all(s in tr.SCENARIOS for s in sk["ladder"]), k
        levels = [tr.SCENARIOS[s]["level"] for s in sk["ladder"]]
        assert levels[0] == min(levels) and levels[-1] == 3, k              # easy first, hard last
    r = tr.clean_run({"scenario": "onetap_heads", "score": 900, "seconds": 40, "hits": 30, "shots": 36, "escaped": 6, "k": [0.92, 1.07]})
    assert r["escaped"] == 6 and r["k"] == [0.92, 1.07]
    assert "k" not in tr.clean_run({"scenario": "grid", "score": 1, "seconds": 30, "hits": 1, "shots": 1, "k": [1, 1]})
    assert "k" not in tr.clean_run({"scenario": "grid", "score": 1, "seconds": 30, "hits": 1, "shots": 1, "k": [9, 1]})


def test_sessions_start_where_you_are():
    p = tr.plan_skill("tracking", 10, [])
    assert p["adaptive"] and p["kind"] == "skill:tracking" and p["items"][0]["id"] == "track_smooth"
    assert p["minutes"] <= 10 and all(x["seconds"] == 40 for x in p["items"])
    # steady on the first three: starts at the fourth, after a warm-up round on the easiest
    runs = [run(s, score=1000, on=0.6) for s in tr.SKILLS["tracking"]["ladder"][:4] for _ in range(6)]
    p = tr.plan_skill("tracking", 20, runs)
    ids = [x["id"] for x in p["items"]]
    assert ids[0] == "track_smooth" and p["items"][0]["why"] == "warm-up" and ids[1] == tr.SKILLS["tracking"]["ladder"][4]
    # skill-session rounds made harder don't set bests
    s = {x["id"]: x for x in tr.summary([run("grid", score=500), run("grid", score=9000, k=[0.8, 1.2])])}
    assert s["grid"]["best"] == 500


def test_ratings():
    runs = [run("track", d=f"2026-11-0{i}", on=0.4 + i * 0.05) for i in range(1, 6)]
    runs += [run("onetap_heads", hits=30, shots=40, escaped=10)]
    r = tr.skill_ratings(runs)
    lvl = 0.85                                                                # "track" is an easy one
    assert r["tracking"]["rating"] == round(100 * lvl * sum(0.4 + i * 0.05 for i in range(1, 6)) / 5)
    assert r["tracking"]["change"] == round(100 * lvl * 0.65) - round(100 * lvl * 0.45) and len(r["tracking"]["days"]) == 5
    assert r["onetap"]["rating"] == round(100 * 0.75 * 0.75 * 0.85)       # accuracy x share of heads hit x easy
    assert r["micro"]["rating"] is None
    harder = tr.skill_ratings([run("track", on=0.5, k=[0.81, 1.21])])["tracking"]["rating"]
    assert harder > tr.skill_ratings([run("track", on=0.5)])["tracking"]["rating"]


def test_trainer_page_has_skills(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert 'id="tr-skills"' in page and 'data-plan="skill_onetap_20"' in page
    boot = json.loads(re.search(r"window.NEXUS_TRAINER = (\{.*?\});\s*</script>", page, re.S).group(1))
    assert boot["plans"]["skill_peeks_30"]["adaptive"] and "warmup" in boot["plans"]
    assert 'data-v="onetap">One taps <span>' in page
