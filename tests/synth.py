"""Synthetic test data in the exact HenrikDev v4 / valorant-api.com shapes.

Builds:
  * a valorant-api.com style maps payload with one map ("Testmap")
  * a v4 match payload (10 players, N rounds, kills with player_locations, plants)
  * optionally a VOD whose minimap and kill feed are drawn from the same data
    with a known time offset and minimap transform, so sync + calibration can
    be verified against ground truth.
"""
from __future__ import annotations

import json
import math
import random
import zlib
from pathlib import Path

import cv2
import numpy as np

MAP_UUID = "00000000-test-map0-0000-000000000001"
X_MULT, Y_MULT, X_ADD, Y_ADD = 7.0e-05, -7.0e-05, 0.5, 0.5

# zone centres in world units (UV within 0.1..0.9)
ZONES = {
    ("A", "Site"): (-5000, -4500),
    ("A", "Main"): (-1500, -5000),
    ("B", "Site"): (-5000, 4500),
    ("B", "Main"): (-1500, 5000),
    ("Mid", "Top"): (-2500, 0),
    ("Mid", "Bottom"): (1000, 0),
    ("Attacker Side", "Spawn"): (5000, 0),
    ("Defender Side", "Spawn"): (-8000, 0),
}

RED = [f"red-{i}" for i in range(5)]
BLUE = [f"blue-{i}" for i in range(5)]
AGENTS = ["Jett", "Sova", "Omen", "Killjoy", "Skye"]
ROUND_LEN_S = 60.0


def agent_uuid(name: str) -> str:
    return f"agent-{name.lower()}"


REAL_ABILITIES = {   # real names, so the strat board finds their shapes/sizes
    "Jett": {"Grenade": "Cloudburst", "Ability1": "Updraft", "Ability2": "Tailwind", "Ultimate": "Blade Storm"},
    "Sova": {"Grenade": "Owl Drone", "Ability1": "Shock Bolt", "Ability2": "Recon Bolt", "Ultimate": "Hunter's Fury"},
    "Omen": {"Grenade": "Paranoia", "Ability1": "Shrouded Step", "Ability2": "Dark Cover", "Ultimate": "From the Shadows"},
    "Killjoy": {"Grenade": "Nanoswarm", "Ability1": "Alarmbot", "Ability2": "Turret", "Ultimate": "Lockdown"},
}


def write_agent_cache(cache: Path) -> None:
    """valorant-api.com style agent list + one placeholder icon per agent (no network in tests)."""
    import json as _json
    (cache / "agents").mkdir(parents=True, exist_ok=True)
    slots = [("Grenade", "Cloud"), ("Ability1", "Dash"), ("Ability2", "Wall"), ("Ultimate", "Storm"), ("Passive", "Drift")]
    data = [{"uuid": agent_uuid(n), "displayName": n, "displayIconSmall": f"https://example.invalid/{n}.png",
             "isPlayableCharacter": True, "role": {"displayName": {"Jett": "Duelist", "Sova": "Initiator", "Omen": "Controller",
                                                                   "Killjoy": "Sentinel", "Skye": "Initiator"}[n]},
             "abilities": [{"slot": sl, "displayName": REAL_ABILITIES.get(n, {}).get(sl, f"{n} {nm}"),
                            "displayIcon": f"https://example.invalid/{n}-{sl}.png"}
                           for sl, nm in slots]} for n in AGENTS]
    (cache / "abilities").mkdir(parents=True, exist_ok=True)
    for n in AGENTS:
        for k, (sl, _) in enumerate(slots):
            ic = np.zeros((64, 64, 4), np.uint8)
            cv2.circle(ic, (32, 32), 10 + 4 * k, (255, 255, 255, 255), 5)
            cv2.imwrite(str(cache / "abilities" / f"{agent_uuid(n)}_{sl.lower()}.png"), ic)
    (cache / "valorant_api_agents.json").write_text(_json.dumps({"status": 200, "data": data}))
    colors = [(60, 120, 230), (230, 160, 60), (150, 80, 200), (60, 200, 230), (90, 200, 120)]
    for n, col in zip(AGENTS, colors):
        img = np.full((96, 96, 3), col, np.uint8)
        cv2.putText(img, n[0], (26, 66), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 4)
        cv2.imwrite(str(cache / "agents" / f"{agent_uuid(n)}.png"), img)


