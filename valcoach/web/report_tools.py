"""Things you can do in a coaching report opened from valcoach:

* Ask the coach about a round: the model gets that round's facts and its own feedback, answers in a
  few sentences, and the question + answer stay with the report (data/reports/<job>/ask.json). Runs in
  the background (local models can take a minute), the page polls for the answer.
* Clips: a short MP4 around a moment of the round (the report's VOD jump times), cut with ffmpeg and
  cached; download it or post it to the team's Discord. Needs ffmpeg on the server.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import abort, g, jsonify, request, send_file

from ..coach.prompts import field_guide

ASK_SYSTEM = """You are the Valorant coach who wrote this match report. The player asks a question about one
round. Answer it in {language}, in 2-6 sentences, like a coach talking to the player:
- Use only the round facts and your earlier feedback below. If the facts don't say (e.g. what an enemy was
  doing where nobody saw them), say that you can't tell from the data and what the player could check in
  the VOD.
- Be concrete: places by their callout names, times, who was alive, what to do instead.
- Don't repeat the whole feedback; answer the question."""
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "description": "the answer, 2-6 sentences"}},
          "required": ["answer"]}
SCHEMA_SOURCES = {"type": "object", "properties": {
    "answer": {"type": "string", "description": "the answer, 2-6 sentences"},
    "sources": {"type": "array", "items": {"type": "integer"}, "description": "numbers of the web results used, [] if none"}},
    "required": ["answer", "sources"]}
ASK_WEB = """
- For facts about the game itself (abilities, costs, patch changes, lineups) you may also use the web results."""
MAX_Q = 400
CLIP_MAX_MB = 9.5            # Discord webhooks take ~10 MB without a boosted server
_ex = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ask")
_pending: dict[tuple[str, int], str] = {}          # (job, round) -> "" running | error text
_lock = threading.Lock()


def ask_path(report_json: Path) -> Path:
    return Path(report_json).parent / "ask.json"


def read_asks(report_json: Path) -> dict:
    try:
        return json.loads(ask_path(report_json).read_text())
    except (OSError, ValueError):
        return {"rounds": {}}


