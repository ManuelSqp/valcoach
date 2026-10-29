"""Your playstyle in four numbers, the pros it resembles, and what to watch.

Style dimensions (0..1, as a percentile among the players in your own matches):
  opening  how often you're in the first duel of a round
  kills    kills per round
  assists  assists per round
  survive  how rarely you die (1 - percentile of deaths per round)
Without lobby data (only archive games) fixed reference ranges are used instead.
"""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from urllib.parse import quote_plus

import yaml

from . import roles
from .aggregate import by_map, map_detail

DIMS = ("opening", "kills", "assists", "survive")
DIM_TEXT = {
    "opening": ("take the first duel often", "rarely take the first duel"),
    "kills": ("get a lot of kills", "get fewer kills"),
    "assists": ("play for your teammates (assists)", "get few assists"),
    "survive": ("stay alive a lot", "die a lot"),
}
GAP_MORE = {"opening": "takes more opening duels", "kills": "gets more kills per round",
            "assists": "gets more assists", "survive": "stays alive more often"}
GAP_LESS = {"opening": "takes fewer opening duels", "kills": "gets fewer kills per round",
            "assists": "gets fewer assists", "survive": "dies more often"}
# fallback reference (mean, spread) per round when there's no lobby data
REFERENCE = {"kpr": (0.70, 0.15), "apr": (0.27, 0.10), "dpr": (0.70, 0.10), "opr": (0.20, 0.08)}
DEFAULT_PROS = Path(__file__).with_name("pros.yaml")
YT = "https://www.youtube.com/results?search_query="


# ---------------------------------------------------------------------------
# your style
# ---------------------------------------------------------------------------
def _pct(value: float, population: list[float]) -> float:
    if not population:
        return 0.5
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    return (below + 0.5 * equal) / len(population)


def _norm(value: float, key: str) -> float:
    mu, sd = REFERENCE[key]
    return 0.5 * (1 + math.erf((value - mu) / (sd * math.sqrt(2))))


def profile(rows: list[dict]) -> dict:
    """Style dims + raw per-round numbers + role / agent shares."""
    out: dict = {"games": len(rows)}
    if not rows:
        return out
    full = [r for r in rows if r.get("source") == "full"]
    rounds = sum(r["rounds"] for r in rows) or 1
    kpr = sum(r["kills"] for r in rows) / rounds
    apr = sum(r["assists"] for r in rows) / rounds
    dpr = sum(r["deaths"] for r in rows) / rounds
    full_rounds = sum(r["rounds"] for r in full)
    opr = (sum(r["fk"] + r["fd"] for r in full) / full_rounds) if full_rounds else None
    lobby = [x for r in full for x in r.get("lobby", [])]
    raw = {"kpr": kpr, "apr": apr, "dpr": dpr, "opr": opr}
    if len(lobby) >= 30:
        cols = list(zip(*lobby))
        dims = {"kills": _pct(kpr, list(cols[0])), "assists": _pct(apr, list(cols[1])),
                "survive": 1 - _pct(dpr, list(cols[2])),
                "opening": _pct(opr, list(cols[3])) if opr is not None else None}
        out["reference"] = f"compared with {len(lobby)} player-games in your matches"
    else:
        dims = {"kills": _norm(kpr, "kpr"), "assists": _norm(apr, "apr"), "survive": 1 - _norm(dpr, "dpr"),
                "opening": _norm(opr, "opr") if opr is not None else None}
        out["reference"] = "compared with typical ranked numbers (update stats for a comparison with your lobbies)"
    if dims["opening"] is None:
        dims["opening"] = 0.5
        out["no_openings"] = True
    out["dims"] = {k: round(v, 3) for k, v in dims.items()}
    out["raw"] = {k: (None if v is None else round(v, 3)) for k, v in raw.items()}
    fk, fd = sum(r["fk"] for r in full), sum(r["fd"] for r in full)
    out["opening_wr"] = fk / (fk + fd) if fk + fd else None
    out["roles"] = {k: v / len(rows) for k, v in Counter(roles.role_of(r["agent"]) for r in rows).most_common()}
    out["agents"] = {k: v / len(rows) for k, v in Counter(r["agent"] for r in rows).most_common()}
    out["main_role"] = next(iter(out["roles"]), "?")
    out["traits"] = traits(out["dims"])
    return out


