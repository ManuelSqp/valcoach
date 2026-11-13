import io
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from nexus.web import create_app  # noqa: E402

MATCH_ID = "synthetic-match-0001"
ADMIN_PW = "admin-pass-123"


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    return synth.write_all(tmp_path_factory.mktemp("websynth"), with_vod=True, n_rounds=6)


def prepare_data(data: Path, synthetic) -> None:
    cache = data / "cache"
    (cache / "matches").mkdir(parents=True, exist_ok=True)
    shutil.copy(synthetic["cache"] / "valorant_api_maps.json", cache / "valorant_api_maps.json")
    shutil.copy(synthetic["match"], cache / "matches" / f"{MATCH_ID}.json")


@pytest.fixture()
def app(tmp_path, synthetic):
    data = tmp_path / "data"
    prepare_data(data, synthetic)
    vods = tmp_path / "recordings" / "Valorant"
    vods.mkdir(parents=True)
    shutil.copy(synthetic["vod"], vods / "Valorant 2026-10-20 19-17.mp4")
    app = create_app(data)
    app.config["TESTING"] = True
    store = app.extensions["nexus"]["store"]
    store.set("henrik_api_key", "HDEV-test")
    store.set("minimap_roi", ", ".join(map(str, synth.MM_ROI)))
    store.set("killfeed_roi", ", ".join(map(str, synth.KF_ROI)))
    store.set("sample_fps", "2")
    store.set("search_provider", "")          # no web search from tests (tests that need it fake it)
    app.recordings = str(tmp_path / "recordings")
    yield app
    app.extensions["nexus"]["runner"].shutdown()


def setup_admin(app, username="manuel"):
    c = app.test_client()
    r = c.post("/setup", data={"username": username, "password": ADMIN_PW, "password2": ADMIN_PW})
    assert r.status_code == 302, r.data
    store = app.extensions["nexus"]["store"]
    store.update_user(store.user_by_name(username).id, vod_dir=app.recordings)
    return c


def login(app, username, password):
    c = app.test_client()
    r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 302, r.data
    return c


def make_user(app, admin_client, username, password="user-pass-123", **extra):
    r = admin_client.post("/admin/users", data={"username": username, "password": password, **extra})
    assert r.status_code == 302
    return login(app, username, password)


def send_upload(client, data: bytes, name="clip.mp4"):
    """What the coach page's script does: ask to start, then send the file in chunks."""
    r = client.post("/api/uploads", json={"name": name, "size": len(data)})
    assert r.status_code == 200, r.data
    uid, chunk = r.json["id"], r.json["chunk"]
    for offset in range(0, len(data), chunk):
        r = client.put(f"/api/uploads/{uid}?offset={offset}", data=data[offset:offset + chunk])
        assert r.status_code == 200 and r.json["received"] == min(offset + chunk, len(data))
    return uid


def wait_job(client, jid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = client.get(f"/api/jobs/{jid}").get_json()
        if d["status"] in ("done", "error"):
            return d
        time.sleep(0.5)
    raise TimeoutError(jid)


def add_profile(client, name="adv1ce", tag="#LFT"):
    r = client.post("/profiles/new", data={"name": name, "tag": tag, "region": "eu", "platform": "pc",
                                           "mode": "both", "language": "English",
                                           "playbook": "principles: ['trade every entry']"})
    assert r.status_code == 302, r.data
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


# ---------------------------------------------------------------------------
def test_first_start_requires_setup(app):
    c = app.test_client()
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/setup")
    assert b"Create the admin account" in c.get("/setup").data
    r = c.post("/setup", data={"username": "ab", "password": "x", "password2": "x"})
    assert b"3 to 32" in r.data
    r = c.post("/setup", data={"username": "manuel", "password": ADMIN_PW, "password2": "nope-nope"})
    assert b"match" in r.data
    r = c.post("/setup", data={"username": "manuel", "password": ADMIN_PW, "password2": ADMIN_PW})
    assert r.status_code == 302
    assert c.get("/").status_code == 200
    # setup is closed once an account exists
    assert app.test_client().get("/setup").headers["Location"].endswith("/login")


def test_pages_render(app):
    c = setup_admin(app)
    assert b"Your players" in c.get("/").data
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/edit")
    assert page.status_code == 200 and b"trade every entry" in page.data
    s = c.get("/settings")
    assert s.status_code == 200 and b"set (" in s.data and b"HDEV-test" not in s.data
    assert c.get("/admin/users").status_code == 200
    assert c.get("/account").status_code == 200
    # duplicate Riot ID in the same workspace rejected
    r = c.post("/profiles/new", data={"name": "ADV1CE", "tag": "lft", "region": "eu", "platform": "pc",
                                      "mode": "both", "language": "English", "playbook": ""})
    assert b"already have a player" in r.data
    r = c.post(f"/profiles/{pid}/edit", data={"name": "adv1ce", "tag": "LFT", "region": "eu", "platform": "pc",
                                              "mode": "both", "language": "English", "playbook": "a: [unclosed"})
    assert b"not valid YAML" in r.data


def test_workspaces_are_isolated(app):
    admin = setup_admin(app)
    alice = make_user(app, admin, "alice")
    bob = make_user(app, admin, "bob")
    pa = add_profile(alice)
    pb = add_profile(bob)                       # same Riot ID is fine in another workspace
    assert pa != pb
    ja = alice.post(f"/profiles/{pa}/coach/{MATCH_ID}", data={"mode": "player", "vod": "", "no_llm": "1"})
    jid = ja.headers["Location"].split("/")[-1]
    assert wait_job(alice, jid)["status"] == "done"

    # bob sees nothing of alice's workspace
    assert b"adv1ce" in bob.get("/").data       # his own profile
    for url in (f"/profiles/{pa}", f"/profiles/{pa}/edit", f"/profiles/{pa}/coach/{MATCH_ID}",
                f"/profiles/{pa}/notes/{MATCH_ID}", f"/jobs/{jid}", f"/api/jobs/{jid}",
                f"/jobs/{jid}/report", f"/jobs/{jid}/vod"):
        assert bob.get(url).status_code == 404, url
    for url in (f"/profiles/{pa}/delete", f"/jobs/{jid}/delete", f"/jobs/{jid}/retry"):
        assert bob.post(url).status_code == 404, url
    assert jid.encode() not in bob.get("/").data
    # admin doesn't see it either (workspaces are private)
    assert admin.get(f"/jobs/{jid}").status_code == 404
    # alice still has it
    assert alice.get(f"/jobs/{jid}/report").status_code == 200

    # normal users can't open admin pages
    for url in ("/settings", "/admin/users", "/admin/users/1"):
        assert bob.get(url).status_code == 403, url
    assert bob.post("/admin/users", data={"username": "evil", "password": "evil-pass-1"}).status_code == 403
    assert b"Users" not in bob.get("/").data.split(b"</nav>")[0]


def test_full_job_with_vod_and_notes(app):
    c = setup_admin(app)
    pid = add_profile(c)
    r = c.post(f"/profiles/{pid}/notes/{MATCH_ID}", data={"round_2": "Entry was not traded", "round_3": ""})
    assert r.status_code == 302
    page = c.get(f"/profiles/{pid}/coach/{MATCH_ID}")
    assert b"Valorant 2026-10-20 19-17.mp4" in page.data
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}",
               data={"mode": "both", "vod": "Valorant/Valorant 2026-10-20 19-17.mp4", "no_llm": "1"})
    jid = r.headers["Location"].split("/")[-1]
    d = wait_job(c, jid)
    assert d["status"] == "done", d["log"]
    assert "Sync: offset 37.3" in d["log"]
    html = c.get(d["report_url"]).data.decode()
    assert f'src="/jobs/{jid}/vod"' in html and 'id="r6"' in html
    v = c.get(f"/jobs/{jid}/vod", headers={"Range": "bytes=0-1023"})
    assert v.status_code == 206 and len(v.data) == 1024
    store = app.extensions["nexus"]["store"]
    job = store.job(jid)
    report = json.loads(Path(job.json_path).read_text())
    assert report["rounds"][1]["own_note"] == "Entry was not traded"
    assert report["rounds"][0]["minimap"]
    assert c.post(f"/jobs/{jid}/delete").status_code == 302
    assert store.job(jid) is None and not Path(job.html_path).exists()


def test_recordings_folder_is_per_user(app):
    admin = setup_admin(app)
    bob = make_user(app, admin, "bob")             # no recordings folder
    pid = add_profile(bob)
    page = bob.get(f"/profiles/{pid}/coach/{MATCH_ID}")
    assert b"19-17.mp4" not in page.data and b"upload the file" in page.data
    # can't pick the admin's file by guessing the path either
    r = bob.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "Valorant/Valorant 2026-10-20 19-17.mp4"})
    assert b"not in your recordings folder" in bob.get(r.headers["Location"]).data
    # upload lands in bob's own upload folder
    r = bob.post(f"/profiles/{pid}/coach/{MATCH_ID}",
                 data={"mode": "team", "vod": "upload", "no_llm": "1", "no_minimap": "1",
                       "upload_id": send_upload(bob, b"\x00" * 2048)})
    jid = r.headers["Location"].split("/")[-1]
    store = app.extensions["nexus"]["store"]
    assert f"/uploads/{store.user_by_name('bob').id}/" in store.job(jid).vod_path


def test_upload_and_bad_inputs(app):
    c = setup_admin(app)
    pid = add_profile(c)
    r = c.post("/api/uploads", json={"name": "evil.exe", "size": 1})
    assert r.status_code == 400 and "Unsupported video type" in r.json["error"]
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "upload"})
    assert b"Choose a video file" in c.get(r.headers["Location"]).data
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "../../etc/passwd"})
    assert b"not in your recordings folder" in c.get(r.headers["Location"]).data
    pid2 = add_profile(c, "someone", "ELSE")
    r = c.get(f"/profiles/{pid2}/coach/{MATCH_ID}")
    assert b"is not in this match" in c.get(r.headers["Location"]).data


def test_two_users_share_the_queue(app):
    admin = setup_admin(app)
    bob = make_user(app, admin, "bob")
    pa = add_profile(admin)
    pb = add_profile(bob, "blue-0", "T")
    j1 = admin.post(f"/profiles/{pa}/coach/{MATCH_ID}", data={"mode": "player", "vod": "", "no_llm": "1"})
    j2 = bob.post(f"/profiles/{pb}/coach/{MATCH_ID}", data={"mode": "team", "vod": "", "no_llm": "1"})
    id1, id2 = (r.headers["Location"].split("/")[-1] for r in (j1, j2))
    assert wait_job(admin, id1)["status"] == "done"
    assert wait_job(bob, id2)["status"] == "done"
    store = app.extensions["nexus"]["store"]
    a = json.loads(Path(store.job(id1).json_path).read_text())
    b = json.loads(Path(store.job(id2).json_path).read_text())
    assert a["meta"]["player"] == "adv1ce#LFT" and b["meta"]["player"] == "blue-0#T"


def test_login_lockout_and_password_change(app):
    admin = setup_admin(app)
    make_user(app, admin, "bob", "bob-pass-123")
    c = app.test_client()
    for _ in range(5):
        assert c.post("/login", data={"username": "bob", "password": "wrong"}).status_code == 401
    r = c.post("/login", data={"username": "bob", "password": "bob-pass-123"})
    assert r.status_code == 429                         # locked even with the right password
    other_ip = app.test_client()
    r = other_ip.post("/login", data={"username": "bob", "password": "bob-pass-123"},
                      environ_base={"REMOTE_ADDR": "10.0.0.9"})
    assert r.status_code == 302

    # two sessions; changing the password logs the other one out
    s1 = login(app, "manuel", ADMIN_PW)
    s2 = login(app, "manuel", ADMIN_PW)
    r = s1.post("/account", data={"current": ADMIN_PW, "password": "new-pass-456", "password2": "new-pass-456"})
    assert r.status_code == 302
    assert s1.get("/").status_code == 200
    assert s2.get("/").status_code == 302
    assert app.test_client().post("/login", data={"username": "manuel", "password": ADMIN_PW}).status_code == 401
    login(app, "manuel", "new-pass-456")
    # wrong current password
    r = s1.post("/account", data={"current": "nope", "password": "x" * 10, "password2": "x" * 10})
    assert b"current password is wrong" in s1.get("/account").data


def test_admin_user_management(app):
    admin = setup_admin(app)
    bob = make_user(app, admin, "bob")
    store = app.extensions["nexus"]["store"]
    bob_id = store.user_by_name("bob").id
    me_id = store.user_by_name("manuel").id
    # duplicate / invalid
    admin.post("/admin/users", data={"username": "BOB", "password": "whatever-123"})
    assert len(store.users()) == 2
    admin.post("/admin/users", data={"username": "x y", "password": "whatever-123"})
    assert len(store.users()) == 2
    # admin can't demote or disable themselves, or delete themselves
    admin.post(f"/admin/users/{me_id}", data={"vod_dir": ""})
    assert store.user(me_id).is_admin == 1
    admin.post(f"/admin/users/{me_id}/delete")
    assert store.user(me_id) is not None
    # disable bob -> his session ends and he can't log in
    admin.post(f"/admin/users/{bob_id}", data={"disabled": "1", "vod_dir": ""})
    assert bob.get("/").status_code == 302
    assert app.test_client().post("/login", data={"username": "bob", "password": "user-pass-123"}).status_code == 401
    # re-enable with a new password, promote to admin
    admin.post(f"/admin/users/{bob_id}", data={"is_admin": "1", "vod_dir": "", "new_password": "fresh-pass-1"})
    bob = login(app, "bob", "fresh-pass-1")
    assert bob.get("/settings").status_code == 200
    # delete bob with his workspace
    pid = add_profile(bob)
    r = bob.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "", "no_llm": "1"})
    wait_job(bob, r.headers["Location"].split("/")[-1])
    admin.post(f"/admin/users/{bob_id}/delete")
    assert store.user(bob_id) is None and store.profile(pid) is None
    assert not store.profile_dir(pid).exists()
    assert bob.get("/").status_code == 302


