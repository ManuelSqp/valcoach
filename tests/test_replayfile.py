"""Replay files (4.9): lining a replay up with the match data, paths for all players, the switch back to the VOD
minimap, and map rules for team comps."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from nexus import pipeline, replayfile  # noqa: E402
from nexus.config import Config, PathsCfg, PlayerCfg, ReplayCfg  # noqa: E402
from nexus.maps import MapRegistry  # noqa: E402
from nexus.parse import parse_match  # noqa: E402
from nexus.stats import roles  # noqa: E402
from nexus.stats.comp import Pool, best_comp, team_plan, top_comps  # noqa: E402
from nexus.stats.comprules import DEFAULT_RULES, for_map, for_team, load_rules, parse_rules  # noqa: E402

BUY_MS = 30000
GAP_MS = 120000


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return synth.write_all(tmp_path_factory.mktemp("synth_rep"), with_vod=False, n_rounds=6)


@pytest.fixture(scope="module")
def match(data):
    return parse_match(json.loads(Path(data["match"]).read_text()))


@pytest.fixture(scope="module")
def map_info(data, match):
    return MapRegistry(data["cache"]).get(match.map_id)


def fake_replay(match, skip_round: int | None = None, shift_ms: int = 0) -> dict:
    """What replayfile.extract would make of this match's replay: rounds start every GAP_MS, the round's time 0
    comes BUY_MS later; positions from synth.player_pos at 4 per second; every kill is a death."""
    rounds, deaths, pos = [], [], {}
    for r in match.rounds:
        start = 5000 + r.index * GAP_MS
        rounds.append([r.index, start])
        zero = start + BUY_MS + shift_ms
        died = {}
        for k in r.kills:
            died.setdefault(k.victim, k.t_round_ms)
            if r.index != skip_round:
                deaths.append([zero + k.t_round_ms, k.killer, k.victim])
        for p in match.players:
            end = died.get(p, 95000)
            for t in range(0, end, 250):
                x, y = synth.player_pos(p, r.index, t / 1000, synth.attackers_for(r.index), synth.target_site(r.index))
                pos.setdefault(p, []).append([zero + t, round(x, 1), round(y, 1), 0.0, 0.0])
    return {"format": replayfile.FORMAT, "match_id": match.match_id.lower(), "build": "test",
            "duration_ms": 5000 + len(match.rounds) * GAP_MS, "map_url": "", "players": {p: {} for p in match.players},
            "rounds": rounds, "deaths": sorted(deaths), "spike": [], "pos": pos}


def test_align_finds_every_round(match):
    rep = fake_replay(match)
    offsets, q = replayfile.align(rep, match)
    assert q["share"] == 1.0 and q["max_error_ms"] == 0
    for r in match.rounds:
        assert offsets[r.index] == 5000 + r.index * GAP_MS + BUY_MS


def test_round_without_kills_takes_the_others_offset(match):
    rep = fake_replay(match, skip_round=2)          # the replay lost round 3's deaths
    offsets, q = replayfile.align(rep, match)
    assert q["matched"] == q["kills"] - len(match.rounds[2].kills)
    assert offsets[2] == 5000 + 2 * GAP_MS + BUY_MS      # from its round start + the usual lead


def test_paths_end_at_death_and_cover_all_players(match, map_info):
    rep = fake_replay(match)
    offsets, _ = replayfile.align(rep, match)
    paths = replayfile.round_paths(rep, match, offsets)
    assert set(paths) == {r.index for r in match.rounds}
    r = match.rounds[1]
    assert set(paths[1]) == set(match.players)
    for k in r.kills:
        if k.victim in paths[1]:
            assert paths[1][k.victim][-1][0] <= k.t_round_ms / 1000 + 0.01
    # the positions are the real ones (same world units as the API)
    p = next(iter(match.players))
    t, x, y = paths[1][p][10]
    ex, ey = synth.player_pos(p, 1, t, synth.attackers_for(1), synth.target_site(1))
    assert abs(x - ex) < 60 and abs(y - ey) < 60


def test_for_match_fills_what_the_coach_reads(tmp_path, match, map_info):
    rdir = tmp_path / "replays"
    replayfile._write(replayfile.data_file(rdir, match.match_id), fake_replay(match))
    focus = match.find_player("adv1ce", "LFT").puuid
    logs = []
    out = replayfile.for_match(rdir, tmp_path / "work", "vrfkit", match, focus, map_info, logs.append)
    assert out is not None and "kills lined up" in logs[-1]
    others = out["others"][0]
    team = match.team_of(focus)
    assert set(others["allies"]) == {p for p in match.players if match.team_of(p) == team and p != focus}
    assert set(others["players"]) == {p for p in match.players if match.team_of(p) != team}
    d = out["minimap"][0]
    assert d["source"] == "replay file" and d["timeline"] and d["your_path"]
    assert any("enemies" in e for e in d["timeline"])


def test_replay_that_doesnt_fit_is_not_used(tmp_path, match, map_info):
    rdir = tmp_path / "replays"
    rep = fake_replay(match)
    rep["deaths"] = [[t, k, "someone-else"] for t, k, _ in rep["deaths"]]
    replayfile._write(replayfile.data_file(rdir, match.match_id), rep)
    focus = match.find_player("adv1ce", "LFT").puuid
    logs = []
    assert replayfile.for_match(rdir, tmp_path, "vrfkit", match, focus, map_info, logs.append) is None
    assert "doesn't fit" in logs[-1]


def _cfg(tmp_path, data, source: str) -> Config:
    return Config(player=PlayerCfg(name="adv1ce", tag="LFT"),
                  paths=PathsCfg(cache_dir=str(data["cache"]), output_dir=str(tmp_path / "out")),
                  replay=ReplayCfg(source=source, dir=str(tmp_path / "replays")), root=tmp_path)


@pytest.mark.parametrize("source", ["replay", "vod"])
def test_switch_between_replay_file_and_vod(tmp_path, data, match, source):
    cfg = _cfg(tmp_path, data, source)
    replayfile._write(replayfile.data_file(pipeline.replays_dir(cfg), match.match_id), fake_replay(match))
    logs = []
    res = pipeline.run(cfg, pipeline.CoachRequest(match=str(data["match"]), no_llm=True), logs.append)
    rep = json.loads(res.json.read_text())
    if source == "replay":
        assert rep["meta"]["positions"] == "replay"
        assert rep["rounds"][0]["minimap"]["source"] == "replay file"
        assert "replay_positions" in rep["rounds"][0]["llm_input"]
        rp = rep["rounds"][0]["replay"]
        assert rp["source"] == "replay file" and len(rp["measured"]) == len(match.players) - 1
        assert "positions from the replay file" in res.html.read_text()
    else:                                  # as before 4.9: the replay file is ignored completely
        assert rep["meta"]["positions"] is None
        assert rep["rounds"][0]["minimap"] is None
        assert rep["rounds"][0]["replay"]["source"] == ""
        assert any("switched off" in line for line in logs)


def test_no_replay_file_falls_back(tmp_path, data, match):
    cfg = _cfg(tmp_path, data, "replay")
    logs = []
    res = pipeline.run(cfg, pipeline.CoachRequest(match=str(data["match"]), no_llm=True), logs.append)
    assert json.loads(res.json.read_text())["meta"]["positions"] is None
    assert any("No replay file" in line for line in logs)


def test_stored_and_match_id_from_name(tmp_path):
    rdir = tmp_path / "r"
    rdir.mkdir()
    (rdir / "12b3659c-735e-432a-8f55-91425f8934df.vrf").write_bytes(b"x")
    (rdir / "notes.txt").write_text("x")
    assert replayfile.stored(rdir) == ["12b3659c-735e-432a-8f55-91425f8934df"]
    assert replayfile._match_id({"friendly_name": "nope"}, "12B3659C-735E-432A-8F55-91425F8934DF.vrf") == \
        "12b3659c-735e-432a-8f55-91425f8934df"
    assert replayfile.check_vrfkit(str(tmp_path / "missing")) is not None


# a real replay file, read by the real vrfkit: set NEXUS_TEST_VRF to a .vrf (and have vrfkit on the PATH or in
# NEXUS_VRFKIT); public ones are in michel-giehl/ValorantReplayParser, tests/Test.Integration/Replays
@pytest.mark.skipif(not os.environ.get("NEXUS_TEST_VRF"), reason="set NEXUS_TEST_VRF to a replay file")
def test_real_replay_file(tmp_path):
    vrfkit = replayfile.vrfkit_path()
    assert replayfile.check_vrfkit(vrfkit) is None
    src = tmp_path / "in.vrf"
    shutil.copy(os.environ["NEXUS_TEST_VRF"], src)
    info = replayfile.ingest(src, tmp_path / "replays", tmp_path / "work", vrfkit)
    assert replayfile.UUID_RE.fullmatch(info["match_id"]) and info["players"] >= 1 and info["rounds"] >= 1
    d = replayfile.load(tmp_path / "replays", info["match_id"])
    pts = next(iter(d["pos"].values()))
    assert len({t // replayfile.SAMPLE_MS for t, *_ in pts}) == len(pts)          # one position per 250 ms
    assert (tmp_path / "replays" / f"{info['match_id']}.vrf").is_file() and not src.exists()
    assert not list((tmp_path / "work").iterdir())          # the export was cleaned up


# ---------------------------------------------------------------------------
# map rules for team comps
# ---------------------------------------------------------------------------
def _rows(agent_map_results):
    return [{"match_id": f"x{i}", "agent": a, "map": m, "won": w, "acs": acs, "rounds": 20, "kills": 15, "deaths": 14,
             "assists": 3, "queue": "premier", "source": "stored"} for i, (a, m, w, acs) in enumerate(agent_map_results)]


def _breeze_pools():
    """The controller player's numbers are a bit better on Omen, but Breeze needs a Viper wall."""
    return [
        Pool.from_rows("ctrl", _rows([("Omen", "Breeze", 1, 215)] * 5 + [("Omen", "Breeze", 0, 200)] * 3
                                     + [("Viper", "Breeze", 1, 190)] * 3 + [("Viper", "Breeze", 0, 180)] * 2)),
        Pool.from_rows("duel", _rows([("Jett", "Breeze", 1, 260)] * 6 + [("Raze", "Breeze", 1, 240)] * 4)),
        Pool.from_rows("init", _rows([("Sova", "Breeze", 1, 210)] * 6 + [("Fade", "Breeze", 1, 205)] * 4)),
        Pool.from_rows("sent", _rows([("Cypher", "Breeze", 1, 190)] * 5 + [("Killjoy", "Breeze", 1, 195)] * 5)),
        Pool.from_rows("flex", _rows([("Skye", "Breeze", 1, 200)] * 5 + [("KAY/O", "Breeze", 1, 195)] * 4
                                     + [("Reyna", "Breeze", 1, 230)] * 2 + [("Reyna", "Breeze", 0, 210)] * 2)),
    ]


