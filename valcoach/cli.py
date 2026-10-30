"""valcoach command line.

  valcoach web                             start the web app (profiles, settings, reports)
  valcoach history                         list your recent matches
  valcoach coach latest --vod match.mp4    full coaching run
  valcoach coach <match_id> --no-llm       facts-only report (no Ollama)
  valcoach sync <match> <vod>              check VOD alignment
  valcoach calibrate-minimap <match> <vod> check minimap ROI / calibration
  valcoach notes-template <match>          create a notes file to annotate rounds
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
from .coach.ollama import OllamaError
from .config import Config, load_config
from .henrik import HenrikError


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _anchor(args) -> pipeline.Anchor | None:
    if getattr(args, "anchor_time", None):
        return pipeline.Anchor(args.anchor_round, args.anchor_kill, args.anchor_time)
    return None


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_history(cfg: Config, args) -> None:
    for r in pipeline.history(cfg, queue=args.queue, size=args.size):
        print(f"{r['match_id']}  {r['started_at'][:16]:16}  {r['queue']:12} {r['map']:10} "
              f"{r['score']:6} {r['agent']:10} {r['kda']}")


def cmd_coach(cfg: Config, args) -> None:
    req = pipeline.CoachRequest(
        match=args.match, vod=args.vod, mode=args.mode, player=args.player, queue=args.queue,
        no_llm=args.no_llm, no_minimap=args.no_minimap, recalibrate=args.recalibrate,
        anchor=_anchor(args), out_dir=Path(args.out) if args.out else None,
        team_review=args.team,
    )
    res = pipeline.run(cfg, req, log)
    print(res.html)


def cmd_sync(cfg: Config, args) -> None:
    match = pipeline.load_match(cfg, args.match)
    res = pipeline.do_sync(cfg, match, args.vod, _anchor(args), log)
    out = Path(args.vod).with_suffix(".sync.json")
    res.save(out)
    print(out)


def cmd_calibrate(cfg: Config, args) -> None:
    import cv2
    from .video.io import crop, frame_at, open_video, video_info, video_roi
    from .video.minimap import detect_blobs

    match = pipeline.load_match(cfg, args.match)
    puuid = pipeline.focus_player(cfg, match, args.player)
    map_info = pipeline.get_map_info(cfg, match, log)
    info = video_info(args.vod)
    mm = video_roi(cfg.video.minimap_roi, info)
    kf = video_roi(cfg.video.killfeed_roi, info)
    sync = pipeline.do_sync(cfg, match, args.vod, _anchor(args), log)
    cal = None
    if map_info and not args.frames_only:
        _, cal = pipeline.do_minimap(cfg, match, map_info, args.vod, sync, puuid,
                                     recalibrate=True, track=False, log=log)

    out_dir = cfg.path(cfg.paths.output_dir) / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    kills = [k for k in match.kills if k.player_locations][:: max(1, len(match.kills) // 6)][:6]
    team = match.team_of(puuid)
    colors = {"self": (0, 255, 255), "ally": (255, 255, 0), "enemy": (0, 0, 255)}
    with open_video(args.vod) as cap:
        for i, k in enumerate(kills):
            t = sync.vod_time(k.t_match_ms, k.round)
            frame = frame_at(cap, info.fps, t)
            if frame is None:
                continue
            cv2.rectangle(frame, (mm[0], mm[1]), (mm[0] + mm[2], mm[1] + mm[3]), (0, 200, 255), 2)
            cv2.rectangle(frame, (kf[0], kf[1]), (kf[0] + kf[2], kf[1] + kf[3]), (255, 0, 255), 2)
            for b in detect_blobs(crop(frame, mm)):
                cv2.circle(frame, (int(mm[0] + b.px), int(mm[1] + b.py)), 9, colors[b.kind], 2)
            if cal and map_info:
                for pl in k.player_locations:
                    u, v = map_info.to_uv(pl.x, pl.y)
                    px, py = cal.uv_to_px(u, v, match.rounds[k.round].side_of(team))
                    c = (0, 255, 0) if pl.team == team else (0, 0, 255)
                    cv2.drawMarker(frame, (int(mm[0] + px), int(mm[1] + py)), c, cv2.MARKER_CROSS, 14, 2)
            cv2.putText(frame, f"R{k.round + 1} kill @ {t:.1f}s  (circle=detected icon, cross=API position)",
                        (20, info.height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            p = out_dir / f"calib_{i + 1}.jpg"
            cv2.imwrite(str(p), frame)
            print(p)
    log("Orange box = minimap area, magenta box = kill-feed area. Crosses should sit on the icons.")


def cmd_notes(cfg: Config, args) -> None:
    match = pipeline.load_match(cfg, args.match)
    puuid = pipeline.focus_player(cfg, match, args.player)
    p = pipeline.notes_path(cfg, match.match_id)
    if p.exists() and not args.force:
        raise SystemExit(f"{p} exists (use --force to overwrite)")
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Notes for {match.map_name} {match.started_at[:10]} - write what actually went wrong / right.",
        "# These are shown to the coach for this match AND used as style examples for other matches.",
        "# Leave rounds empty if you have nothing to say about them.",
        f"match_id: {match.match_id}",
        f"player: {match.players[puuid].riot_id}",
        f"map: {match.map_name}",
        "rounds:",
    ]
    for r in pipeline.notes_rounds(match, puuid):
        lines.append(f"  {r['number']}: \"\"   # {r['side']} {'W' if r['won'] else 'L'} at {r['score_before']}"
                     + (f", plant {r['plant']}" if r["plant"] else ""))
    p.write_text("\n".join(lines) + "\n")
    print(p)


def cmd_web(cfg: Config, args) -> None:
    from .web import create_app, serve
    seed = Path(args.config) if Path(args.config).exists() else None
    app = create_app(Path(args.data).resolve(), config_seed=seed)
    serve(app, args.host, args.port)


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="valcoach", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.toml")
    from . import __version__
    ap.add_argument("--version", action="version", version=f"valcoach {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("web", help="start the web app")
    w.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from your LAN")
    w.add_argument("--port", type=int, default=10070)
    w.add_argument("--data", default="data", help="folder for the database, cache, uploads and reports")

    h = sub.add_parser("history", help="list recent matches")
    h.add_argument("--size", type=int, default=10)
    h.add_argument("--queue", help="competitive | premier | unrated | swiftplay ...")

    def add_anchor(p):
        p.add_argument("--anchor-round", type=int, default=1)
        p.add_argument("--anchor-kill", type=int, default=1)
        p.add_argument("--anchor-time", help="VOD time of that kill, e.g. 03:21.5 (skips auto-sync)")

    c = sub.add_parser("coach", help="analyse + coach a match")
    c.add_argument("match", help="match id, 'latest', or path to a saved v4 match .json")
    c.add_argument("--vod", help="recording of the match (mp4/mkv)")
    c.add_argument("--mode", choices=["team", "player", "both"])
    c.add_argument("--player", help="Name#TAG to coach (default: config player)")
    c.add_argument("--queue", help="queue filter when using 'latest'")
    c.add_argument("--no-llm", action="store_true", help="facts-only report, no Ollama")
    c.add_argument("--no-minimap", action="store_true")
    c.add_argument("--team", action="store_true", help="also review every player of your team")
    c.add_argument("--recalibrate", action="store_true", help="ignore cached minimap calibration")
    c.add_argument("--out", help="output directory")
    add_anchor(c)

    s = sub.add_parser("sync", help="align a VOD to the match timeline")
    s.add_argument("match")
    s.add_argument("vod")
    add_anchor(s)

    k = sub.add_parser("calibrate-minimap", help="debug frames for minimap / kill-feed areas")
    k.add_argument("match")
    k.add_argument("vod")
    k.add_argument("--player")
    k.add_argument("--frames-only", action="store_true", help="only draw areas + detections")
    add_anchor(k)

    n = sub.add_parser("notes-template", help="create a notes file for a match")
    n.add_argument("match")
    n.add_argument("--player")
    n.add_argument("--force", action="store_true")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    try:
        {"web": cmd_web, "history": cmd_history, "coach": cmd_coach, "sync": cmd_sync,
         "calibrate-minimap": cmd_calibrate, "notes-template": cmd_notes}[args.cmd](cfg, args)
    except HenrikError as e:
        raise SystemExit(f"HenrikDev API: {e}")
    except OllamaError as e:
        raise SystemExit(f"Ollama: {e}")
    except ValueError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