def test_signup_toggle(app):
    admin = setup_admin(app)
    c = app.test_client()
    assert c.get("/signup").status_code == 404
    assert b"Ask the admin" in c.get("/login").data
    admin.post("/settings", data={
        "ollama_url": "http://127.0.0.1:1", "ollama_model": "m", "ollama_temperature": "0.3",
        "ollama_num_ctx": "16384", "ollama_parallel": "4", "ollama_timeout_s": "300",
        "minimap_roi": "0.012, 0.025, 0.215, 0.382", "killfeed_roi": "0.7,0.08,0.29,0.25", "sample_fps": "4",
        "workers": "1", "allow_signup": "1"})
    assert b"Create one" in c.get("/login").data
    r = c.post("/signup", data={"username": "newbie", "password": "newbie-pass", "password2": "newbie-pass"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/profiles/new")
    store = app.extensions["nexus"]["store"]
    assert store.user_by_name("newbie").is_admin == 0
    assert c.get("/settings").status_code == 403
    r = app.test_client().post("/signup", data={"username": "NEWBIE", "password": "x" * 9, "password2": "x" * 9})
    assert b"taken" in r.data


def test_api_requires_login(app):
    setup_admin(app)
    c = app.test_client()
    assert c.get("/api/jobs/x").status_code == 401
    r = c.get("/profiles/1")
    assert r.status_code == 302 and "/login?next=/profiles/1" in r.headers["Location"]
    r = login(app, "manuel", ADMIN_PW)
    c2 = app.test_client()
    r = c2.post("/login?next=//evil.example", data={"username": "manuel", "password": ADMIN_PW})
    assert r.headers["Location"] == "/"
    # logout is POST only (no logout-by-link)
    assert c2.get("/logout").status_code in (404, 405)
    c2.post("/logout")
    assert c2.get("/").status_code == 302


def test_migration_from_v21_database(tmp_path, synthetic):
    """A database from the version without accounts: profiles + reports move to the new admin."""
    data = tmp_path / "old"
    prepare_data(data, synthetic)
    db = sqlite3.connect(data / "nexus.db")
    db.executescript("""
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE profiles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE,
      tag TEXT NOT NULL COLLATE NOCASE, region TEXT NOT NULL DEFAULT 'eu', platform TEXT NOT NULL DEFAULT 'pc',
      mode TEXT NOT NULL DEFAULT 'both', language TEXT NOT NULL DEFAULT 'English',
      playbook TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(name, tag));
    CREATE TABLE jobs (id TEXT PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      match_id TEXT NOT NULL, map TEXT NOT NULL DEFAULT '', score TEXT NOT NULL DEFAULT '',
      started_at_match TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL, vod_path TEXT NOT NULL DEFAULT '',
      vod_name TEXT NOT NULL DEFAULT '', options TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'queued',
      log TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', html_path TEXT NOT NULL DEFAULT '',
      json_path TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, started_at TEXT NOT NULL DEFAULT '',
      finished_at TEXT NOT NULL DEFAULT '');
    INSERT INTO settings VALUES ('henrik_api_key', 'HDEV-old'), ('vod_dir', '/tmp'), ('access_password_hash', 'x'),
      ('secret_key', 'abc'), ('seeded', '1');
    INSERT INTO profiles(id, name, tag, playbook, created_at) VALUES (7, 'adv1ce', 'LFT', 'principles: [x]', '2026-10-27');
    INSERT INTO jobs(id, profile_id, match_id, mode, status, map, created_at)
      VALUES ('oldjob', 7, 'synthetic-match-0001', 'both', 'done', 'Testmap', '2026-10-27');
    """)
    db.commit()
    db.close()

    app = create_app(data, start_workers=False)
    store = app.extensions["nexus"]["store"]
    assert store.job("oldjob") is not None            # rebuild didn't cascade-delete jobs
    assert store.profile(7).owner_id is None
    c = app.test_client()
    page = c.get("/setup")
    assert b"existing 1 player" in page.data
    r = c.post("/setup", data={"username": "manuel", "password": ADMIN_PW, "password2": ADMIN_PW})
    assert r.status_code == 302
    uid = store.user_by_name("manuel").id
    assert store.profile(7).owner_id == uid
    assert store.user(uid).vod_dir == "/tmp"
    assert store.get("henrik_api_key") == "HDEV-old" and store.get("access_password_hash") == ""
    assert b"adv1ce" in c.get("/").data
    assert c.get("/jobs/oldjob").status_code == 200
    app.extensions["nexus"]["runner"].shutdown()


def test_restart_recovers_jobs(tmp_path):
    data = tmp_path / "d"
    app = create_app(data, start_workers=False)
    store = app.extensions["nexus"]["store"]
    uid = store.create_user("manuel", ADMIN_PW, is_admin=True)
    pid = store.create_profile(uid, "adv1ce", "LFT")
    store.create_job("run1", pid, MATCH_ID, "both")
    store.update_job("run1", status="running")
    app.extensions["nexus"]["runner"].shutdown()
    app2 = create_app(data)
    assert app2.extensions["nexus"]["store"].job("run1").status == "error"
    app2.extensions["nexus"]["runner"].shutdown()


def test_seed_from_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[player]\nname = "adv1ce"\ntag = "LFT"\n[henrik]\napi_key = "HDEV-x"\n'
                   '[ollama]\nmodel = "qwen3:30b"\n')
    app = create_app(tmp_path / "d", config_seed=cfg, start_workers=False)
    store = app.extensions["nexus"]["store"]
    assert store.get("henrik_api_key") == "HDEV-x" and store.get("ollama_model") == "qwen3:30b"
    c = app.test_client()
    c.post("/setup", data={"username": "manuel", "password": ADMIN_PW, "password2": ADMIN_PW})
    assert [p.riot_id for p in store.profiles(store.user_by_name("manuel").id)] == ["adv1ce#LFT"]
    app.extensions["nexus"]["runner"].shutdown()


def test_player_order(app):
    admin = setup_admin(app)
    bob = make_user(app, admin, "bob")
    store = app.extensions["nexus"]["store"]
    me = store.user_by_name("manuel").id
    a = add_profile(admin, "zed", "Z")
    b = add_profile(admin, "adv1ce", "LFT")
    c = add_profile(admin, "teammate", "X")
    assert [p.id for p in store.profiles(me)] == [a, b, c]          # new players go to the end

    r = admin.post("/api/profiles/order", json={"order": [b, c, a]})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert [p.name for p in store.profiles(me)] == ["adv1ce", "teammate", "zed"]
    html = admin.get("/").data.decode()
    assert html.index('data-pid="%d"' % b) < html.index('data-pid="%d"' % c) < html.index('data-pid="%d"' % a)
    d = add_profile(admin, "newest", "N")
    assert store.profiles(me)[-1].id == d

    # invalid orders are rejected and change nothing
    bad = [{"order": [b, c]}, {"order": [b, b, c, a, d]}, {"order": [b, c, a, d, 999]},
           {"order": "b,c"}, {"nope": 1}]
    for body in bad:
        assert admin.post("/api/profiles/order", json=body).status_code == 400, body
    assert admin.post("/api/profiles/order", data={"order": [b, c, a, d]}).status_code == 400   # form post
    pb = add_profile(bob, "bobs", "B")
    assert admin.post("/api/profiles/order", json={"order": [b, c, a, d, pb]}).status_code == 400
    assert bob.post("/api/profiles/order", json={"order": [a]}).status_code == 400
    assert [p.name for p in store.profiles(me)] == ["adv1ce", "teammate", "zed", "newest"]
    assert app.test_client().post("/api/profiles/order", json={"order": []}).status_code == 401


def test_migration_from_v22_adds_order(tmp_path):
    data = tmp_path / "v22"
    data.mkdir()
    db = sqlite3.connect(data / "nexus.db")
    db.executescript("""
    CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
      password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, vod_dir TEXT NOT NULL DEFAULT '',
      session_key TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
      last_login TEXT NOT NULL DEFAULT '');
    CREATE TABLE profiles (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL COLLATE NOCASE, tag TEXT NOT NULL COLLATE NOCASE, region TEXT NOT NULL DEFAULT 'eu',
      platform TEXT NOT NULL DEFAULT 'pc', mode TEXT NOT NULL DEFAULT 'both', language TEXT NOT NULL DEFAULT 'English',
      playbook TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(owner_id, name, tag));
    INSERT INTO users VALUES (1, 'manuel', 'x', 1, '', 'k', 0, '2026-10-27', '');
    INSERT INTO profiles(id, owner_id, name, tag, created_at) VALUES (1, 1, 'zed', 'Z', 'x'), (2, 1, 'Adv1ce', 'LFT', 'x'),
      (3, 1, 'bravo', 'B', 'x');
    """)
    db.commit()
    db.close()
    from nexus.web.store import Store
    s = Store(data)
    assert [p.name for p in s.profiles(1)] == ["Adv1ce", "bravo", "zed"]     # alphabetical to start
    s.reorder_profiles(1, [1, 3, 2])
    assert [p.name for p in Store(data).profiles(1)] == ["zed", "bravo", "Adv1ce"]


def test_unknown_db_columns_are_ignored(tmp_path):
    """A column added by another version must not crash loading (the 'position' bug)."""
    from nexus.web.store import Store
    s = Store(tmp_path / "d")
    uid = s.create_user("manuel", ADMIN_PW, is_admin=True)
    s.create_profile(uid, "adv1ce", "LFT")
    s.create_job("j1", s.profiles(uid)[0].id, MATCH_ID, "both")
    for table in ("profiles", "users", "jobs"):
        s._exec(f"ALTER TABLE {table} ADD COLUMN from_the_future TEXT NOT NULL DEFAULT 'x'")
    assert [p.riot_id for p in s.profiles(uid)] == ["adv1ce#LFT"]
    assert s.user(uid).username == "manuel" and s.job("j1").match_id == MATCH_ID


def test_paths_follow_moved_data_folder(tmp_path):
    """Reports/uploads saved with absolute paths still open after the data folder moved (Docker)."""
    from nexus.web.store import Store
    s = Store(tmp_path / "new-location")
    (s.data_dir / "reports" / "job1").mkdir(parents=True)
    (s.data_dir / "reports" / "job1" / "r.html").write_text("<html>")
    (s.data_dir / "uploads" / "3").mkdir(parents=True)
    (s.data_dir / "uploads" / "3" / "x.mp4").write_bytes(b"0")
    assert s.resolve("/home/sysadmin/valcoach-v2/data/reports/job1/r.html") == s.data_dir / "reports/job1/r.html"
    assert s.resolve("/home/sysadmin/valcoach-v2/data/uploads/3/x.mp4") == s.data_dir / "uploads/3/x.mp4"
    assert s.resolve("/nope/recordings/a.mp4") is None and s.resolve("") is None


def test_history_paging_and_stored(app, monkeypatch):
    from nexus import pipeline
    calls = []

    def fake_recent(cfg, queue=None, size=10, start=0):
        calls.append(("recent", start))
        n = 10 if start < 20 else 3                     # 2 full pages, then a short one
        return [{"match_id": f"m{start + i}", "started_at": "2026-10-20T19:00:00Z", "queue": "premier",
                 "map": "Ascent", "score": "13-11", "result": "W", "agent": "Sova", "kda": "1/1/1",
                 "rounds": 24} for i in range(n)]

    def fake_stored(cfg, queue=None, page=1, size=20):
        calls.append(("stored", page))
        return ([{"match_id": f"s{page}-{i}", "started_at": "2026-01-01T19:00:00Z", "queue": "competitive",
                  "map": "Bind", "score": "9-13", "result": "L", "agent": "Fade", "kda": "1/1/1",
                  "rounds": 22} for i in range(size if page == 1 else 5)], 25)

    monkeypatch.setattr(pipeline, "history", fake_recent)
    monkeypatch.setattr(pipeline, "stored_history", fake_stored)
    c = setup_admin(app)
    pid = add_profile(c)
    page0 = c.get(f"/profiles/{pid}").data.decode()
    assert "m0" in page0 and "Older →" in page0 and "← Newer" not in page0
    page2 = c.get(f"/profiles/{pid}?page=2").data.decode()
    assert "m20" in page2 and "Older history →" in page2 and "← Newer" in page2
    s1 = c.get(f"/profiles/{pid}?source=stored").data.decode()
    assert "s1-0" in s1 and "25 matches" in s1 and "Older →" in s1
    s2 = c.get(f"/profiles/{pid}?source=stored&page=2").data.decode()
    assert "s2-0" in s2 and "Older →" not in s2
    assert calls == [("recent", 0), ("recent", 20), ("stored", 1), ("stored", 2)]


def _wait_stats(app, key, timeout=60):
    sr = app.extensions["nexus"]["stats"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = sr.status(key)
        if st and st["status"] in ("done", "error"):
            return st
        time.sleep(0.1)
    raise TimeoutError(key)


def test_stats_teams_and_pick_helper(app, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(24)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrik(history, full_depth=6))
    c = setup_admin(app)
    synth.write_agent_cache(Path(app.extensions["nexus"]["store"].data_dir) / "cache")
    me = add_profile(c)
    assert b"No stats yet" in c.get(f"/profiles/{me}/stats").data
    assert b"No games yet" in c.get(f"/profiles/{me}/agents").data
    r = c.post(f"/profiles/{me}/stats/import")
    assert r.status_code == 302
    st = _wait_stats(app, f"import:{me}")
    assert st["status"] == "done", st
    page = c.get(f"/profiles/{me}/stats").data.decode()
    assert "Ascent" in page and "Jett" in page and "Coach tips for" in page
    assert c.get(f"/profiles/{me}/stats?queue=premier&map=Bind").status_code == 200
    page = c.get(f"/profiles/{me}/stats?pick_map=Ascent&locked=Raze&locked=Sova&locked=Cypher&locked=Reyna").data.decode()
    assert "Your team still needs: <b>Controller</b>" in page
    assert c.get("/agent-icon/Jett").status_code == 200
    assert c.get("/agent-icon/Nobody").status_code == 404
    # agents & roles: every agent, what you pick, what your habits fit
    page = c.get(f"/profiles/{me}/agents").data.decode()
    assert "What you pick" in page and "What your habits fit" in page and "All your agents" in page
    assert 'data-agent="Jett"' in page and "Not played yet" in page
    assert c.get(f"/profiles/{me}/agents?queue=premier").status_code == 200
    jett = c.get(f"/profiles/{me}/agents?agent=Jett").data.decode()
    assert "Jett in detail" in jett and "Utility per round" in jett and "Agent × map" in jett
    page = c.get(f"/profiles/{me}/rounds").data.decode()
    assert "Rounds &amp; economy" in page and "Pistol rounds" in page and "Anti-eco" in page
    page = c.get(f"/profiles/{me}/teammates").data.decode()
    assert "Teammates" in page and "red-0" in page

    # the other four starters + a sub, each with their own history
    ids = {"adv1ce": me}
    for name in ("red-0", "red-2", "red-3", "red-4", "subby"):
        ids[name] = add_profile(c, name, "#T")
        c.post(f"/profiles/{ids[name]}/stats/import")
        assert _wait_stats(app, f"import:{ids[name]}")["status"] == "done"
    r = c.post("/teams", data={"name": "Premier squad"})
    assert r.headers["Location"].endswith("/settings")
    tid = int(r.headers["Location"].split("/teams/")[1].split("/")[0])
    form = {f"kind_{pid}": ("sub" if n == "subby" else "starter") for n, pid in ids.items()}
    form.update(name="Premier squad", queue="all", maps=["Ascent", "Haven"], meta="Haven:\n  roles: 1D 1I 2C 1S\n")
    assert c.get(f"/teams/{tid}").status_code == 200          # no starters yet: points to the settings
    assert c.get(f"/teams/{tid}/settings").status_code == 200
    assert c.post(f"/teams/{tid}/settings", data=form).status_code == 302
    page = c.get(f"/teams/{tid}").data.decode()
    assert "Comps at a glance" in page and "Ascent" in page and "Haven" in page and "subby" in page
    assert "1D 1I 2C 1S" in page                       # the meta's role mix is followed on Haven
    page = c.get(f"/teams/{tid}?map=Haven").data.decode()
    assert "If someone is missing" in page and "role mix from your meta" in page
    assert "Premier squad" in c.get("/").data.decode()          # dashboard lists the team
    # 4.9: comp suggestions switch, map rules by default, "your stats only" exactly as before
    page = c.get(f"/teams/{tid}?map=Ascent").data.decode()
    assert "Map rules + your stats" in page and "Which one is you" not in page and "You are" not in page   # 4.10
    assert 'name="comp_method"' in c.get(f"/teams/{tid}/settings").data.decode()
    assert c.post(f"/teams/{tid}/settings", data=dict(form, comp_method="stats")).status_code == 302
    assert app.extensions["nexus"]["store"].team(tid).comp_method == "stats"
    page = c.get(f"/teams/{tid}?map=Ascent").data.decode()
    assert "Your stats only" in page and "Map rules:" not in page
    # 4.10: most comfortable
    c.post(f"/teams/{tid}/settings", data=dict(form, comp_method="comfort"))
    page = c.get(f"/teams/{tid}?map=Ascent").data.decode()
    assert "Most comfortable" in page and "games on Ascent" in page
    # 4.10: from the web: off without web search, then searched with a fake search and model
    c.post(f"/teams/{tid}/settings", data=dict(form, comp_method="web"))
    store = app.extensions["nexus"]["store"]
    store.set("search_provider", "duckduckgo")                       # the default (the test app turns it off)
    page = c.get(f"/teams/{tid}?map=Ascent").data.decode()          # 4.13: no "web_search" switch needed
    assert "Comps from the web" in page and "Web search is off" not in page and "Search comps for Ascent" in page
    store.set("search_provider", "")                                  # Settings › Web search › off
    page = c.get(f"/teams/{tid}?map=Ascent").data.decode()
    assert "Web search is off" in page and "no comps from the web" in page and "Search comps for" not in page
    from nexus.coach import websearch as ws
    import nexus.coach.ollama as oll
    store.set("search_provider", "duckduckgo")
    searched = []
    monkeypatch.setattr(ws, "searcher", lambda st: (lambda q, n=6: searched.append(q) or [
        {"title": "Ascent comps tier list", "url": "https://example.org/ascent", "snippet": "Jett Sova KAY/O Omen Killjoy"}]))
    monkeypatch.setattr(ws, "page_text", lambda url, limit=4000, session=None: "Best Ascent comp: Jett, Sova, KAY/O, Omen, Killjoy.")

    class FakeModel:
        def __init__(self, *a, **k):
            self.model = "fake"

        def check(self):
            pass

        def chat_json(self, system, user, schema):
            assert "Ascent" in user and "[1]" in user
            return {"comps": [{"agents": ["Jett", "Sova", "kayo", "Omen", "Killjoy"], "note": "the standard comp", "sources": [1]},
                              {"agents": ["Jett", "Jett", "Sova", "Omen", "Killjoy"], "note": "broken", "sources": [1]},
                              {"agents": ["Jett", "Sova", "Omen", "Killjoy", "Nobody"], "note": "made up", "sources": [9]}]}
    monkeypatch.setattr(oll, "Ollama", FakeModel)
    assert c.post(f"/teams/{tid}/webcomps", data={"map": "Ascent"}).status_code == 302
    st = _wait_stats(app, f"webcomps:{tid}")
    assert st["status"] == "done", st["log"]
    assert any("Ascent" in q for q in searched)
    page = c.get(f"/teams/{tid}?map=Ascent").data.decode()
    assert "the standard comp" in page and "https://example.org/ascent" in page and "KAY/O" in page
    assert "made up" not in page and "broken" not in page
    data = app.extensions["nexus"]["stats"].read_webcomps(tid)
    assert data["ascent"]["comps"][0]["agents"] == ["Jett", "Sova", "KAY/O", "Omen", "Killjoy"]
    assert "no comps from the web" in c.get(f"/teams/{tid}?map=Haven").data.decode()   # Haven not searched yet
    c.post(f"/teams/{tid}/settings", data=dict(form, comp_method="rules"))
    assert c.post(f"/teams/{tid}/webcomps", data={"map": "Ascent"}).status_code == 400   # only in "From the web"
    # 4.10: no "You are" pick: you are the player whose Riot ID is your in-game name
    admin = next(u for u in store.users() if u.username == "manuel")
    assert not any(m.get("user_id") == admin.id for m in store.team(tid).member_list)
    assert "Set your in-game name" in c.get(f"/teams/{tid}").data.decode()
    store.update_user(admin.id, display_name="adv1ce#LFT")
    page = c.get(f"/teams/{tid}").data.decode()
    assert any(m.get("user_id") == admin.id and m["pid"] == me for m in store.team(tid).member_list)
    assert "Set your in-game name" not in page and '>you</span>' in page
    # 4.11: player overview, short and full view
    ovp = c.get(f"/teams/{tid}/overview").data.decode()
    assert "Player overview" in ovp and "Most played agents" in ovp and "Agent roles" in ovp
    assert "Playstyle" in ovp and "The team at a glance" in ovp and "plays it regularly" in ovp
    assert "Thrives in" in ovp and 'class="chip style"' in ovp          # 4.12: playstyle labels, situations
    full = c.get(f"/teams/{tid}/overview?view=all").data.decode()
    assert "Every agent" in full and "Every map" in full and "Roles and playstyle" in full
    assert "Most played agents" not in full and "Struggles in" in full
    from nexus.stats import overview as ovmod
    from nexus.stats.teamroles import team_roles as _tr
    ctx_rows = [{"label": "a", "pid": 1, "kind": "starter", "rows": [], "assigned": []}]
    assert ovmod.team(_tr(ctx_rows, {}, []), [])["players"][0]["games"] == 0
    # 4.10.1: the mode picker right on the comps page
    assert 'id="compmaker"' in page and "Make comps" in page
    r = c.post(f"/teams/{tid}/comps/method", data={"comp_method": "comfort", "map": "Haven"})
    assert r.status_code == 302 and r.headers["Location"].endswith("map=Haven#detail")
    assert store.team(tid).comp_method == "comfort"
    assert c.post(f"/teams/{tid}/comps/method", data={"comp_method": "nope"}).status_code == 400
    c.post(f"/teams/{tid}/comps/method", data={"comp_method": "web", "map": "Haven"})    # Haven not searched yet
    assert _wait_stats(app, f"webcomps:{tid}")["status"] == "done"
    assert "haven" in app.extensions["nexus"]["stats"].read_webcomps(tid)
    c.post(f"/teams/{tid}/comps/method", data={"comp_method": "rules", "map": "Ascent"})
    # bad meta is refused, other users can't see the team
    r = c.post(f"/teams/{tid}/settings", data=dict(form, meta="Haven:\n  roles: 9D\n"), follow_redirects=True)
    assert "Map meta: Haven: roles must add up to 5" in r.data.decode()
    assert "1D 1I 2C 1S" in c.get(f"/teams/{tid}").data.decode()       # old meta kept
    other = make_user(app, c, "friend")
    assert other.get(f"/teams/{tid}").status_code == 404
    assert other.get(f"/profiles/{me}/stats").status_code == 404
    assert other.get(f"/profiles/{me}/agents").status_code == 404
    app.extensions["nexus"]["stats"].shutdown()


def test_pro_and_videos_page(app, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    from nexus.stats import youtube
    history = sh.build_history(24)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrik(history, full_depth=6))
    c = setup_admin(app)
    me = add_profile(c)
    assert b"No games yet" in c.get(f"/profiles/{me}/pros").data
    c.post(f"/profiles/{me}/stats/import")
    assert _wait_stats(app, f"import:{me}")["status"] == "done"
    page = c.get(f"/profiles/{me}/pros").data.decode()
    assert "Pros with a similar style" in page and "% match" in page and "youtube.com/results?search_query=" in page
    assert "Add a YouTube API key" in page

    # with a YouTube key and a model: videos + watch notes
    class FakeOllama:
        def __init__(self, url, model, *a, **k):
            self.model = model

        def check(self):
            pass

        def chat_json(self, system, user, schema):
            ids = schema["properties"]["items"]["items"]["properties"]["id"]["enum"]
            pro = system.split("The player picked ")[1].split(" as the pro")[0]
            return {"pro_summary": f"Copy how {pro} spaces for the entry.", "items": [{"id": i, "watch_for": f"note {i}"} for i in ids],
                    "habits": ["Trade your entry within 2 s"]}
    import nexus.coach.ollama as oll
    monkeypatch.setattr(oll, "Ollama", FakeOllama)
    monkeypatch.setattr(youtube, "search", lambda key, q, cache, n=3, session=None: [
        {"id": "x1", "title": f"Video for {q}", "channel": "ch", "published": "2026-10-01",
         "thumb": "https://i.ytimg.com/vi/x1/mqdefault.jpg", "url": "https://www.youtube.com/watch?v=x1"}])
    r = c.post("/settings", data={"youtube_api_key": "AIza-test", "ollama_temperature": "0.3", "ollama_num_ctx": "16384",
                                  "ollama_parallel": "4", "ollama_timeout_s": "300", "sample_fps": "2", "workers": "1",
                                  "minimap_roi": ", ".join(map(str, synth.MM_ROI)), "killfeed_roi": ", ".join(map(str, synth.KF_ROI)),
                                  "pros_yaml": "pros: nope"}, follow_redirects=True)
    assert "Pro players: expected a &#39;pros:&#39; list" in r.data.decode()
    c.post(f"/profiles/{me}/pros/build", data={"queue": "all"})
    assert _wait_stats(app, f"watch:{me}:all")["status"] == "done"
    page = c.get(f"/profiles/{me}/pros").data.decode()
    from nexus.stats.style import load_pros, match_pros, profile
    from nexus.stats.aggregate import filter_rows
    sr_ = app.extensions["nexus"]["stats"]
    ms = match_pros(profile(filter_rows(sr_.games(me).rows(), "all")), load_pros(""))
    first, second = ms[0]["name"], ms[1]["name"]
    assert f"Copy how {first} spaces for the entry." in page and "Watch for:</b> note v1" in page
    assert "watch?v=x1" in page and "Trade your entry within 2 s" in page
    # pick another pro: its own searches, and no guide until it's written for that pro
    page2 = c.get(f"/profiles/{me}/pros?pro={second}").data.decode()
    assert f"{second} on " in page2 and f"Copy how {first}" not in page2 and f"Write what to watch for {second}" in page2
    c.post(f"/profiles/{me}/pros/build", data={"queue": "all", "pro": second, "all": "1"})
    assert _wait_stats(app, f"watch:{me}:all")["status"] == "done"
    page2 = c.get(f"/profiles/{me}/pros?pro={second}").data.decode()
    assert f"Copy how {second} spaces for the entry." in page2
    assert f"Copy how {first} spaces" in c.get(f"/profiles/{me}/pros?pro={first}").data.decode()   # still there
    assert set(sr_.read_watch(me, "all")["by_pro"]) == {m["name"] for m in ms}
    app.extensions["nexus"]["stats"].shutdown()


def test_premier_team_import_and_roles(app, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10))
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    existing = add_profile(c)                                   # adv1ce already exists: reused, not duplicated
    r = c.post("/teams", data={"premier_name": "Red Squad#RED", "premier_region": "eu"})
    tid = int(r.headers["Location"].rsplit("/", 1)[1])
    st = _wait_stats(app, f"premier:{tid}")
    assert st["status"] == "done", st
    t = store.team(tid)
    names = {store.profile(m["pid"]).name: m for m in t.member_list}
    assert set(names) == {"adv1ce", "red-0", "red-2", "red-3", "red-4", "subby"}
    assert names["adv1ce"]["pid"] == existing
    assert names["subby"]["kind"] == "sub"                       # played the fewest Premier matches
    assert sum(m["kind"] == "starter" for m in t.member_list) == 5
    assert t.premier_info["placement"]["division"] == 12
    for m in t.member_list:                                      # imports were queued for everyone
        assert _wait_stats(app, f"import:{m['pid']}")["status"] == "done"
    page = c.get(f"/teams/{tid}").data.decode()
    assert "Red Squad#RED" in page and "division 12" in page and "Comps at a glance" in page

    # roles: assign, see the suggestion respect it, agent to learn shows up
    page = c.get(f"/teams/{tid}/roles").data.decode()
    assert "Suggested lineup" in page and "How well everyone fits each role" in page and "Agents to learn" in page
    me = names["adv1ce"]["pid"]
    form = {f"roles_{me}": ["Anchor", "IGL"]}
    assert c.post(f"/teams/{tid}/roles", data=form).status_code == 302
    assert store.team(tid).member_list[[m["pid"] for m in store.team(tid).member_list].index(me)]["roles"] == ["Anchor", "IGL"]
    page = c.get(f"/teams/{tid}/roles").data.decode()
    assert "you set this" in page
    # saving members & maps keeps the roles
    form = {f"kind_{m['pid']}": m["kind"] for m in store.team(tid).member_list}
    form.update(name="Red Squad", queue="all")
    c.post(f"/teams/{tid}/settings", data=form)
    assert next(m for m in store.team(tid).member_list if m["pid"] == me)["roles"] == ["Anchor", "IGL"]
    # re-sync keeps them too
    c.post(f"/teams/{tid}/premier-sync")
    _wait_stats(app, f"premier:{tid}")
    assert next(m for m in store.team(tid).member_list if m["pid"] == me)["roles"] == ["Anchor", "IGL"]
    app.extensions["nexus"]["stats"].shutdown()


@pytest.mark.parametrize("mode", ["nonames", "none"])
def test_premier_roster_without_names(app, monkeypatch, mode):
    """Live HenrikDev returns members with name/tag = null (or no members): names come from the matches / by-puuid."""
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10, members=mode))
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    r = c.post("/teams", data={"premier_name": "Red Squad#RED", "premier_region": "eu"})
    tid = int(r.headers["Location"].rsplit("/", 1)[1])
    st = _wait_stats(app, f"premier:{tid}")
    assert st["status"] == "done", st["log"]
    names = {store.profile(m["pid"]).name for m in store.team(tid).member_list}
    assert {"adv1ce", "red-0", "red-2", "red-3"} <= names
    if mode == "nonames":
        assert "subby" in names                      # never played a Premier match: name from by-puuid
    assert sum(m["kind"] == "starter" for m in store.team(tid).member_list) == 5
    for m in store.team(tid).member_list:
        _wait_stats(app, f"import:{m['pid']}")
    app.extensions["nexus"]["stats"].shutdown()


@pytest.mark.parametrize("roster_in_match", [True, False])
def test_premier_no_members_one_match(app, monkeypatch, roster_in_match):
    """Live case: 0 members and a single Premier match (new season). Use the match's Premier roster,
    or else the side your own player was on."""
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(
        history, full_depth=10, members="none-1match", roster_in_match=roster_in_match))
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    add_profile(c)                                              # adv1ce#LFT is in your workspace
    r = c.post("/teams", data={"premier_name": "Red Squad#RED", "premier_region": "eu"})
    tid = int(r.headers["Location"].rsplit("/", 1)[1])
    st = _wait_stats(app, f"premier:{tid}")
    assert st["status"] == "done", st["log"]
    names = {store.profile(m["pid"]).name for m in store.team(tid).member_list}
    assert {"adv1ce", "red-0", "red-2", "red-3"} <= names and not any(n.startswith("blue") for n in names)
    if roster_in_match:
        assert "subby" in names and "Premier roster in the match data" in "\n".join(st["log"])
    else:
        assert "played on your side" in "\n".join(st["log"])
    for m in store.team(tid).member_list:
        _wait_stats(app, f"import:{m['pid']}")
    app.extensions["nexus"]["stats"].shutdown()


def test_changelog_page_and_update_note(app):
    from nexus import __version__
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    page = c.get("/").data.decode()
    assert f">{__version__}" in page and "was updated to" not in page        # fresh install: no note
    uid = store.user_by_name("manuel").id
    store.set(f"seen_version:{uid}", "2.0.0")                                   # pretend an update happened
    page = c.get("/").data.decode()
    assert f"was updated to <b>{__version__}</b>" in page and "newdot" in page
    page = c.get("/changelog").data.decode()
    assert f"{__version__}<span class=\"tag\">running</span>" in page and "<b>Premier import:</b>" in page
    assert "was updated to" not in c.get("/").data.decode()                    # seen now


class _FakeModel:
    """Answers the batch-2 schemas (game plans, weekly focus)."""

    def __init__(self, url, model, *a, **k):
        self.model = "fake-model"

    def check(self):
        pass

    def chat_json(self, system, user, schema):
        props = schema["properties"]
        if "plans" in props:
            players = props["plans"]["items"]["properties"]["steps"]["items"]["properties"]["player"]["enum"]
            return {"plans": [{"title": f"Plan {i}", "side": "attack" if i < 2 else "defense", "idea": "Fake A, lurk B",
                               "when_to_use": "after a won pistol", "timing": "1:20 fake, 1:05 lurk",
                               "if_then": ["If they rotate early, hit A"], "why": "B plants won 60%",
                               "steps": [{"player": p, "what": f"{p} does job {i}"} for p in players]} for i in range(3)]}
        if "number_to_watch" in props:
            return {"focus": "Fall back after the first kill", "why": "KAST 61%", "in_game": ["Fall back", "Call it"],
                    "number_to_watch": {"metric": "KAST", "now": "61%", "goal": "70%"}}
        raise AssertionError(list(props))


def _premier_team(app, c, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10, roster_in_match=True))
    store = app.extensions["nexus"]["store"]
    # the importer caches full matches; the fake doesn't, so put them where the team data looks
    cache = Path(store.data_dir) / "cache" / "matches"
    cache.mkdir(parents=True, exist_ok=True)
    for d in history:
        (cache / f"{d['metadata']['match_id']}.json").write_text(json.dumps({"status": 200, "data": d}))
    r = c.post("/teams", data={"premier_name": "Red Squad#RED", "premier_region": "eu"})
    tid = int(r.headers["Location"].rsplit("/", 1)[1])
    assert _wait_stats(app, f"premier:{tid}")["status"] == "done"
    for m in store.team(tid).member_list:
        _wait_stats(app, f"import:{m['pid']}")
    return tid


