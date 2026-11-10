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


def loaded_model(m: dict) -> dict:
    """One entry of Ollama's /api/ps: how much of the model is in GPU memory. `size` is everything the model
    takes right now (weights + context), `size_vram` the part of it on the GPU; the rest runs on the CPU (slow)."""
    size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
    share = vram / size if size else (1.0 if vram else 0.0)
    if not size and not vram:
        where = "cpu"
    elif share >= 0.995:
        where = "gpu"
    elif vram == 0:
        where = "cpu"
    else:
        where = "split"
    return {"name": m.get("name", "?"), "size": human(size), "vram": human(vram), "share": share, "where": where,
            "context": int(m.get("context_length") or 0), "until": str(m.get("expires_at") or "")[:16].replace("T", " ")}


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
                out["loaded"] = [loaded_model(m) for m in ps.json().get("models", [])]
        except (requests.RequestException, ValueError) as e:
            out["error"] = e.__class__.__name__
        return out
    return {**_cached(f"ollama:{url}", 30, probe), "requests_day": len(day),
            "avg_s": round(sum(r[1] for r in day) / len(day), 1) if day else None,
            "tokens_day": sum(r[2] for r in day)}


def claude_usage(store) -> dict:
    from datetime import datetime
    from ..coach.llm import LABELS, read_usage
    u = read_usage()
    month = u.get("months", {}).get(datetime.now().strftime("%Y-%m"), {})
    today = u.get("days", {}).get(datetime.now().strftime("%Y-%m-%d"), {})
    days = sorted(u.get("days", {}).items())[-30:]
    budget = float(store.get("claude_budget_usd") or 0)
    spent = sum(v.get("usd", 0) for v in month.values())
    return {"key": bool(store.get("claude_api_key")), "month": spent, "today": sum(v.get("usd", 0) for v in today.values()),
            "budget": budget, "left_pct": (1 - spent / budget) if budget else None,
            "models": sorted(({"label": LABELS.get(m, m), "calls": v["calls"], "usd": v["usd"], "in": v["in"], "out": v["out"]}
                              for m, v in month.items()), key=lambda x: -x["usd"]),
            "days": [{"day": d, "usd": sum(x.get("usd", 0) for x in v.values())} for d, v in days]}


def disk(data_dir: Path) -> dict:
    def measure():
        parts = []
        for name, label in (("cache", "Match cache (HenrikDev)"), ("profiles", "Players (games, tips, quizzes)"),
                            ("teams", "Teams (plans, focus, scouting, reviews)"), ("reports", "Coaching reports"),
                            ("uploads", "Uploaded VODs"), ("replays", "Replay files"), ("tmp", "Uploads in progress")):
            p = data_dir / name
            if p.exists():
                size, n = dir_size(p)
                parts.append({"label": label, "bytes": size, "size": human(size), "files": n})
        db = data_dir / "nexus.db"
        if db.exists():
            parts.append({"label": "Database", "bytes": db.stat().st_size, "size": human(db.stat().st_size), "files": 1})
        du = shutil.disk_usage(data_dir)
        total = sum(p["bytes"] for p in parts)
        return {"parts": sorted(parts, key=lambda p: -p["bytes"]), "total": human(total),
                "free": human(du.free), "disk": human(du.total), "free_pct": du.free / du.total if du.total else None,
                "measured": time.time()}
    return _cached(f"disk:{data_dir}", 300, measure)


def replays(data_dir: Path, vrfkit: str = "") -> dict:
    """Replay files on the server (4.16.1): how many, how big, how recent, how many could be used."""
    def measure():
        import json
        from .. import replayfile
        d = Path(data_dir) / "replays"
        ids = replayfile.stored(d)
        now = time.time()
        vrf = data = size = 0
        newest = None
        week = month = 0
        lined_up = casts = 0
        maps: Counter = Counter()
        for mid in ids:
            when = None
            for suffix in (".json.gz", ".vrf"):
                f = d / f"{mid}{suffix}"
                if f.is_file():
                    st = f.stat()
                    size += st.st_size
                    when = max(when or 0, st.st_mtime)
                    vrf += suffix == ".vrf"
                    data += suffix == ".json.gz"
            if when:
                newest = max(newest or 0, when)
                week += now - when < 7 * 86400
                month += now - when < 30 * 86400
            m = d / f"{mid}.metrics.json"            # written the first time a stats page used this replay
            if m.is_file():
                try:
                    mm = json.loads(m.read_text())
                    lined_up += bool(mm.get("ok"))
                    casts += bool(mm.get("casts"))
                    if mm.get("map"):
                        maps[mm["map"]] += 1
                except (OSError, ValueError):
                    pass
        return {"count": len(ids), "vrf": vrf, "data": data, "size": human(size), "bytes": size, "newest": newest,
                "week": week, "month": month, "lined_up": lined_up, "casts": casts, "maps": maps.most_common(8)}
    out = dict(_cached(f"replays:{data_dir}", 120, measure))
    def probe():
        from .. import replayfile
        return replayfile.check_vrfkit(replayfile.vrfkit_path(vrfkit))
    out["vrfkit_error"] = _cached(f"vrfkit:{vrfkit}", 600, probe)
    return out


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
        ext = app.extensions["nexus"]
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
        counts = {"users": store.user_count(), "online": store.online_count(), "teams": len(store.all_teams()),
                  "players": int(store._all("SELECT COUNT(*) AS n FROM profiles")[0]["n"])}
        return render_template(
            "overview.html", version=__version__, uptime_s=int(now - started_at), py=platform.python_version(),
            henrik=henrik_usage(now), model=model_usage(store.get("ollama_url"), now), model_name=store.get("ollama_model"),
            claude=claude_usage(store),
            backup=__import__("nexus.web.backup", fromlist=["last"]).last(store),
            disk=disk(store.data_dir), replays=replays(store.data_dir, store.get("vrfkit_path") or ""), active=sorted(active, key=lambda a: -a["age_s"]), failed=sorted(failed, key=lambda f: f["age_s"])[:10],
            done_day=done_day.most_common(), coach=coach, counts=counts,
            tick_age_s=int(now - sr.last_tick) if sr.last_tick else None, has_key=bool(store.get("henrik_api_key")))
