"""Bearer-token auth. Two roles: client (plugin/curl) and worker (Mac daemon)."""
from __future__ import annotations

import secrets
from enum import Enum
from typing import Annotated

from fastapi import Header, HTTPException, status

from .config import Config


class Role(str, Enum):
    client = "client"
    worker = "worker"


def _extract(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer"
        )
    return authorization[len("Bearer ") :]


def require_client(config: Config):
    async def dep(authorization: Annotated[str | None, Header()] = None) -> Role:
        token = _extract(authorization)
        if not secrets.compare_digest(token, config.client_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
            )
        return Role.client

    return dep


def require_worker(config: Config):
    async def dep(authorization: Annotated[str | None, Header()] = None) -> Role:
        token = _extract(authorization)
        if not secrets.compare_digest(token, config.worker_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
            )
        return Role.worker

    return dep
