"""Comp sheet (4.13): every player's agent pool and the ideal composition per map, on one page.

Agent pool: each player's agents in order, best first, colored from green to red. It starts from the stats
(most played, then win rate) and the player can change it: reorder, add agents he wants to play, and mark
agents he won't play. Agents played later that aren't in the edited list are added at the end, so the list
never goes stale. Saved per team in data/teams/<tid>/compsheet.json:
  {"pools": {"<pid>": {"order": [agents], "no": [agents]}}, "ideal": {"<map lower>": [5 agents]}}

Ideal composition: per map, the comp web sources name most (webcomps.py, the same search as "From the
web"), or 5 agents the team owner typed. Under every agent: who on the team has it in their pool.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import roles
from .aggregate import by_agent

FILE = "compsheet.json"


# ---------------------------------------------------------------------------- storage
def load(team_dir: Path) -> dict:
    try:
        d = json.loads((Path(team_dir) / FILE).read_text())
        return {"pools": dict(d.get("pools") or {}), "ideal": dict(d.get("ideal") or {})}
    except (OSError, ValueError):
        return {"pools": {}, "ideal": {}}


def save(team_dir: Path, data: dict) -> None:
    p = Path(team_dir) / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pools": data.get("pools") or {}, "ideal": data.get("ideal") or {}}, ensure_ascii=False))
    tmp.replace(p)


def clean_agents(names, limit: int = 40) -> list[str]:
    """Only real agents, each once, in the given order (names from a form)."""
    key = lambda n: re.sub(r"[^a-z0-9]", "", str(n).lower())   # "kayo" = "KAY/O"
    known = {key(a): a for a in roles.all_agents()}
    out = []
    for n in names or []:
        a = known.get(key(n))
        if a and a not in out:
            out.append(a)
    return out[:limit]


# ---------------------------------------------------------------------------- agent pool
def pool(rows: list[dict], saved: dict | None = None) -> dict:
    """{agents: [{agent, role, games, wr, rank, added}], no: [agents], edited: bool}

    added = in the list without games (the player put it there)."""
    played = sorted(by_agent(rows), key=lambda a: (-a["games"], -a.get("wr", 0), a["agent"]))
    stats = {a["agent"]: a for a in played}
    no = clean_agents((saved or {}).get("no"))
    if saved and saved.get("order") is not None:
        order = [a for a in clean_agents(saved["order"]) if a not in no]
        order += [a["agent"] for a in played if a["agent"] not in order and a["agent"] not in no]
    else:
        order = [a["agent"] for a in played if a["agent"] not in no]
    agents = []
    for i, a in enumerate(order, 1):
        s = stats.get(a)
        agents.append({"agent": a, "role": roles.role_of(a), "games": s["games"] if s else 0,
                       "wr": s["wr"] if s else None, "rank": i, "added": s is None})
    return {"agents": agents, "no": no, "edited": bool(saved)}


def hue(rank: int, n: int) -> int:
    """Green (120) for the first agent down to red (0) for the last."""
    return 120 if n <= 1 else round(120 - 120 * (rank - 1) / (n - 1))


# ---------------------------------------------------------------------------- ideal composition
def ideal(map_name: str, typed: list[str] | None, web_entry: dict | None) -> dict | None:
    """The typed comp if there is one, else the first comp from the web; None if neither."""
    typed = clean_agents(typed)
    if len(typed) == 5:
        return {"agents": typed, "source": "typed"}
    comps = (web_entry or {}).get("comps") or []
    if comps:
        c = comps[0]
        return {"agents": list(c["agents"]), "source": "web", "note": c.get("note", ""),
                "sources": c.get("sources", []), "at": web_entry.get("at"), "model": web_entry.get("model", ""),
                "others": len(comps) - 1}
    return None


def who_plays(agent: str, pools: dict[str, dict], top: int = 3) -> list[dict]:
    """Players who have this agent in their pool, best rank first: [{label, rank, games}]."""
    out = []
    for label, pl in pools.items():
        for a in pl["agents"]:
            if a["agent"] == agent:
                out.append({"label": label, "rank": a["rank"], "games": a["games"]})
                break
    return sorted(out, key=lambda x: (x["rank"], -x["games"]))[:top]
