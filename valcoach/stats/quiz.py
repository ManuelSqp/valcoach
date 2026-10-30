"""Decision quiz from your own rounds (player tab "Quiz").

Moments are picked from your recent games with round data: the moment you were left alone
(1vX), a first death far from your team that nobody traded, and rounds your team lost with a
player advantage. For each moment we know only what you could know then (time, spike, how many
are alive, where your teammates stood); the model writes a question with 3-4 calls, the best
one and why. What really happened is added from the match data, after you answer."""
from __future__ import annotations

from ..coach.prompts import field_guide
from ..maps import MapInfo
from ..models import Match

ISOLATED = 2000          # ~20 m to the nearest living teammate
TRADE_MS = 3000
KINDS = {"clutch": "Alone at the end", "alone": "First death, far from the team", "advantage": "A lead that slipped"}


def _area(mi: MapInfo | None, x: float, y: float) -> str:
    if mi is None:
        return "?"
    try:
        return mi.area(x, y)
    except Exception:
        return "?"


def _secs(ms: int) -> int:
    return int(round(ms / 1000))


def _state(match: Match, rnd, team: str, opp: str, upto_ms: int) -> dict:
    alive = {team: {p.puuid for p in match.players_on(team)}, opp: {p.puuid for p in match.players_on(opp)}}
    for k in rnd.kills:
        if k.t_round_ms <= upto_ms:
            for s in alive.values():
                s.discard(k.victim)
    return alive


def _spike(rnd, t_ms: int, mi) -> str:
    if rnd.plant and rnd.plant.t_round_ms <= t_ms:
        since = _secs(t_ms - rnd.plant.t_round_ms)
        return f"spike planted on {rnd.plant.site or '?'} {since} s ago (about {max(0, 45 - since)} s until it explodes)"
    return "spike not planted yet"


def _after(match: Match, rnd, puuid: str, team: str, from_ms: int, mi) -> str:
    """What happened next, in words (shown after answering)."""
    names = {p.puuid: f"{p.agent}" for p in match.players.values()}
    out = []
    mine = [k for k in rnd.kills if k.t_round_ms > from_ms and k.killer == puuid]
    death = next((k for k in rnd.kills if k.t_round_ms > from_ms and k.victim == puuid), None)
    if mine:
        out.append(f"you got {len(mine)} more kill{'s' if len(mine) > 1 else ''}")
    if death:
        out.append(f"you died {_secs(death.t_round_ms - from_ms)} s later at {_area(mi, death.victim_x, death.victim_y)} "
                   f"to {names.get(death.killer, '?')}{' (' + death.weapon + ')' if death.weapon else ''}")
    if rnd.defuse and rnd.defuse.t_round_ms > from_ms:
        out.append("the spike was defused" + (" by you" if rnd.defuse.player == puuid else ""))
    elif rnd.plant and rnd.plant.t_round_ms > from_ms:
        out.append(f"the spike was planted on {rnd.plant.site or '?'}" + (" by you" if rnd.plant.player == puuid else ""))
    won = rnd.winning_team == team
    out.append(f"the round was {'won' if won else 'lost'}" + (f" ({rnd.result.lower()})" if rnd.result else ""))
    s = "; ".join(out)
    return s[:1].upper() + s[1:] + "."


def moments(match: Match, puuid: str, mi: MapInfo | None) -> list[dict]:
    me = match.players.get(puuid)
    if me is None:
        return []
    team, opp = me.team, match.other_team(me.team)
    out = []
    score = {team: 0, opp: 0}
    for rnd in match.rounds:
        side = rnd.side_of(team)
        kills = sorted(rnd.kills, key=lambda k: k.t_round_ms)
        base = {"match_id": match.match_id, "map": match.map_name, "round": rnd.number, "side": side, "agent": me.agent,
                "score": f"{score[team]}–{score[opp]}", "won": rnd.winning_team == team}
        if rnd.winning_team in score:
            score[rnd.winning_team] += 1
        # 1) left alone: the kill that made it 1vX
        alive = {team: {p.puuid for p in match.players_on(team)}, opp: {p.puuid for p in match.players_on(opp)}}
        for k in kills:
            if k.victim == puuid:
                break
            for s in alive.values():
                s.discard(k.victim)
            if alive[team] == {puuid} and alive[opp] and len(alive[opp]) <= 3:
                loc = k.loc_of(puuid)
                facts = {**base, "time_s": _secs(k.t_round_ms), "you_vs": f"1v{len(alive[opp])}", "spike": _spike(rnd, k.t_round_ms, mi),
                         "you_are_at": _area(mi, loc.x, loc.y) if loc else "?",
                         "last_teammate_died_at": _area(mi, k.victim_x, k.victim_y) if k.victim_team == team else None,
                         "your_weapon": (rnd.stats.get(puuid).weapon if rnd.stats.get(puuid) else "") or "?"}
                out.append({"kind": "clutch", "t_ms": k.t_round_ms, "facts": facts,
                            "happened": _after(match, rnd, puuid, team, k.t_round_ms, mi)})
                break
        # 2) first death of the round, far from the team, not traded
        if kills and kills[0].victim == puuid and kills[0].killer:
            k = kills[0]
            mates = [pl for pl in k.player_locations if pl.team == team and pl.puuid != puuid]
            dist = min((((pl.x - k.victim_x) ** 2 + (pl.y - k.victim_y) ** 2) ** 0.5 for pl in mates), default=None)
            traded = any(t.victim == k.killer and 0 < t.t_round_ms - k.t_round_ms <= TRADE_MS for t in kills)
            if dist is not None and dist > ISOLATED and not traded:
                killer = match.players.get(k.killer)
                facts = {**base, "time_s": _secs(k.t_round_ms), "you_were_at": _area(mi, k.victim_x, k.victim_y),
                         "nearest_teammate_m": round(dist / 100),
                         "teammates_at": sorted({_area(mi, pl.x, pl.y) for pl in mates}),
                         "killed_by": f"{killer.agent if killer else '?'}" + (f" with {k.weapon}" if k.weapon else ""),
                         "spike": _spike(rnd, k.t_round_ms, mi)}
                out.append({"kind": "alone", "t_ms": max(0, k.t_round_ms - 4000), "facts": facts,
                            "happened": f"You died first at {facts['you_were_at']} after {facts['time_s']} s, "
                                        f"{facts['nearest_teammate_m']} m from the nearest teammate; nobody traded. "
                                        f"The round was {'won' if base['won'] else 'lost'}."})
        # 3) lost with a 2+ player advantage (you were still alive when the lead was biggest)
        if rnd.winning_team != team:
            alive = {team: {p.puuid for p in match.players_on(team)}, opp: {p.puuid for p in match.players_on(opp)}}
            best = (0, None)
            for k in kills:
                for s in alive.values():
                    s.discard(k.victim)
                lead = len(alive[team]) - len(alive[opp])
                if lead > best[0] and puuid in alive[team]:
                    best = (lead, k, len(alive[team]), len(alive[opp]))
            if best[0] >= 2:
                k = best[1]
                loc = k.loc_of(puuid)
                facts = {**base, "time_s": _secs(k.t_round_ms), "players_alive": f"{best[2]}v{best[3]}",
                         "spike": _spike(rnd, k.t_round_ms, mi), "you_are_at": _area(mi, loc.x, loc.y) if loc else "?",
                         "teammates_at": sorted({_area(mi, pl.x, pl.y) for pl in k.player_locations
                                                 if pl.team == team and pl.puuid != puuid and pl.puuid in alive[team]})}
                out.append({"kind": "advantage", "t_ms": k.t_round_ms, "facts": facts,
                            "happened": _after(match, rnd, puuid, team, k.t_round_ms, mi)})
    return out


