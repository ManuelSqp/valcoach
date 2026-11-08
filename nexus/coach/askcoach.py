"""Ask the coach (4.2): a conversation with the coach about one player, like a chat.

The model gets a compact picture of the player (recent form, agents, maps, habits, what their aim needs,
KovaaK's scores) and the last few questions and answers. With web search set up (Settings › Web search) it
first decides whether to look something up, then answers with the pages it used."""
from __future__ import annotations

import yaml

from ..stats import aim as am
from ..stats import aim_insights as ai
from ..stats import kovaaks as kv
from ..stats import trainer as tr
from ..stats.aggregate import by_agent, by_map
from ..stats.habits import track
from ..stats.weekly import player_facts
from . import websearch as ws
from .llm import NoAnswer
from .prompts import field_guide

SYSTEM = """You are {player}'s Valorant coach, talking with them in a chat. Answer in {language}, like a coach who
knows this player: usually 3-8 sentences, a short list when there are steps.
- About this player: use only the data below (their stats, habits, aim). If the data doesn't show something,
  say so and what they could check; don't invent numbers.
- About the game (agents, abilities, maps, patches, pros, settings, aim trainers): use the web results when
  there are any. Without them, be careful with details that change with patches and say when you're not sure.
- Practical and concrete: what to do in the next games, which drill, which scenario or playlist.
- Answer the question that was asked; don't repeat the whole profile."""
SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string", "description": "the answer"},
    "sources": {"type": "array", "items": {"type": "integer"}, "description": "numbers of the web results used, [] if none"}},
    "required": ["answer", "sources"]}
MAX_Q = 600
HISTORY = 6


def facts(name: str, rows: list[dict], kovaaks_runs: list[dict] | None = None, trainer: dict | None = None) -> dict:
    pct = lambda v: None if v is None else f"{v:.0%}"       # noqa: E731
    f = player_facts(name, rows, [], {}, [], [])
    for k in ("team_roles", "role_fit", "team_patterns", "team_notes_about_them"):
        f.pop(k, None)
    f["agents"] = [{"agent": a["agent"], "role": a["role"], "games": a["games"], "win_rate": pct(a["wr"]),
                    "acs": round(a["acs"]), "kd": round(a["kd"], 2)} for a in by_agent(rows)[:5]]
    f["maps"] = [{"map": m["map"], "games": m["games"], "win_rate": pct(m["wr"])} for m in by_map(rows)[:7]]
    h = track(rows)
    f["habits"] = [{"habit": x["title"], "now": None if x["now"] is None else round(x["now"], 3),
                    "status": x["status_text"]} for x in h.get("habits", [])[:6]]
    f["aim"] = [x["why"] for x in am.needs(rows)]
    ks = kv.summary(kovaaks_runs or [])[:8]
    if ks:
        f["kovaaks_scores"] = [{"scenario": x["name"], "runs": x["runs"], "best": x["best"],
                                "steady_at_best": x["mastered"]} for x in ks]
    t = trainer or {}
    ts = [x for x in tr.summary(t.get("runs", [])) if x["runs"]]
    if ts:
        f["nexus_trainer_scores"] = [{"scenario": x["name"], "trains": ", ".join(x["focus"]), "runs": x["runs"],
                                      "best": x["best"], "last": x["last"],
                                      "accuracy": None if x["acc"] is None else f"{x['acc']:.0%}"} for x in ts]
    setup = t.get("setup", {})
    ins = ai.build(t.get("runs", []), setup)
    if ins["findings"]:
        f["aim_trainer_insights"] = [{"finding": x["title"], "detail": x["text"],
                                      "scenarios": [tr.SCENARIOS[s]["name"] for s in x["play"] if s in tr.SCENARIOS]}
                                     for x in ins["findings"][:5]]
    if ins["good"]:
        f["aim_trainer_strengths"] = ins["good"][:4]
    if setup.get("grip") or setup.get("hand"):
        f["mouse_grip"] = {k: setup[k] for k in ("grip", "hand") if setup.get(k)}
    if setup.get("sens") or setup.get("measured_dpi"):
        f["mouse"] = {k: v for k, v in {"valorant_sens": setup.get("sens"), "dpi_set": setup.get("dpi"),
                                        "dpi_measured": setup.get("measured_dpi"), "polling_hz": setup.get("polling_hz"),
                                        "monitor_hz": setup.get("refresh_hz"), **tr.numbers(setup)}.items() if v is not None}
    return {k: v for k, v in f.items() if v not in (None, [], {})}


def answer(llm, player: str, language: str, question: str, history: list[dict], data: dict,
           search=None, step=lambda s: None) -> dict:
    """-> {answer, sources: [{title, url}], searched: [queries], search_errors: [...]}"""
    context = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    sources: list[dict] = []
    queries: list[str] = []
    errors: list[str] = []
    if search is not None:
        step("Deciding what to look up")
        convo = "\n".join(f"Q: {h['q']}\nA: {h['a'][:300]}" for h in history[-2:])
        queries = ws.queries_for(llm, question, (convo + "\n\n" if convo else "") + context)
        if queries:
            step("Searching the web: " + " · ".join(queries))
            sources, errors = ws.research(search, queries)
    step("Writing the answer")
    talk = "".join(f"\nPlayer: {h['q']}\nCoach: {h['a']}" for h in history[-HISTORY:])
    user = (f"The player's data (YAML):\n{context}" + (f"\nThe conversation so far:{talk}\n" if talk else "") +
            ws.sources_block(sources) + f"\n\nQuestion: {question}")
    system = SYSTEM.format(player=player, language=language) + (ws.SOURCES_RULES if sources else "") + field_guide(SCHEMA)
    out = llm.chat_json(system, user, SCHEMA)
    text = str(out.get("answer") or "").strip()[:6000]
    if not text:
        raise NoAnswer("the model gave no answer")
    return {"answer": text, "sources": ws.cited(sources, out.get("sources")), "searched": queries,
            "search_errors": errors[:2]}
