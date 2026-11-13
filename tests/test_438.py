"""4.38: fewer menu entries grouped by topic, tabs between the pages of a topic, and the Today page."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401


def _tabs(page):
    return re.findall(r'<nav class="ptabs"[^>]*>(.*?)</nav>', page, re.S)


def test_sidebar_topics_and_tabs(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/today").data.decode()
    side = page.split('class="ptabs"')[0]
    for topic in ("Today", "Aim", "Game sense", "Ask the coach", "Matches", "Stats"):
        assert f">{topic}<" in side, topic
    tabs = _tabs(page)
    assert len(tabs) == 1
    for name in ("Today", "Training", "Habits", "Quiz"):
        assert f">{name}" in tabs[0], name
    assert 'class="on"' in tabs[0] and f'/profiles/{pid}/today"' in tabs[0]
    aim = _tabs(c.get(f"/profiles/{pid}/aim").data.decode())
    assert len(aim) == 1 and "Aim trainer" in aim[0] and "Warm-up &amp; routines" in aim[0] and "Mouse &amp; monitor" in aim[0]
    # a topic with a single page shows no tab bar
    assert _tabs(c.get(f"/profiles/{pid}/ask").data.decode()) == []


def test_team_tabs_follow_permissions(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "user_id": owner}])
    tabs = _tabs(c.get(f"/teams/{tid}/scrims").data.decode())
    assert len(tabs) == 1 and "Review evening" in tabs[0] and "Recordings" in tabs[0]
    own = _tabs(c.get(f"/teams/{tid}/notes").data.decode())
    assert own and "Team settings" in own[0]
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    theirs = _tabs(mate.get(f"/teams/{tid}/notes").data.decode())
    assert theirs and all("Team settings" not in t for t in theirs)


def test_today_page(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    page = c.get(f"/profiles/{pid}/today").data.decode()
    assert "Warm up" in page and "Train a skill" in page and "Everything else" in page
    assert "Nothing in the aim trainer yet this week." in page
    c.post(f"/profiles/{pid}/trainer/runs", json={"scenario": "grid", "score": 3000, "seconds": 45, "hits": 40, "shots": 45})
    page = c.get(f"/profiles/{pid}/today").data.decode()
    assert "1 run · " in page and f"/profiles/{pid}/trainer?plan=skill_" in page
    assert c.get("/profiles/9999/today").status_code == 404
    # the player switcher keeps you on Today
    other = add_profile(c, name="subby", tag="#2")
    assert f"/profiles/{other}/today" in c.get(f"/profiles/{pid}/today").data.decode()


def test_search_index_and_german(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    pid = add_profile(c)
    store = app.extensions["nexus"]["store"]
    urls = json.dumps(c.get("/api/search-index").get_json())
    assert f"/profiles/{pid}/today" in urls and f"/profiles/{pid}/callouts" in urls
    store.update_user(store.user_by_name("manuel").id, prefs=json.dumps({"lang": "de"}))
    page = c.get(f"/profiles/{pid}/today").data.decode()
    assert "Einen Skill trainieren" in page and "Alles andere" in page and "Spielverständnis" in page
