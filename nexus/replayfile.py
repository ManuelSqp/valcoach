"""Positions from VALORANT's own replay files (.vrf), read with vrfkit (4.9).

Since patch 11.06 the game can download a replay of a Competitive or Premier match from the match
history. It is saved as <match id>.vrf in %LOCALAPPDATA%\\VALORANT\\Saved\\Demos and holds what the
server sent: every player's position about 128 times a second, where they looked, and the server's
own timeline (round starts, deaths, plant, defuse). Nexus runs vrfkit
(https://github.com/yakisoba0728/vrfkit, Apache-2.0) to turn the file into tables, keeps a compact
copy (4 samples per second per player, data/replays/<match id>.json.gz) and lines it up with the
HenrikDev match data by the kills: each kill is in both, so the time offset of every round is known.

That gives all ten players for the whole round, not only what your own minimap showed, and it
needs no recording. The VOD minimap tracking is still there: Settings › Replay files › Positions
switches back to it, and it is used when a match has no replay file.

Limits: a replay file only exists if someone downloaded it in the game, only for Competitive and
Premier, and the game deletes them when the next patch arrives. vrfkit supports the builds listed in
its README; a newer build may fail to read until vrfkit is updated.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import re
import shutil
import statistics
import subprocess
import uuid
from pathlib import Path

from .maps import MapInfo
from .models import Match

FORMAT = 1                     # version of the compact json.gz
SAMPLE_MS = 250                # kept per player: one position every 250 ms
OUT_HZ = 2.0                   # paths handed to the analysis and the report replay
EXPORT_TIMEOUT_S = 600
MIN_MATCHED_SHARE = 0.6        # share of the API's kills that must be found in the replay
MAX_ROUND_S = 101.0            # round timer (100 s) plus a little
SPIKE_S = 46.0                 # fuse (45 s) plus a little
POST_ROUND_MS = 6000           # the next round's start comes after the end-of-round pause
PARKED = 40000.0               # dead/hidden characters are parked at about -50000 world units
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ID_RE = re.compile(r"[a-z0-9-]{1,64}")      # a match id as everywhere in Nexus (pipeline.MATCH_ID_RE), lower case
MAX_VRF_BYTES = 512 * 1024 ** 2
# 4.16: ability casts. vrfkit types Comp_AbilityStatisticsReplicator.AbilityCastsThisRound[] (docs/DATA.md,
# "Ability cast observations"): one array element per cast, re-sent with every later replication of the array.
CAST_GROUP = "Comp_AbilityStatisticsReplicator"
CAST_FIELD_RE = re.compile(r"AbilityCastsThisRound\[(\d{1,4})\]\.(Player|Slot|Round|CastTime)_\d{1,4}_[0-9A-Fa-f]{32}")
log_ = logging.getLogger(__name__)


class ReplayError(Exception):
    pass


# ---------------------------------------------------------------------------
# vrfkit
# ---------------------------------------------------------------------------
def vrfkit_path(setting: str = "") -> str:
    """The vrfkit program: the setting, else $NEXUS_VRFKIT, else `vrfkit` on the PATH or in ~/.cargo/bin."""
    for cand in (setting.strip(), os.environ.get("NEXUS_VRFKIT", "").strip()):
        if cand:
            return cand
    found = shutil.which("vrfkit")
    if found:
        return found
    cargo = Path.home() / ".cargo" / "bin" / ("vrfkit.exe" if os.name == "nt" else "vrfkit")
    return str(cargo) if cargo.is_file() else "vrfkit"


def check_vrfkit(path: str) -> str | None:
    """None if vrfkit can be run, else why not."""
    try:
        r = subprocess.run([path], capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return f"vrfkit was not found ({path}). Install it (see the README, section Replay files) or set its path."
    except (OSError, subprocess.TimeoutExpired) as e:
        # the details only go to the server log, never to the browser
        log_.warning("vrfkit %s can't be run: %s", path, e)
        return f"vrfkit can't be run ({path}): check the path and that the server's user may run it."
    if "vrfkit" not in (r.stdout + r.stderr).lower():
        return f"{path} doesn't look like vrfkit."
    return None


def export(vrfkit: str, vrf: Path, out_dir: Path) -> Path:
    """vrfkit export <vrf> --out <out_dir> (out_dir must not exist yet)."""
    try:
        r = subprocess.run([vrfkit, "export", str(vrf), "--out", str(out_dir)], capture_output=True, text=True,
                           timeout=EXPORT_TIMEOUT_S)
    except FileNotFoundError:
        raise ReplayError(f"vrfkit was not found ({vrfkit}). An admin installs it, see Settings › Replay files.")
    except subprocess.TimeoutExpired:
        raise ReplayError("vrfkit took too long to read the replay file.")
    if r.returncode != 0 or not (out_dir / "manifest.json").is_file():
        last = next((ln for ln in reversed((r.stderr or r.stdout or "").splitlines()) if ln.strip()), "")
        raise ReplayError(f"vrfkit couldn't read the replay file{': ' + last.strip() if last else ''}. "
                          "Replays of a brand-new patch may need a newer vrfkit.")
    return out_dir


# ---------------------------------------------------------------------------
# export -> compact data
# ---------------------------------------------------------------------------
def _loadouts(manifest: dict) -> dict[str, str]:
    """subject -> agent id (characterId) from the game-specific data."""
    out = {}
    for blob in manifest.get("game_specific_data") or []:
        try:
            d = json.loads(blob) if isinstance(blob, str) else blob
        except ValueError:
            continue
        if isinstance(d, dict):
            for pl in d.get("playerLoadouts") or []:
                if isinstance(pl, dict) and pl.get("subject"):
                    out[str(pl["subject"]).lower()] = str(pl.get("characterId") or "").lower()
    return out


def _match_id(manifest: dict, vrf_name: str = "") -> str:
    for cand in (str(manifest.get("friendly_name") or ""), vrf_name):
        m = UUID_RE.search(cand)
        if m:
            return m.group(0).lower()
    return ""


def extract(export_dir: Path, vrf_name: str = "") -> dict:
    """The parts of a vrfkit export Nexus uses, as plain JSON-able data."""
    try:
        import pyarrow.parquet as pq
    except ImportError:           # pragma: no cover - a dependency since 4.9
        raise ReplayError("pyarrow is missing: run `pip install -e .` again after the update.")
    export_dir = Path(export_dir)
    manifest = json.loads((export_dir / "manifest.json").read_text())
    agents = _loadouts(manifest)
    guid_to: dict[int, str] = {}
    players: dict[str, dict] = {}
    for p in manifest.get("players") or []:
        sub = str(p.get("subject") or "").lower()
        if not sub:
            continue
        guids = [int(g) for g in (p.get("character_net_guids") or []) if g]
        if p.get("character_net_guid") and int(p["character_net_guid"]) not in guids:
            guids.append(int(p["character_net_guid"]))
        for g in guids:
            guid_to[g] = sub
        players[sub] = {"agent_id": agents.get(sub, "")}
    levels = manifest.get("level_names_and_times") or []

    # server timeline
    ev = pq.read_table(export_dir / "events.parquet",
                       columns=["group", "time1", "word0", "word1"]).to_pydict()
    rounds, deaths, spike = [], [], []
    for grp, t, w0, w1 in zip(ev["group"], ev["time1"], ev["word0"], ev["word1"]):
        if t is None:
            continue
        t = int(t)
        if grp == "roundStarted" and w0 is not None:
            rounds.append([int(w0), t])
        elif grp == "characterDeath" and w1 is not None:
            deaths.append([t, guid_to.get(int(w0 or 0), ""), guid_to.get(int(w1), "")])
        elif grp in ("spikePlanted", "spikeDefused", "spikeExploded"):
            spike.append([grp, t])
    # a round number seen twice (e.g. a remake): the last start counts
    by_no: dict[int, int] = {}
    for n, t in rounds:
        by_no[n] = t
    rounds = sorted([[n, t] for n, t in by_no.items()], key=lambda x: x[0])

    # positions, thinned to one per SAMPLE_MS per player
    mv = pq.read_table(export_dir / "movement.parquet",
                       columns=["time_ms", "character_net_guid", "pos_x", "pos_y", "pos_z", "yaw"]).to_pydict()
    pos: dict[str, list] = {}
    last_bucket: dict[str, int] = {}
    order = sorted(range(len(mv["time_ms"])), key=lambda i: mv["time_ms"][i])
    for i in order:
        sub = guid_to.get(int(mv["character_net_guid"][i]))
        if not sub:
            continue                                   # ability pawns, bots, decoys
        x, y, z = mv["pos_x"][i], mv["pos_y"][i], mv["pos_z"][i]
        if x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
            continue
        if (x == 0 and y == 0 and z == 0) or abs(x) > PARKED or abs(y) > PARKED or (z is not None and z < -PARKED):
            continue                                   # not spawned yet, or parked while dead
        t = int(mv["time_ms"][i])
        b = t // SAMPLE_MS
        if last_bucket.get(sub) == b:
            continue
        last_bucket[sub] = b
        pos.setdefault(sub, []).append([t, round(x, 1), round(y, 1), round(z or 0.0, 1), round(mv["yaw"][i] or 0.0, 1)])
    casts = _casts(export_dir, set(players))
    effects = _effects(export_dir)
    return {
        "format": FORMAT,
        "casts": casts,
        "effects": effects,
        "match_id": _match_id(manifest, vrf_name),
        "build": str(manifest.get("replay_build") or ""),
        "duration_ms": int(manifest.get("duration_ms") or 0),
        "map_url": str(levels[0].get("name") or "") if levels and isinstance(levels[0], dict) else "",
        "players": players,
        "rounds": rounds,
        "deaths": sorted(deaths),
        "spike": spike,
        "pos": pos,
    }


def _casts(export_dir: Path, subjects: set[str]) -> list[list]:
    """Ability casts as [time_ms, subject, slot] (replay time, deduplicated), from fields.parquet.

    A cast's CastTime counts from the round's barrier drop (vrfkit docs/DATA.md). The array is re-sent on
    every later replication, so each cast is kept once (player, round, slot, CastTime) and its time is the
    barrier drop of its round + CastTime, the barrier drop being the median of (first send - CastTime) over
    the round's casts. [] if the export has no such rows (older vrfkit, other builds)."""
    f = Path(export_dir) / "fields.parquet"
    if not f.is_file():
        return []
    try:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        cols = [c for c in ("time_ms", "group_path", "actor_net_guid", "packet_id", "field_name",
                            "value_i64", "value_f64", "value_str") if c in pq.read_schema(f).names]
        if not {"time_ms", "group_path", "field_name"} <= set(cols):
            return []
        t = pq.read_table(f, columns=cols)
        t = t.filter(pc.match_substring(t["group_path"], CAST_GROUP))
        t = t.filter(pc.starts_with(t["field_name"], "AbilityCastsThisRound["))
        rows = t.to_pylist()
    except Exception as e:                      # the casts are extra: never fail the import over them
        log_.warning("ability casts not read: %s", e)
        return []
    # one array snapshot = the rows of one replication (actor, packet); element i = one cast
    elems: dict[tuple, dict] = {}
    for r in rows:
        m = CAST_FIELD_RE.fullmatch(str(r.get("field_name") or ""))
        if not m:
            continue
        key = (r.get("actor_net_guid"), r.get("packet_id"), int(r["time_ms"] or 0), int(m.group(1)))
        e = elems.setdefault(key, {"t": int(r["time_ms"] or 0)})
        name = m.group(2)
        if name == "Player":
            e["player"] = str(r.get("value_str") or "").lower()
        elif name == "CastTime":
            e["cast"] = r.get("value_f64")
        else:
            e[name.lower()] = r.get("value_i64")
    first: dict[tuple, dict] = {}
    for e in elems.values():
        if e.get("player") not in subjects or e.get("cast") is None or e.get("round") is None:
            continue
        ident = (e["player"], int(e["round"]), int(e.get("slot") or 0), round(float(e["cast"]), 2))
        if ident not in first or e["t"] < first[ident]["t"]:
            first[ident] = e
    by_round: dict[int, list[float]] = {}
    for (_, rnd, _, cast), e in first.items():
        by_round.setdefault(rnd, []).append(e["t"] - cast * 1000)
    drop = {rnd: statistics.median(v) for rnd, v in by_round.items()}
    out = [[int(drop[rnd] + cast * 1000), player, slot] for (player, rnd, slot, cast) in first]
    return sorted(out)


