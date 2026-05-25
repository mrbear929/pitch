"""Thin HTTP client for the dispatcher."""
from __future__ import annotations

from typing import Optional

import httpx
from pitch_shared import Job, JobProgress, JobResult, JobStatus


class DispatcherClient:
    def __init__(self, base_url: str, token: str, timeout: float = 35.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = timeout

    async def claim_next(self) -> Optional[Job]:
        """Long-poll the dispatcher. Returns None if no job within poll window."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(f"{self._base}/jobs/next", headers=self._headers)
        r.raise_for_status()
        body = r.json()
        if not body or body.get("job") is None and "id" not in body:
            return None
        return Job.model_validate(body)

    async def post_progress(
        self, job_id: str, status: JobStatus, message: Optional[str] = None
    ) -> None:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                f"{self._base}/jobs/{job_id}/progress",
                headers=self._headers,
                json=JobProgress(status=status, message=message).model_dump(),
            )
        r.raise_for_status()

    async def post_result(self, job_id: str, result: JobResult) -> None:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{self._base}/jobs/{job_id}/result",
                headers=self._headers,
                json=result.model_dump(),
            )
        r.raise_for_status()
