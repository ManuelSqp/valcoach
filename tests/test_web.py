import io
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from valcoach.web import create_app  # noqa: E402

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
    store = app.extensions["valcoach"]["store"]
    store.set("henrik_api_key", "HDEV-test")
    store.set("minimap_roi", ", ".join(map(str, synth.MM_ROI)))
    store.set("killfeed_roi", ", ".join(map(str, synth.KF_ROI)))
    store.set("sample_fps", "2")
    app.recordings = str(tmp_path / "recordings")
    yield app
    app.extensions["valcoach"]["runner"].shutdown()


def setup_admin(app, username="manuel"):
    c = app.test_client()
    r = c.post("/setup", data={"username": username, "password": ADMIN_PW, "password2": ADMIN_PW})
    assert r.status_code == 302, r.data
    store = app.extensions["valcoach"]["store"]
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
    store = app.extensions["valcoach"]["store"]
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
                       "vod_file": (io.BytesIO(b"\x00" * 2048), "clip.mp4")},
                 content_type="multipart/form-data")
    jid = r.headers["Location"].split("/")[-1]
    store = app.extensions["valcoach"]["store"]
    assert f"/uploads/{store.user_by_name('bob').id}/" in store.job(jid).vod_path


def test_upload_and_bad_inputs(app):
    c = setup_admin(app)
    pid = add_profile(c)
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}",
               data={"mode": "team", "vod": "upload", "vod_file": (io.BytesIO(b"x"), "evil.exe")},
               content_type="multipart/form-data")
    assert b"Unsupported video type" in c.get(r.headers["Location"]).data
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
    store = app.extensions["valcoach"]["store"]
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
    store = app.extensions["valcoach"]["store"]
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
    store = app.extensions["valcoach"]["store"]
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
    db = sqlite3.connect(data / "valcoach.db")
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
    store = app.extensions["valcoach"]["store"]
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
    app.extensions["valcoach"]["runner"].shutdown()


def test_restart_recovers_jobs(tmp_path):
    data = tmp_path / "d"
    app = create_app(data, start_workers=False)
    store = app.extensions["valcoach"]["store"]
    uid = store.create_user("manuel", ADMIN_PW, is_admin=True)
    pid = store.create_profile(uid, "adv1ce", "LFT")
    store.create_job("run1", pid, MATCH_ID, "both")
    store.update_job("run1", status="running")
    app.extensions["valcoach"]["runner"].shutdown()
    app2 = create_app(data)
    assert app2.extensions["valcoach"]["store"].job("run1").status == "error"
    app2.extensions["valcoach"]["runner"].shutdown()


def test_seed_from_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[player]\nname = "adv1ce"\ntag = "LFT"\n[henrik]\napi_key = "HDEV-x"\n'
                   '[ollama]\nmodel = "qwen3:30b"\n')
    app = create_app(tmp_path / "d", config_seed=cfg, start_workers=False)
    store = app.extensions["valcoach"]["store"]
    assert store.get("henrik_api_key") == "HDEV-x" and store.get("ollama_model") == "qwen3:30b"
    c = app.test_client()
    c.post("/setup", data={"username": "manuel", "password": ADMIN_PW, "password2": ADMIN_PW})
    assert [p.riot_id for p in store.profiles(store.user_by_name("manuel").id)] == ["adv1ce#LFT"]
    app.extensions["valcoach"]["runner"].shutdown()


def test_player_order(app):
    admin = setup_admin(app)
    bob = make_user(app, admin, "bob")
    store = app.extensions["valcoach"]["store"]
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
    db = sqlite3.connect(data / "valcoach.db")
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
    from valcoach.web.store import Store
    s = Store(data)
    assert [p.name for p in s.profiles(1)] == ["Adv1ce", "bravo", "zed"]     # alphabetical to start
    s.reorder_profiles(1, [1, 3, 2])
    assert [p.name for p in Store(data).profiles(1)] == ["zed", "bravo", "Adv1ce"]


def test_unknown_db_columns_are_ignored(tmp_path):
    """A column added by another version must not crash loading (the 'position' bug)."""
    from valcoach.web.store import Store
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
    from valcoach.web.store import Store
    s = Store(tmp_path / "new-location")
    (s.data_dir / "reports" / "job1").mkdir(parents=True)
    (s.data_dir / "reports" / "job1" / "r.html").write_text("<html>")
    (s.data_dir / "uploads" / "3").mkdir(parents=True)
    (s.data_dir / "uploads" / "3" / "x.mp4").write_bytes(b"0")
    assert s.resolve("/home/sysadmin/valcoach-v2/data/reports/job1/r.html") == s.data_dir / "reports/job1/r.html"
    assert s.resolve("/home/sysadmin/valcoach-v2/data/uploads/3/x.mp4") == s.data_dir / "uploads/3/x.mp4"
    assert s.resolve("/nope/recordings/a.mp4") is None and s.resolve("") is None


