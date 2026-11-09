"""Team comps per map (Premier, with substitutes) and the solo-queue pick helper.

How an agent is rated for a player on a map (all win rates pulled towards 50 %):
  * win rate with that agent on that map, pulled towards their win rate with that agent anywhere
  * ACS with it there, relative to the player's normal ACS
  * comfort: how many games they have on the agent at all
  * meta: how often it's played on that map in your matches, plus your own preferences (meta file)
A comp must cover the roles (by default at least one Controller, Initiator and Sentinel; a
Duelist is a bonus). The best combination of distinct agents wins.

4.9: with `rules` (a comprules.MapRules, the team's "Comp suggestions" = Map rules + your stats) the map's
rules are added: needed / key agents per map, the role mixes that work there and what every comp needs
(see comprules.py). Without it (Your stats only) everything works exactly as before.

4.10: with `comfort` (Most comfortable) an agent is rated only by how much the player plays it: games on
this map count most, then games overall. Win rate and ACS don't count. The basic roles still do.
From the web: see webcomps.py; all modes are picked in compmodes.py.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field

import yaml

from . import roles
from .aggregate import PRIOR_GAMES, smooth

CANDIDATES = 6             # agents per player considered for a comp
MISSING_ROLE = {"Controller": 28, "Initiator": 16, "Sentinel": 16, "Duelist": 0}
DUELIST_BONUS = 6
PATTERN_PENALTY = 30       # per role slot off the role mix set in the meta file (you asked for it explicitly)
PICK_NEED = {"Controller": 30, "Initiator": 18, "Sentinel": 18, "Duelist": 12}
COMFORT_MAP = 6            # Most comfortable (4.10): points per game on this map ...
COMFORT_ALL = 1.5          # ... and per game overall
COMFORT_CAP = 40           # games counted at most (so one main doesn't drown out the roles)

META_EXAMPLE = """# Optional: your own map meta. Agents and role patterns here override what the stats suggest.
# roles: D = Duelist, I = Initiator, C = Controller, S = Sentinel (must add up to 5)
# Ascent:
#   prefer: [Sova, KAY/O, Killjoy]
#   avoid: [Reyna]
#   roles: 1D 2I 1C 1S
# Lotus:
#   roles: 1D 1I 2C 1S
"""


@dataclass
class Pool:
    """One player's agent pool from their game rows."""
    label: str
    n: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    w: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    acs: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    nm: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    wm: dict[tuple, float] = field(default_factory=lambda: defaultdict(float))
    acsm: dict[tuple, float] = field(default_factory=lambda: defaultdict(float))
    mean_acs: float = 200.0
    games: int = 0

    @classmethod
    def from_rows(cls, label: str, rows: list[dict]) -> "Pool":
        p = cls(label)
        tot = 0.0
        for r in rows:
            a, m = r["agent"], r["map"].lower()
            p.n[a] += 1
            p.w[a] += r["won"]
            p.acs[a] += r["acs"]
            p.nm[(m, a)] += 1
            p.wm[(m, a)] += r["won"]
            p.acsm[(m, a)] += r["acs"]
            tot += r["acs"]
        p.games = len(rows)
        p.mean_acs = tot / len(rows) if rows else 200.0
        return p


def parse_meta(text: str) -> dict[str, dict]:
    """User meta file -> {map_lower: {"prefer": set, "avoid": set, "roles": {role: n} | None}}."""
    if not (text or "").strip():
        return {}
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("the meta file must map map names to settings")
    out = {}
    for m, v in data.items():
        v = v or {}
        if not isinstance(v, dict):
            raise ValueError(f"{m}: expected prefer / avoid / roles")
        pat = None
        if v.get("roles"):
            pat = {}
            for part in str(v["roles"]).split():
                if len(part) < 2 or not part[:-1].isdigit() or part[-1].upper() not in "DICS":
                    raise ValueError(f"{m}: roles look like '1D 2I 1C 1S'")
                pat[{"D": "Duelist", "I": "Initiator", "C": "Controller", "S": "Sentinel"}[part[-1].upper()]] = int(part[:-1])
            if sum(pat.values()) != 5:
                raise ValueError(f"{m}: roles must add up to 5")
        out[str(m).lower()] = {"prefer": {str(a).lower() for a in v.get("prefer") or []},
                               "avoid": {str(a).lower() for a in v.get("avoid") or []}, "roles": pat}
    return out