# 4.16.3: placed utility (smokes, walls, slows, mollies, traps, recon, orbs, flashes). Every ability effect is an
# actor in actors.parquet with a class, a spawn position and an open/close lifetime (vrfkit docs/DATA.md,
# "Persistent effect position"); the classification follows vrfkit's tools/extract_active_effects.py.
EFFECT_WORDS = ("smoke", "wall", "barrier", "toxicscreen", "slow", "trap", "cage", "molotov", "fire", "decay",
                "orb", "drone", "scout", "recon", "nanoswarm", "alarmbot", "reveal", "flash", "bolt", "turret")
AGENT_PATH_RE = re.compile(r"/Game/Characters/(\w+)/")
SLOT_RE = re.compile(r"_(Q|E|C|X|4)_", re.I)
SLOT_LETTER = {"q": "Q", "e": "E", "c": "C", "x": "X", "4": "E"}     # "4" is the E slot in class names


def effect_type(class_path: str) -> str:
    c = class_path.lower().replace("throughwall", "")
    if "smoke" in c:
        return "smoke"
    if "wall" in c or "barrier" in c or "toxicscreen" in c:
        return "wall"
    if "slow" in c:
        return "slow"
    if "trap" in c or "cage" in c or "turret" in c or "alarmbot" in c:
        return "trap"
    if "molotov" in c or "fire" in c or "decay" in c or "nanoswarm" in c or "orbitalstrike" in c:
        return "damage"
    if "flash" in c:
        return "flash"
    if "orb" in c:
        return "orb"
    if "drone" in c or "scout" in c or "recon" in c or "reveal" in c or "bolt" in c:
        return "recon"
    return "other"


