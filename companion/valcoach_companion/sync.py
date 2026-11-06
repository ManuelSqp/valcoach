"""One round of work: playlists into KovaaK's, new scores to valcoach, matches out of Medal recordings.
The app runs this every few minutes (and on "Sync now"); it only touches what changed since the last round."""
from __future__ import annotations

import tempfile
import time
from datetime import date
from pathlib import Path

from . import kovaaks, medal
from .api import Api, ApiError
from .config import Settings

WAIT_FOR_MATCH_DATA_S = 6 * 3600    # Riot's data can take a few minutes; after this a recording counts as done
STATS_BATCH = 50
KEEP_PLAYLISTS_DAYS = 30            # the coach's own older playlist files are removed after this


def playlists(s: Settings, api: Api, log) -> None:
    today = date.today().isoformat()
    if not (s.put_playlists and s.kovaaks_dir and s.player_id) or s.last_playlists == today:
        return
    folder = kovaaks.playlists_dir(Path(s.kovaaks_dir))
    files = api.playlists(s.player_id)
    written = kovaaks.write_playlists(folder, files)
    s.last_playlists = today
    if written:
        log(f"KovaaK's: new playlists {', '.join(written)}")
    # tidy up: only the coach's own files (valcoach_<kind>_DD-MM-YYYY.json), older than a month
    for f in folder.glob("valcoach_*_??-??-????.json"):
        try:
            if time.time() - f.stat().st_mtime > KEEP_PLAYLISTS_DAYS * 86400:
                f.unlink()
        except OSError:
            pass


def scores(s: Settings, api: Api, log) -> None:
    if not (s.send_scores and s.kovaaks_dir and s.player_id):
        return
    new = kovaaks.new_stats(kovaaks.stats_dir(Path(s.kovaaks_dir)), set(s.stats_sent), s.since)
    for i in range(0, len(new), STATS_BATCH):
        part = new[i:i + STATS_BATCH]
        r = api.send_stats(s.player_id, part)
        s.stats_sent += [f.name for f in part]
        if r.get("new"):
            log(f"KovaaK's: {r['new']} new score{'s' if r['new'] != 1 else ''} sent")


def recordings(s: Settings, api: Api, ffmpeg: str, log, now: float | None = None, workdir: Path | None = None) -> None:
    if not (s.upload_matches and s.medal_dir and s.player_id):
        return
    now = now or time.time()
    todo = [r for r in medal.find(Path(s.medal_dir), s.since, now)
            if s.recordings.get(r.name, {}).get("state") not in ("done", "skipped")]
    if not todo:
        return
    matches = api.matches(s.player_id)
    for rec in todo:
        state = s.recordings.setdefault(rec.name, {"state": "waiting", "matches": []})
        length = medal.duration(ffmpeg, rec.path)
        if length is None:
            state.update(state="skipped", why="the video can't be read")
            log(f"Medal: {rec.name}: the video can't be read, skipped")
            continue
        if not medal.clock_fits(rec, length):
            state.update(state="skipped", why="the start time and length don't fit (did Medal pause the recording?)")
            log(f"Medal: {rec.name}: start time and length don't fit, skipped (did Medal pause?)")
            continue
        found = [m for m in medal.matches_in(rec, matches)
                 if not m.get("has_clip") and m["match_id"] not in state["matches"]
                 and (m.get("coachable") or not s.only_coachable)]
        for m in found:
            with tempfile.TemporaryDirectory(dir=workdir) as tmp:
                out = Path(tmp) / f"{m['match_id']}.mp4"
                log(f"Medal: cutting {m['map']} ({m['score']}) out of {rec.name}")
                medal.cut(ffmpeg, rec.path, out, m["cut_from"], m["cut_length"])
                mb = out.stat().st_size / 1024 ** 2
                log(f"Medal: uploading {m['map']} ({mb:.0f} MB)")
                api.upload_clip(s.player_id, m["match_id"], out, rec.name)
            state["matches"].append(m["match_id"])
            log(f"Medal: {m['map']} {m['score']} is ready on its coach page")
        if now - rec.end > WAIT_FOR_MATCH_DATA_S:
            state["state"] = "done"


def run_once(s: Settings, api: Api, ffmpeg: str, log, workdir: Path | None = None) -> bool:
    """Everything once. -> False when the server says the device isn't logged in anymore."""
    for step in (lambda: playlists(s, api, log), lambda: scores(s, api, log),
                 lambda: recordings(s, api, ffmpeg, log, workdir=workdir)):
        try:
            step()
        except ApiError as e:
            if e.status == 401:
                log("Logged out by the server: log in again")
                return False
            log(f"valcoach: {e}")
        except (OSError, RuntimeError) as e:
            log(f"Error: {e}")
    return True
