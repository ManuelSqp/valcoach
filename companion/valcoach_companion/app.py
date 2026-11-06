"""The window and the tray icon. The work itself is in sync.py; this file only shows settings and what happened.
Logged out: one login card. Logged in: a sidebar (Overview, KovaaK's, Medal, Settings) and one page at a time.

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
        self.root.geometry("900x600")
        self.root.minsize(780, 520)
        self._icon = ctk.CTkImage(logo(64), size=(30, 30))
        self._icon_big = ctk.CTkImage(logo(128), size=(56, 56))
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
        r.grid_columnconfigure(1, weight=1)
        r.grid_rowconfigure(0, weight=1)
        self.v_server = ctk.StringVar(value=self.s.server or "https://")
        self.v_user = ctk.StringVar(value=self.s.user)
        self.v_pw = ctk.StringVar()
        self.v_player = ctk.StringVar()
        self.v_put = ctk.BooleanVar(value=self.s.put_playlists)
        self.v_scores = ctk.BooleanVar(value=self.s.send_scores)
        self.v_upload = ctk.BooleanVar(value=self.s.upload_matches)
        self.v_auto = ctk.BooleanVar(value=self.s.autostart)
        self.v_updates = ctk.BooleanVar(value=self.s.check_updates)
        self.v_kov = ctk.StringVar(value=self.s.kovaaks_dir)
        self.v_medal = ctk.StringVar(value=self.s.medal_dir)

        # ---- logged out: one centred card
        self.login_page = ctk.CTkFrame(r, fg_color="transparent")
        self.login_page.grid_columnconfigure(0, weight=1)
        self.login_page.grid_rowconfigure((0, 2), weight=1)
        card = Card(self.login_page, "Log in", "With your valcoach account. The app gets its own key for this PC; "
                                               "your password isn't stored.")
        card.grid(row=1, column=0, padx=40)
        card.configure(width=420)
        top = ctk.CTkFrame(self.login_page, fg_color="transparent")
        top.grid(row=0, column=0, sticky="s", pady=(0, 18))
        ctk.CTkLabel(top, text="", image=self._icon_big).pack()
        ctk.CTkLabel(top, text="valcoach companion", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(pady=(8, 0))
        b = card.body
        for i, (label, var, kw) in enumerate((("valcoach address", self.v_server, {}),
                                               ("Username", self.v_user, {}),
                                               ("Password", self.v_pw, {"show": "•"}))):
            ctk.CTkLabel(b, text=label, text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
                row=i * 2, column=0, sticky="w", pady=(8 if i else 0, 2))
            e = entry(b, var, width=360, **kw)
            e.grid(row=i * 2 + 1, column=0, sticky="ew")
            if label == "Password":
                e.bind("<Return>", lambda _e: self.login())
        ctk.CTkButton(b, text="Log in", command=self.login, height=40, corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT, font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=6, column=0, sticky="ew", pady=(16, 0))

        # ---- logged in: sidebar + one page at a time
        self.side = ctk.CTkFrame(r, fg_color=CARD, corner_radius=0, width=210)
        self.side.grid_propagate(False)
        self.side.grid_columnconfigure(0, weight=1)
        self.side.grid_rowconfigure(6, weight=1)
        brand = ctk.CTkFrame(self.side, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 18))
        ctk.CTkLabel(brand, text="", image=self._icon).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(names, text="valcoach", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
                     height=18).pack(anchor="w")
        ctk.CTkLabel(names, text="companion", font=ctk.CTkFont(size=12), text_color=MUTED, height=14).pack(anchor="w")
        self.nav: dict[str, ctk.CTkButton] = {}
        for i, (key, label) in enumerate((("overview", "Overview"), ("kovaaks", "KovaaK's"), ("medal", "Medal"),
                                          ("settings", "Settings")), start=1):
            btn = ctk.CTkButton(self.side, text=label, anchor="w", height=38, corner_radius=8, fg_color="transparent",
                                hover_color=LINE, text_color=MUTED, font=ctk.CTkFont(size=14),
                                command=lambda k=key: self.page(k))
            btn.grid(row=i, column=0, sticky="ew", padx=10, pady=2)
            self.nav[key] = btn
        bottom = ctk.CTkFrame(self.side, fg_color="transparent")
        bottom.grid(row=7, column=0, sticky="ew", padx=14, pady=16)
        bottom.grid_columnconfigure(0, weight=1)
        self.pill = ctk.CTkLabel(bottom, text="", font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
        self.pill.grid(row=0, column=0, sticky="ew")
        self.state = ctk.CTkLabel(bottom, text="", text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w",
                                  justify="left", wraplength=180)
        self.state.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkButton(bottom, text="Sync now", command=self.sync_now, height=36, corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT, font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=2, column=0, sticky="ew")

        self.main = ctk.CTkFrame(r, fg_color="transparent")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)
        # update banner (only when there is one)
        self.banner = ctk.CTkFrame(self.main, fg_color="#0f2e2a", corner_radius=12, border_width=1, border_color="#1f5c53")
        self.banner.grid_columnconfigure(0, weight=1)
        self.banner_text = ctk.CTkLabel(self.banner, text="", text_color=TEXT, font=ctk.CTkFont(size=13), anchor="w")
        self.banner_text.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        self.banner_btn = ctk.CTkButton(self.banner, text="Update now", command=self.update_now, width=110, height=32,
                                        corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT,
                                        font=ctk.CTkFont(size=13, weight="bold"))
        self.banner_btn.grid(row=0, column=1, padx=(0, 10), pady=8)
        self.banner_bar = ctk.CTkProgressBar(self.banner, progress_color=ACCENT, fg_color=LINE, height=6)

        self.pages: dict[str, ctk.CTkFrame] = {}
        for key in self.nav:
            f = ctk.CTkFrame(self.main, fg_color="transparent")
            f.grid_columnconfigure(0, weight=1)
            self.pages[key] = f

        # overview: player, what's on, activity
        p = self.pages["overview"]
        p.grid_rowconfigure(3, weight=1)
        self._title(p, "Overview")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text="Player", text_color=MUTED, font=ctk.CTkFont(size=13)).grid(row=0, column=0, padx=(0, 10))
        self.player_menu = ctk.CTkOptionMenu(row, variable=self.v_player, values=["…"], height=34, corner_radius=8,
                                             fg_color=FIELD, button_color=LINE, button_hover_color="#2c3d52",
                                             dropdown_fg_color=CARD, text_color=TEXT,
                                             command=lambda _v: (self.save(), self.sync_now()))
        self.player_menu.grid(row=0, column=1, sticky="w")
        tiles = ctk.CTkFrame(p, fg_color="transparent")
        tiles.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        tiles.grid_columnconfigure((0, 1, 2), weight=1, uniform="t")
        self.tiles = {}
        for i, (key, title, page) in enumerate((("playlists", "Playlists", "kovaaks"), ("scores", "Scores", "kovaaks"),
                                                ("medal", "Medal", "medal"))):
            t = ctk.CTkFrame(tiles, fg_color=CARD, corner_radius=12, border_width=1, border_color=LINE, cursor="hand2")
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            head = ctk.CTkLabel(t, text=title, text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w")
            head.pack(fill="x", padx=14, pady=(12, 0))
            val = ctk.CTkLabel(t, text="", text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
            val.pack(fill="x", padx=14)
            sub = ctk.CTkLabel(t, text="", text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w", justify="left",
                               wraplength=170)
            sub.pack(fill="x", padx=14, pady=(0, 12))
            for w in (t, head, val, sub):
                w.bind("<Button-1>", lambda _e, k=page: self.page(k))
            self.tiles[key] = (val, sub)
        act = ctk.CTkFrame(p, fg_color=CARD, corner_radius=12, border_width=1, border_color=LINE)
        act.grid(row=3, column=0, sticky="nsew")
        act.grid_columnconfigure(0, weight=1)
        act.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(act, text="Activity", text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        self.log = ctk.CTkTextbox(act, corner_radius=8, fg_color=FIELD, border_width=0, text_color=TEXT,
                                  font=ctk.CTkFont(family="Consolas", size=12), wrap="word", state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # KovaaK's
        p = self.pages["kovaaks"]
        self._title(p, "KovaaK's", "The coach's warm-up and training playlists land in KovaaK's › Playlists › Local "
                                   "Playlists, dated. Your scores go to the Aim page.")
        c = Card(p, "Game folder", "The one with Saved and stats in it (found in your Steam libraries).")
        c.grid(row=2, column=0, sticky="ew")
        self._folder_row(c.body, self.v_kov, 0)
        switch(c.body, "Put the playlists into KovaaK's (once a day)", self.v_put, self.save).grid(
            row=2, column=0, sticky="w", pady=(14, 4))
        switch(c.body, "Send new scores to valcoach", self.v_scores, self.save).grid(row=3, column=0, sticky="w", pady=4)

        # Medal
        p = self.pages["medal"]
        self._title(p, "Medal", "Each match is cut out of your session recordings (by the start time in the file name "
                                "and Riot's match start) and uploaded. It's then ready on the match's coach page.")
        c = Card(p, "Recordings folder", "Where Medal saves full-session recordings (MedalTVValorant….mp4).")
        c.grid(row=2, column=0, sticky="ew")
        self._folder_row(c.body, self.v_medal, 0)
        switch(c.body, "Cut my matches out and upload them", self.v_upload, self.save).grid(
            row=2, column=0, sticky="w", pady=(14, 4))

        # settings: account and app
        p = self.pages["settings"]
        self._title(p, "Settings")
        c = Card(p, "Account")
        c.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        c.body.grid_columnconfigure(0, weight=1)
        self.who = ctk.CTkLabel(c.body, text="", text_color=TEXT, font=ctk.CTkFont(size=13), anchor="w")
        self.who.grid(row=0, column=0, sticky="ew")
        ghost_button(c.body, "Log out", self.logout).grid(row=0, column=1)
        c = Card(p, "App")
        c.grid(row=3, column=0, sticky="ew")
        switch(c.body, "Start with Windows (in the tray)", self.v_auto, self.save).grid(row=0, column=0, sticky="w", pady=4)
        switch(c.body, "Look for updates once a day", self.v_updates, self.save).grid(row=1, column=0, sticky="w", pady=4)
        line = ctk.CTkFrame(c.body, fg_color="transparent")
        line.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(line, text=f"Version {__version__}", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="left")
        ghost_button(line, "Check for updates", lambda: self.check_updates(quiet=False), width=150).pack(side="right")
        self.current = "overview"

    def _title(self, master, text: str, sub: str = "") -> None:
        box = ctk.CTkFrame(master, fg_color="transparent")
        box.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(box, text=text, font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT, anchor="w").pack(fill="x")
        if sub:
            ctk.CTkLabel(box, text=sub, font=ctk.CTkFont(size=12), text_color=MUTED, anchor="w", justify="left",
                         wraplength=560).pack(fill="x", pady=(2, 0))

    def page(self, key: str) -> None:
        """Show one page; the sidebar marks it."""
        self.current = key
        for k, f in self.pages.items():
            if k == key:
                f.grid(row=1, column=0, sticky="nsew", padx=24, pady=(20, 20))
            else:
                f.grid_remove()
        for k, b in self.nav.items():
            b.configure(fg_color=LINE if k == key else "transparent", text_color=TEXT if k == key else MUTED)

    @staticmethod
    def _count(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"

    def show_tiles(self) -> None:
        def folder_ok(path: str, *parts: str) -> bool:
            return bool(path) and Path(path, *parts).is_dir()
        kov_ok = folder_ok(self.s.kovaaks_dir, "Saved")
        rows = {
            "playlists": (self.s.put_playlists, kov_ok, "Folder not found" if not kov_ok else
                          (f"Last written {self.s.last_playlists}" if self.s.last_playlists else "Not written yet")),
            "scores": (self.s.send_scores, kov_ok, "Folder not found" if not kov_ok else
                       f"{len(self.s.stats_sent)} file{'s' if len(self.s.stats_sent) != 1 else ''} sent"),
            "medal": (self.s.upload_matches, folder_ok(self.s.medal_dir), "Folder not found"
                      if not folder_ok(self.s.medal_dir) else
                      self._count(sum(len(x.get('matches', [])) for x in self.s.recordings.values()), "match", "matches") + " uploaded"),
        }
        for key, (on, ok, sub) in rows.items():
            val, lab = self.tiles[key]
            val.configure(text="On" if on and ok else ("Check folder" if on else "Off"),
                          text_color=OK if on and ok else (WARN if on else MUTED))
            lab.configure(text=sub if on else "Switched off")

    def _folder_row(self, master, var, row: int) -> None:
        line = ctk.CTkFrame(master, fg_color="transparent")
        line.grid(row=row, column=0, sticky="ew")
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
            self.login_page.grid_remove()
            self.side.grid(row=0, column=0, sticky="nsw")
            self.main.grid(row=0, column=1, sticky="nsew")
            self.page(self.current)
            host = self.s.server.split("://", 1)[-1]
            self.who.configure(text=f"{self.s.user}  ·  {host}")
            threading.Thread(target=self.load_players, daemon=True).start()
        else:
            self.side.grid_remove()
            self.main.grid_remove()
            self.login_page.grid(row=0, column=0, columnspan=2, sticky="nsew")
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
            return
        if self.busy.locked():
            pill, color, state = "Working", WARN, "Working…"
        elif self.last_sync:
            pill, color, state = "Up to date", OK, f"Last check {self.last_sync}, every {self.s.every_min} min"
        else:
            pill, color, state = "Starting", MUTED, "Starting…"
        self.pill.configure(text=f"● {pill}", text_color=color)
        self.state.configure(text=state)
        self.show_tiles()

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
        self.banner.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 0))
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
                with self.busy:                   # never update in the middle of an upload
                    import tempfile
                    setup = updater.download(info, Path(tempfile.gettempdir()), progress)
                    updater.install(setup)
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
