"""Post-match check-ins (4.15): what the match data can't show.

Calling, comms and the team's mood aren't in any API. After a match the team played together, each player can
answer in about 20 seconds: who made most of the calls, how the comms were (1-5), how the mood was (1-5), and
one optional line. Everyone sees the team's answers.

Used by:
- the IGL suggestion (Player overview, Roles): the player named as caller in most check-ins, instead of the
  guess from the stats, once there are MIN_VOTES votes;
- the coach: the team's comms and mood per match (Premier reviews) and over the last matches (weekly focus,
  Ask the coach), with the notes.

Kept per team in teams/<tid>/checkins.json: {match_id: {pid: {caller, comms, mood, note, at}}}.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

MIN_VOTES = 3
NOTE_MAX = 300
SCALE = {1: "bad", 2: "weak", 3: "ok", 4: "good", 5: "great"}


def path(team_dir: Path) -> Path:
    return Path(team_dir) / "checkins.json"


def load(team_dir: Path) -> dict:
    try:
        d = json.loads(path(team_dir).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(team_dir: Path, data: dict) -> None:
    p = path(team_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    # keep the last 200 matches
    if len(data) > 200:
        keep = sorted(data, key=lambda m: max((a.get("at", 0) for a in data[m].values()), default=0))[-200:]
        data = {m: data[m] for m in keep}
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(p)


def _score(v) -> int | None:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if 1 <= v <= 5 else None


def record(team_dir: Path, match_id: str, pid: int, caller: int | None, comms, mood, note: str = "",
           members: set[int] | None = None) -> dict:
    """Saves one player's check-in (replacing his earlier one for this match)."""
    data = load(team_dir)
    if members is not None and caller not in members:
        caller = None
    entry = {"caller": caller or 0, "comms": _score(comms), "mood": _score(mood),
             "note": (note or "").strip()[:NOTE_MAX], "at": time.time()}
    data.setdefault(str(match_id), {})[str(pid)] = entry
    save(team_dir, data)
    return entry


def summary(answers: dict) -> dict:
    """One match: {n, comms, mood (averages), caller (pid or None), votes {pid: n}, notes [(pid, text)]}."""
    vals = list(answers.values())
    comms = [a["comms"] for a in vals if a.get("comms")]
    mood = [a["mood"] for a in vals if a.get("mood")]
    votes = Counter(a["caller"] for a in vals if a.get("caller"))
    top = votes.most_common(1)
    return {"n": len(vals), "comms": sum(comms) / len(comms) if comms else None,
            "mood": sum(mood) / len(mood) if mood else None,
            "caller": top[0][0] if top and (len(votes) == 1 or top[0][1] > votes.most_common(2)[1][1]) else None,
            "votes": dict(votes), "notes": [(int(p), a["note"]) for p, a in answers.items() if a.get("note")]}


def caller_votes(data: dict, last: int = 20) -> Counter:
    """Who was named as caller over the team's last check-ins (one vote per answer)."""
    recent = sorted(data.items(), key=lambda kv: -max((a.get("at", 0) for a in kv[1].values()), default=0))[:last]
    return Counter(a["caller"] for _, ans in recent for a in ans.values() if a.get("caller"))


def igl(data: dict, names: dict[int, str]) -> dict | None:
    """{label, votes, total} for the player the team names as caller, or None below MIN_VOTES."""
    v = caller_votes(data)
    if not v:
        return None
    pid, n = v.most_common(1)[0]
    if n < MIN_VOTES or pid not in names:
        return None
    return {"label": names[pid], "votes": n, "total": sum(v.values())}


def of_player(data: dict, pid: int) -> list[dict]:
    out = []
    for mid, ans in data.items():
        a = ans.get(str(pid))
        if a:
            out.append({"match_id": mid, **a})
    return sorted(out, key=lambda a: -a.get("at", 0))


def player_facts(items: list[dict]) -> dict | None:
    """A player's own last 10 check-ins, for the coach."""
    items = sorted(items, key=lambda a: -a.get("at", 0))[:10]
    if not items:
        return None
    comms = [a["comms"] for a in items if a.get("comms")]
    mood = [a["mood"] for a in items if a.get("mood")]
    out = {"matches": len(items), "note": "the player's own answers after matches (1 = bad, 5 = great)"}
    if comms:
        out["comms_avg"] = round(sum(comms) / len(comms), 1)
    if mood:
        out["mood_avg"] = round(sum(mood) / len(mood), 1)
    notes = [a["note"] for a in items if a.get("note")][:4]
    if notes:
        out["their_notes"] = notes
    return out


def match_facts(answers: dict, names: dict[int, str]) -> dict | None:
    """One match, for a Premier review."""
    if not answers:
        return None
    s = summary(answers)
    out = {"answers": s["n"], "note": "the players' own answers after the match (1 = bad, 5 = great)"}
    if s["comms"] is not None:
        out["comms_avg"] = round(s["comms"], 1)
    if s["mood"] is not None:
        out["mood_avg"] = round(s["mood"], 1)
    if s["caller"] and s["caller"] in names:
        out["caller"] = names[s["caller"]]
    if s["notes"]:
        out["notes"] = [f"{names.get(p, '?')}: {t}" for p, t in s["notes"]][:5]
    return out


def team_facts(data: dict, names: dict[int, str], last: int = 10) -> dict | None:
    """The team's last matches with check-ins, for the weekly focus / plans."""
    recent = sorted(data.items(), key=lambda kv: -max((a.get("at", 0) for a in kv[1].values()), default=0))[:last]
    if not recent:
        return None
    comms = [s["comms"] for s in (summary(a) for _, a in recent) if s["comms"] is not None]
    mood = [s["mood"] for s in (summary(a) for _, a in recent) if s["mood"] is not None]
    out = {"matches": len(recent)}
    if comms:
        out["comms_avg"] = round(sum(comms) / len(comms), 1)
    if mood:
        out["mood_avg"] = round(sum(mood) / len(mood), 1)
    c = igl(data, names)
    if c:
        out["caller"] = f"{c['label']} ({c['votes']} of {c['total']} votes)"
    return out