def is_effect(class_path: str) -> bool:
    if not class_path or "/Game/Characters/" not in class_path:
        return False
    c = class_path.lower().replace("throughwall", "")
    leaf = c.rsplit("/", 1)[-1]
    if leaf.startswith(("ability_", "gun_", "fxc_", "comp_")) or not any(w in c for w in EFFECT_WORDS):
        return False
    return True


def _effects(export_dir: Path) -> list[list]:
    """[[open_ms, close_ms or None, agent codename, slot letter, type, kind, x, y], ...]. A projectile (bolt,
    flash, grenade) is placed where it last moved; a zone or object where it spawned. [] if not available."""
    f = Path(export_dir) / "actors.parquet"
    if not f.is_file():
        return []
    try:
        import pyarrow.parquet as pq
        names = pq.read_schema(f).names
        need = ["actor_net_guid", "event", "time_ms", "class_path", "spawn_x", "spawn_y"]
        if not set(need) <= set(names):
            return []
        t = pq.read_table(f, columns=need).to_pylist()
    except Exception as e:
        log_.warning("ability effects not read: %s", e)
        return []
    evs: dict[int, list] = {}
    for r in t:
        cp = str(r.get("class_path") or "")
        if is_effect(cp):
            evs.setdefault(r["actor_net_guid"], []).append(r)
    inst = []                                       # (guid, open, close, class, x, y)
    for g, rs in evs.items():
        rs.sort(key=lambda r: r["time_ms"] or 0)
        cur = None
        for r in rs:
            if r["event"] == "open":
                if cur:
                    inst.append((g, *cur[:1], None, *cur[1:]))
                cur = (int(r["time_ms"] or 0), r["class_path"], r.get("spawn_x"), r.get("spawn_y"))
            elif r["event"] == "close" and cur:
                inst.append((g, cur[0], int(r["time_ms"] or 0), *cur[1:]))
                cur = None
        if cur:
            inst.append((g, cur[0], None, *cur[1:]))
    if not inst:
        return []
    # projectiles: where they last moved before they closed (ReplicatedMovement, world units)
    proj = {g for g, _, _, cp, _, _ in inst if cp.rsplit("/", 1)[-1].lower().startswith("projectile_")}
    last: dict[int, list] = {}
    if proj:
        try:
            import pyarrow as pa
            import pyarrow.compute as pc
            import pyarrow.parquet as pq
            fp = Path(export_dir) / "fields.parquet"
            if fp.is_file() and {"actor_net_guid", "field_name", "value_str", "time_ms"} <= set(pq.read_schema(fp).names):
                tb = pq.read_table(fp, columns=["actor_net_guid", "field_name", "value_str", "time_ms"])
                tb = tb.filter(pc.equal(tb["field_name"], "ReplicatedMovement"))
                tb = tb.filter(pc.is_in(tb["actor_net_guid"], value_set=pa.array(sorted(proj), type=tb.schema.field("actor_net_guid").type)))
                for r in tb.to_pylist():
                    try:
                        loc = (json.loads(r["value_str"] or "{}").get("location") or {})
                    except ValueError:
                        continue
                    if loc.get("x") is not None:
                        last.setdefault(r["actor_net_guid"], []).append((int(r["time_ms"] or 0), loc["x"], loc["y"]))
        except Exception as e:
            log_.info("projectile positions not read: %s", e)
    out = []
    for g, t0, t1, cp, x, y in inst:
        mv = [m for m in last.get(g, []) if t1 is None or m[0] <= t1]
        if mv:
            _, x, y = max(mv)
        if x is None or y is None:
            continue
        m = AGENT_PATH_RE.search(cp)
        slot = SLOT_RE.search(cp.rsplit("/", 1)[-1])
        leaf = cp.rsplit("/", 1)[-1].split(".", 1)[0]
        out.append([t0, t1, m.group(1) if m else "", SLOT_LETTER.get(slot.group(1).lower(), "") if slot else "",
                    effect_type(cp), leaf.split("_", 1)[0].lower(), round(float(x)), round(float(y))])
    return sorted(out)


