import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
import synth_history as sh  # noqa: E402

from nexus.stats import roles  # noqa: E402
from nexus.stats.aggregate import (by_agent, by_map, filter_rows, local_meta, map_detail,  # noqa: E402
                                      pattern, summary)
from nexus.stats.comp import Pool, best_comp, parse_meta, pick_helper, team_plan  # noqa: E402
from nexus.stats.games import ROW_VERSION, GameStore, import_games  # noqa: E402


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    c = tmp_path_factory.mktemp("cache")
    (c / "valorant_api_maps.json").write_text(json.dumps(synth.maps_payload()))
    synth.write_agent_cache(c)
    return c


@pytest.fixture(scope="module")
def history():
    return sh.build_history(40)


@pytest.fixture(scope="module")
def imported(tmp_path_factory, cache, history):
    gs = GameStore(tmp_path_factory.mktemp("p") / "games.json")
    client = sh.FakeHenrik(history, full_depth=8)
    res = import_games(client, "eu", "pc", "adv1ce", "LFT", gs, cache)
    return gs, client, res


def test_import_full_and_archive(imported, history):
    gs, client, res = imported
    rows = gs.rows()
    assert res["total"] == len(history) == len(rows)            # adv1ce played all 40
    full = [r for r in rows if r["source"] == "full"]
    assert len(full) == 16                                      # 8 newest per queue have round data
    r = full[0]
    assert r["openings"] or r["deaths_at"]
    assert sum(r["sides"][s][0] for s in r["sides"]) == r["rounds"]
    assert len(r["own_agents"]) == 5 and r["role"] == roles.role_of(r["agent"])
    stored = next(x for x in rows if x["source"] == "stored")
    assert stored["acs"] > 0 and stored["map"] in sh.MAPS
    assert rows == sorted(rows, key=lambda x: x["started_at"], reverse=True)


def test_import_is_incremental(imported, cache):
    gs, client, _ = imported
    before = dict(client.calls)
    res = import_games(client, "eu", "pc", "adv1ce", "LFT", gs, cache)
    assert res["full"] == 0 and res["stored"] == 0
    assert client.calls["history"] - before["history"] <= 3        # one page per queue, nothing new: stop
    assert client.calls["stored"] - before["stored"] <= 6


def test_queue_filters():
    rows = [{"queue": q} for q in ("competitive", "premier", "unrated", "swiftplay", "deathmatch")]
    assert [r["queue"] for r in filter_rows(rows, "all")] == ["competitive", "premier"]
    assert [r["queue"] for r in filter_rows(rows, "unrated")] == ["unrated"]
    assert [r["queue"] for r in filter_rows(rows, "everything")] == ["competitive", "premier", "unrated"]
    assert filter_rows(rows, "nonsense") == filter_rows(rows, "all")


def test_aggregates(imported):
    gs, _, _ = imported
    rows = filter_rows(gs.rows(), "all")
    maps = by_map(rows)
    assert {m["map"] for m in maps} == set(sh.MAPS)
    assert sum(m["games"] for m in maps) == len(rows)
    agents = by_agent(rows)
    jett = next(a for a in agents if a["agent"] == "Jett")
    raze = next(a for a in agents if a["agent"] == "Raze")
    assert jett["wr"] > raze["wr"]
    assert len(filter_rows(rows, "premier")) + len(filter_rows(rows, "competitive")) == len(rows)
    d = map_detail(rows, "Ascent")
    assert d["summary"]["games"] == 10 and d["n_full"] >= 3
    assert all(o["kind"] in ("good", "bad", "info") for o in d["observations"])
    s = summary(rows)
    assert 0 <= s["kast"] <= 1 and s["fk"] + s["fd"] > 0


def test_local_meta_counts_each_match_once(imported):
    gs, _, _ = imported
    rows = gs.rows()
    meta = local_meta(rows + rows)                                  # same matches twice (two profiles)
    full_ascent = sum(1 for r in rows if r["source"] == "full" and r["map"] == "Ascent")
    assert meta["Ascent"]["games"] == full_ascent
    shares = sum(a["share"] for a in meta["Ascent"]["agents"])
    assert abs(shares - 5) < 1e-6                                   # 5 agents per team
    assert pattern(["Jett", "Sova", "Omen", "Killjoy", "Skye"]) == "1D 2I 1C 1S"


def _rows(agent_map_results):
    out = []
    for i, (agent, m, won, acs) in enumerate(agent_map_results):
        out.append({"match_id": f"x{i}", "agent": agent, "map": m, "won": won, "acs": acs, "rounds": 20,
                    "kills": 15, "deaths": 14, "assists": 3, "queue": "premier", "source": "stored"})
    return out


def _pools():
    return [
        Pool.from_rows("ctrl", _rows([("Omen", "Ascent", 1, 200)] * 6 + [("Viper", "Ascent", 0, 180)] * 3)),
        Pool.from_rows("duel", _rows([("Jett", "Ascent", 1, 260)] * 5 + [("Raze", "Ascent", 0, 210)] * 5)),
        Pool.from_rows("init", _rows([("Sova", "Ascent", 1, 210)] * 6 + [("Fade", "Bind", 1, 200)] * 3)),
        Pool.from_rows("sent", _rows([("Killjoy", "Ascent", 1, 190)] * 4 + [("Cypher", "Ascent", 0, 170)] * 4)),
        # flex player whose best numbers are on a second Duelist, but the comp needs coverage
        Pool.from_rows("flex", _rows([("Reyna", "Ascent", 1, 250)] * 5 + [("Skye", "Ascent", 1, 200)] * 3
                                     + [("Omen", "Ascent", 0, 150)] * 2)),
    ]


def test_best_comp_covers_roles():
    c = best_comp(_pools(), "Ascent")
    assert c["ok"]
    agents = {p["player"]: p["agent"] for p in c["picks"]}
    assert agents["duel"] == "Jett" and agents["ctrl"] == "Omen" and agents["init"] == "Sova"
    assert len(set(agents.values())) == 5
    got = [roles.role_of(a) for a in agents.values()]
    assert {"Controller", "Initiator", "Sentinel"} <= set(got)
    assert c["missing_roles"] == []


def test_meta_file_overrides():
    meta = parse_meta("Ascent:\n  avoid: [Jett]\n  roles: 2D 1I 1C 1S\n")
    c = best_comp(_pools(), "Ascent", meta=meta["ascent"])
    agents = {p["player"]: p["agent"] for p in c["picks"]}
    assert agents["duel"] == "Raze"                               # Jett avoided
    assert agents["flex"] == "Reyna"                              # 2 duelists asked for
    with pytest.raises(ValueError):
        parse_meta("Ascent:\n  roles: 1D 1I 1C\n")


def test_team_plan_with_substitute():
    pools = _pools()
    sub = Pool.from_rows("subby", _rows([("Killjoy", "Ascent", 1, 200)] * 3 + [("Omen", "Ascent", 1, 190)] * 3))
    plan = team_plan(pools, [sub], ["Ascent"], {}, {})
    fills = {f["out"]: f for f in plan[0]["fills"]}
    assert set(fills) == {p.label for p in pools}
    assert fills["ctrl"]["sub_agent"] in ("Omen", "Killjoy")
    assert fills["sent"]["sub"] == "subby"


def test_pick_helper_fills_missing_role():
    pool = Pool.from_rows("me", _rows([("Jett", "Ascent", 1, 260)] * 8 + [("Omen", "Ascent", 0, 180)] * 3
                                      + [("Killjoy", "Ascent", 0, 170)] * 2))
    res = pick_helper(pool, "Ascent", ["Raze", "Sova", "Cypher", "Reyna"])
    assert res["need"] == ["Controller"]
    assert res["picks"][0]["agent"] == "Omen"                       # last pick and no controller yet
    res = pick_helper(pool, "Ascent", ["Viper"])
    assert res["picks"][0]["agent"] == "Jett"                       # plenty of slots: your best agent