def test_shared_team_notes_plans_focus_discord(app, monkeypatch):
    import nexus.coach.ollama as oll
    from nexus import discord as dc
    monkeypatch.setattr(oll, "Ollama", _FakeModel)
    sent = []

    class Resp:
        status_code = 204
        text = ""
    monkeypatch.setattr(dc.requests, "post", lambda url, json, timeout: sent.append((url, json)) or Resp())
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    tid = _premier_team(app, c, monkeypatch)
    names = {store.profile(m["pid"]).name: m["pid"] for m in store.team(tid).member_list}

    # --- a teammate with their own account; in-game name links them automatically
    friend = make_user(app, c, "burn", display_name="red-0#T")
    assert friend.get(f"/teams/{tid}").status_code == 404                     # not added yet
    c.post(f"/teams/{tid}/access", data={"add": str(store.user_by_name("burn").id)})
    page = friend.get(f"/teams/{tid}").data.decode()
    assert "Comps at a glance" in page and "shared with you" in page and "Members, maps" not in page
    assert friend.get(f"/teams/{tid}/settings").status_code == 403
    assert friend.post(f"/teams/{tid}/import").status_code == 403
    assert "red-0" in page and '<span class="k" style="color:var(--win)">you</span>' in page
    assert "Red Squad" in friend.get("/").data.decode()                          # dashboard lists it
    sp = friend.get(f"/profiles/{names['adv1ce']}/stats").data.decode()          # teammate stats: view only
    assert "view only" in sp and "stats_import" not in sp
    assert friend.get(f"/profiles/{names['adv1ce']}").status_code == 404        # but not their matches/reports
    assert friend.get(f"/teams/{tid}/roles").status_code == 200
    assert friend.post(f"/teams/{tid}/roles", data={}).status_code == 403

    # --- notes: teammates write, everyone sees; tips from the data
    friend.post(f"/teams/{tid}/notes", data={"text": "Burn gets pushed by 2 on B", "about": str(names["adv1ce"]), "map": "Bind"})
    np_ = c.get(f"/teams/{tid}/notes").data.decode()
    assert "Burn gets pushed by 2 on B" in np_ and "From your matches together" in np_
    nid = store.team_notes(tid)[0]["id"]
    other = make_user(app, c, "outsider")
    assert other.post(f"/teams/{tid}/notes/{nid}/delete").status_code == 404

    # --- game plans
    c.post(f"/teams/{tid}/plans/build", data={"map": "Ascent"})
    assert _wait_stats(app, f"plans:{tid}")["status"] == "done"
    pp = friend.get(f"/teams/{tid}/plans?map=Ascent").data.decode()
    assert "Plan 0" in pp and "adv1ce does job 0" in pp and "If / then" in pp and "Comps for Ascent" in pp
    assert "Draw it" in pp
    r = friend.post(f"/teams/{tid}/strats", data={"map": "Ascent", "side": "attack", "from_plan": "2"})
    st_ = store.strat(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert st_["name"] == "Plan 2" and st_["side"] == "defense" and "adv1ce: adv1ce does job 2" in st_["data"]["notes"]
    assert [x["name"] for x in st_["data"]["steps"]] == ["Setup", "Execute"]

    # --- Discord settings, test message, match prep
    bad = c.post(f"/teams/{tid}/discord", data={"prep_url": "https://example.com/x"}, follow_redirects=True)
    assert "doesn&#39;t look like a Discord webhook" in bad.data.decode()
    hook = "https://discord.com/api/webhooks/111/aaa"
    c.post(f"/teams/{tid}/discord", data={"prep_url": hook, "focus_url": "https://discord.com/api/webhooks/222/bbb",
                                          "weekly": "1", "weekly_day": "0", "weekly_hour": "18", "test": "1"})
    assert sent and sent[-1][0] == hook and "connected" in sent[-1][1]["content"]
    c.post(f"/teams/{tid}/discord/prep", data={"maps": ["Ascent"]})
    assert _wait_stats(app, f"post:{tid}")["status"] == "done"
    prep = sent[-1][1]
    assert prep["embeds"][0]["title"] == "Ascent" and "**1.**" in prep["embeds"][0]["description"]
    assert prep["embeds"][0]["fields"] and prep["allowed_mentions"] == {"parse": []}

    # --- weekly focus (manual) + dashboard + post
    c.post(f"/teams/{tid}/focus/build", data={"post": "1"})
    assert _wait_stats(app, f"focus:{tid}")["status"] == "done"
    assert "Fall back after the first kill" in friend.get(f"/teams/{tid}/focus").data.decode()
    assert "Your focus this week" in friend.get("/").data.decode()
    assert sent[-1][0].endswith("/222/bbb") and "KAST: 61% → 70%" in sent[-1][1]["embeds"][0]["description"]
    # 4.15: the focus' number to watch became a goal for every player
    sr_ = app.extensions["nexus"]["stats"]
    for m in store.team(tid).member_list:
        gs = sr_.goals(m["pid"]).load()
        assert gs and gs[-1]["metric"] == "kast" and gs[-1]["target"] == 0.7 and gs[-1]["source"] == "weekly focus"

    # --- the schedule: due on its day/hour once a week, not again after posting
    from datetime import datetime
    sr = app.extensions["nexus"]["stats"]
    job = app.extensions["nexus"]["weekly_job"]
    info = store.team(tid).discord_info
    info.pop("last_focus_week")
    store.update_team(tid, discord=info)
    monday = datetime(2026, 11, 2, 19, 0)
    assert sr.tick(job, now=datetime(2026, 11, 2, 17, 0)) == []                   # too early
    assert sr.tick(job, now=monday) == [tid]
    _wait_stats(app, f"focus:{tid}")
    assert sr.tick(job, now=monday) == []                                         # tried within the hour
    sr.shutdown()


def test_strat_book(app, monkeypatch):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    cache = Path(store.data_dir) / "cache"
    synth.write_agent_cache(cache)
    synth.write_map_image(cache)
    me = add_profile(c)
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter"}], maps=["Testmap"])
    # assets: map image (by name), agent icons, ability icons (Passive is left out)
    assert c.get("/map-image/Testmap").status_code == 200
    assert c.get("/map-image/Nowhere").status_code == 404
    assert c.get("/ability-icon/Jett/Ability1").status_code == 200
    assert c.get("/ability-icon/Jett/Passive").status_code == 404
    # create, edit page with boot data
    r = c.post(f"/teams/{tid}/strats", data={"name": "B split", "map": "Testmap", "side": "attack"})
    sid = int(r.headers["Location"].rsplit("/", 1)[1])
    page = c.get(f"/teams/{tid}/strats/{sid}").data.decode()
    boot = json.loads(page.split('id="strat-boot">')[1].split("</script>")[0].replace("<\\/", "</"))
    jett = next(a for a in boot["assets"]["agents"] if a["name"] == "Jett")
    assert [ab["slot"] for ab in jett["abilities"]] == ["Grenade", "Ability1", "Ability2", "Ultimate"]
    # every ability carries its real shape/size and every agent its colour (smokes distinguishable)
    omen = next(a for a in boot["assets"]["agents"] if a["name"] == "Omen")
    dc = next(ab for ab in omen["abilities"] if ab["name"] == "Dark Cover")
    assert dc["shape"]["k"] == "smoke" and dc["shape"]["r"] == 4.1 and omen["color"] != jett["color"]
    sova = next(a for a in boot["assets"]["agents"] if a["name"] == "Sova")
    hf = next(ab for ab in sova["abilities"] if ab["name"] == "Hunter's Fury")
    assert hf["shape"]["k"] == "strip" and hf["shape"]["min"] < hf["shape"]["max"]
    assert next(ab for ab in jett["abilities"] if ab["name"] == "Updraft")["shape"] is None
    assert boot["assets"]["map"]["callouts"] and boot["assets"]["map"]["m"] > 0 and boot["lineup"] == ["adv1ce"]
    # save (JSON only) and read back
    data = {"steps": [{"name": "Setup", "items": [{"id": "a1", "t": "agent", "a": "Jett", "x": 500, "y": 400, "c": "us"}]},
                      {"name": "Execute", "items": []}], "notes": "dash B"}
    assert c.post(boot["save_url"], data={"x": "1"}).status_code == 400              # a form post is refused
    assert c.post(boot["save_url"], json={"data": {"steps": []}}).status_code == 400
    r = c.post(boot["save_url"], json={"name": "B split v2", "side": "defense", "data": data})
    assert r.status_code == 200 and r.get_json()["ok"]
    s = store.strat(sid)
    assert s["name"] == "B split v2" and s["side"] == "defense" and s["data"]["steps"][0]["items"][0]["a"] == "Jett"
    assert "B split v2" in c.get(f"/teams/{tid}/strats").data.decode()
    # a teammate with access can edit, an outsider can't see it, only author/owner deletes
    friend = make_user(app, c, "burn")
    assert friend.get(f"/teams/{tid}/strats/{sid}").status_code == 404
    store.add_team_access(tid, store.user_by_name("burn").id)
    assert friend.post(boot["save_url"], json={"data": data, "name": "edited by burn"}).status_code == 200
    assert friend.post(f"/teams/{tid}/strats/{sid}/delete").status_code == 403
    r = friend.post(f"/teams/{tid}/strats/{sid}/copy")
    copy_id = int(r.headers["Location"].rsplit("/", 1)[1])
    assert store.strat(copy_id)["data"]["notes"] == "dash B"
    assert friend.post(f"/teams/{tid}/strats/{copy_id}/delete").status_code == 302    # their own copy
    # post a picture to Discord
    from nexus import discord as dc
    sent = []

    class Resp:
        status_code = 204
        text = ""
    monkeypatch.setattr(dc.requests, "post", lambda url, data=None, files=None, timeout=None, json=None: sent.append((url, data, files)) or Resp())
    store.update_team(tid, discord={"prep_url": "https://discord.com/api/webhooks/1/x"})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = c.post(f"/api/teams/{tid}/strats/{sid}/discord", data={"png": (io.BytesIO(png), "b.png"), "step": "Execute"},
               content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    assert "edited by burn" in json.loads(sent[-1][1]["payload_json"])["content"] and sent[-1][2]["files[0]"][1] == png
    r = c.post(f"/api/teams/{tid}/strats/{sid}/discord", data={"png": (io.BytesIO(b"GIF89a"), "b.png")}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert c.post(f"/teams/{tid}/strats/{sid}/delete").status_code == 302 and store.strat(sid) is None


def test_ability_shapes_catalog():
    from nexus.web.abilityshapes import CATALOG, shape_for, color_for, AGENT_COLORS
    fl = shape_for("Fault Line")
    assert fl["k"] == "strip" and fl["w"] == 7.5 and (fl["min"], fl["max"]) == (8, 56)
    assert shape_for("Rolling Thunder")["off"] == 8 and shape_for("ROLLING  thunder") is not None
    assert shape_for("Sky Smoke")["r"] == 4.15 and shape_for("Toxic Screen")["len"] == 60
    assert shape_for("Nebula / Dissipate")["k"] == "smoke" and shape_for("Astral Form / Cosmic Divide")["k"] == "wall"
    assert shape_for("Updraft") is None and shape_for("") is None
    for name, sh in CATALOG.items():
        assert sh["k"] in ("smoke", "area", "strip", "wall", "lane"), name
        if sh["k"] in ("smoke", "area"):
            assert sh["r"] > 0, name
        else:
            assert sh["min"] <= sh["len"] <= sh["max"] and sh.get("w", 1) > 0, name
    controllers = ["Omen", "Brimstone", "Astra", "Viper", "Harbor", "Clove"]
    assert len({AGENT_COLORS[a] for a in controllers}) == len(controllers)
    assert color_for("Someone New", "Controller").startswith("#") and color_for("Nobody").startswith("#")


def test_nightly_sync_and_sortable_roles(app):
    from datetime import datetime
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    sr = app.extensions["nexus"]["stats"]
    me = add_profile(c)
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter"}])
    t = store.team(tid)
    assert t.sync_info["nightly"] and t.sync_info["hour"] == 2                  # on by default, 02:00
    ran = []
    job = lambda team: ran.append(team.id)
    assert sr.tick_nightly(job, now=datetime(2026, 11, 2, 1, 30)) == []          # too early
    assert sr.tick_nightly(job, now=datetime(2026, 11, 2, 13, 0)) == []          # missed it: not at lunch
    assert sr.tick_nightly(job, now=datetime(2026, 11, 2, 2, 5)) == [tid] and ran == [tid]
    assert sr.tick_nightly(job, now=datetime(2026, 11, 2, 3, 0)) == []           # once a night
    info = store.team(tid).sync_info
    info["last_try"] = 0
    store.update_team(tid, sync=info)
    assert sr.tick_nightly(job, now=datetime(2026, 11, 3, 4, 59)) == [tid]       # next night, catching up
    # the real job: same as the buttons (no Premier tag -> import the players)
    app.extensions["nexus"]["nightly_job"](store.team(tid))
    assert sr.status(f"import:{me}") is not None
    _wait_stats(app, f"import:{me}")
    # settings: off, and a different hour
    r = c.post(f"/teams/{tid}/sync-settings", data={"hour": "1"})
    assert r.status_code == 302 and store.team(tid).sync_info == {**store.team(tid).sync_info, "nightly": False, "hour": 1}
    assert sr.tick_nightly(job, now=datetime(2026, 11, 4, 1, 10)) == []
    c.post(f"/teams/{tid}/sync-settings", data={"hour": "1", "nightly": "1"})
    assert "Syncs every night at 01:00" in c.get(f"/teams/{tid}").data.decode()
    assert "Automatic sync" in c.get(f"/teams/{tid}/settings").data.decode()
    # the role table has sortable headers
    page = c.get(f"/teams/{tid}/roles").data.decode()
    assert 'class="sorth"' in page and "<tbody>" in page
    sr.shutdown()


# ---------------------------------------------------------------------------
# review fixes (see notes/review-fixes-2.15.md)
def test_bad_ids_and_anchor_inputs(app):
    c = setup_admin(app)
    pid = add_profile(c)
    for mid in ("..", "x.json", "nexus.db"):
        assert c.get(f"/profiles/{pid}/coach/{mid}").status_code == 404, mid
        assert c.get(f"/profiles/{pid}/notes/{mid}").status_code == 404, mid
    r = c.get(f"/profiles/{pid}/open?match_id=../x")
    assert b"look like a match ID" in c.get(r.headers["Location"]).data
    for rnd, kill in (("abc", "1"), ("99", "1"), ("1", "0")):
        r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}",
                   data={"mode": "team", "vod": "", "anchor_round": rnd, "anchor_kill": kill})
        assert r.status_code == 302 and b"Anchor round must be" in c.get(r.headers["Location"]).data


def test_deathmatch_is_not_coachable(app, synthetic):
    raw = json.loads(Path(synthetic["match"]).read_text())
    raw["data"]["metadata"]["queue"] = {"id": "deathmatch", "name": "Deathmatch", "mode_type": "Deathmatch"}
    store = app.extensions["nexus"]["store"]
    (store.data_dir / "cache" / "matches" / "dm-match-1.json").write_text(json.dumps(raw))
    c = setup_admin(app)
    pid = add_profile(c)
    for url in (f"/profiles/{pid}/coach/dm-match-1", f"/profiles/{pid}/notes/dm-match-1"):
        r = c.get(url)
        assert r.status_code == 302 and b"can&#39;t be coached" in c.get(r.headers["Location"]).data


def test_job_quota_upload_limit_and_running_delete(app):
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    # a job that sits in the queue (never submitted) counts against the quota
    store.create_job("held1", pid, MATCH_ID, "team")
    store.set("max_jobs_per_user", "1")
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "", "no_llm": "1"})
    assert b"already have 1 report" in c.get(r.headers["Location"]).data
    store.set("max_jobs_per_user", "3")
    # upload over the size limit is refused before it is stored
    store.set("max_upload_gb", "0.000001")          # ~1 KB
    r = c.post("/api/uploads", json={"name": "big.mp4", "size": 5000})
    assert r.status_code == 413 and "upload is too big" in r.json["error"]
    assert not list((store.data_dir / "tmp").iterdir())
    # a player with a running report can't be deleted
    store.update_job("held1", status="running")
    r = c.post(f"/profiles/{pid}/delete")
    assert b"being made right now" in c.get(r.headers["Location"]).data
    assert store.profile(pid) is not None
    store.update_job("held1", status="done")
    assert c.post(f"/profiles/{pid}/delete").status_code == 302 and store.profile(pid) is None


def test_forms_from_other_sites_are_blocked(app):
    c = setup_admin(app)
    evil = {"Origin": "http://evil.example"}
    r = c.post("/profiles/new", headers=evil, data={"name": "x", "tag": "y", "region": "eu", "platform": "pc",
                                                     "mode": "both", "language": "English", "playbook": ""})
    assert r.status_code == 403 and b"another website" in r.data
    assert c.post("/logout", headers={"Referer": "http://evil.example/page"}).status_code == 403
    # X-Forwarded-Host only counts from a reverse proxy on this machine / the LAN, not straight from the internet
    fwd = {"Origin": "https://coach.example", "X-Forwarded-Host": "coach.example"}
    assert c.post("/account", headers=fwd, data={"display_name": "x"}).status_code == 302          # proxy on the LAN
    assert c.post("/account", headers=fwd, data={"display_name": "x"},
                  environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403                     # public address
    # the app's own pages (same host) and non-browser clients still work
    assert c.post("/profiles/new", headers={"Origin": "http://localhost"},
                  data={"name": "a", "tag": "b", "region": "eu", "platform": "pc", "mode": "both",
                        "language": "English", "playbook": ""}).status_code == 302


def test_job_is_claimed_once(app):
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    store.create_job("twice1", pid, MATCH_ID, "team")
    assert store.claim_job("twice1") is True
    assert store.claim_job("twice1") is False          # second submit of the same job does nothing
    assert store.job("twice1").status == "running"


def test_strat_board_only_stores_typed_fields(app):
    """A team member can't plant HTML in fields the editor shows as numbers."""
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    me = add_profile(c)
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter"}], maps=["Testmap"])
    r = c.post(f"/teams/{tid}/strats", data={"name": "B split", "map": "Testmap", "side": "attack"})
    sid = int(r.headers["Location"].rsplit("/", 1)[1])
    evil = '"><img src=x onerror=alert(1)>'
    items = [{"id": "a1", "t": "num", "x": 10, "y": 20, "n": evil, "r": evil, "ang": evil, "len": "5"},
             {"id": "a2", "k": "a0", "t": "arrow", "x": 1, "y": 2, "x2": 30, "y2": 40, "c": "us", "dash": 1},
             {"id": "a3", "t": "pen", "pts": [[1, 2], ["x", 3], [4, 5]]}, "junk", {"no": "type"}]
    r = c.post(f"/api/teams/{tid}/strats/{sid}", json={"data": {"steps": [{"name": "S", "items": items}]}})
    assert r.status_code == 200
    saved = store.strat(sid)["data"]["steps"][0]["items"]
    assert saved[0] == {"id": "a1", "t": "num", "x": 10, "y": 20, "len": 5}
    assert saved[1]["x2"] == 30 and saved[1]["dash"] is True and saved[1]["k"] == "a0"     # k: playback links steps
    assert saved[2]["pts"] == [[1, 2], [4, 5]] and len(saved) == 3
    assert "onerror" not in json.dumps(store.strat(sid)["data"])


def test_uptime_clock_in_nav(app):
    c = setup_admin(app)
    page = c.get("/").data.decode()
    assert 'id="uptime"' in page and 'data-start="' in page and 'data-now="' in page


def test_upload_in_chunks_ends_up_as_the_job_vod(app):
    """No request may be bigger than a chunk: waitress buffers a body before the app can refuse it."""
    from nexus.web.uploads import CHUNK_BYTES, MAX_REQUEST_BYTES
    assert app.config["MAX_CONTENT_LENGTH"] == MAX_REQUEST_BYTES
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    data = bytes(range(256)) * ((CHUNK_BYTES + 5000) // 256)
    uid = send_upload(c, data, "My Match.mp4")
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}",
               data={"mode": "player", "vod": "upload", "no_llm": "1", "no_minimap": "1", "upload_id": uid})
    job = store.job(r.headers["Location"].split("/")[-1])
    assert Path(job.vod_path).read_bytes() == data and job.vod_name == "My Match.mp4"
    assert Path(job.vod_path).name.endswith("_My_Match.mp4") and job.opts["uploaded"]
    assert not list((store.data_dir / "tmp").iterdir())
    # an upload is used once
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "upload", "upload_id": uid})
    assert b"doesn&#39;t exist anymore" in c.get(r.headers["Location"]).data


def test_upload_limits_come_before_the_first_byte(app, monkeypatch):
    import shutil as sh
    from collections import namedtuple
    c = setup_admin(app)
    add_profile(c)
    store = app.extensions["nexus"]["store"]
    tmp = store.data_dir / "tmp"
    assert app.test_client().post("/api/uploads", json={"name": "a.mp4", "size": 1}).status_code == 401
    assert app.test_client().put("/api/uploads/x?offset=0", data=b"x").status_code == 401
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(sh, "disk_usage", lambda p: usage(0, 0, 1024 ** 3 + 1000))
    assert c.post("/api/uploads", json={"name": "a.mp4", "size": 5000}).status_code == 507
    # what is still to come for another upload counts as used
    assert c.post("/api/uploads", json={"name": "a.mp4", "size": 800}).status_code == 200
    assert c.post("/api/uploads", json={"name": "b.mp4", "size": 800}).status_code == 507
    monkeypatch.undo()
    store.create_job("held", add_profile(c, "other", "ONE"), MATCH_ID, "team")
    store.set("max_jobs_per_user", "1")
    r = c.post("/api/uploads", json={"name": "a.mp4", "size": 10})
    assert r.status_code == 429 and "already have 1 report" in r.json["error"]
    assert [f.stat().st_size for f in tmp.iterdir()] == [0]       # only the empty part of the upload that passed


def test_upload_position_owner_and_incomplete_file(app):
    from nexus.web.uploads import CHUNK_BYTES
    c = setup_admin(app)
    pid = add_profile(c)
    bob = make_user(app, c, "bob")
    uid = c.post("/api/uploads", json={"name": "a.mp4", "size": 10}).json["id"]
    assert c.put(f"/api/uploads/{uid}?offset=0", data=b"12345").json["received"] == 5
    # the answer got lost and the piece is sent again: the client is told where to go on
    r = c.put(f"/api/uploads/{uid}?offset=0", data=b"12345")
    assert r.status_code == 409 and r.json["received"] == 5
    assert c.put(f"/api/uploads/{uid}?offset=5", data=b"123456").status_code == 400     # past the end
    assert c.put(f"/api/uploads/{uid}", data=b"1").status_code == 400
    assert c.put(f"/api/uploads/{uid}?offset=5", data=b"x" * (CHUNK_BYTES + 1)).status_code == 400
    # someone else's upload doesn't exist for you, and it can't be turned into a job half-finished
    assert bob.put(f"/api/uploads/{uid}?offset=5", data=b"1").status_code == 404
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "upload", "upload_id": uid})
    assert b"isn&#39;t complete" in c.get(r.headers["Location"]).data
    bob_pid = add_profile(bob)
    r = bob.post(f"/profiles/{bob_pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "upload", "upload_id": uid})
    assert b"exist anymore" in bob.get(r.headers["Location"]).data


def test_abandoned_uploads_are_removed(app, monkeypatch):
    import time as t
    from nexus.web.uploads import MAX_OPEN_PER_USER, STALE_S
    c = setup_admin(app)
    tmp = app.extensions["nexus"]["store"].data_dir / "tmp"
    for _ in range(MAX_OPEN_PER_USER + 2):           # page reloaded in the middle of an upload
        assert c.post("/api/uploads", json={"name": "a.mp4", "size": 10}).status_code == 200
    assert len(list(tmp.iterdir())) == MAX_OPEN_PER_USER
    real = t.time
    monkeypatch.setattr("nexus.web.uploads.time.time", lambda: real() + STALE_S + 1)
    assert make_user(app, c, "bob").post("/api/uploads", json={"name": "a.mp4", "size": 10}).status_code == 200
    assert len(list(tmp.iterdir())) == 1


def test_roster_drafts(app):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    me = add_profile(c)
    other = add_profile(c, name="Burn", tag="#NOW")
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter"}, {"pid": other, "kind": "sub"}], maps=["Bind", "Haven"])
    page = c.get(f"/teams/{tid}/drafts").data.decode()
    assert "Drafts" in page and "No drafts for Bind yet" in page
    # new draft: starters in the slots
    r = c.post(f"/teams/{tid}/drafts", data={"map": "Bind"})
    did = int(r.headers["Location"].split("d=")[1])
    d = store.draft(did)
    assert d["map"] == "Bind" and d["data"]["slots"][0]["pid"] == me and len(d["data"]["slots"]) == 5
    page = c.get(r.headers["Location"]).data.decode()
    boot = json.loads(page.split('id="draft-boot">')[1].split("</script>")[0].replace("<\\/", "</"))
    assert boot["draft"]["id"] == did and {p["pid"] for p in boot["players"]} == {me, other}
    assert any(a["name"] == "Omen" for a in boot["agents"])
    # save: only known players / agents and typed fields survive (no HTML from another member)
    bad = {"slots": [{"pid": other, "agent": "Omen", "alt": "Clove", "note": "smokes + IGL"},
                     {"pid": 999, "agent": "<img src=x onerror=alert(1)>", "alt": 5, "note": ["x"]},
                     {"pid": "1; drop", "agent": "Sova"}, "junk"] + [{}] * 5,
           "status": "main", "notes": "try the A split", "evil": "<script>"}
    assert c.post(boot["save_url"], data={"x": "1"}).status_code == 400
    r = c.post(boot["save_url"], json={"name": "Double controller", "data": bad})
    assert r.status_code == 200 and r.get_json()["ok"]
    d = store.draft(did)
    s = d["data"]["slots"]
    assert d["name"] == "Double controller" and d["data"]["status"] == "main" and "evil" not in d["data"]
    assert s[0] == {"pid": other, "agent": "Omen", "alt": "Clove", "note": "smokes + IGL"}
    assert s[1] == {"pid": None, "agent": "", "alt": "", "note": "['x']"} and s[2]["pid"] is None and s[2]["agent"] == "Sova"
    assert len(s) == 5 and "onerror" not in json.dumps(d["data"])
    # copy, other map, list counts
    r = c.post(f"/teams/{tid}/drafts", data={"map": "Bind", "from": f"copy:{did}"})
    assert store.draft(int(r.headers["Location"].split("d=")[1]))["data"]["slots"][0]["agent"] == "Omen"
    assert c.post(f"/teams/{tid}/drafts", data={"map": "Nowhere"}).status_code == 400
    assert len(store.drafts(tid, "Bind")) == 2 and store.drafts(tid, "Haven") == []
    # a teammate with access can edit but not delete someone else's draft
    c2 = make_user(app, c, "burn")
    assert c2.get(f"/teams/{tid}/drafts").status_code == 404                # not shared yet
    store.add_team_access(tid, store.user_by_name("burn").id)
    assert c2.get(f"/teams/{tid}/drafts?map=Bind&d={did}").status_code == 200
    assert c2.post(f"/api/teams/{tid}/drafts/{did}", json={"name": "B stack"}).status_code == 200
    assert c2.post(f"/teams/{tid}/drafts/{did}/delete").status_code == 403
    # outsiders don't see it, the owner deletes
    assert c.post(f"/teams/{tid}/drafts/{did}/delete").status_code == 302 and store.draft(did) is None


def _run_with_model(app, c, monkeypatch, answer, parallel=1):
    """One coaching run; answer(n) is called for the n-th model request and may raise."""
    from nexus.coach.ollama import Ollama
    pid = add_profile(c)
    ext = app.extensions["nexus"]
    store = ext["store"]
    store.set("ollama_parallel", str(parallel))
    calls = []

    def chat_json(self, *a, **k):
        calls.append(1)
        return answer(len(calls))
    monkeypatch.setattr(Ollama, "check", lambda self: None)
    monkeypatch.setattr(Ollama, "chat_json", chat_json)
    store.create_job("j1", pid, MATCH_ID, "both", options={"team_review": True})
    ext["runner"]._run("j1")
    return store.job("j1"), calls


def test_job_fails_when_the_model_fails_on_every_round(app, monkeypatch):
    def down(n):
        raise RuntimeError("Ollama request failed: timed out")
    job, calls = _run_with_model(app, setup_admin(app), monkeypatch, down)
    assert job.status == "error" and "failed on all 6 rounds" in job.error and "timed out" in job.error
    assert not job.html_path
    assert len(calls) == 3        # gave up: no waiting for the other rounds, the match review or the team


def test_no_match_review_when_every_round_failed_below_the_stop_limit(app, monkeypatch):
    """With more parallel requests than rounds the stop limit is never reached."""
    def down(n):
        raise RuntimeError("timed out")
    job, calls = _run_with_model(app, setup_admin(app), monkeypatch, down, parallel=8)
    assert job.status == "error" and "failed on all 6 rounds" in job.error
    assert len(calls) == 6


def test_report_names_the_rounds_the_model_failed_on(app, monkeypatch):
    def flaky(n):
        if n in (1, 2, 4, 5):     # never 3 in a row: the run goes on
            raise RuntimeError("timed out")
        return {"summary": "Fight at A", "importance": 1}
    job, calls = _run_with_model(app, setup_admin(app), monkeypatch, flaky)
    assert job.status == "done" and "failed on 4 of 6 rounds (R1, R2, R4, R5)" in job.log
    report = json.loads(Path(job.json_path).read_text())
    assert report["meta"]["llm_failed_rounds"] == [1, 2, 4, 5] and not report["meta"]["llm_gave_up"]
    assert "failed on 4 of 6 rounds (R1, R2, R4, R5)" in Path(job.html_path).read_text()
    assert len(calls) > 6         # match review and team review still ran


def test_no_warning_in_a_report_without_model_problems(app, monkeypatch):
    job, _ = _run_with_model(app, setup_admin(app), monkeypatch, lambda n: {"summary": "Fight at A", "importance": 1})
    assert job.status == "done" and "The model failed" not in Path(job.html_path).read_text()


def test_premier_scouting_veto_reviews_and_brief(app, monkeypatch):
    from datetime import datetime
    import synth_history as sh
    from nexus import pipeline
    import nexus.discord as discord
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10, roster_in_match=True))
    posted = []
    monkeypatch.setattr(discord, "post", lambda url, content="", embeds=None, session=None: posted.append(embeds))
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    add_profile(c)
    r = c.post("/teams", data={"premier_name": "Red Squad#RED", "premier_region": "eu"})
    tid = int(r.headers["Location"].rsplit("/", 1)[1])
    assert _wait_stats(app, f"premier:{tid}")["status"] == "done"
    for m in store.team(tid).member_list:
        _wait_stats(app, f"import:{m['pid']}")
    page = c.get(f"/teams/{tid}/premier").data.decode()
    assert "This week" in page and "Premier matches" in page and "Season schedule" in page
    # the week's map box: from the built-in or the API schedule (whichever is read first), or not known yet.
    # Don't check for a specific map: the schedule moves on every week, so a hard-coded map breaks the test.
    assert "Premier week" in page or "known yet" in page
    _wait_stats(app, f"schedule:{tid}")

    # scout the division: our own team is skipped, the rival gets a page, the empty team too
    c.post(f"/teams/{tid}/premier/scout", data={"division": "1"})
    st = _wait_stats(app, f"scout:{tid}")
    assert st["status"] == "done", st
    pj = app.extensions["nexus"]["premier"]
    idx = pj.scout_index(tid)
    assert set(idx["teams"]) == {"team-2", "team-3"} and idx["division"]["division"] == 12
    s = pj.scouted(tid, "team-2")
    assert s["matches"] >= 5 and s["players"] and all(p["name"].startswith("blue") for p in s["players"])
    assert s["maps"] and pj.scouted(tid, "team-3")["matches"] == 0
    page = c.get(f"/teams/{tid}/premier/division").data.decode()
    assert "Blue Bandits" in page and "Green Goats" in page and "(you)" in page and "Division 12" in page
    page = c.get(f"/teams/{tid}/premier/team/team-2").data.decode()
    assert "How to play them" in page and "Map veto" in page and "first duels" in page and "pick" in page
    assert c.get(f"/teams/{tid}/premier/team/nope").status_code == 404

    # this week's map comes from the season schedule (Bind); the brief is built for it
    page = c.get(f"/teams/{tid}/premier").data.decode()
    assert ">Bind<" in page and "Premier week 2" in page and "Season schedule" in page
    assert store.team(tid).map_list == ["Ascent", "Bind"]                    # follows the stage map pool
    page = c.get(f"/teams/{tid}/premier/brief").data.decode()
    assert "Our numbers on Bind" in page and "Who you might meet" in page
    # by hand for this week
    c.post(f"/teams/{tid}/premier/settings", data={"week_map": "Ascent"})
    assert ">Ascent<" in c.get(f"/teams/{tid}/premier").data.decode()

    # reviews of our Premier matches (no model here: numbers only), not posted without a webhook
    c.post(f"/teams/{tid}/premier/reviews", data={"post": "1"})
    st = _wait_stats(app, f"review:{tid}")
    assert st["status"] == "done", st
    revs = pj.reviews(tid)
    assert 1 <= len(revs) <= 3
    rv = revs[0]
    assert len(rv["players"]) == 5 and rv["score"] and isinstance(rv["key_rounds"], list)
    page = c.get(f"/teams/{tid}/premier/review/{rv['match_id']}").data.decode()
    assert "Rounds that decided it" in page and "Every player" in page
    assert posted == []
    # a second run finds nothing new
    c.post(f"/teams/{tid}/premier/reviews", data={})
    _wait_stats(app, f"review:{tid}")
    assert len(pj.reviews(tid)) == len(revs)
    # 4.16: the reviewed match can be checked in right away, and the Discord post links there
    page = c.get(f"/teams/{tid}/checkin?m={rv['match_id']}").data.decode()
    assert f'value="{rv["match_id"]}"' in page or "Nexus doesn't know which player you are" in page
    assert store.get("site_url") == "http://localhost"
    from nexus.web.premierjobs import checkin_line
    line = checkin_line(store.get("site_url"), tid, rv)
    assert line.startswith("How did it go?") and f"http://localhost/teams/{tid}/checkin?m=" in line
    assert checkin_line("", tid, rv) == ""

    # match-day brief on Discord: settings, then the scheduler posts it once inside the window
    t = store.team(tid)
    store.update_team(tid, discord={**t.discord_info, "prep_url": "https://discord.com/api/webhooks/1/x"})
    c.post(f"/teams/{tid}/premier/settings", data={"on": "1", "days": ["4"], "time": "20:00", "before": "60"})
    cfg = store.team(tid).sync_info["brief"]
    assert cfg["on"] and cfg["days"] == [4] and cfg["time"] == "20:00"
    tick = app.extensions["nexus"]["ticks"][0]
    assert tick(datetime(2026, 10, 30, 18, 30)) == []                 # Friday, too early
    assert tick(datetime(2026, 10, 30, 19, 15)) == [tid]              # 45 min before
    assert tick(datetime(2026, 10, 30, 19, 40)) == []                 # once a day
    assert posted and "Match day: Ascent" in posted[-1][0]["title"]
    sr = app.extensions["nexus"]["stats"]
    sr.shutdown()


