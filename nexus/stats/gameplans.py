"""'Try this match': detailed game plans per map, written by the model from your team's numbers.

Each plan says what every starter does (by name, agent and role), when, what to do if it
goes differently, and which numbers it's based on. Callouts are limited to the map's real
callout names so the model can't invent places.
"""
from __future__ import annotations

import yaml

from ..coach.prompts import field_guide

SYSTEM = """You are the coach of a Valorant Premier team preparing tonight's match on {map}.
Write concrete plans the team can run in the next match. Rules:
- Base every plan on the numbers given (your sites, timings, where you get flanked, mid control,
  what opponents at your level do). Say which numbers in "why".
- Every plan has exactly one step per starter, by name, matching their agent and team role:
  what they do, where (ONLY these callouts: {callouts}) and when (round time like 1:05).
- Be specific like a real IGL call, e.g. "Player 1+2+3 fake A with util at 1:20, Player 4 lurks
  B Main and peeks on the rotation at 1:05, Player 5 holds Mid for rotators".
- Include "if this happens -> do that" adjustments.
- No generic advice. No aim tips. Write in {language}."""
COUNTER = """
These plans are for the match against {opponent}. Their habits from replay files are given
("when_they_attack" -> your defense plans, "when_they_defend" -> your attack plans): their usual setup and
spots at 20 s, their utility with place and time, where they plant. Build the plans to punish those habits
(e.g. hit the site they leave light, take the space before their usual smoke goes up, stack where they
plant most) and say in "why" which habit each plan uses."""


def schema(players: list[str]) -> dict:
    step = {"type": "object", "properties": {
        "player": {"type": "string", "enum": players}, "what": {"type": "string"}}, "required": ["player", "what"]}
    plan = {"type": "object", "properties": {
        "title": {"type": "string", "description": "short name, e.g. 'A fake into B lurk timing'"},
        "side": {"type": "string", "enum": ["attack", "defense"]},
        "idea": {"type": "string", "description": "one sentence"},
        "when_to_use": {"type": "string"},
        "steps": {"type": "array", "items": step, "minItems": len(players), "maxItems": len(players)},
        "timing": {"type": "string", "description": "key times in the round"},
        "if_then": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "why": {"type": "string", "description": "the numbers behind it"},
    }, "required": ["title", "side", "idea", "steps", "timing", "if_then", "why"]}
    return {"type": "object", "properties": {"plans": {"type": "array", "items": plan, "minItems": 3, "maxItems": 3}},
            "required": ["plans"]}


def write_plans(llm, map_name: str, facts: dict, lineup: list[dict], callouts: list[str], notes: list[str],
                tips: list[str], language: str = "English", opponent: dict | None = None) -> dict:
    """lineup: [{player, agent, roles}] for the 5 starters. opponent (4.19): {name, habits} from replay scouting
    -> counter-plans against that team."""
    payload = {"map": map_name, "lineup": lineup, "your_numbers_on_this_map": facts,
               "team_notes": notes[:10], "patterns_from_your_matches": tips[:8]}
    if opponent:
        payload["opponent_habits"] = opponent.get("habits") or {}
    user = ("Team and map (YAML):\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True) +
            "\nWrite 3 plans: 2 for attack and 1 for defense.")
    players = [p["player"] for p in lineup]
    sch = schema(players)
    system = SYSTEM.format(map=map_name, callouts=", ".join(callouts) or "the map's usual callouts", language=language)
    if opponent:
        system += COUNTER.format(opponent=opponent.get("name") or "this opponent")
    out = llm.chat_json(system + field_guide(sch), user, sch)
    # keep each plan's steps in lineup order, one per player
    for p in out.get("plans", []):
        by = {s.get("player"): s for s in p.get("steps", [])}
        p["steps"] = [by.get(n, {"player": n, "what": ""}) for n in players]
        for s in p["steps"]:                      # "Player: smoke B" -> "smoke B" (the name is shown already)
            w = (s.get("what") or "").strip()
            for pre in (f"{s['player']}:", f"{s['player']} -", f"{s['player']} –"):
                if w.lower().startswith(pre.lower()):
                    w = w[len(pre):].strip()
                    w = w[:1].upper() + w[1:]
            s["what"] = w
    out["_facts"] = facts
    out["_lineup"] = lineup
    out["_model"] = getattr(llm, "model", "")
    if opponent:
        out["_opponent"] = opponent.get("name") or "this opponent"
    return out