def answer(llm, report: dict, rnd: int, question: str, history: list[dict], language: str, search=None) -> dict:
    """-> {answer, sources: [{title, url}]}. With search (Settings › Web search) the model may look things up first."""
    from ..coach import websearch as ws
    import yaml
    r = next((x for x in report.get("rounds", []) if int(x.get("number", 0)) == rnd), None)
    if r is None:
        raise ValueError("no such round")
    meta = report.get("meta", {})
    fb = {k: v for k, v in (r.get("feedback") or {}).items() if k not in ("error",)}
    doc = {"match": {"map": meta.get("map"), "player": meta.get("player"), "agent": meta.get("agent"), "score": meta.get("score")},
           "round": rnd, "round_facts": r.get("llm_input") or "", "your_feedback_for_this_round": fb,
           "own_note_of_the_player": r.get("own_note") or None,
           "earlier_questions_about_this_round": [{"q": h["q"], "a": h["a"]} for h in history[-4:]] or None}
    user = "Report data (YAML):\n" + yaml.safe_dump({k: v for k, v in doc.items() if v is not None}, sort_keys=False,
                                                    allow_unicode=True, width=120) + f"\nQuestion: {question}"
    sources: list[dict] = []
    if search is not None:
        brief = f"Map {meta.get('map')}, agent {meta.get('agent')}, round {rnd}:\n{str(r.get('llm_input') or '')[:1500]}"
        queries = ws.queries_for(llm, question, brief, n=2)
        if queries:
            sources, _ = ws.research(search, queries, read=2)
    schema = SCHEMA_SOURCES if sources else SCHEMA
    system = ASK_SYSTEM.format(language=language) + (ASK_WEB + ws.SOURCES_RULES if sources else "") + field_guide(schema)
    out = llm.chat_json(system, user + ws.sources_block(sources), schema)
    return {"answer": str(out.get("answer") or "").strip()[:2000], "sources": ws.cited(sources, out.get("sources"))}


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def make_clip(vod: Path, out: Path, start: float, length: float) -> Path:
    """MP4 (H.264 720p + AAC) of `length` seconds from `start`. Cached."""
    if out.exists() and out.stat().st_size > 0:
        return out
    exe = ffmpeg()
    if not exe:
        raise RuntimeError("ffmpeg isn't installed on the server (sudo apt install ffmpeg)")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")
    cmd = [exe, "-y", "-loglevel", "error", "-ss", f"{max(0.0, start):.2f}", "-i", str(vod), "-t", f"{length:.2f}",
           "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(tmp)]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("cutting the clip took too long") from None
    if p.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg couldn't cut the clip: " + (p.stderr.decode(errors="replace")[-300:] or "no output"))
    tmp.replace(out)
    return out


def register(app, store, get_job, llm_for, discord_url_for):
    """llm_for(profile, choice) -> llm (checked); discord_url_for(job) -> webhook URL or ""."""

    def report_of(j) -> tuple[dict, Path]:
        jp = store.resolve(j.json_path) if j.status == "done" else None
        if jp is None:
            abort(404)
        try:
            return json.loads(jp.read_text()), jp
        except (OSError, ValueError):
            abort(404)

    @app.post("/api/jobs/<jid>/ask")
    def job_ask(jid: str):
        from .models import picked
        j = get_job(jid)
        report, jp = report_of(j)
        b = request.get_json(silent=True) or {}
        rnd, q = b.get("round"), str(b.get("question") or "").strip()[:MAX_Q]
        if not isinstance(rnd, int) or isinstance(rnd, bool) or not q:
            return jsonify(error="ask a question about a round"), 400
        if not any(int(x.get("number", 0)) == rnd for x in report.get("rounds", [])):
            return jsonify(error="no such round"), 400
        key = (jid, rnd)
        with _lock:
            if _pending.get(key) == "":
                return jsonify(error="the coach is still answering the last question"), 409
            _pending[key] = ""
        profile = store.profile(j.profile_id)
        choice = picked(store)

        def work():
            try:
                llm = llm_for(profile, choice)
                hist = read_asks(jp).get("rounds", {}).get(str(rnd), [])
                from ..coach.websearch import searcher
                res = answer(llm, report, rnd, q, hist, profile.language if profile else "English", search=searcher(store))
                if not res["answer"]:
                    raise RuntimeError("the model gave no answer")
                with _lock:
                    d = read_asks(jp)
                    d.setdefault("rounds", {}).setdefault(str(rnd), []).append(
                        {"q": q, "a": res["answer"], "sources": res["sources"], "model": getattr(llm, "model", ""), "t": time.time()})
                    tmp = ask_path(jp).with_suffix(".tmp")
                    tmp.write_text(json.dumps(d, ensure_ascii=False))
                    tmp.replace(ask_path(jp))
                    _pending.pop(key, None)
            except Exception as e:                     # shown under the question box
                with _lock:
                    _pending[key] = str(e)[:300] or e.__class__.__name__
        _ex.submit(work)
        return jsonify(ok=True, pending=True)

    @app.get("/api/jobs/<jid>/ask")
    def job_asks(jid: str):
        j = get_job(jid)
        _, jp = report_of(j)
        rnd = request.args.get("round", type=int)
        d = read_asks(jp).get("rounds", {})
        with _lock:
            state = _pending.get((jid, rnd)) if rnd is not None else None
            if state:                                  # an error is shown once
                _pending.pop((jid, rnd), None)
        items = d.get(str(rnd), []) if rnd is not None else d
        return jsonify(items=items, pending=state == "", error=state or "")

    def clip_args() -> tuple[float, float]:
        try:
            t = float(request.values.get("t", ""))
            n = float(request.values.get("len", 15))
        except ValueError:
            abort(400)
        if not (0 <= t <= 6 * 3600) or not (3 <= n <= 30):
            abort(400)
        return t, n

    def clip_for(j, t: float, n: float) -> Path:
        vod = store.resolve(j.vod_path) if j.vod_path else None
        if vod is None:
            abort(404)
        out = Path(store.resolve(j.json_path)).parent / "clips" / f"{t:.1f}_{n:.0f}.mp4"
        return make_clip(vod, out, t, n)

    @app.get("/jobs/<jid>/clip")
    def job_clip(jid: str):
        j = get_job(jid)
        t, n = clip_args()
        try:
            f = clip_for(j, t, n)
        except RuntimeError as e:
            return jsonify(error=str(e)), 500
        name = re.sub(r"[^A-Za-z0-9]+", "-", f"{j.map or 'match'}-{int(t // 60)}m{int(t % 60):02d}s").strip("-")
        return send_file(f, mimetype="video/mp4", as_attachment=bool(request.args.get("dl")), download_name=f"{name}.mp4")

    @app.post("/jobs/<jid>/clip/discord")
    def job_clip_discord(jid: str):
        from ..discord import post_file
        j = get_job(jid)
        t, n = clip_args()
        url = discord_url_for(j)
        if not url:
            return jsonify(error="none of your teams with this player has a Discord webhook"), 400
        try:
            f = clip_for(j, t, n)
            if f.stat().st_size > CLIP_MAX_MB * 1024 * 1024:
                return jsonify(error=f"the clip is {f.stat().st_size / 1048576:.1f} MB, Discord takes about 10"), 400
            label = str(request.values.get("label") or "")[:80]
            post_file(url, f"🎬 {j.map or ''} {label}".strip(), f"{j.map or 'clip'}.mp4", f.read_bytes(), content_type="video/mp4")
        except RuntimeError as e:
            return jsonify(error=str(e)), 500
        except Exception as e:
            return jsonify(error=f"Discord: {e}"), 502
        return jsonify(ok=True)

    def boot(j) -> dict:
        """What the report page's script needs (added to the served report)."""
        from .models import choices, last_choice
        return {"ask_url": f"/api/jobs/{j.id}/ask", "clip_url": f"/jobs/{j.id}/clip" if j.vod_path and ffmpeg() else "",
                "discord_url": f"/jobs/{j.id}/clip/discord" if j.vod_path and ffmpeg() and discord_url_for(j) else "",
                "llm": [{"value": c["value"], "label": c["label"]} for c in choices(store, g.user)], "llm_last": last_choice(g.user)}
    return boot
