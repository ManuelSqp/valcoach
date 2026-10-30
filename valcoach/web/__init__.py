"""valcoach web app.

User accounts with separate workspaces (players, reports, notes, playbooks,
uploads), server settings for admins, match list, coaching jobs with a shared
queue, a round-notes editor and the reports, all in the browser.
Start with:  valcoach web   (then open http://<this machine>:10070)
"""
from __future__ import annotations

import functools
import shutil
import socket
import sqlite3
import tempfile
import time
import uuid
from urllib.parse import urlsplit
from datetime import datetime
from pathlib import Path

import requests
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   session, url_for)

from .. import __version__, pipeline
from ..henrik import HenrikError
from .jobs import JobRunner
from .statsjobs import StatsRunner
from .store import (MIN_PASSWORD, MODES, PLATFORMS, REGIONS, Store, parse_roi, validate_password,
                    validate_username)
from .uploads import CHUNK_BYTES, MAX_REQUEST_BYTES, UploadError, Uploads

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
QUEUES = [("", "All queues"), ("premier", "Premier"), ("competitive", "Competitive"),
          ("unrated", "Unrated"), ("swiftplay", "Swiftplay"), ("custom", "Custom")]
HISTORY_TTL_S = 120
HISTORY_PAGE = 10     # full matches per page (each uncached match costs one API request)
STORED_PAGE = 20      # stored-archive rows per page (one API request per page)
PLAYBOOK_EXAMPLE = (Path(__file__).parent / "playbook_example.yaml").read_text()
PUBLIC_ENDPOINTS = {"login", "signup", "setup", "static"}
MAX_LOGIN_FAILS = 5
LOCKOUT_S = 600
MAX_CACHE_ENTRIES = 200                # match-list cache (one entry per player / queue / page)
MAX_TRACKED_LOGINS = 1000              # failed-login records kept for the lockout


