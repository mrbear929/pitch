"""Pipeline interfaces. Real implementations in tools.py; tests substitute fakes."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from .render import FrameVisual, ImageVisual, LessonInputs, TranscriptSegment, render_lesson
from .text import slugify

log = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when media can't be downloaded. The user_guidance is surfaced verbatim."""

    def __init__(self, message: str, user_guidance: str) -> None:
        super().__init__(message)
        self.user_guidance = user_guidance


@dataclass
class MediaBundle:
    """The output of fetching a URL.

    A single post may contain a video, a set of images (carousel post), or both
    (e.g., a video with cover thumbnails). The pipeline branches on what's present.
    """

    title: str
    # Set when a video file was downloaded. None for image-only posts.
    video_path: Optional[Path] = None
    duration_seconds: float = 0.0
    # Carousel images, ordered. Empty for video-only posts.
    image_paths: list[Path] = field(default_factory=list)


class Fetcher(Protocol):
    def fetch(self, url: str, work_dir: Path) -> MediaBundle: ...


class AudioExtractor(Protocol):
    def extract(self, video_path: Path, work_dir: Path) -> Path: ...


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]: ...


class FrameSampler(Protocol):
    def sample(
        self, video_path: Path, work_dir: Path, every_seconds: int
    ) -> list[tuple[float, Path]]: ...


class OcrRunner(Protocol):
    def run(self, image_path: Path) -> str: ...


class VisionAnalyzer(Protocol):
    """Describe an image's visual content (diagrams, code, scenes) in natural language.

    Optional. If the implementation is None or fails, frames/images still get OCR'd
    and the lesson still renders, just without per-image visual descriptions.
    """

    def describe(self, image_path: Path) -> str: ...


class Understander(Protocol):
    """Produce summary/key_points/tools/code from transcript + visual content.

    Implementations may return all-empty fields if the local LLM is unavailable;
    the lesson still renders without a summary section.
    """

    def understand(
        self,
        transcript: list[TranscriptSegment],
        frame_visuals: list[FrameVisual],
        image_visuals: list[ImageVisual],
    ) -> dict: ...


@dataclass
class Pipeline:
    fetcher: Fetcher
    audio: AudioExtractor
    transcriber: Transcriber
    frames: FrameSampler
    ocr: OcrRunner
    vision: Optional[VisionAnalyzer]
    understander: Optional[Understander]

    def run(self, *, url: str, work_dir: Path, frame_every_seconds: int) -> tuple[str, str, str]:
        """Returns (markdown, title, slug)."""
        bundle = self.fetcher.fetch(url, work_dir)

        transcript: list[TranscriptSegment] = []
        frame_visuals: list[FrameVisual] = []
        image_visuals: list[ImageVisual] = []

        if bundle.video_path is not None:
            audio_path = self.audio.extract(bundle.video_path, work_dir)
            transcript = self.transcriber.transcribe(audio_path)
            frame_pairs = self.frames.sample(bundle.video_path, work_dir, frame_every_seconds)
            for ts, p in frame_pairs:
                frame_visuals.append(
                    FrameVisual(
                        timestamp=ts,
                        ocr_text=self._safe_ocr(p),
                        vision_description=self._safe_vision(p),
                    )
                )

        if bundle.image_paths:
            for i, p in enumerate(bundle.image_paths):
                image_visuals.append(
                    ImageVisual(
                        index=i,
                        ocr_text=self._safe_ocr(p),
                        vision_description=self._safe_vision(p),
                    )
                )

        understanding: dict = {}
        if self.understander is not None:
            try:
                understanding = (
                    self.understander.understand(transcript, frame_visuals, image_visuals) or {}
                )
            except Exception:
                log.exception("understander failed; rendering without it")
                understanding = {}

        inputs = LessonInputs(
            source_url=url,
            title=bundle.title,
            duration_seconds=bundle.duration_seconds,
            processed_at=datetime.now(timezone.utc),
            transcript=transcript,
            frame_visuals=frame_visuals,
            image_visuals=image_visuals,
            has_video=bundle.video_path is not None,
            summary=understanding.get("summary"),
            key_points=understanding.get("key_points") or [],
            tools_mentioned=understanding.get("tools_mentioned") or [],
            code_snippets=understanding.get("code_snippets") or [],
        )
        markdown = render_lesson(inputs)
        return markdown, bundle.title, slugify(bundle.title)

    def _safe_ocr(self, image_path: Path) -> str:
        try:
            return self.ocr.run(image_path)
        except Exception:
            log.exception("ocr failed on %s", image_path)
            return ""

    def _safe_vision(self, image_path: Path) -> str:
        if self.vision is None:
            return ""
        try:
            return self.vision.describe(image_path)
        except Exception:
            log.exception("vision failed on %s", image_path)
            return ""