def round_effects(data: dict, match: Match, offsets: dict[int, int], agent_names: dict[str, str] | None = None,
                  ) -> dict[int, list[dict]]:
    """Round index -> [{t0, t1 (round ms; t1 None = until the round ends), owner puuid or None, agent, slot,
    type, x, y}]. The owner is the player with that agent (the codename is mapped with agent_names, e.g.
    "wraith" -> "Omen"); with the same agent on both teams, the one who cast an ability just before."""
    eff = data.get("effects") or []
    if not eff:
        return {}
    starts = sorted((int(n), int(t)) for n, t in data.get("rounds") or [])
    names = {k.lower(): v for k, v in (agent_names or {}).items()}
    by_agent: dict[str, list[str]] = {}
    for p in match.players.values():
        by_agent.setdefault(p.agent.lower(), []).append(p.puuid)
    casts = sorted((t, str(s).lower()) for t, s, _ in data.get("casts") or [])
    known = {p.lower(): p for p in match.players}
    out: dict[int, list[dict]] = {}
    for t0, t1, code, slot, typ, _kind, x, y in eff:
        rnd = next((n for n, t in reversed(starts) if t <= t0), None)
        if rnd is None or rnd not in offsets:
            continue
        agent = names.get(str(code).lower(), "")
        cands = by_agent.get(agent.lower(), []) if agent else []
        owner = cands[0] if len(cands) == 1 else None
        if len(cands) > 1:
            near = [known.get(s) for t, s in casts if t0 - 5000 <= t <= t0 + 500 and known.get(s) in cands]
            owner = near[-1] if near else None
        off = offsets[rnd]
        out.setdefault(rnd, []).append({"t0": int(t0 - off), "t1": None if t1 is None else int(t1 - off),
                                        "owner": owner, "agent": agent, "slot": slot, "type": typ, "x": x, "y": y})
    return out


