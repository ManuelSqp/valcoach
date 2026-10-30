"""SQLite storage for the web app: settings, user accounts, player profiles and coaching jobs.

Every profile belongs to one user (its workspace). Jobs belong to a profile, so
they belong to that profile's owner too. Server settings are shared.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from ..config import (CoachCfg, Config, HenrikCfg, OllamaCfg, PathsCfg, PlayerCfg, VideoCfg,
                      load_config)

PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id   INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL COLLATE NOCASE,
  tag        TEXT NOT NULL COLLATE NOCASE,
  region     TEXT NOT NULL DEFAULT 'eu',
  platform   TEXT NOT NULL DEFAULT 'pc',
  mode       TEXT NOT NULL DEFAULT 'both',
  language   TEXT NOT NULL DEFAULT 'English',
  playbook   TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  position   INTEGER NOT NULL DEFAULT 0,
  UNIQUE(owner_id, name, tag)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  is_admin      INTEGER NOT NULL DEFAULT 0,
  vod_dir       TEXT NOT NULL DEFAULT '',
  session_key   TEXT NOT NULL,
  disabled      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  last_login    TEXT NOT NULL DEFAULT ''
);
""" + PROFILES_TABLE.format(name="profiles") + """
CREATE TABLE IF NOT EXISTS jobs (
  id          TEXT PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  match_id    TEXT NOT NULL,
  map         TEXT NOT NULL DEFAULT '',
  score       TEXT NOT NULL DEFAULT '',
  started_at_match TEXT NOT NULL DEFAULT '',
  mode        TEXT NOT NULL,
  vod_path    TEXT NOT NULL DEFAULT '',
  vod_name    TEXT NOT NULL DEFAULT '',
  options     TEXT NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'queued',
  log         TEXT NOT NULL DEFAULT '',
  error       TEXT NOT NULL DEFAULT '',
  html_path   TEXT NOT NULL DEFAULT '',
  json_path   TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  started_at  TEXT NOT NULL DEFAULT '',
  finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_profile ON jobs(profile_id, created_at);
CREATE TABLE IF NOT EXISTS teams (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  members    TEXT NOT NULL DEFAULT '[]',
  maps       TEXT NOT NULL DEFAULT '[]',
  meta       TEXT NOT NULL DEFAULT '',
  queue      TEXT NOT NULL DEFAULT 'all',
  created_at TEXT NOT NULL,
  premier    TEXT NOT NULL DEFAULT '{}',
  discord    TEXT NOT NULL DEFAULT '{}',
  sync       TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS team_access (
  team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (team_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_notes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  about_pid  INTEGER,
  map        TEXT NOT NULL DEFAULT '',
  text       TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS team_notes_team ON team_notes(team_id, created_at);
CREATE TABLE IF NOT EXISTS strats (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  map        TEXT NOT NULL,
  side       TEXT NOT NULL DEFAULT 'attack',
  name       TEXT NOT NULL,
  data       TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by INTEGER
);
CREATE INDEX IF NOT EXISTS strats_team ON strats(team_id, map);
CREATE TABLE IF NOT EXISTS drafts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  map        TEXT NOT NULL,
  name       TEXT NOT NULL,
  data       TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by INTEGER
);
CREATE INDEX IF NOT EXISTS drafts_team ON drafts(team_id, map);
"""

DEFAULTS: dict[str, str] = {
    "henrik_api_key": "",
    "henrik_base_url": "https://api.henrikdev.xyz",
    # env var lets a container/service point at Ollama without touching the database
    "ollama_url": os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
    "ollama_model": "qwen3.8:27b",
    "ollama_think": "off",
    "ollama_temperature": "0.3",
    "ollama_num_ctx": "16384",
    "ollama_parallel": "4",
    "ollama_timeout_s": "300",
    "minimap_roi": "0.012, 0.025, 0.215, 0.382",
    "killfeed_roi": "0.70, 0.08, 0.29, 0.25",
    "sample_fps": "4",
    "workers": "1",
    "allow_signup": "0",
    "max_upload_gb": "20",         # per uploaded VOD
    "max_jobs_per_user": "3",      # queued + running at the same time
    "youtube_api_key": "",         # optional: inline videos on the Pro & videos page
    "pros_yaml": "",               # optional: edited pro list (empty = built-in stats/pros.yaml)
    "secret_key": "",
    "vod_dir": "",                 # legacy (pre-accounts): moved to the first admin on setup
    "access_password_hash": "",    # legacy (pre-accounts): replaced by user accounts
}

