"""4.22: the quiz on the playback (with the coach's comment), the agent pool advisor."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_web import MATCH_ID, _run_with_model, add_profile, app, make_user, setup_admin, synthetic  # noqa: E402,F401

from nexus.stats import agentpool, compsheet, roles  # noqa: E402


def _rows(agent, n, acs=200.0, lobby=None):
    return [{"agent": agent, "acs": acs, "lobby_agents": [[a, v] + [0] * 9 for a, v in (lobby or [])]} for _ in range(n)]


def test_agent_pool_advisor():
    roles.load(None)
    players = [
        {"label": "a", "pid": 1, "rows": _rows("Jett", 20) + _rows("Sova", 10, 260.0, [("Sova", 200.0)] * 2), "pool": ["Jett", "Sova"], "no": []},
        {"label": "b", "pid": 2, "rows": _rows("Killjoy", 30), "pool": ["Killjoy"], "no": ["Viper"]},
        {"label": "c", "pid": 3, "rows": _rows("Omen", 25) + _rows("Brimstone", 5), "pool": ["Omen", "Brimstone"], "no": []},
    ]
    ideal = {"Ascent": ["Jett", "Sova", "Omen", "Killjoy", "Viper"], "Bind": ["Raze", "Skye", "Brimstone", "Cypher", "Viper"]}
    meta = {"Ascent": {"games": 10, "agents": [{"agent": "Fade", "share": 0.5, "role": "Initiator"}, {"agent": "Jett", "share": 0.9}]}}
    a = agentpool.advise(players, ["Ascent", "Bind"], ideal, meta)
    miss = {m["agent"]: m for m in a["missing"]}
    assert set(miss) == {"Viper", "Raze", "Skye", "Cypher", "Fade"}
    assert miss["Viper"]["maps"] == ["Ascent", "Bind"] and miss["Viper"]["ideal"] and miss["Fade"]["share"] == 0.5
    assert a["missing"][0]["agent"] == "Viper"                                   # needed on the most maps first
    sug = {p["label"]: [s["agent"] for s in p["suggest"]] for p in a["players"]}
    assert "Viper" in sug["c"] and "Viper" not in sug["b"]                       # the controller learns Viper; b won't play it
    assert all(len(v) <= agentpool.PER_PLAYER for v in sug.values())
    given = [x for v in sug.values() for x in v]
    assert len(given) == len(set(given))                                          # each agent to one player
    sk = next(s for p in a["players"] for s in p["suggest"] if s["agent"] in ("Skye", "Fade"))
    assert any("ACS 260 on Initiators, players of their rank 200" in w for w in sk["why"]), sk
    assert a["roles"]["Sentinel"] == ["b"] and "Sentinel" in a["thin"]
    f = agentpool.facts(a)
    assert f["suggested"] and any(x.startswith("Viper") for x in f["agents_nobody_plays_on_your_maps"])
    assert agentpool.advise([], ["Ascent"], {}, {}) is None and agentpool.facts(None) is None


def test_quiz_on_the_playback_with_the_coach(app, monkeypatch):  # noqa: F811 (fixture)
    fb = {"summary": "You took the duel alone", "importance": 2,
          "player": {"went_well": [], "mistakes": ["Peeked without the flash"], "better_option": "Wait for the Sova drone"}}
    c = setup_admin(app)
    job, _ = _run_with_model(app, c, monkeypatch, lambda n: fb)
    sr = app.extensions["nexus"]["stats"]
    pid = job.profile_id
    sr.save_quiz(pid, {"created": 1, "model": "m", "questions": [
        {"id": "q1", "kind": "alone", "kind_label": "First death", "map": "Testmap", "round": 2, "side": "attack",
         "match_id": MATCH_ID, "agent": "Jett", "question": "You are alone at A.", "options": ["Peek", "Wait", "Fall back"],
         "best": 1, "why": "They are three.", "happened": "You died.", "won": False, "t_ms": 9000},
        {"id": "q2", "kind": "alone", "kind_label": "First death", "map": "Testmap", "round": 3, "side": "attack",
         "match_id": MATCH_ID, "agent": "Jett", "question": "Old question.", "options": ["a", "b", "c"], "best": 0,
         "why": "", "happened": "", "won": True}]})                  # written before 4.22: no moment, no playback
    page = c.get(f"/profiles/{pid}/quiz").data.decode()
    assert 'id="rp-box"' in page and "/replay.js" in page and "/quiz/QID/replay" in page
    d = c.get(f"/api/profiles/{pid}/quiz/q1/replay").get_json()
    assert d["t"] == 9000 and d["round"] == "2" and list(d["replay"]["rounds"]) == ["2"] and d["replay"]["map"]
    assert any(x.get("you") for x in d["replay"]["rounds"]["2"]["roster"].values())          # you are marked
    assert d["coach"]["summary"] == "You took the duel alone" and d["coach"]["mistakes"] == ["Peeked without the flash"]
    assert d["coach"]["url"] == f"/jobs/{job.id}/report"
    assert c.get(f"/api/profiles/{pid}/quiz/q2/replay").status_code == 404
    assert c.get(f"/api/profiles/{pid}/quiz/nope/replay").status_code == 404
    other = make_user(app, c, "stranger")
    assert other.get(f"/api/profiles/{pid}/quiz/q1/replay").status_code in (403, 404)


def test_quiz_questions_keep_the_moment():
    from nexus.stats import quiz

    class LLM:
        def chat_json(self, system, user, schema):
            return {"questions": [{"id": "q1", "question": "Q?", "options": ["a", "b", "c"], "best": 0, "why": "w"}]}
    picked = [{"id": "q1", "kind": "clutch", "t_ms": 41234, "happened": "h",
               "facts": {"match_id": "m", "map": "Bind", "round": 7, "side": "defense", "won": False, "agent": "Sova"}}]
    qs = quiz.write_quiz(LLM(), picked)
    assert qs[0]["t_ms"] == 41234 and qs[0]["round"] == 7


def test_comp_sheet_advisor_and_add_to_pool(app):  # noqa: F811 (fixture)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    sr = app.extensions["nexus"]["stats"]
    pid = add_profile(c)
    uid = store.user_by_name("manuel").id
    tid = store.create_team(uid, "Squad")
    store.update_team(tid, members=[{"pid": pid, "kind": "starter", "user_id": uid}], maps=["Testmap"])
    compsheet.save(sr.team_dir(tid), {"pools": {}, "ideal": {"testmap": ["Jett", "Sova", "Omen", "Killjoy", "Viper"]}, "follow": False})
    page = c.get(f"/teams/{tid}/sheet").data.decode()
    assert 'id="advisor"' in page and "Who should learn what" in page and "Viper" in page.split('id="advisor"')[1]
    forms = re.findall(r'sheet/pool/%d/add"><input type="hidden" name="agent" value="(\w+)"' % pid, page)
    assert forms
    r = c.post(f"/teams/{tid}/sheet/pool/{pid}/add", data={"agent": forms[0]})
    assert r.status_code == 302 and r.headers["Location"].endswith("#advisor")
    assert forms[0] in compsheet.load(sr.team_dir(tid))["pools"][str(pid)]["order"]
    assert c.post(f"/teams/{tid}/sheet/pool/{pid}/add", data={"agent": "Nobody"}).status_code == 400
    assert c.post(f"/teams/{tid}/sheet/pool/999/add", data={"agent": "Viper"}).status_code == 404
    other = make_user(app, c, "outsider")
    assert other.post(f"/teams/{tid}/sheet/pool/{pid}/add", data={"agent": "Viper"}).status_code == 404
