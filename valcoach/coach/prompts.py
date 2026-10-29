"""System prompts and JSON schemas for the coaching model."""
from __future__ import annotations

ROUND_SYSTEM = """You are a professional Valorant coach reviewing one round of a match.
You coach {who}.

Hard rules:
- Use ONLY the facts in the round data. Never invent positions, utility, comms or timings that are not there.
- A missing field means the data doesn't have it, NOT that it didn't happen. If there is no utility_casts
  field, utility usage is unknown: don't praise or criticise utility usage at all.
{evidence_rule}
- Be concrete: name callouts, times (m:ss round time), player names/agents, player counts (4v5 etc.).
- Prioritise decisions over mechanics: positioning, trades, timing, economy, utility usage, mid-round calls.
- Judge against the team playbook when one is given; call out deviations from the plan.
- Short, direct sentences. No filler, no praise without a reason.
- Write in {language}.

Glossary for the data:
- player_count_progression: alive players (us v them) after each kill.
- positions_*: number of players per map zone at the moment of a kill snapshot.
- traded: the killer died to a teammate within 5 s. isolated: no alive teammate within ~18 m.
- minimap_tracking (if present): positions read from the VOD minimap, averaged per 10 s window.
- Duel facts come from where players looked at the moment of the kill: "looking at your killer" + damage done
  = a lost aim duel (crosshair placement / first-shot accuracy); killer "off to your side" or "behind" = a
  positioning or awareness problem (crossfire, flank, peeking into multiple angles), not an aim problem.
  0 damage to the killer means the duel was over before you shot back.
- shots_hit per round: low head share with many leg hits points at crosshair placement too low.
- better_position (if asked for): the callout where the player should have been at that moment, only
  when the facts show the position caused the death or a lost fight; otherwise "position was fine".
{playbook}{examples}{fields}"""

# where the model may send the user when the facts can't settle a question
EVIDENCE_WITH_VOD = ('- If the data cannot support a conclusion, don\'t guess: put the moment to re-watch '
                     'in check_in_vod (m:ss + what to look for), never in better_option.')
EVIDENCE_NO_VOD = ('- If the data cannot support a conclusion, leave it out. There is no recording of this match: '
                   'never tell the user to check a VOD or recording.')

MATCH_SYSTEM = """You are a professional Valorant coach writing the post-match review.
You coach {who}. Use only the stats and round reviews given. Find PATTERNS across rounds, not single events.
A stat that is missing is unknown, not zero (e.g. no utility_per_round = utility usage isn't in the data).
Be concrete and prioritised: the top issues are the ones that cost the most rounds.
Each practice item must be something doable in a scrim, custom game or the range.
Write in {language}.
{playbook}{fields}"""

# ---------------------------------------------------------------------------
# JSON schemas (Ollama structured outputs)
# ---------------------------------------------------------------------------
_feedback = {
    "type": "object",
    "properties": {
        "went_well": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                      "description": "what was right in this round and why; empty list if nothing was"},
        "mistakes": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                     "description": "decisions that cost the fight or the round, with time and place"},
        "better_option": {"type": "string",
                          "description": "the ONE concrete thing to do differently next time: what, where, "
                                         "when (1-2 sentences). Never 'None' or 'N/A', never a VOD reference. Also in "
                                         "a won round: the one thing that would have made it safer or cheaper"},
    },
    "required": ["went_well", "mistakes", "better_option"],
}


def field_guide(schema: dict) -> str:
    """The field descriptions as prompt text. Ollama only uses the schema to constrain the output
    format; the model never sees its descriptions unless they are also in the prompt."""
    lines: list[str] = []

    def walk(props: dict, prefix: str) -> None:
        for name, spec in props.items():
            if spec.get("type") == "array" and spec.get("items", {}).get("type") == "object":
                if spec.get("description"):
                    lines.append(f"- {prefix}{name}: {spec['description']}")
                walk(spec["items"].get("properties", {}), f"{prefix}{name}[].")
            elif spec.get("type") == "object":
                walk(spec.get("properties", {}), f"{prefix}{name}.")
            elif spec.get("description"):
                lines.append(f"- {prefix}{name}: {spec['description']}")

    walk(schema.get("properties", {}), "")
    return "\nOutput fields:\n" + "\n".join(lines) + "\n" if lines else ""


