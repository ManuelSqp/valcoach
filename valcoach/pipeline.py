"""Shared pipeline used by the CLI and the web app.

Everything here takes an explicit Config and a `log` callable, so several
coaching runs for different players can execute side by side.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from .config import Config
from .henrik import HenrikClient, HenrikError, load_match_file
from .maps import MapInfo, MapRegistry
from .models import Match
from .parse import parse_match

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------------------
# match data
# ---------------------------------------------------------------------------
MATCH_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")
# modes with rounds, sides and an economy; deathmatch / TDM / Gauntlet have none of these
COACHABLE_MODE_TYPES = {"standard", "swiftplay", "spike rush"}
# queue ids / names (history lists have no mode_type) that are never coachable
NON_ROUND_QUEUES = {"deathmatch", "team deathmatch", "teamdeathmatch", "hurm", "abilitydraftarena"}


def valid_match_id(ref: str) -> bool:
    return bool(MATCH_ID_RE.fullmatch(ref))


def coachable(match: Match) -> str | None:
    """None if the match can be coached, else the reason why not."""
    mt = (match.mode_type or "").lower()
    if (mt and mt not in COACHABLE_MODE_TYPES) or match.queue.lower() in NON_ROUND_QUEUES or len(match.rounds) < 2:
        return (f"{match.mode_type or match.queue or 'This mode'} can't be coached: "
                "the coach needs a round-based mode (Competitive, Premier, Unrated, Swiftplay, Custom).")
    return None


def get_client(cfg: Config) -> HenrikClient:
    return HenrikClient(cfg.henrik.api_key, cfg.path(cfg.paths.cache_dir), cfg.henrik.base_url)


def load_match(cfg: Config, ref: str, queue: str | None = None) -> Match:
    """`ref` = match id, 'latest', or a path to a saved v4 match .json."""
    p = Path(ref)
    if p.suffix == ".json" and p.exists():
        return parse_match(load_match_file(p))
    if ref != "latest" and not valid_match_id(ref):
        raise ValueError(f"Not a valid match ID: {ref!r}")
    cached = cfg.path(cfg.paths.cache_dir) / "matches" / f"{ref}.json"
    if cached.exists():
        return parse_match(json.loads(cached.read_text()))
    client = get_client(cfg)
    if ref == "latest":
        hist = client.match_history(cfg.player.region, cfg.player.platform, cfg.player.name,
                                    cfg.player.tag, mode=queue, size=1)
        if not hist:
            raise HenrikError("No matches found for this player")
        return parse_match({"data": hist[0]})
    return parse_match(client.match(cfg.player.region, ref))


def history(cfg: Config, queue: str | None = None, size: int = 10, start: int = 0) -> list[dict]:
    """Recent matches of the configured player as display rows."""
    client = get_client(cfg)
    rows = []
    for raw in client.match_history(cfg.player.region, cfg.player.platform, cfg.player.name,
                                    cfg.player.tag, mode=queue, size=size, start=start):
        m = parse_match({"data": raw})
        me = m.find_player(cfg.player.name, cfg.player.tag)
        team = me.team if me else ""
        own = m.team_rounds_won.get(team, 0)
        opp = m.team_rounds_won.get(m.other_team(team), 0)
        rows.append({
            "match_id": m.match_id,
            "started_at": m.started_at,
            "queue": m.queue,
            "map": m.map_name,
            "score": f"{own}-{opp}",
            "result": "W" if own > opp else ("L" if own < opp else "D"),
            "agent": me.agent if me else "?",
            "kda": f"{me.kills}/{me.deaths}/{me.assists}" if me else "",
            "rounds": len(m.rounds),
            "coachable": coachable(m) is None,
        })
    return rows


def stored_history(cfg: Config, queue: str | None = None, page: int = 1,
                   size: int = 20) -> tuple[list[dict], int]:
    """Older matches from HenrikDev's stored archive, as display rows + total count."""
    client = get_client(cfg)
    items, results = client.stored_matches(cfg.player.region, cfg.player.name, cfg.player.tag,
                                           mode=queue, page=page, size=size)
    rows = []
    for it in items:
        meta, st, teams = it.get("meta", {}) or {}, it.get("stats", {}) or {}, it.get("teams", {}) or {}
        team = (st.get("team") or "").lower()
        own = teams.get(team)
        opp = teams.get("blue" if team == "red" else "red")
        result = "?"
        if isinstance(own, int) and isinstance(opp, int):
            result = "W" if own > opp else ("L" if own < opp else "D")
        rows.append({
            "match_id": meta.get("id", ""),
            "started_at": meta.get("started_at", ""),
            "queue": (meta.get("mode") or "").lower(),
            "map": (meta.get("map") or {}).get("name", "?"),
            "score": f"{own}-{opp}" if own is not None and opp is not None else "?",
            "result": result,
            "agent": (st.get("character") or {}).get("name", "?"),
            "kda": f"{st.get('kills', 0)}/{st.get('deaths', 0)}/{st.get('assists', 0)}",
            "rounds": (own or 0) + (opp or 0),
            "coachable": (meta.get("mode") or "").lower() not in NON_ROUND_QUEUES,
        })
    return rows, int(results.get("total") or 0)