def test_tips_prompt_and_schema(imported):
    from nexus.stats.tips import facts, write_tips
    gs, _, _ = imported
    rows = filter_rows(gs.rows())

    class LLM:
        model = "fake"

        def chat_json(self, system, user, schema):
            assert "Ascent" in user and "opening_duels_by_area" in user
            assert set(schema["required"]) >= {"summary", "agent_pool", "attack", "defense", "focus_next"}
            return {"summary": "s", "agent_pool": [{"agent": "Jett", "verdict": "main", "why": "w"}],
                    "attack": [{"tip": "t", "evidence": "e"}], "defense": [], "focus_next": "f"}
    out = write_tips(LLM(), rows, "Ascent")
    assert out["_facts"]["map"] == "Ascent" and out["agent_pool"][0]["verdict"] == "main"
    f = facts(rows, "Ascent")
    assert f["overall"]["games"] == 10


def test_pick_helper_names_a_role_you_dont_play():
    pool = Pool.from_rows("me", _rows([("Jett", "Ascent", 1, 260)] * 5 + [("Sova", "Ascent", 1, 200)] * 2))
    local = {"agents": [{"agent": "Omen", "role": "Controller", "share": .9}, {"agent": "Viper", "role": "Controller", "share": .4}]}
    res = pick_helper(pool, "Ascent", ["Raze", "Killjoy"], local)
    assert res["uncovered"] == [{"role": "Controller", "suggest": ["Omen", "Viper"]}]


def test_client_reports_rate_limit_waits(tmp_path, monkeypatch):
    import requests
    from nexus import henrik
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.headers, self.text = code, {"Retry-After": "2"}, ""

        def json(self):
            return {"data": []}

    class S:
        def get(self, *a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise requests.Timeout("slow")
            return Resp(429 if len(calls) == 2 else 200)

    monkeypatch.setattr(henrik.time, "sleep", lambda s: None)
    c = henrik.HenrikClient("k", tmp_path, session=S())
    msgs = []
    c.on_wait = msgs.append
    assert c.match_history("eu", "pc", "a", "b") == []
    assert len(calls) == 3 and "no answer" in msgs[0] and "rate limit" in msgs[1] and "2 s" in msgs[1]


def test_role_mix_from_meta_is_followed_when_possible():
    pools = _pools()
    meta = parse_meta("Ascent:\n  roles: 1D 1I 2C 1S\n")["ascent"]
    c = best_comp(pools, "Ascent", meta=meta)
    assert c["pattern"] == "1D 1I 2C 1S" and c["missing_roles"] == []
    # impossible mix (nobody plays a 3rd controller): best effort, and it says what's missing
    c = best_comp(pools, "Ascent", meta=parse_meta("Ascent:\n  roles: 0D 1I 3C 1S\n")["ascent"])
    assert c["ok"] and any("Controller" in m for m in c["missing_roles"])


# ---------------------------------------------------------------------------
# playstyle, pros, videos
# ---------------------------------------------------------------------------
def test_profile_uses_lobby_percentiles(imported):
    from nexus.stats.style import profile
    gs, _, _ = imported
    rows = filter_rows(gs.rows())
    assert all("lobby" in r and len(r["lobby"]) == 10 for r in rows if r["source"] == "full")
    prof = profile(rows)
    assert set(prof["dims"]) == {"opening", "kills", "assists", "survive"}
    assert all(0 <= v <= 1 for v in prof["dims"].values())
    assert "player-games in your matches" in prof["reference"]
    assert prof["main_role"] == "Duelist" and next(iter(prof["agents"])) == "Jett"


def test_lobby_backfilled_from_cache(tmp_path, cache, history):
    import copy
    gs = GameStore(tmp_path / "games.json")
    import_games(sh.FakeHenrik(history, full_depth=4), "eu", "pc", "adv1ce", "LFT", gs, cache)
    data = gs.load()
    # simulate rows from the previous version (no lobby) whose matches are in the cache
    (cache / "matches").mkdir(exist_ok=True)
    for mid, r in data["games"].items():
        if r["source"] == "full":
            r.pop("lobby"); r.pop("v", None)
            raw = next(d for d in history if d["metadata"]["match_id"] == mid)
            (cache / "matches" / f"{mid}.json").write_text(json.dumps({"status": 200, "data": copy.deepcopy(raw)}))
    gs.save(data)
    import_games(sh.FakeHenrik(history, full_depth=4), "eu", "pc", "adv1ce", "LFT", gs, cache)
    assert all("lobby" in r and r["v"] == ROW_VERSION and "iso" in r and "clutch" in r and "tier" in r for r in gs.rows() if r["source"] == "full")


def test_pro_list_and_matching():
    from nexus.stats.style import load_pros, match_pros
    pros = load_pros("")
    assert len(pros) >= 10 and all(p["role"] in roles.ROLES for p in pros)
    entry = {"games": 50, "dims": {"opening": 0.9, "kills": 0.85, "assists": 0.2, "survive": 0.4},
             "agents": {"Jett": 0.6, "Raze": 0.3, "Sova": 0.1}, "roles": {"Duelist": 0.9, "Initiator": 0.1}}
    top = match_pros(entry, pros)
    assert top[0]["role"] == "Duelist" and "Jett" in top[0]["shared"] and top[0]["score"] > 0.7
    support = {"games": 50, "dims": {"opening": 0.25, "kills": 0.45, "assists": 0.85, "survive": 0.6},
               "agents": {"Sova": 0.7, "Fade": 0.3}, "roles": {"Initiator": 1.0}}
    assert match_pros(support, pros)[0]["role"] == "Initiator"
    with pytest.raises(ValueError):
        load_pros("pros:\n  - name: x\n    role: Healer\n    style: {opening: 1, kills: 1, assists: 1, survive: 1}\n")
    with pytest.raises(ValueError):
        load_pros("pros:\n  - name: x\n    role: Duelist\n    style: {opening: 2}\n")


def test_video_queries(imported):
    from nexus.stats.style import load_pros, match_pros, profile, video_queries
    gs, _, _ = imported
    rows = filter_rows(gs.rows())
    prof = profile(rows)
    matches = match_pros(prof, load_pros(""))
    qs = video_queries(rows, prof, matches)
    assert 2 <= len(qs) <= 6 and qs[0]["kind"] == "pro" and matches[0]["name"] in qs[0]["query"]
    assert all(q["url"].startswith("https://www.youtube.com/results?search_query=") for q in qs)
    assert all("valorant" in q["query"].lower() and q["why"] for q in qs)
    assert len({q["query"] for q in qs}) == len(qs)
    # built around the pro you pick
    other = matches[1]["name"]
    q2 = video_queries(rows, prof, matches, pro=other)
    assert q2[0]["kind"] == "pro" and other in q2[0]["query"] and "#2 closest" in q2[0]["why"]
    assert all(matches[0]["name"] not in q["query"] for q in q2)


def test_youtube_search_and_cache(tmp_path):
    from nexus.stats.youtube import YouTubeError, search

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, json.dumps(body)

        def json(self):
            return self._b

    class Sess:
        calls = 0

        def get(self, url, params, headers, timeout):
            assert "key" not in params and headers == {"X-Goog-Api-Key": "K"}
            Sess.calls += 1
            assert params["type"] == "video"
            return Resp(200, {"items": [{"id": {"videoId": "abc"}, "snippet": {
                "title": "aspas Jett POV", "channelTitle": "VODs", "publishedAt": "2026-09-01T00:00:00Z",
                "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/abc/mqdefault.jpg"}}}}]})
    v = search("K", "aspas Jett POV valorant", tmp_path, session=Sess())
    assert v[0]["url"] == "https://www.youtube.com/watch?v=abc" and v[0]["published"] == "2026-09-01"
    search("K", "aspas Jett POV valorant", tmp_path, session=Sess())
    assert Sess.calls == 1                                   # second call from the cache

    class Bad:
        def get(self, *a, **k):
            return Resp(403, {"error": {"message": "quota exceeded"}})
    with pytest.raises(YouTubeError, match="quota"):
        search("K", "other query", tmp_path, session=Bad())


