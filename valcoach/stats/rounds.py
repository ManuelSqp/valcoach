"""Round types & economy, and teammates (duos), from game rows with round data (row version 5+).

Buy types from the team's average loadout at the start of the round (what everyone carries):
  pistol   round 1 and 13 (and the first overtime rounds)
  eco      under 2,000 credits average
  force    2,000-3,900 (light buy, half buy, force)
  full     3,900 and more (rifles and full shields)
Matchups ("you vs them") show how you do when the buys are uneven: anti-eco, eco against a full buy...
"""
from __future__ import annotations

from collections import defaultdict

from .aggregate import smooth

ECO, FULL = 2000, 3900
KINDS = ["pistol", "eco", "force", "full"]
KIND_TEXT = {"pistol": "Pistol rounds", "eco": "Eco (saving)", "force": "Force / half buy", "full": "Full buy"}
MATCHUPS = [("full", "eco", "Anti-eco", "you full buy, they save: should win almost always"),
            ("full", "force", "Against a force", "you full buy, they force"),
            ("full", "full", "Full against full", "both full buy"),
            ("force", "full", "Force against a full buy", "you force, they have rifles"),
            ("eco", "full", "Eco against a full buy", "you save, they have rifles: every win is a bonus")]


def kind(rnd_no: int, avg: int) -> str:
    if rnd_no in (1, 13) or rnd_no >= 25 and (rnd_no - 25) % 2 == 0 and avg < 1000:
        return "pistol"
    if avg < ECO:
        return "eco"
    return "full" if avg >= FULL else "force"


def _rate(w: int, n: int) -> dict:
    return {"rounds": n, "won": w, "wr": w / n if n else None, "wr_s": smooth(w, n) if n else None}


def economy(rows: list[dict]) -> dict:
    full = [r for r in rows if r.get("source") == "full" and r.get("econ")]
    out: dict = {"games": len(full), "rounds": 0}
    if not full:
        return out
    k = defaultdict(lambda: [0, 0])
    mu = defaultdict(lambda: [0, 0])
    side_k = defaultdict(lambda: [0, 0])
    bonus = [0, 0]                   # the round after a won pistol
    after_loss = [0, 0]              # the round after a lost pistol
    buy_alone = [0, 0]               # you bought (rifle money) while the team saved
    saved_alone = [0, 0]             # the team full bought, you didn't
    total = 0
    for r in full:
        by_no = {e[0]: e for e in r["econ"]}
        for no, side, won, mine, team, them in r["econ"]:
            total += 1
            kk, ok = kind(no, team), kind(no, them)
            k[kk][0] += won
            k[kk][1] += 1
            side_k[(side, kk)][0] += won
            side_k[(side, kk)][1] += 1
            if kk != "pistol" and ok != "pistol":
                mu[(kk, ok)][0] += won
                mu[(kk, ok)][1] += 1
            if no in (2, 14) and (no - 1) in by_no:
                prev_won = by_no[no - 1][2]
                tgt = bonus if prev_won else after_loss
                tgt[0] += won
                tgt[1] += 1
            if kk == "eco" and mine >= FULL - 900:
                buy_alone[0] += won
                buy_alone[1] += 1
            if kk == "full" and mine < ECO:
                saved_alone[0] += won
                saved_alone[1] += 1
    out["rounds"] = total
    out["kinds"] = [dict(kind=x, text=KIND_TEXT[x], share=k[x][1] / total if total else 0, **_rate(*k[x]),
                         attack=_rate(*side_k[("attack", x)]), defense=_rate(*side_k[("defense", x)])) for x in KINDS]
    out["matchups"] = [dict(title=t, text=d, us=a, them=b, **_rate(*mu[(a, b)])) for a, b, t, d in MATCHUPS]
    out["bonus"] = _rate(*bonus)
    out["after_pistol_loss"] = _rate(*after_loss)
    out["buy_alone"] = _rate(*buy_alone)
    out["saved_alone"] = _rate(*saved_alone)
    pp = [sum(r.get("postplant", [0, 0])[i] for r in full) for i in (0, 1)]
    rt = [sum(r.get("retake", [0, 0])[i] for r in full) for i in (0, 1)]
    out["postplant"] = _rate(pp[1], pp[0])
    out["retake"] = _rate(rt[1], rt[0])
    out["notes"] = _notes(out)
    return out


