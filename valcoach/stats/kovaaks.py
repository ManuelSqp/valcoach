"""KovaaK's: playlists the coach writes for you, the scenarios it picks from, and your scores.

A KovaaK's playlist is a small JSON file in FPSAimTrainer/Saved/SaveGames/Playlists that only names scenarios
and how many runs each. valcoach writes such a file from what your matches show (the same needs as the Aim
page); scenarios you don't have yet are downloaded by KovaaK's when the playlist is opened.

Scenario names must be exact, so the coach only uses names it knows: the built-in list below (all taken from
real, popular playlists), plus scenarios people add (by hand, from a playlist file, or found in their scores).

Scores come from KovaaK's stats folder (FPSAimTrainer/stats): one CSV file per run, named
"<scenario> - Challenge - <YYYY.MM.DD-HH.MM.SS> Stats.csv", with "Key:,Value" lines at the end (Score:, Kills:,
Scenario:, ...). The parser only relies on what it finds and skips files it can't read.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime

# what a scenario trains (the Aim page's focus keys; "switching" and "reaction" are KovaaK's-only)
FOCUS_EXTRA = {"switching": "Target switching", "reaction": "Reaction"}
SECONDS_PER_RUN = 75                # 60 s scenario + loading and the score screen
MAX_RUNS = 5000                     # kept per player
MAX_CSV_BYTES = 400_000             # one stats file
MAX_ZIP_FILES = 20_000

# name, focus, level (1 easy, 2 medium, 3 hard). Names exactly as KovaaK's spells them.
BUILTIN: list[tuple[str, list[str], int]] = [
    ("Tile Frenzy", ["flicks", "warmup"], 1),
    ("3 Tile Jumbo Tile Frenzy", ["flicks", "warmup"], 1),
    ("Wide Wall 3 Targets", ["flicks", "warmup"], 1),
    ("Wide Wall 4 Targets", ["flicks", "warmup"], 1),
    ("horizontal flicks v2", ["flicks", "warmup"], 1),
    ("Centering I 180", ["crosshair", "tracking", "warmup"], 1),
    ("Reflex Flick - Easy", ["reaction", "flicks"], 1),
    ("Houston Outlaws - Target Switching", ["switching"], 1),
    ("Overwatch 2 - Smooth Tracking", ["tracking"], 1),
    ("High Ground Tracking a+ Easy", ["tracking"], 1),
    ("Tile Frenzy Mini", ["micro", "flicks"], 2),
    ("Wide Wall 3 Targets Small", ["flicks"], 2),
    ("Wide Wall 4 Targets Small", ["flicks"], 2),
    ("Wide Wall 6Targets", ["flicks"], 2),
    ("Wide Wall 6Targets Pasu Reload", ["flicks"], 2),
    ("1wall 6targets small", ["flicks"], 2),
    ("1wall 6targets small movement", ["flicks", "peeking"], 2),
    ("1w6ts reload", ["flicks"], 2),
    ("6wall18targets small reload", ["flicks"], 2),
    ("1wall5targets_pasu Reload", ["flicks"], 2),
    ("5 Sphere Hipfire Small", ["flicks"], 2),
    ("5 Sphere Hipfire Small Reload", ["flicks"], 2),
    ("beanClick", ["flicks"], 2),
    ("Valorant Vertical Flicks", ["flicks", "crosshair"], 2),
    ("1wall2targets_smallflicks 60s", ["micro"], 2),
    ("1wall 2targets small - valorant", ["micro", "crosshair"], 2),
    ("Valorant One Taps", ["crosshair", "micro"], 2),
    ("n0ted clicking heads", ["crosshair", "micro"], 2),
    ("Floating Heads Timing 400% FIXED", ["micro", "crosshair"], 2),
    ("Fireworks Flick Small", ["flicks", "reaction"], 2),
    ("Flux Valorant Reflex Flick", ["reaction", "peeking"], 2),
    ("Valorant Reflex Flick Strafing", ["reaction", "peeking"], 2),
    ("voxTargetSwitch 250%", ["switching"], 2),
    ("ValTargetSwitch", ["switching"], 2),
    ("beanTS", ["switching"], 2),
    ("Smoothbot Switch Robots", ["switching", "tracking"], 2),
    ("Consecutive Tracking", ["tracking"], 2),
    ("Ascended Tracking 90", ["tracking"], 2),
    ("Ascended Tracking 90 invincible fixed", ["tracking"], 2),
    ("Tile Frenzy 180 Strafing 400Prct Track", ["tracking"], 2),
    ("Extra mini Tile Frenzy", ["micro"], 3),
    ("1 wall 6 targets Xsmall", ["micro", "flicks"], 3),
    ("1w2t smallflicks small 60s", ["micro"], 3),
    ("Wide Wall 10 Extra Small", ["micro"], 3),
    ("Floating Heads Timing 400% no mag", ["micro", "crosshair"], 3),
    ("Tile Frenzy Flick 180 Small", ["flicks"], 3),
    ("Tamspeed 2bpes", ["flicks"], 3),
    ("1w6tmultilayerclosedodgeslowersmaller", ["flicks", "peeking"], 3),
    ("Reflex Flick - Mini", ["reaction", "micro"], 3),
    ("Reflex Micro Flick 250ms", ["reaction", "micro"], 3),
    ("Reactive Clicking Hard", ["reaction", "peeking"], 3),
    ("VoxTargetSwitch xsmall 200%", ["switching", "micro"], 3),
    ("patTS 90 NR", ["switching"], 3),
]


def builtin() -> list[dict]:
    return [{"name": n, "focus": f, "level": lv, "source": "builtin"} for n, f, lv in BUILTIN]


# ------------------------------------------------------------------ tags for scenarios valcoach doesn't know
_GUESS = [
    (r"track|smooth|strafe|ascended|air|bounce|pure|whisphere|controlsphere", "tracking"),
    (r"switch|\bts\b|ts\b|target ?switch", "switching"),
    (r"reflex|react|timing|ww5t|popcorn|1w4ts|detection", "reaction"),
    (r"center|centering|head|one ?tap", "crosshair"),
    (r"micro|xsmall|extra small|mini|tiny|smallflick|1w2t|2 ?targets", "micro"),
    (r"flick|frenzy|click|hipfire|tamspeed|pasu", "flicks"),
]
_GENERIC_FLICKS = r"wall|targets|sphere|bean|\b\d+ ?t"         # clicking scenarios, if nothing else fits


def guess(name: str) -> tuple[list[str], int]:
    """Tags and level from a scenario's name (people can change them)."""
    n = name.lower()
    tags = []
    for rx, tag in _GUESS:
        if re.search(rx, n) and tag not in tags:
            tags.append(tag)
    level = 3 if re.search(r"xsmall|extra small|mini|tiny|hard|200%|250%|nr\b|no mag", n) else (
        1 if re.search(r"easy|jumbo|big|large|warm", n) else 2)
    if not tags and re.search(_GENERIC_FLICKS, n):
        tags.append("flicks")
    return (tags or ["flicks"])[:3], level


