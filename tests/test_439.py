"""4.39: does training help (trainer skills vs match numbers), the mobile pass, compression and caching, 3D warm-up."""
import gzip
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import trainingeffect as te  # noqa: E402
from nexus.web import speed  # noqa: E402

TODAY = date(2026, 11, 13)
STATIC = Path(__file__).parent.parent / "nexus" / "web" / "static"
TEMPLATES = Path(__file__).parent.parent / "nexus" / "web" / "templates"


def _data(trained_every=2, hs_trained=30, hs_not=20, weeks=12, sid="onetap_heads"):
    runs, rows = [], []
    for w in range(weeks):
        mon = TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=weeks - 1 - w)
        trained = w % trained_every == 0
        if trained:
            for _ in range(4):
                runs.append({"s": sid, "d": (mon + timedelta(days=1)).isoformat(), "hits": 30 + w, "shots": 50,
                             "acc": (30 + w) / 50, "ms": 450, "sec": 40})
        for _ in range(3):
            h = hs_trained if trained else hs_not
            day = mon + timedelta(days=2)
            rows.append({"source": "full", "started_at": datetime(day.year, day.month, day.day, 18).isoformat() + "+00:00",
                         "shots": [h, 70, 10], "fk": 3, "fd": 3, "kills": 15, "deaths": 15, "rounds": 20, "won": 1,
                         "acs": 200, "kast": 14})
    return runs, rows


def by_id(res):
    return {s["id"]: s for s in res["skills"]}


def test_training_helps_and_honest_until_enough_weeks():
    res = te.check(*_data(), today=TODAY)
    one = by_id(res)["onetap"]
    assert one["metric"] == "hs" and one["verdict"] == "helps"
    assert one["compare"]["trained_weeks"] == 6 and one["compare"]["untrained_weeks"] == 6
    assert one["compare"]["diff_txt"] == "+7 points" and one["compare"]["trained_txt"] == "27%"   # 30 of 110 vs 20 of 100
    assert by_id(res)["flicks"]["verdict"] is None and by_id(res)["flicks"]["compare"]["missing"] == 3
    assert res["skills"][0]["id"] == "onetap" and res["ready"]
    # no difference -> no claim; worse -> said plainly
    assert by_id(te.check(*_data(hs_trained=25, hs_not=25), today=TODAY))["onetap"]["verdict"] == "no_link"
    assert by_id(te.check(*_data(hs_trained=15, hs_not=30), today=TODAY))["onetap"]["verdict"] == "worse"
    # two weeks of data: says how many weeks are still missing
    few = by_id(te.check(*_data(weeks=2), today=TODAY))["onetap"]
    assert few["verdict"] is None and few["compare"]["missing"] == 3 and few["together"]["missing"] == 4
    ch = few["chart"]
    assert ch["bars"] and ch["rating"] and ch["value"] and ch["last"] == "09.11"


def test_correlation_sign_and_words():
    assert abs(te._corr([1, 2, 3, 4], [2, 4, 6, 8]) - 1) < 1e-9 and te._corr([1, 1, 1], [1, 2, 3]) is None
    runs, rows = _data(trained_every=1)
    for i, r in enumerate(rows):                     # headshots rise with the rating, week by week
        r["shots"] = [10 + i, 70, 10]
    one = by_id(te.check(runs, rows, today=TODAY))["onetap"]
    assert one["together"]["r"] > 0.9 and one["together"]["words"] == "clearly together" and one["verdict"] == "helps"


def test_insights_page_shows_it(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/trainer/insights").data.decode()
    assert 'id="effect"' in page and "Does training help?" in page and "Nothing to compare yet." in page
    c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "onetap_heads", "score": 900, "seconds": 40, "hits": 30, "shots": 40})
    page = c.get(f"/profiles/{pid}/trainer/insights").data.decode()
    assert 'data-skill="onetap"' in page and "Not enough data yet" in page and "Weeks with training and games: 0 of 3" in page
    store = app.extensions["nexus"]["store"]
    store.update_user(store.user_by_name("manuel").id, prefs=json.dumps({"lang": "de"}))
    page = c.get(f"/profiles/{pid}/trainer/insights").data.decode()
    assert "Bringt das Training etwas?" in page and "Noch zu wenig Daten" in page


def test_gzip_and_cache(app):  # noqa: F811 (fixture)
    assert speed.accepts_gzip("gzip, deflate, br") and speed.accepts_gzip("*") and not speed.accepts_gzip("gzip;q=0")
    assert not speed.accepts_gzip("") and not speed.accepts_gzip("br")
    c = setup_admin(app)
    pid = add_profile(c)
    G = {"Accept-Encoding": "gzip"}
    plain = c.get(f"/profiles/{pid}/trainer")
    assert plain.headers.get("Content-Encoding") is None and "Accept-Encoding" in plain.headers.get("Vary", "")
    r = c.get(f"/profiles/{pid}/trainer", headers=G)
    assert r.headers["Content-Encoding"] == "gzip" and len(r.data) < len(plain.data) / 4
    assert b"NEXUS_TRAINER" in gzip.decompress(r.data)
    js = (STATIC / "trainer.js").read_bytes()
    r = c.get("/static/trainer.js?v=1", headers=G)
    assert r.headers["Content-Encoding"] == "gzip" and gzip.decompress(r.data) == js
    assert "max-age=31536000" in r.headers["Cache-Control"] and r.headers["ETag"].endswith('-gz"')
    r.close()
    r = c.get("/static/trainer.js?v=1", headers=G)         # from memory the second time
    assert gzip.decompress(r.data) == js
    r.close()
    r = c.get("/static/trainer.js")
    assert r.headers.get("Content-Encoding") is None and "no-cache" in r.headers["Cache-Control"] and r.data == js
    r.close()
    r = c.get("/static/icons/icon-192.png?v=1", headers=G)  # images aren't compressed, but cached
    assert r.headers.get("Content-Encoding") is None and "max-age=31536000" in r.headers["Cache-Control"]
    r.close()


def test_mobile_fixes_and_3d_touch(app):  # noqa: F811 (fixture)
    scr = (TEMPLATES / "team_scrims.html").read_text()
    assert 'class="scrim"' not in scr and ".scrim{" not in scr and 'class="sc-card"' in scr   # .scrim is the menu backdrop
    m3 = (TEMPLATES / "maps3d.html").read_text()
    assert 'id="m3-jump"' in m3 and "Tap to walk around" in m3 and "touch-action:none" in m3
    js = (STATIC / "map3d.js").read_text()
    assert "touchstart" in js and "touchKeys" in js
    css = (STATIC / "app.css").read_text()
    assert "@media(max-width:700px){.ptabs{gap:2px}" in css and ".ptabs{flex-wrap:nowrap}" not in css
    c = setup_admin(app)
    pid = add_profile(c)
    assert 'id="m3-jump"' in c.get(f"/profiles/{pid}/maps3d").data.decode()
    warm = app.extensions["nexus"]["maps3d_warm"]
    warm()                                               # no replays: nothing to do, no error
    assert warm in app.extensions["nexus"]["ticks"]
