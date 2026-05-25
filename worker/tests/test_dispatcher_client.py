"""Worker's HTTP client tested against a real in-process dispatcher."""
from __future__ import annotations

import threading

import pytest
import uvicorn
from dispatcher.app import create_app
from dispatcher.config import Config as ServerConfig
from dispatcher.store import JobStore
from pitch_shared import JobResult, JobStatus
from worker.dispatcher_client import DispatcherClient


@pytest.fixture
def live_server(tmp_path):
    """Boot the real dispatcher on a random port, in a thread."""
    config = ServerConfig(
        client_token="client-secret",
        worker_token="worker-secret",
        db_path=str(tmp_path / "jobs.db"),
        long_poll_seconds=1.0,
    )
    store = JobStore(config.db_path)
    app = create_app(config=config, store=store)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until uvicorn picks a port and starts serving.
    import time

    deadline = time.time() + 5
    while time.time() < deadline:
        if server.started and server.servers:
            break
        time.sleep(0.05)
    assert server.servers, "dispatcher failed to start"
    sock = list(server.servers[0].sockets)[0]
    port = sock.getsockname()[1]

    yield {
        "url": f"http://127.0.0.1:{port}",
        "client_token": config.client_token,
        "worker_token": config.worker_token,
        "store": store,
    }
    server.should_exit = True
    thread.join(timeout=5)


async def test_claim_next_returns_none_when_empty(live_server):
    client = DispatcherClient(live_server["url"], live_server["worker_token"])
    job = await client.claim_next()
    assert job is None


async def test_full_cycle(live_server):
    store: JobStore = live_server["store"]
    j = store.create(url="https://example.com", topic_hint=None)

    client = DispatcherClient(live_server["url"], live_server["worker_token"])
    job = await client.claim_next()
    assert job is not None
    assert job.id == j.id

    await client.post_progress(j.id, JobStatus.transcribing, "halfway")
    refreshed = store.get(j.id)
    assert refreshed.status == JobStatus.transcribing
    assert refreshed.progress_message == "halfway"

    await client.post_result(
        j.id,
        JobResult(status=JobStatus.done, markdown="# hi", title="Hi", slug="hi"),
    )
    final = store.get(j.id)
    assert final.status == JobStatus.done
    assert final.result_markdown == "# hi"
