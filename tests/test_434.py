"""4.34: the owner links a teammate's account to their player; the comp sheet says how to get linked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus import replayfile  # noqa: E402


def test_owner_links_a_teammate(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}])
    mate = make_user(app, c, "mate")
    uid = store.user_by_name("mate").id
    store.add_team_access(tid, uid)
    sheet = mate.get(f"/teams/{tid}/sheet").data.decode()
    assert "Not linked" in sheet and ">Edit</a>" not in sheet
    assert "Plays as" in c.get(f"/teams/{tid}/settings").data.decode()
    c.post(f"/teams/{tid}/access", data={"link": str(uid), "pid": str(pid)})
    assert store.team(tid).member_list[0]["user_id"] == uid
    sheet = mate.get(f"/teams/{tid}/sheet").data.decode()
    assert "Not linked" not in sheet and ">Edit</a>" in sheet
    c.post(f"/teams/{tid}/access", data={"link": str(uid), "pid": ""})            # unlink
    assert "user_id" not in store.team(tid).member_list[0]
    assert c.post(f"/teams/{tid}/access", data={"link": "999", "pid": str(pid)}).status_code == 400   # not in the team
    assert mate.post(f"/teams/{tid}/access", data={"link": str(uid), "pid": str(pid)}).status_code == 403


def test_replay_notes():
    assert replayfile.SAMPLE_MS == 100 and "Unrated, Competitive, Swiftplay or Premier" in replayfile.__doc__
