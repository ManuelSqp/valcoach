"""The window and the tray icon. The work itself is in sync.py; this file only shows settings and what happened.

Closing the window keeps the app in the tray (bottom right): it goes on syncing every few minutes. "Quit" in the
tray menu ends it."""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw

from . import __version__, config, kovaaks, sync, updater
from .api import Api, ApiError

TITLE = "valcoach companion"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UPDATE_EVERY_S = 24 * 3600

# valcoach's colours: deep navy, teal accent
BG = "#0d141c"
CARD = "#141e29"
LINE = "#223042"
FIELD = "#0f1822"
TEXT = "#e6edf3"
MUTED = "#8b9bab"
ACCENT = "#2dd4bf"
ACCENT_HOVER = "#14b8a6"
ACCENT_TEXT = "#04211d"
OK = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"


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


def logo(size: int = 64, bg: tuple | None = None) -> Image.Image:
    """valcoach's diamond, drawn (no image files to ship)."""
    img = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    d.polygon([(s / 2, s * .06), (s * .94, s / 2), (s / 2, s * .94), (s * .06, s / 2)], fill=(45, 212, 191, 255))
    d.polygon([(s / 2, s * .3), (s * .7, s / 2), (s / 2, s * .7), (s * .3, s / 2)], fill=(13, 20, 28, 255))
    return img


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color=CARD, corner_radius=14, border_width=1, border_color=LINE)
        self.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(head, text=subtitle, font=ctk.CTkFont(size=12), text_color=MUTED, justify="left",
                         wraplength=520).pack(anchor="w", pady=(2, 0))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 16))
        self.body.grid_columnconfigure(0, weight=1)


def entry(master, var, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(master, textvariable=var, height=36, corner_radius=8, fg_color=FIELD, border_color=LINE,
                        text_color=TEXT, **kw)


def switch(master, text: str, var, command) -> ctk.CTkSwitch:
    return ctk.CTkSwitch(master, text=text, variable=var, command=command, progress_color=ACCENT,
                         button_color=TEXT, button_hover_color="#ffffff", fg_color=LINE, text_color=TEXT,
                         font=ctk.CTkFont(size=13))


def ghost_button(master, text: str, command, width: int = 90) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width, height=34, corner_radius=8,
                         fg_color="transparent", border_width=1, border_color=LINE, hover_color=LINE, text_color=TEXT)


