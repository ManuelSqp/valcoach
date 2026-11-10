"""Playstyle labels and the situations a player thrives in (4.12).

Labels like "Aggressive" or "Clutch player" describe HOW someone plays, independent of the team role (Entry,
Anchor, ...). Situations (opening duels, clutches, retakes, post-plants, duel range, sides, alone vs with the
team, trades) say WHERE they do best and worst. Everything comes from the round data of the stored games
(games imported with rounds, "full" rows); nothing is written by the model.

Each situation is a success rate compared with a typical value for ranked games, pulled towards that value
when there are few samples (so 2 clutches won out of 2 don't make a clutch god), and only shown with enough
samples. Each label needs its own evidence and says what it is based on.
"""
from __future__ import annotations

from .evidence import BUY_STATES, buy_state, confidence
from .style import profile

PRIOR = 10                 # samples of "typical" mixed into every rate
SHOW_DIFF = 0.07           # a situation counts as good / bad from 7 points above / below typical
SOLID_X = 3               # 4.15: "solid" from 3× a situation's minimum sample, "early sign" below
BUY_BASE = {"full": 0.5, "anti_eco": 0.75, "own_eco": 0.3}     # typical round win rates by buy state
CLUTCH_BASE = {1: 0.45, 2: 0.18, 3: 0.07, 4: 0.025, 5: 0.01}   # typical 1vX win rates in ranked
RANGES = (("close", 0, 10, "close-range duels (under 10 m)"), ("mid", 10, 25, "mid-range duels (10–25 m)"),
          ("long", 25, 999, "long-range duels (25 m+)"))


def _full(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("source") == "full"]


def _rate(won: float, n: float, base: float) -> float:
    return (won + base * PRIOR) / (n + PRIOR)


def _pct(x: float) -> str:
    return f"{round(x * 100)} %"


def situations(rows: list[dict]) -> list[dict]:
    """Every situation with enough data: {key, label, n, value (shrunk), base, diff, text}."""
    full = _full(rows)
    out = []

    def add(key, label, won, n, base, min_n, text, value=None):
        if n < min_n:
            return
        v = _rate(won, n, base) if value is None else value
        conf = confidence(n, SOLID_X * min_n)
        out.append({"key": key, "label": label, "n": n, "value": v, "base": base, "diff": v - base,
                    "confidence": conf, "text": text})

    fk, fd = sum(r.get("fk", 0) for r in full), sum(r.get("fd", 0) for r in full)
    add("opening", "opening duels", fk, fk + fd, 0.5, 12, f"won {fk} of {fk + fd} first duels of the round")

    att = exp = 0.0
    won_c = 0
    for r in full:
        for x, (a, w) in (r.get("clutch") or {}).items():
            a, w = int(a), int(w)
            att += a
            won_c += w
            exp += a * CLUTCH_BASE.get(int(x), 0.01)
    if att >= 6:
        base = exp / att                      # the typical win rate for exactly these clutches
        add("clutch", "clutches", won_c, att, base, 6,
            f"won {won_c} of {int(att)} clutches (1vX), typical would be about {round(exp, 1)}")

    for key, label, base in (("retake", "retakes", 0.35), ("postplant", "post-plants", 0.65)):
        n = sum((r.get(key) or [0, 0])[0] for r in full)
        w = sum((r.get(key) or [0, 0])[1] for r in full)
        what = "defense rounds still alive at the enemy plant" if key == "retake" else "attack rounds still alive after the plant"
        add(key, label, w, n, base, 10, f"won {w} of {n} {what}")

    # 4.15: rounds by buy state (full buys on both sides, anti-eco, your own eco / force)
    buy = {k: [0, 0] for k in BUY_BASE}
    for r in full:
        for e in r.get("econ") or []:
            if len(e) >= 6:
                st = buy_state(e[4], e[5])
                if st in buy:
                    buy[st][0] += 1
                    buy[st][1] += int(e[2])
    for key, label in BUY_STATES:
        n, w = buy[key]
        add(f"buy_{key}", label.lower(), w, n, BUY_BASE[key], 20, f"won {w} of {n} rounds")

    duels = [d for r in full for d in (r.get("duels") or [])]
    for key, lo, hi, label in RANGES:
        sel = [d for d in duels if lo <= d[0] < hi]
        w = sum(d[1] for d in sel)
        add(key, label, w, len(sel), 0.5, 25, f"won {w} of {len(sel)} duels")

    # sides and alone vs with the team: kill share of fights (kills / (kills + deaths)), against your own average
    iso = {"attack": [0, 0, 0, 0], "defense": [0, 0, 0, 0]}
    for r in full:
        for s in iso:
            for i, v in enumerate((r.get("iso") or {}).get(s) or [0, 0, 0, 0]):
                iso[s][i] += v
    kills = sum(iso[s][0] for s in iso)
    deaths = sum(iso[s][2] for s in iso)
    if kills + deaths >= 40:
        mine = kills / (kills + deaths)
        for s in ("attack", "defense"):
            k, d = iso[s][0], iso[s][2]
            add(s, f"{s} rounds", k, k + d, mine, 30, f"{k} kills, {d} deaths on {s}")
        k_far, d_far = sum(iso[s][1] for s in iso), sum(iso[s][3] for s in iso)
        k_near, d_near = kills - k_far, deaths - d_far
        add("alone", "fighting away from the team", k_far, k_far + d_far, mine, 20,
            f"{k_far} kills, {d_far} deaths 20 m+ away from the nearest teammate")
        add("together", "fighting next to the team", k_near, k_near + d_near, mine, 20,
            f"{k_near} kills, {d_near} deaths close to a teammate")
    trades = sum(r.get("trade_kills", 0) for r in full)
    if kills >= 40:
        share = trades / kills
        conf = confidence(kills, 120)
        out.append({"key": "trades", "label": "trading teammates", "n": kills, "value": share, "base": 0.2,
                    "diff": share - 0.2, "confidence": conf, "text": f"{trades} of {kills} kills were trades"})
    return out


