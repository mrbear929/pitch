"""Pipeline interfaces. Real implementations in tools.py; tests substitute fakes."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol

from pitch_shared import JobStatus

from .render import FrameVisual, ImageVisual, LessonInputs, TranscriptSegment, render_lesson
from .text import slugify

log = logging.getLogger(__name__)

ProgressCallback = Callable[[JobStatus, Optional[str]], None]


def _noop_progress(_status: JobStatus, _message: Optional[str]) -> None:
    pass


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

    title: str                   # The actual post title (the user's words, not the BGM track)
    # Set when a video file was downloaded. None for image-only posts.
    video_path: Optional[Path] = None
    duration_seconds: float = 0.0
    # Carousel images, ordered. Empty for video-only posts.
    image_paths: list[Path] = field(default_factory=list)
    # The full post description; may be longer/multiline. Used as primary
    # signal for the LLM summary. May equal title.
    post_text: str = ""
    # The post author's display name (e.g., "AI大刘"). Empty if not available.
    author: str = ""
    # The BGM/music track name when one is attached. Useful supplemental
    # metadata for image carousels but should not be the title.
    music_title: str = ""


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


class OcrCleaner(Protocol):
    """Clean garbled OCR (spurious spaces, bad chars) into legible text.

    Optional. If None or fails, the raw OCR is shown unchanged. Cleaner runs
    after raw OCR, before the understander gets the data.
    """

    def clean(self, raw_ocr: str, vision_hint: str = "") -> str: ...


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
        post_text: str = "",
        author: str = "",
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
    ocr_cleaner: Optional[OcrCleaner] = None

    def run(
        self,
        *,
        url: str,
        work_dir: Path,
        frame_every_seconds: int,
        progress_cb: ProgressCallback = _noop_progress,
    ) -> tuple[str, str, str]:
        """Returns (markdown, title, slug)."""
        import time

        start = time.monotonic()

        progress_cb(JobStatus.fetching, "downloading media")
        bundle = self.fetcher.fetch(url, work_dir)

        transcript: list[TranscriptSegment] = []
        frame_visuals: list[FrameVisual] = []
        image_visuals: list[ImageVisual] = []

        if bundle.video_path is not None:
            progress_cb(JobStatus.transcribing, "extracting audio")
            audio_path = self.audio.extract(bundle.video_path, work_dir)
            progress_cb(JobStatus.transcribing, "running whisper")
            transcript = self.transcriber.transcribe(audio_path)
            progress_cb(JobStatus.extracting, "sampling frames")
            frame_pairs = self.frames.sample(bundle.video_path, work_dir, frame_every_seconds)
            total = len(frame_pairs)
            for i, (ts, p) in enumerate(frame_pairs, 1):
                progress_cb(JobStatus.extracting, f"frame {i}/{total}")
                vision = self._safe_vision(p)
                raw_ocr = self._safe_ocr(p)
                frame_visuals.append(
                    FrameVisual(
                        timestamp=ts,
                        ocr_text_raw=raw_ocr,
                        ocr_text=self._safe_clean(raw_ocr, vision),
                        vision_description=vision,
                    )
                )

        if bundle.image_paths:
            total = len(bundle.image_paths)
            for i, p in enumerate(bundle.image_paths):
                progress_cb(JobStatus.extracting, f"image {i + 1}/{total}")
                vision = self._safe_vision(p)
                raw_ocr = self._safe_ocr(p)
                image_visuals.append(
                    ImageVisual(
                        index=i,
                        ocr_text_raw=raw_ocr,
                        ocr_text=self._safe_clean(raw_ocr, vision),
                        vision_description=vision,
                    )
                )

        understanding: dict = {}
        if self.understander is not None:
            progress_cb(JobStatus.understanding, "summarizing")
            try:
                understanding = (
                    self.understander.understand(
                        transcript,
                        frame_visuals,
                        image_visuals,
                        post_text=bundle.post_text,
                        author=bundle.author,
                    )
                    or {}
                )
            except Exception:
                log.exception("understander failed; rendering without it")
                understanding = {}

        progress_cb(JobStatus.rendering, "writing markdown")

        elapsed = time.monotonic() - start
        inputs = LessonInputs(
            source_url=url,
            title=bundle.title,
            duration_seconds=bundle.duration_seconds,
            processed_at=datetime.now(timezone.utc),
            processing_seconds=elapsed,
            post_text=bundle.post_text,
            author=bundle.author,
            music_title=bundle.music_title,
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

    def _safe_clean(self, raw_ocr: str, vision_hint: str) -> str:
        if self.ocr_cleaner is None or not raw_ocr.strip():
            return raw_ocr
        try:
            cleaned = self.ocr_cleaner.clean(raw_ocr, vision_hint=vision_hint)
            return cleaned or raw_ocr
        except Exception:
            log.exception("ocr cleaner failed; using raw")
            return raw_ocr
