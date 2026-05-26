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
class AttachmentOut:
    """Binary file the plugin should save into the vault.

    Mirrors pitch_shared.Attachment but lives worker-side so test fakes
    don't have to import pydantic.
    """
    filename: str
    base64: str


@dataclass
class PipelineResult:
    markdown: str
    title: str
    slug: str
    attachments: list[AttachmentOut] = field(default_factory=list)


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
    ) -> "PipelineResult":
        """Returns a PipelineResult: markdown, title, slug, plus optional attachments."""
        import time

        start = time.monotonic()

        progress_cb(JobStatus.fetching, "downloading media")
        bundle = self.fetcher.fetch(url, work_dir)

        # ---- Branch 1: image-only carousel — fast path, no LLM ----
        if bundle.image_paths and bundle.video_path is None:
            return self._run_image_carousel(url, bundle, start, progress_cb)

        # ---- Branch 2: video (or video + images) — full LLM path ----
        return self._run_video(
            url, bundle, work_dir, frame_every_seconds, start, progress_cb
        )

    def _run_image_carousel(
        self,
        url: str,
        bundle: "MediaBundle",
        start: float,
        progress_cb: ProgressCallback,
    ) -> "PipelineResult":
        """Image carousel = post text + embedded images. No vision, no OCR, no LLM.

        Reasoning: the user can read the slides themselves. Pitch's job is to
        capture the post into the vault with the original visuals intact.
        """
        import time

        progress_cb(JobStatus.rendering, f"saving {len(bundle.image_paths)} image(s)")

        slug = slugify(bundle.title)
        attachments = self._build_attachments(bundle.image_paths, slug)
        # Markdown references attachments by relative path under the vault.
        image_paths_rel = [
            f"attachments/pitch/{slug}/{a.filename}" for a in attachments
        ]

        elapsed = time.monotonic() - start
        inputs = LessonInputs(
            source_url=url,
            title=bundle.title,
            duration_seconds=0.0,
            processed_at=datetime.now(timezone.utc),
            processing_seconds=elapsed,
            post_text=bundle.post_text,
            author=bundle.author,
            music_title=bundle.music_title,
            transcript=[],
            frame_visuals=[],
            image_visuals=[],
            has_video=False,
            embedded_image_paths=image_paths_rel,
        )
        markdown = render_lesson(inputs)
        return PipelineResult(
            markdown=markdown, title=bundle.title, slug=slug, attachments=attachments
        )

    def _run_video(
        self,
        url: str,
        bundle: "MediaBundle",
        work_dir: Path,
        frame_every_seconds: int,
        start: float,
        progress_cb: ProgressCallback,
    ) -> "PipelineResult":
        import time

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
            coverage=understanding.get("coverage"),
            summary=understanding.get("summary"),
            key_points=understanding.get("key_points") or [],
            tools_mentioned=understanding.get("tools_mentioned") or [],
            code_snippets=understanding.get("code_snippets") or [],
        )
        markdown = render_lesson(inputs)
        return PipelineResult(
            markdown=markdown,
            title=bundle.title,
            slug=slugify(bundle.title),
            attachments=[],
        )

    def _build_attachments(
        self, image_paths: list[Path], slug: str
    ) -> list["AttachmentOut"]:
        """Resize images to 1280px long-edge, JPEG-encode, base64-wrap."""
        import base64
        from io import BytesIO

        try:
            from PIL import Image
        except ImportError:
            Image = None

        out: list[AttachmentOut] = []
        for i, p in enumerate(image_paths):
            try:
                if Image is not None:
                    img = Image.open(p)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    long_edge = max(img.size)
                    if long_edge > 1280:
                        scale = 1280 / long_edge
                        new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
                        img = img.resize(new_size, Image.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    raw = buf.getvalue()
                else:
                    raw = p.read_bytes()
            except Exception:
                log.exception("attachment encode failed for %s", p)
                continue
            out.append(
                AttachmentOut(
                    filename=f"{i + 1:02d}.jpg",
                    base64=base64.b64encode(raw).decode("ascii"),
                )
            )
        return out

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