REGIONS = ["eu", "na", "ap", "kr", "latam", "br"]
PLATFORMS = ["pc", "console"]
MODES = ["both", "team", "player"]
MIN_PASSWORD = 8


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_roi(text: str) -> list[float]:
    vals = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
    if len(vals) != 4 or not all(0 <= v <= 1 for v in vals) or vals[2] <= 0 or vals[3] <= 0:
        raise ValueError("needs 4 numbers between 0 and 1: x, y, width, height")
    return vals


def validate_username(name: str) -> str | None:
    if not 3 <= len(name) <= 32:
        return "Username must have 3 to 32 characters."
    if not all(c.isalnum() or c in "-_." for c in name):
        return "Username may only contain letters, digits, - _ and ."
    return None


def validate_password(pw: str) -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"Password must have at least {MIN_PASSWORD} characters."
    return None


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    is_admin: int
    vod_dir: str
    session_key: str
    disabled: int
    created_at: str
    last_login: str
    display_name: str = ""     # in-game name, e.g. adv1ce#LFT

    @property
    def label(self) -> str:
        return self.display_name or self.username


@dataclass
class Profile:
    id: int
    owner_id: int | None
    name: str
    tag: str
    region: str
    platform: str
    mode: str
    language: str
    playbook: str
    created_at: str
    position: int = 0

    @property
    def riot_id(self) -> str:
        return f"{self.name}#{self.tag}"


@dataclass
class Job:
    id: str
    profile_id: int
    match_id: str
    map: str
    score: str
    started_at_match: str
    mode: str
    vod_path: str
    vod_name: str
    options: str
    status: str
    log: str
    error: str
    html_path: str
    json_path: str
    created_at: str
    started_at: str
    finished_at: str

    @property
    def opts(self) -> dict:
        return json.loads(self.options or "{}")


@dataclass
class Team:
    id: int
    owner_id: int
    name: str
    members: str          # JSON [{"pid": 1, "kind": "starter" | "sub"}]
    maps: str             # JSON ["Ascent", ...]
    meta: str             # YAML, see stats/comp.py META_EXAMPLE
    queue: str
    created_at: str
    premier: str = "{}"   # JSON {name, tag, region, id, placement, stats, synced_at}
    discord: str = "{}"   # JSON {prep_url, focus_url, weekly_day, weekly_hour, last_focus_week}
    sync: str = "{}"      # JSON {nightly (default on), hour (default 2), last_day, last_try, last_at}

    @property
    def sync_info(self) -> dict:
        try:
            d = json.loads(self.sync or "{}")
        except ValueError:
            d = {}
        d.setdefault("nightly", True)
        d.setdefault("hour", 2)
        return d

    @property
    def discord_info(self) -> dict:
        try:
            return json.loads(self.discord or "{}")
        except ValueError:
            return {}

    @property
    def premier_info(self) -> dict:
        try:
            return json.loads(self.premier or "{}")
        except ValueError:
            return {}

    @property
    def member_list(self) -> list[dict]:
        return json.loads(self.members or "[]")

    @property
    def map_list(self) -> list[str]:
        return json.loads(self.maps or "[]")