def test_history_paging_and_stored(app, monkeypatch):
    from valcoach import pipeline
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
    sr = app.extensions["valcoach"]["stats"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = sr.status(key)
        if st and st["status"] in ("done", "error"):
            return st
        time.sleep(0.1)
    raise TimeoutError(key)


def test_stats_teams_and_pick_helper(app, monkeypatch):
    import synth_history as sh
    from valcoach import pipeline
    history = sh.build_history(24)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrik(history, full_depth=6))
    c = setup_admin(app)
    synth.write_agent_cache(Path(app.extensions["valcoach"]["store"].data_dir) / "cache")
    me = add_profile(c)
    assert b"No stats yet" in c.get(f"/profiles/{me}/stats").data
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
    # bad meta is refused, other users can't see the team
    r = c.post(f"/teams/{tid}/settings", data=dict(form, meta="Haven:\n  roles: 9D\n"), follow_redirects=True)
    assert "Map meta: Haven: roles must add up to 5" in r.data.decode()
    assert "1D 1I 2C 1S" in c.get(f"/teams/{tid}").data.decode()       # old meta kept
    other = make_user(app, c, "friend")
    assert other.get(f"/teams/{tid}").status_code == 404
    assert other.get(f"/profiles/{me}/stats").status_code == 404
    app.extensions["valcoach"]["stats"].shutdown()


def test_pro_and_videos_page(app, monkeypatch):
    import synth_history as sh
    from valcoach import pipeline
    from valcoach.stats import youtube
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
            return {"pro_summary": "Copy how he spaces for the entry.", "items": [{"id": i, "watch_for": f"note {i}"} for i in ids],
                    "habits": ["Trade your entry within 2 s"]}
    import valcoach.coach.ollama as oll
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
    assert "Copy how he spaces for the entry." in page and "Watch for:</b> note v1" in page
    assert "watch?v=x1" in page and "Trade your entry within 2 s" in page
    app.extensions["valcoach"]["stats"].shutdown()


def test_premier_team_import_and_roles(app, monkeypatch):
    import synth_history as sh
    from valcoach import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10))
    c = setup_admin(app)
    store = app.extensions["valcoach"]["store"]
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
    assert "Premier Red Squad#RED" in page and "division 12" in page and "Comps at a glance" in page

    # roles: assign, see the suggestion respect it, agent to learn shows up
    page = c.get(f"/teams/{tid}/roles").data.decode()
    assert "Suggested lineup" in page and "How well everyone fits each role" in page and "Agent to learn" in page
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
    app.extensions["valcoach"]["stats"].shutdown()


@pytest.mark.parametrize("mode", ["nonames", "none"])
def test_premier_roster_without_names(app, monkeypatch, mode):
    """Live HenrikDev returns members with name/tag = null (or no members): names come from the matches / by-puuid."""
    import synth_history as sh
    from valcoach import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10, members=mode))
    c = setup_admin(app)
    store = app.extensions["valcoach"]["store"]
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
    app.extensions["valcoach"]["stats"].shutdown()


@pytest.mark.parametrize("roster_in_match", [True, False])
def test_premier_no_members_one_match(app, monkeypatch, roster_in_match):
    """Live case: 0 members and a single Premier match (new season). Use the match's Premier roster,
    or else the side your own player was on."""
    import synth_history as sh
    from valcoach import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(
        history, full_depth=10, members="none-1match", roster_in_match=roster_in_match))
    c = setup_admin(app)
    store = app.extensions["valcoach"]["store"]
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
    app.extensions["valcoach"]["stats"].shutdown()


def test_changelog_page_and_update_note(app):
    from valcoach import __version__
    c = setup_admin(app)
    store = app.extensions["valcoach"]["store"]
    page = c.get("/").data.decode()
    assert f"v{__version__}" in page and "was updated to" not in page        # fresh install: no note
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
    from valcoach import pipeline
    history = sh.build_history(30)
    monkeypatch.setattr(pipeline, "get_client", lambda cfg: sh.FakeHenrikPremier(history, full_depth=10, roster_in_match=True))
    store = app.extensions["valcoach"]["store"]
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
    import valcoach.coach.ollama as oll
    from valcoach import discord as dc
    monkeypatch.setattr(oll, "Ollama", _FakeModel)
    sent = []

    class Resp:
        status_code = 204
        text = ""
    monkeypatch.setattr(dc.requests, "post", lambda url, json, timeout: sent.append((url, json)) or Resp())
    c = setup_admin(app)
    store = app.extensions["valcoach"]["store"]
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

    # --- the schedule: due on its day/hour once a week, not again after posting
    from datetime import datetime
    sr = app.extensions["valcoach"]["stats"]
    job = app.extensions["valcoach"]["weekly_job"]
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
    store = app.extensions["valcoach"]["store"]
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
    from valcoach import discord as dc
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
    from valcoach.web.abilityshapes import CATALOG, shape_for, color_for, AGENT_COLORS
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
    store = app.extensions["valcoach"]["store"]
    sr = app.extensions["valcoach"]["stats"]
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
    app.extensions["valcoach"]["nightly_job"](store.team(tid))
    assert sr.status(f"import:{me}") is not None
    _wait_stats(app, f"import:{me}")
    # settings: off, and a different hour
    r = c.post(f"/teams/{tid}/sync-settings", data={"hour": "1"})
    assert r.status_code == 302 and store.team(tid).sync_info == {**store.team(tid).sync_info, "nightly": False, "hour": 1}
    assert sr.tick_nightly(job, now=datetime(2026, 11, 4, 1, 10)) == []
    c.post(f"/teams/{tid}/sync-settings", data={"hour": "1", "nightly": "1"})
    assert "syncs nightly 01:00" in c.get(f"/teams/{tid}").data.decode()
    assert "Automatic sync" in c.get(f"/teams/{tid}/settings").data.decode()
    # the role table has sortable headers
    page = c.get(f"/teams/{tid}/roles").data.decode()
    assert 'class="sorth"' in page and "<tbody>" in page
    sr.shutdown()