def test_built_in_rules_parse_and_bad_rules_are_refused():
    rules = parse_rules(DEFAULT_RULES.read_text())
    assert "breeze" in rules["maps"] and rules["general"]["need_roles"] == {"Controller": 1}
    with pytest.raises(ValueError):
        parse_rules("maps:\n  Ascent:\n    roles: ['1D 1I 1C']\n")
    with pytest.raises(ValueError):
        parse_rules("general:\n  need: {Healer: 1}\n")
    assert load_rules("this: [is broken")["maps"]          # broken edited rules: the built-in ones are used


def test_stats_only_is_unchanged_and_rules_add_map_knowledge():
    roles.load(None)
    stats = best_comp(_breeze_pools(), "Breeze")
    assert stats["method"] == "stats" and stats["notes"] == []
    assert {p["player"]: p["agent"] for p in stats["picks"]}["ctrl"] == "Omen"     # best numbers win
    rules = best_comp(_breeze_pools(), "Breeze", rules=for_map(load_rules(), "Breeze"))
    picks = {p["player"]: p for p in rules["picks"]}
    assert rules["method"] == "rules" and picks["ctrl"]["agent"] == "Viper"         # Breeze needs the wall
    assert any("Breeze" in w for w in picks["ctrl"]["why"])
    # a team's own role mix still wins over the map's
    from nexus.stats.comp import parse_meta
    meta = parse_meta("Breeze:\n  roles: 2D 1I 1C 1S\n")["breeze"]
    c = best_comp(_breeze_pools(), "Breeze", meta=meta, rules=for_map(load_rules(), "Breeze"))
    assert c["pattern"] == "2D 1I 1C 1S"