def _load(cls, row):
    """Build a dataclass from a DB row. Columns this code version doesn't know are ignored,
    so a database touched by a newer/older version never crashes the app."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in dict(row).items() if k in names})


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "valcoach.db"
        self._lock = threading.RLock()
        self._migrate()
        if not self.get("secret_key"):
            self.set("secret_key", secrets.token_hex(32))

    # ---- connection / migration --------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _migrate(self) -> None:
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        try:
            c.execute("PRAGMA foreign_keys = OFF")     # table rebuild must not cascade-delete jobs
            c.executescript(SCHEMA)
            cols = [r[1] for r in c.execute("PRAGMA table_info(profiles)")]
            if "owner_id" not in cols:
                # v2.1 database: profiles without owners -> rebuild, owners assigned at first setup
                c.execute("BEGIN")
                c.execute(PROFILES_TABLE.format(name="profiles_new"))
                c.execute("INSERT INTO profiles_new(id, owner_id, name, tag, region, platform, mode, language, "
                          "playbook, created_at) SELECT id, NULL, name, tag, region, platform, mode, language, "
                          "playbook, created_at FROM profiles")
                c.execute("DROP TABLE profiles")
                c.execute("ALTER TABLE profiles_new RENAME TO profiles")
                c.execute("COMMIT")
            tcols = [r[1] for r in c.execute("PRAGMA table_info(teams)")]
            if "premier" not in tcols:
                # v2.10 database: Premier team link (name, tag, region, placement)
                c.execute("ALTER TABLE teams ADD COLUMN premier TEXT NOT NULL DEFAULT '{}'")
            if "discord" not in tcols:
                # v2.11 database: Discord webhooks and the weekly schedule
                c.execute("ALTER TABLE teams ADD COLUMN discord TEXT NOT NULL DEFAULT '{}'")
            if "sync" not in tcols:
                # v2.15 database: nightly automatic sync
                c.execute("ALTER TABLE teams ADD COLUMN sync TEXT NOT NULL DEFAULT '{}'")
            ucols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
            if "display_name" not in ucols:
                # v2.11 database: in-game name shown to teammates
                c.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
            cols = [r[1] for r in c.execute("PRAGMA table_info(profiles)")]
            if "position" not in cols:
                # v2.2 database: add the drag-and-drop order, starting alphabetical
                c.execute("ALTER TABLE profiles ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
                rows = c.execute("SELECT id FROM profiles ORDER BY owner_id, name COLLATE NOCASE").fetchall()
                c.execute("BEGIN")
                for i, (pid,) in enumerate(rows):
                    c.execute("UPDATE profiles SET position = ? WHERE id = ?", (i, pid))
                c.execute("COMMIT")
        finally:
            c.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            c = self._conn()
            try:
                cur = c.execute(sql, params)
                c.commit()
                return cur
            finally:
                c.close()

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            c = self._conn()
            try:
                return c.execute(sql, params).fetchall()
            finally:
                c.close()

    # ---- settings ---------------------------------------------------------
    def get(self, key: str) -> str:
        rows = self._all("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else DEFAULTS.get(key, "")

    def set(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def settings(self) -> dict[str, str]:
        out = dict(DEFAULTS)
        for r in self._all("SELECT key, value FROM settings"):
            out[r["key"]] = r["value"]
        return out

    def is_seeded(self) -> bool:
        return bool(self._all("SELECT 1 FROM settings WHERE key = 'seeded'"))

    def seed_from_config(self, path: Path | None) -> None:
        """First start: take server settings (and the player as first profile) from config.toml.
        The profile has no owner yet; the admin created at setup gets it."""
        if self.is_seeded():
            return
        if path and path.exists():
            cfg = load_config(path)
            self.set("henrik_api_key", cfg.henrik.api_key)
            self.set("henrik_base_url", cfg.henrik.base_url)
            self.set("ollama_url", cfg.ollama.url)
            self.set("ollama_model", cfg.ollama.model)
            self.set("ollama_temperature", str(cfg.ollama.temperature))
            self.set("ollama_num_ctx", str(cfg.ollama.num_ctx))
            self.set("ollama_parallel", str(cfg.ollama.parallel))
            self.set("ollama_timeout_s", str(cfg.ollama.timeout_s))
            self.set("ollama_think", cfg.ollama.think)
            self.set("minimap_roi", ", ".join(str(v) for v in cfg.video.minimap_roi))
            self.set("killfeed_roi", ", ".join(str(v) for v in cfg.video.killfeed_roi))
            self.set("sample_fps", str(cfg.video.sample_fps))
            if cfg.player.name and cfg.player.tag and not self._all("SELECT 1 FROM profiles"):
                playbook = ""
                pb = cfg.path(cfg.coach.playbook)
                if pb.is_file():
                    playbook = pb.read_text()
                self.create_profile(None, cfg.player.name, cfg.player.tag, cfg.player.region,
                                    cfg.player.platform, cfg.coach.mode, cfg.coach.language, playbook)
        self.set("seeded", "1")

    # ---- users ------------------------------------------------------------
    def user_count(self) -> int:
        return int(self._all("SELECT COUNT(*) AS n FROM users")[0]["n"])

    def admin_count(self) -> int:
        return int(self._all("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND disabled = 0")[0]["n"])

    def users(self) -> list[User]:
        return [_load(User, r) for r in self._all("SELECT * FROM users ORDER BY username")]

    def user(self, uid: int) -> User | None:
        rows = self._all("SELECT * FROM users WHERE id = ?", (uid,))
        return _load(User, rows[0]) if rows else None

    def user_by_name(self, username: str) -> User | None:
        rows = self._all("SELECT * FROM users WHERE username = ?", (username.strip(),))
        return _load(User, rows[0]) if rows else None

    def create_user(self, username: str, password: str, is_admin: bool = False, vod_dir: str = "") -> int:
        cur = self._exec(
            "INSERT INTO users(username, password_hash, is_admin, vod_dir, session_key, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (username.strip(), generate_password_hash(password), int(is_admin), vod_dir,
             secrets.token_hex(16), now()))
        return int(cur.lastrowid)

    def verify_login(self, username: str, password: str) -> User | None:
        u = self.user_by_name(username)
        if u is None:
            # same work as a real check, so response time doesn't reveal which usernames exist
            check_password_hash(generate_password_hash("x"), password)
            return None
        if u.disabled or not check_password_hash(u.password_hash, password):
            return None
        self._exec("UPDATE users SET last_login = ? WHERE id = ?", (now(), u.id))
        return u

    def set_password(self, uid: int, password: str) -> str:
        """Change password and rotate the session key (logs out all other sessions)."""
        key = secrets.token_hex(16)
        self._exec("UPDATE users SET password_hash = ?, session_key = ? WHERE id = ?",
                   (generate_password_hash(password), key, uid))
        return key

    def update_user(self, uid: int, **fields) -> None:
        allowed = {"is_admin", "vod_dir", "disabled", "display_name"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        if sets.get("disabled"):
            sets["session_key"] = secrets.token_hex(16)     # kick out active sessions
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._exec(f"UPDATE users SET {cols} WHERE id = ?", (*sets.values(), uid))

    def delete_user(self, uid: int) -> None:
        self._exec("DELETE FROM users WHERE id = ?", (uid,))     # cascades to profiles + jobs

    def claim_orphans(self, uid: int) -> int:
        """Give profiles without owner (from before accounts existed) to this user."""
        return self._exec("UPDATE profiles SET owner_id = ? WHERE owner_id IS NULL", (uid,)).rowcount

    def resolve(self, stored: str) -> Path | None:
        """Find a file whose path was saved in the database.

        Reports and uploads live inside the data folder; if that folder moved (e.g. into a
        Docker volume mounted at /data), the old absolute path is re-based onto the current
        data folder. Other paths (recordings folders) are used as they are."""
        if not stored:
            return None
        p = Path(stored)
        if p.is_file():
            return p
        parts = p.parts
        for marker in ("reports", "uploads"):
            if marker in parts:
                i = len(parts) - 1 - parts[::-1].index(marker)
                cand = self.data_dir.joinpath(*parts[i:])
                if cand.is_file():
                    return cand
        return None

    def upload_dir(self, uid: int) -> Path:
        return self.data_dir / "uploads" / str(uid)

    # ---- profiles ---------------------------------------------------------
    def profiles(self, owner_id: int) -> list[Profile]:
        return [_load(Profile, r) for r in
                self._all("SELECT * FROM profiles WHERE owner_id = ? ORDER BY position, name COLLATE NOCASE",
                          (owner_id,))]

    def profile(self, pid: int) -> Profile | None:
        rows = self._all("SELECT * FROM profiles WHERE id = ?", (pid,))
        return _load(Profile, rows[0]) if rows else None

    def create_profile(self, owner_id: int | None, name: str, tag: str, region: str = "eu",
                       platform: str = "pc", mode: str = "both", language: str = "English",
                       playbook: str = "") -> int:
        last = self._all("SELECT COALESCE(MAX(position), -1) AS m FROM profiles WHERE owner_id IS ?", (owner_id,))
        cur = self._exec(
            "INSERT INTO profiles(owner_id, name, tag, region, platform, mode, language, playbook, created_at, position) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, name.strip(), tag.strip().lstrip("#"), region, platform, mode, language, playbook, now(),
             int(last[0]["m"]) + 1))
        pid = int(cur.lastrowid)
        self._write_playbook(pid, playbook)
        return pid

    def update_profile(self, pid: int, **fields) -> None:
        allowed = {"name", "tag", "region", "platform", "mode", "language", "playbook"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "tag" in sets:
            sets["tag"] = sets["tag"].strip().lstrip("#")
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._exec(f"UPDATE profiles SET {cols} WHERE id = ?", (*sets.values(), pid))
        if "playbook" in sets:
            self._write_playbook(pid, sets["playbook"])

    def reorder_profiles(self, owner_id: int, ordered_ids: list[int]) -> None:
        """Save the drag-and-drop order. Must contain exactly this owner's profiles."""
        own = {p.id for p in self.profiles(owner_id)}
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != own:
            raise ValueError("order must list each of your players exactly once")
        with self._lock:
            c = self._conn()
            try:
                c.executemany("UPDATE profiles SET position = ? WHERE id = ? AND owner_id = ?",
                              [(i, pid, owner_id) for i, pid in enumerate(ordered_ids)])
                c.commit()
            finally:
                c.close()

    def find_profile(self, owner_id: int, name: str, tag: str) -> Profile | None:
        rows = self._all("SELECT * FROM profiles WHERE owner_id = ? AND name = ? AND tag = ?",
                         (owner_id, name.strip(), tag.strip().lstrip("#")))
        return _load(Profile, rows[0]) if rows else None

    def delete_profile(self, pid: int) -> None:
        self._exec("DELETE FROM profiles WHERE id = ?", (pid,))

    def profile_dir(self, pid: int) -> Path:
        return self.data_dir / "profiles" / str(pid)

    def _write_playbook(self, pid: int, text: str) -> None:
        p = self.profile_dir(pid) / "playbook.yaml"
        if text.strip():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        elif p.exists():
            p.unlink()

    # ---- jobs -------------------------------------------------------------
    def create_job(self, job_id: str, profile_id: int, match_id: str, mode: str, vod_path: str = "",
                   vod_name: str = "", options: dict | None = None, map_name: str = "",
                   started_at_match: str = "") -> None:
        self._exec(
            "INSERT INTO jobs(id, profile_id, match_id, map, started_at_match, mode, vod_path, vod_name, "
            "options, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, profile_id, match_id, map_name, started_at_match, mode, vod_path, vod_name,
             json.dumps(options or {}), now()))

    def job(self, job_id: str) -> Job | None:
        rows = self._all("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return _load(Job, rows[0]) if rows else None

    def job_owner(self, job_id: str) -> int | None:
        rows = self._all("SELECT p.owner_id FROM jobs j JOIN profiles p ON p.id = j.profile_id WHERE j.id = ?",
                         (job_id,))
        return rows[0]["owner_id"] if rows else None

    def jobs(self, profile_id: int, limit: int = 50) -> list[Job]:
        rows = self._all("SELECT * FROM jobs WHERE profile_id = ? ORDER BY created_at DESC LIMIT ?",
                         (profile_id, limit))
        return [_load(Job, r) for r in rows]

    def jobs_for_owner(self, owner_id: int, limit: int = 50) -> list[Job]:
        rows = self._all("SELECT j.* FROM jobs j JOIN profiles p ON p.id = j.profile_id "
                         "WHERE p.owner_id = ? ORDER BY j.created_at DESC LIMIT ?", (owner_id, limit))
        return [_load(Job, r) for r in rows]

    def active_jobs_for_owner(self, owner_id: int) -> int:
        return int(self._all("SELECT COUNT(*) AS n FROM jobs j JOIN profiles p ON p.id = j.profile_id "
                             "WHERE p.owner_id = ? AND j.status IN ('queued', 'running')", (owner_id,))[0]["n"])

    def jobs_for_match(self, profile_id: int, match_id: str) -> list[Job]:
        rows = self._all("SELECT * FROM jobs WHERE profile_id = ? AND match_id = ? ORDER BY created_at DESC",
                         (profile_id, match_id))
        return [_load(Job, r) for r in rows]

    def jobs_with_status(self, *statuses: str) -> list[Job]:
        q = ",".join("?" * len(statuses))
        rows = self._all(f"SELECT * FROM jobs WHERE status IN ({q}) ORDER BY created_at", statuses)
        return [_load(Job, r) for r in rows]

    def jobs_using_vod(self, vod_path: str) -> list[Job]:
        return [_load(Job, r) for r in self._all("SELECT * FROM jobs WHERE vod_path = ?", (vod_path,))]

    def update_job(self, job_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def claim_job(self, job_id: str) -> bool:
        """queued -> running in one statement; False if it wasn't queued (already taken, deleted)."""
        cur = self._exec("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                         (now(), job_id))
        return cur.rowcount == 1

    def append_log(self, job_id: str, line: str) -> None:
        self._exec("UPDATE jobs SET log = log || ? WHERE id = ?", (line.rstrip() + "\n", job_id))

    def delete_job(self, job_id: str) -> None:
        self._exec("DELETE FROM jobs WHERE id = ?", (job_id,))

    def queue_position(self, job_id: str) -> int:
        rows = self._all("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at")
        ids = [r["id"] for r in rows]
        return ids.index(job_id) + 1 if job_id in ids else 0

    def usage_by_user(self) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for r in self._all("SELECT u.id, COUNT(DISTINCT p.id) AS profiles, COUNT(j.id) AS jobs FROM users u "
                           "LEFT JOIN profiles p ON p.owner_id = u.id LEFT JOIN jobs j ON j.profile_id = p.id "
                           "GROUP BY u.id"):
            out[r["id"]] = {"profiles": r["profiles"], "jobs": r["jobs"]}
        return out

    # ---- teams --------------------------------------------------------------
    def teams(self, owner_id: int) -> list[Team]:
        return [_load(Team, r) for r in self._all("SELECT * FROM teams WHERE owner_id = ? ORDER BY name", (owner_id,))]

    def team(self, tid: int) -> Team | None:
        rows = self._all("SELECT * FROM teams WHERE id = ?", (tid,))
        return _load(Team, rows[0]) if rows else None

    def create_team(self, owner_id: int, name: str) -> int:
        cur = self._exec("INSERT INTO teams(owner_id, name, created_at) VALUES(?, ?, ?)", (owner_id, name.strip(), now()))
        return int(cur.lastrowid)

    def update_team(self, tid: int, **fields) -> None:
        allowed = {"name", "members", "maps", "meta", "queue", "premier", "discord", "sync"}
        sets = {k: (json.dumps(v) if k in ("members", "maps", "premier", "discord", "sync") and not isinstance(v, str) else v)
                for k, v in fields.items() if k in allowed}
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            self._exec(f"UPDATE teams SET {cols} WHERE id = ?", (*sets.values(), tid))

    def delete_team(self, tid: int) -> None:
        self._exec("DELETE FROM teams WHERE id = ?", (tid,))

    def all_teams(self) -> list["Team"]:
        return [_load(Team, r) for r in self._all("SELECT * FROM teams ORDER BY id")]

    # ---- team access (teammates with their own accounts) -------------------
    def teams_for_user(self, uid: int) -> list["Team"]:
        """Teams you own plus teams you were added to."""
        rows = self._all("SELECT t.* FROM teams t WHERE t.owner_id = ? OR t.id IN "
                         "(SELECT team_id FROM team_access WHERE user_id = ?) ORDER BY t.name", (uid, uid))
        return [_load(Team, r) for r in rows]

    def team_access(self, tid: int) -> list[User]:
        rows = self._all("SELECT u.* FROM users u JOIN team_access a ON a.user_id = u.id WHERE a.team_id = ? "
                         "ORDER BY u.username", (tid,))
        return [_load(User, r) for r in rows]

    def has_team_access(self, tid: int, uid: int) -> bool:
        return bool(self._all("SELECT 1 FROM team_access WHERE team_id = ? AND user_id = ?", (tid, uid)))

    def add_team_access(self, tid: int, uid: int) -> None:
        self._exec("INSERT OR IGNORE INTO team_access(team_id, user_id, created_at) VALUES(?, ?, ?)", (tid, uid, now()))

    def remove_team_access(self, tid: int, uid: int) -> None:
        self._exec("DELETE FROM team_access WHERE team_id = ? AND user_id = ?", (tid, uid))

    # ---- team notes ------------------------------------------------------------
    def team_notes(self, tid: int) -> list[dict]:
        rows = self._all("SELECT n.*, COALESCE(NULLIF(u.display_name, ''), u.username) AS author FROM team_notes n "
                         "LEFT JOIN users u ON u.id = n.author_id WHERE n.team_id = ? ORDER BY n.created_at DESC", (tid,))
        return [dict(r) for r in rows]

    def add_team_note(self, tid: int, author_id: int, text: str, about_pid: int | None = None, map_name: str = "") -> None:
        self._exec("INSERT INTO team_notes(team_id, author_id, about_pid, map, text, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                   (tid, author_id, about_pid, map_name, text.strip()[:2000], now()))

    def team_note(self, nid: int) -> dict | None:
        rows = self._all("SELECT * FROM team_notes WHERE id = ?", (nid,))
        return dict(rows[0]) if rows else None

    def delete_team_note(self, nid: int) -> None:
        self._exec("DELETE FROM team_notes WHERE id = ?", (nid,))

    # ---- strat book ---------------------------------------------------------------
    def strats(self, tid: int) -> list[dict]:
        rows = self._all("SELECT s.id, s.team_id, s.author_id, s.map, s.side, s.name, s.created_at, s.updated_at, "
                         "LENGTH(s.data) AS size, COALESCE(NULLIF(u.display_name, ''), u.username) AS author "
                         "FROM strats s LEFT JOIN users u ON u.id = s.updated_by WHERE s.team_id = ? "
                         "ORDER BY s.map, s.side, s.name", (tid,))
        return [dict(r) for r in rows]

    def strat(self, sid: int) -> dict | None:
        rows = self._all("SELECT * FROM strats WHERE id = ?", (sid,))
        if not rows:
            return None
        d = dict(rows[0])
        try:
            d["data"] = json.loads(d["data"] or "{}")
        except ValueError:
            d["data"] = {}
        return d

    def create_strat(self, tid: int, author_id: int, map_name: str, side: str, name: str, data: dict | None = None) -> int:
        cur = self._exec("INSERT INTO strats(team_id, author_id, map, side, name, data, created_at, updated_at, updated_by) "
                         "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (tid, author_id, map_name, side, name.strip()[:80], json.dumps(data or {}), now(), now(), author_id))
        return int(cur.lastrowid)

    def update_strat(self, sid: int, user_id: int, **fields) -> None:
        sets = {k: v for k, v in fields.items() if k in ("name", "side", "data")}
        if "data" in sets and not isinstance(sets["data"], str):
            sets["data"] = json.dumps(sets["data"])
        sets.update(updated_at=now(), updated_by=user_id)
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._exec(f"UPDATE strats SET {cols} WHERE id = ?", (*sets.values(), sid))

    def delete_strat(self, sid: int) -> None:
        self._exec("DELETE FROM strats WHERE id = ?", (sid,))

    # ---- roster drafts (team tab "Drafts") -----------------------------------
    def drafts(self, tid: int, map_name: str | None = None) -> list[dict]:
        q = ("SELECT d.*, COALESCE(NULLIF(u.display_name, ''), u.username) AS editor FROM drafts d "
             "LEFT JOIN users u ON u.id = d.updated_by WHERE d.team_id = ?")
        args: tuple = (tid,)
        if map_name:
            q += " AND d.map = ?"
            args += (map_name,)
        out = []
        for r in self._all(q + " ORDER BY d.map, d.updated_at DESC", args):
            d = dict(r)
            try:
                d["data"] = json.loads(d["data"] or "{}")
            except ValueError:
                d["data"] = {}
            out.append(d)
        return out

    def draft(self, did: int) -> dict | None:
        rows = self._all("SELECT * FROM drafts WHERE id = ?", (did,))
        if not rows:
            return None
        d = dict(rows[0])
        try:
            d["data"] = json.loads(d["data"] or "{}")
        except ValueError:
            d["data"] = {}
        return d

    def create_draft(self, tid: int, author_id: int, map_name: str, name: str, data: dict | None = None) -> int:
        cur = self._exec("INSERT INTO drafts(team_id, author_id, map, name, data, created_at, updated_at, updated_by) "
                         "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                         (tid, author_id, map_name, name.strip()[:80], json.dumps(data or {}), now(), now(), author_id))
        return int(cur.lastrowid)

    def update_draft(self, did: int, user_id: int, **fields) -> None:
        sets = {k: v for k, v in fields.items() if k in ("name", "data")}
        if "data" in sets and not isinstance(sets["data"], str):
            sets["data"] = json.dumps(sets["data"])
        sets.update(updated_at=now(), updated_by=user_id)
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._exec(f"UPDATE drafts SET {cols} WHERE id = ?", (*sets.values(), did))

    def delete_draft(self, did: int) -> None:
        self._exec("DELETE FROM drafts WHERE id = ?", (did,))

    # ---- config for one run -------------------------------------------------
    def build_config(self, profile: Profile) -> Config:
        s = self.settings()
        pdir = self.profile_dir(profile.id)
        return Config(
            player=PlayerCfg(name=profile.name, tag=profile.tag, region=profile.region,
                             platform=profile.platform),
            henrik=HenrikCfg(api_key=s["henrik_api_key"], base_url=s["henrik_base_url"]),
            ollama=OllamaCfg(url=s["ollama_url"], model=s["ollama_model"],
                             temperature=float(s["ollama_temperature"]), num_ctx=int(s["ollama_num_ctx"]),
                             parallel=int(s["ollama_parallel"]), timeout_s=int(s["ollama_timeout_s"]),
                             think=s["ollama_think"]),
            coach=CoachCfg(mode=profile.mode, language=profile.language,
                           playbook=str(pdir / "playbook.yaml"), notes_dir=str(pdir / "notes")),
            video=VideoCfg(minimap_roi=parse_roi(s["minimap_roi"]), killfeed_roi=parse_roi(s["killfeed_roi"]),
                           sample_fps=float(s["sample_fps"])),
            paths=PathsCfg(cache_dir=str(self.data_dir / "cache"), output_dir=str(self.data_dir / "reports")),
            root=self.data_dir,
        )
