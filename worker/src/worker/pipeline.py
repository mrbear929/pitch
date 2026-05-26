"""Pipeline interfaces. Real implementations in tools.py; tests substitute fakes."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol

from pitch_shared import JobStatus

from .render import LessonInputs, TranscriptSegment, render_lesson
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
    """Binary file the plugin saves into the vault."""
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
    """The output of fetching a URL."""

    title: str
    video_path: Optional[Path] = None
    duration_seconds: float = 0.0
    image_paths: list[Path] = field(default_factory=list)
    post_text: str = ""
    author: str = ""
    music_title: str = ""


class Fetcher(Protocol):
    def fetch(self, url: str, work_dir: Path) -> MediaBundle: ...


class AudioExtractor(Protocol):
    def extract(self, video_path: Path, work_dir: Path) -> Path: ...


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]: ...


class VideoUnderstander(Protocol):
    """Produce coverage + extracted info from a video file directly.

    Modern hosted models (Gemini, GPT-4o) ingest the video natively — no need
    to extract frames + OCR + describe each in separate calls. We pass the
    video file plus the post text and let the model do everything.
    """

    def understand(
        self,
        video_path: Path,
        transcript: list[TranscriptSegment],
        post_text: str = "",
        author: str = "",
    ) -> dict: ...


@dataclass
class Pipeline:
    fetcher: Fetcher
    audio: AudioExtractor
    transcriber: Transcriber
    understander: Optional[VideoUnderstander]

    def run(
        self,
        *,
        url: str,
        work_dir: Path,
        progress_cb: ProgressCallback = _noop_progress,
    ) -> PipelineResult:
        """Returns a PipelineResult: markdown, title, slug, plus optional attachments."""
        import time

        start = time.monotonic()

        progress_cb(JobStatus.fetching, "downloading media")
        bundle = self.fetcher.fetch(url, work_dir)

        if bundle.image_paths and bundle.video_path is None:
            return self._run_image_carousel(url, bundle, start, progress_cb)
        return self._run_video(url, bundle, work_dir, start, progress_cb)

    def _run_image_carousel(
        self,
        url: str,
        bundle: MediaBundle,
        start: float,
        progress_cb: ProgressCallback,
    ) -> PipelineResult:
        """Image carousel = post text + embedded images. No LLM."""
        import time

        progress_cb(JobStatus.rendering, f"saving {len(bundle.image_paths)} image(s)")

        slug = slugify(bundle.title)
        attachments = self._build_attachments(bundle.image_paths, slug)
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
            transcript=[],
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
        bundle: MediaBundle,
        work_dir: Path,
        start: float,
        progress_cb: ProgressCallback,
    ) -> PipelineResult:
        import time

        transcript: list[TranscriptSegment] = []
        understanding: dict = {}

        if bundle.video_path is not None:
            progress_cb(JobStatus.transcribing, "extracting audio")
            audio_path = self.audio.extract(bundle.video_path, work_dir)

            progress_cb(JobStatus.transcribing, "uploading audio for transcription")
            try:
                transcript = self.transcriber.transcribe(audio_path)
            except Exception:
                log.exception("transcription failed; continuing without")

            if self.understander is not None:
                progress_cb(JobStatus.understanding, "analyzing video")
                try:
                    understanding = (
                        self.understander.understand(
                            bundle.video_path,
                            transcript,
                            post_text=bundle.post_text,
                            author=bundle.author,
                        )
                        or {}
                    )
                except Exception:
                    log.exception("video understander failed; rendering without")

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
            transcript=transcript,
            has_video=bundle.video_path is not None,
            coverage=understanding.get("coverage"),
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
    ) -> list[AttachmentOut]:
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
