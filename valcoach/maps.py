"""Map geometry: world <-> minimap UV transforms and callout lookup.

Map transforms and callouts come from valorant-api.com (/v1/maps), cached.
The world->UV formula is the community-standard one used with those fields:

    u = y * xMultiplier + xScalarToAdd
    v = x * yMultiplier + yScalarToAdd

(u, v) are 0..1 coordinates on the map's displayIcon (the minimap image,
attacker spawn not rotated).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import requests

VALORANT_API_MAPS = "https://valorant-api.com/v1/maps"
VALORANT_API_AGENTS = "https://valorant-api.com/v1/agents?isPlayableCharacter=true"
SITE_SUPERS = {"A", "B", "C", "Mid"}


@dataclass
class Callout:
    region: str
    super_region: str
    x: float
    y: float

    @property
    def label(self) -> str:
        if self.super_region in SITE_SUPERS:
            return f"{self.super_region} {self.region}"
        if "Attacker" in self.super_region:
            return "Attacker Side " + self.region if self.region != "Spawn" else "Attacker Spawn"
        if "Defender" in self.super_region:
            return "Defender Side " + self.region if self.region != "Spawn" else "Defender Spawn"
        return f"{self.super_region} {self.region}".strip()


@dataclass
class MapInfo:
    uuid: str
    name: str
    x_mult: float
    y_mult: float
    x_add: float
    y_add: float
    display_icon: str = ""
    callouts: list[Callout] = field(default_factory=list)

    # world -> normalised minimap (0..1)
    def to_uv(self, x: float, y: float) -> tuple[float, float]:
        return (y * self.x_mult + self.x_add, x * self.y_mult + self.y_add)

    # normalised minimap -> world (inverse)
    def from_uv(self, u: float, v: float) -> tuple[float, float]:
        y = (u - self.x_add) / self.x_mult
        x = (v - self.y_add) / self.y_mult
        return x, y

    def callout_at(self, x: float, y: float) -> Callout | None:
        if not self.callouts:
            return None
        return min(self.callouts, key=lambda c: (c.x - x) ** 2 + (c.y - y) ** 2)

    def area(self, x: float, y: float) -> str:
        c = self.callout_at(x, y)
        return c.label if c else f"({int(x)},{int(y)})"

    def zone(self, x: float, y: float) -> str:
        """Coarse zone: 'A', 'B', 'C', 'Mid', 'Attacker Side', 'Defender Side'."""
        c = self.callout_at(x, y)
        return c.super_region if c else "?"


def _parse_maps(payload: dict) -> list[MapInfo]:
    out = []
    for m in payload.get("data", []):
        if m.get("xMultiplier") in (None, 0):
            continue  # menu/range maps without a playable minimap
        callouts = [
            Callout(
                region=c.get("regionName", ""),
                super_region=c.get("superRegionName", ""),
                x=float(c["location"]["x"]),
                y=float(c["location"]["y"]),
            )
            for c in (m.get("callouts") or [])
            if c.get("location")
        ]
        out.append(MapInfo(
            uuid=m.get("uuid", ""),
            name=m.get("displayName", ""),
            x_mult=float(m["xMultiplier"]),
            y_mult=float(m["yMultiplier"]),
            x_add=float(m["xScalarToAdd"]),
            y_add=float(m["yScalarToAdd"]),
            display_icon=m.get("displayIcon") or "",
            callouts=callouts,
        ))
    return out


class MapRegistry:
    def __init__(self, cache_dir: Path):
        self.cache_file = Path(cache_dir) / "valorant_api_maps.json"
        self._maps: list[MapInfo] | None = None

    def load(self, refresh: bool = False) -> list[MapInfo]:
        if self._maps is not None and not refresh:
            return self._maps
        if refresh or not self.cache_file.exists():
            r = requests.get(VALORANT_API_MAPS, timeout=30)
            r.raise_for_status()
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(r.text)
        self._maps = _parse_maps(json.loads(self.cache_file.read_text()))
        return self._maps

    def get(self, map_id: str = "", name: str = "") -> MapInfo | None:
        maps = self.load()
        for m in maps:
            if map_id and m.uuid.lower() == map_id.lower():
                return m
        for m in maps:
            if name and m.name.lower() == name.lower():
                return m
        return None

    def minimap_image(self, info: MapInfo) -> Path | None:
        """Download & cache the minimap image (used by minimap calibration)."""
        if not info.display_icon:
            return None
        p = self.cache_file.parent / "minimaps" / f"{info.uuid}.png"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            r = requests.get(info.display_icon, timeout=60)
            r.raise_for_status()
            p.write_bytes(r.content)
        return p


class AgentRegistry:
    """Agent icons from valorant-api.com, cached on disk (list + one small PNG per agent)."""

    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.list_file = self.dir / "valorant_api_agents.json"
        self._agents: list[dict] | None = None

    def load(self, refresh: bool = False) -> list[dict]:
        if self._agents is not None and not refresh:
            return self._agents
        if refresh or not self.list_file.exists():
            r = requests.get(VALORANT_API_AGENTS, timeout=30)
            r.raise_for_status()
            self.dir.mkdir(parents=True, exist_ok=True)
            self.list_file.write_text(r.text)
        data = json.loads(self.list_file.read_text()).get("data", []) or []
        self._agents = [{
            "uuid": a.get("uuid", ""), "name": a.get("displayName", ""),
            "icon": a.get("displayIconSmall") or a.get("displayIcon") or "",
            "role": (a.get("role") or {}).get("displayName", ""),
            "abilities": [{"slot": ab.get("slot", ""), "name": ab.get("displayName", ""), "icon": ab.get("displayIcon") or ""}
                          for ab in (a.get("abilities") or []) if ab.get("slot") and ab.get("slot") != "Passive"],
        } for a in data]
        return self._agents

    def find(self, agent_id: str = "", name: str = "") -> dict | None:
        agents = self.load()
        for a in agents:
            if agent_id and a["uuid"].lower() == agent_id.lower():
                return a
        for a in agents:
            if name and a["name"].lower() == name.lower():
                return a
        return None

    def icon_file(self, agent: dict) -> Path | None:
        """Local copy of the agent's icon (downloaded on first use)."""
        if not agent.get("icon") or not agent.get("uuid"):
            return None
        p = self.dir / "agents" / f"{agent['uuid'].lower()}.png"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            r = requests.get(agent["icon"], timeout=30)
            r.raise_for_status()
            p.write_bytes(r.content)
        return p


    def ability_icon_file(self, agent: dict, slot: str) -> Path | None:
        """Local copy of one ability icon (white on transparent), downloaded on first use."""
        ab = next((x for x in agent.get("abilities", []) if x["slot"].lower() == slot.lower()), None)
        if ab is None or not ab.get("icon"):
            return None
        p = self.dir / "abilities" / f"{agent['uuid'].lower()}_{ab['slot'].lower()}.png"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            r = requests.get(ab["icon"], timeout=30)
            r.raise_for_status()
            p.write_bytes(r.content)
        return p


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)
