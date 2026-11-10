"""How much a number can be trusted (4.15): recency, patch, opponent strength, buy state and sample size.

Every stats page used to count a game from three months and two patches ago like last night's game, an ACS
farmed on enemy eco rounds like one from full buys, and showed a label from 9 rounds like one from 300. This
module is the one place that decides:

- **weight(row)**: recent games count more (half the weight every HALF_LIFE_DAYS days), games from an older
  patch count PATCH_OLD as much, and a game against a lobby stronger than your own counts a bit more (weaker:
  a bit less, OPP_STEP per rank division, between OPP_MIN and OPP_MAX). Used by the comp maker (comp.Pool) and
  the coach's player facts.
- **buy_split(rows)**: rounds by buy state (full buy on both sides, you on eco / force, the enemy on eco),
  each with rounds, round win rate and K/D, so a K/D padded by anti-ecos shows.
- **opponent_split(rows)**: games against stronger / similar / weaker lobbies.
- **confidence(n, solid)**: "solid" or "early sign" for a number from n samples, the same wording everywhere,
  so the coach (and you) can tell a pattern from noise.
"""
from __future__ import annotations

from datetime import datetime, timezone

HALF_LIFE_DAYS = 45.0
PATCH_OLD = 0.6            # a game from an older patch than the newest one in the data
OPP_STEP = 0.06            # per rank division the enemy lobby is above / below yours
OPP_MIN, OPP_MAX = 0.75, 1.3
FULL_BUY = 3900            # average loadout (credits) from which a team counts as fully bought
ECO = 2000                 # below this a team is saving (eco / pistol-ish)
SIMILAR = 1.5              # lobbies within 1.5 divisions count as "similar"

EARLY = "early sign"
SOLID = "solid"


