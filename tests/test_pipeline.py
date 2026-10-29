import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from valcoach.analysis.core import death_infos  # noqa: E402
from valcoach.coach.engine import analyse, run_coach  # noqa: E402
from valcoach.coach.ollama import parse_json  # noqa: E402
from valcoach.maps import MapRegistry  # noqa: E402
from valcoach.parse import infer_attackers, parse_match  # noqa: E402
from valcoach.report import render_report  # noqa: E402


# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def data(tmp_path_factory):
    return synth.write_all(tmp_path_factory.mktemp("synth"), with_vod=True, n_rounds=8)


@pytest.fixture(scope="session")
def match(data):
    return parse_match(json.loads(Path(data["match"]).read_text()))


@pytest.fixture(scope="session")
def map_info(data, match):
    return MapRegistry(data["cache"]).get(match.map_id)


@pytest.fixture(scope="session")
def focus(match):
    return match.find_player("adv1ce", "LFT").puuid


@pytest.fixture(scope="session")
def sync(data, match):
    from valcoach.video.sync import sync_vod
    return sync_vod(match, str(data["vod"]), synth.KF_ROI)


@pytest.fixture(scope="session")
def calibration(data, match, map_info, sync, focus):
    from valcoach.video.io import roi_px, video_info
    from valcoach.video.minimap import calibrate, collect_calibration_samples
    samples = collect_calibration_samples(match, map_info, str(data["vod"]), sync, synth.MM_ROI, focus)
    info = video_info(str(data["vod"]))
    roi = roi_px(synth.MM_ROI, info.width, info.height)
    return calibrate(samples, (roi[2], roi[3]), map_info.uuid)


# ---------------------------------------------------------------------------
def test_parse_basics(match):
    assert len(match.rounds) == 8
    assert len(match.players) == 10
    assert match.map_name == "Testmap"
    assert [r.start_match_ms for r in match.rounds] == [i * 60000 for i in range(8)]
    assert all(r.attacking_team == "Red" for r in match.rounds)


def test_sides_full_match():
    m = parse_match(synth.build_match(n_rounds=24))
    assert [r.attacking_team for r in m.rounds] == ["Red"] * 12 + ["Blue"] * 12


def test_side_inference_flips_on_evidence():
    rounds = [{"plant": {"player": {"team": "Blue"}}} for _ in range(5)] + [{} for _ in range(19)]
    att = infer_attackers(rounds, ["Red", "Blue"], 12)
    assert att[0] == "Blue" and att[12] == "Red"
    # overtime alternates, starting on original sides
    att_ot = infer_attackers([{}] * 28, ["Red", "Blue"], 12)
    assert att_ot[24:] == ["Red", "Blue", "Red", "Blue"]


def _mini_match(kills, winner="Red", result="Elimination"):
    """Two-kill round to test trades / isolation precisely."""
    def pl(pu, team):
        return {"puuid": pu, "name": pu, "tag": "x", "team": team}
    players = [{"puuid": p, "name": p, "tag": "x", "team_id": t, "agent": {"id": "a", "name": "Jett"},
                "stats": {}, "ability_casts": {}} for p, t in
               [("r1", "Red"), ("r2", "Red"), ("b1", "Blue"), ("b2", "Blue")]]
    ks = []
    for (killer, kt, victim, vt, t, vx, locs) in kills:
        ks.append({"round": 0, "time_in_round_in_ms": t, "time_in_match_in_ms": t,
                   "killer": pl(killer, kt), "victim": pl(victim, vt), "assistants": [],
                   "location": {"x": vx, "y": 0}, "weapon": {"name": "Vandal"},
                   "player_locations": [{"player": pl(p, tm), "view_radians": 0, "location": {"x": x, "y": 0}}
                                        for p, tm, x in locs]})
    return parse_match({"data": {
        "metadata": {"match_id": "mini", "map": {"id": "", "name": "x"}, "queue": {"id": "premier"}},
        "players": players, "teams": [{"team_id": "Red", "rounds": {"won": 1}}, {"team_id": "Blue", "rounds": {"won": 0}}],
        "rounds": [{"id": 0, "winning_team": winner, "result": result, "stats": []}],
        "kills": ks}})