def refresh_if_old(replays_dir: Path, match_id: str, work_dir: Path, vrfkit: str) -> dict | None:
    """Reads the kept .vrf again when the stored data predates casts / effects (4.16 / 4.16.3)."""
    try:
        vrf = vrf_file(replays_dir, match_id)
        if not vrf.is_file():
            return None
        ingest(vrf, replays_dir, work_dir, vrfkit)
        return load(replays_dir, match_id)
    except Exception as e:
        log_.info("replay %s not read again: %s", match_id, e)
        return None


# ---------------------------------------------------------------------------
# storage: data/replays/<match id>.vrf + <match id>.json.gz
# ---------------------------------------------------------------------------
def _inside(replays_dir: Path, match_id: str, suffix: str) -> Path:
    """<replays_dir>/<match id><suffix>. The match id comes from requests: only letters, digits and dashes are
    accepted, and the path must stay inside the folder (4.10)."""
    mid = str(match_id or "").lower()
    if not ID_RE.fullmatch(mid):
        raise ReplayError("That isn't a match id.")
    base = os.path.realpath(replays_dir)
    full = os.path.realpath(os.path.join(base, mid + suffix))
    if not full.startswith(base + os.sep):
        raise ReplayError("That isn't a match id.")
    return Path(full)


def data_file(replays_dir: Path, match_id: str) -> Path:
    return _inside(replays_dir, match_id, ".json.gz")


def vrf_file(replays_dir: Path, match_id: str) -> Path:
    return _inside(replays_dir, match_id, ".vrf")


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(path)


def ingest(vrf: Path, replays_dir: Path, work_dir: Path, vrfkit: str, keep_vrf: bool = True) -> dict:
    """Read a .vrf, store its compact data under its match id and (with keep_vrf) move the file next to it.
    Returns a short summary: match_id, players, rounds, deaths, build."""
    vrf = Path(vrf)
    if not vrf.is_file():
        raise ReplayError("The replay file is missing.")
    if vrf.stat().st_size > MAX_VRF_BYTES:
        raise ReplayError("That file is too big for a replay file.")
    with open(vrf, "rb") as f:
        head = f.read(4)
    if len(head) < 4:
        raise ReplayError("That isn't a replay file.")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / f"vrf-{uuid.uuid4().hex}"
    try:
        export(vrfkit, vrf, out)
        data = extract(out, vrf.name)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    if not data["match_id"]:
        raise ReplayError("The replay file doesn't say which match it is.")
    if not data["pos"]:
        raise ReplayError("The replay file has no player positions.")
    _write(data_file(replays_dir, data["match_id"]), data)
    if keep_vrf:
        dest = vrf_file(replays_dir, data["match_id"])
        if vrf.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(vrf), dest)
    return summary(data)


