"""Server overview (/admin/overview): HenrikDev use, the model, background jobs, disk space.

Admins see it; an admin can also give it to someone else (Users › user › "Can see the server
overview") without making them admin. It shows no API keys, passwords, logs or anyone's games."""
from __future__ import annotations

import functools
import os
import platform
import shutil
import time
from collections import Counter
from pathlib import Path

import requests
from flask import abort, g, render_template

PERM = "overview"
JOB_NAMES = {"import": "history import", "tips": "playstyle tips", "premier": "Premier roster", "plans": "game plans",
             "focus": "weekly focus", "post": "Discord post", "scout": "scouting", "review": "match reviews",
             "schedule": "season schedule", "watch": "what to watch", "quiz": "quiz"}
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def dir_size(p: Path) -> tuple[int, int]:
    """(bytes, files) under a folder."""
    total = n = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return total, n


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def henrik_usage(now: float | None = None) -> dict:
    from ..henrik import LIMITS, USAGE
    now = now or time.time()
    rows = list(USAGE)
    hour = [r for r in rows if now - r[0] < 3600]
    day = [r for r in rows if now - r[0] < 86400]
    per_min = Counter(int((now - r[0]) // 60) for r in hour)
    return {"hour": len(hour), "day": len(day), "limited_hour": sum(1 for r in hour if r[1] == 429),
            "errors_hour": sum(1 for r in hour if r[1] >= 400 and r[1] != 429),
            "busiest_minute": max(per_min.values(), default=0),
            "by_kind": Counter(r[2] for r in day).most_common(),
            "minutes": [per_min.get(m, 0) for m in range(59, -1, -1)],       # oldest -> newest
            "limits": {k.replace("x-ratelimit-", ""): v for k, v in LIMITS.items() if k != "at"},
            "limits_age_s": int(now - LIMITS["at"]) if LIMITS.get("at") else None}


def model_usage(url: str, now: float | None = None) -> dict:
    from ..coach.ollama import RECENT
    now = now or time.time()
    day = [r for r in RECENT if now - r[0] < 86400]

    def probe():
        out = {"reachable": False, "loaded": [], "installed": 0, "error": ""}
        try:
            tags = requests.get(f"{url.rstrip('/')}/api/tags", timeout=2)
            tags.raise_for_status()
            out["installed"] = len(tags.json().get("models", []))
            out["reachable"] = True
            ps = requests.get(f"{url.rstrip('/')}/api/ps", timeout=2)
            if ps.ok:
                out["loaded"] = [{"name": m.get("name", "?"), "vram": human(m.get("size_vram") or 0)} for m in ps.json().get("models", [])]
        except (requests.RequestException, ValueError) as e:
            out["error"] = e.__class__.__name__
        return out
    return {**_cached(f"ollama:{url}", 30, probe), "requests_day": len(day),
            "avg_s": round(sum(r[1] for r in day) / len(day), 1) if day else None,
            "tokens_day": sum(r[2] for r in day)}


def disk(data_dir: Path) -> dict:
    def measure():
        parts = []
        for name, label in (("cache", "Match cache (HenrikDev)"), ("profiles", "Players (games, tips, quizzes)"),
                            ("teams", "Teams (plans, focus, scouting, reviews)"), ("reports", "Coaching reports"),
                            ("uploads", "Uploaded VODs"), ("tmp", "Uploads in progress")):
            p = data_dir / name
            if p.exists():
                size, n = dir_size(p)
                parts.append({"label": label, "bytes": size, "size": human(size), "files": n})
        db = data_dir / "valcoach.db"
        if db.exists():
            parts.append({"label": "Database", "bytes": db.stat().st_size, "size": human(db.stat().st_size), "files": 1})
        du = shutil.disk_usage(data_dir)
        total = sum(p["bytes"] for p in parts)
        return {"parts": sorted(parts, key=lambda p: -p["bytes"]), "total": human(total),
                "free": human(du.free), "disk": human(du.total), "free_pct": du.free / du.total if du.total else None,
                "measured": time.time()}
    return _cached(f"disk:{data_dir}", 300, measure)


def register(app, store, started_at: float) -> None:
    def overview_required(view):
        @functools.wraps(view)
        def wrapped(*a, **k):
            if not g.user.can(PERM):
                abort(403)
            return view(*a, **k)
        return wrapped

    @app.get("/admin/overview")
    @overview_required
    def overview():
        from .. import __version__
        ext = app.extensions["valcoach"]
        sr = ext["stats"]
        now = time.time()
        # background jobs: what runs now, and what failed lately (kinds only, no logs or names)
        states = sr.states()
        active = [{"kind": JOB_NAMES.get(k.split(":")[0], k.split(":")[0]), "status": v["status"], "age_s": int(now - v["t"])}
                  for k, v in states.items() if v["status"] in ("queued", "running")]
        failed = [{"kind": JOB_NAMES.get(k.split(":")[0], k.split(":")[0]), "error": (v["error"] or "")[:140], "age_s": int(now - v["t"])}
                  for k, v in states.items() if v["status"] == "error" and now - v["t"] < 86400]
        done_day = Counter(JOB_NAMES.get(k.split(":")[0], k.split(":")[0]) for k, v in states.items()
                           if v["status"] == "done" and now - v["t"] < 86400)
        coach = {s: len(store.jobs_with_status(s)) for s in ("queued", "running")}
        counts = {"users": store.user_count(), "teams": len(store.all_teams()),
                  "players": int(store._all("SELECT COUNT(*) AS n FROM profiles")[0]["n"])}
        return render_template(
            "overview.html", version=__version__, uptime_s=int(now - started_at), py=platform.python_version(),
            henrik=henrik_usage(now), model=model_usage(store.get("ollama_url"), now), model_name=store.get("ollama_model"),
            disk=disk(store.data_dir), active=sorted(active, key=lambda a: -a["age_s"]), failed=sorted(failed, key=lambda f: f["age_s"])[:10],
            done_day=done_day.most_common(), coach=coach, counts=counts,
            tick_age_s=int(now - sr.last_tick) if sr.last_tick else None, has_key=bool(store.get("henrik_api_key")))
