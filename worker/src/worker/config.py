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
    whisper_bin: str
    whisper_model: str
    ollama_url: str
    ollama_model: str
    vision_model: str  # "" disables vision analysis
    frame_every_seconds: int
    poll_idle_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        url = os.environ.get("PITCH_DISPATCHER_URL", "").rstrip("/")
        token = os.environ.get("PITCH_WORKER_TOKEN", "")
        if not url or not token:
            raise RuntimeError("PITCH_DISPATCHER_URL and PITCH_WORKER_TOKEN required")

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
            whisper_bin=os.environ.get("PITCH_WHISPER_BIN", "whisper-cli"),
            whisper_model=os.environ.get(
                "PITCH_WHISPER_MODEL",
                str(Path.home() / "Library/Application Support/Pitch/models/ggml-medium.bin"),
            ),
            ollama_url=os.environ.get("PITCH_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("PITCH_OLLAMA_MODEL", "qwen2.5:7b"),
            vision_model=os.environ.get("PITCH_VISION_MODEL", "qwen2.5vl:7b"),
            frame_every_seconds=int(os.environ.get("PITCH_FRAME_EVERY_SECONDS", "30")),
            poll_idle_seconds=float(os.environ.get("PITCH_POLL_IDLE_SECONDS", "5")),
        )
