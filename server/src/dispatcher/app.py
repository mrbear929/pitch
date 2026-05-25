"""FastAPI dispatcher. Queue + auth, no media processing."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pitch_shared import JobProgress, JobResult, JobStatus, JobSubmit

from .auth import require_client, require_worker
from .config import Config
from .store import JobStore


def create_app(config: Optional[Config] = None, store: Optional[JobStore] = None) -> FastAPI:
    config = config or Config.from_env()
    store = store or JobStore(config.db_path)
    app = FastAPI(title="Pitch Dispatcher", version="0.1.0")

    client_dep = require_client(config)
    worker_dep = require_worker(config)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "stats": store.stats()}

    # ---- client endpoints ----

    @app.post("/jobs", dependencies=[Depends(client_dep)])
    async def submit_job(payload: JobSubmit) -> dict:
        if not payload.url:
            raise HTTPException(status_code=400, detail="url required (file upload not yet supported)")
        job = store.create(url=payload.url, topic_hint=payload.topic_hint)
        return {"id": job.id, "status": job.status.value}

    # ---- worker endpoints (registered before /jobs/{job_id} so /jobs/next matches first) ----

    @app.get("/jobs/next", dependencies=[Depends(worker_dep)])
    async def next_job() -> dict:
        """Long-poll: claim the oldest pending job, or wait briefly if none."""
        deadline = asyncio.get_event_loop().time() + config.long_poll_seconds
        while True:
            job = store.claim_next_pending()
            if job:
                return job.model_dump(mode="json")
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return {"job": None}
            await asyncio.sleep(min(1.0, remaining))

    @app.get("/jobs/{job_id}", dependencies=[Depends(client_dep)])
    async def get_job(job_id: str) -> dict:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="not found")
        return job.model_dump(mode="json")

    @app.post("/jobs/{job_id}/progress", dependencies=[Depends(worker_dep)])
    async def post_progress(job_id: str, payload: JobProgress) -> dict:
        job = store.update_progress(
            job_id, status=payload.status, message=payload.message
        )
        if not job:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @app.post("/jobs/{job_id}/result", dependencies=[Depends(worker_dep)])
    async def post_result(job_id: str, payload: JobResult) -> dict:
        if payload.status not in (JobStatus.done, JobStatus.failed):
            raise HTTPException(status_code=400, detail="status must be done or failed")
        job = store.complete(
            job_id,
            status=payload.status,
            markdown=payload.markdown,
            title=payload.title,
            slug=payload.slug,
            error=payload.error,
            user_guidance=payload.user_guidance,
        )
        if not job:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    return app


# Run with: uvicorn dispatcher.app:create_app --factory

