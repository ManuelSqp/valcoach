"""How every ability looks on the strat board: its shape, its size in meters and the agent's colour.

Shapes
  smoke  a sphere/cloud of radius r (drawn opaque-ish in the agent's colour, like valoplant)
  area   a circle of radius r (mollies, slows, stuns, reveals): see-through with the icon in the middle
  strip  a rectangle from where it's cast: width w, length len (min..max), starting `off` meters ahead
         (Fault Line, Rolling Thunder, Armageddon...). Drag the end handle to aim and stretch it.
  wall   a line from where it's cast: length len (min..max), thickness w (Toxic Screen, Blaze...)
  lane   two parallel walls (Neon's Fast Lane)
  (missing) just the icon

Sizes marked approx=True are estimates (the wikis don't list them, or they change with patches);
the person drawing can change every radius/length on the board. Keys are ability names as
valorant-api.com spells them, compared lowercase without punctuation.
"""
from __future__ import annotations

import re

# agent colours (fill of their smokes/areas). Controllers are the ones that matter most: everyone
# must see at a glance whose smoke is whose.
AGENT_COLORS = {
    "Omen": "#6a4bd6", "Brimstone": "#c79a5b", "Astra": "#a35cff", "Viper": "#3fcf6e", "Harbor": "#2f9fd8",
    "Clove": "#ff6fb5", "Jett": "#a9dcff", "Cypher": "#d9dde3", "Sage": "#4fe0c3", "Phoenix": "#ff7a2f",
    "Breach": "#e9852f", "Sova": "#4f8cff", "Fade": "#7d6bbf", "KAY/O": "#6fe0ff", "Skye": "#8bd15a",
    "Gekko": "#b9f23c", "Killjoy": "#ffd23f", "Chamber": "#d9b35b", "Deadlock": "#b8cfe0", "Raze": "#ff8b2b",
    "Reyna": "#c13cff", "Neon": "#3cc8ff", "Yoru": "#4a63ff", "Iso": "#8f6bff", "Vyse": "#b27cff",
    "Tejo": "#f0a640", "Waylay": "#ff9ad5", "Veto": "#9fb4c8",
}
ROLE_COLORS = {"Controller": "#8c7bd6", "Initiator": "#e9a03f", "Sentinel": "#d9d06a", "Duelist": "#ff6b5b"}

SMOKE, AREA, STRIP, WALL, LANE = "smoke", "area", "strip", "wall", "lane"

