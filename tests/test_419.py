"""4.19: counter-plans from replay scouting, goals from "You vs your rank"."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_418 import _row  # noqa: E402
from test_replayfile import fake_replay  # noqa: E402
from test_web import _FakeModel, _premier_team, _wait_stats, app, setup_admin, synthetic  # noqa: E402,F401

from nexus import replayfile  # noqa: E402
from nexus.stats import gameplans, goals, peers, progress, replayprep  # noqa: E402


def test_goals_from_your_rank():
    rows = [_row(fk=1, fd=4, adr=120.0, peers_=[[13, 200.0, 0.7, 0.72, 0.25, 135.0, 0.2, 0.7, 2, 2]] * 5
                 + [[15, 300.0, 1.0, 0.5, 0.3, 190.0, 0.3, 0.8, 3, 1]] * 5) for _ in range(6)]
    a = peers.analyse(rows)
    m = {x["key"]: x for x in a["metrics"]}
    assert m["adr"]["goal"] == {"metric": "adr", "target": "135", "level": "rank", "text": "Damage per round like your rank"}
    assert m["owr"]["goal"]["metric"] == "first_duels" and m["owr"]["goal"]["target"] == "50 %"
    assert m["acs"]["goal"]["level"] == "next" and m["acs"]["goal"]["target"] == "300"     # ahead of your rank already
    assert m["opr"]["goal"] is None                                                          # depends on the role
    # the goal metrics exist and read the same numbers
    assert progress.value(rows, "kpr") == 18 / 20 and progress.value(rows, "dpr") == 12 / 20
    assert goals.parse_target("first_duels", "50 %") == 0.5 and goals.parse_target("dpr", "0.62") == 0.62
    assert not goals.higher_is_better("dpr")
    assert "kpr" not in progress.ORDER                                                         # not on the Progress page


def test_counter_plan_prompt_and_facts():
    d = {"matches": 2, "defense": {"rounds": 10, "won": 4, "with_pos": 10, "setups": [["A 2 · B 2 · Mid 1", 7]],
                                   "spots": [{"zone": "B", "area": "B Site", "share": 0.9, "agents": ["Killjoy"]}],
                                   "util": [{"type": "smoke", "area": "B Main", "n": 6, "t": 22.0, "agents": ["Omen"]}],
                                   "plants": []}}
    f = replayprep.facts(d, "Their Team")
    assert f["team"] == "Their Team" and "when_they_attack" not in f
    w = f["when_they_defense"]
    assert w["setup_20s"] == ["A 2 · B 2 · Mid 1 in 7 of 10 rounds"] and "B Site (B) in 90% of rounds by Killjoy" in w["spots_taken"]
    assert w["utility"] == ["smoke at B Main in 6 of 10 rounds, around 22 s (Omen)"]

    class LLM:
        model = "m"

        def chat_json(self, system, user, schema):
            self.system, self.user = system, user
            return {"plans": []}
    llm = LLM()
    out = gameplans.write_plans(llm, "Ascent", {}, [{"player": "a", "agent": "Jett"}], ["A Site"], [], [], opponent={"name": "Their Team", "habits": f})
    assert out["_opponent"] == "Their Team" and "against Their Team" in llm.system and "opponent_habits" in llm.user
    out = gameplans.write_plans(llm, "Ascent", {}, [{"player": "a", "agent": "Jett"}], ["A Site"], [], [])
    assert "_opponent" not in out and "opponent_habits" not in llm.user and "against" not in llm.system


def test_web_counter_plans_and_rank_goals(app, monkeypatch):  # noqa: F811 (fixture)
    import nexus.coach.ollama as oll
    seen = []

    class Model(_FakeModel):
        def chat_json(self, system, user, schema):
            seen.append((system, user))
            return super().chat_json(system, user, schema)
    monkeypatch.setattr(oll, "Ollama", Model)
    c = setup_admin(app)
    store = app.extensions["nexus"]["store"]
    sr = app.extensions["nexus"]["stats"]
    tid = _premier_team(app, c, monkeypatch)
    names = {store.profile(m["pid"]).name: m["pid"] for m in store.team(tid).member_list}
    me = names["adv1ce"]

    # goals from "You vs your rank": a button for numbers behind, back to the stats page, then "goal set"
    page = c.get(f"/profiles/{me}/stats").data.decode()
    forms = re.findall(r'name="metric" value="(\w+)"><input type="hidden" name="target" value="([^"]+)"', page)
    assert forms and "＋ Goal" in page
    metric, target = forms[0]
    r = c.post(f"/profiles/{me}/goals", data={"metric": metric, "target": target, "text": "x", "from": "peers"})
    assert r.status_code == 302 and r.headers["Location"].endswith("#peers")
    g = [x for x in sr.goals(me).load() if x["metric"] == metric][0]
    assert g["source"] == "your rank" and g["state"] == "open"
    assert "goal set" in c.get(f"/profiles/{me}/stats").data.decode()

    # counter-plans: replay files of the team's matches, then "Write counter-plans" on the scouting page
    from nexus.parse import parse_match
    rdir = store.data_dir / "replays"
    for f in sorted((store.data_dir / "cache" / "matches").glob("*.json"))[:8]:
        m = parse_match(json.loads(f.read_text()))
        if m.rounds:
            replayfile._write(replayfile.data_file(rdir, m.match_id), fake_replay(m))
    page = c.get(f"/teams/{tid}/replay-scouting").data.decode()
    assert "Write counter-plans for" in page
    who = re.search(r'name="who" value="(\w+)"', page.split('class="counter"')[1]).group(1)
    mp = re.search(r'name="map" value="([^"]+)"', page.split('class="counter"')[1]).group(1)
    assert c.post(f"/teams/{tid}/replay-scouting/counter", data={"who": "nope", "map": mp}).status_code == 302
    assert not sr.status(f"plans:{tid}")                     # nothing started
    r = c.post(f"/teams/{tid}/replay-scouting/counter", data={"who": who, "map": mp})
    assert r.status_code == 302 and f"map={mp}" in r.headers["Location"]
    assert _wait_stats(app, f"plans:{tid}")["status"] == "done"
    system, user = seen[-1]
    assert "Their habits from replay files" in system and "opponent_habits" in user and "when_they_" in user
    plans = sr.read_plans(tid, mp)
    assert plans["_opponent"] and len(plans["plans"]) == 3
    pp = c.get(f"/teams/{tid}/plans?map={mp}").data.decode()
    assert "Counter-plans against" in pp and "Plan 0" in pp
    # "us" has no counter-plan button
    assert "Write counter-plans" not in c.get(f"/teams/{tid}/replay-scouting?who=us").data.decode()
