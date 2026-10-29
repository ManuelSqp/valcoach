"""Aggregates over game rows: per map, per agent, sides, opening duels, death spots,
plus short plain-language observations (only where the sample is big enough)."""
from __future__ import annotations

from collections import Counter, defaultdict

from . import roles

PRIOR_GAMES = 4            # win rates are pulled towards 50 % by this many virtual games
MIN_GAMES_AGENT = 3        # show an agent's numbers as meaningful from here on


def smooth(wins: float, n: int, prior: float = 0.5, k: float = PRIOR_GAMES) -> float:
    return (wins + prior * k) / (n + k)


def filter_rows(rows: list[dict], queue: str = "all") -> list[dict]:
    if queue in ("competitive", "premier"):
        return [r for r in rows if r.get("queue") == queue]
    return [r for r in rows if r.get("queue") in ("competitive", "premier")]


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"games": 0}
    wins = sum(r["won"] for r in rows)
    kills, deaths = sum(r["kills"] for r in rows), sum(r["deaths"] for r in rows)
    rounds = sum(r["rounds"] for r in rows)
    full = [r for r in rows if r.get("source") == "full"]
    full_rounds = sum(r["rounds"] for r in full)
    out = {
        "games": n, "wins": wins, "wr": wins / n, "wr_s": smooth(wins, n),
        "acs": sum(r["acs"] * r["rounds"] for r in rows) / rounds if rounds else 0,
        "kd": kills / deaths if deaths else float(kills),
        "adr": sum(r.get("adr", 0) * r["rounds"] for r in rows) / rounds if rounds else 0,
        "full": len(full),
    }
    if full_rounds:
        out["kast"] = sum(r["kast"] for r in full) / full_rounds
        fk, fd = sum(r["fk"] for r in full), sum(r["fd"] for r in full)
        out["fk"], out["fd"] = fk, fd
        out["opening_rate"] = (fk + fd) / full_rounds          # share of rounds you take the first duel
        out["opening_wr"] = fk / (fk + fd) if fk + fd else None
    return out


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[r.get(key) or "?"].append(r)
    return g


def by_map(rows: list[dict]) -> list[dict]:
    out = []
    for m, rs in _group(rows, "map").items():
        s = summary(rs)
        agents = sorted(((a, summary(x)) for a, x in _group(rs, "agent").items()), key=lambda kv: -kv[1]["games"])
        s.update(map=m, agents=[{"agent": a, "role": roles.role_of(a), **x} for a, x in agents[:3]])
        out.append(s)
    return sorted(out, key=lambda s: -s["games"])


def by_agent(rows: list[dict]) -> list[dict]:
    out = []
    for a, rs in _group(rows, "agent").items():
        s = summary(rs)
        s.update(agent=a, role=roles.role_of(a))
        out.append(s)
    return sorted(out, key=lambda s: -s["games"])


def by_role(rows: list[dict]) -> list[dict]:
    out = []
    for role, rs in _group([dict(r, role=roles.role_of(r["agent"])) for r in rows], "role").items():
        s = summary(rs)
        s.update(role=role)
        out.append(s)
    return sorted(out, key=lambda s: -s["games"])


def _areas(items: list[list], side: str, flag_index: int | None = None) -> list[dict]:
    c: Counter = Counter()
    good: Counter = Counter()
    for it in items:
        if it[0] != side:
            continue
        c[it[1]] += 1
        if flag_index is not None and it[flag_index]:
            good[it[1]] += 1
    total = sum(c.values())
    return [{"area": a, "n": n, "share": n / total, "good": good[a], "rate": good[a] / n}
            for a, n in c.most_common(8)]


def map_detail(rows: list[dict], map_name: str) -> dict:
    rs = [r for r in rows if r.get("map") == map_name]
    full = [r for r in rs if r.get("source") == "full"]
    d = {"map": map_name, "summary": summary(rs), "agents": by_agent(rs), "n_full": len(full)}
    sides = {}
    for side in ("attack", "defense"):
        played = sum(r["sides"][side][0] for r in full)
        won = sum(r["sides"][side][1] for r in full)
        sides[side] = {"rounds": played, "won": won, "wr": won / played if played else None}
    d["sides"] = sides
    openings = [o for r in full for o in r["openings"]]
    deaths = [x for r in full for x in r["deaths_at"]]
    kills = [x for r in full for x in r["kills_at"]]
    d["openings"] = {s: _areas(openings, s, 2) for s in ("attack", "defense")}
    d["deaths"] = {s: _areas(deaths, s, 2) for s in ("attack", "defense")}       # good = traded
    d["kills"] = {s: _areas(kills, s) for s in ("attack", "defense")}
    d["observations"] = observations(d)
    return d


