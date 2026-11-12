"""You against players of your rank (4.18), from the lobbies of your own matches.

Every full match stores everyone else's numbers with the rank shown in that match (games.peer_metrics,
row v7). Per game the players within one division of your rank then count as "your rank", the players
two to four divisions above as "a rank higher". Your numbers are summed over the same games, so the
comparison is like for like: same maps, same patch, same lobbies.

  analyse(rows)  -> {"rank", "games", "same": n, "next": n, "metrics": [...], "hints": [...]} or None
  facts(rows)    -> a compact block for the coach
"""
from __future__ import annotations

from collections import Counter

from .rank import tier_id, tier_name

MIN_GAMES = 5            # your full games with lobby ranks
MIN_PEERS = 30           # player-games of your rank
SAME = 1                 # within one division = your rank
NEXT = (2, 4)            # two to four divisions higher = a rank higher
REL_GAP = 0.07           # a difference counts from 7 % (numbers) ...
PTS_GAP = 0.03           # ... or 3 points (shares)

# key, label, higher is better (None = neither: depends on the role), share (shown in %)
METRICS = (
    ("acs", "ACS", True, False),
    ("kpr", "Kills per round", True, False),
    ("dpr", "Deaths per round", False, False),
    ("apr", "Assists per round", True, False),
    ("adr", "Damage per round", True, False),
    ("hs", "Headshot share", True, True),
    ("kast", "KAST", True, True),
    ("opr", "Opening duels per round", None, False),
    ("owr", "Opening duels won", True, True),
)


def _fmt(key: str, v: float | None) -> str:
    if v is None:
        return "–"
    if key in ("hs", "kast", "owr"):
        return f"{v * 100:.0f}%"
    if key in ("acs", "adr"):
        return f"{v:.0f}"
    return f"{v:.2f}"


def _pool(entries: list[tuple[list, int]]) -> dict:
    """entries: (peer list, rounds of that match) -> averages per player-game."""
    n = len(entries)
    if not n:
        return {}
    col = lambda i: [e[0][i] for e in entries if e[0][i] is not None]     # noqa: E731
    avg = lambda xs: sum(xs) / len(xs) if xs else None                    # noqa: E731
    fk = sum(e[0][8] for e in entries)
    fd = sum(e[0][9] for e in entries)
    return {"acs": avg(col(1)), "kpr": avg(col(2)), "dpr": avg(col(3)), "apr": avg(col(4)), "adr": avg(col(5)),
            "hs": avg(col(6)), "kast": avg(col(7)),
            "opr": avg([(e[0][8] + e[0][9]) / (e[1] or 1) for e in entries]),
            "owr": fk / (fk + fd) if fk + fd else None, "n": n}


def _own(rows: list[dict]) -> dict:
    rounds = sum(r["rounds"] for r in rows) or 1
    shots = [sum(r.get("shots") or [0, 0, 0]) for r in rows]
    heads = sum((r.get("shots") or [0])[0] for r in rows)
    fk, fd = sum(r.get("fk", 0) for r in rows), sum(r.get("fd", 0) for r in rows)
    return {"acs": sum(r["acs"] * r["rounds"] for r in rows) / rounds,
            "kpr": sum(r["kills"] for r in rows) / rounds, "dpr": sum(r["deaths"] for r in rows) / rounds,
            "apr": sum(r["assists"] for r in rows) / rounds,
            "adr": sum((r.get("adr") or 0) * r["rounds"] for r in rows) / rounds,
            "hs": heads / sum(shots) if sum(shots) else None, "kast": sum(r.get("kast", 0) for r in rows) / rounds,
            "opr": (fk + fd) / rounds, "owr": fk / (fk + fd) if fk + fd else None}


def _verdict(key: str, better, you, them) -> str:
    """"good", "bad" or "" (no clear difference / neither better nor worse)."""
    if you is None or them is None or better is None:
        return ""
    gap = (you - them) if key in ("hs", "kast", "owr") else ((you - them) / them if them else 0)
    lim = PTS_GAP if key in ("hs", "kast", "owr") else REL_GAP
    if abs(gap) < lim:
        return ""
    return "good" if (gap > 0) == better else "bad"


def analyse(rows: list[dict]) -> dict | None:
    full = [r for r in rows if r.get("source") == "full" and r.get("peers") and tier_id(r.get("tier"))]
    if len(full) < MIN_GAMES:
        return None
    same: list[tuple[list, int]] = []
    nxt: list[tuple[list, int]] = []
    for r in full:
        me = tier_id(r["tier"])
        for p in r["peers"]:
            d = p[0] - me
            if abs(d) <= SAME:
                same.append((p, r["rounds"]))
            elif NEXT[0] <= d <= NEXT[1]:
                nxt.append((p, r["rounds"]))
    if len(same) < MIN_PEERS:
        return None
    you, s, h = _own(full), _pool(same), _pool(nxt) if len(nxt) >= MIN_PEERS else {}
    rank = Counter(tier_name(tier_id(r["tier"])) for r in full).most_common(1)[0][0]
    metrics = []
    for key, label, better, _share in METRICS:
        metrics.append({"key": key, "label": label, "you": _fmt(key, you[key]), "same": _fmt(key, s.get(key)),
                        "next": _fmt(key, h.get(key)) if h else None,
                        "v_same": _verdict(key, better, you[key], s.get(key)),
                        "v_next": _verdict(key, better, you[key], h.get(key)) if h else "",
                        "raw": (you[key], s.get(key), h.get(key) if h else None)})
    out = {"rank": rank, "games": len(full), "same": s["n"], "next": h.get("n", 0), "metrics": metrics}
    out["hints"] = hints(out)
    return out


def _gap(m: dict, col: int) -> float:
    you, them = m["raw"][0], m["raw"][col]
    if you is None or not them:
        return 0.0
    return abs(you - them) if m["key"] in ("hs", "kast", "owr") else abs(you - them) / them


def hints(a: dict) -> list[str]:
    out = []
    behind = sorted((m for m in a["metrics"] if m["v_same"] == "bad"), key=lambda m: -_gap(m, 1))
    ahead = sorted((m for m in a["metrics"] if m["v_same"] == "good"), key=lambda m: -_gap(m, 1))
    if ahead:
        m = ahead[0]
        out.append(f"Better than your rank in {m['label']}: {m['you']} vs {m['same']}")
    if behind:
        m = behind[0]
        out.append(f"Behind your rank in {m['label']}: {m['you']} vs {m['same']}")
    if a["next"]:
        gap = sorted((m for m in a["metrics"] if m["v_next"] == "bad"), key=lambda m: -_gap(m, 2))
        if gap:
            m = gap[0]
            out.append(f"The biggest step to the next rank is {m['label']}: {m['you']} vs {m['next']} a rank higher")
    return out


def facts(rows: list[dict]) -> dict | None:
    a = analyse(rows)
    if not a:
        return None
    return {"rank": a["rank"], "games": a["games"], "player_games_of_your_rank": a["same"],
            "you_vs_your_rank": {m["label"]: f"{m['you']} vs {m['same']}" + (f" (a rank higher {m['next']})" if m["next"] else "")
                                 for m in a["metrics"]},
            "note": "lobby players of the same rank in your own matches; opening duels depend on the role",
            "hints": a["hints"]}
