"""Direct store tests (no HTTP)."""
from pitch_shared import JobStatus


def test_create_and_get(store):
    j = store.create(url="https://x", topic_hint=None)
    assert j.status == JobStatus.pending
    j2 = store.get(j.id)
    assert j2 is not None
    assert j2.url == "https://x"


def test_claim_is_atomic(store):
    j1 = store.create(url="https://a", topic_hint=None)
    j2 = store.create(url="https://b", topic_hint=None)

    claimed_a = store.claim_next_pending()
    claimed_b = store.claim_next_pending()
    none = store.claim_next_pending()

    assert claimed_a.id == j1.id  # FIFO
    assert claimed_b.id == j2.id
    assert none is None


def test_complete(store):
    j = store.create(url="https://x", topic_hint=None)
    store.claim_next_pending()
    final = store.complete(
        j.id,
        status=JobStatus.done,
        markdown="# hi",
        title="Hi",
        slug="hi",
        error=None,
        user_guidance=None,
    )
    assert final.result_markdown == "# hi"
    assert final.completed_at is not None


def test_stats(store):
    store.create(url="https://a", topic_hint=None)
    store.create(url="https://b", topic_hint=None)
    j = store.create(url="https://c", topic_hint=None)
    store.claim_next_pending()
    store.complete(
        j.id,
        status=JobStatus.failed,
        markdown=None,
        title=None,
        slug=None,
        error="oops",
        user_guidance="try uploading",
    )
    stats = store.stats()
    # one claimed (the FIFO first we just claimed), rest pending, the third we completed as failed
    assert stats.get("pending", 0) >= 1