def _when(r: dict) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(r.get("started_at") or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _patch_key(p: str) -> tuple[int, int]:
    try:
        a, b = str(p).split(".")
        return int(a), int(b)
    except (ValueError, AttributeError):
        return (0, 0)


def current_patch(rows: list[dict]) -> str:
    """The newest patch any of these games was played on ("" if no game knows its patch)."""
    ps = [r.get("patch") for r in rows if r.get("patch")]
    return max(ps, key=_patch_key) if ps else ""


def opp_gap(r: dict) -> float | None:
    """How many rank divisions the enemy lobby was above (+) or below (-) your own team."""
    o, s = r.get("opp_tier"), r.get("own_tier")
    if o is None or s is None:
        return None
    return float(o) - float(s)


def weight(r: dict, now: datetime | None = None, patch: str = "") -> float:
    """How much this game counts (1.0 = a game from today, on the current patch, against an even lobby)."""
    now = now or datetime.now(timezone.utc)
    d = _when(r)
    w = 1.0
    if d is not None:
        age = max(0.0, (now - d).total_seconds() / 86400)
        w *= 0.5 ** (age / HALF_LIFE_DAYS)
    if patch and r.get("patch") and _patch_key(r["patch"]) < _patch_key(patch):
        w *= PATCH_OLD
    gap = opp_gap(r)
    if gap is not None:
        w *= min(OPP_MAX, max(OPP_MIN, 1 + OPP_STEP * gap))
    return w


def weights(rows: list[dict], now: datetime | None = None) -> list[float]:
    patch = current_patch(rows)
    return [weight(r, now, patch) for r in rows]


def weighted_summary(rows: list[dict], now: datetime | None = None) -> dict | None:
    """Win rate / ACS / K/D with the weights above, next to the plain numbers."""
    if not rows:
        return None
    ws = weights(rows, now)
    tw = sum(ws) or 1.0
    k = sum(w * r.get("kills", 0) for w, r in zip(ws, rows))
    d = sum(w * r.get("deaths", 0) for w, r in zip(ws, rows))
    return {"games": len(rows), "effective_games": round(tw, 1),
            "win_rate": sum(w * r.get("won", 0) for w, r in zip(ws, rows)) / tw,
            "acs": sum(w * r.get("acs", 0) for w, r in zip(ws, rows)) / tw,
            "kd": k / d if d else None, "patch": current_patch(rows)}


def confidence(n: float, solid: float) -> str:
    return SOLID if n >= solid else EARLY


def tag(n: float, solid: float, unit: str = "rounds") -> str:
    """"solid, 84 rounds" / "early sign, 9 rounds" (for tips and the coach)."""
    return f"{confidence(n, solid)}, {int(n)} {unit}"


# ---------------------------------------------------------------------------
# buy state
# ---------------------------------------------------------------------------
BUY_STATES = (("full", "Full buys on both sides"), ("anti_eco", "Enemy saving (anti-eco)"),
              ("own_eco", "You saving or forcing"))


def buy_state(team_avg: float, enemy_avg: float) -> str:
    if team_avg >= FULL_BUY and enemy_avg >= FULL_BUY:
        return "full"
    if team_avg >= FULL_BUY and enemy_avg < ECO:
        return "anti_eco"
    if team_avg < FULL_BUY:
        return "own_eco"
    return "mixed"


def buy_split(rows: list[dict]) -> list[dict]:
    """Rounds by buy state: {key, label, rounds, wr, kills, deaths, kd, confidence}. Needs rows from 4.15 on
    for K/D (economy entries with kills / deaths); older rows only give the round win rate."""
    acc: dict[str, list] = {k: [0, 0, 0, 0, 0] for k, _ in BUY_STATES}   # rounds, won, kills, deaths, rounds with k/d
    for r in rows:
        if r.get("source") != "full":
            continue
        for e in r.get("econ") or []:
            if len(e) < 6:
                continue
            st = buy_state(e[4], e[5])
            if st not in acc:
                continue
            a = acc[st]
            a[0] += 1
            a[1] += int(e[2])
            if len(e) >= 8:
                a[2] += int(e[6])
                a[3] += int(e[7])
                a[4] += 1
    out = []
    for key, label in BUY_STATES:
        n, won, k, d, nk = acc[key]
        if not n:
            continue
        out.append({"key": key, "label": label, "rounds": n, "wr": won / n,
                    "kd": (k / d if d else (float(k) if k else None)) if nk else None, "kills": k, "deaths": d,
                    "confidence": confidence(n, 40)})
    return out


def buy_note(split: list[dict]) -> str | None:
    """One line when the K/D mostly comes from enemy eco rounds."""
    by = {x["key"]: x for x in split}
    f, a = by.get("full"), by.get("anti_eco")
    if not f or not a or f.get("kd") is None or a.get("kd") is None or f["rounds"] < 30 or a["rounds"] < 10:
        return None
    if a["kd"] >= 1.6 * max(f["kd"], 0.1) and f["kd"] < 1.0:
        return (f"K/D {f['kd']:.2f} in full-buy rounds but {a['kd']:.2f} against saving enemies: "
                f"the overall K/D looks better than the fights that decide rounds")
    return None


# ---------------------------------------------------------------------------
# opponent strength
# ---------------------------------------------------------------------------
def opponent_split(rows: list[dict]) -> list[dict]:
    """Games against stronger / similar / weaker lobbies: {key, label, games, wr, acs, kd, confidence}."""
    groups: dict[str, list[dict]] = {"stronger": [], "similar": [], "weaker": []}
    for r in rows:
        gap = opp_gap(r)
        if gap is None:
            continue
        groups["stronger" if gap > SIMILAR else ("weaker" if gap < -SIMILAR else "similar")].append(r)
    labels = {"stronger": "Against stronger lobbies", "similar": "Against similar lobbies",
              "weaker": "Against weaker lobbies"}
    out = []
    for key, rs in groups.items():
        if not rs:
            continue
        k, d = sum(r.get("kills", 0) for r in rs), sum(r.get("deaths", 0) for r in rs)
        out.append({"key": key, "label": labels[key], "games": len(rs), "wr": sum(r.get("won", 0) for r in rs) / len(rs),
                    "acs": sum(r.get("acs", 0) for r in rs) / len(rs), "kd": k / d if d else None,
                    "confidence": confidence(len(rs), 8)})
    return out


def facts(rows: list[dict], now: datetime | None = None) -> dict:
    """Compact block for the coach's player facts."""
    pct = lambda v: None if v is None else f"{v:.0%}"     # noqa: E731
    out: dict = {}
    ws = weighted_summary(rows, now)
    if ws:
        out["weighted"] = {"note": f"recent games and the current patch ({ws['patch'] or 'unknown'}) count more, "
                                   "games against stronger lobbies a bit more",
                           "effective_games": ws["effective_games"], "win_rate": pct(ws["win_rate"]),
                           "acs": round(ws["acs"]), "kd": None if ws["kd"] is None else round(ws["kd"], 2)}
    b = buy_split(rows)
    if b:
        out["by_buy"] = [{"state": x["label"], "rounds": x["rounds"], "round_win_rate": pct(x["wr"]),
                          "kd": None if x["kd"] is None else round(x["kd"], 2), "confidence": x["confidence"]} for x in b]
        note = buy_note(b)
        if note:
            out["buy_note"] = note
    o = opponent_split(rows)
    if o:
        out["by_opponent"] = [{"lobbies": x["label"], "games": x["games"], "win_rate": pct(x["wr"]),
                               "acs": round(x["acs"]), "kd": None if x["kd"] is None else round(x["kd"], 2),
                               "confidence": x["confidence"]} for x in o]
    return out