def test_watch_guide_prompt(imported):
    from nexus.stats.style import load_pros, match_pros, profile, video_queries
    from nexus.stats.tips import write_watch_guide
    gs, _, _ = imported
    rows = filter_rows(gs.rows())
    prof = profile(rows)
    matches = match_pros(prof, load_pros(""))
    qs = video_queries(rows, prof, matches)

    class LLM:
        model = "fake"

        def chat_json(self, system, user, schema):
            assert matches[0]["name"] in user and "percentiles" in user
            ids = schema["properties"]["items"]["items"]["properties"]["id"]["enum"]
            assert ids == [q["id"] for q in qs]
            return {"pro_summary": "p", "items": [{"id": ids[0], "watch_for": "w"}], "habits": ["h"]}
    out = write_watch_guide(LLM(), prof, matches, qs)
    assert out["items"][0]["watch_for"] == "w" and out["_model"] == "fake"


def test_team_roles_scores_and_lineup(tmp_path, cache, history):
    from nexus.stats.teamroles import PRIMARY, TEAM_ROLES, team_roles
    members = []
    for n, t in [("adv1ce", "LFT"), ("red-0", "T"), ("red-2", "T"), ("red-3", "T"), ("red-4", "T")]:
        gs = GameStore(tmp_path / f"{n}.json")
        import_games(sh.FakeHenrik(history, full_depth=20), "eu", "pc", n, t, gs, cache)
        members.append({"label": n, "kind": "starter", "rows": filter_rows(gs.rows()), "assigned": []})
    members[3]["assigned"] = ["Anchor"]
    members[0]["assigned"] = ["IGL"]
    res = team_roles(members, local_meta([r for m in members for r in m["rows"]]), ["Ascent", "Bind"])
    for p in res["players"]:
        assert set(p["scores"]) == set(TEAM_ROLES)
        assert all(0 <= v["score"] <= 100 and v["evidence"] for v in p["scores"].values())
    lu = res["lineup"]
    assert sorted(lu["primary"].values()) == sorted(PRIMARY)          # one of each primary role
    assert lu["primary"]["red-3"] == "Anchor" and lu["hats"]["IGL"] == "adv1ce"   # assigned roles win
    assert all(p["learn"] and p["learn"]["agent"] for p in res["players"])
    # a player whose assigned role doesn't show in the data gets a gentle check
    members[1]["assigned"] = ["Operator"]
    res = team_roles(members, {}, [])
    assert any("Operator" in c for c in next(p for p in res["players"] if p["label"] == "red-0")["checks"])


# ---------------------------------------------------------------------------
# batch 2: team data, comps top 3, discord
# ---------------------------------------------------------------------------
def test_team_matches_tips_and_map_facts(tmp_path, cache, history):
    from nexus.stats.teamdata import map_facts, team_matches, teammate_tips
    (cache / "matches").mkdir(exist_ok=True)
    for d in history:                                   # what the importer caches
        (cache / "matches" / f"{d['metadata']['match_id']}.json").write_text(json.dumps({"status": 200, "data": d}))
    rows = {}
    for n, t, pu in [("adv1ce", "LFT", "red-1"), ("red-0", "T", "red-0"), ("red-2", "T", "red-2"), ("red-3", "T", "red-3")]:
        gs = GameStore(tmp_path / f"{n}.json")
        import_games(sh.FakeHenrik(history, full_depth=20), "eu", "pc", n, t, gs, cache)
        rows[pu] = gs.rows()
    ms = team_matches(cache, rows)
    assert ms and all(team == "Red" for _, team in ms)
    f = map_facts(ms, cache, "Ascent")
    assert f["team_matches"] > 0 and f["attack"]["rounds"] > 0
    assert set(f) >= {"attack", "defense", "mid_control"}
    assert map_facts(ms, cache, "Nowhere") == {"map": "Nowhere", "team_matches": 0}
    tips = teammate_tips(ms, cache, {"red-1": "adv1ce", "red-0": "red-0", "red-2": "red-2", "red-3": "red-3"})
    assert all(t["kind"] in ("outnumbered", "alone", "duo") and t["text"] for t in tips)