def test_trade_and_isolation():
    m = _mini_match([
        # b1 kills r1 at x=0; r2 is 3000 units away (isolated)
        ("b1", "Blue", "r1", "Red", 10_000, 0, [("r2", "Red", 3000), ("b1", "Blue", 500), ("b2", "Blue", 900)]),
        # r2 kills b1 4 s later -> trade
        ("r2", "Red", "b1", "Blue", 14_000, 500, [("r2", "Red", 2000), ("b2", "Blue", 900)]),
    ])
    d = death_infos(m, m.rounds[0])
    assert d[0].traded and d[0].traded_by == "r2" and d[0].trade_time_ms == 4000
    assert d[0].isolated and d[0].first_death
    assert d[1].isolated is True or d[1].nearest_teammate_units == pytest.approx(400)


def test_analysis_runs(match, map_info, focus):
    an = analyse(match, focus, map_info)
    assert len(an.team_facts) == len(an.player_facts) == 8
    assert an.team_stats.rounds_won + an.team_stats.rounds_lost == 8
    assert sum(f.kills for f in an.player_facts) == match.players[focus].kills
    assert any(f.plant_site for f in an.team_facts)
    assert all(not f.path or "Spawn" in f.path[0] or "Main" in f.path[0] or "Mid" in f.path[0]
               or "Site" in f.path[0] for f in an.player_facts)


def test_sync_recovers_offset(sync):
    assert sync.global_offset_s == pytest.approx(synth.TRUE_OFFSET_S, abs=0.3)
    assert sync.confidence > 0.85
    for off in sync.per_round_offset_s.values():
        assert off == pytest.approx(synth.TRUE_OFFSET_S, abs=0.3)


def test_sync_anchor(data, match):
    from valcoach.video.sync import sync_from_anchor
    k = match.rounds[2].kills[0]
    res = sync_from_anchor(match, str(data["vod"]), 3, 1, k.t_match_ms / 1000 + synth.TRUE_OFFSET_S)
    assert res.global_offset_s == pytest.approx(synth.TRUE_OFFSET_S, abs=0.01)


def test_minimap_calibration(calibration, data):
    gt = data["gt"]
    assert calibration.rot_k == gt["rot_k"]
    assert calibration.scale == pytest.approx(gt["scale"], rel=0.02)
    assert calibration.tx == pytest.approx(gt["tx"], abs=3)
    assert calibration.ty == pytest.approx(gt["ty"], abs=3)
    assert calibration.rms_px < 3


