"""Coaching pipeline: analysis -> (optional VOD tracking) -> LLM round + match review."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .. import __version__
from ..analysis.player import PlayerRoundFacts, analyse_player_round, player_match_stats
from ..analysis.team import TeamRoundFacts, analyse_team_round, team_match_stats
from ..analysis.view import ViewModel, calibrate
from ..maps import MapInfo
from ..models import Match
from ..pipeline import note_rounds
from . import prompts
from .ollama import Ollama
from .replay import build_replay
from .summarize import match_stats_block, round_summary


@dataclass
class Analysis:
    match: Match
    focus_puuid: str
    team: str
    map_info: MapInfo | None
    team_facts: list[TeamRoundFacts]
    player_facts: list[PlayerRoundFacts]
    team_stats: object
    player_stats: object
    minimap: dict[int, dict] = field(default_factory=dict)   # round index -> describe_track()
    view: ViewModel = field(default_factory=ViewModel)
    self_paths: dict[int, list] = field(default_factory=dict)  # round index -> [(t_s, x, y)] from the VOD
    vod_others: dict[int, dict] = field(default_factory=dict)  # round index -> {"allies": {puuid: path}, "enemies": [...]}
    nav: object | None = None                                   # NavGrid for estimated routes


def analyse(match: Match, focus_puuid: str, map_info: MapInfo | None) -> Analysis:
    team = match.team_of(focus_puuid)
    vm = calibrate(match)
    tf = [analyse_team_round(match, r, team, map_info, vm) for r in match.rounds]
    pf = [analyse_player_round(match, r, focus_puuid, map_info, vm) for r in match.rounds]
    return Analysis(
        match=match, focus_puuid=focus_puuid, team=team, map_info=map_info,
        team_facts=tf, player_facts=pf,
        team_stats=team_match_stats(match, team, tf),
        player_stats=player_match_stats(match, focus_puuid, pf, vm),
        view=vm,
    )


# ---------------------------------------------------------------------------
# knowledge: playbook + user's own notes
# ---------------------------------------------------------------------------
def load_playbook(path: Path, map_name: str) -> str:
    if not path.is_file():
        return ""
    pb = yaml.safe_load(path.read_text()) or {}
    if not isinstance(pb, dict):
        return "\nTeam playbook (judge decisions against this):\n" + str(pb) + "\n"
    maps = pb.get("maps")
    if not isinstance(maps, dict):
        maps = {}
    relevant = {k: v for k, v in pb.items() if k != "maps"}
    for name, data in maps.items():
        if str(name).lower() == map_name.lower():
            relevant["this_map"] = {name: data}
    if not relevant:
        return ""
    return "\nTeam playbook (judge decisions against this):\n" + yaml.safe_dump(relevant, sort_keys=False, allow_unicode=True)


def load_notes(notes_dir: Path, match_id: str) -> tuple[dict[int, str], list[str]]:
    """Returns (notes for this match by round number, example notes from other matches)."""
    this: dict[int, str] = {}
    examples: list[str] = []
    if not notes_dir.exists():
        return this, examples
    for p in sorted(notes_dir.glob("*.y*ml")):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        rounds = note_rounds(d)
        if isinstance(d, dict) and d.get("match_id") == match_id:
            this = rounds
        else:
            examples.extend(rounds.values())
    return this, examples[:10]


def _examples_block(examples: list[str]) -> str:
    if not examples:
        return ""
    lines = "\n".join(f"- {e}" for e in examples)
    return ("\nExamples of round feedback the user wrote themselves. Match this level of detail, "
            "directness and what they care about:\n" + lines + "\n")


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
@dataclass
class CoachReport:
    meta: dict
    team_stats: dict
    player_stats: dict
    rounds: list[dict]          # per round: facts + llm feedback + vod times
    match_review: dict
    sync: dict | None = None
    map: dict | None = None
    agents: dict | None = None
    team_review: dict | None = None   # whole-team review (coach/teamreview.py)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str))


PLACEHOLDERS = {"", "n/a", "na", "none", "-", "nothing", "null"}
STOP_AFTER_FAILS = 3        # rounds failed in a row (or `parallel`, if higher): the model is down, stop waiting for it
GAVE_UP = "Skipped: the model stopped answering"


def _is_filler(text) -> bool:
    """'N/A', 'None.' or 'None. The round went fine' - nothing to act on."""
    first = str(text or "").strip().split(".")[0].split(" - ")[0].strip().lower()
    return first in PLACEHOLDERS


def clean_feedback(fb: dict) -> dict:
    """Drop filler the model writes into required fields ('N/A', '-'), so the report hides them."""
    for side in ("team", "player"):
        part = fb.get(side)
        if isinstance(part, dict) and _is_filler(part.get("better_option")):
            part.pop("better_option", None)
    if _is_filler(fb.get("check_in_vod")):
        fb.pop("check_in_vod", None)
    return fb


def run_coach(an: Analysis, llm: Ollama | None, mode: str = "both", language: str = "English",
              playbook_path: Path | None = None, notes_dir: Path | None = None,
              parallel: int = 4, sync=None, progress=None) -> CoachReport:
    m = an.match
    me = m.players[an.focus_puuid]
    team_label = f"team {an.team} on {m.map_name}"
    who = prompts.who(mode, f"{me.riot_id} ({me.agent})", team_label)
    playbook = load_playbook(playbook_path, m.map_name) if playbook_path else ""
    own_notes, examples = load_notes(notes_dir, m.match_id) if notes_dir else ({}, [])

    callouts = sorted({c.label for c in an.map_info.callouts}) if an.map_info else None
    has_vod = sync is not None
    schema = prompts.round_schema(mode, callouts, has_vod)
    round_sys = prompts.ROUND_SYSTEM.format(
        who=who, language=language, playbook=playbook, examples=_examples_block(examples),
        evidence_rule=prompts.EVIDENCE_WITH_VOD if has_vod else prompts.EVIDENCE_NO_VOD,
        fields=prompts.field_guide(schema))

    inputs = []
    for i, r in enumerate(m.rounds):
        tf = an.team_facts[i] if mode in ("team", "both") else None
        pf = an.player_facts[i] if mode in ("player", "both") else None
        inputs.append(round_summary(tf, pf, an.minimap.get(r.index), own_notes.get(r.number)))

    stop_after = max(STOP_AFTER_FAILS, parallel)
    fails_in_a_row = 0
    lock = threading.Lock()

    def _one(i: int) -> dict:
        nonlocal fails_in_a_row
        if llm is None:
            return {}
        with lock:
            if fails_in_a_row >= stop_after:
                return {"error": GAVE_UP}
        try:
            fb = clean_feedback(llm.chat_json(round_sys, inputs[i], schema))
        except Exception as e:  # keep the report usable if one round fails
            with lock:
                fails_in_a_row += 1
            return {"error": str(e)}
        with lock:
            fails_in_a_row = 0
        return fb

    feedback: list[dict] = [{}] * len(inputs)
    if llm is not None:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
            for n, (i, fb) in enumerate(zip(range(len(inputs)), ex.map(_one, range(len(inputs))))):
                feedback[i] = fb
                if progress:
                    progress(n + 1, len(inputs))

    # ---- match review -------------------------------------------------
    match_review: dict = {}
    gave_up = fails_in_a_row >= stop_after or (llm is not None and all("error" in fb for fb in feedback))
    if gave_up:
        match_review = {"error": GAVE_UP}
    elif llm is not None:
        stats_txt = match_stats_block(an.team_stats if mode != "player" else None,
                                      an.player_stats if mode != "team" else None)
        digest = []
        for i, fb in enumerate(feedback):
            if not fb or "error" in fb:
                continue
            line = {"round": i + 1, "importance": fb.get("importance"), "summary": fb.get("summary")}
            if "team" in fb:
                line["team_mistakes"] = fb["team"].get("mistakes")
            if "player" in fb:
                line["player_mistakes"] = fb["player"].get("mistakes")
            digest.append(line)
        user = ("MATCH STATS\n" + stats_txt + "\nROUND REVIEWS\n" +
                yaml.safe_dump(digest, sort_keys=False, allow_unicode=True, width=120))
        mschema = prompts.match_schema(mode)
        try:
            match_review = llm.chat_json(
                prompts.MATCH_SYSTEM.format(who=who, language=language, playbook=playbook,
                                            fields=prompts.field_guide(mschema)),
                user, mschema)
        except Exception as e:
            match_review = {"error": str(e)}

    # ---- assemble -----------------------------------------------------
    rounds_out = []
    for i, r in enumerate(m.rounds):
        vod = None
        if sync is not None and r.start_match_ms is not None:
            vod = {
                "start": round(sync.vod_time(r.start_match_ms, r.index), 2),
                "kills": [round(sync.vod_time(k.t_match_ms, r.index), 2) for k in r.kills],
            }
            my_death = next((k for k in r.kills if k.victim == an.focus_puuid), None)
            if my_death:
                vod["your_death"] = round(sync.vod_time(my_death.t_match_ms, r.index), 2)
            if r.kills:
                vod["first_kill"] = vod["kills"][0]
        rounds_out.append({
            "number": r.number,
            "team_facts": asdict(an.team_facts[i]),
            "player_facts": asdict(an.player_facts[i]),
            "minimap": an.minimap.get(r.index),
            "own_note": own_notes.get(r.number),
            "llm_input": inputs[i],
            "feedback": feedback[i],
            "vod": vod,
            "replay": build_replay(m, r, an.focus_puuid, an.map_info, an.view, an.self_paths.get(r.index), an.nav,
                                   an.vod_others.get(r.index)),
        })

    meta = {
        "match_id": m.match_id, "map": m.map_name, "queue": m.queue, "started_at": m.started_at,
        "player": me.riot_id, "agent": me.agent, "team": an.team,
        "score": f"{m.team_rounds_won.get(an.team, 0)}-{m.team_rounds_won.get(m.other_team(an.team), 0)}",
        "mode": mode, "model": llm.model if llm else None, "valcoach_version": __version__,
        "llm_failed_rounds": [r.number for r, fb in zip(m.rounds, feedback) if "error" in fb], "llm_gave_up": gave_up,
        "roster": [{"name": p.riot_id, "agent": p.agent, "team": p.team,
                    "k": p.kills, "d": p.deaths, "a": p.assists,
                    "acs": round(p.score / max(1, len(m.rounds)), 1)} for p in m.players.values()],
    }
    return CoachReport(
        meta=meta,
        team_stats=asdict(an.team_stats),
        player_stats=asdict(an.player_stats),
        rounds=rounds_out,
        match_review=match_review,
        sync=asdict(sync) if sync is not None else None,
    )
