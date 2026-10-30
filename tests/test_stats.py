import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
import synth_history as sh  # noqa: E402

from valcoach.stats import roles  # noqa: E402
from valcoach.stats.aggregate import (by_agent, by_map, filter_rows, local_meta, map_detail,  # noqa: E402
                                      pattern, summary)
from valcoach.stats.comp import Pool, best_comp, parse_meta, pick_helper, team_plan  # noqa: E402
from valcoach.stats.games import GameStore, import_games  # noqa: E402


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
    assert client.calls["history"] - before["history"] <= 2        # one page per queue, nothing new: stop
    assert client.calls["stored"] - before["stored"] <= 4


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
    from valcoach.stats.tips import facts, write_tips
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
    from valcoach import henrik
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
    from valcoach.stats.style import profile
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
    assert all("lobby" in r and r["v"] == 3 and "iso" in r and "clutch" in r for r in gs.rows() if r["source"] == "full")


def test_pro_list_and_matching():
    from valcoach.stats.style import load_pros, match_pros
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
    from valcoach.stats.style import load_pros, match_pros, profile, video_queries
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
    from valcoach.stats.youtube import YouTubeError, search

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
    from valcoach.stats.style import load_pros, match_pros, profile, video_queries
    from valcoach.stats.tips import write_watch_guide
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
    from valcoach.stats.teamroles import PRIMARY, TEAM_ROLES, team_roles
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
    from valcoach.stats.teamdata import map_facts, team_matches, teammate_tips
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


def test_top_comps_are_different():
    from valcoach.stats.comp import top_comps
    cs = top_comps(_pools(), "Ascent")
    assert len(cs) == 3 and cs[0]["total"] >= cs[1]["total"] >= cs[2]["total"]
    sets = [{p["agent"] for p in c["picks"]} for c in cs]
    assert all(len(a - b) >= 2 for i, a in enumerate(sets) for b in sets[:i])


def test_discord_payloads():
    from valcoach.discord import DiscordError, focus_embeds, post, prep_embeds, valid_url
    assert valid_url("https://discord.com/api/webhooks/123456/abcDEF-_x")
    assert not valid_url("https://example.com/api/webhooks/1/x") and not valid_url("")
    from valcoach.stats.comp import top_comps
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
    from valcoach.stats.gameplans import write_plans

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
    from valcoach import discord
    from valcoach.stats import youtube
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
    assert full and all(r["v"] == 3 for r in full)
    r = full[0]
    assert len(r["shots"]) == 3 and all(isinstance(x, int) for x in r["shots"])
    assert r["duels"] and all(isinstance(d[0], int) and d[1] in (0, 1) for d in r["duels"])
    assert all(k.isdigit() and 1 <= int(k) <= 5 and v[1] <= v[0] for k, v in r["clutch"].items())
    for key in ("retake", "postplant"):
        assert len(r[key]) == 2 and r[key][1] <= r[key][0]
    assert sum(d[1] for d in r["duels"]) == r["kills"] or len(r["duels"]) <= r["kills"] + r["deaths"]


def test_progress_weeks_trend_and_focus_check():
    from datetime import datetime, timedelta, timezone
    from valcoach.stats import progress as prog
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
    from valcoach.stats import training as tr
    from valcoach.stats.style import load_pros
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
    from valcoach.stats.teamroles import FALLBACK_AGENTS, ROLE_AGENTS
    learn = tr.agents_to_learn("Support", {"Sova": 20}, {"Initiator": 2, "Controller": 0}, {"Omen": 0.3}, 5, ROLE_AGENTS, FALLBACK_AGENTS)
    assert 3 <= len(learn) <= 5 and learn[0]["agent_role"] == "Controller" and learn[0]["agent"] == "Omen"
    assert all(x["agent"] != "Sova" for x in learn)
    p = tr.learn_path("Jett", rows, ["Ascent", "Bind"], load_pros(""))
    assert p["steps"][0]["done"] == (p["games"] >= 1) and p["total"] == 5 and 0 <= p["reached"] <= 5
    assert any(s.get("optional") for s in p["steps"])        # watch a pro who plays it


def test_premier_schedule_from_api_and_builtin():
    from datetime import datetime, timezone
    from valcoach.stats.premier_schedule import BUILTIN, current, schedule
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
