"""The window and the tray icon. The work itself is in sync.py; this file only shows settings and what happened.

Closing the window keeps the app in the tray (bottom right): it goes on syncing every few minutes. "Quit" in the
tray menu ends it."""
from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, config, kovaaks, sync
from .api import Api, ApiError

TITLE = "valcoach companion"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def set_autostart(on: bool) -> None:
    """Start with Windows (only for the installed .exe)."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "valcoach companion", 0, winreg.REG_SZ, f'"{sys.executable}" --tray')
        else:
            try:
                winreg.DeleteValue(k, "valcoach companion")
            except FileNotFoundError:
                pass


def guess_medal_dir() -> str:
    home = Path.home()
    for p in (home / "Videos" / "Medal", home / "Videos" / "Medal" / "Clips", Path("D:/Medal"), Path("D:/Videos/Medal")):
        if p.is_dir():
            return str(p)
    return ""


class App:
    def __init__(self, start_hidden: bool = False):
        self.s = config.load()
        if not self.s.medal_dir:
            self.s.medal_dir = guess_medal_dir()
        if not self.s.kovaaks_dir:
            game = kovaaks.find_game()
            self.s.kovaaks_dir = str(game) if game else ""
        self.api = Api(self.s.server, config.get_token(self.s.server)) if self.s.server else None
        self.msgs: queue.Queue[str] = queue.Queue()
        self.busy = threading.Lock()
        self.wake = threading.Event()
        self.ffmpeg = ffmpeg_path()
        self.last_sync = ""

        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.minsize(560, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._build()
        self.refresh()
        if start_hidden and self.logged_in():
            self.root.withdraw()
        self.root.after(300, self.pump)
        threading.Thread(target=self.loop, daemon=True).start()
        self.tray = self._tray()

    # ------------------------------------------------------------------ window
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        f = ttk.Frame(self.root, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="valcoach server").grid(row=0, column=0, sticky="w", **pad)
        self.v_server = tk.StringVar(value=self.s.server or "https://")
        ttk.Entry(f, textvariable=self.v_server).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        self.login_box = ttk.Frame(f)
        self.login_box.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.login_box.columnconfigure(1, weight=1)
        ttk.Label(self.login_box, text="Username").grid(row=0, column=0, sticky="w", **pad)
        self.v_user = tk.StringVar(value=self.s.user)
        ttk.Entry(self.login_box, textvariable=self.v_user).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Label(self.login_box, text="Password").grid(row=1, column=0, sticky="w", **pad)
        self.v_pw = tk.StringVar()
        ttk.Entry(self.login_box, textvariable=self.v_pw, show="•").grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(self.login_box, text="Log in", command=self.login).grid(row=1, column=2, **pad)

        self.who = ttk.Label(f, text="")
        self.who.grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        self.logout_btn = ttk.Button(f, text="Log out", command=self.logout)
        self.logout_btn.grid(row=2, column=2, sticky="e", **pad)

        ttk.Label(f, text="Player").grid(row=3, column=0, sticky="w", **pad)
        self.v_player = tk.StringVar()
        self.player_box = ttk.Combobox(f, textvariable=self.v_player, state="readonly")
        self.player_box.grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        self.player_box.bind("<<ComboboxSelected>>", lambda e: (self.save(), self.sync_now()))
        self.players: list[dict] = []

        ttk.Separator(f).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        self.v_put = tk.BooleanVar(value=self.s.put_playlists)
        self.v_scores = tk.BooleanVar(value=self.s.send_scores)
        self.v_upload = tk.BooleanVar(value=self.s.upload_matches)
        self.v_auto = tk.BooleanVar(value=self.s.autostart)
        ttk.Label(f, text="KovaaK's folder").grid(row=5, column=0, sticky="w", **pad)
        self.v_kov = tk.StringVar(value=self.s.kovaaks_dir)
        ttk.Entry(f, textvariable=self.v_kov).grid(row=5, column=1, sticky="ew", **pad)
        ttk.Button(f, text="…", width=3, command=lambda: self.pick(self.v_kov)).grid(row=5, column=2, **pad)
        ttk.Checkbutton(f, text="Put the coach's warm-up and training playlists into KovaaK's (once a day)",
                        variable=self.v_put, command=self.save).grid(row=6, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(f, text="Send new KovaaK's scores to valcoach", variable=self.v_scores,
                        command=self.save).grid(row=7, column=0, columnspan=3, sticky="w", **pad)

        ttk.Label(f, text="Medal folder").grid(row=8, column=0, sticky="w", **pad)
        self.v_medal = tk.StringVar(value=self.s.medal_dir)
        ttk.Entry(f, textvariable=self.v_medal).grid(row=8, column=1, sticky="ew", **pad)
        ttk.Button(f, text="…", width=3, command=lambda: self.pick(self.v_medal)).grid(row=8, column=2, **pad)
        ttk.Checkbutton(f, text="Cut my matches out of Medal recordings and upload them", variable=self.v_upload,
                        command=self.save).grid(row=9, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(f, text="Start with Windows (in the tray)", variable=self.v_auto,
                        command=self.save).grid(row=10, column=0, columnspan=3, sticky="w", **pad)

        bar = ttk.Frame(f)
        bar.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Button(bar, text="Sync now", command=self.sync_now).pack(side="left", padx=10)
        self.state = ttk.Label(bar, text="")
        self.state.pack(side="left")
        ttk.Label(bar, text=f"v{__version__}", foreground="#888").pack(side="right", padx=10)

        self.log = tk.Text(f, height=10, state="disabled", wrap="word")
        self.log.grid(row=12, column=0, columnspan=3, sticky="nsew", padx=10, pady=4)
        f.rowconfigure(12, weight=1)

    def pick(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if d:
            var.set(d)
            self.save()

    def logged_in(self) -> bool:
        return bool(self.api and self.api.token)

    def refresh(self) -> None:
        if self.logged_in():
            self.login_box.grid_remove()
            self.who.config(text=f"Logged in as {self.s.user}")
            self.logout_btn.grid()
            threading.Thread(target=self.load_players, daemon=True).start()
        else:
            self.login_box.grid()
            self.who.config(text="Log in with your valcoach account.")
            self.logout_btn.grid_remove()

    def load_players(self) -> None:
        try:
            me = self.api.me()
        except ApiError as e:
            self.msgs.put(f"valcoach: {e}")
            if e.status == 401:
                self.root.after(0, self.logout)
            return
        self.root.after(0, lambda: self.show_players(me.get("players", [])))

    def show_players(self, players: list[dict]) -> None:
        self.players = players
        self.player_box["values"] = [p["riot_id"] for p in players]
        mine = next((p for p in players if p["id"] == self.s.player_id), players[0] if players else None)
        before = self.s.player_id
        if mine:
            self.v_player.set(mine["riot_id"])
        self.save()
        if self.s.player_id and self.s.player_id != before:
            self.sync_now()                        # first login or another player: start right away

    def save(self) -> None:
        s = self.s
        s.server = self.v_server.get().strip().rstrip("/")
        s.kovaaks_dir, s.medal_dir = self.v_kov.get().strip(), self.v_medal.get().strip()
        s.put_playlists, s.send_scores, s.upload_matches = self.v_put.get(), self.v_scores.get(), self.v_upload.get()
        p = next((p for p in self.players if p["riot_id"] == self.v_player.get()), None)
        if p:
            s.player_id, s.player_name = p["id"], p["riot_id"]
        if s.autostart != self.v_auto.get():
            s.autostart = self.v_auto.get()
            try:
                set_autostart(s.autostart)
            except OSError as e:
                self.msgs.put(f"Start with Windows: {e}")
        config.save(s)

    def login(self) -> None:
        self.save()
        if not self.s.server.startswith(("https://", "http://")):
            messagebox.showerror(TITLE, "Enter the server address, e.g. https://coach.example.com")
            return
        api = Api(self.s.server)
        try:
            token = api.login(self.v_user.get().strip(), self.v_pw.get())
        except ApiError as e:
            messagebox.showerror(TITLE, str(e))
            return
        self.v_pw.set("")
        self.s.user = self.v_user.get().strip()
        config.set_token(self.s.server, token)
        self.api = api
        self.save()
        self.refresh()
        self.sync_now()

    def logout(self) -> None:
        if self.api:
            self.api.logout()
            config.set_token(self.s.server, "")
        self.api = None
        self.refresh()

    def say(self, text: str) -> None:
        self.msgs.put(f"{time.strftime('%H:%M')}  {text}")

    def pump(self) -> None:
        while not self.msgs.empty():
            line = self.msgs.get()
            self.log.config(state="normal")
            self.log.insert("end", line + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.state.config(text="working…" if self.busy.locked() else
                          (f"up to date (last check {self.last_sync})" if self.last_sync else ""))
        self.root.after(500, self.pump)

    def hide(self) -> None:
        self.root.withdraw()

    def show(self) -> None:
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(), self.root.focus_force()))

    # ------------------------------------------------------------------ work
    def sync_now(self) -> None:
        self.wake.set()

    def loop(self) -> None:
        while True:
            if self.logged_in() and self.s.player_id and not self.busy.locked():
                with self.busy:
                    ok = sync.run_once(self.s, self.api, self.ffmpeg, self.say)
                    config.save(self.s)
                self.last_sync = time.strftime("%H:%M")
                if not ok:
                    self.root.after(0, self.logout)
            self.wake.wait(max(1, self.s.every_min) * 60)
            self.wake.clear()

    # ------------------------------------------------------------------ tray
    def _tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return None
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.polygon([(32, 4), (60, 32), (32, 60), (4, 32)], fill=(94, 234, 212, 255))
        d.polygon([(32, 18), (46, 32), (32, 46), (18, 32)], fill=(15, 23, 42, 255))
        menu = pystray.Menu(pystray.MenuItem("Open", lambda: self.show(), default=True),
                            pystray.MenuItem("Sync now", lambda: self.sync_now()),
                            pystray.MenuItem("Quit", lambda: self.quit()))
        icon = pystray.Icon("valcoach", img, TITLE, menu)
        icon.run_detached()
        return icon

    def quit(self) -> None:
        if self.tray:
            self.tray.stop()
        self.root.after(0, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App(start_hidden="--tray" in sys.argv).run()