def rate(pool: Pool, agent: str, map_name: str, local: dict | None = None, meta: dict | None = None,
         rules=None, comfort_only: bool = False) -> dict:
    """Score and the numbers behind it. comfort_only (4.10): only how much the player plays the agent."""
    m = map_name.lower()
    n_a, n_am = pool.n.get(agent, 0), pool.nm.get((m, agent), 0)
    wr_a = smooth(pool.w.get(agent, 0), n_a)
    wr_am = smooth(pool.wm.get((m, agent), 0), n_am, prior=wr_a)
    acs_a = (pool.acs.get(agent, 0) + pool.mean_acs * PRIOR_GAMES) / (n_a + PRIOR_GAMES)
    acs_am = (pool.acsm.get((m, agent), 0) + acs_a * PRIOR_GAMES) / (n_am + PRIOR_GAMES)
    rel = acs_am / pool.mean_acs if pool.mean_acs else 1.0
    comfort = min(1.0, n_a / 15)
    score = 100 * (wr_am - 0.5) + 40 * (rel - 1) + 10 * comfort
    why = []
    share = 0.0
    if comfort_only:
        score = COMFORT_MAP * min(n_am, COMFORT_CAP) + COMFORT_ALL * min(n_a, COMFORT_CAP)
        why.append(f"{n_am} games on {map_name}, {n_a} overall")
    if local and not comfort_only:
        share = next((x["share"] for x in local.get("agents", []) if x["agent"] == agent), 0.0)
        score += 8 * min(1.0, share / 0.4)
    if meta:
        if agent.lower() in meta.get("prefer", set()):
            score += 10
            why.append("preferred in your meta")
        if agent.lower() in meta.get("avoid", set()):
            score -= 200                  # practically excluded
            why.append("avoided in your meta")
    if rules is not None:
        pts, reason = rules.agent_bonus(agent)
        if pts:
            score += pts
            why.append(reason)
    return {"agent": agent, "role": roles.role_of(agent), "score": round(score, 1), "n_map": n_am, "n_all": n_a,
            "wr_map": pool.wm.get((m, agent), 0) / n_am if n_am else None,
            "acs_map": pool.acsm.get((m, agent), 0) / n_am if n_am else None,
            "wr_all": pool.w.get(agent, 0) / n_a if n_a else None, "meta_share": share, "why": why}


def _role_score(agents: list[str], pattern: dict | None, rules=None) -> tuple[float, list[str], list[str]]:
    """(points, missing roles, notes). notes only come from map rules (4.9)."""
    counts = defaultdict(int)
    for a in agents:
        counts[roles.role_of(a)] += 1
    if pattern:
        off = sum(abs(counts.get(r, 0) - pattern.get(r, 0)) for r in roles.ROLES) / 2
        missing = [f"{pattern[r] - counts.get(r, 0)} more {r}" for r in roles.ROLES
                   if counts.get(r, 0) < pattern.get(r, 0)]
        pen, notes = -PATTERN_PENALTY * off, []
        if rules is not None:                 # your own role mix decides the roles; the other map rules still count
            extra, notes, _ = rules.comp_score(agents, pattern)
            pen += extra
        return pen, missing, notes
    if rules is not None:
        pts, notes, missing = rules.comp_score(agents)
        return pts, missing, notes
    pen, missing = 0.0, []
    for r, p in MISSING_ROLE.items():
        if counts.get(r, 0) == 0 and p:
            pen -= p
            missing.append(r)
    if counts.get("Duelist", 0):
        pen += DUELIST_BONUS
    return pen, missing, []


