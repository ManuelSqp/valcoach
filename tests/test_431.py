"""4.31: VOD review, a match recording watched together with timed comments and drawings."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import MATCH_ID, add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import vodreview as vr  # noqa: E402


def test_clean_notes_and_rounds():
    good = {"t": 61.5, "text": "  Rotate   earlier ", "strokes": [{"c": vr.COLORS[0], "k": "arrow", "p": [[0.1, 0.2], [0.5, 0.5]]},
                                                              {"c": "#123456", "p": [[0, 0], [1, 1]]},       # not one of ours
                                                              {"c": vr.COLORS[1], "p": [[0.2, 0.2]]},        # one point
                                                              {"c": vr.COLORS[2], "k": "laser", "p": [[0, 0], [1, 1]]}]}
    n, err = vr.clean_note(good)
    assert n == {"t": 61.5, "text": "Rotate earlier", "strokes": [{"c": vr.COLORS[0], "k": "arrow", "p": [[0.1, 0.2], [0.5, 0.5]]}]}
    assert vr.clean_note({"t": 5, "text": "", "strokes": []})[0] is None
    assert vr.clean_note({"t": -1, "text": "x"})[0] is None and vr.clean_note({"t": True, "text": "x"})[0] is None
    assert vr.clean_note({"t": 1, "strokes": [{"c": vr.COLORS[0], "p": [[0, 0], [9, 9]]}]})[0] is None   # off the frame
    rounds = vr.rounds_of({"rounds": [{"number": 1, "vod": {"start": 10}, "team_facts": {"won": True}},
                                      {"number": 2, "vod": None}, {"number": 3, "vod": {"start": 120.4}}]})
    assert rounds == [{"n": 1, "t": 10.0, "won": True}, {"n": 3, "t": 120.4, "won": False}]
    assert vr.round_at(5, rounds) is None and vr.round_at(60, rounds) == 1 and vr.round_at(200, rounds) == 3
    data = {}
    vr.add_note(data, n, 1, "me", rounds)
    vr.add_note(data, dict(n, t=12.0), 1, "me", rounds)
    assert [x["t"] for x in data["notes"]] == [12.0, 61.5] and data["notes"][1]["round"] == 1


def test_review_page_comments_and_team_access(app, synthetic):  # noqa: F811 (fixtures)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    store.create_job("vr1", pid, MATCH_ID, "both", vod_path=str(synthetic["vod"]), vod_name="match.mp4")
    store.create_job("novod", pid, MATCH_ID, "both")
    page = c.get("/jobs/vr1/review").data.decode()
    assert "NEXUS_VR" in page and "vodreview.js" in page
    assert c.get("/jobs/novod/review").status_code == 404
    v = c.get("/jobs/vr1/review/video", headers={"Range": "bytes=0-99"})
    assert v.status_code == 206 and len(v.data) == 100
    assert "Review the recording together" in c.get("/jobs/vr1").data.decode()
    r = c.post("/api/jobs/vr1/review/notes", json={"t": 3.2, "text": "Wide swing here", "strokes": []})
    assert r.status_code == 200 and r.get_json()["note"]["by"]
    nid = r.get_json()["note"]["id"]
    assert c.post("/api/jobs/vr1/review/notes", json={"t": 3.2, "text": ""}).status_code == 400
    # a teammate (in a team with this player) can watch and comment, but not remove the owner's comment
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}])
    mate = make_user(app, c, "mate")
    assert mate.get("/jobs/vr1/review").status_code == 404                  # not in the team yet
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert mate.get("/jobs/vr1/review").status_code == 200
    assert mate.get("/jobs/vr1/review/video").status_code == 200
    m = mate.post("/api/jobs/vr1/review/notes", json={"t": 8, "text": "I should have traded"}).get_json()
    assert len(m["notes"]) == 2
    assert mate.post(f"/api/jobs/vr1/review/notes/{nid}/delete").status_code == 403
    assert mate.post(f"/api/jobs/vr1/review/notes/{m['note']['id']}/delete").status_code == 200
    # the team's recordings list
    rec = mate.get(f"/teams/{tid}/recordings").data.decode()
    assert "/jobs/vr1/review" in rec and "1 comment<" in rec and "/jobs/novod/review" not in rec
    # the owner removes any comment
    assert c.post(f"/api/jobs/vr1/review/notes/{nid}/delete").get_json()["notes"] == []
    assert json.loads((store.data_dir / "vodreview" / "vr1.json").read_text())["notes"] == []
