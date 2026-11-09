"""Team comps from the web (4.10): the "From the web" comp suggestions.

Per map, a background job (statsjobs.submit_webcomps) searches the web with the search set up under
Settings › Web search, reads the best pages, and the model lists the 5-agent comps those pages name, each
with the sources it came from. Only comps of 5 different, real agents are kept. Stored per team in
data/teams/<tid>/webcomps.json and shown until they are fetched again.

The comps page then gives every found comp to your 5 players: each agent goes to the player who does best
on it (the same rating as "Your stats only", over all 120 ways to hand out the 5 agents). An agent nobody
plays costs points and is marked "new". The comps that fit your players best come first.
"""
from __future__ import annotations

import itertools
import time

from . import roles
from .comp import Pool, rate

MAX_COMPS = 4
NEW_AGENT = 25            # points off when a player gets an agent he has never played
QUERIES = ["valorant {map} best team composition {year}", "valorant {map} pro agent comp VCT {year}",
           "valorant {map} meta comp current patch"]

SYSTEM = """You read web pages about VALORANT and list the 5-agent team compositions they recommend or that pro
teams play on {map}. Use only what the sources say: never invent a comp, never fill in agents a source doesn't
name. Prefer the newest information (patch, year). A comp is exactly 5 different agents. Give at most {n} comps,
the most recommended first, each with the numbers of the sources that name it and one short sentence (in
{language}) on why it works or who plays it. Valid agents: {agents}. If the sources name no full comp, give none."""

SCHEMA = {
    "type": "object",
    "properties": {"comps": {"type": "array", "items": {
        "type": "object",
        "properties": {"agents": {"type": "array", "items": {"type": "string"}},
                       "note": {"type": "string"},
                       "sources": {"type": "array", "items": {"type": "integer"}}},
        "required": ["agents", "note", "sources"]}}},
    "required": ["comps"],
}


def queries(map_name: str, year: int | None = None) -> list[str]:
    y = year or time.gmtime().tm_year
    return [q.format(map=map_name, year=y) for q in QUERIES]


def _canon(name: str, known: dict[str, str]) -> str | None:
    """'kayo', 'KAY/O', ' Viper ' -> 'KAY/O' / 'Viper'; None if it isn't an agent."""
    k = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return known.get(k)


def clean(raw: list[dict], sources: list[dict]) -> list[dict]:
    """Keep comps of 5 different real agents, with the sources they cite (numbers it made up are dropped)."""
    from ..coach.websearch import cited
    known = {"".join(ch for ch in a.lower() if ch.isalnum()): a for a in roles.all_agents()}
    out, seen = [], set()
    for c in raw or []:
        agents = [_canon(a, known) for a in (c.get("agents") or [])]
        if len(agents) != 5 or None in agents or len(set(agents)) != 5:
            continue
        key = frozenset(agents)
        if key in seen:
            continue
        seen.add(key)
        out.append({"agents": agents, "note": str(c.get("note") or "")[:300],
                    "sources": cited(sources, c.get("sources"))})
        if len(out) >= MAX_COMPS:
            break
    return out


def fetch(search, llm, map_name: str, language: str = "English", reader=None) -> dict:
    """Search, read and extract the comps for one map. -> {map, comps, sources, errors, at, model}"""
    from ..coach.websearch import research, sources_block
    srcs, errors = research(search, queries(map_name), per_query=4, read=4, page_chars=3000, reader=reader)
    comps = []
    if srcs:
        system = SYSTEM.format(map=map_name, n=MAX_COMPS, language=language, agents=", ".join(roles.all_agents()))
        out = llm.chat_json(system, f"Map: {map_name}" + sources_block(srcs), SCHEMA)
        comps = clean(out.get("comps") or [], srcs)
    return {"map": map_name, "comps": comps, "sources": [{"title": s["title"], "url": s["url"]} for s in srcs],
            "errors": errors, "at": time.time(), "model": getattr(llm, "model", "")}


def assign(players: list[Pool], agents: list[str], map_name: str, local: dict | None = None,
           meta: dict | None = None) -> dict:
    """The best way to hand these 5 agents to these 5 players. -> a comp like comp.best_comp's."""
    from .aggregate import pattern as pat_str
    rated = [{a: rate(p, a, map_name, local, meta) for a in agents} for p in players]
    best = None
    for perm in itertools.permutations(agents):
        total = 0.0
        for i, a in enumerate(perm):
            r = rated[i][a]
            total += r["score"] - (NEW_AGENT if r["n_all"] == 0 else 0)
        if best is None or total > best[0]:
            best = (total, perm)
    total, perm = best
    picks = []
    for p, a, rr in zip(players, perm, rated):
        r = dict(rr[a])
        if r["n_all"] == 0:
            r["why"] = r["why"] + [f"{p.label} hasn't played {a} yet"]
        picks.append({"player": p.label, **r, "low_sample": r["n_map"] < 2 and r["n_all"] < 5, "new": r["n_all"] == 0,
                      "alternatives": []})
    return {"map": map_name, "ok": True, "total": round(total, 1), "picks": picks, "missing_roles": [],
            "pattern": pat_str(list(perm)), "notes": [], "method": "web"}


def comps_for(players: list[Pool], map_name: str, data: dict | None, local: dict | None = None,
              meta: dict | None = None) -> list[dict]:
    """Every comp found for this map, given to these players, best fit first. [] if none were found yet."""
    if not data or not data.get("comps") or any(not p.n for p in players):
        return []
    out = []
    for i, c in enumerate(data["comps"]):
        comp = assign(players, c["agents"], map_name, local, meta)
        comp["web"] = {"note": c.get("note", ""), "sources": c.get("sources", []), "rank": i + 1,
                       "at": data.get("at"), "model": data.get("model", "")}
        comp["notes"] = [f"from the web: {c['note']}" if c.get("note") else "from the web"]
        new = [p["player"] for p in comp["picks"] if p.get("new")]
        if new:
            comp["notes"].append(f"new agent for {', '.join(new)}")
        out.append(comp)
    out.sort(key=lambda c: -c["total"])
    return out
