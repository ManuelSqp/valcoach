"""Optional: real videos from the YouTube Data API v3 (needs a free API key, set in Settings).

A search costs 100 of the 10,000 daily quota units, so results are cached for a day
per query. Without a key the app shows search links instead."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://www.googleapis.com/youtube/v3/search"
CACHE_S = 24 * 3600
MAX_AGE_DAYS = 540            # skip videos from old patches


class YouTubeError(RuntimeError):
    pass


def search(api_key: str, query: str, cache_dir: Path, n: int = 3, session=None) -> list[dict]:
    """[{id, title, channel, published, thumb, url}] for a query, newest-relevant first."""
    cache = Path(cache_dir) / "youtube"
    f = cache / (hashlib.sha1(f"{query}|{n}".encode()).hexdigest()[:16] + ".json")
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_S:
        return json.loads(f.read_text())
    after = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = (session or requests).get(API, params={
        "part": "snippet", "type": "video", "q": query, "maxResults": n, "order": "relevance",
        "publishedAfter": after, "relevanceLanguage": "en", "safeSearch": "moderate", "key": api_key,
    }, timeout=10)
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        raise YouTubeError(f"YouTube API {r.status_code}: {msg}")
    out = []
    for it in r.json().get("items", []):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        if not vid:
            continue
        thumbs = sn.get("thumbnails") or {}
        out.append({"id": vid, "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                    "published": (sn.get("publishedAt") or "")[:10],
                    "thumb": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}"})
    cache.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out