def test_minimap_self_tracking(data, match, map_info, calibration, sync):
    from valcoach.video.minimap import describe_track, track_round
    r = 3
    tr = track_round(match, r, map_info, calibration, str(data["vod"]), sync, synth.MM_ROI)
    selfs = [p for p in tr.points if p.kind == "self"]
    assert len(selfs) > 20
    errs = []
    for p in selfs:
        tx, ty = synth.player_pos("red-1", r, p.t_round_s, synth.attackers_for(r), synth.target_site(r))
        errs.append(math.hypot(p.x - tx, p.y - ty))
    errs.sort()
    assert errs[len(errs) // 2] < 400          # median error < 4 m
    d = describe_track(tr)
    assert d["timeline"] and d["your_path"]


def test_teammate_tracking(data, match, map_info, calibration, sync, focus):
    from valcoach.video.allies import ally_paths, coverage, enemy_sightings
    from valcoach.video.minimap import track_round
    errs, covs = [], []
    for r in (1, 3, 5):
        tr = track_round(match, r, map_info, calibration, str(data["vod"]), sync, synth.MM_ROI)
        paths = ally_paths(match, r, tr, focus)
        assert focus not in paths and paths
        assert all(match.team_of(p) == match.team_of(focus) for p in paths)
        covs.append(coverage(paths, match, r, focus))
        for p, pts in paths.items():
            for t, x, y in pts:
                tx, ty = synth.player_pos(p, r, t, synth.attackers_for(r), synth.target_site(r))
                errs.append(math.hypot(x - tx, y - ty))
        assert enemy_sightings(tr)                       # enemies flicker in and out on the synthetic minimap
    errs.sort()
    assert sum(covs) / len(covs) > 0.8                    # measured most of the time
    assert errs[len(errs) // 2] < 400                     # median < 4 m
    assert sum(e > 800 for e in errs) / len(errs) < 0.02  # < 2 % assigned to the wrong player


def test_estimates_hold_then_move():
    from valcoach.coach.replay import ESTIMATE, KNOWN, SPAWN, _track
    speed = 0.01 / 1000                                   # 0.01 map widths per second
    # known at 0 s and at 20 s, 0.05 apart: the walk takes 5 s, so they hold until 15 s
    pts = _track([(10_000, [0.2, 0.5], KNOWN), (30_000, [0.25, 0.5], KNOWN)], None, speed)
    hold = [q for q in pts if q[3] == ESTIMATE]
    assert hold and hold[0][0] == 25_000 and hold[0][1:3] == [0.2, 0.5]
    # from spawn they move first and then wait at the destination
    pts = _track([(0, [0.2, 0.5], SPAWN), (20_000, [0.25, 0.5], KNOWN)], None, speed)
    assert [q[0] for q in pts] == [0, 5_000, 20_000] and pts[1][1:3] == [0.25, 0.5]
    # without a speed the old behaviour: straight line over the whole gap
    pts = _track([(0, [0.2, 0.5], KNOWN), (20_000, [0.25, 0.5], KNOWN)], None)
    assert [q[0] for q in pts] == [0, 20_000]


def test_replay_uses_measured_teammates(match, map_info, focus):
    from valcoach.coach.replay import build_replay
    an = analyse(match, focus, map_info)
    rnd = match.rounds[2]
    mate = next(p.puuid for p in match.players.values() if p.team == match.team_of(focus) and p.puuid != focus)
    others = {"allies": {mate: [(t / 2, -2000.0, 100.0 * t) for t in range(1, 20)]},
              "enemies": [(5.0, -3000.0, 0.0)]}
    rp = build_replay(match, rnd, focus, map_info, an.view, None, None, others)
    short = next(k for k, v in rp["roster"].items() if v["name"] == match.players[mate].name)
    assert rp["measured"] == [short] and rp["seen"][0][0] == 5000
    assert sum(q[3] == 1 for q in rp["tracks"][short]["pts"]) >= 15


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.calls = []

    def chat_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        if "practice_plan" in schema["properties"]:
            return {"headline": "h", "strengths": ["s"],
                    "practice_plan": [{"drill": "Pre-aim A Link corners", "where": "Custom game", "minutes": 10,
                                       "fixes": "0-damage deaths"}],
                    "team_issues": [{"issue": "i", "evidence": "e", "fix": "f"}], "igl_notes": ["n"],
                    "player_issues": [{"issue": "i", "evidence": "e", "fix": "f"}]}
        out = {"summary": "sum", "key_moment": {"time": "0:30", "what": "w"}, "importance": 2,
               "team": {"went_well": ["a"], "mistakes": ["b"], "better_option": "c"},
               "player": {"went_well": ["a"], "mistakes": ["b"], "better_option": "c"}}
        if "better_position" in schema["properties"]:
            enum = schema["properties"]["better_position"]["properties"]["callout"]["enum"]
            out["better_position"] = {"time": "0:30", "callout": enum[1], "why": "hold from cover"}
        return out


def test_engine_and_report(tmp_path, match, map_info, focus, sync):
    an = analyse(match, focus, map_info)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "m.yaml").write_text(f"match_id: {match.match_id}\nrounds:\n  2: 'my own note'\n")
    (notes / "other.yaml").write_text("match_id: other\nrounds:\n  1: 'style example note'\n")
    pb = tmp_path / "pb.yaml"
    pb.write_text("principles: ['trade every entry']\nmaps:\n  Testmap:\n    defense: {setup: '2-1-2'}\n  Bind: {}\n")
    llm = FakeLLM()
    rep = run_coach(an, llm, mode="both", playbook_path=pb, notes_dir=notes, parallel=3, sync=sync)
    assert len(llm.calls) == 9
    sys_prompt = llm.calls[0][0]
    assert "trade every entry" in sys_prompt and "2-1-2" in sys_prompt and "Bind" not in sys_prompt
    assert "style example note" in sys_prompt
    assert any("my own note" in c[1] for c in llm.calls)
    assert rep.rounds[0]["vod"]["start"] == pytest.approx(synth.TRUE_OFFSET_S, abs=0.3)
    jp = tmp_path / "r.json"
    rep.save(jp)
    out = render_report(json.loads(jp.read_text()), tmp_path / "r.html", None)
    html = out.read_text()
    assert 'id="r8"' in html and "Match review" in html


def test_parse_json_tolerant():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_cli_end_to_end(tmp_path, data):
    from valcoach.cli import main
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"""
[player]
name = "adv1ce"
tag = "LFT"
[paths]
cache_dir = "{data['cache']}"
output_dir = "{tmp_path / 'out'}"
[video]
minimap_roi = {synth.MM_ROI}
killfeed_roi = {synth.KF_ROI}
sample_fps = 2
""")
    main(["--config", str(cfg), "coach", str(data["match"]), "--vod", str(data["vod"]), "--no-llm"])
    htmls = list((tmp_path / "out").glob("*.html"))
    assert len(htmls) == 1
    html = htmls[0].read_text()
    assert "<video" in html and "Round 1" in html
    rep = json.loads(htmls[0].with_suffix(".json").read_text())
    assert rep["rounds"][3]["minimap"]["your_path"]
    # calibration cached for reuse
    assert list((Path(data["cache"]) / "minimap_calib").glob("*.json"))
    main(["--config", str(cfg), "notes-template", str(data["match"])])


