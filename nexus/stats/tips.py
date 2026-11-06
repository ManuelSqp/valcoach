"""Playstyle tips for one map from the model, based on the aggregated stats.

The model only gets numbers we computed (per agent, per side, opening duels, death
spots, what's played at your level) and must point to them as evidence."""
from __future__ import annotations

import json

import yaml

from ..coach.prompts import field_guide

from .aggregate import local_meta, map_detail

SYSTEM = """You are a Valorant coach looking at one player's long-term stats on one map.
Rules:
- Use ONLY the numbers given. Every tip must cite its evidence (counts, rates, areas).
- Small samples (under ~5 games or ~8 events) are weak evidence: say so or skip them.
- Missing data means unknown, not zero. There is no aim or crosshair data here.
- Be concrete: name areas/callouts from the data and what to do differently there.
- No generic advice ("communicate more", "use utility") unless the numbers point to it.
- Write in {language}."""


def schema() -> dict:
    tip = {"type": "object", "properties": {"tip": {"type": "string"}, "evidence": {"type": "string"}},
           "required": ["tip", "evidence"]}
    return {"type": "object", "properties": {
        "summary": {"type": "string", "description": "2 sentences: how this player does on this map and the main lever."},
        "agent_pool": {"type": "array", "items": {"type": "object", "properties": {
            "agent": {"type": "string"}, "verdict": {"type": "string", "enum": ["main", "backup", "drop"]},
            "why": {"type": "string"}}, "required": ["agent", "verdict", "why"]}},
        "attack": {"type": "array", "items": tip, "maxItems": 3},
        "defense": {"type": "array", "items": tip, "maxItems": 3},
        "focus_next": {"type": "string", "description": "The one thing to try in the next games on this map."},
    }, "required": ["summary", "agent_pool", "attack", "defense", "focus_next"]}


def facts(rows: list[dict], map_name: str, all_rows: list[dict] | None = None) -> dict:
    d = map_detail(rows, map_name)
    s = d["summary"]
    pct = lambda v: None if v is None else f"{v:.0%}"     # noqa: E731
    out = {
        "map": map_name,
        "overall": {"games": s.get("games"), "win_rate": pct(s.get("wr")), "acs": round(s.get("acs", 0)),
                    "kd": round(s.get("kd", 0), 2), "kast": pct(s.get("kast")), "games_with_round_data": d["n_full"],
                    "opening_duels": None if s.get("opening_wr") is None else
                    {"first_kills": s["fk"], "first_deaths": s["fd"], "won": pct(s["opening_wr"]),
                     "share_of_rounds": pct(s["opening_rate"])}},
        "agents": [{"agent": a["agent"], "role": a["role"], "games": a["games"], "win_rate": pct(a["wr"]),
                    "acs": round(a["acs"]), "kd": round(a["kd"], 2)} for a in d["agents"][:6]],
        "sides": {k: {"rounds": v["rounds"], "team_win_rate": pct(v["wr"])} for k, v in d["sides"].items()},
        "opening_duels_by_area": {k: [{"area": o["area"], "duels": o["n"], "won": o["good"]} for o in v[:4]]
                                  for k, v in d["openings"].items()},
        "deaths_by_area": {k: [{"area": o["area"], "deaths": o["n"], "traded": o["good"]} for o in v[:4]]
                           for k, v in d["deaths"].items()},
        "kills_by_area": {k: [{"area": o["area"], "kills": o["n"]} for o in v[:4]] for k, v in d["kills"].items()},
        "findings": [o["text"] for o in d["observations"]],
    }
    meta = local_meta(all_rows or rows).get(map_name)
    if meta and meta["games"] >= 5:
        out["played_at_your_level"] = {"matches": meta["games"],
                                       "agents": [{"agent": a["agent"], "pick_rate": pct(a["share"]), "win_rate": pct(a["wr"])}
                                                  for a in meta["agents"][:8]]}
    return out


def write_tips(llm, rows: list[dict], map_name: str, language: str = "English",
               all_rows: list[dict] | None = None) -> dict:
    f = facts(rows, map_name, all_rows)
    user = ("Stats for this map (YAML):\n" + yaml.safe_dump(f, sort_keys=False, allow_unicode=True) +
            "\nGive the agent pool verdicts, up to 3 tips each for attack and defense, and one focus.")
    out = llm.chat_json(SYSTEM.format(language=language) + field_guide(schema()), user, schema())
    out["_facts"] = f
    out["_model"] = getattr(llm, "model", "")
    return out


def dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# watch guide: what to look for in the pro's games and the videos
# ---------------------------------------------------------------------------
WATCH_SYSTEM = """You are a Valorant coach. A player will watch the videos listed below to improve.
For each one, say in 1-2 sentences what exactly to watch for, tied to THIS player's numbers
(the "why" of each video and their style profile). Be concrete: positions, timing, when to
peek or fall back, how the pro uses utility before a fight. Don't describe the video itself
(you haven't seen it); say what to look for. The player picked {pro} as the pro to copy: write
pro_summary and habits about copying {pro} specifically (what {pro} does that this player should take
over, and what to keep of their own). Write in {language}."""


def watch_schema(ids: list[str]) -> dict:
    return {"type": "object", "properties": {
        "pro_summary": {"type": "string", "description": "2-3 sentences: why the chosen pro fits and what to copy from them."},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string", "enum": ids}, "watch_for": {"type": "string"}}, "required": ["id", "watch_for"]}},
        "habits": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                   "description": "Habits to practice in the next games while copying the pro."},
    }, "required": ["pro_summary", "items", "habits"]}


def write_watch_guide(llm, prof: dict, matches: list[dict], queries: list[dict], language: str = "English",
                      pro: str | None = None) -> dict:
    """pro = the pro the player picked (default: the closest). It goes first in the facts."""
    pro = pro or (matches[0]["name"] if matches else "the closest pro")
    matches = sorted(matches, key=lambda m: m["name"] != pro)
    facts = {
        "your_style": {"main_role": prof.get("main_role"), "agents": {a: f"{v:.0%}" for a, v in list(prof.get("agents", {}).items())[:4]},
                       "percentiles": prof.get("dims"), "per_round": prof.get("raw"),
                       "opening_duels_won": None if prof.get("opening_wr") is None else f"{prof['opening_wr']:.0%}",
                       "traits": prof.get("traits"), "reference": prof.get("reference")},
        "chosen_pro": pro,
        "closest_pros": [{"name": m["name"], "role": m["role"], "agents": m["agents"], "known_for": m["known_for"],
                          "match": f"{m['score']:.0%}", "why": m["why"], "difference": m["gap"]} for m in matches],
        "videos": [{"id": q["id"], "title": q["title"], "search": q["query"], "why": q["why"],
                    **({"found": [v["title"] for v in q.get("videos", [])]} if q.get("videos") else {})} for q in queries],
    }
    user = "Player and videos (YAML):\n" + yaml.safe_dump(facts, sort_keys=False, allow_unicode=True)
    sch = watch_schema([q["id"] for q in queries])
    out = llm.chat_json(WATCH_SYSTEM.format(language=language, pro=pro) + field_guide(sch), user, sch)
    out["_model"] = getattr(llm, "model", "")
    return out