def _notes(o: dict) -> list[dict]:
    """Plain-language findings, only with enough rounds."""
    notes = []
    m = {x["title"]: x for x in o["matchups"]}
    ae = m["Anti-eco"]
    if ae["rounds"] >= 8 and ae["wr"] < 0.8:
        notes.append({"bad": True, "text": f"You lose {1 - ae['wr']:.0%} of anti-eco rounds ({ae['rounds']}): against "
                      "saving teams, don't peek alone into shotguns, keep distance and trade."})
    pi = next(x for x in o["kinds"] if x["kind"] == "pistol")
    if pi["rounds"] >= 8:
        good = pi["wr"] >= 0.55
        notes.append({"bad": not good, "text": f"Pistol rounds: {pi['won']} of {pi['rounds']} won ({pi['wr']:.0%})."
                      + ("" if good else " A fixed pistol plan per side helps: who buys what, where you go.")})
    if o["bonus"]["rounds"] >= 5 and o["bonus"]["wr"] < 0.6:
        notes.append({"bad": True, "text": f"After a won pistol you win only {o['bonus']['wr']:.0%} of the next round "
                      "(it should be an easy one): play it slow, trade, don't give them free guns."})
    ba = o["buy_alone"]
    if ba["rounds"] >= 4:
        notes.append({"bad": ba["wr"] < 0.35, "text": f"{ba['rounds']}× you bought while the team saved: "
                      f"{ba['wr']:.0%} of those rounds won. Buying together with the team is usually worth more."})
    fe = m["Force against a full buy"]
    if fe["rounds"] >= 8:
        notes.append({"bad": fe["wr"] < 0.25, "text": f"Forcing against full buys: {fe['wr']:.0%} won ({fe['rounds']} rounds)."})
    if o["postplant"]["rounds"] >= 8:
        notes.append({"bad": o["postplant"]["wr"] < 0.6, "text": f"Post-plant (you alive at the plant): {o['postplant']['wr']:.0%} won."})
    if o["retake"]["rounds"] >= 8:
        notes.append({"bad": False, "text": f"Retakes (they planted, you alive): {o['retake']['wr']:.0%} won."})
    return notes


def teammates(rows: list[dict], min_games: int = 3) -> dict:
    """Who you win with: games, win rate and your numbers with each teammate (needs row version 5)."""
    withm = [r for r in rows if r.get("mates")]
    out: dict = {"games": len(withm), "mates": []}
    if not withm:
        return out
    base_wins = sum(r["won"] for r in withm)
    base = {"wr": base_wins / len(withm), "acs": sum(r["acs"] for r in withm) / len(withm)}
    out["base"] = base
    per: dict[str, list[dict]] = defaultdict(list)
    premade: dict[str, int] = defaultdict(int)
    for r in withm:
        for m in r["mates"]:
            per[m["name"]].append(r)
            premade[m["name"]] += int(m.get("premade", False))
    for name, rs in per.items():
        if len(rs) < min_games:
            continue
        w = sum(r["won"] for r in rs)
        acs = sum(r["acs"] for r in rs) / len(rs)
        out["mates"].append({"name": name, "games": len(rs), "wins": w, "wr": w / len(rs), "wr_s": smooth(w, len(rs)),
                             "acs": acs, "acs_diff": acs - base["acs"], "premade": premade[name] / len(rs),
                             "maps": sorted({r["map"] for r in rs}),
                             "last": max(r.get("started_at") or "" for r in rs)})
    out["mates"].sort(key=lambda m: (-m["games"], -m["wr_s"]))
    ranked = [m for m in out["mates"] if m["games"] >= 5]
    if len(ranked) >= 2:
        out["best"] = max(ranked, key=lambda m: m["wr_s"])
        out["worst"] = min(ranked, key=lambda m: m["wr_s"])
    out["solo"] = _solo_vs_premade(withm)
    return out


def _solo_vs_premade(rows: list[dict]) -> dict:
    solo = [r for r in rows if not any(m.get("premade") for m in r["mates"])]
    party = [r for r in rows if any(m.get("premade") for m in r["mates"])]
    f = lambda rs: {"games": len(rs), "wr": (sum(r["won"] for r in rs) / len(rs)) if rs else None,  # noqa: E731
                    "acs": (sum(r["acs"] for r in rs) / len(rs)) if rs else None}
    return {"solo": f(solo), "party": f(party)}