def test_scouting_veto_and_season_map():
    from datetime import datetime, timezone
    from nexus.stats.scouting import how_to_play, veto
    from nexus.web.premier_views import season_week_map
    v = veto({"Bind": {"games": 6, "wins": 5}, "Lotus": {"games": 4, "wins": 1}, "Ascent": {"games": 2, "wins": 1}},
             {"Bind": {"games": 3, "wins": 1}, "Lotus": {"games": 5, "wins": 5}, "Haven": {"games": 2, "wins": 1}},
             ["Ascent", "Bind", "Haven", "Lotus"], {"Bind": {"attack": .6, "defense": .45}}, {"Bind": {"attack": .5, "defense": .5}})
    assert v["pick"] == "Bind" and v["bans"][0] == "Lotus" and len(v["bans"]) == 2
    assert next(r for r in v["rows"] if r["map"] == "Bind")["side"] == "attack"
    assert season_week_map({"x": [{"starts_at": "2026-10-26T00:00:00Z", "ends_at": "2026-11-02T00:00:00Z",
                                    "map_selection": {"maps": [{"name": "Sunset"}]}}]},
                           datetime(2026, 10, 30, tzinfo=timezone.utc)) == "Sunset"
    assert season_week_map({"events": []}) is None and season_week_map(None) is None
    assert how_to_play({"matches": 0}) == ["No Premier matches of this team found yet."]


def test_progress_and_training_pages(app, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(24)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrik(history, full_depth=10))
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    me = add_profile(c)
    assert "No games yet" in c.get(f"/profiles/{me}/progress").data.decode()
    c.post(f"/profiles/{me}/stats/import")
    assert _wait_stats(app, f"import:{me}")["status"] == "done"
    page = c.get(f"/profiles/{me}/progress").data.decode()
    assert "Clutches, retakes, post-plants" in page and "KAST" in page and "1v1" in page
    assert 'id="when"' in page and "Game in the session" in page and "After losses" in page     # 4.17
    # rank over time from the RR history (kept locally), with a chart
    assert "Rank over time" in page and "<svg class=\"rkc\"" in page and " RR</div>" in page
    entries = app.extensions["nexus"]["stats"].rank_path(me)
    assert entries.exists() and len(json.loads(entries.read_text())["entries"]) >= 5
    # 4.16.4: the newest game comes from the live history (the stored one lags behind) and isn't doubled
    ents = json.loads(entries.read_text())["entries"]
    newest = max((r for r in app.extensions["nexus"]["stats"].games(me).rows() if r.get("queue") == "competitive"),
                 key=lambda r: r["started_at"])
    assert ents[-1]["match_id"] == newest["match_id"] and len({e["match_id"] for e in ents}) == len(ents)
    log = "\n".join(app.extensions["nexus"]["stats"].status(f"import:{me}")["log"])
    assert "· recent rank: " in log and "· rank history: " in log
    entries.unlink()                                       # without it: the rank shown in each match
    page = c.get(f"/profiles/{me}/progress").data.decode()
    assert "Rank over time" in page and "Platinum 1" in page and "no RR yet" in page
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter", "roles": ["Support"]}], maps=["Ascent", "Bind"])
    page = c.get(f"/profiles/{me}/training").data.decode()
    assert "Aim fundamentals" in page and "Your warm-up" in page and "Fights by range" in page
    assert "Squad: agents to learn" in page and "Premier-ready" in page
    assert "0-day streak" in page
    assert c.post(f"/profiles/{me}/training/done").status_code == 302
    assert "1-day streak" in c.get(f"/profiles/{me}/training").data.decode()
    c.post(f"/profiles/{me}/training/done")                          # undo
    assert "0-day streak" in c.get(f"/profiles/{me}/training").data.decode()
    # another user can't tick someone else's routine
    c2 = make_user(app, c, "burn")
    assert c2.post(f"/profiles/{me}/training/done").status_code == 404
    app.extensions["nexus"]["stats"].shutdown()


