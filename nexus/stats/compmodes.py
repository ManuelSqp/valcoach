"""How a team's comps are made (4.10): team settings › Comp suggestions.

  rules    Map rules + your stats (default, 4.9): your players' results plus the map rules (comprules.py)
  comfort  Most comfortable: every player on what he plays most, on this map first (comp.py, comfort_only)
  web      From the web: comps that web sources name for the map, handed to your players (webcomps.py);
           a map without comps from the web yet uses the map rules until they are fetched
  stats    Your stats only: exactly as before 4.9

The comps page, the alternatives, drafts and the Discord prep all go through plan() / top() here.
"""
from __future__ import annotations

from .comp import best_comp, team_plan, top_comps
from .comprules import for_map, load_rules
from .webcomps import comps_for

METHODS = {
    "rules": "Map rules + your stats",
    "comfort": "Most comfortable (most played)",
    "web": "From the web",
    "stats": "Your stats only (as before 4.9)",
}
DEFAULT = "rules"
NO_WEB_NOTE = "no comps from the web for this map yet: map rules + your stats instead"


def method_of(team) -> str:
    m = getattr(team, "comp_method", DEFAULT) or DEFAULT
    return m if m in METHODS else DEFAULT


def _web_entry(web: dict | None, map_name: str) -> dict | None:
    return (web or {}).get(map_name.lower())


def _fallback(comp: dict) -> dict:
    comp = dict(comp)
    comp["web_missing"] = True
    comp["notes"] = [NO_WEB_NOTE] + list(comp.get("notes") or [])
    return comp


def plan(method: str, starters, subs, maps, local, meta, rules_text: str = "", web: dict | None = None) -> list[dict]:
    """Per map: the starters' comp and the best fill-in for each starter (comp.team_plan)."""
    if method == "comfort":
        return team_plan(starters, subs, maps, local, meta,
                         solve=lambda lineup, m, lm, mm: best_comp(lineup, m, lm, mm, comfort_only=True))
    if method == "web":
        rules = load_rules(rules_text)

        def solve(lineup, m, lm, mm):
            found = comps_for(lineup, m, _web_entry(web, m), lm, mm)
            return found[0] if found else _fallback(best_comp(lineup, m, lm, mm, for_map(rules, m)))
        return team_plan(starters, subs, maps, local, meta, solve=solve)
    return team_plan(starters, subs, maps, local, meta, load_rules(rules_text) if method == "rules" else None)


def top(method: str, players, map_name: str, local=None, meta=None, rules_text: str = "", web: dict | None = None,
        n: int = 3) -> list[dict]:
    """The n best comps for these players on this map (comp.top_comps)."""
    if method == "comfort":
        return top_comps(players, map_name, local, meta, n=n, comfort_only=True)
    if method == "web":
        found = comps_for(players, map_name, _web_entry(web, map_name), local, meta)
        if found:
            return found[:n]
        out = top_comps(players, map_name, local, meta, n=n, rules=for_map(load_rules(rules_text), map_name))
        return [_fallback(c) if c.get("ok") else c for c in out]
    rules = for_map(load_rules(rules_text), map_name) if method == "rules" else None
    return top_comps(players, map_name, local, meta, n=n, rules=rules)
