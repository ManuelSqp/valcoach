"""Background work for the stats pages: history imports (HenrikDev) and playstyle tips (Ollama).

Runs on its own single worker, separate from the coaching queue, so a long import never
blocks a coaching run. Status lives in memory (the results are files, so a restart only
loses the progress text)."""
from __future__ import annotations

import json
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import pipeline
from ..stats.games import GameStore, import_games
from .store import Store

FULL_LIMIT = 60          # recent full matches per queue (10 per request)
STORED_LIMIT = 300       # archive summaries per queue (20 per request)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


class StatsRunner:
    def __init__(self, store: Store):
        self.store = store
        self.ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stats")
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---- paths ------------------------------------------------------------
    def games(self, pid: int) -> GameStore:
        return GameStore(self.store.profile_dir(pid) / "stats" / "games.json")

    def tips_path(self, pid: int, map_name: str, queue: str) -> Path:
        return self.store.profile_dir(pid) / "stats" / "tips" / f"{slug(map_name)}_{queue}.json"

    def read_tips(self, pid: int, map_name: str, queue: str) -> dict | None:
        p = self.tips_path(pid, map_name, queue)
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except ValueError:
            return None

    # ---- status -----------------------------------------------------------
    def status(self, key: str) -> dict | None:
        with self._lock:
            st = self._state.get(key)
            return dict(st, log=list(st["log"])) if st else None

    def busy(self, key: str) -> bool:
        st = self.status(key)
        return bool(st and st["status"] in ("queued", "running"))

    def _set(self, key: str, **kw) -> None:
        with self._lock:
            self._state.setdefault(key, {"status": "queued", "log": [], "error": "", "t": time.time()}).update(kw)

    def _log(self, key: str, msg: str) -> None:
        with self._lock:
            st = self._state.get(key)
            if st is not None:
                st["log"] = (st["log"] + [msg])[-40:]

    # ---- work -------------------------------------------------------------
    def submit_import(self, pid: int) -> str:
        key = f"import:{pid}"
        if not self.busy(key):
            with self._lock:
                self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}
            self.ex.submit(self._import, key, pid)
        return key

    def _import(self, key: str, pid: int) -> None:
        p = self.store.profile(pid)
        if p is None:
            self._set(key, status="error", error="Player was deleted")
            return
        self._set(key, status="running")
        try:
            cfg = self.store.build_config(p)
            client = pipeline.get_client(cfg)
            client.on_wait = lambda m: self._log(key, m)
            self._log(key, f"· Importing {p.riot_id} ({p.region.upper()}) ...")
            res = import_games(client, p.region, p.platform, p.name, p.tag, self.games(pid),
                               cfg.path(cfg.paths.cache_dir), lambda m: self._log(key, m),
                               full_limit=FULL_LIMIT, stored_limit=STORED_LIMIT)
            self._log(key, f"✓ {res['total']} games ({res['full']} new with round data, {res['stored']} new from the archive)")
            self._set(key, status="done")
        except Exception as e:
            self._log(key, "✗ " + str(e))
            self._log(key, traceback.format_exc(limit=3))
            self._set(key, status="error", error=str(e) or e.__class__.__name__)

    def submit_tips(self, pid: int, map_name: str, queue: str, all_rows: list[dict]) -> str:
        key = f"tips:{pid}:{slug(map_name)}:{queue}"
        if not self.busy(key):
            with self._lock:
                self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}
            self.ex.submit(self._tips, key, pid, map_name, queue, all_rows)
        return key

    def _tips(self, key: str, pid: int, map_name: str, queue: str, all_rows: list[dict]) -> None:
        from ..coach.ollama import Ollama
        from ..stats.aggregate import filter_rows
        from ..stats.tips import write_tips
        p = self.store.profile(pid)
        if p is None:
            self._set(key, status="error", error="Player was deleted")
            return
        self._set(key, status="running")
        try:
            cfg = self.store.build_config(p)
            llm = Ollama(cfg.ollama.url, cfg.ollama.model, cfg.ollama.temperature, cfg.ollama.num_ctx,
                         cfg.ollama.timeout_s, cfg.ollama.think)
            llm.check()
            self._log(key, f"· Writing tips for {map_name} with {cfg.ollama.model} ...")
            rows = filter_rows(self.games(pid).rows(), queue)
            out = write_tips(llm, rows, map_name, p.language, all_rows)
            out["_created"] = time.time()
            path = self.tips_path(pid, map_name, queue)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, ensure_ascii=False))
            self._set(key, status="done")
        except Exception as e:
            self._log(key, "✗ " + str(e))
            self._set(key, status="error", error=str(e) or e.__class__.__name__)

    # ---- pro & videos ---------------------------------------------------------
    def watch_path(self, pid: int, queue: str) -> Path:
        return self.store.profile_dir(pid) / "stats" / f"watch_{queue}.json"

    def read_watch(self, pid: int, queue: str) -> dict:
        """{"by_pro": {pro name: {queries, guide, errors, _created}}}. Files from before 2.16 had one
        guide for the closest pro; it's kept under the key "" (= whoever is closest)."""
        p = self.watch_path(pid, queue)
        try:
            d = json.loads(p.read_text()) if p.exists() else {}
        except ValueError:
            d = {}
        if "by_pro" not in d:
            d = {"by_pro": {"": d}} if d.get("queries") else {"by_pro": {}}
        return d

    def submit_watch(self, pid: int, queue: str, prof: dict, matches: list[dict], jobs: list[dict]) -> str:
        """jobs: [{"pro": name, "queries": [...]}], one guide (and one model run) per pro."""
        key = f"watch:{pid}:{queue}"
        if not self.busy(key):
            with self._lock:
                self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}
            self.ex.submit(self._watch, key, pid, queue, prof, matches, jobs)
        return key

    def _watch(self, key: str, pid: int, queue: str, prof: dict, matches: list[dict], jobs: list[dict]) -> None:
        from ..coach.ollama import Ollama
        from ..stats.tips import write_watch_guide
        from ..stats.youtube import search
        p = self.store.profile(pid)
        if p is None:
            self._set(key, status="error", error="Player was deleted")
            return
        self._set(key, status="running")
        yt_key = self.store.get("youtube_api_key")
        llm, llm_error = None, None
        try:
            cfg = self.store.build_config(p)
            llm = Ollama(cfg.ollama.url, cfg.ollama.model, cfg.ollama.temperature, cfg.ollama.num_ctx,
                         cfg.ollama.timeout_s, cfg.ollama.think)
            llm.check()
        except Exception as e:
            llm, llm_error = None, f"Coach: {e}"
        produced = False
        all_errors = []
        for n, job in enumerate(jobs, 1):
            pro, queries = job["pro"], job["queries"]
            out = {"pro": pro, "queries": queries, "guide": None, "errors": [], "_created": time.time()}
            if yt_key:
                self._log(key, f"· {pro}: searching YouTube ...")
                for q in queries:
                    try:
                        q["videos"] = search(yt_key, q["query"], self.store.data_dir / "cache")
                    except Exception as e:
                        out["errors"].append(f"YouTube: {e}")
                        break                       # same error for every query (bad key, quota)
            if llm:
                self._log(key, f"· {pro} ({n}/{len(jobs)}): writing what to watch for with {cfg.ollama.model} ...")
                try:
                    out["guide"] = write_watch_guide(llm, prof, matches, queries, p.language, pro=pro)
                except Exception as e:
                    out["errors"].append(f"Coach: {e}")
            elif llm_error:
                out["errors"].append(llm_error)
            produced = produced or out["guide"] is not None or any(q.get("videos") for q in queries)
            all_errors += out["errors"]
            saved = self.read_watch(pid, queue)              # merge: other pros' guides stay
            saved["by_pro"][pro] = out
            path = self.watch_path(pid, queue)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(saved, ensure_ascii=False))
        if not produced:
            self._set(key, status="error", error="; ".join(dict.fromkeys(all_errors)) or "nothing produced")
        else:
            self._set(key, status="done")

    # ---- Premier team setup --------------------------------------------------
    def submit_premier(self, tid: int, owner_id: int, name: str, tag: str, region: str) -> str:
        key = f"premier:{tid}"
        if not self.busy(key):
            with self._lock:
                self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}
            self.ex.submit(self._premier, key, tid, owner_id, name, tag, region)
        return key

    def _client(self):
        from .store import Profile
        dummy = Profile(id=0, owner_id=None, name="", tag="", region="eu", platform="pc", mode="both",
                        language="English", playbook="", created_at="")
        cfg = self.store.build_config(dummy)
        return pipeline.get_client(cfg)

    def _premier(self, key: str, tid: int, owner_id: int, name: str, tag: str, region: str) -> None:
        from ..henrik import account_by_puuid, premier_history, premier_team
        self._set(key, status="running")
        try:
            team = self.store.team(tid)
            if team is None:
                raise RuntimeError("Team was deleted")
            client = self._client()
            self._log(key, f"· Looking up Premier team {name}#{tag} ({region.upper()}) ...")
            data = premier_team(client, name, tag, region)
            members = [m for m in data.get("member") or [] if m.get("puuid")]
            named = sum(1 for m in members if m.get("name") and m.get("tag"))
            self._log(key, f"· HenrikDev returned {len(members)} members ({named} with names)"
                           f"{' · team id ' + str(data.get('id'))[:8] if data.get('id') else ''}")

            # the team's latest Premier matches: who plays, and everyone's name#tag
            appearances: dict[str, int] = {}
            names: dict[str, tuple[str, str]] = {}
            roster_ids: list[str] = []        # from the match data's Premier roster of this team
            side_ids: list[str] = []          # players on the side where one of your players was
            mine = {(p.name.lower(), p.tag.lower()) for p in self.store.profiles(owner_id)}
            try:
                hist = premier_history(client, name, tag, region)[:10]
                self._log(key, f"· Reading the last {len(hist)} Premier match{'es' if len(hist) != 1 else ''} ...")
                for h in hist:
                    try:
                        d = client.match(region, h["id"]).get("data") or {}
                    except Exception as e:
                        self._log(key, f"  ! match {h['id'][:8]}: {e}")
                        continue
                    players = d.get("players", []) or []
                    for pl in players:
                        pu = pl.get("puuid")
                        if not pu:
                            continue
                        appearances[pu] = appearances.get(pu, 0) + 1
                        if pl.get("name") and pl.get("tag"):
                            names[pu] = (pl["name"], pl["tag"])
                    our_side = None
                    for t in d.get("teams", []) or []:
                        pr = t.get("premier_roster") or {}
                        if pr and ((pr.get("tag") or "").lower() == tag.lower()
                                   or (pr.get("name") or "").lower() == name.lower()
                                   or (data.get("id") and pr.get("id") == data.get("id"))):
                            our_side = t.get("team_id")
                            for mm in pr.get("members") or []:
                                pu = mm if isinstance(mm, str) else (mm or {}).get("puuid")
                                if pu and pu not in roster_ids:
                                    roster_ids.append(pu)
                    if our_side is None:
                        me = next((pl for pl in players if (str(pl.get("name", "")).lower(), str(pl.get("tag", "")).lower()) in mine), None)
                        our_side = me.get("team_id") if me else None
                    for pl in players:
                        if our_side and pl.get("team_id") == our_side and pl.get("puuid") not in side_ids:
                            side_ids.append(pl["puuid"])
            except Exception as e:
                self._log(key, f"  ! no match history: {e}")

            if not members and roster_ids:
                members = [{"puuid": pu} for pu in roster_ids]
                self._log(key, f"· No member list from the team lookup; using the Premier roster in the match data ({len(members)} players)")
            if not members and side_ids:
                members = [{"puuid": pu} for pu in side_ids]
                self._log(key, f"· No member list; using the {len(members)} players who played on your side")
            if not members:
                regulars = [pu for pu, n in appearances.items() if n >= 2]
                members = [{"puuid": pu} for pu in regulars]
                if members:
                    self._log(key, f"· No member list; using the {len(members)} players who appear in 2+ of the team's matches")
            if not members:
                raise RuntimeError("HenrikDev returned no members for this team, and its Premier matches don't show who's on it. "
                                   "Add yourself as a player first (then your side of the match is used), or create the team "
                                   "by hand and pick the players under Members & maps.")

            roster = []
            for m in members:
                pu = m["puuid"]
                n, t = m.get("name"), m.get("tag")
                if not (n and t) and pu in names:
                    n, t = names[pu]
                if not (n and t):
                    try:
                        acc = account_by_puuid(client, pu)
                        n, t = acc.get("name"), acc.get("tag")
                    except Exception as e:
                        self._log(key, f"  ! name lookup for a member failed: {e}")
                if n and t:
                    roster.append({"puuid": pu, "name": n, "tag": t})
                else:
                    self._log(key, f"  ! skipped one member: name not available ({pu[:8]}…)")
            if not roster:
                raise RuntimeError("Could not find the members' names (HenrikDev returned only player ids)")
            self._log(key, f"· Roster: {', '.join(m['name'] + '#' + m['tag'] for m in roster)}")

            # players in your workspace (existing ones are reused, roles you set are kept)
            old = {m["pid"]: m for m in team.member_list}
            new_members, pids = [], []
            ranked = sorted(roster, key=lambda m: -appearances.get(m["puuid"], 0))
            for i, m in enumerate(ranked):
                prof = self.store.find_profile(owner_id, m["name"], m["tag"])
                if prof is None:
                    pid = self.store.create_profile(owner_id, m["name"], m["tag"], region)
                    self._log(key, f"  + added player {m['name']}#{m['tag']}")
                else:
                    pid = prof.id
                prev = old.get(pid, {})
                kind = prev.get("kind") or ("starter" if i < 5 else "sub")
                new_members.append({**prev, "pid": pid, "kind": kind, "roles": prev.get("roles", []), "puuid": m["puuid"],
                                    "premier_games": appearances.get(m["puuid"], 0)})
                pids.append(pid)
            for pid, m in old.items():                     # keep manually added members
                if pid not in pids:
                    new_members.append(m)
            info = {"name": data.get("name", name), "tag": data.get("tag", tag), "region": region,
                    "id": data.get("id", ""), "placement": data.get("placement") or {}, "stats": data.get("stats") or {},
                    "synced_at": time.time()}
            self.store.update_team(tid, members=new_members, premier=info,
                                   name=team.name if team.name and team.name != "…" else info["name"])
            self._log(key, f"✓ {len(roster)} players · starters by Premier appearances (change them under Members & maps); "
                           "importing their stats now")
            self._set(key, status="done")
            for pid in pids:
                self.submit_import(pid)
        except Exception as e:
            self._log(key, "✗ " + str(e))
            self._set(key, status="error", error=str(e) or e.__class__.__name__)

    # ---- team files --------------------------------------------------------------
    def team_dir(self, tid: int) -> Path:
        return self.store.data_dir / "teams" / str(tid)

    def read_plans(self, tid: int, map_name: str) -> dict | None:
        p = self.team_dir(tid) / "plans" / f"{slug(map_name)}.json"
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except ValueError:
            return None

    def read_focus(self, tid: int, week: str | None = None) -> dict | None:
        d = self.team_dir(tid) / "focus"
        if week is None:
            files = sorted(d.glob("*.json")) if d.exists() else []
            if not files:
                return None
            p = files[-1]
        else:
            p = d / f"{week}.json"
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except ValueError:
            return None

    def my_focus(self, team, uid: int) -> dict | None:
        """This week's focus for the player you're linked to in this team (dashboard)."""
        mine = next((m for m in team.member_list if m.get("user_id") == uid), None)
        if mine is None:
            return None
        f = self.read_focus(team.id)
        p = (f or {}).get("players", {}).get(str(mine["pid"]))
        return {"week": f["week"], **p} if p and p.get("focus") else None

    def _llm(self, profile):
        from ..coach.ollama import Ollama
        cfg = self.store.build_config(profile)
        llm = Ollama(cfg.ollama.url, cfg.ollama.model, cfg.ollama.temperature, cfg.ollama.num_ctx,
                     cfg.ollama.timeout_s, cfg.ollama.think)
        llm.check()
        return llm, cfg

    # ---- game plans -----------------------------------------------------------------
    def submit_plans(self, tid: int, items: list[dict], language: str, post: dict | None = None) -> str:
        """items: [{map, facts, lineup, callouts, notes, tips}]"""
        key = f"plans:{tid}"
        if not self.busy(key):
            with self._lock:
                self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}
            self.ex.submit(self._plans, key, tid, items, language, post)
        return key

    def _plans(self, key, tid, items, language, post) -> None:
        from ..stats.gameplans import write_plans
        self._set(key, status="running")
        try:
            team = self.store.team(tid)
            prof = self.store.profile(team.member_list[0]["pid"]) if team and team.member_list else None
            if prof is None:
                raise RuntimeError("Team has no players")
            llm, cfg = self._llm(prof)
            d = self.team_dir(tid) / "plans"
            d.mkdir(parents=True, exist_ok=True)
            for i, it in enumerate(items, 1):
                self._log(key, f"· {it['map']} ({i}/{len(items)}) with {cfg.ollama.model} ...")
                try:
                    out = write_plans(llm, it["map"], it["facts"], it["lineup"], it["callouts"], it["notes"], it["tips"], language)
                    out["_created"] = time.time()
                    (d / f"{slug(it['map'])}.json").write_text(json.dumps(out, ensure_ascii=False))
                except Exception as e:
                    self._log(key, f"  ! {it['map']}: {e}")
            self._set(key, status="done")
            if post:
                self._post_prep(key, tid, post)
        except Exception as e:
            self._log(key, "✗ " + str(e))
            self._set(key, status="error", error=str(e) or e.__class__.__name__)

    def _post_prep(self, key, tid, post) -> None:
        from ..discord import post as dpost, prep_embeds
        team = self.store.team(tid)
        url = (team.discord_info or {}).get("prep_url") or (team.discord_info or {}).get("focus_url")
        if not url:
            return
        plans = {m["map"]: self.read_plans(tid, m["map"]) for m in post["maps"]}
        try:
            dpost(url, f"**{team.name}**: comps and game plans for {', '.join(m['map'] for m in post['maps'])}",
                  prep_embeds(team.name, post["maps"], plans))
            self._log(key, "✓ posted to Discord")
        except Exception as e:
            self._log(key, f"! Discord: {e}")

    def submit_post_prep(self, tid: int, post: dict) -> str:
        key = f"post:{tid}"
        with self._lock:
            self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}

        def run():
            self._set(key, status="running")
            self._post_prep(key, tid, post)
            st = self.status(key) or {}
            bad = next((l for l in st.get("log", []) if l.startswith("! Discord")), None)
            self._set(key, status="error" if bad else "done", error=bad or "")
        self.ex.submit(run)
        return key

    # ---- weekly focus -----------------------------------------------------------------
    def submit_focus(self, tid: int, week: str, items: list[dict], language: str, post: bool = False) -> str:
        """items: [{pid, name, roles, facts}]"""
        key = f"focus:{tid}"
        if not self.busy(key):
            with self._lock:
                self._state[key] = {"status": "queued", "log": [], "error": "", "t": time.time()}
            self.ex.submit(self._focus, key, tid, week, items, language, post)
        return key

    def _focus(self, key, tid, week, items, language, post) -> None:
        from ..stats.weekly import write_focus
        self._set(key, status="running")
        try:
            team = self.store.team(tid)
            prof = self.store.profile(items[0]["pid"]) if items else None
            if team is None or prof is None:
                raise RuntimeError("Team has no players")
            llm, cfg = self._llm(prof)
            out = {"week": week, "created": time.time(), "model": cfg.ollama.model, "players": {}}
            for i, it in enumerate(items, 1):
                self._log(key, f"· {it['name']} ({i}/{len(items)}) ...")
                try:
                    f = write_focus(llm, it["facts"], language)
                except Exception as e:
                    self._log(key, f"  ! {it['name']}: {e}")
                    f = {"error": str(e)}
                out["players"][str(it["pid"])] = {"name": it["name"], "roles": it["roles"], **f}
            d = self.team_dir(tid) / "focus"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{week}.json").write_text(json.dumps(out, ensure_ascii=False))
            self._set(key, status="done")
            if post:
                self.post_focus(tid, key)
        except Exception as e:
            self._log(key, "✗ " + str(e))
            self._set(key, status="error", error=str(e) or e.__class__.__name__)

    def post_focus(self, tid: int, key: str | None = None) -> None:
        from ..discord import focus_embeds, post as dpost
        team = self.store.team(tid)
        info = team.discord_info or {}
        url = info.get("focus_url") or info.get("prep_url")
        f = self.read_focus(tid)
        if not url or not f:
            return
        players = [{"name": p["name"], "roles": p.get("roles", []), "focus": p} for p in f["players"].values()]
        try:
            dpost(url, f"**{team.name}**: focus for week {f['week']}", focus_embeds(team.name, f["week"], players))
            info["last_focus_week"] = f["week"]
            self.store.update_team(tid, discord=info)
            if key:
                self._log(key, "✓ posted to Discord")
        except Exception as e:
            if key:
                self._log(key, f"! Discord: {e}")
            else:
                raise

    # ---- schedule ------------------------------------------------------------------------
    def start_scheduler(self, weekly_job, nightly_job=None, every_s: int = 300, extra=None) -> None:
        """weekly_job(team) is called once a week per team at its Discord day/hour (server time);
        nightly_job(team) once a night at the team's sync hour (default 02:00)."""
        def loop():
            while not self._stop.wait(every_s):
                try:
                    self.tick(weekly_job)
                except Exception:
                    traceback.print_exc()
                if nightly_job:
                    try:
                        self.tick_nightly(nightly_job)
                    except Exception:
                        traceback.print_exc()
                for fn in extra or []:          # e.g. the Premier brief
                    try:
                        fn()
                    except Exception:
                        traceback.print_exc()
        self._stop = threading.Event()
        threading.Thread(target=loop, name="valcoach-schedule", daemon=True).start()

    def tick(self, weekly_job, now=None) -> list[int]:
        from datetime import datetime
        from ..stats.weekly import week_id
        now = now or datetime.now()
        started = []
        for t in self.store.all_teams():
            info = t.discord_info or {}
            if not info.get("weekly") or not (info.get("focus_url") or info.get("prep_url")):
                continue
            day, hour = int(info.get("weekly_day", 0)), int(info.get("weekly_hour", 18))
            if now.weekday() == day and now.hour >= hour and info.get("last_focus_week") != week_id(now) \
                    and not self.busy(f"focus:{t.id}") and time.time() - float(info.get("last_try", 0)) > 3600:
                info["last_try"] = time.time()          # don't retry every few minutes if the model is down
                self.store.update_team(t.id, discord=info)
                weekly_job(t)
                started.append(t.id)
        return started

    NIGHTLY_WINDOW_H = 3      # if the server was off at the sync hour, catch up within 3 hours, not at noon

    def tick_nightly(self, nightly_job, now=None) -> list[int]:
        from datetime import datetime
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        started = []
        for t in self.store.all_teams():
            info = t.sync_info
            hour = int(info.get("hour", 2))
            if not info.get("nightly") or info.get("last_day") == today:
                continue
            if not (hour <= now.hour < hour + self.NIGHTLY_WINDOW_H):
                continue
            if time.time() - float(info.get("last_try", 0)) < 3600 or self.busy(f"premier:{t.id}"):
                continue
            info.update(last_try=time.time(), last_day=today, last_at=time.time())
            self.store.update_team(t.id, sync=info)
            nightly_job(t)
            started.append(t.id)
        return started

    def shutdown(self) -> None:
        if getattr(self, "_stop", None):
            self._stop.set()
        self.ex.shutdown(wait=False, cancel_futures=True)
