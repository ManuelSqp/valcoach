"""Agent roles. valorant-api.com is the source (new agents appear there first); this
table is the offline fallback."""
from __future__ import annotations

from pathlib import Path

ROLES = ["Duelist", "Initiator", "Controller", "Sentinel"]

FALLBACK = {
    "Jett": "Duelist", "Phoenix": "Duelist", "Reyna": "Duelist", "Raze": "Duelist", "Yoru": "Duelist",
    "Neon": "Duelist", "Iso": "Duelist", "Waylay": "Duelist",
    "Sova": "Initiator", "Breach": "Initiator", "Skye": "Initiator", "KAY/O": "Initiator", "Fade": "Initiator",
    "Gekko": "Initiator", "Tejo": "Initiator",
    "Brimstone": "Controller", "Omen": "Controller", "Viper": "Controller", "Astra": "Controller",
    "Harbor": "Controller", "Clove": "Controller",
    "Killjoy": "Sentinel", "Cypher": "Sentinel", "Sage": "Sentinel", "Chamber": "Sentinel",
    "Deadlock": "Sentinel", "Vyse": "Sentinel", "Veto": "Sentinel",
}

_cache: dict[str, str] = {}


def load(cache_dir: Path | None) -> dict[str, str]:
    """Agent name -> role, from the cached valorant-api.com agent list plus the fallback."""
    out = dict(FALLBACK)
    if cache_dir is not None:
        try:
            import json
            f = Path(cache_dir) / "valorant_api_agents.json"
            if f.exists():
                for a in json.loads(f.read_text()).get("data", []) or []:
                    role = (a.get("role") or {}).get("displayName")
                    if a.get("displayName") and role in ROLES:
                        out[a["displayName"]] = role
        except Exception:
            pass
    _cache.update(out)
    return out


def role_of(agent: str) -> str:
    return _cache.get(agent) or FALLBACK.get(agent) or "?"


def all_agents() -> list[str]:
    return sorted(set(_cache) | set(FALLBACK))
