"""4.37: the weekly aim report and the team's aim board with a weekly challenge."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import aimweek as aw  # noqa: E402

TODAY = date(2026, 11, 13)                          # a Friday; the week started Monday the 9th


def run(sid, d, **kw):
    r = {"s": sid, "score": kw.pop("score", 1000), "sec": 40, "t": 1, "d": d.isoformat()}
    if sid.startswith("track"):
        r["on"] = kw.pop("on", 0.5)
    else:
        r.update(hits=40, shots=50, acc=0.8, ms=450)
    r.update(kw)
    return r


def test_report():
    last_week = TODAY - timedelta(days=7)
    runs = [run("track", last_week, on=0.3) for _ in range(4)] + [run("track", TODAY, on=0.7, score=1200) for _ in range(4)]
    runs += [run("grid", last_week, score=2000), run("grid", TODAY, score=2500), run("grid", TODAY, score=9000, k=[0.8, 1.2])]
    rep = aw.report(runs, today=TODAY)
    assert rep["week"] == "2026-W46" and rep["runs"] == 6 and rep["days"] == 1 and rep["minutes"] == 4
    tracking = next(s for s in rep["skills"] if s["id"] == "tracking")
    assert tracking["change"] > 0 and tracking["played"] == 4
    assert [b["id"] for b in rep["bests"]] == ["grid", "track"] and rep["bests"][0]["best"] == 2500   # adapted round left out
    assert rep["next"]["why"] in ("weakest", "untried")


def test_challenge_and_board():
    assert aw.challenge_of({}, "2026-W46") in aw.CHALLENGES
    assert aw.challenge_of({"2026-W46": "spider"}, "2026-W46") == "spider"
    a = {"name": "A", "pid": 1, "runs": [run("grid", TODAY, score=3000), run("grid", TODAY, score=3500)]}
    b = {"name": "B", "pid": 2, "runs": [run("grid", TODAY, score=4000), run("grid", TODAY - timedelta(days=8), score=9999)]}
    c = {"name": "C", "pid": 3, "runs": []}
    bd = aw.board([a, b, c], "grid", today=TODAY)
    assert [(x["name"], x["best"], x["tries"]) for x in bd["leaderboard"]] == [("B", 4000, 1), ("A", 3500, 2)]
    emb = aw.discord_embeds("Squad", bd, "Grid flicks")
    assert "Grid flicks" in emb[0]["description"] and "🥇 **B** 4000" in emb[0]["description"]


def test_pages(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "grid", "score": 3000, "seconds": 45, "hits": 40, "shots": 45})
    aim = c.get(f"/profiles/{pid}/aim").data.decode()
    assert 'id="week"' in aim and "1 run<" in aim
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "user_id": owner}])
    page = c.get(f"/teams/{tid}/aimboard").data.decode()
    assert "Challenge of the week" in page and "Leaderboard" in page
    c.post(f"/teams/{tid}/aimboard", data={"challenge": "grid"})
    page = c.get(f"/teams/{tid}/aimboard").data.decode()
    assert "Grid flicks" in page and "3000" in page and f"/profiles/{pid}/trainer?play=grid" in page
    assert c.post(f"/teams/{tid}/aimboard", data={"challenge": "nope"}).status_code == 400
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert mate.get(f"/teams/{tid}/aimboard").status_code == 200
    assert mate.post(f"/teams/{tid}/aimboard", data={"challenge": "spider"}).status_code == 403
    r = c.post(f"/teams/{tid}/aimboard", data={"post": "1"}, follow_redirects=True).data.decode()
    assert "No Discord channel set" in r
    assert json.loads((store.data_dir / "teams" / str(tid) / "aimboard.json").read_text())["challenges"]