def test_look_and_feel_search_and_lineups(app):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    me = add_profile(c)
    page = c.get("/").data.decode()
    assert 'class="skin-classic a-count a-lift a-tabs a-loaders a-toasts"' in page and "ui.js" in page and "styles/" not in page
    # pick a style and switch two animations off
    r = c.post("/account", data={"look": "1", "style": "hud", "anim_count": "1", "anim_tabs": "1", "anim_loaders": "1"})
    assert r.status_code == 302
    page = c.get("/").data.decode()
    assert 'class="skin-hud a-count a-tabs a-loaders"' in page and "styles/hud.css" in page
    assert "fonts.googleapis.com" not in page                                  # fonts ship with Nexus
    assert c.get("/static/fonts/rajdhani-600.woff2").status_code == 200
    assert c.get("/static/styles/hud.css").status_code == 200
    c.post("/account", data={"look": "1", "style": "<script>"})            # unknown style -> classic
    assert "skin-classic" in c.get("/").data.decode()
    assert "Look &amp; feel" in c.get("/account").data.decode()
    # menu at the top or on the left; a form without the field keeps the choice
    assert " nav-top" not in c.get("/").data.decode()
    c.post("/account", data={"look": "1", "style": "neon", "nav": "top"})
    page = c.get("/").data.decode()
    assert 'class="skin-neon nav-top' in page and not re.search(r'class="ngroup" data-g="\w+" open', page)   # dropdowns start closed
    c.post("/account", data={"look": "1", "style": "classic"})
    assert 'class="skin-classic nav-top' in c.get("/").data.decode()
    c.post("/account", data={"look": "1", "style": "classic", "nav": "side"})
    assert " nav-top" not in c.get("/").data.decode()
    # Ctrl+K index: players, team tabs, maps, drafts, strats
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter"}], maps=["Bind"])
    store.create_draft(tid, store.user_by_name("manuel").id, "Bind", "Double controller", {"slots": []})
    idx = c.get("/api/search-index").get_json()
    labels = {i["label"] for i in idx}
    assert "adv1ce#LFT" in labels and "Squad · drafts" in labels and "Bind · game plans" in labels and "Double controller" in labels
    assert "Squad · lineups" in labels and "Settings" in labels
    assert all(i["url"].startswith("/") for i in idx)
    # lineups: add with a YouTube link (thumbnail), refuse javascript: links, delete
    r = c.post(f"/teams/{tid}/lineups", data={"map": "Bind", "agent": "Omen", "title": "A Short smoke", "side": "attack",
                                              "site": "A", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12", "notes": "from spawn"})
    assert r.status_code == 302
    rows = store.lineups(tid, "Bind")
    assert len(rows) == 1 and rows[0]["agent"] == "Omen" and rows[0]["site"] == "A"
    page = c.get(f"/teams/{tid}/lineups?map=Bind").data.decode()
    assert "A Short smoke" in page and "i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg" in page
    c.post(f"/teams/{tid}/lineups", data={"map": "Bind", "agent": "Omen", "title": "bad", "url": "javascript:alert(1)"})
    assert len(store.lineups(tid, "Bind")) == 1
    c.post(f"/teams/{tid}/lineups", data={"map": "Bind", "agent": "Nobody", "title": "x"})
    assert len(store.lineups(tid, "Bind")) == 1
    assert c.post(f"/teams/{tid}/lineups/{rows[0]['id']}/delete").status_code == 302 and store.lineups(tid) == []


def test_clip_info():
    from nexus.web.lineups import clip_info
    assert clip_info("https://youtu.be/abcdefghijk")["thumb"].endswith("/abcdefghijk/mqdefault.jpg")
    assert clip_info("https://www.youtube.com/shorts/abcdefghijk")["thumb"]
    assert clip_info("https://medal.tv/games/valorant/clips/xyz")["thumb"] is None
    assert clip_info("https://youtube.com/watch?v=<script>")["thumb"] is None
    assert clip_info("javascript:alert(1)") is None and clip_info("ftp://x/y") is None and clip_info("") is None


def test_availability_and_subs(app):
    from datetime import date
    from nexus.web.availability import day_summary, match_days, summary_line
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pids = [add_profile(c, name=f"P{i}", tag="#T") for i in range(6)]
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": p, "kind": "starter" if i < 5 else "sub"} for i, p in enumerate(pids)], maps=["Bind"])
    # every day a match day, so the page always has today
    info = store.team(tid).sync_info
    info["brief"] = {"on": False, "days": list(range(7)), "time": "20:00", "before": 60}
    store.update_team(tid, sync=info)
    today = date.today().isoformat()
    page = c.get(f"/teams/{tid}/premier/availability").data.decode()
    assert "Who can play" in page and "0 ✓" in page and "P5" in page and "Nobody has answered yet" in page
    # without an in-game name or a link, Nexus doesn't know who you are: nothing to click
    assert "doesn&#39;t know which player you are" in page.replace("doesn't", "doesn&#39;t") and 'class="cell' in page
    assert ' disabled>' in page and '<tr class="av-me">' not in page
    assert c.post(f"/api/teams/{tid}/availability", json={"day": today, "state": "yes"}).status_code == 403
    # the owner's in-game name is P0's Riot ID: that's their row, at the top, and the only one they can change
    owner = store.user_by_name("manuel")
    store.update_user(owner.id, display_name=store.profile(pids[0]).riot_id.upper())
    page = c.get(f"/teams/{tid}/premier/availability").data.decode()
    tbl = page[page.index('id="av"'):]
    assert '<tr class="av-me">' in tbl and tbl.index(">You<") < tbl.index(">P1<")                 # your row first
    assert page.count('data-day="') - page.count(' disabled>') == page.count(f'data-pid="{pids[0]}" data-day=')     # only your cells
    assert c.post(f"/api/teams/{tid}/availability", json={"pid": pids[1], "day": today, "state": "yes"}).status_code == 403
    # yes for four starters (they set it themselves), no for P0 (the owner, through the page), the sub is free
    for p in pids[1:]:
        store.set_availability(tid, p, today, "yes", "", owner.id)
    r = c.post(f"/api/teams/{tid}/availability", json={"pid": pids[0], "day": today, "state": "no", "note": "<b>away</b>"})
    assert r.status_code == 200, r.data
    marks = store.availability(tid, [today])
    assert marks[(pids[0], today)] == {"state": "no", "note": "<b>away</b>"}
    page = c.get(f"/teams/{tid}/premier/availability").data.decode()
    assert "5 ✓" in page and "5 confirmed: you can play" in page and "P0</b> can&#39;t play" in page.replace("can't", "can&#39;t") and "&lt;b&gt;away" in page
    assert "<b>away</b>" not in page
    # bad input: someone else, bad day, not JSON
    assert c.post(f"/api/teams/{tid}/availability", json={"pid": 999, "day": today, "state": "yes"}).status_code == 403
    assert c.post(f"/api/teams/{tid}/availability", json={"day": "soon", "state": "yes"}).status_code == 400
    assert c.post(f"/api/teams/{tid}/availability", data={"pid": pids[1]}).status_code == 400
    # empty state clears your mark
    c.post(f"/api/teams/{tid}/availability", json={"day": today, "state": ""})
    assert (pids[0], today) not in store.availability(tid)
    c.post(f"/api/teams/{tid}/availability", json={"day": today, "state": "no", "note": "<b>away</b>"})
    # a teammate: recognised by the in-game name they signed up with, only their own row
    make_user(app, c, "mate")
    mid = store.user_by_name("mate").id
    store.add_team_access(tid, mid)
    m2 = login(app, "mate", "user-pass-123")
    assert m2.post(f"/api/teams/{tid}/availability", json={"day": today, "state": "no"}).status_code == 403
    store.update_user(mid, display_name=store.profile(pids[2]).riot_id)
    assert m2.post(f"/api/teams/{tid}/availability", json={"day": today, "state": "maybe"}).status_code == 200
    assert store.availability(tid, [today])[(pids[2], today)]["state"] == "maybe"
    assert m2.post(f"/api/teams/{tid}/availability", json={"pid": pids[3], "day": today, "state": "no"}).status_code == 403
    # a link to the player counts too (and comes first)
    store.update_user(mid, display_name="")
    store.update_team(tid, members=[dict(m, user_id=mid) if m["pid"] == pids[2] else m for m in store.team(tid).member_list])
    assert m2.post(f"/api/teams/{tid}/availability", json={"pid": pids[2], "day": today, "state": "maybe"}).status_code == 200
    # brief shows who's playing
    assert "Who&#39;s playing" in c.get(f"/teams/{tid}/premier/brief?map=Bind").data.decode().replace("Who's", "Who&#39;s")

    # pure: the sub who plays the missing agent comes first
    members = [{"pid": 1, "name": "A", "kind": "starter"}, {"pid": 2, "name": "B", "kind": "sub"}, {"pid": 3, "name": "C", "kind": "sub"}]
    d = {"day": today, "label": "x", "map": "Bind"}
    marks = {(1, today): {"state": "no"}, (2, today): {"state": "yes"}, (3, today): {"state": "maybe"}}
    rows = {2: [{"agent": "Sage", "won": 1}] * 3, 3: [{"agent": "Sova", "won": 1}] * 4}
    s = day_summary(d, members, marks, [{"pid": 1, "agent": "Sova"}], rows)
    assert s["missing"][0]["subs"][0]["name"] == "C" and "plays Sova (4 games" in s["missing"][0]["subs"][0]["why"]
    assert "A can't play (Sova) → C plays Sova" in summary_line(s)
    days = match_days([5, 6], None, date(2026, 10, 30))
    assert [x["label"] for x in days] == ["Sat 31.10.", "Sun 01.11.", "Sat 07.11.", "Sun 08.11."]


def test_decision_quiz(app, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    from nexus.coach.ollama import Ollama
    history = sh.build_history(24)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrik(history, full_depth=10))
    seen = {}

    def chat_json(self, system, user, schema):
        ids = schema["properties"]["questions"]["items"]["properties"]["id"]["enum"]
        seen["user"] = user
        qs = [{"id": i, "question": f"You are alone ({i}). What now?", "options": ["Save", "Play for time", "<script>x</script>"],
               "best": 1, "why": "Time is on your side."} for i in ids]
        qs.append({"id": "nope", "question": "x", "options": ["a", "b", "c"], "best": 0, "why": ""})     # unknown id: dropped
        qs[0]["best"] = 7                                                                                 # out of range: dropped
        return {"questions": qs}
    monkeypatch.setattr(Ollama, "check", lambda self: None)
    monkeypatch.setattr(Ollama, "chat_json", chat_json)
    # the synthetic games have no 1vX / lonely deaths: one made-up moment per game (moments() itself: test_stats)
    import nexus.stats.quiz as qz
    monkeypatch.setattr(qz, "moments", lambda m, pu, mi: [{"kind": "clutch", "t_ms": 60000, "happened": "You lost the 1v2.",
        "facts": {"match_id": m.match_id, "map": m.map_name, "round": 9, "side": "defense", "agent": "Sova", "score": "4–4",
                  "won": False, "time_s": 60, "you_vs": "1v2", "spike": "spike planted on B 10 s ago"}}])
    c = setup_admin(app)
    me = add_profile(c)
    cache = Path(app.extensions["nexus"]["store"].data_dir) / "cache" / "matches"      # the real client caches every match
    cache.mkdir(parents=True, exist_ok=True)
    for d in history:
        (cache / f"{d['metadata']['match_id']}.json").write_text(json.dumps({"status": 200, "data": d}))
    assert "Make my first quiz" in c.get(f"/profiles/{me}/quiz").data.decode()
    c.post(f"/profiles/{me}/stats/import")
    assert _wait_stats(app, f"import:{me}")["status"] == "done"
    assert c.post(f"/profiles/{me}/quiz").status_code == 302
    st = _wait_stats(app, f"quiz:{me}")
    assert st["status"] == "done", st
    sr = app.extensions["nexus"]["stats"]
    q = sr.read_quiz(me)
    assert 2 <= len(q["questions"]) <= 5 and all(x["happened"] and x["map"] for x in q["questions"])
    assert "time_s" in seen["user"] and "happened" not in seen["user"]          # the model never sees the outcome
    page = c.get(f"/profiles/{me}/quiz").data.decode()
    assert "New quiz from my latest games" in page and "quiz-data" in page and "<script>x</script>" not in page.split('id="quiz-data">')[0]
    # score is counted on the server
    n = len(q["questions"])
    r = c.post(f"/api/profiles/{me}/quiz/result", json={"answers": [1] * n})
    assert r.get_json() == {"ok": True, "score": n, "of": n}
    assert c.post(f"/api/profiles/{me}/quiz/result", json={"answers": [1]}).status_code == 400
    assert "Your scores" in c.get(f"/profiles/{me}/quiz").data.decode()
    c2 = make_user(app, c, "burn")
    assert c2.post(f"/profiles/{me}/quiz").status_code == 404
    app.extensions["nexus"]["stats"].shutdown()


def test_server_overview_permission(app, monkeypatch):
    import nexus.web.overview as ov
    from nexus import henrik
    monkeypatch.setattr(ov, "model_usage", lambda url, now=None: {"reachable": False, "loaded": [], "installed": 0, "error": "ConnectionError",
                                                                  "requests_day": 0, "avg_s": None, "tokens_day": 0})
    henrik.USAGE.extend([(time.time(), 200, "match"), (time.time(), 429, "premier")])
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    store.set("henrik_api_key", "HDEV-secret-key")
    page = c.get("/admin/overview").data.decode()
    assert "Server overview" in page and "HenrikDev API" in page and "Rate-limited" in page and "offline" in page
    assert "HDEV-secret-key" not in page and "Match cache" not in page or "Database" in page
    assert 'id="uptime"' in c.get("/").data.decode()                          # the uptime clock in the menu
    # 4.16.1: replay files on the server
    import json as _json
    assert 'id="replays"' in page and "Replay files" in page
    rd = store.data_dir / "replays"
    rd.mkdir(exist_ok=True)
    ids = ["11111111-2222-3333-4444-555555555555", "66666666-7777-8888-9999-000000000000"]
    for i in ids:
        (rd / f"{i}.json.gz").write_bytes(b"x" * 1000)
    (rd / f"{ids[0]}.vrf").write_bytes(b"y" * 5000)
    (rd / f"{ids[0]}.metrics.json").write_text(_json.dumps({"v": 2, "ok": True, "casts": True, "map": "Ascent"}))
    (rd / "not-a-match.json.gz").write_bytes(b"z")
    monkeypatch.setattr(ov, "_cache", {})
    r = ov.replays(store.data_dir, "/nowhere/vrfkit")
    assert r["count"] == 2 and r["vrf"] == 1 and r["week"] == 2 and r["lined_up"] == 1 and r["casts"] == 1
    assert r["maps"] == [("Ascent", 1)] and r["vrfkit_error"] and r["bytes"] == 7000
    page = c.get("/admin/overview").data.decode()
    assert "<b>2</b> matches" in page and "1 of 2" in page and "Ascent: 1" in page
    c2 = make_user(app, c, "darki")
    assert c2.get("/admin/overview").status_code == 403 and 'id="uptime"' not in c2.get("/").data.decode()
    uid = store.user_by_name("darki").id
    # the admin gives the overview (and only that) to darki
    r = c.post(f"/admin/users/{uid}", data={"perm_overview": "1", "vod_dir": ""})
    assert r.status_code == 302 and store.user(uid).perms == "overview" and not store.user(uid).is_admin
    assert c2.get("/admin/overview").status_code == 200 and 'id="uptime"' in c2.get("/").data.decode()
    assert c2.get("/admin/users").status_code == 403 and c2.get("/settings").status_code == 403
    c.post(f"/admin/users/{uid}", data={"vod_dir": ""})                        # and takes it away again
    assert store.user(uid).perms == "" and c2.get("/admin/overview").status_code == 403


def test_report_votes_focus_and_note_hints(app, monkeypatch):
    from nexus.coach.engine import _examples_block, load_votes
    fb = {"summary": "Fight at A", "importance": 2, "key_moment": {"time": "1:05", "what": "You peeked A Main alone"},
          "player": {"went_well": [], "mistakes": ["Peeked <b>alone</b> into two"], "better_option": "Wait for the flash"}}
    c = setup_admin(app)
    job, _ = _run_with_model(app, c, monkeypatch, lambda n: fb)
    assert job.status == "done"
    html = c.get(f"/jobs/{job.id}/report").data.decode()
    assert 'data-fb="1" data-who="you"' in html and "window.VALCOACH_FB" in html and "report_fb.js" in html
    assert "&lt;b&gt;alone" in html                                       # the model's text stays escaped
    text = "Peeked <b>alone</b> into two"
    r = c.post(f"/api/jobs/{job.id}/vote", json={"round": 1, "who": "you", "text": text, "vote": "up"})
    assert r.status_code == 200
    c.post(f"/api/jobs/{job.id}/vote", json={"round": 2, "who": "you", "text": "Play safer", "vote": "down"})
    assert c.post(f"/api/jobs/{job.id}/vote", json={"round": "1", "who": "you", "text": "x", "vote": "up"}).status_code == 400
    assert c.post(f"/api/jobs/{job.id}/vote", json={"round": 1, "who": "boss", "text": "x", "vote": "up"}).status_code == 400
    html = c.get(f"/jobs/{job.id}/report").data.decode()
    assert '"1|Peeked <b>alone<\\/b> into two": "up"' in html                # the vote shows again; no </ in the script
    store = app.extensions["nexus"]["store"]
    notes_dir = store.profile_dir(job.profile_id) / "notes"
    liked, disliked = load_votes(notes_dir)
    assert liked == [text] and disliked == ["Play safer"]
    assert load_votes(notes_dir, job.match_id) == ([], [])                    # never examples from the same match
    blk = _examples_block(["my note"], liked, disliked)
    assert "marked as helpful" in blk and "NOT helpful" in blk and "my note" in blk
    # someone else can't vote on my report
    c2 = make_user(app, c, "burn")
    assert c2.post(f"/api/jobs/{job.id}/vote", json={"round": 1, "who": "you", "text": "x", "vote": "up"}).status_code == 404
    # 🎯 a line as my focus: shows on Training
    pid = job.profile_id
    assert c.post(f"/api/profiles/{pid}/own-focus", json={"focus": "Wait for the flash", "why": "R1", "source": "report"}).status_code == 200
    page = c.get(f"/profiles/{pid}/training").data.decode()
    assert "Your own focus this week" in page and "Wait for the flash" in page and "from a report" in page
    assert c2.post(f"/api/profiles/{pid}/own-focus", json={"focus": "x"}).status_code == 404
    assert c.delete(f"/api/profiles/{pid}/own-focus").status_code == 200
    assert "Your own focus this week" not in c.get(f"/profiles/{pid}/training").data.decode()
    # notes page: tags and the coach's line as a hint (placeholder, not the note itself)
    page = c.get(f"/profiles/{pid}/notes/{job.match_id}").data.decode()
    assert 'class="tg"' in page and "died alone" in page and 'placeholder="Coach said: Fight at A"' in page
    assert ">Fight at A</textarea>" not in page


def test_quiz_categories_ratings_and_training(app, monkeypatch):
    c = setup_admin(app)
    me = add_profile(c)
    sr = app.extensions["nexus"]["stats"]
    qs = [{"id": f"q{i}", "kind": k, "kind_label": "x", "map": "Bind", "round": i, "side": "attack", "match_id": "m",
           "question": f"Q{i}?", "options": ["a", "b", "c"], "best": 0, "why": "because", "happened": "lost", "won": False}
          for i, k in enumerate(["clutch", "clutch", "alone"])]
    sr.save_quiz(me, {"created": 1, "questions": qs, "results": []})
    for answers in ([1, 1, 0], [1, 0, 0], [2, 1, 0]):                 # clutch: 1 of 6 right, alone: 3 of 3
        assert c.post(f"/api/profiles/{me}/quiz/result", json={"answers": answers}).status_code == 200
    page = c.get(f"/profiles/{me}/quiz").data.decode()
    assert "Alone at the end" in page and "1/6" in page and "3/3" in page
    page = c.get(f"/profiles/{me}/training").data.decode()
    assert "Decisions when you&#39;re alone" in page and "Clutch checklist" in page and "1 of 6 times" in page
    assert "Taking fights without your team" not in page
    # ratings go into the bank and the next prompt
    assert c.post(f"/api/profiles/{me}/quiz/rate", json={"id": "q0", "rating": "good"}).status_code == 200
    assert c.post(f"/api/profiles/{me}/quiz/rate", json={"id": "q1", "rating": "obvious"}).status_code == 200
    assert c.post(f"/api/profiles/{me}/quiz/rate", json={"id": "q1", "rating": "meh"}).status_code == 400
    assert c.post(f"/api/profiles/{me}/quiz/rate", json={"id": "nope", "rating": "good"}).status_code == 400
    from nexus.stats.quiz import rated_block
    blk = rated_block(sr.read_quiz(me)["bank"])
    assert "Q0? Best call: a" in blk and "(too obvious) Q1?" in blk
    # quiz → own focus → team focus page and brief
    tid = app.extensions["nexus"]["store"].create_team(app.extensions["nexus"]["store"].user_by_name("manuel").id, "Squad")
    app.extensions["nexus"]["store"].update_team(tid, members=[{"pid": me, "kind": "starter"}], maps=["Bind"])
    c.post(f"/api/profiles/{me}/own-focus", json={"focus": "Play the timer", "source": "quiz"})
    sr.save_quiz(me, sr.read_quiz(me))
    page = c.get(f"/teams/{tid}/premier/brief?map=Bind").data.decode()
    assert "🎯 Play the timer" in page


def test_strat_step_calls_and_availability_reminder(app, monkeypatch):
    import nexus.discord as discord
    from datetime import date
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pids = [add_profile(c, name=f"P{i}", tag="#T") for i in range(5)]
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": p, "kind": "starter"} for p in pids], maps=["Testmap"],
                      discord={"prep_url": "https://discord.com/api/webhooks/1/x"})
    # strat: each step keeps its call
    r = c.post(f"/teams/{tid}/strats", data={"name": "B split", "map": "Testmap", "side": "attack"})
    sid = int(r.headers["Location"].rsplit("/", 1)[1])
    c.post(f"/api/teams/{tid}/strats/{sid}", json={"data": {"steps": [{"name": "Setup", "call": "1:20 smokes" * 30, "items": []},
                                                                    {"name": "Go", "call": 5, "items": []}]}})
    steps = store.strat(sid)["data"]["steps"]
    assert steps[0]["call"].startswith("1:20 smokes") and len(steps[0]["call"]) == 200 and steps[1]["call"] == "5"
    page = c.get(f"/teams/{tid}/strats/{sid}").data.decode()
    assert 'id="sb-stepcall"' in page and 'id="sb-stepmode"' in page
    # availability: notes in the day card, reminder pings only players with an ID
    info = store.team(tid).sync_info
    info["brief"] = {"on": False, "days": list(range(7)), "time": "20:00", "before": 60}
    store.update_team(tid, sync=info)
    today = date.today().isoformat()
    store.update_user(store.user_by_name("manuel").id, display_name=store.profile(pids[0]).riot_id)
    r = c.post(f"/api/teams/{tid}/availability", json={"day": today, "state": "maybe", "note": "from 21:00"})
    assert r.status_code == 200, r.data
    assert "from 21:00" in c.get(f"/teams/{tid}/premier/availability").data.decode()
    c.post(f"/teams/{tid}/premier/availability/discord-ids", data={f"did_{pids[1]}": "284019573925183488", f"did_{pids[2]}": "not-an-id"})
    ms = {m["pid"]: m for m in store.team(tid).member_list}
    assert ms[pids[1]]["discord_id"] == "284019573925183488" and "discord_id" not in ms[pids[2]]
    sent = []
    monkeypatch.setattr(discord, "post", lambda url, content="", embeds=None, session=None, mentions=None: sent.append((content, mentions)))
    r = c.post(f"/teams/{tid}/premier/availability/remind")
    assert r.status_code == 302 and sent
    content, mentions = sent[0]
    assert "<@284019573925183488>" in content and "P2" in content and "P0" not in content.split("\n")[1] and mentions == ["284019573925183488"]
    # a teammate can't change the IDs
    c2 = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert c2.post(f"/teams/{tid}/premier/availability/discord-ids", data={}).status_code == 403


def test_discord_mentions_are_limited():
    from nexus import discord
    seen = []

    class S:
        def post(self, url, json=None, timeout=None, **k):
            seen.append(json)
            return type("R", (), {"status_code": 204, "text": ""})()
    discord.post("https://discord.com/api/webhooks/1/x", "hi <@1> @everyone", session=S(), mentions=["123456789012345678", "x"])
    discord.post("https://discord.com/api/webhooks/1/x", "hi", session=S())
    assert seen[0]["allowed_mentions"] == {"parse": [], "users": ["123456789012345678"]}
    assert seen[1]["allowed_mentions"] == {"parse": []}


def test_model_picker_claude_permission_and_runs(app, monkeypatch):
    from nexus.coach import llm as L
    from nexus.coach.ollama import Ollama
    import nexus.web.models as wm
    monkeypatch.setattr(wm, "local_models", lambda url: ["gemma4:26b", "qwen3.8:27b"])
    used = []
    monkeypatch.setattr(Ollama, "check", lambda self: None)
    monkeypatch.setattr(L.ClaudeLLM, "chat_json", lambda self, system, user, schema, **k: used.append(self.model) or {"questions": []})
    monkeypatch.setattr(Ollama, "chat_json", lambda self, system, user, schema, **k: used.append(self.model) or {"questions": []})
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    store.set("ollama_model", "gemma4:26b")
    me = add_profile(c)
    # no key: only local models
    page = c.get(f"/profiles/{me}/quiz").data.decode()
    assert 'name="llm"' in page and "qwen3.8:27b (local)" in page and "Claude" not in page.split('name="llm"')[1][:400]
    # the admin adds a key and settings
    r = c.post("/settings", data={"claude_api_key": "sk-ant-test-1234", "claude_models": "claude-haiku-5-5, claude-sonnet-5-5",
                                  "claude_budget_usd": "15", "claude_fallback": "1", "llm_auto": "claude:claude-haiku-5-5",
                                  "ollama_temperature": "0.3", "ollama_num_ctx": "16384", "ollama_parallel": "4", "ollama_timeout_s": "300",
                                  "sample_fps": "2", "workers": "1", "max_upload_gb": "20", "max_jobs_per_user": "3",
                                  "minimap_roi": store.get("minimap_roi"), "killfeed_roi": store.get("killfeed_roi")})
    assert r.status_code == 302
    assert store.get("claude_api_key") == "sk-ant-test-1234" and store.get("llm_auto") == "claude:claude-haiku-5-5" and store.get("claude_budget_usd") == "15"
    settings = c.get("/settings").data.decode()
    assert "…1234" in settings and "sk-ant-test-1234" not in settings
    assert c.post("/settings", data={"claude_models": "gpt-4, <b>"}).status_code == 302 and store.get("claude_models") == "claude-haiku-5-5, claude-sonnet-5-5"
    page = c.get(f"/profiles/{me}/quiz").data.decode()
    assert "☁ Claude Sonnet 5.5" in page and "☁ Claude Haiku 5.5" in page
    # a run with the picked model; the pick is remembered as the default
    sr = app.extensions["nexus"]["stats"]
    sr.games(me).save({"version": 1, "games": {}, "puuid": ""})
    import nexus.stats.quiz as qz
    monkeypatch.setattr(qz, "pick", lambda found, n=6: [{"id": f"q{i}", "kind": "clutch", "happened": "x", "facts": {"map": "Bind", "round": 1, "side": "attack", "match_id": "m", "won": False}} for i in range(3)])
    c.post(f"/profiles/{me}/quiz", data={"llm": "claude:claude-sonnet-5-5"})
    _wait_stats(app, f"quiz:{me}")
    assert used[-1] == "claude-sonnet-5-5"
    assert 'value="claude:claude-sonnet-5-5" selected' in c.get(f"/profiles/{me}/quiz").data.decode()
    # automatic jobs use the "automatic" model
    llm, _ = sr._llm(store.profile(me), sr.AUTO)
    assert llm.model == "claude-haiku-5-5"
    # a user without "Can use Claude" can't pick it, even by sending the value
    c2 = make_user(app, c, "burn")
    p2 = add_profile(c2, name="Burn", tag="#NOW")
    assert "Claude" not in c2.get(f"/profiles/{p2}/quiz").data.decode().split('name="llm"')[1][:400]
    c2.post(f"/profiles/{p2}/quiz", data={"llm": "claude:claude-sonnet-5-5"})
    _wait_stats(app, f"quiz:{p2}")
    assert used[-1] == "gemma4:26b"
    uid = store.user_by_name("burn").id
    c.post(f"/admin/users/{uid}", data={"perm_claude": "1", "vod_dir": ""})
    assert store.user(uid).can("claude") and not store.user(uid).can("overview")
    assert "☁ Claude Sonnet 5.5" in c2.get(f"/profiles/{p2}/quiz").data.decode()
    # coaching runs keep the pick in the job
    assert 'name="llm"' in c.get(f"/profiles/{me}/coach/{MATCH_ID}").data.decode()
    # the overview shows the spend
    L.set_usage_file(store.data_dir / "llm_usage.json")
    L._add_usage("claude-sonnet-5-5", 100_000, 20_000, 0.4)
    page = c.get("/admin/overview").data.decode()
    assert "Claude (Anthropic API)" in page and "US$ 0.40" in page and "of 15 budget" in page
    app.extensions["nexus"]["stats"].shutdown()


def test_last_active_on_users_page(app):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    c2 = make_user(app, c, "burn")
    uid = store.user_by_name("burn").id
    c2.get("/")
    assert store.user(uid).last_seen
    page = c.get("/admin/users").data.decode()
    assert "Last active" in page and "● online now" in page
    store._exec("UPDATE users SET last_seen = ? WHERE id = ?", ("2026-01-05T10:00:00+00:00", uid))
    assert "05.01.2026" in c.get("/admin/users").data.decode()
    seen = store.user(uid).last_seen
    c2.get("/")                                      # stale: updated again
    assert store.user(uid).last_seen != seen
    first = store.user(uid).last_seen
    c2.get("/")                                      # within a minute: not written again
    assert store.user(uid).last_seen == first
    assert "last active" in c.get(f"/admin/users/{uid}").data.decode()
    assert "online now" in c.get("/admin/overview").data.decode()


def test_ask_the_coach_and_clips(app, monkeypatch, synthetic):
    import nexus.web.report_tools as rt
    from nexus.coach.ollama import Ollama
    fb = {"summary": "Fight at A", "importance": 2, "player": {"went_well": [], "mistakes": ["Peeked alone"], "better_option": "Wait"}}
    c = setup_admin(app)
    job, _ = _run_with_model(app, c, monkeypatch, lambda n: fb)
    seen = {}

    def chat_json(self, system, user, schema, **k):
        seen["user"] = user
        return {"answer": "You were 1v2 with 30 s on the spike: <play> the timer."}
    monkeypatch.setattr(Ollama, "chat_json", chat_json)
    html = c.get(f"/jobs/{job.id}/report").data.decode()
    assert "report_tools.js" in html and '"ask_url": "/api/jobs/' in html
    assert c.post(f"/api/jobs/{job.id}/ask", json={"round": 99, "question": "x"}).status_code == 400
    assert c.post(f"/api/jobs/{job.id}/ask", json={"round": 2, "question": ""}).status_code == 400
    r = c.post(f"/api/jobs/{job.id}/ask", json={"round": 2, "question": "Should I have saved?"})
    assert r.status_code == 200 and r.get_json()["pending"]
    for _ in range(300):                      # up to 30 s: a busy machine is slower than 10 s
        s = c.get(f"/api/jobs/{job.id}/ask?round=2").get_json()
        if not s["pending"]:
            break
        time.sleep(0.1)
    assert s["items"][0]["q"] == "Should I have saved?" and "<play>" in s["items"][0]["a"] and not s["error"]
    assert "round_facts" in seen["user"] and "Question: Should I have saved?" in seen["user"]
    assert c.get(f"/api/jobs/{job.id}/ask").get_json()["items"]["2"][0]["a"]          # all rounds at once
    c2 = make_user(app, c, "burn")
    assert c2.post(f"/api/jobs/{job.id}/ask", json={"round": 2, "question": "x"}).status_code == 404
    # a failing model: the error comes back once
    from nexus.coach.ollama import OllamaError
    monkeypatch.setattr(Ollama, "chat_json", lambda *a, **k: (_ for _ in ()).throw(OllamaError("model down")))
    c.post(f"/api/jobs/{job.id}/ask", json={"round": 3, "question": "Why?"})
    for _ in range(100):
        s = c.get(f"/api/jobs/{job.id}/ask?round=3").get_json()
        if s["error"]:
            break
        time.sleep(0.1)
    assert "model down" in s["error"]
    # anything else (a bug, a file error) never shows its text in the browser
    monkeypatch.setattr(Ollama, "chat_json", lambda *a, **k: (_ for _ in ()).throw(OSError("/srv/secret/path")))
    c.post(f"/api/jobs/{job.id}/ask", json={"round": 4, "question": "Why?"})
    for _ in range(100):
        s = c.get(f"/api/jobs/{job.id}/ask?round=4").get_json()
        if s["error"]:
            break
        time.sleep(0.1)
    assert s["error"] and "/srv/secret" not in s["error"]
    # clips from the VOD (ffmpeg); no VOD -> 404
    assert c.get(f"/jobs/{job.id}/clip?t=1").status_code == 404
    store = app.extensions["nexus"]["store"]
    store.update_job(job.id, vod_path=str(synthetic["vod"]))
    if rt.ffmpeg():
        r = c.get(f"/jobs/{job.id}/clip?t=0.5&len=3&dl=1")
        assert r.status_code == 200 and r.mimetype == "video/mp4" and "attachment" in r.headers["Content-Disposition"]
        assert len(r.data) > 1000
        assert '"clip_url": "/jobs/' in c.get(f"/jobs/{job.id}/report").data.decode()
    assert c.get(f"/jobs/{job.id}/clip?t=-1").status_code == 400 and c.get(f"/jobs/{job.id}/clip?t=1&len=99").status_code == 400
    assert c.post(f"/jobs/{job.id}/clip/discord?t=1").get_json()["error"].startswith("none of your teams")


def test_settings_test_buttons(app, monkeypatch):
    import requests as rq
    from nexus import henrik
    c = setup_admin(app)
    assert c.post("/settings/test/claude").get_json() == {"ok": False, "msg": "No key saved yet."}
    store = app.extensions["nexus"]["store"]
    store.set("claude_api_key", "sk-ant-secret")
    import nexus.web.models as wm
    monkeypatch.setattr(wm, "local_models", lambda url: [])
    monkeypatch.setattr(rq, "get", lambda url, **k: type("R", (), {"status_code": 401, "json": lambda self: {}})())
    j = c.post("/settings/test/claude").get_json()
    assert j["ok"] is False and "refused" in j["msg"] and "sk-ant" not in j["msg"]
    monkeypatch.setattr(henrik.HenrikClient, "_get", lambda self, path, params=None: {"data": {}})
    add_profile(c)
    j = c.post("/settings/test/henrik").get_json()
    assert j["ok"] and "adv1ce#LFT" in j["msg"]
    assert c.post("/settings/test/nope").status_code == 404
    assert make_user(app, c, "burn").post("/settings/test/henrik").status_code == 403
    assert 'data-test="henrik"' in c.get("/settings").data.decode()


def test_heat_map_on_stats(app, monkeypatch):
    import synth_history as sh
    from nexus import pipeline
    history = sh.build_history(20)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrik(history, full_depth=10))
    from nexus.maps import MapRegistry
    orig = MapRegistry.get
    monkeypatch.setattr(MapRegistry, "get", lambda self, map_id="", name="": orig(self, "00000000-test-map0-0000-000000000001"))
    c = setup_admin(app)
    me = add_profile(c)
    c.post(f"/profiles/{me}/stats/import")
    assert _wait_stats(app, f"import:{me}")["status"] == "done"
    rows = app.extensions["nexus"]["stats"].games(me).rows()
    m = next(r["map"] for r in rows if r.get("source") == "full" and r.get("deaths_at"))
    page = c.get(f"/profiles/{me}/stats?map={m}").data.decode()
    assert "heatsvg" in page and "deaths," in page and 'data-hs="defense"' in page
    app.extensions["nexus"]["stats"].shutdown()


def test_strat_history_and_restore(app, monkeypatch):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, maps=["Testmap"])
    r = c.post(f"/teams/{tid}/strats", data={"name": "B split", "map": "Testmap", "side": "attack"})
    sid = int(r.headers["Location"].rsplit("/", 1)[1])
    board = lambda n: {"data": {"steps": [{"name": "S", "items": [{"id": f"a{i}", "t": "mark", "x": i, "y": i} for i in range(n)]}]}}
    c.post(f"/api/teams/{tid}/strats/{sid}", json=board(1))
    c.post(f"/api/teams/{tid}/strats/{sid}", json=board(2))           # same person within 10 min: no new version
    assert len(store.strat_versions(sid)) == 1
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    mate.post(f"/api/teams/{tid}/strats/{sid}", json=board(3))         # someone else edits: the board before is kept
    vs = c.get(f"/api/teams/{tid}/strats/{sid}/versions").get_json()["versions"]
    assert len(vs) == 2 and vs[0]["items"] == 2 and vs[0]["by"] == "manuel"
    r = c.post(f"/api/teams/{tid}/strats/{sid}/versions/{vs[0]['id']}/restore")
    assert r.status_code == 200
    assert len(store.strat(sid)["data"]["steps"][0]["items"]) == 2
    assert store.strat_versions(sid)[0]["items"] == 3                  # what was there before the restore
    assert c.post(f"/api/teams/{tid}/strats/{sid}/versions/99999/restore").status_code == 404
    assert make_user(app, c, "outsider").get(f"/api/teams/{tid}/strats/{sid}/versions").status_code == 404
    assert 'id="sb-hist"' in c.get(f"/teams/{tid}/strats/{sid}").data.decode()


def test_home_today_nav_and_tabs(app):
    from datetime import date
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    page = c.get("/").data.decode()
    assert "Get started" in page
    pids = [add_profile(c, name=f"P{i}", tag="#T") for i in range(3)]
    uid = store.user_by_name("manuel").id
    store.update_user(uid, display_name="P1#T")
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, members=[{"pid": p, "kind": "starter", **({"user_id": uid} if i == 1 else {})} for i, p in enumerate(pids)], maps=["Bind"])
    info = store.team(tid).sync_info
    info["brief"] = {"on": False, "days": list(range(7)), "time": "20:00", "before": 60}
    store.update_team(tid, sync=info)
    page = c.get("/").data.decode()
    assert "Squad" in page and "Can you play?" in page
    assert f'data-pid="{pids[1]}"' in page and "Warm-up" in page and "No quiz yet" in page
    # menu: your own player is picked, everyone in the player picker
    assert 'class="ctxpick"' in page and "Player · you" in page and all(f'data-pid="{p}"' in page for p in pids)
    # answer from the home page
    c.post(f"/api/teams/{tid}/availability", json={"pid": pids[1], "day": date.today().isoformat(), "state": "yes"})
    today_part = c.get("/").data.decode().split("Your teams")[0]
    assert "Can you play?" not in today_part and 'class="yes on"' in today_part
    # what's new by others since the last visit
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    import json as _j
    prefs = _j.loads(store.user(uid).prefs or "{}")
    prefs["home_seen"] = 1.0
    store.update_user(uid, prefs=_j.dumps(prefs))
    mate.post(f"/teams/{tid}/notes", data={"text": "Rotate earlier on B", "about": "", "map": "Bind"})
    page = c.get("/").data.decode()
    assert "New since your last visit" in page and "Rotate earlier on B" in page
    assert "Rotate earlier on B" in c.get("/").data.decode()                       # same visit: still there
    prefs = _j.loads(store.user(uid).prefs)
    prefs["home_seen"] -= 3600                                                   # next visit, an hour later
    store.update_user(uid, prefs=_j.dumps(prefs))
    store._exec("UPDATE team_notes SET created_at = '2020-01-01T00:00:00+00:00'")   # the note came before that visit
    assert "New since your last visit" not in c.get("/").data.decode()
    # one menu in groups; the team and player it works on are the last ones opened
    page = c.get(f"/teams/{tid}").data.decode()
    assert "Match day" in page and "Roster &amp; setup" in page and page.index(">This week<") < page.index(">Comps<")
    assert f'href="/teams/{tid}/strats"' in page and f'href="/profiles/{pids[1]}/stats"' in page
    c.get(f"/profiles/{pids[2]}/stats")
    page = c.get("/").data.decode()
    assert f'href="/profiles/{pids[2]}/training"' in page and "<b>P2</b>" in page


