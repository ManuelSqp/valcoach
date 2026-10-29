"""Team roles (IGL, entry, lurker, anchor, ...): how well each player fits each role, a
suggested lineup, and an agent worth learning.

Scores are 0-100 from what players actually do in their games with round data:
  Entry         first of the team into the fight on attack, many opening duels
  Second entry  trades teammates (kills the player who just killed a teammate)
  Lurker        fights far away from the team on attack
  Anchor        holds the same site on defense and survives there
  Support       assists, trades, plays initiators / controllers
  Operator      buys and gets kills with the Operator
  Flex          plays several agent roles at a decent level
  IGL           can't be measured (no comms): "could call" from traits that make calling
                easier - alive late in rounds, not first into fights, controller / initiator, KAST
Roles you assign on the team page always win; the scores are a suggestion and a check.
"""
from __future__ import annotations

from collections import Counter

from scipy.optimize import linear_sum_assignment

from . import roles as agent_roles

TEAM_ROLES = ["IGL", "Entry", "Second entry", "Lurker", "Anchor", "Support", "Operator", "Flex"]
PRIMARY = ["Entry", "Second entry", "Lurker", "Anchor", "Support"]   # one each in a lineup of 5
HATS = ["IGL", "Operator"]                                            # worn on top of a primary role
MIN_GAMES = 5
SITES = ("A", "B", "C")

ROLE_AGENTS = {          # which agent roles suit a team role (first = most natural)
    "Entry": ["Duelist", "Initiator"],
    "Second entry": ["Initiator", "Duelist"],
    "Lurker": ["Sentinel", "Duelist"],
    "Anchor": ["Sentinel", "Controller"],
    "Support": ["Initiator", "Controller"],
    "IGL": ["Controller", "Initiator"],
    "Operator": ["Sentinel", "Duelist"],
    "Flex": ["Initiator", "Controller", "Sentinel", "Duelist"],
}
FALLBACK_AGENTS = {      # when nobody at your level plays the role, start with these (easy to learn first)
    "Duelist": ["Phoenix", "Reyna", "Raze", "Jett"], "Initiator": ["Sova", "Skye", "Breach", "Fade"],
    "Controller": ["Omen", "Brimstone", "Clove", "Viper"], "Sentinel": ["Killjoy", "Sage", "Cypher", "Vyse"],
}
DESCRIPTION = {
    "IGL": "makes the calls: sets the default, reads the enemy and adapts mid-round",
    "Entry": "first into the site, takes the opening duel so the team can follow",
    "Second entry": "right behind the entry, trades him and takes the next angle",
    "Lurker": "plays away from the team on attack, cuts rotations and flanks with timing",
    "Anchor": "holds one site on defense, stays alive and delays until help arrives",
    "Support": "plays utility for the others, flashes, recons and trades",
    "Operator": "holds long angles with the Operator, takes the first pick from range",
    "Flex": "fills whatever the comp needs on the day",
}


def _n(v: float | None, lo: float, hi: float) -> float:
    """Map v from [lo, hi] onto [0, 1] (clipped)."""
    if v is None:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def metrics(rows: list[dict]) -> dict:
    full = [r for r in rows if r.get("source") == "full" and r.get("v", 1) >= 2]
    out: dict = {"games": len(rows), "full": len(full)}
    if not full:
        return out
    att_r = sum(r["sides"]["attack"][0] for r in full) or 1
    def_r = sum(r["sides"]["defense"][0] for r in full) or 1
    rounds = sum(r["rounds"] for r in full) or 1
    kills = sum(r["kills"] for r in full) or 1
    att_open = sum(1 for r in full for o in r["openings"] if o[0] == "attack")
    iso_a = [sum(r["iso"]["attack"][i] for r in full) for i in range(4)]
    zones = Counter(z for r in full for z in r.get("def_zones", []) if z in SITES)
    site, site_n = (zones.most_common(1)[0] if zones else (None, 0))
    agents = Counter(r["agent"] for r in rows)
    role_share = Counter()
    for a, n in agents.items():
        role_share[agent_roles.role_of(a)] += n / len(rows)
    out.update({
        "first_in_att": sum(r["first_in"]["attack"] for r in full) / att_r,
        "opening_att": att_open / att_r,
        "trade_share": sum(r["trade_kills"] for r in full) / kills,
        "iso_att": (iso_a[1] + iso_a[3]) / (iso_a[0] + iso_a[2]) if iso_a[0] + iso_a[2] else None,
        "iso_att_kills": iso_a[1] / iso_a[0] if iso_a[0] else None,
        "def_site": site, "def_site_focus": site_n / sum(zones.values()) if zones else None,
        "def_survive": sum(r["survived"]["defense"] for r in full) / def_r,
        "survive": sum(r["survived"]["attack"] + r["survived"]["defense"] for r in full) / rounds,
        "apr": sum(r["assists"] for r in full) / rounds,
        "kast": sum(r["kast"] for r in full) / rounds,
        "op_share": sum(r["op_rounds"] for r in full) / rounds,
        "op_kills": sum(r["op_kills"] for r in full),
        "role_share": dict(role_share),
        "roles_played": sum(1 for v in role_share.values() if v >= 0.15),
    })
    return out