def traits(dims: dict) -> list[str]:
    out = []
    for k in DIMS:
        v = dims.get(k)
        if v is None:
            continue
        if v >= 0.7:
            out.append(f"you {DIM_TEXT[k][0]}")
        elif v <= 0.3:
            out.append(f"you {DIM_TEXT[k][1]}")
    return out


# ---------------------------------------------------------------------------
# pros
# ---------------------------------------------------------------------------
def load_pros(text: str | None = None) -> list[dict]:
    """Parse the pro list (the admin's version from Settings, or the built-in one)."""
    data = yaml.safe_load(text if (text or "").strip() else DEFAULT_PROS.read_text()) or {}
    pros = data.get("pros") if isinstance(data, dict) else None
    if not isinstance(pros, list):
        raise ValueError("expected a 'pros:' list")
    out = []
    for i, p in enumerate(pros, 1):
        if not isinstance(p, dict) or not p.get("name"):
            raise ValueError(f"entry {i}: needs a name")
        style = p.get("style") or {}
        bad = [k for k in DIMS if not isinstance(style.get(k), (int, float)) or not 0 <= style[k] <= 1]
        if bad:
            raise ValueError(f"{p['name']}: style needs {', '.join(bad)} between 0 and 1")
        if p.get("role") not in roles.ROLES:
            raise ValueError(f"{p['name']}: role must be one of {', '.join(roles.ROLES)}")
        out.append({"name": str(p["name"]), "role": p["role"], "agents": [str(a) for a in p.get("agents") or []],
                    "style": {k: float(style[k]) for k in DIMS}, "known_for": str(p.get("known_for", ""))})
    return out


def match_pros(prof: dict, pros: list[dict], top: int = 3) -> list[dict]:
    """Similarity = 50 % style distance, 25 % role, 25 % shared agents."""
    if not prof.get("dims"):
        return []
    dims, agent_share, role_share = prof["dims"], prof["agents"], prof["roles"]
    out = []
    for p in pros:
        diff = {k: dims[k] - p["style"][k] for k in DIMS}
        style_sim = 1 - sum(abs(v) for v in diff.values()) / len(DIMS)
        role_sim = role_share.get(p["role"], 0.0)
        shared = [a for a in p["agents"] if a in agent_share]
        agent_sim = min(1.0, sum(agent_share[a] for a in shared) * 1.5)
        score = 0.5 * style_sim + 0.25 * role_sim + 0.25 * agent_sim
        close = sorted(DIMS, key=lambda k: abs(diff[k]))
        far = max(DIMS, key=lambda k: abs(diff[k]))
        why = []
        if shared:
            why.append(f"plays your agents: {', '.join(shared)}")
        if role_sim >= 0.4:
            why.append(f"same role ({p['role']})")
        alike = [k for k in close[:2] if abs(diff[k]) <= 0.15]
        if alike:
            why.append("similar " + " and ".join({"opening": "opening-duel rate", "kills": "kill rate",
                                                  "assists": "assist rate", "survive": "survival"}[k] for k in alike))
        gap = None
        if abs(diff[far]) >= 0.25:
            gap = f"{p['name']} {(GAP_MORE if diff[far] < 0 else GAP_LESS)[far]} than you"
        out.append({**p, "score": round(score, 3), "why": why, "gap": gap, "shared": shared,
                    "diff": {k: round(v, 2) for k, v in diff.items()}})
    out.sort(key=lambda x: -x["score"])
    return out[:top]