def test_first_contact_skips_zones_without_a_timing_window(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from nexus.stats import teamdata
    monkeypatch.setattr(teamdata, "_map_info", lambda *a: NS(area=lambda x, y: "A", zone=lambda x, y: x))
    monkeypatch.setattr(teamdata, "_spawn", lambda *a: None)
    rounds = [NS(side_of=lambda t: "defense", winning_team="Red", plant=None,
                 kills=[NS(t_round_ms=20000, victim_x=z, victim_y=0, killer_team="Red", victim_team="Blue")])
              for z in ["B"] * 3 + ["Mid"] * 2]             # 2 rounds is too few for a window
    f = teamdata.map_facts([(NS(map_name="Ascent", rounds=rounds), "Red")], tmp_path, "Ascent")
    assert [c["where"] for c in f["defense"]["first_contact"]] == ["B"]


def test_top_comps_are_different():
    from nexus.stats.comp import top_comps
    cs = top_comps(_pools(), "Ascent")
    assert len(cs) == 3 and cs[0]["total"] >= cs[1]["total"] >= cs[2]["total"]
    sets = [{p["agent"] for p in c["picks"]} for c in cs]
    assert all(len(a - b) >= 2 for i, a in enumerate(sets) for b in sets[:i])


def test_discord_payloads():
    from nexus.discord import DiscordError, focus_embeds, post, prep_embeds, valid_url
    assert valid_url("https://discord.com/api/webhooks/123456/abcDEF-_x")
    assert not valid_url("https://example.com/api/webhooks/1/x") and not valid_url("")
    from nexus.stats.comp import top_comps
    plans = {"Ascent": {"plans": [{"title": "A fake", "side": "attack", "idea": "fake A, hit B", "timing": "1:05",
                                   "if_then": ["if they stack B, go A"], "steps": [{"player": "duel", "what": "lurk B"}]}]}}
    e = prep_embeds("Peek911", [{"map": "Ascent", "comps": top_comps(_pools(), "Ascent")}], plans)
    assert e[0]["title"] == "Ascent" and "**1.**" in e[0]["description"] and e[0]["fields"][0]["name"].endswith("A fake")
    fe = focus_embeds("Peek911", "2026-W44", [{"name": "Burn", "roles": ["Anchor"], "focus": {
        "focus": "Fall back after the first kill", "why": "w", "in_game": ["a", "b"], "number_to_watch": {"metric": "KAST", "now": "62%", "goal": "70%"}}}])
    assert "Burn · Anchor" in fe[0]["title"] and "KAST: 62% → 70%" in fe[0]["description"]
    sent = []

    class S:
        def post(self, url, json, timeout):
            sent.append(json)

            class R:
                status_code = 204
            return R()
    post("https://discord.com/api/webhooks/1/x", "hi", [{"title": str(i)} for i in range(13)], session=S())
    assert len(sent) == 2 and len(sent[0]["embeds"]) == 10 and sent[0]["allowed_mentions"] == {"parse": []}
    with pytest.raises(DiscordError):
        post("https://evil.example/hook", "x")


def test_game_plan_steps_cleaned_and_ordered():
    from nexus.stats.gameplans import write_plans

    class LLM:
        model = "m"

        def chat_json(self, system, user, schema):
            assert "Only these callouts" not in system and "A Main" in system
            return {"plans": [{"title": "t", "side": "attack", "idea": "i", "timing": "1:05", "if_then": [], "why": "w",
                               "steps": [{"player": "b", "what": "b: lurk mid"}, {"player": "a", "what": "smoke A"}]}] * 3}
    out = write_plans(LLM(), "Ascent", {}, [{"player": "a", "agent": "Omen"}, {"player": "b", "agent": "Jett"}],
                      ["A Main", "Mid"], [], [])
    assert [s["player"] for s in out["plans"][0]["steps"]] == ["a", "b"]
    assert out["plans"][0]["steps"][1]["what"] == "Lurk mid"


def test_secrets_stay_out_of_network_errors(tmp_path, monkeypatch):
    """requests puts the whole URL in its error text, and those texts are shown to teammates."""
    import requests
    from nexus import discord
    from nexus.stats import youtube
    monkeypatch.setattr(youtube, "API", "https://127.0.0.1:9/youtube/v3/search")   # nothing listens here
    with pytest.raises(requests.RequestException) as e:
        youtube.search("SECRETKEY", "q", tmp_path)
    assert "SECRETKEY" not in str(e.value)

    url = "https://discord.com/api/webhooks/1/SECRETTOKEN"

    class Down:
        def post(self, url, **kw):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
    for send in (lambda: discord.post(url, "hi", session=Down()),
                 lambda: discord.post_file(url, "hi", "a.png", b"x", session=Down())):
        with pytest.raises(discord.DiscordError) as e:
            send()
        assert "SECRETTOKEN" not in str(e.value) and "ConnectionError" in str(e.value)
        assert e.value.__suppress_context__


def test_rows_v3_clutch_duels_retakes(imported):
    gs, _, _ = imported
    full = [r for r in gs.rows() if r.get("source") == "full"]
    assert full and all(r["v"] == ROW_VERSION and isinstance(r["tier"], str) for r in full)
    r = full[0]
    assert len(r["shots"]) == 3 and all(isinstance(x, int) for x in r["shots"])
    assert r["duels"] and all(isinstance(d[0], int) and d[1] in (0, 1) for d in r["duels"])
    assert all(k.isdigit() and 1 <= int(k) <= 5 and v[1] <= v[0] for k, v in r["clutch"].items())
    for key in ("retake", "postplant"):
        assert len(r[key]) == 2 and r[key][1] <= r[key][0]
    assert sum(d[1] for d in r["duels"]) == r["kills"] or len(r["duels"]) <= r["kills"] + r["deaths"]


def test_progress_weeks_trend_and_focus_check():
    from datetime import datetime, timedelta, timezone
    from nexus.stats import progress as prog
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)

    def row(days, won, kast, fk, fd):
        return {"started_at": (now - timedelta(days=days)).isoformat(), "won": won, "acs": 200, "kills": 15, "deaths": 14,
                "source": "full", "rounds": 20, "kast": kast, "fk": fk, "fd": fd, "traded_deaths": 4,
                "iso": {"attack": [0, 0, 7, 3], "defense": [0, 0, 7, 2]}, "survived": {"attack": 3, "defense": 3},
                "shots": [20, 60, 10], "clutch": {"1": [1, 1]}, "retake": [2, 1]}
    old = [row(30 + i, 0.0, 12, 2, 4) for i in range(6)]          # KAST 60%, first duels 33%
    new = [row(1 + i, 1.0, 15, 4, 2) for i in range(4)]           # KAST 75%, first duels 67%
    rows = new + old
    weeks = prog.weekly(rows, 10, now)
    assert len(weeks) == 10 and weeks[-1]["games"] >= 1 and sum(w["games"] for w in weeks) == 10
    t = prog.trend(rows, "kast", now)
    assert t["better"] and round(t["now"], 2) == 0.75 and round(t["before"], 2) == 0.6
    assert prog.metric_for("KAST") == "kast" and prog.metric_for("first duel win rate") == "first_duels"
    assert prog.metric_for("deaths without a teammate nearby") == "alone" and prog.metric_for("vibes") is None
    week = f"{(now - timedelta(days=6)).isocalendar()[0]}-W{(now - timedelta(days=6)).isocalendar()[1]:02d}"
    ck = prog.focus_check(rows, week, {"focus": "Trade more", "number_to_watch": {"metric": "KAST", "now": "60%", "goal": "70%"}})
    assert ck["metric"] == "kast" and ck["before"] == 0.6 and ck["goal"] == 0.7 and ck["verdict"] == "goal reached" and ck["ok"]
    ck = prog.focus_check(rows, week, {"focus": "x", "number_to_watch": {"metric": "something odd", "now": "1", "goal": "2"}})
    assert ck is None
    assert prog.fmt("kast", 0.756) == "76%" and prog.fmt("kd", 1.234) == "1.23" and prog.fmt("acs", None) == "–"


def test_training_aim_routine_and_learning_path(imported):
    from nexus.stats import training as tr
    from nexus.stats.style import load_pros
    gs, _, _ = imported
    rows = gs.rows()
    a = tr.aim_profile(rows)
    assert a["games"] >= 1 and a["duels"] > 0 and set(a["ranges"]) == {"close", "mid", "long"}
    weak = {**a, "hs": 0.12, "ranges": {**a["ranges"], "close": {"duels": 30, "won": 0.3, "share": .4}},
            "alone_deaths": 0.5}
    d = tr.diagnose(weak)
    assert [x["key"] for x in d][:2] == ["hs", "close"] and any(x["key"] == "alone" for x in d)
    r = tr.routine(d)
    assert r[0]["key"] == "crosshair" and r[-1]["key"] == "dm_warm" and len({x["key"] for x in r}) == len(r)
    refs = tr.team_refs("me", {"me": weak, "mate": {**weak, "hs": 0.25}})
    assert refs and refs[0]["who"] == "mate" and refs[0]["what"] == "headshots"
    from nexus.stats.teamroles import FALLBACK_AGENTS, ROLE_AGENTS
    learn = tr.agents_to_learn("Support", {"Sova": 20}, {"Initiator": 2, "Controller": 0}, {"Omen": 0.3}, 5, ROLE_AGENTS, FALLBACK_AGENTS)
    assert 3 <= len(learn) <= 5 and learn[0]["agent_role"] == "Controller" and learn[0]["agent"] == "Omen"
    assert all(x["agent"] != "Sova" for x in learn)
    p = tr.learn_path("Jett", rows, ["Ascent", "Bind"], load_pros(""))
    assert p["steps"][0]["done"] == (p["games"] >= 1) and p["total"] == 5 and 0 <= p["reached"] <= 5
    assert any(s.get("optional") for s in p["steps"])        # watch a pro who plays it


