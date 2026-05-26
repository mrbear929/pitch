"""SQLite-backed job store. Tiny, durable, no external dependency."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from pitch_shared import Job, JobStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, submitted_at);
"""


class JobStore:
    """Thread-safe job store. SQLite gives us durability across restarts."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def create(self, *, url: Optional[str], topic_hint: Optional[str]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], url=url, topic_hint=topic_hint)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO jobs(id, payload, status, submitted_at) VALUES (?, ?, ?, ?)",
                (
                    job.id,
                    job.model_dump_json(),
                    job.status.value,
                    job.submitted_at.isoformat(),
                ),
            )
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not row:
            return None
        return Job.model_validate_json(row[0])

    def claim_next_pending(self) -> Optional[Job]:
        """Atomically claim the oldest pending job. Returns None if none."""
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id, payload FROM jobs WHERE status = ? "
                "ORDER BY submitted_at ASC LIMIT 1",
                (JobStatus.pending.value,),
            ).fetchone()
            if not row:
                return None
            job = Job.model_validate_json(row[1])
            job.status = JobStatus.claimed
            job.claimed_at = datetime.now(timezone.utc)
            c.execute(
                "UPDATE jobs SET payload = ?, status = ? WHERE id = ? AND status = ?",
                (
                    job.model_dump_json(),
                    job.status.value,
                    job.id,
                    JobStatus.pending.value,
                ),
            )
            if c.total_changes == 0:
                # someone else claimed in the race
                return None
            return job

    def update_progress(
        self, job_id: str, *, status: JobStatus, message: Optional[str]
    ) -> Optional[Job]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT payload FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return None
            job = Job.model_validate_json(row[0])
            job.status = status
            job.progress_message = message
            c.execute(
                "UPDATE jobs SET payload = ?, status = ? WHERE id = ?",
                (job.model_dump_json(), status.value, job_id),
            )
            return job

    def complete(
        self,
        job_id: str,
        *,
        status: JobStatus,
        markdown: Optional[str],
        title: Optional[str],
        slug: Optional[str],
        error: Optional[str],
        user_guidance: Optional[str],
        attachments: Optional[list] = None,
    ) -> Optional[Job]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT payload FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return None
            job = Job.model_validate_json(row[0])
            job.status = status
            job.result_markdown = markdown
            job.result_title = title
            job.result_slug = slug
            job.error = error
            job.user_guidance = user_guidance
            job.completed_at = datetime.now(timezone.utc)
            if attachments is not None:
                job.result_attachments = attachments
            c.execute(
                "UPDATE jobs SET payload = ?, status = ? WHERE id = ?",
                (job.model_dump_json(), status.value, job_id),
            )
            return job

    def stats(self) -> dict:
        """Counts by status. Useful for /healthz."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            ).fetchall()
        return {status: count for status, count in rows}

    def _debug_dump(self) -> str:  # pragma: no cover
        with self._conn() as c:
            rows = c.execute("SELECT id, status, payload FROM jobs").fetchall()
        return json.dumps(rows, indent=2)
