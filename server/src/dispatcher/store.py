"""SQLite-backed job store. Tiny, durable, no external dependency."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from pitch_shared import Job, JobStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    last_progress_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, submitted_at);
"""


# Statuses that mean a worker holds the job. If we haven't heard a progress
# ping for STUCK_TTL_SECONDS, assume the worker died and put the job back.
# Workers ping every 15s, so 5 min is generous.
_IN_FLIGHT_STATES = (
    JobStatus.claimed,
    JobStatus.fetching,
    JobStatus.transcribing,
    JobStatus.extracting,
    JobStatus.understanding,
    JobStatus.rendering,
)
STUCK_TTL_SECONDS = 5 * 60


class JobStore:
    """Thread-safe job store. SQLite gives us durability across restarts."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            # Backfill column on existing DBs that pre-date last_progress_at.
            cols = {row[1] for row in c.execute("PRAGMA table_info(jobs)").fetchall()}
            if "last_progress_at" not in cols:
                c.execute("ALTER TABLE jobs ADD COLUMN last_progress_at TEXT")

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
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO jobs(id, payload, status, submitted_at, last_progress_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.model_dump_json(),
                    job.status.value,
                    job.submitted_at.isoformat(),
                    now,
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
        """Atomically claim the oldest pending job. Returns None if none.

        Before picking, sweep any in-flight rows whose worker hasn't pinged
        in STUCK_TTL_SECONDS — flip them back to pending so a fresh worker
        can pick them up. Without this, a worker that dies mid-job leaves
        the row stuck forever.
        """
        with self._lock, self._conn() as c:
            self._reclaim_stuck(c)

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
            now_iso = job.claimed_at.isoformat()
            c.execute(
                "UPDATE jobs SET payload = ?, status = ?, last_progress_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    job.model_dump_json(),
                    job.status.value,
                    now_iso,
                    job.id,
                    JobStatus.pending.value,
                ),
            )
            if c.total_changes == 0:
                # someone else claimed in the race
                return None
            return job

    def _reclaim_stuck(self, c: sqlite3.Connection) -> int:
        """Flip rows that have been in-flight too long back to pending.

        Returns count of rows reclaimed. Caller holds self._lock + a connection.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=STUCK_TTL_SECONDS)
        ).isoformat()
        in_flight = [s.value for s in _IN_FLIGHT_STATES]
        rows = c.execute(
            "SELECT id, payload FROM jobs "
            "WHERE status IN (" + ",".join("?" * len(in_flight)) + ") "
            "AND (last_progress_at IS NULL OR last_progress_at < ?)",
            (*in_flight, cutoff),
        ).fetchall()
        reclaimed = 0
        for job_id, payload in rows:
            job = Job.model_validate_json(payload)
            job.status = JobStatus.pending
            job.claimed_at = None
            job.progress_message = (
                "reclaimed from stuck worker; will be retried"
            )
            c.execute(
                "UPDATE jobs SET payload = ?, status = ? WHERE id = ?",
                (job.model_dump_json(), JobStatus.pending.value, job_id),
            )
            reclaimed += 1
        return reclaimed

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
            now_iso = datetime.now(timezone.utc).isoformat()
            c.execute(
                "UPDATE jobs SET payload = ?, status = ?, last_progress_at = ? "
                "WHERE id = ?",
                (job.model_dump_json(), status.value, now_iso, job_id),
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
            now_iso = job.completed_at.isoformat()
            c.execute(
                "UPDATE jobs SET payload = ?, status = ?, last_progress_at = ? "
                "WHERE id = ?",
                (job.model_dump_json(), status.value, now_iso, job_id),
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
