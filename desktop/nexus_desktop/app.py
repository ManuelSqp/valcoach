"""The Nexus app for Windows: the Nexus website in its own window (WebView2, through pywebview), a tray icon, and
the work only a PC can do (sync.py: KovaaK's playlists and scores, matches cut out of Medal recordings).

- First start: a small local page asks for the server's address. After that the window shows the server, and you
  log in there like in a browser (the login is kept between starts).
- Logged in, the website gives the app a key for this PC (POST /account/devices/pair, see base.html) and shows
  "This PC" in the menu: folders, switches, activity and updates of this app (this_pc.html), through the Bridge
  below. The Bridge answers only pages of the server the app is connected to.
- Closing the window keeps the app in the tray (bottom right): it goes on syncing every few minutes. "Quit" in the
  tray menu ends it.
"""
from __future__ import annotations

import html
import platform
import sys
import tempfile
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, config, demos, kovaaks, sync, updater
from .api import Api, ApiError

TITLE = "Nexus"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
OLD_RUN_VALUE = "valcoach companion"          # the autostart entry up to 4.4
UPDATE_EVERY_S = 24 * 3600
BG = "#0e131b"
SWITCHES = ("put_playlists", "send_scores", "upload_matches", "send_replays", "autostart", "check_updates")


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def set_autostart(on: bool) -> None:
    """Start with Windows, in the tray (only for the installed .exe). Removes the entry of the old companion app."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name in (OLD_RUN_VALUE, *(() if on else ("Nexus",))):
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        if on:
            winreg.SetValueEx(k, "Nexus", 0, winreg.REG_SZ, f'"{sys.executable}" --tray')


def guess_medal_dir() -> str:
    home = Path.home()
    for p in (home / "Videos" / "Medal", home / "Videos" / "Medal" / "Clips", Path("D:/Medal"), Path("D:/Videos/Medal")):
        if p.is_dir():
            return str(p)
    return ""


def logo(size: int = 64):
    """Nexus's diamond, drawn (no image files to ship)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    d.polygon([(s / 2, s * .06), (s * .94, s / 2), (s / 2, s * .94), (s * .06, s / 2)], fill=(45, 212, 191, 255))
    d.polygon([(s / 2, s * .3), (s * .7, s / 2), (s / 2, s * .7), (s * .3, s / 2)], fill=(13, 20, 28, 255))
    return img


def origin(url) -> str:
    """scheme://host[:port] in lower case, or "" for anything that isn't http(s). (WebView2 may hand over a .NET Uri
    instead of a string, hence str().)"""
    try:
        u = urlsplit(str(url) if url is not None else "")
        u.port                                   # a bad port raises ValueError here
    except ValueError:
        return ""
    if u.scheme not in ("http", "https") or not u.hostname:
        return ""
    port = f":{u.port}" if u.port and u.port != {"http": 80, "https": 443}[u.scheme] else ""
    return f"{u.scheme}://{u.hostname.lower()}{port}"


def clean_server(text: str) -> str:
    """What someone typed as the address -> https://host[:port][/path] without a trailing slash, or ""."""
    t = (text or "").strip()
    if t and "://" not in t:
        t = "https://" + t
    o = origin(t)
    if not o:
        return ""
    path = urlsplit(t).path.rstrip("/")
    return o + path


def safe_call(name: str) -> bool:
    """Which names a page may call through the bridge: our own flat method names and pywebview's internal ones.
    pywebview would also follow dotted names and names with underscores (e.g. "status.__func__.__globals__")."""
    return bool(name) and "." not in name and not name.startswith("_")


def harden_bridge() -> None:
    """Make pywebview drop calls that aren't one of the bridge's methods (see safe_call)."""
    if sys.platform != "win32":
        return
    try:
        from webview.platforms import edgechromium
    except Exception:
        return
    original = edgechromium.js_bridge_call
    if getattr(original, "_nexus_safe", False):
        return

    def checked(window, func_name, param, value_id):
        if not safe_call(str(func_name)):
            return None
        return original(window, func_name, param, value_id)
    checked._nexus_safe = True
    edgechromium.js_bridge_call = checked