class App:
    def __init__(self, start_hidden: bool = False):
        updater.cleanup()
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
        self.update_info: dict | None = None
        self.players: list[dict] = []

        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk(fg_color=BG)
        self.root.title(TITLE)
        self.root.geometry("640x780")
        self.root.minsize(560, 560)
        self._icon = ctk.CTkImage(logo(64), size=(26, 26))
        try:
            from PIL import ImageTk
            self._win_icon = ImageTk.PhotoImage(logo(64))
            self.root.iconphoto(True, self._win_icon)
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._build()
        self.refresh()
        if start_hidden and self.logged_in():
            self.root.withdraw()
        self.root.after(300, self.pump)
        threading.Thread(target=self.loop, daemon=True).start()
        if self.s.check_updates and time.time() - self.s.last_update_check > UPDATE_EVERY_S:
            self.check_updates(quiet=True)
        self.tray = self._tray()

    # ------------------------------------------------------------------ window
    def _build(self) -> None:
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(2, weight=1)

        # header: logo, name, status
        head = ctk.CTkFrame(r, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 8))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="", image=self._icon).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(head, text="valcoach companion", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEXT).grid(row=0, column=1, sticky="w")
        self.sub = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=12), text_color=MUTED)
        self.sub.grid(row=1, column=1, sticky="w")
        self.pill = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=12, weight="bold"), corner_radius=999,
                                 fg_color=LINE, text_color=MUTED, padx=12, height=26)
        self.pill.grid(row=0, column=2, rowspan=2, sticky="e")

        # update banner (only when there is one)
        self.banner = ctk.CTkFrame(r, fg_color="#0f2e2a", corner_radius=12, border_width=1, border_color="#1f5c53")
        self.banner.grid_columnconfigure(0, weight=1)
        self.banner_text = ctk.CTkLabel(self.banner, text="", text_color=TEXT, font=ctk.CTkFont(size=13), anchor="w")
        self.banner_text.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        self.banner_btn = ctk.CTkButton(self.banner, text="Update now", command=self.update_now, width=110, height=32,
                                        corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT,
                                        font=ctk.CTkFont(size=13, weight="bold"))
        self.banner_btn.grid(row=0, column=1, padx=(0, 10), pady=8)
        self.banner_bar = ctk.CTkProgressBar(self.banner, progress_color=ACCENT, fg_color=LINE, height=6)

        body = ctk.CTkScrollableFrame(r, fg_color="transparent", scrollbar_button_color=LINE)
        body.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 6))
        body.grid_columnconfigure(0, weight=1)

        # account
        acc = Card(body, "Account")
        acc.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        b = acc.body
        self.v_server = ctk.StringVar(value=self.s.server or "https://")
        self.v_user = ctk.StringVar(value=self.s.user)
        self.v_pw = ctk.StringVar()
        self.login_box = ctk.CTkFrame(b, fg_color="transparent")
        self.login_box.grid_columnconfigure(0, weight=1)
        for i, (label, var, kw) in enumerate((("valcoach address", self.v_server, {}),
                                               ("Username", self.v_user, {}),
                                               ("Password", self.v_pw, {"show": "•"}))):
            ctk.CTkLabel(self.login_box, text=label, text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
                row=i * 2, column=0, sticky="w", pady=(6 if i else 0, 2))
            e = entry(self.login_box, var, **kw)
            e.grid(row=i * 2 + 1, column=0, sticky="ew")
            if label == "Password":
                e.bind("<Return>", lambda _e: self.login())
        ctk.CTkButton(self.login_box, text="Log in", command=self.login, height=38, corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT, font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=6, column=0, sticky="ew", pady=(12, 0))

        self.who_box = ctk.CTkFrame(b, fg_color="transparent")
        self.who_box.grid_columnconfigure(0, weight=1)
        self.who = ctk.CTkLabel(self.who_box, text="", text_color=TEXT, font=ctk.CTkFont(size=13), anchor="w")
        self.who.grid(row=0, column=0, sticky="ew")
        ghost_button(self.who_box, "Log out", self.logout).grid(row=0, column=1)
        ctk.CTkLabel(self.who_box, text="Player", text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
            row=1, column=0, sticky="w", pady=(10, 2))
        self.v_player = ctk.StringVar()
        self.player_menu = ctk.CTkOptionMenu(self.who_box, variable=self.v_player, values=["…"], height=36,
                                             corner_radius=8, fg_color=FIELD, button_color=LINE,
                                             button_hover_color="#2c3d52", dropdown_fg_color=CARD, text_color=TEXT,
                                             command=lambda _v: (self.save(), self.sync_now()))
        self.player_menu.grid(row=2, column=0, columnspan=2, sticky="ew")

        # KovaaK's
        self.v_put = ctk.BooleanVar(value=self.s.put_playlists)
        self.v_scores = ctk.BooleanVar(value=self.s.send_scores)
        self.v_upload = ctk.BooleanVar(value=self.s.upload_matches)
        self.v_auto = ctk.BooleanVar(value=self.s.autostart)
        self.v_updates = ctk.BooleanVar(value=self.s.check_updates)
        self.v_kov = ctk.StringVar(value=self.s.kovaaks_dir)
        self.v_medal = ctk.StringVar(value=self.s.medal_dir)
        kov = Card(body, "KovaaK's", "The coach's playlists land in KovaaK's › Playlists › Local Playlists, dated.")
        kov.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        self._folder_row(kov.body, "Game folder (with Saved and stats in it)", self.v_kov, 0)
        switch(kov.body, "Put the warm-up and training playlists into KovaaK's", self.v_put, self.save).grid(
            row=2, column=0, sticky="w", pady=(12, 4))
        switch(kov.body, "Send new scores to valcoach", self.v_scores, self.save).grid(row=3, column=0, sticky="w", pady=4)

        # Medal
        med = Card(body, "Medal", "Each match is cut out of your session recordings and uploaded: it's then ready on the "
                                  "match's coach page in valcoach.")
        med.grid(row=2, column=0, sticky="ew", padx=10, pady=8)
        self._folder_row(med.body, "Recordings folder", self.v_medal, 0)
        switch(med.body, "Cut my matches out and upload them", self.v_upload, self.save).grid(
            row=2, column=0, sticky="w", pady=(12, 4))

        # activity
        act = Card(body, "Activity")
        act.grid(row=3, column=0, sticky="ew", padx=10, pady=8)
        self.log = ctk.CTkTextbox(act.body, height=150, corner_radius=8, fg_color=FIELD, border_width=1,
                                  border_color=LINE, text_color=TEXT, font=ctk.CTkFont(family="Consolas", size=12),
                                  wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="ew")

        # app
        appc = Card(body, "App")
        appc.grid(row=4, column=0, sticky="ew", padx=10, pady=(8, 12))
        switch(appc.body, "Start with Windows (in the tray)", self.v_auto, self.save).grid(row=0, column=0, sticky="w", pady=4)
        switch(appc.body, "Look for updates once a day", self.v_updates, self.save).grid(row=1, column=0, sticky="w", pady=4)
        row = ctk.CTkFrame(appc.body, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(row, text=f"Version {__version__}", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="left")
        ghost_button(row, "Check for updates", lambda: self.check_updates(quiet=False), width=150).pack(side="right")

        # footer
        foot = ctk.CTkFrame(r, fg_color=CARD, corner_radius=0, border_width=0)
        foot.grid(row=3, column=0, sticky="ew")
        foot.grid_columnconfigure(0, weight=1)
        self.state = ctk.CTkLabel(foot, text="", text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w")
        self.state.grid(row=0, column=0, sticky="ew", padx=22, pady=12)
        ctk.CTkButton(foot, text="Sync now", command=self.sync_now, width=120, height=36, corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT, font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=1, padx=22, pady=10)

    def _folder_row(self, master, label: str, var, row: int) -> None:
        ctk.CTkLabel(master, text=label, text_color=MUTED, font=ctk.CTkFont(size=12)).grid(row=row, column=0, sticky="w",
                                                                                              pady=(0, 2))
        line = ctk.CTkFrame(master, fg_color="transparent")
        line.grid(row=row + 1, column=0, sticky="ew")
        line.grid_columnconfigure(0, weight=1)
        e = entry(line, var)
        e.grid(row=0, column=0, sticky="ew")
        e.bind("<FocusOut>", lambda _e: self.save())
        ghost_button(line, "Browse", lambda: self.pick(var)).grid(row=0, column=1, padx=(8, 0))

    def pick(self, var) -> None:
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if d:
            var.set(d)
            self.save()

    def logged_in(self) -> bool:
        return bool(self.api and self.api.token)

    def refresh(self) -> None:
        if self.logged_in():
            self.login_box.grid_remove()
            self.who_box.grid(row=0, column=0, sticky="ew")
            host = self.s.server.split("://", 1)[-1]
            self.who.configure(text=f"{self.s.user}  ·  {host}")
            self.sub.configure(text=f"Logged in as {self.s.user}")
            threading.Thread(target=self.load_players, daemon=True).start()
        else:
            self.who_box.grid_remove()
            self.login_box.grid(row=0, column=0, sticky="ew")
            self.sub.configure(text="Log in with your valcoach account")
        self.show_state()

    def load_players(self) -> None:
        try:
            me = self.api.me()
        except ApiError as e:
            self.say(f"valcoach: {e}")
            if e.status == 401:
                self.root.after(0, self.logout)
            return
        self.root.after(0, lambda: self.show_players(me.get("players", [])))

    def show_players(self, players: list[dict]) -> None:
        self.players = players
        names = [p["riot_id"] for p in players] or ["No player in your account yet"]
        self.player_menu.configure(values=names)
        mine = next((p for p in players if p["id"] == self.s.player_id), players[0] if players else None)
        before = self.s.player_id
        self.v_player.set(mine["riot_id"] if mine else names[0])
        self.save()
        if self.s.player_id and self.s.player_id != before:
            self.sync_now()                        # first login or another player: start right away

    def save(self) -> None:
        s = self.s
        server = self.v_server.get().strip().rstrip("/")
        if server and server not in ("https:", "http:"):
            s.server = server
        s.kovaaks_dir, s.medal_dir = self.v_kov.get().strip(), self.v_medal.get().strip()
        s.put_playlists, s.send_scores, s.upload_matches = self.v_put.get(), self.v_scores.get(), self.v_upload.get()
        s.check_updates = self.v_updates.get()
        p = next((p for p in self.players if p["riot_id"] == self.v_player.get()), None)
        if p:
            s.player_id, s.player_name = p["id"], p["riot_id"]
        if s.autostart != self.v_auto.get():
            s.autostart = self.v_auto.get()
            try:
                set_autostart(s.autostart)
            except OSError as e:
                self.say(f"Start with Windows: {e}")
        config.save(s)

    def login(self) -> None:
        self.save()
        if not self.s.server.startswith(("https://", "http://")):
            messagebox.showerror(TITLE, "Enter valcoach's address, e.g. https://coach.example.com")
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
        self.say("Logged in")
        self.sync_now()

    def logout(self) -> None:
        if self.api:
            self.api.logout()
            config.set_token(self.s.server, "")
        self.api = None
        self.refresh()

    def say(self, text: str) -> None:
        self.msgs.put(f"{time.strftime('%H:%M')}  {text}")

    def show_state(self) -> None:
        if not self.logged_in():
            pill, color, state = "Logged out", MUTED, "Log in to start."
        elif self.busy.locked():
            pill, color, state = "Working", WARN, "Working…"
        elif self.last_sync:
            pill, color, state = "Up to date", OK, f"Last check {self.last_sync} · every {self.s.every_min} min"
        else:
            pill, color, state = "Starting", MUTED, "Starting…"
        self.pill.configure(text=f"● {pill}", text_color=color)
        self.state.configure(text=state)

    def pump(self) -> None:
        while not self.msgs.empty():
            line = self.msgs.get()
            self.log.configure(state="normal")
            self.log.insert("end", line + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.show_state()
        self.root.after(500, self.pump)

    def hide(self) -> None:
        if self.tray is None:                     # no tray icon: closing the window ends the app
            self.quit()
            return
        self.root.withdraw()

    def show(self) -> None:
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(), self.root.focus_force()))

    # ------------------------------------------------------------------ updates
    def check_updates(self, quiet: bool) -> None:
        def work():
            try:
                info = updater.latest()
            except updater.UpdateError as e:
                if not quiet:
                    self.say(f"Updates: {e}")
                return
            self.s.last_update_check = time.time()
            config.save(self.s)
            self.root.after(0, lambda: self.show_update(info, quiet))
        threading.Thread(target=work, daemon=True).start()

    def show_update(self, info: dict | None, quiet: bool) -> None:
        self.update_info = info
        if info is None:
            self.banner.grid_remove()
            if not quiet:
                self.say(f"Updates: version {__version__} is the newest")
            return
        self.banner_text.configure(text=f"Version {info['version']} is available (you have {__version__}).")
        self.banner_btn.configure(state="normal", text="Update now" if updater.can_install() else "Open download")
        self.banner.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        if not quiet:
            self.show()
        elif getattr(self, "tray", None):
            try:
                self.tray.notify(f"Version {info['version']} is available. Open the app to update.", TITLE)
            except Exception:
                pass

    def update_now(self) -> None:
        info = self.update_info
        if not info:
            return
        if not updater.can_install():
            import webbrowser
            webbrowser.open(info["page"] or info["url"])
            return
        self.banner_btn.configure(state="disabled", text="Downloading…")
        self.banner_bar.set(0)
        self.banner_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))

        def progress(done, total):
            if total:
                self.root.after(0, lambda: self.banner_bar.set(done / total))

        def work():
            try:
                with self.busy:                   # never swap the app in the middle of an upload
                    new = updater.download(info, Path(sys.executable).parent, progress)
                    updater.install(new)
            except (updater.UpdateError, OSError) as e:
                self.say(f"Update: {e}")
                self.root.after(0, lambda: (self.banner_btn.configure(state="normal", text="Try again"),
                                            self.banner_bar.grid_remove()))
                return
            self.root.after(0, self.quit)
        threading.Thread(target=work, daemon=True).start()

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
            if self.s.check_updates and time.time() - self.s.last_update_check > UPDATE_EVERY_S:
                self.check_updates(quiet=True)
            self.wake.wait(max(1, self.s.every_min) * 60)
            self.wake.clear()

    # ------------------------------------------------------------------ tray
    def _tray(self):
        try:
            import pystray
        except Exception:
            return None
        menu = pystray.Menu(pystray.MenuItem("Open", lambda: self.show(), default=True),
                            pystray.MenuItem("Sync now", lambda: self.sync_now()),
                            pystray.MenuItem("Quit", lambda: self.quit()))
        icon = pystray.Icon("valcoach", logo(64), TITLE, menu)
        icon.run_detached()
        return icon

    def quit(self) -> None:
        if getattr(self, "tray", None):
            self.tray.stop()
        self.root.after(0, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App(start_hidden="--tray" in sys.argv).run()
