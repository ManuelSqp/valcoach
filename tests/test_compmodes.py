"""Comp suggestion modes (4.10): most comfortable, from the web, map rules, stats only; and the replay path check."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from nexus import replayfile  # noqa: E402
from nexus.stats import roles  # noqa: E402
from nexus.stats import compmodes, webcomps  # noqa: E402
from nexus.stats.comp import Pool  # noqa: E402


def _rows(spec):
    """[(agent, map, won, acs, count)] -> game rows"""
    out, i = [], 0
    for agent, mp, won, acs, count in spec:
        for _ in range(count):
            i += 1
            out.append({"match_id": f"x{i}", "agent": agent, "map": mp, "won": won, "acs": acs, "rounds": 20,
                        "kills": 15, "deaths": 14, "assists": 3, "queue": "premier", "source": "stored"})
    return out


def _pools():
    """ctrl wins more on Viper but plays Omen far more; the rest are clear."""
    return [
        Pool.from_rows("ctrl", _rows([("Omen", "Ascent", 0, 190, 14), ("Omen", "Ascent", 1, 200, 10),
                                      ("Viper", "Ascent", 1, 240, 6)])),
        Pool.from_rows("duel", _rows([("Jett", "Ascent", 1, 250, 12), ("Raze", "Ascent", 1, 230, 3)])),
        Pool.from_rows("init", _rows([("Sova", "Ascent", 1, 210, 12), ("KAY/O", "Ascent", 1, 200, 4)])),
        Pool.from_rows("sent", _rows([("Killjoy", "Ascent", 1, 200, 12), ("Cypher", "Ascent", 1, 190, 3)])),
        Pool.from_rows("flex", _rows([("Skye", "Ascent", 1, 205, 10), ("Fade", "Ascent", 1, 200, 3)])),
    ]


@pytest.fixture(autouse=True)
def _roles():
    roles.load(None)


def picks(comp):
    return {p["player"]: p["agent"] for p in comp["picks"]}


def test_most_comfortable_goes_by_games_played():
    stats = compmodes.top("stats", _pools(), "Ascent")[0]
    comfort = compmodes.top("comfort", _pools(), "Ascent")[0]
    assert picks(stats)["ctrl"] == "Viper"              # better results
    assert picks(comfort)["ctrl"] == "Omen"             # played 24 times
    assert comfort["method"] == "comfort" and "24 games on Ascent" in comfort["picks"][0]["why"][0]
    plan = compmodes.plan("comfort", _pools(), [], ["Ascent"], {}, {})
    assert picks(plan[0]["main"])["ctrl"] == "Omen"


def test_web_comps_are_cleaned_and_handed_to_the_right_players():
    sources = [{"n": 1, "title": "A", "url": "https://a.example/x"}, {"n": 2, "title": "B", "url": "https://b.example/y"}]
    raw = [{"agents": ["jett", "SOVA", "Kay/O", "Omen", "killjoy"], "note": "standard", "sources": [1, 7]},
           {"agents": ["Jett", "Sova", "KAY/O", "Omen", "Killjoy"], "note": "duplicate", "sources": [2]},
           {"agents": ["Jett", "Sova", "Omen", "Killjoy"], "note": "only 4", "sources": [1]},
           {"agents": ["Jett", "Sova", "Omen", "Killjoy", "Ghost"], "note": "no such agent", "sources": [1]},
           {"agents": ["Raze", "Fade", "Viper", "Omen", "Cypher"], "note": "double smoke", "sources": [2]}]
    comps = webcomps.clean(raw, sources)
    assert [c["note"] for c in comps] == ["standard", "double smoke"]
    assert comps[0]["agents"] == ["Jett", "Sova", "KAY/O", "Omen", "Killjoy"]
    assert comps[0]["sources"] == [{"title": "A", "url": "https://a.example/x"}]     # [7] was made up

    data = {"map": "Ascent", "comps": comps, "at": 1.0, "model": "m"}
    found = webcomps.comps_for(_pools(), "Ascent", data)
    assert found[0]["web"]["note"] == "standard"          # fits these players best: everyone on his agent
    assert picks(found[0]) == {"ctrl": "Omen", "duel": "Jett", "init": "Sova", "sent": "Killjoy", "flex": "KAY/O"}
    dbl = next(c for c in found if c["web"]["note"] == "double smoke")
    assert any(p.get("new") for p in dbl["picks"]) and any("new agent" in n for n in dbl["notes"])
    assert found[0]["total"] > dbl["total"]


def test_web_mode_falls_back_until_comps_are_found():
    out = compmodes.top("web", _pools(), "Ascent", web={})
    assert out[0]["web_missing"] and compmodes.NO_WEB_NOTE in out[0]["notes"]
    web = {"ascent": {"comps": [{"agents": ["Jett", "Sova", "Skye", "Omen", "Killjoy"], "note": "n", "sources": []}],
                      "at": 1.0}}
    out = compmodes.top("web", _pools(), "Ascent", web=web)
    assert out[0]["method"] == "web" and not out[0].get("web_missing")
    plan = compmodes.plan("web", _pools(), [], ["Ascent", "Haven"], {}, {}, web=web)
    assert plan[0]["main"]["method"] == "web" and plan[1]["main"].get("web_missing")


def test_fetch_uses_search_and_model():
    calls = []

    def search(q, n=6):
        calls.append(q)
        return [{"title": f"t{len(calls)}", "url": f"https://s.example/{len(calls)}", "snippet": "s"}]

    class LLM:
        model = "x"

        def chat_json(self, system, user, schema):
            assert "Lotus" in system and "[1]" in user
            return {"comps": [{"agents": ["Raze", "Fade", "Omen", "Viper", "Killjoy"], "note": "n", "sources": [1, 2]}]}

    out = webcomps.fetch(search, LLM(), "Lotus", reader=lambda url, limit: "page text")
    assert len(calls) == len(webcomps.QUERIES) and all("Lotus" in q for q in calls)
    assert out["comps"][0]["agents"][0] == "Raze" and len(out["comps"][0]["sources"]) == 2
    assert out["model"] == "x" and len(out["sources"]) == 3


def test_method_of_unknown_falls_back():
    class T:
        comp_method = "nonsense"
    assert compmodes.method_of(T()) == "rules"
    T.comp_method = "comfort"
    assert compmodes.method_of(T()) == "comfort"


def test_replay_paths_stay_inside_the_folder(tmp_path):
    good = "12b3659c-735e-432a-8f55-91425f8934df"
    assert replayfile.data_file(tmp_path, good.upper()).parent == tmp_path.resolve()
    for bad in ("../../etc/passwd", "..", "", "12b3659c-735e-432a-8f55-91425f8934df/../x", "a" * 65, "x.y", "a\\b"):
        with pytest.raises(replayfile.ReplayError):
            replayfile.vrf_file(tmp_path, bad)
        assert replayfile.has_replay(tmp_path, bad) is False


def _follow(pools, edits):
    """4.14: "Follow our agent pools" as the web app sets it: each Pool gets its player's pool."""
    from nexus.stats import compsheet
    for p in pools:
        rows = [{"agent": a, "won": int(p.w[a] * 2 > p.n[a]), "kills": 1, "deaths": 1, "rounds": 1, "acs": 1}
                for a in p.n for _ in range(p.n[a])]
        p.pref = compsheet.prefs(rows, edits.get(p.label))
    return pools


