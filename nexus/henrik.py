"""HenrikDev API v4 client with on-disk cache and 429 handling.

Docs: https://docs.henrikdev.xyz  (API key via header `Authorization`).
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

import requests


class HenrikError(RuntimeError):
    pass


# requests made by this server (for the admin overview): (time, HTTP status, kind)
USAGE: "deque[tuple[float, int, str]]" = deque(maxlen=20000)
LIMITS: dict = {}            # the last rate-limit headers HenrikDev sent


def _kind(path: str) -> str:
    for k in ("stored-mmr-history", "stored-matches", "premier", "by-puuid/account", "matches", "match"):
        if f"/{k}/" in path:
            return {"by-puuid/account": "account", "stored-mmr-history": "rank history"}.get(k, k)
    return "other"


class HenrikClient:
    def __init__(self, api_key: str, cache_dir: Path, base_url: str = "https://api.henrikdev.xyz",
                 max_retries: int = 4, session: requests.Session | None = None):
        if not api_key:
            raise HenrikError(
                "No HenrikDev API key. Set [henrik].api_key in config.toml or HENRIK_API_KEY. "
                "Get one in the HenrikDev Discord (#get-a-key -> 'VALORANT (Basic Key)')."
            )
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self.cache = Path(cache_dir)
        (self.cache / "matches").mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.s = session or requests.Session()
        self.on_wait = None          # optional callback(str): tells the user why nothing happens

    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        for attempt in range(self.max_retries + 1):
            try:
                r = self.s.get(url, params=params, headers={"Authorization": self.api_key}, timeout=60)
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt >= self.max_retries:
                    raise HenrikError(f"HenrikDev didn't answer for {path} ({e.__class__.__name__}), "
                                      f"tried {attempt + 1} times") from e
                self._wait(5 * (attempt + 1), f"no answer from HenrikDev ({e.__class__.__name__}), retrying")
                continue
            USAGE.append((time.time(), r.status_code, _kind(path)))
            lim = {k.lower(): v for k, v in (getattr(r, "headers", None) or {}).items() if k.lower().startswith("x-ratelimit")}
            if lim:
                LIMITS.clear()
                LIMITS.update(lim, at=time.time())
            if r.status_code == 429 and attempt < self.max_retries:
                wait = r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Reset") or "5"
                try:
                    wait_s = float(wait)
                except ValueError:
                    wait_s = 5.0
                self._wait(min(max(wait_s, 1.0), 120.0), "HenrikDev rate limit reached")
                continue
            if r.status_code >= 500 and attempt < self.max_retries:
                self._wait(2 ** (attempt + 1), f"HenrikDev error {r.status_code}, retrying")
                continue
            if r.status_code != 200:
                try:
                    detail = r.json().get("errors", r.text)
                except ValueError:
                    detail = r.text[:300]
                raise HenrikError(f"HTTP {r.status_code} for {path}: {detail}")
            return r.json()
        raise HenrikError(f"Gave up on {path} after {self.max_retries} retries")

    def _wait(self, seconds: float, why: str) -> None:
        if self.on_wait:
            try:
                self.on_wait(f"  … {why}, waiting {seconds:.0f} s")
            except Exception:
                pass
        time.sleep(seconds)

    # ------------------------------------------------------------------
    def match(self, region: str, match_id: str, use_cache: bool = True) -> dict:
        """Full v4 match payload. Completed matches never change, so cache forever."""
        cp = self.cache / "matches" / f"{match_id}.json"
        if use_cache and cp.exists():
            return json.loads(cp.read_text())
        data = self._get(f"/valorant/v4/match/{region}/{match_id}")
        if data.get("data", {}).get("metadata", {}).get("is_completed", True):
            cp.write_text(json.dumps(data))
        return data

    def match_history(self, region: str, platform: str, name: str, tag: str,
                      mode: str | None = None, size: int = 10, start: int = 0) -> list[dict]:
        """Recent matches (v4). Returns the list under `data`."""
        params: dict = {"size": size}
        if mode:
            params["mode"] = mode
        if start:
            params["start"] = start
        data = self._get(f"/valorant/v4/matches/{region}/{platform}/{name}/{tag}", params)
        matches = data.get("data", []) or []
        # history entries are full matches in v4: cache them too
        for m in matches:
            mid = m.get("metadata", {}).get("match_id")
            if mid and m.get("metadata", {}).get("is_completed", True):
                (self.cache / "matches" / f"{mid}.json").write_text(json.dumps({"status": 200, "data": m}))
        return matches


    def stored_matches(self, region: str, name: str, tag: str, mode: str | None = None,
                       page: int = 1, size: int = 20) -> tuple[list[dict], dict]:
        """HenrikDev's stored match archive (summaries only, may have gaps). Cheap: 1 request.
        Returns (items, results) where results has total/returned/before/after."""
        params: dict = {"page": max(1, page), "size": size}
        if mode:
            params["mode"] = mode
        data = self._get(f"/valorant/v1/stored-matches/{region}/{name}/{tag}", params)
        return data.get("data", []) or [], data.get("results", {}) or {}


def mmr_history(client: "HenrikClient", region: str, name: str, tag: str, size: int = 50) -> list[dict]:
    """Rank and RR per competitive game (HenrikDev's stored MMR history, newest first)."""
    data = client._get(f"/valorant/v1/stored-mmr-history/{region}/{name}/{tag}", {"page": 1, "size": size})
    return data.get("data", []) or []


# ------------------------------------------------------------------ Premier
def premier_team(client: "HenrikClient", name: str, tag: str, affinity: str | None = None) -> dict:
    """Team details incl. `member` [{puuid, name, tag}], placement and stats."""
    from urllib.parse import quote
    params = {"affinity": affinity} if affinity else None
    return client._get(f"/valorant/v1/premier/{quote(name, safe='')}/{quote(tag, safe='')}", params).get("data", {}) or {}


def premier_history(client: "HenrikClient", name: str, tag: str, affinity: str | None = None) -> list[dict]:
    """League matches [{id, started_at, points_before, points_after}], newest first."""
    from urllib.parse import quote
    params = {"affinity": affinity} if affinity else None
    data = client._get(f"/valorant/v1/premier/{quote(name, safe='')}/{quote(tag, safe='')}/history", params).get("data", {}) or {}
    out = list(data.get("league_matches") or [])
    for t in data.get("tournament_matches") or []:
        for mid in t.get("matches") or []:
            out.append({"id": mid, "started_at": "", "tournament": True})
    out.sort(key=lambda m: m.get("started_at") or "", reverse=True)
    return out


def account_by_puuid(client: "HenrikClient", puuid: str) -> dict:
    """{name, tag, region, ...} for a player id (Premier rosters often come without names)."""
    return client._get(f"/valorant/v2/by-puuid/account/{puuid}").get("data", {}) or {}


def premier_team_by_id(client: "HenrikClient", team_id: str) -> dict:
    from urllib.parse import quote
    return client._get(f"/valorant/v1/premier/{quote(str(team_id), safe='')}").get("data", {}) or {}


def premier_history_by_id(client: "HenrikClient", team_id: str) -> list[dict]:
    """Like premier_history, by team id (what the leaderboard gives us)."""
    from urllib.parse import quote
    data = client._get(f"/valorant/v1/premier/{quote(str(team_id), safe='')}/history").get("data", {}) or {}
    out = list(data.get("league_matches") or [])
    for t in data.get("tournament_matches") or []:
        for mid in t.get("matches") or []:
            out.append({"id": mid, "started_at": "", "tournament": True})
    out.sort(key=lambda m: m.get("started_at") or "", reverse=True)
    return out


def premier_leaderboard(client: "HenrikClient", region: str, conference: str, division: int | str) -> list[dict]:
    """Teams of one division: [{id, name, tag, wins, losses, points, place}] (field names normalised,
    the API's are read tolerantly)."""
    from urllib.parse import quote
    data = client._get(f"/valorant/v1/premier/leaderboard/{quote(region, safe='')}/{quote(str(conference), safe='')}/"
                       f"{quote(str(division), safe='')}").get("data") or []
    if isinstance(data, dict):
        data = data.get("teams") or data.get("leaderboard") or []
    out = []
    for i, t in enumerate(data):
        if not isinstance(t, dict):
            continue
        tid = t.get("id") or t.get("team_id") or t.get("roster_id")
        name = t.get("name") or t.get("team_name")
        if not (tid and name):
            continue
        num = lambda *ks: next((t[k] for k in ks if isinstance(t.get(k), (int, float))), None)  # noqa: E731
        out.append({"id": str(tid), "name": str(name), "tag": str(t.get("tag") or t.get("team_tag") or ""),
                    "wins": num("wins", "win"), "losses": num("losses", "loss"),
                    "points": num("score", "points", "premier_score"),
                    "place": num("ranking", "place", "rank", "position") or i + 1})
    return out


def premier_seasons(client: "HenrikClient", region: str) -> list[dict]:
    from urllib.parse import quote
    data = client._get(f"/valorant/v1/premier/seasons/{quote(region, safe='')}").get("data") or []
    return data if isinstance(data, list) else [data]


def load_match_file(path: str | Path) -> dict:
    """Load a saved v4 match JSON (for offline use / tests)."""
    return json.loads(Path(path).read_text())