def test_rules_explain_what_a_comp_lacks():
    roles.load(None)
    mr = for_map(load_rules(), "Breeze")
    pts, notes, missing = mr.comp_score(["Jett", "Raze", "Reyna", "Killjoy", "Sage"])
    assert pts < 0 and "Controller" in missing
    assert any("controller" in n for n in notes) and any("duelists" in n for n in notes)
    assert any("Viper" in n for n in notes) and any("flash" in n for n in notes)
    pts2, notes2, _ = mr.comp_score(["Jett", "Sova", "Skye", "Viper", "Cypher"])
    assert pts2 > pts and notes2 == []


def test_team_plan_and_top_comps_use_rules_per_map():
    roles.load(None)
    plan = team_plan(_breeze_pools(), [], ["Breeze"], {}, {}, load_rules())
    assert {p["player"]: p["agent"] for p in plan[0]["main"]["picks"]}["ctrl"] == "Viper"
    assert team_plan(_breeze_pools(), [], ["Breeze"], {}, {})[0]["main"]["method"] == "stats"
    tops = top_comps(_breeze_pools(), "Breeze", rules=for_map(load_rules(), "Breeze"))
    assert all(c["method"] == "rules" for c in tops if c.get("ok"))

    class T:
        comp_method = "stats"
    assert for_team(T()) is None
    T.comp_method = "rules"
    assert for_team(T())["maps"]