def clean_name(name) -> str:
    """KovaaK's names are exact; keep them as they are, only refuse what can't be a name."""
    s = str(name or "")
    if not s.strip() or len(s) > 120 or any(c in s for c in "\r\n\t\0") or "/" in s or "\\" in s:
        return ""
    return s


# ------------------------------------------------------------------ playlists people give us
def read_playlist(raw: bytes | str) -> dict | None:
    """A KovaaK's playlist file -> {name, code, scenarios: [(name, runs)]} or None."""
    try:
        d = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("scenarioList"), list):
        return None
    out = []
    for s in d["scenarioList"][:200]:
        if not isinstance(s, dict):
            continue
        name = clean_name(s.get("scenario_name", s.get("scenario_Name")))
        if not name:
            continue
        try:
            runs = max(1, min(20, int(s.get("play_Count") or 1)))
        except (TypeError, ValueError):
            runs = 1
        out.append((name, runs))
    if not out:
        return None
    code = str(d.get("shareCode") or "")
    return {"name": str(d.get("playlistName") or "KovaaK's playlist")[:60],
            "code": code if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{3,63}", code) else "",
            "scenarios": out}


# ------------------------------------------------------------------ stats files
_FILE_RE = re.compile(r"^(?P<s>.+?) - (?:Challenge|Freeplay|[A-Za-z ]+?) - (?P<d>\d{4})\.(?P<m>\d{2})\.(?P<day>\d{2})-(?P<H>\d{2})\.(?P<M>\d{2})\.(?P<S>\d{2}) Stats\.csv$")