CORRIDORS = [
    (("Attacker Side", "Spawn"), ("Mid", "Bottom")), (("Mid", "Bottom"), ("Mid", "Top")),
    (("Mid", "Top"), ("Defender Side", "Spawn")),
    (("Attacker Side", "Spawn"), ("A", "Main")), (("A", "Main"), ("A", "Site")), (("A", "Site"), ("Defender Side", "Spawn")),
    (("Attacker Side", "Spawn"), ("B", "Main")), (("B", "Main"), ("B", "Site")), (("B", "Site"), ("Defender Side", "Spawn")),
    (("Mid", "Top"), ("A", "Site")), (("Mid", "Top"), ("B", "Site")),
]


def write_map_image(cache: Path, size: int = 512) -> Path:
    """Minimap-like RGBA image: transparent outside, grey corridors between the zones (walls elsewhere)."""
    img = np.zeros((size, size, 4), np.uint8)
    def px(zone):
        u, v = to_uv(*ZONES[zone])
        return int(u * size), int(v * size)
    for a, b in CORRIDORS:
        cv2.line(img, px(a), px(b), (150, 150, 150, 255), 26)
    for z in ZONES:
        cv2.circle(img, px(z), 30, (150, 150, 150, 255), -1)
    p = cache / "minimaps" / f"{MAP_UUID}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(p), img)
    return p


def maps_payload() -> dict:
    return {"status": 200, "data": [
        {"uuid": "menu", "displayName": "The Range", "xMultiplier": 0, "yMultiplier": 0,
         "xScalarToAdd": 0, "yScalarToAdd": 0, "callouts": None},
        {"uuid": MAP_UUID, "displayName": "Testmap", "displayIcon": "https://example.invalid/testmap.png",
         "xMultiplier": X_MULT, "yMultiplier": Y_MULT, "xScalarToAdd": X_ADD, "yScalarToAdd": Y_ADD,
         "callouts": [{"regionName": r, "superRegionName": s, "location": {"x": x, "y": y}}
                      for (s, r), (x, y) in ZONES.items()]},
    ]}


def to_uv(x: float, y: float) -> tuple[float, float]:
    return y * X_MULT + X_ADD, x * Y_MULT + Y_ADD


def target_site(rnd: int) -> str:
    return "A" if zlib.crc32(f"site-{rnd}".encode()) % 2 == 0 else "B"


VIEW_SIGN, VIEW_OFFSET = -1, math.pi / 2    # synthetic API convention (calibration must find it)


def view_from_world(a: float) -> float:
    """API view_radians for a world-space look angle a (inverse of sign*v + offset)."""
    return (a - VIEW_OFFSET) / VIEW_SIGN


def attackers_for(i: int) -> str:
    return "Red" if i < 12 else "Blue"


def player_pos(puuid: str, rnd: int, t: float, attackers: str, target_site: str) -> tuple[float, float]:
    """Deterministic movement: spawn -> lane -> site over 40 s."""
    team = "Red" if puuid.startswith("red") else "Blue"
    i = int(puuid.split("-")[1])
    rng = random.Random(zlib.crc32(f"{puuid}-{rnd}".encode()))
    jitter = (rng.uniform(-300, 300), rng.uniform(-300, 300))
    if team == attackers:
        start = ZONES[("Attacker Side", "Spawn")]
        lane = ZONES[(target_site, "Main")] if i < 4 else ZONES[("Mid", "Bottom")]
        end = ZONES[(target_site, "Site")] if i < 4 else ZONES[("Mid", "Top")]
    else:
        start = ZONES[("Defender Side", "Spawn")]
        site = "A" if i < 2 else ("B" if i < 4 else "Mid")
        lane = ZONES[(site, "Site")] if site != "Mid" else ZONES[("Mid", "Top")]
        end = lane
    if t < 15:
        a, b, f = start, lane, t / 15
    else:
        a, b, f = lane, end, min(1.0, (t - 15) / 25)
    return (a[0] + (b[0] - a[0]) * f + jitter[0] + 40 * i,
            a[1] + (b[1] - a[1]) * f + jitter[1] - 40 * i)