def observations(d: dict) -> list[dict]:
    """Deterministic findings with their evidence. kind: good | bad | info."""
    out: list[dict] = []
    s, m = d["summary"], d["map"]
    if not s.get("games"):
        return out
    a, df = d["sides"]["attack"], d["sides"]["defense"]
    if a["rounds"] >= 40 and df["rounds"] >= 40 and abs(a["wr"] - df["wr"]) >= 0.12:
        strong, weak = ("attack", "defense") if a["wr"] > df["wr"] else ("defense", "attack")
        out.append({"kind": "info", "text": f"Your team wins {d['sides'][strong]['wr']:.0%} of {strong} rounds but only "
                    f"{d['sides'][weak]['wr']:.0%} of {weak} rounds on {m}.",
                    "evidence": f"{a['rounds']} attack / {df['rounds']} defense rounds"})
    if s.get("opening_wr") is not None and s["fk"] + s["fd"] >= 8:
        n = s["fk"] + s["fd"]
        if s["opening_wr"] < 0.42:
            out.append({"kind": "bad", "text": f"You take the first duel in {s['opening_rate']:.0%} of rounds and win only "
                        f"{s['opening_wr']:.0%} of them.", "evidence": f"{s['fk']} first kills, {s['fd']} first deaths"})
        elif s["opening_wr"] > 0.58:
            out.append({"kind": "good", "text": f"You win {s['opening_wr']:.0%} of your opening duels.",
                        "evidence": f"{s['fk']} first kills, {s['fd']} first deaths in {n} openings"})
    for side in ("attack", "defense"):
        for o in d["openings"][side][:2]:
            if o["n"] >= 4 and o["share"] >= 0.25 and o["area"] != "?":
                if o["rate"] <= 0.35:
                    out.append({"kind": "bad", "text": f"On {side}, {o['n']} of your opening duels are at {o['area']} and you win "
                                f"{o['good']} of them.", "evidence": f"{o['rate']:.0%} won"})
                elif o["rate"] >= 0.65:
                    out.append({"kind": "good", "text": f"On {side} you win {o['good']} of {o['n']} opening duels at {o['area']}.",
                                "evidence": f"{o['rate']:.0%} won"})
        for x in d["deaths"][side][:1]:
            if x["n"] >= 5 and x["share"] >= 0.25 and x["area"] != "?" and x["rate"] < 0.3:
                out.append({"kind": "bad", "text": f"Your most common death on {side} is {x['area']} ({x['n']} deaths), traded only "
                            f"{x['rate']:.0%} of the time.", "evidence": f"{x['share']:.0%} of your {side} deaths"})
    if s.get("kast") is not None and s["full"] >= 5:
        if s["kast"] < 0.65:
            out.append({"kind": "bad", "text": f"KAST {s['kast']:.0%}: in about a third of rounds you die without a kill, assist or trade.",
                        "evidence": f"{s['full']} games with full data"})
        elif s["kast"] > 0.75:
            out.append({"kind": "good", "text": f"KAST {s['kast']:.0%}: you contribute in most rounds.",
                        "evidence": f"{s['full']} games with full data"})
    pool = [x for x in d["agents"] if x["games"] >= MIN_GAMES_AGENT]
    if len(pool) >= 2:
        best = max(pool, key=lambda x: x["wr_s"])
        if best["wr_s"] - s["wr_s"] >= 0.06:
            out.append({"kind": "good", "text": f"{best['agent']} is your best agent here: {best['wins']:.0f}-"
                        f"{best['games'] - best['wins']:.0f} ({best['wr']:.0%}), ACS {best['acs']:.0f}.",
                        "evidence": f"map average {s['wr']:.0%} over {s['games']} games"})
        worst = min(pool, key=lambda x: x["wr_s"])
        if s["wr_s"] - worst["wr_s"] >= 0.08 and worst is not best:
            out.append({"kind": "bad", "text": f"{worst['agent']} hasn't worked here: {worst['wins']:.0f}-"
                        f"{worst['games'] - worst['wins']:.0f} ({worst['wr']:.0%}), ACS {worst['acs']:.0f}.",
                        "evidence": f"map average {s['wr']:.0%}"})
    return out


# ---------------------------------------------------------------------------
# what's played at your level (from full matches: all 10 players)
# ---------------------------------------------------------------------------
def local_meta(rows: list[dict]) -> dict[str, dict]:
    """map -> {"games", "agents": [{agent, role, picks, share, wr}], "patterns": [{pattern, n, wr}]}.
    Rows of several players may contain the same match: it is counted once."""
    seen: set[str] = set()
    per_map: dict[str, dict] = {}
    for r in rows:
        if r.get("source") != "full" or not r.get("own_agents") or r["match_id"] in seen:
            continue
        seen.add(r["match_id"])
        m = per_map.setdefault(r["map"], {"games": 0, "picks": Counter(), "wins": Counter(),
                                          "pat": Counter(), "pat_w": Counter()})
        m["games"] += 1
        for agents, won in ((r["own_agents"], r["won"]), (r["opp_agents"], 1 - r["won"])):
            for a in agents:
                m["picks"][a] += 1
                m["wins"][a] += won
            pat = pattern(agents)
            m["pat"][pat] += 1
            m["pat_w"][pat] += won
    out = {}
    for name, m in per_map.items():
        teams = 2 * m["games"]
        out[name] = {
            "games": m["games"],
            "agents": [{"agent": a, "role": roles.role_of(a), "picks": n, "share": n / teams,
                        "wr": m["wins"][a] / n} for a, n in m["picks"].most_common()],
            "patterns": [{"pattern": p, "n": n, "wr": m["pat_w"][p] / n} for p, n in m["pat"].most_common(5)],
        }
    return out


def pattern(agents: list[str]) -> str:
    """Role pattern of a comp, e.g. '1D 2I 1C 1S'."""
    c = Counter(roles.role_of(a) for a in agents)
    return " ".join(f"{c.get(r, 0)}{r[0]}" for r in roles.ROLES)
