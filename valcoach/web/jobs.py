"""Background job queue: coaching runs from all users go through here.

`workers` runs execute at the same time (default 1: Ollama and video decoding
are the bottleneck, so running more at once rarely finishes sooner). Everyone
else waits in the queue and sees their position on the job page.
"""
from __future__ import annotations

import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import pipeline
from .store import Store, now


class JobRunner:
    def __init__(self, store: Store, workers: int = 1):
        self.store = store
        self.workers = max(1, workers)
        self.ex = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="coach")

    def recover(self) -> None:
        """After a restart: running jobs were interrupted, queued ones start again."""
        for j in self.store.jobs_with_status("running"):
            self.store.update_job(j.id, status="error", error="Interrupted by a server restart",
                                  finished_at=now())
        for j in self.store.jobs_with_status("queued"):
            self.submit(j.id)

    def submit(self, job_id: str) -> None:
        self.ex.submit(self._run, job_id)

    def report_dir(self, job_id: str) -> Path:
        return self.store.data_dir / "reports" / job_id

    def _run(self, job_id: str) -> None:
        st = self.store
        # atomic queued -> running: a job submitted twice (double "Run again") runs only once
        if not st.claim_job(job_id):
            return
        job = st.job(job_id)
        profile = st.profile(job.profile_id) if job else None
        if profile is None:
            st.update_job(job_id, status="error", error="Profile was deleted", finished_at=now())
            return

        def log(msg: str) -> None:
            st.append_log(job_id, msg)

        try:
            cfg = st.build_config(profile)
            o = job.opts
            anchor = None
            if o.get("anchor_time"):
                anchor = pipeline.Anchor(int(o.get("anchor_round") or 1), int(o.get("anchor_kill") or 1),
                                         o["anchor_time"])
            req = pipeline.CoachRequest(
                match=job.match_id,
                vod=str(st.resolve(job.vod_path) or job.vod_path) if job.vod_path else None,
                mode=job.mode,
                no_llm=bool(o.get("no_llm")),
                no_minimap=bool(o.get("no_minimap")),
                recalibrate=bool(o.get("recalibrate")),
                anchor=anchor,
                out_dir=self.report_dir(job_id),
                vod_url=f"/jobs/{job_id}/vod" if job.vod_path else None,
                team_review=bool(o.get("team_review")),
                team_roles=self.team_roles(profile.owner_id),
            )
            res = pipeline.run(cfg, req, log)
            st.update_job(job_id, status="done", html_path=str(res.html), json_path=str(res.json),
                          map=res.map_name, score=res.score, started_at_match=res.started_at,
                          finished_at=now())
        except Exception as e:  # report every failure on the job page
            tb = traceback.format_exc(limit=4)
            log("✗ " + str(e))
            log(tb)
            st.update_job(job_id, status="error", error=str(e) or e.__class__.__name__, finished_at=now())

    def team_roles(self, owner_id: int | None) -> dict[str, list[str]]:
        """'name#tag' (lower case) -> roles assigned on this user's team pages."""
        out: dict[str, list[str]] = {}
        if owner_id is None:
            return out
        for t in self.store.teams(owner_id):
            for m in t.member_list:
                p = self.store.profile(m["pid"])
                if p is not None and m.get("roles"):
                    out.setdefault(f"{p.name}#{p.tag}".lower(), [])
                    out[f"{p.name}#{p.tag}".lower()] += [r for r in m["roles"] if r not in out[f"{p.name}#{p.tag}".lower()]]
        return out

    def delete(self, job_id: str) -> None:
        job = self.store.job(job_id)
        if job is None or job.status == "running":
            return
        shutil.rmtree(self.report_dir(job_id), ignore_errors=True)
        if job.opts.get("uploaded") and job.vod_path:
            # only delete the upload if no other job uses the same file
            others = [j for j in self.store.jobs_using_vod(job.vod_path) if j.id != job_id]
            if not others:
                found = self.store.resolve(job.vod_path)
                if found:
                    found.unlink(missing_ok=True)
        self.store.delete_job(job_id)

    def shutdown(self) -> None:
        self.ex.shutdown(wait=False, cancel_futures=True)
