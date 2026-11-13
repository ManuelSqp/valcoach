"""4.26: KovaaK's is gone from the web pages (one switch, stats/kovaaks.py WEB); the code and stored data stay."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import kovaaks as kv  # noqa: E402


def test_no_kovaaks_on_the_pages(app):  # noqa: F811 (fixture)
    assert kv.WEB is False
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    # someone who used to import KovaaK's scores and saved a share code as a routine
    aim_json = store.data_dir / "profiles" / str(pid) / "stats" / "aim.json"      # stats/<pid>: the player's data
    aim_json.parent.mkdir(parents=True, exist_ok=True)
    aim_json.write_text(json.dumps({"kovaaks": [{"s": "Tile Frenzy", "score": 90, "t": 1, "d": "2026-10-01"}]}))
    uid = store.user_by_name("manuel").id
    upath = store.data_dir / "aim" / f"user-{uid}.json"
    upath.parent.mkdir(parents=True, exist_ok=True)
    upath.write_text(json.dumps({"routines": [{"id": "kk1", "name": "Old KK code", "kind": "kovaaks", "code": "KovaaKsOldCode",
                                               "url": "", "minutes": 10, "focus": ["flicks"], "steps": ""}]}))
    for url in (f"/profiles/{pid}/aim", f"/profiles/{pid}/ask", "/settings", "/account", "/this-pc"):
        r = c.get(url)
        if r.status_code == 404:
            continue
        page = r.data.decode()
        assert "KovaaK" not in page, url
    assert c.get(f"/profiles/{pid}/aim").status_code == 200
    # the warm-up isn't the KovaaK's one, even with KovaaK's scores; the old share-code routine doesn't show
    page = c.get(f"/profiles/{pid}/aim").data.decode()
    assert "Old KK code" not in page and "KovaaKsOldCode" not in page
    # the KovaaK's page, downloads, actions and the playlist search are off
    assert c.get(f"/profiles/{pid}/aim/kovaaks").status_code == 404
    assert c.get(f"/profiles/{pid}/aim/kovaaks/warmup.json").status_code == 404
    assert c.post(f"/profiles/{pid}/aim", data={"action": "k_clear_stats"}).status_code == 404
    assert c.post(f"/profiles/{pid}/aim", data={"action": "add", "name": "x", "kind": "kovaaks", "code": "KovaaKsAbc"}).status_code == 400
    assert c.post(f"/api/profiles/{pid}/aim/find-playlists").status_code == 404
    # nothing was deleted: the scores and the routine are still stored
    assert json.loads(aim_json.read_text())["kovaaks"]
    assert json.loads(upath.read_text())["routines"][0]["code"] == "KovaaKsOldCode"


def test_switch_brings_it_back(app, monkeypatch):  # noqa: F811 (fixture)
    monkeypatch.setattr(kv, "WEB", True)
    c = setup_admin(app)
    pid = add_profile(c)
    assert "Open KovaaK" in c.get(f"/profiles/{pid}/aim").data.decode()
    assert c.get(f"/profiles/{pid}/aim/kovaaks").status_code == 200