def test_premier_schedule_from_api_and_builtin():
    from datetime import datetime, timezone
    from nexus.stats.premier_schedule import BUILTIN, current, schedule
    api = [{"id": "old", "events": [{"type": "LEAGUE", "starts_at": "2025-01-01T00:00:00Z", "ends_at": "2025-01-05T00:00:00Z",
                                     "map_selection": {"maps": [{"name": "Icebox"}]}}]},
           {"id": "S2", "events": [
               {"type": "LEAGUE", "starts_at": "2026-10-21T00:00:00Z", "ends_at": "2026-10-26T00:00:00Z",
                "map_selection": {"type": "RANDOM", "maps": [{"name": "Bind", "id": "x"}]},
                "conference_schedules": [{"conference": "EU_CENTRAL", "starts_at": "2026-10-22T17:00:00Z", "ends_at": "2026-10-25T21:00:00Z"}]},
               {"type": "LEAGUE", "starts_at": "2026-10-28T00:00:00Z", "ends_at": "2026-11-02T00:00:00Z",
                "map_selection": {"maps": [{"name": "Corrode"}]}},
               {"type": "TOURNAMENT", "starts_at": "2026-12-06T00:00:00Z", "ends_at": "2026-12-06T23:00:00Z",
                "map_selection": {"type": "PICKBAN", "maps": [{"name": "Bind"}, {"name": "Corrode"}, {"name": "Lotus"}]}}]}]
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    s = schedule(api, "EU_CENTRAL", now)
    assert s["id"] == "S2" and [w["map"] for w in s["weeks"]] == ["Bind", "Corrode"]
    assert s["weeks"][0]["starts"] == "2026-10-22" and s["playoffs"]["maps"] == ["Bind", "Corrode", "Lotus"]
    c = current(s, now)
    assert c["week"]["map"] == "Corrode" and not c["upcoming"] and c["pool"] == ["Bind", "Corrode"]
    assert schedule(None) is BUILTIN and schedule({"events": []}) is BUILTIN
    assert current(BUILTIN, datetime(2026, 11, 3, tzinfo=timezone.utc))["week"]["map"] == "Sunset"   # Tuesday before week 3
    assert current(BUILTIN, datetime(2026, 12, 6, 15, tzinfo=timezone.utc))["in_playoffs"]


def _quiz_match():
    """Round 1: you're left 1v2 after the plant. Round 2: you die first, 30 m from your team, untraded.
    Round 3: your team is 5v3 and loses."""
    from nexus.models import Kill, Match, Player, PlayerLoc, Round, SpikeEvent
    red = [f"r{i}" for i in range(5)]
    blue = [f"b{i}" for i in range(5)]
    pl = {pu: Player(pu, pu, "T", "Red" if pu in red else "Blue", "Sova" if pu == "r0" else "Jett", "", "", 0, 0, 0, 0, 0, 0, 0, 0, 0, {})
          for pu in red + blue}
    locs = lambda far=False: [PlayerLoc(pu, "Red", 3000 if (far and pu == "r0") else 0, 0) for pu in red] + [PlayerLoc(pu, "Blue", 500, 0) for pu in blue]
    K = lambda t, killer, victim, x=0: Kill(1, t, t, killer, pl[killer].team, victim, pl[victim].team, [], "Vandal", "Weapon", x, 0, locs())
    r1 = Round(0, "Blue", "Detonate", "", "Blue", SpikeEvent("plant", 40000, "B", "b0", "Blue", 0, 0), None, {},
               [K(10000, "b0", "r1"), K(20000, "b1", "r2"), K(30000, "r0", "b2"), K(32000, "r0", "b3"), K(34000, "r0", "b4"), K(45000, "b0", "r3"), K(50000, "b1", "r4"),
                K(60000, "b0", "r0")])
    k_alone = Kill(2, 15000, 15000, "b3", "Blue", "r0", "Red", [], "Operator", "Weapon", 3000, 0, locs(far=True))
    r2 = Round(1, "Blue", "Elimination", "", "Blue", None, None, {}, [k_alone, K(30000, "b3", "r1")])
    r3 = Round(2, "Blue", "Elimination", "", "Blue", None, None, {},
               [K(10000, "r1", "b0"), K(12000, "r2", "b1"), K(30000, "b2", "r3"), K(35000, "b2", "r4"), K(40000, "b3", "r2"),
                K(45000, "b3", "r1"), K(50000, "b4", "r0")])
    return Match("m1", "Bind", "bind", "2026-10-30T20:00:00Z", "Premier", 0, "eu", pl, ["Red", "Blue"],
                 {"Red": 0, "Blue": 3}, [r1, r2, r3], [])


def test_quiz_moments_and_pick():
    from nexus.stats.quiz import moments, pick
    ms = moments(_quiz_match(), "r0", None)
    kinds = {m["kind"]: m for m in reversed(ms)}          # the first of each kind
    assert set(kinds) == {"clutch", "alone", "advantage"} and len(ms) == 4      # round 3 ends in a 1v3 too
    c = kinds["clutch"]["facts"]
    assert c["you_vs"] == "1v2" and c["time_s"] == 50 and "planted on B 10 s ago" in c["spike"] and c["round"] == 1
    assert "You died 10 s later" in kinds["clutch"]["happened"] and "round was lost" in kinds["clutch"]["happened"]
    a = kinds["alone"]["facts"]
    assert a["nearest_teammate_m"] == 30 and "Operator" in a["killed_by"] and a["round"] == 2 and a["score"] == "0–1"
    assert kinds["advantage"]["facts"]["players_alive"] == "5v3"
    p = pick(ms * 3)
    assert [m["id"] for m in p] == ["q1", "q2"] and len({m["kind"] for m in p}) == 2     # at most 2 from one match


def test_rank_history():
    from nexus.stats import rank as rk
    items = [{"match_id": f"m{i}", "tier": {"id": 14, "name": "GOLD 3"}, "ranking_in_tier": 10 * i, "last_mmr_change": 10,
              "date": f"2026-10-{i + 1:02d}T20:00:00Z"} for i in range(5)]
    items.append({"currenttierpatched": "Platinum 1", "ranking_in_tier": 5, "mmr_change_to_last_game": 20, "date_raw": 1793300000})
    items.append({"tier": "x", "ranking_in_tier": "y"})                       # junk is skipped
    e = rk.parse_entries(items)
    assert len(e) == 6 and e[-1]["tier"] == 15 and e[0]["tier"] == 14
    assert rk.tier_id("Platinum 1") == 15 and rk.tier_name(27) == "Radiant" and rk.tier_id(99) is None
    pts, src = rk.series(e, [])
    assert src == "rr" and pts[-1]["pts"] == 1205 and pts[0]["name"] == "Gold 3"
    ch = rk.chart(pts)
    assert ch["path"].startswith("M") and [l["label"] for l in ch["lines"]][:2] == ["Gold 3", "Platinum 1"]
    # without the RR history: the rank shown in each ranked match
    pts, src = rk.series([], [{"queue": "competitive", "tier": "Gold 2", "started_at": "1"}, {"queue": "premier", "tier": "Gold 3"}])
    assert src == "match" and len(pts) == 1 and pts[0]["name"] == "Gold 2"


def test_premier_schedule_skips_an_old_api_season():
    from datetime import datetime, timezone
    from nexus.stats.premier_schedule import current, schedule
    old = [{"id": "S1", "events": [{"type": "LEAGUE", "starts_at": f"2025-03-0{d}T00:00:00Z", "ends_at": f"2025-03-0{d + 1}T00:00:00Z",
                                    "map_selection": {"maps": [{"name": "Ascent"}]}} for d in (1, 3, 5)]}]
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    s = schedule(old, None, now)
    assert s["id"] == "V26A6" and "older season" in s["note"] and current(s, now)["week"]["map"] == "Corrode"
    new = [{"id": "S2", "events": [{"type": "LEAGUE", "starts_at": "2026-10-28T00:00:00Z", "ends_at": "2026-11-01T00:00:00Z",
                                    "map_selection": {"maps": [{"name": "Pearl"}]}}]}]
    assert current(schedule(new, None, now), now)["week"]["map"] == "Pearl"


class _Resp:
    def __init__(self, status, body, headers=None):
        self.status_code, self._b, self.headers, self.text = status, body, headers or {}, json.dumps(body)

    def json(self):
        return self._b


