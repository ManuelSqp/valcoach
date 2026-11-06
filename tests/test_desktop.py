"""The Nexus app for Windows (desktop/nexus_desktop): Medal names and cuts, KovaaK's folders, one sync, updates, the
bridge between the website and the app."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from nexus_desktop import kovaaks, medal, sync  # noqa: E402
from nexus_desktop.config import Settings  # noqa: E402

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
    files = [{"file_name": "nexus_warmup_06-11-2026.json", "data": {"playlistName": "w"}},
             {"file_name": "../../evil.json", "data": {}}, {"file_name": "other.json", "data": {}}]
    assert kovaaks.write_playlists(folder, files) == ["nexus_warmup_06-11-2026.json"]
    assert kovaaks.write_playlists(folder, files) == []                     # same content: left alone
    assert sorted(p.name for p in folder.iterdir()) == ["nexus_warmup_06-11-2026.json"]
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


def test_the_app_has_the_server_s_version():
    import nexus
    import nexus_desktop
    assert nexus_desktop.__version__ == nexus.__version__


def test_updates_pick_the_newest_release_and_check_the_download(tmp_path):
    import hashlib
    from nexus_desktop import updater

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
    setup = b"MZ installer"
    good = "sha256:" + hashlib.sha256(setup).hexdigest()

    def rel(tag, digest=good, draft=False, asset="nexus-setup.exe"):
        return {"tag_name": tag, "draft": draft, "prerelease": False, "html_url": f"https://github.com/r/{tag}",
                "assets": [{"name": asset, "size": len(setup), "digest": digest,
                            "browser_download_url": f"https://github.com/r/releases/download/{tag}/{asset}"}]}

    class S:
        def __init__(self, releases):
            self.releases = releases

        def get(self, url, **k):
            return R(self.releases) if url.startswith("https://api.github.com/") else R(body=setup)
    s = S([rel("v4.3.0", asset="something-else.zip"), rel("companion-v9.0.0"), rel("v4.4.0"), rel("v4.10.0", draft=True),
           rel("v4.3.5")])
    info = updater.latest("4.3.1", session=s)
    assert info["version"] == "4.4.0" and info["sha256"] == good[7:]       # 4.10 is a draft, 9.0.0 the old naming
    assert updater.latest("4.4.0", session=s) is None
    path = updater.download(info, tmp_path, session=s)
    assert path.name == "nexus-setup-4.4.0.exe" and path.read_bytes() == setup
    with pytest.raises(updater.UpdateError):
        updater.download(dict(info, sha256="0" * 64), tmp_path, session=s)
    assert not list(tmp_path.glob("*.download"))                            # nothing half-written stays
    with pytest.raises(updater.UpdateError):
        updater.download(dict(info, url="https://evil.example/setup.exe"), tmp_path, session=s)


def test_playlists_of_the_old_name_are_still_tidied(tmp_path):
    folder = tmp_path / "Playlists"
    folder.mkdir()
    files = [{"file_name": "valcoach_training_05-11-2026.json", "data": {"playlistName": "t"}},
             {"file_name": "../evil.json", "data": {}}]
    assert kovaaks.write_playlists(folder, files) == ["valcoach_training_05-11-2026.json"]


def test_addresses_origins_and_bridge_names():
    from nexus_desktop.app import clean_server, origin, safe_call
    assert clean_server("coach.example.com/") == "https://coach.example.com"
    assert clean_server(" http://10.0.0.5:10070 ") == "http://10.0.0.5:10070"
    assert clean_server("https://Coach.Example.com:443/nexus/") == "https://coach.example.com/nexus"
    assert clean_server("javascript:alert(1)") == "" and clean_server("") == "" and clean_server("https://x:99999") == ""
    assert origin("https://coach.example.com/account?x=1") == "https://coach.example.com"
    assert origin("https://coach.example.com.evil.net/") != origin("https://coach.example.com/")
    assert origin("about:blank") == "" and origin(None) == "" and origin("data:text/html,hi") == ""
    assert safe_call("status") and safe_call("pywebviewAsyncCallback")
    assert not safe_call("status.__func__.__globals__") and not safe_call("_Bridge__app") and not safe_call("__class__")


class FakeWindow:
    def __init__(self, url):
        self.url, self.loaded, self.html = url, [], None

    def get_current_url(self):
        return self.url

    def load_url(self, url):
        self.loaded.append(url)
        self.url = url

    def load_html(self, html):
        self.html, self.url = html, None


def make_app(tmp_path, monkeypatch, server="https://coach.example.com"):
    from nexus_desktop import app as appmod, config
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(appmod.kovaaks, "find_game", lambda: None)
    tokens = {}
    monkeypatch.setattr(config, "get_token", lambda server: tokens.get(server, ""))
    monkeypatch.setattr(config, "set_token", lambda server, token: tokens.__setitem__(server, token))
    s = config.Settings(server=server)
    config.save(s)
    a = appmod.App()
    a.window = FakeWindow(server + "/this-pc")
    return a, appmod.Bridge(a), tokens


def test_the_bridge_answers_only_the_connected_server(tmp_path, monkeypatch):
    a, b, tokens = make_app(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(a, "load_players", lambda: calls.append("players"))
    st = b.status()
    assert st["server"] == "https://coach.example.com" and st["paired_user"] == "" and st["update"] is None
    assert b.set("send_scores", False) == {"ok": True} and a.s.send_scores is False
    assert "error" in b.set("server", "https://evil.example") and a.s.server == "https://coach.example.com"
    assert "error" in b.set("player_id", "1; drop") and b.set("player_id", 7) == {"ok": True} and a.s.player_id == 7
    with pytest.raises(ValueError):
        b.paired("not-a-key", "manuel")
    b.paired("vc_abc", "manuel")
    assert tokens["https://coach.example.com"] == "vc_abc" and b.status()["paired_user"] == "manuel" and calls
    # another website in the window (a link that wasn't caught): no answers, and no server change
    a.window.url = "https://evil.example/page"
    for call in (b.status, b.sync_now, b.check_updates, lambda: b.set("autostart", True), lambda: b.paired("vc_x", "x")):
        with pytest.raises(PermissionError):
            call()
    with pytest.raises(PermissionError):
        b.set_server("https://evil.example")
    # the guard sends it to the browser and goes back to Nexus
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    a.on_loaded()
    assert opened == ["https://evil.example/page"] and a.window.loaded[-1] == "https://coach.example.com"


def test_the_setup_page_sets_the_server(tmp_path, monkeypatch):
    from nexus_desktop import app as appmod
    from nexus_desktop.api import ApiError
    a, b, tokens = make_app(tmp_path, monkeypatch, server="")
    assert a.setup_mode
    a.window = FakeWindow(None)                                      # the local page has no http(s) address
    with pytest.raises(PermissionError):
        b.status()                                                   # nothing but set_server works there

    def me(self):
        if "nexus" not in self.server:
            raise ApiError("The server didn't answer like Nexus (check the address)")
        raise ApiError("Not logged in", 401)
    monkeypatch.setattr(appmod.Api, "me", me)
    assert "error" in b.set_server("example.org")
    assert "error" in b.set_server("ftp://nexus.example")
    assert b.set_server("nexus.example.com/") == {"ok": True}
    assert a.s.server == "https://nexus.example.com" and not a.setup_mode and a.window.loaded == ["https://nexus.example.com"]
    with pytest.raises(PermissionError):
        b.set_server("https://elsewhere.example")                   # not from the setup page anymore


def test_settings_of_the_companion_app_are_taken_over(tmp_path, monkeypatch):
    from nexus_desktop import config
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = tmp_path / "valcoach-companion"
    old.mkdir()
    (old / "config.json").write_text(json.dumps({"server": "https://coach.example.com", "player_id": 3}))
    s = config.load()
    assert s.server == "https://coach.example.com" and s.player_id == 3 and (tmp_path / "Nexus" / "config.json").exists()