def scores(m: dict) -> dict[str, dict]:
    """role -> {"score": 0-100, "evidence": [...]}. Empty when there's too little round data."""
    if m.get("full", 0) < MIN_GAMES:
        return {}
    rs = m["role_share"]
    pct = lambda v: "–" if v is None else f"{v:.0%}"   # noqa: E731
    out = {
        "Entry": (0.5 * _n(m["first_in_att"], 0.12, 0.40) + 0.3 * _n(m["opening_att"], 0.10, 0.35)
                  + 0.2 * rs.get("Duelist", 0),
                  [f"in the team's first fight in {pct(m['first_in_att'])} of attack rounds",
                   f"opening duel in {pct(m['opening_att'])} of attack rounds"]),
        "Second entry": (0.55 * _n(m["trade_share"], 0.08, 0.30) + 0.25 * _n(m["opening_att"], 0.05, 0.25)
                         + 0.2 * (rs.get("Initiator", 0) + rs.get("Duelist", 0)),
                         [f"{pct(m['trade_share'])} of your kills are trades for a teammate"]),
        "Lurker": (0.6 * _n(m["iso_att"], 0.15, 0.50) + 0.2 * _n(m["iso_att_kills"], 0.10, 0.45)
                   + 0.2 * rs.get("Sentinel", 0),
                   [f"{pct(m['iso_att'])} of your attack fights are 20 m+ away from the team",
                    f"{pct(m['iso_att_kills'])} of your attack kills come from there"]),
        "Anchor": (0.45 * _n(m["def_site_focus"], 0.40, 0.80) + 0.35 * _n(m["def_survive"], 0.20, 0.50)
                   + 0.2 * rs.get("Sentinel", 0),
                   [f"{pct(m['def_site_focus'])} of your defense fights on {m['def_site'] or '?'} site",
                    f"alive at the end of {pct(m['def_survive'])} of defense rounds"]),
        "Support": (0.5 * _n(m["apr"], 0.15, 0.40) + 0.3 * _n(m["trade_share"], 0.08, 0.30)
                    + 0.2 * (rs.get("Initiator", 0) + rs.get("Controller", 0)),
                    [f"{m['apr']:.2f} assists per round", f"{pct(m['trade_share'])} of kills are trades"]),
        "Operator": (_n(m["op_share"], 0.03, 0.35),
                     [f"Operator in {pct(m['op_share'])} of rounds, {m['op_kills']} Operator kills"]),
        "Flex": (0.7 * _n(m["roles_played"], 1, 3.5) + 0.3 * _n(m["kast"], 0.62, 0.78),
                 [f"plays {m['roles_played']} agent roles regularly"]),
        "IGL": (0.35 * _n(m["survive"], 0.22, 0.45) + 0.25 * (rs.get("Controller", 0) + rs.get("Initiator", 0))
                + 0.2 * _n(m["kast"], 0.62, 0.78) + 0.2 * (1 - _n(m["opening_att"], 0.08, 0.30)),
                [f"alive at round end in {pct(m['survive'])} of rounds", f"KAST {pct(m['kast'])}",
                 "a guess from traits: who calls well only shows in comms"]),
    }
    return {k: {"score": round(100 * min(1.0, v)), "evidence": ev} for k, (v, ev) in out.items()}


