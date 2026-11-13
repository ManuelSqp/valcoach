"""Practice › 3D maps (per player, the maps are the same for everyone): walk around a map rebuilt from the replays on
the server (stats/map3d.py). The page renders and moves in the browser (static/map3d.js)."""
from __future__ import annotations

import json
import threading

from flask import abort, jsonify, render_template

from ..maps import MapRegistry
from ..parse import parse_match
from ..stats import map3d as m3
from .aim import _read

_lock = threading.Lock()


def register(app, store, sr, view_profile, known_maps: list[str]) -> None:
    cache = store.data_dir / "cache"
    reg = MapRegistry(cache)
    out_dir = store.data_dir / "maps3d"
    replays_dir = store.data_dir / "replays"

    def map_of(mid: str) -> str | None:
        idx = _read(out_dir / "index.json", {})
        if mid in idx:
            return idx[mid]
        raw = None
        for name in (mid, mid.lower(), mid.upper()):
            f = cache / "matches" / f"{name}.json"
            if f.is_file():
                raw = _read(f, None)
                break
        if not raw:
            return None
        try:
            name = parse_match(raw).map_name
        except Exception:
            return None
        with _lock:
            idx = _read(out_dir / "index.json", {})
            idx[mid] = name
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.json").write_text(json.dumps(idx))
        return name

    def built(name: str, ids: list[str]) -> dict | None:
        """The rebuilt map, from the cache while the set of replays is the same."""
        f = out_dir / f"{name.lower()}.json"
        d = _read(f, {})
        if d.get("ids") == sorted(ids) and d.get("version") == m3.VERSION:
            return d
        mi = reg.get(name=name)
        if mi is None:
            return None
        d = m3.rebuild(mi, m3.load_replays(replays_dir, ids), name)
        d["ids"] = sorted(ids)
        with _lock:
            out_dir.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d, separators=(",", ":")))
        return d

    warmed: dict[str, list[str]] = {}

    def warm() -> None:
        """Every 5 minutes (the scheduler): rebuild a map whose replays changed, so the page doesn't wait for it
        (a few seconds per map with several full replays)."""
        for name, ids in m3.replays_by_map(replays_dir, map_of).items():
            if warmed.get(name) != sorted(ids):
                built(name, ids)
                warmed[name] = sorted(ids)
    app.extensions["nexus"].setdefault("ticks", []).append(warm)
    app.extensions["nexus"]["maps3d_warm"] = warm          # for tests

    @app.get("/profiles/<int:pid>/maps3d")
    def maps3d(pid: int):
        p, can_edit = view_profile(pid)
        by = m3.replays_by_map(replays_dir, map_of)
        maps = [{"name": m, "replays": len(by.get(m, []))} for m in sorted(set(known_maps) | set(by))]
        maps.sort(key=lambda x: (-x["replays"], x["name"]))
        setup = _read(sr.games(pid).path.parent / "trainer.json", {}).get("setup", {})
        boot = {"maps": maps, "api": "/api/maps3d/", "sens": setup.get("sens") or 0.4}
        return render_template("maps3d.html", p=p, active_pid=pid, maps=maps, boot=boot)

    @app.get("/api/maps3d/<name>")
    def maps3d_data(name: str):
        if not name.replace(" ", "").isalnum() or len(name) > 30:
            abort(404)
        by = m3.replays_by_map(replays_dir, map_of)
        real = next((m for m in by if m.lower() == name.lower()), None)
        if real is None:
            return jsonify(error="No replay of this map on the server yet."), 404
        d = built(real, by[real])
        if d is None or not d["cells"]:
            return jsonify(error="The map data isn't loaded yet (valorant-api.com)."), 404
        return jsonify(d)