# name -> shape. src: where the number comes from (fandom = valorant.fandom.com ability page).
CATALOG: dict[str, dict] = {
    # --- smokes
    "Dark Cover":          {"k": SMOKE, "r": 4.1, "src": "fandom"},
    "Sky Smoke":           {"k": SMOKE, "r": 4.15, "src": "fandom"},
    "Cove":                {"k": SMOKE, "r": 4.6, "src": "fandom"},
    "Nebula / Dissipate":  {"k": SMOKE, "r": 4.75, "approx": True},
    "Nebula":              {"k": SMOKE, "r": 4.75, "approx": True},
    "Poison Cloud":        {"k": SMOKE, "r": 4.5, "approx": True},
    "Ruse":                {"k": SMOKE, "r": 4.1, "approx": True},
    "Cloudburst":          {"k": SMOKE, "r": 3.0, "approx": True},
    "Cyber Cage":          {"k": SMOKE, "r": 3.5, "approx": True},
    # --- walls / lines
    "Toxic Screen":        {"k": WALL, "len": 60, "min": 6, "max": 60, "w": 1.2, "src": "fandom"},
    "Blaze":               {"k": WALL, "len": 20, "min": 4, "max": 22, "w": 1.4, "approx": True},
    "High Tide":           {"k": WALL, "len": 40, "min": 5, "max": 55, "w": 1.4, "approx": True},
    "Barrier Orb":         {"k": WALL, "len": 10, "min": 10, "max": 10, "w": 1.6, "approx": True},
    "Barrier Mesh":        {"k": WALL, "len": 10, "min": 10, "max": 10, "w": 1.2, "approx": True},
    "Shear":               {"k": WALL, "len": 9, "min": 9, "max": 9, "w": 1.0, "approx": True},
    "Trapwire":            {"k": WALL, "len": 10, "min": 2, "max": 15, "w": 0.4, "approx": True},
    "Astral Form / Cosmic Divide": {"k": WALL, "len": 120, "min": 20, "max": 200, "w": 1.6, "approx": True},
    "Cosmic Divide":       {"k": WALL, "len": 120, "min": 20, "max": 200, "w": 1.6, "approx": True},
    "Fast Lane":           {"k": LANE, "len": 50, "min": 10, "max": 55, "w": 4.5, "approx": True},
    # --- strips (aim + stretch from where it's cast)
    "Fault Line":          {"k": STRIP, "w": 7.5, "len": 30, "min": 8, "max": 56, "src": "fandom"},
    "Rolling Thunder":     {"k": STRIP, "w": 23, "len": 32, "min": 32, "max": 32, "off": 8, "src": "fandom"},
    "Armageddon":          {"k": STRIP, "w": 6, "len": 30, "min": 8, "max": 50, "approx": True},
    "Hunter's Fury":       {"k": STRIP, "w": 2, "len": 66, "min": 10, "max": 66, "approx": True},
    "Nightfall":           {"k": STRIP, "w": 22, "len": 40, "min": 40, "max": 40, "approx": True},
    "Paranoia":            {"k": STRIP, "w": 6, "len": 40, "min": 40, "max": 40, "approx": True},
    "Cascade":             {"k": STRIP, "w": 12, "len": 30, "min": 5, "max": 30, "approx": True},
    "Contingency":         {"k": STRIP, "w": 8, "len": 25, "min": 5, "max": 30, "approx": True},
    "Undercut":            {"k": STRIP, "w": 2, "len": 30, "min": 30, "max": 30, "approx": True},
    "Kill Contract":       {"k": STRIP, "w": 7, "len": 40, "min": 40, "max": 40, "approx": True},
    "Convergent Paths":    {"k": STRIP, "w": 10, "len": 40, "min": 40, "max": 40, "approx": True},
    # --- areas
    "Incendiary":          {"k": AREA, "r": 4.5, "approx": True},
    "Snake Bite":          {"k": AREA, "r": 4.5, "src": "fandom"},
    "Hot Hands":           {"k": AREA, "r": 4.5, "approx": True},
    "Nanoswarm":           {"k": AREA, "r": 4.5, "approx": True},
    "Mosh Pit":            {"k": AREA, "r": 6, "approx": True},
    "Paint Shells":        {"k": AREA, "r": 6, "approx": True},
    "Blast Pack":          {"k": AREA, "r": 4, "approx": True},
    "FRAG/ment":           {"k": AREA, "r": 6, "approx": True},
    "Shock Bolt":          {"k": AREA, "r": 4, "approx": True},
    "Guided Salvo":        {"k": AREA, "r": 4, "approx": True},
    "Special Delivery":    {"k": AREA, "r": 6, "approx": True},
    "Aftershock":          {"k": AREA, "r": 3, "approx": True},
    "Slow Orb":            {"k": AREA, "r": 7, "approx": True},
    "Gravity Well":        {"k": AREA, "r": 4.75, "approx": True},
    "Nova Pulse":          {"k": AREA, "r": 4.75, "approx": True},
    "Stim Beacon":         {"k": AREA, "r": 6, "approx": True},
    "Orbital Strike":      {"k": AREA, "r": 9, "approx": True},
    "Meddle":              {"k": AREA, "r": 6, "approx": True},
    "Seize":               {"k": AREA, "r": 6, "approx": True},
    "GravNet":             {"k": AREA, "r": 6.5, "approx": True},
    "Sonic Sensor":        {"k": AREA, "r": 6, "approx": True},
    "Razorvine":           {"k": AREA, "r": 5, "approx": True},
    "Relay Bolt":          {"k": AREA, "r": 5, "approx": True},
    "Saturate":            {"k": AREA, "r": 5, "approx": True},
    "Regrowth":            {"k": AREA, "r": 18, "approx": True},
    "Recon Bolt":          {"k": AREA, "r": 30, "approx": True},
    "Haunt":               {"k": AREA, "r": 30, "approx": True},
    "Alarmbot":            {"k": AREA, "r": 6, "approx": True},
    "Trademark":           {"k": AREA, "r": 10, "approx": True},
    "Rendezvous":          {"k": AREA, "r": 15, "approx": True},
    "ZERO/point":          {"k": AREA, "r": 15, "approx": True},
    "NULL/cmd":            {"k": AREA, "r": 42.5, "approx": True},
    "Lockdown":            {"k": AREA, "r": 32.5, "approx": True},
    "Steel Garden":        {"k": AREA, "r": 32, "approx": True},
    "Viper's Pit":         {"k": AREA, "r": 17, "approx": True},
    "Reckoning":           {"k": AREA, "r": 12, "approx": True},
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_INDEX = {_norm(k): v for k, v in CATALOG.items()}


def shape_for(ability_name: str) -> dict | None:
    """The shape of an ability by name (None = icon only). Also tries the halves of "A / B" names."""
    n = _norm(ability_name)
    if n in _INDEX:
        return dict(_INDEX[n])
    for part in re.split(r"\s*/\s*", ability_name or ""):
        if _norm(part) in _INDEX and len(_norm(part)) > 3:
            return dict(_INDEX[_norm(part)])
    return None


def color_for(agent: str, role: str | None = None) -> str:
    return AGENT_COLORS.get(agent) or ROLE_COLORS.get(role or "", "#9aa4b2")
