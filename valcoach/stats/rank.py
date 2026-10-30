"""Rank over time (Progress tab): competitive rank and RR per game.

Source 1: HenrikDev's stored MMR history (rank, RR, RR change per competitive game), fetched on
import and kept in profiles/<id>/stats/rank.json (the API only keeps a limited window, so
older entries are kept locally). Source 2, when that's empty: the rank shown in each match.
"Points" = (tier - Iron 1) * 100 + RR, so one tier is 100 points."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIERS = ["Unrated", "Unused 1", "Unused 2",
         "Iron 1", "Iron 2", "Iron 3", "Bronze 1", "Bronze 2", "Bronze 3", "Silver 1", "Silver 2", "Silver 3",
         "Gold 1", "Gold 2", "Gold 3", "Platinum 1", "Platinum 2", "Platinum 3", "Diamond 1", "Diamond 2", "Diamond 3",
         "Ascendant 1", "Ascendant 2", "Ascendant 3", "Immortal 1", "Immortal 2", "Immortal 3", "Radiant"]
MAX_KEEP = 400


def tier_id(name) -> int | None:
    if isinstance(name, int) and not isinstance(name, bool):
        return name if 3 <= name < len(TIERS) else None
    n = str(name or "").strip().lower()
    for i, t in enumerate(TIERS):
        if i >= 3 and t.lower() == n:
            return i
    return None


def tier_name(tid: int | None) -> str:
    return TIERS[tid] if tid is not None and 3 <= tid < len(TIERS) else ""


def points(tid: int, rr: int | float) -> float:
    return (tid - 3) * 100 + float(rr)


def _ts(s) -> str:
    if not s:
        return ""
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s, timezone.utc).isoformat(timespec="seconds")
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")
    except ValueError:
        return ""


def parse_entries(items) -> list[dict]:
    """HenrikDev MMR history items (stored v1 or recent v1 shapes) -> entries."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        tier = it.get("tier")
        tid = tier_id(tier.get("id") if isinstance(tier, dict) else tier)
        if tid is None:
            tid = tier_id(it.get("currenttier")) or tier_id(it.get("currenttierpatched") or (tier.get("name") if isinstance(tier, dict) else None))
        rr = it.get("ranking_in_tier", it.get("rr"))
        date = _ts(it.get("date_raw") or it.get("date"))
        if tid is None or not isinstance(rr, (int, float)) or not date:
            continue
        change = it.get("last_mmr_change", it.get("mmr_change_to_last_game", it.get("last_change")))
        m = it.get("map")
        out.append({"match_id": str(it.get("match_id") or ""), "date": date, "tier": tid, "rr": int(rr),
                    "change": int(change) if isinstance(change, (int, float)) else None,
                    "map": (m.get("name") if isinstance(m, dict) else m) or ""})
    return out


class RankStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text()).get("entries", []) if self.path.exists() else []
        except ValueError:
            return []

    def merge(self, new: list[dict]) -> int:
        have = {(e.get("match_id") or e["date"]): e for e in self.load()}
        added = 0
        for e in new:
            k = e.get("match_id") or e["date"]
            if k not in have:
                added += 1
            have[k] = e
        entries = sorted(have.values(), key=lambda e: e["date"])[-MAX_KEEP:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"entries": entries}))
        tmp.replace(self.path)
        return added


def series(entries: list[dict], rows: list[dict]) -> tuple[list[dict], str]:
    """Points per competitive game, oldest first, and where they come from."""
    if entries:
        return [{**e, "pts": points(e["tier"], e["rr"]), "name": tier_name(e["tier"])} for e in sorted(entries, key=lambda e: e["date"])], "rr"
    out = []
    for r in sorted(rows, key=lambda r: r.get("started_at", "")):
        tid = tier_id(r.get("tier"))
        if r.get("queue") == "competitive" and tid is not None:
            out.append({"match_id": r.get("match_id"), "date": r.get("started_at", ""), "tier": tid, "rr": None, "change": None,
                        "map": r.get("map", ""), "pts": points(tid, 50), "name": tier_name(tid), "won": r.get("won")})
    return out, "match"


def chart(pts: list[dict], width: int = 720, height: int = 220, last: int = 80) -> dict | None:
    """SVG-ready numbers: the line, a dot per game and the tier lines in range."""
    pts = pts[-last:]
    if len(pts) < 2:
        return None
    vals = [p["pts"] for p in pts]
    lo = (min(vals) // 100) * 100
    hi = (max(vals) // 100 + 1) * 100
    if hi - lo < 200:
        hi = lo + 200
    pad_l, pad_r, pad_t, pad_b = 92, 12, 10, 22
    W, H = width - pad_l - pad_r, height - pad_t - pad_b
    xs = lambda i: pad_l + (W * i / (len(pts) - 1))
    ys = lambda v: pad_t + H * (1 - (v - lo) / (hi - lo))
    dots = [{"x": round(xs(i), 1), "y": round(ys(p["pts"]), 1), "up": (p["change"] or 0) > 0 if p.get("change") is not None else None,
             "title": f"{p['date'][:10]} · {p['name']}{(' ' + str(p['rr']) + ' RR') if p.get('rr') is not None else ''}"
                      f"{(' (' + ('+' if p['change'] > 0 else '') + str(p['change']) + ')') if p.get('change') is not None else ''}"
                      f"{(' · ' + p['map']) if p.get('map') else ''}"} for i, p in enumerate(pts)]
    lines = []
    for v in range(int(lo), int(hi) + 1, 100):
        tid = v // 100 + 3
        lines.append({"y": round(ys(v), 1), "label": tier_name(tid) if v < hi else "",     # the tier above each line,
                      "ly": round(ys(v + 50) + 4, 1)})                                     # named in the middle of its band
    return {"w": width, "h": height, "path": " ".join(f"{'M' if i == 0 else 'L'}{d['x']},{d['y']}" for i, d in enumerate(dots)),
            "dots": dots, "lines": lines, "x0": pad_l, "x1": width - pad_r, "first": pts[0]["date"][:10], "last": pts[-1]["date"][:10],
            "bottom": height - 4}


def summary(pts: list[dict], now: datetime | None = None) -> dict | None:
    if not pts:
        return None
    now = now or datetime.now(timezone.utc)
    cur = pts[-1]
    cut = (now - timedelta(days=14)).isoformat()
    before = [p for p in pts if p["date"] < cut]
    peak = max(pts, key=lambda p: p["pts"])
    recent = [p for p in pts if p["date"] >= cut]
    return {"name": cur["name"], "rr": cur.get("rr"), "pts": cur["pts"], "games": len(pts),
            "delta14": round(cur["pts"] - before[-1]["pts"]) if before and recent else None,
            "games14": len(recent), "peak": peak["name"] + (f" {peak['rr']} RR" if peak.get("rr") is not None else ""),
            "peak_date": peak["date"][:10]}