class _Session:
    def __init__(self, answers):
        self.answers, self.sent = list(answers), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.sent.append((url, json, headers))
        return self.answers.pop(0)


def test_claude_client_cost_budget_and_fallback(tmp_path, monkeypatch):
    from nexus.coach import llm as L
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    L.set_usage_file(tmp_path / "llm_usage.json")
    ok = _Resp(200, {"content": [{"type": "tool_use", "name": "answer", "input": {"x": 1}}], "stop_reason": "tool_use",
                     "usage": {"input_tokens": 100_000, "output_tokens": 20_000}})
    s = _Session([_Resp(529, {"error": {"message": "overloaded"}}), ok])
    c = L.ClaudeLLM("sk-test", "claude-sonnet-5-5", session=s)
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    assert c.chat_json("sys", "user", schema) == {"x": 1}
    url, body, headers = s.sent[-1]
    assert url == L.API_URL and headers["x-api-key"] == "sk-test" and body["tool_choice"] == {"type": "tool", "name": "answer"}
    assert body["tools"][0]["input_schema"] == schema and body["system"] == "sys"
    assert abs(c.cost - 0.4) < 1e-9 and abs(L.month_cost() - 0.4) < 1e-9          # 100k in x $2 + 20k out x $10
    assert c.summary()["cost_usd"] == 0.4 and L.price("claude-haiku-5-5", 200_000, 0) == 0.1
    # a cut-off answer is asked again with more room
    s2 = _Session([_Resp(200, {"content": [], "stop_reason": "max_tokens", "usage": {}}), ok])
    assert L.ClaudeLLM("k", "claude-haiku-5-5", session=s2).chat_json("s", "u", schema) == {"x": 1}
    assert s2.sent[1][1]["max_tokens"] == 8192
    # key refused / budget used up: ClaudeError, and with fallback the local model answers
    bad = L.ClaudeLLM("k", "claude-sonnet-5-5", session=_Session([_Resp(401, {"error": {"message": "invalid x-api-key"}})]))
    with pytest.raises(L.ClaudeError):
        bad.chat_json("s", "u", schema)

    class Local:
        model = "gemma4:26b"

        def check(self):
            pass

        def chat_json(self, *a, **k):
            return {"x": 2}

        def summary(self):
            return {"requests": 1}
    fb = L.WithFallback(L.ClaudeLLM("k", "claude-sonnet-5-5", session=_Session([_Resp(400, {"error": {"message": "Your credit balance is too low"}})])), Local)
    assert fb.chat_json("s", "u", schema) == {"x": 2} and fb.chat_json("s", "u", schema) == {"x": 2}
    assert fb.model.startswith("claude-sonnet-5-5 → gemma4:26b (Anthropic API: Your credit balance") and fb.summary()["fell_back"]
    broke = L.ClaudeLLM("k", "claude-opus-5-5", budget_usd=0.3)
    with pytest.raises(L.ClaudeError, match="budget"):
        broke.check()
    with pytest.raises(L.ClaudeError, match="No Anthropic API key"):
        L.ClaudeLLM("", "claude-opus-5-5").check()


def test_make_llm_choices():
    from nexus.coach.llm import ClaudeLLM, WithFallback, make_llm
    from nexus.coach.ollama import Ollama
    from nexus.config import Config
    cfg = Config()
    cfg.ollama.model = "gemma4:26b"
    assert isinstance(make_llm(cfg), Ollama) and make_llm(cfg).model == "gemma4:26b"
    assert make_llm(cfg, "ollama:qwen3.8:27b").model == "qwen3.8:27b"
    cfg.claude.api_key = "k"
    m = make_llm(cfg, "claude:claude-haiku-5-5")
    assert isinstance(m, WithFallback) and m.model == "claude-haiku-5-5"
    cfg.claude.fallback = False
    assert isinstance(make_llm(cfg, "claude:claude-haiku-5-5"), ClaudeLLM)
    cfg.llm = "claude:claude-opus-5-5"
    assert make_llm(cfg).model == "claude-opus-5-5"


def test_rows_v5_utility_economy_teammates(imported):
    from nexus.stats.agentroles import agent_detail, grid
    from nexus.stats.rounds import economy, kind, teammates
    gs, _, _ = imported
    rows = gs.rows()
    full = [r for r in rows if r["source"] == "full"]
    r = full[0]
    assert r["v"] >= 5 and set(r["casts"]) == {"grenade", "ability1", "ability2", "ultimate"}
    assert len(r["econ"]) == r["rounds"] and len(r["econ"][0]) == 8          # 4.15: + kills, died
    assert r["v"] >= 6 and "patch" in r and r["no_util"] is not None and r["no_util"][1] == r["deaths"]
    assert r["own_tier"] is None or 3 <= r["own_tier"] <= 27
    assert len(r["mates"]) == 4 and all("#" in m["name"] for m in r["mates"])
    assert len(r["lobby_agents"]) == 9 and isinstance(r["lobby_agents"][0][0], str)
    e = economy(rows)
    assert e["rounds"] == sum(x["rounds"] for x in full) and sum(k["rounds"] for k in e["kinds"]) == e["rounds"]
    assert kind(1, 800) == "pistol" and kind(5, 1500) == "eco" and kind(5, 3000) == "force" and kind(5, 4500) == "full"
    t = teammates(rows)
    assert t["games"] == len(full) and t["mates"] and t["mates"][0]["games"] >= 3
    agent = full[0]["agent"]
    d = agent_detail(rows, agent, {"grenade": "Smoke"})
    assert d["games"] >= 1 and d["compare"] and d["utility"][0]["name"] == "Smoke" and d["trend"]
    gr = grid(rows)
    assert agent in gr["agents"] and any(k.startswith(agent + "|") for k in gr["cells"])


def test_review_evening_summary_and_scouted_round_types():
    from nexus.stats import evening as ev
    rounds = [{"n": n, "won": n % 2 == 0, "side": "attack", "score": "0–0", "tags": tags, "why": [ev.THEMES[t][0] for t in tags]}
              for n, tags in [(1, ["pistol_lost", "untraded"]), (2, []), (3, ["lead_lost", "untraded"]), (4, []), (5, ["untraded", "opening_lost"]),
                              (6, []), (7, ["opening_lost"])]]
    marks = {"1": {"A": {"m": "fault", "note": "too early"}}, "3": {"A": {"m": "fault"}, "B": {"m": "talk", "note": "call?"}},
             "5": {"B": {"m": "fault"}}, "7": {"B": {"m": "fault"}}, "2": {"A": {"m": "good"}}, "9": {"A": {"m": "fault"}},
             "4": {"A": {"m": "bogus"}}}
    s = ev.summarize({"rounds": rounds, "marks": marks})
    assert s["counts"] == {"fault": 4, "good": 1, "talk": 1}
    assert s["themes"][0]["tag"] == "untraded" and s["themes"][0]["rounds"] == 3
    assert [x["n"] for x in s["talk"]] == [1, 3]
    b = next(p for p in s["players"] if p["name"] == "B")
    assert b["fault"] == [5, 7] and b["focus"]["title"] == "First-duel drill"
    # the team items already cover B's first duels, so there's no extra item just for him
    assert [p["title"] for p in s["plan"]] == ["From the review evening: trade drill", "From the review evening: first-duel drill"]
    s2 = ev.summarize({"rounds": rounds, "marks": {"5": {"B": {"m": "fault"}}, "7": {"B": {"m": "fault"}}, "1": {"A": {"m": "fault"}}}})
    assert any(p["who"] == ["B"] for p in s2["plan"]) or s2["themes"]
    assert ev.key_rounds([{"n": 1, "won": False, "tags": ["lead_lost"], "buy": None},
                          {"n": 2, "won": True, "tags": [], "buy": {"us": "eco", "them": "full"}},
                          {"n": 3, "won": True, "tags": [], "buy": {"us": "full", "them": "full"}}]) == [1, 2]
    text = ev.discord_text({"map": "Bind", "score": "13–11", "opponent": "X"}, s, "Squad")
    assert "Bind" in text and "trade drill" in text.lower()