# ---------------------------------------------------------------------------
# videos to watch
# ---------------------------------------------------------------------------
def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _q(*parts: str) -> str:
    text = " ".join(p for p in parts if p)
    return text if "valorant" in text.lower() else text + " valorant"


def video_queries(rows: list[dict], prof: dict, matches: list[dict], limit: int = 6) -> list[dict]:
    """Targeted YouTube searches: your pro on your agent/map, plus your weak spots."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, title: str, query: str, why: str) -> None:
        if query.lower() in seen or len(out) >= limit:
            return
        seen.add(query.lower())
        out.append({"id": f"v{len(out) + 1}", "kind": kind, "title": title, "query": query,
                    "url": YT + quote_plus(query), "why": why})

    maps = [m for m in by_map(rows) if m["games"] >= 3]
    top_agent = next(iter(prof.get("agents", {})), "")
    if matches:
        pro = matches[0]
        agent = (pro["shared"] or pro["agents"] or [top_agent])[0]
        agent_maps = [m for m in maps if any(a["agent"] == agent for a in m["agents"])]
        m_name = agent_maps[0]["map"] if agent_maps else (maps[0]["map"] if maps else "")
        add("pro", f"{pro['name']} on {agent}{' · ' + m_name if m_name else ''}", _q(pro["name"], agent, m_name, "POV"),
            f"Closest pro to your style ({round(pro['score'] * 100)}% match). {_cap(pro['known_for'])}.")
        if len(matches) > 1:
            p2 = matches[1]
            a2 = (p2["shared"] or p2["agents"] or [""])[0]
            add("pro", f"{p2['name']} on {a2}", _q(p2["name"], a2, "POV"), f"Second closest pro. {_cap(p2['known_for'])}.")
    weak = sorted((m for m in maps if m["games"] >= 5), key=lambda m: m["wr_s"])
    if weak and weak[0]["wr_s"] < 0.5:
        m = weak[0]
        agent = m["agents"][0]["agent"] if m["agents"] else top_agent
        who = matches[0]["name"] if matches else ""
        add("map", f"{m['map']}: your weakest map", _q(who, agent, m["map"], "VOD" if who else "guide"),
            f"{m['wins']:.0f}-{m['games'] - m['wins']:.0f} on {m['map']} ({m['wr']:.0%}).")
    for m in maps[:3]:
        d = map_detail(rows, m["map"])
        agent = m["agents"][0]["agent"] if m["agents"] else top_agent
        for o in d["observations"]:
            if o["kind"] != "bad" or len(out) >= limit:
                continue
            t = o["text"]
            if "opening duels are at" in t:
                side = "attack" if "On attack" in t else "defense"
                area = t.split(" are at ")[1].split(" and ")[0]
                add("fix", f"{m['map']} {area} on {side}", _q(agent, m["map"], area, side, "tips"), t)
            elif "most common death" in t:
                side = "attack" if "on attack" in t else "defense"
                area = t.split(" is ")[1].split(" (")[0]
                add("fix", f"{m['map']} {area}: {side} positioning", _q(agent, m["map"], area, side, "positioning"), t)
            elif "first duel" in t:
                add("fix", f"Winning opening duels on {agent}", _q(agent, "how to win opening duels entry tips"), t)
            elif t.startswith("KAST"):
                add("fix", f"Staying alive and trading as {roles.role_of(agent)}",
                    _q(roles.role_of(agent), "how to trade and stay alive tips"), t)
            elif "hasn't worked here" in t:
                bad = t.split(" hasn't")[0]
                add("fix", f"{bad} on {m['map']}", _q(bad, m["map"], "guide lineups"), t)
    if prof.get("dims", {}).get("survive", 1) <= 0.3 and len(out) < limit:
        add("fix", "Dying less often", _q(prof.get("main_role", ""), "positioning how to die less"),
            "You die more per round than most players in your matches.")
    return out
