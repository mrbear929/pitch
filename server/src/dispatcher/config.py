"""Runtime configuration. All from env so we never commit secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    client_token: str
    worker_token: str
    db_path: str
    long_poll_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        client = os.environ.get("PITCH_CLIENT_TOKEN", "")
        worker = os.environ.get("PITCH_WORKER_TOKEN", "")
        if not client or not worker:
            raise RuntimeError(
                "PITCH_CLIENT_TOKEN and PITCH_WORKER_TOKEN must both be set"
            )
        if client == worker:
            raise RuntimeError("client and worker tokens must differ")
        return cls(
            client_token=client,
            worker_token=worker,
            db_path=os.environ.get("PITCH_DB_PATH", "jobs.db"),
            long_poll_seconds=float(os.environ.get("PITCH_LONG_POLL_SECONDS", "25")),
        )
