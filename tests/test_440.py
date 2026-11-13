"""4.40: a general replay upload (Replay files page): any match, several files, no coaching run needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus import replayfile  # noqa: E402
from nexus.web import replays as wr  # noqa: E402

MATCH_ID = "02b3659c-735e-432a-8f55-91425f8934df"          # one of this player's matches
OTHER = "12b3659c-735e-432a-8f55-91425f8934df"
OLD = "22b3659c-735e-432a-8f55-91425f8934df"


def _fake(monkeypatch):
    def fake_ingest(vrf, rdir, work, vrfkit, keep_vrf=True):
        mid = vrf.read_bytes().decode().strip()
        if mid == "broken":
            raise replayfile.ReplayError("The replay file has no player positions.")
        Path(rdir).mkdir(parents=True, exist_ok=True)
        (Path(rdir) / f"{mid}.vrf").write_bytes(b"x")
        return {"match_id": mid, "players": 10, "rounds": 24, "deaths": 150, "build": "t", "map_url": ""}
    monkeypatch.setattr(replayfile, "ingest", fake_ingest)
    rows = [{"match_id": MATCH_ID, "started_at": "2026-11-12T19:00:00Z", "map": "Haven", "agent": "Jett", "won": 1.0,
             "score": "13-9", "queue": "unrated"},
            {"match_id": OLD, "started_at": "2026-11-10T19:00:00Z", "map": "Lotus", "agent": "Sova", "won": 0.0,
             "score": "8-13", "queue": "competitive"}]
    monkeypatch.setattr(wr, "_rows", lambda _app, pid: rows)


def _upload(c, body: bytes, pid: int, name="r.vrf"):
    up = c.post("/api/replays", json={"name": name, "size": len(body)}).get_json()
    assert c.put(f"/api/uploads/{up['id']}?offset=0", data=body).get_json()["received"] == len(body)
    return c.post(f"/api/replays/{up['id']}/store?pid={pid}")


def test_upload_any_replay(app, monkeypatch):  # noqa: F811 (fixture)
    _fake(monkeypatch)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/replays").data.decode()
    assert "Upload replay files" in page and 'id="rf-file"' in page and "multiple" in page
    assert "Recent matches without a replay" in page and "Lotus" in page and "Haven" in page
    assert f'href="/profiles/{pid}/replays"' in c.get(f"/profiles/{pid}").data.decode()      # button + tab on Matches
    r = _upload(c, MATCH_ID.encode(), pid)
    d = r.get_json()
    assert r.status_code == 200 and d["ok"] and d["mine"] and d["map"] == "Haven" and d["rounds"] == 24
    r = _upload(c, OTHER.encode(), pid)                  # someone else's match: kept, no coaching needed
    assert r.status_code == 200 and r.get_json()["mine"] is False
    r = _upload(c, b"broken", pid)
    assert r.status_code == 422 and "no player positions" in r.get_json()["error"]
    page = c.get(f"/profiles/{pid}/replays").data.decode()
    mine = page.split("Your matches with a replay")[1].split("Recent matches without a replay")[0]
    assert "Haven" in mine and f"/profiles/{pid}/coach/{MATCH_ID}" in mine and "Lotus" not in mine
    assert "Replay files on the server: 2" in page and "1 from other matches" in page
    assert set(replayfile.stored(wr.replays_dir(app.extensions["nexus"]["store"]))) == {MATCH_ID, OTHER}
    assert c.post("/api/replays", json={"name": "x.mp4", "size": 10}).status_code == 400


def test_teammate_can_upload_but_not_coach(app, monkeypatch):  # noqa: F811 (fixture)
    _fake(monkeypatch)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "user_id": owner}])
    mate = make_user(app, c, "mate")
    stranger = make_user(app, c, "stranger")
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert stranger.get(f"/profiles/{pid}/replays").status_code == 404
    assert _upload(stranger, OTHER.encode(), pid).status_code == 404
    assert _upload(mate, MATCH_ID.encode(), pid).get_json()["mine"] is True
    page = mate.get(f"/profiles/{pid}/replays").data.decode()
    assert "Haven" in page and "/coach/" not in page          # coaching runs stay with the owner


def test_links_and_german(app, monkeypatch):  # noqa: F811 (fixture)
    import json
    _fake(monkeypatch)
    c = setup_admin(app)
    pid = add_profile(c)
    assert f"/profiles/{pid}/replays" in c.get(f"/profiles/{pid}/maps3d").data.decode()
    assert f"/profiles/{pid}/replays" in json.dumps(c.get("/api/search-index").get_json())
    store = app.extensions["nexus"]["store"]
    store.update_user(store.user_by_name("manuel").id, prefs=json.dumps({"lang": "de"}))
    page = c.get(f"/profiles/{pid}/replays").data.decode()
    assert "Replay-Dateien hochladen" in page and "Letzte Matches ohne Replay" in page
