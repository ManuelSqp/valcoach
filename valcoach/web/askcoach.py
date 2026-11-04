"""Practice › Ask the coach (per player): a chat with the coach about this player, with web search when it's
set up. Each user has their own conversation per player: data/profiles/<pid>/stats/ask-u<uid>.json.
Answers are written in the background (a local model can take a minute); the page polls for them."""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from markupsafe import Markup, escape
from flask import flash, g, jsonify, redirect, render_template, request, url_for

from ..coach import askcoach as ac
from ..coach import websearch as ws

MAX_ITEMS = 60
_ex = ThreadPoolExecutor(max_workers=2, thread_name_prefix="askcoach")
_state: dict[tuple[int, int], dict] = {}            # (uid, pid) -> {"step": ..., "error": ..., "q": ...}
_lock = threading.Lock()


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {"items": []}
    except (OSError, ValueError):
        return {"items": []}


def register(app, store, sr, view_profile, filter_rows) -> None:
    from .aim import player_runs

    @app.template_filter("askfmt")
    def askfmt(text) -> Markup:
        """The coach's answer as HTML: paragraphs, line breaks and **bold**; everything else escaped."""
        out = []
        for para in re.split(r"\n{2,}", str(text or "").strip()):
            h = str(escape(para))
            h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h).replace("\n", "<br>")
            out.append(f"<p>{h}</p>")
        return Markup("".join(out))

    def path(pid: int, uid: int) -> Path:
        return store.profile_dir(pid) / "stats" / f"ask-u{int(uid)}.json"

    @app.get("/profiles/<int:pid>/ask")
    def ask_coach(pid: int):
        p, _ = view_profile(pid)
        items = _read(path(pid, g.user.id)).get("items", [])
        with _lock:
            st = dict(_state.get((g.user.id, pid)) or {})
        return render_template("ask_coach.html", p=p, active_pid=pid, items=items, pending=st if "step" in st else None,
                               search_on=bool(ws.provider(store)), search_name=ws.PROVIDERS.get(ws.provider(store), ""),
                               games=len(sr.games(pid).rows()))

    @app.post("/api/profiles/<int:pid>/ask")
    def ask_coach_post(pid: int):
        from .models import picked
        p, _ = view_profile(pid)
        uid = g.user.id
        b = request.get_json(silent=True) or {}
        q = " ".join(str(b.get("question") or "").split())[:ac.MAX_Q]
        if not q:
            return jsonify(error="Ask a question first."), 400
        key = (uid, pid)
        with _lock:
            if "step" in (_state.get(key) or {}):
                return jsonify(error="The coach is still answering your last question."), 409
            _state[key] = {"step": "Waiting for the model", "q": q, "t": time.time()}
        choice = picked(store)
        search = ws.searcher(store)

        def step(text: str) -> None:
            with _lock:
                if key in _state:
                    _state[key]["step"] = text

        def work():
            try:
                llm, _cfg = sr._llm(p, choice)
                rows = filter_rows(sr.games(pid).rows(), "everything")
                data = ac.facts(p.riot_id, rows, player_runs(sr, pid))
                f = path(pid, uid)
                hist = _read(f).get("items", [])
                out = ac.answer(llm, p.name, p.language or "English", q, hist, data, search=search, step=step)
                with _lock:
                    d = _read(f)
                    d.setdefault("items", []).append({"q": q, "a": out["answer"], "sources": out["sources"],
                                                      "searched": out["searched"], "search_errors": out["search_errors"],
                                                      "model": getattr(llm, "model", ""), "t": time.time()})
                    del d["items"][:-MAX_ITEMS]
                    f.parent.mkdir(parents=True, exist_ok=True)
                    tmp = f.with_suffix(".tmp")
                    tmp.write_text(json.dumps(d, ensure_ascii=False))
                    tmp.replace(f)
                    _state.pop(key, None)
            except Exception as e:                       # shown once under the question box
                with _lock:
                    _state[key] = {"error": str(e)[:300] or e.__class__.__name__, "q": q}
        _ex.submit(work)
        return jsonify(ok=True, pending=True)

    @app.get("/api/profiles/<int:pid>/ask")
    def ask_coach_state(pid: int):
        view_profile(pid)
        key = (g.user.id, pid)
        with _lock:
            st = dict(_state.get(key) or {})
            if "error" in st:
                _state.pop(key, None)
        items = _read(path(pid, g.user.id)).get("items", [])
        return jsonify(items=items[-MAX_ITEMS:], pending="step" in st, step=st.get("step", ""),
                       error=st.get("error", ""), q=st.get("q", ""))

    @app.post("/profiles/<int:pid>/ask/clear")
    def ask_coach_clear(pid: int):
        view_profile(pid)
        path(pid, g.user.id).unlink(missing_ok=True)
        flash("New conversation.", "ok")
        return redirect(url_for("ask_coach", pid=pid))
