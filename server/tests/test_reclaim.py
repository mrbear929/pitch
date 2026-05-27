"""Stale-claim reclaim: stuck in-flight rows go back to pending."""
from __future__ import annotations

import sqlite3
import time

from dispatcher import store as store_mod
from pitch_shared import JobStatus


def _backdate_progress(db_path: str, job_id: str, seconds_ago: int) -> None:
    """Make a row look like its last progress ping was N seconds ago."""
    iso = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - seconds_ago),
    )
    with sqlite3.connect(db_path) as c:
        c.execute(
            "UPDATE jobs SET last_progress_at = ? WHERE id = ?",
            (iso, job_id),
        )


def test_stuck_claimed_job_returns_to_pending(store, monkeypatch):
    """A claimed job that hasn't progressed in TTL+ flips back to pending."""
    monkeypatch.setattr(store_mod, "STUCK_TTL_SECONDS", 30)

    j = store.create(url="https://x", topic_hint=None)
    claimed = store.claim_next_pending()
    assert claimed.id == j.id

    # Backdate to look stuck.
    _backdate_progress(store.path, j.id, seconds_ago=120)

    # Next claim_next_pending should reclaim and immediately re-pick it.
    reclaimed = store.claim_next_pending()
    assert reclaimed is not None
    assert reclaimed.id == j.id
    assert reclaimed.status == JobStatus.claimed  # picked up again


def test_recent_progress_does_not_reclaim(store, monkeypatch):
    """A claimed job with a recent ping stays claimed."""
    monkeypatch.setattr(store_mod, "STUCK_TTL_SECONDS", 30)

    j = store.create(url="https://x", topic_hint=None)
    store.claim_next_pending()
    # Worker sends a fresh progress ping right after.
    store.update_progress(j.id, status=JobStatus.transcribing, message="halfway")

    # Within TTL, should NOT be reclaimed.
    none = store.claim_next_pending()
    assert none is None


def test_completed_job_not_touched(store, monkeypatch):
    """done/failed rows are immune to TTL sweep regardless of timestamp."""
    monkeypatch.setattr(store_mod, "STUCK_TTL_SECONDS", 30)

    j = store.create(url="https://x", topic_hint=None)
    store.claim_next_pending()
    store.complete(
        j.id,
        status=JobStatus.done,
        markdown="# hi",
        title="Hi",
        slug="hi",
        error=None,
        user_guidance=None,
    )
    _backdate_progress(store.path, j.id, seconds_ago=9999)

    # Submit a new job; the done one must NOT show up.
    j2 = store.create(url="https://y", topic_hint=None)
    picked = store.claim_next_pending()
    assert picked.id == j2.id  # the new pending one, not the old done one
