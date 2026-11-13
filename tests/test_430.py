"""4.30: Team › Practice › Scrims, the scrim log."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import scrims as sc  # noqa: E402

MAPS = ["Ascent", "Bind", "Lotus"]


def mk(**kw):
    base = {"opponent": "Team X", "map": "Ascent", "us": "13", "them": "9", "date": "2026-11-01"}
    base.update(kw)
    s, err = sc.clean(base, MAPS)
    assert s, err
    return s


def test_clean_summary_and_tendencies():
    assert sc.clean({"opponent": "", "map": "Ascent", "us": 1, "them": 2}, MAPS)[0] is None
    assert sc.clean({"opponent": "A", "map": "Nowhere", "us": 1, "them": 2}, MAPS)[0] is None
    assert sc.clean({"opponent": "A", "map": "Ascent", "us": "x", "them": 2}, MAPS)[0] is None
    assert sc.clean({"opponent": "A", "map": "Ascent", "us": 1, "them": 2, "date": "13.11.2026"}, MAPS)[0] is None
    s = mk(good=["pistols", "nope"], bad=["retakes", "pistols"], h_us="8", h_them="4", side="attack")
    assert s["good"] == ["pistols"] and s["bad"] == ["retakes"] and s["half"] == [8, 4]
    assert mk(h_us="14", h_them="1")["half"] is None                 # a first half bigger than the score: dropped
    data = {}
    for s in [mk(bad=["retakes"], side="attack", h_us="8", h_them="4"), mk(us="7", them="13", bad=["retakes", "comms"], good=["pistols"]),
              mk(map="Bind", us="13", them="11", good=["pistols"], opponent="team x"), mk(map="Bind", us="5", them="13", opponent="Other")]:
        sc.add(data, s, 1, "me")
    sm = sc.summary(data["scrims"])
    assert sm["all"]["n"] == 4 and (sm["all"]["w"], sm["all"]["l"]) == (2, 2)
    assert sm["opps"][0]["name"].lower() == "team x" and sm["opps"][0]["n"] == 3      # names match without case
    assert sm["topics"][0]["id"] == "retakes" and sm["topics"][0]["bad"] == 2
    assert sm["sides"]["attack"] == {"won": 8, "played": 12, "rate": 0.67}
    kinds = {x["kind"]: x for x in sc.tendencies(sm)}
    assert kinds["bad"]["items"] == ["Retakes"] and kinds["good"]["items"] == ["Pistol rounds"]
    assert kinds["maps"]["items"][0].startswith("Ascent")


def test_page_add_edit_delete(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    pid = add_profile(c)
    owner = store.user_by_name("manuel").id
    tid = store.create_team(owner, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter"}])
    assert "No scrims yet" in c.get(f"/teams/{tid}/scrims").data.decode()
    c.post(f"/teams/{tid}/scrims", data={"opponent": "Night Owls", "map": "Ascent", "us": "13", "them": "7",
                                         "good": ["executes"], "bad": ["retakes"], "worked": "Fast A hits"})
    page = c.get(f"/teams/{tid}/scrims").data.decode()
    assert "Night Owls" in page and "Fast A hits" in page and "Executes" in page
    d = json.loads((store.data_dir / "teams" / str(tid) / "scrims.json").read_text())
    sid = d["scrims"][0]["id"]
    # a teammate adds one too, but can't change the owner's
    mate = make_user(app, c, "mate")
    store.add_team_access(tid, store.user_by_name("mate").id)
    mate.post(f"/teams/{tid}/scrims", data={"opponent": "Night Owls", "map": "Bind", "us": "9", "them": "13"})
    assert mate.post(f"/teams/{tid}/scrims", data={"id": sid, "opponent": "X", "map": "Bind", "us": "1", "them": "13"}).status_code == 403
    assert mate.post(f"/teams/{tid}/scrims/{sid}/delete").status_code == 403
    page = c.get(f"/teams/{tid}/scrims?opp=night owls").data.decode()
    assert "1–1" in page                                     # both scrims against them, filtered by name
    # the owner changes it, then removes it
    c.post(f"/teams/{tid}/scrims", data={"id": sid, "opponent": "Night Owls", "map": "Ascent", "us": "13", "them": "11"})
    assert json.loads((store.data_dir / "teams" / str(tid) / "scrims.json").read_text())["scrims"][0]["them"] == 11
    c.post(f"/teams/{tid}/scrims/{sid}/delete")
    assert len(json.loads((store.data_dir / "teams" / str(tid) / "scrims.json").read_text())["scrims"]) == 1
    # outsiders don't see it
    other = make_user(app, c, "other")
    assert other.get(f"/teams/{tid}/scrims").status_code == 404