def test_ollama_think_flag_and_errors(monkeypatch):
    import requests as rq
    from valcoach.coach.ollama import Ollama, OllamaError
    sent = []

    class R:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, json.dumps(body)

        def json(self):
            return self._b

    def post(url, json=None, timeout=None):
        sent.append(json)
        if json["model"] == "nothink":
            return R(400, {"error": "model does not support thinking"})
        return R(200, {"message": {"content": '<think>hmm {x}</think>{"ok": 1}'}})

    monkeypatch.setattr(rq, "post", post)
    assert Ollama("http://x", "m", think="off").chat_json("s", "u", {}) == {"ok": 1}
    assert sent[-1]["think"] is False
    Ollama("http://x", "m", think="").chat_json("s", "u", {})
    assert "think" not in sent[-1]
    with pytest.raises(OllamaError, match="does not support thinking"):
        Ollama("http://x", "nothink", think="on").chat_json("s", "u", {})
    assert len(sent) == 3          # 400 is not retried


def test_ollama_check_exact_model(monkeypatch):
    import requests as rq
    from valcoach.coach.ollama import Ollama, OllamaError

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3.8:27b-mlx"}, {"name": "gemma4:latest"}]}

    monkeypatch.setattr(rq, "get", lambda *a, **k: R())
    Ollama("http://x", "gemma4").check()
    Ollama("http://x", "qwen3.8:27b-mlx").check()
    with pytest.raises(OllamaError, match="ollama pull qwen3.8:27b"):
        Ollama("http://x", "qwen3.8:27b").check()


def test_ollama_speed_stats_and_case(monkeypatch):
    import requests as rq
    from valcoach.coach.ollama import Ollama

    class G:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "orcarouter/Qwen3.8-27B-Uncensored:iq4_xs"}]}

    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"message": {"content": '{"a": 1}', "thinking": "let me think"},
                    "prompt_eval_count": 2000, "prompt_eval_duration": 4_000_000_000,
                    "eval_count": 300, "eval_duration": 20_000_000_000}

    monkeypatch.setattr(rq, "get", lambda *a, **k: G())
    monkeypatch.setattr(rq, "post", lambda *a, **k: R())
    llm = Ollama("http://x", "orcarouter/qwen3.8-27b-uncensored:IQ4_XS", think="off")
    llm.check()
    assert llm.model == "orcarouter/Qwen3.8-27B-Uncensored:iq4_xs"
    for _ in range(3):
        llm.chat_json("s", "u", {})
    st = llm.summary()
    assert st["requests"] == 3 and st["gen_tok_per_s"] == 15.0 and st["prompt_tok_per_s"] == 500.0
    assert st["thinking"] is True