def test_backups_and_discord_channels(app, tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_BACKUP_ROOTS", str(tmp_path))         # a backup folder outside the data folder
    import tarfile
    from nexus.discord import channel
    from nexus.web import backup
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    (store.profile_dir(pid) / "notes").mkdir(parents=True, exist_ok=True)
    (store.profile_dir(pid) / "notes" / "m.yaml").write_text("rounds: {1: hi}")
    (store.data_dir / "cache" / "big.json").write_text("x" * 1000)
    dest = tmp_path / "nas"
    dest.mkdir()
    r = c.post("/settings", data={"backup_on": "1", "backup_dir": str(dest), "backup_keep": "2",
                                  "ollama_temperature": "0.3", "ollama_num_ctx": "16384", "ollama_parallel": "4", "ollama_timeout_s": "300",
                                  "sample_fps": "2", "workers": "1", "max_upload_gb": "20", "max_jobs_per_user": "3",
                                  "minimap_roi": store.get("minimap_roi"), "killfeed_roi": store.get("killfeed_roi")})
    assert r.status_code == 302 and store.get("backup_dir") == str(dest) and store.get("backup_keep") == "2"
    c.post("/settings/backup-now")
    files = list(dest.glob("nexus-backup-*.tar.gz"))
    assert len(files) == 1
    with tarfile.open(files[0]) as tar:
        names = tar.getnames()
    assert "nexus.db" in names and any(n.endswith("notes/m.yaml") for n in names) and not any(n.startswith("cache") for n in names)
    assert backup.last(store)["ok"] and "Last backup" in c.get("/admin/overview").data.decode()
    # keep 2: older ones go
    for i in range(3):
        (dest / f"nexus-backup-2020-01-0{i + 1}_0400.tar.gz").write_text("old")
    backup.run(store)
    assert len(list(dest.glob("nexus-backup-*.tar.gz"))) == 2
    # nightly: runs once after 04:00
    from datetime import datetime
    store.set("backup_last", "")
    assert backup.tick(store, datetime(2026, 11, 2, 5, 0)) and not backup.tick(store, datetime(2026, 11, 2, 6, 0))
    assert not backup.tick(store, datetime(2026, 11, 3, 3, 0))
    # bad folder
    c.post("/settings", data={"backup_keep": "14", "backup_dir": "relative/path", "minimap_roi": store.get("minimap_roi"), "killfeed_roi": store.get("killfeed_roi")})
    assert store.get("backup_dir") == str(dest)
    # Discord: each kind of post finds its channel
    info = {"prep_url": "P", "focus_url": "F", "review_url": "R"}
    assert channel(info, "review") == "R" and channel(info, "clip") == "P" and channel(info, "focus") == "F" and channel({}, "prep") == ""


def test_share_report_pwa_push_and_match_screen(app, monkeypatch):
    from nexus.web import push
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    # a finished report
    store.create_job("sh1", pid, MATCH_ID, "both")
    rep = store.data_dir / "reports" / "sh1"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "r.html").write_text("<html><body><h1>Ascent 13-9</h1><video src=\"/jobs/sh1/vod\"></video></body></html>")
    store.update_job("sh1", status="done", html_path=str(rep / "r.html"), map="Ascent", score="13-9")
    assert "Make a share link" in c.get("/jobs/sh1").data.decode()
    c.post("/jobs/sh1/share")
    tok = store.job("sh1").share_token
    assert len(tok) >= 20 and f"/share/{tok}" in c.get("/jobs/sh1").data.decode()
    anon = app.test_client()
    r = anon.get(f"/share/{tok}")
    page = r.data.decode()
    assert r.status_code == 200 and "Ascent 13-9" in page and "read only" in page and f"/share/{tok}/vod" in page
    assert "/jobs/sh1/vod" not in page and "VALCOACH_FB" not in page
    assert anon.get("/share/" + "x" * 30).status_code == 404 and anon.get("/jobs/sh1/report").status_code == 302
    other = make_user(app, c, "mate")
    assert other.post("/jobs/sh1/share").status_code == 404                   # only the owner shares
    c.post("/jobs/sh1/share", data={"off": "1"})
    assert anon.get(f"/share/{tok}").status_code == 404
    # installable app
    m = anon.get("/manifest.webmanifest").get_json()
    assert m["display"] == "standalone" and any(i["purpose"] == "maskable" for i in m["icons"])
    sw = anon.get("/sw.js")
    assert sw.status_code == 200 and "showNotification" in sw.data.decode() and anon.get("/offline").status_code == 200
    assert 'rel="manifest"' in c.get("/").data.decode()
    # push: subscribe, test, notification settings, report-ready message
    if push.available():
        assert c.get("/api/push/key").get_json()["key"]
        assert c.post("/api/push/subscribe", json={"endpoint": "http://evil", "keys": {}}).status_code == 400
        assert c.post("/api/push/subscribe", json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}).get_json()["devices"] == 1
        sent = []
        monkeypatch.setattr(push, "_send_one", lambda store_, sub, payload, priv, claim: sent.append(payload) or True)
        assert c.post("/api/push/test").get_json()["devices"] == 1 and sent[-1]["title"] == "Nexus"
        app.extensions["nexus"]["runner"].on_finish("sh1", "done")
        import time as _t
        _t.sleep(0.3)
        assert sent[-1]["title"] == "Report ready: Ascent 13-9" and sent[-1]["url"] == "/jobs/sh1/report"
        c.post("/account", data={"notify": "1"})                               # everything off
        n = len(sent)
        app.extensions["nexus"]["runner"].on_finish("sh1", "done")
        _t.sleep(0.3)
        assert len(sent) == n
        assert "pywebpush" not in c.get("/account").data.decode()
        c.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/abc"})
        assert store.push_subs() == []
    # match screen
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}], maps=["Bind", "Ascent"])
    store.create_strat(tid, 1, "Ascent", "defense", "Stack B")
    page = c.get(f"/teams/{tid}/match?map=Ascent&side=defense").data.decode()
    assert "Match screen" in page and "Stack B" in page and 'data-side="defense" class="on"' in page
    assert "embed=1" in page and c.get(f"/teams/{tid}/match?map=Nowhere").status_code == 404
    assert 'class="vc-side"' not in c.get(f"/teams/{tid}/strats/1?play=1&embed=1").data.decode()
    assert other.get(f"/teams/{tid}/match").status_code == 404


def test_habits_page_and_practice_plan(app, monkeypatch):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    assert "No games yet" in c.get(f"/profiles/{pid}/habits").data.decode()
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}], maps=["Lotus"])
    store.create_strat(tid, 1, "Lotus", "attack", "A split")
    page = c.get(f"/teams/{tid}/practice").data.decode()
    assert "Practice plan" in page and "Warm-up" in page and "A split" in page
    import re as _re
    day = _re.search(r'data-day="([\d-]+)"', page).group(1)
    item = _re.search(r'class="pi[^"]*" data-id="(\w+)"', page).group(1)
    r = c.post(f"/api/teams/{tid}/practice", json={"action": "tick", "day": day, "id": item, "done": True}).get_json()
    assert r["done"] == 1
    assert c.post(f"/api/teams/{tid}/practice", json={"action": "add", "day": day, "title": "Pistol rounds", "minutes": 20}).get_json()["ok"]
    assert "Pistol rounds" in c.get(f"/teams/{tid}/practice").data.decode()
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert mate.post(f"/api/teams/{tid}/practice", json={"action": "remove", "day": day, "id": item}).status_code == 403
    assert mate.post(f"/teams/{tid}/practice", data={"days": ["0"], "time": "18:00", "minutes": "60"}).status_code in (403, 404)
    c.post(f"/teams/{tid}/practice", data={"days": ["0", "2"], "time": "18:30", "minutes": "60"})
    page = c.get(f"/teams/{tid}/practice").data.decode()
    assert "18:30" in page and "Mon" in page


def test_review_evening(app):
    import json as _json
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    raw = _json.loads((store.data_dir / "cache" / "matches" / f"{MATCH_ID}.json").read_text())
    players = raw.get("data", raw)["players"]
    side = players[0]["team_id"]
    ours = [p for p in players if p["team_id"] == side][:2]
    pids = [add_profile(c, name=p["name"], tag="#" + p["tag"]) for p in ours]
    uid = store.user_by_name("manuel").id
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "puuid": p["puuid"], **({"user_id": uid} if i == 0 else {})}
                                    for i, (pid, p) in enumerate(zip(pids, ours))], maps=["Testmap"])
    assert "Pick a match" in c.get(f"/teams/{tid}/review-evening").data.decode()
    assert c.post(f"/teams/{tid}/review-evening", data={"match_id": "../etc"}).status_code == 400
    r = c.post(f"/teams/{tid}/review-evening", data={"match_id": MATCH_ID})
    assert r.status_code == 302
    sid = r.headers["Location"].rstrip("/").split("/")[-1]
    page = c.get(f"/teams/{tid}/review-evening/{sid}").data.decode()
    assert "Your mark" in page and "ev-boot" in page and ours[0]["name"] in page
    boot = _json.loads(page.split('id="ev-boot">')[1].split("</script>")[0])
    assert boot["me"] == ours[0]["name"] and boot["host"] and len(boot["rounds"]) == 6
    api = f"/api/teams/{tid}/review-evening/{sid}"
    st = c.post(api, json={"action": "mark", "round": 1, "player": ours[0]["name"], "mark": "fault", "note": "too early"}).get_json()
    assert st["marks"]["1"][ours[0]["name"]]["m"] == "fault"
    assert c.post(api, json={"action": "mark", "round": 99, "player": ours[0]["name"], "mark": "good"}).status_code == 400
    assert c.post(api, json={"action": "mark", "round": 1, "player": "someone else", "mark": "good"}).status_code == 400
    assert c.post(api, json={"action": "mark", "round": 1, "player": ours[1]["name"], "mark": "lol"}).status_code == 400
    c.post(api, json={"action": "mark", "round": 2, "player": ours[1]["name"], "mark": "talk", "note": "<b>why</b>"})
    assert c.post(api, json={"action": "goto", "round": 3}).get_json()["current"] == 3
    summary = c.get(f"/teams/{tid}/review-evening/{sid}/summary").data.decode()
    assert "too early" in summary and "<b>why</b>" not in summary and "&lt;b&gt;why" in summary
    # a teammate can mark but not move everyone or delete
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert mate.post(api, json={"action": "goto", "round": 2}).status_code == 403
    assert mate.post(api, json={"action": "mark", "round": 3, "player": ours[1]["name"], "mark": "good"}).status_code == 200
    assert mate.post(f"/teams/{tid}/review-evening/{sid}/delete").status_code == 403
    assert mate.get(f"/api/teams/{tid}/review-evening/{sid}").get_json()["current"] == 3
    # strangers see nothing; made-up ids are 404
    stranger = make_user(app, c, "stranger")
    assert stranger.get(f"/teams/{tid}/review-evening/{sid}").status_code == 404
    assert c.get(f"/teams/{tid}/review-evening/zzz").status_code == 404
    rp = c.get(f"/teams/{tid}/review-evening/{sid}/replay.json").get_json()
    assert "rounds" in rp
    assert c.get("/replay.js").status_code == 200
    assert c.post(api, json={"action": "finish"}).get_json()["finished"]
    r = c.post(f"/teams/{tid}/review-evening/{sid}/plan")
    assert r.status_code == 302
    if r.headers["Location"].endswith("/practice"):        # themes found: they're on the practice plan now
        assert "From the review evening" in c.get(f"/teams/{tid}/practice").data.decode()
    else:
        assert "#summary" in r.headers["Location"]
    assert c.post(f"/teams/{tid}/review-evening/{sid}/delete").status_code == 302
    assert c.get(f"/teams/{tid}/review-evening/{sid}").status_code == 404


def test_small_fixes_37(app):
    import json as _json
    from nexus.web.overview import loaded_model
    c = setup_admin(app)
    # Ollama memory: all on the GPU, split, CPU only
    assert loaded_model({"name": "m", "size": 4 * 2**30, "size_vram": 4 * 2**30})["where"] == "gpu"
    sp = loaded_model({"name": "m", "size": 10 * 2**30, "size_vram": 6 * 2**30})
    assert sp["where"] == "split" and round(sp["share"], 1) == 0.6
    assert loaded_model({"name": "m", "size": 10 * 2**30, "size_vram": 0})["where"] == "cpu"
    # What's new: sub-bullets are their own list
    page = c.get("/changelog").data.decode()
    assert "<ul><li><b>Progress over time:</b>" in page
    # error pages don't mark a menu entry as the current page
    assert 'aria-current="page"' not in c.get("/teams/999").data.decode()
    # a damaged draft doesn't break the drafts page
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}], maps=["Lotus"])
    did = store.create_draft(tid, 1, "Lotus", "broken", {})
    store._exec("UPDATE drafts SET data = ? WHERE id = ?", (_json.dumps({"slots": "x", "status": "weird"}), did))
    page = c.get(f"/teams/{tid}/drafts?map=Lotus&d={did}").data.decode()
    assert "broken" in page
    boot = _json.loads(page.split('id="draft-boot">')[1].split("</script>")[0])
    assert len(boot["draft"]["data"]["slots"]) == 5 and boot["draft"]["data"]["status"] == "idea"


def test_aim_routines_and_warmup(app, monkeypatch):
    from nexus.stats import kovaaks as _kv
    monkeypatch.setattr(_kv, "WEB", True)        # 4.26: KovaaK's is off on the pages; these tests switch it on
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    uid = store.user_by_name("manuel").id
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "user_id": uid}], maps=["Lotus"])
    page = c.get(f"/profiles/{pid}/aim").data.decode()
    assert "Your warm-up before matches" in page and "Range warm-up" in page
    # links must be http(s), codes plain
    c.post(f"/profiles/{pid}/aim", data={"action": "add", "name": "Evil", "kind": "link", "url": "javascript:alert(1)"})
    c.post(f"/profiles/{pid}/aim", data={"action": "add", "name": "Bad code", "kind": "kovaaks", "code": "<script>"})
    page = c.get(f"/profiles/{pid}/aim").data.decode()
    assert "Evil" not in page and "Bad code" not in page
    c.post(f"/profiles/{pid}/aim", data={"action": "add", "name": "Flicks AL", "kind": "aimlabs", "url": "https://go.aimlabs.com/x",
                                         "focus": ["flicks", "warmup"], "minutes": "12", "scope": f"team:{tid}"})
    c.post(f"/profiles/{pid}/aim", data={"action": "add", "name": "Mine KK", "kind": "kovaaks", "code": "KovaaKsWarmup-1", "focus": ["tracking"]})
    page = c.get(f"/profiles/{pid}/aim").data.decode()
    assert "Flicks AL" in page and "Mine KK" in page and 'rel="noopener noreferrer nofollow"' in page
    team_r = json.loads((store.data_dir / "teams" / str(tid) / "aim.json").read_text())["routines"][0]
    # the owner makes it the team's warm-up: practice plan, match screen
    c.post(f"/profiles/{pid}/aim", data={"action": "team_warmup", "tid": str(tid), "rid": team_r["id"]})
    c.post(f"/teams/{tid}/practice", data={"action": "remake"})
    assert "Warm-up: Flicks AL" in c.get(f"/teams/{tid}/practice").data.decode()
    assert "Flicks AL" in c.get(f"/teams/{tid}/match").data.decode()
    # done with a score, shown in the log; a bad score is refused
    c.post(f"/profiles/{pid}/aim", data={"action": "done", "rid": team_r["id"], "score": "87,5"})
    assert c.post(f"/profiles/{pid}/aim", data={"action": "done", "rid": team_r["id"], "score": "lots"}).status_code == 302
    page = c.get(f"/profiles/{pid}/aim").data.decode()
    assert "score 87.5" in page and "Done today" in page
    assert c.post(f"/profiles/{pid}/aim", data={"action": "done", "rid": "nope"}).status_code == 400
    # redirect back only to this site
    r = c.post(f"/profiles/{pid}/aim", data={"action": "warmup", "rid": "b-hsdm", "next": "//evil.example/x"})
    assert r.headers["Location"].endswith(f"/profiles/{pid}/aim")
    # a teammate sees the team routine but can't remove it or set the team warm-up
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert "Flicks AL" in mate.get(f"/profiles/{pid}/aim").data.decode()
    assert "Mine KK" not in mate.get(f"/profiles/{pid}/aim").data.decode()
    assert mate.post(f"/profiles/{pid}/aim", data={"action": "remove", "rid": team_r["id"], "scope": f"team:{tid}"}).status_code == 403
    assert mate.post(f"/profiles/{pid}/aim", data={"action": "team_warmup", "tid": str(tid), "rid": "b-range"}).status_code == 403
    assert mate.post(f"/profiles/{pid}/aim", data={"action": "done", "rid": "b-range"}).status_code == 403
    stranger = make_user(app, c, "stranger")
    assert stranger.get(f"/profiles/{pid}/aim").status_code == 404
    # 30 minutes before the match: one warm-up push run per team and day
    ext = app.extensions["nexus"]
    tick = ext["aim"]["tick"]
    ext["minutes_to_match"] = lambda t: 30
    assert tick() == [tid] and tick() == []
    c.post(f"/profiles/{pid}/aim", data={"action": "remove", "rid": team_r["id"], "scope": f"team:{tid}"})
    assert "<h3>Flicks AL" not in c.get(f"/profiles/{pid}/aim").data.decode()     # the log keeps its name


def test_german_interface_and_language_switch(app):
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    page = c.get("/account").data.decode()
    assert "Log out" in page and 'lang="en"' in page and "i18n.js" not in page
    c.post("/account", data={"look": "1", "style": "classic", "nav": "side", "lang": "de"})
    page = c.get("/account").data.decode()
    assert 'lang="de"' in page and "Abmelden" in page and "Log out" not in page and "i18n.js" in page
    c.post("/account", data={"look": "1", "style": "neon", "nav": "top"})          # keeps the language
    assert "Abmelden" in c.get("/account").data.decode()
    assert c.get("/i18n/de.json").get_json()["Log out"] == "Abmelden"
    assert c.get("/i18n/en.json").status_code == 404
    # the coach's text and people's notes are not touched
    pid = add_profile(c)
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}], maps=["Lotus"])
    store.add_team_note(tid, store.user_by_name("manuel").id, "Fall back after your first kill on Ascent")
    page = c.get(f"/teams/{tid}/notes").data.decode()
    assert "Notizen" in page and "Fall back after your first kill on Ascent" in page
    # login page: the browser's language, or the switch on the page
    anon = app.test_client()
    assert "Anmelden" in anon.get("/login", headers={"Accept-Language": "de-CH,de;q=0.9"}).data.decode()
    assert "Log in" in anon.get("/login", headers={"Accept-Language": "en-US"}).data.decode()
    r = anon.get("/lang/de?next=/login")
    assert r.status_code == 302 and "vc-lang=de" in r.headers.get("Set-Cookie", "")
    assert "Anmelden" in anon.get("/login").data.decode()
    assert anon.get("/lang/de?next=//evil.example").headers["Location"].endswith("/login")
    assert anon.get("/lang/xx").status_code == 404
    # Discord posts follow the team's language
    from nexus import discord
    info = {"prep_url": "https://discord.com/api/webhooks/1/abc", "lang": "de"}
    store.update_team(tid, discord=info)
    content, embeds = discord._translate(discord._lang(info["prep_url"]), "Posted to Discord", [{"title": "Rounds that decided it"}])
    assert content == "Auf Discord gepostet" and embeds[0]["title"] == "Entscheidende Runden"


def test_kovaaks_playlists_scores_and_scenarios(app, monkeypatch):
    from nexus.stats import kovaaks as _kv
    monkeypatch.setattr(_kv, "WEB", True)
    import io as _io
    import zipfile as _zip
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    assert "KovaaK's playlists from the coach" not in c.get(f"/profiles/{pid}/aim").data.decode()   # 4.25: its own page
    assert "KovaaK's playlists from the coach" in page and "Download for KovaaK's" in page
    r = c.get(f"/profiles/{pid}/aim/kovaaks/warmup.json")
    assert r.status_code == 200 and "nexus_warmup_" in r.headers["Content-Disposition"]
    data = r.get_json()
    assert data["scenarioList"] and all(set(x) == {"scenario_name", "play_Count"} for x in data["scenarioList"])
    assert c.get(f"/profiles/{pid}/aim/kovaaks/other.json").status_code == 404
    tr = c.get(f"/profiles/{pid}/aim/kovaaks/training.json").get_json()   # training: other scenarios than the warm-up
    assert not {x["scenario_name"] for x in data["scenarioList"]} & {x["scenario_name"] for x in tr["scenarioList"]}
    # import a playlist: its unknown scenario joins your list, the playlist becomes a routine with its share code
    pl = json.dumps({"playlistName": "Friend's list", "shareCode": "KovaaKsFriendList", "scenarioList": [
        {"scenario_name": "Tile Frenzy", "play_Count": 1}, {"scenario_name": "Totally New Scenario", "play_Count": 2}]})
    c.post(f"/profiles/{pid}/aim", data={"action": "k_import_playlist", "as_routine": "1", "scope": "me",
                                         "files": (_io.BytesIO(pl.encode()), "friend.json")}, content_type="multipart/form-data")
    page = c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    assert "Totally New Scenario" in page                                  # the coach's scenario list (KovaaK's page)
    assert "KovaaKsFriendList" in c.get(f"/profiles/{pid}/aim").data.decode()    # the routine (Aim page library)
    # add one by hand, then remove it
    c.post(f"/profiles/{pid}/aim", data={"action": "k_add_scenario", "name": "Hand Added", "level": "3", "scope": "me"})
    assert "Hand Added" in c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    c.post(f"/profiles/{pid}/aim", data={"action": "k_remove_scenario", "name": "Hand Added", "scope": "me"})
    c.get(f"/profiles/{pid}/aim/kovaaks")                                  # the "Removed" message
    assert "Hand Added" not in c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    # scores from a zipped stats folder (twice: nothing is counted double)
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w") as z:
        for i in range(6):
            z.writestr(f"Found In Stats - Challenge - 2026.10.1{i}-18.00.00 Stats.csv",
                       f"Weapon,Shots,Hits\npistol,100,70\n\nKills:,70\nScore:,{700 + i}.0\nScenario:,Found In Stats\n")
    for _ in range(2):
        c.post(f"/profiles/{pid}/aim", data={"action": "k_import_stats", "files": (_io.BytesIO(buf.getvalue()), "stats.zip")},
               content_type="multipart/form-data")
    aim = json.loads((store.data_dir / "profiles" / str(pid) / "stats" / "aim.json").read_text())
    assert len(aim["kovaaks"]) == 6
    page = c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    assert "Found In Stats" in page and "6 runs" in page
    # someone who plays KovaaK's gets the coach's KovaaK's warm-up by default
    assert "KovaaK&#39;s warm-up from the coach" in c.get(f"/profiles/{pid}/aim").data.decode().split('id="warmup"')[1][:600]
    # teammates see the page but can't import into this player's scores
    mate = make_user(app, c, "mate")
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}])
    store.add_team_access(tid, store.user_by_name("mate").id)
    assert mate.post(f"/profiles/{pid}/aim", data={"action": "k_import_stats", "files": (_io.BytesIO(b"x"), "a.csv")},
                     content_type="multipart/form-data").status_code == 403
    c.post(f"/profiles/{pid}/aim", data={"action": "k_clear_stats"})
    assert "kovaaks" not in json.loads((store.data_dir / "profiles" / str(pid) / "stats" / "aim.json").read_text())


def test_ask_the_coach_chat_with_web_search(app, monkeypatch):
    from nexus.coach import websearch as ws
    from nexus.coach.ollama import Ollama
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/ask").data.decode()
    assert "Ask the coach" in page and "Set up web search" in page            # admin: link to Settings
    assert c.post(f"/api/profiles/{pid}/ask", json={"question": "  "}).status_code == 400
    # web search via SearXNG (faked): the model first writes queries, then answers with the sources it used
    calls = []

    def chat_json(self, system, user, schema, **k):
        calls.append(user)
        if "queries" in schema["properties"]:
            return {"queries": ["Jett dash cost patch"]}
        assert "[1] Jett changes" in user and "Question: What changed for Jett?" in user
        return {"answer": "Her dash got **shorter**.\n\nPractise <entries> again.", "sources": [1, 7]}
    monkeypatch.setattr(Ollama, "check", lambda self: None)
    monkeypatch.setattr(Ollama, "chat_json", chat_json)
    searched = []
    monkeypatch.setattr(ws, "searcher", lambda store: (lambda q, n=6: searched.append(q) or
                                                        [{"title": "Jett changes", "url": "https://example.org/jett", "snippet": "dash"}]))
    monkeypatch.setattr(ws, "page_text", lambda url, limit=4000, session=None: "Patch 12: Jett's dash is shorter.")
    monkeypatch.setattr(ws, "provider", lambda store: "searxng")
    r = c.post(f"/api/profiles/{pid}/ask", json={"question": "What changed for Jett?"})
    assert r.status_code == 200
    for _ in range(300):
        s = c.get(f"/api/profiles/{pid}/ask").get_json()
        if not s["pending"]:
            break
        time.sleep(0.1)
    assert not s["error"] and len(s["items"]) == 1, s
    it = s["items"][0]
    assert it["sources"] == [{"title": "Jett changes", "url": "https://example.org/jett"}]     # made-up [7] dropped
    assert it["searched"] == ["Jett dash cost patch"] and searched == ["Jett dash cost patch"]
    page = c.get(f"/profiles/{pid}/ask").data.decode()
    assert "<b>shorter</b>" in page and "&lt;entries&gt;" in page and 'href="https://example.org/jett"' in page
    # someone else's player: 404; a new conversation clears it
    c2 = make_user(app, c, "burn")
    assert c2.get(f"/profiles/{pid}/ask").status_code == 404
    assert c2.post(f"/api/profiles/{pid}/ask", json={"question": "x"}).status_code == 404
    c.post(f"/profiles/{pid}/ask/clear")
    assert c.get(f"/api/profiles/{pid}/ask").get_json()["items"] == []


