from __future__ import annotations

import pytest
from dispatcher.app import create_app
from dispatcher.config import Config
from dispatcher.store import JobStore
from fastapi.testclient import TestClient


@pytest.fixture
def config(tmp_path):
    return Config(
        client_token="client-secret",
        worker_token="worker-secret",
        db_path=str(tmp_path / "jobs.db"),
        long_poll_seconds=0.5,
    )


@pytest.fixture
def store(config):
    return JobStore(config.db_path)


@pytest.fixture
def app(config, store):
    return create_app(config=config, store=store)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def client_headers():
    return {"Authorization": "Bearer client-secret"}


@pytest.fixture
def worker_headers():
    return {"Authorization": "Bearer worker-secret"}