def summary(data: dict) -> dict:
    return {"match_id": data["match_id"], "players": len(data.get("players") or {}),
            "rounds": len(data.get("rounds") or []), "deaths": len(data.get("deaths") or []),
            "build": data.get("build", ""), "map_url": data.get("map_url", "")}


def has_replay(replays_dir: Path, match_id: str) -> bool:
    try:
        return data_file(replays_dir, match_id).is_file() or vrf_file(replays_dir, match_id).is_file()
    except ReplayError:
        return False


def load(replays_dir: Path, match_id: str, work_dir: Path | None = None, vrfkit: str = "") -> dict | None:
    """The compact data of this match, or None. A .vrf put into the folder by hand is read on first use."""
    p = data_file(replays_dir, match_id)
    if p.is_file():
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("format") == FORMAT:
                return d
        except (OSError, ValueError):
            pass
    v = vrf_file(replays_dir, match_id)
    if v.is_file() and work_dir is not None:
        ingest(v, replays_dir, work_dir, vrfkit or vrfkit_path())
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    return None


def stored(replays_dir: Path) -> list[str]:
    """Match ids that have replay data on the server."""
    d = Path(replays_dir)
    if not d.is_dir():
        return []
    ids = {f.name[:-len(".json.gz")] for f in d.glob("*.json.gz")} | {f.stem for f in d.glob("*.vrf")}
    return sorted(i for i in ids if UUID_RE.fullmatch(i))


# ---------------------------------------------------------------------------
# lining the replay up with the match data
# ---------------------------------------------------------------------------
def align(data: dict, match: Match) -> tuple[dict[int, int], dict]:
    """Replay time (ms since the file's start) of each round's time 0 in the match data, by round index.

    Every kill is in both: in the match data as (round, victim, time in round), in the replay as (victim,
    time). Matched kills give the offset of their round (median); a round without kills takes the offset
    of the others relative to its round start. Returns (offsets, quality)."""
    starts = {int(n): int(t) for n, t in data.get("rounds") or []}
    deaths_by: dict[str, list[int]] = {}
    for t, _killer, victim in data.get("deaths") or []:
        if victim:
            deaths_by.setdefault(victim, []).append(int(t))
    used: set[tuple[str, int]] = set()
    total = matched = 0
    per_round: dict[int, list[int]] = {}
    for r in match.rounds:
        lo = starts.get(r.index)
        hi = starts.get(r.index + 1)
        for k in r.kills:
            total += 1
            cands = [t for t in deaths_by.get(k.victim.lower(), []) if (k.victim.lower(), t) not in used]
            if lo is not None:
                cands = [t for t in cands if t >= lo and (hi is None or t < hi)]
            if not cands:
                continue
            t = cands[0]
            used.add((k.victim.lower(), t))
            per_round.setdefault(r.index, []).append(t - k.t_round_ms)
            matched += 1
    offsets = {i: int(statistics.median(v)) for i, v in per_round.items()}
    rel = [offsets[i] - starts[i] for i in offsets if i in starts]
    lead = int(statistics.median(rel)) if rel else None
    for r in match.rounds:
        if r.index not in offsets and r.index in starts and lead is not None:
            offsets[r.index] = starts[r.index] + lead
    spread = [abs(x - offsets[i]) for i, v in per_round.items() for x in v]
    quality = {"kills": total, "matched": matched, "share": matched / total if total else 0.0,
               "rounds": len(offsets), "max_error_ms": max(spread) if spread else 0}
    return offsets, quality


def _round_end(match: Match, idx: int, offsets: dict[int, int], data_starts: dict[int, int]) -> float:
    """Round time (s) at which the round's paths stop."""
    r = match.rounds[idx]
    events = [k.t_round_ms for k in r.kills] + [e.t_round_ms for e in (r.plant, r.defuse) if e]
    cap = (r.plant.t_round_ms / 1000 + SPIKE_S) if r.plant else MAX_ROUND_S
    nxt = data_starts.get(idx + 1)
    if nxt is not None and idx in offsets:
        cap = min(cap, (nxt - offsets[idx] - POST_ROUND_MS) / 1000)
    return max(cap, max(events, default=0) / 1000 + 2.0)