SETUP_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Nexus</title><style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e131b;color:#e6edf3;font:15px/1.5 "Segoe UI",system-ui,sans-serif}
main{width:min(420px,calc(100vw - 32px))}
.mark{width:44px;height:44px;margin-bottom:18px}
h1{font-size:24px;margin:0 0 6px}
p{color:#8b9bab;margin:0 0 22px}
label{display:block;font-size:13px;color:#8b9bab;margin-bottom:6px}
input{box-sizing:border-box;width:100%;padding:11px 12px;border-radius:8px;border:1px solid #223042;background:#0f1822;color:#e6edf3;font:inherit}
input:focus{outline:2px solid #2dd4bf;outline-offset:1px;border-color:transparent}
button{margin-top:14px;width:100%;padding:11px;border:0;border-radius:8px;background:#2dd4bf;color:#04211d;font:600 15px "Segoe UI",system-ui,sans-serif;cursor:pointer}
button:focus-visible{outline:2px solid #e6edf3;outline-offset:2px}
#err{color:#f87171;font-size:13px;min-height:20px;margin-top:10px}
</style></head><body><main>
<svg class="mark" viewBox="0 0 100 100" aria-hidden="true"><path d="M50 6 94 50 50 94 6 50z" fill="#2dd4bf"/><path d="M50 30 70 50 50 70 30 50z" fill="#0d141c"/></svg>
<h1>Connect to Nexus</h1>
<p>The address you open Nexus with in the browser. You log in on the next page, like on the website.</p>
<form id="f"><label for="u">Nexus address</label>
<input id="u" value="__VALUE__" placeholder="https://coach.example.com" autocomplete="url" spellcheck="false" autofocus>
<button>Connect</button><div id="err" role="alert"></div></form>
<script>
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const err = document.getElementById('err'); err.textContent = 'Connecting…';
  try { const r = await window.pywebview.api.set_server(document.getElementById('u').value);
        if (r && r.error) err.textContent = r.error; }
  catch (x) { err.textContent = 'The app isn\\'t ready yet: try again in a second.'; }
});
</script></main></body></html>"""


class App:
    def __init__(self, start_hidden: bool = False):
        updater.cleanup()
        self.s = config.load()
        if not self.s.medal_dir:
            self.s.medal_dir = guess_medal_dir()
        if not self.s.demos_dir:
            self.s.demos_dir = demos.default_dir()
        if not self.s.kovaaks_dir:
            game = kovaaks.find_game()
            self.s.kovaaks_dir = str(game) if game else ""
        token = config.get_token(self.s.server) if self.s.server else ""
        self.api = Api(self.s.server, token) if token else None
        self.lines: deque[str] = deque(maxlen=200)
        self.busy = threading.Lock()
        self.wake = threading.Event()
        self.ffmpeg = ffmpeg_path()
        self.last_sync = ""
        self.update_info: dict | None = None
        self.update_progress: float | None = None
        self.update_error = ""
        self.start_hidden = start_hidden
        self.setup_mode = not self.s.server
        self.quitting = False
        self.fullscreen_on = False
        self.window = None
        self.tray = None
        try:
            set_autostart(self.s.autostart)            # also moves the old companion's autostart entry over
        except OSError:
            pass

    # ------------------------------------------------------------------ the page the window shows
    def on_server(self) -> bool:
        """Is the window showing a page of the connected server? Only those may use the bridge."""
        if not self.window or not self.s.server or self.setup_mode:
            return False
        try:
            return origin(self.window.get_current_url()) == origin(self.s.server)
        except Exception:
            return False

    def on_setup(self) -> bool:
        """Is the window showing the local "Connect to Nexus" page?"""
        if not self.window or not self.setup_mode:
            return False
        try:
            return not origin(self.window.get_current_url())
        except Exception:
            return False

    def show_setup(self) -> None:
        self.setup_mode = True
        self.window.load_html(SETUP_PAGE.replace("__VALUE__", html.escape(self.s.server or "", quote=True)))

    def connect(self, server: str) -> None:
        """Another server: forget this PC's key for the old one and open the new one."""
        if server != self.s.server:
            self.unpair()
            self.s.server, self.s.user, self.s.player_id, self.s.player_name = server, "", 0, ""
            config.save(self.s)
        self.setup_mode = False
        self.window.load_url(server)

    def on_loaded(self) -> None:
        """Links to other websites open in the browser; the window stays on Nexus."""
        if self.setup_mode or not self.window:
            return
        try:
            url = str(self.window.get_current_url() or "")
        except Exception:
            return
        here = origin(url)
        if here and here != origin(self.s.server):
            webbrowser.open(url)
            self.window.load_url(self.s.server)

    def on_closing(self):
        if self.quitting or self.tray is None:     # no tray icon: closing the window ends the app
            self.quitting = True
            return True
        threading.Thread(target=self.window.hide, daemon=True).start()
        return False

    # ------------------------------------------------------------------ device key
    def pair(self, token: str, user: str) -> None:
        if not (isinstance(token, str) and token.startswith("vc_") and len(token) <= 100):
            raise ValueError("That isn't a device key.")
        if self.api and self.api.token and self.api.token != token:
            self.api.logout()                          # the key of the account before
        self.api = Api(self.s.server, token)
        config.set_token(self.s.server, token)
        self.s.user = str(user or "")[:100]
        config.save(self.s)
        self.say(f"Connected to {self.s.user}'s account")
        self.load_players()
        self.sync_now()

    def unpair(self) -> None:
        if self.api:
            self.api.logout()
            config.set_token(self.s.server, "")
        self.api = None
        self.s.user = ""
        config.save(self.s)

    def load_players(self) -> None:
        """No player picked yet (or it's gone): the account's first one."""
        try:
            players = self.api.me().get("players", []) if self.api else []
        except ApiError as e:
            self.say(f"Nexus: {e}")
            return
        ids = {p["id"] for p in players}
        if players and self.s.player_id not in ids:
            self.s.player_id, self.s.player_name = players[0]["id"], players[0]["riot_id"]
            config.save(self.s)

    # ------------------------------------------------------------------ state for "This PC"
    def logged_in(self) -> bool:
        return bool(self.api and self.api.token)

    def say(self, text: str) -> None:
        self.lines.append(f"{time.strftime('%H:%M')}  {text}")

    def status(self) -> dict:
        s = self.s

        def folder_ok(path: str, *parts: str) -> bool:
            return bool(path) and Path(path, *parts).is_dir()
        info = self.update_info
        return {
            "version": __version__, "device": platform.node() or "This PC", "server": s.server,
            "paired_user": s.user if self.logged_in() else "", "player_id": s.player_id,
            "kovaaks_dir": s.kovaaks_dir, "medal_dir": s.medal_dir, "demos_dir": s.demos_dir,
            "kovaaks_ok": folder_ok(s.kovaaks_dir, "Saved"), "medal_ok": folder_ok(s.medal_dir),
            "demos_ok": folder_ok(s.demos_dir),
            "replays_sent": sum(1 for x in s.replays.values() if x.get("state") == "done"),
            **{k: bool(getattr(s, k)) for k in SWITCHES},
            "every_min": s.every_min, "last_playlists": s.last_playlists, "scores_sent": len(s.stats_sent),
            "matches_uploaded": sum(len(x.get("matches", [])) for x in s.recordings.values()),
            "busy": self.busy.locked(), "last_sync": self.last_sync, "log": list(self.lines),
            "update": {"version": info["version"], "can_install": updater.can_install()} if info else None,
            "update_progress": self.update_progress, "update_error": self.update_error,
        }

    def change(self, key: str, value) -> dict:
        s = self.s
        if key in SWITCHES:
            on = bool(value)
            setattr(s, key, on)
            if key == "autostart":
                try:
                    set_autostart(on)
                except OSError as e:
                    self.say(f"Start with Windows: {e}")
        elif key == "player_id":
            if type(value) is not int or value <= 0:
                return {"error": "That isn't a player."}
            s.player_id = value
        else:
            return {"error": "That can't be changed here."}
        config.save(s)
        if key in ("player_id", "put_playlists", "send_scores", "upload_matches", "send_replays") and value:
            self.sync_now()
        return {"ok": True}

    def pick_folder(self, which: str) -> dict:
        import webview
        attr = {"kovaaks": "kovaaks_dir", "medal": "medal_dir", "demos": "demos_dir"}.get(which)
        if not attr:
            return {"error": "Unknown folder."}
        start = getattr(self.s, attr) or str(Path.home())
        picked = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        if picked:
            setattr(self.s, attr, str(picked[0] if isinstance(picked, (list, tuple)) else picked))
            config.save(self.s)
            self.sync_now()
        return {"ok": True}

    # ------------------------------------------------------------------ updates
    def check_updates(self, quiet: bool) -> None:
        try:
            info = updater.latest()
        except updater.UpdateError as e:
            if not quiet:
                self.say(f"Updates: {e}")
            return
        self.s.last_update_check = time.time()
        config.save(self.s)
        self.update_info, self.update_error = info, ""
        if info is None:
            if not quiet:
                self.say(f"Updates: version {__version__} is the newest")
        elif quiet and self.tray:
            try:
                self.tray.notify(f"Version {info['version']} is available. Open This PC in the app to update.", TITLE)
            except Exception:
                pass

    def update_now(self) -> None:
        info = self.update_info
        if not info or self.update_progress is not None:
            return
        if not updater.can_install():
            webbrowser.open(info["page"] or info["url"])
            return
        self.update_progress, self.update_error = 0.0, ""

        def progress(done, total):
            if total:
                self.update_progress = done / total

        def work():
            try:
                with self.busy:                       # never update in the middle of an upload
                    setup = updater.download(info, Path(tempfile.gettempdir()), progress)
                    updater.install(setup)
            except (updater.UpdateError, OSError) as e:
                self.update_progress, self.update_error = None, f"Update: {e}"
                self.say(self.update_error)
                return
            self.quit()
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ work
    def sync_now(self) -> None:
        self.wake.set()

    def loop(self) -> None:
        while not self.quitting:
            if self.logged_in() and self.s.player_id and not self.busy.locked():
                with self.busy:
                    ok = sync.run_once(self.s, self.api, self.ffmpeg, self.say)
                    config.save(self.s)
                self.last_sync = time.strftime("%H:%M")
                if not ok:                            # the key was removed (Account) or the password changed
                    self.say("This PC was logged out: open Nexus in the app and log in again")
                    self.api = None
                    config.set_token(self.s.server, "")
                    self.s.user = ""
                    config.save(self.s)
            elif self.logged_in() and not self.s.player_id:
                self.load_players()
            if self.s.check_updates and time.time() - self.s.last_update_check > UPDATE_EVERY_S:
                self.check_updates(quiet=True)
            self.wake.wait(max(1, self.s.every_min) * 60)
            self.wake.clear()

    # ------------------------------------------------------------------ tray and window
    def show(self) -> None:
        if self.window:
            self.window.show()
            self.window.restore()

    def _tray(self):
        try:
            import pystray
        except Exception:
            return None
        menu = pystray.Menu(pystray.MenuItem("Open", lambda: self.show(), default=True),
                            pystray.MenuItem("Sync now", lambda: self.sync_now()),
                            pystray.MenuItem("Change server…", lambda: (self.show_setup(), self.show())),
                            pystray.MenuItem("Quit", lambda: self.quit()))
        icon = pystray.Icon("Nexus", logo(64), TITLE, menu)
        icon.run_detached()
        return icon

    def quit(self) -> None:
        self.quitting = True
        self.wake.set()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        if self.window:
            self.window.destroy()

    def run(self) -> None:
        import webview
        harden_bridge()
        webview.settings["ALLOW_DOWNLOADS"] = True           # exports, playlists and clips from the website
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        hidden = self.start_hidden and not self.setup_mode
        self.window = webview.create_window(
            TITLE, url=None if self.setup_mode else self.s.server,
            html=SETUP_PAGE.replace("__VALUE__", "") if self.setup_mode else None, js_api=Bridge(self),
            width=1280, height=820, min_size=(900, 600), background_color=BG, hidden=hidden, text_select=True)
        self.window.events.closing += self.on_closing
        self.window.events.loaded += self.on_loaded
        self.tray = self._tray()
        threading.Thread(target=self.loop, daemon=True).start()
        storage = config.folder() / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        webview.start(private_mode=False, storage_path=str(storage))
        self.quit()


class Bridge:
    """What the pages of the connected server can ask the app (window.pywebview.api.*). Every method checks that the
    calling page belongs to that server (the app keeps nothing else as an attribute here, see safe_call)."""

    def __init__(self, app: App):
        self.__app = app                        # name-mangled and private: pywebview doesn't offer it to pages

    def _ok(self) -> App:
        a = self.__app
        if not a.on_server():
            raise PermissionError("Only Nexus's own pages can use the app.")
        return a

    def status(self) -> dict:
        return self._ok().status()

    def set(self, key: str, value) -> dict:
        return self._ok().change(str(key), value)

    def pick_folder(self, which: str) -> dict:
        return self._ok().pick_folder(str(which))

    def sync_now(self) -> dict:
        self._ok().sync_now()
        return {"ok": True}

    def paired(self, token: str, user: str) -> dict:
        self._ok().pair(token, user)
        return {"ok": True}

    def check_updates(self) -> dict:
        self._ok().check_updates(quiet=False)
        return {"ok": True}

    def update_now(self) -> dict:
        self._ok().update_now()
        return {"ok": True}

    def fullscreen(self, on) -> dict:
        """The aim trainer playing fullscreen: the whole window (the page alone can't in WebView2)."""
        a = self._ok()
        on = bool(on)
        if a.fullscreen_on != on:
            a.window.toggle_fullscreen()
            a.fullscreen_on = on
        return {"ok": True}

    def change_server(self) -> dict:
        a = self._ok()
        a.show_setup()
        return {"ok": True}

    def set_server(self, text: str) -> dict:
        """Only from the local "Connect to Nexus" page."""
        a = self.__app
        if not a.on_setup():
            raise PermissionError("Only the app's own setup page can change the server.")
        server = clean_server(str(text or ""))
        if not server:
            return {"error": "Enter the address like https://coach.example.com"}
        try:
            Api(server).me()
        except ApiError as e:
            if e.status != 401:                       # 401: it's Nexus, just not logged in yet
                return {"error": f"{server}: {e}"}
        a.connect(server)
        return {"ok": True}


def main() -> None:
    App(start_hidden="--tray" in sys.argv).run()