# ---------------------------------------------------------------------------
# review fixes (see CHANGES.md)
def test_bad_ids_and_anchor_inputs(app):
    c = setup_admin(app)
    pid = add_profile(c)
    for mid in ("..", "x.json", "valcoach.db"):
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
    store = app.extensions["valcoach"]["store"]
    (store.data_dir / "cache" / "matches" / "dm-match-1.json").write_text(json.dumps(raw))
    c = setup_admin(app)
    pid = add_profile(c)
    for url in (f"/profiles/{pid}/coach/dm-match-1", f"/profiles/{pid}/notes/dm-match-1"):
        r = c.get(url)
        assert r.status_code == 302 and b"can&#39;t be coached" in c.get(r.headers["Location"]).data


def test_job_quota_upload_limit_and_running_delete(app):
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["valcoach"]["store"]
    # a job that sits in the queue (never submitted) counts against the quota
    store.create_job("held1", pid, MATCH_ID, "team")
    store.set("max_jobs_per_user", "1")
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}", data={"mode": "team", "vod": "", "no_llm": "1"})
    assert b"already have 1 report" in c.get(r.headers["Location"]).data
    store.set("max_jobs_per_user", "3")
    # upload over the size limit is refused before it is stored
    store.set("max_upload_gb", "0.000001")          # ~1 KB
    r = c.post(f"/profiles/{pid}/coach/{MATCH_ID}",
               data={"mode": "team", "vod": "upload", "vod_file": (io.BytesIO(b"x" * 5000), "big.mp4")},
               content_type="multipart/form-data")
    assert b"upload is too big" in c.get(r.headers["Location"]).data
    assert not list(store.upload_dir(store.user_by_name("manuel").id).glob("*"))
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
    # the app's own pages (same host) and non-browser clients still work
    assert c.post("/profiles/new", headers={"Origin": "http://localhost"},
                  data={"name": "a", "tag": "b", "region": "eu", "platform": "pc", "mode": "both",
                        "language": "English", "playbook": ""}).status_code == 302


def test_job_is_claimed_once(app):
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["valcoach"]["store"]
    store.create_job("twice1", pid, MATCH_ID, "team")
    assert store.claim_job("twice1") is True
    assert store.claim_job("twice1") is False          # second submit of the same job does nothing
    assert store.job("twice1").status == "running"


def test_strat_board_only_stores_typed_fields(app):
    """A team member can't plant HTML in fields the editor shows as numbers."""
    c = setup_admin(app)
    store = app.extensions["valcoach"]["store"]
    me = add_profile(c)
    tid = store.create_team(store.user_by_name("manuel").id, "Squad")
    store.update_team(tid, members=[{"pid": me, "kind": "starter"}], maps=["Testmap"])
    r = c.post(f"/teams/{tid}/strats", data={"name": "B split", "map": "Testmap", "side": "attack"})
    sid = int(r.headers["Location"].rsplit("/", 1)[1])
    evil = '"><img src=x onerror=alert(1)>'
    items = [{"id": "a1", "t": "num", "x": 10, "y": 20, "n": evil, "r": evil, "ang": evil, "len": "5"},
             {"id": "a2", "t": "arrow", "x": 1, "y": 2, "x2": 30, "y2": 40, "c": "us", "dash": 1},
             {"id": "a3", "t": "pen", "pts": [[1, 2], ["x", 3], [4, 5]]}, "junk", {"no": "type"}]
    r = c.post(f"/api/teams/{tid}/strats/{sid}", json={"data": {"steps": [{"name": "S", "items": items}]}})
    assert r.status_code == 200
    saved = store.strat(sid)["data"]["steps"][0]["items"]
    assert saved[0] == {"id": "a1", "t": "num", "x": 10, "y": 20, "len": 5}
    assert saved[1]["x2"] == 30 and saved[1]["dash"] is True
    assert saved[2]["pts"] == [[1, 2], [4, 5]] and len(saved) == 3
    assert "onerror" not in json.dumps(store.strat(sid)["data"])