def pick(found: list[dict], n: int = 6) -> list[dict]:
    """A mix: lost moments first, one of each kind before seconds, then fill up; at most 2 from one match."""
    order = sorted(found, key=lambda m: (m["facts"]["won"], {"clutch": 0, "advantage": 1, "alone": 2}[m["kind"]]))
    out, per_kind, per_match = [], {}, {}
    for cap in (1, 2, n):
        for m in order:
            if len(out) >= n:
                break
            if m in out or per_kind.get(m["kind"], 0) >= cap or per_match.get(m["facts"]["match_id"], 0) >= 2:
                continue
            out.append(m)
            per_kind[m["kind"]] = per_kind.get(m["kind"], 0) + 1
            per_match[m["facts"]["match_id"]] = per_match.get(m["facts"]["match_id"], 0) + 1
    for i, m in enumerate(out, 1):
        m["id"] = f"q{i}"
    return out


SYSTEM = """You are a Valorant coach. Write a short decision quiz for one player from moments in
their own games. Rules:
- One question per moment, in second person ("You are..."), using ONLY what the player could know
  at that moment: map, side, round, score, time, the spike, how many are alive, where they and
  their teammates are. Never tell what happened afterwards.
- 3 or 4 options: concrete calls a player could make in that spot (e.g. "Play for the defuse
  from Hookah", "Save", "Wait for the plant and retake with the timer"). Exactly one is the best
  call for this situation; the others are the realistic mistakes.
- "why": 1-3 sentences, why the best call is right here, naming the facts (time, numbers alive,
  spike). No generic aim advice.
Write in {language}."""


def schema(ids: list[str]) -> dict:
    q = {"type": "object", "properties": {
        "id": {"type": "string", "enum": ids},
        "question": {"type": "string", "description": "the situation and the question, 1-3 sentences"},
        "options": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4,
                    "description": "3 or 4 short calls"},
        "best": {"type": "integer", "minimum": 0, "maximum": 3, "description": "index of the best option (0 = first)"},
        "why": {"type": "string", "description": "why that call is best here"},
    }, "required": ["id", "question", "options", "best", "why"]}
    return {"type": "object", "properties": {"questions": {"type": "array", "items": q, "minItems": 1, "maxItems": len(ids)}},
            "required": ["questions"]}


def write_quiz(llm, picked: list[dict], language: str = "English") -> list[dict]:
    import yaml
    ids = [m["id"] for m in picked]
    payload = [{"id": m["id"], "type": KINDS[m["kind"]], **{k: v for k, v in m["facts"].items() if k not in ("match_id", "won") and v is not None}}
               for m in picked]
    sch = schema(ids)
    out = llm.chat_json(SYSTEM.format(language=language) + field_guide(sch),
                        "Moments (YAML):\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True) +
                        f"\nWrite one question for each of the {len(ids)} moments.", sch)
    by = {m["id"]: m for m in picked}
    qs = []
    for q in out.get("questions") or []:
        m = by.pop(q.get("id"), None)
        opts = [str(o).strip()[:160] for o in (q.get("options") or []) if str(o).strip()][:4]
        best = q.get("best")
        if m is None or len(opts) < 3 or not isinstance(best, int) or not 0 <= best < len(opts) or not str(q.get("question") or "").strip():
            continue
        qs.append({"id": m["id"], "kind": m["kind"], "kind_label": KINDS[m["kind"]], "map": m["facts"]["map"],
                   "round": m["facts"]["round"], "side": m["facts"]["side"], "match_id": m["facts"]["match_id"],
                   "agent": m["facts"].get("agent"), "question": str(q["question"]).strip()[:600], "options": opts, "best": best,
                   "why": str(q.get("why") or "").strip()[:600], "happened": m["happened"], "won": m["facts"]["won"]})
    return qs