def round_paths(data: dict, match: Match, offsets: dict[int, int]) -> dict[int, dict[str, list]]:
    """Round index -> {puuid: [(t_round_s, x, y)]} at OUT_HZ, from round time 0 to death or the round's end."""
    starts = {int(n): int(t) for n, t in data.get("rounds") or []}
    known = {p.lower(): p for p in match.players}
    out: dict[int, dict[str, list]] = {}
    for r in match.rounds:
        off = offsets.get(r.index)
        if off is None:
            continue
        end = _round_end(match, r.index, offsets, starts)
        died: dict[str, float] = {}
        for k in r.kills:
            died.setdefault(k.victim, k.t_round_ms / 1000)
        paths: dict[str, list] = {}
        for sub, pts in (data.get("pos") or {}).items():
            puuid = known.get(sub.lower())
            if puuid is None:
                continue
            stop = min(end, died.get(puuid, math.inf))
            seq, last_b = [], None
            for t_ms, x, y, *_ in pts:
                t = (t_ms - off) / 1000
                if t < 0:
                    continue
                if t > stop:
                    break
                b = int(t * OUT_HZ)
                if b == last_b:
                    continue
                last_b = b
                seq.append((round(t, 2), float(x), float(y)))
            if seq:
                paths[puuid] = seq
        if paths:
            out[r.index] = paths
    return out


def round_cast_events(data: dict, match: Match, offsets: dict[int, int]) -> dict[int, list[list]]:
    """Round index -> [[round time (ms), puuid, slot], ...] for the playback (4.16.2); negative = buy phase."""
    starts = sorted((int(n), int(t)) for n, t in data.get("rounds") or [])
    known = {p.lower(): p for p in match.players}
    out: dict[int, list[list]] = {}
    for t_ms, sub, slot in data.get("casts") or []:
        puuid = known.get(str(sub).lower())
        rnd = next((n for n, t in reversed(starts) if t <= t_ms), None)
        if puuid is None or rnd is None or rnd not in offsets:
            continue
        out.setdefault(rnd, []).append([int(t_ms - offsets[rnd]), puuid, int(slot or 0)])
    return out


def round_casts(data: dict, match: Match, offsets: dict[int, int]) -> dict[int, dict[str, list[float]]]:
    """Round index -> {puuid: [round time (s) of each ability cast]} (negative = during the buy phase).
    A cast belongs to the round whose start (buy phase) is the last one before it."""
    casts = data.get("casts") or []
    if not casts:
        return {}
    starts = sorted((int(n), int(t)) for n, t in data.get("rounds") or [])
    known = {p.lower(): p for p in match.players}
    out: dict[int, dict[str, list[float]]] = {}
    for t_ms, sub, _slot in casts:
        puuid = known.get(str(sub).lower())
        rnd = next((n for n, t in reversed(starts) if t <= t_ms), None)
        if puuid is None or rnd is None or rnd not in offsets:
            continue
        out.setdefault(rnd, {}).setdefault(puuid, []).append(round((t_ms - offsets[rnd]) / 1000, 1))
    return out


# ---------------------------------------------------------------------------
# what the coach reads
# ---------------------------------------------------------------------------
def _zone_counts(paths: dict[str, list], who: list[str], t0: float, t1: float, mi: MapInfo) -> dict[str, float]:
    """Average number of these players per zone between t0 and t1."""
    acc: dict[str, int] = {}
    samples = 0
    for t in [t0 + i / OUT_HZ for i in range(int((t1 - t0) * OUT_HZ))]:
        any_here = False
        for p in who:
            pt = _at(paths.get(p, []), t)
            if pt is None:
                continue
            any_here = True
            z = mi.zone(pt[0], pt[1])
            acc[z] = acc.get(z, 0) + 1
        samples += any_here
    if not samples:
        return {}
    return {z: round(c / samples, 1) for z, c in sorted(acc.items(), key=lambda kv: -kv[1]) if c / samples >= 0.1}


def _at(seq: list, t: float) -> tuple[float, float] | None:
    """Position at round time t (nearest sample within 0.6 s)."""
    best, bd = None, 0.6
    for ts, x, y in seq:
        d = abs(ts - t)
        if d <= bd:
            best, bd = (x, y), d
        elif ts > t:
            break
    return best


def _rotations(timeline: list[dict], key: str, label: str) -> list[str]:
    out = []
    for a, b in zip(timeline, timeline[1:]):
        za, zb = a.get(key, {}), b.get(key, {})
        lost = {z: za[z] - zb.get(z, 0) for z in za if za[z] - zb.get(z, 0) >= 1.5}
        gained = {z: zb[z] - za.get(z, 0) for z in zb if zb[z] - za.get(z, 0) >= 1.5}
        for zl in lost:
            for zg in gained:
                if zl != zg:
                    out.append(f"{b['t']}: ~{round(min(lost[zl], gained[zg]))} {label} {zl} -> {zg}")
    return out