def suggest_lineup(players: list[dict]) -> dict:
    """players: [{label, scores, assigned}] (starters). Primary role per player (one each) and the hats."""
    have = [p for p in players if p["scores"]]
    if len(have) < 2:
        return {}
    # roles you assigned are fixed; the others are filled by the best fit (one per role)
    primary, taken = {}, set()
    for p in have:
        fixed = next((r for r in p.get("assigned", []) if r in PRIMARY and r not in taken), None)
        if fixed:
            primary[p["label"]] = fixed
            taken.add(fixed)
    free_p = [p for p in have if p["label"] not in primary]
    free_r = [r for r in PRIMARY if r not in taken]
    if free_p and free_r:
        ri, ci = linear_sum_assignment([[-p["scores"][r]["score"] for r in free_r] for p in free_p])
        for i, j in zip(ri, ci):
            primary[free_p[i]["label"]] = free_r[j]
    hats = {}
    for h in HATS:
        fixed = next((p["label"] for p in players if h in p.get("assigned", [])), None)
        if fixed:
            hats[h] = fixed
            continue
        best = max(have, key=lambda p: p["scores"][h]["score"])
        if best["scores"][h]["score"] >= (25 if h == "IGL" else 40):
            hats[h] = best["label"]
    return {"primary": primary, "hats": hats}


def agent_to_learn(label: str, role: str | None, pool: dict[str, int], team_cover: dict[str, int],
                   meta_share: dict[str, float]) -> dict | None:
    """One agent worth learning: in an agent role that suits their team role and that the team is thin on."""
    if not role:
        return None
    options = ROLE_AGENTS.get(role, [])
    if not options:
        return None
    target = min(options, key=lambda r: (team_cover.get(r, 0), options.index(r)))
    known = {a for a, n in pool.items() if n >= 5}
    cands = [a for a in agent_roles.all_agents() if agent_roles.role_of(a) == target and a not in known]
    if not cands:
        return None
    by_meta = sorted(cands, key=lambda a: (-meta_share.get(a, 0.0),
                                           FALLBACK_AGENTS.get(target, []).index(a) if a in FALLBACK_AGENTS.get(target, []) else 99))
    agent = by_meta[0]
    why = [f"fits the {role} role"]
    if team_cover.get(target, 0) <= 1:
        why.append(f"only {team_cover.get(target, 0)} of your starters play a {target} regularly")
    if meta_share.get(agent):
        why.append(f"picked by {meta_share[agent]:.0%} of teams on your maps at your level")
    if pool.get(agent):
        why.append(f"you've played it {pool[agent]}× already")
    return {"agent": agent, "agent_role": target, "why": why}


def team_roles(members: list[dict], local: dict[str, dict], maps: list[str]) -> dict:
    """members: [{label, kind, rows, assigned}] -> per-player metrics, scores, suggestions and agent to learn."""
    out = []
    for m in members:
        met = metrics(m["rows"])
        sc = scores(met)
        out.append({**m, "metrics": met, "scores": sc,
                    # IGL is only a guess and a hat on top of a role: not a "best fit"
                    "best": sorted((r for r in sc if r != "IGL"), key=lambda r: -sc[r]["score"])[:3] if sc else []})
    starters = [p for p in out if p["kind"] == "starter"]
    lineup = suggest_lineup(starters)
    # how many starters play each agent role regularly (10+ games)
    cover = Counter()
    for p in starters:
        per_role = Counter()
        for r in p["rows"]:
            per_role[agent_roles.role_of(r["agent"])] += 1
        for role, n in per_role.items():
            if n >= 10:
                cover[role] += 1
    meta_share: dict[str, float] = Counter()
    for mp in maps:
        for a in (local.get(mp) or {}).get("agents", []):
            meta_share[a["agent"]] += a["share"] / max(1, len(maps))
    for p in out:
        pool = Counter(r["agent"] for r in p["rows"])
        primary = next((r for r in p["assigned"] if r in PRIMARY or r == "Flex"), None) \
            or (lineup.get("primary", {}).get(p["label"]) if p["kind"] == "starter" else (p["best"][0] if p["best"] else None))
        p["role_for_agent"] = primary
        p["learn"] = agent_to_learn(p["label"], primary, pool, cover, meta_share)
        p["checks"] = []
        for r in p["assigned"]:
            s = p["scores"].get(r, {}).get("score")
            if s is not None and r != "IGL" and s < 35:
                p["checks"].append(f"{r}: the data shows little of it ({s}/100). Worth talking about.")
    sites = {}
    for p in starters:
        met = p["metrics"]
        if met.get("def_site") and (met.get("def_site_focus") or 0) >= 0.5:
            sites.setdefault(met["def_site"], []).append(p["label"])
    return {"players": out, "lineup": lineup, "cover": dict(cover), "def_sites": sites}
