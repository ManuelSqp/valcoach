"""Map rules for team comps (4.9): the "Map rules + your stats" method.

The stats method (comp.py, as before 4.9) rates each player's agents from their own results and only
requires the basic roles. This adds what the stats can't know, from stats/comp_rules.yaml (editable
in Settings › Map rules for team comps):
  * per map: role mixes that work there, agents the map needs (Viper on Breeze), key and good agents
  * for every comp: a controller, no more than two duelists, someone to flash corners, someone for info
Each rule that changes a comp is listed with its reason, so the suggestion explains itself. The players'
own results (comp.rate) still count as before; a team's own map meta (prefer / avoid / roles) wins.

Switch per team in the team settings: "Comp suggestions" (all modes: compmodes.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import roles

DEFAULT_RULES = Path(__file__).with_name("comp_rules.yaml")

NEED_ROLE = 60          # per missing required role (no controller)
OVER_ROLE = 18          # per agent above a role's maximum
WANT_DEFAULT = 10
PATTERN_FIT = 8         # the comp has one of the map's role mixes
PATTERN_STEP = 10       # per role slot away from the closest mix
NEED_AGENT = 25         # none of the agents the map needs
NEED_BONUS = 12         # per player, for an agent the map needs
KEY_BONUS = 8
GOOD_BONUS = 3
LETTER = {"D": "Duelist", "I": "Initiator", "C": "Controller", "S": "Sentinel"}


def _pattern(text: str, where: str) -> dict[str, int]:
    out = {}
    for part in str(text).split():
        if len(part) < 2 or not part[:-1].isdigit() or part[-1].upper() not in LETTER:
            raise ValueError(f"{where}: role mixes look like '1D 2I 1C 1S'")
        out[LETTER[part[-1].upper()]] = int(part[:-1])
    if sum(out.values()) != 5:
        raise ValueError(f"{where}: a role mix must add up to 5 ({text})")
    return out


def _role_counts(text_map, where: str) -> dict[str, int]:
    if not text_map:
        return {}
    if not isinstance(text_map, dict):
        raise ValueError(f"{where}: expected role: number")
    out = {}
    for r, n in text_map.items():
        if r not in roles.ROLES:
            raise ValueError(f"{where}: unknown role {r!r} (use {', '.join(roles.ROLES)})")
        out[r] = int(n)
    return out


def _agents_why(v, where: str) -> dict[str, str]:
    """[A, B] or {A: why} -> {Agent: why} ("" when no reason is given)."""
    if not v:
        return {}
    if isinstance(v, list):
        return {str(a): "" for a in v}
    if isinstance(v, dict):
        return {str(a): str(w or "") for a, w in v.items()}
    raise ValueError(f"{where}: expected a list of agents or agent: reason")


@dataclass
class MapRules:
    map: str = ""
    need_roles: dict[str, int] = field(default_factory=dict)
    max_roles: dict[str, int] = field(default_factory=dict)
    patterns: list[dict[str, int]] = field(default_factory=list)
    want: list[dict] = field(default_factory=list)            # {name, agents (lower set), points, why}
    need: dict[str, str] = field(default_factory=dict)        # Agent -> why
    key: dict[str, str] = field(default_factory=dict)
    good: dict[str, str] = field(default_factory=dict)
    known_map: bool = False

    # ---- one agent -----------------------------------------------------------
    def agent_bonus(self, agent: str) -> tuple[float, str | None]:
        a = agent.lower()
        for table, pts, label in ((self.need, NEED_BONUS, "needed on"), (self.key, KEY_BONUS, "key on"),
                                  (self.good, GOOD_BONUS, "fits")):
            for name, why in table.items():
                if name.lower() == a:
                    return pts, (f"{label} {self.map}: {why}" if why else f"{label} {self.map}")
        return 0.0, None

    # ---- a whole comp --------------------------------------------------------
    def comp_score(self, agents: list[str], user_pattern: dict | None = None) -> tuple[float, list[str], list[str]]:
        """(points, notes shown with the comp, missing roles)"""
        counts: dict[str, int] = {}
        for a in agents:
            counts[roles.role_of(a)] = counts.get(roles.role_of(a), 0) + 1
        lower = {a.lower() for a in agents}
        pts, notes, missing = 0.0, [], []
        for r, n in self.need_roles.items():
            short = n - counts.get(r, 0)
            if short > 0:
                pts -= NEED_ROLE * short
                missing.append(r)
                notes.append(f"no {r.lower()}" if n == 1 else f"{short} more {r.lower()} needed")
        for r, n in self.max_roles.items():
            over = counts.get(r, 0) - n
            if over > 0:
                pts -= OVER_ROLE * over
                notes.append(f"{counts[r]} {r.lower()}s (at most {n})")
        for w in self.want:
            if not lower & w["agents"]:
                pts -= w["points"]
                notes.append(w["why"] or f"no {w['name']}")
        if not user_pattern and self.patterns:   # a team's own role mix (team meta) is handled by comp.py
            dist = min(sum(abs(counts.get(r, 0) - p.get(r, 0)) for r in roles.ROLES) / 2 for p in self.patterns)
            if dist == 0:
                pts += PATTERN_FIT
            else:
                pts -= PATTERN_STEP * dist
                best = min(self.patterns, key=lambda p: sum(abs(counts.get(r, 0) - p.get(r, 0)) for r in roles.ROLES))
                notes.append(f"role mix off what works on {self.map or 'this map'} "
                             f"({' '.join(f'{best.get(r, 0)}{r[0]}' for r in roles.ROLES)})")
                for r in roles.ROLES:          # "missing" = nobody plays it at all (the page says so)
                    if counts.get(r, 0) == 0 and best.get(r, 0) and r not in missing:
                        missing.append(r)
        if self.need and not lower & {a.lower() for a in self.need}:
            pts -= NEED_AGENT
            names = " or ".join(self.need)
            why = next(iter(self.need.values()), "")
            notes.append(f"no {names}" + (f": {why}" if why else ""))
        return pts, notes, missing


def parse_rules(text: str) -> dict:
    """YAML text -> {"general": {...}, "maps": {map_lower: {...}}} (validated). Raises ValueError."""
    data = yaml.safe_load(text or "") or {}
    if not isinstance(data, dict):
        raise ValueError("expected 'general:' and 'maps:'")
    g = data.get("general") or {}
    if not isinstance(g, dict):
        raise ValueError("general: expected need / max / roles / want")
    want = []
    for name, w in (g.get("want") or {}).items():
        if not isinstance(w, dict) or not isinstance(w.get("agents"), list):
            raise ValueError(f"general › want › {name}: expected agents: [..], points, why")
        want.append({"name": str(name), "agents": {str(a).lower() for a in w["agents"]},
                     "points": float(w.get("points", WANT_DEFAULT)), "why": str(w.get("why") or "")})
    general = {"need_roles": _role_counts(g.get("need"), "general › need"),
               "max_roles": _role_counts(g.get("max"), "general › max"),
               "patterns": [_pattern(p, "general › roles") for p in (g.get("roles") or [])],
               "want": want}
    maps = {}
    for m, v in (data.get("maps") or {}).items():
        v = v or {}
        if not isinstance(v, dict):
            raise ValueError(f"maps › {m}: expected roles / need / key / good")
        maps[str(m).lower()] = {
            "name": str(m),
            "patterns": [_pattern(p, f"maps › {m} › roles") for p in (v.get("roles") or [])],
            "need": _agents_why(v.get("need"), f"maps › {m} › need"),
            "key": _agents_why(v.get("key"), f"maps › {m} › key"),
            "good": _agents_why(v.get("good"), f"maps › {m} › good"),
        }
    return {"general": general, "maps": maps}


def load_rules(text: str = "") -> dict:
    """The admin's edited rules (Settings), else the built-in file. Broken edited rules fall back to built-in."""
    if text and text.strip():
        try:
            return parse_rules(text)
        except Exception:
            pass
    return parse_rules(DEFAULT_RULES.read_text())


def for_map(rules: dict, map_name: str) -> MapRules:
    g = rules.get("general") or {}
    m = (rules.get("maps") or {}).get(map_name.lower())
    return MapRules(
        map=m["name"] if m else map_name,
        need_roles=dict(g.get("need_roles") or {}), max_roles=dict(g.get("max_roles") or {}),
        patterns=list(m["patterns"]) if m and m["patterns"] else list(g.get("patterns") or []),
        want=list(g.get("want") or []),
        need=dict(m["need"]) if m else {}, key=dict(m["key"]) if m else {}, good=dict(m["good"]) if m else {},
        known_map=m is not None,
    )


def for_team(team, rules_text: str = "") -> dict | None:
    """The parsed rules if this team uses "Map rules + your stats", else None."""
    if (getattr(team, "comp_method", "rules") or "rules") != "rules":
        return None
    return load_rules(rules_text)