def best_comp(players: list[Pool], map_name: str, local: dict | None = None, meta: dict | None = None,
              rules=None, comfort_only: bool = False) -> dict:
    """Best distinct-agent assignment for these players on this map (rules: comprules.MapRules or None;
    comfort_only: rate by games played only)."""
    cands, no_data = [], []
    for p in players:
        if not p.n:
            no_data.append(p.label)
            cands.append([])
            continue
        rated = sorted((rate(p, a, map_name, local, meta, rules, comfort_only) for a in p.n), key=lambda x: -x["score"])
        cands.append(rated[:CANDIDATES])
    if no_data:
        return {"map": map_name, "ok": False, "no_data": no_data}
    pattern = (meta or {}).get("roles")
    best = exact = None
    for combo in itertools.product(*cands):
        agents = [c["agent"] for c in combo]
        if len(set(agents)) < len(agents):
            continue
        rs, missing, notes = _role_score(agents, pattern, rules)
        total = sum(c["score"] for c in combo) + rs
        if best is None or total > best[0]:
            best = (total, combo, missing, notes)
        if pattern and not missing and (exact is None or total > exact[0]):
            exact = (total, combo, missing, notes)
    if exact is not None:
        best = exact                 # a role mix you set is followed whenever the pools allow it
    if best is None:
        return {"map": map_name, "ok": False, "no_data": [], "reason": "not enough different agents in the pools"}
    total, combo, missing, notes = best
    picks = [{"player": p.label, **c, "low_sample": c["n_map"] < 2 and c["n_all"] < 5,
              "alternatives": [x["agent"] for x in cand if x["agent"] != c["agent"]][:2]}
             for p, c, cand in zip(players, combo, cands)]
    from .aggregate import pattern as pat_str
    return {"map": map_name, "ok": True, "total": round(total, 1), "picks": picks, "missing_roles": missing,
            "pattern": pat_str([c["agent"] for c in combo]), "notes": notes,
            "method": "comfort" if comfort_only else ("rules" if rules is not None else "stats")}


def team_plan(starters: list[Pool], subs: list[Pool], maps: list[str], local: dict[str, dict],
              meta: dict[str, dict], rules: dict | None = None, solve=None) -> list[dict]:
    """Per map: the starters' comp, and for each starter the best fill-in from the subs.
    rules: the parsed map rules (comprules.load_rules) for the "Map rules + your stats" method, None = stats only.
    solve(lineup, map, local, meta) -> comp: another way to make a comp (4.10, see compmodes.py)."""
    from .comprules import for_map
    out = []
    for m in maps:
        lm, mm = local.get(m), meta.get(m.lower())
        mr = for_map(rules, m) if rules is not None else None
        if solve is None:
            def one(lineup, _m=m, _lm=lm, _mm=mm, _mr=mr):
                return best_comp(lineup, _m, _lm, _mm, _mr)
        else:
            def one(lineup, _m=m, _lm=lm, _mm=mm):
                return solve(lineup, _m, _lm, _mm)
        main = one(starters)
        fills = []
        if main.get("ok"):
            for i, missing in enumerate(starters):
                best = None
                for s in subs:
                    lineup = starters[:i] + [s] + starters[i + 1:]
                    c = one(lineup)
                    if c.get("ok") and (best is None or c["total"] > best[1]["total"]):
                        best = (s, c)
                if best:
                    s, c = best
                    before = {p["player"]: p["agent"] for p in main["picks"]}
                    changes = [f"{p['player']}: {before[p['player']]} → {p['agent']}" for p in c["picks"]
                               if p["player"] in before and before[p["player"]] != p["agent"]]
                    sub_pick = next(p for p in c["picks"] if p["player"] == s.label)
                    fills.append({"out": missing.label, "sub": s.label, "sub_agent": sub_pick["agent"],
                                  "changes": changes, "comp": c, "drop": round(main["total"] - c["total"], 1)})
        out.append({"map": m, "main": main, "fills": fills,
                    "local": lm, "meta": {k: sorted(v) if isinstance(v, set) else v for k, v in (mm or {}).items()}})
    return out