def test_round_facts_and_round_types_on_synthetic(tmp_path):
    import synth
    from nexus.parse import parse_match
    from nexus.stats import evening as ev
    from nexus.stats.rounds import round_types
    files = synth.write_all(tmp_path, with_vod=False, n_rounds=6)
    m = parse_match(json.loads(Path(files["match"]).read_text()))
    side = m.teams[0]
    facts = ev.round_facts(m, side)
    assert len(facts) == 6 and all(set(f) >= {"n", "won", "kills", "players", "tags", "alive"} for f in facts)
    assert ev.our_side(m, {p.puuid for p in m.players_on(side)}) == side
    assert ev.our_side(m, set()) is None
    rt = round_types([(m, side)])
    assert rt["rounds"] == 6 and sum(k["rounds"] for k in rt["kinds"]) == 6 and isinstance(rt["lines"], list)


def test_aim_routines_pick_and_effect():
    from nexus.stats import aim
    r, err = aim.clean({"name": "x", "kind": "link", "url": "javascript:alert(1)"})
    assert r is None and "https" in err
    r, _ = aim.clean({"name": "KK", "kind": "kovaaks", "code": "Abc-123", "focus": ["tracking", "bogus"], "minutes": "500"})
    assert r["code"] == "Abc-123" and r["focus"] == ["tracking"] and r["minutes"] == 90
    assert aim.clean({"name": "s", "kind": "steps"})[0] is None
    need = [{"focus": ["crosshair", "micro"], "weight": 3, "why": "hs"}]
    lib = [dict(x, source="builtin") for x in aim.BUILTIN] + [dict(r, source="mine", focus=["micro", "crosshair"])]
    picks = aim.pick(lib, need)
    assert picks[0]["name"] == "KK" and picks[0]["why"] == "hs"
    assert aim.warmup_for(lib, None)["source"] == "builtin" and aim.warmup_for(lib, "b-spray")["id"] == "b-spray"
    assert aim.needs([])[0]["focus"] == ["warmup"]
    rows = [{"source": "full", "shots": [3, 7, 0] if i % 2 else [1, 9, 0], "started_at": f"2026-10-{10 + i:02d}T12:00:00Z"} for i in range(12)]
    log = [{"date": f"2026-10-{10 + i:02d}", "routine": "b-range"} for i in range(12) if i % 2]
    e = aim.effect(rows, log)
    assert e["ready"] and round(e["with"]["hs"], 2) == 0.3 and round(e["without"]["hs"], 2) == 0.1 and e["diff"] > 0
    assert not aim.effect(rows, [])["ready"]


def _kcsv(scenario="1wall 6targets small", score=812.5, shots=100, hits=80):
    return (f"Kill #,Timestamp,Bot,Weapon,TTK,Shots,Hits\n1,18:00:01.000,Target,pistol,0.5s,1,1\n\n"
            f"Weapon,Shots,Hits,Damage Done,Damage Possible\npistol,{shots},{hits},1000,1200\n\n"
            f"Kills:,{hits}\nDeaths:,0\nScore:,{score}\nScenario:,{scenario}\nGame Version:,3.6\n")


def test_kovaaks_files_scores_and_playlists():
    import io as _io
    import zipfile as _zip
    from nexus.stats import kovaaks as kv
    # playlists in both spellings KovaaK's has used
    old = kv.read_playlist(json.dumps({"playlistName": "A", "shareCode": "KovaaKsTest", "scenarioList": [
        {"scenario_Name": " Wide Wall 10 Extra Small Moving ", "play_Count": 2}, {"scenario_Name": "bad/name"}]}))
    assert old["scenarios"] == [(" Wide Wall 10 Extra Small Moving ", 2)] and old["code"] == "KovaaKsTest"
    assert kv.read_playlist(json.dumps({"scenarioList": [{"scenario_name": "Tile Frenzy", "play_Count": 99}]}))["scenarios"] == [("Tile Frenzy", 20)]
    assert kv.read_playlist("not json") is None and kv.read_playlist("{}") is None
    # stats files: one CSV, a zip, unreadable ones counted
    name = "1wall 6targets small - Challenge - 2026.10.10-18.03.00 Stats.csv"
    r = kv.read_stats(name, _kcsv())
    assert r == {"s": "1wall 6targets small", "t": "2026-10-10T18:03:00", "d": "2026-10-10", "score": 812.5, "kills": 80, "acc": 0.8}
    assert kv.read_stats("random.csv", _kcsv()) is None and kv.read_stats(name, "nothing here") is None
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w") as z:
        for i in range(8):
            z.writestr(f"stats/1wall 6targets small - Challenge - 2026.10.1{i}-18.00.00 Stats.csv", _kcsv(score=900 + i))
        z.writestr("stats/broken - Challenge - 2026.10.10-18.00.00 Stats.csv", "x")
        z.writestr("readme.txt", "not a csv")
    runs, bad = kv.read_upload("stats.zip", buf.getvalue())
    assert len(runs) == 8 and bad == 1
    allr, new = kv.merge_runs([r], runs + runs)
    assert new == 8 and len(allr) == 9
    s = kv.summary(allr)[0]
    assert s["runs"] == 9 and s["best"] == 907 and s["mastered"]
    # the coach's playlists: only known names, about the right length, harder once you're steady at your best
    cat = kv.builtin() + [{"name": "My scenario", "focus": ["micro"], "level": 2}]
    need = [{"focus": ["crosshair", "micro"], "weight": 3, "why": "hs"}, {"focus": ["peeking", "flicks", "reaction"], "weight": 1, "why": "duels"}]
    w = kv.build("warmup", need, cat, [], week="2026-W45")
    names = {c["name"] for c in cat}
    assert all(x["name"] in names for x in w["items"]) and 7 <= sum(x["runs"] for x in w["items"]) <= 9
    assert w["items"][0]["focus"] == "warmup" and kv.build("warmup", need, cat, [], week="2026-W45") == w
    wn = {x["name"] for x in w["items"]}
    t = kv.build("training", need, cat, [], week="2026-W45", exclude=wn)
    assert sum(x["runs"] for x in t["items"]) == round(25 * 60 / kv.SECONDS_PER_RUN)
    # training: other scenarios than the warm-up, many different ones, not the same few over and over
    assert not wn & {x["name"] for x in t["items"]}
    assert max(x["runs"] for x in t["items"]) <= 2 and len(t["items"]) >= 10
    assert any(x["why"] == "something different" for x in t["items"])
    tiny = [{"name": f"s{i}", "focus": ["flicks"], "level": 2} for i in range(3)]   # nothing new left: repeats
    assert sum(x["runs"] for x in kv.build("training", need, tiny, [], week="w")["items"]) == round(25 * 60 / kv.SECONDS_PER_RUN)
    flicks_mastered = kv.build("training", [{"focus": ["flicks"], "weight": 3, "why": ""}], cat, allr, week="2026-W45")
    assert any(x["level"] == 3 for x in flicks_mastered["items"] if x["focus"] == "flicks")
    from datetime import date as _date
    f = kv.playlist_file(w, "Player", _date(2026, 11, 3))
    assert f["playlistName"] == "Nexus warm-up 03-11-2026 (Player)" and kv.file_name("training", _date(2026, 11, 3)) == "nexus_training_03-11-2026.json"
    assert f["scenarioList"][0] == {"scenario_name": w["items"][0]["name"], "play_Count": 1} and f["version"] == 31
    assert kv.guess("VoxTargetSwitch xsmall 200%") == (["switching", "micro"], 3)
    assert kv.guess("Smooth Strafe Track Easy")[0][0] == "tracking"


