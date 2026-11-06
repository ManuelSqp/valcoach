"""Weekly focus: one thing per player to work on this week, from their recent numbers and team role."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import yaml

from ..coach.prompts import field_guide

from .aggregate import by_map, map_detail, summary

SYSTEM = """You are a Valorant coach giving one player ONE focus for this week of matches.
Pick the thing that would help the team most, judged against the player's team role(s).
Use only the numbers given and cite them. The focus must be something they can do in normal
matches (no aim-trainer homework). Write in {language}."""


def schema() -> dict:
    return {"type": "object", "properties": {
        "focus": {"type": "string", "description": "short title, e.g. 'Fall back after the first kill on B'"},
        "why": {"type": "string", "description": "1-2 sentences with the numbers"},
        "in_game": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3,
                    "description": "what to do differently in matches, concrete"},
        "number_to_watch": {"type": "object", "properties": {
            "metric": {"type": "string"}, "now": {"type": "string"}, "goal": {"type": "string"}},
            "required": ["metric", "now", "goal"]},
    }, "required": ["focus", "why", "in_game", "number_to_watch"]}


def week_id(now: datetime | None = None) -> str:
    y, w, _ = (now or datetime.now()).isocalendar()
    return f"{y}-W{w:02d}"


def _recent(rows: list[dict], days: int) -> tuple[list[dict], list[dict]]:
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [r for r in rows if (r.get("started_at") or "") >= cut], [r for r in rows if (r.get("started_at") or "") < cut]


def player_facts(name: str, rows: list[dict], roles: list[str], role_scores: dict, tips: list[str],
                 notes: list[str]) -> dict:
    recent, older = _recent(rows, 14)
    full = [r for r in rows if r.get("source") == "full"]

    def block(rs):
        s = summary(rs)
        if not s.get("games"):
            return None
        fr = [r for r in rs if r.get("source") == "full"]
        deaths = sum(r["deaths"] for r in fr)
        return {"games": s["games"], "win_rate": f"{s['wr']:.0%}", "acs": round(s["acs"]), "kd": round(s["kd"], 2),
                "kast": None if s.get("kast") is None else f"{s['kast']:.0%}",
                "opening_duels_won": None if s.get("opening_wr") is None else f"{s['opening_wr']:.0%}",
                "deaths_traded": None if not deaths else f"{sum(r.get('traded_deaths', 0) for r in fr) / deaths:.0%}"}
    findings = []
    for m in by_map(full)[:3]:
        findings += [f"{m['map']}: {o['text']}" for o in map_detail(full, m["map"])["observations"] if o["kind"] == "bad"]
    return {"player": name, "team_roles": roles or ["not set"],
            "role_fit": {r: v["score"] for r, v in role_scores.items()} if role_scores else None,
            "last_2_weeks": block(recent), "before": block(older), "findings": findings[:6],
            "team_patterns": tips[:4], "team_notes_about_them": notes[:5]}


def write_focus(llm, facts: dict, language: str = "English") -> dict:
    user = "Player (YAML):\n" + yaml.safe_dump(facts, sort_keys=False, allow_unicode=True)
    out = llm.chat_json(SYSTEM.format(language=language) + field_guide(schema()), user, schema())
    out["_model"] = getattr(llm, "model", "")
    return out