def test_settings_web_search_width_and_backup_message(app, tmp_path):
    import errno
    from urllib.parse import urlparse
    from nexus.web import backup
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    c.post("/settings", data={"search_provider": "searxng", "searxng_url": ""})
    assert store.get("search_provider") == ""                                  # no URL: stays off
    c.post("/settings", data={"search_provider": "duckduckgo", "search_backup": "searxng", "searxng_url": ""})
    assert store.get("search_provider") == "duckduckgo" and store.get("search_backup") == ""   # backup needs its URL
    c.post("/settings", data={"search_provider": "searxng", "searxng_url": "http://10.0.0.5:8080/"})
    assert store.get("search_provider") == "searxng" and store.get("searxng_url") == "http://10.0.0.5:8080"
    c.post("/settings", data={"search_provider": "claude", "searxng_url": "http://10.0.0.5:8080"})
    assert store.get("search_provider") == "searxng"                           # Claude needs a key
    c.post("/settings", data={"search_provider": "duckduckgo", "search_backup": "searxng", "searxng_url": "http://10.0.0.5:8080"})
    assert store.get("search_provider") == "duckduckgo" and store.get("search_backup") == "searxng"
    # Test: a line per search, each with its own result
    from nexus.coach import websearch as ws

    def fake_one(st, which):
        if which == "duckduckgo":
            def blocked(q, n=6):
                raise ws.SearchError("duckduckgo", "blocked", "HTTP 202")
            return blocked
        return lambda q, n=6: [{"title": "x", "url": "https://x.org", "snippet": ""}]
    orig = ws._one
    ws._one = fake_one
    try:
        j = c.post("/settings/test/search").get_json()
    finally:
        ws._one = orig
    assert j["ok"] and [(x["role"], x["ok"]) for x in j["parts"]] == [("main", False), ("backup", True)]
    assert "refused" in j["parts"][0]["msg"] and "SearXNG: works" in j["parts"][1]["msg"]
    assert 'id="search"' in c.get("/settings").data.decode()
    # page width per user: a class on <body>
    c.post("/account", data={"look": "1", "style": "terminal", "width": "narrow"})
    assert "w-narrow" in c.get("/account").data.decode()
    c.post("/account", data={"look": "1", "style": "classic", "width": "bogus"})
    assert "w-narrow" in c.get("/account").data.decode()                        # unknown value keeps the old one
    c.post("/account", data={"look": "1", "style": "classic", "width": "auto"})
    assert ' w-' not in c.get("/account").data.decode().split("<body", 1)[1].split(">", 1)[0]
    # a read-only backup folder (the systemd sandbox) is explained, not shown as a bare Errno
    msg = backup.explain(OSError(errno.EROFS, "Read-only file system"), "/srv/backups")
    assert "ReadWritePaths=/srv/backups" in msg and "Errno" not in msg
    data = store.data_dir
    (data / "bk").mkdir()
    assert backup.check_folder(data / "bk", data) == "" and "not found" in backup.check_folder(data / "nope", data)
    for bad in ("/etc", "/", "/mnt/../etc", "relative/path", "/usr/local/bk"):
        assert backup.check_folder(bad, data), bad
    assert backup.clean_folder("/mnt/nas/Nexus", data)[0] is not None
    c.post("/settings", data={"backup_keep": "14", "backup_dir": "/etc"})
    assert store.get("backup_dir") != "/etc"
    # redirects after a form or a language switch stay on this site, whatever browsers make of the target
    for evil in ("//evil.com", "/\\evil.com", "/\t/evil.com", "https://evil.com", "/%0a"):
        r = c.get("/lang/en?next=" + evil.replace("\t", "%09"))
        loc = r.headers["Location"]
        assert loc.startswith("/") and not loc.startswith("//") and not urlparse(loc).netloc, (evil, loc)
    assert c.get("/lang/en?next=/account").headers["Location"].endswith("/account")


def test_kovaaks_community_playlists(app, monkeypatch):
    from nexus.stats import kovaaks as _kv
    monkeypatch.setattr(_kv, "WEB", True)
    from nexus.coach import websearch as ws
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    assert "Playlists from the community" in page and "KovaaKsTeleportingJebaitedBuystation" in page
    assert "Search the web" not in page                                           # no web search set up
    c.post(f"/profiles/{pid}/aim", data={"action": "k_add_shared", "code": "KovaaKsAcingShamrockLowground"})
    page = c.get(f"/profiles/{pid}/aim/kovaaks").data.decode()
    assert "Voltaic Iron" in page and "in your routines" in page
    r = c.post(f"/profiles/{pid}/aim", data={"action": "k_add_shared", "code": "KovaaKsAcingShamrockLowground"}, follow_redirects=True)
    assert "already in" in r.data.decode()
    c.post(f"/profiles/{pid}/aim", data={"action": "k_add_shared", "code": "<script>"})
    assert c.post(f"/api/profiles/{pid}/aim/find-playlists").status_code == 400
    # found online: names come from the text in front of the code
    monkeypatch.setattr(ws, "searcher", lambda store: (lambda q, n=6: [{"title": "Codes", "url": "https://example.org/c", "snippet": ""}]))
    monkeypatch.setattr(ws, "page_text", lambda url, limit=4000, session=None:
                        "Routines\nPeek drills - KovaaKsTestingNewPeekCode\nVoltaic Iron - KovaaKsAcingShamrockLowground")
    assert c.post(f"/api/profiles/{pid}/aim/find-playlists").get_json()["pending"]     # runs in the background
    for _ in range(100):
        j = c.get(f"/api/profiles/{pid}/aim/find-playlists").get_json()
        if not j["pending"]:
            break
        time.sleep(0.1)
    assert [x["code"] for x in j["found"]] == ["KovaaKsTestingNewPeekCode"] and j["found"][0]["name"] == "Peek drills"
    c.post(f"/profiles/{pid}/aim", data={"action": "k_add_shared", "code": "KovaaKsTestingNewPeekCode", "name": "Peek drills",
                                         "url": "https://example.org/c"})
    assert "Peek drills" in c.get(f"/profiles/{pid}/aim").data.decode()


def test_companion_app_api(app, monkeypatch):
    from nexus import pipeline
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    anon = app.test_client()
    assert anon.get("/api/companion/me").status_code == 401
    assert anon.post("/api/companion/login", json={"username": "manuel", "password": "nope"}).status_code == 401
    r = anon.post("/api/companion/login", json={"username": "manuel", "password": ADMIN_PW, "device": "Gaming PC"})
    assert r.status_code == 200, r.data
    token = r.get_json()["token"]
    H = {"Authorization": f"Bearer {token}"}
    me = anon.get("/api/companion/me", headers=H).get_json()
    assert me["players"][0]["id"] == pid and me["chunk"] > 0
    assert anon.get("/account", headers=H).status_code == 302                  # the key only opens the app's API
    assert "Gaming PC" in c.get("/account").data.decode()
    # playlists for KovaaK's
    pl = anon.get(f"/api/companion/players/{pid}/playlists", headers=H).get_json()["playlists"]
    assert {x["kind"] for x in pl} == {"warmup", "training"} and pl[0]["file_name"].endswith(".json")
    # scores from the stats folder
    csv_text = ("Kill #,Timestamp,Bot,Weapon,TTK,Shots,Hits,Accuracy,Damage Done,Damage Possible,Efficiency,Cheated\n"
                "\nScore:,812.5\nScenario:,1wall6targets TE\nChallenge Start:,20:01:02.000\n")
    r = anon.post(f"/api/companion/players/{pid}/kovaaks", headers=H, data={
        "files": [(io.BytesIO(csv_text.encode()), "1wall6targets TE - Challenge - 2026.11.06-20.01.40 Stats.csv")]},
        content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["new"] == 1, r.data
    # matches with start and length, then a clip for one of them
    monkeypatch.setattr(pipeline, "history", lambda cfg, size=10, **k: [
        {"match_id": "abc-123", "started_at": "2026-11-06T19:10:00+00:00", "length_s": 2400, "map": "Ascent",
         "queue": "competitive", "score": "13-9", "agent": "Jett", "coachable": True}])
    ms = anon.get(f"/api/companion/players/{pid}/matches", headers=H).get_json()["matches"]
    assert ms[0]["start"] == 1793992200.0 and ms[0]["length_s"] == 2400 and not ms[0]["has_clip"]
    body = b"\x00" * 1000
    up = anon.post("/api/companion/uploads", headers=H, json={"name": "abc.mp4", "size": len(body)}).get_json()
    assert anon.put(f"/api/companion/uploads/{up['id']}?offset=0", headers=H, data=body).get_json()["received"] == 1000
    r = anon.post(f"/api/companion/players/{pid}/clips", headers=H,
                  json={"match_id": "abc-123", "upload_id": up["id"], "source": "MedalTVValorant20261106200223161.mp4"})
    assert r.status_code == 200, r.data
    assert anon.get(f"/api/companion/players/{pid}/matches", headers=H).get_json()["matches"][0]["has_clip"]
    from nexus.web.companion import clip_for
    assert clip_for(store, 1, "abc-123")["size"] == 1000
    # someone else's player: not found; logging out the device in Account kills the key
    other = store.create_user("burn2", "correct-horse-2")
    oth = store.create_profile(other, "Other", "TAG")
    assert anon.get(f"/api/companion/players/{oth}/playlists", headers=H).status_code == 404
    dev = store.devices(1)[0]["id"]
    c.post(f"/account/devices/{dev}/delete")
    assert anon.get("/api/companion/me", headers=H).status_code == 401
    # changing the password logs every device out
    t2 = anon.post("/api/companion/login", json={"username": "manuel", "password": ADMIN_PW}).get_json()["token"]
    store.set_password(1, "another-pass-99")
    assert anon.get("/api/companion/me", headers={"Authorization": f"Bearer {t2}"}).status_code == 401


def test_nexus_app_pairs_with_the_session_and_has_its_page(app):
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    # "This PC" is in the menu but hidden: base.html shows it only inside the app (window.pywebview)
    home = c.get("/").data.decode()
    assert 'data-app-only hidden' in home and "/this-pc" in home and "/account/devices/pair" in home
    page = c.get("/this-pc").data.decode()
    assert "Only in the Nexus app" in page and f'<option value="{pid}"' in page and "releases/latest" in page
    assert app.test_client().get("/this-pc").status_code == 302                       # logged out: login first
    # the app's key for this PC comes from the website session (same-site POST)
    r = c.post("/account/devices/pair", json={"device": "Gaming PC"}, headers={"Origin": "http://localhost"})
    assert r.status_code == 200, r.data
    d = r.get_json()
    assert d["user"] == "manuel" and d["token"].startswith("vc_")
    assert app.test_client().get("/api/companion/me", headers={"Authorization": f"Bearer {d['token']}"}).status_code == 200
    assert store.devices(1)[0]["name"] == "Gaming PC"
    # from another website: refused (CSRF); without a session: no key
    assert c.post("/account/devices/pair", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert app.test_client().post("/account/devices/pair", json={}).status_code in (302, 401)
    assert len(store.devices(1)) == 1


def test_old_database_name_and_backups_are_taken_over(tmp_path, monkeypatch):
    from nexus.web import backup
    from nexus.web.store import Store
    data = tmp_path / "data"
    Store(data).set("henrik_api_key", "HDEV-old")
    (data / "nexus.db").rename(data / "valcoach.db")               # what 4.4 left behind
    store = Store(data)
    assert (data / "nexus.db").exists() and not (data / "valcoach.db").exists()
    assert store.get("henrik_api_key") == "HDEV-old"
    # backups made before the rename still count (list, newest first, and retention)
    dest = data / "backups"
    dest.mkdir()
    (dest / "valcoach-backup-2026-10-01_0400.tar.gz").write_text("old")
    (dest / "nexus-backup-2026-09-01_0400.tar.gz").write_text("older")
    names = [b["name"] for b in backup.list_backups(store)]
    assert names == ["valcoach-backup-2026-10-01_0400.tar.gz", "nexus-backup-2026-09-01_0400.tar.gz"]
    store.set("backup_keep", "1")
    backup.make_backup(store)
    left = sorted(p.name for p in dest.iterdir())
    assert len(left) == 1 and left[0].startswith("nexus-backup-")
    # the environment variables keep working under their old names
    monkeypatch.delenv("NEXUS_BACKUP_ROOTS", raising=False)
    monkeypatch.setenv("VALCOACH_BACKUP_ROOTS", "/srv/old-name")
    assert "/srv/old-name" in backup.allowed_roots(data)


def test_aim_trainer_and_mouse_check(app):
    import json as _json
    from nexus.stats import trainer as tr
    c = setup_admin(app)
    pid = add_profile(c)
    H = {"Origin": "http://localhost"}
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert "Grid flicks" in page and "trainer.js" in page and "Start warm-up" in page and "/trainer/runs" in page
    gear = c.get(f"/profiles/{pid}/gear").data.decode()
    assert "Polling rate" in gear and "gearcheck.js" in gear
    assert f"/profiles/{pid}/trainer" in c.get("/").data.decode()             # in the menu (Practice)
    # a run: checked and stored; nonsense is refused
    r = c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "grid", "score": 812, "seconds": 60, "hits": 40,
                                                       "shots": 48, "ms": 512}, headers=H)
    assert r.status_code == 200 and r.get_json()["is_best"] and r.get_json()["best_before"] is None
    for bad in ({"scenario": "nope", "score": 1, "seconds": 30}, {"scenario": "grid", "score": 5, "seconds": 30, "hits": 9, "shots": 3},
                {"scenario": "track", "score": 5, "seconds": 30, "on_target": 1.5}, {"scenario": "grid", "score": float("1e9"), "seconds": 30}):
        assert c.post(f"/profiles/{pid}/trainer/runs", json=bad, headers=H).status_code == 400
    assert c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "grid", "score": 1}, headers={"Origin": "https://evil.example"}).status_code == 403
    # the last round of a warm-up ticks it off on the Aim page
    r = c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "micro", "score": 300, "seconds": 30, "hits": 12, "shots": 14,
                                                       "plan_done": "warmup", "plan_score": 1500}, headers=H)
    assert r.status_code == 200
    sr = app.extensions["nexus"]["stats"]
    aim = _json.loads((sr.games(pid).path.parent / "aim.json").read_text())
    assert aim["log"][-1]["routine"] == "t-warmup" and aim["log"][-1]["score"] == 1500
    aimpage = c.get(f"/profiles/{pid}/aim").data.decode()
    assert "Nexus trainer warm-up" in aimpage and "Open the trainer" in aimpage
    # settings and what the check measured
    r = c.post(f"/profiles/{pid}/trainer/setup", json={"sens": 0.35, "dpi": 800, "measured_dpi": 776, "polling_hz": 1000,
                                                        "refresh_hz": 240, "evil": "x", "raw": True}, headers=H)
    d = r.get_json()
    assert d["numbers"]["edpi"] == 280 and d["numbers"]["cm360"] == 46.7 and d["numbers"]["dpi_off"] == -0.03
    assert "evil" not in d["setup"] and d["setup"]["raw"] is True
    assert c.post(f"/profiles/{pid}/trainer/setup", json={"sens": -1}, headers=H).status_code == 400
    data = _json.loads((sr.games(pid).path.parent / "trainer.json").read_text())
    from nexus.coach import askcoach as ac
    f = ac.facts("x", [], [], data)
    assert f["nexus_trainer_scores"][0]["scenario"] == "Grid flicks" and f["mouse"]["dpi_measured"] == 776
    assert c.get("/profiles/999/trainer").status_code == 404                     # a player that isn't yours
    assert tr.plan("training", [{"focus": ["tracking"], "weight": 3, "why": "x"}], [])["items"][0]["id"] == "track"


def test_sens_finder_finds_the_best_sens(app):
    import math
    from nexus.stats import trainer as tr
    c = setup_admin(app)
    pid = add_profile(c)
    H = {"Origin": "http://localhost"}

    def session(true, base=0.4):         # a player who aims best at `true`
        def q(s):
            return max(0.0, 1 - 2 * math.log(s / true) ** 2)
        tests = [{"sens": base * f, "click": 2000 * q(base * f), "track": 0.6 * q(base * f),
                  "over": max(0, math.log(base * f / true)), "under": max(0, -math.log(base * f / true))}
                 for f in (0.7, 0.85, 1, 1.15, 1.3)]
        tests += [{"sens": s, "click": 2000 * q(s), "track": 0.6 * q(s)} for s in tr.round2(tests)]
        return {"base": base, "tests": tests}

    first = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert 'data-finder="quick"' in first and 'data-finder="standard"' in first and 'data-finder="full"' in first
    r = c.post(f"/profiles/{pid}/trainer/sens", json=session(0.32), headers=H)
    d = r.get_json()
    assert r.status_code == 200 and abs(d["sens"] - 0.32) < 0.01 and d["sessions"] == 1 and d["sure"] == "low"
    for _ in range(2):
        d = c.post(f"/profiles/{pid}/trainer/sens", json=session(0.32), headers=H).get_json()
    assert d["sessions"] == 3 and d["sure"] == "medium" and d["low"] < 0.32 < d["high"]   # all on one day
    days = [tr.clean_sens_session(session(0.32)) for _ in range(3)]
    for k, s in enumerate(days):
        s["d"] = f"2026-11-0{k + 1}"
    assert tr.recommend(days)["sure"] == "high"                                          # three days that agree
    c.post(f"/profiles/{pid}/trainer/setup", json={"sens": 0.4, "dpi": 800}, headers=H)
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert "30 min · most exact" in page and "tr-chart" in page and "Change it in steps" in page
    # the best at the end of what was tested: said so, and the next test starts there
    rec = tr.recommend([tr.clean_sens_session(session(0.2))])
    assert rec["edge"] == "lower"
    # nonsense is refused
    for bad in ({"base": 0.4, "tests": []}, {"base": 0.4, "tests": [{"sens": 0.4, "click": -1, "track": 0.5}] * 5},
                {"base": "x", "tests": session(0.3)["tests"]}):
        assert c.post(f"/profiles/{pid}/trainer/sens", json=bad, headers=H).status_code == 400
    assert tr.sens_step(0.4, 0.42) == {"change": 0.05, "steps": [0.42]}

    # thorough: your sens at the start and the end shows how much you tired; the rounds in between are corrected
    def thorough(true, base=0.4, tire=0.012):
        def q(s):
            return max(0.0, 1 - 2 * math.log(s / true) ** 2)
        order = [base] + [base * f for f in (0.65, 0.75, 0.87, 1, 1.15, 1.3, 1.5)]
        order += [true * f for f in (0.88, 0.93, 0.97, 1.03, 1.07, 1.12)] * 2 + [base]
        return {"base": base, "mode": "thorough",
                "tests": [{"sens": round(s, 4), "i": i, "click": 2000 * q(s) * (1 - tire * i), "track": 0.6 * q(s) * (1 - tire * i)}
                          for i, s in enumerate(order)]}
    s = tr.clean_sens_session(thorough(0.3))
    assert s["mode"] == "thorough" and len(s["tests"]) == 21 and abs(tr._tiring(s) - 0.012) < 0.002
    rec = tr.recommend([s])
    assert abs(rec["sens"] - 0.3) < 0.01 and rec["sure"] == "medium" and rec["long"] == 1     # one thorough = two quick
    quick_only = tr.recommend([tr.clean_sens_session(session(0.32))])
    assert quick_only["sure"] == "low" and tr._tiring(tr.clean_sens_session(session(0.32))) == 0
    assert tr.sens_step(0.4, 0.3)["steps"][-1] == 0.3 and len(tr.sens_step(0.4, 0.3)["steps"]) == 4


def test_trainer_crosshair_is_kept_and_checked(app):
    from nexus.stats import trainer as tr
    c = setup_admin(app)
    pid = add_profile(c)
    H = {"Origin": "http://localhost"}
    x = {"color": "#00FF00", "outline": False, "ot": 1, "oo": 0.5, "dot": True, "dt": 2, "da": 1, "inner": True, "it": 2,
         "il": 3, "iv": 3, "ig": False, "io": 2, "ia": 1, "outer": False, "ot2": 2, "ol": 2, "ov": 2, "og": False, "oo2": 10, "oa": 0.35}
    r = c.post(f"/profiles/{pid}/trainer/setup", json={"crosshair": x}, headers=H)
    assert r.status_code == 200 and r.get_json()["setup"]["crosshair"]["color"] == "#00ff00"
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert 'id="tr-xpanel"' in page and '"dot": true' in page and "tr-xhair" in page        # set inside the trainer
    assert 'id="tr-fs"' in page                                                  # the fullscreen switch
    assert tr.clean_crosshair(dict(x, color="red")) is None                       # not a colour
    assert tr.clean_crosshair(dict(x, il=500)) is None                            # out of range
    assert tr.clean_crosshair(dict(x, dot="yes"))["dot"] is False                 # switches are true or false
    assert c.post(f"/profiles/{pid}/trainer/setup", json={"crosshair": {"color": "#fff"}}, headers=H).status_code == 400