def test_view_calibration_and_duels(match, map_info, focus):
    from valcoach.analysis.view import calibrate
    vm = calibrate(match)
    assert vm.ok and vm.sign == synth.VIEW_SIGN and abs(vm.offset - synth.VIEW_OFFSET) < 1e-6
    assert vm.median_error_deg < 10
    an = analyse(match, focus, map_info)
    assert an.view.ok
    ps = an.player_stats
    assert ps.view_analysis
    deaths = [f for f in an.player_facts if not f.survived]
    assert sum(ps.deaths_by_my_view.values()) == len([f for f in deaths if f.death_my_view])
    assert all(f.death_distance_m is not None for f in deaths)
    assert all(f.damage_to_killer is not None for f in deaths)
    assert sum(r["kills"] + r["deaths"] for r in ps.duels_by_range.values()) == ps.kills + len(deaths)
    # killers always face victims in the synthetic data -> victims of my kills: my angle ~0
    for f in an.player_facts:
        for d in f.kill_duels:
            assert d["range"] and d["distance_m"] is not None
    assert ps.shots_by_weapon and all("hs_pct" in w for w in ps.shots_by_weapon.values())


def test_view_off_when_data_is_noise():
    from valcoach.analysis.view import calibrate
    raw = synth.build_match(n_rounds=6, seed=3)
    import random
    rng = random.Random(1)
    for k in raw["data"]["kills"]:
        for pl in k["player_locations"]:
            pl["view_radians"] = rng.uniform(-3.14, 3.14)
    vm = calibrate(parse_match(raw))
    assert not vm.ok


def test_duel_view_without_victim_location():
    from valcoach.analysis.view import ViewModel, duel_view
    from valcoach.models import Kill, PlayerLoc
    vm = ViewModel(sign=1, offset=0.0, median_error_deg=5, samples=10)
    k = Kill(round=0, t_round_ms=1000, t_match_ms=1000, killer="a", killer_team="Red", victim="b",
             victim_team="Blue", assistants=[], weapon="Vandal", weapon_type="", victim_x=1000, victim_y=0,
             player_locations=[PlayerLoc("a", "Red", 0, 0, view=0.0)])       # victim not listed
    dv = duel_view(vm, k, "b", "a")          # from the victim's perspective
    assert dv.distance_m == 10.0 and dv.my_angle_to_other is None and dv.other_angle_to_me == 0


def test_replay_and_report(tmp_path, match, map_info, focus, sync):
    an = analyse(match, focus, map_info)
    an.self_paths = {0: [(1.0, 5000, 0), (5.0, 1000, 0), (12.0, -1500, 5000)]}
    rep = run_coach(an, FakeLLM(), mode="both", parallel=2, sync=sync)
    from valcoach.coach.replay import map_meta
    rep.map = map_meta(map_info, None)
    r0 = rep.rounds[0]["replay"]
    kinds = [e["kind"] for e in r0["events"]]
    assert kinds.count("kill") == len(match.rounds[0].kills)
    assert ("plant" in kinds) == (match.rounds[0].plant is not None)
    assert any(v["you"] for v in r0["roster"].values())
    assert all(0 <= p["p"][0] <= 1 and 0 <= p["p"][1] <= 1 for e in r0["events"] for p in e["players"])
    assert any(p["a"] is not None for e in r0["events"] for p in e["players"])
    assert len(r0["path"]) == 3 and r0["view"] is True
    jp = tmp_path / "r.json"
    rep.save(jp)
    html = render_report(json.loads(jp.read_text()), tmp_path / "r.html", None).read_text()
    assert 'id="rp-box"' in html and 'id="r1"' in html and '"callouts"' in html
    assert "Died looking at killer" in html and "Main weapon" in html
    data = html.split('id="replay-data" type="application/json">')[1].split("</script>")[0]
    parsed = json.loads(data.replace("<\\/", "</"))
    assert parsed["better"]["1"]["why"] == "hold from cover"



