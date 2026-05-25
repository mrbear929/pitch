"""Pipeline interfaces. Real implementations in tools.py; tests substitute fakes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from .render import FrameOcr, LessonInputs, TranscriptSegment, render_lesson
from .text import slugify


class FetchError(Exception):
    """Raised when a video can't be downloaded. The user_guidance is surfaced verbatim."""

    def __init__(self, message: str, user_guidance: str) -> None:
        super().__init__(message)
        self.user_guidance = user_guidance


@dataclass
class VideoMeta:
    title: str
    duration_seconds: float
    media_path: Path  # the downloaded video file


class Fetcher(Protocol):
    def fetch(self, url: str, work_dir: Path) -> VideoMeta: ...


class AudioExtractor(Protocol):
    def extract(self, video_path: Path, work_dir: Path) -> Path: ...


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]: ...


class FrameSampler(Protocol):
    def sample(self, video_path: Path, work_dir: Path, every_seconds: int) -> list[tuple[float, Path]]: ...


class OcrRunner(Protocol):
    def run(self, image_path: Path) -> str: ...


class Understander(Protocol):
    """Optional: produce summary/key_points/tools/code from transcript+ocr.

    Implementations may return all-empty fields if the local LLM is unavailable;
    the lesson still renders without a summary section.
    """

    def understand(
        self, transcript: list[TranscriptSegment], frames: list[FrameOcr]
    ) -> dict: ...


@dataclass
class Pipeline:
    fetcher: Fetcher
    audio: AudioExtractor
    transcriber: Transcriber
    frames: FrameSampler
    ocr: OcrRunner
    understander: Optional[Understander]

    def run(self, *, url: str, work_dir: Path, frame_every_seconds: int) -> tuple[str, str, str]:
        """Returns (markdown, title, slug)."""
        meta = self.fetcher.fetch(url, work_dir)
        audio_path = self.audio.extract(meta.media_path, work_dir)
        transcript = self.transcriber.transcribe(audio_path)
        frame_pairs = self.frames.sample(meta.media_path, work_dir, frame_every_seconds)
        frame_ocrs = [
            FrameOcr(timestamp=ts, text=self.ocr.run(p)) for ts, p in frame_pairs
        ]

        understanding: dict = {}
        if self.understander is not None:
            try:
                understanding = self.understander.understand(transcript, frame_ocrs) or {}
            except Exception:
                understanding = {}

        inputs = LessonInputs(
            source_url=url,
            title=meta.title,
            duration_seconds=meta.duration_seconds,
            processed_at=datetime.now(timezone.utc),
            transcript=transcript,
            frames=frame_ocrs,
            summary=understanding.get("summary"),
            key_points=understanding.get("key_points") or [],
            tools_mentioned=understanding.get("tools_mentioned") or [],
            code_snippets=understanding.get("code_snippets") or [],
        )
        markdown = render_lesson(inputs)
        return markdown, meta.title, slugify(meta.title)