def thrives(sit: list[dict], top: int = 3) -> tuple[list[dict], list[dict]]:
    good = sorted((s for s in sit if s["diff"] >= SHOW_DIFF), key=lambda s: -s["diff"])[:top]
    # few trades mostly come with the role (the entry gets traded, doesn't trade): only ever a strength
    bad = sorted((s for s in sit if s["diff"] <= -SHOW_DIFF and s["key"] != "trades"), key=lambda s: s["diff"])[:2]
    return good, bad


def labels(rows: list[dict], prof: dict | None = None, sit: list[dict] | None = None) -> list[dict]:
    """Up to 3 playstyle labels, strongest first: {label, why}."""
    full = _full(rows)
    prof = prof or profile(rows)
    dims = prof.get("dims") or {}
    sit = {s["key"]: s for s in (sit if sit is not None else situations(rows))}
    rounds = sum(r.get("rounds", 0) for r in full) or 0
    att_r = sum((r.get("sides") or {}).get("attack", [0, 0])[0] for r in full) or 0
    first_in = sum((r.get("first_in") or {}).get("attack", 0) for r in full)
    out = []

    def add(strength, label, why):
        out.append((strength, {"label": label, "why": why}))

    opening = dims.get("opening") if not prof.get("no_openings") else None
    if opening is not None and att_r >= 40:
        fi = first_in / att_r
        if opening >= 0.68 or fi >= 0.42:
            add(max(opening, fi + 0.25), "Aggressive", f"in the first fight of {_pct(fi)} of attack rounds, "
                f"takes more opening duels than {_pct(opening)} of players in your lobbies")
        elif opening <= 0.32 and dims.get("survive", 0) >= 0.55:
            add(1 - opening, "Patient", f"rarely takes the first duel (fewer than {_pct(1 - opening)} of players), "
                f"stays alive in many rounds")
    c = sit.get("clutch")
    if c and c["n"] >= 8 and c["diff"] >= 0.06:
        add(0.7 + c["diff"], "Clutch player", c["text"])
    t = sit.get("trades")
    if t and t["value"] >= 0.27:
        add(0.6 + t["value"], "Trader", f"{t['text']}: quick to punish a teammate's death")
    a = sit.get("alone")
    if a and a["n"] >= 25:
        far_share = a["n"] / max(1, sum(s["n"] for s in sit.values() if s["key"] in ("alone", "together")))
        if far_share >= 0.35 and a["diff"] >= -0.03:      # holds up alone about as well as with the team
            add(0.6 + far_share, "Lone wolf", f"{_pct(far_share)} of fights far from the team, and holds up there "
                f"({a['text']})")
    if dims.get("survive", 0) >= 0.78:
        add(dims["survive"], "Survivor", f"dies less than {_pct(dims['survive'])} of players in your lobbies")
    if dims.get("kills", 0) >= 0.75:
        add(dims["kills"], "Fragger", f"more kills per round than {_pct(dims['kills'])} of players in your lobbies")
    if dims.get("assists", 0) >= 0.72 and dims.get("kills", 1) <= 0.6:
        add(dims["assists"], "Playmaker", f"more assists than {_pct(dims['assists'])} of players: sets up teammates")
    close, long_ = sit.get("close"), sit.get("long")
    if close and close["diff"] >= 0.07 and (not long_ or close["diff"] > long_["diff"] + 0.05):
        add(0.6 + close["diff"], "Brawler", f"strong up close: {close['text']} under 10 m")
    if long_ and long_["diff"] >= 0.07 and (not close or long_["diff"] > close["diff"] + 0.05):
        add(0.6 + long_["diff"], "Long-range duelist", f"strong at range: {long_['text']} at 25 m+")
    op_r = sum(r.get("op_rounds", 0) for r in full)
    op_k = sum(r.get("op_kills", 0) for r in full)
    if rounds and op_r / rounds >= 0.15 and op_r >= 30:
        add(0.65 + op_r / rounds, "Operator player", f"Operator in {_pct(op_r / rounds)} of rounds, "
            f"{op_k / op_r:.2f} kills per Operator round")
    out.sort(key=lambda x: -x[0])
    conf = confidence(rounds, 250)          # 4.15: every label says how much it rests on
    return [dict(x[1], confidence=conf, rounds=rounds) for x in out[:3]]


def analyse(rows: list[dict], prof: dict | None = None) -> dict:
    """{labels, thrives, struggles, situations, full_games} for one player."""
    sit = situations(rows)
    good, bad = thrives(sit)
    return {"labels": labels(rows, prof, sit), "thrives": good, "struggles": bad, "situations": sit,
            "full_games": len(_full(rows))}