def test_trainer_scenarios_hold_the_angle_and_the_long_sens_finder(app):
    import math
    from nexus.stats import trainer as tr
    c = setup_admin(app)
    pid = add_profile(c)
    H = {"Origin": "http://localhost"}
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    for name in ("Close flicks", "Far flicks", "Close tracking", "Far tracking", "Reactive tracking", "Hold the angle"):
        assert name in page
    lib = page[page.index('id="tr-lib"'):]                                                     # the library
    assert lib.index(">Flicks<") < lib.index(">Duels<") < lib.index(">Tracking<")                  # grouped
    assert {s["group"] for s in tr.scenario_list()} == set(tr.GROUPS)
    # hold the angle: headshots are hits, body shots and enemies that got away are kept
    r = c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "holdangle", "score": 1500, "seconds": 60, "hits": 12,
                                                       "shots": 16, "ms": 310, "body": 3, "escaped": 2}, headers=H)
    assert r.status_code == 200
    import json as _json
    sr = app.extensions["nexus"]["stats"]
    run = _json.loads((sr.games(pid).path.parent / "trainer.json").read_text())["runs"][-1]
    assert run["s"] == "holdangle" and run["body"] == 3 and run["escaped"] == 2 and run["acc"] == 0.75
    # the plan can pick the new ones (tracking need -> a tracking scenario first)
    assert tr.plan("training", [{"focus": ["peeking"], "weight": 3, "why": "x"}], [])["items"][0]["id"] in ("holdangle", "peek", "track_react")

    # 30 minutes: per part; tiring from start, middle and end at your own sens
    def full(flick, track, base=0.4, tire=0.008):
        def q(s, v):
            return max(0.0, 1 - 2 * math.log(s / v) ** 2)
        order = [base] + [base * f for f in (0.6, 0.7, 0.8, 0.9, 1, 1.12, 1.25, 1.4, 1.6)]
        r2 = [0.33 * f for f in (0.86, 0.91, 0.96, 1, 1.04, 1.09, 1.14)] * 3
        r2.insert(len(r2) // 2, base)
        tests = []
        for i, s in enumerate(order + r2 + [base]):
            k = 1 - tire * i
            p = {"fc": 1000 * q(s, flick) * k, "ff": 800 * q(s, flick) * k, "tc": 0.7 * q(s, track) * k,
                 "tf": 0.6 * q(s, track) * k, "tr": 0.5 * q(s, track) * k}
            tests.append({"sens": round(s, 4), "i": i, "click": p["fc"] + p["ff"], "track": (p["tc"] + p["tf"] + p["tr"]) / 3,
                          "parts": {a: round(b, 3) for a, b in p.items()}})
        return {"base": base, "mode": "full", "tests": tests}
    body = full(0.30, 0.36)
    s = tr.clean_sens_session(body)
    assert s["mode"] == "full" and len(s["tests"]) == 33 and abs(tr._tiring(s) - 0.008) < 0.002
    r = c.post(f"/profiles/{pid}/trainer/sens", json=body, headers=H).get_json()
    assert 0.29 < r["sens"] < 0.35 and abs(r["parts"]["fc"] - 0.30) < 0.02 and abs(r["parts"]["tc"] - 0.36) < 0.02
    page = c.get(f"/profiles/{pid}/trainer").data.decode()
    assert "Which sens each part likes" in page and "Close tracking" in page
    assert 'class="tr-dot" data-sens="' in page and 'data-mode="30 min"' in page and 'id="tr-tip"' in page   # hover a dot
    assert tr.recommend([s])["long"] == 1 and tr.MODE_WEIGHT["full"] == 3
    bad = dict(body, tests=[dict(t, parts={"fc": -5, "zz": 1}) for t in body["tests"]])
    assert all("parts" not in t or "fc" not in t["parts"] for t in tr.clean_sens_session(bad)["tests"])


def _detail(flick_ms=(380, 380), over=0.02, under=0.02, miss=(0, 0, 0, 0), track_on=(0.6, 0.6), lead=0.0,
            peek=(0, 0), place=0.0, body=0):
    """One run's detail the way the aim trainer sends it (trainer.js ixNew)."""
    d = [[0, 0, 0, 0, 0] for _ in range(8)]
    for k in range(8):
        ms = flick_ms[0] if k in (3, 4, 5) else flick_ms[1]
        d[k] = [4, 4 * ms, 4 * over, 4 * under, 4]
    lft, rgt, hi, lo = miss
    g = {}
    if hi:
        g["0,2"] = hi
    if lo:
        g["0,-2"] = lo
    if lft:
        g["-2,0"] = lft
    if rgt:
        g["2,0"] = rgt
    pk = {"L": [peek[0] and 3, 3 * peek[0], 3], "R": [peek[1] and 3, 3 * peek[1], 3]}
    return {"f": {"d": d, "s": [[10, 3000], [12, 4600], [10, 5000]],
                  "m": {"n": sum(miss), "l": lft, "r": rgt, "h": hi, "lo": lo, "g": g}},
            "t": {"L": [10, 10 * track_on[0]], "R": [10, 10 * track_on[1]], "lead": [lead * 8, 8], "re": [0, 0]},
            "p": {**pk, "place": [place * 6, 0, 6], "body": body}}


def test_aim_insights_from_the_trainers_runs(app):
    import json as _json
    from nexus.stats import aim_insights as ai
    from nexus.stats import trainer as tr
    c = setup_admin(app)
    pid = add_profile(c)
    H = {"Origin": "http://localhost"}
    # nothing measured yet: the page says how to start
    page = c.get(f"/profiles/{pid}/trainer/insights").data.decode()
    assert "Nothing measured yet" in page and "Open the aim trainer" in page
    assert f"/profiles/{pid}/trainer/insights" in c.get(f"/profiles/{pid}/trainer").data.decode()
    # the detail of a run is checked and stored; a broken one is dropped (the run is still kept)
    x = _detail(flick_ms=(520, 380), over=0.15, miss=(2, 2, 1, 14), track_on=(0.42, 0.62), lead=-1.0,
                peek=(520, 400), place=-1.2, body=1)
    assert tr.clean_detail(x) is not None
    assert tr.clean_detail({"f": {"d": [[1, 2]]}}) is None
    assert tr.clean_detail(_json.loads(_json.dumps(x).replace('"0,-2"', '"99,0"')))["f"]["m"]["g"] == {"0,2": 1, "-2,0": 2, "2,0": 2}
    for i in range(6):
        r = c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": ["grid", "track", "holdangle"][i % 3], "score": 900 + i,
                   "seconds": 45, "hits": 30, "shots": 40, "on_target": 0.5, "detail": x}, headers=H)
        assert r.status_code == 200
    r = c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "grid", "score": 800, "seconds": 45, "hits": 30, "shots": 40,
                                                       "detail": {"f": "nope"}}, headers=H)
    assert r.status_code == 200
    sr = app.extensions["nexus"]["stats"]
    data = _json.loads((sr.games(pid).path.parent / "trainer.json").read_text())
    assert "x" in data["runs"][0] and "x" not in data["runs"][-1]
    # grip and hand are kept, nonsense isn't
    r = c.post(f"/profiles/{pid}/trainer/setup", json={"grip": "fingertip", "hand": "right"}, headers=H)
    assert r.get_json()["setup"]["grip"] == "fingertip"
    assert c.post(f"/profiles/{pid}/trainer/setup", json={"grip": "fist", "hand": "both"}, headers=H).status_code == 400
    # what stands out: slower flicks to the left (right hand: toward the thumb), flying past, misses below, tracking
    # to the left, trailing, peeks from the left, crosshair below the head
    res = ai.build(data["runs"], {"grip": "fingertip", "hand": "right"})
    ids = [f["id"] for f in res["findings"]]
    for k in ("flick-side", "overshoot", "miss-vertical", "track-side", "track-behind", "peek-side", "placement-low"):
        assert k in ids, k
    side = next(f for f in res["findings"] if f["id"] == "flick-side")
    assert side["data"]["slow"] == "left" and "thumb side" in side["tips"][0]
    assert any("fingertip" in t for t in next(f for f in res["findings"] if f["id"] == "overshoot")["tips"])
    assert next(f for f in res["findings"] if f["id"] == "miss-vertical")["data"]["dir"] == "below"
    assert all(s in tr.SCENARIOS for f in res["findings"] for s in f["play"])
    assert res["findings"] == sorted(res["findings"], key=lambda f: -f["weight"])
    # left-handed: the same slow left side is the side away from the body
    lefty = ai.build(data["runs"], {"hand": "left"})
    assert "away from the body" in next(f for f in lefty["findings"] if f["id"] == "flick-side")["tips"][0]
    # even and clean -> nothing to work on there, it's listed as good
    clean = [dict(r, x=_detail()) for r in data["runs"][:6]]
    ok = ai.build(clean, {})
    assert not {"flick-side", "overshoot", "undershoot", "track-side"} & {f["id"] for f in ok["findings"]}
    assert any("even left and right" in g for g in ok["good"])
    # too few samples: no findings
    few = ai.findings(ai.numbers(ai.aggregate(data["runs"][:1]), data["runs"][:1]), {})[0]
    assert "flick-side" not in [f["id"] for f in few]
    # old runs (over 30 days) don't count
    old = [dict(r, d="2020-01-01") for r in data["runs"]]
    assert ai.build(old, {})["detail_runs"] == 0
    # skill profile, charts, focus plan
    assert {a["name"] for a in res["profile"]} >= {"Flick speed", "Tracking", "Reaction"}
    assert all(0 <= a["v"] <= 100 for a in res["profile"])
    assert len(res["charts"]["wheel"]) == 8 and res["charts"]["misses"] and res["charts"]["radar"]["pts"]
    assert {w["cls"] for w in res["charts"]["wheel"]} == {"over"}
    focus = res["focus"]
    assert focus and len(focus["items"]) <= 6 and len({i["id"] for i in focus["items"]}) == len(focus["items"]) // 2
    # the page: findings, tips, play links, charts; the trainer page has the focus plan and opens ?play=
    page = c.get(f"/profiles/{pid}/trainer/insights").data.decode()
    assert "Flicks to the left are slower" in page and "Hand, grip and how to fix it" in page
    assert f"/profiles/{pid}/trainer?play=" in page and "Start focus training" in page and "Skill profile" in page
    assert 'value="fingertip" selected' in page
    tp = c.get(f"/profiles/{pid}/trainer?plan=focus&play=track").data.decode()
    assert 'data-plan="focus"' in tp and '"start": "focus"' in tp and '"play": "track"' in tp
    assert '"play": ""' in c.get(f"/profiles/{pid}/trainer?play=nope").data.decode()
    # the last round of the focus training ticks it off on the Aim page
    r = c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "grid", "score": 300, "seconds": 30, "hits": 12, "shots": 14,
                                                       "plan_done": "focus", "plan_score": 2000}, headers=H)
    aim = _json.loads((sr.games(pid).path.parent / "aim.json").read_text())
    assert aim["log"][-1]["routine"] == "t-focus" and aim["log"][-1]["name"] == "Nexus trainer focus"
    # the coach knows the findings
    from nexus.coach import askcoach as ac
    data = _json.loads((sr.games(pid).path.parent / "trainer.json").read_text())
    f = ac.facts("x", [], [], data)
    assert f["aim_trainer_insights"][0]["finding"] and f["mouse_grip"] == {"grip": "fingertip", "hand": "right"}
    # in German
    c.post("/account", data={"look": "1", "style": "classic", "nav": "side", "lang": "de"})
    de = c.get(f"/profiles/{pid}/trainer/insights").data.decode()
    assert "Aim-Analyse" in de and "Flicks nach links sind langsamer" in de and "Hand, Griff und wie du es behebst" in de
    assert c.get("/profiles/999/trainer/insights").status_code == 404


def test_replay_files_settings_upload_and_app(app, monkeypatch):
    """4.9: the positions switch, vrfkit test, the coach page's replay card and uploads from the page and the app."""
    from nexus import replayfile
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    page = c.get("/settings").data.decode()
    assert 'name="replay_source"' in page and 'name="comp_rules_yaml"' in page and "Viper" in page
    form = {"ollama_temperature": "0.3", "ollama_num_ctx": "16384", "ollama_parallel": "4", "ollama_timeout_s": "300",
            "sample_fps": "2", "workers": "1", "max_upload_gb": "20", "max_jobs_per_user": "3",
            "minimap_roi": store.get("minimap_roi"), "killfeed_roi": store.get("killfeed_roi")}
    assert c.post("/settings", data=dict(form, replay_source="vod", vrfkit_path="/opt/nope/vrfkit")).status_code == 302
    assert store.get("replay_source") == "vod" and store.get("vrfkit_path") == "/opt/nope/vrfkit"
    assert store.build_config(store.profile(pid)).replay.source == "vod"
    r = c.post("/settings/test/vrfkit").get_json()
    assert not r["ok"] and "not found" in r["msg"]
    r = c.post("/settings", data=dict(form, comp_rules_yaml="maps:\n  Ascent:\n    roles: ['9D']\n"), follow_redirects=True)
    assert "Map rules for comps" in r.data.decode() and store.get("comp_rules_yaml") == ""
    c.post("/settings", data=dict(form, replay_source="replay"))
    assert store.build_config(store.profile(pid)).replay.source == "replay"

    page = c.get(f"/profiles/{pid}/coach/{MATCH_ID}").data.decode()
    assert 'id="replaycard"' in page and "Upload replay file" in page

    # upload from the coach page (vrfkit itself is tested in test_replayfile.py)
    def fake_ingest(vrf, rdir, work, vrfkit, keep_vrf=True):
        mid = vrf.read_bytes().decode().strip()
        Path(rdir).mkdir(parents=True, exist_ok=True)
        (Path(rdir) / f"{mid}.vrf").write_bytes(b"x")
        return {"match_id": mid, "players": 10, "rounds": 6, "deaths": 40, "build": "t", "map_url": ""}
    monkeypatch.setattr(replayfile, "ingest", fake_ingest)
    assert c.post("/api/replays", json={"name": "x.mp4", "size": 10}).status_code == 400
    body = MATCH_ID.encode()
    up = c.post("/api/replays", json={"name": "replay.vrf", "size": len(body)}).get_json()
    assert c.put(f"/api/uploads/{up['id']}?offset=0", data=body).get_json()["received"] == len(body)
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}/replay", json={"upload_id": up["id"]})
    assert r.status_code == 200 and r.get_json()["players"] == 10, r.data
    assert "The server has this match" in c.get(f"/profiles/{pid}/coach/{MATCH_ID}").data.decode()
    assert not list((store.data_dir / "cache" / "vrf_work").glob("*"))          # the upload was cleaned up
    # a replay of another match is kept for that match, and said so
    other = b"12b3659c-735e-432a-8f55-91425f8934df"
    up = c.post("/api/replays", json={"name": "r.vrf", "size": len(other)}).get_json()
    c.put(f"/api/uploads/{up['id']}?offset=0", data=other)
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}/replay", json={"upload_id": up["id"]})
    assert r.status_code == 409 and "another match" in r.get_json()["error"]

    # from the Nexus app: check what's there, upload the rest
    token = app.test_client().post("/api/companion/login", json={"username": "manuel", "password": ADMIN_PW}).get_json()["token"]
    H = {"Authorization": f"Bearer {token}"}
    anon = app.test_client()
    have = anon.post("/api/companion/replays/check", headers=H,
                     json={"match_ids": ["12b3659c-735e-432a-8f55-91425f8934df", "aaaaaaaa-0000-0000-0000-000000000000",
                                         "../../etc"]}).get_json()["have"]
    assert have == ["12b3659c-735e-432a-8f55-91425f8934df"]
    new = b"aaaaaaaa-0000-0000-0000-000000000000"
    up = anon.post("/api/companion/uploads", headers=H, json={"name": "aaaaaaaa-0000-0000-0000-000000000000.vrf",
                                                              "size": len(new)}).get_json()
    anon.put(f"/api/companion/uploads/{up['id']}?offset=0", headers=H, data=new)
    r = anon.post("/api/companion/replays", headers=H, json={"upload_id": up["id"]})
    assert r.status_code == 200 and r.get_json()["match_id"] == new.decode()
    # an unreadable replay is refused with a reason (the app then doesn't send it again)
    monkeypatch.setattr(replayfile, "ingest", lambda *a, **k: (_ for _ in ()).throw(replayfile.ReplayError("bad file")))
    up = anon.post("/api/companion/uploads", headers=H, json={"name": "b.vrf", "size": 3}).get_json()
    anon.put(f"/api/companion/uploads/{up['id']}?offset=0", headers=H, data=b"abc")
    r = anon.post("/api/companion/replays", headers=H, json={"upload_id": up["id"]})
    assert r.status_code == 422 and r.get_json()["error"] == "bad file"


def test_comp_sheet(app, monkeypatch):
    """4.13: comp sheet: agent pools from the stats (editable), ideal comp per map (web or typed)."""
    import nexus.coach.ollama as oll
    from nexus.coach import websearch as ws
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    tid = _premier_team(app, c, monkeypatch)
    names = {store.profile(m["pid"]).name: m["pid"] for m in store.team(tid).member_list}
    off = c.get(f"/teams/{tid}/sheet").data.decode()
    assert "Web search is off" in off and "Search the web" not in off and "Set by hand" in off
    store.set("search_provider", "duckduckgo")
    page = c.get(f"/teams/{tid}/sheet").data.decode()
    assert "Agent pool" in page and "Ideal composition" in page and "Not searched yet" in page
    assert "hsla(120," in page and "Search the web for all maps" in page and "Comp sheet" in page
    me = names["adv1ce"]
    edit = c.get(f"/teams/{tid}/sheet?edit={me}").data.decode()
    assert 'class="poolform"' in edit and "+ add agent" in edit

    # the owner saves a pool: own order, an added agent, one he won't play
    r = c.post(f"/teams/{tid}/sheet/pool/{me}", data={"order": "Viper,Jett,nobody", "no": "Sova"})
    assert r.status_code == 302 and r.headers["Location"].endswith("#pool")
    from nexus.stats import compsheet
    saved = compsheet.load(app.extensions["nexus"]["stats"].team_dir(tid))
    assert saved["pools"][str(me)]["order"][:2] == ["Viper", "Jett"] and saved["pools"][str(me)]["no"] == ["Sova"]
    page = c.get(f"/teams/{tid}/sheet").data.decode()
    assert "Won't play: Sova" in page and "Added by hand" in page and "edited" in page
    assert ">Show all agents<" not in page and "more</button>" not in page              # 3 agents: nothing to fold
    c.post(f"/teams/{tid}/sheet/pool/{me}", data={"order": "Viper,Jett,Omen,Fade,Skye,Sage,Neon,Yoru,Iso,Clove", "no": "Sova"})
    page = c.get(f"/teams/{tid}/sheet").data.decode()
    assert ">Show all agents<" in page and "+ 3 more</button>" in page and page.count('class=" more"') + page.count('class="added more"') == 3
    c.post(f"/teams/{tid}/sheet/pool/{me}", data={"reset": "1"})
    assert str(me) not in compsheet.load(app.extensions["nexus"]["stats"].team_dir(tid))["pools"]
    assert c.post(f"/teams/{tid}/sheet/pool/999999", data={"order": "Jett"}).status_code == 404

    # a teammate edits his own pool only
    friend = make_user(app, c, "burn", display_name="red-0#T")
    c.post(f"/teams/{tid}/access", data={"add": str(store.user_by_name("burn").id)})
    assert friend.get(f"/teams/{tid}/sheet").status_code == 200
    assert friend.post(f"/teams/{tid}/sheet/pool/{names['red-0']}", data={"order": "Omen", "no": ""}).status_code == 302
    assert friend.post(f"/teams/{tid}/sheet/pool/{me}", data={"order": "Omen", "no": ""}).status_code == 403
    assert friend.post(f"/teams/{tid}/sheet/ideal", data={"map": "Ascent", "agent": ["Jett"] * 5}).status_code in (403, 404)

    # ideal composition: typed by the owner
    mp = (store.team(tid).map_list or ["Ascent"])[0]
    r = c.post(f"/teams/{tid}/sheet/ideal", data={"map": mp, "agent": ["Jett", "Sova", "KAY/O", "Omen", "Killjoy"]})
    assert r.status_code == 302 and r.headers["Location"].endswith("#ideal")
    page = c.get(f"/teams/{tid}/sheet").data.decode()
    assert "set by you" in page and "Use the web comp" in page
    r = c.post(f"/teams/{tid}/sheet/ideal", data={"map": mp, "agent": ["Jett", "Jett", "Sova", "Omen", ""]}, follow_redirects=True)
    assert "5 different agents" in r.data.decode()
    c.post(f"/teams/{tid}/sheet/ideal", data={"map": mp, "reset": "1"})
    assert "set by you" not in c.get(f"/teams/{tid}/sheet").data.decode()

    # from the web, even when the comps page uses another mode
    assert store.team(tid).comp_method != "web"
    monkeypatch.setattr(ws, "searcher", lambda st: (lambda q, n=6: [
        {"title": "Comps", "url": "https://example.org/comps", "snippet": "Jett Sova KAY/O Omen Killjoy"}]))
    monkeypatch.setattr(ws, "page_text", lambda url, limit=4000, session=None: "Best comp: Jett, Sova, KAY/O, Omen, Killjoy.")

    class FakeModel:
        def __init__(self, *a, **k):
            self.model = "fake"

        def check(self):
            pass

        def chat_json(self, system, user, schema):
            return {"comps": [{"agents": ["Jett", "Sova", "KAY/O", "Omen", "Killjoy"], "note": "the standard comp", "sources": [1]}]}
    monkeypatch.setattr(oll, "Ollama", FakeModel)
    r = c.post(f"/teams/{tid}/webcomps", data={"map": mp, "back": "sheet"})
    assert r.status_code == 302 and "/sheet" in r.headers["Location"]
    assert _wait_stats(app, f"webcomps:{tid}")["status"] == "done"
    page = c.get(f"/teams/{tid}/sheet").data.decode()
    assert "from the web" in page and "the standard comp" in page and "https://example.org/comps" in page
    assert "Search again" in page

    # 4.14: "Follow our agent pools": off by default, switched on the comp sheet, the comps page or the settings
    comps = c.get(f"/teams/{tid}?map={mp}").data.decode()
    assert 'name="follow_pools"' in comps and "agent pool)" not in comps and "in adv1ce&#39;s agent pool" not in comps
    assert friend.post(f"/teams/{tid}/sheet/follow", data={"follow_pools": "1"}).status_code in (403, 404)
    c.post(f"/teams/{tid}/sheet/pool/{me}", data={"order": "Raze,Sova", "no": "Jett"})
    r = c.post(f"/teams/{tid}/sheet/follow", data={"follow_pools": "1"}, follow_redirects=True)
    assert "The comps now follow your agent pools." in r.data.decode() and "Comps follow these pools" in r.data.decode()
    comps = c.get(f"/teams/{tid}?map={mp}").data.decode()
    assert "in adv1ce&#39;s agent pool" in comps and "won't play it (agent pool)" not in comps
    assert "following your agent pools" in friend.get(f"/teams/{tid}?map={mp}").data.decode()
    r = c.post(f"/teams/{tid}/comps/method", data={"comp_method": "rules", "map": mp}, follow_redirects=True)
    assert "in adv1ce&#39;s agent pool" not in r.data.decode()                 # box not ticked: switched off
    c.post(f"/teams/{tid}/comps/method", data={"comp_method": "comfort", "map": mp, "follow_pools": "1"})
    assert "#1 in adv1ce&#39;s agent pool" in c.get(f"/teams/{tid}?map={mp}").data.decode()
    assert "checked> Follow our agent pools" in c.get(f"/teams/{tid}/settings").data.decode()

    # the overview explains its labels with popups, not a bare "?" cursor
    ovp = c.get(f"/teams/{tid}/overview").data.decode()
    assert "data-tip=" in ovp and 'class="chip style" title=' not in ovp
    app.extensions["nexus"]["stats"].shutdown()


def test_compsheet_helpers():
    from nexus.stats import compsheet
    def r(agent, won):
        return {"agent": agent, "won": won, "kills": 15, "deaths": 14, "rounds": 22, "acs": 220, "queue": "competitive"}
    rows = [r("Jett", 1)] * 5 + [r("Jett", 0)] * 2 + [r("Sova", 1)] * 3 + [r("Omen", 0)] * 3
    p = compsheet.pool(rows, None)
    assert [a["agent"] for a in p["agents"]] == ["Jett", "Sova", "Omen"] and not p["edited"]   # games, then win rate
    assert p["agents"][0]["rank"] == 1 and p["agents"][0]["games"] == 7
    p = compsheet.pool(rows, {"order": ["Omen", "Viper"], "no": ["Sova"]})
    assert [a["agent"] for a in p["agents"]] == ["Omen", "Viper", "Jett"] and p["no"] == ["Sova"] and p["edited"]
    assert next(a for a in p["agents"] if a["agent"] == "Viper")["added"]
    assert compsheet.hue(1, 5) == 120 and compsheet.hue(5, 5) == 0 and compsheet.hue(1, 1) == 120
    assert compsheet.clean_agents(["jett", "Nobody", "Jett", "kayo"]) == ["Jett", "KAY/O"]
    web = {"comps": [{"agents": ["Jett", "Sova", "KAY/O", "Omen", "Killjoy"], "note": "n", "sources": [1]},
                     {"agents": ["Raze", "Sova", "KAY/O", "Omen", "Killjoy"]}], "sources": [{"url": "u", "title": "t"}], "at": 1}
    assert compsheet.ideal("Ascent", None, web)["source"] == "web" and compsheet.ideal("Ascent", None, web)["others"] == 1
    assert compsheet.ideal("Ascent", ["Raze", "Fade", "Omen", "Viper", "Cypher"], web)["source"] == "typed"
    assert compsheet.ideal("Ascent", ["Raze"] * 5, web)["source"] == "web"          # not 5 different: ignored
    assert compsheet.ideal("Ascent", None, None) is None
    pools = {"a": {"agents": [{"agent": "Jett", "rank": 2, "games": 4}]}, "b": {"agents": [{"agent": "Jett", "rank": 1, "games": 9}]}}
    assert [w["label"] for w in compsheet.who_plays("Jett", pools)] == ["b", "a"]
    assert compsheet.who_plays("Viper", pools) == []


def test_goals_checkins_and_context(app, monkeypatch):
    """4.15: goals on the Habits page, post-match check-ins (and the IGL from them), how much the numbers tell."""
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    sr = app.extensions["nexus"]["stats"]
    tid = _premier_team(app, c, monkeypatch)
    members = store.team(tid).member_list
    names = {store.profile(m["pid"]).name: m["pid"] for m in members}
    me = names["adv1ce"]

    # stats page: weighted numbers, rounds by buy state, lobbies
    page = c.get(f"/profiles/{me}/stats").data.decode()
    assert "How much the numbers tell" in page and "Win rate weighted" in page and "Rounds won: " in page
    assert 'id="peers"' in page and "You vs your rank" in page and "Damage per round" in page     # 4.18

    # habits page: set a goal by hand, from a habit, drop it
    page = c.get(f"/profiles/{me}/habits").data.decode()
    assert 'id="goals"' in page and "No goals yet" in page and "Set goal" in page
    r = c.post(f"/profiles/{me}/goals", data={"metric": "traded", "target": "45 %", "games": "10", "text": "trade the entry"})
    assert r.status_code == 302 and r.headers["Location"].endswith("#goals")
    gs = sr.goals(me).load()
    assert gs[0]["metric"] == "traded" and gs[0]["target"] == 0.45 and gs[0]["source"] == "you"
    assert c.post(f"/profiles/{me}/goals", data={"metric": "kd", "target": ""}).status_code == 302
    assert len(sr.goals(me).load()) == 1                                     # no target: nothing saved
    c.post(f"/profiles/{me}/goals", data={"habit": "kast"})
    gs = sr.goals(me).load()
    assert gs[-1]["metric"] == "kast" and gs[-1]["target"] == 0.65
    page = c.get(f"/profiles/{me}/habits").data.decode()
    assert "trade the entry" in page and "Deaths traded" in page and "Drop" in page
    c.post(f"/profiles/{me}/goals/{gs[-1]['id']}/drop")
    assert sr.goals(me).load()[-1]["state"] == "dropped"

    # a teammate sets goals for his own player only
    friend = make_user(app, c, "burn", display_name="red-0#T")
    c.post(f"/teams/{tid}/access", data={"add": str(store.user_by_name("burn").id)})
    assert friend.post(f"/profiles/{names['red-0']}/goals", data={"metric": "hs", "target": "20%"}).status_code == 302
    assert sr.goals(names["red-0"]).load()[0]["metric"] == "hs"
    assert friend.post(f"/profiles/{me}/goals", data={"metric": "hs", "target": "20%"}).status_code == 403

    # check-in: the team's matches, one answer per player, the IGL from the votes
    page = c.get(f"/teams/{tid}/checkin").data.decode()
    assert "Who made most of the calls?" not in page and "Nexus doesn't know which player you are" in page
    page = c.get(f"/teams/{tid}/checkin?as={me}").data.decode()            # the owner answers as a player
    assert "Who made most of the calls?" in page and "Answer as" in page
    import re
    mids = re.findall(r'name="match_id" value="([^"]+)"', page)
    assert mids
    caller = names["red-2"]
    for who in ("adv1ce", "red-0", "red-3"):
        cl = friend if who == "red-0" else None
        data = {"match_id": mids[0], "caller": str(caller), "comms": "4", "mood": "3", "note": f"{who} note"}
        if cl is None:                                       # the owner answers for players without an account
            data["as"] = str(names[who])
            cl = c
        assert cl.post(f"/teams/{tid}/checkin", data=data).status_code == 302
    assert friend.post(f"/teams/{tid}/checkin", data={"match_id": "not-a-team-match", "comms": "3"}).status_code == 404
    page = c.get(f"/teams/{tid}/checkin?m={mids[0]}").data.decode()
    assert "3 answers" in page and "red-3 note" in page and "Caller according to the check-ins: <b>red-2</b>" in page
    ov = c.get(f"/teams/{tid}/overview").data.decode()
    assert "Named as the caller in 3 of 3 post-match check-ins" in ov
    assert 'id="duos"' in ov and "Who plays well together" in ov and "Traded each other" in ov      # 4.17
    assert "caller (3 check-in votes)" in c.get(f"/teams/{tid}/roles").data.decode()

    # what the coach gets for a player
    rows = sr.games(me).rows()
    ex = sr.coach_extras(me, rows, store.data_dir / "cache")
    assert ex["context"]["weighted"]["effective_games"] > 0 and ex["goals"] and ex["check_ins"]["comms_avg"] == 4.0
    sr.shutdown()