NO_CHANGE = "position was fine"


def round_schema(mode: str, callouts: list[str] | None = None, has_vod: bool = False) -> dict:
    props = {
        "summary": {"type": "string",
                    "description": "1-2 sentences on what decided this round: which fight, where, why. "
                                   "Not a heading: never write 'Round N', 'review' or the player's name."},
        "key_moment": {
            "type": "object",
            "properties": {"time": {"type": "string", "description": "round time m:ss of the moment that decided the round"},
                           "what": {"type": "string", "description": "what happened there, one sentence"}},
            "required": ["time", "what"],
        },
        "importance": {"type": "integer", "minimum": 1, "maximum": 3,
                       "description": "3 = round with a big lesson, 1 = nothing notable"},
    }
    req = ["summary", "key_moment", "importance"]
    if has_vod:
        props["check_in_vod"] = {"type": "string",
                                 "description": "m:ss + what to look for in the recording, when the facts can't "
                                                "answer a question; empty string if nothing"}
    if mode in ("team", "both"):
        props["team"] = _feedback
        req.append("team")
    if mode in ("player", "both"):
        props["player"] = _feedback
        req.append("player")
        if callouts:
            # shown on the round replay as a marker + arrow; enum keeps it to real callouts
            props["better_position"] = {
                "type": "object",
                "properties": {
                    "time": {"type": "string", "description": "round time m:ss the advice applies to"},
                    "callout": {"type": "string", "enum": [NO_CHANGE] + callouts},
                    "why": {"type": "string", "description": "one short sentence"},
                },
                "required": ["time", "callout", "why"],
            }
            req.append("better_position")
    return {"type": "object", "properties": props, "required": req}


def match_schema(mode: str) -> dict:
    issue = {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "the pattern, one sentence"},
            "evidence": {"type": "string", "description": "rounds / numbers that show it"},
            "fix": {"type": "string", "description": "what to do instead, concrete"},
        },
        "required": ["issue", "evidence", "fix"],
    }
    drill = {
        "type": "object",
        "properties": {
            "drill": {"type": "string", "description": "one concrete exercise, starts with a verb, max 25 words"},
            "where": {"type": "string", "enum": ["Range", "Custom game", "Deathmatch", "Team Deathmatch",
                                                 "Scrim", "Ranked / Premier", "VOD review"]},
            "minutes": {"type": "integer", "minimum": 5, "maximum": 60},
            "fixes": {"type": "string", "description": "which issue this drill addresses, a few words"},
        },
        "required": ["drill", "where", "minutes", "fixes"],
    }
    props = {
        "headline": {"type": "string",
                     "description": "ONE sentence with the most important takeaway of this match "
                                    "(not a title, no player name)"},
        "strengths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3,
                      "description": "what to keep doing, each with the rounds / numbers that show it"},
        "practice_plan": {"type": "array", "items": drill, "minItems": 2, "maxItems": 4},
    }
    req = ["headline", "strengths", "practice_plan"]
    if mode in ("team", "both"):
        props["team_issues"] = {"type": "array", "items": issue, "maxItems": 3}
        props["igl_notes"] = {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                              "description": "calls / mid-round adjustments for the IGL, one per item"}
        req += ["team_issues", "igl_notes"]
    if mode in ("player", "both"):
        props["player_issues"] = {"type": "array", "items": issue, "maxItems": 3}
        req.append("player_issues")
    return {"type": "object", "properties": props, "required": req}


def who(mode: str, player_label: str, team_label: str) -> str:
    if mode == "team":
        return f"the team ({team_label}); the user is the IGL"
    if mode == "player":
        return f"the player {player_label}"
    return (f"both the team ({team_label}, the user is the IGL) and the player {player_label} individually. "
            "Keep team feedback (macro, calls, trades, economy) separate from individual feedback "
            "(positioning, duels, utility, decision making)")