def build_match(n_rounds: int = 8, seed: int = 7) -> dict:
    rng = random.Random(seed)
    players = []
    for team, ids in (("Red", RED), ("Blue", BLUE)):
        for j, pu in enumerate(ids):
            players.append({
                "puuid": pu, "name": ("adv1ce" if pu == "red-1" else pu), "tag": ("LFT" if pu == "red-1" else "T"),
                "team_id": team, "platform": "PC", "party_id": "p",
                "agent": {"id": agent_uuid(AGENTS[j]), "name": AGENTS[j]},
                "stats": {"score": 0, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0,
                          "bodyshots": 0, "legshots": 0, "damage": {"dealt": 0, "received": 0}},
                "ability_casts": {"grenade": 3, "ability1": 5, "ability2": 4, "ultimate": 1},
                "tier": {"id": 15, "name": "Platinum 1"}, "customization": {"card": "", "title": ""},
                "account_level": 100, "session_playtime_in_ms": 0,
                "behavior": {"afk_rounds": 0, "friendly_fire": {"incoming": 0, "outgoing": 0}, "rounds_in_spawn": 0},
                "economy": {"spent": {"overall": 0, "average": 0}, "loadout_value": {"overall": 0, "average": 0}},
            })
    pmap = {p["puuid"]: p for p in players}
    kills_all, rounds = [], []
    won = {"Red": 0, "Blue": 0}
    for r in range(n_rounds):
        att = attackers_for(r)
        dfn = "Blue" if att == "Red" else "Red"
        site = target_site(r)
        start_ms = int(r * ROUND_LEN_S * 1000)
        alive = {pu: True for pu in RED + BLUE}
        t = rng.uniform(18, 24)
        rkills = []
        plant = None
        winner = None
        last_kill_t: dict[str, float] = {}
        for _ in range(rng.randint(5, 8)):
            al_att = [p for p in (RED if att == "Red" else BLUE) if alive[p]]
            al_def = [p for p in (RED if dfn == "Red" else BLUE) if alive[p]]
            if not al_att or not al_def:
                break
            if rng.random() < 0.5:
                killer, victim = rng.choice(al_att), rng.choice(al_def)
            else:
                killer, victim = rng.choice(al_def), rng.choice(al_att)
            t += rng.uniform(1.2, 6.0)
            if t > 55:
                break
            vx, vy = player_pos(victim, r, t, att, site)
            locs = []
            for pu in RED + BLUE:
                if alive[pu]:
                    x, y = player_pos(pu, r, t, att, site)
                    if pu == killer:
                        target = (vx, vy)                      # killers look at their victim
                    elif pu == victim:
                        target = player_pos(killer, r, t, att, site) if rng.random() < 0.5 else None
                    else:
                        target = None
                    if target is not None:
                        a = math.atan2(target[1] - y, target[0] - x) + math.radians(rng.uniform(-8, 8))
                    else:
                        a = rng.uniform(-math.pi, math.pi)
                    locs.append({"player": {"puuid": pu, "name": pmap[pu]["name"], "tag": pmap[pu]["tag"],
                                            "team": pmap[pu]["team_id"]},
                                 "view_radians": round(view_from_world(a), 4), "location": {"x": int(x), "y": int(y)}})
            alive[victim] = False
            k = {
                "time_in_round_in_ms": int(t * 1000), "time_in_match_in_ms": start_ms + int(t * 1000),
                "round": r,
                "killer": {"puuid": killer, "name": pmap[killer]["name"], "tag": pmap[killer]["tag"], "team": pmap[killer]["team_id"]},
                "victim": {"puuid": victim, "name": pmap[victim]["name"], "tag": pmap[victim]["tag"], "team": pmap[victim]["team_id"]},
                "assistants": [], "location": {"x": int(vx), "y": int(vy)},
                "weapon": {"id": "w", "name": "Vandal", "type": "Weapon"}, "secondary_fire_mode": False,
                "player_locations": locs,
            }
            rkills.append(k)
            pmap[killer]["stats"]["kills"] += 1
            pmap[victim]["stats"]["deaths"] += 1
            last_kill_t[killer] = t
            if plant is None and t > 35 and any(alive[p] for p in (RED if att == "Red" else BLUE)):
                planter = next(p for p in (RED if att == "Red" else BLUE) if alive[p])
                px, py = player_pos(planter, r, t, att, site)
                plant = {"round_time_in_ms": int(t * 1000) + 500, "site": site,
                         "location": {"x": int(px), "y": int(py)},
                         "player": {"puuid": planter, "name": pmap[planter]["name"], "tag": pmap[planter]["tag"], "team": att},
                         "player_locations": []}
        a_alive = sum(alive[p] for p in (RED if att == "Red" else BLUE))
        d_alive = sum(alive[p] for p in (RED if dfn == "Red" else BLUE))
        if a_alive > d_alive or (plant and a_alive >= d_alive):
            winner, result = att, ("Bomb detonated" if plant else "Elimination")
        else:
            winner, result = dfn, "Elimination"
        won[winner] += 1
        stats = []
        for pu in RED + BLUE:
            lv = 800 if r in (0, 12) else rng.choice([3900, 4300, 4700, 2400, 900])
            stats.append({
                "player": {"puuid": pu, "name": pmap[pu]["name"], "tag": pmap[pu]["tag"], "team": pmap[pu]["team_id"]},
                "ability_casts": {"grenade": 1, "ability_1": 1, "ability_2": 0, "ultimate": 1 if rng.random() < 0.1 else 0},
                "damage_events": [{"player": {"puuid": k["victim"]["puuid"], "name": "", "tag": "", "team": k["victim"]["team"]},
                                   "bodyshots": 2, "headshots": 1, "legshots": 0, "damage": 150}
                                  for k in rkills if k["killer"]["puuid"] == pu],
                "stats": {"score": 200 * sum(1 for k in rkills if k["killer"]["puuid"] == pu),
                          "kills": sum(1 for k in rkills if k["killer"]["puuid"] == pu),
                          "headshots": 1, "bodyshots": 2, "legshots": 0},
                "economy": {"loadout_value": lv, "remaining": 1000,
                            "weapon": {"id": "w", "name": "Vandal" if lv > 3000 else "Classic", "type": "Weapon"},
                            "armor": {"id": "a", "name": "Heavy Shields" if lv > 3000 else None}},
                "was_afk": False, "received_penalty": False, "stayed_in_spawn": False,
            })
        for s in stats:
            pmap[s["player"]["puuid"]]["stats"]["score"] += s["stats"]["score"]
        rounds.append({"id": r, "result": result, "ceremony": "CeremonyDefault", "winning_team": winner,
                       "plant": plant, "defuse": None, "stats": stats})
        kills_all.extend(rkills)
    return {"status": 200, "data": {
        "metadata": {"match_id": "synthetic-match-0001", "map": {"id": MAP_UUID, "name": "Testmap"},
                     "game_version": "test", "game_length_in_ms": int(n_rounds * ROUND_LEN_S * 1000),
                     "started_at": "2026-10-20T19:00:00Z", "is_completed": True,
                     "queue": {"id": "premier", "name": "Premier", "mode_type": "Standard"},
                     "season": {"id": "s", "short": "e9a3"}, "platform": "PC", "party_rr_penaltys": [],
                     "region": "eu", "cluster": "Frankfurt", "premier": None},
        "players": players, "observers": [], "coaches": [],
        "teams": [{"team_id": "Red", "rounds": {"won": won["Red"], "lost": won["Blue"]}, "won": won["Red"] > won["Blue"], "premier_roster": None},
                  {"team_id": "Blue", "rounds": {"won": won["Blue"], "lost": won["Red"]}, "won": won["Blue"] > won["Red"], "premier_roster": None}],
        "rounds": rounds, "kills": kills_all,
    }}


