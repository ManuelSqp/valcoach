"""The companion app's logic (companion/valcoach_companion): Medal names and cuts, KovaaK's folders, one sync."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from valcoach_companion import kovaaks, medal, sync  # noqa: E402
from valcoach_companion.config import Settings  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def test_medal_names_and_matches_in_a_session():
    t = medal.start_of("MedalTVValorant20260701203418498.mp4")
    assert t == datetime(2026, 7, 1, 20, 34, 18, 498000).timestamp()
    assert medal.start_of("MedalTVValorant20260329202412030-1774815019.mp4") is None      # a saved clip
    assert medal.start_of("MedalTVValorant20261399999999999.mp4") is None
    # a whole evening: 20 min in the menu, then two matches back to back
    rec = medal.Recording(Path("x.mp4"), start=1000.0, end=1000.0 + 3 * 3600, size=10 ** 9)
    ms = [{"match_id": "m1", "start": 1000.0 + 1200, "length_s": 2400},
          {"match_id": "m2", "start": 1000.0 + 1200 + 2400 + 300, "length_s": 2100},
          {"match_id": "before", "start": 500.0, "length_s": 2000},
          {"match_id": "after", "start": 1000.0 + 3 * 3600 - 600, "length_s": 2000}]
    got = medal.matches_in(rec, ms)
    assert [m["match_id"] for m in got] == ["m1", "m2"]
    assert got[0]["cut_from"] == 1200 - medal.PRE_ROLL_S and got[0]["cut_length"] == 2400 + medal.PRE_ROLL_S + medal.POST_ROLL_S
    assert got[1]["cut_from"] == 1200 + 2400 + 300 - medal.PRE_ROLL_S
    assert medal.clock_fits(rec, 3 * 3600 - 30) and not medal.clock_fits(rec, 2 * 3600)          # Medal paused


def test_kovaaks_playlists_and_stats(tmp_path):
    folder = tmp_path / "Playlists"
    folder.mkdir()
    files = [{"file_name": "valcoach_warmup_06-11-2026.json", "data": {"playlistName": "w"}},
             {"file_name": "../../evil.json", "data": {}}, {"file_name": "other.json", "data": {}}]
    assert kovaaks.write_playlists(folder, files) == ["valcoach_warmup_06-11-2026.json"]
    assert kovaaks.write_playlists(folder, files) == []                     # same content: left alone
    assert sorted(p.name for p in folder.iterdir()) == ["valcoach_warmup_06-11-2026.json"]
    stats = tmp_path / "stats"
    stats.mkdir()
    (stats / "a - Challenge - 2026.11.06-20.00.00 Stats.csv").write_text("x")
    (stats / "b - Challenge - 2026.11.06-20.05.00 Stats.csv").write_text("x")
    old = stats / "old - Challenge - 2025.01.01-20.00.00 Stats.csv"
    old.write_text("x")
    os.utime(old, (1, 1))
    assert [f.name[0] for f in kovaaks.new_stats(stats, {"a - Challenge - 2026.11.06-20.00.00 Stats.csv"}, 1000)] == ["b"]


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_one_sync_cuts_the_match_out_and_uploads_it(tmp_path, monkeypatch):
    medal_dir = tmp_path / "Medal"
    medal_dir.mkdir()
    start = datetime(2026, 11, 6, 20, 0, 0)
    src = medal_dir / f"MedalTVValorant{start.strftime('%Y%m%d%H%M%S')}000.mp4"
    subprocess.run([FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "300",
                    "-c:v", "libx264", "-g", "10", "-y", str(src)], check=True)
    s0 = start.timestamp()
    os.utime(src, (s0 + 300, s0 + 300))
    monkeypatch.setattr(medal, "MIN_SIZE", 0)
    uploaded = []

    class FakeApi:
        def matches(self, pid):
            return [{"match_id": "m-1", "start": s0 + 120, "length_s": 60, "map": "Ascent", "score": "13-5",
                     "coachable": True, "has_clip": False}]

        def upload_clip(self, pid, mid, path, source, progress=None):
            uploaded.append((mid, medal.duration(FFMPEG, path), source))
            return {"ok": True}
    s = Settings(player_id=1, medal_dir=str(medal_dir), since=s0 - 60)
    log = []
    sync.recordings(s, FakeApi(), FFMPEG, log.append, now=s0 + 10_000)
    assert uploaded and uploaded[0][0] == "m-1" and uploaded[0][2] == src.name
    assert 60 + medal.PRE_ROLL_S + medal.POST_ROLL_S - 2 <= uploaded[0][1] <= 300            # the match plus margins
    assert s.recordings[src.name]["matches"] == ["m-1"]
    sync.recordings(s, FakeApi(), FFMPEG, log.append, now=s0 + 30_000)                       # nothing twice
    assert len(uploaded) == 1 and s.recordings[src.name]["state"] == "done"
    json.dumps(s.recordings)


def test_updates_pick_the_newest_release_and_check_the_download(tmp_path):
    import hashlib
    from valcoach_companion import updater

    class R:
        def __init__(self, data=None, body=b"", code=200):
            self.status_code, self._d, self._b = code, data, body

        def json(self):
            return self._d

        def iter_content(self, n):
            yield self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    exe = b"MZ new app"
    good = "sha256:" + hashlib.sha256(exe).hexdigest()

    def rel(tag, digest=good, draft=False):
        return {"tag_name": tag, "draft": draft, "prerelease": False, "html_url": f"https://github.com/r/{tag}",
                "assets": [{"name": "valcoach-companion.exe", "size": len(exe), "digest": digest,
                            "browser_download_url": f"https://github.com/r/releases/download/{tag}/valcoach-companion.exe"}]}

    class S:
        def __init__(self, releases):
            self.releases = releases

        def get(self, url, **k):
            return R(self.releases) if "api.github.com" in url else R(body=exe)
    s = S([rel("v4.3.0"), rel("companion-v1.0.0"), rel("companion-v1.2.0"), rel("companion-v1.10.0", draft=True),
           rel("companion-v1.1.5")])
    info = updater.latest("1.1.0", session=s)
    assert info["version"] == "1.2.0" and info["sha256"] == good[7:]                 # 1.10 is a draft
    assert updater.latest("1.2.0", session=s) is None
    path = updater.download(info, tmp_path, session=s)
    assert path.read_bytes() == exe
    bad = dict(info, sha256="0" * 64)
    with pytest.raises(updater.UpdateError):
        updater.download(bad, tmp_path, session=s)
    assert not (tmp_path / "valcoach-companion.exe.download").exists()              # nothing half-written stays
    with pytest.raises(updater.UpdateError):
        updater.download(dict(info, url="https://evil.example/app.exe"), tmp_path, session=s)