def read_stats(filename: str, text: str) -> dict | None:
    """One KovaaK's stats CSV -> {s: scenario, t: ISO time, d: date, score, kills, acc} or None."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    m = _FILE_RE.match(base)
    kv: dict[str, str] = {}
    lines = text.splitlines()
    shots = hits = 0.0
    for i, line in enumerate(lines):
        if ":," in line:
            k, _, v = line.partition(":,")
            kv[k.strip().lower()] = v.split(",")[0].strip()
        elif line.lower().startswith("weapon,shots,hits") and i + 1 < len(lines):
            parts = lines[i + 1].split(",")
            try:
                shots, hits = float(parts[1]), float(parts[2])
            except (IndexError, ValueError):
                pass
    scenario = clean_name(kv.get("scenario") or (m.group("s") if m else ""))
    try:
        score = float(kv.get("score", ""))
    except ValueError:
        return None
    if not scenario:
        return None
    if m:
        when = datetime(int(m.group("d")), int(m.group("m")), int(m.group("day")), int(m.group("H")), int(m.group("M")), int(m.group("S")))
    else:
        return None                                   # without a time we can't tell runs apart
    try:
        kills = int(float(kv.get("kills", "0") or 0))
    except ValueError:
        kills = 0
    return {"s": scenario, "t": when.isoformat(timespec="seconds"), "d": when.date().isoformat(), "score": round(score, 1),
            "kills": kills, "acc": round(hits / shots, 3) if shots else None}


def read_upload(filename: str, data: bytes) -> tuple[list[dict], int]:
    """A stats CSV, or a .zip of the stats folder -> (runs, files that couldn't be read)."""
    runs, bad = [], 0
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = [i for i in z.infolist() if i.filename.lower().endswith(".csv")][:MAX_ZIP_FILES]
                for info in infos:
                    if info.file_size > MAX_CSV_BYTES:
                        bad += 1
                        continue
                    with z.open(info) as fh:
                        r = read_stats(info.filename, fh.read(MAX_CSV_BYTES + 1).decode("utf-8", "replace"))
                    if r:
                        runs.append(r)
                    else:
                        bad += 1
        except zipfile.BadZipFile:
            return [], 1
        return runs, bad
    if len(data) > MAX_CSV_BYTES:
        return [], 1
    r = read_stats(filename, data.decode("utf-8", "replace"))
    return ([r], 0) if r else ([], 1)


def merge_runs(old: list[dict], new: list[dict]) -> tuple[list[dict], int]:
    """Add new runs (one per scenario and start time), newest kept. -> (all, how many were new)."""
    seen = {(r["s"], r["t"]) for r in old}
    add = [r for r in new if (r["s"], r["t"]) not in seen and not seen.add((r["s"], r["t"]))]
    allr = sorted(old + add, key=lambda r: r["t"])[-MAX_RUNS:]
    return allr, len(add)


def summary(runs: list[dict]) -> list[dict]:
    """Per scenario: runs, best, last, the last 12 scores and whether it's going up."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by[r["s"]].append(r)
    out = []
    for s, rs in by.items():
        rs.sort(key=lambda r: r["t"])
        scores = [r["score"] for r in rs]
        best = max(scores)
        recent, before = scores[-5:], scores[-10:-5]
        trend = None
        if len(before) >= 3 and len(recent) >= 3:
            a, b = sum(before) / len(before), sum(recent) / len(recent)
            trend = (b - a) / a if a else None
        out.append({"name": s, "runs": len(rs), "best": best, "last": scores[-1], "spark": scores[-12:],
                    "trend": trend, "last_day": rs[-1]["d"], "mastered": mastered(scores)})
    return sorted(out, key=lambda x: (x["last_day"], x["runs"]), reverse=True)


def mastered(scores: list[float]) -> bool:
    """Steady near your best: the last 3 runs all within 4% of your best, with 6 or more runs."""
    if len(scores) < 6:
        return False
    best = max(scores)
    return best > 0 and all(s >= best * 0.96 for s in scores[-3:])


# ------------------------------------------------------------------ the playlist the coach writes
KINDS = {"warmup": ("warm-up", 10), "training": ("training", 25)}


def build(kind: str, needs: list[dict], catalog: list[dict], runs: list[dict] | None = None, week: str = "",
          exclude: set[str] | frozenset = frozenset()) -> dict:
    """needs: the Aim page's [{focus: [...], weight, why}]. catalog: [{name, focus, level}].
    exclude: scenarios to leave out (the training playlist leaves out the warm-up's).
    -> {kind, title, minutes, items: [{name, runs, focus, level, why, best, last, mastered}]}

    Warm-up: two easy openers, then one run each of medium scenarios for what you need.
    Training: different scenarios from the warm-up, in blocks per need (medium, then hard), at most two runs each,
    plus something different to finish (a kind you don't train otherwise). Harder scenarios where you're steady
    near your best (imported scores). The pick changes every week (week = seed) and repeats a scenario only when
    the list has nothing new left."""
    label, minutes = KINDS.get(kind, KINDS["warmup"])
    training = kind == "training"
    total = max(4, round(minutes * 60 / SECONDS_PER_RUN))
    per_max = 2 if training else 1
    stats = {x["name"]: x for x in summary(runs or [])}
    weights: dict[str, float] = defaultdict(float)
    why: dict[str, str] = {}
    for n in needs:
        for f in n.get("focus", []):
            weights[f] += n.get("weight", 1)
            why.setdefault(f, n.get("why", ""))
    if "crosshair" in weights:                           # these go together in KovaaK's
        weights["micro"] += weights["crosshair"] / 2
    if "peeking" in weights:
        weights["reaction"] += weights["peeking"]
    if not weights or set(weights) <= {"warmup"}:
        weights.update({"flicks": 2, "micro": 1, "switching": 1})

    def rank(s: dict) -> str:                            # stable within a week, different next week
        return hashlib.sha1(f"{week}|{kind}|{s['name']}".encode()).hexdigest()

    def level_for(focus: str, level: int) -> int:
        # one level up once you're steady at your best on a scenario of this kind at that level
        c = [s for s in catalog if focus in s["focus"] and s["level"] == level]
        return min(3, level + 1) if any(stats.get(s["name"], {}).get("mastered") for s in c) else level

    def candidates(focus: str, level: int) -> list[dict]:
        """Scenarios of this kind, the asked level first, then the nearest levels; not used yet."""
        level = level_for(focus, level)
        c = [s for s in catalog if focus in s["focus"] and s["name"] not in used]
        return sorted(c, key=lambda s: (abs(s["level"] - level), rank(s)))

    items: list[dict] = []
    used: set[str] = set(exclude)

    def add(s: dict, n: int, reason: str, focus: str) -> int:
        if s["name"] in used or n <= 0:
            return 0
        used.add(s["name"])
        st = stats.get(s["name"]) or {}
        items.append({"name": s["name"], "runs": n, "focus": focus, "level": s["level"], "why": reason,
                      "best": st.get("best"), "last": st.get("last"), "mastered": st.get("mastered", False)})
        return n

    left = total
    openers = sorted((s for s in catalog if "warmup" in s["focus"] and s["level"] == 1 and s["name"] not in used), key=rank)
    for s in openers[:1 if training else 2]:
        left -= add(s, 1, "warm-up: big targets, slow and clean" if not training else "to start: big targets, slow and clean", "warmup")
    order = sorted(((f, w) for f, w in weights.items() if f != "warmup"), key=lambda x: -x[1])
    share = sum(w for _, w in order) or 1
    room = left - (2 if training else 0)                  # training keeps a little room for something different
    for f, w in order:
        want = max(1, round(room * w / share))
        for level in ((2, 3) if training else (2,)):       # training: medium first, then the harder ones
            for s in candidates(f, level)[:max(1, want // per_max + (want % per_max > 0))]:
                if want <= 0 or left <= 0:
                    break
                if training and level == 2 and s["level"] > 2 and want > per_max:
                    continue                               # keep the hard ones for the second half of the block
                got = add(s, min(per_max, want, left), why.get(f) or f, f)
                want -= got
                left -= got
            if want <= 0 or left <= 0:
                break
    # training: finish with something you don't train otherwise, so it isn't the same thing over and over
    if training:
        others = [f for f in ("tracking", "switching", "reaction", "flicks", "micro") if f not in weights]
        others += [f for f, _ in reversed(order)]
        for f in others:
            if left <= 0:
                break
            for s in candidates(f, 2)[:2]:
                if left <= 0:
                    break
                left -= add(s, min(per_max, left), "something different", f)
    # still room: new scenarios of what you need, before anything is repeated
    for f, _ in order:
        for s in candidates(f, 2):
            if left <= 0:
                break
            left -= add(s, min(per_max, left), why.get(f) or f, f)
    i = 0                                                  # the list has nothing new left: one more run
    while left > 0 and items and i < 100:
        items[i % len(items)]["runs"] += 1
        left -= 1
        i += 1
    return {"kind": kind, "title": label, "minutes": round(sum(x["runs"] for x in items) * SECONDS_PER_RUN / 60),
            "items": items}


def playlist_file(plan: dict, player: str, day: date | None = None) -> dict:
    """The JSON KovaaK's reads (same fields as its own playlist files). The date is in the name (DD-MM-YYYY),
    so older playlists stay next to the new one and you can tell them apart."""
    return {
        "playlistName": f"valcoach {plan['title']} {stamp(day)} ({player})"[:60],
        "playlistId": 0,
        "authorSteamId": "",
        "authorName": "valcoach",
        "scenarioList": [{"scenario_name": x["name"], "play_Count": x["runs"]} for x in plan["items"]],
        "description": "Made by valcoach from your matches: " + ", ".join(sorted({x["focus"] for x in plan["items"]})),
        "hasOfflineScenarios": False,
        "hasEdited": False,
        "shareCode": "",
        "version": 31,
    }


def stamp(day: date | None = None) -> str:
    """DD-MM-YYYY, for playlist names and file names."""
    return (day or date.today()).strftime("%d-%m-%Y")


def file_name(kind: str, day: date | None = None) -> str:
    return f"valcoach_{kind}_{stamp(day)}.json"


def run_days(runs: list[dict]) -> set[str]:
    return {r["d"] for r in runs}


def week_id(d: date | None = None) -> str:
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"