def pick_helper(pool: Pool, map_name: str, locked: list[str], local: dict | None = None,
                meta: dict | None = None, top: int = 4, rules=None) -> dict:
    """Solo queue: what to lock from your pool given what your teammates already locked."""
    have = defaultdict(int)
    for a in locked:
        have[roles.role_of(a)] += 1
    need = [r for r in ("Controller", "Initiator", "Sentinel", "Duelist") if not have.get(r)]
    slots_left = 5 - len(locked)
    out = []
    for a in pool.n:
        if a in locked:
            continue
        r = rate(pool, a, map_name, local, meta, rules)
        role = r["role"]
        bonus = 0.0
        tight = slots_left <= len(need)          # every remaining pick must fill a missing role
        if role in need:
            bonus = PICK_NEED.get(role, 0) * (1.5 if tight else 1.0)
        elif tight:
            bonus = -60
        elif have.get(role, 0) >= 2:
            bonus = -15
        r["fit"] = round(r["score"] + bonus, 1)
        r["fills"] = role in need
        out.append(r)
    out.sort(key=lambda x: -x["fit"])
    pool_roles = {roles.role_of(a) for a in pool.n}
    uncovered = []
    for r in need:
        if r not in pool_roles and r != "Duelist":
            sugg = [x["agent"] for x in (local or {}).get("agents", []) if x["role"] == r and x["agent"] not in locked][:2]
            uncovered.append({"role": r, "suggest": sugg})
    return {"map": map_name, "locked": locked, "need": need, "picks": out[:top], "uncovered": uncovered,
            "pool_size": len(pool.n), "games": pool.games}


def top_comps(players: list[Pool], map_name: str, local: dict | None = None, meta: dict | None = None,
              n: int = 3, min_diff: int = 2, rules=None, comfort_only: bool = False) -> list[dict]:
    """The n best comps that differ from each other by at least `min_diff` agents."""
    best = best_comp(players, map_name, local, meta, rules, comfort_only)
    if not best.get("ok"):
        return [best]
    cands = []
    for p in players:
        rated = sorted((rate(p, a, map_name, local, meta, rules, comfort_only) for a in p.n), key=lambda x: -x["score"])
        cands.append(rated[:CANDIDATES])
    pattern = (meta or {}).get("roles")
    scored = []
    for combo in itertools.product(*cands):
        agents = [c["agent"] for c in combo]
        if len(set(agents)) < len(agents):
            continue
        rs, missing, notes = _role_score(agents, pattern, rules)
        if pattern and missing:
            continue
        scored.append((sum(c["score"] for c in combo) + rs, combo, missing, notes))
    scored.sort(key=lambda x: -x[0])
    from .aggregate import pattern as pat_str
    chosen = [best]
    for total, combo, missing, notes in scored:
        if len(chosen) >= n:
            break
        agents = {c["agent"] for c in combo}
        if all(len(agents - {p["agent"] for p in c["picks"]}) >= min_diff for c in chosen):
            chosen.append({"map": map_name, "ok": True, "total": round(total, 1), "missing_roles": missing,
                           "pattern": pat_str([c["agent"] for c in combo]), "notes": notes,
                           "method": "comfort" if comfort_only else ("rules" if rules is not None else "stats"),
                           "picks": [{"player": p.label, **c, "low_sample": c["n_map"] < 2 and c["n_all"] < 5, "alternatives": []}
                                     for p, c in zip(players, combo)]})
    return chosen