def get_map_info(cfg: Config, match: Match, log: Log = _noop) -> MapInfo | None:
    reg = MapRegistry(cfg.path(cfg.paths.cache_dir))
    try:
        info = reg.get(match.map_id, match.map_name)
        if info is None:
            log(f"! Map '{match.map_name}' not in valorant-api.com data; callouts disabled")
        return info
    except Exception as e:  # network down etc. - analysis still works without callouts
        log(f"! Could not load map data from valorant-api.com ({e}); callouts disabled")
        return None


def focus_player(cfg: Config, match: Match, override: str | None = None) -> str:
    name, tag = cfg.player.name, cfg.player.tag
    if override:
        name, _, tag = override.partition("#")
        tag = tag or None
    p = match.find_player(name, tag)
    if p is None:
        names = ", ".join(pp.riot_id for pp in match.players.values())
        raise ValueError(f"Player {name}#{tag} is not in this match. Players: {names}")
    return p.puuid


def match_end_epoch(match: Match) -> float | None:
    """Unix time the match ended (used to find the matching recording)."""
    from datetime import datetime
    if not match.started_at:
        return None
    try:
        start = datetime.fromisoformat(match.started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return start.timestamp() + match.game_length_ms / 1000


# ---------------------------------------------------------------------------
# video
# ---------------------------------------------------------------------------
@dataclass
class Anchor:
    round: int = 1
    kill: int = 1
    time: str | None = None      # VOD time of that kill, e.g. "2:13.4"


def parse_ts(s: str) -> float:
    """'1:02:03.5' | '12:34' | '754.2' -> seconds"""
    out = 0.0
    for x in s.strip().split(":"):
        out = out * 60 + float(x)
    return out


def calib_path(cfg: Config, map_uuid: str, width: int, height: int,
               content: tuple[int, int, int, int] | None = None) -> Path:
    # the game picture's place in the frame (black bars) is part of the key: same size, other layout
    key = cfg.video.minimap_roi if content is None or content == (0, 0, width, height) else [cfg.video.minimap_roi, list(content)]
    h = hashlib.sha1(json.dumps(key).encode()).hexdigest()[:8]
    return cfg.path(cfg.paths.cache_dir) / "minimap_calib" / f"{map_uuid}_{width}x{height}_{h}.json"


def do_sync(cfg: Config, match: Match, vod: str, anchor: Anchor | None = None, log: Log = _noop):
    from .video.sync import sync_from_anchor, sync_vod
    if anchor and anchor.time:
        res = sync_from_anchor(match, vod, anchor.round, anchor.kill, parse_ts(anchor.time),
                               cfg.video.killfeed_roi)
    else:
        log("· Detecting kill-feed events in the VOD ...")
        res = sync_vod(match, vod, cfg.video.killfeed_roi,
                       progress=lambda t, T: log(f"  scanned {t / 60:5.1f}/{T / 60:.1f} min"))
    log(f"· Sync: offset {res.global_offset_s:.2f} s, {res.matched_kills}/{res.total_kills} kills matched "
        f"({res.confidence:.0%}), {len(res.per_round_offset_s)} rounds refined")
    if res.method == "auto" and res.confidence < 0.4:
        log("! Low sync confidence. Check the kill-feed area (calibrate-minimap), "
            "or give a manual anchor (VOD time of one kill).")
    return res


def do_minimap(cfg: Config, match: Match, map_info: MapInfo, vod: str, sync, puuid: str,
               recalibrate: bool = False, track: bool = True,
               log: Log = _noop, paths: dict | None = None,
               others: dict | None = None) -> tuple[dict[int, dict], object | None]:
    from .video.allies import ally_paths, coverage, enemy_sightings
    from .video.io import video_info, video_roi
    from .video.minimap import (Calibration, calibrate, collect_calibration_samples,
                                describe_track, track_round)
    info = video_info(vod)
    cp = calib_path(cfg, map_info.uuid, info.width, info.height, info.content)
    if info.content != (0, 0, info.width, info.height):
        x, y, w, h = info.content
        log(f"· Video {info.width}x{info.height}: game picture is {w}x{h} at x={x}, y={y} (black bars left out)")
    if cp.exists() and not recalibrate:
        cal = Calibration.load(cp)
        log(f"· Using cached minimap calibration ({cp.name}, rms {cal.rms_px:.1f}px)")
    else:
        log("· Calibrating minimap from kill snapshots ...")
        samples = collect_calibration_samples(match, map_info, vod, sync, cfg.video.minimap_roi, puuid)
        roi = video_roi(cfg.video.minimap_roi, info)
        try:
            cal = calibrate(samples, (roi[2], roi[3]), map_info.uuid)
        except RuntimeError as e:
            log(f"! {e}. Skipping minimap tracking.")
            return {}, None
        cal.roi_frac, cal.frame_size = list(cfg.video.minimap_roi), [info.width, info.height]
        turn = f" (+180 deg when you're on {cal.flip_side}: map orientation based on side)" if cal.flip_side else ""
        log(f"· Calibration: rot {cal.rot_k * 90} deg{turn}, scale {cal.scale:.1f}px, rms {cal.rms_px:.1f}px "
            f"from {cal.n_points} points")
        if cal.rms_px > 0.03 * cal.scale:
            log("! Calibration error is high; minimap positions may be unreliable "
                "(check Minimap settings: rotate = Fixed, keep player centered OFF).")
        cal.save(cp)
    if not track:
        return {}, cal
    from .coach.replay import nav_grid
    nav = nav_grid(map_info, MapRegistry(cfg.path(cfg.paths.cache_dir)))
    floor = nav.near_floor if nav else None          # drops HUD marks and map lines next to the map
    out = {}
    for r in match.rounds:
        tr = track_round(match, r.index, map_info, cal, vod, sync, cfg.video.minimap_roi,
                         sample_fps=cfg.video.sample_fps, side=r.side_of(match.team_of(puuid)),
                         focus=puuid, floor=floor)
        d = describe_track(tr)
        if d:
            out[r.index] = d
        if paths is not None:
            # your own icon, 2 points per second, for the replay map
            pts, last_bucket = [], None
            for p in sorted((p for p in tr.points if p.kind == "self"), key=lambda p: p.t_round_s):
                b = int(p.t_round_s * 2)
                if b != last_bucket:
                    pts.append((p.t_round_s, p.x, p.y))
                    last_bucket = b
            if pts:
                paths[r.index] = pts
        extra = ""
        if others is not None:
            try:
                allies = ally_paths(match, r.index, tr, puuid)
                others[r.index] = {"allies": allies, "enemies": enemy_sightings(tr)}
                extra = f", teammates tracked {coverage(allies, match, r.index, puuid):.0%} of the time"
            except Exception as e:          # never let this break the run: the replay falls back to estimates
                extra = f", teammate tracking failed ({e})"
        log(f"  minimap round {r.number}/{len(match.rounds)}: {len(tr.points)} detections{extra}")
    return out, cal


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------
def notes_rounds(match: Match, puuid: str) -> list[dict]:
    """Round list with context, for the notes editor / template."""
    team = match.team_of(puuid)
    rows = []
    for r in match.rounds:
        own, opp = match.score_before(r.index, team)
        rows.append({
            "number": r.number,
            "side": r.side_of(team),
            "won": r.winning_team == team,
            "score_before": f"{own}-{opp}",
            "plant": r.plant.site if r.plant else None,
            "result": r.result,
        })
    return rows


def notes_path(cfg: Config, match_id: str) -> Path:
    return cfg.path(cfg.coach.notes_dir) / f"{match_id}.yaml"


def read_notes(cfg: Config, match_id: str) -> dict[int, str]:
    p = notes_path(cfg, match_id)
    if not p.exists():
        return {}
    try:
        d = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {}
    return note_rounds(d)


def note_rounds(doc) -> dict[int, str]:
    """{round number: note} from a notes YAML doc; ignores entries a hand edit broke."""
    rounds = doc.get("rounds") if isinstance(doc, dict) else None
    if not isinstance(rounds, dict):
        return {}
    return {int(k): str(v) for k, v in rounds.items() if v and str(k).strip().isdigit()}


def write_notes(cfg: Config, match: Match, puuid: str, notes: dict[int, str]) -> Path:
    p = notes_path(cfg, match.match_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = {int(k): v.strip() for k, v in notes.items() if v and v.strip()}
    doc = {"match_id": match.match_id, "player": match.players[puuid].riot_id,
           "map": match.map_name, "rounds": clean}
    p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120))
    return p