def describe(paths: dict[str, list], match: Match, round_index: int, focus: str, mi: MapInfo,
             bucket_s: float = 10.0, casts: list[float] | None = None) -> dict:
    """Compact, LLM-friendly movement of both teams in one round (exact positions from the replay file)."""
    if not paths:
        return {}
    team = match.team_of(focus)
    allies = [p for p in match.players if match.team_of(p) == team and p != focus]
    enemies = [p for p in match.players if match.team_of(p) != team]
    end = max(seq[-1][0] for seq in paths.values())
    timeline = []
    t = 0.0
    while t <= end:
        entry: dict = {"t": f"{int(t)}-{int(t + bucket_s)}s"}
        a = _zone_counts(paths, allies, t, t + bucket_s, mi)
        e = _zone_counts(paths, enemies, t, t + bucket_s, mi)
        you = _zone_counts(paths, [focus], t, t + bucket_s, mi)
        if a:
            entry["allies"] = a
        if you:
            entry["you"] = max(you, key=you.get)
        if e:
            entry["enemies"] = e
        if len(entry) > 1:
            timeline.append(entry)
        t += bucket_s
    your_path, last = [], None
    for ts, x, y in paths.get(focus, []):
        area = mi.area(x, y)
        if area != last:
            your_path.append(f"{int(ts)}s {area}")
            last = area
    return {"source": "replay file",
            "note": "exact positions of all ten players from the game's replay file; numbers are the average "
                    "player count per zone in each window",
            "timeline": timeline,
            "rotations": _rotations(timeline, "allies", "allies") + _rotations(timeline, "enemies", "enemies"),
            "your_path": your_path[:25],
            **({"your_ability_casts": [("buy phase" if t < 0 else f"{int(t)}s") for t in sorted(casts)][:12]}
               if casts else {})}


def for_match(replays_dir: Path, work_dir: Path, vrfkit: str, match: Match, focus: str, mi: MapInfo | None,
              log=lambda s: None, agent_names: dict[str, str] | None = None) -> dict | None:
    """Everything the coaching run takes from the replay file, or None (logged why) if there is none or it
    doesn't fit: {"minimap": {round: describe}, "self_paths": {round: path}, "others": {round: {...}}}."""
    if not has_replay(replays_dir, match.match_id):
        log("· No replay file for this match on the server")
        return None
    try:
        data = load(replays_dir, match.match_id, work_dir, vrfkit)
    except ReplayError as e:
        log(f"! Replay file can't be read: {e}")
        return None
    if data is None:
        log("! Replay file can't be read")
        return None
    if "effects" not in data:                     # stored before 4.16.3: read the .vrf again for the utility
        data = refresh_if_old(replays_dir, match.match_id, work_dir, vrfkit) or data
    if data.get("match_id") and data["match_id"] != match.match_id.lower():
        log("! The replay file belongs to another match; not used")
        return None
    offsets, q = align(data, match)
    if q["kills"] and q["share"] < MIN_MATCHED_SHARE:
        log(f"! The replay file doesn't fit the match data ({q['matched']}/{q['kills']} kills found); not used")
        return None
    if not offsets:
        log("! The replay file has no rounds that could be lined up with the match data; not used")
        return None
    paths = round_paths(data, match, offsets)
    rcasts = round_casts(data, match, offsets)
    cast_events = round_cast_events(data, match, offsets)
    effects = round_effects(data, match, offsets, agent_names)
    team = match.team_of(focus)
    out: dict = {"minimap": {}, "self_paths": {}, "others": {}}
    for idx, ps in paths.items():
        if focus in ps:
            out["self_paths"][idx] = ps[focus]
        out["others"][idx] = {
            "allies": {p: s for p, s in ps.items() if p != focus and match.team_of(p) == team},
            "players": {p: s for p, s in ps.items() if p != focus and match.team_of(p) != team},
            "enemies": [],
            "casts": cast_events.get(idx) or [],       # 4.16.2: everyone's ability casts for the playback
            "effects": effects.get(idx) or [],         # 4.16.3: smokes, walls, recon ... where and how long
        }
        if mi is not None:
            d = describe(ps, match, idx, focus, mi, casts=(rcasts.get(idx) or {}).get(focus))
            if d:
                out["minimap"][idx] = d
    log(f"· Replay file ({data.get('build') or 'unknown build'}): {len(paths)}/{len(match.rounds)} rounds, "
        f"{q['matched']}/{q['kills']} kills lined up (max {q['max_error_ms']} ms apart), "
        f"{len(data.get('pos') or {})} players tracked")
    return out