# ---------------------------------------------------------------------------
# synthetic VOD
# ---------------------------------------------------------------------------
TRUE_OFFSET_S = 37.3            # vod = match + offset
TRUE_ROT_K = 1                  # minimap rotated 90 deg vs displayIcon
MM_ROI = [0.012, 0.025, 0.215, 0.382]
KF_ROI = [0.70, 0.08, 0.29, 0.25]


def render_vod(match: dict, path: Path, fps: int = 10, w: int = 1280, h: int = 720,
               self_puuid: str = "red-1", bars: int = 0, flip_from_round: int | None = None) -> dict:
    """Draw minimap icons + kill feed. Returns ground truth transform.
    bars: black bars of this width left and right (16:9 game on an ultrawide screen).
    flip_from_round: from this round on the minimap is turned 180 deg (orientation based on side)."""
    data = match["data"]
    n_rounds = len(data["rounds"])
    duration = TRUE_OFFSET_S + n_rounds * ROUND_LEN_S + 5
    mx, my, mw, mh = int(MM_ROI[0] * w), int(MM_ROI[1] * h), int(MM_ROI[2] * w), int(MM_ROI[3] * h)
    side = min(mw, mh) * 0.92
    gt = {"scale": side, "tx": (mw - side) / 2 + 3, "ty": (mh - side) / 2 - 2, "rot_k": TRUE_ROT_K}

    def uv_px(u, v, k=TRUE_ROT_K):
        c = np.array([u - 0.5, v - 0.5])
        for _ in range(k):
            c = np.array([-c[1], c[0]])
        c = c + 0.5
        return gt["scale"] * c[0] + gt["tx"], gt["scale"] * c[1] + gt["ty"]

    kills_by_t = sorted(((k["time_in_match_in_ms"] / 1000 + TRUE_OFFSET_S, k) for k in data["kills"]),
                        key=lambda x: x[0])
    dead_at: dict[tuple[int, str], float] = {}
    for k in data["kills"]:
        dead_at[(k["round"], k["victim"]["puuid"])] = k["time_in_round_in_ms"] / 1000
    target = {r["id"]: target_site(r["id"]) for r in data["rounds"]}

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w + 2 * bars, h))
    team_of = {p["puuid"]: p["team_id"] for p in data["players"]}
    my_team = team_of[self_puuid]
    n_frames = int(duration * fps)
    for fi in range(n_frames):
        t = fi / fps
        frame = np.full((h, w, 3), (38, 42, 46), np.uint8)
        cv2.rectangle(frame, (mx, my), (mx + mw, my + mh), (60, 60, 60), -1)
        tm = t - TRUE_OFFSET_S
        rid = int(tm // ROUND_LEN_S) if tm >= 0 else -1
        if 0 <= rid < n_rounds:
            tr = tm - rid * ROUND_LEN_S
            att = attackers_for(rid)
            k = TRUE_ROT_K + (2 if flip_from_round is not None and rid >= flip_from_round else 0)
            # draw your own icon last: in game it renders on top of the others
            for pu in [p for p in RED + BLUE if p != self_puuid] + [self_puuid]:
                if (rid, pu) in dead_at and dead_at[(rid, pu)] <= tr:
                    continue
                team = team_of[pu]
                x, y = player_pos(pu, rid, tr, att, target[rid])
                u, v = to_uv(x, y)
                px, py = uv_px(u, v, k)
                c = (int(mx + px), int(my + py))
                if pu == self_puuid:
                    cv2.circle(frame, c, 6, (0, 230, 255), 3)            # yellow
                elif team == my_team:
                    cv2.circle(frame, c, 6, (210, 200, 0), 3)            # teal
                elif int(tr * 10) % 30 < 12:                             # enemies flicker (spotted)
                    cv2.circle(frame, c, 6, (40, 40, 235), 3)            # red
        # kill feed: entries visible for 4 s, newest on top
        active = [(kt, k) for kt, k in kills_by_t if kt <= t < kt + 4.0]
        kx, ky = int(KF_ROI[0] * w), int(KF_ROI[1] * h)
        for row, (kt, k) in enumerate(reversed(active[-5:])):
            col = (210, 200, 0) if k["killer"]["team"] == my_team else (40, 40, 235)
            y0 = ky + 8 + row * 30
            cv2.rectangle(frame, (kx + 20, y0), (kx + 340, y0 + 24), (25, 25, 25), -1)
            cv2.rectangle(frame, (kx + 20, y0), (kx + 340, y0 + 24), col, 3)
            cv2.putText(frame, "Vandal", (kx + 150, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        vw.write(np.pad(frame, ((0, 0), (bars, bars), (0, 0))) if bars else frame)
    vw.release()
    return gt


def write_all(dir_: Path, with_vod: bool = True, n_rounds: int = 8) -> dict:
    dir_.mkdir(parents=True, exist_ok=True)
    m = build_match(n_rounds)
    (dir_ / "match.json").write_text(json.dumps(m))
    cache = dir_ / "cache"
    cache.mkdir(exist_ok=True)
    (cache / "valorant_api_maps.json").write_text(json.dumps(maps_payload()))
    write_agent_cache(cache)
    write_map_image(cache)
    out = {"match": dir_ / "match.json", "cache": cache}
    if with_vod:
        out["vod"] = dir_ / "vod.mp4"
        out["gt"] = render_vod(m, out["vod"])
    return out


if __name__ == "__main__":
    import sys
    print(write_all(Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic")))