def test_agent_icons(tmp_path, match, monkeypatch):
    import requests as rq
    from valcoach.coach.replay import agent_icons
    from valcoach.maps import AgentRegistry

    def offline(*a, **k):
        raise rq.ConnectionError("offline")
    monkeypatch.setattr(rq, "get", offline)
    synth.write_agent_cache(tmp_path)
    icons = agent_icons(match, AgentRegistry(tmp_path))
    assert set(icons) == set(synth.AGENTS)
    assert all(v.startswith("data:image/png;base64,") for v in icons.values())
    # unknown uuid but known name still matches; missing local file falls back to the URL
    reg = AgentRegistry(tmp_path)
    assert reg.find("nope", "jett")["name"] == "Jett"
    (tmp_path / "agents" / f"{synth.agent_uuid('Omen')}.png").unlink()
    assert agent_icons(match, AgentRegistry(tmp_path))["Omen"] == "https://example.invalid/Omen.png"
    # nothing cached and offline: no icons, no crash
    assert agent_icons(match, AgentRegistry(tmp_path / "empty")) == {}



def test_nav_routes_follow_corridors(tmp_path):
    from valcoach.coach.nav import NavGrid, path_length
    img = synth.write_map_image(tmp_path)
    nav = NavGrid.from_image(img)
    assert nav is not None
    a = synth.to_uv(*synth.ZONES[("A", "Site")])
    b = synth.to_uv(*synth.ZONES[("B", "Site")])
    route = nav.route(a, b)
    assert len(route) > 2
    straight = path_length([a, b])
    assert path_length(route) > straight * 1.05            # goes around, not through the wall
    for u, v in route[1:-1]:                               # every waypoint is on the floor
        assert nav.walk[min(nav.n - 1, int(v * nav.n)), min(nav.n - 1, int(u * nav.n))]
    assert NavGrid.from_image(tmp_path / "missing.png") is None


def test_replay_tracks(tmp_path, match, map_info, focus):
    from valcoach.coach.nav import NavGrid
    from valcoach.coach.replay import build_replay
    an = analyse(match, focus, map_info)
    nav = NavGrid.from_image(synth.write_map_image(tmp_path))
    rnd = match.rounds[2]
    rp = build_replay(match, rnd, focus, map_info, an.view, None, nav)
    assert rp["routes"] and rp["end"] > max(e["t"] for e in rp["events"])
    assert set(rp["tracks"]) == set(rp["roster"])           # everybody starts in spawn at least
    victims = {e["victim"]: e["t"] for e in rp["events"] if e["kind"] == "kill"}
    for pid, tr in rp["tracks"].items():
        ts = [q[0] for q in tr["pts"]]
        assert ts == sorted(ts) and tr["pts"][0][0] == 0 and tr["pts"][0][3] == 2
        if pid in victims:
            assert tr["death"] == victims[pid] and ts[-1] == victims[pid]
    assert any(q[3] == 0 for tr in rp["tracks"].values() for q in tr["pts"])   # estimated route points
    me = next(k for k, v in rp["roster"].items() if v["you"])
    assert list(rp["roster"])[0] == me                       # you first


def test_missing_utility_is_unknown_not_zero(map_info):
    raw = synth.build_match(n_rounds=4)
    for p in raw["data"]["players"]:
        p["ability_casts"] = {"grenade": None, "ability1": None, "ability2": None, "ultimate": None}
    for r in raw["data"]["rounds"]:
        for st in r["stats"]:
            st["ability_casts"] = {"grenade": None, "ability_1": None, "ability_2": None, "ultimate": None}
    m = parse_match(raw)
    assert m.has_utility is False and match_has_utility_default()
    focus = m.find_player("adv1ce", "LFT").puuid
    an = analyse(m, focus, map_info)
    from valcoach.coach.summarize import round_summary
    txt = round_summary(an.team_facts[0], an.player_facts[0])
    assert "utility_casts" not in txt and "ult_used" not in txt and "ults_used" not in txt
    assert an.player_stats.utility_per_round is None


def match_has_utility_default():
    return parse_match(synth.build_match(n_rounds=2)).has_utility is True