@pytest.mark.parametrize("mode", ["rules", "comfort", "stats"])
def test_followed_pools_count_in_every_mode(mode):
    plain = compmodes.top(mode, _pools(), "Ascent")[0]
    assert picks(plain)["ctrl"] in ("Omen", "Viper") and picks(plain)["duel"] == "Jett"
    # ctrl won't play Omen or Viper but added Astra; duel put Raze first
    pools = _follow(_pools(), {"ctrl": {"order": ["Astra"], "no": ["Omen", "Viper"]},
                               "duel": {"order": ["Raze", "Jett"], "no": []}})
    comp = compmodes.top(mode, pools, "Ascent")[0]
    assert picks(comp)["ctrl"] == "Astra"                          # added by hand, no games: still picked
    assert any("agent pool" in w for p in comp["picks"] for w in p["why"])
    plan = compmodes.plan(mode, pools, [], ["Ascent"], {}, {})
    assert "Omen" not in picks(plan[0]["main"]).values() and "Viper" not in picks(plan[0]["main"]).values()
    if mode == "comfort":                    # most comfortable: the player's own order beats the games played
        assert picks(comp)["duel"] == "Raze" and "#1 in duel's agent pool" in comp["picks"][1]["why"]


def test_followed_pools_with_web_comps():
    data = {"comps": [{"agents": ["Jett", "Sova", "Astra", "Killjoy", "Skye"], "note": "", "sources": []}]}
    plain = webcomps.comps_for(_pools(), "Ascent", data)[0]
    assert next(p for p in plain["picks"] if p["agent"] == "Astra")["new"]
    pools = _follow(_pools(), {"ctrl": {"order": ["Astra", "Omen"], "no": []}})
    comp = webcomps.comps_for(pools, "Ascent", data)[0]
    astra = next(p for p in comp["picks"] if p["agent"] == "Astra")
    assert astra["player"] == "ctrl" and not astra["new"] and comp["total"] > plain["total"]
    # nobody gets an agent he won't play when there's another way
    pools = _follow(_pools(), {"flex": {"order": None, "no": ["Skye"]}})
    comp = webcomps.comps_for(pools, "Ascent", data)[0]
    assert picks(comp)["flex"] != "Skye"


def test_pools_not_followed_change_nothing():
    a = compmodes.top("rules", _pools(), "Ascent")
    b = compmodes.top("rules", _pools(), "Ascent")
    assert [picks(c) for c in a] == [picks(c) for c in b] and all(p.pref is None for p in _pools())
