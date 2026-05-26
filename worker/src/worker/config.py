"""Worker runtime configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    dispatcher_url: str
    worker_token: str
    work_dir: Path
    groq_api_key: str
    gemini_api_key: str
    poll_idle_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        url = os.environ.get("PITCH_DISPATCHER_URL", "").rstrip("/")
        token = os.environ.get("PITCH_WORKER_TOKEN", "")
        if not url or not token:
            raise RuntimeError("PITCH_DISPATCHER_URL and PITCH_WORKER_TOKEN required")

        groq = os.environ.get("PITCH_GROQ_API_KEY", "")
        gemini = os.environ.get("PITCH_GEMINI_API_KEY", "")
        if not groq:
            raise RuntimeError(
                "PITCH_GROQ_API_KEY required (https://console.groq.com/keys)"
            )
        if not gemini:
            raise RuntimeError(
                "PITCH_GEMINI_API_KEY required (https://aistudio.google.com/apikey)"
            )

        work_dir = Path(
            os.environ.get(
                "PITCH_WORK_DIR",
                str(Path.home() / "Library/Application Support/Pitch/work"),
            )
        )
        work_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            dispatcher_url=url,
            worker_token=token,
            work_dir=work_dir,
            groq_api_key=groq,
            gemini_api_key=gemini,
            poll_idle_seconds=float(os.environ.get("PITCH_POLL_IDLE_SECONDS", "5")),
        )