def test_jobs_work_without_opencv(match, map_info, focus):
    """Coaching without a VOD must not need OpenCV (servers without libGL)."""
    import subprocess
    code = (
        "import sys, json; sys.modules['cv2'] = None\n"
        "import valcoach.coach.engine, valcoach.coach.replay, valcoach.pipeline, valcoach.report\n"
        "from valcoach.coach.nav import NavGrid\n"
        "print(NavGrid.from_image('/nope.png'))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "None"


def test_simplify_keeps_corners():
    import numpy as np
    from valcoach.coach.nav import _simplify
    pts = np.array([[0, 0], [1, 0.01], [2, 0], [3, 0], [3, 1], [3, 2], [3, 3]], dtype=float)
    out = _simplify(pts, 0.5)
    assert out.tolist() == [[0, 0], [3, 0], [3, 3]]



def test_generic_round_summaries_are_hidden():
    from valcoach.report import _useful_summary
    assert _useful_summary("Round 1 review for BurnTheGoat#NOW (Cypher).") is None
    assert _useful_summary("Round 9 Review: BurnTheGoat#NOW (Cypher)") is None
    assert _useful_summary("Round 10 Review") is None
    assert _useful_summary("") is None and _useful_summary(None) is None
    keep = "Lost the 2v3 retake on B because the team swung one by one from CT."
    assert _useful_summary(keep) == keep


def test_whole_team_review(tmp_path, match, map_info, focus):
    from valcoach.coach.teamreview import facts, review
    team = match.team_of(focus)
    f = facts(match, team, map_info)
    assert set(f["players"]) == {p.puuid for p in match.players_on(team)}
    for d in f["players"].values():
        assert d["deaths"] >= len(d["deaths_list"]) and 0 <= d["kast"] <= 1
        assert d["alone_deaths"] <= d["untraded_deaths"] <= len(d["deaths_list"])
    calls = []

    class LLM:
        def chat_json(self, system, user, schema):
            calls.append(system)
            return {"summary": "s", "went_well": [{"point": "good trade", "rounds": [2]}],
                    "fix": [{"issue": "died alone", "rounds": [3, 5], "try": "play with Sova"}],
                    "teammates_can_help": "join him on B"}
    me = match.players[focus]
    out = review(match, team, map_info, LLM(), roles={f"{me.name}#{me.tag}".lower(): ["Anchor"]}, parallel=2)
    assert len(out["players"]) == 5 and len(calls) == 5
    mine = next(p for p in out["players"] if p["puuid"] == focus)
    assert mine["roles"] == ["Anchor"] and any("Anchor" in c for c in calls)
    # the report shows the section with round links
    an = analyse(match, focus, map_info)
    rep = run_coach(an, FakeLLM(), mode="both")
    rep.team_review = out
    rep.save(tmp_path / "r.json")
    html = render_report(json.loads((tmp_path / "r.json").read_text()), tmp_path / "r.html").read_text()
    assert 'id="team"' in html and "How the team can help" in html and 'onclick="openRound(3)' in html
    assert "Together" in html and "Who traded whom" in html or "No trades between teammates" in html


def test_team_review_trades_are_consistent(match, map_info, focus):
    from valcoach.coach.teamreview import facts
    f = facts(match, match.team_of(focus), map_info)
    by_name = {d["name"]: d for d in f["players"].values()}
    for name, d in by_name.items():
        assert d["trades"] == sum(t["times"] for t in f["trade_pairs"] if t["traded_by"] == name)


# ---------------------------------------------------------------------------
# review fixes (see CHANGES.md)
def test_live_api_utility_shape():
    """Live API: match totals filled, every per-round cast null. Rounds must not claim "no utility"."""
    from valcoach.coach.summarize import match_stats_block, round_summary
    raw = synth.build_match(n_rounds=4)
    for r in raw["data"]["rounds"]:
        for st in r["stats"]:
            st["ability_casts"] = {"grenade": None, "ability_1": None, "ability_2": None, "ultimate": None}
    m = parse_match(raw)
    assert m.has_utility is False
    me = m.find_player("adv1ce", "LFT").puuid
    an = analyse(m, me, None)
    txt = round_summary(an.team_facts[0], an.player_facts[0])
    assert "utility_casts" not in txt and "ult_used" not in txt
    # match totals (grenade 3 + ability1 5 + ability2 4 over 4 rounds) are still used
    assert an.player_stats.utility_per_round == 3.0 and an.player_stats.ults_used == 1
    assert "utility_per_round: 3.0" in match_stats_block(None, an.player_stats)


def test_non_round_modes_are_not_coachable():
    from valcoach.pipeline import coachable
    assert coachable(parse_match(synth.build_match(n_rounds=4))) is None
    for mode_type in ("Deathmatch", "Team Deathmatch", "Gauntlet: Glitched"):
        raw = synth.build_match(n_rounds=4)
        raw["data"]["metadata"]["queue"]["mode_type"] = mode_type
        assert "can't be coached" in coachable(parse_match(raw))
    one_round = synth.build_match(n_rounds=1)
    one_round["data"]["metadata"]["queue"]["mode_type"] = ""
    assert coachable(parse_match(one_round)) is not None


def test_time_out_detected_without_result_text():
    from valcoach.analysis.team import analyse_team_round
    # Red attacks round 1, loses with 1 player left, no plant, API result empty -> time ran out
    m = _mini_match([("b1", "Blue", "r1", "Red", 10_000, 0, [])], winner="Blue", result="")
    att = analyse_team_round(m, m.rounds[0], "Red", None)
    dfn = analyse_team_round(m, m.rounds[0], "Blue", None)
    assert att.result == "Time expired" and "failed to plant before time ran out" in att.notable
    assert "held until time ran out (no plant)" in dfn.notable
    # attackers all dead = elimination even without result text
    m = _mini_match([("b1", "Blue", "r1", "Red", 10_000, 0, []), ("b1", "Blue", "r2", "Red", 12_000, 0, [])],
                    winner="Blue", result="")
    assert analyse_team_round(m, m.rounds[0], "Red", None).result == ""


def test_match_ids_and_broken_notes(tmp_path):
    from valcoach.config import CoachCfg, Config, PathsCfg
    from valcoach.pipeline import load_match, read_notes
    cfg = Config(coach=CoachCfg(notes_dir=str(tmp_path)), paths=PathsCfg(cache_dir=str(tmp_path)), root=tmp_path)
    for bad in ("..", "../../etc/passwd", "a b", "x" * 65):
        with pytest.raises(ValueError):
            load_match(cfg, bad)
    (tmp_path / "m1.yaml").write_text("rounds: {1: ok, two: bad, 3: ''}\n")
    assert read_notes(cfg, "m1") == {1: "ok"}
    (tmp_path / "m2.yaml").write_text("- just\n- a list\n")
    assert read_notes(cfg, "m2") == {}
    (tmp_path / "m3.yaml").write_text("rounds: [unclosed\n")
    assert read_notes(cfg, "m3") == {}


def test_prompts_show_field_rules_to_the_model():
    """Ollama only enforces the schema; the field descriptions must be in the prompt text."""
    from valcoach.coach import prompts
    from valcoach.coach.engine import clean_feedback
    s = prompts.round_schema("both", ["A Main"], has_vod=False)
    guide = prompts.field_guide(s)
    assert "player.better_option:" in guide and "Never 'None' or 'N/A'" in guide
    assert "summary:" in guide and "check_in_vod" not in guide
    assert "check_in_vod" in prompts.round_schema("player", None, has_vod=True)["properties"]
    assert "never tell the user to check a VOD" in prompts.EVIDENCE_NO_VOD
    assert "headline:" in prompts.field_guide(prompts.match_schema("team"))
    fb = clean_feedback({"summary": "x", "check_in_vod": "", "player": {"better_option": "N/A"},
                         "team": {"better_option": "None. The round went fine."}})
    assert "better_option" not in fb["player"] and "better_option" not in fb["team"] and "check_in_vod" not in fb
    keep = clean_feedback({"player": {"better_option": "Hold B Main with the team instead of peeking alone."}})
    assert keep["player"]["better_option"].startswith("Hold")


def test_new_llm_features_send_their_field_rules(monkeypatch):
    """Weekly focus, map tips, game plans and the team review also tell the model what each field means."""
    from valcoach.coach.prompts import field_guide
    from valcoach.stats import gameplans, tips, weekly
    for sch in (weekly.schema(), tips.schema()):
        assert field_guide(sch).count("\n- ") >= 2
    seen = []

    class FakeLLM:
        model = "fake"

        def chat_json(self, system, user, schema):
            seen.append(system)
            return {}
    weekly.write_focus(FakeLLM(), {"player": "x"})
    assert "Output fields:" in seen[-1] and "focus:" in seen[-1]