def test_web_search_helpers_and_community_playlists():
    from nexus.coach import websearch as ws
    from nexus.stats import kovaaks as kv

    class R:
        def __init__(self, code, data):
            self.status_code, self._d = code, data

        def json(self):
            return self._d

    class S:
        def get(self, url, params=None, **k):
            assert url == "http://sx:8080/search" and params["format"] == "json"
            return R(200, {"results": [{"title": "<b>Jett</b> guide", "url": "https://a.org/j", "content": "dash &amp; updraft"},
                                       {"title": "dup", "url": "https://a.org/j"}, {"title": "bad", "url": "javascript:x"}]})
    out = ws.searxng("http://sx:8080/", "jett unique query", 5, session=S())
    assert out == [{"title": "Jett guide", "url": "https://a.org/j", "snippet": "dash & updraft"}]

    class Forbidden:
        def get(self, *a, **k):
            return R(403, {})
    try:
        ws.searxng("http://sx:8080", "other query", session=Forbidden())
        raise AssertionError("expected SearchError")
    except ws.SearchError as e:
        assert "formats" in ws.describe(e)
    # pages on the LAN, the server itself or cloud metadata are never read
    for u in ("http://127.0.0.1/", "http://10.0.0.1/x", "http://169.254.169.254/latest", "file:///etc/passwd",
              "http://user:pw@example.org/", "http://[::1]/"):
        assert not ws.public_url(u), u
    assert ws.html_text("<html><script>x()</script><nav>menu</nav><p>Hello <b>you</b></p><p>Line 2</p>") == "Hello you\nLine 2"
    src, err = ws.research(lambda q, n: [{"title": q, "url": f"https://x.org/{q}", "snippet": "s"}], ["a", "b", "a"],
                           reader=lambda u, n: "page " + u)
    assert [s["n"] for s in src] == [1, 2] and src[0]["text"] == "page https://x.org/a" and not err
    assert ws.cited(src, [2, "1", 9, "x", 2]) == [{"title": "b", "url": "https://x.org/b"}, {"title": "a", "url": "https://x.org/a"}]
    assert "[1] a (https://x.org/a)" in ws.sources_block(src)

    def broken(q, n):
        raise ws.SearchError("searxng", "unreachable", "ConnectionError: secret internal detail")
    assert ws.research(broken, ["q"]) == ([], ["SearXNG isn't reachable"])
    # community playlists: what fits the needs, at about your level, without the ones you have
    need = [{"focus": ["peeking", "flicks", "reaction"], "weight": 3, "why": "first duels"}]
    picks = kv.suggest(need, [], 4)
    assert picks and all(set(p["focus"]) & {"peeking", "flicks", "reaction"} for p in picks) and picks[0]["why"] == "first duels"
    assert picks[0]["code"] not in {p["code"] for p in kv.suggest(need, [], 4, {picks[0]["code"].upper()})}
    assert len({x["code"] for x in kv.shared()}) == len(kv.SHARED) and all(ws.SHARE_CODE_RE.fullmatch(x["code"]) for x in kv.shared())


def test_duckduckgo_results_and_the_backup_search():
    from nexus.coach import websearch as ws
    page = """<div class="result results_links web-result"><div class="links_main result__body">
      <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://playvalorant.com/patch-12">Patch <b>12</b> notes</a></h2>
      <a class="result__snippet" href="https://playvalorant.com/patch-12">Jett&#x27;s dash is <b>shorter</b>.</a></div></div>
      <div class="result result--ad"><div class="result__body"><h2><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Buy</a></h2></div></div>
      <div class="result"><div class="result__body"><h2><a class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fkovaaks%3Fa%3D1&amp;rut=x">KovaaK's codes</a></h2></div></div>"""
    assert ws.ddg_results(page) == [
        {"title": "Patch 12 notes", "url": "https://playvalorant.com/patch-12", "snippet": "Jett's dash is shorter."},
        {"title": "KovaaK's codes", "url": "https://example.org/kovaaks?a=1", "snippet": ""}]

    class R:
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text

    class Blocked:
        def post(self, *a, **k):
            return R(202, "<div class='anomaly-modal'>")
    try:
        ws.duckduckgo("blocked query", session=Blocked())
        raise AssertionError("expected SearchError")
    except ws.SearchError as e:
        assert "refused" in ws.describe(e)

    def down(q, n=6):
        raise ws.SearchError("duckduckgo", "blocked")
    spare = lambda q, n=6: [{"title": "from SearXNG", "url": "https://s.org", "snippet": ""}]   # noqa: E731
    assert ws.with_backup(down, spare)("q")[0]["title"] == "from SearXNG"
    assert ws.with_backup(lambda q, n=6: [], spare)("q")[0]["title"] == "from SearXNG"         # nothing found: backup too
    assert ws.with_backup(lambda q, n=6: [{"title": "main"}], spare)("q") == [{"title": "main"}]
    def down2(q, n=6):
        raise ws.SearchError("searxng", "no_json", "<html>stack trace</html>")
    try:
        ws.with_backup(down, down2)("q")
        raise AssertionError("expected SearchError")
    except ws.SearchError as e:                       # the backup's error; only fixed texts reach the browser
        assert ws.describe(e) == "SearXNG didn't answer JSON: add json to search › formats in its settings.yml"
    assert ws.describe(ValueError("internal")) == "the search failed"


def test_web_pages_are_read_from_the_checked_address(monkeypatch):
    """No second DNS lookup (DNS rebinding): the connection goes to the address that was checked, with the
    name in the Host header; a redirect to a non-public name is refused."""
    import http.server
    import threading
    from nexus.coach import websearch as ws
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Host")))
            if self.path == "/r":
                self.send_response(302)
                self.send_header("Location", f"http://lan.test:{self.server.server_port}/p")
                self.end_headers()
                return
            body = "<html><nav>menu</nav><p>Jett&#x27;s dash</p></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port
    try:
        monkeypatch.setattr(ws, "_public_ip", lambda host, p: "127.0.0.1" if host == "ok.test" else None)
        assert ws.page_text(f"http://ok.test:{port}/p?x=1") == "Jett's dash"
        assert seen[-1] == ("/p?x=1", f"ok.test:{port}")
        assert ws.page_text(f"http://ok.test:{port}/r") == ""          # redirect to a name that isn't public
        assert ws.page_text(f"http://lan.test:{port}/p") == ""
        assert not ws.public_url(f"http://lan.test:{port}/p")
    finally:
        srv.shutdown()
    # the search cache doesn't grow forever
    ws._cache.clear()
    for i in range(ws.CACHE_MAX + 20):
        ws._remember("duckduckgo", f"q{i}", [])
    assert len(ws._cache) == ws.CACHE_MAX and ("duckduckgo", "q0") not in ws._cache
    ws._cache.clear()
    # research takes turns between the queries: the pages read are each query's best hit
    hits = {"a": [{"title": f"a{i}", "url": f"https://a.org/{i}"} for i in range(4)],
            "b": [{"title": f"b{i}", "url": f"https://b.org/{i}"} for i in range(4)]}
    read = []
    src, _ = ws.research(lambda q, n: hits[q], ["a", "b"], read=2, reader=lambda u, n: read.append(u) or "")
    assert read == ["https://a.org/0", "https://b.org/0"] and [s["title"] for s in src[:3]] == ["a0", "b0", "a1"]