def _host_boot() -> float | None:
    """When the machine itself booted (Linux), for the uptime tooltip."""
    try:
        return time.time() - float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def create_app(data_dir: Path, config_seed: Path | None = None, start_workers: bool = True) -> Flask:
    started_at = time.time()
    store = Store(data_dir)
    store.seed_from_config(config_seed)
    runner = JobRunner(store, int(store.get("workers") or 1))
    if start_workers:
        runner.recover()

    uploads = Uploads(store.data_dir / "tmp")

    app = Flask(__name__)
    app.secret_key = store.get("secret_key")
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,  # VODs come in chunks (uploads.py)
        SESSION_COOKIE_SAMESITE="Lax",         # blocks cross-site form posts (CSRF) in browsers
        SESSION_COOKIE_HTTPONLY=True,
    )
    stats_runner = StatsRunner(store)
    app.extensions["valcoach"] = {"store": store, "runner": runner, "stats": stats_runner, "uploads": uploads}
    history_cache: dict[tuple, tuple[float, list[dict]]] = {}
    login_fails: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ helpers
    def get_profile(pid: int):
        p = store.profile(pid)
        if p is None or p.owner_id != g.user.id:
            abort(404)                         # other users' data simply doesn't exist for you
        return p

    def get_job(jid: str):
        j = store.job(jid)
        if j is None or store.job_owner(jid) != g.user.id:
            abort(404)
        return j

    def admin_required(view):
        @functools.wraps(view)
        def wrapped(*a, **k):
            if not g.user.is_admin:
                abort(403)
            return view(*a, **k)
        return wrapped

    def vod_root(user) -> Path | None:
        d = (user.vod_dir or "").strip()
        if not d:
            return None
        p = Path(d).expanduser()
        return p if p.is_dir() else None

    def list_vods(user, match_end: float | None) -> tuple[list[dict], str | None]:
        root = vod_root(user)
        if root is None:
            return [], None
        files = []
        for f in root.rglob("*"):
            try:
                if f.suffix.lower() not in VIDEO_EXT or len(f.relative_to(root).parts) > 3 or not f.is_file():
                    continue
                st = f.stat()
            except OSError:
                continue
            files.append({"rel": str(f.relative_to(root)), "name": f.name, "mtime": st.st_mtime,
                          "size": st.st_size})
        files.sort(key=lambda x: -x["mtime"])
        files = files[:100]
        suggested = None
        if match_end and files:
            # a recording is saved when it stops = shortly after the match ends
            best = min(files, key=lambda x: abs(x["mtime"] - match_end))
            if abs(best["mtime"] - match_end) < 20 * 60:
                suggested = best["rel"]
        return files, suggested

    def resolve_vod(user, rel: str) -> Path | None:
        root = vod_root(user)
        if root is None:
            return None
        p = (root / rel).resolve()
        if root.resolve() not in p.parents or not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
            return None
        return p

    def ollama_models() -> tuple[list[str], str | None]:
        try:
            r = requests.get(store.get("ollama_url").rstrip("/") + "/api/tags", timeout=2)
            r.raise_for_status()
            return sorted(m.get("name", "") for m in r.json().get("models", [])), None
        except Exception as e:
            return [], str(e)

    def log_in(user) -> None:
        session.clear()
        session.permanent = True
        session["uid"] = user.id
        session["sk"] = user.session_key

    def safe_next(default: str = "/") -> str:
        nxt = request.args.get("next", default)
        return nxt if nxt.startswith("/") and not nxt.startswith("//") else default

    def form_int(name: str, default: int, lo: int, hi: int) -> int | None:
        """Integer form field in [lo, hi]; None if it isn't one."""
        raw = request.form.get(name, "").strip()
        if not raw:
            return default
        try:
            val = int(raw)
        except ValueError:
            return None
        return val if lo <= val <= hi else None

    def job_quota_error(uid: int) -> str | None:
        limit = int(store.get("max_jobs_per_user") or 3)
        if store.active_jobs_for_owner(uid) >= limit:
            return (f"You already have {limit} reports queued or running. "
                    "Wait until one finishes before starting another.")
        return None

    def signup_enabled() -> bool:
        return store.get("allow_signup") == "1"

    def delete_user_data(uid: int) -> None:
        for p in store.profiles(uid):
            for j in store.jobs(p.id, 100_000):
                runner.delete(j.id)
            shutil.rmtree(store.profile_dir(p.id), ignore_errors=True)
        shutil.rmtree(store.upload_dir(uid), ignore_errors=True)
        store.delete_user(uid)

    # ------------------------------------------------------------- templating
    @app.template_filter("localtime")
    def localtime(iso: str) -> str:
        if not iso:
            return ""
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return iso

    @app.template_filter("epoch")
    def epoch(ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")

    @app.template_filter("mode_label")
    def mode_label(m: str) -> str:
        return {"both": "Team + me", "team": "Team / IGL", "player": "Only me"}.get(m, m)

    @app.template_filter("filesize")
    def filesize(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    @app.context_processor
    def inject():
        user = getattr(g, "user", None)
        return {
            "user": user,
            "nav_profiles": store.profiles(user.id) if user else [],
            "has_api_key": bool(store.get("henrik_api_key")),
            "signup_enabled": signup_enabled(),
            "min_password": MIN_PASSWORD,
            "app_version": __version__,
            "app_started": int(started_at),
            "server_now": int(time.time()),
            "host_boot": _host_boot(),
            "new_version": bool(user) and store.get(f"seen_version:{user.id}") not in ("", __version__),
        }

    # ------------------------------------------------------------------- auth
    @app.before_request
    def same_origin_only():
        """Forms may only be sent from this site (CSRF). Browsers add Origin (or at least Referer) to
        every POST; a form on another site carries that site's address and is refused."""
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        src = request.headers.get("Origin") or request.headers.get("Referer")
        if not src:
            return None                        # not a browser (CLI, scripts): SameSite cookies still apply
        if urlsplit(src).netloc not in {request.host, request.headers.get("X-Forwarded-Host", "")}:
            return render_template("error.html", code=403,
                                   msg="This form was sent from another website and was blocked."), 403
        return None

    @app.before_request
    def load_user():
        g.user = None
        if store.user_count() == 0:
            # fresh install (or upgrade from the version without accounts): create the admin first
            if request.endpoint not in ("setup", "static"):
                return redirect(url_for("setup"))
            return None
        uid = session.get("uid")
        if uid:
            u = store.user(uid)
            if u and not u.disabled and session.get("sk") == u.session_key:
                g.user = u
            else:
                session.clear()
        if g.user is not None and not store.get(f"seen_version:{g.user.id}"):
            # first visit of this account since the changelog exists: nothing to announce yet
            store.set(f"seen_version:{g.user.id}", __version__)
        if g.user is None and request.endpoint not in PUBLIC_ENDPOINTS:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login", next=request.path))
        return None

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if store.user_count() > 0:
            return redirect(url_for("login"))
        orphans = len(store._all("SELECT id FROM profiles WHERE owner_id IS NULL"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
            err = validate_username(username) or validate_password(pw) or (
                "The passwords don't match." if pw != pw2 else None)
            if not err:
                uid = store.create_user(username, pw, is_admin=True, vod_dir=store.get("vod_dir"))
                claimed = store.claim_orphans(uid)
                store.set("access_password_hash", "")     # replaced by accounts
                log_in(store.user(uid))
                flash(f"Welcome, {username}. You are the admin."
                      + (f" Your existing {claimed} player(s) and their reports are in your workspace." if claimed else ""),
                      "ok")
                return redirect(url_for("index"))
            flash(err, "error")
        return render_template("auth.html", mode="setup", orphans=orphans)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            key = f"{request.remote_addr}|{username.lower()}"
            if len(login_fails) > MAX_TRACKED_LOGINS:
                # forget expired lockouts so the table can't grow without end
                for k in [k for k, ts in login_fails.items() if not ts or time.time() - ts[-1] >= LOCKOUT_S]:
                    del login_fails[k]
            recent = [t for t in login_fails.get(key, []) if time.time() - t < LOCKOUT_S]
            login_fails[key] = recent
            if len(recent) >= MAX_LOGIN_FAILS:
                flash("Too many failed attempts. Try again in 10 minutes.", "error")
                return render_template("auth.html", mode="login", username=username), 429
            user = store.verify_login(username, request.form.get("password", ""))
            if user:
                login_fails.pop(key, None)
                log_in(user)
                return redirect(safe_next())
            recent.append(time.time())
            flash("Wrong username or password.", "error")
            return render_template("auth.html", mode="login", username=username), 401
        return render_template("auth.html", mode="login", username="")

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if not signup_enabled():
            abort(404)
        if g.user:
            return redirect(url_for("index"))
        username = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
            err = validate_username(username) or validate_password(pw) or (
                "The passwords don't match." if pw != pw2 else None)
            if not err and store.user_by_name(username):
                err = "This username is taken."
            if not err:
                uid = store.create_user(username, pw)
                store.update_user(uid, display_name=request.form.get("display_name", "").strip()[:40])
                log_in(store.user(uid))
                flash(f"Welcome, {username}! Add the player you want to coach.", "ok")
                return redirect(url_for("profile_new"))
            flash(err, "error")
        return render_template("auth.html", mode="signup", username=username,
                               display_name=request.form.get("display_name", ""))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/changelog")
    def changelog():
        store.set(f"seen_version:{g.user.id}", __version__)
        return render_template("changelog.html", versions=_changelog())

    @app.route("/account", methods=["GET", "POST"])
    def account():
        if request.method == "POST" and "display_name" in request.form:
            store.update_user(g.user.id, display_name=request.form["display_name"].strip()[:40])
            flash("Saved.", "ok")
            return redirect(url_for("account"))
        if request.method == "POST":
            if not store.verify_login(g.user.username, request.form.get("current", "")):
                flash("Your current password is wrong.", "error")
            else:
                pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
                err = validate_password(pw) or ("The new passwords don't match." if pw != pw2 else None)
                if err:
                    flash(err, "error")
                else:
                    session["sk"] = store.set_password(g.user.id, pw)
                    flash("Password changed. Other devices were logged out.", "ok")
            return redirect(url_for("account"))
        usage = store.usage_by_user().get(g.user.id, {"profiles": 0, "jobs": 0})
        return render_template("account.html", usage=usage, vod_root=vod_root(g.user))

    # -------------------------------------------------------------- dashboard
    @app.get("/")
    def index():
        profiles = store.profiles(g.user.id)
        names = {p.id: p.riot_id for p in profiles}
        counts = {p.id: len(store.jobs(p.id, 1000)) for p in profiles}
        teams = []
        for t in store.teams_for_user(g.user.id):
            tnames = {p.id: p.name for p in store.profiles(t.owner_id)}
            ms = [m for m in t.member_list if m["pid"] in tnames]
            teams.append({"t": t, "starters": [tnames[m["pid"]] for m in ms if m["kind"] == "starter"],
                          "subs": [tnames[m["pid"]] for m in ms if m["kind"] == "sub"],
                          "shared": t.owner_id != g.user.id,
                          "focus": app.extensions["valcoach"]["stats"].my_focus(t, g.user.id)})
        return render_template("index.html", profiles=profiles, jobs=store.jobs_for_owner(g.user.id, 20),
                               names=names, counts=counts, teams=teams)

    # --------------------------------------------------------------- profiles
    def _profile_form_values() -> dict:
        f = request.form
        return {
            "name": f.get("name", "").strip(),
            "tag": f.get("tag", "").strip().lstrip("#"),
            "region": f.get("region", "eu"),
            "platform": f.get("platform", "pc"),
            "mode": f.get("mode", "both"),
            "language": f.get("language", "English").strip() or "English",
            "playbook": f.get("playbook", "").replace("\r\n", "\n"),
        }

    def _validate_profile(v: dict) -> str | None:
        if not v["name"] or not v["tag"]:
            return "Riot name and tag are required."
        if "#" in v["name"]:
            return "Enter the name without #TAG; the tag goes in its own field."
        if v["region"] not in REGIONS or v["platform"] not in PLATFORMS or v["mode"] not in MODES:
            return "Invalid region / platform / mode."
        if v["playbook"].strip():
            import yaml
            try:
                yaml.safe_load(v["playbook"])
            except yaml.YAMLError as e:
                return f"Playbook is not valid YAML: {e}"
        return None

    @app.route("/profiles/new", methods=["GET", "POST"])
    def profile_new():
        v = {"name": "", "tag": "", "region": "eu", "platform": "pc", "mode": "both",
             "language": "English", "playbook": ""}
        if request.method == "POST":
            v = _profile_form_values()
            err = _validate_profile(v)
            if not err:
                try:
                    pid = store.create_profile(g.user.id, **v)
                    flash(f"Added {v['name']}#{v['tag']}.", "ok")
                    return redirect(url_for("profile", pid=pid))
                except sqlite3.IntegrityError:
                    err = "You already have a player with this Riot ID."
            flash(err, "error")
        return render_template("profile_form.html", v=v, profile=None, regions=REGIONS,
                               platforms=PLATFORMS, example=PLAYBOOK_EXAMPLE)

    @app.route("/profiles/<int:pid>/edit", methods=["GET", "POST"])
    def profile_edit(pid: int):
        p = get_profile(pid)
        v = {k: getattr(p, k) for k in ("name", "tag", "region", "platform", "mode", "language", "playbook")}
        if request.method == "POST":
            v = _profile_form_values()
            err = _validate_profile(v)
            if not err:
                try:
                    store.update_profile(pid, **v)
                    history_cache.clear()
                    flash("Saved.", "ok")
                    return redirect(url_for("profile", pid=pid))
                except sqlite3.IntegrityError:
                    err = "You already have a player with this Riot ID."
            flash(err, "error")
        return render_template("profile_form.html", v=v, profile=p, regions=REGIONS,
                               platforms=PLATFORMS, example=PLAYBOOK_EXAMPLE, active_pid=pid)

    @app.post("/profiles/<int:pid>/delete")
    def profile_delete(pid: int):
        p = get_profile(pid)
        if any(j.status == "running" for j in store.jobs(pid, 100_000)):
            flash(f"A report for {p.riot_id} is being made right now; delete the player when it's done.", "error")
            return redirect(url_for("profile", pid=pid))
        for j in store.jobs(pid, 100_000):
            runner.delete(j.id)
        store.delete_profile(pid)
        shutil.rmtree(store.profile_dir(pid), ignore_errors=True)
        flash(f"Deleted {p.riot_id}.", "ok")
        return redirect(url_for("index"))

    @app.post("/api/profiles/order")
    def profiles_order():
        data = request.get_json(silent=True)          # JSON only: a cross-site form can't send this
        if not isinstance(data, dict) or not isinstance(data.get("order"), list):
            return jsonify(error="expected {\"order\": [ids]}"), 400
        try:
            store.reorder_profiles(g.user.id, [int(x) for x in data["order"]])
        except (TypeError, ValueError) as e:
            return jsonify(error=str(e)), 400
        return jsonify(ok=True)

    @app.get("/profiles/<int:pid>")
    def profile(pid: int):
        p = get_profile(pid)
        queue = request.args.get("queue", "")
        source = "stored" if request.args.get("source") == "stored" else "recent"
        try:
            page = max(0 if source == "recent" else 1, int(request.args.get("page", 0 if source == "recent" else 1)))
        except ValueError:
            page = 0 if source == "recent" else 1
        key = (pid, p.name.lower(), p.tag.lower(), p.region, queue, source, page)
        rows, error, total = [], None, None
        cached = history_cache.get(key)
        if cached and not request.args.get("refresh") and time.time() - cached[0] < HISTORY_TTL_S:
            rows, total = cached[1]
        elif not store.get("henrik_api_key"):
            error = ("Add the HenrikDev API key in Settings to load matches." if g.user.is_admin
                     else "No HenrikDev API key is set yet. Ask the admin to add one in Settings.")
        else:
            try:
                cfg = store.build_config(p)
                if source == "recent":
                    rows = pipeline.history(cfg, queue=queue or None, size=HISTORY_PAGE, start=page * HISTORY_PAGE)
                else:
                    rows, total = pipeline.stored_history(cfg, queue=queue or None, page=page, size=STORED_PAGE)
                if len(history_cache) >= MAX_CACHE_ENTRIES:
                    del history_cache[min(history_cache, key=lambda k: history_cache[k][0])]
                history_cache[key] = (time.time(), (rows, total))
            except HenrikError as e:
                error = str(e)
            except requests.RequestException as e:
                error = f"Could not reach the HenrikDev API: {e}"
        page_size = HISTORY_PAGE if source == "recent" else STORED_PAGE
        has_older = len(rows) >= page_size and (total is None or page * page_size < total)
        jobs = store.jobs(pid, 100)
        latest_done = {}
        for j in jobs:
            if j.status == "done" and j.match_id not in latest_done:
                latest_done[j.match_id] = j
        notes_dir = store.profile_dir(pid) / "notes"
        noted = {f.stem for f in notes_dir.glob("*.yaml")} if notes_dir.exists() else set()
        return render_template("profile.html", p=p, rows=rows, error=error, queue=queue, queues=QUEUES,
                               jobs=jobs, latest_done=latest_done, noted=noted, active_pid=pid,
                               source=source, page=page, has_older=has_older, total=total)

    @app.get("/profiles/<int:pid>/open")
    def profile_open(pid: int):
        get_profile(pid)
        mid = request.args.get("match_id", "").strip()
        if not mid:
            return redirect(url_for("profile", pid=pid))
        if not pipeline.valid_match_id(mid):
            flash("That doesn't look like a match ID (letters, digits and dashes only).", "error")
            return redirect(url_for("profile", pid=pid))
        return redirect(url_for("coach", pid=pid, match_id=mid))

    # ---------------------------------------------------------------- uploads
    @app.errorhandler(UploadError)
    def upload_error(e: UploadError):
        return jsonify(error=str(e), received=e.received), e.status

    @app.post("/api/uploads")
    def upload_begin():
        data = request.get_json(silent=True)          # JSON only: a cross-site form can't send this
        if not isinstance(data, dict) or type(data.get("size")) is not int or data["size"] <= 0:
            raise UploadError("expected {\"name\": file name, \"size\": bytes}")
        name = str(data.get("name") or "")
        if Path(name).suffix.lower() not in VIDEO_EXT:
            raise UploadError("Unsupported video type (use mp4, mkv, mov or webm).")
        if err := job_quota_error(g.user.id):
            raise UploadError(err, 429)
        if data["size"] > float(store.get("max_upload_gb") or 20) * 1024 ** 3:
            raise UploadError(f"The upload is too big (limit {store.get('max_upload_gb')} GB, set by the admin).", 413)
        return jsonify(id=uploads.begin(g.user.id, name, data["size"]).id, chunk=CHUNK_BYTES)

    @app.put("/api/uploads/<upload_id>")
    def upload_chunk(upload_id: str):
        offset = request.args.get("offset", "")
        if not offset.isdigit():
            raise UploadError("offset missing")
        return jsonify(received=uploads.write(g.user.id, upload_id, int(offset), request.stream, request.content_length))

    # ------------------------------------------------------------------ coach
    def _load(p, match_id):
        if not pipeline.valid_match_id(match_id):
            abort(404)                         # web: match IDs only, never file paths
        cfg = store.build_config(p)
        match = pipeline.load_match(cfg, match_id)
        puuid = pipeline.focus_player(cfg, match)
        return cfg, match, puuid

    @app.route("/profiles/<int:pid>/coach/<match_id>", methods=["GET", "POST"])
    def coach(pid: int, match_id: str):
        p = get_profile(pid)
        try:
            cfg, match, puuid = _load(p, match_id)
        except (HenrikError, ValueError, requests.RequestException) as e:
            flash(str(e), "error")
            return redirect(url_for("profile", pid=pid))
        if why := pipeline.coachable(match):
            flash(why, "error")
            return redirect(url_for("profile", pid=pid))

        if request.method == "POST":
            if err := job_quota_error(g.user.id):
                flash(err, "error")
                return redirect(request.url)
            f = request.form
            mode = f.get("mode", p.mode)
            if mode not in MODES:
                mode = p.mode
            anchor_round = form_int("anchor_round", 1, 1, len(match.rounds))
            anchor_kill = form_int("anchor_kill", 1, 1, 50)
            if anchor_round is None or anchor_kill is None:
                flash(f"Anchor round must be 1-{len(match.rounds)} and anchor kill a number from 1.", "error")
                return redirect(request.url)
            anchor_time = f.get("anchor_time", "").strip()
            if anchor_time:
                try:
                    pipeline.parse_ts(anchor_time)
                except ValueError:
                    flash("Anchor time must look like 2:13.4", "error")
                    return redirect(request.url)
            choice = f.get("vod", "")
            vod_path = vod_name = ""
            uploaded = False
            if choice == "upload":
                if not f.get("upload_id"):
                    flash("Choose a video file to upload.", "error")
                    return redirect(request.url)
                dest_dir = store.upload_dir(g.user.id)
                dest_dir.mkdir(parents=True, exist_ok=True)
                try:
                    dest, vod_name = uploads.finish(g.user.id, f["upload_id"], dest_dir)
                except UploadError as e:
                    flash(str(e), "error")
                    return redirect(request.url)
                vod_path, uploaded = str(dest), True
            elif choice:
                path = resolve_vod(g.user, choice)
                if path is None:
                    flash("That recording is not in your recordings folder anymore.", "error")
                    return redirect(request.url)
                vod_path, vod_name = str(path), path.name
            opts = {
                "no_llm": bool(f.get("no_llm")),
                "no_minimap": bool(f.get("no_minimap")),
                "team_review": bool(f.get("team_review")),
                "recalibrate": bool(f.get("recalibrate")),
                "uploaded": uploaded,
                "anchor_time": anchor_time,
                "anchor_round": anchor_round,
                "anchor_kill": anchor_kill,
            }
            jid = uuid.uuid4().hex[:12]
            store.create_job(jid, pid, match.match_id, mode, vod_path, vod_name, opts,
                             map_name=match.map_name, started_at_match=match.started_at)
            runner.submit(jid)
            return redirect(url_for("job", jid=jid))

        me = match.players[puuid]
        team = me.team
        summary = {
            "map": match.map_name, "queue": match.queue, "started_at": match.started_at,
            "score": f"{match.team_rounds_won.get(team, 0)}-{match.team_rounds_won.get(match.other_team(team), 0)}",
            "agent": me.agent, "kda": f"{me.kills}/{me.deaths}/{me.assists}", "rounds": len(match.rounds),
        }
        vods, suggested = list_vods(g.user, pipeline.match_end_epoch(match))
        notes = pipeline.read_notes(cfg, match.match_id)
        return render_template("coach.html", p=p, match_id=match.match_id, s=summary, vods=vods,
                               suggested=suggested, vod_root=vod_root(g.user), notes_count=len(notes),
                               jobs=store.jobs_for_match(pid, match.match_id), active_pid=pid)

    # ------------------------------------------------------------------ notes
    @app.route("/profiles/<int:pid>/notes/<match_id>", methods=["GET", "POST"])
    def notes(pid: int, match_id: str):
        p = get_profile(pid)
        try:
            cfg, match, puuid = _load(p, match_id)
        except (HenrikError, ValueError, requests.RequestException) as e:
            flash(str(e), "error")
            return redirect(url_for("profile", pid=pid))
        if why := pipeline.coachable(match):
            flash(why, "error")
            return redirect(url_for("profile", pid=pid))
        if request.method == "POST":
            data = {int(k.split("_", 1)[1]): v for k, v in request.form.items()
                    if k.startswith("round_") and k.split("_", 1)[1].isdigit()}
            pipeline.write_notes(cfg, match, puuid, data)
            flash("Notes saved. They are used the next time you coach this match, "
                  "and as style examples for your other matches.", "ok")
            if request.form.get("then") == "coach":
                return redirect(url_for("coach", pid=pid, match_id=match_id))
            return redirect(request.url)
        team = match.team_of(puuid)
        own = match.team_rounds_won.get(team, 0)
        opp = match.team_rounds_won.get(match.other_team(team), 0)
        return render_template("notes.html", p=p, match_id=match.match_id, map=match.map_name,
                               score=f"{own}-{opp}", rounds=pipeline.notes_rounds(match, puuid),
                               existing=pipeline.read_notes(cfg, match.match_id), active_pid=pid)

    # ------------------------------------------------------------------- jobs
    @app.get("/jobs/<jid>")
    def job(jid: str):
        j = get_job(jid)
        return render_template("job.html", j=j, p=store.profile(j.profile_id), active_pid=j.profile_id)

    @app.get("/api/jobs/<jid>")
    def job_api(jid: str):
        j = get_job(jid)
        return jsonify(
            status=j.status, error=j.error, log=j.log[-12000:],
            queue_position=store.queue_position(jid) if j.status == "queued" else 0,
            report_url=url_for("job_report", jid=jid) if j.status == "done" else None,
        )

    @app.get("/jobs/<jid>/report")
    def job_report(jid: str):
        j = get_job(jid)
        path = store.resolve(j.html_path) if j.status == "done" else None
        if path is None:
            abort(404)
        return send_file(path, mimetype="text/html", max_age=0)

    @app.get("/jobs/<jid>/vod")
    def job_vod(jid: str):
        j = get_job(jid)
        path = store.resolve(j.vod_path)
        if path is None:
            abort(404)
        return send_file(path, conditional=True)   # supports Range requests (seeking)

    @app.post("/jobs/<jid>/delete")
    def job_delete(jid: str):
        j = get_job(jid)
        if j.status == "running":
            flash("This report is still being made; wait until it finishes.", "error")
            return redirect(url_for("job", jid=jid))
        runner.delete(jid)
        flash("Report deleted.", "ok")
        return redirect(url_for("profile", pid=j.profile_id))

    @app.post("/jobs/<jid>/retry")
    def job_retry(jid: str):
        j = get_job(jid)
        if j.status in ("error", "done"):
            if err := job_quota_error(g.user.id):
                flash(err, "error")
                return redirect(url_for("job", jid=jid))
            store.update_job(jid, status="queued", log="", error="", started_at="", finished_at="")
            runner.submit(jid)
        return redirect(url_for("job", jid=jid))

    # ------------------------------------------------------------ admin: users
    @app.route("/admin/users", methods=["GET", "POST"])
    @admin_required
    def users():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            pw = request.form.get("password", "")
            vod_dir = request.form.get("vod_dir", "").strip()
            err = validate_username(username) or validate_password(pw)
            if not err and store.user_by_name(username):
                err = "This username is taken."
            if not err and vod_dir and not Path(vod_dir).expanduser().is_dir():
                err = f"Recordings folder not found on this server: {vod_dir}"
            if err:
                flash(err, "error")
            else:
                uid = store.create_user(username, pw, is_admin=bool(request.form.get("is_admin")), vod_dir=vod_dir)
                store.update_user(uid, display_name=request.form.get("display_name", "").strip()[:40])
                flash(f"Created {username}. Give them the password; they can change it under Account.", "ok")
            return redirect(url_for("users"))
        return render_template("users.html", users=store.users(), usage=store.usage_by_user())

    @app.route("/admin/users/<int:uid>", methods=["GET", "POST"])
    @admin_required
    def user_edit(uid: int):
        u = store.user(uid)
        if u is None:
            abort(404)
        if request.method == "POST":
            f = request.form
            is_admin = bool(f.get("is_admin"))
            disabled = bool(f.get("disabled"))
            vod_dir = f.get("vod_dir", "").strip()
            errors = []
            if u.id == g.user.id and (not is_admin or disabled):
                errors.append("You can't remove your own admin rights or disable yourself.")
            if u.is_admin and (not is_admin or disabled) and store.admin_count() <= 1:
                errors.append("There must be at least one active admin.")
            if vod_dir and not Path(vod_dir).expanduser().is_dir():
                errors.append(f"Recordings folder not found on this server: {vod_dir}")
            new_pw = f.get("new_password", "")
            if new_pw and (e := validate_password(new_pw)):
                errors.append(e)
            for e in errors:
                flash(e, "error")
            if not errors:
                store.update_user(uid, is_admin=int(is_admin), disabled=int(disabled), vod_dir=vod_dir)
                if new_pw:
                    key = store.set_password(uid, new_pw)
                    if uid == g.user.id:
                        session["sk"] = key
                flash(f"Saved {u.username}.", "ok")
                return redirect(url_for("users"))
            return redirect(url_for("user_edit", uid=uid))
        return render_template("user_edit.html", u=u, usage=store.usage_by_user().get(uid, {}))

    @app.post("/admin/users/<int:uid>/delete")
    @admin_required
    def user_delete(uid: int):
        u = store.user(uid)
        if u is None:
            abort(404)
        if u.id == g.user.id:
            flash("You can't delete your own account.", "error")
            return redirect(url_for("user_edit", uid=uid))
        if any(j.status == "running" for p in store.profiles(uid) for j in store.jobs(p.id, 1000)):
            flash(f"{u.username} has a report being made right now; try again when it's done.", "error")
            return redirect(url_for("user_edit", uid=uid))
        delete_user_data(uid)
        flash(f"Deleted {u.username} and their whole workspace.", "ok")
        return redirect(url_for("users"))

    # --------------------------------------------------------------- settings
    @app.route("/settings", methods=["GET", "POST"])
    @admin_required
    def settings():
        if request.method == "POST":
            f = request.form
            errors = []
            if f.get("henrik_api_key", "").strip():
                store.set("henrik_api_key", f["henrik_api_key"].strip())
                history_cache.clear()
            if f.get("clear_api_key"):
                store.set("henrik_api_key", "")
            numeric = {
                "ollama_temperature": (float, 0, 2), "ollama_num_ctx": (int, 2048, 262144),
                "ollama_parallel": (int, 1, 64), "ollama_timeout_s": (int, 10, 3600),
                "sample_fps": (float, 0.5, 30), "workers": (int, 1, 8),
                "max_upload_gb": (float, 0.1, 64), "max_jobs_per_user": (int, 1, 50),
            }
            for key, (conv, lo, hi) in numeric.items():
                raw = f.get(key, "").strip()
                try:
                    val = conv(raw)
                    if not lo <= val <= hi:
                        raise ValueError
                    store.set(key, str(val))
                except ValueError:
                    errors.append(f"{key}: must be between {lo} and {hi}")
            if f.get("ollama_think", "") in ("", "off", "on"):
                store.set("ollama_think", f.get("ollama_think", ""))
            for key in ("ollama_url", "ollama_model", "henrik_base_url"):
                if f.get(key, "").strip():
                    store.set(key, f[key].strip())
            for key in ("minimap_roi", "killfeed_roi"):
                try:
                    store.set(key, ", ".join(str(v) for v in parse_roi(f.get(key, ""))))
                except ValueError as e:
                    errors.append(f"{key}: {e}")
            store.set("allow_signup", "1" if f.get("allow_signup") else "0")
            if f.get("youtube_api_key", "").strip():
                store.set("youtube_api_key", f["youtube_api_key"].strip())
            if f.get("clear_youtube_key"):
                store.set("youtube_api_key", "")
            if "pros_yaml" in f:
                from ..stats.style import DEFAULT_PROS, load_pros
                text = f.get("pros_yaml", "").replace("\r\n", "\n")
                if f.get("reset_pros") or text.strip() == DEFAULT_PROS.read_text().strip():
                    store.set("pros_yaml", "")
                else:
                    try:
                        load_pros(text)
                        store.set("pros_yaml", text)
                    except Exception as e:
                        errors.append(f"Pro players: {e}")
            for e in errors:
                flash(e, "error")
            if not errors:
                msg = "Settings saved."
                if int(store.get("workers")) != runner.workers:
                    msg += " Restart valcoach to apply the new number of parallel jobs."
                flash(msg, "ok")
            return redirect(url_for("settings"))
        models, ollama_error = ollama_models()
        s = store.settings()
        from ..stats.style import DEFAULT_PROS
        return render_template("settings.html", s=s, key_set=bool(s["henrik_api_key"]),
                               yt_hint=("…" + s["youtube_api_key"][-4:]) if s["youtube_api_key"] else "",
                               pros_text=s["pros_yaml"] or DEFAULT_PROS.read_text(), pros_custom=bool(s["pros_yaml"]),
                               key_hint=("…" + s["henrik_api_key"][-4:]) if s["henrik_api_key"] else "",
                               models=models, ollama_error=ollama_error, running_workers=runner.workers)

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, msg="You can't do this here: it's for admins or the team owner."), 403

    @app.errorhandler(413)
    def too_large(_):
        return render_template("error.html", code=413, msg="This request is too big."), 413

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, msg="Not found."), 404

    from .stats_views import register as register_stats
    register_stats(app, store, stats_runner, get_profile)
    if start_workers:
        stats_runner.start_scheduler(app.extensions["valcoach"]["weekly_job"], app.extensions["valcoach"]["nightly_job"])
    return app


def _changelog() -> list[dict]:
    """CHANGELOG.md -> [{version, items: [html]}] (a tiny Markdown subset: headings, bullets, **bold**, `code`)."""
    import html
    import re
    p = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
    if not p.exists():
        return []
    out, cur, item = [], None, None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = {"version": line[3:].strip(), "items": []}
            out.append(cur)
            item = None
        elif cur is not None and line.startswith("- "):
            item = line[2:].strip()
            cur["items"].append(item)
        elif cur is not None and line.startswith("  ") and line.strip() and cur["items"]:
            cur["items"][-1] += " " + line.strip()
    for v in out:
        v["items"] = [re.sub(r"\*([^*]+)\*", r"<i>\1</i>",
                             re.sub(r"`([^`]+)`", r"<code>\1</code>", re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", html.escape(i))))
                      for i in v["items"]]
    return out


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def serve(app: Flask, host: str = "0.0.0.0", port: int = 10070) -> None:
    shown = lan_ip() if host in ("0.0.0.0", "") else host
    from .. import __version__
    print(f"valcoach {__version__} web is running: http://{shown}:{port}  (Ctrl+C to stop)", flush=True)
    print(f"code: {Path(__file__).resolve().parent.parent}", flush=True)
    try:
        from waitress import serve as wserve
    except ImportError:
        app.run(host=host, port=port, threaded=True)
        return
    # waitress buffers bodies in the temp dir; /tmp is often a small RAM disk
    tempfile.tempdir = str(app.extensions["valcoach"]["uploads"].dir)
    wserve(app, host=host, port=port, threads=8, channel_timeout=900, max_request_body_size=MAX_REQUEST_BYTES)
