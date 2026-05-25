"""Job schema shared between dispatcher and worker.

Single source of truth for the JSON exchanged across the wire.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"        # in queue
    claimed = "claimed"        # worker has picked it up
    fetching = "fetching"      # downloading the video
    transcribing = "transcribing"
    extracting = "extracting"  # frames + ocr
    understanding = "understanding"  # local LLM pass
    rendering = "rendering"
    done = "done"
    failed = "failed"


class JobSubmit(BaseModel):
    """Client → dispatcher."""
    url: Optional[str] = None
    topic_hint: Optional[str] = None
    # If url is None the worker expects a local file path the client uploaded
    # via /jobs/{id}/upload (future).


class JobProgress(BaseModel):
    """Worker → dispatcher progress ping."""
    status: JobStatus
    message: Optional[str] = None


class JobResult(BaseModel):
    """Worker → dispatcher final result."""
    status: JobStatus            # done or failed
    markdown: Optional[str] = None
    title: Optional[str] = None
    slug: Optional[str] = None
    error: Optional[str] = None
    user_guidance: Optional[str] = None  # surfaced verbatim in plugin notice on failure


class Job(BaseModel):
    """Server-side job state."""
    id: str
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    url: Optional[str] = None
    topic_hint: Optional[str] = None
    status: JobStatus = JobStatus.pending
    progress_message: Optional[str] = None
    result_markdown: Optional[str] = None
    result_title: Optional[str] = None
    result_slug: Optional[str] = None
    error: Optional[str] = None
    user_guidance: Optional[str] = None
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