# ---------------------------------------------------------------------------
# full coaching run
# ---------------------------------------------------------------------------
@dataclass
class CoachRequest:
    match: str
    vod: str | None = None
    mode: str | None = None
    player: str | None = None          # Name#TAG override
    queue: str | None = None           # only used with match='latest'
    no_llm: bool = False
    no_minimap: bool = False
    recalibrate: bool = False
    anchor: Anchor | None = None
    out_dir: Path | None = None
    vod_url: str | None = None         # how the report references the VOD (web app)
    team_review: bool = False          # review every player of your team, not only you
    team_roles: dict | None = None     # 'name#tag' lower -> assigned team roles


@dataclass
class CoachResult:
    html: Path
    json: Path
    match_id: str
    map_name: str
    score: str
    started_at: str


def run(cfg: Config, req: CoachRequest, log: Log = _noop) -> CoachResult:
    from .coach.engine import analyse, run_coach
    from .coach.ollama import Ollama, OllamaError
    from .report import render_report

    match = load_match(cfg, req.match, req.queue)
    if why := coachable(match):
        raise ValueError(why)
    puuid = focus_player(cfg, match, req.player)
    map_info = get_map_info(cfg, match, log)
    mode = req.mode or cfg.coach.mode
    me = match.players[puuid]
    log(f"· {match.map_name} · {len(match.rounds)} rounds · {me.riot_id} ({me.agent}) · mode {mode}")

    an = analyse(match, puuid, map_info)

    sync = None
    if req.vod:
        sync = do_sync(cfg, match, req.vod, req.anchor, log)
        if map_info and not req.no_minimap:
            an.minimap, _ = do_minimap(cfg, match, map_info, req.vod, sync, puuid, req.recalibrate, log=log,
                                       paths=an.self_paths, others=an.vod_others)

    from .coach.replay import nav_grid
    an.nav = nav_grid(map_info, MapRegistry(cfg.path(cfg.paths.cache_dir)))
    log("· Replay: movement between kills estimated along walkable routes" if an.nav
        else "· Replay: no map image for routes; movement between kills drawn as straight lines")

    llm = None
    if not req.no_llm:
        llm = Ollama(cfg.ollama.url, cfg.ollama.model, cfg.ollama.temperature, cfg.ollama.num_ctx,
                     cfg.ollama.timeout_s, cfg.ollama.think)
        llm.check()
        log(f"· Coaching with {cfg.ollama.model} ({cfg.ollama.parallel} parallel, "
            f"reasoning {cfg.ollama.think or 'model default'}) ...")

    report = run_coach(
        an, llm, mode=mode, language=cfg.coach.language,
        playbook_path=cfg.path(cfg.coach.playbook) if cfg.coach.playbook else None,
        notes_dir=cfg.path(cfg.coach.notes_dir),
        parallel=cfg.ollama.parallel, sync=sync,
        progress=lambda n, N: log(f"  coached round {n}/{N}"),
    )
    failed = report.meta["llm_failed_rounds"]
    if failed:
        if len(failed) == len(report.rounds):
            raise OllamaError(f"The model failed on all {len(failed)} rounds, so no report was made: "
                              f"{report.rounds[0]['feedback']['error']}")
        log(f"! The model failed on {len(failed)} of {len(report.rounds)} rounds (R{', R'.join(map(str, failed))}). "
            "They show facts only; use Run again to retry.")
    if req.team_review:
        from .coach.teamreview import review
        log("· Reviewing every player of your team ...")
        report.team_review = review(match, an.team, map_info, None if report.meta["llm_gave_up"] else llm,
                                    cfg.coach.language, req.team_roles,
                                    parallel=cfg.ollama.parallel,
                                    progress=lambda n, N: log(f"  reviewed player {n}/{N}"))
    from .coach.replay import agent_icons, map_meta
    from .maps import AgentRegistry
    report.map = map_meta(map_info, MapRegistry(cfg.path(cfg.paths.cache_dir)))
    report.agents = agent_icons(match, AgentRegistry(cfg.path(cfg.paths.cache_dir)))
    if not match.has_utility:
        log("· This match's data has no per-round ability casts; round coaching leaves utility out "
            "(match totals are still used)")
    if an.view.ok:
        log(f"· View directions calibrated (killers face victims within {an.view.median_error_deg:.0f} deg median)")
    else:
        log("· View directions not usable for this match; duel analysis uses positions and damage only")
    if llm is not None:
        st = llm.summary()
        if st:
            report.meta["llm_stats"] = st
            log(f"· Model speed: {st['avg_s_per_request']} s per request · "
                f"generation {st['gen_tok_per_s'] or '?'} tok/s · prompt {st['prompt_tok_per_s'] or '?'} tok/s · "
                f"{st['avg_gen_tokens']} tokens per answer ({st['requests']} requests)")
            if st["thinking"] and cfg.ollama.think != "on":
                log("! The model produced reasoning ('thinking') although Reasoning is not 'On'. "
                    "That costs time. Set Reasoning to 'Off', or use a model whose template supports it.")
    out_dir = Path(req.out_dir) if req.out_dir else cfg.path(cfg.paths.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{match.started_at[:10] or 'match'}_{match.map_name}_{match.match_id[:8]}"
    jp = out_dir / f"{stem}.json"
    report.save(jp)
    hp = render_report(json.loads(jp.read_text()), out_dir / f"{stem}.html", req.vod, vod_url=req.vod_url)
    log(f"✓ Report ready: {hp.name}")
    team = match.team_of(puuid)
    score = f"{match.team_rounds_won.get(team, 0)}-{match.team_rounds_won.get(match.other_team(team), 0)}"
    return CoachResult(html=hp, json=jp, match_id=match.match_id, map_name=match.map_name,
                       score=score, started_at=match.started_at)
